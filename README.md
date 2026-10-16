# RVP-Example

RV64 P intrinsics for grayscale image block matching.

Compare scalar C with RV64 P intrinsics using SAD: the sum of absolute pixel
differences. Both kernels search for a matching 16×16 grayscale image block.

**P 0.6 is a draft. QEMU results are not hardware performance measurements.**

## Run

```bash
git clone https://github.com/pz9115/RVP-Example.git
cd RVP-Example
```

First build the P-enabled tools using [docs/BUILD.md](docs/BUILD.md).
Then run from the project root:

```bash
python3 scripts/check-host.py
bash scripts/present.sh
```

The scripts use local installations in `toolchain/` and `qemu/`. Binaries,
component source trees and generated results are not tracked by Git.

Tested host: **x86_64 Ubuntu 24.04.2 / glibc 2.39 under WSL**. Running requires
Bash, Make, Python 3.10+, coreutils and the shared libraries checked by
`check-host.py`. Other host versions are not validated.

Optional: open `RVP_Tutorial.ipynb` in Jupyter. The command-line demo does not
require Jupyter or an external image dataset.

## Results

Output is written to `build/present/`:

- `result.json`: correctness, code size and guest instruction counts.
- `demo.svg`: input images, matched blocks and search costs.
- `images/`: PGM inputs and all 289 search costs.
- `sad-p.dis`: generated P instructions.
- `benchmark.csv`: emulator timing samples, **not hardware speedup**.

Expected: **82,576 C checks pass**, all **289 image costs match** an independent
Python reference, and the recovered shift is **(5, -3)** with **SAD = 0**.

```bash
bash scripts/acceptance.sh  # O2, O3, Os and negative controls.
```

See [VALIDATION.md](VALIDATION.md) for the measured results.

## Intrinsic loop

```c
uint8x8_t av = __riscv_pld_u8x8 ((uint8_t *) (a + x));
uint8x8_t bv = __riscv_pld_u8x8 ((uint8_t *) (b + x));
sum += __riscv_pabdsumu_u8x8_u64 (av, bv);
```

One packed operation handles eight pixels. The full kernel handles alignment,
tails and row strides, with a 64-bit sum. Both kernels use the same compiler
and common flags, without LTO or automatic vectorization.

## Code and documentation

- [Example source and method](examples/rvp-image-sad/README.md)
- [Build instructions](docs/BUILD.md)
- [Demonstration outline](docs/DEMO_2_3_MIN.md)
- [Presentation slides](docs/RVP-Image-SAD.pptx) ([PDF](docs/RVP-Image-SAD.pdf))
- [Instruction-count chart](docs/images/sad-instruction-counts.png)
- [Tested tool versions](VERSION.json)

The toolchain configuration supports **RV64, C, static Linux programs**.
It does not supply RV32, C++, libstdc++, shared libgcc or thread-enabled libgcc.

## License

The example code, scripts and tutorial use the [MIT License](LICENSE).
Copied specifications and third-party components retain their own licenses;
see [licenses/NOTICE](licenses/NOTICE).
