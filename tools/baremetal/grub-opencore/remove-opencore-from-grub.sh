#!/bin/bash
# Undo add-opencore-to-grub.sh on CachyOS:  sudo bash remove-opencore-from-grub.sh
# Removes the marked block from /etc/grub.d/40_custom (backup first) and regenerates grub.cfg. OpenCore files on the EFI are not touched.
set -euo pipefail
CUSTOM=/etc/grub.d/40_custom
BEGIN='### BEGIN navi44 opencore ###'
END='### END navi44 opencore ###'
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
cfg=""
for c in /boot/grub/grub.cfg /boot/grub2/grub.cfg; do [ -f "$c" ] && { cfg=$c; break; }; done
[ -n "$cfg" ] || { echo "STOP no grub.cfg"; exit 1; }
grep -qF "$BEGIN" "$CUSTOM" || { echo "No OpenCore entry in $CUSTOM; nothing to do."; exit 0; }
ts=$(date +%Y%m%d-%H%M%S)
cp -a "$CUSTOM" "$CUSTOM.navi44-backup-$ts"
sed -i "/^$BEGIN\$/,/^$END\$/d" "$CUSTOM"
cp -a "$cfg" "$cfg.navi44-backup-$ts"
grub-mkconfig -o "$cfg"
echo "Removed. Backups: $CUSTOM.navi44-backup-$ts, $cfg.navi44-backup-$ts"
