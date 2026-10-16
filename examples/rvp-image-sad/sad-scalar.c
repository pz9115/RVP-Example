/* Portable reference kernel.  Compile separately, without LTO.  */

#include "sad.h"

uint64_t
sad_scalar (const uint8_t *a, size_t a_stride, const uint8_t *b,
            size_t b_stride, size_t width, size_t height)
{
  uint64_t sum = 0;

  if (width == 0 || height == 0)
    return 0;

  for (size_t y = 0; y < height; ++y)
    for (size_t x = 0; x < width; ++x)
      {
        unsigned av = a[y * a_stride + x];
        unsigned bv = b[y * b_stride + x];
        sum += av >= bv ? av - bv : bv - av;
      }

  return sum;
}
