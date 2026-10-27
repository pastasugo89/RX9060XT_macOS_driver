#!/usr/bin/env bash
# One-time, guarded layout change for Lexar EQ790 QBA343R000865P220C.
# This script is intentionally not run by Codex; root review is required first.
set -Eeuo pipefail
umask 077

readonly EXPECTED_SERIAL='QBA343R000865P220C'
readonly EXPECTED_MODEL='Lexar SSD EQ790 1TB'
readonly OLD_FS_UUID='be2a9624-d2c1-4778-ac99-fcf9258d3328'
readonly OLD_PARTUUID='b2978c53-2b87-4de8-872e-261479abeee3'
readonly OLD_START=1527257088
readonly OLD_SIZE=419430400
readonly ARCHIVE_SHA='9b5c54877e4cc67c084df6a3ca0fa4f55fea00279b1641fe27059317c6d1abd3'
readonly ARCHIVE='/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026/lexar-p7-preservation.tar'
readonly BACKUP_DIR='/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026'
readonly MOUNTPOINT='/mnt/vm'
readonly GRUB_DIR='backups/host-vfio-20261020-170657'
readonly P7_START=1527257088
readonly P7_SIZE=104857600
readonly P7_END=1632114687
readonly P8_START=1632114688
readonly P8_SIZE=314572800
readonly P8_END=1946687487
readonly APFS_GUID='7C3457EF-0000-11AA-AA11-00306543ECAC'
readonly BTRFS_GUID='0FC63DAF-8483-4772-8E79-3D69D8477DE4'

usage() {
  printf 'Usage: sudo %s --apply\n' "$0"
  printf 'This performs the approved Lexar p7/p8 layout change. It has no dry-run mode.\n'
}

if [[ ${1:-} != '--apply' || $# -ne 1 ]]; then
  usage
  exit 2
fi
[[ $EUID -eq 0 ]] || { echo 'Run through sudo from the dedicated Konsole.' >&2; exit 2; }
[[ ${SUDO_UID:-} =~ ^[1-9][0-9]*$ && ${SUDO_GID:-} =~ ^[0-9]+$ ]] || {
  echo 'Expected sudo environment (SUDO_UID/SUDO_GID); do not run as a root login.' >&2
  exit 2
}

for tool in lsblk sfdisk blkid findmnt df sha256sum tar python3 mkfs.btrfs \
            mount umount blockdev udevadm wipefs ps stat install sync awk sed sort diff tr grep systemctl; do
  command -v "$tool" >/dev/null || { echo "Required tool missing: $tool" >&2; exit 2; }
done

declare -a devices
mapfile -t devices < <(lsblk -dnro NAME,SERIAL | awk -v serial="$EXPECTED_SERIAL" '$2 == serial {print $1}')
[[ ${#devices[@]} -eq 1 ]] || { echo 'Lexar serial is absent or not unique; stopped.' >&2; exit 2; }
readonly DISK="/dev/${devices[0]}"
readonly MODEL="$(lsblk -dno MODEL "$DISK" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
readonly SECTOR_SIZE="$(lsblk -dnro LOG-SEC "$DISK" | tr -d '[:space:]')"
readonly DISK_TYPE="$(lsblk -dnro PTTYPE "$DISK" | tr -d '[:space:]')"
readonly DISK_GUID="$(lsblk -dnro PTUUID "$DISK" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
[[ $MODEL == "$EXPECTED_MODEL" && $SECTOR_SIZE == 512 && $DISK_TYPE == gpt ]] || {
  echo 'Lexar model, sector size, or GPT identity changed; stopped.' >&2; exit 2;
}
[[ -b "$DISK" ]] || { echo 'Resolved disk is not a block device.' >&2; exit 2; }
if [[ ${DISK##*/} == nvme* || ${DISK##*/} == mmcblk* ]]; then
  readonly PART7="${DISK}p7"
  readonly PART8="${DISK}p8"
else
  readonly PART7="${DISK}7"
  readonly PART8="${DISK}8"
fi

readonly BACKUP_SOURCE="$(findmnt -nro SOURCE -T "$BACKUP_DIR")"
readonly BACKUP_BLOCK="${BACKUP_SOURCE%%\[*}"
[[ -b $BACKUP_BLOCK ]] || { echo 'Backup filesystem source is not a resolved block device; stopped.' >&2; exit 2; }
readonly BACKUP_CHAIN_SERIALS="$(lsblk -s -no SERIAL "$BACKUP_BLOCK")"
readonly BACKUP_CHAIN_MODELS="$(lsblk -s -no MODEL "$BACKUP_BLOCK")"
! grep -Fq "$EXPECTED_SERIAL" <<< "$BACKUP_CHAIN_SERIALS" || {
  echo 'The approved backup filesystem traces back to the Lexar; stopped.' >&2; exit 2;
}
grep -qi 'Samsung' <<< "$BACKUP_CHAIN_MODELS" || {
  echo 'The approved backup filesystem does not trace back to a Samsung disk; stopped.' >&2; exit 2;
}
[[ -f $ARCHIVE && -r $ARCHIVE ]] || { echo 'Approved preservation archive is unavailable.' >&2; exit 2; }
[[ $(stat -c '%a' "$ARCHIVE") == 600 && $(stat -c '%a' "$BACKUP_DIR") == 700 ]] || {
  echo 'Preservation archive permissions differ from the reviewed private backup.' >&2; exit 2;
}

readonly RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_DIR="$BACKUP_DIR/lexar-repartition-$RUN_ID"
install -d -m 0700 -o "$SUDO_UID" -g "$SUDO_GID" "$RUN_DIR"
readonly LOG="$RUN_DIR/progress.jsonl"
: > "$LOG"
chmod 0600 "$LOG"
chown "$SUDO_UID:$SUDO_GID" "$LOG"

log() {
  local event=$1 detail=${2:-}
  LOG_PATH="$LOG" LOG_EVENT="$event" LOG_DETAIL="$detail" python3 - <<'PY'
import datetime, json, os
row = {
    "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "event": os.environ["LOG_EVENT"],
    "detail": os.environ.get("LOG_DETAIL", ""),
}
with open(os.environ["LOG_PATH"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(row, sort_keys=True) + "\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
}
on_error() {
  local status=$?
  trap - ERR
  log 'stopped_error' "line=$LINENO status=$status" || true
  printf 'Stopped at line %s (status %s). No automatic rollback was attempted; see %s\n' "$LINENO" "$status" "$LOG" >&2
  exit "$status"
}
trap on_error ERR

log 'start' "disk=$DISK serial=$EXPECTED_SERIAL model=$MODEL run=$RUN_ID"

readonly TABLE_GUID="$(python3 - "$DISK" "$PART7" "$OLD_FS_UUID" "$OLD_PARTUUID" "$OLD_START" "$OLD_SIZE" "$BTRFS_GUID" "$DISK_GUID" <<'PY'
import json, subprocess, sys
disk, part7, fsuuid, partuuid, oldstart, oldsize, btrfs_guid, expected_disk_guid = sys.argv[1:]
table = json.loads(subprocess.check_output(["sfdisk", "--json", disk], text=True))["partitiontable"]
assert table["label"] == "gpt" and table["sectorsize"] == 512, "unexpected partition table"
assert table["id"].lower() == expected_disk_guid.lower(), "disk GUID changed"
parts = table["partitions"]
by_n = {int(p["node"].removeprefix(disk + "p" if "nvme" in disk or "mmcblk" in disk else disk)): p for p in parts}
assert sorted(by_n) == list(range(1, 8)), "expected exactly p1..p7 before repartition"
p = by_n[7]
assert p["node"] == part7 and int(p["start"]) == int(oldstart) and int(p["size"]) == int(oldsize), "p7 geometry changed"
assert p["uuid"].lower() == partuuid.lower(), "p7 PARTUUID changed"
assert p["type"].lower() == btrfs_guid.lower(), "p7 is not the expected Linux filesystem partition"
print(table["id"].lower())
PY
)"
[[ $TABLE_GUID == "$DISK_GUID" ]]
[[ $(blkid -p -s UUID -o value "$PART7") == "$OLD_FS_UUID" ]]
[[ $(blkid -p -s TYPE -o value "$PART7") == btrfs ]]
[[ $(findmnt -nro TARGET -T "$MOUNTPOINT") == "$MOUNTPOINT" ]]
[[ $(findmnt -nro UUID -T "$MOUNTPOINT") == "$OLD_FS_UUID" ]]
[[ $(findmnt -nro FSTYPE -T "$MOUNTPOINT") == btrfs ]]
[[ $(findmnt -rnro UUID | awk -v u="$OLD_FS_UUID" '$1 == u {n++} END {print n+0}') == 1 ]]

if ps -eo comm= | awk '$1 ~ /^(qemu-system|qemu-kvm|VirtualBoxVM|vmware-vmx)/ {found=1} END {exit !found}'; then
  echo 'A VM process is active; stop it and rerun only after review.' >&2
  exit 2
fi
if awk -v old="UUID=$OLD_FS_UUID" -v mount="$MOUNTPOINT" '
  /^[[:space:]]*#/ || NF == 0 {next}
  $2 == mount {n++; if ($1 != old || $3 != "btrfs") bad=1; if ($4 ~ /(^|,)(subvol|subvolid)=/) bad=1}
  END {exit !(n == 1 && !bad)}
' /etc/fstab; then :; else
  echo 'Expected exactly one simple UUID-based Btrfs /mnt/vm fstab row; stopped.' >&2
  exit 2
fi

printf '%s  %s\n' "$ARCHIVE_SHA" "$ARCHIVE" | sha256sum --check --status
tar --compare --file="$ARCHIVE" --directory="$MOUNTPOINT"
tar --list --file="$ARCHIVE" | python3 -c '
import sys
for line in sys.stdin:
 p=line.rstrip("\n")
 if p.startswith("/") or any(x == ".." for x in p.split("/")):
  raise SystemExit("unsafe archive member path")
'
[[ -f "$MOUNTPOINT/$GRUB_DIR/grub.cfg" && -f "$MOUNTPOINT/$GRUB_DIR/grub.cfg.candidate" ]]
[[ $(stat -c '%u:%g:%a' "$MOUNTPOINT/$GRUB_DIR/grub.cfg") == '0:0:600' ]]
[[ $(stat -c '%u:%g:%a' "$MOUNTPOINT/$GRUB_DIR/grub.cfg.candidate") == '0:0:600' ]]
[[ $(stat -c '%s' "$MOUNTPOINT/$GRUB_DIR/grub.cfg") -lt 1048576 ]]
[[ $(stat -c '%s' "$MOUNTPOINT/$GRUB_DIR/grub.cfg.candidate") -lt 1048576 ]]

readonly CURRENT_DUMP="$RUN_DIR/partition-table.before.sfdisk"
readonly CURRENT_JSON="$RUN_DIR/partition-table.before.json"
readonly CANDIDATE="$RUN_DIR/partition-table.candidate.sfdisk"
sfdisk --dump "$DISK" > "$CURRENT_DUMP"
sfdisk --json "$DISK" > "$CURRENT_JSON"
cp --preserve=all /etc/fstab "$RUN_DIR/fstab.before"
chmod 0600 "$CURRENT_DUMP" "$CURRENT_JSON" "$RUN_DIR/fstab.before"
chown "$SUDO_UID:$SUDO_GID" "$CURRENT_DUMP" "$CURRENT_JSON" "$RUN_DIR/fstab.before"
shopt -s nullglob
sfdisk --backup-pt-sectors --backup-file "$RUN_DIR/gpt-sectors" "$DISK"
shopt -s nullglob
GPT_BACKUPS=("$RUN_DIR"/gpt-sectors*)
shopt -u nullglob
[[ ${#GPT_BACKUPS[@]} -ge 2 ]] || {
  echo 'sfdisk did not produce its raw GPT-sector backup; stopped.' >&2; exit 2;
}

readonly ROOT_TAR="$RUN_DIR/host-vfio-grub.tar"
readonly ROOT_SHA="$RUN_DIR/host-vfio-grub.sha256"
(
  cd "$MOUNTPOINT"
  sha256sum -- "$GRUB_DIR/grub.cfg" "$GRUB_DIR/grub.cfg.candidate" > "$ROOT_SHA"
  printf '%s\0' "$GRUB_DIR/grub.cfg" "$GRUB_DIR/grub.cfg.candidate" |
    tar --create --file="$ROOT_TAR" --directory="$MOUNTPOINT" --null --files-from=- --numeric-owner --xattrs --acls
  tar --compare --file="$ROOT_TAR" --directory="$MOUNTPOINT"
)
chmod 0600 "$ROOT_TAR" "$ROOT_SHA"
chown "$SUDO_UID:$SUDO_GID" "$ROOT_TAR" "$ROOT_SHA"
sha256sum "$ROOT_TAR" > "$ROOT_TAR.sha256"
chmod 0600 "$ROOT_TAR.sha256"
chown "$SUDO_UID:$SUDO_GID" "$ROOT_TAR.sha256"
sha256sum --check --status "$ROOT_TAR.sha256"
(cd "$MOUNTPOINT" && sha256sum --check --status "$ROOT_SHA")
tar --list --file="$ROOT_TAR" | sort | diff -u - <(printf '%s\n' "$GRUB_DIR/grub.cfg" "$GRUB_DIR/grub.cfg.candidate" | sort)

python3 - "$CURRENT_DUMP" "$CANDIDATE" "$PART7" "$PART8" "$P7_START" "$P7_SIZE" "$P7_END" "$P8_START" "$P8_SIZE" "$P8_END" "$APFS_GUID" <<'PY'
import re, sys
src, dst, part7, part8, p7start, p7size, p7end, p8start, p8size, p8end, apfs = sys.argv[1:]
lines = open(src, encoding="utf-8").readlines()
prefix = part7 + " :"
indexes = [i for i, line in enumerate(lines) if line.startswith(prefix)]
assert len(indexes) == 1, "could not identify exactly one p7 row"
i = indexes[0]
line = re.sub(r"\bstart=\s*\d+", f"start={p7start}", lines[i], count=1)
line = re.sub(r"\bsize=\s*\d+", f"size={p7size}", line, count=1)
assert re.search(r"\bstart=" + re.escape(p7start) + r"\b", line)
assert re.search(r"\bsize=" + re.escape(p7size) + r"\b", line)
if re.search(r"\bname=(?:\"[^\"]*\"|[^,\s]+)", line):
    line = re.sub(r"\bname=(?:\"[^\"]*\"|[^,\s]+)", 'name="vm-archive"', line, count=1)
else:
    line = line.rstrip("\n") + ', name="vm-archive"\n'
lines[i] = line
assert int(p7start) + int(p7size) - 1 == int(p7end)
assert int(p8start) + int(p8size) - 1 == int(p8end)
if not lines[-1].endswith("\n"):
    lines[-1] += "\n"
lines.append(f"{part8} : start={p8start}, size={p8size}, type={apfs}, name=\"macOS\"\n")
open(dst, "w", encoding="utf-8").writelines(lines)
PY
chmod 0600 "$CANDIDATE"
chown "$SUDO_UID:$SUDO_GID" "$CANDIDATE"
sfdisk --no-act --no-reread --wipe never --wipe-partitions never "$DISK" < "$CANDIDATE" >/dev/null

free_bytes="$(df -B1 --output=avail "$BACKUP_DIR" | awk 'NR == 2 {print $1}')"
[[ $free_bytes =~ ^[0-9]+$ && $free_bytes -ge 3000000000 ]] || {
  echo 'Less than 3 GB remains on Samsung after preservation staging; stopped.' >&2; exit 2;
}
sha256sum "$CURRENT_DUMP" "$CURRENT_JSON" "$RUN_DIR/fstab.before" "$CANDIDATE" \
  "$ROOT_TAR" "$ROOT_SHA" "$ROOT_TAR.sha256" > "$RUN_DIR/prewrite.sha256"
sha256sum "${GPT_BACKUPS[@]}" >> "$RUN_DIR/prewrite.sha256"
chmod 0600 "$RUN_DIR/prewrite.sha256"
chown "$SUDO_UID:$SUDO_GID" "$RUN_DIR/prewrite.sha256"
sync
log 'preflight_complete' "gpt_and_fstab_backed_up archive_sha=$ARCHIVE_SHA root_grub_archive_sha=$(sha256sum "$ROOT_TAR" | awk '{print $1}') free_bytes=$free_bytes"

tar --compare --file="$ARCHIVE" --directory="$MOUNTPOINT"
(cd "$MOUNTPOINT" && sha256sum --check --status "$ROOT_SHA")
umount "$MOUNTPOINT"
[[ $(findmnt -rn -o TARGET | awk -v m="$MOUNTPOINT" '$1 == m {n++} END {print n+0}') == 0 ]]
log 'unmounted' "$MOUNTPOINT"
sfdisk --lock=yes --wipe never --wipe-partitions never "$DISK" < "$CANDIDATE"
sync
blockdev --rereadpt "$DISK"
udevadm settle
[[ -b $PART7 && -b $PART8 ]]

readonly AFTER_JSON="$RUN_DIR/partition-table.after.json"
sfdisk --json "$DISK" > "$AFTER_JSON"
chmod 0600 "$AFTER_JSON"
chown "$SUDO_UID:$SUDO_GID" "$AFTER_JSON"
sha256sum "$AFTER_JSON" > "$AFTER_JSON.sha256"
chmod 0600 "$AFTER_JSON.sha256"
chown "$SUDO_UID:$SUDO_GID" "$AFTER_JSON.sha256"

readonly P8_PARTUUID="$(python3 - "$CURRENT_JSON" "$AFTER_JSON" "$DISK" "$PART7" "$PART8" "$DISK_GUID" "$P7_START" "$P7_SIZE" "$P7_END" "$P8_START" "$P8_SIZE" "$P8_END" "$APFS_GUID" "$BTRFS_GUID" "$OLD_PARTUUID" <<'PY'
import json, sys
oldjson, afterjson, disk, p7node, p8node, disk_guid, p7start, p7size, p7end, p8start, p8size, p8end, apfs, btrfs, partuuid = sys.argv[1:]
old = json.load(open(oldjson, encoding="utf-8"))["partitiontable"]
new = json.load(open(afterjson, encoding="utf-8"))["partitiontable"]
assert old["label"] == new["label"] == "gpt" and old["sectorsize"] == new["sectorsize"] == 512
assert old["id"].lower() == new["id"].lower() == disk_guid.lower(), "disk GUID changed"
def number(node):
    return int(node.removeprefix(disk + "p" if "nvme" in disk or "mmcblk" in disk else disk))
a = {number(p["node"]): p for p in old["partitions"]}
b = {number(p["node"]): p for p in new["partitions"]}
assert sorted(a) == list(range(1, 8)) and sorted(b) == list(range(1, 9))
for n in range(1, 7):
    assert a[n] == b[n], f"p{n} changed"
assert b[7]["node"] == p7node and int(b[7]["start"]) == int(p7start) and int(b[7]["size"]) == int(p7size)
assert int(p7start) + int(p7size) - 1 == int(p7end)
assert b[7]["type"].lower() == btrfs.lower() and b[7]["uuid"].lower() == partuuid.lower()
assert b[8]["node"] == p8node and int(b[8]["start"]) == int(p8start) and int(b[8]["size"]) == int(p8size)
assert int(p8start) + int(p8size) - 1 == int(p8end)
assert b[8]["type"].lower() == apfs.lower() and b[8].get("uuid"), "missing APFS partition GUID"
print(b[8]["uuid"].lower())
PY
 )"
[[ $P8_PARTUUID =~ ^[0-9a-f-]{36}$ ]]
[[ $(blockdev --getsz "$PART7") == "$P7_SIZE" ]]
[[ $(blockdev --getsz "$PART8") == "$P8_SIZE" ]]
sha256sum --check --status "$AFTER_JSON.sha256"
log 'gpt_written_verified' "p1-p6 and disk GUID unchanged; p7=50GiB; p8=150GiB APFS type partuuid=$P8_PARTUUID"

# p8 still contains old VM data; remove recognized filesystem signatures only.
wipefs --all "$PART8"
remaining_wipefs_output="$(wipefs --no-act --output TYPE "$PART8")"
remaining_wipefs_types="$(awk 'NR > 1 && NF {print $1}' <<< "$remaining_wipefs_output")"
if [[ -n $remaining_wipefs_types ]]; then
  echo 'A filesystem signature remains on new p8; stopped before formatting p7.' >&2
  exit 2
fi
mkfs.btrfs --force --nodiscard --label vm-archive "$PART7"
readonly NEW_FS_UUID="$(blkid -p -s UUID -o value "$PART7")"
[[ -n $NEW_FS_UUID && $NEW_FS_UUID != "$OLD_FS_UUID" ]]
[[ $(blkid -p -s TYPE -o value "$PART7") == btrfs ]]
mount -t btrfs -o rw "$PART7" "$MOUNTPOINT"
[[ $(findmnt -nro TARGET -T "$MOUNTPOINT") == "$MOUNTPOINT" ]]
[[ $(findmnt -nro FSTYPE -T "$MOUNTPOINT") == btrfs ]]
[[ $(findmnt -nro MAJ:MIN -T "$MOUNTPOINT") == "$(lsblk -dnro MAJ:MIN "$PART7" | tr -d '[:space:]')" ]]
[[ $(findmnt -nro UUID -T "$MOUNTPOINT") == "$NEW_FS_UUID" ]]
tar --extract --file="$ARCHIVE" --directory="$MOUNTPOINT" --numeric-owner --same-owner --same-permissions --xattrs --acls
tar --extract --file="$ROOT_TAR" --directory="$MOUNTPOINT" --numeric-owner --same-owner --same-permissions --xattrs --acls
tar --compare --file="$ARCHIVE" --directory="$MOUNTPOINT"
tar --compare --file="$ROOT_TAR" --directory="$MOUNTPOINT"
 (cd "$MOUNTPOINT" && sha256sum --check --status "$ROOT_SHA")
[[ $(stat -c '%u:%g:%a' "$MOUNTPOINT/$GRUB_DIR/grub.cfg") == '0:0:600' ]]
[[ $(stat -c '%u:%g:%a' "$MOUNTPOINT/$GRUB_DIR/grub.cfg.candidate") == '0:0:600' ]]
python3 - /etc/fstab "$RUN_DIR/fstab.before" "$OLD_FS_UUID" "$NEW_FS_UUID" "$MOUNTPOINT" <<'PY'
import os, re, sys, tempfile
path, before, old, new, mountpoint = sys.argv[1:]
data = open(before, "rb").read()
assert open(path, "rb").read() == data, "/etc/fstab changed after its snapshot"
lines = data.decode("utf-8").splitlines(keepends=True)
pattern = re.compile(r"^(\s*)UUID=" + re.escape(old) + r"(?=\s)")
changed = 0
for i, line in enumerate(lines):
    if line.lstrip().startswith("#") or not line.strip():
        continue
    fields = line.split()
    if len(fields) >= 3 and fields[1] == mountpoint:
        assert fields[0] == "UUID=" + old and fields[2] == "btrfs", "fstab row changed since preflight"
        m = pattern.search(line)
        assert m, "could not identify the source field"
        lines[i] = line[:m.start()] + m.group(1) + "UUID=" + new + line[m.end():]
        changed += 1
assert changed == 1, "expected one /mnt/vm row"
st = os.stat(path)
fd, tmp = tempfile.mkstemp(prefix=".fstab-lexar-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "wb") as stream:
        stream.write("".join(lines).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, st.st_mode & 0o7777)
    assert open(path, "rb").read() == data, "/etc/fstab changed before atomic replace"
    os.replace(tmp, path)
    dfd = os.open(os.path.dirname(path), os.O_DIRECTORY)
    try: os.fsync(dfd)
    finally: os.close(dfd)
except BaseException:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    raise
PY
systemctl daemon-reload
[[ $(findmnt -nro UUID -T "$MOUNTPOINT") == "$NEW_FS_UUID" ]]
[[ $(findmnt -nro FSTYPE -T "$MOUNTPOINT") == btrfs ]]
sync
log 'complete' "new_p7_uuid=$NEW_FS_UUID p8=$PART8 p8_partuuid=$P8_PARTUUID apfs_type_unformatted=true"
trap - ERR
printf 'Complete. Archive Btrfs UUID: %s\nNew blank APFS-type partition: %s, PARTUUID %s (%s sectors).\nLog and recovery snapshots: %s\n' \
  "$NEW_FS_UUID" "$PART8" "$P8_PARTUUID" "$P8_SIZE" "$RUN_DIR"
