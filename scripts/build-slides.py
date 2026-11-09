#!/usr/bin/env python3
"""Build six editable RV32-first slides from a complete acceptance matrix.

The default backend uses stdlib ZIP/XML and the existing PPTX as a package
template, plus installed Matplotlib/Pillow for PDF. No downloads are needed.
All slide bodies are rebuilt as editable shapes; historical content is removed.
The optional --backend uno needs the Python UNO bridge and LibreOffice Impress.
The input layout is RESULTS/rv{32,64}/{hardware,strict}/{O2,O3,Os}/result.json.

  /usr/bin/python3 scripts/build-slides.py --results /tmp/matrix --check-only
  /usr/bin/python3 scripts/build-slides.py --results /tmp/matrix \
      --output-dir /tmp/rvp-slides

The slide deck, PDF, standalone SVG chart and source-data JSON are staged
together before publication. Existing output files require --overwrite.
LibreOffice uses a private /tmp profile and pipe; only its own process is
terminated. This script never builds kernels or updates the notebook.
"""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
import posixpath
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "docs/images/image-block-matching.png"
TEMPLATE = ROOT / "docs/RVP-Image-SAD.pptx"
OUTPUTS = ("RVP-Image-SAD-RV32.pptx", "RVP-Image-SAD-RV32.pdf",
           "rv32-instruction-counts.svg", "slides-data.json")
NAVY = 0x142B49
ORANGE = 0xEF6438
GRAY = 0x718092
PALE = 0xF3F6FA
LINE = 0xDAE1EA
WHITE = 0xFFFFFF
WIDTH, HEIGHT = 960, 540
NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
      "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
      "dc": "http://purl.org/dc/elements/1.1/",
      "dcterms": "http://purl.org/dc/terms/",
      "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
      "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"}
for prefix, namespace in NS.items():
    ET.register_namespace(prefix, namespace)


def qualified(name):
    prefix, local = name.split(":")
    return "{" + NS[prefix] + "}" + local


def child(parent, tag, **attributes):
    return ET.SubElement(parent, qualified(tag), {key: str(value) for key, value in attributes.items()})


def xml_bytes(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, description, minimum=0):
    require(type(value) is int and value >= minimum,
            f"{description} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class Measurement:
    source: str
    xlen: int
    alignment: str
    optimization: str
    cases: int
    candidates: int
    checksum: int
    counts: dict
    text: dict
    frames: dict
    versions: dict

    def count(self, kernel, layout="aligned"):
        return self.counts[(kernel, layout)]


def read_measurement(path, xlen, alignment, optimization):
    """Reject failed, inconsistent, or differently configured result files."""
    data = json.loads(path.read_text())
    config = data["build_configuration"]
    expected = {"xlen": xlen, "alignment": alignment,
                "optimization": "-" + optimization, "tune": "size"}
    for name, value in expected.items():
        require(config[name] == value, f"configuration {name}: expected {value!r}")
    require(data["spec_state"] == "P v0.6 draft, not ratified", "expected P draft 0.6")
    require(data["qemu_timings_are_hardware_performance"] is False
            and data["hardware_speedup"] is None, "unexpected hardware-performance claim")
    if xlen == 32:
        for name, value in {"abi": "ilp32", "runtime_abi": "ilp32",
                            "kernel_arch": "rv32imcp0p6_zba_zbb",
                            "baseline_arch": "rv32imc_zba_zbb",
                            "runtime_arch": "rv32imac"}.items():
            require(config[name] == value, f"RV32 target assumption changed: {name}")
        for disabled in ("f=false", "d=false", "v=false", "zfa=false"):
            require(disabled in config["qemu_cpu"].split(","),
                    f"RV32 QEMU must explicitly disable {disabled.split('=')[0]}")
        regression = data["compiler_regression"]
        require(regression["rv32_uint64_add"] == "pass", "RV32 carry regression failed")
        integer(regression["cases"], "RV32 carry regression cases", 1)

    tests, demo, oracle = data["tests"], data["demo"], data["independent_image_check"]
    require(integer(tests["failures"], "test failures") == 0, "C checks failed")
    cases = integer(tests["cases"], "C test cases", 1)
    candidates = integer(demo["candidates"], "image candidates", 1)
    require(demo["all_costs_match"] is True and demo["sad"] == 0,
            "image search did not match")
    require(oracle["python_oracle_candidates"] == candidates,
            "independent oracle candidate count differs")
    require(oracle["displacement"] == [demo["dx"], demo["dy"]],
            "independent oracle displacement differs")
    # The reused image contains these labels. Never pair it with different data.
    require((candidates, demo["dx"], demo["dy"]) == (289, 5, -3),
            "result does not match the supplied image illustration")

    code = data["code_generation"]
    for name in ("packed_sad_present", "no_rvv", "no_floating_point"):
        require(code[name] is True, f"code-generation check failed: {name}")
    require(code["native_load"] == ("lw" if xlen == 32 else "ld"),
            "unexpected native load width")
    text, frames = {}, {}
    for kernel in ("scalar", "p"):
        text[kernel] = integer(code["text_bytes"][kernel], f"{kernel} text bytes", 1)
        stack = code["stack_usage"][kernel]
        frames[kernel] = integer(stack["max_static_frame_bytes"], f"{kernel} frame")
        sizes = [integer(item["bytes"], "function frame") for item in stack["functions"]]
        require(sizes and max(sizes) == frames[kernel], "inconsistent static frame summary")
        lines = [line for line in data["build_commands"].splitlines()
                 if f"-c sad-{kernel}.c" in line]
        require(lines, f"missing {kernel} compile command")
        flags = ("-fno-lto", "-fno-tree-vectorize", "-fno-tree-slp-vectorize",
                 "-mtune=size", "-" + optimization)
        require(all(all(flag in line.split() for flag in flags) for line in lines),
                f"{kernel} compiler flags do not match the slide's method")

    trace = data["instruction_counts"]
    require(trace["xlen"] == xlen and trace["alignment_policy"] == alignment,
            "instruction-count configuration differs")
    require(trace["metric"] == "Executed guest instructions inside the SAD kernel, including return",
            "instruction-count scope changed")
    if alignment == "hardware":
        require(trace["hardware_mode_check"]["performed"] is True,
                "hardware-mode load check was not performed")
    counts, checksums = {}, set()
    for row in trace["results"]:
        key = (row["kernel"], row["layout"])
        require(key in {(k, layout) for k in ("scalar", "p")
                        for layout in ("aligned", "unaligned")}, "unknown trace variant")
        require(key not in counts, "duplicate trace variant")
        require((row["xlen"], row["alignment_policy"], row["width"], row["height"])
                == (xlen, alignment, 16, 16), "trace is not the expected 16 x 16 call")
        runs = row["runs"]
        require(len(runs) >= 2, "need at least two repeated instruction traces")
        signatures = []
        for run in runs:
            count = integer(run["guest_instructions"], "guest instruction count", 1)
            checksum = integer(run["checksum"], "trace SAD")
            opcodes = run["opcodes"]
            require(opcodes and sum(integer(n, "opcode count") for n in opcodes.values())
                    == count, "opcode totals differ from guest instruction count")
            packed = sum(opcodes.get(op, 0) for op in ("pabdsumu.b", "pabdsumau.b"))
            require(packed == (256 // (xlen // 8) if key[0] == "p" else 0),
                    "unexpected number of packed SAD operations")
            if alignment == "hardware" and key[0] == "p":
                require(opcodes.get(code["native_load"], 0) > 0
                        and not any(opcodes.get(op, 0) for op in ("lb", "lbu")),
                        "hardware-mode packed trace has no native loads or uses byte loads")
            signatures.append((count, checksum, opcodes))
            checksums.add(checksum)
        require(all(item == signatures[0] for item in signatures[1:]),
                "repeated instruction traces disagree")
        counts[key] = signatures[0][0]
    require(len(counts) == 4 and len(checksums) == 1,
            "need all four trace variants with identical logical-pixel SAD")
    require(counts[("scalar", "aligned")] == counts[("scalar", "unaligned")],
            "the shared scalar bar requires equal counts across layouts")
    if alignment == "hardware":
        require(counts[("p", "aligned")] == counts[("p", "unaligned")],
                "the hardware-mode bar requires equal counts across layouts")
    return Measurement(str(path), xlen, alignment, optimization, cases, candidates,
                       checksums.pop(), counts, text, frames, data["tested_versions"])


def load_matrix(directory):
    matrix = {}
    for xlen in (32, 64):
        for alignment in ("hardware", "strict"):
            for optimization in ("O2", "O3", "Os"):
                path = directory / f"rv{xlen}" / alignment / optimization / "result.json"
                try:
                    item = read_measurement(path, xlen, alignment, optimization)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise ValueError(f"{path}: {error}") from error
                matrix[(xlen, alignment, optimization)] = item
    reference = matrix[(32, "hardware", "O3")]
    for item in matrix.values():
        require((item.cases, item.candidates, item.checksum, item.versions)
                == (reference.cases, reference.candidates, reference.checksum, reference.versions),
                f"matrix checks, inputs or tool versions differ: {item.source}")
        scalar = matrix[(item.xlen, "hardware", item.optimization)].count("scalar")
        require(item.count("scalar") == scalar,
                f"the common scalar baseline differs between alignment policies: {item.source}")
    return matrix


def chart_data(matrix):
    hardware, strict = (matrix[(32, policy, "O3")] for policy in ("hardware", "strict"))
    rows = [("Scalar C · either layout", hardware.count("scalar"), GRAY),
            ("P · hardware / either layout", hardware.count("p"), ORANGE),
            ("P · strict / aligned", strict.count("p"), ORANGE),
            ("P · strict / unaligned", strict.count("p", "unaligned"), ORANGE)]
    # Five equal divisions with a rounded upper bound, always starting at zero.
    maximum = max(row[1] for row in rows)
    magnitude = 10 ** math.floor(math.log10(maximum / 5))
    step = math.ceil(maximum / 5 / magnitude) * magnitude
    ceiling = step * 5
    fewer = 100 * (1 - hardware.count("p") / hardware.count("scalar"))
    title = (f"RV32: {fewer:.0f}% fewer executed instructions" if fewer > 0
             else "RV32: executed instructions per call")
    return rows, ceiling, title


def units(points):
    return round(points * 2540 / 72)


class Deck:
    """Small editable-shape wrapper; coordinates and font sizes are points."""

    def __init__(self, document, uno, context):
        self.doc, self.uno, self.context = document, uno, context
        self.pages = document.getDrawPages()
        self.index = 0

    def enum(self, kind, value):
        return self.uno.Enum("com.sun.star." + kind, value)

    def shape(self, page, kind, x, y, width, height):
        shape = self.doc.createInstance("com.sun.star.drawing." + kind)
        page.add(shape)
        point = self.uno.createUnoStruct("com.sun.star.awt.Point")
        point.X, point.Y = units(x), units(y)
        size = self.uno.createUnoStruct("com.sun.star.awt.Size")
        size.Width, size.Height = units(width), units(height)
        shape.setPosition(point)
        shape.setSize(size)
        return shape

    def rectangle(self, page, x, y, width, height, color):
        shape = self.shape(page, "RectangleShape", x, y, width, height)
        shape.FillStyle = self.enum("drawing.FillStyle", "SOLID")
        shape.FillColor = color
        shape.LineStyle = self.enum("drawing.LineStyle", "NONE")
        return shape

    def text(self, page, x, y, width, height, value, size=16, color=NAVY,
             bold=False, mono=False, align="LEFT"):
        shape = self.shape(page, "TextShape", x, y, width, height)
        shape.FillStyle = self.enum("drawing.FillStyle", "NONE")
        shape.LineStyle = self.enum("drawing.LineStyle", "NONE")
        shape.TextAutoGrowHeight = False
        shape.TextAutoGrowWidth = False
        shape.TextFitToSize = self.enum("drawing.TextFitToSizeType", "NONE")
        shape.TextLeftDistance = shape.TextRightDistance = 0
        shape.TextUpperDistance = shape.TextLowerDistance = 0
        shape.TextVerticalAdjust = self.enum("drawing.TextVerticalAdjust", "TOP")
        text = shape.getText()
        text.setString(value)
        cursor = text.createTextCursor()
        cursor.gotoEnd(True)
        cursor.CharHeight = float(size)
        cursor.CharColor = color
        cursor.CharWeight = 150.0 if bold else 100.0
        cursor.CharFontName = "Liberation Mono" if mono else "Liberation Sans"
        cursor.ParaAdjust = self.enum("style.ParagraphAdjust", align)
        cursor.ParaTopMargin = cursor.ParaBottomMargin = 0
        return shape

    def page(self, title, subtitle):
        page = self.pages.getByIndex(0) if self.index == 0 else self.pages.insertNewByIndex(self.index)
        while page.getCount():
            page.remove(page.getByIndex(0))
        page.Width, page.Height = units(WIDTH), units(HEIGHT)
        self.rectangle(page, 0, 0, WIDTH, HEIGHT, WHITE)
        self.rectangle(page, 42, 32, 48, 5, ORANGE)
        self.text(page, 42, 53, 876, 44, title, 30, bold=True)
        self.text(page, 42, 105, 876, 30, subtitle, 17, GRAY)
        self.rectangle(page, 42, 506, 876, 1, LINE)
        self.text(page, 42, 515, 820, 16,
                  "RVP-Example | P 0.6 draft", 10, GRAY)
        self.text(page, 878, 515, 40, 16, str(self.index + 1), 10, GRAY, align="RIGHT")
        self.index += 1
        return page

    def picture(self, page, path, x, y, width, height):
        # GraphicProvider loads the bitmap into the document, not as an external link.
        context = self.context
        provider = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.graphic.GraphicProvider", context)
        graphic = provider.queryGraphic((property_value(self.uno, "URL", path.as_uri()),))
        require(graphic is not None, "cannot load the image illustration")
        shape = self.shape(page, "GraphicObjectShape", x, y, width, height)
        shape.Graphic = graphic


class NativeDeck:
    """Shared point-based layout for native OOXML shapes and a vector PDF."""

    def __init__(self, title="Image block matching with RV32 P",
                 description="Current validated RV32/RV64 matrix. P 0.6 draft. Guest instructions are not hardware timing."):
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextToPath
        self.font_properties = FontProperties
        self.measure = TextToPath()
        self.pages = []
        self.title, self.description = title, description

    def rectangle(self, page, x, y, width, height, color):
        page.append(dict(kind="rectangle", x=x, y=y, width=width, height=height, color=color))

    def text(self, page, x, y, width, height, value, size=16, color=NAVY,
             bold=False, mono=False, align="LEFT"):
        font = "Liberation Mono" if mono else "Liberation Sans"
        properties = self.font_properties(family=font, size=size, weight="bold" if bold else "normal")

        def measured(line):
            return self.measure.get_text_width_height_descent(line, properties, ismath=False)[0]

        lines = []
        for paragraph in value.split("\n"):
            if mono or measured(paragraph) <= width:
                lines.append(paragraph)
                continue
            line = ""
            for word in paragraph.split():
                candidate = line + " " + word if line else word
                if line and measured(candidate) > width:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
        require(all(measured(line) <= width + 0.1 for line in lines),
                f"text exceeds its slide box width: {value!r}")
        require(size + (len(lines) - 1) * size * 1.15 <= height + 0.1,
                f"text exceeds its slide box height: {value!r}")
        page.append(dict(kind="text", x=x, y=y, width=width, height=height, lines=lines,
                         size=size, color=color, bold=bold, font=font, align=align))

    def picture(self, page, path, x, y, width, height):
        page.append(dict(kind="picture", x=x, y=y, width=width, height=height, path=path))

    def polyline(self, page, points, color, thickness=1):
        require(len(points) >= 2, "A signal line needs at least two points")
        xs, ys = zip(*points)
        page.append(dict(kind="polyline", x=min(xs), y=min(ys),
                         width=max(max(xs) - min(xs), 0.01),
                         height=max(max(ys) - min(ys), 0.01),
                         points=points, color=color, thickness=thickness))

    def page(self, title, subtitle):
        page = []
        self.pages.append(page)
        self.rectangle(page, 0, 0, WIDTH, HEIGHT, WHITE)
        self.rectangle(page, 42, 32, 48, 5, ORANGE)
        self.text(page, 42, 53, 876, 44, title, 30, bold=True)
        self.text(page, 42, 105, 876, 30, subtitle, 17, GRAY)
        self.rectangle(page, 42, 506, 876, 1, LINE)
        self.text(page, 42, 515, 820, 16,
                  "RVP-Example | P 0.6 draft", 10, GRAY)
        self.text(page, 878, 515, 40, 16, str(len(self.pages)), 10, GRAY, align="RIGHT")
        return page

    def slide_xml(self, page):
        slide = ET.Element(qualified("p:sld"), showMasterSp="0")
        tree = child(child(slide, "p:cSld"), "p:spTree")
        group = child(tree, "p:nvGrpSpPr")
        child(group, "p:cNvPr", id=1, name="")
        child(group, "p:cNvGrpSpPr")
        child(group, "p:nvPr")
        transform = child(child(tree, "p:grpSpPr"), "a:xfrm")
        for name, attributes in (("off", {"x": 0, "y": 0}), ("ext", {"cx": 0, "cy": 0}),
                                 ("chOff", {"x": 0, "y": 0}), ("chExt", {"cx": 0, "cy": 0})):
            child(transform, "a:" + name, **attributes)
        for identifier, item in enumerate(page, 2):
            picture = item["kind"] == "picture"
            shape = child(tree, "p:pic" if picture else "p:sp")
            nonvisual = child(shape, "p:nvPicPr" if picture else "p:nvSpPr")
            child(nonvisual, "p:cNvPr", id=identifier, name=f"{item['kind']} {identifier}")
            child(nonvisual, "p:cNvPicPr" if picture else "p:cNvSpPr",
                  **({"txBox": 1} if item["kind"] == "text" else {}))
            child(nonvisual, "p:nvPr")
            if picture:
                fill = child(shape, "p:blipFill")
                blip = child(fill, "a:blip")
                blip.set(qualified("r:embed"), "rvpImage")
                child(child(fill, "a:stretch"), "a:fillRect")
            properties = child(shape, "p:spPr")
            transform = child(properties, "a:xfrm")
            child(transform, "a:off", x=round(item["x"] * 12700), y=round(item["y"] * 12700))
            child(transform, "a:ext", cx=round(item["width"] * 12700), cy=round(item["height"] * 12700))
            if item["kind"] == "polyline":
                geometry = child(properties, "a:custGeom")
                for name in ("avLst", "gdLst", "ahLst", "cxnLst"):
                    child(geometry, "a:" + name)
                child(geometry, "a:rect", l=0, t=0, r="r", b="b")
                path = child(child(geometry, "a:pathLst"), "a:path",
                             w=round(item["width"] * 12700), h=round(item["height"] * 12700),
                             fill="none", stroke=1)
                for index, (x, y) in enumerate(item["points"]):
                    child(child(path, "a:moveTo" if index == 0 else "a:lnTo"), "a:pt",
                          x=round((x - item["x"]) * 12700), y=round((y - item["y"]) * 12700))
            else:
                child(child(properties, "a:prstGeom", prst="rect"), "a:avLst")
            if item["kind"] == "rectangle":
                child(child(properties, "a:solidFill"), "a:srgbClr", val=f"{item['color']:06X}")
            elif not picture:
                child(properties, "a:noFill")
            if item["kind"] == "polyline":
                line = child(properties, "a:ln", w=round(item["thickness"] * 12700), cap="rnd")
                child(child(line, "a:solidFill"), "a:srgbClr", val=f"{item['color']:06X}")
                child(line, "a:prstDash", val="solid")
                child(line, "a:round")
            else:
                child(child(properties, "a:ln"), "a:noFill")
            if item["kind"] == "text":
                body = child(shape, "p:txBody")
                child(child(body, "a:bodyPr", wrap="none", lIns=0, rIns=0, tIns=0, bIns=0, anchor="t"),
                      "a:noAutofit")
                child(body, "a:lstStyle")
                for line in item["lines"]:
                    paragraph = child(body, "a:p")
                    props = child(paragraph, "a:pPr", algn={"LEFT": "l", "RIGHT": "r", "CENTER": "ctr"}[item["align"]])
                    child(child(props, "a:lnSpc"), "a:spcPts", val=round(item["size"] * 115))
                    child(child(props, "a:spcBef"), "a:spcPts", val=0)
                    child(child(props, "a:spcAft"), "a:spcPts", val=0)
                    run = child(paragraph, "a:r")
                    runprops = child(run, "a:rPr", lang="en-US", sz=round(item["size"] * 100),
                                     b=int(item["bold"]))
                    child(child(runprops, "a:solidFill"), "a:srgbClr", val=f"{item['color']:06X}")
                    child(runprops, "a:latin", typeface=item["font"])
                    child(run, "a:t").text = line
                    child(paragraph, "a:endParaRPr", lang="en-US", sz=round(item["size"] * 100))
        child(child(slide, "p:clrMapOvr"), "a:masterClrMapping")
        return xml_bytes(slide)

    def save_pptx(self, path):
        # Reuse only the template's package/master/theme infrastructure, never
        # its slides, notes or measurements. A deck may supply one bitmap or none.
        images = {item["path"] for page in self.pages for item in page if item["kind"] == "picture"}
        require(len(images) <= 1, "This focused slide renderer supports one shared bitmap per deck")
        with ZipFile(TEMPLATE) as source:
            parts = {name: source.read(name) for name in source.namelist()
                     if not name.startswith(("ppt/slides/", "ppt/notesSlides/", "ppt/media/"))}
        content = ET.fromstring(parts["[Content_Types].xml"])
        for item in list(content):
            if item.get("PartName", "").startswith(("/ppt/slides/", "/ppt/notesSlides/", "/ppt/media/")):
                content.remove(item)
        presentation = ET.fromstring(parts["ppt/presentation.xml"])
        identifiers = presentation.find(qualified("p:sldIdLst"))
        require(identifiers is not None, "PPTX template has no slide list")
        identifiers.clear()
        size = presentation.find(qualified("p:sldSz"))
        size.set("cx", str(WIDTH * 12700))
        size.set("cy", str(HEIGHT * 12700))
        relationships = ET.fromstring(parts["ppt/_rels/presentation.xml.rels"])
        for relation in list(relationships):
            if relation.get("Type", "").endswith("/slide"):
                relationships.remove(relation)
        for index, page in enumerate(self.pages, 1):
            identifier = child(identifiers, "p:sldId", id=255 + index)
            identifier.set(qualified("r:id"), f"rvpSlide{index}")
            child(relationships, "rel:Relationship", Id=f"rvpSlide{index}",
                  Type=NS["r"] + "/slide", Target=f"slides/slide{index}.xml")
            child(content, "ct:Override", PartName=f"/ppt/slides/slide{index}.xml",
                  ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml")
            parts[f"ppt/slides/slide{index}.xml"] = self.slide_xml(page)
            rels = ET.Element(qualified("rel:Relationships"))
            child(rels, "rel:Relationship", Id="rvpLayout", Type=NS["r"] + "/slideLayout",
                  Target="../slideLayouts/slideLayout2.xml")
            if any(item["kind"] == "picture" for item in page):
                child(rels, "rel:Relationship", Id="rvpImage", Type=NS["r"] + "/image",
                      Target="../media/image1.png")
            parts[f"ppt/slides/_rels/slide{index}.xml.rels"] = xml_bytes(rels)
        if images:
            parts["ppt/media/image1.png"] = next(iter(images)).read_bytes()
        parts["[Content_Types].xml"] = xml_bytes(content)
        parts["ppt/presentation.xml"] = xml_bytes(presentation)
        parts["ppt/_rels/presentation.xml.rels"] = xml_bytes(relationships)
        core = ET.fromstring(parts["docProps/core.xml"])
        metadata = {"dc:title": self.title,
                    "dc:subject": self.description,
                    "dc:description": self.description,
                    "dcterms:modified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for name, value in metadata.items():
            core.find(qualified(name)).text = value
        parts["docProps/core.xml"] = xml_bytes(core)
        application = ET.fromstring(parts["docProps/app.xml"])
        application.find(qualified("ep:Application")).text = "RVP-Example editable OOXML generator"
        slide_count = application.find(qualified("ep:Slides"))
        if slide_count is None:
            slide_count = child(application, "ep:Slides")
        slide_count.text = str(len(self.pages))
        parts["docProps/app.xml"] = xml_bytes(application)
        with ZipFile(path, "w", ZIP_DEFLATED) as output:
            for name, payload in parts.items():
                output.writestr(name, payload)
        validate_pptx(path, len(self.pages))

    def save_pdf(self, path):
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure
        from matplotlib.lines import Line2D
        from matplotlib.patches import Rectangle
        from PIL import Image
        with PdfPages(path, metadata={"Title": self.title,
                                      "Author": "RVP-Example",
                                      "Subject": self.description}) as output:
            for page in self.pages:
                figure = Figure(figsize=(WIDTH / 72, HEIGHT / 72), dpi=72)
                for layer, item in enumerate(page, 1):
                    x, y, width, height = (item[key] for key in ("x", "y", "width", "height"))
                    if item["kind"] == "rectangle":
                        figure.patches.append(Rectangle((x / WIDTH, 1 - (y + height) / HEIGHT),
                            width / WIDTH, height / HEIGHT, transform=figure.transFigure,
                            facecolor=f"#{item['color']:06x}", edgecolor="none", zorder=layer))
                    elif item["kind"] == "picture":
                        axes = figure.add_axes((x / WIDTH, 1 - (y + height) / HEIGHT,
                                                width / WIDTH, height / HEIGHT), zorder=layer)
                        with Image.open(item["path"]) as bitmap:
                            axes.imshow(bitmap, aspect="auto", interpolation="nearest")
                        axes.set_axis_off()
                    elif item["kind"] == "polyline":
                        xs, ys = zip(*item["points"])
                        figure.lines.append(Line2D([value / WIDTH for value in xs],
                            [1 - value / HEIGHT for value in ys], transform=figure.transFigure,
                            color=f"#{item['color']:06x}", linewidth=item["thickness"], zorder=layer))
                    else:
                        horizontal = {"LEFT": "left", "CENTER": "center", "RIGHT": "right"}[item["align"]]
                        anchor = x + (width if horizontal == "right" else width / 2 if horizontal == "center" else 0)
                        for index, line in enumerate(item["lines"]):
                            figure.text(anchor / WIDTH, 1 - (y + index * item["size"] * 1.15) / HEIGHT, line,
                                        fontsize=item["size"], color=f"#{item['color']:06x}",
                                        fontfamily=item["font"], weight="bold" if item["bold"] else "normal",
                                        ha=horizontal, va="top", parse_math=False, zorder=layer)
                output.savefig(figure)
                figure.clear()


def validate_pptx(path, slides):
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None, "PPTX ZIP integrity failed")
        for name in names:
            if name.endswith((".xml", ".rels")):
                element = ET.fromstring(archive.read(name))
                if name.endswith(".rels"):
                    base = posixpath.dirname(posixpath.dirname(name))
                    for relation in element:
                        if relation.get("TargetMode") != "External":
                            target = posixpath.normpath(posixpath.join(base, relation.attrib["Target"]))
                            require(target in names, f"PPTX relationship target is missing: {target}")
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        require(len(presentation.find(qualified("p:sldIdLst"))) == slides, "PPTX slide count differs")
        require(all(f"ppt/slides/slide{index}.xml" in names for index in range(1, slides + 1)),
                "PPTX slide body is missing")
    print(f"Validated PPTX ZIP, all XML and internal relationships; {slides} editable slides.")


@contextmanager
def native_rendering():
    with tempfile.TemporaryDirectory(prefix="rvp-slides-mpl-", dir="/tmp") as cache:
        previous = os.environ.get("MPLCONFIGDIR")
        os.environ["MPLCONFIGDIR"] = cache
        try:
            import matplotlib
            matplotlib.use("pdf")
            with matplotlib.rc_context({"pdf.fonttype": 42}):
                yield
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = previous


def export_native(matrix, staging):
    with native_rendering():
        deck = NativeDeck()
        build_deck(deck, matrix)
        deck.save_pptx(staging / OUTPUTS[0])
        deck.save_pdf(staging / OUTPUTS[1])


def build_deck(deck, matrix):
    hw, strict, small = (matrix[(32, policy, opt)]
                         for policy, opt in (("hardware", "O3"), ("strict", "O3"),
                                             ("hardware", "Os")))
    page = deck.page("Image block matching, now on RV32 P",
                     "Add absolute pixel differences. The lowest SAD identifies the match.")
    deck.picture(page, IMAGE, 42, 148, 876, 328.5)
    # Reuse the verified illustration, with a shorter presentation caption.
    deck.rectangle(page, 42, 435, 876, 42, WHITE)
    deck.text(page, 62, 449, 836, 24,
              f"{hw.candidates}/{hw.candidates} image costs independently verified · best SAD = 0", 15)

    page = deck.page("Four pixels per packed operation",
                     "The image kernel is C. No inline assembly is required.")
    deck.rectangle(page, 42, 150, 636, 235, PALE)
    code = ("#include <riscv_packed_simd.h>\n\n"
            "uint64_t sum = 0;\n"
            "size_t x = 0;\n"
            "for (; width - x >= 4; x += 4)\n"
            "  {\n"
            "    uint8x4_t av = __riscv_pld_u8x4 ((uint8_t *) (a + x));\n"
            "    uint8x4_t bv = __riscv_pld_u8x4 ((uint8_t *) (b + x));\n"
            "    sum += __riscv_pabdsumu_u8x4_u32 (av, bv);\n"
            "  }")
    deck.text(page, 58, 167, 608, 205, code, 14, mono=True)
    for y, label, detail in ((155, "LOAD", "Four pixels from each image"),
                             (231, "REDUCE", "Four absolute byte differences"),
                             (307, "ACCUMULATE", "Add to a 64-bit total")):
        deck.text(page, 704, y, 210, 25, label, 16, ORANGE, bold=True)
        deck.text(page, 704, y + 28, 210, 43, detail, 16)
    deck.text(page, 42, 410, 876, 28, "Generated packed SAD: pabdsumu.b / pabdsumau.b", 17, bold=True)
    deck.text(page, 42, 450, 876, 38,
              "Full kernel: row strides, alignment handling and scalar tails. RV64 uses eight byte lanes.", 14)

    page = deck.page("DSP support for a compact integer core",
                     "Packed arithmetic in the integer registers, using the same C source structure.")
    deck.rectangle(page, 42, 151, 410, 257, PALE)
    deck.text(page, 62, 169, 370, 25, "RV32 TARGET", 16, ORANGE, bold=True)
    deck.text(page, 62, 214, 370, 39, "RV32IMC + Zba/Zbb + P", 24, bold=True)
    deck.text(page, 62, 267, 370, 38, "P draft 0.6 · ILP32 soft-float ABI", 16)
    deck.text(page, 62, 326, 365, 61,
              "Linux demo runtime: RV32IMAC.\nRV64 counterpart: eight byte lanes.", 16)
    deck.text(page, 485, 166, 430, 27, "HARDWARE LOAD PATH", 17, ORANGE, bold=True)
    deck.text(page, 485, 203, 430, 64,
              "Direct word loads for cores\nwith misaligned-access support.", 17)
    deck.text(page, 485, 291, 430, 27, "CHECKED LOAD PATH", 17, ORANGE, bold=True)
    deck.text(page, 485, 328, 430, 66,
              "Alignment checks select word loads\nor byte loads plus packing.", 17)
    deck.text(page, 42, 440, 876, 45,
              "Choose the packed width and load policy that fit your core.", 19, bold=True)

    rows, ceiling, title = chart_data(matrix)
    page = deck.page(title, "One 16 × 16 kernel call, including return · -O3 · lower is better")
    for tick in range(6):
        x = 320 + tick * 102
        deck.rectangle(page, x, 163, 0.6, 237, LINE)
        deck.text(page, x - 38, 407, 76, 24, f"{ceiling * tick // 5:,}", 14, GRAY, align="CENTER")
    for index, (label, count, color) in enumerate(rows):
        y = 174 + index * 58
        deck.text(page, 42, y, 267, 26, label, 16)
        width = count / ceiling * 510
        deck.rectangle(page, 320, y, width, 30, color)
        deck.text(page, 332 + width, y + 3, 95, 26, f"{count:,}", 17, bold=True)
    deck.text(page, 320, 436, 510, 24, "Executed guest instructions", 14, GRAY, align="CENTER")
    deck.text(page, 42, 476, 876, 23,
              f"Identical 16 × 16 pixels in both layouts; SAD = {hw.checksum:,}.", 14, GRAY)

    page = deck.page("Choose code size or instruction count",
                     "RV32 hardware mode · kernel text and static frame sizes")
    columns = ((42, 209), (251, 167), (418, 167), (585, 167), (752, 166))
    headers = ("Metric", "Scalar · -O3", "P · -O3", "Scalar · -Os", "P · -Os")
    for (x, width), label in zip(columns, headers):
        deck.rectangle(page, x, 151, width, 46, NAVY)
        deck.text(page, x + 13, 166, width - 20, 26, label, 16, WHITE, bold=True)
    items = (("Guest instructions", hw.count("scalar"), hw.count("p"), small.count("scalar"), small.count("p")),
             ("Kernel text, bytes", hw.text["scalar"], hw.text["p"], small.text["scalar"], small.text["p"]),
             ("Static frame, bytes", hw.frames["scalar"], hw.frames["p"], small.frames["scalar"], small.frames["p"]))
    for row, values in enumerate(items):
        y = 197 + row * 52
        for column, ((x, width), value) in enumerate(zip(columns, values)):
            deck.rectangle(page, x, y, width, 52, PALE if row % 2 == 0 else WHITE)
            label = value if isinstance(value, str) else f"{value:,}"
            deck.text(page, x + 13, y + 17, width - 20, 28, label, 16,
                      ORANGE if column in (2, 4) else NAVY, bold=column in (2, 4))
    deck.text(page, 42, 381, 876, 30,
              f"P at -Os: text {hw.text['p']:,} → {small.text['p']:,} bytes; "
              f"instructions {hw.count('p'):,} → {small.count('p'):,}.", 18, bold=True)
    deck.text(page, 42, 428, 876, 30,
              f"Strict P at -O3: {strict.text['p']:,} text bytes; "
              f"{strict.frames['p']:,}-byte static frame.", 16)

    page = deck.page("A demo you can reproduce",
                     "C kernels, included tools, independently checked image-search costs.")
    for x, number, label in ((42, str(len(matrix)), "configurations pass"),
                             (342, f"{hw.cases:,}", "C checks per build"),
                             (642, f"{hw.candidates}/{hw.candidates}", "image costs verified")):
        deck.rectangle(page, x, 157, 276, 127, PALE)
        deck.text(page, x + 15, 174, 246, 53, number, 35, ORANGE, bold=True, align="CENTER")
        deck.text(page, x + 15, 242, 246, 30, label, 16, align="CENTER")
    deck.text(page, 42, 306, 876, 28,
              "RV32 / RV64 × hardware / strict alignment × O2 / O3 / Os", 17, align="CENTER")
    deck.rectangle(page, 42, 351, 876, 54, NAVY)
    deck.text(page, 58, 369, 844, 26,
              "XLEN=32 ALIGNMENT=hardware bash scripts/present.sh", 17, WHITE, mono=True)
    deck.text(page, 42, 426, 876, 48,
              "Try image matching, dot product and FIR with the included tools.", 18, bold=True)
    deck.text(page, 42, 459, 876, 18, "github.com/pz9115/RVP-Example", 12, GRAY)
    deck.text(page, 42, 485, 876, 16,
              "QEMU guest instructions, -O3/-Os, -mtune=size; hardware mode assumes misaligned word loads. Hardware timing not measured.", 10, GRAY)


def property_value(uno, name, value):
    item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    item.Name, item.Value = name, value
    return item


@contextmanager
def office_session(uno, executable, timeout):
    """Use a unique pipe/profile and always reap exactly the process we start."""
    with tempfile.TemporaryDirectory(prefix="rvp-slides-lo-", dir="/tmp") as temporary:
        temporary = Path(temporary)
        pipe = "rvp_slides_" + uuid.uuid4().hex
        command = [executable, "-env:UserInstallation=" + (temporary / "profile").as_uri(),
                   "--headless", "--norestore", "--nodefault", "--nofirststartwizard",
                   "--nolockcheck", f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext"]
        # Profile isolation alone does not redirect GLib/dconf or font caches.
        # Keep those writes private too, including on read-only /run/user hosts.
        environment = os.environ.copy()
        for variable, name in (("HOME", "home"), ("XDG_RUNTIME_DIR", "runtime"),
                               ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config")):
            directory = temporary / name
            directory.mkdir(mode=0o700)
            environment[variable] = str(directory)
        environment["GSETTINGS_BACKEND"] = "memory"
        environment["SAL_USE_VCLPLUGIN"] = "svp"
        desktop = document = None
        with (temporary / "office.log").open("w+") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, env=environment)
            try:
                local = uno.getComponentContext()
                resolver = local.ServiceManager.createInstanceWithContext(
                    "com.sun.star.bridge.UnoUrlResolver", local)
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        context = resolver.resolve(
                            f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
                        break
                    except Exception as error:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            log.seek(0)
                            raise RuntimeError(f"LibreOffice did not start (exit={process.poll()}): "
                                               + log.read()[-4000:]) from error
                        time.sleep(0.1)
                desktop = context.ServiceManager.createInstanceWithContext(
                    "com.sun.star.frame.Desktop", context)
                try:
                    document = desktop.loadComponentFromURL("private:factory/simpress", "_blank", 0,
                        (property_value(uno, "Hidden", True),))
                except Exception as error:
                    raise RuntimeError("LibreOffice started but could not create an Impress document. "
                                       "Verify that the Impress module is installed (Core/Writer alone "
                                       "are insufficient). UNO error: " + str(error)) from error
                require(document is not None, "LibreOffice could not create an Impress document")
                yield document, context
            finally:
                if document is not None:
                    try:
                        document.close(True)
                    except Exception:
                        pass
                if desktop is not None:
                    try:
                        desktop.terminate()
                    except Exception:
                        pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # The launcher can have a soffice.bin child. This group is
                    # private to this invocation, never an existing office UI.
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                finally:
                    # Also cover a launcher that exited before its child.
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass


def write_chart(path, matrix):
    rows, ceiling, title = chart_data(matrix)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
           'viewBox="0 0 960 540" role="img" aria-labelledby="title desc">',
           f'<title id="title">{escape(title)}</title>',
           '<desc id="desc">Zero-based bars for one 16 by 16 RV32 kernel call at O3. '
           'Executed QEMU guest instructions, not cycles or hardware speedup.</desc>',
           '<rect width="960" height="540" fill="white"/>',
           '<g font-family="Liberation Sans, sans-serif">']

    def label(x, y, value, size=16, color=NAVY, anchor="start", bold=False):
        svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="#{color:06x}" '
                   f'text-anchor="{anchor}" font-weight="{700 if bold else 400}">'
                   f'{escape(value)}</text>')

    label(42, 84, title, 30, bold=True)
    label(42, 122, "One 16 × 16 kernel call, including return · -O3 · lower is better", 17, GRAY)
    for tick in range(6):
        x = 320 + tick * 102
        svg.append(f'<path d="M{x} 163V400" stroke="#{LINE:06x}"/>')
        label(x, 427, f"{ceiling * tick // 5:,}", 14, GRAY, "middle")
    for index, (name, count, color) in enumerate(rows):
        y = 174 + index * 58
        width = count / ceiling * 510
        label(42, y + 21, name)
        svg.append(f'<rect x="320" y="{y}" width="{width:.3f}" height="30" fill="#{color:06x}"/>')
        label(332 + width, y + 23, f"{count:,}", 17, bold=True)
    label(575, 454, "Executed guest instructions", 14, GRAY, "middle")
    label(42, 489, "Same logical pixels and -mtune=size; no LTO or auto-vectorization. P 0.6 draft.", 10, GRAY)
    label(42, 514, "QEMU guest instructions, -O3; hardware mode assumes misaligned word loads. Hardware timing not measured.", 10, GRAY)
    svg.append("</g></svg>\n")
    path.write_text("\n".join(svg))


def write_source_data(path, matrix, source, backend):
    entries = []
    for item in matrix.values():
        entries.append({"source": str(Path(item.source).relative_to(source)),
                        "xlen": item.xlen, "alignment": item.alignment,
                        "optimization": item.optimization, "c_checks": item.cases,
                        "image_candidates": item.candidates, "trace_sad": item.checksum,
                        "guest_instructions": {f"{kernel}_{layout}": value
                                               for (kernel, layout), value in item.counts.items()},
                        "kernel_text_bytes": item.text, "static_frame_bytes": item.frames,
                        "tested_versions": item.versions})
    path.write_text(json.dumps({"input_layout": "rv{32,64}/{hardware,strict}/{O2,O3,Os}/result.json",
                    "scope": "Guest instruction counts, not cycles or hardware speedup",
                    "presentation_backend": backend,
                    "pdf_method": ("Shared slide layout rendered with Matplotlib; not a PowerPoint/Impress round-trip"
                                   if backend == "native" else "LibreOffice Impress export"),
                    "chart_configuration": "RV32 O3; identical logical pixels across layouts",
                    "results": entries}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", required=True, type=Path, help="complete matrix directory")
    parser.add_argument("--output-dir", type=Path, help="PPTX/PDF/SVG/data destination (for example /tmp/slides)")
    parser.add_argument("--check-only", action="store_true", help="validate input JSON without UNO or writes")
    parser.add_argument("--backend", choices=("native", "uno"), default="native",
                        help="native: editable OOXML + Matplotlib PDF (default); uno: LibreOffice Impress")
    parser.add_argument("--overwrite", action="store_true", help="replace this generator's existing output files")
    parser.add_argument("--office-timeout", type=float, default=30, help="LibreOffice startup timeout in seconds")
    args = parser.parse_args()
    if not args.check_only and args.output_dir is None:
        parser.error("--output-dir is required unless --check-only is used")
    if not math.isfinite(args.office_timeout) or not 1 <= args.office_timeout <= 60:
        parser.error("--office-timeout must be between 1 and 60 seconds")
    try:
        source = args.results.resolve()
        matrix = load_matrix(source)
        with IMAGE.open("rb") as stream:
            header = stream.read(24)
        require(header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) == 24
                and struct.unpack(">II", header[16:24]) == (1440, 540),
                "expected the existing 1440 x 540 image-block-matching.png illustration")
        print(f"Validated {len(matrix)} result files; slide and chart values come from this matrix.")
        if args.check_only:
            return
        if args.backend == "uno":
            executable = shutil.which("libreoffice") or shutil.which("soffice")
            require(executable is not None, "LibreOffice is not installed")
            try:
                import uno
            except ImportError as error:
                raise ValueError("Python UNO bridge is unavailable; use /usr/bin/python3") from error
        destination = args.output_dir.resolve()
        existing = [name for name in OUTPUTS if (destination / name).exists()]
        require(args.overwrite or not existing,
                "output already exists (use --overwrite): " + ", ".join(existing))
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".rvp-slides-", dir=destination) as staging:
            staging = Path(staging)
            if args.backend == "native":
                export_native(matrix, staging)
            else:
                with office_session(uno, executable, args.office_timeout) as (document, context):
                    document.getDocumentProperties().Title = "Image block matching with RV32 P"
                    document.getDocumentProperties().Subject = "C intrinsics, validated instruction counts and footprint"
                    document.getDocumentProperties().Author = "RVP-Example"
                    build_deck(Deck(document, uno, context), matrix)
                    for name, filter_name in ((OUTPUTS[0], "Impress MS PowerPoint 2007 XML"),
                                               (OUTPUTS[1], "impress_pdf_Export")):
                        document.storeToURL((staging / name).as_uri(),
                            (property_value(uno, "FilterName", filter_name),
                             property_value(uno, "Overwrite", True)))
                validate_pptx(staging / OUTPUTS[0], len(matrix) // 2)
            write_chart(staging / OUTPUTS[2], matrix)
            write_source_data(staging / OUTPUTS[3], matrix, source, args.backend)
            for name in OUTPUTS:
                require((staging / name).is_file() and (staging / name).stat().st_size > 0,
                        f"missing or empty generated artifact: {name}")
            for name in OUTPUTS:
                (staging / name).replace(destination / name)
                print(destination / name)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Slide generation failed: {error}\n")


if __name__ == "__main__":
    main()
