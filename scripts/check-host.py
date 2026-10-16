#!/usr/bin/env python3
"""Check the project's local RV64 toolchain and emulator installations."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = "riscv64-unknown-linux-gnu"


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True,
                                   stderr=subprocess.STDOUT, timeout=30).strip()


def internal(path):
    path = Path(path).resolve()
    if not path.exists() or not path.is_relative_to(ROOT):
        raise RuntimeError(f"Missing or external tool dependency: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    errors, observed = [], {}
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        errors.append("The validated tool configuration requires x86_64 Linux.")
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 or newer is required.")
    for name in ("make", "bash", "ldd"):
        if not shutil.which(name):
            errors.append(f"Missing host utility: {name}")
    for name in ("GCC_EXEC_PREFIX", "COMPILER_PATH", "LIBRARY_PATH",
                 "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
        if os.environ.get(name):
            errors.append(f"Unset {name} to avoid external compiler dependencies.")
    gcc = ROOT / "toolchain/bin" / (TARGET + "-gcc")
    try:
        if output(gcc, "-dumpmachine") != TARGET:
            raise RuntimeError("Wrong compiler target")
        programs = {name: internal(output(gcc, "-print-prog-name=" + name))
                    for name in ("cc1", "collect2", "lto1", "as", "ld")}
        programs.update({name: internal(ROOT / "toolchain/bin" / (TARGET + "-" + name))
                         for name in ("gcc", "objdump", "nm", "size", "readelf")})
        programs["qemu"] = internal(ROOT / "qemu/bin/qemu-riscv64")
        sysroot = internal(output(gcc, "-print-sysroot"))
        include = internal(output(gcc, "-print-file-name=include"))
        internal(include / "riscv_packed_simd.h")
        crt1 = internal(output(gcc, "-print-file-name=crt1.o"))
        libgcc = internal(output(gcc, "-print-libgcc-file-name"))
        libc = internal(sysroot / "usr/lib/libc.a")
        elf = output(programs["readelf"], "-h", crt1)
        if "ELF64" not in elf or "RISC-V" not in elf:
            raise RuntimeError("The startup object is not RV64")
        macros = output(gcc, "-march=rv64gc_p0p6", "-mabi=lp64d",
                        "-dM", "-E", "-x", "c", "/dev/null")
        if not re.search(r"^#define __riscv_p 6000$", macros, re.M):
            raise RuntimeError("The frontend does not advertise P 0.6")
        observed["runtime"] = {"sysroot": str(sysroot), "crt1": str(crt1),
                               "libgcc": str(libgcc), "libc": str(libc)}
        for name, path in programs.items():
            version_args = ["--version"]
            if name == "cc1":
                version_args = ["-quiet", "-version", "/dev/null", "-o", "/dev/null"]
            # collect2 is an internal linker wrapper, not a user-facing driver.
            version = output(path, *version_args) if name != "collect2" else "internal helper"
            libraries = subprocess.run(["ldd", str(path)], text=True,
                                       capture_output=True, timeout=30)
            deps = libraries.stdout + libraries.stderr
            if "not found" in deps:
                errors.append(f"Missing host library for {name}: {deps}")
            observed[name] = {"path": str(path), "version": version,
                              "host_libraries": deps.strip()}
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    report = {"project": str(ROOT), "host": platform.platform(),
              "libc": platform.libc_ver(), "python": platform.python_version(),
              "tools": observed, "errors": errors, "pass": not errors}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    for error in errors:
        print("FAIL:", error, file=sys.stderr)
    if not errors:
        print("PASS: local RV64 GCC, Binutils, runtime and P QEMU")
        print(f"Host: {platform.platform()}, libc {platform.libc_ver()}")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
