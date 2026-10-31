#!/bin/bash
# Installs VoodooHDA 3.6.8 (Navi44 analog personality) into /Library/Extensions and
# publishes an AuxiliaryKernelExtensions.kc built from the REAL /Library/Extensions.
# Mirrors NullMoth install.sh: a root-owned temp repo is only a preflight; the published
# AKC is built with --repository /Library/Extensions into "$AKC.audio-v1-new".
# Run with: sudo /path/to/install-audio.sh     (reboot + user approval afterwards)
set -euo pipefail
export LC_ALL=C

[ "$(id -u)" -eq 0 ] || { echo "STOP run with sudo"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/kext/VoodooHDA.kext"
EXT=/Library/Extensions
DST="$EXT/VoodooHDA.kext"
OURID=org.voodoo.driver.VoodooHDA
BOOT=/System/Library/KernelCollections/BootKernelExtensions.kc
SYS=/System/Library/KernelCollections/SystemKernelExtensions.kc
AKC=/Library/KernelCollections/AuxiliaryKernelExtensions.kc
NEWAKC="$AKC.audio-v1-new"
TS=$(date +%Y%m%d-%H%M%S)
BK="/Library/Application Support/Navi44/audio-v1-backup/$TS"
W=$(mktemp -d /var/tmp/audio-v1-install.XXXXXX)
NEWKEXT=0; AKC_REPLACED=0

die() { echo "STOP $*"; exit 1; }
cleanup() {
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "FAILED (exit $rc): rolling back"
    rm -f "$NEWAKC"
    if [ "$AKC_REPLACED" = 0 ] && [ "$NEWKEXT" = 1 ]; then rm -rf "$DST"; echo "  removed $DST"; fi
    [ "$AKC_REPLACED" = 1 ] && echo "  AKC was replaced; restore: cp -p $BK/AuxiliaryKernelExtensions.kc.pre $AKC"
  fi
  rm -rf "$W"
}
trap cleanup EXIT

# inventory of bundle IDs in an AKC file (tab-separated: id, version, path)
akc_ids()  { kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' 'NF>=3{print $1}' | sort -u; }
akc_paths(){ kmutil inspect -a x86_64 -A "$1" --show-extension-info 2>/dev/null | awk -F'\t' 'NF>=3 && $3 ~ /^\/Library\// {print $1}' | sort -u; }

# 1. Staged kext: hashes and signature.
[ -d "$SRC" ] || die "staged kext missing: $SRC"
(cd "$SRC" && find . -type f | sort | xargs shasum -a 256 | diff - "$HERE/kext/SHA256SUMS" >/dev/null) \
  || die "staged kext does not match SHA256SUMS"
codesign --verify --deep --strict "$SRC" >/dev/null 2>&1 || die "staged kext signature invalid"

# 2. Refuse if already installed.
[ ! -e "$DST" ] || die "$DST already exists; run uninstall-audio.sh first"
[ ! -e "$NEWAKC" ] || die "$NEWAKC exists; remove it first"

# 3. Every kext in /Library/Extensions must already be root:wheel. Never chown other owners' kexts.
BAD=$(find "$EXT" -mindepth 1 -maxdepth 1 \( ! -user root -o ! -group wheel \) -print)
[ -z "$BAD" ] || die "these entries in $EXT are not root:wheel (fix ownership yourself, nothing changed):
$BAD"

# 4. Record currently loaded aux kexts (must all survive).
kmutil showloaded --collection aux 2>/dev/null | awk '/\(/ { for (i=1;i<=NF;i++) if ($i ~ /^(com|org|io)\./) { print $i; break } }' | sort -u > "$W/loaded.txt"
echo "currently loaded aux: $(tr '\n' ' ' < "$W/loaded.txt")"

# 5. Backup (copies only).
mkdir -p "$BK" || die "cannot create $BK"
cp -p "$AKC" "$BK/AuxiliaryKernelExtensions.kc.pre" || die "cannot back up AKC"
kmutil inspect -a x86_64 -A "$AKC" --show-extension-info 2>/dev/null > "$BK/akc-pre-extensions.txt" || die "cannot inspect current AKC"
akc_paths "$AKC" > "$W/pre-ours.txt"
echo "backup: $BK"

# 6. Install our kext into the real location (root:wheel, no group/world write).
cp -R "$SRC" "$DST" || die "copy kext"; NEWKEXT=1
chown -R root:wheel "$DST" && chmod -R go-w "$DST" || die "kext permissions"

# 7. Preflight only: root-owned temp repo, drop-guard. Not published.
T="$W/preflight"; mkdir -p "$T/repo"
for k in "$EXT"/*.kext; do [ -d "$k" ] && cp -R "$k" "$T/repo/"; done
chown -R root:wheel "$T/repo" && chmod -R go-w "$T/repo" || die "preflight permissions"
kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$T/repo" -A "$T/aux.kc" -z > "$T/kmutil.log" 2>&1 \
  || { tail -20 "$T/kmutil.log"; die "preflight kernel collection build failed (nothing published)"; }
[ -s "$T/aux.kc" ] || die "preflight produced no collection"
akc_ids "$T/aux.kc" > "$W/pre-new.txt"
cat "$W/loaded.txt" "$W/pre-ours.txt" | grep -v -x "$OURID" | sort -u > "$W/required-pre.txt"
M=$(comm -23 "$W/required-pre.txt" "$W/pre-new.txt" || true)
[ -z "$M" ] || die "preflight would drop: $M"
grep -qx "$OURID" "$W/pre-new.txt" || die "preflight: $OURID absent"
echo "preflight ok"

# 8. Publish build: real repository, written next to the live AKC, then guarded.
kmutil create -n aux --volume-root / --allow-missing-kdk -B "$BOOT" -S "$SYS" --repository "$EXT" -A "$NEWAKC" -z > "$W/kmutil-live.log" 2>&1 \
  || { tail -20 "$W/kmutil-live.log"; die "live kernel collection build failed (nothing published)"; }
[ -s "$NEWAKC" ] || die "live build produced no output"
akc_ids "$NEWAKC" > "$W/new.txt"
[ -s "$W/new.txt" ] || die "parser extracted no bundle IDs from the new AKC"
cat "$W/loaded.txt" "$W/pre-ours.txt" | grep -v -x "$OURID" | sort -u > "$W/required.txt"
M=$(comm -23 "$W/required.txt" "$W/new.txt" || true)
[ -z "$M" ] || die "live build would drop: $M"
grep -qx "$OURID" "$W/new.txt" || die "$OURID absent from new AKC"
echo "guard ok: $(wc -l < "$W/required.txt") required kexts present in new AKC"
echo "--- new AKC entries for GPU kexts:"
kmutil inspect -a x86_64 -A "$NEWAKC" --show-extension-info 2>/dev/null | grep -E $'com\\.hackintosh\\.RDNA4FB\t|com\\.navi48\\.accelprobe\t' || die "GPU kext line missing from new AKC"

# 9. Publish.
chown root:wheel "$NEWAKC" && chmod 644 "$NEWAKC" || die "AKC permissions"
mv -f "$NEWAKC" "$AKC" || die "cannot publish AKC"; AKC_REPLACED=1
echo "OK installed. Reboot now, then approve VoodooHDA in System Settings > Privacy & Security if prompted."
echo "Rollback: sudo $HERE/uninstall-audio.sh   or restore $BK/AuxiliaryKernelExtensions.kc.pre over $AKC"
