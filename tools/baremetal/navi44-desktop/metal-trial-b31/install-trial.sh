#!/bin/bash
# install-trial.sh - install Metal bundle 31 and its boot guard; keep v30 backups.
# Run AFTER ./stage.sh:   sudo ./install-trial.sh
# Changes: /Library/GPUBundles/Navi48Metal.bundle (atomic swap) and the boot guard.
# No audio step, /private/var/tmp/n48m-spv is not moved. Nothing runs until reboot.
# Rollback: sudo ./rollback-trial.sh
set -Eeuo pipefail
export LC_ALL=C
umask 022
PATH=/usr/bin:/bin:/usr/sbin:/sbin

[ "$(id -u)" -eq 0 ] || { echo "STOP: run with sudo: sudo $0" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "STOP: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

W=$(cd "$(dirname "$0")" && pwd)
PROJ=/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver
PAYBASE=$PROJ/research/builds/macos-20261031/trial-b31
PY=/usr/bin/python3
GPUB=/Library/GPUBundles
LIVE=$GPUB/Navi48Metal.bundle
APPDIR='/Library/Application Support/Navi44'
APP="$APPDIR/accelerated-trial"
GUARD="$APP/accelerated-reboot-trial.sh"
STATE="$APP/boot-state.json"
PLIST=/Library/LaunchDaemons/org.navi44.accelerated-trial.plist
KILL=/private/tmp/n48m-off
HEADLESS=/private/tmp/n48m-headless-no
PROFILE_V30=stage30-vonly-v1
PROFILE_V31=stage31-msaa-iosurface-v1
TS=$(date +%Y%m%d-%H%M%S)
BKDIR="$APPDIR/trial-b31-backup-$TS"
BK_GPU="$GPUB/Navi48Metal.bundle.v30-backup-$TS"
STAGE="$GPUB/.Navi48Metal.b31-staging-$TS"
NEWGUARD="$APP/.accelerated-reboot-trial.b31-$TS"

ROOTTMP=""
SWAPPED=0
OTHER=""          # path holding the displaced v30 bundle while SWAPPED=1
GUARD_REPLACED=0
PHASE="unknown"

write_record() {
  [ -d "$BKDIR" ] || return 0
  {
    printf 'TS=%s\n' "$TS"
    printf 'BKDIR=%s\n' "$BKDIR"
    printf 'BK_GPU=%s\n' "$BK_GPU"
  } > "$BKDIR/install-record.env.tmp"
  chown root:wheel "$BKDIR/install-record.env.tmp"
  chmod 600 "$BKDIR/install-record.env.tmp"
  mv -f "$BKDIR/install-record.env.tmp" "$BKDIR/install-record.env"
}

# abort: undo only what this run changed, then exit. Never deletes a backup.
abort() {
  local rc=$1
  trap - ERR
  set +e
  echo "" >&2
  echo "FAILED (rc=$rc): restoring what this run changed" >&2
  if [ "$GUARD_REPLACED" = 1 ] && [ -f "$BKDIR/accelerated-reboot-trial.v30.sh" ]; then
    cp "$BKDIR/accelerated-reboot-trial.v30.sh" "$GUARD.restore" && chown root:wheel "$GUARD.restore" \
      && chmod 755 "$GUARD.restore" && mv -f "$GUARD.restore" "$GUARD" && echo "  guard restored to v30"
  fi
  if [ "$SWAPPED" = 1 ] && [ -n "$OTHER" ] && [ -e "$OTHER" ]; then
    if "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$OTHER" >/dev/null; then
      mv "$OTHER" "$BKDIR/failed-b31.bundle" && echo "  bundle swapped back to v30; failed b31 kept in $BKDIR/failed-b31.bundle"
    else
      echo "  MANUAL: swap failed; v30 is at $OTHER, b31 at $LIVE. Run sudo ./rollback-trial.sh" >&2
    fi
  fi
  # Remove only temporaries created by this run (the unswapped staging copy and the temp guard).
  if [ "$SWAPPED" = 0 ] && [ -n "$STAGE" ] && [ -d "$STAGE" ] && [ "${STAGE#"$GPUB/.Navi48Metal.b31-staging-"}" != "$STAGE" ]; then
    rm -rf "$STAGE" && echo "  unused staging copy removed"
  fi
  if [ "$GUARD_REPLACED" = 0 ] && [ -f "$NEWGUARD" ]; then rm -f "$NEWGUARD"; fi
  [ -n "$ROOTTMP" ] && [ -d "$ROOTTMP" ] && rm -rf "$ROOTTMP"
  echo "  backups kept in: $BKDIR" >&2
  exit "$rc"
}
die() { echo "STOP: $*" >&2; abort 1; }
trap 'abort $?' ERR
trap 'rc=$?; [ -n "$ROOTTMP" ] && [ -d "$ROOTTMP" ] && rm -rf "$ROOTTMP"; exit $rc' EXIT

echo "== 1 preflight"
PAYDIR=$PAYBASE/payload
ROOTTMP=$(mktemp -d /private/var/tmp/trial-b31-install.XXXXXX)
chmod 700 "$ROOTTMP"
cp -p "$W/lib/payload_tool.py" "$ROOTTMP/payload_tool.py"
[ -f "$PAYDIR/manifest.json" ] || die "payload missing: run ./stage.sh first ($PAYDIR)"
ditto "$PAYDIR" "$ROOTTMP/payload"
PAYROOT=$ROOTTMP/payload
"$PY" -I "$ROOTTMP/payload_tool.py" check "$PAYROOT/manifest.json" "" "$PAYROOT"
[ "$("$PY" -I "$ROOTTMP/payload_tool.py" manifest-get "$PAYROOT/manifest.json" candidate_bundle_version)" = 31 ] \
  || die "manifest is not for bundle 31"
[ "$("$PY" -I "$ROOTTMP/payload_tool.py" manifest-get "$PAYROOT/manifest.json" profile)" = "$PROFILE_V31" ] \
  || die "manifest profile is not $PROFILE_V31"
REC_LIVE_GUARD_SHA=$("$PY" -I "$ROOTTMP/payload_tool.py" manifest-get "$PAYROOT/manifest.json" live_guard_sha256)
PAYVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$PAYROOT/Navi48Metal.bundle/Contents/Info.plist")
[ "$PAYVER" = 31 ] || die "payload bundle is version '$PAYVER', expected 31"
codesign --verify --deep --strict "$PAYROOT/Navi48Metal.bundle" >/dev/null 2>&1 || die "payload signature invalid"
bash -n "$PAYROOT/accelerated-reboot-trial.sh" || die "payload guard fails bash -n"
grep -Fxq "PROFILE=$PROFILE_V31" "$PAYROOT/accelerated-reboot-trial.sh" || die "payload guard is not the $PROFILE_V31 guard"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$PAYROOT/accelerated-reboot-trial.sh" "$PAYROOT/Navi48Metal.bundle" 31
echo "  payload verified against manifest (bundle 31)"

[ -d "$LIVE" ] && [ ! -L "$LIVE" ] || die "live bundle missing: $LIVE"
LIVEVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist" 2>/dev/null || true)
[ "$LIVEVER" = 30 ] || die "live bundle is version '$LIVEVER', expected 30"
[ -f "$GUARD" ] && [ ! -L "$GUARD" ] || die "live guard missing: $GUARD"
grep -Fxq "PROFILE=$PROFILE_V30" "$GUARD" || die "live guard is not the $PROFILE_V30 guard"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$GUARD" "$LIVE" 30 \
  || die "live bundle hashes do not match the bundle-30 guard constants"
echo "  live bundle is v30; hashes match the live guard"

LIVE_GUARD_SHA_NOW=$("$PY" -I "$ROOTTMP/payload_tool.py" hash "$GUARD")
[ "$LIVE_GUARD_SHA_NOW" = "$REC_LIVE_GUARD_SHA" ] \
  || die "live guard changed since staging (now $LIVE_GUARD_SHA_NOW, staged from $REC_LIVE_GUARD_SHA); rerun ./stage.sh"
echo "  live guard unchanged since staging ($LIVE_GUARD_SHA_NOW)"

[ -f "$STATE" ] || [ ! -e "$STATE" ] || die "unexpected boot-state entry"
STATUS_JSON=$("$PY" -I "$APP/boot-state.py" status --state "$STATE" --profile "$PROFILE_V30") \
  || die "cannot read boot-state (see $APP/boot-state.py)"
PHASE=$(printf '%s' "$STATUS_JSON" | "$PY" -I "$ROOTTMP/payload_tool.py" phase)
case "$PHASE" in
  absent|stable|stopped) echo "  boot latch: $PHASE (next boot may begin a new attempt)" ;;
  *) die "boot latch is '$PHASE'; reviewed reset required before installing (see README)" ;;
esac

echo "  kill switch and flags (reported only):"
for p in "$KILL" "$HEADLESS" "$APP/disabled"; do
  if [ -e "$p" ] || [ -L "$p" ]; then
    echo "    PRESENT $p ($(stat -f '%Su:%Sg mode %Lp size %z' "$p"))"
  else
    echo "    absent  $p"
  fi
done
[ -e "$APP/disabled" ] && echo "  WARNING: $APP/disabled exists: the boot job will not activate bundle 31 on reboot"
[ -f "$PLIST" ] && echo "  launchd job plist present" || echo "  WARNING: launchd job plist missing: $PLIST"
echo "  n48m-spv: left in place (this package never moves it)"
echo "  audio: not touched"
if [ "$(who | wc -l)" -gt 0 ]; then echo "  WARNING: a user session is logged in; the swap is safe but reboot before testing"; fi

for p in "$BK_GPU" "$BKDIR" "$STAGE" "$NEWGUARD"; do
  [ ! -e "$p" ] && [ ! -L "$p" ] || die "target already exists: $p"
done
NEED_KB=$(du -sk "$LIVE" | awk '{print $1}')
FREE_KB=$(df -Pk "$GPUB" | awk 'NR==2{print $4}')
[ "$FREE_KB" -gt $((NEED_KB * 3)) ] || die "not enough free space in $GPUB"

echo "== 2 backups (copies only)"
mkdir -p "$APPDIR"
mkdir -m 700 "$BKDIR"
write_record
ditto "$LIVE" "$BK_GPU"
ditto "$LIVE" "$BKDIR/Navi48Metal.bundle.v30"
cp -p "$GUARD" "$BKDIR/accelerated-reboot-trial.v30.sh"
if [ -e "$STATE" ]; then
  cp -p "$STATE" "$BKDIR/boot-state.pre-b31.json"
else
  echo "  no boot-state file to back up"
fi
cp -p "$PLIST" "$BKDIR/org.navi44.accelerated-trial.plist"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live.json"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BK_GPU" > "$ROOTTMP/bk-gpu.json"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BKDIR/Navi48Metal.bundle.v30" > "$ROOTTMP/bk-app.json"
"$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk-gpu.json"
"$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk-app.json"
chown -R root:wheel "$BK_GPU" "$BKDIR"
chmod -R go-w "$BK_GPU" "$BKDIR"
chmod 700 "$BKDIR"
echo "  GPU bundle backup: $BK_GPU"
echo "  app-support backup: $BKDIR"

echo "== 3 stage bundle 31 next to the live path, then atomic swap"
ditto "$PAYROOT/Navi48Metal.bundle" "$STAGE"
chown -R root:wheel "$STAGE"
chmod -R go-w "$STAGE"
"$PY" -I "$ROOTTMP/payload_tool.py" check "$PAYROOT/manifest.json" "Navi48Metal.bundle/" "$STAGE"
codesign --verify --deep --strict "$STAGE" >/dev/null 2>&1 || die "staged bundle signature invalid"
OTHER=$STAGE
"$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$STAGE" >/dev/null
SWAPPED=1
codesign --verify --deep --strict "$LIVE" >/dev/null 2>&1 || die "live bundle signature invalid after swap"
"$PY" -I "$ROOTTMP/payload_tool.py" check "$PAYROOT/manifest.json" "Navi48Metal.bundle/" "$LIVE"
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist")" = 31 ] \
  || die "live bundle is not version 31 after swap"
mv "$STAGE" "$BKDIR/displaced-v30.bundle"
OTHER=$BKDIR/displaced-v30.bundle
echo "  live bundle is now 31; displaced v30 kept in $OTHER"

echo "== 4 install boot guard for bundle 31"
cp "$PAYROOT/accelerated-reboot-trial.sh" "$NEWGUARD"
chown root:wheel "$NEWGUARD"
chmod 755 "$NEWGUARD"
bash -n "$NEWGUARD"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$NEWGUARD" "$LIVE" 31
mv -f "$NEWGUARD" "$GUARD"
GUARD_REPLACED=1
echo "  guard installed (v30 copy kept in $BKDIR)"

echo "== 5 summary"
write_record
cat <<SUMMARY

BUNDLE 31 AND GUARD 31 ARE INSTALLED FOR THE NEXT BOOT. Nothing is activated yet.

Backups:
  v30 bundle (GPUBundles):    $BK_GPU
  v30 bundle + guard + state: $BKDIR
  n48m-spv:                   not moved
  audio:                      not touched
  boot latch before install:  $PHASE

NEXT STEPS
  1. sudo reboot
  2. At the login window, wait about 5 minutes before logging in. The guard waits for the
     translator, registry, and WindowServer restart in that time.
  3. After login, follow "Dopo il riavvio" in README.md. Logs:
     /private/var/tmp/navi44-accelerated-trial/run.log
     $APP/boot-state.json (read with sudo)
  4. To return to v30 at any time: sudo $W/rollback-trial.sh
SUMMARY
exit 0
