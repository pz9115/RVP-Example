# RV32 P demonstration: 2–3 minutes

1. Start with a grayscale image and a shifted copy. Finding a matching 16×16
   block is a small, recognizable building block of motion estimation.
2. Show scalar SAD: add the absolute difference of corresponding pixels.
   Then show `examples/rvp-image-sad/sad-p.c`: RV32 loads four bytes and reduces
   their unsigned absolute differences with one packed SAD operation. The
   total is 64-bit. RV64 uses the same structure with eight-byte loads.
3. Run `XLEN=32 ALIGNMENT=hardware bash scripts/present.sh` in advance or live.
   Show the recovered shift
   `(5, -3)`, zero SAD, and agreement for all 289 candidate positions.
   `RVP_Tutorial.ipynb` visualizes the images and cost surface.
4. Show the generated `pabdsumu.b` / `pabdsumau.b` and `lw` instructions. Use
   the runner's `result.json` for guest instruction counts, kernel text size
   and static stack frames. Both input layouts contain identical pixels.
   `hardware` assumes supported unaligned loads; `ALIGNMENT=strict` selects
   a checked-alignment path with byte-load fallback. Both handle tails safely.
5. State the target and limits: the kernel uses RV32IMC, Zba, Zbb and P 0.6;
   the Linux runtime additionally requires A. Neither requires floating point
   or RVV. QEMU verifies correctness and guest instruction counts, not memory
   latency or hardware speedup. Those require a compatible board or cycle model.

Use `XLEN=64` for the RV64 counterpart. The notebook defaults to RV32 and lets
the presenter select both the target and alignment policy. Its C examples are
the algorithm; Python only builds, checks and displays the results.
