/* SPDX-License-Identifier: MIT */
#include "q15.h"
#include <riscv_packed_simd.h>

#if (__riscv_xlen != 32 && __riscv_xlen != 64) || __riscv_p != 6000
#error "This example requires RV32 or RV64 P draft 0.6"
#endif

#ifndef Q15_HW_UNALIGNED
#define Q15_HW_UNALIGNED 0
#endif
#if Q15_HW_UNALIGNED != 0 && Q15_HW_UNALIGNED != 1
#error "Q15_HW_UNALIGNED must be zero or one"
#endif

#define PACKED_BYTES (__riscv_xlen / 8)

static inline __attribute__ ((always_inline)) int64_t
dot_p_body (const int16_t *a, const int16_t *b, size_t count)
{
  int64_t sum = 0;
  size_t i = 0;

  /* The bundled load intrinsics use aligned(1), may_alias memory types.
     They only read despite the draft API's non-const pointer arguments.
     -mstrict-align splits loads when alignment is not proven.  */
#if __riscv_xlen == 32
  for (; count - i >= 2; i += 2)
    {
      int16x2_t av = __riscv_pld_i16x2 ((int16_t *) (a + i));
      int16x2_t bv = __riscv_pld_i16x2 ((int16_t *) (b + i));
      sum = __riscv_pm2wadda_i64 (sum, av, bv);
    }
#else
  for (; count - i >= 4; i += 4)
    {
      int16x4_t av = __riscv_pld_i16x4 ((int16_t *) (a + i));
      int16x4_t bv = __riscv_pld_i16x4 ((int16_t *) (b + i));
      sum = __riscv_pm4adda_i16x4 (sum, av, bv);
    }
#endif

  for (; i < count; ++i)
    {
      int32_t product = (int32_t) a[i] * (int32_t) b[i];
      sum += product;
    }
  return sum;
}

static inline __attribute__ ((always_inline)) int64_t
dot_p (const int16_t *a, const int16_t *b, size_t count)
{
#if !Q15_HW_UNALIGNED
  if ((((uintptr_t) a | (uintptr_t) b) & (PACKED_BYTES - 1)) == 0)
    return dot_p_body (__builtin_assume_aligned (a, PACKED_BYTES),
                       __builtin_assume_aligned (b, PACKED_BYTES), count);
#endif
  return dot_p_body (a, b, count);
}

int64_t
q15_dot_p (const int16_t *a, const int16_t *b, size_t count)
{
  return dot_p (a, b, count);
}

void
q15_fir_p (const int16_t *state, const int16_t *h_rev,
           size_t taps, size_t outputs, int16_t *out)
{
  for (size_t n = 0; n < outputs; ++n)
    out[n] = q15_round_sat (dot_p (state + n, h_rev, taps));
}
