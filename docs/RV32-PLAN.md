# RV32 development plan

## Target

Provide the existing image block-matching example on RV32, while retaining
RV64. Add Q15 dot-product and FIR examples. Use P draft 0.6 and report
correctness, executed guest instructions, kernel text size and static stack usage.

The RV32 kernels target RV32IMC with Zba, Zbb and P, using ILP32. M includes
Zmmul, which P requires. The Linux test harness and glibc also require A;
their baseline is RV32IMAC / ILP32. No RV32 floating-point or vector extension
is required. RV64 retains its existing RV64GC / LP64D runtime.

## Stages

1. Port the SAD kernel.
   - Use four byte lanes on RV32 and eight on RV64.
   - Preserve arbitrary row strides, tails and the 64-bit result contract.
   - Keep boundary, guard-page and large-sum tests.
2. Make alignment and measurements explicit.
   - Provide hardware-unaligned and strict-alignment configurations.
   - Use identical logical pixels across layouts and implementations.
   - Use the same optimization and tuning settings for both kernels.
   - Record the actual load instructions, text size and stack usage.
3. Deliver a matching RV32 environment.
   - Build soft-float ILP32 GCC support libraries and glibc.
   - Include P-enabled RV32 QEMU and relocatable host binaries.
   - Check that compiler helpers, target headers and target libraries resolve locally.
4. Validate and document.
   - Run O2, O3 and Os on both XLENs and alignment configurations.
   - Verify all 289 image search costs against an independent oracle.
   - Require repeatable instruction traces and matching layout checksums.
   - Require P-disabled and corrupted-image negative controls to fail.
   - Update the English quick start, notebook and measured results.

## Alignment policy

Hardware-unaligned is the primary demonstration configuration. Strict mode
remains available for implementations without efficient misaligned accesses.

Use `-mtune=size` for both kernels and both alignment configurations. This
selects GCC's size-oriented cost model.
Together with `-mno-strict-align`, it permits direct word loads from the
unaligned intrinsic API. Verify the generated load instructions.

## Measurement

Report QEMU guest-instruction counts, kernel text size and static frames.
Hardware timing needs a compatible board or cycle model. Build the demo
toolchain separately from ongoing compiler optimization experiments.

## Status

- Planning and runtime ABI audit: complete.
- Kernel, measurement scripts and RV32 soft-float toolchain: complete.
- RV32 carry-loss compiler backport and regression: complete.
- All 12 architecture/alignment/optimization configurations: pass.
- Notebook, image preview and English documentation: updated.
- Six-slide RV32 image deck, PDF and editable chart: complete.
- Q15 dot/FIR kernels, independent references and alignment probes: complete.
- Q15 DSP: all 12 configurations pass, 110,597 C checks each; scalar-only
  host UBSan checks pass (56,324 checks).
- DSP notebook: four target/alignment configurations pass headlessly.
- DSP presentation material: three-page PPTX/PDF, editable FIR signal and
  instruction charts complete; all nine image/DSP slides visually checked.

## Delivery work: November 2026

- Fix relocated frontend version probing without weakening actual driver,
  header, link or runtime checks.
- Clear old success reports when a rerun fails, including invalid settings
  and a failure after report generation; cover this with host-only tests.
- Repeat the complete image-demo matrix with the included tools.
- Refresh the English PPT/PDF with RV32-first code and editable instruction
  count charts. Keep code size and stack tradeoffs visible.
- Commit validated changes locally in coherent groups.

## Additional DSP examples

Scope update, 2026-11-09: Q15 dot product and Q15 FIR are now required parts
of the current NA delivery goal, in addition to the image example.

Both examples will prioritize RV32 and retain RV64 support. Each must include
portable scalar C, a P-intrinsic implementation and an independent reference.
Use explicit accumulator bounds, rounding and saturation rules; do not rely
on signed overflow or silently change arithmetic between implementations.
Cover extrema, empty/short inputs, tails, alignment and overflow boundaries.

The dot-product example will demonstrate a basic fixed-point DSP operation.
The FIR example will demonstrate a complete finite-impulse-response filter
and show its input/output signal. Define coefficient order and history
handling clearly. Test signal and coefficient edge cases independently.

For each example, validate with the included RV32/RV64 tools, retain generated
assembly, and report guest instructions and kernel footprint. Update the
English quick start and presentation material, and make separate local
commits.
