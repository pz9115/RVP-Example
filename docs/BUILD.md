# Build the tools

Prebuilt tools are included for x86_64 Linux. Building is optional; the normal
runner uses the binaries in `toolchain-rv32/`, `toolchain/` and `qemu/`.

Unmodified release sources with the same version numbers are not sufficient:
GCC, Binutils and QEMU must include the P draft 0.6 implementation.

## Sources

Prepare this layout, or set `SOURCE_ROOT` to an equivalent directory:

```text
sources/
  binutils/
  gcc/
  glibc/
  qemu/                  Including required subprojects
  linux-headers/include/ Exported Linux UAPI headers
```

Sources are local dependencies, not tracked in this example repository.
See `VERSION.json` for the validated component versions.

The older demo GCC snapshot has an RV32 64-bit addition selection bug.
For RV32 builds, the recipe applies `patches/rv32-wide-add.patch` to a private
source copy under the build directory. Original sources are not modified.
An already-applied fix is accepted; an unexpected pattern stops the build.
The standalone carry regression and large-image SAD test cover this fix.

## Build

Host tools: GCC/G++, Make, patch, flex, bison, texinfo, gawk, Python, Ninja and
pkg-config. Development libraries: GLib, GMP, MPFR, MPC, zlib and zstd.
QEMU subprojects and Python dependencies must already be available; automatic
downloads are disabled.

Use fresh build directories and intentionally selected installation paths:

```bash
XLEN=32 bash scripts/build-toolchain.sh
XLEN=64 bash scripts/build-toolchain.sh
bash scripts/build-qemu.sh
```

RV32 installs to `toolchain-rv32/`: RV32IMAC, ILP32, no floating-point
extensions. RV64 installs to `toolchain/`: RV64GC, LP64D. Each includes a
matching libgcc and glibc sysroot. Do not mix RV32 ILP32 and ILP32D libraries.

QEMU builds both RV32 and RV64 Linux-user emulators. The scripts use two jobs
and a 3 GiB per-process address-space limit. Set `JOBS=1` on constrained hosts.
The toolchain recipe also permits `JOBS=3` or `JOBS=4`; use these only with
enough memory for concurrent compiler processes. The RV32 tools were built
with up to four jobs under the same per-process limit.
Build the components sequentially when memory is limited.

`BUILD_ROOT`, `QEMU_BUILD_ROOT`, `PREFIX` and `QEMU_PREFIX` select alternate
build/install paths. The demo runner expects the installation directories
listed above inside the project.

## Run variants

```bash
python3 scripts/check-host.py --xlen 32
XLEN=32 ALIGNMENT=hardware bash scripts/present.sh
XLEN=32 ALIGNMENT=strict bash scripts/present.sh
XLEN=64 ALIGNMENT=hardware bash scripts/present.sh
OUT="$PWD/build/custom-rv32-O2" XLEN=32 OPTFLAGS=-O2 bash scripts/present.sh
```

Use `ALIGNMENT=hardware|strict`, not a standalone `ALIGNFLAGS` override:
the compiler option and the C kernel's load path must agree. Both kernels use
the same `-mtune=size` cost model. This does not identify or model a real core.

Unset external compiler search variables such as `GCC_EXEC_PREFIX`,
`COMPILER_PATH`, `LIBRARY_PATH` and `CPATH`. Use paths without whitespace.

```bash
XLEN=32 bash scripts/acceptance.sh
XLEN=64 bash scripts/acceptance.sh
```

Each command covers O2/O3/Os and both alignment policies, with negative
controls and a libc-free alignment test. Programs are static and
single-threaded; arbitrary dynamic or threaded applications are not validated.

## Notebook images

To refresh the saved notebook preview from validated output:

```bash
python3 scripts/update-notebook-images.py build/rv32-hardware
```

Refreshing requires ImageMagick. Viewing the notebook does not.

## Presentation slides

Generate the current six-slide RV32 deck from a complete validation matrix:

```bash
XLEN=32 OUT="$PWD/build/slide-matrix/rv32" bash scripts/acceptance.sh
XLEN=64 OUT="$PWD/build/slide-matrix/rv64" bash scripts/acceptance.sh
/usr/bin/python3 scripts/build-slides.py --results build/slide-matrix \
  --output-dir build/slides
```

The default generator uses Python, Matplotlib and Pillow, and reuses the
earlier deck's master/theme. Text and bars in the new PPTX remain editable.
The PDF renders the same layout; it is not a PowerPoint/Impress round-trip.
Use `--check-only` to validate input reports without producing slides.
