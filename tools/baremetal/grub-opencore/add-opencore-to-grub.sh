#!/bin/bash
# Add a "macOS Tahoe (OpenCore)" entry to CachyOS's GRUB menu. Run once on CachyOS (the install on the 256 GB SSD):
#     sudo bash add-opencore-to-grub.sh
# The entry chainloads \EFI\OC\OpenCore.efi from the CachyOS EFI partition (GPT partition UUID below), where the
# working OpenCore tree (kernel 665) was copied from the OCBOOT stick on 31 October 2026.
# What it changes: appends one marked block to /etc/grub.d/40_custom and regenerates grub.cfg. Both files are
# backed up first. Running it again changes nothing. remove-opencore-from-grub.sh undoes it.
set -euo pipefail

ESP_PARTUUID=ca42fcab-d077-43ee-b98d-f1bafc0f6f90   # disk1s1 (macOS: diskutil info disk1s1, "Disk / Partition UUID")
CUSTOM=/etc/grub.d/40_custom
BEGIN='### BEGIN navi44 opencore ###'
END='### END navi44 opencore ###'

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
command -v grub-mkconfig >/dev/null || { echo "STOP grub-mkconfig not found (is this the CachyOS install that owns the GRUB menu?)"; exit 1; }

dev=$(readlink -f "/dev/disk/by-partuuid/$ESP_PARTUUID" 2>/dev/null || true)
[ -b "$dev" ] || { echo "STOP EFI partition $ESP_PARTUUID not found"; exit 1; }
fsuuid=$(blkid -s UUID -o value "$dev")
fstype=$(blkid -s TYPE -o value "$dev")
[ "$fstype" = vfat ] && [ -n "$fsuuid" ] || { echo "STOP $dev is not a FAT partition with a UUID ($fstype)"; exit 1; }

# The ESP must hold OpenCore. Use its mount point if mounted, otherwise mount it read-only for the check.
mnt=$(findmnt -n -o TARGET --source "$dev" | head -1 || true)
tmp=""
if [ -z "$mnt" ]; then tmp=$(mktemp -d); mount -o ro "$dev" "$tmp"; mnt=$tmp; fi
ok=1; for f in EFI/OC/OpenCore.efi EFI/OC/config.plist; do [ -f "$mnt/$f" ] || { echo "STOP $dev has no $f"; ok=0; }; done
[ -n "$tmp" ] && { umount "$tmp"; rmdir "$tmp"; }
[ "$ok" = 1 ] || exit 1

if [ -r /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c ] &&
   [ "$(od -An -t u1 -j4 -N1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | tr -d ' ')" = 1 ]; then
    echo "WARNING Secure Boot is ON: GRUB will refuse to chainload the unsigned OpenCore.efi. The OCBOOT stick works today, so it is probably off."
fi

cfg=""
for c in /boot/grub/grub.cfg /boot/grub2/grub.cfg; do [ -f "$c" ] && { cfg=$c; break; }; done
[ -n "$cfg" ] || { echo "STOP no grub.cfg in /boot/grub or /boot/grub2"; exit 1; }
[ -f "$CUSTOM" ] || { echo "STOP $CUSTOM missing"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
if grep -qF "$BEGIN" "$CUSTOM"; then
    echo "The entry is already in $CUSTOM; regenerating grub.cfg only."
else
    cp -a "$CUSTOM" "$CUSTOM.navi44-backup-$ts"
    cat >> "$CUSTOM" <<ENTRY

$BEGIN
menuentry 'macOS Tahoe (OpenCore)' --class macos --class os {
	insmod part_gpt
	insmod fat
	insmod chain
	search --no-floppy --fs-uuid --set=root $fsuuid
	chainloader /EFI/OC/OpenCore.efi
}
$END
ENTRY
    echo "Added the entry to $CUSTOM (backup $CUSTOM.navi44-backup-$ts)."
fi
[ -x "$CUSTOM" ] || chmod +x "$CUSTOM"

cp -a "$cfg" "$cfg.navi44-backup-$ts"
grub-mkconfig -o "$cfg"
grep -q "macOS Tahoe (OpenCore)" "$cfg" || { echo "STOP the entry is not in the new $cfg; restoring the backup"; cp -a "$cfg.navi44-backup-$ts" "$cfg"; exit 1; }
echo "OK: 'macOS Tahoe (OpenCore)' is in $cfg (backup $cfg.navi44-backup-$ts). EFI partition $dev, FAT UUID $fsuuid."
