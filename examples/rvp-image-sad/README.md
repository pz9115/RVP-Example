# RV32 and RV64 P image SAD

Two C kernels compute unsigned 8-bit grayscale SAD. A 16×16 block search
compares all 289 offsets in `[-8, 8]²`. The input has a known shift of
`(5, -3)` and a best SAD of zero.

## Run

From the project root:

```bash
bash scripts/present.sh                         # RV32, hardware unaligned loads
XLEN=32 ALIGNMENT=strict bash scripts/present.sh
XLEN=64 ALIGNMENT=hardware bash scripts/present.sh
XLEN=32 bash scripts/acceptance.sh               # Both policies, O2/O3/Os
```

See [the project README](../../README.md) for local binary requirements.
The kernels are in `sad-scalar.c` and `sad-p.c`; `demo.c` contains the tests,
image search and timing harness. `sad.h` defines the buffer/result contract.

## Kernel

RV32 uses four byte lanes:

```c
uint8x4_t av = __riscv_pld_u8x4 ((uint8_t *) (a + x));
uint8x4_t bv = __riscv_pld_u8x4 ((uint8_t *) (b + x));
sum += __riscv_pabdsumu_u8x4_u32 (av, bv);
```

RV64 uses `uint8x8_t`, `__riscv_pld_u8x8` and
`__riscv_pabdsumu_u8x8_u64`. Scalar tails handle the remaining pixels.
Both implementations return a 64-bit sum; the tests include a sum above
`UINT32_MAX`. The casts match the draft load API; inputs are not modified.

## Alignment and ISA

`ALIGNMENT=hardware` sets `SAD_HW_UNALIGNED=1` and uses native-width loads
without an alignment dispatch. It requires hardware-supported unaligned loads.
`ALIGNMENT=strict` checks alignment per row and uses safe byte loads and
packing for unaligned rows. Neither path reads beyond the requested pixels.

Both kernels use `-mtune=size`, with `-mno-strict-align` or `-mstrict-align`
respectively. This selects a compiler cost model, not a physical core.
The generated instructions are checked; permitting unaligned accesses alone
does not guarantee that every tuning model chooses wide loads.

RV32 kernels use ILP32 and RV32IMC with Zba/Zbb; P is enabled only for the
intrinsic kernel. The Linux harness/runtime also needs A. RV64 retains
RV64GC/LP64D. LTO and automatic vectorization are disabled. This is not an
RVV comparison or a comparison against a hand-optimized scalar implementation.

## Validation

- 82,640 C cases cover all byte pairs, lanes, offsets, row strides, tails,
  guard pages, empty images, large sums and identical layout data.
- Python independently recomputes all 289 costs from the PGM pixels.
- RV32 has seven additional 64-bit addition regression cases.
- P-disabled execution and corrupted-image checks are negative controls.
- A separate libc-free alignment probe tests the strict kernel with QEMU
  misaligned-access support disabled. The hardware path must fault in that
  configuration. This does not validate glibc on a strict-alignment CPU.

## Measurements

The same logical pixels are used for aligned and unaligned inputs, both
kernels and both architectures. The timing harness warms up and alternates
kernel order, recording nine samples for three image sizes and two layouts.
Allocation and data generation are outside the timed region.

`trace-count.py` uses one guest instruction per QEMU translation block,
disabled chaining and symbol-address filters. Two runs must match exactly.
A 16×16 P call executes 64 packed SAD instructions on RV32 or 32 on RV64.
Counts include kernel entry/exit and exclude the harness; they are not cycles,
hardware throughput or application speedup.

Reports include kernel text bytes and GCC's `-fstack-usage` static frames.
These are not the Linux runtime footprint or whole-program maximum stack.

For hardware measurements, first confirm compatible P encodings and alignment
support. Run correctness checks before measuring; record CPU, clock, caches,
memory and OS settings, retain raw samples, and report variability.
