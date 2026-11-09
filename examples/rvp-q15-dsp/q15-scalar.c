/* SPDX-License-Identifier: MIT */
#include "q15.h"

static inline __attribute__ ((always_inline)) int64_t
dot_scalar (const int16_t *a, const int16_t *b, size_t count)
{
  int64_t sum = 0;

  for (size_t i = 0; i < count; ++i)
    {
      int32_t product = (int32_t) a[i] * (int32_t) b[i];
      sum += product;
    }
  return sum;
}

int64_t
q15_dot_scalar (const int16_t *a, const int16_t *b, size_t count)
{
  return dot_scalar (a, b, count);
}

void
q15_fir_scalar (const int16_t *state, const int16_t *h_rev,
                size_t taps, size_t outputs, int16_t *out)
{
  for (size_t n = 0; n < outputs; ++n)
    out[n] = q15_round_sat (dot_scalar (state + n, h_rev, taps));
}
