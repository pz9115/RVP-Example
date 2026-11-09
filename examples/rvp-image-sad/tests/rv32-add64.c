/* Check RV32 P carry propagation across the halves of a uint64_t sum.
   An older P backend incorrectly selected ordinary ADD for DImode addition.
   Keep the operands unknown inside add64 so constant folding cannot hide it.  */

#include <stddef.h>
#include <stdint.h>

#if __riscv_xlen != 32 || __riscv_p != 6000
#error "This regression test requires RV32 P draft 0.6"
#endif

__attribute__ ((noinline, noclone)) uint64_t
add64 (uint64_t a, uint64_t b)
{
  return a + b;
}

int
main (void)
{
  static const uint64_t cases[][3] =
    {
      { UINT64_C (0xffffffff), 1, UINT64_C (0x100000000) },
      { UINT64_C (0x100000000), UINT64_C (0x200000000),
        UINT64_C (0x300000000) },
      { UINT64_MAX, 1, 0 },
      { UINT64_C (0xffffffff00000000), UINT64_C (0xffffffff), UINT64_MAX },
      { UINT64_C (0x12345678ffffffff), UINT64_C (0x1111111100000001),
        UINT64_C (0x2345678a00000000) },
      { UINT64_C (0x8000000000000000), UINT64_C (0x8000000000000000), 0 },
      { UINT64_C (0x80000000), UINT64_C (0x80000000), UINT64_C (0x100000000) }
    };

  for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i)
    if (add64 (cases[i][0], cases[i][1]) != cases[i][2])
      return 1;
  return 0;
}
