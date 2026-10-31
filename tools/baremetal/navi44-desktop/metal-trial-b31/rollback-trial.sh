#!/bin/bash
# rollback-trial.sh - return to Metal bundle 30 and its boot guard, from the trial-b31 backup.
# Runs from Terminal, SSH, or a local login. Needs no GPU, does not touch WindowServer, does not reboot.
# Usage: sudo ./rollback-trial.sh [--backup DIR] [--reset-latch]
#   --backup DIR   trial-b31 backup to restore (default: newest trial-b31-backup-* directory)
#   --reset-latch  archive boot-state.json so the v30 guard may activate on the next boot.
#                  Use only after reviewing why the latch is pending/failed.
# This package does not touch audio.
set -Eeuo pipefail
export LC_ALL=C
umask 022
PATH=/usr/bin:/bin:/usr/sbin:/sbin

[ "$(id -u)" -eq 0 ] || { echo "STOP: run with sudo: sudo $0" >&2; exit 1; }

BACKUP=""
RESET_LATCH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --backup) [ $# -ge 2 ] || { echo "STOP: --backup needs a directory" >&2; exit 1; }; BACKUP=$2; shift ;;
    --reset-latch) RESET_LATCH=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "STOP: unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

W=$(cd "$(dirname "$0")" && pwd)
PY=/usr/bin/python3
GPUB=/Library/GPUBundles
LIVE=$GPUB/Navi48Metal.bundle
APPDIR='/Library/Application Support/Navi44'
APP="$APPDIR/accelerated-trial"
GUARD="$APP/accelerated-reboot-trial.sh"
STATE="$APP/boot-state.json"
PROFILE_V30=stage30-vonly-v1
PROFILE_V31=stage31-msaa-iosurface-v1
TS=$(date +%Y%m%d-%H%M%S)
RBDIR="$APPDIR/trial-b31-rollback-$TS"
STAGE2="$GPUB/.Navi48Metal.rollback-staging-$TS"
ROOTTMP=""
SWAPPED=0
OTHER=""
GUARD_REPLACED=0

die() { echo "STOP: $*" >&2; abort 1; }

abort() {
  local rc=$1
  trap - ERR
  set +e
  echo "" >&2
  echo "FAILED (rc=$rc): restoring the state from before this run" >&2
  if [ "$GUARD_REPLACED" = 1 ] && [ -f "$RBDIR/accelerated-reboot-trial.displaced.sh" ]; then
    cp "$RBDIR/accelerated-reboot-trial.displaced.sh" "$GUARD.restore" && chown root:wheel "$GUARD.restore" \
      && chmod 755 "$GUARD.restore" && mv -f "$GUARD.restore" "$GUARD" && echo "  guard put back as it was"
  fi
  if [ "$SWAPPED" = 1 ] && [ -n "$OTHER" ] && [ -e "$OTHER" ]; then
    if "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$OTHER" >/dev/null; then
      echo "  bundle put back as it was"
    else
      echo "  MANUAL: bundle state unclear; the other copy is at $OTHER" >&2
    fi
  fi
  if [ "$SWAPPED" = 0 ] && [ -n "$STAGE2" ] && [ -d "$STAGE2" ] && [ "${STAGE2#"$GPUB/.Navi48Metal.rollback-staging-"}" != "$STAGE2" ]; then
    rm -rf "$STAGE2" && echo "  unused rollback staging copy removed"
  fi
  if [ "$GUARD_REPLACED" = 0 ] && [ -f "$GUARD.restore" ]; then rm -f "$GUARD.restore"; fi
  [ -n "$ROOTTMP" ] && [ -d "$ROOTTMP" ] && rm -rf "$ROOTTMP"
  exit "$rc"
}
trap 'abort $?' ERR
trap 'rc=$?; [ -n "$ROOTTMP" ] && [ -d "$ROOTTMP" ] && rm -rf "$ROOTTMP"; exit $rc' EXIT

echo "== 1 locate and verify the v30 backup"
if [ -z "$BACKUP" ]; then
  shopt -s nullglob
  candidates=("$APPDIR"/trial-b31-backup-*)
  shopt -u nullglob
  [ "${#candidates[@]}" -gt 0 ] || die "no trial-b31-backup-* directory found in $APPDIR"
  BACKUP=${candidates[${#candidates[@]}-1]}
fi
[ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] || die "backup is not a real directory: $BACKUP"
[ "$(stat -f '%u' "$BACKUP")" = 0 ] || die "backup is not owned by root: $BACKUP"
echo "  backup: $BACKUP"

ROOTTMP=$(mktemp -d /private/var/tmp/trial-b31-rollback.XXXXXX)
chmod 700 "$ROOTTMP"
cp -p "$W/lib/payload_tool.py" "$ROOTTMP/payload_tool.py"
BKBUNDLE=$BACKUP/Navi48Metal.bundle.v30
BKGUARD=$BACKUP/accelerated-reboot-trial.v30.sh
[ -d "$BKBUNDLE" ] && [ -f "$BKGUARD" ] || die "backup lacks the v30 bundle or guard"
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$BKBUNDLE/Contents/Info.plist")" = 30 ] \
  || die "backup bundle is not version 30"
codesign --verify --deep --strict "$BKBUNDLE" >/dev/null 2>&1 || die "backup bundle signature invalid"
grep -Fxq "PROFILE=$PROFILE_V30" "$BKGUARD" || die "backup guard is not the $PROFILE_V30 guard"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$BKGUARD" "$BKBUNDLE" 30 || die "backup guard hashes do not match backup bundle"
echo "  backup bundle v30 verified; backup guard verified"

echo "== 2 current state (reported)"
LIVEVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist" 2>/dev/null || echo "missing")
echo "  live bundle version: $LIVEVER"
STATUS_JSON=$("$PY" -I "$APP/boot-state.py" status --state "$STATE" --profile "$PROFILE_V31") \
  || die "cannot read boot-state"
PHASE=$(printf '%s' "$STATUS_JSON" | "$PY" -I "$ROOTTMP/payload_tool.py" phase)
echo "  boot latch phase: $PHASE"
for p in /private/tmp/n48m-off /private/tmp/n48m-headless-no "$APP/disabled"; do
  if [ -e "$p" ] || [ -L "$p" ]; then echo "  PRESENT $p"; else echo "  absent  $p"; fi
done

for p in "$RBDIR" "$STAGE2"; do
  [ ! -e "$p" ] && [ ! -L "$p" ] || die "target already exists: $p"
done
mkdir -m 700 "$RBDIR"

echo "== 3 restore bundle v30 (atomic swap; the current copy is kept, not deleted)"
if [ -d "$LIVE" ] && [ ! -L "$LIVE" ] && "$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live.json" \
   && "$PY" -I "$ROOTTMP/payload_tool.py" tree "$BKBUNDLE" > "$ROOTTMP/bk.json" \
   && "$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk.json" >/dev/null 2>&1; then
  echo "  live bundle already equals the v30 backup; nothing to swap"
else
  ditto "$BKBUNDLE" "$STAGE2"
  chown -R root:wheel "$STAGE2"
  chmod -R go-w "$STAGE2"
  codesign --verify --deep --strict "$STAGE2" >/dev/null 2>&1 || die "restored copy signature invalid"
  if [ -d "$LIVE" ]; then
    OTHER=$STAGE2
    "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$STAGE2" >/dev/null
    SWAPPED=1
    mv "$STAGE2" "$RBDIR/displaced-current.bundle"
    OTHER=$RBDIR/displaced-current.bundle
  else
    mv "$STAGE2" "$LIVE"
  fi
  codesign --verify --deep --strict "$LIVE" >/dev/null 2>&1 || die "restored bundle signature invalid"
  "$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live-after.json"
  "$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/bk.json" "$ROOTTMP/live-after.json" >/dev/null \
    || die "restored bundle differs from the v30 backup"
  echo "  live bundle restored to v30; the replaced copy is in $OTHER"
fi

echo "== 4 restore boot guard v30"
if [ -f "$GUARD" ]; then cp -p "$GUARD" "$RBDIR/accelerated-reboot-trial.displaced.sh"; fi
cp "$BKGUARD" "$GUARD.restore"
chown root:wheel "$GUARD.restore"
chmod 755 "$GUARD.restore"
bash -n "$GUARD.restore"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$GUARD.restore" "$LIVE" 30
mv -f "$GUARD.restore" "$GUARD"
GUARD_REPLACED=1
echo "  guard v30 restored (replaced guard kept in $RBDIR)"

echo "== 5 boot latch"
if [ "$RESET_LATCH" = 1 ]; then
  if [ -e "$STATE" ]; then
    mv "$STATE" "$RBDIR/boot-state.before-reset.json"
    echo "  boot-state archived to $RBDIR/boot-state.before-reset.json (next boot may activate v30)"
  else
    echo "  no boot-state file present"
  fi
else
  case "$PHASE" in
    absent|stable|stopped) echo "  latch '$PHASE': v30 guard may begin on the next boot" ;;
    *) echo "  latch '$PHASE': the v30 guard will REFUSE on the next boot (software mode, no crash)."
       echo "  To allow it, review the failure and rerun with --reset-latch." ;;
  esac
fi

[ -n "$ROOTTMP" ] && rm -rf "$ROOTTMP"
cat <<ROLLBACK_TEXT_END

ROLLBACK COMPLETE: bundle 30 and guard 30 are back. Reboot to run the v30 state.
Folder for this rollback: $RBDIR

Emergency options if the desktop is unusable after reboot:
  - Run this script again from Terminal or SSH (it needs no GPU and no WindowServer).
  - Stop the next boot from activating the GPU without restoring files:
      sudo touch "$APP/disabled"     (the guard refuses before changing anything)
      remove it later with: sudo rm "$APP/disabled"
  - /private/tmp/n48m-off is the runtime kill file written by the guard. The next boot archives it and
    continues, so it does NOT block the next boot by itself; use the "disabled" marker for that.
  - OpenCore picker: F11 at power-on opens the menu (see research/reports/baremetal_bringup.md).
    Shift safe-boot was not verified (research/reports/recovery_install_readonly_20261026.md).
    Do not reset NVRAM.
ROLLBACK_TEXT_END
exit 0
