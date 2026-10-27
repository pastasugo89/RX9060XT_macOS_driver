#!/usr/bin/env bash
# Restore only the reviewed preservation archives to the already-created Lexar p7.
set -Eeuo pipefail
umask 077

readonly SERIAL='QBA343R000865P220C'
readonly MODEL='Lexar SSD EQ790 1TB'
readonly DISK_GUID='3bb8134b-c2c8-428e-a820-31f03be96b02'
readonly P7_UUID='0ae89dbc-e934-4c12-a6bd-90d01e5bd0da'
readonly P7_PARTUUID='b2978c53-2b87-4de8-872e-261479abeee3'
readonly P8_PARTUUID='2cdc5f53-02b8-43db-863f-aa3ca5676577'
readonly ARCHIVE='/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026/lexar-p7-preservation.tar'
readonly BACKUP='/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026'
readonly RUN="$BACKUP/lexar-repartition-20261026T160458Z"
readonly ROOT_TAR="$RUN/host-vfio-grub.tar"
readonly ROOT_SHA="$RUN/host-vfio-grub.sha256"
readonly AFTER_JSON="$RUN/partition-table.after.json"
readonly FSTAB_BEFORE="$RUN/fstab.before"
readonly MOUNTPOINT='/mnt/vm'
readonly MAIN_SHA='9b5c54877e4cc67c084df6a3ca0fa4f55fea00279b1641fe27059317c6d1abd3'
readonly ROOT_TAR_SHA='447238142dbc4b455b90ba13acf7ccf1c789dc6c4bc47e4c445aad6fd3ea3e5a'
readonly OLD_UUID='be2a9624-d2c1-4778-ac99-fcf9258d3328'

[[ $EUID -eq 0 && ${SUDO_UID:-} =~ ^[1-9][0-9]*$ && ${SUDO_GID:-} =~ ^[0-9]+$ ]] || {
  echo 'Run this restore through sudo from the dedicated Konsole.' >&2; exit 2;
}
for tool in lsblk sfdisk blkid findmnt sha256sum tar python3 stat install chown chmod sync systemctl cmp readlink blockdev mktemp awk tr xargs date; do
  command -v "$tool" >/dev/null || { echo "Required tool missing: $tool" >&2; exit 2; }
done

declare -a disks
mapfile -t disks < <(lsblk -dnro NAME,SERIAL | awk -v s="$SERIAL" '$2 == s {print $1}')
[[ ${#disks[@]} == 1 ]] || { echo 'Lexar serial absent or ambiguous; stopped.' >&2; exit 2; }
readonly DISK="/dev/${disks[0]}"
[[ $(lsblk -dno MODEL "$DISK" | xargs) == "$MODEL" ]]
[[ $(lsblk -dnro LOG-SEC "$DISK" | tr -d '[:space:]') == 512 ]]
[[ $(lsblk -dnro PTUUID "$DISK" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]') == "$DISK_GUID" ]]
[[ ${DISK##*/} == nvme* ]] || { echo 'Unexpected Lexar device naming; stopped.' >&2; exit 2; }
readonly P7="${DISK}p7"
readonly P8="${DISK}p8"

readonly LIVE_JSON="$(mktemp)"
trap 'rm -f "$LIVE_JSON"' EXIT
sfdisk --json "$DISK" > "$LIVE_JSON"
python3 - "$AFTER_JSON" "$LIVE_JSON" "$DISK" "$P7_UUID" "$P7_PARTUUID" "$P8_PARTUUID" <<'PY'
import json, sys
approved, live, disk, p7uuid, p7partuuid, p8partuuid = sys.argv[1:]
a = json.load(open(approved, encoding="utf-8"))["partitiontable"]
b = json.load(open(live, encoding="utf-8"))["partitiontable"]
assert a == b, "live GPT differs from the post-write snapshot"
assert a["label"] == "gpt" and a["sectorsize"] == 512
assert a["id"].lower() == "3bb8134b-c2c8-428e-a820-31f03be96b02"
def num(p): return int(p["node"].removeprefix(disk + "p"))
parts = {num(p): p for p in a["partitions"]}
assert sorted(parts) == list(range(1, 9))
assert int(parts[7]["start"]) == 1527257088 and int(parts[7]["size"]) == 104857600
assert parts[7]["uuid"].lower() == p7partuuid.lower()
assert parts[7]["type"].lower() == "0fc63daf-8483-4772-8e79-3d69d8477de4"
assert int(parts[8]["start"]) == 1632114688 and int(parts[8]["size"]) == 314572800
assert parts[8]["uuid"].lower() == p8partuuid.lower()
assert parts[8]["type"].lower() == "7c3457ef-0000-11aa-aa11-00306543ecac"
PY

[[ $(blkid -p -s UUID -o value "$P7") == "$P7_UUID" ]]
[[ $(blkid -p -s TYPE -o value "$P7") == btrfs ]]
[[ $(lsblk -dnro PARTUUID "$P7" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]') == "$P7_PARTUUID" ]]
[[ $(lsblk -dnro PARTUUID "$P8" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]') == "$P8_PARTUUID" ]]
[[ $(blockdev --getsz "$P7") == 104857600 && $(blockdev --getsz "$P8") == 314572800 ]]
[[ $(findmnt -nro TARGET -T "$MOUNTPOINT") == "$MOUNTPOINT" ]]
readonly MOUNT_SOURCE="$(findmnt -nro SOURCE -T "$MOUNTPOINT")"
[[ $(readlink -f "${MOUNT_SOURCE%%\[*}") == "$(readlink -f "$P7")" ]]
[[ $(findmnt -nro UUID -T "$MOUNTPOINT") == "$P7_UUID" ]]
[[ $(findmnt -nro FSTYPE -T "$MOUNTPOINT") == btrfs ]]
python3 - "$MOUNTPOINT" <<'PY'
import os, sys
assert not os.listdir(sys.argv[1]), "p7 is not empty; refusing to overlay existing files"
PY

[[ -f $ARCHIVE && -f $ROOT_TAR && -f $ROOT_SHA && -f $FSTAB_BEFORE ]]
printf '%s  %s\n' "$MAIN_SHA" "$ARCHIVE" | sha256sum --check --status
printf '%s  %s\n' "$ROOT_TAR_SHA" "$ROOT_TAR" | sha256sum --check --status
readonly RESTORE_DIR="$BACKUP/lexar-restore-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 -o "$SUDO_UID" -g "$SUDO_GID" "$RESTORE_DIR"
readonly LOG="$RESTORE_DIR/progress.jsonl"
: > "$LOG"; chmod 0600 "$LOG"; chown "$SUDO_UID:$SUDO_GID" "$LOG"
log() {
  LOG_PATH="$LOG" LOG_EVENT="$1" LOG_DETAIL="${2:-}" python3 - <<'PY'
import datetime, json, os
with open(os.environ["LOG_PATH"], "a", encoding="utf-8") as f:
 f.write(json.dumps({"time_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"event":os.environ["LOG_EVENT"],"detail":os.environ["LOG_DETAIL"]},sort_keys=True)+"\n")
 f.flush(); os.fsync(f.fileno())
PY
}
on_error() { rc=$?; trap - ERR; log stopped "line=${BASH_LINENO[0]:-unknown} status=$rc" || true; exit "$rc"; }
trap on_error ERR
log start "p7=$P7 p7_uuid=$P7_UUID p8_partuuid=$P8_PARTUUID"

tar --extract --file="$ARCHIVE" --directory="$MOUNTPOINT" --numeric-owner --same-owner --same-permissions --xattrs --acls
tar --extract --file="$ROOT_TAR" --directory="$MOUNTPOINT" --numeric-owner --same-owner --same-permissions --xattrs --acls
tar --compare --file="$ARCHIVE" --directory="$MOUNTPOINT"
tar --compare --file="$ROOT_TAR" --directory="$MOUNTPOINT"
(cd "$MOUNTPOINT" && sha256sum --check --status "$ROOT_SHA")
log restore_verified 'both archives compare clean; protected GRUB checksums pass'

python3 - /etc/fstab "$FSTAB_BEFORE" "$OLD_UUID" "$P7_UUID" "$MOUNTPOINT" "$RESTORE_DIR/fstab.expected" <<'PY'
import os, re, sys, tempfile
path, before, old, new, mountpoint, expected = sys.argv[1:]
data = open(before,"rb").read()
assert open(path,"rb").read() == data, "/etc/fstab changed since snapshot"
lines=data.decode("utf-8").splitlines(keepends=True); pat=re.compile(r"^(\s*)UUID="+re.escape(old)+r"(?=\s)"); changed=0
for i,line in enumerate(lines):
 if line.lstrip().startswith("#") or not line.strip(): continue
 fields=line.split()
 if len(fields)>=3 and fields[1]==mountpoint:
  assert fields[0]=="UUID="+old and fields[2]=="btrfs"
  m=pat.search(line); assert m
  lines[i]=line[:m.start()]+m.group(1)+"UUID="+new+line[m.end():]; changed+=1
assert changed==1
result="".join(lines).encode("utf-8")
with open(expected,"wb") as f: f.write(result); f.flush(); os.fsync(f.fileno())
os.chmod(expected,0o600); os.chown(expected,int(os.environ["SUDO_UID"]),int(os.environ["SUDO_GID"]))
st=os.stat(path); fd,tmp=tempfile.mkstemp(prefix=".fstab-restore-",dir=os.path.dirname(path))
try:
 with os.fdopen(fd,"wb") as f: f.write(result); f.flush(); os.fsync(f.fileno())
 os.chown(tmp,st.st_uid,st.st_gid); os.chmod(tmp,st.st_mode&0o7777)
 assert open(path,"rb").read()==data, "/etc/fstab changed before replace"
 os.replace(tmp,path); d=os.open(os.path.dirname(path),os.O_DIRECTORY); os.fsync(d); os.close(d)
except BaseException:
 try: os.unlink(tmp)
 except FileNotFoundError: pass
 raise
PY
systemctl daemon-reload
cmp -s "$RESTORE_DIR/fstab.expected" /etc/fstab
[[ $(findmnt -nro UUID -T "$MOUNTPOINT") == "$P7_UUID" ]]
[[ $(findmnt -nro FSTYPE -T "$MOUNTPOINT") == btrfs ]]
sync
log complete "p7_uuid=$P7_UUID p8_partuuid=$P8_PARTUUID"
trap - ERR
printf 'Restore complete. p7 UUID %s; p8 PARTUUID %s. Log: %s\n' "$P7_UUID" "$P8_PARTUUID" "$LOG"
