#!/usr/bin/env python3
"""Count guest kernel instructions, NOT simulated cycles or hardware speedup.

One guest instruction per TB plus disabled TB chaining makes every Trace line
one execution event.  Symbol address filters exclude startup and the harness.
Use only on this single-threaded, non-faulting workload; retain raw traces.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess


def output(command):
    return subprocess.check_output(list(map(str, command)), text=True, timeout=60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--binutils", required=True, type=Path)
    parser.add_argument("--binutils-prefix", default="")
    args = parser.parse_args()
    out = args.output.resolve()
    config = json.loads((out / "build-config.json").read_text())
    xlen = config["xlen"]
    assert xlen in (32, 64)
    assert config["alignment"] in ("hardware", "strict")
    assert config["qemu_cpu"].split(",")[0] == f"rv{xlen}"
    executable = out / "sad-demo"
    prefix = args.binutils_prefix
    nm = prefix + "nm" if prefix else "nm-new"
    symbols = output([args.binutils / nm, "-S", "--defined-only", executable])
    results = []
    for kernel in ("scalar", "p"):
        name = "sad_" + kernel
        functions = []
        for line in symbols.splitlines():
            fields = line.split()
            if len(fields) == 4 and fields[2] in ("t", "T"):
                if fields[3] == name or fields[3].startswith(name + "."):
                    functions.append((int(fields[0], 16), int(fields[1], 16), fields[3]))
        assert functions, name
        ranges = ",".join(f"0x{start:x}+0x{size:x}" for start, size, _ in functions)
        instructions = {}
        operands_by_pc = {}
        for _, _, symbol in functions:
            dis = output([args.binutils / (prefix + "objdump"), "-d", "--disassemble=" + symbol,
                          executable])
            for address, opcode, operands in re.findall(
                    r"^\s*([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)([^\n]*)", dis, re.M):
                # Out-of-line calls would be missing from a kernel-only filter.
                assert opcode not in ("call", "tail", "jal", "jalr", "jr",
                                      "c.jal", "c.jalr", "c.jr"), (symbol, opcode)
                instructions[int(address, 16)] = opcode
                operands_by_pc[int(address, 16)] = operands
        # A tail call can also appear as an ordinary jump after relaxation.
        for pc, opcode in instructions.items():
            if opcode in ("j", "c.j", "c.beqz", "c.bnez") or re.fullmatch(
                    r"b(?:eq|ne|ge|lt|le|gt)u?z?", opcode):
                target = re.search(r"(?:^|,)\s*([0-9a-f]+)\s*<",
                                   operands_by_pc[pc])
                assert target and int(target[1], 16) in instructions, (hex(pc), opcode)
        for layout in ("aligned", "unaligned"):
            runs = []
            for repetition in range(2):
                trace = out / f"trace-{kernel}-{layout}-{repetition}.log"
                command = [args.qemu, "-R", "512M", "-cpu",
                           config["qemu_cpu"],
                           "-one-insn-per-tb", "-d", "exec,nochain", "-dfilter", ranges,
                           "-D", trace, executable, "--trace", kernel, layout]
                case = json.loads(output(command))
                pcs = []
                for line in trace.read_text().splitlines():
                    if not line.startswith("Trace "):
                        continue
                    match = re.search(r"\[[0-9a-f]+/([0-9a-f]+)/", line)
                    assert match, line
                    pc = int(match[1], 16)
                    assert pc in instructions, hex(pc)
                    pcs.append(pc)
                entry = next(start for start, _, symbol in functions if symbol == name)
                assert pcs and pcs[0] == entry
                assert instructions[pcs[-1]] == "ret", "Missing kernel return"
                histogram = Counter(instructions[pc] for pc in pcs)
                packed = histogram["pabdsumu.b"] + histogram["pabdsumau.b"]
                expected_packed = 16 * 16 // (xlen // 8) if kernel == "p" else 0
                assert packed == expected_packed, histogram
                if kernel == "p" and config["alignment"] == "hardware":
                    # Width is a multiple of the packed width: byte loads here
                    # would indicate a split-load fallback, not a scalar tail.
                    assert histogram["lbu"] == histogram["lb"] == 0, histogram
                    wide = (histogram["lw"] + histogram["lwu"] if xlen == 32
                            else histogram["ld"])
                    assert wide >= 2 * expected_packed, histogram
                runs.append({"guest_instructions": len(pcs), "opcodes": dict(histogram),
                             "checksum": case["sad"], "command": list(map(str, command)),
                             "trace": trace.name})
            for field in ("guest_instructions", "opcodes", "checksum"):
                assert runs[0][field] == runs[1][field], (name, layout, field)
            results.append({"kernel": kernel, "layout": layout, "xlen": xlen,
                            "alignment_policy": config["alignment"],
                            "width": 16, "height": 16, "runs": runs})
    assert len({r["runs"][0]["checksum"] for r in results}) == 1, \
        "Layouts and kernels must use identical logical input pixels"
    report = {
        "xlen": xlen,
        "alignment_policy": config["alignment"],
        "metric": "Executed guest instructions inside the SAD kernel, including return",
        "method": "QEMU -one-insn-per-tb -d exec,nochain, symbol-address filtered",
        "warning": "Not cycles, hardware throughput, or application speedup",
        "input_policy": "Identical logical pixels, dimensions and strides across layouts",
        "hardware_mode_check": {
            "performed": config["alignment"] == "hardware",
            "scope": "No split byte loads in the traced packed loop; "
                     "instruction counts do not measure misalignment latency",
        },
        "results": results,
    }
    (out / "instruction-counts.json").write_text(json.dumps(report, indent=2) + "\n")
    for result in results:
        print(f"Guest instructions: {result['kernel']} {result['layout']}: "
              f"{result['runs'][0]['guest_instructions']}")


if __name__ == "__main__":
    main()
