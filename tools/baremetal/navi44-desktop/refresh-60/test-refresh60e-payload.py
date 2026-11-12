#!/usr/bin/env python3
"""Check the 0.0.673 (display arbitration) kernel candidate and payload v9 against their reviewed inputs.

Release record: RELEASES['0.0.673'] (production-kernel-payload.py) holds the reviewed values: the candidate binary, the 0.0.671 EFI it is
derived from (payload v7's candidate state, the live EFI: payload v8 / 0.0.672 was never installed), the navi48test it carries, the reused probe,
the base and the carried files.
Candidate: kernel-contexts-v9 is the reviewed 0.0.672 candidate TREE (kernel-contexts-v8) with kernel-0.0.673-over-0.0.672.diff applied (its sha256
is pinned in build-production-contexts.py) and the 0.0.673 markers (kN1cKextBuild, the Metal ops build number). The test applies the patch again to a
copy of the 0.0.672 tree and compares the result with the candidate's recorded inputs.
Guard: the 0.0.673 guard is derived from the LIVE guard at stage time (payload v9's evidence copy: the 0.0.671 guard with the live bundle-38 Metal
expectations, the same file payload v8 was derived from) with exactly five lines changed, each 671 -> 673. It equals payload v8's guard with 672 -> 673.
EFI: payload v9's EFI is payload v7's candidate EFI with the 0.0.673 kext and its recovery copy added and the boot configuration's BundlePath
moved to 0.0.673; nothing else changes.

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
BUILDS = ROOT / 'research/builds/macos-20261112/kernel-673'
V8 = ROOT / 'research/builds/macos-20261112/kernel-672/kernel-payload-v8'
V7 = ROOT / 'research/builds/macos-20261105/kernel-671/kernel-payload-v7'
V9 = BUILDS / 'kernel-payload-v9'
CAND = BUILDS / 'kernel-contexts-v9'
BASE672 = ROOT / 'research/builds/macos-20261112/kernel-672/kernel-contexts-v8'
PATCH = BUILDS / 'PATCHES/kernel-0.0.673-over-0.0.672.diff'
BINARY = CAND / 'candidate-source/build/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup'
KEXT = 'OC/Kexts/Navi48Bringup-contexts-0.0.673.kext'
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'
NAVI_REL = APP + '/navi48test'
TREE_NAMES = ('src', 'firmware', 'shaders', 'tools')
TEST_LOGS = ('test-kernel-vmid-leases.py', 'test-kernel-context-close.py', 'test-kernel-bo-release.py', 'test-kernel-wait-identity.py',
             'test-kernel-query-info.py', 'test-kernel-app-admission.py', 'test-kernel-refresh60.py', 'test-kernel-refresh60-wiring.py')

# The reviewed values, written out here so that a change to the script alone cannot move them.
KERNEL_673 = 'f53efdb50e4884c2a51c0d2cc2b9ab8d820527ea16851de4201698083dfda8f8'
KERNEL_672 = '69f5965016d8d6700a4f4b42f23b5f4e4621c110358948adf3ee5e71ca50e00d'
KERNEL_671 = '984989280e30be5dc0d26d9760b698393be0fae99a43e2604b380c7cfdddec22'
KERNEL_669 = 'cb6fd1067edf3ebd1f12ea20a91726698bdf2833591a86d50489d31626057def'
CONFIG_669 = '64fe3c2689d313dd8d076f3d7cf16edcc48eb30d94a63f42d8bf67eee019dc5b'   # payload v5's candidate configuration (v7's baseline copy)
CONFIG_671 = 'fa8c993c839a5a37794a54f178fbcee3e63a06901ddffe9efa9f65eb97429d57'   # payload v7's candidate configuration (v9's baseline)
CONFIG_673 = 'd3a39e1a8d281e5685187a156fd03cd2803dd9393c8dac5befc40219b276272c'   # payload v9's candidate configuration
CONFIG_672 = 'cff71a95fecf1ef5fc6ecf9c243c937aea93832610cd4394938f1a669a71a11e'   # payload v8's candidate configuration
GUARD_672 = '1667d96431cef2bba0c35d2b7f977b98755b0ff4d297c568e6c4cd86612d1d9e'   # payload v8's guard (derived from the same live guard)
GUARD_673 = 'b6a9f2fc19b862753777259996a2be4ae2dcec2695b3a01dab35dc07a618cd79'   # payload v9's guard (derived from the live guard below)
LIVE_GUARD = 'e9876cbf6288ee24a5829f36888f9288e6f820600dcbcb4b033e48d1c44b7f86'   # the live guard at stage time (payload v9's evidence copy, = payload v8's)
GUARD_671 = '08146029c5a1be34cb209dfb5a8ee40d913c7ccf37d599592d5d6bdbd0a48a4e'   # payload v7's guard (the 0.0.671 guard, bundle-34 pins)
PATCH_SHA = '8a64a2a2e60418190b5cdac7cce6eaa316497b524a855a871a6c23346a716545'
PROBE = '5afe2b52b0c0adc7a4bf1ea8f8e07437929ed9cfe066fa1f56a39240ceb000c5'
PROBE_SELF_TEST_SHA = '934011ce4b4a3f4ebaabe6b69247e06f13f39387976c790ccfc65fb95c2d75ed'
NAVI48TEST_SHA = '83e7f3e3c9609ce636e138acf5a5186dbf6ef5c8951bcc6342eb21a1d058b94c'
METAL_34 = {'Contents/MacOS/Navi48Metal': 'cd4f3ce581fc5e50ff02f07892db0b65b3d4ac5a82572defae1b0c754194d7fe',
            'Contents/Resources/libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
            'Contents/Resources/libn48xlate.dylib': '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a'}
METAL_38 = {'Contents/MacOS/Navi48Metal': 'c919abd8e603fb6c424e7a318929cd11158348a11b35529d74a915bffa1ab230',
            'Contents/Resources/libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
            'Contents/Resources/libn48xlate.dylib': 'c79adc839e8ec9dda7d042eb8469630faa5dfff304105d14c41f88fb8e522f62'}
# the four lines in which the live guard (bundle 38) differs from payload v7's guard (bundle 34)
BUNDLE_38_LINES = (('PROFILE=stage34-zinit-v1', 'PROFILE=stage38-swz-v1'),
                   ('[[ "$bundle_version" == 34 ]] || { echo "STOP expected Stage34 Metal bundle version 34, got: $bundle_version"; exit 1; }',
                    '[[ "$bundle_version" == 38 ]] || { echo "STOP expected Stage38 Metal bundle version 38, got: $bundle_version"; exit 1; }'),
                   (METAL_34['Contents/MacOS/Navi48Metal'], METAL_38['Contents/MacOS/Navi48Metal']),
                   (METAL_34['Contents/Resources/libn48xlate.dylib'], METAL_38['Contents/Resources/libn48xlate.dylib']))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load('payload', DESKTOP / 'production-kernel-payload.py')
R673 = m.RELEASES['0.0.673']


def sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def code_only(text):
    """The source without its // comments."""
    return '\n'.join(line.split('//', 1)[0] for line in text.splitlines())


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


class Release673(unittest.TestCase):
    def test_the_release_record_is_the_reviewed_one(self):
        self.assertEqual(R673['new'], 'Navi48Bringup-contexts-0.0.673.kext')
        self.assertEqual(R673['recovery'], 'RECOVERY/pre-contexts-673-config.plist')
        self.assertEqual(R673['from'], 'Navi48Bringup-contexts-0.0.671.kext')   # payload v8 (0.0.672) was never installed
        self.assertEqual(R673['from_kernel_sha'], KERNEL_671)
        self.assertEqual(R673['from_config_sha'], CONFIG_671)
        self.assertEqual(R673['kernel_sha'], KERNEL_673)
        self.assertEqual(R673['tests'], 8)
        self.assertEqual(R673['base'], 'reviewed-candidate-672')
        self.assertEqual(R673['base_kernel_sha'], KERNEL_672)   # the 0.0.672 candidate tree the 0.0.673 patch is applied to
        self.assertEqual(R673['probe_reuse'], PROBE)
        self.assertEqual(R673['system_files'], {m.APP + '/navi48test': NAVI48TEST_SHA})
        self.assertEqual(R673['binary_checks'], 'not-run')
        self.assertEqual(R673['self_test_log_sha'], PROBE_SELF_TEST_SHA)
        self.assertEqual(R673['guard'], 'live-673')
        self.assertIsNone(R673['metal'])
        self.assertIsNone(R673['metal_version'])
        self.assertEqual(R673['edits'], [{'path': 'Kernel/Add/7/BundlePath', 'old': 'Navi48Bringup-contexts-0.0.671.kext',
                                          'new': 'Navi48Bringup-contexts-0.0.673.kext'}])
        self.assertEqual(R673['extras'], {'RECOVERY/pre-contexts-673-config.plist': 'baseline'})
        self.assertEqual(R673['carried'], m.RELEASES['0.0.672']['carried'])   # the same baseline EFI as payload v8
        self.assertEqual(R673['carried']['RECOVERY/pre-contexts-671-config.plist'], CONFIG_669)
        self.assertNotIn('RECOVERY/pre-contexts-672-config.plist', R673['carried'])
        for text in ('GTT BO could not be given wired pages', 'Navi48,UclkPin', 'Navi48,DisplayUnderflow', 'Navi48,DisplayArb',
                     'disparb: display monitor started', 'ufmon: UCLK fallback'):
            self.assertIn(text, R673['strings'])

    def test_the_candidate_build_is_the_recorded_0_0_673_kernel(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        self.assertEqual(build['status'], 'built-cpu-tested-not-installed-hardware-unverified')
        self.assertEqual(build['candidate_version'], '0.0.673')
        self.assertEqual(build['candidate_binary_sha256'], KERNEL_673)
        self.assertEqual(m.sha(BINARY), KERNEL_673)
        self.assertEqual(len(build['cpu_tests']), R673['tests'])
        self.assertEqual(build['cpu_tests'], list(TEST_LOGS))
        self.assertTrue(set(R673['strings']) <= set(build['required_strings']))
        self.assertEqual(build['active_baseline'], {'bundle_path': 'Navi48Bringup-contexts-0.0.671.kext', 'kernel_sha256': KERNEL_671,
                                                    'config_sha256': CONFIG_671, 'version': '0.0.671'})
        self.assertTrue(m.reviewed_base(build, R673))
        self.assertFalse(m.reviewed_base(build, m.RELEASES['0.0.672']))   # not the 0.0.671 base
        self.assertEqual(build['overlay']['source'], 'patch')
        self.assertEqual(build['overlay']['patch_sha256'], PATCH_SHA)
        self.assertEqual(build['disparb_overlay']['patch_sha256'], PATCH_SHA)

    def test_the_candidate_is_the_0_0_672_tree_with_the_patch_and_the_markers_only(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        base = json.loads((BASE672 / 'manifest.json').read_text())
        self.assertEqual(base['candidate_version'], '0.0.672')
        self.assertEqual(base['candidate_binary_sha256'], KERNEL_672)
        self.assertEqual(build['base_verified'], {'manifest': str((BASE672 / 'manifest.json').relative_to(ROOT)),
                                                  'candidate_inputs_checked': len(base['candidate_inputs']), 'binary_sha256': KERNEL_672})
        self.assertEqual(build['baseline_inputs'], base['candidate_inputs'])
        self.assertEqual(build['changed_source_files'], sorted([
            'Info.plist', 'src/Navi48Bringup.cpp', 'src/Navi48MetalNub.cpp', 'src/amd/amdgpu_smu.h', 'src/amd/native_s1c.h',
            'src/amd/smu_uclkpin_pure.h', 'src/amd/smu_v14_0.cpp', 'src/dcn/navi48_dcn.cpp', 'src/dcn/navi48_dcn.hpp',
            'src/dcn/navi48_disparb_pure.h', 'src/dcn/navi48_ufmon_pure.h']))
        self.assertEqual(m.sha(PATCH), PATCH_SHA)
        with tempfile.TemporaryDirectory(prefix='refresh60e-patch-') as tmp:
            work = Path(tmp)
            for name in TREE_NAMES:
                shutil.copytree(BASE672 / 'candidate-source' / name, work / name)
            for name in ('Makefile', 'Info.plist'):
                shutil.copyfile(BASE672 / 'candidate-source' / name, work / name)
            subprocess.run(['patch', '-p1', '-s', '--forward', '--batch', '--no-backup-if-mismatch', '-d', str(work), '-i', str(PATCH)], check=True)
            replace_once(work / 'src/amd/native_s1c.h', 'kN1cKextBuild = 672;', 'kN1cKextBuild = 673;', 1)
            replace_once(work / 'src/Navi48MetalNub.cpp', 'sizeof(N48MetalOps), 672u', 'sizeof(N48MetalOps), 673u', 2)
            derived = tree_inputs(work)
        self.assertEqual(derived, build['candidate_inputs'])
        self.assertEqual(tree_inputs(CAND / 'candidate-source'), build['candidate_inputs'])

    def test_the_candidate_markers_and_the_test_logs(self):
        source = CAND / 'candidate-source'
        plist = (source / 'Info.plist').read_text()
        self.assertEqual(plist.count('<string>0.0.673</string>'), 2)
        self.assertNotIn('<string>0.0.672</string>', plist)
        self.assertIn('kN1cKextBuild = 673;', (source / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((source / 'src/Navi48MetalNub.cpp').read_text().count('sizeof(N48MetalOps), 673u'), 2)
        for name in TEST_LOGS:
            self.assertIn('PASS', (CAND / (name + '.log')).read_text(), name)
        self.assertIn('0.0.673 verb dispatch', (CAND / 'test-kernel-refresh60-wiring.py.log').read_text())
        self.assertIn('refresh60_test: 176 checks, 0 failures', (CAND / 'test-kernel-refresh60.py.log').read_text())
        self.assertIn('native_gtt_test: 71 checks, 0 failures', (CAND / 'test-kernel-bo-release.py.log').read_text())

    def test_the_binary_carries_the_display_arbitration_and_the_earlier_fixes(self):
        binary = BINARY.read_bytes()
        for text in (b'Navi48,DisplayArb', b'Navi48,UclkPin', b'Navi48,DisplayUnderflow', b'GTT BO could not be given wired pages', b'Navi48,RefreshHz',
                     b'navi48-det', b'navi48-wm', b'navi48-sr', b'navi48-dispmon', b'navi48-uclkpin', b'navi48-ufmon'):
            self.assertIn(text, binary, text)
        src = CAND / 'candidate-source/src'
        self.assertIn('n48dcn::uclkPinDescribe(t, sizeof(t));', (src / 'Navi48Bringup.cpp').read_text())
        self.assertIn('smu_uclk_display_pin(const DeviceContext &dev, bool pin, uint32_t why)', (src / 'amd/smu_v14_0.cpp').read_text())
        dcn = (src / 'dcn/navi48_dcn.cpp').read_text()
        self.assertIn('if (on) ufmon_poll(monGen);', dcn)
        self.assertNotIn('ufmon_poll(myGen);', dcn)   # 0.0.672's call from the scanout watchdog is gone
        self.assertIn('gArbRes = n48arb::apply(disparb_hw(), c);', dcn)
        self.assertIn('constexpr uint32_t kDetTargetSegs', (src / 'dcn/navi48_disparb_pure.h').read_text())
        self.assertNotIn('sysmem_alloc(', (src / 'amd/native_s1c.cpp').read_text())


class Guard673(unittest.TestCase):
    def setUp(self):
        # the 0.0.673 input is the live guard at stage time (payload v9's evidence copy); payload v7's guard is the 0.0.671 guard it was derived from
        self.live = (V9 / 'evidence/original-guard.sh').read_text()
        self.v7 = (V7 / 'system' / GUARD).read_text()
        self.v9 = (V9 / 'system' / GUARD).read_text()

    def test_the_input_guard_is_the_live_guard_at_stage_time(self):
        self.assertEqual(m.sha(V9 / 'evidence/original-guard.sh'), LIVE_GUARD)
        self.assertEqual(m.sha(V7 / 'system' / GUARD), GUARD_671)
        expected = self.v7
        for old, new in BUNDLE_38_LINES:
            expected = expected.replace(old, new, 1)
        self.assertEqual(expected, self.live)   # the live guard is payload v7's guard with the four bundle-38 lines

    def test_the_guard_on_disk_is_the_derived_guard_pinned(self):
        self.assertEqual(sha_text(self.v9), GUARD_673)
        self.assertEqual(m.sha(V9 / 'system' / GUARD), GUARD_673)
        self.assertEqual(self.v9, m.make_guard(R673, self.live, PROBE, '0.0.673'))
        self.assertEqual(self.v9, m.bump_guard_673(self.live, PROBE))
        # payload v8's guard (0.0.672, never installed) was derived from the same live guard: with 672 -> 673 it is this guard
        v8 = (V8 / 'system' / GUARD).read_text()
        self.assertEqual(m.sha(V8 / 'system' / GUARD), GUARD_672)
        self.assertEqual(v8.replace('0.0.672', '0.0.673').replace('0\\.0\\.672', '0\\.0\\.673').replace('kernel 672', 'kernel 673'), self.v9)

    def test_exactly_five_lines_change_from_671_to_673_and_four_from_the_bundle_38_pins(self):
        before, after = self.live.splitlines(), self.v9.splitlines()
        self.assertEqual(len(before), len(after))
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 5, changed)
        for a, b in changed:
            self.assertEqual(a.replace('671', '673'), b)
        # against payload v7's guard: the five kernel lines and the four bundle-38 lines (nothing else)
        v7_lines, v9_lines = self.v7.splitlines(), self.v9.splitlines()
        self.assertEqual(len(v7_lines), len(v9_lines))
        differing = [(a, b) for a, b in zip(v7_lines, v9_lines) if a != b]
        self.assertEqual(len(differing), 9, differing)
        kernel_lines = [(a, b) for a, b in differing if a.replace('671', '673') == b]
        self.assertEqual(len(kernel_lines), 5)
        other_lines = [(a, b) for a, b in differing if a.replace('671', '673') != b]
        self.assertEqual(len(other_lines), 4, other_lines)
        for a, b in other_lines:
            self.assertTrue(any(old in a and new in b for old, new in BUNDLE_38_LINES), (a, b))

    def test_no_reference_to_kernel_671_or_672_remains(self):
        for old in ('0.0.671', 'kernel 671', '0\\.0\\.671', '0.0.672', 'kernel 672', '0\\.0\\.672', '0.0.669', '0.0.670'):
            self.assertNotIn(old, self.v9)

    def test_the_capability_block_and_the_hook_are_present_exactly_once(self):
        block = m.capability_block(m.KERNEL_BRANCH_673, PROBE)
        self.assertEqual(self.v9.count(block), 1)
        self.assertEqual(self.v9.count('REFRESH60_INSTALLED'), 1)
        self.assertEqual(self.v9.count('refresh_begin() {'), 1)
        self.assertEqual(self.v9.count("local re_bringup='com\\.navi48\\.bringup[[:space:]]+\\(0\\.0\\.673\\)'"), 1)

    def test_the_metal_expectations_are_the_bundle_38_pins(self):
        version, pins = m.live_metal_pins(self.v9)
        self.assertEqual(version, '38')
        self.assertEqual(pins, METAL_38)
        self.assertEqual(m.live_metal_pins(self.live), (version, pins))

    def test_bash_accepts_the_guard(self):
        r = subprocess.run(['/bin/bash', '-n', str(V9 / 'system' / GUARD)], capture_output=True, text=True)
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


class Gates673(unittest.TestCase):
    """The capability block and the refresh hook of the 0.0.673 guard, run in bash against fake commands."""

    def setUp(self):
        self.guard = (V9 / 'system' / GUARD).read_text()
        self.tmp = tempfile.TemporaryDirectory(prefix='refresh60e-gates-')
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

    def test_the_capability_block_accepts_0_0_673_and_stops_the_others(self):
        block = m.capability_block(m.KERNEL_BRANCH_673, self.probe_sha)
        script = CAPABILITY_HARNESS + 'loaded=$(kmutil showloaded --list-only)\n' + block
        line = lambda kernel: '  12 0 0x0 0x0 com.navi48.bringup (%s) 1 UUID' % kernel
        env = {'FAKE_SESSION': '63 / 9 / 1'}
        rc, _, out, calls = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.673')})
        self.assertEqual(rc, 0)
        self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', out)
        self.assertIn('accel sessstat 95', calls)
        rc, _, out, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.665')})
        self.assertEqual(rc, 0)
        self.assertIn('CAPABILITY_CHECKS=skipped for kernel 0.0.665', out)
        for kernel in ('0.0.672', '0.0.671', '0.0.670', '0.0.669', '0.0.668'):
            with self.subTest(kernel=kernel):
                rc, last, _, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line(kernel)})
                self.assertEqual((rc, last), (1, 'STOP expected kernel 673 or 665'))

    def test_the_hook_gate_requests_60_only_for_0_0_673_with_the_flag(self):
        fn = function_text(self.guard, 'refresh_begin')
        flag = self.work / 'app/refresh-60'
        kexts_673 = ('  92 0 0xffffff8004240000 0x7eb000 0x7eb000 com.navi48.bringup (0.0.673) 9716F9B9-A7FA-3BC4-9A9D-2CCC29AF069F <19 9 7 6 3 1>\n'
                     '  93 0 0xffffff8004340000 0x1000 0x1000 com.hackintosh.RDNA4FB (0.0.9) 1A2B3C4D-0000-0000-0000-000000000000 <5 3 2>\n')
        kexts_672 = kexts_673.replace('(0.0.673)', '(0.0.672)')
        kexts_671 = kexts_673.replace('(0.0.673)', '(0.0.671)')
        kexts_rdna8 = kexts_673.replace('(0.0.9)', '(0.0.8)')
        script = HOOK_HARNESS + 'refresh_active=0\nREFRESH_TIMEOUT=120\nREFRESH_FLAG="$APP/refresh-60"\n' + fn + '\nrefresh_begin\necho "rc=$?"\n'
        base = {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts_673}
        # no flag file: nothing runs
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual((rc, last, calls), (0, 'rc=0', ''))
        # flag present, 0.0.673 and RDNA4FB 0.0.9: the 60 Hz request with the 120 s timeout
        flag.write_text('')
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual(rc, 0)
        self.assertIn('REFRESH60_REQUESTED', out)
        self.assertEqual(calls.strip(), 'accel refresh 60 120')
        # 0.0.672, 0.0.671 or another RDNA4FB: refused by name, no request
        for name, kexts in (('0.0.672', kexts_672), ('0.0.671', kexts_671), ('RDNA4FB 0.0.8', kexts_rdna8)):
            with self.subTest(kexts=name):
                rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts})
                self.assertIn('REFRESH60_SKIPPED loaded kexts are not 0.0.673 and RDNA4FB 0.0.9', out)
                self.assertEqual(calls, '')
        # a flag that is not root-owned 0644: refused, no request
        rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '0', 'FAKE_KEXTS': kexts_673})
        self.assertIn('REFRESH60_SKIPPED flag is not a root-owned 0644 regular file', out)
        self.assertEqual(calls, '')


class Efi673(unittest.TestCase):
    def test_efi_is_the_671_candidate_plus_the_listed_673_files_only(self):
        man = json.loads((V9 / 'manifest.json').read_text())
        v7 = json.loads((V7 / 'manifest.json').read_text())
        self.assertEqual(man['candidate_version'], '0.0.673')
        self.assertEqual(man['candidate_kernel_sha256'], KERNEL_673)
        self.assertEqual(man['baseline_config_sha256'], CONFIG_671)
        self.assertEqual(man['candidate_config_sha256'], CONFIG_673)
        self.assertEqual(man['baseline_efi_files'], v7['candidate_efi_files'])
        t7, t9 = m.tree(V7 / 'EFI'), m.tree(V9 / 'EFI')
        self.assertEqual({n for n in t7 if t9.get(n) != t7[n]}, {'OC/config.plist'})
        added = set(t9) - set(t7)
        self.assertEqual(added, {n for n in added if n.startswith(KEXT + '/')} | {'RECOVERY/pre-contexts-673-config.plist'})
        self.assertEqual(sorted(man['add_files']), sorted(added))
        self.assertEqual(m.sha(V9 / 'EFI' / KEXT / 'Contents/MacOS/Navi48Bringup'), KERNEL_673)

    def test_the_configuration_differs_only_in_the_bundle_path(self):
        before = plistlib.loads((V7 / 'EFI/OC/config.plist').read_bytes())
        after = plistlib.loads((V9 / 'EFI/OC/config.plist').read_bytes())
        self.assertEqual(m.diff_paths(before, after), ['/Kernel/Add/7/BundlePath'])
        self.assertEqual(after['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.673.kext')
        self.assertEqual(m.sha(V9 / 'EFI/OC/config.plist'), CONFIG_673)
        self.assertEqual(m.sha(V9 / 'EFI/RECOVERY/pre-contexts-673-config.plist'), CONFIG_671)
        self.assertEqual((V9 / 'EFI/RECOVERY/pre-contexts-673-config.plist').read_bytes(), (V7 / 'EFI/OC/config.plist').read_bytes())

    def test_the_kext_identity(self):
        info = plistlib.loads((V9 / 'EFI' / KEXT / 'Contents/Info.plist').read_bytes())
        self.assertEqual((info['CFBundleIdentifier'], info['CFBundleVersion']), ('com.navi48.bringup', '0.0.673'))

    def test_the_system_files_are_the_three_reviewed_files(self):
        system = {p.relative_to(V9 / 'system').as_posix() for p in (V9 / 'system').rglob('*') if p.is_file()}
        self.assertEqual(system, {GUARD, APP + '/context-isolation-probe', NAVI_REL})
        self.assertEqual(m.sha(V9 / 'system' / APP / 'context-isolation-probe'), PROBE)
        self.assertEqual(m.sha(V9 / 'system' / NAVI_REL), NAVI48TEST_SHA)
        self.assertEqual(m.sha(V9 / 'system' / GUARD), GUARD_673)
        for name in system:
            self.assertEqual((V9 / 'system' / name).stat().st_mode & 0o777, 0o755, name)
        self.assertEqual(m.sha(V9 / 'evidence/probe-self-test.log'), PROBE_SELF_TEST_SHA)
        self.assertEqual(m.sha(V9 / 'evidence/original-guard.sh'), LIVE_GUARD)
        self.assertEqual(m.sha(V9 / 'evidence/build-manifest.json'), m.sha(CAND / 'manifest.json'))

    def test_the_payload_verifier_accepts_it_without_a_live_mount(self):
        self.assertEqual(m.verify(V9, live=False)['candidate_version'], '0.0.673')

    def test_the_payload_holds_no_path_outside_the_release_layout(self):
        self.assertEqual({p.name for p in V9.iterdir()}, {'EFI', 'system', 'evidence', 'manifest.json'})
        self.assertEqual({p.name for p in (V9 / 'EFI').iterdir()}, {'OC', 'RECOVERY'})
        self.assertEqual({p.relative_to(V9 / 'evidence').as_posix() for p in (V9 / 'evidence').rglob('*') if p.is_file()},
                         {'build-manifest.json', 'original-guard.sh', 'probe-self-test.log'})


class Stage673(unittest.TestCase):
    def test_the_stage_script_names_the_673_paths_and_parses(self):
        script = HERE / 'stage-673-payload.sh'
        text = script.read_text()
        self.assertIn('macos-20261112/kernel-673/kernel-payload-v9', text)
        self.assertIn('macos-20261112/kernel-673/kernel-contexts-v9', text)
        self.assertIn('macos-20261105/kernel-671/kernel-payload-v7', text)
        self.assertIn('--baseline-state candidate', text)
        self.assertTrue(os.access(script, os.X_OK))
        r = subprocess.run(['/bin/bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
