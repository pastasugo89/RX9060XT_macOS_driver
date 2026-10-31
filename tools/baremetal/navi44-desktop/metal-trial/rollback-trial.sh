#!/bin/bash
# rollback-trial.sh - return from the live Metal bundle N+1 to bundle N and its boot guard, from the
# newest trial-b<N+1>-backup directory (N+1 = live bundle version).
# Runs from Terminal, SSH, or a local login. Needs no GPU, does not touch WindowServer, does not reboot.
# Usage: sudo ./rollback-trial.sh [--backup DIR] [--reset-latch]
#   --backup DIR   trial-b<N+1>-backup directory to restore (default: newest trial-b<N+1>-backup-*)
#   --reset-latch  archive boot-state.json so the v<N> guard may activate on the next boot.
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
TS=$(date +%Y%m%d-%H%M%S)

# LIVEVER = N+1 (the bundle this rollback leaves); OLDVER = N (the bundle it restores).
LIVEVER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$LIVE/Contents/Info.plist" 2>/dev/null || true)
case "$LIVEVER" in ''|0|1|*[!0-9]*|0*) echo "STOP: live bundle version '$LIVEVER' cannot be rolled back (need an integer >= 2)" >&2; exit 1 ;; esac
OLDVER=$((LIVEVER - 1))
RBDIR="$APPDIR/trial-b$LIVEVER-rollback-$TS"
STAGE2="$GPUB/.Navi48Metal.rollback-staging-$TS"    # the restored v$OLDVER copy before the swap
DISPLACED2="$RBDIR/displaced-current.bundle"        # the v$LIVEVER bundle after the swap

ROOTTMP=""
BK_PROFILE=""
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

# The state on disk, printed on stderr after an abort.
report_state() {
  local guard_line
  guard_line=$(grep -m1 '^PROFILE=' "$GUARD" 2>/dev/null || echo "no PROFILE= line")
  echo "  final state:" >&2
  echo "    live bundle:  v$(version_of "$LIVE")  ($LIVE)" >&2
  echo "    live guard:   $guard_line  ($GUARD)" >&2
  for p in "$STAGE2" "$DISPLACED2"; do
    if [ -e "$p" ]; then echo "    copy left at: $p (v$(version_of "$p"))" >&2; fi
  done
  if [ -d "$RBDIR" ]; then echo "    rollback folder: $RBDIR" >&2; fi
}

# abort: put back what this run changed. It judges the state on disk, not flags, so it is right wherever
# the run stopped (a failed command, Ctrl-C, TERM, HUP). The backups are never touched.
abort() {
  local rc=$1 lv sv dv other
  trap - ERR
  trap '' INT HUP TERM
  set +e
  echo "" >&2
  echo "FAILED (rc=$rc): restoring the state from before this run" >&2

  # 1. Boot guard: if the v$OLDVER guard is in place, put back the guard this run replaced.
  if [ -n "$BK_PROFILE" ] && grep -Fxq "PROFILE=$BK_PROFILE" "$GUARD" 2>/dev/null; then
    if [ -f "$RBDIR/accelerated-reboot-trial.displaced.sh" ] \
       && cp "$RBDIR/accelerated-reboot-trial.displaced.sh" "$GUARD.restore" \
       && chown root:wheel "$GUARD.restore" && chmod 755 "$GUARD.restore" \
       && mv -f "$GUARD.restore" "$GUARD"; then
      echo "  guard: put back as it was (v$LIVEVER guard)" >&2
    else
      echo "  guard: MANUAL: the replaced guard is $RBDIR/accelerated-reboot-trial.displaced.sh" >&2
    fi
  else
    echo "  guard: unchanged" >&2
  fi
  if [ -f "$GUARD.restore" ]; then rm -f "$GUARD.restore"; fi

  # 2. Bundle: the live path must be v$LIVEVER again. The restored v$OLDVER copy is temporary.
  lv=$(version_of "$LIVE")
  if [ "$lv" = "$OLDVER" ]; then
    sv=$(version_of "$STAGE2")
    dv=$(version_of "$DISPLACED2")
    other=""
    if [ "$sv" = "$LIVEVER" ]; then other=$STAGE2
    elif [ "$dv" = "$LIVEVER" ]; then other=$DISPLACED2; fi
    if [ -z "$other" ]; then
      echo "  bundle: MANUAL: live is v$OLDVER and no v$LIVEVER copy was found (staging: $sv, displaced: $dv)" >&2
    elif "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$other" >/dev/null 2>&1; then
      if [ "$(version_of "$other")" = "$OLDVER" ]; then
        rm -rf "$other" && echo "  bundle: swapped back; live is v$LIVEVER again (temporary v$OLDVER copy removed)" >&2
      else
        echo "  bundle: swapped back; live is v$LIVEVER; '$other' holds v$(version_of "$other") and was kept" >&2
      fi
    else
      echo "  bundle: MANUAL: swap back failed; v$LIVEVER should be at $other, v$OLDVER at $LIVE" >&2
    fi
  elif [ "$lv" = "$LIVEVER" ]; then
    sv=$(version_of "$STAGE2")
    if [ -d "$STAGE2" ] && [ "$sv" != "$LIVEVER" ]; then
      rm -rf "$STAGE2" && echo "  bundle: live untouched (v$LIVEVER); the unused restored copy was removed" >&2
    else
      echo "  bundle: live untouched (v$LIVEVER)" >&2
    fi
  else
    echo "  bundle: MANUAL: live bundle is version '$lv' (expected $LIVEVER or $OLDVER)" >&2
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

echo "== 1 locate and verify the backup (live bundle $LIVEVER -> restore $OLDVER)"
ROOTTMP=$(mktemp -d /private/var/tmp/trial-b$LIVEVER-rollback.XXXXXX)
chmod 700 "$ROOTTMP"
cp -p "$W/lib/payload_tool.py" "$ROOTTMP/payload_tool.py"
[ -f "$GUARD" ] && [ ! -L "$GUARD" ] || die "live guard missing: $GUARD"
GUARD_VER=$("$PY" -I "$ROOTTMP/payload_tool.py" guard-version "$GUARD") || die "live guard has no single bundle_version check"
[ "$GUARD_VER" = "$LIVEVER" ] || die "live guard checks version $GUARD_VER, but the live bundle is $LIVEVER"
LIVE_PROFILE=$("$PY" -I "$ROOTTMP/payload_tool.py" guard-profile "$GUARD") || die "live guard has no single PROFILE= line"
if [ -z "$BACKUP" ]; then
  shopt -s nullglob
  candidates=("$APPDIR"/trial-b"$LIVEVER"-backup-*)
  shopt -u nullglob
  [ "${#candidates[@]}" -gt 0 ] || die "no trial-b$LIVEVER-backup-* directory found in $APPDIR"
  BACKUP=${candidates[${#candidates[@]}-1]}
fi
[ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] || die "backup is not a real directory: $BACKUP"
[ "$(stat -f '%u' "$BACKUP")" = 0 ] || die "backup is not owned by root: $BACKUP"
case "$(basename "$BACKUP")" in
  trial-b"$LIVEVER"-backup-*) ;;
  *) die "backup $(basename "$BACKUP") is not a trial-b$LIVEVER-backup-* directory (the live bundle is $LIVEVER)" ;;
esac
echo "  backup: $BACKUP"
BKBUNDLE=$BACKUP/Navi48Metal.bundle.v$OLDVER
BKGUARD=$BACKUP/accelerated-reboot-trial.v$OLDVER.sh
[ -d "$BKBUNDLE" ] && [ -f "$BKGUARD" ] || die "backup lacks the v$OLDVER bundle or guard"
[ "$(version_of "$BKBUNDLE")" = "$OLDVER" ] || die "backup bundle is not version $OLDVER"
codesign --verify --deep --strict "$BKBUNDLE" >/dev/null 2>&1 || die "backup bundle signature invalid"
BK_PROFILE=$("$PY" -I "$ROOTTMP/payload_tool.py" guard-profile "$BKGUARD") || die "backup guard has no single PROFILE= line"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$BKGUARD" "$BKBUNDLE" "$OLDVER" || die "backup guard hashes do not match backup bundle"
echo "  backup bundle v$OLDVER verified; backup guard verified ($BK_PROFILE)"

echo "== 2 current state (reported)"
echo "  live bundle version: $LIVEVER (guard $LIVE_PROFILE)"
STATUS_JSON=$("$PY" -I "$APP/boot-state.py" status --state "$STATE" --profile "$LIVE_PROFILE") \
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
[ -d "$LIVE" ] && [ ! -L "$LIVE" ] || die "live bundle missing: $LIVE"

echo "== 3 restore bundle $OLDVER (atomic swap; the current copy is kept, not deleted)"
"$PY" -I "$ROOTTMP/payload_tool.py" tree "$BKBUNDLE" > "$ROOTTMP/bk.json"
if "$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live.json" \
   && "$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/live.json" "$ROOTTMP/bk.json" >/dev/null 2>&1; then
  echo "  live bundle already equals the v$OLDVER backup; nothing to swap"
else
  ditto "$BKBUNDLE" "$STAGE2"
  chown -R root:wheel "$STAGE2"
  chmod -R go-w "$STAGE2"
  codesign --verify --deep --strict "$STAGE2" >/dev/null 2>&1 || die "restored copy signature invalid"
  "$PY" -I "$ROOTTMP/payload_tool.py" swap "$LIVE" "$STAGE2" >/dev/null
  # The v$LIVEVER bundle is now at $STAGE2. Move it to the rollback folder straight away (a rename).
  mv "$STAGE2" "$DISPLACED2"
  codesign --verify --deep --strict "$LIVE" >/dev/null 2>&1 || die "restored bundle signature invalid"
  "$PY" -I "$ROOTTMP/payload_tool.py" tree "$LIVE" > "$ROOTTMP/live-after.json"
  "$PY" -I "$ROOTTMP/payload_tool.py" compare "$ROOTTMP/bk.json" "$ROOTTMP/live-after.json" >/dev/null \
    || die "restored bundle differs from the v$OLDVER backup"
  echo "  live bundle restored to v$OLDVER; the replaced copy is in $DISPLACED2"
fi

echo "== 4 restore boot guard $OLDVER"
if [ -f "$GUARD" ]; then cp -p "$GUARD" "$RBDIR/accelerated-reboot-trial.displaced.sh"; fi
cp "$BKGUARD" "$GUARD.restore"
chown root:wheel "$GUARD.restore"
chmod 755 "$GUARD.restore"
bash -n "$GUARD.restore"
"$PY" -I "$ROOTTMP/payload_tool.py" guard-check "$GUARD.restore" "$LIVE" "$OLDVER"
mv -f "$GUARD.restore" "$GUARD"
echo "  guard v$OLDVER restored (replaced guard kept in $RBDIR)"

echo "== 5 boot latch"
if [ "$RESET_LATCH" = 1 ]; then
  if [ -e "$STATE" ]; then
    mv "$STATE" "$RBDIR/boot-state.before-reset.json"
    echo "  boot-state archived to $RBDIR/boot-state.before-reset.json (next boot may activate v$OLDVER)"
  else
    echo "  no boot-state file present"
  fi
else
  case "$PHASE" in
    absent|stable|stopped) echo "  latch '$PHASE': v$OLDVER guard may begin on the next boot" ;;
    *) echo "  latch '$PHASE': the v$OLDVER guard will REFUSE on the next boot (software mode, no crash)."
       echo "  To allow it, review the failure and rerun with --reset-latch." ;;
  esac
fi

[ -n "$ROOTTMP" ] && rm -rf "$ROOTTMP"
cat <<ROLLBACK_TEXT_END

ROLLBACK COMPLETE: bundle $OLDVER and guard $OLDVER are back. Reboot to run the v$OLDVER state.
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
