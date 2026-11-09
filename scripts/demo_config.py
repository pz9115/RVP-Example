#!/usr/bin/env python3
"""Architecture and alignment settings shared by the demo tools."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configuration(xlen, alignment):
    if xlen not in (32, 64) or alignment not in ("hardware", "strict"):
        raise ValueError("Choose XLEN=32|64 and ALIGNMENT=hardware|strict")
    rv32 = xlen == 32
    return {
        "xlen": xlen,
        "abi": "ilp32" if rv32 else "lp64d",
        "alignment": alignment,
        "tune": "size",
        "kernel_arch": "rv32imcp0p6_zba_zbb" if rv32 else "rv64gc_p0p6",
        "baseline_arch": "rv32imc_zba_zbb" if rv32 else "rv64gc_zba_zbb",
        "runtime_arch": "rv32imac" if rv32 else "rv64gc",
        "runtime_abi": "ilp32" if rv32 else "lp64d",
        "target": f"riscv{xlen}-unknown-linux-gnu",
        "toolchain_directory": "toolchain-rv32" if rv32 else "toolchain",
        "qemu_cpu": (f"rv{xlen},x-p=true,zmmul=true,zba=true,zbb=true"
                     + (",f=false,d=false,v=false,zfa=false" if rv32 else "")),
    }
