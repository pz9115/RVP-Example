# Build the tools

The demo needs P 0.6-enabled GCC, Binutils and QEMU. Unmodified release sources
with the same version numbers are not sufficient.

## Source layout

Prepare these directories under `sources/`, or set `SOURCE_ROOT` to an
existing source directory with the same layout:

```text
sources/
  binutils/              P-enabled Binutils source
  gcc/                   GCC source with the P intrinsic API
  glibc/                 glibc source
  qemu/                  P-enabled QEMU source, including required subprojects
  linux-headers/include/ Exported Linux UAPI headers
```

Source checkouts are local dependencies, not part of this repository.
`VERSION.json` lists the versions used for validation.

## Requirements

Host tools: GCC/G++, Make, flex, bison, texinfo, gawk, Python, Ninja and
pkg-config. Development libraries: GLib, GMP, MPFR, MPC, zlib and zstd.
QEMU's required subprojects and Python wheels must be present; its build
disables automatic downloads.

## Build and run

From the project root, using fresh build and install directories:

```bash
bash scripts/build-toolchain.sh
bash scripts/build-qemu.sh
python3 scripts/check-host.py
bash scripts/present.sh
```

Tools are installed in `toolchain/` and `qemu/`. The scripts use two jobs and
a 3 GiB per-process virtual-memory limit. Run them sequentially on a
memory-constrained host. Set `JOBS=1` for a single build job.

Set `SOURCE_ROOT=/path/to/sources` to use external source trees.
`BUILD_ROOT` and `QEMU_BUILD_ROOT` select fresh build directories; by default
they are under `/tmp`. `PREFIX` and `QEMU_PREFIX` change the install paths,
but the demo scripts expect installations under this project.

GCC uses a C-only configuration with RV64 libgcc and a glibc sysroot.
QEMU uses a minimal RV64 Linux-user configuration. Validation covers the
single-threaded static demo, not arbitrary dynamic or threaded programs.

## Use the tools

```bash
source env.sh
riscv64-unknown-linux-gnu-gcc -O3 -march=rv64gc_p0p6 -mabi=lp64d \
  -static program.c -o program
qemu-riscv64 -R 512M -cpu rv64,x-p=true,zmmul=true,zba=true,zbb=true ./program
```

The compiler defaults to RV64GC; enable P explicitly.
Sourcing `env.sh` also sets `RVP_EXAMPLE_ROOT`, used to locate the project
when starting the notebook from another directory.

## Run variants

```bash
OUT="$PWD/build/custom-O2" OPTFLAGS=-O2 bash scripts/present.sh
```

Unset external compiler search variables such as `GCC_EXEC_PREFIX`,
`COMPILER_PATH`, `LIBRARY_PATH` and `CPATH`. Use paths without whitespace.

## Notebook images

The notebook includes a saved PNG preview. To refresh it from validated output:

```bash
python3 scripts/update-notebook-images.py build/acceptance/O3
```

Refreshing requires ImageMagick. Viewing the notebook does not.
