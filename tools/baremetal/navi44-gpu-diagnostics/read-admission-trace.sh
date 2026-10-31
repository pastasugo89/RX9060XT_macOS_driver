#!/bin/sh
#
# read-admission-trace.sh - READ-ONLY admission diagnostic for 0xe00002c7 refusals of 'N48N' opens.
#
# Run by a human, as root:
#     sudo sh tools/baremetal/navi44-gpu-diagnostics/read-admission-trace.sh | tee admission-trace.txt
#
# Paths below are relative to the repo root (rx9060xt_metal_driver/). Only the installed tool is run:
#     /Library/Application Support/Navi44/accelerated-trial/navi48test
# (the same binary tools/baremetal/navi44-gpu-diagnostics/session-check.py calls).
#
# WHAT IT RUNS, AND WHY EACH STEP CANNOT WRITE GPU, KERNEL OR ALLOW-LIST STATE
#
# 1. `navi48test log` (the driver log ring, which carries the bring-up trace events "aux trace: event N" and the
#    native-open lines "native-s1c: ..."):
#    - cmd_log(): tools/pc/navi48test.c:308-327 calls IOConnectCallMethod(conn, kNavi48SelReadLog, ...).
#    - kNavi48SelReadLog = 10: src/navi48-bringup/src/Navi48UserClientABI.h:31.
#    - Navi48UserClient::doReadLog: src/navi48-bringup/src/Navi48UserClient.cpp:407-421 calls
#      amdgpu::n48_log_read(offset, ...) and returns the bytes.
#    - n48_log_read: src/navi48-bringup/src/amd/n48log.cpp:69-83 only memcpy()s out of g_buf under the lock. It does not
#      advance g_consumed (that is the separate kNavi48SelLogConsume streaming path, not called here) and does not clear
#      g_used. The verb `logreset` (kNavi48SelLogReset, navi48test.c:3594) and `logstream` (consumes) are never called.
#
# 2. The connection itself: open_service() (tools/pc/navi48test.c:44-60) does IOServiceOpen on service "Navi48Bringup"
#    (src/navi48-bringup/src/Navi48UserClientABI.h:17) with type 0. Navi48Bringup::newUserClient sends only type 'N48N'
#    to the native client (src/navi48-bringup/src/Navi48Bringup.cpp:7163); type 0 gets the legacy Navi48UserClient,
#    whose initWithTask admits only administrators (Navi48UserClient.cpp:44-56). No 'N48N' open happens, so no native
#    session slot is taken and no session is created or closed. No GPU register or ring is touched.
#
# 3. `navi48test accel appallow list <page>` and `navi48test accel appallow strikes`:
#    - cmd_accel() (navi48test.c:1533, 1976-1985) sends kNavi48SelAccelExperiment with action 104.
#    - doAccelExperiment (Navi48UserClient.cpp:540) -> Navi48Bringup.cpp (action 104 branch, ~line 7593) ->
#      amdgpu::n1c_app_verb (src/navi48-bringup/src/amd/native_s1c.cpp:2219) -> verb_run
#      (src/navi48-bringup/src/amd/native_g4_pure.h:143-165).
#    - verb_run executes ADD and REMOVE (writes to the allow-list) only for those ops. LIST and STRIKES only load the
#      table. This script never passes the `add` or `remove` argument (navi48test.c:1976-1985 rejects them without a name).
#    - Side effect to know about: each call writes ONE line ("accel-experiment: appallow op ...") into the driver log
#      ring, through N48LOG in Navi48Bringup.cpp. That is a log append, not state. It is why the ring is read first.
#
# NOT USED, ON PURPOSE:
#    - `accel sessstat <page>` (action 103): the kernel comment says READ-ONLY, but
#      tools/baremetal/navi44-gpu-diagnostics/session-check.py documents that sessstat "updates its diagnostic fault
#      baseline". Since the sources disagree, this script does not call it. Session slot state is therefore not read here.
#    - `accel status|fire|...`, `logreset`, `logstream`, `power`, `test`, and any IOServiceOpen of type 'N48N'.
#    - Metal (`/usr/bin/log show` for the APP probe lines) is not run by this script, because it needs no privilege.
#      Use the command printed at the end of this script's output to match processes with their pid and time.
#
# OUTPUT SECTIONS
#    A. Ring size, capacity warning.
#    B. Trace events of interest (1 PROBE_OK, 2 DEVICE_OPEN, 3 DEVICE_CLOSE, 4 POPULATE, 10 STARTED, 15 NATIVE_OPEN),
#       event 15 decoded to its IOReturn name.
#    C. Admission lines (app open / open admitted / open refused / appallow).
#    D. Allow-list pages 0..3 and strike table.
#    E. Heuristic verdict, outcomes E0..E8 (the decision table in the diagnosis report).
#
# NOTE ON PROCESS IDENTITY: the event 15 record carries only the rc and the client pointer, no pid. The bring-up's
# "app open: uid .., process .." line (native-s1c) precedes the event in the ring, and the script prints the most recent
# one as "prior". That line is only logged for the first 64 app opens of the boot (native_s1c.cpp, gAppOpenLogged),
# so it can be missing. An 0xe00002c7 open never reaches the bring-up at all, so it has no event 15 and no ring line.
# Those are matched only through the unified log APP probe lines, printed at the end.

TOOL="/Library/Application Support/Navi44/accelerated-trial/navi48test"

if [ "$(/usr/bin/id -u)" -ne 0 ]; then
    echo "read-admission-trace.sh: run with sudo (the legacy Navi48UserClient is administrator-only)." >&2
    exit 2
fi
if [ ! -x "$TOOL" ]; then
    echo "read-admission-trace.sh: $TOOL not found or not executable." >&2
    exit 2
fi

echo "== A/B/C. driver log ring (navi48test log: read-only, see header step 1) =="
"$TOOL" log 2>&1 | /usr/bin/awk '
BEGIN {
    rcname["0x0"]         = "Success"
    rcname["0xe00002c1"]  = "NotPrivileged (bring-up policy refusal: allow-list or role, Navi48NativeClient.cpp:39)"
    rcname["0xe00002c2"]  = "BadArgument"
    rcname["0xe00002bd"]  = "NoMemory"
    rcname["0xe00002be"]  = "NoResources"
    rcname["0xe00002c5"]  = "ExclusiveAccess (slots busy, native_s1c.cpp:920)"
    rcname["0xe00002c7"]  = "Unsupported (aux refused before the bring-up: nuc_plan / N48_AUX_ENTER, Navi48Accel.cpp:511-520)"
    rcname["0xe00002c9"]  = "InternalError (aux: success with no client)"
    rcname["0xe00002d8"]  = "NotReady (bring-up gate: device/nub/HUNG, Navi48MetalNub.cpp op_native_open)"
    lastid = "(none before this event)"
    lastdev = "(no device event in ring)"
}
/ReadLog failed/ { print "ERROR: " $0; bad = 1 }
/bytes of driver log/ { footer = $0 }
/AT CAPACITY/ { cap = 1 }
/native-s1c: (app open|open admitted|open refused)/ {
    lastid = "ring line " NR ": " substr($0, index($0, "native-s1c:"), 220)
    if ($0 ~ /app open:/) nappopen++
    if ($0 ~ /open admitted/) nadmit++
    if ($0 ~ /open refused/) nrefused++
    print "  ring line " NR ": " substr($0, index($0, "native-s1c:"), 220)
}
/appallow/ { print "  ring line " NR ": " substr($0, 1, 220) }
/aux trace: event [0-9]+ a 0x[0-9a-fA-F]+ b 0x[0-9a-fA-F]+/ {
    if (!match($0, /aux trace: event [0-9]+ a 0x[0-9a-fA-F]+ b 0x[0-9a-fA-F]+/)) next
    seg = substr($0, RSTART, RLENGTH)
    split(seg, f, " ")
    ev = f[4]; a = tolower(f[6]); b = f[8]
    nev[ev]++
    if (ev == 1) nprobe++
    if (ev == 10) nstarted++
    if (ev == 2) lastdev = "DEVICE_OPEN at ring line " NR
    if (ev == 3) lastdev = "DEVICE_CLOSE at ring line " NR
    if (ev == 15) {
        nn15++
        nm = (a in rcname) ? rcname[a] : "unmapped rc " a
        cnt15[a]++
        printf "  ring line %d: NATIVE_OPEN rc=%s  %s  client=%s\n      prior identity: %s\n", NR, a, nm, b, lastid
    } else if (ev == 2 || ev == 3 || ev == 4 || ev == 10 || ev == 1) {
        printf "  ring line %d: event %s a=%s b=%s\n", NR, ev, a, b
    }
}
END {
    print ""
    print "ring footer: " (footer == "" ? "(none: the tool printed no size line)" : footer)
    if (cap) print "WARNING: the ring is AT CAPACITY. The driver stops appending when full (n48log.cpp), so later events, including the refusals, are NOT in this output."
    print "counts: event1 PROBE_OK=" nprobe+0 "  event10 STARTED=" nstarted+0 "  event15 NATIVE_OPEN=" nn15+0 "  app-open lines=" nappopen+0 "  admitted=" nadmit+0 "  refused=" nrefused+0
    print "last device event: " lastdev
    print ""
    print "== E. heuristic verdict (see header; the table in the report decides) =="
    if (bad) print "E0 the log could not be read: nothing below is evidence."
    if (nprobe + 0 == 0) print "E7 no event 1 (PROBE_OK) in the ring: the aux kext never published its ops table to the bring-up. Fix: aux/bring-up ops handshake (Navi48MetalNub.cpp op table, Navi48Accel.cpp probe)."
    if (cap) print "E6 ring at capacity: this readout is incomplete. Reproduce after a human runs `sudo navi48test logreset`, then open the app again and rerun this script."
    if (cnt15["0xe00002c1"] + 0 > 0) print "E1 event 15 shows NotPrivileged: opens DO reach the bring-up and are refused by policy (allow-list or role). Fix: bring-up admission policy (`sudo navi48test accel appallow add <name>` or the navi48-apps role). Note this would surface as 0xe00002c1 in Metal, not c7, so the c7 opens are a different path."
    if (cnt15["0xe00002c5"] + 0 > 0) print "E2 event 15 shows ExclusiveAccess: slots are full. Not an 0xe00002c7 cause. Fix: close sessions (bring-up session pool)."
    if (cnt15["0xe00002c7"] + 0 > 0) print "E3 event 15 shows Unsupported: unexpected, the bring-up never returns c7 itself (native_open_verdict, native_metal_pure.h:207). Check the accel kext build matches the bring-up build."
    if (nn15 + 0 == 0 && (lastdev ~ /DEVICE_CLOSE/ || lastdev ~ /no device event/)) print "E4 no event 15 and the last device event is DEVICE_CLOSE: the accelerator has no device context (ctx == nullptr), so nuc_plan returns kNucUnsupported (Navi48Accel.cpp:517-520). Fix: accel kext device lifecycle (configureDevice / teardownDevice / populateAccelConfig, Navi48Accel.cpp:380-420)."
    if (nn15 + 0 == 0 && lastdev ~ /DEVICE_OPEN/ && nprobe + 0 > 0) print "E5 no event 15 although a device context exists: the refusal is decided in the aux nuc_plan gate (gate, ops ABI or capability bit, n48accel_pure.h:120-123). Fix: accel kext (and a new trace event for the plan refusal, not present yet)."
    if (nn15 + 0 > 0 && cnt15["0x0"] + 0 == nn15 + 0) print "E8 every event 15 is Success: the bring-up admitted every open the aux saw. A c7 seen in Metal then comes from a DIFFERENT accelerator object or port. Compare the Metal `initWithAcceleratorPort` value with the aux object."
}'
echo ""

echo "== D. allow-list (navi48test accel appallow list, read-only; appends one ring line per call) =="
for page in 0 1 2 3; do
    "$TOOL" accel appallow list "$page" 2>&1
done
"$TOOL" accel appallow strikes 2>&1
echo ""

echo "== Unified log: match these APP probe lines to pid and time (no privilege needed) =="
echo "  /usr/bin/log show --start \"2026-10-31 17:37:00\" --style compact --predicate 'eventMessage CONTAINS \"APP probe\"'"
