#!/bin/bash
# stage.sh - build the payload for the next Metal bundle (live N -> N+1) and its boot guard.
# The guard is a copy of the LIVE guard; only three lines of the copy change: PROFILE=, the
# bundle_version check (N -> N+1, message included) and the Contents/MacOS/Navi48Metal hash.
# Runs WITHOUT root. Writes only under the git-ignored build dir research/builds/macos-20261031/trial-b<N+1>.
# Installs nothing. Reads /Library only (read-only).
# Usage: ./stage.sh BUNDLE_PATH NEW_PROFILE
#   BUNDLE_PATH  Navi48Metal.bundle whose CFBundleVersion is N+1 (N = live bundle version). Required.
#   NEW_PROFILE  stage<N+1>-<name>, e.g. stage32-dualsrc-v1 for bundle 32. Required.
set -euo pipefail
export LC_ALL=C
umask 022

[ "$(id -u)" -ne 0 ] || { echo "STOP: stage.sh must not run as root (install-trial.sh does the root part)"; exit 1; }
[ "$#" -eq 2 ] || { echo "STOP: usage: ./stage.sh BUNDLE_PATH NEW_PROFILE   (NEW_PROFILE is required, e.g. stage32-dualsrc-v1)" >&2; exit 1; }

W=$(cd "$(dirname "$0")" && pwd)
PROJ=/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver
MAC=$PROJ/research/builds/macos-20261031
LIVE_BUNDLE=/Library/GPUBundles/Navi48Metal.bundle
LIVE_GUARD='/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'
TOOL=$W/lib/payload_tool.py
PY=/usr/bin/python3
NEW_PROFILE=$2
TS=$(date +%Y%m%d-%H%M%S)

die() { echo "STOP: $*" >&2; exit 1; }
step() { echo "== $*"; }
ptool() { "$PY" -I "$TOOL" "$@"; }

SRC_ARG=$1
[ -d "$(dirname "$SRC_ARG")" ] || die "no such directory: $(dirname "$SRC_ARG")"
SRC=$(cd "$(dirname "$SRC_ARG")" && pwd -P)/$(basename "$SRC_ARG")

step "0 preconditions (read-only)"
[ -f "$TOOL" ] || die "payload tool missing: $TOOL"
[ -d "$SRC" ] && [ ! -L "$SRC" ] || die "bundle missing or symlink: $SRC"
case "$SRC" in /Library/*) die "refusing to stage from the live GPU bundle path" ;; esac
[ -d "$LIVE_BUNDLE" ] && [ ! -L "$LIVE_BUNDLE" ] || die "live bundle missing: $LIVE_BUNDLE"
[ -f "$LIVE_GUARD" ] && [ ! -L "$LIVE_GUARD" ] || die "live guard missing: $LIVE_GUARD"
OLD_VER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE_BUNDLE/Contents/Info.plist" 2>/dev/null || true)
case "$OLD_VER" in ''|0|*[!0-9]*|0*) die "live bundle CFBundleVersion is '$OLD_VER', not a positive integer" ;; esac
NEW_VER=$((OLD_VER + 1))
GUARD_VER=$(ptool guard-version "$LIVE_GUARD") || die "live guard does not have exactly one bundle_version check"
[ "$GUARD_VER" = "$OLD_VER" ] || die "live guard checks bundle version $GUARD_VER, but the live bundle is $OLD_VER"
OLD_PROFILE=$(ptool guard-profile "$LIVE_GUARD") || die "live guard does not have exactly one PROFILE= line"
ptool profile-check "$NEW_PROFILE" "$NEW_VER" >/dev/null || exit 1
echo "  live bundle N = $OLD_VER (its guard agrees); live profile = $OLD_PROFILE"
echo "  candidate: bundle $NEW_VER, profile $NEW_PROFILE"

step "0b new bundle"
for f in Contents/Info.plist Contents/MacOS/Navi48Metal Contents/Resources/libvulkan_radeon.dylib Contents/Resources/libn48xlate.dylib; do
  [ -f "$SRC/$f" ] || die "bundle lacks $f"
done
[ -d "$SRC/Contents/Resources/spvcache" ] || die "bundle lacks Resources/spvcache"
VER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SRC/Contents/Info.plist" 2>/dev/null || true)
[ "$VER" = "$NEW_VER" ] || die "CFBundleVersion is '$VER', expected $NEW_VER (live $OLD_VER + 1)"
if [ -n "$(find "$SRC" -type f -mmin -2 -print -quit)" ]; then
  die "bundle files changed in the last 2 minutes (rebuild running?); retry later"
fi
busy=$(pgrep -f "build-$NEW_VER" 2>/dev/null | grep -v -x -e "$$" || true)
[ -z "$busy" ] || die "a process mentioning build-$NEW_VER is running (pids: $(echo $busy)); wait for the build to finish"

# Read-only: the live bundle must be the bundle-N install that the live guard describes.
ptool guard-check "$LIVE_GUARD" "$LIVE_BUNDLE" "$OLD_VER" || die "live guard constants do not match the live bundle"

OUT=$MAC/trial-b$NEW_VER
mkdir -p "$OUT"
TMPNEW=$(mktemp -d "$OUT/.payload-new.XXXXXX")
cleanup() { if [ -n "${TMPNEW:-}" ] && [ -d "$TMPNEW" ]; then rm -rf "$TMPNEW"; fi; }
trap cleanup EXIT

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
ptool manifest "$TMPNEW/payload/manifest.json" "$TMPNEW/payload" "$NEW_PROFILE" "$SRC" "$LIVE_GUARD_SHA" \
  "$OLD_VER" "$OLD_PROFILE"

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
echo "  live -> candidate: bundle $OLD_VER ($OLD_PROFILE) -> bundle $NEW_VER ($NEW_PROFILE)"
echo "  payload:          $OUT/payload"
echo "  guard diff:       $OUT/GUARD.diff"
echo "  live guard sha:   $LIVE_GUARD_SHA (recorded in manifest; install refuses if it changed)"
echo "  Navi48Metal main: $(ptool hash "$OUT/payload/Navi48Metal.bundle/Contents/MacOS/Navi48Metal")"
echo "  libvulkan_radeon: $(ptool hash "$OUT/payload/Navi48Metal.bundle/Contents/Resources/libvulkan_radeon.dylib")"
echo "  libn48xlate:      $(ptool hash "$OUT/payload/Navi48Metal.bundle/Contents/Resources/libn48xlate.dylib")"
echo "  guard:            $(ptool hash "$OUT/payload/accelerated-reboot-trial.sh")"
echo "Next: cd $W && sudo ./install-trial.sh"
