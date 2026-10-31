#!/bin/bash
# stage.sh - build the payload for Metal bundle 31 and its boot guard (guard edited from the LIVE guard).
# Runs WITHOUT root. Writes only under the git-ignored build dir (research/builds/macos-20261031/trial-b31).
# Installs nothing. Reads /Library only (read-only).
# Usage: ./stage.sh [PATH_TO_Navi48Metal.bundle]
set -euo pipefail
export LC_ALL=C
umask 022

[ "$(id -u)" -ne 0 ] || { echo "STOP: stage.sh must not run as root (install-trial.sh does the root part)"; exit 1; }

W=$(cd "$(dirname "$0")" && pwd)
PROJ=/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver
MAC=$PROJ/research/builds/macos-20261031
SRC=${1:-$MAC/bundle31b-src/build-31b/Navi48Metal.bundle}
OUT=$MAC/trial-b31
LIVE_BUNDLE=/Library/GPUBundles/Navi48Metal.bundle
LIVE_GUARD='/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'
TOOL=$W/lib/payload_tool.py
PY=/usr/bin/python3
OLD_VER=30
NEW_VER=31
OLD_PROFILE=stage30-vonly-v1
NEW_PROFILE=stage31-msaa-iosurface-v1
TS=$(date +%Y%m%d-%H%M%S)

die() { echo "STOP: $*" >&2; exit 1; }
step() { echo "== $*"; }
ptool() { "$PY" -I "$TOOL" "$@"; }

mkdir -p "$OUT"
TMPNEW=$(mktemp -d "$OUT/.payload-new.XXXXXX")
cleanup() { if [ -n "${TMPNEW:-}" ] && [ -d "$TMPNEW" ]; then rm -rf "$TMPNEW"; fi; }
trap cleanup EXIT

step "0 preconditions"
[ -f "$TOOL" ] || die "payload tool missing: $TOOL"
[ -d "$SRC" ] && [ ! -L "$SRC" ] || die "bundle missing or symlink: $SRC"
case "$SRC" in /Library/*) die "refusing to stage from the live GPU bundle path" ;; esac
for f in Contents/Info.plist Contents/MacOS/Navi48Metal Contents/Resources/libvulkan_radeon.dylib Contents/Resources/libn48xlate.dylib; do
  [ -f "$SRC/$f" ] || die "bundle lacks $f"
done
[ -d "$SRC/Contents/Resources/spvcache" ] || die "bundle lacks Resources/spvcache"
VER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SRC/Contents/Info.plist" 2>/dev/null || true)
[ "$VER" = "$NEW_VER" ] || die "CFBundleVersion is '$VER', expected $NEW_VER"
if [ -n "$(find "$SRC" -type f -mmin -2 -print -quit)" ]; then
  die "bundle files changed in the last 2 minutes (rebuild running?); retry later"
fi
busy=$(pgrep -f 'build-31' 2>/dev/null | grep -v -x -e "$$" || true)
[ -z "$busy" ] || die "a process mentioning build-31 is running (pids: $(echo $busy)); wait for the build to finish"

# Read-only: the live bundle must be the bundle-30 install that the live guard describes.
[ -d "$LIVE_BUNDLE" ] && [ ! -L "$LIVE_BUNDLE" ] || die "live bundle missing: $LIVE_BUNDLE"
LIVEVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE_BUNDLE/Contents/Info.plist" 2>/dev/null || true)
[ "$LIVEVER" = "$OLD_VER" ] || die "live bundle is version '$LIVEVER', expected $OLD_VER"
[ -f "$LIVE_GUARD" ] && [ ! -L "$LIVE_GUARD" ] || die "live guard missing: $LIVE_GUARD"
grep -Fxq "PROFILE=$OLD_PROFILE" "$LIVE_GUARD" || die "live guard is not the $OLD_PROFILE guard"
ptool guard-check "$LIVE_GUARD" "$LIVE_BUNDLE" "$OLD_VER" || die "live guard constants do not match the live bundle"

step "1 snapshot source tree"
ptool tree "$SRC" > "$TMPNEW/src-before.json"

step "2 copy with ditto and compare"
mkdir "$TMPNEW/payload"
ditto "$SRC" "$TMPNEW/payload/Navi48Metal.bundle"
ptool tree "$SRC" > "$TMPNEW/src-after.json"
ptool compare "$TMPNEW/src-before.json" "$TMPNEW/src-after.json" || die "source changed during copy"
ptool tree "$TMPNEW/payload/Navi48Metal.bundle" > "$TMPNEW/copy.json"
ptool compare "$TMPNEW/src-before.json" "$TMPNEW/copy.json" || die "copy differs from source"

step "3 signature and version of the copy"
codesign --verify --deep --strict "$TMPNEW/payload/Navi48Metal.bundle" || die "codesign --verify --deep --strict failed"
CV=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$TMPNEW/payload/Navi48Metal.bundle/Contents/Info.plist")
[ "$CV" = "$NEW_VER" ] || die "copy CFBundleVersion is '$CV'"

step "4 guard: copy the LIVE guard, edit only the three allowed lines in the copy"
cp "$LIVE_GUARD" "$TMPNEW/live-guard.sh"
LIVE_GUARD_SHA=$(ptool hash "$TMPNEW/live-guard.sh")
ptool edit-guard "$TMPNEW/live-guard.sh" "$TMPNEW/payload/Navi48Metal.bundle" \
  "$TMPNEW/payload/accelerated-reboot-trial.sh" "$TMPNEW/GUARD.diff" \
  "$OLD_PROFILE" "$NEW_PROFILE" "$OLD_VER" "$NEW_VER" || die "guard edit refused (see above)"
chmod 755 "$TMPNEW/payload/accelerated-reboot-trial.sh"
bash -n "$TMPNEW/payload/accelerated-reboot-trial.sh" || die "guard fails bash -n"
ptool guard-check "$TMPNEW/payload/accelerated-reboot-trial.sh" "$TMPNEW/payload/Navi48Metal.bundle" "$NEW_VER"
grep -Fxq "PROFILE=$NEW_PROFILE" "$TMPNEW/payload/accelerated-reboot-trial.sh" || die "new guard profile wrong"

step "5 manifest over the whole payload"
ptool manifest "$TMPNEW/payload/manifest.json" "$TMPNEW/payload" "$NEW_PROFILE" "$SRC" "$LIVE_GUARD_SHA"

step "6 publish to $OUT/payload"
mv -f "$TMPNEW/GUARD.diff" "$OUT/GUARD.diff"
if [ -e "$OUT/payload" ]; then
  mv "$OUT/payload" "$OUT/payload.prev-$TS"
  echo "previous payload kept as $OUT/payload.prev-$TS"
fi
mv "$TMPNEW/payload" "$OUT/payload"
ptool check "$OUT/payload/manifest.json" "" "$OUT/payload"

echo
echo "STAGED OK (not installed)"
echo "  payload:          $OUT/payload"
echo "  guard diff:       $OUT/GUARD.diff"
echo "  live guard sha:   $LIVE_GUARD_SHA (recorded in manifest; install refuses if it changed)"
echo "  Navi48Metal main: $(ptool hash "$OUT/payload/Navi48Metal.bundle/Contents/MacOS/Navi48Metal")"
echo "  libvulkan_radeon: $(ptool hash "$OUT/payload/Navi48Metal.bundle/Contents/Resources/libvulkan_radeon.dylib")"
echo "  libn48xlate:      $(ptool hash "$OUT/payload/Navi48Metal.bundle/Contents/Resources/libn48xlate.dylib")"
echo "  guard:            $(ptool hash "$OUT/payload/accelerated-reboot-trial.sh")"
echo "Next: cd $W && sudo ./install-trial.sh"
