/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "q15.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef int64_t (*dot_fn) (const int16_t *, const int16_t *, size_t);
typedef void (*fir_fn) (const int16_t *, const int16_t *, size_t, size_t,
                       int16_t *);

struct implementation
{
  const char *name;
  dot_fn dot;
  fir_fn fir;
};

static const struct implementation implementations[] = {
  { "scalar", q15_dot_scalar, q15_fir_scalar },
#ifndef Q15_SCALAR_ONLY
  { "p", q15_dot_p, q15_fir_p },
#endif
};
#define IMPLEMENTATIONS (sizeof implementations / sizeof implementations[0])
#define ARRAY_SIZE(a) (sizeof (a) / sizeof (a)[0])

static uint64_t cases;

static void
check (int condition, const char *what)
{
  ++cases;
  if (!condition)
    {
      fprintf (stderr, "Q15 failure at check %" PRIu64 ": %s\n", cases, what);
      exit (1);
    }
}

static uint32_t
random_u32 (uint32_t *state)
{
  *state ^= *state << 13;
  *state ^= *state >> 17;
  *state ^= *state << 5;
  return *state;
}

static int16_t
random_q15 (uint32_t *state)
{
  return (int16_t) ((int32_t) (random_u32 (state) & 65535u) - 32768);
}

/* Intentionally independent of q15_round_sat: signed division truncates
   toward zero; the signed remainder identifies either half-way case.  */
static int16_t
oracle_round (int64_t value)
{
  int64_t result = value / 32768;
  int64_t remainder = value % 32768;
  if (remainder >= 16384)
    ++result;
  else if (remainder <= -16384)
    --result;
  if (result > INT16_MAX)
    return INT16_MAX;
  if (result < INT16_MIN)
    return INT16_MIN;
  return (int16_t) result;
}

static int64_t
oracle_dot (const int16_t *a, const int16_t *b, size_t count)
{
  int64_t sum = 0;
  for (size_t i = 0; i < count; ++i)
    sum += (int64_t) a[i] * b[i];
  return sum;
}

/* Natural causal coefficients, not the kernels' reversed dot formulation.
   history[0] is x[-taps+1], and h[0] multiplies the current input sample.  */
static int64_t
oracle_fir (const int16_t *history, const int16_t *input,
            const int16_t *h, size_t taps, size_t n)
{
  int64_t sum = 0;
  for (size_t j = 0; j < taps; ++j)
    {
      int16_t sample = j <= n ? input[n - j]
                      : history[taps - 1 - (j - n)];
      sum += (int64_t) h[j] * sample;
    }
  return sum;
}

static void
reverse_coefficients (int16_t *reversed, const int16_t *h, size_t taps)
{
  for (size_t k = 0; k < taps; ++k)
    reversed[k] = h[taps - 1 - k];
}

static void
print_i16 (const int16_t *values, size_t count)
{
  putchar ('[');
  for (size_t i = 0; i < count; ++i)
    printf ("%s%d", i == 0 ? "" : ",", (int) values[i]);
  putchar (']');
}

static void
print_i64 (const int64_t *values, size_t count)
{
  putchar ('[');
  for (size_t i = 0; i < count; ++i)
    printf ("%s%" PRId64, i == 0 ? "" : ",", values[i]);
  putchar (']');
}

static void
test_rounding (void)
{
  static const int64_t values[] = {
    INT64_MIN, INT64_MAX, 0, 1, -1, 16383, -16383, 16384, -16384,
    16385, -16385, 49151, -49151, 49152, -49152,
    INT64_C (1073709056), INT64_C (1073725439), INT64_C (1073725440),
    -INT64_C (1073741824), -INT64_C (1073758207), -INT64_C (1073758208)
  };
  for (size_t i = 0; i < ARRAY_SIZE (values); ++i)
    check (q15_round_sat (values[i]) == oracle_round (values[i]), "round/clamp");
  check (q15_round_sat (16384) == 1, "positive tie away from zero");
  check (q15_round_sat (-16384) == -1, "negative tie away from zero");
  for (int64_t i = -65536; i <= 65536; i += 127)
    check (q15_round_sat (i) == oracle_round (i), "rounding neighborhood");
}

static void
check_dot (const int16_t *a, const int16_t *b, size_t count)
{
  int64_t expected = oracle_dot (a, b, count);
  for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
    check (implementations[k].dot (a, b, count) == expected,
           implementations[k].name);
}

static void
test_dot (void)
{
  static _Alignas (8) int16_t a[Q15_MAX_TERMS + 4];
  static _Alignas (8) int16_t b[Q15_MAX_TERMS + 4];
  static const int16_t edges[] = {
    INT16_MIN, -32767, -16384, -1, 0, 1, 16384, INT16_MAX
  };
  static const size_t lengths[] = { 31, 32, 33, 63, 64, 65, 255, 256, 257 };

  check_dot (NULL, NULL, 0);
  for (size_t count = 0; count <= 17; ++count)
    for (size_t ao = 0; ao < 4; ++ao)
      for (size_t bo = 0; bo < 4; ++bo)
        for (unsigned pattern = 0; pattern < 5; ++pattern)
          {
            uint32_t seed = 0x51a7u + (uint32_t) count;
            for (size_t i = 0; i < count; ++i)
              {
                a[ao + i] = pattern == 0 ? 0
                            : pattern == 1 ? INT16_MIN
                            : pattern == 2 ? INT16_MAX
                            : pattern == 3 ? edges[i % ARRAY_SIZE (edges)]
                            : random_q15 (&seed);
                b[bo + i] = pattern == 0 ? 0
                            : pattern == 1 ? INT16_MIN
                            : pattern == 2 ? INT16_MIN
                            : pattern == 3 ? edges[(i + 3) % ARRAY_SIZE (edges)]
                            : random_q15 (&seed);
              }
            check_dot (a + ao, b + bo, count);
          }

  for (size_t u = 0; u < ARRAY_SIZE (edges); ++u)
    for (size_t v = 0; v < ARRAY_SIZE (edges); ++v)
      for (size_t lane = 0; lane < 8; ++lane)
        {
          memset (a, 0, 8 * sizeof *a);
          memset (b, 0, 8 * sizeof *b);
          a[lane] = edges[u];
          b[lane] = edges[v];
          check_dot (a, b, 8);
        }

  for (size_t l = 0; l < ARRAY_SIZE (lengths); ++l)
    for (size_t ao = 0; ao < 4; ++ao)
      for (size_t bo = 0; bo < 4; ++bo)
        {
          uint32_t seed = 0x8912u;
          for (size_t i = 0; i < lengths[l]; ++i)
            {
              a[ao + i] = random_q15 (&seed);
              b[bo + i] = random_q15 (&seed);
            }
          check_dot (a + ao, b + bo, lengths[l]);
        }

  for (size_t i = 0; i < Q15_MAX_TERMS; ++i)
    a[i] = b[i] = INT16_MIN;
  for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
    {
      check (implementations[k].dot (a, b, 2) == INT64_C (2147483648),
             "two products exceed signed32");
      check (implementations[k].dot (a, b, 4) == INT64_C (4294967296),
             "four products exceed unsigned32");
      check (implementations[k].dot (a, b, Q15_MAX_TERMS)
             == INT64_C (70368744177664), "maximum positive Q30 sum");
      int16_t output;
      implementations[k].fir (a, b, Q15_MAX_TERMS, 1, &output);
      check (output == INT16_MAX, "maximum FIR tap count");
    }
  for (size_t i = 0; i < Q15_MAX_TERMS; ++i)
    b[i] = INT16_MAX;
  check_dot (a, b, Q15_MAX_TERMS);
  for (size_t i = 1; i < Q15_MAX_TERMS; i += 2)
    a[i] = INT16_MAX;
  check_dot (a, b, Q15_MAX_TERMS);

  const int16_t lane_a[] = { 1, 2, 3, 4 };
  const int16_t lane_b[] = { 7, 11, 13, 17 };
  for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
    check (implementations[k].dot (lane_a, lane_b, 4) == 136, "lane pairing");
}

static void
test_fir_case (size_t taps, size_t outputs, size_t so, size_t ho,
               unsigned pattern)
{
  if (taps == 0 || taps > 33 || outputs > 17 || so > 3 || ho > 3)
    {
      fputs ("Invalid internal FIR test dimensions\n", stderr);
      exit (1);
    }
  _Alignas (8) int16_t state_store[33 + 17 + 4];
  _Alignas (8) int16_t coeff_store[33 + 4];
  int16_t state_copy[ARRAY_SIZE (state_store)];
  int16_t coeff_copy[ARRAY_SIZE (coeff_store)];
  int16_t h[33], history[32], input[17], out[17 + 2];
  int16_t *state = state_store + so;
  int16_t *h_rev = coeff_store + ho;
  uint32_t seed = 0x7135u + (uint32_t) taps * 17u + (uint32_t) outputs;

  for (size_t i = 0; i < ARRAY_SIZE (state_store); ++i)
    state_store[i] = 12345;
  for (size_t i = 0; i < ARRAY_SIZE (coeff_store); ++i)
    coeff_store[i] = -12345;
  for (size_t i = 0; i < taps; ++i)
    h[i] = pattern == 0 ? 0 : pattern == 1 ? INT16_MIN
           : pattern == 2 ? (int16_t) ((i & 1) ? 137 : -257)
           : random_q15 (&seed);
  for (size_t i = 0; i + 1 < taps; ++i)
    history[i] = pattern == 0 ? 0 : pattern == 1 ? INT16_MIN
                 : random_q15 (&seed);
  for (size_t i = 0; i < outputs; ++i)
    input[i] = pattern == 0 ? 0 : pattern == 1 ? INT16_MIN
               : random_q15 (&seed);
  memcpy (state, history, (taps - 1) * sizeof *state);
  memcpy (state + taps - 1, input, outputs * sizeof *state);
  reverse_coefficients (h_rev, h, taps);
  memcpy (state_copy, state_store, sizeof state_store);
  memcpy (coeff_copy, coeff_store, sizeof coeff_store);

  for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
    {
      for (size_t i = 0; i < ARRAY_SIZE (out); ++i)
        out[i] = 23456;
      implementations[k].fir (state, h_rev, taps, outputs, out + 1);
      for (size_t n = 0; n < outputs; ++n)
        {
          int64_t raw = oracle_fir (history, input, h, taps, n);
          check (out[n + 1] == oracle_round (raw), "causal FIR output");
          check (implementations[k].dot (state + n, h_rev, taps) == raw,
                 "causal FIR raw sum before clipping");
        }
      check (out[0] == 23456 && out[outputs + 1] == 23456, "FIR output canary");
      check (memcmp (state_store, state_copy, sizeof state_store) == 0,
             "FIR state is read-only");
      check (memcmp (coeff_store, coeff_copy, sizeof coeff_store) == 0,
             "FIR coefficients are read-only");
    }
}

static void
test_streaming (void)
{
  const size_t chunks[] = { 1, 4, 3, 8, 7 };
  const int16_t h[7] = { 8192, -4096, 2048, 1024, -512, 256, 128 };
  int16_t history[6], input[23], state[29], h_rev[7];
  uint32_t seed = 0x9731u;
  for (size_t i = 0; i < ARRAY_SIZE (history); ++i)
    history[i] = random_q15 (&seed);
  for (size_t i = 0; i < ARRAY_SIZE (input); ++i)
    input[i] = random_q15 (&seed);
  memcpy (state, history, sizeof history);
  memcpy (state + 6, input, sizeof input);
  reverse_coefficients (h_rev, h, 7);

  for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
    {
      int16_t whole[23], chunked[23], rolling[6], block[6 + 8];
      implementations[k].fir (state, h_rev, 7, 23, whole);
      memcpy (rolling, history, sizeof rolling);
      size_t offset = 0;
      for (size_t c = 0; c < ARRAY_SIZE (chunks); ++c)
        {
          memcpy (block, rolling, sizeof rolling);
          memcpy (block + 6, input + offset, chunks[c] * sizeof *block);
          implementations[k].fir (block, h_rev, 7, chunks[c], chunked + offset);
          memcpy (rolling, block + chunks[c], sizeof rolling);
          offset += chunks[c];
        }
      check (offset == ARRAY_SIZE (input), "chunk partition");
      for (size_t n = 0; n < ARRAY_SIZE (input); ++n)
        {
          check (chunked[n] == whole[n], "chunked streaming equivalence");
          check (chunked[n] == oracle_round (oracle_fir (history, input, h, 7, n)),
                 "streaming causal oracle");
        }
    }
}

struct guarded
{
  void *mapping;
  size_t bytes;
  int16_t *data;
};

static struct guarded
guarded_samples (size_t count)
{
  long page_value = sysconf (_SC_PAGESIZE);
  check (page_value > 0, "page size");
  size_t page = (size_t) page_value;
  check (count * sizeof (int16_t) <= page, "guard fixture fits one page");
  void *mapping = mmap (NULL, 3 * page, PROT_NONE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  check (mapping != MAP_FAILED, "guard mmap");
  unsigned char *middle = (unsigned char *) mapping + page;
  check (mprotect (middle, page, PROT_READ | PROT_WRITE) == 0, "guard mprotect");
  return (struct guarded) { mapping, 3 * page,
                           (int16_t *) (middle + page - count * sizeof (int16_t)) };
}

static void
release_guard (struct guarded *buffer)
{
  check (munmap (buffer->mapping, buffer->bytes) == 0, "guard munmap");
}

static void
test_guards (void)
{
  for (size_t count = 0; count <= 17; ++count)
    {
      struct guarded a = guarded_samples (count);
      struct guarded b = guarded_samples (count);
      for (size_t i = 0; i < count; ++i)
        {
          a.data[i] = (int16_t) ((int) i * 173 - 1000);
          b.data[i] = (int16_t) ((int) i * 311 - 2000);
        }
      check_dot (a.data, b.data, count);
      release_guard (&a);
      release_guard (&b);
    }
  for (size_t taps = 1; taps <= 9; ++taps)
    for (size_t outputs = 0; outputs <= 5; ++outputs)
      {
        struct guarded state = guarded_samples (taps - 1 + outputs);
        struct guarded coeff = guarded_samples (taps);
        struct guarded out = guarded_samples (outputs);
        int16_t h[9];
        for (size_t i = 0; i < taps - 1 + outputs; ++i)
          state.data[i] = (int16_t) ((int) i * 97 - 512);
        for (size_t i = 0; i < taps; ++i)
          h[i] = (int16_t) ((int) i * 257 - 1024);
        reverse_coefficients (coeff.data, h, taps);
        for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
          {
            implementations[k].fir (state.data, coeff.data, taps, outputs, out.data);
            for (size_t n = 0; n < outputs; ++n)
              check (out.data[n] == oracle_round (oracle_fir (state.data,
                     state.data + taps - 1, h, taps, n)), "FIR guard-page tail");
          }
        release_guard (&state);
        release_guard (&coeff);
        release_guard (&out);
      }
}

static void
run_tests (void)
{
  const size_t taps[] = { 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33 };
  const size_t outputs[] = { 0, 1, 5, 17 };
  test_rounding ();
  test_dot ();
  for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
    {
      implementations[k].fir (NULL, NULL, 1, 0, NULL);
      check (1, "empty FIR does not access pointers");
    }
  for (size_t t = 0; t < ARRAY_SIZE (taps); ++t)
    for (size_t n = 0; n < ARRAY_SIZE (outputs); ++n)
      for (size_t so = 0; so < 4; ++so)
        for (size_t ho = 0; ho < 4; ++ho)
          for (unsigned pattern = 0; pattern < 4; ++pattern)
            test_fir_case (taps[t], outputs[n], so, ho, pattern);

  const int16_t h[] = { 16384, 8192, -4096 };
  const int16_t history[] = { 0, 0 };
  const int16_t input[] = { 8192, -16384, 24576, -8192, 0 };
  const int16_t expected[] = { 4096, -6144, 7168, 4096, -5120 };
  for (size_t n = 0; n < ARRAY_SIZE (input); ++n)
    check (oracle_round (oracle_fir (history, input, h, 3, n)) == expected[n],
           "independent FIR oracle golden fixture");
  test_streaming ();
  test_guards ();
  printf ("{\"cases\":%" PRIu64 ",\"failures\":0,\"implementations\":%zu,"
          "\"guard_pages\":true,\"max_terms\":%u}\n", cases,
          IMPLEMENTATIONS, Q15_MAX_TERMS);
}

#ifndef Q15_SCALAR_ONLY
static void
run_demo (void)
{
  int16_t a[17], b[17];
  const int16_t h[7] = { 8192, 6144, 4096, 2048, 1024, 512, 256 };
  const int16_t history[6] = { -8000, -6000, -3000, 1000, 2500, 4500 };
  int16_t input[64], state[70], h_rev[7], scalar[64], packed[64];
  int64_t raw[64];
  uint32_t seed = 0x12345678u;
  for (size_t i = 0; i < ARRAY_SIZE (a); ++i)
    {
      a[i] = random_q15 (&seed);
      b[i] = random_q15 (&seed);
    }
  for (size_t i = 0; i < ARRAY_SIZE (input); ++i)
    {
      int phase = (int) (i % 32);
      int triangle = phase < 16 ? phase : 32 - phase;
      int value = triangle * 1800 - 14400 + ((i & 1) ? -3500 : 3500);
      if (i == 20)
        value += 12000;
      if (i >= 40)
        value += 5000;
      input[i] = (int16_t) value;
      raw[i] = oracle_fir (history, input, h, 7, i);
    }
  memcpy (state, history, sizeof history);
  memcpy (state + 6, input, sizeof input);
  reverse_coefficients (h_rev, h, 7);
  q15_fir_scalar (state, h_rev, 7, 64, scalar);
  q15_fir_p (state, h_rev, 7, 64, packed);
  printf ("{\"dot\":{\"a\":");
  print_i16 (a, ARRAY_SIZE (a));
  printf (",\"b\":");
  print_i16 (b, ARRAY_SIZE (b));
  printf (",\"sum_scalar_q30\":%" PRId64 ",\"sum_p_q30\":%" PRId64 "},"
          "\"fir\":{\"coefficients\":", q15_dot_scalar (a, b, 17),
          q15_dot_p (a, b, 17));
  print_i16 (h, 7);
  printf (",\"history\":");
  print_i16 (history, 6);
  printf (",\"input\":");
  print_i16 (input, 64);
  printf (",\"scalar_q15\":");
  print_i16 (scalar, 64);
  printf (",\"p_q15\":");
  print_i16 (packed, 64);
  printf (",\"raw_q30\":");
  print_i64 (raw, 64);
  puts ("}}");
}
#endif

static void
run_trace (const char *workload, const struct implementation *impl,
           const char *layout)
{
  const size_t offset = strcmp (layout, "unaligned") == 0 ? 1 : 0;
  uint32_t seed = 0x51f15eedu;
  if (strcmp (workload, "dot") == 0)
    {
      _Alignas (8) int16_t a_store[1024 + 4], b_store[1024 + 4];
      int16_t *a = a_store + offset;
      int16_t *b = b_store + offset;
      for (size_t i = 0; i < 1024; ++i)
        {
          a[i] = random_q15 (&seed);
          b[i] = random_q15 (&seed);
        }
      /* Exactly one requested kernel call.  No P calls on the scalar path.  */
      int64_t sum = impl->dot (a, b, 1024);
      check (sum == oracle_dot (a, b, 1024), "trace dot oracle");
      printf ("{\"workload\":\"dot\",\"kernel\":\"%s\",\"layout\":\"%s\","
              "\"count\":1024,\"seed\":%" PRIu32 ",\"a\":", impl->name,
              layout, UINT32_C (0x51f15eed));
      print_i16 (a, 1024);
      printf (",\"b\":");
      print_i16 (b, 1024);
      printf (",\"sum_q30\":%" PRId64 ",\"q15\":%d,\"checksum\":%" PRId64 "}\n",
              sum, (int) q15_round_sat (sum), sum);
    }
  else
    {
      const size_t taps = 32, outputs = 64;
      _Alignas (8) int16_t state_store[31 + 64 + 4], coeff_store[32 + 4];
      int16_t *state = state_store + offset;
      int16_t *h_rev = coeff_store + offset;
      int16_t h[32], history[31], input[64], out[64];
      int64_t raw[64], checksum = 0;
      for (size_t i = 0; i < taps; ++i)
        h[i] = (int16_t) (random_q15 (&seed) / 16);
      for (size_t i = 0; i < taps - 1; ++i)
        history[i] = random_q15 (&seed);
      for (size_t i = 0; i < outputs; ++i)
        input[i] = random_q15 (&seed);
      memcpy (state, history, sizeof history);
      memcpy (state + taps - 1, input, sizeof input);
      reverse_coefficients (h_rev, h, taps);
      impl->fir (state, h_rev, taps, outputs, out);
      for (size_t n = 0; n < outputs; ++n)
        {
          raw[n] = oracle_fir (history, input, h, taps, n);
          check (out[n] == oracle_round (raw[n]), "trace FIR oracle");
          checksum += out[n];
        }
      printf ("{\"workload\":\"fir\",\"kernel\":\"%s\",\"layout\":\"%s\","
              "\"taps\":32,\"outputs\":64,\"seed\":%" PRIu32 ",\"coefficients\":",
              impl->name, layout, UINT32_C (0x51f15eed));
      print_i16 (h, taps);
      printf (",\"history\":");
      print_i16 (history, taps - 1);
      printf (",\"input\":");
      print_i16 (input, outputs);
      printf (",\"output_q15\":");
      print_i16 (out, outputs);
      printf (",\"raw_q30\":");
      print_i64 (raw, outputs);
      printf (",\"checksum\":%" PRId64 "}\n", checksum);
    }
}

int
main (int argc, char **argv)
{
  if (argc == 2 && strcmp (argv[1], "--test") == 0)
    {
      run_tests ();
      return 0;
    }
#ifndef Q15_SCALAR_ONLY
  if (argc == 2 && strcmp (argv[1], "--demo") == 0)
    {
      run_demo ();
      return 0;
    }
#endif
  if (argc == 5 && strcmp (argv[1], "--trace") == 0
      && (strcmp (argv[2], "dot") == 0 || strcmp (argv[2], "fir") == 0)
      && (strcmp (argv[4], "aligned") == 0 || strcmp (argv[4], "unaligned") == 0))
    for (size_t k = 0; k < IMPLEMENTATIONS; ++k)
      if (strcmp (argv[3], implementations[k].name) == 0)
        {
          run_trace (argv[2], &implementations[k], argv[4]);
          return 0;
        }
  fprintf (stderr, "Usage: %s --test | --demo | "
           "--trace dot|fir scalar|p aligned|unaligned\n", argv[0]);
  return 2;
}
