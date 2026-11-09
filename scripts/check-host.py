#!/usr/bin/env python3
"""Check the selected local toolchain, ABI and emulator installation."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from demo_config import ROOT, configuration


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
    parser.add_argument("--xlen", type=int, choices=(32, 64),
                        default=int(os.environ.get("XLEN", "32")))
    args = parser.parse_args()
    config = configuration(args.xlen, "hardware")
    target = config["target"]
    bindir = ROOT / config["toolchain_directory"] / "bin"
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
    gcc = bindir / (target + "-gcc")
    try:
        if output(gcc, "-dumpmachine") != target:
            raise RuntimeError("Wrong compiler target")
        programs = {name: internal(output(gcc, "-print-prog-name=" + name))
                    for name in ("cc1", "collect2", "lto1", "as", "ld")}
        programs.update({name: internal(bindir / (target + "-" + name))
                         for name in ("gcc", "objdump", "nm", "size", "readelf")})
        programs["qemu"] = internal(ROOT / "qemu/bin" / f"qemu-riscv{args.xlen}")
        sysroot = internal(output(gcc, "-print-sysroot"))
        include = internal(output(gcc, "-print-file-name=include"))
        internal(include / "riscv_packed_simd.h")
        crt1 = internal(output(gcc, "-print-file-name=crt1.o"))
        libgcc = internal(output(gcc, "-print-libgcc-file-name"))
        libc = internal(sysroot / "usr/lib/libc.a")
        elf = output(programs["readelf"], "-h", crt1)
        if f"ELF{args.xlen}" not in elf or "RISC-V" not in elf:
            raise RuntimeError(f"The startup object is not RV{args.xlen}")
        expected_abi = "soft-float ABI" if args.xlen == 32 else "double-float ABI"
        if expected_abi not in elf:
            raise RuntimeError(f"Wrong runtime ABI: expected {expected_abi}")
        macros = output(gcc, "-march=" + config["kernel_arch"],
                        "-mabi=" + config["abi"],
                        "-dM", "-E", "-x", "c", "/dev/null")
        if not re.search(r"^#define __riscv_p 6000$", macros, re.M):
            raise RuntimeError("The frontend does not advertise P 0.6")
        if not re.search(rf"^#define __riscv_xlen {args.xlen}$", macros, re.M):
            raise RuntimeError("Wrong frontend XLEN")
        observed["runtime"] = {"sysroot": str(sysroot), "crt1": str(crt1),
                               "libgcc": str(libgcc), "libc": str(libc)}
        for name, path in programs.items():
            version_args = ["--version"]
            if name == "cc1":
                # Query the frontend without looking for target headers.
                version_args = ["-quiet", "-version", "-fpreprocessed",
                                "/dev/null", "-o", "/dev/null"]
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
    report = {"project": str(ROOT), "configuration": config,
              "host": platform.platform(),
              "libc": platform.libc_ver(), "python": platform.python_version(),
              "tools": observed, "errors": errors, "pass": not errors}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    for error in errors:
        print("FAIL:", error, file=sys.stderr)
    if not errors:
        print(f"PASS: local RV{args.xlen} GCC, Binutils, {config['abi']} runtime and P QEMU")
        print(f"Host: {platform.platform()}, libc {platform.libc_ver()}")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
