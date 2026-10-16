# RV64 P image SAD

Two kernels compute unsigned 8-bit grayscale SAD: the sum of absolute pixel
differences. A 16×16 block search compares all 289 offsets in `[-8, 8]²`.
The synthetic input has a known shift of `(5, -3)` and a best SAD of zero.

## Run

From the project root:

```bash
bash scripts/present.sh
bash scripts/acceptance.sh
```

Results are written to `build/present/` and `build/acceptance/`.
See [the project README](../../README.md) for toolchain requirements.

## Files

| File | Role |
| --- | --- |
| `sad-scalar.c` | Portable scalar C baseline |
| `sad-p.c` | RV64 load and packed SAD intrinsics |
| `sad.h` | Kernel interface and buffer contract |
| `demo.c` | Correctness tests, image search and timing harness |
| `report.py` | Independent image oracle and result report |
| `trace-count.py` | Executed guest instruction counts |
| `Makefile` | Separate kernel compilation and static linking |

## Kernel behavior

```c
uint8x8_t av = __riscv_pld_u8x8 ((uint8_t *) (a + x));
uint8x8_t bv = __riscv_pld_u8x8 ((uint8_t *) (b + x));
sum += __riscv_pabdsumu_u8x8_u64 (av, bv);
```

Each packed operation processes eight pixels. A scalar tail handles the last
zero to seven pixels. The 64-bit accumulator avoids 32-bit image-sum overflow.
The casts match the draft load API; inputs are not modified.

Aligned rows use an alignment-checked fast path. Unaligned rows remain safe
under `-mstrict-align`, but require extra byte loads and packing. Width, stride
and accessible buffer sizes must satisfy the contract in `sad.h`.

Both kernels use the same GCC and common flags. Scalar uses `rv64gc_zba_zbb`;
P uses `rv64gc_p0p6`, which also enables Zba/Zbb. LTO and automatic vectorization
are disabled. No V extension is used. This is not an RVV comparison.

## Checks

- 82,576 C cases: every unsigned byte pair, lane limits, all alignment offsets,
  row strides, tails, guard-page boundaries and sums larger than `UINT32_MAX`.
- An independent Python reference recomputes all 289 costs from the PGM pixels.
- Assembly checks require packed SAD, aligned loads and P 0.6 ELF attributes.
- Negative controls disable P and alter an input pixel; both must fail.

Acceptance runs at `-O2`, `-O3` and `-Os`. Test results are in
[VALIDATION.md](../../VALIDATION.md).

## Measurements

The harness warms up, alternates kernel order and records nine samples for
each of three image sizes and two alignments. Raw samples are in
`benchmark.csv`. Allocation and I/O are outside the timed region.

`trace-count.py` uses one guest instruction per QEMU translation block,
disabled chaining and symbol-address filters. Two runs must have identical
counts and checksums. Counts cover one 16×16 kernel call, including return.
They are not cycles, hardware throughput or application speedup.

For hardware measurements, first confirm matching P 0.6 encodings. Run
`sad-demo --test`, then `sad-demo --bench hardware` on a pinned core. Record
CPU, clock, cache, memory and OS settings; retain raw samples and report their
spread. Use an end-to-end workload before claiming application speedup.
