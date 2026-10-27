#!/bin/bash
# One-shot root LaunchDaemon: arm Navi48Metal at the next boot, then observe one
# login. It mirrors Cobalt64's Core Image backstop and bounded WindowServer watcher.
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
CONSUMED="$APP/consumed-stage21-shutdown-check.plist"
mkdir -p "$LOGDIR"
chmod 755 "$LOGDIR"
exec >>"$LOG" 2>&1
echo "START $(date -u)"

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
  if (( guard_checked && rc != 0 )); then touch "$KILL" && chmod 644 "$KILL" || true; fi
  if (( active )); then
    echo "FAILSAFE_BEGIN rc=$rc $(date -u)"
    "$NT" accel pipearm 0 || true
    touch "$KILL" && chmod 644 "$KILL" || true
    if (( renamed )); then
      "$NT" accel fbname 0 || true
      rm -f "$FLAG"
      echo "FAILSAFE_FRAMEBUFFER_NAME_RESTORED"
    fi
    if (( renamed )) || [[ -z $(who) ]]; then
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
trap 'exit 143' TERM

[[ $(id -u) == 0 && -x "$NT" && -x "$NUB" ]] || { echo 'STOP root/tools missing'; exit 1; }
[[ $(sw_vers -productVersion) == 26.6.2 && $(sw_vers -buildVersion) == 25G83 ]] || { echo 'STOP unexpected macOS build'; exit 1; }
args=$(nvram boot-args 2>/dev/null || true)
for arg in navi48-stage=17 navi48-native=1 navi48-metal=1 navi48-metal-disp=1 navi48-metal-ws=1 navi48-agdc=1 rdna4-vbl=1 amfi_get_out_of_my_way=1; do
  [[ " $args " == *" $arg "* || " $args " == *" $arg" ]] || { echo "STOP required boot arg missing: $arg"; exit 1; }
done
[[ ! -e /private/tmp/n48m-noflip1 && ! -e /private/tmp/n48m-noflip2 ]] || { echo 'STOP Navi48 no-flip kill switch present'; exit 1; }
# The previous one-shot deliberately left its root-owned empty L1 kill file for
# this boot. Validate it read-only here; archive/clear it only after consuming
# this one-shot plist, so a partial preflight cannot silently remove the guard.
stale_kill=0
if [[ -e "$KILL" || -L "$KILL" ]]; then
  killmeta=$(/usr/bin/stat -f '%Su:%Sg:%Lp:%z' "$KILL" 2>/dev/null || true)
  [[ ! -L "$KILL" && "$killmeta" == 'root:wheel:644:0' ]] || { echo "STOP unrecognized Navi48 kill switch: $killmeta"; exit 1; }
  stale_kill=1
fi
guard_checked=1
[[ -x /Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal ]] || { echo 'STOP Metal bundle missing'; exit 1; }
bundle_version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' /Library/GPUBundles/Navi48Metal.bundle/Contents/Info.plist 2>/dev/null || true)
[[ "$bundle_version" == 23 ]] || { echo "STOP expected Stage18 Metal bundle version 23, got: $bundle_version"; exit 1; }
echo 'CANDIDATE=stage21-shutdown-check' 

[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal" | cut -d " " -f 1) == edc7255882ae823299212cde384a0bb89047de62c993cc618766302087e6e0cb ]] || { echo "STOP bundle component changed: MacOS/Navi48Metal"; exit 1; }
[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/Resources/libvulkan_radeon.dylib" | cut -d " " -f 1) == f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155 ]] || { echo "STOP bundle component changed: Resources/libvulkan_radeon.dylib"; exit 1; }
[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/Resources/libn48xlate.dylib" | cut -d " " -f 1) == 194c80d8b7a9f0c209adffd031602c1f83a8fb14de43eec39f49e860259b5890 ]] || { echo "STOP bundle component changed: Resources/libn48xlate.dylib"; exit 1; }

# Consume the boot job before doing GPU writes. It will not retry on a later boot.
[[ -f "$PLIST" && ! -e "$CONSUMED" ]] || { echo 'STOP one-shot plist missing/already consumed'; exit 1; }
mv "$PLIST" "$CONSUMED"
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

for ((i=0;i<90;i++)); do
  launchctl print system/com.navi48.translate >/dev/null 2>&1 && break
  [[ -z $(who) ]] || { echo 'STOP user session appeared while waiting for translator'; exit 1; }
  sleep 2
done
launchctl print system/com.navi48.translate >/dev/null 2>&1 || { echo 'STOP shader translator service is not running'; exit 1; }

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

adopt=$("$NT" accel pipeadopt 2>&1) || { echo "STOP pipeadopt failed: $adopt"; exit 1; }
echo "$adopt"
agdc=$("$NT" accel pipeagdc 1 2>&1) || { echo "STOP pipeagdc failed: $agdc"; exit 1; }
echo "$agdc"
stat=$("$NT" accel pipestat 0 2>&1) || { echo "STOP initial pipestat failed: $stat"; exit 1; }
echo "$stat"
flags=$(printf '%s\n' "$stat" | sed -nE 's/.*flags[^:]*:[[:space:]]*(0x[0-9a-fA-F]+).*/\1/p')
[[ -n "$flags" ]] && (( (flags & 2) != 0 && (flags & 4) == 0 )) || { echo 'STOP pipe not adopted or unexpectedly armed'; exit 1; }

# One explicitly staged trial may reset the process-start counter; preserve it first.
if [[ -e /private/tmp/n48m-starts || -L /private/tmp/n48m-starts ]]; then
  [[ -f /private/tmp/n48m-starts && ! -L /private/tmp/n48m-starts ]] || { echo 'STOP unexpected starts marker'; exit 1; }
  cp -p /private/tmp/n48m-starts "$LOGDIR/starts-pre-stage19-$(date -u +%Y%m%dT%H%M%SZ)"
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
touch "$FLAG" && chmod 644 "$FLAG" || { echo 'STOP cannot set WindowServer headless override'; exit 1; }
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
(( login_seen == 1 )) || { echo 'STOP login did not occur within 5 minutes'; exit 1; }
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
echo "TRIAL_STABLE_120S pid=$newpid; pipe left armed for user inspection"
active=0
exit 0
