#!/usr/bin/env python3
"""Check the 0.0.670 (refresh-60b) kernel candidate and payload v6 against their reviewed inputs.

Release record: RELEASES['0.0.670'] (production-kernel-payload.py) holds the reviewed values: the candidate binary, the 0.0.669 EFI it is
derived from, the navi48test it carries, the reused probe, the base and the carried files.
Candidate: kernel-contexts-v6 is the 0.0.668 base with the refresh overlay (its source is the repo's pure header) and the 0.0.670 markers.
Guard: the 0.0.670 guard is the 0.0.669 guard (payload v5's, the live one) with exactly five lines changed, each 669 -> 670 (the capability
block's kernel match and STOP text, and the refresh-60 hook's comment, regex and skip message). Bash runs the capability block and the
hook's gate with fake NT, kmutil, probe and flag files in a temporary directory. No research-tree binary is executed.
EFI: payload v6's EFI is payload v5's candidate EFI with the 0.0.670 kext and its recovery copy added and the boot configuration's
BundlePath moved to 0.0.670; nothing else changes.

Reads files only (plus the bash checks in a temporary directory). The live guard is not read here.
"""
import difflib
import hashlib
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True   # no __pycache__ inside the repository
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DESKTOP = HERE.parent
BUILDS = ROOT / 'research/builds/macos-20261101/refresh-60b'
V5 = ROOT / 'research/builds/macos-20261101/refresh-60/kernel-payload-v5'
V6 = BUILDS / 'kernel-payload-v6'
CAND = BUILDS / 'kernel-contexts-v6'
BINARY = CAND / 'candidate-source/build/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup'
KEXT = 'OC/Kexts/Navi48Bringup-contexts-0.0.670.kext'
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'

# The reviewed values, written out here so that a change to the script alone cannot move them.
KERNEL_670 = 'c212c7310fb5a506d128d72dd5798725ecc2d6aaf84d7cee27dc0f6b88959eb3'
KERNEL_669 = 'cb6fd1067edf3ebd1f12ea20a91726698bdf2833591a86d50489d31626057def'
KERNEL_668 = 'ab4c7fed6dd6c6ee52096da25d78f50bc515a51fdbfe8f591654143afe9ccb6d'
CONFIG_669 = '64fe3c2689d313dd8d076f3d7cf16edcc48eb30d94a63f42d8bf67eee019dc5b'   # payload v5's candidate configuration (v6's baseline)
CONFIG_670 = '442055d2566f9d4be8d906eefe8ba38370e92aab5946afa9a4ae34f0631d2d66'
GUARD_669 = '36ab536ab8368d54713fd1c82fe69023bb27c56659c26e3e82d4e60b56d05cf0'   # the live 0.0.669 guard (payload v5's guard)
GUARD_670 = 'a119d817ca7c0d7acab0574d4397655d88fc9940a76bc7bc96ee9b666a06a29c'
PROBE = '5afe2b52b0c0adc7a4bf1ea8f8e07437929ed9cfe066fa1f56a39240ceb000c5'
PROBE_SELF_TEST_SHA = '934011ce4b4a3f4ebaabe6b69247e06f13f39387976c790ccfc65fb95c2d75ed'
NAVI48TEST_SHA = '83e7f3e3c9609ce636e138acf5a5186dbf6ef5c8951bcc6342eb21a1d058b94c'
NAVI_REL = APP + '/navi48test'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load('payload', DESKTOP / 'production-kernel-payload.py')
hook = load('apply_refresh_guard', HERE / 'apply_refresh_guard.py')
R670 = m.RELEASES['0.0.670']


def sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Release670(unittest.TestCase):
    def test_the_release_record_is_the_reviewed_one(self):
        self.assertEqual(R670['new'], 'Navi48Bringup-contexts-0.0.670.kext')
        self.assertEqual(R670['recovery'], 'RECOVERY/pre-contexts-670-config.plist')
        self.assertEqual(R670['from'], 'Navi48Bringup-contexts-0.0.669.kext')
        self.assertEqual(R670['from_kernel_sha'], KERNEL_669)
        self.assertEqual(R670['from_config_sha'], CONFIG_669)
        self.assertEqual(R670['kernel_sha'], KERNEL_670)
        self.assertEqual(R670['tests'], 8)
        self.assertEqual(R670['base'], 'reviewed-candidate')
        self.assertEqual(R670['base_kernel_sha'], KERNEL_668)   # the same 0.0.668 candidate 0.0.669 was built on
        self.assertEqual(R670['probe_reuse'], PROBE)
        self.assertEqual(R670['system_files'], {m.APP + '/navi48test': NAVI48TEST_SHA})
        self.assertEqual(R670['binary_checks'], 'not-run')
        self.assertEqual(R670['self_test_log_sha'], PROBE_SELF_TEST_SHA)
        self.assertEqual(R670['guard'], 'live-670')
        self.assertIsNone(R670['metal'])
        self.assertIsNone(R670['metal_version'])
        self.assertEqual(R670['edits'], [{'path': 'Kernel/Add/7/BundlePath', 'old': 'Navi48Bringup-contexts-0.0.669.kext',
                                          'new': 'Navi48Bringup-contexts-0.0.670.kext'}])
        self.assertEqual(R670['extras'], {'RECOVERY/pre-contexts-670-config.plist': 'baseline'})
        self.assertEqual(R670['carried'][ 'RECOVERY/pre-contexts-669-config.plist'], m.CONFIG_668_SHA)
        self.assertEqual(R670['strings'], m.RELEASES['0.0.669']['strings'])

    def test_the_candidate_build_is_the_recorded_0_0_670_kernel(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        self.assertEqual(build['status'], 'built-cpu-tested-not-installed-hardware-unverified')
        self.assertEqual(build['candidate_version'], '0.0.670')
        self.assertEqual(build['candidate_binary_sha256'], KERNEL_670)
        self.assertEqual(m.sha(BINARY), KERNEL_670)
        self.assertEqual(len(build['cpu_tests']), R670['tests'])
        self.assertTrue(set(R670['strings']) <= set(build['required_strings']))
        self.assertEqual(build['active_baseline'], {'bundle_path': 'Navi48Bringup-contexts-0.0.669.kext', 'kernel_sha256': KERNEL_669,
                                                    'config_sha256': CONFIG_669, 'version': '0.0.669'})
        self.assertTrue(m.reviewed_base(build, R670))

    def test_the_candidate_is_the_0_0_668_base_with_the_refresh_overlay_only(self):
        build = json.loads((CAND / 'manifest.json').read_text())
        base = json.loads((ROOT / 'research/builds/macos-20261031/production/kernel-contexts-v4/manifest.json').read_text())
        self.assertEqual(build['base_verified']['binary_sha256'], KERNEL_668)
        self.assertEqual(build['base_verified']['candidate_inputs_checked'], len(base['candidate_inputs']))
        self.assertEqual(build['baseline_inputs'], base['candidate_inputs'])
        self.assertEqual(build['changed_source_files'], ['Info.plist', 'src/Navi48Bringup.cpp', 'src/Navi48Bringup.hpp', 'src/Navi48MetalNub.cpp',
                                                         'src/Navi48UserClient.cpp', 'src/amd/native_s1c.h', 'src/dcn/navi48_dcn.cpp',
                                                         'src/dcn/navi48_dcn.hpp', 'src/dcn/navi48_refresh_pure.h'])
        self.assertEqual(build['refresh_overlay']['files']['src/dcn/navi48_refresh_pure.h'],
                         m.sha(ROOT / 'cobalt64/src/navi48-bringup/src/dcn/navi48_refresh_pure.h'))
        self.assertEqual(m.sha(CAND / 'candidate-source/src/dcn/navi48_refresh_pure.h'),
                         m.sha(ROOT / 'cobalt64/src/navi48-bringup/src/dcn/navi48_refresh_pure.h'))

    def test_the_candidate_markers_and_the_test_logs(self):
        source = CAND / 'candidate-source'
        plist = (source / 'Info.plist').read_text()
        self.assertEqual(plist.count('<string>0.0.670</string>'), 2)
        self.assertNotIn('<string>0.0.669</string>', plist)
        self.assertIn('kN1cKextBuild = 670;', (source / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((source / 'src/Navi48MetalNub.cpp').read_text().count('sizeof(N48MetalOps), 670u'), 2)
        for name in ('test-kernel-refresh60.py.log', 'test-kernel-refresh60-wiring.py.log'):
            self.assertIn('PASS', (CAND / name).read_text(), name)
        self.assertIn('0.0.670 verb dispatch', (CAND / 'test-kernel-refresh60-wiring.py.log').read_text())
        self.assertIn('refresh60_test: 176 checks, 0 failures', (CAND / 'test-kernel-refresh60.py.log').read_text())


class Guard670(unittest.TestCase):
    def setUp(self):
        # the 0.0.670 input is the 0.0.669 guard (payload v5's system guard, which is the live guard once installed)
        self.v5 = (V5 / 'system' / GUARD).read_text()
        self.v6 = (V6 / 'system' / GUARD).read_text()

    def test_the_0_0_669_input_is_the_pinned_live_guard(self):
        self.assertEqual(sha_text(self.v5), GUARD_669)
        self.assertEqual(m.sha(V5 / 'evidence/original-guard.sh'), '8cc406859e1e3c5d4265dbb0cf1a39df1bb7c6bebe8b1ca5739cc4451055dcd1')

    def test_the_guard_on_disk_is_the_derived_guard_pinned(self):
        self.assertEqual(sha_text(self.v6), GUARD_670)
        self.assertEqual(self.v6, m.make_guard(R670, self.v5, PROBE, '0.0.670'))
        self.assertEqual(self.v6, m.bump_guard_670(self.v5, PROBE))

    def test_exactly_five_lines_change_and_each_is_669_to_670(self):
        before, after = self.v5.splitlines(), self.v6.splitlines()
        self.assertEqual(len(before), len(after))
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 5, changed)
        for a, b in changed:
            self.assertEqual(a.replace('669', '670'), b)
        diff = [l for l in difflib.unified_diff(before, after, lineterm='', n=0) if l[:1] in '+-' and l[:3] not in ('+++', '---')]
        self.assertEqual(len(diff), 10)   # five removed and five added lines

    def test_no_reference_to_kernel_669_remains(self):
        self.assertNotIn('669', self.v6.replace(PROBE, ''))
        self.assertNotIn('0.0.669', self.v6)

    def test_the_capability_block_and_the_hook_are_present_exactly_once(self):
        block = m.capability_block(m.KERNEL_BRANCH_670, PROBE)
        self.assertEqual(self.v6.count(block), 1)
        self.assertEqual(self.v6.count('REFRESH60_INSTALLED'), 1)
        self.assertEqual(self.v6.count('refresh_begin() {'), 1)
        self.assertEqual(self.v6.count("local re_bringup='com\\.navi48\\.bringup[[:space:]]+\\(0\\.0\\.670\\)'"), 1)

    def test_the_0_0_669_guard_is_the_stage34_guard_with_its_bump_and_hook(self):
        # the chain that produced the 0.0.669 guard: stage34 original -> 0.0.669 capability block -> refresh-60 hook
        stage34 = (V5 / 'evidence/original-guard.sh').read_text()
        self.assertEqual(self.v5, hook.apply_refresh_patch(m.bump_guard_669(stage34, m.PROBE_667_SHA)))

    def test_bash_accepts_the_guard(self):
        r = subprocess.run(['/bin/bash', '-n', str(V6 / 'system' / GUARD)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_metal_expectations_are_the_live_bundle_34_pins(self):
        version, pins = m.live_metal_pins(self.v6)
        self.assertEqual(version, '34')
        self.assertEqual(pins, m.live_metal_pins(self.v5)[1])


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


class Gates670(unittest.TestCase):
    """The capability block and the refresh hook of the 0.0.670 guard, run in bash against fake commands."""

    def setUp(self):
        self.guard = (V6 / 'system' / GUARD).read_text()
        self.tmp = tempfile.TemporaryDirectory(prefix='refresh60b-gates-')
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

    def test_the_capability_block_accepts_0_0_670_and_stops_the_others(self):
        block = m.capability_block(m.KERNEL_BRANCH_670, self.probe_sha)
        script = CAPABILITY_HARNESS + 'loaded=$(kmutil showloaded --list-only)\n' + block
        line = lambda kernel: '  12 0 0x0 0x0 com.navi48.bringup (%s) 1 UUID' % kernel
        env = {'FAKE_SESSION': '63 / 9 / 1'}
        rc, _, out, calls = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.670')})
        self.assertEqual(rc, 0)
        self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', out)
        self.assertIn('accel sessstat 95', calls)
        rc, _, out, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line('0.0.665')})
        self.assertEqual(rc, 0)
        self.assertIn('CAPABILITY_CHECKS=skipped for kernel 0.0.665', out)
        for kernel in ('0.0.669', '0.0.668'):
            with self.subTest(kernel=kernel):
                rc, last, _, _ = run_script(self.work, script, {**env, 'FAKE_LOADED': line(kernel)})
                self.assertEqual((rc, last), (1, 'STOP expected kernel 670 or 665'))

    def test_the_hook_gate_requests_60_only_for_0_0_670_with_the_flag(self):
        fn = function_text(self.guard, 'refresh_begin')
        flag = self.work / 'app/refresh-60'
        kexts_670 = ('  92 0 0xffffff8004240000 0x7eb000 0x7eb000 com.navi48.bringup (0.0.670) 9716F9B9-A7FA-3BC4-9A9D-2CCC29AF069F <19 9 7 6 3 1>\n'
                     '  93 0 0xffffff8004340000 0x1000 0x1000 com.hackintosh.RDNA4FB (0.0.9) 1A2B3C4D-0000-0000-0000-000000000000 <5 3 2>\n')
        kexts_669 = kexts_670.replace('(0.0.670)', '(0.0.669)')
        kexts_rdna8 = kexts_670.replace('(0.0.9)', '(0.0.8)')
        script = HOOK_HARNESS + 'refresh_active=0\nREFRESH_TIMEOUT=120\nREFRESH_FLAG="$APP/refresh-60"\n' + fn + '\nrefresh_begin\necho "rc=$?"\n'
        base = {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts_670}
        # no flag file: nothing runs
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual((rc, last, calls), (0, 'rc=0', ''))
        # flag present, 0.0.670 and RDNA4FB 0.0.9: the 60 Hz request with the 120 s timeout
        flag.write_text('')
        rc, last, out, calls = run_script(self.work, script, base)
        self.assertEqual(rc, 0)
        self.assertIn('REFRESH60_REQUESTED', out)
        self.assertEqual(calls.strip(), 'accel refresh 60 120')
        # 0.0.669 or another RDNA4FB: refused by name, no request
        for name, kexts in (('0.0.669', kexts_669), ('RDNA4FB 0.0.8', kexts_rdna8)):
            with self.subTest(kexts=name):
                rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '1', 'FAKE_KEXTS': kexts})
                self.assertIn('REFRESH60_SKIPPED loaded kexts are not 0.0.670 and RDNA4FB 0.0.9', out)
                self.assertEqual(calls, '')
        # a flag that is not root-owned 0644: refused, no request
        rc, _, out, calls = run_script(self.work, script, {'FAKE_FLAG_VALID': '0', 'FAKE_KEXTS': kexts_670})
        self.assertIn('REFRESH60_SKIPPED flag is not a root-owned 0644 regular file', out)
        self.assertEqual(calls, '')


class Efi670(unittest.TestCase):
    def test_efi_is_the_669_candidate_plus_the_listed_670_files_only(self):
        man = json.loads((V6 / 'manifest.json').read_text())
        v5 = json.loads((V5 / 'manifest.json').read_text())
        self.assertEqual(man['candidate_version'], '0.0.670')
        self.assertEqual(man['candidate_kernel_sha256'], KERNEL_670)
        self.assertEqual(man['baseline_config_sha256'], CONFIG_669)
        self.assertEqual(man['baseline_efi_files'], v5['candidate_efi_files'])
        t5, t6 = m.tree(V5 / 'EFI'), m.tree(V6 / 'EFI')
        self.assertEqual({n for n in t5 if t6.get(n) != t5[n]}, {'OC/config.plist'})
        added = set(t6) - set(t5)
        self.assertEqual(added, {n for n in added if n.startswith(KEXT + '/')} | {'RECOVERY/pre-contexts-670-config.plist'})
        self.assertEqual(sorted(man['add_files']), sorted(added))
        self.assertEqual(m.sha(V6 / 'EFI' / KEXT / 'Contents/MacOS/Navi48Bringup'), KERNEL_670)

    def test_the_configuration_differs_only_in_the_bundle_path(self):
        before = plistlib.loads((V5 / 'EFI/OC/config.plist').read_bytes())
        after = plistlib.loads((V6 / 'EFI/OC/config.plist').read_bytes())
        self.assertEqual(m.diff_paths(before, after), ['/Kernel/Add/7/BundlePath'])
        self.assertEqual(after['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.670.kext')
        self.assertEqual(m.sha(V6 / 'EFI/OC/config.plist'), CONFIG_670)
        self.assertEqual(m.sha(V6 / 'EFI/RECOVERY/pre-contexts-670-config.plist'), CONFIG_669)

    def test_the_kext_identity(self):
        info = plistlib.loads((V6 / 'EFI' / KEXT / 'Contents/Info.plist').read_bytes())
        self.assertEqual((info['CFBundleIdentifier'], info['CFBundleVersion']), ('com.navi48.bringup', '0.0.670'))

    def test_the_system_files_are_the_three_reviewed_files(self):
        system = {p.relative_to(V6 / 'system').as_posix() for p in (V6 / 'system').rglob('*') if p.is_file()}
        self.assertEqual(system, {GUARD, APP + '/context-isolation-probe', NAVI_REL})
        self.assertEqual(m.sha(V6 / 'system' / GUARD), GUARD_670)
        self.assertEqual(m.sha(V6 / 'system' / APP / 'context-isolation-probe'), PROBE)
        self.assertEqual(m.sha(V6 / 'system' / NAVI_REL), NAVI48TEST_SHA)
        self.assertEqual(m.sha(V6 / 'system' / NAVI_REL), m.sha(V5 / 'system' / NAVI_REL))
        for name in system:
            self.assertEqual((V6 / 'system' / name).stat().st_mode & 0o777, 0o755, name)
        self.assertEqual(m.sha(V6 / 'evidence/probe-self-test.log'), PROBE_SELF_TEST_SHA)
        self.assertEqual(m.sha(V6 / 'evidence/original-guard.sh'), GUARD_669)

    def test_the_payload_verifier_accepts_it_without_a_live_mount(self):
        self.assertEqual(m.verify(V6, live=False)['candidate_version'], '0.0.670')

    def test_the_payload_holds_no_path_outside_the_release_layout(self):
        self.assertEqual({p.name for p in V6.iterdir()}, {'EFI', 'system', 'evidence', 'manifest.json'})
        self.assertEqual({p.name for p in (V6 / 'EFI').iterdir()}, {'OC', 'RECOVERY'})
        self.assertEqual({p.relative_to(V6 / 'evidence').as_posix() for p in (V6 / 'evidence').rglob('*') if p.is_file()},
                         {'build-manifest.json', 'original-guard.sh', 'probe-self-test.log'})


if __name__ == '__main__':
    unittest.main()
