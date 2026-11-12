#!/usr/bin/env python3
"""Check the 0.0.674 (two-stage UCLK fallback) kernel candidate and payload v10 against their reviewed inputs.

Release record: RELEASES['0.0.674'] (production-kernel-payload.py) holds the reviewed values: the candidate binary, the 0.0.673 EFI it replaces (payload v9's
candidate state, the installed EFI), the navi48test it carries, the reused probe, the base and the carried files.
Candidate: kernel-contexts-v10 is the reviewed 0.0.673 candidate TREE (kernel-contexts-v9) with kernel-0.0.674-over-0.0.673.diff applied (its sha256 is pinned in
build-production-contexts.py) and the 0.0.674 markers (kN1cKextBuild, the Metal ops build number). The test applies the patch again to a copy of the 0.0.673 tree
and compares the result with the candidate's recorded inputs.
Guard: the 0.0.674 guard is derived from the LIVE guard at stage time (payload v10's evidence copy, which is the installed 0.0.673 guard, payload v9's) with exactly
five lines changed, each 673 -> 674. Nothing else in the guard changes.
EFI: payload v10's EFI is payload v9's EFI with the 0.0.674 kext and its recovery copy added and the boot configuration's BundlePath moved to 0.0.674; nothing else changes.

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
BUILDS = ROOT / 'research/builds/macos-20261112/kernel-674'
V9 = ROOT / 'research/builds/macos-20261112/kernel-673/kernel-payload-v9'
V10 = BUILDS / 'kernel-payload-v10'
CAND = BUILDS / 'kernel-contexts-v10'
BASE673 = ROOT / 'research/builds/macos-20261112/kernel-673/kernel-contexts-v9'
PATCH = BUILDS / 'PATCHES/kernel-0.0.674-over-0.0.673.diff'
BINARY = CAND / 'candidate-source/build/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup'
KEXT = 'OC/Kexts/Navi48Bringup-contexts-0.0.674.kext'
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'
NAVI_REL = APP + '/navi48test'
TREE_NAMES = ('src', 'firmware', 'shaders', 'tools')
TEST_LOGS = ('test-kernel-vmid-leases.py', 'test-kernel-context-close.py', 'test-kernel-bo-release.py', 'test-kernel-wait-identity.py',
             'test-kernel-query-info.py', 'test-kernel-app-admission.py', 'test-kernel-refresh60.py', 'test-kernel-refresh60-wiring.py')

# The reviewed values, written out here so that a change to the script alone cannot move them.
KERNEL_674 = 'b71f535783f95c92dae163953c3579da7b0479a7841ebac120529d88f1399036'
KERNEL_673 = 'f53efdb50e4884c2a51c0d2cc2b9ab8d820527ea16851de4201698083dfda8f8'
CONFIG_671 = 'fa8c993c839a5a37794a54f178fbcee3e63a06901ddffe9efa9f65eb97429d57'   # payload v7's candidate configuration (v9's baseline copy)
CONFIG_673 = 'd3a39e1a8d281e5685187a156fd03cd2803dd9393c8dac5befc40219b276272c'   # payload v9's candidate configuration (v10's baseline)
CONFIG_674 = 'd75bbca200f02456180acab51ba415c7ca120a4e529d43704818078ffc2d9bd5'   # payload v10's candidate configuration
GUARD_673 = 'b6a9f2fc19b862753777259996a2be4ae2dcec2695b3a01dab35dc07a618cd79'   # payload v9's guard = the live guard, installed (v10's input)
GUARD_674 = 'bafae54f8c24a69c80470c9a1a16b3c80367075bc632a8120924d91d4d13adac'   # payload v10's guard
PATCH_SHA = 'ca223bc8fd32d217cce9057a16a5f4c3586c271e132a1d96056ab0f19d0c21af'
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
R674 = m.RELEASES['0.0.674']


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


class Release674(unittest.TestCase):
    def test_the_release_record_is_the_reviewed_one(self):
        self.assertEqual(R674['new'], 'Navi48Bringup-contexts-0.0.674.kext')
        self.assertEqual(R674['recovery'], 'RECOVERY/pre-contexts-674-config.plist')
        self.assertEqual(R674['from'], 'Navi48Bringup-contexts-0.0.673.kext')
        self.assertEqual(R674['from_kernel_sha'], KERNEL_673)
        self.assertEqual(R674['from_config_sha'], CONFIG_673)
        self.assertEqual(R674['kernel_sha'], KERNEL_674)
        self.assertEqual(R674['tests'], 8)
        self.assertEqual(R674['base'], 'reviewed-candidate-673')
        self.assertEqual(R674['base_kernel_sha'], KERNEL_673)   # the 0.0.673 candidate tree the 0.0.674 patch is applied to
        self.assertEqual(R674['probe_reuse'], PROBE)
        self.assertEqual(R674['system_files'], {m.APP + '/navi48test': NAVI48TEST_SHA})
        self.assertEqual(R674['binary_checks'], 'not-run')
        self.assertEqual(R674['self_test_log_sha'], PROBE_SELF_TEST_SHA)
        self.assertEqual(R674['guard'], 'live-674')
        self.assertIsNone(R674['metal'])
        self.assertIsNone(R674['metal_version'])
        self.assertEqual(R674['edits'], [{'path': 'Kernel/Add/7/BundlePath', 'old': 'Navi48Bringup-contexts-0.0.673.kext',
                                          'new': 'Navi48Bringup-contexts-0.0.674.kext'}])
        self.assertEqual(R674['extras'], {'RECOVERY/pre-contexts-674-config.plist': 'baseline'})
        self.assertEqual(R674['carried']['RECOVERY/pre-contexts-673-config.plist'], CONFIG_671)   # payload v9's own recovery copy
        self.assertEqual(R674['carried']['RECOVERY/pre-contexts-671-config.plist'], m.RELEASES['0.0.673']['carried']['RECOVERY/pre-contexts-671-config.plist'])
        self.assertNotIn('RECOVERY/pre-contexts-674-config.plist', R674['carried'])
        for text in ('GTT BO could not be given wired pages', 'Navi48,UclkPin', 'Navi48,DisplayUnderflow', 'Navi48,DisplayArb',
                     'disparb: display monitor started', 'ufmon: UCLK fallback', '10 min without underflow', 'OPTC alone %llu',
                     'fallback stage 1 (stutter off, no pin)'):
            self.assertIn(text, R674['strings'])

    def test_the_candidate_build_is_the_recorded_0_0_674_kernel(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        self.assertEqual(build['status'], 'built-cpu-tested-not-installed-hardware-unverified')
        self.assertEqual(build['candidate_version'], '0.0.674')
        self.assertEqual(build['candidate_binary_sha256'], KERNEL_674)
        self.assertEqual(m.sha(BINARY), KERNEL_674)
        self.assertEqual(len(build['cpu_tests']), R674['tests'])
        self.assertEqual(build['cpu_tests'], list(TEST_LOGS))
        self.assertTrue(set(R674['strings']) <= set(build['required_strings']))
        self.assertEqual(build['active_baseline'], {'bundle_path': 'Navi48Bringup-contexts-0.0.673.kext', 'kernel_sha256': KERNEL_673,
                                                    'config_sha256': CONFIG_673, 'version': '0.0.673'})
        self.assertTrue(m.reviewed_base(build, R674))
        self.assertFalse(m.reviewed_base(build, m.RELEASES['0.0.673']))   # not the 0.0.672 base
        self.assertEqual(build['overlay']['source'], 'patch')
        self.assertEqual(build['overlay']['patch_sha256'], PATCH_SHA)
        self.assertEqual(build['fallback_overlay']['patch_sha256'], PATCH_SHA)

    def test_the_candidate_is_the_0_0_673_tree_with_the_patch_and_the_markers_only(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        base = json.loads((BASE673 / 'manifest.json').read_text())
        self.assertEqual(base['candidate_version'], '0.0.673')
        self.assertEqual(base['candidate_binary_sha256'], KERNEL_673)
        self.assertEqual(build['base_verified'], {'manifest': str((BASE673 / 'manifest.json').relative_to(ROOT)),
                                                  'candidate_inputs_checked': len(base['candidate_inputs']), 'binary_sha256': KERNEL_673})
        self.assertEqual(build['baseline_inputs'], base['candidate_inputs'])
        self.assertEqual(build['changed_source_files'], sorted([
            'Info.plist', 'src/Navi48Bringup.cpp', 'src/Navi48MetalNub.cpp', 'src/amd/native_s1c.h', 'src/amd/smu_uclkpin_pure.h',
            'src/dcn/navi48_dcn.cpp', 'src/dcn/navi48_ufmon_pure.h']))
        self.assertEqual(m.sha(PATCH), PATCH_SHA)
        with tempfile.TemporaryDirectory(prefix='refresh60f-patch-') as tmp:
            work = Path(tmp)
            for name in TREE_NAMES:
                shutil.copytree(BASE673 / 'candidate-source' / name, work / name)
            for name in ('Makefile', 'Info.plist'):
                shutil.copyfile(BASE673 / 'candidate-source' / name, work / name)
            subprocess.run(['patch', '-p1', '-s', '--forward', '--batch', '--no-backup-if-mismatch', '-d', str(work), '-i', str(PATCH)], check=True)
            replace_once(work / 'src/amd/native_s1c.h', 'kN1cKextBuild = 673;', 'kN1cKextBuild = 674;', 1)
            replace_once(work / 'src/Navi48MetalNub.cpp', 'sizeof(N48MetalOps), 673u', 'sizeof(N48MetalOps), 674u', 2)
            derived = tree_inputs(work)
        self.assertEqual(derived, build['candidate_inputs'])
        self.assertEqual(tree_inputs(CAND / 'candidate-source'), build['candidate_inputs'])

    def test_the_candidate_markers_and_the_test_logs(self):
        source = CAND / 'candidate-source'
        plist = (source / 'Info.plist').read_text()
        self.assertEqual(plist.count('<string>0.0.674</string>'), 2)
        self.assertNotIn('<string>0.0.673</string>', plist)
        self.assertIn('kN1cKextBuild = 674;', (source / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((source / 'src/Navi48MetalNub.cpp').read_text().count('sizeof(N48MetalOps), 674u'), 2)
        for name in TEST_LOGS:
            self.assertIn('PASS', (CAND / (name + '.log')).read_text(), name)
        self.assertIn('0.0.674 verb dispatch', (CAND / 'test-kernel-refresh60-wiring.py.log').read_text())
        self.assertIn('refresh60_test: 176 checks, 0 failures', (CAND / 'test-kernel-refresh60.py.log').read_text())
        self.assertIn('native_gtt_test: 71 checks, 0 failures', (CAND / 'test-kernel-bo-release.py.log').read_text())

    def test_the_binary_carries_the_fallback_and_the_earlier_fixes(self):
        binary = BINARY.read_bytes()
        for text in (b'Navi48,DisplayArb', b'Navi48,UclkPin', b'Navi48,DisplayUnderflow', b'GTT BO could not be given wired pages', b'Navi48,RefreshHz',
                     b'navi48-det', b'navi48-wm', b'navi48-sr', b'navi48-dispmon', b'navi48-uclkpin', b'navi48-ufmon',
                     b'10 min without underflow', b'OPTC alone %llu', b'fallback stage 1 (stutter off, no pin)'):
            self.assertIn(text, binary, text)
        src = CAND / 'candidate-source/src'
        self.assertIn('char t[640];   // 0.0.674', (src / 'Navi48Bringup.cpp').read_text())
        self.assertIn('n48dcn::uclkPinDescribe(t, sizeof(t));', (src / 'Navi48Bringup.cpp').read_text())
        self.assertIn('smu_uclk_display_pin(const DeviceContext &dev, bool pin, uint32_t why)', (src / 'amd/smu_v14_0.cpp').read_text())
        dcn = (src / 'dcn/navi48_dcn.cpp').read_text()
        self.assertIn('if (on) ufmon_poll(monGen);', dcn)
        self.assertNotIn('ufmon_poll(myGen);', dcn)   # 0.0.672's call from the scanout watchdog is gone
        self.assertIn('gArbRes = n48arb::apply(disparb_hw(), c);', dcn)
        self.assertIn('if (act == n48uclk::fb::kStutterOff) {', dcn)   # 0.0.674 stage 1: its own branch
        self.assertIn('static bool arb_sr_revert() {', dcn)
        self.assertIn('constexpr uint32_t kDetTargetSegs', (src / 'dcn/navi48_disparb_pure.h').read_text())
        self.assertIn('kQuietReleaseMs = 600000u', (src / 'amd/smu_uclkpin_pure.h').read_text())
        self.assertIn('n48ufmon::after_clear(gUf, true, n48mt::uf::hubp_bad(h3) || n48mt::uf::optc_bad(o3));', dcn)
        self.assertNotIn('sysmem_alloc(', (src / 'amd/native_s1c.cpp').read_text())


class Guard674(unittest.TestCase):
    def setUp(self):
        # the 0.0.674 input is the live guard at stage time (payload v10's evidence copy, which is the installed 0.0.673 guard = payload v9's)
        self.live = (V10 / 'evidence/original-guard.sh').read_text()
        self.v9 = (V9 / 'system' / GUARD).read_text()
        self.v10 = (V10 / 'system' / GUARD).read_text()

    def test_the_input_guard_is_the_installed_guard(self):
        self.assertEqual(m.sha(V10 / 'evidence/original-guard.sh'), GUARD_673)
        self.assertEqual(self.live, self.v9)   # payload v9 installed exactly this guard

    def test_the_guard_on_disk_is_the_derived_guard_pinned(self):
        self.assertEqual(sha_text(self.v10), GUARD_674)
        self.assertEqual(m.sha(V10 / 'system' / GUARD), GUARD_674)
        self.assertEqual(self.v10, m.make_guard(R674, self.live, PROBE, '0.0.674'))
        self.assertEqual(self.v10, m.bump_guard_674(self.live, PROBE))

    def test_exactly_five_lines_change_from_673_to_674(self):
        before, after = self.live.splitlines(), self.v10.splitlines()
        self.assertEqual(len(before), len(after))
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 5, changed)
        for a, b in changed:
            self.assertEqual(a.replace('673', '674'), b)

    def test_no_reference_to_kernel_673_remains(self):
        for old in ('0.0.673', 'kernel 673', '0\\.0\\.673'):
            self.assertNotIn(old, self.v10)

    def test_the_capability_block_and_the_hook_are_present_exactly_once(self):
        block = m.capability_block(m.KERNEL_BRANCH_674, PROBE)
        self.assertEqual(self.v10.count(block), 1)
        self.assertEqual(self.v10.count('REFRESH60_INSTALLED'), 1)
        self.assertEqual(self.v10.count('refresh_begin() {'), 1)
        self.assertEqual(self.v10.count("local re_bringup='com\\.navi48\\.bringup[[:space:]]+\\(0\\.0\\.674\\)'"), 1)

    def test_the_metal_expectations_are_the_bundle_38_pins(self):
        version, pins = m.live_metal_pins(self.v10)
        self.assertEqual(version, '38')
        self.assertEqual(pins, METAL_38)
        self.assertEqual(m.live_metal_pins(self.live), (version, pins))

    def test_bash_accepts_the_guard(self):
        r = subprocess.run(['/bin/bash', '-n', str(V10 / 'system' / GUARD)], capture_output=True, text=True)
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


class Gates674(unittest.TestCase):
    """The capability block and the refresh hook of the 0.0.674 guard, run in bash against fake commands."""

    def setUp(self):
        self.guard = (V10 / 'system' / GUARD).read_text()
        self.tmp = tempfile.TemporaryDirectory(prefix='refresh60f-gates-')
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

    def test_the_capability_block_accepts_0_0_674_and_stops_the_others(self):
        block = m.capability_block(m.KERNEL_BRANCH_674, self.probe_sha)
        script = CAPABILITY_HARNESS + 'loaded=$(kmutil showloaded --list-only)\n' + block
        line = lambda kernel: '  12 0 0x0 0x0 com.navi48.bringup (%s) 1 UUID' % kernel
        env = {'FAKE_SESSION': '63 / 9 / 1'}
        rc, _, out, calls = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.674')})
        self.assertEqual(rc, 0)
        self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', out)
        self.assertIn('accel sessstat 95', calls)
        rc, _, out, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.665')})
        self.assertEqual(rc, 0)
        self.assertIn('CAPABILITY_CHECKS=skipped for kernel 0.0.665', out)
        for kernel in ('0.0.673', '0.0.672', '0.0.671', '0.0.670', '0.0.669'):
            with self.subTest(kernel=kernel):
                rc, last, _, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line(kernel)})
                self.assertEqual((rc, last), (1, 'STOP expected kernel 674 or 665'))

    def test_the_hook_gate_requests_60_only_for_0_0_674_with_the_flag(self):
        fn = function_text(self.guard, 'refresh_begin')
        flag = self.work / 'app/refresh-60'
        kexts_674 = ('  92 0 0xffffff8004240000 0x7eb000 0x7eb000 com.navi48.bringup (0.0.674) 9716F9B9-A7FA-3BC4-9A9D-2CCC29AF069F <19 9 7 6 3 1>\n'
                     '  93 0 0xffffff8004340000 0x1000 0x1000 com.hackintosh.RDNA4FB (0.0.9) 1A2B3C4D-0000-0000-0000-000000000000 <5 3 2>\n')
        kexts_673 = kexts_674.replace('(0.0.674)', '(0.0.673)')
        kexts_672 = kexts_674.replace('(0.0.674)', '(0.0.672)')
        kexts_rdna8 = kexts_674.replace('(0.0.9)', '(0.0.8)')
        script = HOOK_HARNESS + 'refresh_active=0\nREFRESH_TIMEOUT=120\nREFRESH_FLAG="$APP/refresh-60"\n' + fn + '\nrefresh_begin\necho "rc=$?"\n'
        base = {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts_674}
        # no flag file: nothing runs
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual((rc, last, calls), (0, 'rc=0', ''))
        # flag present, 0.0.674 and RDNA4FB 0.0.9: the 60 Hz request with the 120 s timeout
        flag.write_text('')
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual(rc, 0)
        self.assertIn('REFRESH60_REQUESTED', out)
        self.assertEqual(calls.strip(), 'accel refresh 60 120')
        # 0.0.673, 0.0.672 or another RDNA4FB: refused by name, no request
        for name, kexts in (('0.0.673', kexts_673), ('0.0.672', kexts_672), ('RDNA4FB 0.0.8', kexts_rdna8)):
            with self.subTest(kexts=name):
                rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts})
                self.assertIn('REFRESH60_SKIPPED loaded kexts are not 0.0.674 and RDNA4FB 0.0.9', out)
                self.assertEqual(calls, '')
        # a flag that is not root-owned 0644: refused, no request
        rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '0', 'FAKE_KEXTS': kexts_674})
        self.assertIn('REFRESH60_SKIPPED flag is not a root-owned 0644 regular file', out)
        self.assertEqual(calls, '')


class Efi674(unittest.TestCase):
    def test_efi_is_the_673_installed_state_plus_the_listed_674_files_only(self):
        man = json.loads((V10 / 'manifest.json').read_text())
        v9 = json.loads((V9 / 'manifest.json').read_text())
        self.assertEqual(man['candidate_version'], '0.0.674')
        self.assertEqual(man['candidate_kernel_sha256'], KERNEL_674)
        self.assertEqual(man['baseline_config_sha256'], CONFIG_673)
        self.assertEqual(man['candidate_config_sha256'], CONFIG_674)
        self.assertEqual(man['baseline_efi_files'], v9['candidate_efi_files'])
        t9, t10 = m.tree(V9 / 'EFI'), m.tree(V10 / 'EFI')
        self.assertEqual({n for n in t9 if t10.get(n) != t9[n]}, {'OC/config.plist'})
        added = set(t10) - set(t9)
        self.assertEqual(added, {n for n in added if n.startswith(KEXT + '/')} | {'RECOVERY/pre-contexts-674-config.plist'})
        self.assertEqual(sorted(man['add_files']), sorted(added))
        self.assertEqual(m.sha(V10 / 'EFI' / KEXT / 'Contents/MacOS/Navi48Bringup'), KERNEL_674)

    def test_the_configuration_differs_only_in_the_bundle_path(self):
        before = plistlib.loads((V9 / 'EFI/OC/config.plist').read_bytes())
        after = plistlib.loads((V10 / 'EFI/OC/config.plist').read_bytes())
        self.assertEqual(m.diff_paths(before, after), ['/Kernel/Add/7/BundlePath'])
        self.assertEqual(after['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.674.kext')
        self.assertEqual(m.sha(V10 / 'EFI/OC/config.plist'), CONFIG_674)
        self.assertEqual(m.sha(V10 / 'EFI/RECOVERY/pre-contexts-674-config.plist'), CONFIG_673)
        self.assertEqual((V10 / 'EFI/RECOVERY/pre-contexts-674-config.plist').read_bytes(), (V9 / 'EFI/OC/config.plist').read_bytes())

    def test_the_kext_identity(self):
        info = plistlib.loads((V10 / 'EFI' / KEXT / 'Contents/Info.plist').read_bytes())
        self.assertEqual((info['CFBundleIdentifier'], info['CFBundleVersion']), ('com.navi48.bringup', '0.0.674'))

    def test_the_system_files_are_the_three_reviewed_files(self):
        system = {p.relative_to(V10 / 'system').as_posix() for p in (V10 / 'system').rglob('*') if p.is_file()}
        self.assertEqual(system, {GUARD, APP + '/context-isolation-probe', NAVI_REL})
        self.assertEqual(m.sha(V10 / 'system' / APP / 'context-isolation-probe'), PROBE)
        self.assertEqual(m.sha(V10 / 'system' / NAVI_REL), NAVI48TEST_SHA)
        self.assertEqual(m.sha(V10 / 'system' / GUARD), GUARD_674)
        for name in system:
            self.assertEqual((V10 / 'system' / name).stat().st_mode & 0o777, 0o755, name)
        self.assertEqual(m.sha(V10 / 'evidence/probe-self-test.log'), PROBE_SELF_TEST_SHA)
        self.assertEqual(m.sha(V10 / 'evidence/original-guard.sh'), GUARD_673)
        self.assertEqual(m.sha(V10 / 'evidence/build-manifest.json'), m.sha(CAND / 'manifest.json'))

    def test_the_payload_verifier_accepts_both_the_installed_and_the_staged_payloads_without_a_live_mount(self):
        self.assertEqual(m.verify(V9, live=False)['candidate_version'], '0.0.673')
        self.assertEqual(m.verify(V10, live=False)['candidate_version'], '0.0.674')

    def test_the_payload_holds_no_path_outside_the_release_layout(self):
        self.assertEqual({p.name for p in V10.iterdir()}, {'EFI', 'system', 'evidence', 'manifest.json'})
        self.assertEqual({p.name for p in (V10 / 'EFI').iterdir()}, {'OC', 'RECOVERY'})
        self.assertEqual({p.relative_to(V10 / 'evidence').as_posix() for p in (V10 / 'evidence').rglob('*') if p.is_file()},
                         {'build-manifest.json', 'original-guard.sh', 'probe-self-test.log'})


class Stage674(unittest.TestCase):
    def test_the_stage_script_names_the_674_paths_and_parses(self):
        script = HERE / 'stage-674-payload.sh'
        text = script.read_text()
        self.assertIn('macos-20261112/kernel-674/kernel-payload-v10', text)
        self.assertIn('macos-20261112/kernel-674/kernel-contexts-v10', text)
        self.assertIn('macos-20261112/kernel-673/kernel-payload-v9', text)
        self.assertIn('--baseline-state candidate', text)
        self.assertTrue(os.access(script, os.X_OK))
        r = subprocess.run(['/bin/bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
