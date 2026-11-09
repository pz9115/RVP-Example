# RVP-Example

RV32 and RV64 P intrinsics for grayscale image block matching.

Compare portable scalar C with packed-SIMD intrinsics using SAD: the sum of
absolute pixel differences. Both kernels search for a matching 16×16 block.

**P 0.6 is a draft. QEMU results are not hardware performance measurements.**

## Run

```bash
git clone https://github.com/pz9115/RVP-Example.git
cd RVP-Example
python3 scripts/check-host.py
bash scripts/present.sh
```

The default is **RV32 with hardware-supported unaligned loads**. Prebuilt
P-enabled GCC, Binutils, matching runtimes and QEMU are included for x86_64
Linux. The scripts use these local binaries; no toolchain build is required.

```bash
XLEN=32 ALIGNMENT=strict bash scripts/present.sh
XLEN=64 ALIGNMENT=hardware bash scripts/present.sh
XLEN=32 bash scripts/acceptance.sh
XLEN=64 bash scripts/acceptance.sh
```

Each acceptance run covers hardware and strict alignment at O2, O3 and Os,
plus negative controls. Use Bash, Make, Python 3.10+ and the host libraries
checked by `check-host.py`. The validated host is x86_64 Ubuntu 24.04.2,
glibc 2.39, under WSL. Other hosts are not validated.

Optional: open `RVP_Tutorial.ipynb` and select XLEN and alignment. Python
builds and displays the results; the DSP kernels are C intrinsic examples.

## Target configurations

| | RV32 | RV64 |
| --- | --- | --- |
| P kernel | RV32IMC + Zba/Zbb/P 0.6 | RV64GC + P 0.6 |
| Scalar kernel | RV32IMC + Zba/Zbb | RV64GC + Zba/Zbb |
| ABI | ILP32, soft float | LP64D |
| Linux runtime | RV32IMAC | RV64GC |
| Pixels per packed SAD | 4 | 8 |

P requires Zmmul, Zba and Zbb; M includes Zmmul. The RV32 Linux runtime needs A,
but the SAD kernel does not. The RV32 build does not require floating-point or
vector extensions. RV64 keeps its existing hard-float runtime; neither SAD
kernel uses floating-point or RVV instructions.

The `hardware` configuration permits direct unaligned word loads.
The `strict` configuration checks alignment and uses byte loads plus packing
when needed. Hardware support is an example target assumption, not a P
requirement. Both kernels use the same size-oriented tuning and common flags,
without LTO or automatic vectorization.

## C intrinsic loop

RV32 processes four pixels per operation:

```c
uint8x4_t av = __riscv_pld_u8x4 ((uint8_t *) (a + x));
uint8x4_t bv = __riscv_pld_u8x4 ((uint8_t *) (b + x));
sum += __riscv_pabdsumu_u8x4_u32 (av, bv);
```

The full kernel handles row strides and tails, and returns a 64-bit sum.
RV64 uses the corresponding eight-lane intrinsics.

## Results

Outputs are written to `build/rv32-hardware/` by default, or
`build/rv<XLEN>-<ALIGNMENT>/` for the selected configuration:

- `result.json`: checks, code size, static kernel frames and instruction counts.
- `build-config.json`: ISA, ABI, alignment policy and compiler options.
- `demo.svg` and `images/`: inputs, matched blocks and all 289 search costs.
- `sad-p.dis`: generated instructions.
- `benchmark.csv`: emulator timings, **not hardware speedup**.

Expected: **82,640 C checks pass**, all **289 image costs** match an independent
Python reference, and the recovered shift is **(5, -3)** with **SAD = 0**.
Aligned and unaligned measurements use identical logical pixels.

## Documentation

- [Example and measurement method](examples/rvp-image-sad/README.md)
- [Validation results](VALIDATION.md)
- [Build instructions](docs/BUILD.md)
- [Development plan](docs/RV32-PLAN.md)
- [Demonstration outline](docs/DEMO_2_3_MIN.md)
- [RV32 presentation slides](docs/RVP-Image-SAD-RV32.pptx) ([PDF](docs/RVP-Image-SAD-RV32.pdf))
- [RV32 instruction chart](docs/images/rv32-instruction-counts.svg)
- [Earlier RV64 slides](docs/RVP-Image-SAD.pptx) ([PDF](docs/RVP-Image-SAD.pdf))
- [Tool versions](VERSION.json)

The supplied toolchains support this C/static-Linux example. They do not
provide C++, libstdc++, shared libgcc or thread-enabled libgcc.

## License

The example code, scripts and tutorial use the [MIT License](LICENSE).
Third-party components retain their own licenses; see [licenses/NOTICE](licenses/NOTICE).
