/* SPDX-License-Identifier: MIT
   Libc-free Linux-user probe for the same objects used by the measured demo.
   Inline assembly is only the Linux exit syscall, never the DSP kernel.  */
#include "../q15.h"

#ifndef DOT_KERNEL
#error "Define DOT_KERNEL as q15_dot_scalar or q15_dot_p"
#endif
#ifndef FIR_KERNEL
#error "Define FIR_KERNEL as q15_fir_scalar or q15_fir_p"
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
  _Alignas (8) int16_t a[24];
  _Alignas (8) int16_t b[24];
  int16_t out[7];
  for (unsigned i = 0; i < 24; ++i)
    {
      a[i] = (int16_t) ((int) i * 37 - 300);
      b[i] = (int16_t) ((int) i * 19 - 170);
    }

  if (DOT_KERNEL (NULL, NULL, 0) != 0)
    finish (1);
  FIR_KERNEL (NULL, NULL, 1, 0, NULL);

  /* 4 * 4 * 18 = 288 dot fixtures.  Offsets are samples, not bytes:
     all scalar halfword accesses remain naturally aligned.  */
  for (unsigned ao = 0; ao < 4; ++ao)
    for (unsigned bo = 0; bo < 4; ++bo)
      for (unsigned count = 0; count <= 17; ++count)
        {
          int32_t expected = 0;
          for (unsigned i = 0; i < count; ++i)
            expected += (int32_t) a[ao + i] * b[bo + i];
          if (DOT_KERNEL (a + ao, b + bo, count) != expected)
            finish (2);
        }

  /* 4 * 4 * 9 * 6 = 864 FIR fixtures, plus the two empty calls above:
     1,154 kernel calls total (289 dot, 865 FIR).  Small inputs keep the
     independent reference sum within signed32; no libgcc helpers are needed.
     b is the reversed layout passed to the kernel.  The oracle traverses
     natural causal taps: newest sample first, reversing b's index.  */
  for (unsigned ao = 0; ao < 4; ++ao)
    for (unsigned bo = 0; bo < 4; ++bo)
      for (unsigned taps = 1; taps <= 9; ++taps)
        for (unsigned outputs = 0; outputs <= 5; ++outputs)
          {
            for (unsigned i = 0; i < 7; ++i)
              out[i] = 23456;
            FIR_KERNEL (a + ao, b + bo, taps, outputs, out + 1);
            for (unsigned n = 0; n < outputs; ++n)
              {
                int32_t raw = 0;
                for (unsigned j = 0; j < taps; ++j)
                  raw += (int32_t) b[bo + taps - 1 - j]
                         * a[ao + n + taps - 1 - j];
                int32_t expected = raw < 0 ? -((-raw + 16384) / 32768)
                                   : (raw + 16384) / 32768;
                if (out[n + 1] != expected)
                  finish (3);
              }
            if (out[0] != 23456 || out[outputs + 1] != 23456)
              finish (4);
          }
  finish (0);
}
