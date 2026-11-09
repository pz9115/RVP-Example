#!/usr/bin/env python3
"""Build and validate one configuration using only the included binaries."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from demo_config import ROOT, configuration


SUCCESS_REPORTS = (
    "result.json", "instruction-counts.json", "tests.json", "demo.json",
    "compiler-regression.json", "alignment-checks.json",
)


def clear_success_reports(out):
    """Keep diagnostics and unrelated files, but never retain stale success."""
    for name in SUCCESS_REPORTS:
        (out / name).unlink(missing_ok=True)


def run(command, destination=None, combined=False):
    command = list(map(str, command))
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=60)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        if destination:
            destination.write_text(stdout + (stderr if combined else ""))
        else:
            print(stdout, end="", flush=True)
        print(stderr, end="", file=sys.stderr, flush=True)
        raise
    if destination:
        destination.write_text(result.stdout + (result.stderr if combined else ""))
    else:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    result.check_returncode()
    return result


def main():
    supplied_out = os.environ.get("OUT")
    if supplied_out == "":
        raise ValueError("OUT must not be empty")
    out = Path(supplied_out).resolve() if supplied_out is not None else None
    try:
        # An explicit output is known even when the new settings are invalid.
        if out is not None:
            clear_success_reports(out)
        config = configuration(int(os.environ.get("XLEN", "32")),
                               os.environ.get("ALIGNMENT", "hardware"))
        if out is None:
            out = (ROOT / "build" /
                   f"rv{config['xlen']}-{config['alignment']}").resolve()
            clear_success_reports(out)
        if os.environ.get("ALIGNFLAGS"):
            raise ValueError("Use ALIGNMENT=hardware|strict instead of ALIGNFLAGS")
        if any(c.isspace() for c in str(ROOT) + str(out)):
            raise ValueError("Use project and output paths without whitespace")
        run_demo(config, out)
    except BaseException:
        # Also remove reports created before a later failure or interruption.
        if out is not None:
            clear_success_reports(out)
        raise


def run_demo(config, out):
    xlen = config["xlen"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    config["optimization"] = os.environ.get("OPTFLAGS", "-O3")
    (out / "build-config.json").write_text(json.dumps(config, indent=2) + "\n")
    run([sys.executable, ROOT / "scripts/check-host.py", "--xlen", xlen,
         "--output", out / "host.json"])
    bindir = ROOT / config["toolchain_directory"] / "bin"
    prefix = config["target"] + "-"
    gcc = bindir / (prefix + "gcc")
    qemu = ROOT / "qemu/bin" / f"qemu-riscv{xlen}"
    here = ROOT / "examples/rvp-image-sad"
    run(["make", "-C", here, "-j2", "-B", f"BUILD={out}",
                 f"CC={gcc}", f"LINK_CC={gcc}", f"XLEN={xlen}",
                 f"ALIGNMENT={config['alignment']}",
                 f"OPTFLAGS={config['optimization']}"], out / "build.log", combined=True)
    run([gcc, "-march=" + config["kernel_arch"], "-mabi=" + config["abi"],
         "-dM", "-E", "-x", "c", "/dev/null"], out / "macros.txt")
    for kernel in ("scalar", "p"):
        run([bindir / (prefix + "objdump"), "-dr", out / f"sad-{kernel}.o"],
            out / f"sad-{kernel}.dis")
        run([bindir / (prefix + "size"), "-A", out / f"sad-{kernel}.o"],
            out / f"sad-{kernel}.size")
    run([bindir / (prefix + "readelf"), "-A", out / "sad-demo"],
        out / "attributes.txt")
    run([bindir / (prefix + "readelf"), "-A", out / "sad-p.o"],
        out / "kernel-attributes.txt")
    crt = run([gcc, "-print-file-name=crt1.o"]).stdout.strip()
    run([bindir / (prefix + "readelf"), "-h", crt], out / "runtime-startup-elf.txt")
    version = run([gcc, "-v"])
    for name in ("compiler-version.txt", "link-driver-version.txt"):
        (out / name).write_text(version.stdout + version.stderr)
    cc1 = run([gcc, "-print-prog-name=cc1"]).stdout.strip()
    version = run([cc1, "-quiet", "-version", "-fpreprocessed",
                   "/dev/null", "-o", "/dev/null"])
    (out / "cc1-version.txt").write_text(version.stdout + version.stderr)
    run([qemu, "--version"], out / "qemu-version.txt")
    runner = [qemu, "-R", "512M", "-cpu", config["qemu_cpu"], out / "sad-demo"]
    if xlen == 32:
        carry = out / "rv32-add64"
        run([gcc, *shlex.split(config["optimization"]), "-mtune=size",
             "-march=" + config["kernel_arch"], "-mabi=ilp32", "-static",
             here / "tests/rv32-add64.c", "-o", carry],
            out / "rv32-add64-build.log", combined=True)
        run([qemu, "-R", "512M", "-cpu", config["qemu_cpu"], carry])
        (out / "compiler-regression.json").write_text(
            json.dumps({"rv32_uint64_add": "pass", "cases": 7}, indent=2) + "\n")
    run([*runner, "--test"], out / "tests.json")
    run([*runner, "--demo", out / "images"], out / "demo.json")
    timing = run([*runner, "--bench", "qemu"], out / "benchmark.csv")
    (out / "benchmark-note.txt").write_text(timing.stderr)
    run([sys.executable, here / "trace-count.py", out, "--qemu", qemu,
         "--binutils", bindir, "--binutils-prefix", prefix])
    run([sys.executable, here / "report.py", out, "--versions", ROOT / "VERSION.json"])
    run([sys.executable, ROOT / "scripts/render-demo.py", out])
    print(f"Results: {out / 'result.json'}")


if __name__ == "__main__":
    main()
