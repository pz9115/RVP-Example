/* A libc-free alignment probe for QEMU Linux-user.
   Inline assembly is used only for the Linux exit syscall, not the kernel.  */

#include "../sad.h"

#ifndef ALIGNMENT_KERNEL
#error "Define ALIGNMENT_KERNEL as sad_scalar or sad_p"
#endif

static __attribute__ ((noreturn)) void
finish (unsigned status)
{
  register unsigned result __asm__ ("a0") = status;
  register unsigned syscall __asm__ ("a7") = 93;
  __asm__ volatile ("ecall" : : "r" (result), "r" (syscall) : "memory");
  __builtin_unreachable ();
}

__attribute__ ((noreturn)) void
_start (void)
{
  uint8_t a[40] __attribute__ ((aligned (8)));
  uint8_t b[40] __attribute__ ((aligned (8)));
  for (unsigned i = 0; i < sizeof a; ++i)
    {
      a[i] = i * 11;
      b[i] = i * 7;
    }

  if (ALIGNMENT_KERNEL (NULL, 0, NULL, 0, 0, 1) != 0
      || ALIGNMENT_KERNEL (NULL, 0, NULL, 0, 24, 0) != 0)
    finish (1);

  /* Cover both native packed widths, scalar tails and all byte offsets.
     The maximum address accessed is 7 + 23, inside each buffer.  */
  for (unsigned ao = 0; ao < 8; ++ao)
    for (unsigned bo = 0; bo < 8; ++bo)
      for (unsigned width = 0; width <= 24; ++width)
        {
          uint64_t expected = 0;
          for (unsigned x = 0; x < width; ++x)
            {
              unsigned av = a[ao + x], bv = b[bo + x];
              expected += av >= bv ? av - bv : bv - av;
            }
          if (ALIGNMENT_KERNEL (a + ao, width, b + bo, width, width, 1)
              != expected)
            finish (2);
        }
  finish (0);
}
