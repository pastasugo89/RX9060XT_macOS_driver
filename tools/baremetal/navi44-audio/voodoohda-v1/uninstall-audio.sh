#!/bin/bash
# Removes VoodooHDA from /Library/Extensions and publishes an AKC rebuilt from the real
# /Library/Extensions without it. Refuses (and changes nothing) if the rebuild would drop
# any loaded or AKC-listed kext. Mirrors install-audio.sh.
# Run with: sudo /path/to/uninstall-audio.sh   (reboot afterwards)
set -euo pipefail
export LC_ALL=C

[ "$(id -u)" -eq 0 ] || { echo "STOP run with sudo"; exit 1; }
EXT=/Library/Extensions
DST="$EXT/VoodooHDA.kext"
OURID=org.voodoo.driver.VoodooHDA
BOOT=/System/Library/KernelCollections/BootKernelExtensions.kc
SYS=/System/Library/KernelCollections/SystemKernelExtensions.kc
AKC=/Library/KernelCollections/AuxiliaryKernelExtensions.kc
NEWAKC="$AKC.audio-v1-new"
TS=$(date +%Y%m%d-%H%M%S)
BK="/Library/Application Support/Navi44/audio-v1-backup/uninstall-$TS"
W=$(mktemp -d /var/tmp/audio-v1-uninstall.XXXXXX)
MOVED=0; AKC_REPLACED=0

die() { echo "STOP $*"; exit 1; }
cleanup() {
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "FAILED (exit $rc): rolling back"
    rm -f "$NEWAKC"
    if [ "$MOVED" = 1 ] && [ "$AKC_REPLACED" = 0 ] && [ ! -e "$DST" ]; then mv "$BK/VoodooHDA.kext" "$DST" && echo "  kext restored"; fi
    [ "$AKC_REPLACED" = 1 ] && echo "  AKC was replaced; restore: cp -p $BK/AuxiliaryKernelExtensions.kc.pre $AKC"
  fi
  rm -rf "$W"
}
trap cleanup EXIT

akc_ids()  { kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' 'NF>=3{print $1}' | sort -u; }
akc_paths(){ kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' 'NF>=3 && $3 ~ /^\/Library\// {print $1}' | sort -u; }

[ -d "$DST" ] || die "$DST not present; nothing to remove"
[ ! -e "$NEWAKC" ] || die "$NEWAKC exists; remove it first"

# Every entry in /Library/Extensions must be root:wheel (never chown others' kexts).
BAD=$(find "$EXT" -mindepth 1 -maxdepth 1 \( ! -user root -o ! -group wheel \) -print)
[ -z "$BAD" ] || die "these entries in $EXT are not root:wheel (fix ownership yourself, nothing changed):
$BAD"

kmutil showloaded --collection aux 2>/dev/null | awk '/\(/ { for (i=1;i<=NF;i++) if ($i ~ /^(com|org|io)\./) { print $i; break } }' | sort -u > "$W/loaded.txt"
mkdir -p "$BK" || die "cannot create $BK"
cp -p "$AKC" "$BK/AuxiliaryKernelExtensions.kc.pre" || die "cannot back up AKC"
kmutil inspect -a x86_64 -A "$AKC" --show-extension-info 2>/dev/null > "$BK/akc-pre-extensions.txt" || die "cannot inspect current AKC"
akc_paths "$AKC" > "$W/pre-ours.txt"
cat "$W/loaded.txt" "$W/pre-ours.txt" | grep -v -x "$OURID" | sort -u > "$W/required.txt"
echo "backup: $BK"

# Preflight: root-owned temp repo without our kext (not published).
T="$W/preflight"; mkdir -p "$T/repo"
for k in "$EXT"/*.kext; do [ -d "$k" ] || continue; [ "$k" = "$DST" ] && continue; cp -R "$k" "$T/repo/"; done
chown -R root:wheel "$T/repo" && chmod -R go-w "$T/repo" || die "preflight permissions"
kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$T/repo" -A "$T/aux.kc" -z > "$T/kmutil.log" 2>&1 \
  || { tail -20 "$T/kmutil.log"; die "preflight build failed (nothing changed)"; }
akc_ids "$T/aux.kc" > "$W/pre-new.txt"
[ -s "$W/pre-new.txt" ] || die "parser extracted no IDs from preflight (nothing changed)"
M=$(comm -23 "$W/required.txt" "$W/pre-new.txt" || true)
[ -z "$M" ] || die "preflight would drop: $M (nothing changed)"
echo "preflight ok"

# Move our kext into the backup (move, not delete), then publish the real-repository build.
mv "$DST" "$BK/VoodooHDA.kext" || die "cannot move kext to backup"; MOVED=1
kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$EXT" -A "$NEWAKC" -z > "$W/kmutil-live.log" 2>&1 \
  || { tail -20 "$W/kmutil-live.log"; die "live build failed (kext restored)"; }
[ -s "$NEWAKC" ] || die "live build produced no output (kext restored)"
akc_ids "$NEWAKC" > "$W/new.txt"
[ -s "$W/new.txt" ] || die "parser extracted no IDs from new AKC (kext restored)"
M=$(comm -23 "$W/required.txt" "$W/new.txt" || true)
[ -z "$M" ] || die "live build would drop: $M (kext restored)"
grep -qx "$OURID" "$W/new.txt" && die "$OURID still in new AKC (kext restored)"
echo "guard ok: $(wc -l < "$W/required.txt") required kexts present in new AKC"

chown root:wheel "$NEWAKC" && chmod 644 "$NEWAKC" || die "AKC permissions"
mv -f "$NEWAKC" "$AKC" || die "cannot publish AKC"; AKC_REPLACED=1
echo "OK VoodooHDA removed and AKC rebuilt. Reboot to take effect."
echo "Kext kept in backup: $BK/VoodooHDA.kext ; previous AKC: $BK/AuxiliaryKernelExtensions.kc.pre"
