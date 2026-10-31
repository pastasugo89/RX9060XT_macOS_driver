#!/bin/bash
# Persistent root LaunchDaemon: activate once per boot and watch the login transition.
# Failed/abandoned attempts latch software mode until a reviewed deployment resets state.
set -Eeuo pipefail
PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 022
APP='/Library/Application Support/Navi44/accelerated-trial'
LOGDIR=/private/var/tmp/navi44-accelerated-trial
LOG=$LOGDIR/run.log
NT="$APP/navi48test"
NUB="$APP/n48nub"
FLAG=/private/tmp/n48m-headless-no
KILL=/private/tmp/n48m-off
PLIST=/Library/LaunchDaemons/org.navi44.accelerated-trial.plist
STATE="$APP/boot-state.json"
PROFILE=stage30-vonly-v1
state_started=0
ordered_stop=0
[[ $(id -u) == 0 ]] || { echo 'STOP root required'; exit 1; }
if [[ ! -e "$LOGDIR" && ! -L "$LOGDIR" ]]; then mkdir -m 755 "$LOGDIR" || exit 1; fi
[[ -d "$LOGDIR" && ! -L "$LOGDIR" && $(stat -f '%u:%g:%Lp' "$LOGDIR") == '0:0:755' ]] || { echo 'STOP unsafe log directory'; exit 1; }
if [[ -e "$LOG" || -L "$LOG" ]]; then
  logmeta=$(stat -f '%u:%g:%l:%Lp' "$LOG" 2>/dev/null || true)
  [[ -f "$LOG" && ! -L "$LOG" && ( "$logmeta" == '0:0:1:644' || "$logmeta" == '0:0:1:600' ) ]] || { echo 'STOP unsafe log file'; exit 1; }
fi
exec >>"$LOG" 2>&1
echo "START $(date -u)"

root_flag_valid() {
  [[ -f "$1" && ! -L "$1" && $(stat -f '%u:%g:%Lp:%z:%l' "$1" 2>/dev/null) == '0:0:644:0:1' ]]
}
make_root_flag() {
  if [[ -e "$1" || -L "$1" ]]; then root_flag_valid "$1"; return; fi
  # noclobber uses exclusive creation: a raced file/symlink is never followed.
  (umask 022; set -C; : > "$1") || return 1
  root_flag_valid "$1"
}

verify_fbname() {
  printf '%s\n' "$1" | grep -Eq 'armed[[:space:]]*:[[:space:]]*1[[:space:]]*\(status 0\)' &&
  printf '%s\n' "$1" | grep -Eq 'class name NOW[[:space:]]*:[[:space:]]*AMDRDNA4$' &&
  [[ "$2" == *'class AMDRDNA4FB,'* ]]
}

active=0
headless=0
renamed=0
guard_removed=0
guard_checked=0
rollback() {
  rc=$?
  trap - EXIT INT TERM
  if (( state_started && rc != 0 )); then
    result=failed
    (( ordered_stop )) && result=stopped
    /usr/bin/python3 "$APP/boot-state.py" "$result" --state "$STATE" --profile "$PROFILE" --observation "activation-exit-$rc" || echo 'BOOT_STATE_FAILURE_RECORD_FAILED'
  fi
  if (( guard_checked && rc != 0 )); then make_root_flag "$KILL" || true; fi
  if (( active )); then
    echo "FAILSAFE_BEGIN rc=$rc $(date -u)"
    "$NT" accel pipearm 0 || true
    make_root_flag "$KILL" || true
    if (( renamed )); then
      "$NT" accel fbname 0 || true
      rm -f "$FLAG"
      echo "FAILSAFE_FRAMEBUFFER_NAME_RESTORED"
    fi
    if [[ -z $(who) ]]; then
      killall -9 WindowServer || true
      echo 'FAILSAFE_WINDOWSERVER_RESTARTED_SOFTWARE'
    else
      echo 'FAILSAFE_DEFERRED_USER_SESSION_PRESENT'
    fi
    echo 'FAILSAFE_DONE'
  fi
  if (( headless && active )); then rm -f "$FLAG"; fi
  echo "END rc=$rc $(date -u)"
  exit "$rc"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'ordered_stop=1; exit 143' TERM

[[ $(id -u) == 0 && -x "$NT" && -x "$NUB" ]] || { echo 'STOP root/tools missing'; exit 1; }
[[ -z $(who) ]] || { echo 'STOP refusing activation in an existing user session'; exit 1; }
[[ ! -e "$APP/disabled" && ! -L "$APP/disabled" ]] || { echo 'STOP persistent activation disabled'; exit 1; }
[[ $(sw_vers -productVersion) == 26.6.2 && $(sw_vers -buildVersion) == 25G83 ]] || { echo 'STOP unexpected macOS build'; exit 1; }
args=$(nvram boot-args 2>/dev/null || true)
for arg in navi48-stage=17 navi48-native=1 navi48-metal=1 navi48-metal-disp=1 navi48-metal-ws=1 navi48-agdc=1 rdna4-vbl=1 amfi_get_out_of_my_way=1 navi48-multisession=1 navi48-apps=1 navi48-g5=1; do
  [[ " $args " == *" $arg "* || " $args " == *" $arg" ]] || { echo "STOP required boot arg missing: $arg"; exit 1; }
done
[[ ! -e /private/tmp/n48m-noflip1 && ! -e /private/tmp/n48m-noflip2 ]] || { echo 'STOP Navi48 no-flip kill switch present'; exit 1; }
# Validate a previous root-owned empty L1 kill file read-only. Clear it only
# after the persistent boot latch grants this new attempt; failed attempts are
# never retried merely because the machine rebooted.
stale_kill=0
if [[ -e "$KILL" || -L "$KILL" ]]; then
  root_flag_valid "$KILL" || { echo 'STOP unrecognized Navi48 kill switch'; exit 1; }
  stale_kill=1
fi
guard_checked=1
[[ -x /Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal ]] || { echo 'STOP Metal bundle missing'; exit 1; }
bundle_version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' /Library/GPUBundles/Navi48Metal.bundle/Contents/Info.plist 2>/dev/null || true)
[[ "$bundle_version" == 30 ]] || { echo "STOP expected Stage30 Metal bundle version 30, got: $bundle_version"; exit 1; }
echo 'CANDIDATE=stage25-archive-boundary' 

[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal" | cut -d " " -f 1) == @@SHA_MACHO@@ ]] || { echo "STOP bundle component changed: MacOS/Navi48Metal"; exit 1; }
[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/Resources/libvulkan_radeon.dylib" | cut -d " " -f 1) == @@SHA_VULKAN@@ ]] || { echo "STOP bundle component changed: Resources/libvulkan_radeon.dylib"; exit 1; }
[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/Resources/libn48xlate.dylib" | cut -d " " -f 1) == @@SHA_XLATE@@ ]] || { echo "STOP bundle component changed: Resources/libn48xlate.dylib"; exit 1; }

# Keep the launchd job across boots, but latch an attempt BEFORE clearing guards
# or changing GPU/display state. An unfinished/failed attempt blocks later boots.
[[ -f "$PLIST" && ! -L "$PLIST" && -f "$APP/boot-state.py" ]] || { echo 'STOP boot job/state helper missing'; exit 1; }
/usr/bin/python3 "$APP/boot-state.py" begin --state "$STATE" --profile "$PROFILE" || { echo 'STOP prior activation blocked or already attempted'; exit 1; }
state_started=1
if (( stale_kill )); then
  archive="$LOGDIR/n48m-off-pre-rearm-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$KILL" "$archive" || { echo 'STOP cannot archive previous Navi48 kill switch'; exit 1; }
  guard_removed=1
  echo "PREVIOUS_KILL_ARCHIVED=$archive"
fi
echo "BOOT_ARGS_OK $(date -u)"

# Cobalt64's desktop recipe sets this before user workloads. The bundle also
# applies it in its constructor, but that is too late if CIKL is used first.
if launchctl setenv CI_USE_MTL_DAG_FOR_CIKL_SRC 0; then
  echo 'CIKL_BACKSTOP=system-launchd-set'
else
  echo 'CIKL_BACKSTOP=system-launchd-set-failed'
fi

translator_ready() {
  local status pid
  status=$(launchctl print system/com.navi48.translate 2>/dev/null) || return 1
  printf '%s\n' "$status" | grep -Eq '^[[:space:]]*state = running$' || return 1
  pid=$(printf '%s\n' "$status" | awk '$1 == "pid" && $2 == "=" { print $3; exit }')
  [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] && kill -0 "$pid" 2>/dev/null
}
for ((i=0;i<90;i++)); do
  translator_ready && break
  [[ -z $(who) ]] || { echo 'STOP user session appeared while waiting for translator'; exit 1; }
  sleep 2
done
translator_ready || { echo 'STOP shader translator has no live running process'; exit 1; }

# Wait for the login window while no user session exists. Never restart WS after login.
for ((i=0;i<180;i++)); do
  [[ -z $(who) ]] || { echo 'STOP user session already present'; exit 1; }
  pgrep -x WindowServer >/dev/null 2>&1 && break
  sleep 2
done
[[ -n $(pgrep -x WindowServer || true) ]] || { echo 'STOP WindowServer not available'; exit 1; }
sleep 12
[[ -z $(who) ]] || { echo 'STOP user logged in during settle'; exit 1; }

loaded=$(kmutil showloaded --list-only 2>/dev/null) || { echo 'STOP cannot query loaded kexts'; exit 1; }
[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo 'STOP bringup or RDNA4FB kext missing'; exit 1; }

# The aux kext matches the nub; publish first, then wait for the accelerator to attach.
nubout=$("$NUB" publish 2>&1) || { echo "STOP nub publish failed: $nubout"; exit 1; }
echo "$nubout"
# A loaded kext does not establish IOService registration or successful matching.
# Wait for the nub properties and accelerator service together, without GPU writes.
ready=0
for ((i=0;i<60;i++)); do
  [[ -z $(who) ]] || { echo 'STOP user session appeared while waiting for registry readiness'; exit 1; }
  nubstat=$("$NUB" status 2>&1) || nubstat=""
  accelstat=$(ioreg -r -c Navi48Accelerator -d 1 2>/dev/null || true)
  if [[ "$nubstat" == *'Navi48MetalNub present'* && "$nubstat" == *'Navi48,Ready = 1'* && "$accelstat" == *'class Navi48Accelerator,'* ]]; then
    ready=1
    echo "REGISTRY_READY after_seconds=$i"
    echo "$nubstat"
    break
  fi
  sleep 1
done
(( ready == 1 )) || { echo "STOP registry readiness timed out; nub=$nubstat accelerator=$accelstat"; exit 1; }

fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)
printf '%s\n' "$fbidentity" | grep -Fq '"model" = "AMD Radeon RX 9060 XT"' || { echo 'STOP framebuffer identity correction not verified'; exit 1; }
echo 'FRAMEBUFFER_MODEL_VERIFIED=AMD Radeon RX 9060 XT'

/usr/bin/python3 "$APP/seed-gpu-apps.py" --tool "$NT" --names "$APP/app-allowlist.json" || { echo 'STOP GPU application admission setup failed'; exit 1; }

adopt=$("$NT" accel pipeadopt 2>&1) || { echo "STOP pipeadopt failed: $adopt"; exit 1; }
echo "$adopt"
agdc=$("$NT" accel pipeagdc 1 2>&1) || { echo "STOP pipeagdc failed: $agdc"; exit 1; }
echo "$agdc"
stat=$("$NT" accel pipestat 0 2>&1) || { echo "STOP initial pipestat failed: $stat"; exit 1; }
echo "$stat"
flags=$(printf '%s\n' "$stat" | sed -nE 's/.*flags[^:]*:[[:space:]]*(0x[0-9a-fA-F]+).*/\1/p')
[[ -n "$flags" ]] && (( (flags & 2) != 0 && (flags & 4) == 0 )) || { echo 'STOP pipe not adopted or unexpectedly armed'; exit 1; }

# One granted attempt per boot may reset the process-start counter; preserve it first.
if [[ -e /private/tmp/n48m-starts || -L /private/tmp/n48m-starts ]]; then
  [[ -f /private/tmp/n48m-starts && ! -L /private/tmp/n48m-starts ]] || { echo 'STOP unexpected starts marker'; exit 1; }
  cp -p /private/tmp/n48m-starts "$LOGDIR/starts-pre-stage23-$(date -u +%Y%m%dT%H%M%SZ)"
  rm /private/tmp/n48m-starts
fi
# Cobalt64's AMD vendor selection, after AGDC publication and before arming.
# Set rollback state BEFORE the rename, including on a partial/error return.
active=1
renamed=1
fbout=$("$NT" accel fbname 1 2>&1) || { echo "STOP framebuffer rename failed: $fbout"; exit 1; }
echo "$fbout"
# The ABI reports exactly eight name bytes: AMDRDNA4 (not the complete class name).
# Read the complete class via the original metacast: fbname changes className,
# while the kernel deliberately keeps the original RDNA4FB metacast registration.
fbregistry=$(ioreg -r -c RDNA4FB -d 1 2>/dev/null || true)
verify_fbname "$fbout" "$fbregistry" || { echo "STOP framebuffer rename readback: $fbregistry"; exit 1; }
echo 'FRAMEBUFFER_RENAME_VERIFIED=AMDRDNA4FB' 
make_root_flag "$FLAG" || { echo 'STOP cannot set WindowServer headless override'; exit 1; }
headless=1
active=1
arm=$("$NT" accel pipearm 1 2>&1) || { echo "STOP pipearm failed: $arm"; exit 1; }
echo "$arm"
printf '%s\n' "$arm" | grep -Eq 'status[[:space:]]*:[[:space:]]*0[[:space:]]' || { echo 'STOP pipearm status'; exit 1; }
printf '%s\n' "$arm" | grep -Eq 'accel\+0xccf now[[:space:]]*:[[:space:]]*1[[:space:]]' || { echo 'STOP pipearm readback'; exit 1; }
"$NT" accel pipereload || { echo 'STOP pipereload failed'; exit 1; }
oldpid=$(pgrep -x WindowServer | head -1)
[[ -n "$oldpid" && -z $(who) ]] || { echo 'STOP session changed before restart'; exit 1; }
echo "RESTART_WINDOWSERVER old=$oldpid $(date -u)"
killall -9 WindowServer

# Observe the restarted WindowServer continuously. One PID change is treated as
# a crash/restart: arm off, restore the framebuffer name and reload software compositor.
newpid=
for ((i=0;i<30;i++)); do
  newpid=$(pgrep -x WindowServer | head -1 || true)
  [[ -n "$newpid" && "$newpid" != "$oldpid" ]] && break
  sleep 1
done
[[ -n "$newpid" && "$newpid" != "$oldpid" ]] || { echo 'STOP WindowServer did not restart'; exit 1; }
echo "WINDOWSERVER_READY pid=$newpid $(date -u)"

# Mirror Cobalt64's best-effort user-domain backstop. At the login window the
# uid-501 domain may not exist yet, so this must remain non-fatal.
if launchctl asuser 501 launchctl setenv CI_USE_MTL_DAG_FOR_CIKL_SRC 0; then
  echo 'CIKL_BACKSTOP=uid501-set'
else
  echo 'CIKL_BACKSTOP=uid501-unavailable'
fi

login_seen=0
for ((i=0;i<300;i++)); do
  pid=$(pgrep -x WindowServer | head -1 || true)
  if [[ -z "$pid" ]]; then
    echo 'WINDOWSERVER_MISSING_BEFORE_LOGIN'
    exit 1
  fi
  if [[ "$pid" != "$newpid" ]]; then
    echo "WINDOWSERVER_RESTART_BEFORE_LOGIN old=$newpid new=$pid; restoring software compositor"
    exit 1
  fi
  if [[ -n $(who) ]]; then login_seen=1; break; fi
  sleep 1
done
observation=login-window-stable-300s
if (( login_seen == 1 )); then
  echo "LOGIN_SEEN pid=$newpid $(date -u)"

  for ((i=1;i<=120;i++)); do
    sleep 1
    pid=$(pgrep -x WindowServer | head -1 || true)
    if [[ -z "$pid" ]]; then
      echo "WINDOWSERVER_MISSING after_login_seconds=$i"
      exit 1
    fi
    if [[ "$pid" != "$newpid" ]]; then
      echo "WINDOWSERVER_RESTART old=$newpid new=$pid after_login_seconds=$i; restoring software compositor"
      exit 1
    fi
    if (( i % 15 == 0 )); then
      echo "SAMPLE=$((i/15)) $(date -u)"
      "$NT" accel pipestat 0 || true
      "$NT" accel pipestat 4 || true
      tail -20 /private/var/tmp/n48m-translate-state/translate.log 2>/dev/null || true
    fi
  done
  observation=desktop-stable-120s
else
  echo 'LOGIN_WINDOW_STABLE_ONLY; user transition has not been observed'
fi
/usr/bin/python3 "$APP/boot-state.py" stable --state "$STATE" --profile "$PROFILE" --observation "$observation" || { echo 'STOP cannot record verified startup state'; exit 1; }
state_started=0
active=0
echo "GPU_BOOT_STABLE pid=$newpid observation=$observation; persistent job retained" || true
exit 0
