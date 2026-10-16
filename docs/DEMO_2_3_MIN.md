# RV64 P demonstration: 2–3 minutes

1. Start with a grayscale image and a shifted copy. Finding a matching 16×16
   block is a small, recognizable building block of motion estimation.
2. Show scalar SAD: add the absolute difference of corresponding pixels.
   Then show `examples/rvp-image-sad/sad-p.c`: load eight bytes and reduce their
   unsigned absolute differences with one P intrinsic operation.
3. Run `bash scripts/present.sh` in advance or live. Show the recovered shift
   `(5, -3)`, zero SAD, and agreement for all 289 candidate positions.
   `RVP_Tutorial.ipynb` visualizes the images and cost surface.
4. Show the generated `pabdsumu.b` / `pabdsumau.b` and aligned loads. Use
   `build/present/result.json` for measured guest instruction counts. Mention
   the unaligned fallback and scalar tails rather than showing only an ideal
   aligned case.
5. State the measurement limits: QEMU checks correctness and guest instruction
   counts. Hardware speedup requires a compatible board or cycle model.
