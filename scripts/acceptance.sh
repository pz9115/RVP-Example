#!/bin/bash
set -euo pipefail
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
export XLEN=${XLEN:-32}
out=${OUT:-"$root/build/acceptance-rv$XLEN"}
mkdir -p "$out"
out=$(cd -- "$out" && pwd -P)
for alignment in hardware strict; do
  for opt in O2 O3 Os; do
    OUT="$out/$alignment/$opt" ALIGNMENT="$alignment" OPTFLAGS="-$opt" \
      bash "$root/scripts/present.sh" 2>&1 | tee "$out/$alignment-$opt.log"
    python3 "$root/scripts/negative-control.py" "$out/$alignment/$opt"
    python3 "$root/scripts/check-alignment.py" "$out/$alignment/$opt"
  done
done
printf 'PASS: RV%s hardware/strict, O2/O3/Os and negative controls\n' "$XLEN"
