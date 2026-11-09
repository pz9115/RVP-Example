#!/bin/bash
# Build and validate the selected RV32 or RV64 image SAD demo.
set -euo pipefail
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
ulimit -v 3145728
ulimit -c 0
exec python3 "$root/scripts/run-demo.py"
