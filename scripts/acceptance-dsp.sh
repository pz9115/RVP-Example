#!/bin/bash
# Check both Q15 kernels at O2/O3/Os under both load policies.
set -euo pipefail
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
xlen=${XLEN:-32}
case "$xlen" in
  32|64) ;;
  *) echo 'XLEN must be 32 or 64' >&2; exit 1 ;;
esac
base=${OUT_BASE:-"$root/build/acceptance-dsp-rv$xlen"}
for alignment in hardware strict; do
  for optimization in O2 O3 Os; do
    XLEN="$xlen" ALIGNMENT="$alignment" OPTFLAGS="-$optimization" \
      OUT="$base/$alignment/$optimization" bash "$root/scripts/dsp.sh"
  done
done
