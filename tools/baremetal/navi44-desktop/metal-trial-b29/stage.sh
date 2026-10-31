#!/bin/bash
# stage.sh - build W/payload for Metal bundle 29 and its boot guard.
# Runs WITHOUT root. Writes only inside this trial directory. Installs nothing.
# Usage: ./stage.sh [PATH_TO_Navi48Metal.bundle]
set -euo pipefail
export LC_ALL=C
umask 022

[ "$(id -u)" -ne 0 ] || { echo "STOP: stage.sh must not run as root (install-trial.sh does the root part)"; exit 1; }

W=$(cd "$(dirname "$0")" && pwd)
PROJ=/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver
MAC=$PROJ/research/builds/macos-20261031
SRC=${1:-$MAC/bundle29-src/build-29-newxlate/Navi48Metal.bundle}
BASE28=$PROJ/research/builds/macos-20261030/archive-recovery/accelerated-reboot-trial.sh
TEMPLATE=$W/src/accelerated-reboot-trial.template.sh
TOOL=$W/lib/payload_tool.py
PY=/usr/bin/python3
PROFILE=stage29-nullmoth-v1
TS=$(date +%Y%m%d-%H%M%S)

die() { echo "STOP: $*" >&2; exit 1; }
step() { echo "== $*"; }

TMPNEW=$(mktemp -d "$W/.payload-new.XXXXXX")
cleanup() { if [ -n "${TMPNEW:-}" ] && [ -d "$TMPNEW" ]; then rm -rf "$TMPNEW"; fi; }
trap cleanup EXIT

step "0 preconditions"
[ -d "$SRC" ] && [ ! -L "$SRC" ] || die "bundle missing or symlink: $SRC"
[ -f "$TEMPLATE" ] || die "guard template missing: $TEMPLATE"
[ -f "$BASE28" ] || die "bundle-28 guard reference missing: $BASE28"
for f in Contents/Info.plist Contents/MacOS/Navi48Metal Contents/Resources/libvulkan_radeon.dylib Contents/Resources/libn48xlate.dylib; do
  [ -f "$SRC/$f" ] || die "bundle lacks $f"
done
[ -d "$SRC/Contents/Resources/spvcache" ] || die "bundle lacks Resources/spvcache"
VER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SRC/Contents/Info.plist" 2>/dev/null || true)
[ "$VER" = 29 ] || die "CFBundleVersion is '$VER', expected 29"
if [ -n "$(find "$SRC" -type f -mmin -2 -print -quit)" ]; then
  die "bundle files changed in the last 2 minutes (rebuild running?); retry later"
fi
if pgrep -fl 'build-29' >/dev/null 2>&1; then
  die "a process mentioning build-29 is running; wait for the build to finish"
fi

step "1 snapshot source tree"
"$PY" -I "$TOOL" tree "$SRC" > "$TMPNEW/src-before.json"

step "2 copy with ditto and compare"
mkdir "$TMPNEW/payload"
ditto "$SRC" "$TMPNEW/payload/Navi48Metal.bundle"
"$PY" -I "$TOOL" tree "$SRC" > "$TMPNEW/src-after.json"
"$PY" -I "$TOOL" compare "$TMPNEW/src-before.json" "$TMPNEW/src-after.json" || die "source changed during copy"
"$PY" -I "$TOOL" tree "$TMPNEW/payload/Navi48Metal.bundle" > "$TMPNEW/copy.json"
"$PY" -I "$TOOL" compare "$TMPNEW/src-before.json" "$TMPNEW/copy.json" || die "copy differs from source"

step "3 signature and version of the copy"
codesign --verify --deep --strict "$TMPNEW/payload/Navi48Metal.bundle" || die "codesign --verify --deep --strict failed"
CV=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$TMPNEW/payload/Navi48Metal.bundle/Contents/Info.plist")
[ "$CV" = 29 ] || die "copy CFBundleVersion is '$CV'"

step "4 fill guard constants from the copied bundle"
"$PY" -I "$TOOL" fill-guard "$TEMPLATE" "$TMPNEW/payload/accelerated-reboot-trial.sh" "$TMPNEW/payload/Navi48Metal.bundle"
chmod 755 "$TMPNEW/payload/accelerated-reboot-trial.sh"
bash -n "$TMPNEW/payload/accelerated-reboot-trial.sh" || die "guard fails bash -n"
"$PY" -I "$TOOL" guard-check "$TMPNEW/payload/accelerated-reboot-trial.sh" "$TMPNEW/payload/Navi48Metal.bundle" 29

step "5 diff against bundle-28 guard (only profile, version and hash-constant lines may change)"
rc=0
diff -u --label bundle28-guard --label bundle29-guard "$BASE28" "$TMPNEW/payload/accelerated-reboot-trial.sh" > "$TMPNEW/GUARD.diff" || rc=$?
[ "$rc" -le 1 ] || die "diff failed"
REMOVED=$(grep '^-[^-]' "$TMPNEW/GUARD.diff" || true)
OTHER_CHANGES=$(printf '%s\n' "$REMOVED" | grep -v -E '^-PROFILE=|bundle_version" == 28 \]\]|shasum -a 256' | grep -c . || true)
[ "$OTHER_CHANGES" = 0 ] || die "guard diff changes lines other than profile, version and hash constants"
[ "$(printf '%s\n' "$REMOVED" | grep -c -E '^-PROFILE=' || true)" = 1 ] || die "profile line not changed exactly once"
HASHLINES=$(printf '%s\n' "$REMOVED" | grep -c 'shasum -a 256' || true)
echo "  changed: profile, version, $HASHLINES hash-constant line(s) (unchanged dylib constants are not listed)"

step "6 manifest over the whole payload"
"$PY" -I "$TOOL" manifest "$TMPNEW/payload/manifest.json" "$TMPNEW/payload" "$PROFILE" "$SRC" "$MAC/audio-v1"

step "7 publish to $W/payload"
mv -f "$TMPNEW/GUARD.diff" "$W/GUARD.diff"
if [ -e "$W/payload" ]; then
  mv "$W/payload" "$W/payload.prev-$TS"
  echo "previous payload kept as $W/payload.prev-$TS"
fi
mv "$TMPNEW/payload" "$W/payload"
"$PY" -I "$TOOL" check "$W/payload/manifest.json" "" "$W/payload"

echo
echo "STAGED OK (not installed)"
echo "  payload:          $W/payload"
echo "  guard diff:       $W/GUARD.diff"
echo "  Navi48Metal main: $("$PY" -I "$TOOL" hash "$W/payload/Navi48Metal.bundle/Contents/MacOS/Navi48Metal")"
echo "  libvulkan_radeon: $("$PY" -I "$TOOL" hash "$W/payload/Navi48Metal.bundle/Contents/Resources/libvulkan_radeon.dylib")"
echo "  libn48xlate:      $("$PY" -I "$TOOL" hash "$W/payload/Navi48Metal.bundle/Contents/Resources/libn48xlate.dylib")"
echo "  guard:            $("$PY" -I "$TOOL" hash "$W/payload/accelerated-reboot-trial.sh")"
echo "Next: cd $W && sudo ./install-trial.sh"
