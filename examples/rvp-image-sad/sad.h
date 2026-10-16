/* RV64 P image-processing example: sum of absolute differences (SAD).  */

#ifndef RVP_IMAGE_SAD_H
#define RVP_IMAGE_SAD_H

#include <stddef.h>
#include <stdint.h>

/* Rows contain WIDTH bytes and have independent strides, at least WIDTH.
   Inputs may be unaligned.  Empty images are not accessed.  The caller must
   supply valid image buffers and ensure 255 * WIDTH * HEIGHT fits uint64_t.  */
typedef uint64_t (*sad_fn) (const uint8_t *, size_t, const uint8_t *, size_t,
                          size_t, size_t);

uint64_t sad_scalar (const uint8_t *, size_t, const uint8_t *, size_t,
                     size_t, size_t);
uint64_t sad_p (const uint8_t *, size_t, const uint8_t *, size_t,
                size_t, size_t);

#endif
