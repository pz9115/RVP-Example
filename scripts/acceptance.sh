#!/bin/bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
out=${OUT:-"$root/build/acceptance"}
mkdir -p "$out"
out=$(cd -- "$out" && pwd -P)
for opt in O2 O3 Os; do
  OUT="$out/$opt" OPTFLAGS="-$opt" bash "$root/scripts/present.sh" \
    2>&1 | tee "$out/$opt.log"
done
python3 "$root/scripts/negative-control.py" "$out/O3"
printf 'PASS: O2, O3, Os and negative controls\n'
