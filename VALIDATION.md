# Validation

Revalidated on 2026-11-09 with the included x86_64 Linux binaries.
Host: Ubuntu 24.04.2, glibc 2.39, WSL2. Components: GCC 16.1.0,
Binutils 2.47, glibc 2.43 and QEMU 11.1.50, with P draft 0.6 support.

## Matrix and correctness

All **12 configurations** pass: RV32/RV64 × hardware/strict alignment ×
O2/O3/Os. Each configuration passes:

- **82,640 C checks**, including arbitrary offsets, row strides, tails,
  guard pages, empty images and a SAD exceeding `UINT32_MAX`.
- **289 independently recomputed image costs**; shift `(5, -3)`, SAD zero.
- Two identical instruction traces per kernel and input layout.
- Scalar execution with P disabled; packed execution fails with SIGILL.
- The image oracle rejects a corrupted input.

RV32 additionally passes seven 64-bit addition carry/high-word/wrap cases
per build. The bundled RV32 compiler includes `patches/rv32-wide-add.patch`:
an older backend incorrectly selected a 32-bit ADD for a 64-bit sum.
The fix is applied only to a private compiler source copy.

All RV32 runs disable F, D, V and Zfa in QEMU. The runtime uses RV32IMAC/ILP32;
the kernels need RV32IMC, Zba/Zbb and, for the intrinsic variant, P.
RV64 retains its RV64GC/LP64D runtime. Neither kernel uses FP or RVV instructions.

## Executed guest instructions

One 16×16 kernel call, including return. Aligned and unaligned inputs contain
the same logical pixels; every trace has SAD **22,364**.
Both kernels use `-mtune=size`, without LTO or automatic vectorization.

| Target | Policy | Optimization | Scalar, either layout | P aligned | P unaligned |
| --- | --- | --- | ---: | ---: | ---: |
| RV32 | Hardware | O2 / O3 | 2,955 | 717 | 717 |
| RV32 | Hardware | Os | 3,334 | 845 | 845 |
| RV32 | Strict | O2 / O3 | 2,955 | 850 | 1,954 |
| RV32 | Strict | Os | 3,334 | 879 | 1,999 |
| RV64 | Hardware | O2 / O3 | 2,189 | 438 | 438 |
| RV64 | Hardware | Os | 2,552 | 503 | 503 |
| RV64 | Strict | O2 / O3 | 2,189 | 565 | 1,877 |
| RV64 | Strict | Os | 2,552 | 503 | 1,911 |

Each P call executes 64 packed SAD instructions on RV32 or 32 on RV64.
Hardware-mode traces contain native word loads and no byte-load fallback.
Equal aligned/unaligned counts do not imply equal hardware memory latency.

**These are instruction counts, not cycles or speedup measurements.**
Emulator elapsed times remain diagnostic only.

## Kernel footprint

O2 and O3 give the same sizes and frames in this example.

| Target | Policy | Optimization | Scalar / P text bytes | Scalar / P static frame bytes |
| --- | --- | --- | ---: | ---: |
| RV32 | Hardware | O2 / O3 | 108 / 204 | 0 / 32 |
| RV32 | Hardware | Os | 102 / 132 | 16 / 16 |
| RV32 | Strict | O2 / O3 | 108 / 400 | 0 / 48 |
| RV32 | Strict | Os | 102 / 296 | 16 / 16 |
| RV64 | Hardware | O2 / O3 | 98 / 178 | 16 / 32 |
| RV64 | Hardware | Os | 92 / 114 | 16 / 0 |
| RV64 | Strict | O2 / O3 | 98 / 470 | 16 / 96 |
| RV64 | Strict | Os | 92 / 354 | 16 / 0 |

Frames come from GCC `-fstack-usage`. These measurements exclude the harness
and runtime and are not whole-program maximum stack usage.

## Alignment checks

A libc-free probe links the actual measured kernel objects. Each successful
run checks **1,602 cases**: widths 0–24, all input offsets 0–7 and empty images.

- Scalar passes with QEMU misaligned access support disabled.
- Both P variants pass with support enabled.
- Strict P passes with support disabled.
- Hardware-mode P raises the expected SIGBUS with support disabled.

This checks the kernel's contract, not the full glibc program on a
strict-trapping CPU. It does not establish hardware timing or atomicity.

## Tools and tutorial

- A fresh RV32 GCC/Binutils/libgcc/glibc toolchain and both QEMU user emulators
  build successfully.
- The RV32 toolchain passes relocated-prefix tests in an empty environment,
  with compiler helpers, target headers and target libraries resolving locally.
- The notebook's code cells pass headlessly for both architectures and both
  alignment policies; its saved image preview is from RV32 hardware mode.
  The interactive Jupyter UI is not validated.
- Invalid configuration, failed-build and timeout controls check that failed
  reruns do not retain an earlier success report.
- Eight runner tests and nine notebook-state tests pass. Notebook displays
  reject stale results after a failed run or a change of target, alignment,
  optimization or output directory.
- The six-slide RV32 PPTX passes ZIP, XML and relationship checks; every PDF
  page has been visually checked. The PDF uses the shared slide layout, not
  a PowerPoint/Impress round-trip. Both charts use the current matrix.

Reproduce with `XLEN=32 bash scripts/acceptance.sh` and `XLEN=64 bash
scripts/acceptance.sh`. Reports and traces are generated in
`build/acceptance-rv<XLEN>/<policy>/<optimization>/`.

## Earlier RV64 measurements

The October RV64 slides and chart use the earlier compiler tuning and input
layout. Their numbers are historical, not the current matrix. The current
tests use identical pixels across alignments; do not mix the two datasets.

Scope: this static, single-threaded C example, not all P instructions, other
host distributions, arbitrary applications or hardware performance.
