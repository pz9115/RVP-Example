/* Four (RV32) or eight (RV64) unsigned pixels per packed SAD instruction.  */

#include "sad.h"
#include <riscv_packed_simd.h>

#if (__riscv_xlen != 32 && __riscv_xlen != 64) || __riscv_p != 6000
#error "This example requires RV32 or RV64 P draft 0.6"
#endif

#ifndef SAD_HW_UNALIGNED
#define SAD_HW_UNALIGNED 0
#endif

#if SAD_HW_UNALIGNED != 0 && SAD_HW_UNALIGNED != 1
#error "SAD_HW_UNALIGNED must be 0 or 1"
#endif

#define SAD_PACKED_BYTES (__riscv_xlen / 8)

static inline __attribute__ ((always_inline)) uint64_t
sad_row_p (const uint8_t *a, const uint8_t *b, size_t width)
{
  uint64_t sum = 0;
  size_t x = 0;

  for (; width - x >= SAD_PACKED_BYTES; x += SAD_PACKED_BYTES)
    {
      /* The draft load API takes non-const pointers, but only reads them.
         It permits arbitrary alignment and reads exactly one packed word.  */
#if __riscv_xlen == 32
      uint8x4_t av = __riscv_pld_u8x4 ((uint8_t *) (a + x));
      uint8x4_t bv = __riscv_pld_u8x4 ((uint8_t *) (b + x));
      sum += __riscv_pabdsumu_u8x4_u32 (av, bv);
#else
      uint8x8_t av = __riscv_pld_u8x8 ((uint8_t *) (a + x));
      uint8x8_t bv = __riscv_pld_u8x8 ((uint8_t *) (b + x));
      sum += __riscv_pabdsumu_u8x8_u64 (av, bv);
#endif
    }

  for (; x < width; ++x)
    {
      unsigned av = a[x];
      unsigned bv = b[x];
      sum += av >= bv ? av - bv : bv - av;
    }

  return sum;
}

uint64_t
sad_p (const uint8_t *a, size_t a_stride, const uint8_t *b, size_t b_stride,
       size_t width, size_t height)
{
  uint64_t sum = 0;

  if (width == 0 || height == 0)
    return 0;

  for (size_t y = 0; y < height; ++y)
    {
      const uint8_t *ar = a + y * a_stride;
      const uint8_t *br = b + y * b_stride;

#if SAD_HW_UNALIGNED
      /* This configuration requires hardware-supported unaligned loads.
         The intrinsic does not impose a C pointer-alignment requirement.  */
      sum += sad_row_p (ar, br, width);
#else
      /* Give the compiler alignment information only after checking it.
         The other path remains valid on strict-alignment implementations.  */
      if ((((uintptr_t) ar | (uintptr_t) br) & (SAD_PACKED_BYTES - 1)) == 0)
        sum += sad_row_p (__builtin_assume_aligned (ar, SAD_PACKED_BYTES),
                          __builtin_assume_aligned (br, SAD_PACKED_BYTES),
                          width);
      else
        sum += sad_row_p (ar, br, width);
#endif
    }

  return sum;
}
