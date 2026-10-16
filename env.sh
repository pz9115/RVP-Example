# Source this file from Bash; no host installation is performed.
export RVP_EXAMPLE_ROOT
RVP_EXAMPLE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
export PATH="$RVP_EXAMPLE_ROOT/toolchain/bin:$RVP_EXAMPLE_ROOT/qemu/bin:$PATH"
