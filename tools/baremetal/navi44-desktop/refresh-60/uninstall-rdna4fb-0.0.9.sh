#!/bin/bash
# RDNA4FB 0.0.9 uninstaller: restores the 0.0.8 kext from a backup made by install-rdna4fb-0.0.9.sh and
# publishes an AuxiliaryKernelExtensions.kc rebuilt from the REAL /Library/Extensions with it. Refuses (and changes
# nothing) if the rebuild would drop a loaded or AuxKC-listed kext. Mirrors uninstall-audio.sh.
#
#   sudo uninstall-rdna4fb-0.0.9.sh [--backup DIR]        restore 0.0.8; reboot afterwards
#   uninstall-rdna4fb-0.0.9.sh --dry-run [--backup DIR]   read-only checks and the planned commands
#
# Without --backup, the newest install backup that holds the 0.0.8 kext is used.
# This script does not call sudo. Without root a real run stops at once. --dry-run writes nothing: it creates no
# temp dir, no backup, no kext copy and no kmutil write. It runs only shasum, codesign-free checks, PlistBuddy Print,
# find, awk, sort and kmutil showloaded.
# Exit status: 0 restored (or a dry run with every check passing), 1 refused or failed, 2 usage.
set -euo pipefail
export LC_ALL=C

DRY=0
BACKUP_ARG=""
usage() { echo "usage: $0 [--dry-run] [--backup DIR]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --backup)  [ $# -ge 2 ] || { usage; exit 2; }; BACKUP_ARG="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)         usage; exit 2 ;;
  esac
  shift
done

if [ "$DRY" = 0 ] && [ "$(id -u)" -ne 0 ]; then
  echo "STOP run with sudo (this script does not call sudo). Use --dry-run for the read-only checks."
  exit 1
fi

NEW_VER=0.0.9
NEW_BIN_SHA256=2235682d735eb629ad6a0899e0a2fcc8ea7e395f6aac9d4bc22a5eeadd0e6460
OLD_VER=0.0.8
OLD_BIN_SHA256=f51ac257f5ab4f2fa8136c9e7d8cbe0fa1205c4e911350a547d0f2a72f8b6468
OURID=com.hackintosh.RDNA4FB
BIN=Contents/MacOS/RDNA4FB
EXT=/Library/Extensions
# AppleMobileDevice.kext is published in the live AuxKC from this repository, so the rebuilds must include it (the drop-guard
# refuses a rebuild that loses it; without this repository it would refuse every run).
APPLE_EXT=/Library/Apple/System/Library/Extensions
DST="$EXT/RDNA4FB-0.0.8-n44.kext"
BOOT=/System/Library/KernelCollections/BootKernelExtensions.kc
SYS=/System/Library/KernelCollections/SystemKernelExtensions.kc
AKC=/Library/KernelCollections/AuxiliaryKernelExtensions.kc
NEWAKC="$AKC.rdna4fb-0.0.9-new"
BKROOT="/Library/Application Support/Navi44/rdna4fb-0.0.9-backup"
TS=$(date +%Y%m%d-%H%M%S)
BK="$BKROOT/uninstall-$TS"
PLIST=/usr/libexec/PlistBuddy

DRY_FAIL=0
die()     { echo "STOP $*"; exit 1; }
refuse()  { if [ "$DRY" = 1 ]; then echo "DRY-RUN would STOP: $*"; DRY_FAIL=1; else die "$*"; fi; }
hash_of() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }
plist_get() { "$PLIST" -c "Print :$2" "$1/Contents/Info.plist" 2>/dev/null; }
loaded_aux() {
  kmutil showloaded --collection aux --list-only 2>/dev/null |
    awk '/\(/ { for (i=2;i<=NF;i++) if ($i ~ /^\(/) { print $(i-1); break } }' | sort -u
}
akc_ids()   { kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' 'NF>=3{print $1}' | sort -u; }
akc_paths() { kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' 'NF>=3 && $3 ~ /^\/Library\// {print $1}' | sort -u; }
akc_version() { kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' -v id="$2" 'NF>=3 && $1==id {print $2; exit}'; }

# The install backup to restore from: the one given, else the newest that holds the 0.0.8 kext. The glob is
# quoted only in its prefix and keeps spaces in the path (no word splitting); it sorts ascending under LC_ALL=C.
BACKUP="$BACKUP_ARG"
if [ -z "$BACKUP" ]; then
  for d in "$BKROOT"/[0-9]*; do
    if [ -d "$d/RDNA4FB-0.0.8-n44.kext" ]; then BACKUP="$d"; fi
  done
fi

echo "== RDNA4FB $NEW_VER uninstall ($([ "$DRY" = 1 ] && echo 'DRY RUN: read-only checks' || echo 'REAL RUN'))"

echo "1. install backup (source of the 0.0.8 kext)"
BK_OLD=""; BK_AKC=""
if [ -n "$BACKUP" ] && [ -d "$BACKUP" ]; then
  echo "   $BACKUP"
  BK_OLD="$BACKUP/RDNA4FB-0.0.8-n44.kext"
  BK_AKC="$BACKUP/AuxiliaryKernelExtensions.kc.pre"
  if [ -f "$BK_OLD/$BIN" ] && [ "$(hash_of "$BK_OLD/$BIN")" = "$OLD_BIN_SHA256" ]; then
    echo "   0.0.8 kext present, binary sha256 $OLD_BIN_SHA256 (as recorded)"
  else
    refuse "$BK_OLD is missing or is not the recorded 0.0.8 build"
  fi
  [ -f "$BK_AKC" ] || refuse "backup AuxKC copy missing: $BK_AKC"
else
  refuse "no install backup found under $BKROOT (pass --backup DIR)"
fi

echo "2. installed kext at $DST (must be the 0.0.9 build)"
if [ -d "$DST" ] && [ -f "$DST/$BIN" ] && [ "$(hash_of "$DST/$BIN")" = "$NEW_BIN_SHA256" ]; then
  echo "   present: 0.0.9 binary sha256 $NEW_BIN_SHA256"
else
  refuse "$DST is not the 0.0.9 kext (sha256 $NEW_BIN_SHA256 expected): nothing to remove, or another build"
fi

echo "3. ownership: every entry in $EXT must be root:wheel"
BAD=$(find "$EXT" -mindepth 1 -maxdepth 1 \( ! -user root -o ! -group wheel \) -print)
[ -z "$BAD" ] || refuse "these entries in $EXT are not root:wheel (fix ownership yourself, nothing changed): $BAD"

echo "4. AuxKC and staging names"
[ -f "$AKC" ] || refuse "AuxKC missing: $AKC"
[ ! -e "$NEWAKC" ] || refuse "$NEWAKC exists; remove it first"
[ ! -e "$BK" ] || refuse "$BK exists (timestamp clash); retry"

echo "5. loaded kexts (the drop-guard input)"
ALL_N=$(kmutil showloaded --list-only 2>/dev/null | awk '/\(/' | wc -l | tr -d ' ') ||
  refuse "kmutil showloaded --list-only failed"
LOADED=$(loaded_aux) || refuse "kmutil showloaded --collection aux --list-only failed"
echo "   loaded kexts, all collections: $ALL_N"
echo "   loaded aux kexts (all must survive the AuxKC rebuild):"
printf '     %s\n' $LOADED

if [ "$DRY" = 1 ]; then
  echo
  if [ "$DRY_FAIL" = 0 ]; then
    echo "DRY-RUN: every read-only check passed. Nothing was written."
  else
    echo "DRY-RUN: $DRY_FAIL check(s) would make a real run refuse. Nothing was written."
  fi
  echo "Planned commands for a real run (run with sudo; not executed by --dry-run):"
  cat <<PLAN
  mkdir -p "$BK"; log to "$BK/uninstall.log"
  cp -p "$AKC" "$BK/AuxiliaryKernelExtensions.kc.pre-uninstall"
  kmutil inspect -a x86_64 -A "$AKC" --show-extension-info > "$BK/akc-pre-extensions.txt"
  mv "$DST" "$BK/RDNA4FB-0.0.9-n44.kext"          # the 0.0.9 kext is moved to this backup, not deleted
  cp -R "$BK_OLD" "$DST"; chown -R root:wheel "$DST"; chmod -R go-w "$DST"   # 0.0.8 restored
  preflight: root-owned temp repo = copy of $EXT/*.kext (with the restored 0.0.8)
             kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository <temp repo> --repository "$APPLE_EXT" -A <temp aux.kc> -z
             drop-guard (loaded aux + AuxKC /Library ids, minus $OURID); $OURID must be $OLD_VER
  live:      kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$EXT" --repository "$APPLE_EXT" -A "$NEWAKC" -z
             drop-guard as above; $OURID must be $OLD_VER
  publish:   chown root:wheel "$NEWAKC"; chmod 644 "$NEWAKC"; mv -f "$NEWAKC" "$AKC"
  then reboot. Rollback on failure: the 0.0.9 kext is moved back.
PLAN
  [ "$DRY_FAIL" = 0 ]
  exit $?
fi

# ---- real run (root) -------------------------------------------------------------------------------------------
W=$(mktemp -d /var/tmp/rdna4fb-0.0.9-uninstall.XXXXXX)
SWAPPED=0; AKC_REPLACED=0
cleanup() {
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "FAILED (exit $rc): rolling back"
    rm -f "$NEWAKC"
    if [ "$AKC_REPLACED" = 0 ] && [ "$SWAPPED" = 1 ]; then
      rm -rf "$DST"
      mv "$BK/RDNA4FB-0.0.9-n44.kext" "$DST" && echo "  0.0.9 kext restored to $DST"
    fi
    if [ "$AKC_REPLACED" = 1 ]; then
      echo "  AKC was replaced; restore: cp -p $BK/AuxiliaryKernelExtensions.kc.pre-uninstall $AKC"
    fi
  fi
  rm -rf "$W"
  exit $rc
}
trap cleanup EXIT

mkdir -p "$BK" || die "cannot create $BK"
exec > >(tee -a "$BK/uninstall.log") 2>&1
echo "uninstall $NEW_VER started $(date)"
echo "backup used: $BACKUP   log: $BK"

cp -p "$AKC" "$BK/AuxiliaryKernelExtensions.kc.pre-uninstall" || die "cannot back up AKC"
kmutil inspect -a x86_64 -A "$AKC" --show-extension-info > "$BK/akc-pre-extensions.txt" 2>/dev/null || die "cannot inspect current AKC"
akc_paths "$AKC" > "$W/pre-ours.txt"
loaded_aux > "$W/loaded.txt" || die "kmutil showloaded failed"
echo "currently loaded aux: $(tr '\n' ' ' < "$W/loaded.txt")"

# Move the 0.0.9 kext out (kept in this backup), then restore the 0.0.8 kext from the install backup.
mv "$DST" "$BK/RDNA4FB-0.0.9-n44.kext" || die "cannot move the 0.0.9 kext to the backup"
SWAPPED=1
cp -R "$BK_OLD" "$DST" || die "restore the 0.0.8 kext"
chown -R root:wheel "$DST" && chmod -R go-w "$DST" || die "kext permissions"
[ "$(hash_of "$DST/$BIN")" = "$OLD_BIN_SHA256" ] || die "restored 0.0.8 binary has the wrong hash"
echo "restored $DST ($OLD_VER)"

# Preflight only: root-owned temp repo of the real /Library/Extensions (with the restored 0.0.8), drop-guard.
T="$W/preflight"; mkdir -p "$T/repo"
for k in "$EXT"/*.kext; do [ -d "$k" ] && cp -R "$k" "$T/repo/"; done
chown -R root:wheel "$T/repo" && chmod -R go-w "$T/repo" || die "preflight permissions"
kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$T/repo" --repository "$APPLE_EXT" -A "$T/aux.kc" -z > "$T/kmutil.log" 2>&1 ||
  { tail -20 "$T/kmutil.log"; die "preflight build failed (kext restored to 0.0.9 by rollback)"; }
[ -s "$T/aux.kc" ] || die "preflight produced no collection"
akc_ids "$T/aux.kc" > "$W/pre-new.txt"
[ -s "$W/pre-new.txt" ] || die "parser extracted no IDs from preflight"
cat "$W/loaded.txt" "$W/pre-ours.txt" | { grep -v -x "$OURID" || true; } | sort -u > "$W/required-pre.txt"
M=$(comm -23 "$W/required-pre.txt" "$W/pre-new.txt" || true)
[ -z "$M" ] || die "preflight would drop: $M"
[ "$(akc_version "$T/aux.kc" "$OURID")" = "$OLD_VER" ] || die "preflight: $OURID is not $OLD_VER"
echo "preflight ok"

# Live build from the real repository, then the same guard.
kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$EXT" --repository "$APPLE_EXT" -A "$NEWAKC" -z > "$W/kmutil-live.log" 2>&1 ||
  { tail -20 "$W/kmutil-live.log"; die "live build failed (kext restored to 0.0.9 by rollback)"; }
[ -s "$NEWAKC" ] || die "live build produced no output"
akc_ids "$NEWAKC" > "$W/new.txt"
[ -s "$W/new.txt" ] || die "parser extracted no IDs from the new AKC"
cat "$W/loaded.txt" "$W/pre-ours.txt" | { grep -v -x "$OURID" || true; } | sort -u > "$W/required.txt"
M=$(comm -23 "$W/required.txt" "$W/new.txt" || true)
[ -z "$M" ] || die "live build would drop: $M"
grep -qx "$OURID" "$W/new.txt" || die "$OURID absent from the new AKC"
[ "$(akc_version "$NEWAKC" "$OURID")" = "$OLD_VER" ] || die "$OURID in the new AKC is not $OLD_VER"
echo "guard ok: $(wc -l < "$W/required.txt" | tr -d ' ') required kexts present in new AKC"
cp "$W/kmutil-live.log" "$W/loaded.txt" "$W/pre-ours.txt" "$W/new.txt" "$W/required.txt" "$BK/" || true

# Publish.
chown root:wheel "$NEWAKC" && chmod 644 "$NEWAKC" || die "AKC permissions"
mv -f "$NEWAKC" "$AKC" || die "cannot publish AKC"; AKC_REPLACED=1
echo "OK: 0.0.8 restored at $DST and the AuxKC rebuilt. Reboot to load it."
echo "The 0.0.9 kext is kept in: $BK/RDNA4FB-0.0.9-n44.kext"
