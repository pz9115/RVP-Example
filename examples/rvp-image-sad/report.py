#!/usr/bin/env python3
"""Validate demo output and summarize correctness and timing results."""

import argparse
import csv
import json
from pathlib import Path
import re
import statistics


def read_pgm(path):
    magic, dimensions, maximum, pixels = path.read_bytes().split(b"\n", 3)
    assert magic == b"P5" and maximum == b"255"
    width, height = map(int, dimensions.split())
    assert len(pixels) == width * height
    return width, height, pixels


def verify_images(directory):
    width, height, a = read_pgm(directory / "reference.pgm")
    bw, bh, b = read_pgm(directory / "shifted.pgm")
    assert (width, height) == (bw, bh) == (96, 80)
    rows = list(csv.DictReader((directory / "costs.csv").open()))
    assert len(rows) == 289
    seen = set()
    for row in rows:
        dx, dy = int(row["dx"]), int(row["dy"])
        assert -8 <= dx <= 8 and -8 <= dy <= 8
        assert (dx, dy) not in seen
        seen.add((dx, dy))
        expected = sum(abs(a[(32 + y) * width + 32 + x]
                           - b[(32 + dy + y) * width + 32 + dx + x])
                       for y in range(16) for x in range(16))
        assert expected == int(row["scalar_sad"]) == int(row["p_sad"])
    best = min(rows, key=lambda row: int(row["p_sad"]))
    assert (int(best["dx"]), int(best["dy"]), int(best["p_sad"])) == (5, -3, 0)
    return {"python_oracle_candidates": len(rows), "displacement": [5, -3]}


def timings(path):
    groups = {}
    expected_by_size = {}
    for row in csv.DictReader(path.open()):
        key = tuple(row[k] for k in ("environment", "kernel", "width", "height",
                                    "a_stride", "b_stride", "a_offset", "b_offset"))
        assert row["environment"] in ("qemu", "hardware")
        iterations = int(row["iterations"])
        elapsed = int(row["elapsed_ns"])
        assert iterations > 0 and elapsed > 0
        per_call, remainder = divmod(int(row["checksum"]), iterations)
        assert remainder == 0, "Invalid accumulated benchmark checksum"
        size = (int(row["width"]), int(row["height"]))
        assert expected_by_size.setdefault(size, per_call) == per_call, \
            "Benchmark layouts and kernels must use identical logical pixels"
        group = groups.setdefault(key, {"samples": set(), "times": []})
        assert row["sample"] not in group["samples"]
        group["samples"].add(row["sample"])
        group["times"].append(elapsed / iterations)
    result = []
    for key, values in sorted(groups.items()):
        assert values["samples"] == {str(i) for i in range(9)}
        times = values["times"]
        result.append({
            "environment": key[0], "kernel": key[1],
            "width": int(key[2]), "height": int(key[3]),
            "a_stride": int(key[4]), "b_stride": int(key[5]),
            "a_offset": int(key[6]), "b_offset": int(key[7]),
            "samples": len(times), "median_ns_per_call": statistics.median(times),
            "min_ns_per_call": min(times), "max_ns_per_call": max(times),
        })
    assert len(result) == 12
    return result


def stack_usage(path, name):
    """Return compiler-reported static frames, not a whole-program stack bound."""
    frames = []
    for line in path.read_text().splitlines():
        location, size, kind = line.split("\t")
        function = location.rsplit(":", 1)[-1]
        if function == name or function.startswith(name + "."):
            assert kind == "static", (function, kind)
            frames.append({"function": function, "bytes": int(size)})
    assert frames, f"Missing stack usage for {name}"
    return {"max_static_frame_bytes": max(frame["bytes"] for frame in frames),
            "functions": frames}


def opcodes(disassembly):
    return re.findall(r"^\s*[0-9a-f]+:\s+[0-9a-f]+\s+(\S+)",
                      disassembly, re.M)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--versions", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    versions = json.loads(args.versions.read_text())
    config = json.loads((out / "build-config.json").read_text())
    xlen = config["xlen"]
    assert xlen in (32, 64)
    assert config["alignment"] in ("hardware", "strict")
    tests = json.loads((out / "tests.json").read_text())
    demo = json.loads((out / "demo.json").read_text())
    assert tests["failures"] == 0 and tests["cases"] == 82640
    assert demo["all_costs_match"] and demo["sad"] == 0
    macros = (out / "macros.txt").read_text()
    assert re.search(r"^#define __riscv_p 6000$", macros, re.M)
    assert re.search(rf"^#define __riscv_xlen {xlen}$", macros, re.M)
    assert "_p0p6" in (out / "attributes.txt").read_text()
    kernel_attributes = (out / "kernel-attributes.txt").read_text()
    assert f"rv{xlen}i" in kernel_attributes and "_p0p6" in kernel_attributes
    if xlen == 32:
        assert config["abi"] == config["runtime_abi"] == "ilp32"
        assert re.search(r"^#define __riscv_float_abi_soft 1$", macros, re.M)
        assert not re.search(r"_(?:f|d|v)\d+p\d+", kernel_attributes)
        assert not re.search(r"_(?:f|d|v)\d+p\d+",
                             (out / "attributes.txt").read_text())
    p_asm = (out / "sad-p.dis").read_text()
    scalar_asm = (out / "sad-scalar.dis").read_text()
    assert "pabdsumu.b" in p_asm or "pabdsumau.b" in p_asm
    wide_load = "lw" if xlen == 32 else "ld"
    assert wide_load in opcodes(p_asm), "Missing native-width packed loads"
    assert not re.search(r"\s(?:pabdsumu|pabdsumau)\.b\s", scalar_asm)
    instructions = opcodes(p_asm + scalar_asm)
    assert not any(op.startswith("v") for op in instructions), "Unexpected RVV instruction"
    assert not any(op.startswith("f") and not op.startswith("fence")
                   for op in instructions), "Unexpected floating-point instruction"

    code_bytes = {}
    frames = {}
    for kernel in ("scalar", "p"):
        sizes = (out / f"sad-{kernel}.size").read_text()
        code_bytes[kernel] = sum(int(size) for size in re.findall(
            r"^\.text\S*\s+(\d+)\s+", sizes, re.M))
        assert code_bytes[kernel] > 0
        frames[kernel] = stack_usage(out / f"sad-{kernel}.su", "sad_" + kernel)
    counts = json.loads((out / "instruction-counts.json").read_text())
    assert counts["xlen"] == xlen and counts["alignment_policy"] == config["alignment"]
    report = {
        "purpose": f"RV{xlen} P image block matching / SAD demonstration",
        "build_configuration": config,
        "spec_state": "P v0.6 draft, not ratified",
        "tested_versions": versions["versions"],
        "tests": tests, "demo": demo,
        "compiler_regression": (json.loads((out / "compiler-regression.json").read_text())
                                if xlen == 32 else None),
        "independent_image_check": verify_images(out / "images"),
        "code_generation": {"packed_sad_present": True,
                            "native_load": wide_load,
                            "no_rvv": True, "no_floating_point": True,
                            "text_bytes": code_bytes, "stack_usage": frames,
                            "stack_scope": "Compiler-reported kernel frames, "
                                           "not whole-program stack usage"},
        "instruction_counts": counts,
        "measurement_scope": "SAD kernels only; warmed-up emulator timings, "
                             "not end-to-end video or a hardware cache model",
        "qemu_timings_are_hardware_performance": False,
        "hardware_speedup": None,
        "timing_note": "Emulator host elapsed times are diagnostic only. "
                       "Static code size is not dynamic instruction count or speedup.",
        "timings": timings(out / "benchmark.csv"),
        "build_commands": (out / "build.log").read_text(),
        "compiler_driver": (out / "compiler-version.txt").read_text(),
        "compiler_frontend": (out / "cc1-version.txt").read_text(),
        "link_driver": (out / "link-driver-version.txt").read_text(),
        "qemu": (out / "qemu-version.txt").read_text(),
    }
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {tests['cases']} C cases; 289 independent Python image costs")
    print(f"Code bytes (not a speedup): {code_bytes}")
    print("Kernel stack frames:",
          {kernel: frame["max_static_frame_bytes"] for kernel, frame in frames.items()})
    print("Hardware performance: not measured; QEMU times are diagnostic only")


if __name__ == "__main__":
    main()
