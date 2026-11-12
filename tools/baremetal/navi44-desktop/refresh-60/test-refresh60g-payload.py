#!/usr/bin/env python3
"""Check the 0.0.675 (GFX clock gating + thermal policy) kernel candidate and payload v11 against their reviewed inputs.

Release record: RELEASES['0.0.675'] (production-kernel-payload.py) holds the reviewed values: the candidate binary, the 0.0.674 EFI it replaces (payload v10's
candidate state, the installed EFI: kernel-payload-v10-193959, the latest v10 directory), the navi48test it carries, the reused probe, the base and the carried files.
Candidate: kernel-contexts-v11 is the reviewed 0.0.674 candidate TREE (kernel-contexts-v10) with kernel-0.0.675-over-0.0.674.diff applied (its sha256 is pinned in
build-production-contexts.py) and the 0.0.675 markers (kN1cKextBuild, the Metal ops build number). The test applies the patch again to a copy of the 0.0.674 tree
and compares the result with the candidate's recorded inputs.
Guard: the 0.0.675 guard is derived from the LIVE guard at stage time (payload v11's evidence copy, which is the installed 0.0.674 guard, payload v10's) with exactly
five lines changed, each 674 -> 675. Nothing else in the guard changes.
EFI: payload v11's EFI is payload v10's EFI with the 0.0.675 kext and its recovery copy added and the boot configuration's BundlePath moved to 0.0.675; nothing else changes.

Reads files only (plus the bash checks and the patch check in a temporary directory). The live guard is not read here.
"""
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True   # no __pycache__ inside the repository
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DESKTOP = HERE.parent
BUILDS = ROOT / 'research/builds/macos-20261112/kernel-675'
V10 = ROOT / 'research/builds/macos-20261112/kernel-674/kernel-payload-v10-193959'
V11 = BUILDS / 'kernel-payload-v11'
CAND = BUILDS / 'kernel-contexts-v11'
BASE674 = ROOT / 'research/builds/macos-20261112/kernel-674/kernel-contexts-v10'
PATCH = BUILDS / 'PATCHES/kernel-0.0.675-over-0.0.674.diff'
BINARY = CAND / 'candidate-source/build/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup'
KEXT = 'OC/Kexts/Navi48Bringup-contexts-0.0.675.kext'
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'
NAVI_REL = APP + '/navi48test'
TREE_NAMES = ('src', 'firmware', 'shaders', 'tools')
TEST_LOGS = ('test-kernel-vmid-leases.py', 'test-kernel-context-close.py', 'test-kernel-bo-release.py', 'test-kernel-wait-identity.py',
             'test-kernel-query-info.py', 'test-kernel-app-admission.py', 'test-kernel-refresh60.py', 'test-kernel-refresh60-wiring.py')

# The reviewed values, written out here so that a change to the script alone cannot move them.
KERNEL_675 = '70b8dbfa950be263817f90e4e55750d3484e9ca63be0a9a6f1f83d68e08fefc2'
KERNEL_674 = 'b71f535783f95c92dae163953c3579da7b0479a7841ebac120529d88f1399036'
CONFIG_673 = 'd3a39e1a8d281e5685187a156fd03cd2803dd9393c8dac5befc40219b276272c'   # payload v9's candidate configuration (v10's baseline copy)
CONFIG_674 = 'd75bbca200f02456180acab51ba415c7ca120a4e529d43704818078ffc2d9bd5'   # payload v10's candidate configuration (v11's baseline)
CONFIG_675 = '87b4220a1dd0d0b14c828af2caf481ddefb34b620068b418e1a47912b0ea5d0e'   # payload v11's candidate configuration
GUARD_674 = 'bafae54f8c24a69c80470c9a1a16b3c80367075bc632a8120924d91d4d13adac'   # payload v10's guard = the live guard, installed (v11's input)
GUARD_675 = '3c5f062535e39168b6cf346ba6c94d3ec40aa5e9b4e1b73ee9e5109a1b8debae'   # payload v11's guard
PATCH_SHA = '5a9f0732bda1ef460cc78ef67d07c90f39f52769407ea7b43eeb8ce1db7396dc'
PROBE = '5afe2b52b0c0adc7a4bf1ea8f8e07437929ed9cfe066fa1f56a39240ceb000c5'
PROBE_SELF_TEST_SHA = '934011ce4b4a3f4ebaabe6b69247e06f13f39387976c790ccfc65fb95c2d75ed'
NAVI48TEST_SHA = '83e7f3e3c9609ce636e138acf5a5186dbf6ef5c8951bcc6342eb21a1d058b94c'
METAL_38 = {'Contents/MacOS/Navi48Metal': 'c919abd8e603fb6c424e7a318929cd11158348a11b35529d74a915bffa1ab230',
            'Contents/Resources/libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
            'Contents/Resources/libn48xlate.dylib': 'c79adc839e8ec9dda7d042eb8469630faa5dfff304105d14c41f88fb8e522f62'}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load('payload', DESKTOP / 'production-kernel-payload.py')
R675 = m.RELEASES['0.0.675']


def sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def tree_inputs(root):
    """The candidate's recorded inputs, computed as build-production-contexts.py computes them (tree_files)."""
    result = {}
    for name in (*TREE_NAMES, 'Makefile', 'Info.plist'):
        paths = [root / name] if (root / name).is_file() else sorted((root / name).rglob('*'))
        for p in paths:
            if p.is_file():
                result[p.relative_to(root).as_posix()] = m.sha(p)
    return result


def replace_once(path, old, new, count):
    text = path.read_text()
    if text.count(old) != count:
        raise AssertionError('unexpected count in ' + str(path) + ': ' + old[:60])
    path.write_text(text.replace(old, new))


class Release675(unittest.TestCase):
    def test_the_release_record_is_the_reviewed_one(self):
        self.assertEqual(R675['new'], 'Navi48Bringup-contexts-0.0.675.kext')
        self.assertEqual(R675['recovery'], 'RECOVERY/pre-contexts-675-config.plist')
        self.assertEqual(R675['from'], 'Navi48Bringup-contexts-0.0.674.kext')
        self.assertEqual(R675['from_kernel_sha'], KERNEL_674)
        self.assertEqual(R675['from_config_sha'], CONFIG_674)
        self.assertEqual(R675['kernel_sha'], KERNEL_675)
        self.assertEqual(R675['tests'], 8)
        self.assertEqual(R675['base'], 'reviewed-candidate-674')
        self.assertEqual(R675['base_kernel_sha'], KERNEL_674)   # the 0.0.674 candidate tree the 0.0.675 patch is applied to
        self.assertEqual(R675['probe_reuse'], PROBE)
        self.assertEqual(R675['system_files'], {m.APP + '/navi48test': NAVI48TEST_SHA})
        self.assertEqual(R675['binary_checks'], 'not-run')
        self.assertEqual(R675['self_test_log_sha'], PROBE_SELF_TEST_SHA)
        self.assertEqual(R675['guard'], 'live-675')
        self.assertIsNone(R675['metal'])
        self.assertIsNone(R675['metal_version'])
        self.assertEqual(R675['edits'], [{'path': 'Kernel/Add/7/BundlePath', 'old': 'Navi48Bringup-contexts-0.0.674.kext',
                                          'new': 'Navi48Bringup-contexts-0.0.675.kext'}])
        self.assertEqual(R675['extras'], {'RECOVERY/pre-contexts-675-config.plist': 'baseline'})
        self.assertEqual(R675['carried']['RECOVERY/pre-contexts-674-config.plist'], CONFIG_673)   # payload v10's own recovery copy
        for name, digest in m.RELEASES['0.0.674']['carried'].items():   # everything payload v10 carried is carried again
            self.assertEqual(R675['carried'][name], digest, name)
        self.assertNotIn('RECOVERY/pre-contexts-675-config.plist', R675['carried'])
        for text in ('GTT BO could not be given wired pages', 'Navi48,UclkPin', 'Navi48,DisplayUnderflow', 'Navi48,DisplayArb',
                     'disparb: display monitor started', 'ufmon: UCLK fallback', '10 min without underflow', 'OPTC alone %llu',
                     'fallback stage 1 (stutter off, no pin)', 'Navi48,ClockGating', 'navi48-cg-ints',
                     'event=%s reason=%s hotspot=%d power_state=%u', 'TRIP clamps GFXCLK, never refuses submissions'):
            self.assertIn(text, R675['strings'])

    def test_the_candidate_build_is_the_recorded_0_0_675_kernel(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        self.assertEqual(build['status'], 'built-cpu-tested-not-installed-hardware-unverified')
        self.assertEqual(build['candidate_version'], '0.0.675')
        self.assertEqual(build['candidate_binary_sha256'], KERNEL_675)
        self.assertEqual(m.sha(BINARY), KERNEL_675)
        self.assertEqual(len(build['cpu_tests']), R675['tests'])
        self.assertEqual(build['cpu_tests'], list(TEST_LOGS))
        self.assertTrue(set(R675['strings']) <= set(build['required_strings']))
        self.assertEqual(build['active_baseline'], {'bundle_path': 'Navi48Bringup-contexts-0.0.674.kext', 'kernel_sha256': KERNEL_674,
                                                    'config_sha256': CONFIG_674, 'version': '0.0.674'})
        self.assertTrue(m.reviewed_base(build, R675))
        self.assertFalse(m.reviewed_base(build, m.RELEASES['0.0.674']))   # not the 0.0.672 base
        self.assertEqual(build['overlay']['source'], 'patch')
        self.assertEqual(build['overlay']['patch_sha256'], PATCH_SHA)
        self.assertEqual(build['gating_overlay']['patch_sha256'], PATCH_SHA)

    def test_the_candidate_is_the_0_0_674_tree_with_the_patch_and_the_markers_only(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        base = json.loads((BASE674 / 'manifest.json').read_text())
        self.assertEqual(base['candidate_version'], '0.0.674')
        self.assertEqual(base['candidate_binary_sha256'], KERNEL_674)
        self.assertEqual(build['base_verified'], {'manifest': str((BASE674 / 'manifest.json').relative_to(ROOT)),
                                                  'candidate_inputs_checked': len(base['candidate_inputs']), 'binary_sha256': KERNEL_674})
        self.assertEqual(build['baseline_inputs'], base['candidate_inputs'])
        self.assertEqual(build['changed_source_files'], sorted([
            'Info.plist', 'src/Navi48Bringup.cpp', 'src/Navi48MetalNub.cpp', 'src/Navi48NativeClient.cpp', 'src/Navi48UserClient.cpp',
            'src/amd/gfx_v12_0_cg.cpp', 'src/amd/gfx_v12_0_cg.h', 'src/amd/gfx_v12_0_cg_pure.h', 'src/amd/n4x_safety.cpp', 'src/amd/n4x_safety.h',
            'src/amd/n4x_safety_pure.h', 'src/amd/native_s1c.h']))
        self.assertEqual(m.sha(PATCH), PATCH_SHA)
        with tempfile.TemporaryDirectory(prefix='refresh60g-patch-') as tmp:
            work = Path(tmp)
            for name in TREE_NAMES:
                shutil.copytree(BASE674 / 'candidate-source' / name, work / name)
            for name in ('Makefile', 'Info.plist'):
                shutil.copyfile(BASE674 / 'candidate-source' / name, work / name)
            subprocess.run(['patch', '-p1', '-s', '--forward', '--batch', '--no-backup-if-mismatch', '-d', str(work), '-i', str(PATCH)], check=True)
            replace_once(work / 'src/amd/native_s1c.h', 'kN1cKextBuild = 674;', 'kN1cKextBuild = 675;', 1)
            replace_once(work / 'src/Navi48MetalNub.cpp', 'sizeof(N48MetalOps), 674u', 'sizeof(N48MetalOps), 675u', 2)
            derived = tree_inputs(work)
        self.assertEqual(derived, build['candidate_inputs'])
        self.assertEqual(tree_inputs(CAND / 'candidate-source'), build['candidate_inputs'])

    def test_the_candidate_markers_and_the_test_logs(self):
        source = CAND / 'candidate-source'
        plist = (source / 'Info.plist').read_text()
        self.assertEqual(plist.count('<string>0.0.675</string>'), 2)
        self.assertNotIn('<string>0.0.674</string>', plist)
        self.assertIn('kN1cKextBuild = 675;', (source / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((source / 'src/Navi48MetalNub.cpp').read_text().count('sizeof(N48MetalOps), 675u'), 2)
        for name in TEST_LOGS:
            self.assertIn('PASS', (CAND / (name + '.log')).read_text(), name)
        self.assertIn('0.0.675 verb dispatch', (CAND / 'test-kernel-refresh60-wiring.py.log').read_text())
        self.assertIn('refresh60_test: 176 checks, 0 failures', (CAND / 'test-kernel-refresh60.py.log').read_text())
        self.assertIn('native_gtt_test: 71 checks, 0 failures', (CAND / 'test-kernel-bo-release.py.log').read_text())

    def test_the_binary_carries_the_gating_the_thermal_policy_and_the_earlier_fixes(self):
        binary = BINARY.read_bytes()
        for text in (b'Navi48,DisplayArb', b'Navi48,UclkPin', b'Navi48,DisplayUnderflow', b'GTT BO could not be given wired pages', b'Navi48,RefreshHz',
                     b'navi48-det', b'navi48-wm', b'navi48-sr', b'navi48-dispmon', b'navi48-uclkpin', b'navi48-ufmon',
                     b'10 min without underflow', b'OPTC alone %llu', b'fallback stage 1 (stutter off, no pin)',
                     b'Navi48,ClockGating', b'navi48-cg', b'navi48-cg-ints', b'RLC_CGTT_MGCG_OVERRIDE', b'CP_INT_CNTL_RING0',
                     b'event=%s reason=%s hotspot=%d power_state=%u', b'TRIP clamps GFXCLK, never refuses submissions', b'navi48-idle-clamp'):
            self.assertIn(text, binary, text)
        src = CAND / 'candidate-source/src'
        bringup = (src / 'Navi48Bringup.cpp').read_text()
        self.assertIn('char t[640];   // 0.0.674', bringup)   # 0.0.674's change is still there
        self.assertIn('(void)amdgpu::gfx_v12_0_enable_clock_gating(dev, dev.ip.isResolved(amdgpu::IPBlock::SDMA1), cgInts);', bringup)
        self.assertLess(bringup.index('gfx_v12_0_enable_clock_gating(dev'), bringup.index('(void)amdgpu::native_s1b_run(ctx);'))   # before the native self-test
        self.assertLess(bringup.index('kern_return_t r = amdgpu::bringup_to(ctx, (amdgpu::BringupStage)target);'), bringup.index('gfx_v12_0_enable_clock_gating(dev'))
        self.assertIn('n4xs::set_restore_state(ctx.idleClamp ? amdgpu::SMUPowerState::Low : amdgpu::SMUPowerState::Auto);', bringup)
        self.assertIn('uint32_t clamp = 1;\n\tPE_parse_boot_argn("navi48-idle-clamp", &clamp, sizeof(clamp));', bringup)   # the idle clamp default is unchanged
        native = (src / 'Navi48NativeClient.cpp').read_text()
        self.assertIn('if (n4xs::submit_refused()) return kIOReturnNotPermitted;', native)
        self.assertEqual(native.count('n4xs::refused()'), 3)   # DAL step, mode trial, mode hold: still refused on TRIP
        user = (src / 'Navi48UserClient.cpp').read_text()
        self.assertIn('if (n4xs::submit_refused()) return kIOReturnNotPermitted;', user)
        self.assertIn('if (n4xs::refused() && state != amdgpu::SMUPowerState::Low) return kIOReturnNotPermitted;', user)
        pure = (src / 'amd/n4x_safety_pure.h').read_text()
        for text in ('constexpr int32_t kDefaultWarnC      = 90;', 'constexpr int32_t kDefaultTripC      = 100;', 'constexpr int32_t kDefaultReleaseC   = 85;',
                     'constexpr uint64_t kReleaseHoldMs    = 10000;', 'constexpr int32_t kConfigMaxC        = 105;',
                     'inline bool refuses_submissions(bool stopping, uint32_t /*level*/) { return stopping; }'):
            self.assertIn(text, pure)
        cg = (src / 'amd/gfx_v12_0_cg_pure.h').read_text()
        self.assertIn('constexpr uint32_t kCgcgIdleThreshold         = 0x36;', cg)
        self.assertIn('constexpr uint32_t kSafeModePollUs            = 100000;', cg)
        self.assertNotIn('sysmem_alloc(', (src / 'amd/native_s1c.cpp').read_text())


class Guard675(unittest.TestCase):
    def setUp(self):
        # the 0.0.675 input is the live guard at stage time (payload v11's evidence copy, which is the installed 0.0.674 guard = payload v10's)
        self.live = (V11 / 'evidence/original-guard.sh').read_text()
        self.v10 = (V10 / 'system' / GUARD).read_text()
        self.v11 = (V11 / 'system' / GUARD).read_text()

    def test_the_input_guard_is_the_installed_guard(self):
        self.assertEqual(m.sha(V11 / 'evidence/original-guard.sh'), GUARD_674)
        self.assertEqual(self.live, self.v10)   # payload v10 installed exactly this guard

    def test_the_guard_on_disk_is_the_derived_guard_pinned(self):
        self.assertEqual(sha_text(self.v11), GUARD_675)
        self.assertEqual(m.sha(V11 / 'system' / GUARD), GUARD_675)
        self.assertEqual(self.v11, m.make_guard(R675, self.live, PROBE, '0.0.675'))
        self.assertEqual(self.v11, m.bump_guard_675(self.live, PROBE))

    def test_exactly_five_lines_change_from_674_to_675(self):
        before, after = self.live.splitlines(), self.v11.splitlines()
        self.assertEqual(len(before), len(after))
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 5, changed)
        for a, b in changed:
            self.assertEqual(a.replace('674', '675'), b)

    def test_no_reference_to_kernel_674_remains(self):
        for old in ('0.0.674', 'kernel 674', '0\\.0\\.674'):
            self.assertNotIn(old, self.v11)

    def test_the_capability_block_and_the_hook_are_present_exactly_once(self):
        block = m.capability_block(m.KERNEL_BRANCH_675, PROBE)
        self.assertEqual(self.v11.count(block), 1)
        self.assertEqual(self.v11.count('REFRESH60_INSTALLED'), 1)
        self.assertEqual(self.v11.count('refresh_begin() {'), 1)
        self.assertEqual(self.v11.count("local re_bringup='com\\.navi48\\.bringup[[:space:]]+\\(0\\.0\\.675\\)'"), 1)

    def test_the_metal_expectations_are_the_bundle_38_pins(self):
        version, pins = m.live_metal_pins(self.v11)
        self.assertEqual(version, '38')
        self.assertEqual(pins, METAL_38)
        self.assertEqual(m.live_metal_pins(self.live), (version, pins))

    def test_bash_accepts_the_guard(self):
        r = subprocess.run(['/bin/bash', '-n', str(V11 / 'system' / GUARD)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


FAKE_NT = r'''#!/bin/bash
echo "$*" >> "$CALLS"
case "$*" in
  "accel sessstat 95") echo "slot / VMID / session : $FAKE_SESSION" ;;
  "accel refresh 60 120") echo "refresh: code 0 (ok) active 60 Hz" ;;
esac
'''
FAKE_PROBE = '#!/bin/bash\nif [ "$1" = "--check-profile" ]; then echo PROFILE_OK; fi\n'
CAPABILITY_HARNESS = r'''kmutil() { printf '%s\n' "$FAKE_LOADED"; }
ioreg() { :; }
'''
HOOK_HARNESS = r'''kmutil() { printf '%s\n' "$FAKE_KEXTS"; }
root_flag_valid() { [[ "$FAKE_FLAG_VALID" == 1 ]]; }
'''


def run_script(work, text, env_extra):
    script = work / 'block.sh'
    script.write_text(text)
    calls = work / 'calls.txt'
    calls.unlink(missing_ok=True)
    env = {'PATH': os.environ['PATH'], 'APP': str(work / 'app'), 'NT': str(work / 'nt'), 'CALLS': str(calls), **env_extra}
    result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    return result.returncode, (lines[-1] if lines else ''), result.stdout, (calls.read_text() if calls.exists() else '')


def function_text(text, name):
    start = text.index(name + '() {\n')
    return text[start:text.index('\n}\n', start) + 3]


class Gates675(unittest.TestCase):
    """The capability block and the refresh hook of the 0.0.675 guard, run in bash against fake commands."""

    def setUp(self):
        self.guard = (V11 / 'system' / GUARD).read_text()
        self.tmp = tempfile.TemporaryDirectory(prefix='refresh60g-gates-')
        self.work = Path(self.tmp.name)
        (self.work / 'app').mkdir()
        probe = self.work / 'app/context-isolation-probe'
        probe.write_text(FAKE_PROBE)
        probe.chmod(0o755)
        self.probe_sha = hashlib.sha256(probe.read_bytes()).hexdigest()   # the digest the block checks: the fake probe's
        nt = self.work / 'nt'
        nt.write_text(FAKE_NT)
        nt.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_capability_block_accepts_0_0_675_and_stops_the_others(self):
        block = m.capability_block(m.KERNEL_BRANCH_675, self.probe_sha)
        script = CAPABILITY_HARNESS + 'loaded=$(kmutil showloaded --list-only)\n' + block
        line = lambda kernel: '  12 0 0x0 0x0 com.navi48.bringup (%s) 1 UUID' % kernel
        env = {'FAKE_SESSION': '63 / 9 / 1'}
        rc, _, out, calls = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.675')})
        self.assertEqual(rc, 0)
        self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', out)
        self.assertIn('accel sessstat 95', calls)
        rc, _, out, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.665')})
        self.assertEqual(rc, 0)
        self.assertIn('CAPABILITY_CHECKS=skipped for kernel 0.0.665', out)
        for kernel in ('0.0.674', '0.0.673', '0.0.672', '0.0.671', '0.0.670', '0.0.669'):
            with self.subTest(kernel=kernel):
                rc, last, _, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line(kernel)})
                self.assertEqual((rc, last), (1, 'STOP expected kernel 675 or 665'))

    def test_the_hook_gate_requests_60_only_for_0_0_675_with_the_flag(self):
        fn = function_text(self.guard, 'refresh_begin')
        flag = self.work / 'app/refresh-60'
        kexts_675 = ('  92 0 0xffffff8004240000 0x7eb000 0x7eb000 com.navi48.bringup (0.0.675) 9716F9B9-A7FA-3BC4-9A9D-2CCC29AF069F <19 9 7 6 3 1>\n'
                     '  93 0 0xffffff8004340000 0x1000 0x1000 com.hackintosh.RDNA4FB (0.0.9) 1A2B3C4D-0000-0000-0000-000000000000 <5 3 2>\n')
        kexts_674 = kexts_675.replace('(0.0.675)', '(0.0.674)')
        kexts_672 = kexts_675.replace('(0.0.675)', '(0.0.672)')
        kexts_rdna8 = kexts_675.replace('(0.0.9)', '(0.0.8)')
        script = HOOK_HARNESS + 'refresh_active=0\nREFRESH_TIMEOUT=120\nREFRESH_FLAG="$APP/refresh-60"\n' + fn + '\nrefresh_begin\necho "rc=$?"\n'
        base = {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts_675}
        # no flag file: nothing runs
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual((rc, last, calls), (0, 'rc=0', ''))
        # flag present, 0.0.675 and RDNA4FB 0.0.9: the 60 Hz request with the 120 s timeout
        flag.write_text('')
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual(rc, 0)
        self.assertIn('REFRESH60_REQUESTED', out)
        self.assertEqual(calls.strip(), 'accel refresh 60 120')
        # 0.0.674, 0.0.672 or another RDNA4FB: refused by name, no request
        for name, kexts in (('0.0.674', kexts_674), ('0.0.672', kexts_672), ('RDNA4FB 0.0.8', kexts_rdna8)):
            with self.subTest(kexts=name):
                rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts})
                self.assertIn('REFRESH60_SKIPPED loaded kexts are not 0.0.675 and RDNA4FB 0.0.9', out)
                self.assertEqual(calls, '')
        # a flag that is not root-owned 0644: refused, no request
        rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '0', 'FAKE_KEXTS': kexts_675})
        self.assertIn('REFRESH60_SKIPPED flag is not a root-owned 0644 regular file', out)
        self.assertEqual(calls, '')


class Efi675(unittest.TestCase):
    def test_efi_is_the_674_installed_state_plus_the_listed_675_files_only(self):
        man = json.loads((V11 / 'manifest.json').read_text())
        v9 = json.loads((V10 / 'manifest.json').read_text())
        self.assertEqual(man['candidate_version'], '0.0.675')
        self.assertEqual(man['candidate_kernel_sha256'], KERNEL_675)
        self.assertEqual(man['baseline_config_sha256'], CONFIG_674)
        self.assertEqual(man['candidate_config_sha256'], CONFIG_675)
        self.assertEqual(man['baseline_efi_files'], v9['candidate_efi_files'])
        t9, t10 = m.tree(V10 / 'EFI'), m.tree(V11 / 'EFI')
        self.assertEqual({n for n in t9 if t10.get(n) != t9[n]}, {'OC/config.plist'})
        added = set(t10) - set(t9)
        self.assertEqual(added, {n for n in added if n.startswith(KEXT + '/')} | {'RECOVERY/pre-contexts-675-config.plist'})
        self.assertEqual(sorted(man['add_files']), sorted(added))
        self.assertEqual(m.sha(V11 / 'EFI' / KEXT / 'Contents/MacOS/Navi48Bringup'), KERNEL_675)

    def test_the_configuration_differs_only_in_the_bundle_path(self):
        before = plistlib.loads((V10 / 'EFI/OC/config.plist').read_bytes())
        after = plistlib.loads((V11 / 'EFI/OC/config.plist').read_bytes())
        self.assertEqual(m.diff_paths(before, after), ['/Kernel/Add/7/BundlePath'])
        self.assertEqual(after['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.675.kext')
        self.assertEqual(m.sha(V11 / 'EFI/OC/config.plist'), CONFIG_675)
        self.assertEqual(m.sha(V11 / 'EFI/RECOVERY/pre-contexts-675-config.plist'), CONFIG_674)
        self.assertEqual((V11 / 'EFI/RECOVERY/pre-contexts-675-config.plist').read_bytes(), (V10 / 'EFI/OC/config.plist').read_bytes())

    def test_the_kext_identity(self):
        info = plistlib.loads((V11 / 'EFI' / KEXT / 'Contents/Info.plist').read_bytes())
        self.assertEqual((info['CFBundleIdentifier'], info['CFBundleVersion']), ('com.navi48.bringup', '0.0.675'))

    def test_the_system_files_are_the_three_reviewed_files(self):
        system = {p.relative_to(V11 / 'system').as_posix() for p in (V11 / 'system').rglob('*') if p.is_file()}
        self.assertEqual(system, {GUARD, APP + '/context-isolation-probe', NAVI_REL})
        self.assertEqual(m.sha(V11 / 'system' / APP / 'context-isolation-probe'), PROBE)
        self.assertEqual(m.sha(V11 / 'system' / NAVI_REL), NAVI48TEST_SHA)
        self.assertEqual(m.sha(V11 / 'system' / GUARD), GUARD_675)
        for name in system:
            self.assertEqual((V11 / 'system' / name).stat().st_mode & 0o777, 0o755, name)
        self.assertEqual(m.sha(V11 / 'evidence/probe-self-test.log'), PROBE_SELF_TEST_SHA)
        self.assertEqual(m.sha(V11 / 'evidence/original-guard.sh'), GUARD_674)
        self.assertEqual(m.sha(V11 / 'evidence/build-manifest.json'), m.sha(CAND / 'manifest.json'))

    def test_the_payload_verifier_accepts_both_the_installed_and_the_staged_payloads_without_a_live_mount(self):
        self.assertEqual(m.verify(V10, live=False)['candidate_version'], '0.0.674')
        self.assertEqual(m.verify(V11, live=False)['candidate_version'], '0.0.675')

    def test_the_payload_holds_no_path_outside_the_release_layout(self):
        self.assertEqual({p.name for p in V11.iterdir()}, {'EFI', 'system', 'evidence', 'manifest.json'})
        self.assertEqual({p.name for p in (V11 / 'EFI').iterdir()}, {'OC', 'RECOVERY'})
        self.assertEqual({p.relative_to(V11 / 'evidence').as_posix() for p in (V11 / 'evidence').rglob('*') if p.is_file()},
                         {'build-manifest.json', 'original-guard.sh', 'probe-self-test.log'})


class Stage675(unittest.TestCase):
    def test_the_stage_script_names_the_675_paths_and_parses(self):
        script = HERE / 'stage-675-payload.sh'
        text = script.read_text()
        self.assertIn('macos-20261112/kernel-675/kernel-payload-v11', text)
        self.assertIn('macos-20261112/kernel-675/kernel-contexts-v11', text)
        self.assertIn('macos-20261112/kernel-674/kernel-payload-v10-193959', text)
        self.assertIn('--baseline-state candidate', text)
        self.assertTrue(os.access(script, os.X_OK))
        r = subprocess.run(['/bin/bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
