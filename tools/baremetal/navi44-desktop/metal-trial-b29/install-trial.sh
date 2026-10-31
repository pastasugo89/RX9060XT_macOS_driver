#!/bin/bash
# install-trial.sh - install Metal bundle 29 and its boot guard; keep v28 backups.
# Run AFTER ./stage.sh:   sudo ./install-trial.sh [--no-audio]
# Changes: /Library/GPUBundles/Navi48Metal.bundle (atomic swap), the boot guard,
# /private/var/tmp/n48m-spv (renamed, never deleted), and optionally VoodooHDA audio
# (audio-v1/install-audio.sh, run LAST and independently). Nothing runs until reboot.
# Rollback: sudo ./rollback-trial.sh
set -Eeuo pipefail
export LC_ALL=C
umask 022
PATH=/usr/bin:/bin:/usr/sbin:/sbin

[ "$(id -u)" -eq 0 ] || { echo "STOP: run with sudo: sudo $0" >&2; exit 1; }

NO_AUDIO=0
for arg in "$@"; do
  case "$arg" in
    --no-audio) NO_AUDIO=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "STOP: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

W=$(cd "$(dirname "$0")" && pwd)
MAC=$(cd "$W/.." && pwd)
AUDIO_DIR=$MAC/audio-v1
PY=/usr/bin/python3
GPUB=/Library/GPUBundles
LIVE=$GPUB/Navi48Metal.bundle
APPDIR='/Library/Application Support/Navi44'
APP="$APPDIR/accelerated-trial"
GUARD="$APP/accelerated-reboot-trial.sh"
STATE="$APP/boot-state.json"
PLIST=/Library/LaunchDaemons/org.navi44.accelerated-trial.plist
SPV=/private/var/tmp/n48m-spv
KILL=/private/tmp/n48m-off
HEADLESS=/private/tmp/n48m-headless-no
PROFILE_V28=stage25-archive-boundary-v1
PROFILE_V29=stage29-nullmoth-v1
TS=$(date +%Y%m%d-%H%M%S)
BKDIR="$APPDIR/trial-b29-backup-$TS"
BK_GPU="$GPUB/Navi48Metal.bundle.v28-backup-$TS"
STAGE="$GPUB/.Navi48Metal.b29-staging-$TS"
SPV_RENAMED="$SPV.pre-b29-$TS"
NEWGUARD="$APP/.accelerated-reboot-trial.b29-$TS"

ROOTTMP=""
SWAPPED=0
OTHER=""          # path holding the displaced v28 bundle while SWAPPED=1
GUARD_REPLACED=0
SPV_MOVED=0
AUDIO_RESULT="not run"
PHASE="unknown"

write_record() {
  [ -d "$BKDIR" ] || return 0
  {
    printf 'TS=%s\n' "$TS"
    printf 'BKDIR=%s\n' "$BKDIR"
    printf 'BK_GPU=%s\n' "$BK_GPU"
    printf 'SPV_RENAMED=%s\n' "$([ "$SPV_MOVED" = 1 ] && echo "$SPV_RENAMED" || echo "")"
    printf 'AUDIO_RESULT=%s\n' "$AUDIO_RESULT"
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
  if [ "$GUARD_REPLACED" = 1 ] && [ -f "$BKDIR/accelerated-reboot-trial.v28.sh" ]; then
    cp "$BKDIR/accelerated-reboot-trial.v28.sh" "$GUARD.restore" && chown root:wheel "$GUARD.restore" \
      && chmod 755 "$GUARD.restore" && mv -f "$GUARD.restore" "$GUARD" && echo "  guard restored to v28"
  fi
  if [ "$SWAPPED" = 1 ] && [ -n "$OTHER" ] && [ -e "$OTHER" ]; then
    if "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$OTHER" >/dev/null; then
      mv "$OTHER" "$BKDIR/failed-b29.bundle" && echo "  bundle swapped back to v28; failed b29 kept in $BKDIR/failed-b29.bundle"
    else
      echo "  MANUAL: swap failed; v28 is at $OTHER, b29 at $LIVE. Run sudo ./rollback-trial.sh" >&2
    fi
  fi
  if [ "$SPV_MOVED" = 1 ] && [ -d "$SPV_RENAMED" ] && [ ! -e "$SPV" ]; then
    mv "$SPV_RENAMED" "$SPV" && echo "  n48m-spv restored"
  fi
  # Remove only temporaries created by this run (the unswapped staging copy and the temp guard).
  if [ "$SWAPPED" = 0 ] && [ -n "$STAGE" ] && [ -d "$STAGE" ] && [ "${STAGE#"$GPUB/.Navi48Metal.b29-staging-"}" != "$STAGE" ]; then
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
ROOTTMP=$(mktemp -d /private/var/tmp/trial-b29-install.XXXXXX)
chmod 700 "$ROOTTMP"
cp -p "$W/lib/payload_tool.py" "$ROOTTMP/payload_tool.py"
[ -f "$W/payload/manifest.json" ] || die "payload missing: run ./stage.sh first"
ditto "$W/payload" "$ROOTTMP/payload"
PAYROOT=$ROOTTMP/payload
"$PY" -I "$ROOTTMP/payload_tool.py" check "$PAYROOT/manifest.json" "" "$PAYROOT"
PAYVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$PAYROOT/Navi48Metal.bundle/Contents/Info.plist")
[ "$PAYVER" = 29 ] || die "payload bundle is version '$PAYVER', expected 29"
codesign --verify --deep --strict "$PAYROOT/Navi48Metal.bundle" >/dev/null 2>&1 || die "payload signature invalid"
bash -n "$PAYROOT/accelerated-reboot-trial.sh" || die "payload guard fails bash -n"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$PAYROOT/accelerated-reboot-trial.sh" "$PAYROOT/Navi48Metal.bundle" 29
echo "  payload verified against manifest (bundle 29)"

[ -d "$LIVE" ] && [ ! -L "$LIVE" ] || die "live bundle missing: $LIVE"
LIVEVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist" 2>/dev/null || true)
[ "$LIVEVER" = 28 ] || die "live bundle is version '$LIVEVER', expected 28"
[ -f "$GUARD" ] && [ ! -L "$GUARD" ] || die "live guard missing: $GUARD"
grep -Fq "PROFILE=$PROFILE_V28" "$GUARD" || die "live guard is not the $PROFILE_V28 guard"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$GUARD" "$LIVE" 28 \
  || die "live bundle hashes do not match the bundle-28 guard constants"
echo "  live bundle is v28; hashes match the bundle-28 guard"

[ -f "$STATE" ] || [ ! -e "$STATE" ] || die "unexpected boot-state entry"
STATUS_JSON=$("$PY" -I "$APP/boot-state.py" status --state "$STATE" --profile "$PROFILE_V28") \
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
[ -e "$APP/disabled" ] && echo "  WARNING: $APP/disabled exists: the boot job will not activate bundle 29 on reboot"
[ -f "$PLIST" ] && echo "  launchd job plist present" || echo "  WARNING: launchd job plist missing: $PLIST"
if [ "${N48M_MOVE_SPV:-0}" = 1 ] && [ -d "$SPV" ]; then echo "  n48m-spv present: will be renamed to $SPV_RENAMED"; else echo "  n48m-spv: kept in place"; fi
if [ "$(who | wc -l)" -gt 0 ]; then echo "  WARNING: a user session is logged in; the swap is safe but reboot before testing"; fi

for p in "$BK_GPU" "$BKDIR" "$STAGE" "$SPV_RENAMED" "$NEWGUARD"; do
  [ ! -e "$p" ] && [ ! -L "$p" ] || die "target already exists: $p"
done
NEED_KB=$(du -sk "$LIVE" | awk '{print $1}')
FREE_KB=$(df -Pk "$GPUB" | awk 'NR==2{print $4}')
[ "$FREE_KB" -gt $((NEED_KB * 3)) ] || die "not enough free space in $GPUB"

if [ "$NO_AUDIO" = 0 ]; then
  if "$PY" -I "$ROOTTMP/payload_tool.py" audio-check "$PAYROOT/manifest.json" "$AUDIO_DIR" >/dev/null 2>&1; then
    echo "  audio scripts match the staged manifest (audio runs at step 6)"
  else
    echo "  WARNING: audio scripts differ from the staged manifest; audio will NOT run"
  fi
fi

echo "== 2 backups (copies only)"
mkdir -p "$APPDIR"
mkdir -m 700 "$BKDIR"
write_record
ditto "$LIVE" "$BK_GPU"
ditto "$LIVE" "$BKDIR/Navi48Metal.bundle.v28"
cp -p "$GUARD" "$BKDIR/accelerated-reboot-trial.v28.sh"
cp -p "$STATE" "$BKDIR/boot-state.pre-b29.json"
cp -p "$PLIST" "$BKDIR/org.navi44.accelerated-trial.plist"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live.json"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BK_GPU" > "$ROOTTMP/bk-gpu.json"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BKDIR/Navi48Metal.bundle.v28" > "$ROOTTMP/bk-app.json"
"$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk-gpu.json"
"$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk-app.json"
chown -R root:wheel "$BK_GPU" "$BKDIR"
chmod -R go-w "$BK_GPU" "$BKDIR"
chmod 700 "$BKDIR"
echo "  GPU bundle backup: $BK_GPU"
echo "  app-support backup: $BKDIR"

echo "== 3 n48m-spv is kept in place"
# Not moved any more: WindowServer never translates in process, so this daemon-filled cache is
# its only source for shaders missing from the bundle spvcache. Moving it aside (first b29 install,
# 31/10) left Control Center on magenta placeholders. N48M_MOVE_SPV=1 restores the old behaviour.
if [ "${N48M_MOVE_SPV:-0}" = 1 ] && [ -d "$SPV" ] && [ ! -L "$SPV" ]; then
  mv "$SPV" "$SPV_RENAMED"
  SPV_MOVED=1
  write_record
  echo "  moved to $SPV_RENAMED"
else
  echo "  nothing to move"
fi

echo "== 4 stage bundle 29 next to the live path, then atomic swap"
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
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist")" = 29 ] \
  || die "live bundle is not version 29 after swap"
mv "$STAGE" "$BKDIR/displaced-v28.bundle"
OTHER=$BKDIR/displaced-v28.bundle
echo "  live bundle is now 29; displaced v28 kept in $OTHER"

echo "== 5 install boot guard for bundle 29"
cp "$PAYROOT/accelerated-reboot-trial.sh" "$NEWGUARD"
chown root:wheel "$NEWGUARD"
chmod 755 "$NEWGUARD"
bash -n "$NEWGUARD"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$NEWGUARD" "$LIVE" 29
mv -f "$NEWGUARD" "$GUARD"
GUARD_REPLACED=1
echo "  guard installed (v28 copy kept in $BKDIR)"

if [ "$NO_AUDIO" = 0 ]; then
  echo "== 6 audio (independent: a failure here leaves the GPU part installed)"
  if "$PY" -I "$ROOTTMP/payload_tool.py" audio-check "$PAYROOT/manifest.json" "$AUDIO_DIR" >/dev/null 2>&1; then
    arc=0
    /bin/bash "$AUDIO_DIR/install-audio.sh" > "$BKDIR/audio-install.log" 2>&1 || arc=$?
    if [ "$arc" = 0 ]; then
      AUDIO_RESULT="installed; reboot needed; approve VoodooHDA if prompted"
    else
      AUDIO_RESULT="FAILED rc=$arc (log: $BKDIR/audio-install.log); GPU part remains installed"
    fi
  else
    AUDIO_RESULT="NOT RUN: audio scripts changed since staging"
  fi
  echo "  audio: $AUDIO_RESULT"
else
  AUDIO_RESULT="skipped (--no-audio)"
fi
write_record
echo "  record: $BKDIR/install-record.env"

echo "== 7 summary"
cat <<EOF

BUNDLE 29 AND GUARD 29 ARE INSTALLED FOR THE NEXT BOOT. Nothing is activated yet.

Backups:
  v28 bundle (GPUBundles):   $BK_GPU
  v28 bundle + guard + state: $BKDIR
  n48m-spv:                  $( [ "$SPV_MOVED" = 1 ] && echo "$SPV_RENAMED" || echo "not moved")
  audio:                     $AUDIO_RESULT
  boot latch before install: $PHASE

Translator note: libn48xlate.dylib in this bundle is checked and hashed as staged. Confirm
it is the translator you intend (see README) before judging the shader cache result.

NEXT STEPS
  1. sudo reboot
  2. At the login window, wait about 5 minutes before logging in. The guard waits for the
     translator, registry, and WindowServer restart in that time.
  3. After login, follow "Dopo il riavvio" in README.md. Logs:
     /private/var/tmp/navi44-accelerated-trial/run.log
     $APP/boot-state.json (read with sudo)
  4. To return to v28 at any time: sudo $W/rollback-trial.sh
EOF
exit 0
