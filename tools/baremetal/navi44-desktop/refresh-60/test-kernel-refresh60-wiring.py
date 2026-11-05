#!/usr/bin/env python3
"""0.0.669/0.0.670 CPU test: the wiring of the 60 Hz verb in the candidate kernel source (static checks, no execution).
Checks: the verb is dispatched BEFORE the native-boot refusal and only for well-formed requests; the user client admits 109 and 110; the
lock is taken after the timer is created and released before the timer is removed; the stop path restores 120 Hz before the registers
are unmapped; the RDNA4FB property name is the one RDNA4FB 0.0.9 reads; the version markers are those of --version (default 0.0.669).
"""
from pathlib import Path
import argparse
import re

root = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernel-source', type=Path, required=True)
parser.add_argument('--version', default='0.0.669', help='the candidate CFBundleVersion the markers must carry (0.0.669 or 0.0.670)')
args = parser.parse_args()
if args.version not in ('0.0.669', '0.0.670'):
    raise SystemExit('unsupported --version: ' + args.version)
build_marker = int(args.version.rsplit('.', 1)[1])
src = args.kernel_source.resolve()
bringup = (src / 'src/Navi48Bringup.cpp').read_text()
client = (src / 'src/Navi48UserClient.cpp').read_text()
dcn = (src / 'src/dcn/navi48_dcn.cpp').read_text()
plist = (src / 'Info.plist').read_text()
s1c = (src / 'src/amd/native_s1c.h').read_text()
failures = []


def check(ok, what):
    if not ok:
        failures.append(what)


def between(text, start, end):
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# 1. dispatch before the native refusal, exempt only for well-formed requests
dispatch = bringup.find('if (n48rf::is_refresh_action(action)) {')
refusal = bringup.find('if (!n48scan::accel_exempt(action, argScalar) && !n48disp::native_exempt(')
check(dispatch != -1 and refusal != -1 and dispatch < refusal, 'the refresh dispatch is not before the native-boot refusal')
check('if (!n48rf::native_exempt(action, argScalar)) return kIOReturnBadArgument;' in bringup, 'malformed refresh requests are not refused')
check('return refreshVerb(action, argScalar, outExtra);' in bringup, 'the dispatch does not call refreshVerb')

# 2. the user client admits 109 and 110 (the bound check is the only other gate)
check('if (n48rf::is_refresh_action(action)) {' in client, 'the user client does not admit the refresh actions')
check(client.find('n48rf::is_refresh_action(action)') < client.find('n48native::g4::action_admitted(amdgpu::n1c_apps_enabled(), action)'),
      'the refresh admission is not the first branch of the admission chain')

# 3. the verb: the timer is made before the session lock is taken
verb = between(bringup, 'IOReturn Navi48Bringup::refreshVerb(', 'void Navi48Bringup::refreshShutdown()')
check(verb.index('refreshEnsureTimer()') < verb.index('IOLockLock(refreshLock)'), 'the revert timer must be created before the lock is taken')
check(verb.count('IOLockLock(refreshLock)') == 1 and verb.count('IOLockUnlock(refreshLock)') == 1, 'the verb must lock and unlock once')

# 4. the revert path takes the same lock; the shutdown removes the timer only after releasing the lock
shut = between(bringup, 'void Navi48Bringup::refreshShutdown()', 'IOReturn Navi48Bringup::accelExperiment(')
check(shut.index('IOLockUnlock(refreshLock)') < shut.index('removeEventSource(refreshTimer)'),
      'refreshShutdown removes the timer while holding the lock (deadlock with the timer action)')
fired = between(bringup, 'void Navi48Bringup::refreshTimerFired(', 'uint32_t Navi48Bringup::refreshRequestLocked(')
check('IOLockLock(refreshLock)' in fired and 'IOLockUnlock(refreshLock)' in fired, 'the automatic revert does not take the session lock')
check('restore120' in fired and 'setRefreshProperty(120)' in fired, 'the automatic revert does not restore 120 Hz and reset the property')

# 5. the stop path restores 120 Hz while the registers are still mapped
stop = between(bringup, 'void Navi48Bringup::stop(IOService *provider) {', 'void Navi48Bringup::free() {')
check(stop.index('refreshShutdown();') < stop.index('n48dcn::scanShutdown();'), 'the stop path does not restore 120 Hz before scanShutdown')
check(stop.index('refreshShutdown();') < stop.index('unmapRegisters();'), 'the stop path unmaps the registers before the refresh restore')

# 6. the RDNA4FB property: the name is shared with RDNA4FB 0.0.9
check('pciDevice->setProperty("Navi48,RefreshHz", value)' in bringup and 'OSNumber::withNumber(60ull, 32)' in bringup and 'OSNumber::withNumber(120ull, 32)' in bringup and 'refreshNum60->release()' in bringup,
      'the registry property must be set to the kext-retained OSNumber objects (a fresh object per call can be freed under the reader)')

# 7. the write allowlist callbacks are the only register path (dcn_wreg), and the refresh callbacks are present
check('n48rf::Hw refresh_hw()' in dcn and 'dcn_wreg(ctx, abs, value)' in dcn, 'refresh_hw does not write through dcn_wreg')
check('rf_wr' in dcn and 'dcn_rreg(ctx, abs)' in dcn, 'the refresh reads do not go through dcn_rreg')

# 8. version markers
check(plist.count('<string>%s</string>' % args.version) == 2, 'Info.plist is not ' + args.version)
check('kN1cKextBuild = %d;' % build_marker in s1c, 'kN1cKextBuild is not %d' % build_marker)

if failures:
    print('FAIL test-kernel-refresh60-wiring.py')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('PASS test-kernel-refresh60-wiring.py: %s verb dispatch, admission, lock order, shutdown order, property name, callbacks and markers' % args.version)
