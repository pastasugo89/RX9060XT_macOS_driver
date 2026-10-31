#!/bin/bash
# install-trial.sh - install the staged Metal bundle N+1 and its boot guard; keep the bundle N backups.
# N = live bundle version; the payload is research/builds/macos-20261031/trial-b<N+1>/payload (from ./stage.sh).
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
TS=$(date +%Y%m%d-%H%M%S)

# N = live bundle version; the staged payload must be N+1.
OLD_VER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist" 2>/dev/null || true)
case "$OLD_VER" in ''|0|*[!0-9]*|0*) echo "STOP: live bundle version '$OLD_VER' is not a positive integer" >&2; exit 1 ;; esac
NEW_VER=$((OLD_VER + 1))
PAYBASE=$PROJ/research/builds/macos-20261031/trial-b$NEW_VER
BKDIR="$APPDIR/trial-b$NEW_VER-backup-$TS"
BK_GPU="$GPUB/Navi48Metal.bundle.v$OLD_VER-backup-$TS"
STAGE="$GPUB/.Navi48Metal.b$NEW_VER-staging-$TS"    # the v$NEW_VER copy before the swap
DISPLACED="$BKDIR/displaced-v$OLD_VER.bundle"        # the v$OLD_VER bundle after the swap
FAILED="$BKDIR/failed-b$NEW_VER.bundle"              # the v$NEW_VER bundle if the install is undone
NEWGUARD="$APP/.accelerated-reboot-trial.b$NEW_VER-$TS"

ROOTTMP=""
PROFILE_OLD=""
PROFILE_NEW=""
PHASE="unknown"

# ---- helpers begin ----
# Version of a bundle (CFBundleVersion), or "absent" / "unreadable". Read only.
version_of() {
  if [ -e "$1/Contents/Info.plist" ]; then
    /usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$1/Contents/Info.plist" 2>/dev/null || echo "unreadable"
  else
    echo "absent"
  fi
}

write_record() {
  [ -d "$BKDIR" ] || return 0
  {
    printf 'TS=%s\n' "$TS"
    printf 'BKDIR=%s\n' "$BKDIR"
    printf 'BK_GPU=%s\n' "$BK_GPU"
    printf 'FROM_VER=%s\n' "$OLD_VER"
    printf 'TO_VER=%s\n' "$NEW_VER"
  } > "$BKDIR/install-record.env.tmp"
  chown root:wheel "$BKDIR/install-record.env.tmp"
  chmod 600 "$BKDIR/install-record.env.tmp"
  mv -f "$BKDIR/install-record.env.tmp" "$BKDIR/install-record.env"
}

# The state on disk, printed on stderr after an abort.
report_state() {
  local guard_line
  guard_line=$(grep -m1 '^PROFILE=' "$GUARD" 2>/dev/null || echo "no PROFILE= line")
  echo "  final state:" >&2
  echo "    live bundle:  v$(version_of "$LIVE")  ($LIVE)" >&2
  echo "    live guard:   $guard_line  ($GUARD)" >&2
  for p in "$STAGE" "$DISPLACED" "$FAILED"; do
    if [ -e "$p" ]; then echo "    copy left at: $p (v$(version_of "$p"))" >&2; fi
  done
  if [ -d "$BKDIR" ]; then echo "    backups kept: $BKDIR" >&2; fi
}

# abort: undo what this run changed. It judges the state on disk, not flags, so it is right wherever
# the run stopped (a failed command, Ctrl-C, TERM, HUP). It never deletes a backup: the old bundle and
# the failed new bundle are moved, not removed.
abort() {
  local rc=$1 lv sv dv other
  trap - ERR
  trap '' INT HUP TERM
  set +e
  echo "" >&2
  echo "FAILED (rc=$rc): undoing what this run changed" >&2

  # 1. Boot guard: if the v$NEW_VER guard is in place, put the v$OLD_VER copy back.
  if [ -n "$PROFILE_NEW" ] && grep -Fxq "PROFILE=$PROFILE_NEW" "$GUARD" 2>/dev/null; then
    if [ -f "$BKDIR/accelerated-reboot-trial.v$OLD_VER.sh" ] \
       && cp "$BKDIR/accelerated-reboot-trial.v$OLD_VER.sh" "$GUARD.restore" \
       && chown root:wheel "$GUARD.restore" && chmod 755 "$GUARD.restore" \
       && mv -f "$GUARD.restore" "$GUARD"; then
      echo "  guard: the v$NEW_VER guard was replaced by the v$OLD_VER copy" >&2
    else
      echo "  guard: MANUAL: copy $BKDIR/accelerated-reboot-trial.v$OLD_VER.sh to $GUARD" >&2
    fi
  else
    echo "  guard: unchanged" >&2
  fi
  if [ -f "$GUARD.restore" ]; then rm -f "$GUARD.restore"; fi
  if [ -f "$NEWGUARD" ]; then rm -f "$NEWGUARD"; fi

  # 2. Bundle: the live path must end up as v$OLD_VER again.
  lv=$(version_of "$LIVE")
  if [ "$lv" = "$NEW_VER" ]; then
    sv=$(version_of "$STAGE")
    dv=$(version_of "$DISPLACED")
    other=""
    if [ "$sv" = "$OLD_VER" ]; then other=$STAGE
    elif [ "$dv" = "$OLD_VER" ]; then other=$DISPLACED; fi
    if [ -z "$other" ]; then
      echo "  bundle: MANUAL: live is v$NEW_VER and no v$OLD_VER copy was found (staging: $sv, displaced: $dv)" >&2
    elif "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$other" >/dev/null 2>&1; then
      echo "  bundle: swapped back; live is v$OLD_VER again" >&2
      if mv "$other" "$FAILED"; then
        echo "  bundle: the failed v$NEW_VER bundle is in $FAILED" >&2
      else
        echo "  bundle: the failed v$NEW_VER bundle is still at $other (could not move it to $FAILED)" >&2
      fi
    else
      echo "  bundle: MANUAL: swap back failed; v$OLD_VER is at $other, v$NEW_VER at $LIVE" >&2
    fi
  elif [ "$lv" = "$OLD_VER" ]; then
    sv=$(version_of "$STAGE")
    if [ -d "$STAGE" ] && [ "$sv" != "$OLD_VER" ]; then
      rm -rf "$STAGE" && echo "  bundle: live untouched (v$OLD_VER); the unused staging copy was removed" >&2
    else
      echo "  bundle: live untouched (v$OLD_VER)" >&2
    fi
  else
    echo "  bundle: MANUAL: live bundle is version '$lv' (expected $OLD_VER or $NEW_VER)" >&2
  fi

  # 3. Temporaries of this run, then the state as it is now.
  if [ -n "$ROOTTMP" ] && [ -d "$ROOTTMP" ]; then rm -rf "$ROOTTMP"; fi
  report_state
  exit "$rc"
}
on_signal() { abort "$1"; }
die() { echo "STOP: $*" >&2; abort 1; }
# ---- helpers end ----

# ---- traps begin ----
trap 'on_signal 130' INT
trap 'on_signal 129' HUP
trap 'on_signal 143' TERM
trap 'abort $?' ERR
trap 'rc=$?; [ -n "$ROOTTMP" ] && [ -d "$ROOTTMP" ] && rm -rf "$ROOTTMP"; exit $rc' EXIT
# ---- traps end ----

echo "== 1 preflight (live bundle $OLD_VER -> staged bundle $NEW_VER)"
PAYDIR=$PAYBASE/payload
ROOTTMP=$(mktemp -d /private/var/tmp/trial-b$NEW_VER-install.XXXXXX)
chmod 700 "$ROOTTMP"
cp -p "$W/lib/payload_tool.py" "$ROOTTMP/payload_tool.py"
[ -f "$PAYDIR/manifest.json" ] || die "payload missing: run ./stage.sh first ($PAYDIR)"
ditto "$PAYDIR" "$ROOTTMP/payload"
PAYROOT=$ROOTTMP/payload
MANIFEST=$PAYROOT/manifest.json
"$PY" -I "$ROOTTMP/payload_tool.py" check "$MANIFEST" "" "$PAYROOT"
mget() { "$PY" -I "$ROOTTMP/payload_tool.py" manifest-get "$MANIFEST" "$1"; }
[ "$(mget candidate_bundle_version)" = "$NEW_VER" ] || die "manifest is not for bundle $NEW_VER"
[ "$(mget live_bundle_version)" = "$OLD_VER" ] \
  || die "manifest was staged for live bundle $(mget live_bundle_version), the live bundle is $OLD_VER; rerun ./stage.sh"
PROFILE_NEW=$(mget profile)
PROFILE_OLD=$(mget live_profile)
REC_LIVE_GUARD_SHA=$(mget live_guard_sha256)
PAYVER=$(version_of "$PAYROOT/Navi48Metal.bundle")
[ "$PAYVER" = "$NEW_VER" ] || die "payload bundle is version '$PAYVER', expected $NEW_VER"
codesign --verify --deep --strict "$PAYROOT/Navi48Metal.bundle" >/dev/null 2>&1 || die "payload signature invalid"
bash -n "$PAYROOT/accelerated-reboot-trial.sh" || die "payload guard fails bash -n"
grep -Fxq "PROFILE=$PROFILE_NEW" "$PAYROOT/accelerated-reboot-trial.sh" || die "payload guard is not the $PROFILE_NEW guard"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$PAYROOT/accelerated-reboot-trial.sh" "$PAYROOT/Navi48Metal.bundle" "$NEW_VER"
echo "  payload verified against manifest (bundle $NEW_VER, profile $PROFILE_NEW)"

[ -d "$LIVE" ] && [ ! -L "$LIVE" ] || die "live bundle missing: $LIVE"
LIVEVER=$(version_of "$LIVE")
[ "$LIVEVER" = "$OLD_VER" ] || die "live bundle is version '$LIVEVER', expected $OLD_VER"
[ -f "$GUARD" ] && [ ! -L "$GUARD" ] || die "live guard missing: $GUARD"
grep -Fxq "PROFILE=$PROFILE_OLD" "$GUARD" || die "live guard is not the $PROFILE_OLD guard"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$GUARD" "$LIVE" "$OLD_VER" \
  || die "live bundle hashes do not match the bundle-$OLD_VER guard constants"
echo "  live bundle is v$OLD_VER; hashes match the live guard"

LIVE_GUARD_SHA_NOW=$("$PY" -I "$ROOTTMP/payload_tool.py" hash "$GUARD")
[ "$LIVE_GUARD_SHA_NOW" = "$REC_LIVE_GUARD_SHA" ] \
  || die "live guard changed since staging (now $LIVE_GUARD_SHA_NOW, staged from $REC_LIVE_GUARD_SHA); rerun ./stage.sh"
echo "  live guard unchanged since staging ($LIVE_GUARD_SHA_NOW)"

[ -f "$STATE" ] || [ ! -e "$STATE" ] || die "unexpected boot-state entry"
STATUS_JSON=$("$PY" -I "$APP/boot-state.py" status --state "$STATE" --profile "$PROFILE_OLD") \
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
[ -e "$APP/disabled" ] && echo "  WARNING: $APP/disabled exists: the boot job will not activate bundle $NEW_VER on reboot"
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
ditto "$LIVE" "$BKDIR/Navi48Metal.bundle.v$OLD_VER"
cp -p "$GUARD" "$BKDIR/accelerated-reboot-trial.v$OLD_VER.sh"
if [ -e "$STATE" ]; then
  cp -p "$STATE" "$BKDIR/boot-state.pre-b$NEW_VER.json"
else
  echo "  no boot-state file to back up"
fi
cp -p "$PLIST" "$BKDIR/org.navi44.accelerated-trial.plist"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live.json"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BK_GPU" > "$ROOTTMP/bk-gpu.json"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BKDIR/Navi48Metal.bundle.v$OLD_VER" > "$ROOTTMP/bk-app.json"
"$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk-gpu.json"
"$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk-app.json"
chown -R root:wheel "$BK_GPU" "$BKDIR"
chmod -R go-w "$BK_GPU" "$BKDIR"
chmod 700 "$BKDIR"
echo "  GPU bundle backup: $BK_GPU"
echo "  app-support backup: $BKDIR"

echo "== 3 stage bundle $NEW_VER next to the live path, then atomic swap"
ditto "$PAYROOT/Navi48Metal.bundle" "$STAGE"
chown -R root:wheel "$STAGE"
chmod -R go-w "$STAGE"
"$PY" -I "$ROOTTMP/payload_tool.py" check "$MANIFEST" "Navi48Metal.bundle/" "$STAGE"
codesign --verify --deep --strict "$STAGE" >/dev/null 2>&1 || die "staged bundle signature invalid"
"$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$STAGE" >/dev/null
# The v$OLD_VER bundle is now at $STAGE. Move it to its backup name straight away (a rename, same volume).
mv "$STAGE" "$DISPLACED"
codesign --verify --deep --strict "$LIVE" >/dev/null 2>&1 || die "live bundle signature invalid after swap"
"$PY" -I "$ROOTTMP/payload_tool.py" check "$MANIFEST" "Navi48Metal.bundle/" "$LIVE"
[ "$(version_of "$LIVE")" = "$NEW_VER" ] || die "live bundle is not version $NEW_VER after swap"
echo "  live bundle is now $NEW_VER; displaced v$OLD_VER kept in $DISPLACED"

echo "== 4 install boot guard for bundle $NEW_VER"
cp "$PAYROOT/accelerated-reboot-trial.sh" "$NEWGUARD"
chown root:wheel "$NEWGUARD"
chmod 755 "$NEWGUARD"
bash -n "$NEWGUARD"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$NEWGUARD" "$LIVE" "$NEW_VER"
mv -f "$NEWGUARD" "$GUARD"
echo "  guard installed (v$OLD_VER copy kept in $BKDIR)"

echo "== 5 summary"
write_record
cat <<SUMMARY

BUNDLE $NEW_VER AND GUARD $NEW_VER ARE INSTALLED FOR THE NEXT BOOT. Nothing is activated yet.

Backups:
  v$OLD_VER bundle (GPUBundles):    $BK_GPU
  v$OLD_VER bundle + guard + state: $BKDIR
  displaced v$OLD_VER bundle:       $DISPLACED
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
  4. To return to v$OLD_VER at any time: sudo $W/rollback-trial.sh
SUMMARY
exit 0
