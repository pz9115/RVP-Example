#!/usr/bin/env python3
"""Build three RV32-first Q15 DSP slides from real RV32/RV64 hardware O3 runs.

Use --rv32 and --rv64 to select output directories from scripts/run-dsp.py.
Each directory must contain result.json, demo.json and repeated trace fixtures.
No kernels are built here, no measurements are invented, and no downloads occur.
The native editable-PPTX/PDF renderer is shared with build-slides.py.
"""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import signal
import sys
import tempfile

from dsp_report import render, verify_demo, verify_trace


SCRIPTS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("rvp_slide_layout", SCRIPTS / "build-slides.py")
LAYOUT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LAYOUT
SPEC.loader.exec_module(LAYOUT)
require, integer = LAYOUT.require, LAYOUT.integer
NAVY, ORANGE, GRAY, PALE, LINE, WHITE = (getattr(LAYOUT, name)
    for name in ("NAVY", "ORANGE", "GRAY", "PALE", "LINE", "WHITE"))
OUTPUTS = ("RVP-Q15-DSP-RV32.pptx", "RVP-Q15-DSP-RV32.pdf",
           "rv32-q15-dsp.svg", "dsp-slides-data.json")


def load_target(directory, xlen):
    """Check reports and independently recompute every displayed signal/trace."""
    report = json.loads((directory / "result.json").read_text())
    demo = json.loads((directory / "demo.json").read_text())
    config = report["build_configuration"]
    for name, expected in {"xlen": xlen, "alignment": "hardware",
                           "optimization": "-O3", "tune": "size"}.items():
        require(config[name] == expected, f"{directory}: unexpected {name}")
    if xlen == 32:
        for name, expected in {"abi": "ilp32", "runtime_abi": "ilp32",
                               "kernel_arch": "rv32imcp0p6_zba_zbb",
                               "baseline_arch": "rv32imc_zba_zbb",
                               "runtime_arch": "rv32imac"}.items():
            require(config[name] == expected, f"RV32 target assumption changed: {name}")
        require(all(flag in config["qemu_cpu"].split(",")
                    for flag in ("f=false", "d=false", "v=false", "zfa=false")),
                "RV32 QEMU must explicitly disable FP/RVV")
    require(integer(report["tests"]["failures"], "test failures") == 0, "C tests failed")
    integer(report["tests"]["cases"], "C test cases", 1)
    require(report["python_oracle"] == verify_demo(demo), "Independent demo oracle differs")
    require(report["metric"] == "Executed guest kernel instructions, including return",
            "Unexpected measurement scope")
    require(report["scope"] == "Prepared data only; excludes history/coefficients setup and harness",
            "Prepared-data scope changed")
    require(report["hardware_speedup"] is None, "Unexpected hardware-performance claim")
    require(report["negative_controls"] == {"scalar_without_p": "pass", "packed_without_p": "SIGILL"},
            "P-disabled controls did not pass")
    alignment = report["alignment_checks"]
    for name, expected in {"scope": "Libc-free probe of the measured dot and FIR objects",
                           "scalar_with_misaligned_traps": "pass",
                           "packed_with_misaligned_support": "pass",
                           "packed_with_misaligned_traps": "SIGBUS"}.items():
        require(alignment[name] == expected, f"Alignment check differs: {name}")
    probes = [item for item in alignment["commands"] if isinstance(item, dict)]
    require(len(probes) == 3, "Missing alignment-probe execution records")
    for probe, support, kernel in zip(probes, (False, True, False), ("scalar", "p", "p")):
        command = probe["command"]
        cpu = command[command.index("-cpu") + 1]
        require(f"zicclsm={'true' if support else 'false'}" in cpu.split(",")
                and Path(command[-1]).name == f"alignment-{kernel}",
                "Alignment-probe command does not match its reported policy")
        require(probe["returncode"] in (-signal.SIGBUS, 128 + signal.SIGBUS)
                if kernel == "p" and not support else probe["returncode"] == 0,
                "Alignment-probe return code does not match its reported result")
    expected_keys = {(workload, kernel, layout) for workload in ("dot", "fir")
                     for kernel in ("scalar", "p") for layout in ("aligned", "unaligned")}
    rows, fixtures = {}, {}
    for row in report["instruction_counts"]:
        key = row["workload"], row["kernel"], row["layout"]
        require(key in expected_keys and key not in rows, "Missing, duplicate or unknown trace variant")
        workload, kernel, layout = key
        require(len(row["runs"]) == 2, "Need two repeated traces per variant")
        signatures = []
        for repetition, run in enumerate(row["runs"]):
            case = json.loads((directory / f"{workload}-{kernel}-{layout}-{repetition}.json").read_text())
            require((case["workload"], case["kernel"], case["layout"]) == key,
                    "Trace fixture metadata differs")
            expected = verify_trace(case)
            require(run["result"] == expected, "Reported trace result differs from the integer oracle")
            fields = ("a", "b") if workload == "dot" else ("coefficients", "history", "input")
            inputs = [case[field] for field in fields]
            require(fixtures.setdefault(workload, inputs) == inputs,
                    "Trace inputs differ between kernels, layouts or repetitions")
            count = integer(run["guest_instructions"], "guest instructions", 1)
            opcodes = run["opcodes"]
            require(sum(integer(value, "opcode count") for value in opcodes.values()) == count,
                    "Opcode totals differ from the instruction count")
            require(opcodes.get("ret", 0) == 1, "Trace must contain exactly one kernel return")
            require(not any(op in opcodes for op in ("call", "tail", "jal", "jalr", "jr",
                                                      "c.jal", "c.jalr", "c.jr")),
                    "Trace contains an out-of-line call or jump")
            require(not any(op.startswith("v") or (op.startswith("f") and not op.startswith("fence"))
                            for op in opcodes), "Unexpected floating-point or RVV opcode")
            packed = sum(value for op, value in opcodes.items()
                         if re.fullmatch(r"pm(?:2w|4)add[a]?\.h", op))
            products = 1024 if workload == "dot" else 32 * 64
            require(packed == (products // (xlen // 16) if kernel == "p" else 0),
                    "Unexpected packed MAC count")
            if kernel == "p":
                loads = opcodes.get("lw", 0) + opcodes.get("lwu", 0) if xlen == 32 else opcodes.get("ld", 0)
                require(loads >= 2 * packed, "Missing native packed loads")
                require(not any(opcodes.get(op, 0) for op in ("lb", "lbu", "lh", "lhu")),
                        "Hardware-mode packed trace contains a narrow-load fallback")
            else:
                require(not any(op.startswith("p") for op in opcodes), "P opcode in scalar baseline")
            signatures.append((count, opcodes, expected))
        require(signatures[0] == signatures[1], "Repeated traces disagree")
        require(integer(row["guest_instructions"], "reported instructions", 1) == signatures[0][0],
                "Instruction summary differs from the repeated traces")
        rows[key] = signatures[0][0]
    require(set(rows) == expected_keys, "Need all eight dot/FIR trace variants")
    footprint = report["kernel_footprint"]
    for workload in ("dot", "fir"):
        for kernel in ("scalar", "p"):
            item = footprint[f"q15_{workload}_{kernel}"]
            integer(item["text_bytes"], "kernel text bytes", 1)
            integer(item["static_frame_bytes"], "static frame bytes")
    return {"report": report, "demo": demo, "counts": rows, "fixtures": fixtures}


def load_pair(rv32, rv64):
    targets = {32: load_target(rv32, 32), 64: load_target(rv64, 64)}
    for field in ("demo", "fixtures"):
        require(targets[32][field] == targets[64][field], f"RV32/RV64 {field} differ")
    require(targets[32]["report"]["tested_versions"] == targets[64]["report"]["tested_versions"],
            "RV32/RV64 tool versions differ")
    return targets


def build_deck(deck, targets):
    rv32, rv64 = targets[32], targets[64]
    page = deck.page("Lightweight DSP in ordinary C",
                     "Q15 dot product and FIR, using packed multiply-accumulate intrinsics.")
    deck.rectangle(page, 42, 151, 630, 233, PALE)
    code = ("int64_t sum = 0;\n"
            "size_t i = 0;\n"
            "for (; count - i >= 2; i += 2)\n"
            "  {\n"
            "    int16x2_t av = __riscv_pld_i16x2 ((int16_t *) (a + i));\n"
            "    int16x2_t bv = __riscv_pld_i16x2 ((int16_t *) (b + i));\n"
            "    sum = __riscv_pm2wadda_i64 (sum, av, bv);\n"
            "  }")
    deck.text(page, 58, 173, 602, 193, code, 14, mono=True)
    deck.text(page, 696, 155, 220, 26, "LOAD", 16, ORANGE, bold=True)
    deck.text(page, 696, 185, 220, 45, "Two signed Q15 samples\nfrom each input.", 16)
    deck.text(page, 696, 239, 220, 26, "MULTIPLY–ACCUMULATE", 15, ORANGE, bold=True)
    deck.text(page, 696, 269, 220, 45, "Add both products to\na 64-bit running sum.", 16)
    deck.text(page, 696, 324, 220, 26, "REUSE FOR FIR", 16, ORANGE, bold=True)
    deck.text(page, 696, 354, 220, 45, "Apply the dot product\nto each sample window.", 16)
    deck.text(page, 42, 408, 876, 32,
              "Two samples per packed MAC on RV32; four on RV64.", 20, bold=True)
    deck.text(page, 42, 451, 876, 37,
              "The same intrinsic loop supports a dot product and each FIR sample window.\n"
              "Complete C kernels and test inputs are included.", 14)

    fir = rv32["demo"]["fir"]
    taps, samples = len(fir["coefficients"]), len(fir["input"])
    page = deck.page("Filter a signal with a short FIR",
                     f"{taps} asymmetric taps · {samples} samples · h[0] multiplies the current sample")
    left, right, top, bottom = 104, 907, 180, 405
    for value in (-32768, -16384, 0, 16384, 32767):
        y = top + (32767 - value) / 65535 * (bottom - top)
        deck.rectangle(page, left, y, right - left, 0.6, LINE)
        deck.text(page, 42, y - 8, 52, 22, f"{value:,}", 14, GRAY, align="RIGHT")
    for index in (0, 16, 32, 48, samples - 1):
        x = left + index / (samples - 1) * (right - left)
        deck.text(page, x - 20, 414, 40, 22, str(index), 14, GRAY, align="CENTER")
    for values, color in ((fir["input"], GRAY), (fir["p_q15"], ORANGE)):
        points = [(left + index / (samples - 1) * (right - left),
                   top + (32767 - value) / 65535 * (bottom - top))
                  for index, value in enumerate(values)]
        deck.polyline(page, points, color, 2)
    deck.text(page, 104, 145, 200, 23, "Q15 integer samples", 14, GRAY)
    deck.text(page, 120, 450, 180, 24, "Input", 16, GRAY, bold=True)
    deck.text(page, 280, 450, 300, 24, "FIR output", 16, ORANGE, bold=True)
    deck.text(page, 780, 450, 128, 24, "Sample index", 14, GRAY, align="RIGHT")
    deck.text(page, 42, 483, 876, 18,
              f"Scalar C and P intrinsics produce the same {samples} output samples.", 10, GRAY)

    page = deck.page("Less work for common DSP kernels",
                     "RV32 · dot: 1,024 terms · FIR: 32 taps × 64 outputs · base-aligned buffers")
    pairs = [(workload, kernel) for workload in ("dot", "fir") for kernel in ("scalar", "p")]
    counts = [rv32["counts"][(workload, kernel, "aligned")] for workload, kernel in pairs]
    step = 10 ** math.floor(math.log10(max(counts) / 4))
    ceiling = math.ceil(max(counts) / 4 / step) * step * 4
    left, width = 216, 375
    for tick in range(5):
        x = left + tick / 4 * width
        deck.rectangle(page, x, 167, 0.6, 231, LINE)
        deck.text(page, x - 37, 404, 74, 24, f"{ceiling * tick // 4:,}", 14, GRAY, align="CENTER")
    for index, ((workload, kernel), count) in enumerate(zip(pairs, counts)):
        y = 177 + index * 53 + (15 if index >= 2 else 0)
        label = ("Dot" if workload == "dot" else "FIR") + (" · scalar C" if kernel == "scalar" else " · P")
        deck.text(page, 42, y + 3, 166, 24, label, 16)
        bar_width = count / ceiling * width
        deck.rectangle(page, left, y, bar_width, 30, GRAY if kernel == "scalar" else ORANGE)
        deck.text(page, left + bar_width + 8, y + 4, 84, 24, f"{count:,}", 16, bold=True)
    deck.text(page, 690, 155, 228, 24, "RV32 footprint, bytes", 16, bold=True)
    columns = ((690, 94), (784, 68), (852, 66))
    for (x, span), label in zip(columns, ("Kernel", "Text", "Frame")):
        deck.rectangle(page, x, 190, span, 34, NAVY)
        deck.text(page, x + 7, 200, span - 12, 22, label, 14, WHITE, bold=True)
    for index, (workload, kernel) in enumerate(pairs):
        item = rv32["report"]["kernel_footprint"][f"q15_{workload}_{kernel}"]
        values = (workload.upper() + (" C" if kernel == "scalar" else " P"),
                  str(item["text_bytes"]), str(item["static_frame_bytes"]))
        for (x, span), label in zip(columns, values):
            y = 224 + index * 39
            deck.rectangle(page, x, y, span, 39, PALE if index % 2 == 0 else WHITE)
            deck.text(page, x + 7, y + 12, span - 12, 22, label, 14,
                      ORANGE if kernel == "p" else NAVY)
    deck.text(page, 690, 398, 228, 36, "Compiler-reported\nstatic frames.", 14, GRAY)
    deck.text(page, 216, 438, 375, 23, "Executed guest instructions", 14, GRAY, align="CENTER")
    other = rv64["counts"]
    deck.text(page, 42, 473, 876, 20,
              f"RV64 scalar/P reference: dot {other[('dot', 'scalar', 'aligned')]:,} / {other[('dot', 'p', 'aligned')]:,}; "
              f"FIR {other[('fir', 'scalar', 'aligned')]:,} / {other[('fir', 'p', 'aligned')]:,} instructions.", 10, GRAY)
    deck.text(page, 42, 489, 876, 16,
              "QEMU guest instructions on prepared inputs, -O3; misaligned word loads assumed for FIR's 2-byte steps. Hardware timing not measured.", 10, GRAY)


def source_data(targets):
    return {"input_layout": "RV32/RV64 hardware O3 run directories: result.json, demo.json and repeated trace fixtures",
            "pdf_method": "Shared slide layout rendered with Matplotlib; not a PowerPoint/Impress round-trip",
            "scope": "Prepared data only; guest kernel instructions, not hardware cycles or speedup",
            "layout_note": "Base-aligned buffers do not imply word-aligned FIR windows; state advances two bytes per output",
            "targets": [{"xlen": xlen, "alignment": "hardware", "optimization": "-O3",
                         "tests": data["report"]["tests"], "python_oracle": data["report"]["python_oracle"],
                         "alignment_checks": {key: value for key, value in data["report"]["alignment_checks"].items()
                                              if key != "commands"},
                         "counts": {"/".join(key): value for key, value in data["counts"].items()},
                         "kernel_footprint": data["report"]["kernel_footprint"],
                         "tested_versions": data["report"]["tested_versions"]}
                        for xlen, data in targets.items()],
            "demo": targets[32]["demo"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rv32", required=True, type=Path, help="RV32 hardware -O3 runner output")
    parser.add_argument("--rv64", required=True, type=Path, help="RV64 hardware -O3 runner output")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not args.check_only and args.output_dir is None:
        parser.error("--output-dir is required unless --check-only is used")
    try:
        targets = load_pair(args.rv32.resolve(), args.rv64.resolve())
        print("Validated RV32/RV64 hardware O3 reports, independent demo oracles and all repeated trace fixtures.")
        if args.check_only:
            return
        destination = args.output_dir.resolve()
        require(args.overwrite or not any((destination / name).exists() for name in OUTPUTS),
                "Output exists; use a fresh directory or --overwrite")
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".rvp-dsp-slides-", dir=destination) as temporary:
            staging = Path(temporary)
            with LAYOUT.native_rendering():
                deck = LAYOUT.NativeDeck(title="RV32 P Q15 DSP",
                    description="Q15 dot product and FIR: exact arithmetic, verified signal and measured guest instructions")
                build_deck(deck, targets)
                deck.save_pptx(staging / OUTPUTS[0])
                deck.save_pdf(staging / OUTPUTS[1])
            render(targets[32]["report"], targets[32]["demo"], staging / OUTPUTS[2])
            (staging / OUTPUTS[3]).write_text(json.dumps(source_data(targets), indent=2) + "\n")
            for name in OUTPUTS:
                require((staging / name).is_file() and (staging / name).stat().st_size > 0,
                        f"Missing output artifact: {name}")
            for name in OUTPUTS:
                (staging / name).replace(destination / name)
                print(destination / name)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"DSP slide generation failed: {error}\n")


if __name__ == "__main__":
    main()
