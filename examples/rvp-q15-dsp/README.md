# Q15 dot product and FIR: RV32 first, RV64 compatible

Two portable scalar C kernels are compared with P 0.6 C intrinsic kernels:
an exact 64-bit Q15 dot product and a causal Q15 finite impulse response (FIR)
filter. The same sources support RV32 and RV64 with P draft 0.6.

## Run

From the repository root, use the bundled compiler, runtime and QEMU:

```bash
bash scripts/dsp.sh
XLEN=32 ALIGNMENT=strict bash scripts/dsp.sh
XLEN=64 ALIGNMENT=hardware bash scripts/dsp.sh
XLEN=64 ALIGNMENT=strict OPTFLAGS=-Os bash scripts/dsp.sh
```

The default runner configuration is RV32, hardware-supported unaligned
loads, and O3. `OPTFLAGS` also accepts `-O2` and `-Os`. The runner retains
build configuration, C test results, independent Python checks, raw QEMU
traces, disassembly, kernel text sizes/static stack frames, and `dsp.svg`
under `build/dsp-rv<XLEN>-<ALIGNMENT>/`. Set `OUT` to keep separate reports
for different optimization levels.

The executable's interfaces are:

```text
q15-demo --test
q15-demo --demo
q15-demo --trace dot scalar aligned
q15-demo --trace dot p unaligned
q15-demo --trace fir scalar aligned
q15-demo --trace fir p unaligned
```

Run the target executable through the matching P-enabled QEMU; the runner
supplies its CPU configuration. The trace mode makes exactly one requested
kernel call. A scalar trace does not invoke any P kernel, including during
reference calculations. All successful modes print JSON. Invalid arguments
return status 2, and failed checks return status 1.

For portable scalar-only host checking, without a RISC-V compiler:

```bash
make -C examples/rvp-q15-dsp host BUILD=/tmp/q15-host
/tmp/q15-host/q15-host-test --test
```

Host mode tests the scalar implementation. Guard-page tests require a
POSIX host with `mmap`, such as Linux.

## Arithmetic contract

`q15.h` describes bounded, valid-input APIs. Every sample and coefficient
is a signed 16-bit integer representing the real value `integer / 32768`.
The full `int16_t` range, including -32768, is supported.

For `0 <= count <= 65536`, the dot product returns the exact signed Q30 sum:

```text
S = sum(a[i] * b[i])
```

Each product has magnitude at most 2^30. Every partial sum therefore has
magnitude at most 2^46 and fits signed 64 bits. Scalar multiplication is
performed in signed 32 bits, where an individual product is representable,
before widening the addition. There is no signed overflow. Empty dots
return zero and may receive null pointers.

The FIR requires `1 <= taps <= 65536`; zero taps is not a valid filter.
An empty output accesses no pointers. For nonempty output, callers provide
`outputs + taps - 1` state samples, `taps` coefficients, and `outputs`
destination samples. Array sizes and their arithmetic must be representable
in `size_t`. Output must not overlap either input. The kernels do not
allocate storage or check these caller preconditions.

The dot result remains Q30. The FIR converts each completed sum to Q15
**once**, using nearest rounding with ties away from zero, then clamps to
[-32768, 32767]:

```text
magnitude = abs(S), calculated in unsigned 64-bit arithmetic
rounded_magnitude = (magnitude + 16384) >> 15
result = clamp(sign(S) * rounded_magnitude, -32768, 32767)
```

Thus +16384 Q30 becomes +1 Q15 and -16384 becomes -1. The helper handles
`INT64_MIN` without signed negation overflow and uses no negative signed
right shift. A separate division/remainder oracle checks the rule.

## Packed multiply-accumulate

RV32 consumes two signed halfwords per iteration:

```c
int16x2_t av = __riscv_pld_i16x2 ((int16_t *) (a + i));
int16x2_t bv = __riscv_pld_i16x2 ((int16_t *) (b + i));
sum = __riscv_pm2wadda_i64 (sum, av, bv);
```

The instruction computes `sum + a0*b0 + a1*b1`. Its 64-bit accumulator
occupies an even/odd GPR pair on RV32, with the low word in the even register.
RV64 uses four halfwords and `__riscv_pm4adda_i16x4`, accumulating into one
64-bit GPR. Ordinary scalar tails cover the remaining samples without
overreading either array.

These MACs do **not** saturate or round. The length contract prevents their
64-bit wraparound. In contrast, `__riscv_pwmacc_i32x2` has two independent
32-bit lane accumulators, not one 64-bit sum; it is not appropriate for
unrestricted repeated full-range Q15 MACs. Per-product Q-format rounding
intrinsics would also change the sum-then-round result.

The bundled header implements the selected load and arithmetic APIs. The
[intrinsic reference](../../docs/spec/P-ext-intrinsics.adoc) documents
`pm2wadda_i64` and `pm4adda_i16x4`. The runner checks the generated instructions.

## Causal FIR and history

The public mathematical definition uses natural causal coefficients:

```text
raw[n] = sum(h[j] * x[n-j], j = 0 .. taps-1)
```

`h[0]` multiplies the newest sample. To load increasing addresses in both
kernels, the driver prepares oldest-to-newest history followed by the input,
and reverses the coefficients once:

```text
state = [x[-taps+1], ..., x[-1], x[0], x[1], ...]
h_rev[k] = h[taps-1-k]
raw[n] = dot(state + n, h_rev, taps)
```

Both scalar and P kernels receive this same prepared layout. Coefficient
reversal and history preparation are outside the measured call. The C and
Python oracles use natural `h[j] * x[n-j]`, not the reversed dot formula,
so an accidental correlation or coefficient reversal is detectable.

The demonstration has seven asymmetric coefficients, six nonzero history
samples, and 64 inputs containing a triangular signal, alternating noise,
an impulse and a step. Exported `raw_q30` values are independent reference
sums, not an additional measured FIR return value. Tests separately compare
each kernel's raw dot window with the causal reference before clipping can
hide errors. Chunked processing is also compared with one-block filtering.

## Alignment

Public pointers refer to naturally two-byte-aligned `int16_t` arrays.
"Unaligned" means misaligned to the 4-byte RV32 or 8-byte RV64 packed word,
never an odd-address scalar pointer.

`ALIGNMENT=hardware` uses `-mno-strict-align` and requires target support
for misaligned packed-word loads. This is an explicit example target
assumption, not a requirement of P. `ALIGNMENT=strict` uses
`-mstrict-align`, checks packed alignment, and supplies alignment hints only
when justified. The bundled load intrinsics use `aligned(1), may_alias`
memory types, allowing the compiler to split loads safely when necessary.
No plain scalar-word pointer cast is used to access sample arrays.

Trace fixtures named `aligned` have **base-aligned buffers**. FIR window
`state + n` advances by two bytes per output: odd windows on RV32 and three
out of four windows on RV64 are packed-word-misaligned even in that fixture.
The `unaligned` fixture shifts both state and coefficient bases by one
sample. The shifted coefficient base keeps the strict fallback necessary
for every output. Both layouts contain identical logical data.

The libc-free `tests/alignment.c` probe exercises the actual kernel objects
with QEMU misaligned access disabled. It makes 1,154 kernel calls: 289 dot
calls and 865 FIR calls, including null-pointer empty cases. Offsets range
over 0, 1, 2 and 3 samples; dot lengths over 0..17; FIR taps over 1..9 and
output lengths over 0..5. The only inline assembly is the Linux exit syscall.

## Checks and measurement scope

The driver checks scalar and P independently against integer references.
It covers full-range extrema, all representative edge-value pairs in each
lane, deterministic random values, empty and short inputs, packed tails,
positive sums above signed32/unsigned32 limits, negative sums, and the
65,536-term bound. FIR tests vary input/history/coefficient values, lengths
and word alignment; check raw sums and final outputs; preserve input and
output canaries; and verify chunked streaming. Guard pages catch tail
overreads and output overwrites. Explicit half-way and clamp-boundary tests
check quantization, including negative ties.

JSON demo fixtures contain every input, natural coefficient and history
sample for independent Python recomputation. Trace fixtures similarly
expose their complete data: dot length 1,024, or 32 taps and 64 FIR outputs.
Both use unsigned xorshift32 seed `0x51f15eed`. Dot generation alternates
`a[i]` then `b[i]`; FIR generates natural coefficients first (Q15 random
values divided by 16 with truncation toward zero), then history, then input.
The checksum is the raw dot sum or the unweighted signed sum of FIR outputs;
the oracle checks all values, not only this checksum.

The runner counts executed guest instructions using QEMU one-instruction
translation blocks, disabled chaining, and kernel symbol-address filters.
It checks repeated traces and rejects out-of-line calls that would be lost
by such a filter. Dot counts include its raw accumulation and return; FIR
counts include all outputs, final rounding/clamping, and return. Input
generation, coefficient reversal, state preparation and checks are excluded.

The kernels use matching optimization, size-oriented tuning, alignment
policy, no LTO, and no automatic vectorization. RV32 uses ILP32 with
RV32IMC/Zba/Zbb, plus P only for the intrinsic object; its Linux runtime also
requires A. RV64 keeps LP64D/RV64GC. Neither kernel uses floating point or
RVV. Text bytes and static frames are reported for each kernel.

QEMU guest-instruction counts are not hardware timing.

The example code is MIT licensed; third-party compiler/specification
components retain their own licenses.
