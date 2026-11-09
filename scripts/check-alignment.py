#!/usr/bin/env python3
"""Check kernel alignment behavior without the Linux C runtime.

The ordinary glibc demo is not a strict-alignment execution environment.
This probe links the same kernel objects into a libc-free Linux-user program.
QEMU's zicclsm setting controls whether misaligned loads and stores trap.
No timing or hardware atomicity claim follows from these checks.
"""

import argparse
import json
from pathlib import Path
import resource
import signal
import subprocess

from demo_config import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    destination = out / "alignment-checks.json"
    destination.unlink(missing_ok=True)
    config = json.loads((out / "build-config.json").read_text())
    xlen = config["xlen"]
    assert xlen in (32, 64)
    assert config["alignment"] in ("hardware", "strict")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    gcc = ROOT / config["toolchain_directory"] / "bin" / (config["target"] + "-gcc")
    qemu = ROOT / "qemu/bin" / f"qemu-riscv{xlen}"
    source = ROOT / "examples/rvp-image-sad/tests/alignment.c"
    commands = []

    def run(command):
        command = list(map(str, command))
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        commands.append({"command": command, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        return result

    executables = {}
    for kernel in ("scalar", "p"):
        executable = out / f"alignment-{kernel}"
        # The probe itself always uses strict scalar accesses.  Only the
        # separately compiled kernel object's alignment policy varies.
        result = run([gcc, "-O2", "-mtune=" + config["tune"], "-mstrict-align",
                      "-march=" + config["baseline_arch"], "-mabi=" + config["abi"],
                      "-fno-tree-vectorize", "-fno-tree-slp-vectorize",
                      "-ffreestanding", "-fno-pie", "-fno-stack-protector",
                      "-fno-lto", "-nostdlib", "-static", "-no-pie",
                      "-Wl,-e,_start", "-DALIGNMENT_KERNEL=sad_" + kernel,
                      source, out / f"sad-{kernel}.o", "-o", executable])
        assert result.returncode == 0, result.stderr
        executables[kernel] = executable

    cpu = ",".join(part for part in config["qemu_cpu"].split(",")
                   if not part.startswith("zicclsm="))

    def execute(kernel, misaligned):
        return run([qemu, "-R", "512M", "-cpu",
                    cpu + ",zicclsm=" + ("true" if misaligned else "false"),
                    executables[kernel]])

    scalar = execute("scalar", False)
    assert scalar.returncode == 0, scalar.stderr
    normal = execute("p", True)
    assert normal.returncode == 0, normal.stderr
    trapping = execute("p", False)
    if config["alignment"] == "hardware":
        assert trapping.returncode in (-signal.SIGBUS, 128 + signal.SIGBUS), \
            (trapping.returncode, trapping.stderr)
        expected = "SIGBUS"
    else:
        assert trapping.returncode == 0, trapping.stderr
        expected = "PASS"
    report = {
        "xlen": xlen,
        "alignment_policy": config["alignment"],
        "scope": "Libc-free kernel probe, not the full glibc demo",
        "completed_cases_per_successful_run": 1602,
        "cases": "All input offsets 0..7 and widths 0..24; two empty-image cases",
        "scalar_with_misaligned_traps": "PASS",
        "packed_with_misaligned_support": "PASS",
        "packed_with_misaligned_traps": expected,
        "commands": commands,
    }
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: RV{xlen} {config['alignment']} alignment probe; "
          f"packed kernel with misaligned traps: {expected}")


if __name__ == "__main__":
    main()
