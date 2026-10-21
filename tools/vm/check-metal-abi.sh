#!/usr/bin/env bash
# Run inside the macOS build VM. Compile/link only, then process-local ABI tests.
# Never install a bundle, initialise a GPU device, or call the real Apple lazy init.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == x86_64 ]] || {
  echo 'Richiede il guest macOS x86_64.' >&2; exit 1;
}
[[ "$(sw_vers -buildVersion)" == 25G83 ]] || {
  echo 'ABI supportata da questa verifica: soltanto 25G83.' >&2; exit 1;
}
SRC="$ROOT/cobalt64/tools/native/navi48metal"
VK="${N48_VK_HEADERS:-$ROOT/deps/mesa-darwin/include}"
OUT="$ROOT/validation/lazy-abi"
[[ -f "$VK/vulkan/vulkan.h" ]] || { echo "Header Vulkan assenti: $VK" >&2; exit 1; }
mkdir -p "$OUT"
clang -arch x86_64 -fobjc-arc -Wall -Wextra -Werror -framework Foundation \
  -framework Metal "$SRC/test-lazy-abi.m" -o "$OUT/test-lazy-abi"
for lazy in 0 1; do
  binary="$OUT/Navi48Metal-lazy$lazy.NOT-INSTALLED"
  clang -I"$VK" -arch x86_64 -mmacosx-version-min=12.0 -fobjc-arc -O2 \
    -Wall -Wextra -Werror -DN48_LAZY="$lazy" -DN48_9D=1 -I"$SRC" -bundle \
    -framework Foundation -framework Metal -framework IOKit -framework IOSurface \
    -o "$binary" "$SRC/Navi48Device.m" > "$OUT/compile-$lazy.log" 2>&1
  "$OUT/test-lazy-abi" "$binary" "$lazy" > "$OUT/test-$lazy.log" 2>&1
  cat "$OUT/test-$lazy.log"
done
