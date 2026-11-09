/* SPDX-License-Identifier: MIT */
#ifndef RVP_Q15_H
#define RVP_Q15_H

#include <stddef.h>
#include <stdint.h>

#define Q15_MAX_TERMS 65536u

/* Inputs are naturally aligned int16_t arrays, including in "unaligned"
   fixtures: only alignment to the packed 4/8-byte word is relaxed.  A P
   kernel built with Q15_HW_UNALIGNED=1 additionally requires hardware support
   for misaligned 4/8-byte loads.  Natural int16_t alignment is not enough to
   meet that target assumption; use the strict build on other targets.

   DOT: count <= Q15_MAX_TERMS; each input contains count samples.  An empty
   dot returns zero without accessing the pointers.  Full-range Q15 products
   are summed exactly in signed Q30: every prefix has magnitude <= 2^46.

   FIR: 1 <= taps <= Q15_MAX_TERMS.  For nonempty output, state contains
   outputs + taps - 1 samples and h_rev contains taps reversed coefficients.
   Their sizes and the sum outputs + taps - 1 must be representable in size_t.
   state is oldest-to-newest history followed by the new input samples;
   h_rev[k] = h[taps - 1 - k], where h[0] multiplies the newest sample.
   out must not overlap either input.  Empty output touches no pointers.
   Each complete Q30 sum is rounded once, ties away from zero, then clamped.
   These are bounded valid-input APIs; callers validate lengths/storage.  */
int64_t q15_dot_scalar (const int16_t *, const int16_t *, size_t);
int64_t q15_dot_p (const int16_t *, const int16_t *, size_t);
void q15_fir_scalar (const int16_t *, const int16_t *, size_t, size_t,
                     int16_t *);
void q15_fir_p (const int16_t *, const int16_t *, size_t, size_t, int16_t *);

/* Unsigned magnitude also handles INT64_MIN.  No signed negative shift or
   out-of-range signed conversion is needed, and constant shifts avoid an
   RV32 division helper inside the measured FIR kernel.  */
static inline __attribute__ ((always_inline)) int16_t
q15_round_sat (int64_t sum)
{
  uint64_t magnitude = sum < 0
                       ? UINT64_C (0) - (uint64_t) sum
                       : (uint64_t) sum;
  uint64_t rounded = (magnitude + UINT64_C (16384)) >> 15;

  if (sum < 0)
    {
      if (rounded >= UINT64_C (32768))
        return INT16_MIN;
      return (int16_t) -(int32_t) rounded;
    }
  if (rounded > INT16_MAX)
    return INT16_MAX;
  return (int16_t) rounded;
}

#endif
