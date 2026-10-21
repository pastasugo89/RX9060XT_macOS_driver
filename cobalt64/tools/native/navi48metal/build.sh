#!/bin/zsh
# Build Navi48Metal.bundle (x86_64, ad-hoc signed) into tools/native/navi48metal/build/.
#   build.sh            -> build/Navi48Metal.bundle (x86_64, for the PC) + arm64 compile/link sanity build (NOT shipped)
#   N48_LAZY=0 build.sh -> 9e variant (supportLazyInitialization not YES)
#   N48_9D=0  build.sh  -> without the 9d feature overrides
#   N48_SPVCACHE_DIR=<dir> build.sh -> take the spvcache pairs from <dir> (default: spvcache/ beside this script)
#   N48_ALLOW_EMPTY_SPVCACHE=1 build.sh -> allow an EMPTY spvcache (fallback-only bundle: WindowServer shows magenta until the daemon's translations hot-swap in)
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
# Work dir is OUTSIDE the repo: the repo lives in a file-provider folder that stamps com.apple.FinderInfo on
# *.bundle directories, which codesign --verify rejects ("detritus not allowed").  The shippable artefact is
# build/Navi48Metal.bundle.tar (bsdtar --no-xattrs); extract it on the PC.
B="$D/build"; W="$(mktemp -d "${TMPDIR:-/tmp}/navi48metal.XXXXXX")"; APP="$W/Navi48Metal.bundle"
LAZY="${N48_LAZY:-1}"; F9D="${N48_9D:-1}"
# Board (n48_asic.h): navi44 (RX 9060 XT, default) or navi48 (RX 9070 XT). Must match the kext (make ASIC=...) and the RADV
# shipped below (mesa-patches/0010: navi44 = default build, navi48 = built with -DRADV_DARWIN_NAVI48).
ASIC="${ASIC:-navi44}"
case "$ASIC" in navi44) ASIC_DEF="" ;; navi48) ASIC_DEF="-DN4X_ASIC_NAVI48" ;; *) echo "build.sh: ASIC must be navi44 or navi48" >&2; exit 1 ;; esac
RADV="${N48_RADV_LIB:-$HOME/navi48-native/mesa-mac/build-x86_64/src/amd/vulkan/libvulkan_radeon.dylib}"   # x86_64 RADV (10a: shipped in Resources)
[ -f "$RADV" ] || { echo "build.sh: RADV dylib not found: $RADV" >&2; exit 1; }
# Bundle 14: libn48xlate.dylib (x86_64), the LGPL in-process translator of the fork (NATIVE-S8-INPROC.md). N48_XLATE_LIB takes a prebuilt one; otherwise it is built from the fork
# (branch n48-inproc of ~/navi48-native/metal2vulkan, or N48_M2V_DIR) with `cargo build --release -p n48xlate --target x86_64-apple-darwin`.
XL="${N48_XLATE_LIB:-}"
if [ -z "$XL" ]; then
  M2V="${N48_M2V_DIR:-$HOME/navi48-native/metal2vulkan}"
  [ -f "$M2V/n48xlate/Cargo.toml" ] || { echo "build.sh: the fork with n48xlate is not at $M2V (set N48_M2V_DIR or N48_XLATE_LIB)" >&2; exit 1; }
  ( cd "$M2V" && PATH="/opt/homebrew/opt/rustup/bin:/opt/homebrew/bin:$PATH" MACOSX_DEPLOYMENT_TARGET=12.0 cargo build --release -p n48xlate --target x86_64-apple-darwin >&2 ) || { echo "build.sh: cargo build of n48xlate failed" >&2; exit 1; }
  XL="$M2V/target/x86_64-apple-darwin/release/libn48xlate.dylib"
fi
[ -f "$XL" ] || { echo "build.sh: libn48xlate.dylib not found: $XL" >&2; exit 1; }
[ "$(lipo -archs "$XL" 2>/dev/null)" = "x86_64" ] || { echo "build.sh: $XL is not a thin x86_64 library" >&2; exit 1; }
VKINC="${N48_VK_INC:--I/opt/homebrew/include}"
rm -rf "$B"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$B/sanity"
cp "$D/Info.plist" "$APP/Contents/Info.plist"
cp "$RADV" "$APP/Contents/Resources/libvulkan_radeon.dylib"
cp "$XL" "$APP/Contents/Resources/libn48xlate.dylib"
# 10d SPIR-V cache. N48_SPVCACHE_DIR: the .spv/.meta.json pairs (default: spvcache/ beside this script; the locally generated 25G83
# set lives outside the repo, research/ext/spvcache-25G83/spvcache). A PARTIAL cache is always packaged: every miss takes the fallback
# (WindowServer: magenta, compute no-op; the translation daemon's output hot-swaps in, n48_hotswap.h). An EMPTY cache is refused unless
# N48_ALLOW_EMPTY_SPVCACHE=1 is set on purpose. The glob is null-safe (zsh (N)): before, an absent spvcache/ stopped the build.
SPVC="${N48_SPVCACHE_DIR:-$D/spvcache}"
spvf=("$SPVC"/*.spv(N)); metaf=("$SPVC"/*.meta.json(N))
echo "spvcache: ${#spvf} .spv, ${#metaf} .meta.json from $SPVC"
if [ ${#spvf} -eq 0 ] && [ "${N48_ALLOW_EMPTY_SPVCACHE:-0}" != 1 ]; then
  echo "build.sh: no .spv in $SPVC (set N48_SPVCACHE_DIR, or N48_ALLOW_EMPTY_SPVCACHE=1 to package an empty cache on purpose)" >&2; exit 1
fi
[ ${#spvf} -eq ${#metaf} ] || echo "build.sh: WARNING: ${#spvf} .spv but ${#metaf} .meta.json (a kernel without its meta fails at dispatch)" >&2
mkdir -p "$APP/Contents/Resources/spvcache"; for f in "${spvf[@]}" "${metaf[@]}"; do cat "$f" > "$APP/Contents/Resources/spvcache/${f:t}"; done   # cat, not cp: cp(1) hung forever in lseek on spvcache/eee33f36...meta.json
clang $VKINC -arch x86_64 -mmacosx-version-min=12.0 -fobjc-arc -O2 -Wall -Wextra -Werror \
      -DN48_LAZY=$LAZY -DN48_9D=$F9D ${=ASIC_DEF} -I"$D" -bundle -framework Foundation -framework Metal -framework IOKit -framework IOSurface \
      -o "$APP/Contents/MacOS/Navi48Metal" "$D/Navi48Device.m"
xattr -cr "$APP"
codesign --force --sign - "$APP/Contents/Resources/libvulkan_radeon.dylib"
codesign --force --sign - "$APP/Contents/Resources/libn48xlate.dylib"
codesign --force --sign - "$APP"
# arm64 build of the same source: compile/link sanity only (there is no Rosetta here to load x86_64); never install it.
clang $VKINC -arch arm64 -fobjc-arc -O2 -Wall -Wextra -Werror -DN48_LAZY=$LAZY -DN48_9D=$F9D ${=ASIC_DEF} \
      -I"$D" -bundle -framework Foundation -framework Metal -framework IOKit -framework IOSurface -o "$B/sanity/Navi48Metal-arm64.NOT-SHIPPED" "$D/Navi48Device.m"
codesign --verify --strict -v "$APP"
tar --no-xattrs --no-mac-metadata -C "$W" -cf "$B/Navi48Metal.bundle.tar" Navi48Metal.bundle 2>/dev/null || \
  tar --no-xattrs -C "$W" -cf "$B/Navi48Metal.bundle.tar" Navi48Metal.bundle
file "$APP/Contents/MacOS/Navi48Metal"
echo "built (asic=$ASIC lazy=$LAZY 9d=$F9D): $APP  and  $B/Navi48Metal.bundle.tar ; install: see INSTALL.md"
