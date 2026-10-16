# Source this file from Bash; no host installation is performed.
export RVP_NA_ROOT
RVP_NA_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
export PATH="$RVP_NA_ROOT/toolchain/bin:$RVP_NA_ROOT/qemu/bin:$PATH"
