/* Correctness tests, a deterministic block-matching demo and timing harness.
   Timing under QEMU describes the emulator, not P hardware performance.  */

#define _GNU_SOURCE
#include "sad.h"
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static uint32_t random_state = 0x12345678;
static volatile uint64_t result_sink;
static size_t checked_cases;

static void
fail (const char *message)
{
  fprintf (stderr, "FAIL: %s\n", message);
  exit (EXIT_FAILURE);
}

static void *
allocate (size_t size)
{
  void *p = malloc (size);
  if (p == NULL)
    fail ("allocation");
  return p;
}

static uint8_t
random_byte (void)
{
  random_state ^= random_state << 13;
  random_state ^= random_state >> 17;
  random_state ^= random_state << 5;
  return random_state >> 24;
}

static uint64_t
oracle (const uint8_t *a, size_t as, const uint8_t *b, size_t bs,
        size_t width, size_t height)
{
  uint64_t sum = 0;
  for (size_t y = 0; y < height; ++y)
    for (size_t x = 0; x < width; ++x)
      sum += abs ((int) a[y * as + x] - (int) b[y * bs + x]);
  return sum;
}

static void
check (const uint8_t *a, size_t as, const uint8_t *b, size_t bs,
       size_t width, size_t height, uint64_t expected)
{
  uint64_t scalar = sad_scalar (a, as, b, bs, width, height);
  uint64_t packed = sad_p (a, as, b, bs, width, height);
  if (scalar != expected || packed != expected)
    {
      fprintf (stderr, "case %zu: %zux%zu, strides %zu/%zu, "
               "expected %" PRIu64 ", scalar %" PRIu64 ", P %" PRIu64 "\n",
               checked_cases, width, height, as, bs, expected, scalar, packed);
      fail ("SAD mismatch");
    }
  ++checked_cases;
}

static void
test_correctness (void)
{
  uint8_t *a = allocate (4096);
  uint8_t *b = allocate (4096);
  const size_t heights[] = { 0, 1, 2, 7 };

  check (NULL, 0, NULL, 0, 0, 3, 0);
  check (NULL, 0, NULL, 0, 23, 0, 0);
  for (unsigned av = 0; av < 256; ++av)
    for (unsigned bv = 0; bv < 256; ++bv)
      {
        memset (a, av, 8);
        memset (b, bv, 8);
        check (a, 8, b, 8, 8, 1, 8 * abs ((int) av - (int) bv));
      }

  for (size_t lane = 0; lane < 8; ++lane)
    {
      memset (a, 0, 8);
      memset (b, 0, 8);
      b[lane] = 255;
      check (a, 8, b, 8, 8, 1, 255);
    }

  for (size_t i = 0; i < 4096; ++i)
    {
      a[i] = random_byte ();
      b[i] = random_byte ();
    }
  check (a, 64, a, 64, 64, 32, 0);
  for (size_t width = 0; width <= 65; ++width)
    for (size_t h = 0; h < sizeof heights / sizeof heights[0]; ++h)
      for (size_t ao = 0; ao < 8; ++ao)
        for (size_t bo = 0; bo < 8; ++bo)
          {
            size_t as = width + 8 + ao;
            size_t bs = width + 16 + bo;
            uint64_t expected = oracle (a + ao, as, b + bo, bs,
                                        width, heights[h]);
            check (a + ao, as, b + bo, bs, width, heights[h], expected);
          }

  /* Place the last byte immediately before an inaccessible page.  A packed
     load past the tail faults even if its extra lanes are later masked.  */
  long page_size = sysconf (_SC_PAGESIZE);
  if (page_size < 128)
    fail ("page size");
  size_t page = (size_t) page_size;
  uint8_t *guard = mmap (NULL, 2 * page, PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  if (guard == MAP_FAILED || mprotect (guard + page, page, PROT_NONE) != 0)
    fail ("guard page");
  for (size_t i = 0; i < page; ++i)
    guard[i] = random_byte ();
  for (size_t width = 0; width <= 65; ++width)
    {
      uint8_t *tail = guard + page - width;
      uint64_t expected = oracle (tail, width, b, width, width, 1);
      check (tail, width, b, width, width, 1, expected);
      check (b, width, tail, width, width, 1, expected);
    }
  if (munmap (guard, 2 * page) != 0)
    fail ("unmap");
  free (a);
  free (b);

  /* Exceed UINT32_MAX without overflowing the specified 64-bit result.  */
  size_t width = 1 << 20;
  size_t height = 17;
  a = allocate (width * height);
  b = allocate (width * height);
  memset (a, 0, width * height);
  memset (b, 255, width * height);
  check (a, width, b, width, width, height, UINT64_C (255) * width * height);
  free (a);
  free (b);
  printf ("{\"mode\":\"test\",\"cases\":%zu,\"failures\":0}\n", checked_cases);
}

static FILE *
open_output (const char *directory, const char *name)
{
  char path[4096];
  int length = snprintf (path, sizeof path, "%s/%s", directory, name);
  if (length < 0 || (size_t) length >= sizeof path)
    fail ("output path too long");
  FILE *file = fopen (path, "wb");
  if (file == NULL)
    {
      perror (path);
      fail ("open output (create the directory first)");
    }
  return file;
}

static void
write_pgm (const char *dir, const char *name, const uint8_t *pixels,
           size_t width, size_t height)
{
  FILE *file = open_output (dir, name);
  if (fprintf (file, "P5\n%zu %zu\n255\n", width, height) < 0
      || fwrite (pixels, 1, width * height, file) != width * height
      || fclose (file) != 0)
    fail ("write PGM");
}

static void
image_demo (const char *dir)
{
  enum { WIDTH = 96, HEIGHT = 80, BLOCK = 16, RADIUS = 8, GRID = 17 };
  uint8_t reference[WIDTH * HEIGHT];
  uint8_t shifted[WIDTH * HEIGHT];
  uint8_t heatmap[GRID * GRID];
  uint64_t best = UINT64_MAX;
  int best_dx = 0;
  int best_dy = 0;
  FILE *costs = open_output (dir, "costs.csv");

  for (int y = 0; y < HEIGHT; ++y)
    for (int x = 0; x < WIDTH; ++x)
      reference[y * WIDTH + x] = (x * 3 + y * 5 + random_byte () / 4) & 255;
  for (int y = 0; y < HEIGHT; ++y)
    for (int x = 0; x < WIDTH; ++x)
      {
        int sx = x - 5;
        int sy = y + 3;
        shifted[y * WIDTH + x] = (sx >= 0 && sx < WIDTH && sy < HEIGHT)
                                 ? reference[sy * WIDTH + sx] : 0;
      }

  fprintf (costs, "dx,dy,scalar_sad,p_sad\n");
  for (int dy = -RADIUS; dy <= RADIUS; ++dy)
    for (int dx = -RADIUS; dx <= RADIUS; ++dx)
      {
        const uint8_t *a = reference + 32 * WIDTH + 32;
        const uint8_t *b = shifted + (32 + dy) * WIDTH + 32 + dx;
        uint64_t scalar = sad_scalar (a, WIDTH, b, WIDTH, BLOCK, BLOCK);
        uint64_t packed = sad_p (a, WIDTH, b, WIDTH, BLOCK, BLOCK);
        if (scalar != packed)
          fail ("block-matching cost mismatch");
        fprintf (costs, "%d,%d,%" PRIu64 ",%" PRIu64 "\n",
                 dx, dy, scalar, packed);
        heatmap[(dy + RADIUS) * GRID + dx + RADIUS] = packed / (BLOCK * BLOCK);
        if (packed < best)
          {
            best = packed;
            best_dx = dx;
            best_dy = dy;
          }
      }
  if (ferror (costs) || fclose (costs) != 0)
    fail ("write costs");
  if (best != 0 || best_dx != 5 || best_dy != -3)
    fail ("known image displacement");
  write_pgm (dir, "reference.pgm", reference, WIDTH, HEIGHT);
  write_pgm (dir, "shifted.pgm", shifted, WIDTH, HEIGHT);
  write_pgm (dir, "cost-map.pgm", heatmap, GRID, GRID);
  printf ("{\"mode\":\"demo\",\"candidates\":289,\"dx\":%d,\"dy\":%d,"
          "\"sad\":%" PRIu64 ",\"all_costs_match\":true}\n",
          best_dx, best_dy, best);
}

static uint64_t
now_ns (void)
{
  struct timespec ts;
  if (clock_gettime (CLOCK_MONOTONIC, &ts) != 0)
    fail ("clock_gettime");
  return (uint64_t) ts.tv_sec * UINT64_C (1000000000) + ts.tv_nsec;
}

static uint64_t
measure (sad_fn fn, const uint8_t *a, size_t as, const uint8_t *b, size_t bs,
         size_t width, size_t height, size_t iterations, uint64_t *checksum)
{
  uint64_t sum = 0;
  uint64_t start = now_ns ();
  for (size_t i = 0; i < iterations; ++i)
    sum += fn (a, as, b, bs, width, height);
  uint64_t elapsed = now_ns () - start;
  result_sink = sum;
  *checksum = sum;
  return elapsed;
}

static void
benchmark (const char *environment)
{
  const size_t sizes[][2] = { { 16, 16 }, { 64, 64 }, { 1920, 1080 } };
  sad_fn functions[] = { sad_scalar, sad_p };
  const char *names[] = { "scalar", "p" };
  fprintf (stderr, "%s\n", strcmp (environment, "qemu") == 0
           ? "QEMU host timings: NOT hardware performance or a P speedup."
           : "Hardware timing: record CPU, clock, affinity and cache policy.");
  puts ("environment,kernel,width,height,a_stride,b_stride,a_offset,b_offset,"
        "sample,iterations,elapsed_ns,checksum");
  for (size_t c = 0; c < sizeof sizes / sizeof sizes[0]; ++c)
    for (size_t unaligned = 0; unaligned < 2; ++unaligned)
      {
        size_t width = sizes[c][0];
        size_t height = sizes[c][1];
        size_t as = width + 8;
        size_t bs = width + 16;
        uint8_t *a = allocate (as * height + 8);
        uint8_t *b = allocate (bs * height + 8);
        for (size_t i = 0; i < as * height + 8; ++i)
          a[i] = random_byte ();
        for (size_t i = 0; i < bs * height + 8; ++i)
          b[i] = random_byte ();
        const uint8_t *ar = a + unaligned;
        const uint8_t *br = b + 3 * unaligned;
        uint64_t expected = oracle (ar, as, br, bs, width, height);
        check (ar, as, br, bs, width, height, expected);
        uint64_t checksum;
        for (size_t f = 0; f < 2; ++f)
          measure (functions[f], ar, as, br, bs, width, height, 4, &checksum);

        size_t iterations = 1;
        while (measure (sad_scalar, ar, as, br, bs, width, height,
                        iterations, &checksum) < UINT64_C (20000000)
               && iterations < (1U << 24))
          iterations *= 2;

        /* Alternate execution order to reduce systematic first-run bias.  */
        for (unsigned sample = 0; sample < 9; ++sample)
          for (unsigned order = 0; order < 2; ++order)
            {
              unsigned f = (sample + order) & 1;
              uint64_t elapsed = measure (functions[f], ar, as, br, bs,
                                          width, height, iterations, &checksum);
              if (checksum != expected * iterations)
                fail ("benchmark checksum");
              printf ("%s,%s,%zu,%zu,%zu,%zu,%zu,%zu,%u,%zu,%" PRIu64
                      ",%" PRIu64 "\n", environment, names[f], width, height,
                      as, bs, unaligned, 3 * unaligned, sample, iterations,
                      elapsed, checksum);
            }
        free (a);
        free (b);
      }
}

/* Exactly one kernel call, for address-filtered instruction tracing.
   The input, strides and offsets match the 16x16 timing workload.  */
static void
trace_case (const char *kernel, const char *layout)
{
  uint8_t a[24 * 16 + 8] __attribute__ ((aligned (8)));
  uint8_t b[32 * 16 + 8] __attribute__ ((aligned (8)));
  size_t offset = strcmp (layout, "unaligned") == 0;
  for (size_t i = 0; i < sizeof a; ++i)
    a[i] = random_byte ();
  for (size_t i = 0; i < sizeof b; ++i)
    b[i] = random_byte ();
  uint64_t expected = oracle (a + offset, 24, b + 3 * offset, 32, 16, 16);
  sad_fn fn = strcmp (kernel, "scalar") == 0 ? sad_scalar : sad_p;
  uint64_t actual = fn (a + offset, 24, b + 3 * offset, 32, 16, 16);
  if (actual != expected)
    fail ("trace workload checksum");
  printf ("{\"mode\":\"trace\",\"kernel\":\"%s\",\"layout\":\"%s\","
          "\"width\":16,\"height\":16,\"sad\":%" PRIu64 "}\n",
          kernel, layout, actual);
}

int
main (int argc, char **argv)
{
  if (argc == 2 && strcmp (argv[1], "--test") == 0)
    test_correctness ();
  else if (argc == 3 && strcmp (argv[1], "--demo") == 0)
    image_demo (argv[2]);
  else if (argc == 3 && strcmp (argv[1], "--bench") == 0
           && (strcmp (argv[2], "qemu") == 0
               || strcmp (argv[2], "hardware") == 0))
    benchmark (argv[2]);
  else if (argc == 4 && strcmp (argv[1], "--trace") == 0
           && (strcmp (argv[2], "scalar") == 0 || strcmp (argv[2], "p") == 0)
           && (strcmp (argv[3], "aligned") == 0
               || strcmp (argv[3], "unaligned") == 0))
    trace_case (argv[2], argv[3]);
  else
    {
      fprintf (stderr, "Usage: %s --test | --demo DIRECTORY | "
               "--bench qemu|hardware | "
               "--trace scalar|p aligned|unaligned\n", argv[0]);
      return EXIT_FAILURE;
    }
  return EXIT_SUCCESS;
}
