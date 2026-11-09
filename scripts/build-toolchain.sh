#!/bin/bash
# Build a C demo toolchain from P-enabled source checkouts.
set -euo pipefail
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
source_root=${SOURCE_ROOT:-"$bundle/sources"}
xlen=${XLEN:-64}
case "$xlen" in
  32) arch=rv32imac; abi=ilp32; directory=toolchain-rv32;;
  64) arch=rv64gc; abi=lp64d; directory=toolchain;;
  *) echo 'XLEN must be 32 or 64' >&2; exit 2;;
esac
build_root=${BUILD_ROOT:-"${TMPDIR:-/tmp}/rvp-example-rv$xlen-build-$UID"}
prefix=${PREFIX:-"$bundle/$directory"}
jobs=${JOBS:-2}
target=riscv$xlen-unknown-linux-gnu
[[ "$jobs" =~ ^[1-4]$ ]] || { echo 'JOBS must be between 1 and 4' >&2; exit 2; }
ulimit -v 3145728
ulimit -c 0
export LC_ALL=C
export CFLAGS='-O2 -g0'
export CXXFLAGS='-O2 -g0'

for component in binutils gcc glibc; do
  test -f "$source_root/$component/configure"
  if test -d "$build_root/$component" \
    && test -n "$(ls -A "$build_root/$component")"; then
    echo "Refusing nonempty build directory: $build_root/$component" >&2
    exit 2
  fi
done
test -d "$source_root/linux-headers/include"
mkdir -p "$prefix" "$build_root" "$prefix/sysroot/usr/include"
prefix=$(cd "$prefix" && pwd -P)
source_root=$(cd "$source_root" && pwd -P)
build_root=$(cd "$build_root" && pwd -P)
gcc_source="$source_root/gcc"
if test "$xlen" = 32; then
  # Older demo sources incorrectly select a scalar RV64 add for RV32 DI
  # arithmetic.  Backport the existing fix only in a private source copy.
  fix="$bundle/patches/rv32-wide-add.patch"
  test -f "$fix"
  if patch --batch --forward --fuzz=0 --dry-run -p1 -d "$gcc_source" \
       < "$fix" >/dev/null 2>&1; then
    test ! -e "$build_root/sources/gcc"
    mkdir -p "$build_root/sources/gcc"
    cp -a --reflink=auto "$gcc_source/." "$build_root/sources/gcc/"
    gcc_source="$build_root/sources/gcc"
    patch --batch --forward --fuzz=0 -p1 -d "$gcc_source" < "$fix"
  elif ! patch --batch --reverse --fuzz=0 --dry-run -p1 -d "$gcc_source" \
       < "$fix" >/dev/null 2>&1; then
    echo 'Unrecognized GCC RV32 wide-add pattern; review the backport.' >&2
    exit 2
  fi
fi
export PATH="$prefix/bin:$PATH"
cp -a "$source_root/linux-headers/include/." "$prefix/sysroot/usr/include/"

mkdir "$build_root/binutils"
cd "$build_root/binutils"
"$source_root/binutils/configure" --target="$target" --prefix="$prefix" \
  --with-sysroot="$prefix/sysroot" --disable-multilib --disable-nls \
  --disable-werror --disable-gdb --disable-sim --disable-gprofng \
  --enable-plugins --with-system-zlib
make -j"$jobs" all-binutils all-gas all-ld
make install-binutils install-gas install-ld

mkdir "$build_root/gcc"
cd "$build_root/gcc"
"$gcc_source/configure" --target="$target" --prefix="$prefix" \
  --with-sysroot="$prefix/sysroot" --with-newlib --without-headers \
  --with-pkgversion='RVP-Example-P0.6' \
  --enable-languages=c,lto --enable-checking=release --disable-analyzer \
  --disable-multilib --disable-bootstrap --disable-shared --disable-threads \
  --enable-tls --disable-nls --disable-libatomic --disable-libssp \
  --disable-libquadmath --disable-libgomp --disable-libsanitizer \
  --disable-default-pie --with-arch="$arch" --with-abi="$abi" \
  --with-isa-spec=20191213 --with-system-zlib \
  --with-static-standard-libraries=yes
make -j"$jobs" inhibit-libc=true all-gcc
make inhibit-libc=true install-gcc
make -j"$jobs" inhibit-libc=true all-target-libgcc
make inhibit-libc=true install-target-libgcc

mkdir "$build_root/glibc"
cd "$build_root/glibc"
# The Linux runtime needs A.  The DSP kernel can use RV32IMC / ILP32.
CC="$prefix/bin/$target-gcc -march=$arch -mabi=$abi" \
  CXX=false BUILD_CC=/usr/bin/gcc CFLAGS='-O2 -g0' \
  "$source_root/glibc/configure" --host="$target" --prefix=/usr \
  --libdir=/usr/lib libc_cv_slibdir=/lib libc_cv_rtlddir=/lib \
  --disable-werror --enable-shared --disable-multilib \
  --with-headers="$source_root/linux-headers/include" --enable-kernel=5.4.0
make -j"$jobs"
make install install_root="$prefix/sysroot"

"$prefix/bin/$target-gcc" --version
test -f "$("$prefix/bin/$target-gcc" -print-file-name=include)/riscv_packed_simd.h"
test -f "$("$prefix/bin/$target-gcc" -print-libgcc-file-name)"
test -f "$("$prefix/bin/$target-gcc" -print-file-name=crt1.o)"
printf 'RV%s C/static-Linux demo toolchain ready: %s (%s, %s)\n' \
  "$xlen" "$prefix" "$arch" "$abi"
