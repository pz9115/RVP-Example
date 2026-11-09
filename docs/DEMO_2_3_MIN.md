# Lightweight DSP in C: 2–3 minute presentation

## 1. Start with a familiar problem

"Finding the same image block in two frames is a useful building block for
motion estimation. We compare corresponding pixels and add their absolute
differences. The position with the lowest sum is our match."

Show the reference image, the shifted image and the SAD search map.
The example recovers a shift of **(+5, -3)** and verifies all **289** candidates.

## 2. Show the C intrinsic

"On RV32, one packed SAD operation handles four pixels. The code remains C:
load the pixels, calculate their differences and accumulate the result."

```c
uint8x4_t av = __riscv_pld_u8x4 ((uint8_t *) (a + x));
uint8x4_t bv = __riscv_pld_u8x4 ((uint8_t *) (b + x));
sum += __riscv_pabdsumu_u8x4_u32 (av, bv);
```

## 3. Extend the same idea to DSP

"We also have a Q15 dot product and a complete FIR example. A packed MAC
combines two signed 16-bit products into a 64-bit accumulator on RV32.
The FIR reuses that dot product over a sliding window."

```c
int16x2_t av = __riscv_pld_i16x2 ((int16_t *) (a + i));
int16x2_t bv = __riscv_pld_i16x2 ((int16_t *) (b + i));
sum = __riscv_pm2wadda_i64 (sum, av, bv);
```

Show the input and filtered signal. The seven-tap filter uses the same
coefficient order and rounding rule in scalar C and the intrinsic version.

## 4. Show the measured instruction reduction

"The RV32 image kernel goes from 2,955 to 717 instructions. For a 1,024-term
dot product, the count falls from 12,295 to 3,597. A 32-tap FIR producing
64 outputs goes from 27,985 to 8,536."

Use the labeled bars. The implementation also includes tests for sample
tails, coefficient order and streaming history.

## 5. Invite the audience to try it

"The repository includes the C examples, compiler and QEMU binaries, and
notebooks. The same workflow runs on RV32 and RV64."

```bash
bash scripts/present.sh
bash scripts/dsp.sh
```

Repository: [pz9115/RVP-Example](https://github.com/pz9115/RVP-Example).

Presenter note: the bars count guest instructions in QEMU at O3 with
hardware-supported misaligned loads; hardware timing has not been measured.
Target and arithmetic details are in the example READMEs.
