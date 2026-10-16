# Validation

Tested on 2026-10-16: x86_64 Ubuntu 24.04.2, glibc 2.39, WSL2.
Tests use P-enabled builds of GCC 16.1.0, Binutils 2.47 and QEMU 11.1.50,
with glibc 2.43. Tested versions are listed in `VERSION.json`.

## Correctness

| Build | C checks | Independent image costs | Recovered shift |
| --- | ---: | ---: | --- |
| `-O2` | 82,576 passed | 289 matched | `(5, -3)`, SAD 0 |
| `-O3` | 82,576 passed | 289 matched | `(5, -3)`, SAD 0 |
| `-Os` | 82,576 passed | 289 matched | `(5, -3)`, SAD 0 |

All builds contain packed SAD instructions, aligned loads and P 0.6 ELF
attributes. The compiler defines `__riscv_p` as `6000`.

Negative controls passed: P-disabled execution raises `SIGILL`, and the
independent image checker rejects a modified input pixel.

## Generated code

Executed guest instructions for one 16×16 kernel call, including return:

| Build | Scalar aligned | P aligned | Scalar unaligned | P unaligned |
| --- | ---: | ---: | ---: | ---: |
| `-O2` | 2,527 | 571 | 2,524 | 1,899 |
| `-O3` | 2,527 | 571 | 2,524 | 1,899 |
| `-Os` | 2,551 | 503 | 2,554 | 1,911 |

Each P call executes 32 packed SAD instructions. Two trace runs per case
produce identical counts and checksums. Kernel text sizes are 78/450 bytes
(scalar/P) at O2 and O3, and 92/354 bytes at Os.

**These are instruction counts and code sizes, not hardware speedup.**
QEMU elapsed-time samples are diagnostic only. Hardware has not been measured.

## Tool and script checks

- GCC, Binutils, libgcc, glibc and QEMU build successfully.
- All three optimization variants and negative controls pass after relocation.
- Relocated runs use an empty environment, a temporary `HOME`, and
  `PATH=/usr/bin:/bin`.
- Compiler helpers, intrinsic headers, startup objects and runtime libraries
  resolve inside the relocated project. Include and linker traces contain no
  original installation paths. No external or broken toolchain symlinks remain.
- All notebook code cells execute headlessly; SVG output is checked.
  The interactive Jupyter UI has not been tested on this host.

Raw reports, object files, assembly, traces, images and timing samples are
generated under `build/acceptance/{O2,O3,Os}/`. Reported paths identify the build
location; they are not runtime dependencies.

Scope: the provided RV64 static C example. This does not certify all P
instructions, other host distributions, dynamic linking or threaded programs.
