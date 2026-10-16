#!/bin/bash
# Compatibility entry point for the project demo runner.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd -P)
root=$(cd -- "$here/../.." && pwd -P)
exec bash "$root/scripts/present.sh"
