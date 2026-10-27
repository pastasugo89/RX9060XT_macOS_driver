#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
readonly P7=/dev/nvme1n1p7 UUID=0ae89dbc-e934-4c12-a6bd-90d01e5bd0da
readonly SERIAL=QBA343R000865P220C SAMSUNG_SERIAL=S672NE0R891253
readonly MOUNT=/mnt/vm ARCHIVE=/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026/lexar-p7-preservation.tar
readonly MANIFEST=/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026/source.SHA256SUMS
readonly RESTORE=/home/pastasugo89/Documenti/rx9060xt_metal_driver/research/ext/vm-preservation-20261026/lexar-restore-20261026T161046Z
readonly TAR_SHA=9b5c54877e4cc67c084df6a3ca0fa4f55fea00279b1641fe27059317c6d1abd3
[[ $EUID == 0 && ${SUDO_UID:-} == "$(id -u pastasugo89)" ]] || { echo 'Run through sudo as pastasugo89.' >&2; exit 2; }
for t in findmnt readlink lsblk sha256sum tar python3 runuser install stat wc date tr; do command -v "$t" >/dev/null || exit 2; done
[[ $(readlink -f "$(findmnt -nro SOURCE -T "$MOUNT")") == $(readlink -f "$P7") ]]
[[ $(findmnt -nro UUID -T "$MOUNT") == "$UUID" && $(lsblk -dnro SERIAL /dev/nvme1n1 | tr -d '[:space:]') == "$SERIAL" ]]
LOGSRC=$(findmnt -nro SOURCE -T "$RESTORE"); LOGSRC=${LOGSRC%%\[*}
[[ $(lsblk -srno SERIAL "$LOGSRC" | tr -d '[:space:]') == "$SAMSUNG_SERIAL" && -r $ARCHIVE && -r $MANIFEST ]]
printf '%s  %s\n' "$TAR_SHA" "$ARCHIVE" | sha256sum --check --status
[[ $(wc -l < "$MANIFEST") == 445 && -d $RESTORE && $(stat -c '%u:%a' "$RESTORE") == "$(id -u pastasugo89):700" ]]
readonly LOG="$RESTORE/fix-parent-permissions.jsonl" RUN_USER=pastasugo89
[[ ! -e $LOG ]] || { echo 'Refusing to overwrite the existing run log.' >&2; exit 2; }
install -m 0600 -o "$SUDO_UID" -g "$SUDO_GID" /dev/null "$LOG"
log() { python3 - "$LOG" "$1" "$2" <<'PY'
import datetime,json,os,sys
with open(sys.argv[1],"a",encoding="utf-8") as f:
 f.write(json.dumps({"time_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"event":sys.argv[2],"detail":sys.argv[3]},sort_keys=True)+"\n"); f.flush(); os.fsync(f.fileno())
PY
}
on_error() { rc=$?; trap - ERR; log stopped "line=${BASH_LINENO[0]:-unknown} status=$rc" || true; exit "$rc"; }
trap on_error ERR
log start "p7=$P7 uuid=$UUID tar_sha=$TAR_SHA manifest_entries=445"
fixed=$(python3 - "$MOUNT" "$ARCHIVE" <<'PY'
import os,posixpath,stat,sys,tarfile
root,archive=sys.argv[1:]; flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
def clean(name):
 if name.startswith("/"): raise RuntimeError("absolute archive path")
 p=posixpath.normpath(name)
 if p in (".",""): return ""
 if p==".." or p.startswith("../"): raise RuntimeError("unsafe archive path")
 return p
with tarfile.open(archive,"r:") as tf:
 members=tf.getmembers(); dirs={clean(m.name) for m in members if m.isdir()}
 parents=set()
 for m in members:
  p=clean(m.name)
  while "/" in p:
   p=p.rsplit("/",1)[0]
   if p and p not in dirs: parents.add(p)
 opened=[]
 try:
  for rel in sorted(parents,key=lambda x:(x.count("/"),x)):
   fd=os.open(root,flags)
   try:
    for part in rel.split("/"):
     nxt=os.open(part,flags,dir_fd=fd); os.close(fd); fd=nxt
    s=os.fstat(fd)
    if not stat.S_ISDIR(s.st_mode): raise RuntimeError("implicit parent is not a directory")
    if (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700): opened.append((fd,rel)); fd=-1
   finally:
    if fd>=0: os.close(fd)
  for fd,_ in opened: os.fchmod(fd,0o755); os.fsync(fd)
  print(len(opened))
 finally:
  for fd,_ in opened: os.close(fd)
PY
)
log parent_permissions_fixed "implicit_root_0700_dirs=$fixed mode=0755"
runuser -u "$RUN_USER" -- bash -c 'cd /mnt/vm && sha256sum --check --quiet "$1"' -- "$MANIFEST"
log manifest_verified 'entries=445 verified_as=pastasugo89'
log complete "implicit_root_0700_dirs=$fixed manifest_entries=445"
printf 'Parent-directory permissions fixed: %s. All 445 manifest hashes pass. Log: %s\n' "$fixed" "$LOG"
