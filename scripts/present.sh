#!/bin/bash
# Build and validate the RV64 image SAD demo using local tool installations.
set -euo pipefail
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
here="$root/examples/rvp-image-sad"
out=${OUT:-"$root/build/present"}
mkdir -p "$out/images"
out=$(cd -- "$out" && pwd -P)
case "$root:$out" in
  *[[:space:]]*) echo 'Use project/output paths without whitespace (Makefile limitation).' >&2; exit 2;;
esac
ulimit -v 3145728
ulimit -c 0
python3 "$root/scripts/check-host.py" --output "$out/host.json"
prefix="$root/toolchain/bin/riscv64-unknown-linux-gnu-"
gcc="${prefix}gcc"
qemu="$root/qemu/bin/qemu-riscv64"
make -C "$here" -j2 -B BUILD="$out" CC="$gcc" LINK_CC="$gcc" \
  OPTFLAGS="${OPTFLAGS:--O3}" ALIGNFLAGS="${ALIGNFLAGS:--mstrict-align}" \
  2>&1 | tee "$out/build.log"
"$gcc" -march=rv64gc_p0p6 -mabi=lp64d -dM -E -x c /dev/null > "$out/macros.txt"
for kernel in scalar p; do
  "${prefix}objdump" -dr "$out/sad-$kernel.o" > "$out/sad-$kernel.dis"
  "${prefix}size" -A "$out/sad-$kernel.o" > "$out/sad-$kernel.size"
done
"${prefix}readelf" -A "$out/sad-demo" > "$out/attributes.txt"
"${prefix}readelf" -h "$("$gcc" -print-file-name=crt1.o)" > "$out/runtime-startup-elf.txt"
"$gcc" -v > "$out/compiler-version.txt" 2>&1
cp "$out/compiler-version.txt" "$out/link-driver-version.txt"
"$("$gcc" -print-prog-name=cc1)" -quiet -version /dev/null -o /dev/null \
  > "$out/cc1-version.txt" 2>&1
"$qemu" --version > "$out/qemu-version.txt"
runner=("$qemu" -R 512M -cpu rv64,x-p=true,zmmul=true,zba=true,zbb=true)
"${runner[@]}" "$out/sad-demo" --test | tee "$out/tests.json"
"${runner[@]}" "$out/sad-demo" --demo "$out/images" | tee "$out/demo.json"
"${runner[@]}" "$out/sad-demo" --bench qemu \
  > "$out/benchmark.csv" 2> "$out/benchmark-note.txt"
python3 "$here/trace-count.py" "$out" --qemu "$qemu" \
  --binutils "$root/toolchain/bin" --binutils-prefix riscv64-unknown-linux-gnu-
python3 "$here/report.py" "$out" --versions "$root/VERSION.json"
python3 "$root/scripts/render-demo.py" "$out"
printf 'Results: %s/result.json\n' "$out"
