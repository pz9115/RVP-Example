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
    for row in csv.DictReader(path.open()):
        key = tuple(row[k] for k in ("environment", "kernel", "width", "height",
                                    "a_stride", "b_stride", "a_offset", "b_offset"))
        assert row["environment"] in ("qemu", "hardware")
        iterations = int(row["iterations"])
        elapsed = int(row["elapsed_ns"])
        assert iterations > 0 and elapsed > 0
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--versions", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    versions = json.loads(args.versions.read_text())
    tests = json.loads((out / "tests.json").read_text())
    demo = json.loads((out / "demo.json").read_text())
    assert tests["failures"] == 0 and tests["cases"] > 80000
    assert demo["all_costs_match"] and demo["sad"] == 0
    assert re.search(r"^#define __riscv_p 6000$",
                     (out / "macros.txt").read_text(), re.M)
    assert "_p0p6" in (out / "attributes.txt").read_text()
    p_asm = (out / "sad-p.dis").read_text()
    scalar_asm = (out / "sad-scalar.dis").read_text()
    assert "pabdsumu.b" in p_asm or "pabdsumau.b" in p_asm
    assert re.search(r"\sld\s", p_asm), "Missing aligned packed loads"
    assert not re.search(r"\s(?:pabdsumu|pabdsumau)\.b\s", scalar_asm)
    assert not re.search(r"\svset(?:i?vli|vl)\s", p_asm + scalar_asm)

    code_bytes = {}
    for kernel in ("scalar", "p"):
        sizes = (out / f"sad-{kernel}.size").read_text()
        code_bytes[kernel] = sum(int(size) for size in re.findall(
            r"^\.text\S*\s+(\d+)\s+", sizes, re.M))
    report = {
        "purpose": "RV64 P image block matching / SAD demonstration",
        "spec_state": "P v0.6 draft, not ratified",
        "tested_versions": versions["versions"],
        "tests": tests, "demo": demo,
        "independent_image_check": verify_images(out / "images"),
        "code_generation": {"packed_sad_present": True,
                            "aligned_ld_present": True,
                            "no_rvv_vset": True, "text_bytes": code_bytes},
        "instruction_counts": json.loads((out / "instruction-counts.json").read_text()),
        "measurement_scope": "Warm-cache SAD kernels only; not end-to-end video",
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
    print("Hardware performance: not measured; QEMU times are diagnostic only")


if __name__ == "__main__":
    main()
