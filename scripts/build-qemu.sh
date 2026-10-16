#!/bin/bash
# Build a minimal P-enabled RV64 Linux-user emulator.
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
source_root=${SOURCE_ROOT:-"$root/sources"}
build=${QEMU_BUILD_ROOT:-"${TMPDIR:-/tmp}/rvp-na-qemu-build-$UID"}
prefix=${QEMU_PREFIX:-"$root/qemu"}
jobs=${JOBS:-2}
[[ "$jobs" =~ ^[12]$ ]] || { echo 'JOBS must be 1 or 2' >&2; exit 2; }
test -f "$source_root/qemu/configure"
if test -e "$build"; then
  echo "Refusing existing build directory: $build" >&2
  exit 2
fi
ulimit -v 3145728
ulimit -c 0
mkdir -p "$build" "$prefix/bin"
prefix=$(cd "$prefix" && pwd -P)
source_root=$(cd "$source_root" && pwd -P)
cd "$build"
"$source_root/qemu/configure" --prefix="$prefix" \
  --target-list=riscv64-linux-user --without-default-features --enable-tcg \
  --enable-linux-user --disable-system --disable-rust --disable-docs \
  --disable-containers --disable-download --disable-plugins
ninja -j"$jobs" qemu-riscv64
install -m 755 qemu-riscv64 "$prefix/bin/qemu-riscv64"
strip --strip-debug "$prefix/bin/qemu-riscv64"
"$prefix/bin/qemu-riscv64" --version
