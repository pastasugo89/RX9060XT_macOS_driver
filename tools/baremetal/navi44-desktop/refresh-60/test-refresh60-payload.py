#!/usr/bin/env python3
"""Check the 0.0.669 (refresh-60) kernel payload against its reviewed inputs.

Release record: RELEASES['0.0.669'] holds the reviewed values (candidate binary, navi48test, probe, base, carried files).
Guard: the 0.0.669 guard is the live 0.0.668 guard with only its capability block moved to 0.0.669, plus the refresh-60 hook
(additions only). Against the reviewed hook output only the capability block differs; bash -n accepts it; the hook is present
once and gated (flag file, root-owned flag, loaded kernel 0.0.669 and RDNA4FB 0.0.9, then the request).
Payload: kernel-payload-v5 is internally consistent (every recorded sha matches its file), its system files are exactly the
release's three reviewed files, and its EFI additions are exactly the listed files.

Reads files only. The bash checks run the capability block with fake NT and probe scripts in a temporary directory.
No research-tree binary is executed. The live guard and the live Metal bundle are READ (read only) for the stage-time consistency checks;
nothing live is written, and no sudo or network access is used.
"""
import difflib
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
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True   # no __pycache__ inside the repository
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DESKTOP = HERE.parent
REFRESH_BUILD = ROOT / 'research/builds/macos-20261101/refresh-60'
V4 = ROOT / 'research/builds/macos-20261031/production/kernel-payload-v4'
V5 = REFRESH_BUILD / 'kernel-payload-v5'

# The reviewed values, written out here so that a change to the script alone cannot move them.
KERNEL_668 = 'ab4c7fed6dd6c6ee52096da25d78f50bc515a51fdbfe8f591654143afe9ccb6d'
CONFIG_668 = 'c8e2a26453bfcadb6afd716ad3a6927d9312c9fd290e49c37609f8d5ee8775ab'
GUARD_668 = 'eaf88b0ab3a2711531c02efe22bc61bdf0012c1f0f2089fe8dd8ebd960ffd948'
HOOK_668_GUARD = '95777cd184daca0ef5bb9c2b460d1bcd61713839700e400f2f0468d0bd6397fd'
KERNEL_669 = 'cb6fd1067edf3ebd1f12ea20a91726698bdf2833591a86d50489d31626057def'
GUARD_669 = '36ab536ab8368d54713fd1c82fe69023bb27c56659c26e3e82d4e60b56d05cf0'   # stage-time derivation of the CURRENT live guard (profile stage34-zinit-v1, Metal bundle 34)
GUARD_669_STAGE = '8cc406859e1e3c5d4265dbb0cf1a39df1bb7c6bebe8b1ca5739cc4451055dcd1'   # the stage34 guard the 0.0.669 guard was derived from (payload v5 evidence)
LIVE_GUARD = Path('/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh')
PROBE = '5afe2b52b0c0adc7a4bf1ea8f8e07437929ed9cfe066fa1f56a39240ceb000c5'
NAVI48TEST_SHA = '83e7f3e3c9609ce636e138acf5a5186dbf6ef5c8951bcc6342eb21a1d058b94c'
INSTALLED_NAVI48TEST_SHA = 'aa1e6415387fe38e0e02a0c6d345cf5d1c575e623c41e7b07c62fd1a5123ad15'   # the 305376-byte copy it replaces
PROBE_SELF_TEST_SHA = '934011ce4b4a3f4ebaabe6b69247e06f13f39387976c790ccfc65fb95c2d75ed'
NAVI_REL = 'Library/Application Support/Navi44/accelerated-trial/navi48test'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load('payload', DESKTOP / 'production-kernel-payload.py')
hook = load('apply_refresh_guard', HERE / 'apply_refresh_guard.py')
R669, R668 = m.RELEASES['0.0.669'], m.RELEASES['0.0.668']


def changes(before, after):
    """Removed and added lines between two texts (unified diff with no context)."""
    diff =[l for l in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm='', n=0)
            if l[:1] in '+-' and l[:3] not in ('+++', '---')]
    return [l[1:] for l in diff if l[0] == '-'], [l[1:] for l in diff if l[0] == '+']


def only(text, needle):
    """The single line of text that contains needle (the capability lines are found this way)."""
    hits = [line for line in text.splitlines() if needle in line]
    if len(hits) != 1:
        raise AssertionError('expected one line containing %r, found %d' % (needle, len(hits)))
    return hits[0]


# The capability block's own kernel match and STOP text (the hook's regex lines carry no '; then', so these match one line each).
CAP_668 = r"[[:space:]]+\(0\.0\.668\)'; then"
CAP_669 = r"[[:space:]]+\(0\.0\.669\)'; then"
STOP_668 = 'STOP expected kernel 668 or 665'
STOP_669 = 'STOP expected kernel 669 or 665'


class Release669(unittest.TestCase):
    def test_release_record_holds_the_reviewed_values(self):
        self.assertEqual(R669['new'], 'Navi48Bringup-contexts-0.0.669.kext')
        self.assertEqual(R669['recovery'], 'RECOVERY/pre-contexts-669-config.plist')
        self.assertEqual(R669['from'], 'Navi48Bringup-contexts-0.0.668.kext')
        self.assertEqual(R669['from_kernel_sha'], KERNEL_668)
        self.assertEqual(R669['from_config_sha'], CONFIG_668)
        self.assertEqual(R669['kernel_sha'], KERNEL_669)
        self.assertEqual(R669['tests'], 8)
        self.assertEqual(R669['probe_reuse'], PROBE)
        self.assertEqual(R669['system_files'], {m.APP + '/navi48test': NAVI48TEST_SHA})
        self.assertEqual(R669['guard'], 'live-669')
        self.assertIsNone(R669['metal_version'])   # derived from the guard at stage time (release_for_guard)
        self.assertIsNone(R669['metal'])
        version, pins = m.release_for_guard(R669, LIVE_GUARD.read_text()).get('metal_version'), m.release_for_guard(R669, LIVE_GUARD.read_text())['metal']
        self.assertEqual(version, '34')
        self.assertEqual(set(pins), set(m.METAL_COMPONENTS))
        self.assertEqual(R669['edits'], [{'path': 'Kernel/Add/7/BundlePath', 'old': 'Navi48Bringup-contexts-0.0.668.kext',
                                          'new': 'Navi48Bringup-contexts-0.0.669.kext'}])
        self.assertEqual(R669['extras'], {'RECOVERY/pre-contexts-669-config.plist': 'baseline'})
        self.assertEqual(R669['carried'], {m.STARTUP: m.STARTUP_SHA, 'RECOVERY/funzionante-665.plist': m.BASE_CONFIG_SHA,
                                           'RECOVERY/pre-contexts-667-config.plist': m.BASE_CONFIG_SHA})
        self.assertEqual(R669['recovery_entry'], m.RECOVERY_ENTRY)
        self.assertEqual(R669['base'], 'reviewed-candidate')
        self.assertEqual(R669['binary_checks'], 'not-run')
        self.assertEqual(R669['self_test_log_sha'], PROBE_SELF_TEST_SHA)

    def test_strings_are_the_668_strings_plus_the_refresh_strings(self):
        self.assertEqual(set(R669['strings']), set(R668['strings']) | {'refresh60: verb action', 'Navi48,RefreshHz'})

    def test_the_668_release_keeps_its_behaviour_fields(self):
        self.assertEqual(R668['guard'], 'live-668')
        self.assertEqual(R668['kernel_sha'], KERNEL_668)
        for key in ('system_files', 'binary_checks', 'base'):
            self.assertNotIn(key, R668)

    def test_the_candidate_build_is_the_recorded_0_0_669_kernel(self):
        build = json.loads((REFRESH_BUILD / 'kernel-contexts-v5/manifest.json').read_text())
        self.assertEqual(build['candidate_version'], '0.0.669')
        self.assertEqual(build['candidate_binary_sha256'], KERNEL_669)
        self.assertEqual(m.sha(REFRESH_BUILD / 'kernel-contexts-v5' / build['candidate_bundle'] / 'Contents/MacOS/Navi48Bringup'), KERNEL_669)
        self.assertEqual(len(build['cpu_tests']), R669['tests'])
        self.assertTrue(set(R669['strings']) <= set(build['required_strings']))
        self.assertEqual(build['active_baseline']['kernel_sha256'], KERNEL_668)
        self.assertEqual(build['active_baseline']['config_sha256'], CONFIG_668)
        self.assertTrue(m.reviewed_base(build, R669))

    def test_the_refresh60_navi48test_is_the_reviewed_file(self):
        source = REFRESH_BUILD / 'navi48test/navi48test'
        self.assertEqual(m.sha(source), NAVI48TEST_SHA)
        self.assertEqual(source.stat().st_size, 264320)


class Guard669(unittest.TestCase):
    def setUp(self):
        # the stage-time input, read from payload v5's evidence copy: the live file is the 0.0.669 guard once installed (it is no longer the input)
        self.live = (V5 / 'evidence/original-guard.sh').read_text()
        # the hook applied to the same live guard (the stage33 hooked file of the earlier review is historical, not an input any more)
        self.reviewed = hook.apply_refresh_patch(self.live)
        self.derived = m.make_guard(R669, self.live, m.PROBE_667_SHA, '0.0.669')

    def test_the_stage_time_input_is_the_pinned_stage34_guard(self):
        self.assertEqual(hashlib.sha256(self.live.encode('utf-8')).hexdigest(), GUARD_669_STAGE)

    def test_the_input_has_the_reviewed_0_0_668_capability_block_once(self):
        self.assertEqual(self.live.count(m.capability_block(m.KERNEL_BRANCH_668, m.PROBE_667_SHA)), 1)

    def test_the_derived_guard_is_pinned_and_is_the_hook_on_the_bumped_668_guard(self):
        self.assertEqual(hashlib.sha256(self.derived.encode('utf-8')).hexdigest(), GUARD_669)
        self.assertEqual(self.derived, hook.apply_refresh_patch(m.bump_guard_669(self.live, m.PROBE_667_SHA)))

    def test_the_hook_alone_is_additions_only_and_is_the_reviewed_output(self):
        hooked = hook.apply_refresh_patch(self.live)
        self.assertEqual(hooked, self.reviewed)
        removed, added = changes(self.live, hooked)
        self.assertEqual(removed, [])
        self.assertGreater(len(added), 0)

    def test_against_the_reviewed_hook_output_only_the_capability_block_differs(self):
        removed, added = changes(self.reviewed, self.derived)
        self.assertEqual(removed, [only(self.reviewed, CAP_668), only(self.reviewed, STOP_668)])
        self.assertEqual(added, [only(self.derived, CAP_669), only(self.derived, STOP_669)])

    def test_against_the_live_668_guard_the_changes_are_the_capability_lines_plus_the_hook(self):
        removed, added = changes(self.live, self.derived)
        self.assertEqual(removed, [only(self.live, CAP_668), only(self.live, STOP_668)])
        hook_added = changes(self.live, self.reviewed)[1]
        self.assertEqual(Counter(added) - Counter(hook_added), Counter([only(self.derived, CAP_669), only(self.derived, STOP_669)]))
        self.assertEqual(Counter(hook_added) - Counter(added), Counter())

    def test_the_0_0_669_capability_block_is_present_exactly_once(self):
        self.assertEqual(self.derived.count(m.capability_block(m.KERNEL_BRANCH_669, m.PROBE_667_SHA)), 1)

    def test_the_derivation_refuses_other_text(self):
        with self.assertRaises(ValueError):
            m.guard_669(self.live.replace(m.capability_block(m.KERNEL_BRANCH_668, m.PROBE_667_SHA), ''), m.PROBE_667_SHA)
        with self.assertRaises(ValueError):
            hook.apply_refresh_patch(self.derived)   # the hook is never applied twice

    def test_bash_accepts_the_derived_guard(self):
        with tempfile.TemporaryDirectory(prefix='refresh60-guard-') as work:
            path = Path(work) / 'guard.sh'
            path.write_text(self.derived)
            result = subprocess.run(['/bin/bash', '-n', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_hook_is_present_once_and_gated(self):
        g = self.derived
        self.assertEqual(g.count('REFRESH60_INSTALLED'), 1)
        self.assertEqual(g.count('refresh_begin || true'), 1)
        # the request follows the pipereload check and precedes the WindowServer restart
        self.assertLess(g.index('"$NT" accel pipereload'), g.index('refresh_begin || true'))
        self.assertLess(g.index('refresh_begin || true'), g.index('echo "RESTART_WINDOWSERVER'))
        # the 0.0.669 and RDNA4FB 0.0.9 patterns are defined once each (the function defines them before its gates)
        for definition in ("re_bringup='com\\.navi48\\.bringup[[:space:]]+\\(0\\.0\\.669\\)'",
                           "re_fb='com\\.hackintosh\\.RDNA4FB[[:space:]]+\\(0\\.0\\.9\\)'"):
            self.assertEqual(g.count(definition), 1, definition)
        # the gates, in order: the flag file, its root-owned check, the loaded kernels, then the request
        gates = ['if [[ ! -e "$REFRESH_FLAG" && ! -L "$REFRESH_FLAG" ]]; then',
                 'if ! root_flag_valid "$APP/refresh-60"; then',
                 'if ! [[ $kexts =~ $re_bringup && $kexts =~ $re_fb ]]; then',
                 '"$NT" accel refresh 60 "$REFRESH_TIMEOUT"']
        positions = []
        for gate in gates:
            self.assertEqual(g.count(gate), 1, gate)
            positions.append(g.index(gate))
        self.assertEqual(positions, sorted(positions))
        self.assertLess(positions[-1], g.index('refresh_begin || true'))


@unittest.skipUnless(shutil.which('shasum'), 'needs shasum (macOS guard)')
class Capability669(unittest.TestCase):
    HARNESS = r'''kmutil() { printf '%s\n' "$FAKE_LOADED"; }
ioreg() { :; }
'''
    FAKE_NT = r'''#!/bin/bash
echo "$*" >> "$CALLS"
case "$*" in
  "accel sessstat 95") echo "slot / VMID / session : $FAKE_SESSION" ;;
esac
'''
    FAKE_PROBE = '#!/bin/bash\nif [ "$1" = "--check-profile" ]; then echo PROFILE_OK; fi\n'

    def run_block(self, work, block, loaded, session='63 / 9 / 1'):
        script = work / 'block.sh'
        script.write_text(self.HARNESS + 'loaded=$(kmutil showloaded --list-only)\n' + block)
        calls = work / 'calls.txt'
        calls.unlink(missing_ok=True)
        env = {'PATH': os.environ['PATH'], 'APP': str(work / 'app'), 'NT': str(work / 'nt'), 'CALLS': str(calls),
               'FAKE_LOADED': loaded, 'FAKE_SESSION': session}
        result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
        lines = result.stdout.strip().splitlines()
        return result.returncode, (lines[-1] if lines else ''), result.stdout, (calls.read_text() if calls.exists() else '')

    def test_the_669_block_accepts_669_and_stops_the_other_kernels(self):
        with tempfile.TemporaryDirectory(prefix='refresh60-block-') as tmp:
            work = Path(tmp)
            (work / 'app').mkdir()
            probe = work / 'app/context-isolation-probe'
            probe.write_text(self.FAKE_PROBE)
            probe.chmod(0o755)
            nt = work / 'nt'
            nt.write_text(self.FAKE_NT)
            nt.chmod(0o755)
            probe_sha = hashlib.sha256(probe.read_bytes()).hexdigest()
            block = m.capability_block(m.KERNEL_BRANCH_669, probe_sha)
            line = lambda kernel: '  12 0 0x0 0x0 com.navi48.bringup (%s) 1 UUID' % kernel
            rc, _, out, calls = self.run_block(work, block, line('0.0.669'))
            self.assertEqual(rc, 0)
            self.assertIn('CONTEXT_PROFILE_VERIFIED=PROFILE_OK', out)
            self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', out)
            self.assertIn('accel sessstat 95', calls)
            rc, _, out, _ = self.run_block(work, block, line('0.0.665'))
            self.assertEqual(rc, 0)
            self.assertIn('CAPABILITY_CHECKS=skipped for kernel 0.0.665', out)
            for kernel in ('0.0.668', '0.0.667'):
                with self.subTest(kernel=kernel):
                    rc, last, _, _ = self.run_block(work, block, line(kernel))
                    self.assertEqual((rc, last), (1, 'STOP expected kernel 669 or 665'))
            rc, last, _, _ = self.run_block(work, block, line('0.0.669'), session='12 / 9 / 1')
            self.assertEqual((rc, last), (1, 'STOP missing logical context 63'))
            wrong = m.capability_block(m.KERNEL_BRANCH_669, 'f' * 64)
            rc, last, _, _ = self.run_block(work, wrong, line('0.0.669'))
            self.assertEqual((rc, last), (1, 'STOP context profile checker changed'))


class Payload669(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((V5 / 'manifest.json').read_text())

    def test_manifest_records_a_prepared_not_installed_payload(self):
        man = self.manifest
        self.assertEqual(man['status'], 'prepared-not-installed')
        self.assertEqual(man['candidate_version'], '0.0.669')
        self.assertEqual(man['candidate_kernel_sha256'], KERNEL_669)
        self.assertEqual(man['candidate_config_sha256'], m.sha(V5 / 'EFI/OC/config.plist'))
        self.assertEqual(man['baseline_config_sha256'], CONFIG_668)
        self.assertIs(man['live_efi_verified'], False)
        self.assertEqual(man['installation'], 'not performed')
        self.assertEqual(man['hardware_validation'], 'not performed')
        self.assertEqual(man['baseline_source'], 'recorded-payload:kernel-payload-v4:candidate')
        self.assertEqual(man['deferred_checks'], {**m.DEFERRED_CHECKS, 'probe_self_test_log_sha256': PROBE_SELF_TEST_SHA})

    def test_every_recorded_sha_and_mode_matches_its_file(self):
        for name, digest in self.manifest['files'].items():
            self.assertEqual(m.sha(V5 / name), digest, name)
        for name, mode in self.manifest['file_modes'].items():
            self.assertEqual((V5 / name).stat().st_mode & 0o777, mode, name)
        on_disk = sorted(p.relative_to(V5).as_posix() for p in V5.rglob('*') if p.is_file() and p.name != 'manifest.json')
        self.assertEqual(on_disk, sorted(self.manifest['files']))

    def test_the_script_verifier_accepts_the_payload_without_a_live_mount(self):
        self.assertEqual(m.verify(V5, live=False)['candidate_version'], '0.0.669')

    def test_the_system_files_are_exactly_the_three_reviewed_files(self):
        system = {p.relative_to(V5 / 'system').as_posix() for p in (V5 / 'system').rglob('*') if p.is_file()}
        self.assertEqual(system, {m.GUARD, m.PROBE, NAVI_REL})
        self.assertEqual(m.sha(V5 / 'system' / m.GUARD), GUARD_669)
        self.assertEqual(m.sha(V5 / 'system' / m.PROBE), PROBE)
        self.assertEqual(m.sha(V5 / 'system' / NAVI_REL), NAVI48TEST_SHA)
        for name in system:
            self.assertEqual((V5 / 'system' / name).stat().st_mode & 0o777, 0o755, name)

    def test_the_navi48test_is_the_refresh60_build_and_replaces_the_installed_copy(self):
        self.assertEqual(m.sha(V5 / 'system' / NAVI_REL), m.sha(REFRESH_BUILD / 'navi48test/navi48test'))
        self.assertEqual((V5 / 'system' / NAVI_REL).stat().st_size, 264320)
        self.assertEqual(self.manifest['system_before'][NAVI_REL]['sha256'], INSTALLED_NAVI48TEST_SHA)
        self.assertEqual(self.manifest['critical_system_files'][NAVI_REL]['sha256'], INSTALLED_NAVI48TEST_SHA)
        self.assertNotEqual(INSTALLED_NAVI48TEST_SHA, NAVI48TEST_SHA)

    def test_the_guard_in_the_payload_is_the_derived_guard_for_its_evidence(self):
        self.assertEqual(m.sha(V5 / 'evidence/original-guard.sh'), GUARD_669_STAGE)
        # the live file is the stage-time guard (before the install) or the installed 0.0.669 guard; anything else is a change to review
        self.assertIn(hashlib.sha256(LIVE_GUARD.read_bytes()).hexdigest(), {GUARD_669_STAGE, GUARD_669})
        expected = m.make_guard(R669, (V5 / 'evidence/original-guard.sh').read_text(), m.sha(V5 / 'system' / m.PROBE), '0.0.669')
        self.assertEqual((V5 / 'system' / m.GUARD).read_text(), expected)
        self.assertEqual(m.sha(V5 / 'system' / m.GUARD), GUARD_669)

    def test_the_probe_is_the_reviewed_binary_with_its_recorded_self_test(self):
        self.assertEqual(m.sha(V5 / 'system' / m.PROBE), PROBE)
        self.assertEqual(m.sha(V5 / 'evidence/probe-self-test.log'), PROBE_SELF_TEST_SHA)
        self.assertEqual(m.sha(V4 / 'evidence/probe-self-test.log'), PROBE_SELF_TEST_SHA)

    def test_efi_is_the_668_candidate_plus_the_listed_669_files_only(self):
        v4 = json.loads((V4 / 'manifest.json').read_text())
        base = self.manifest['baseline_efi_files']
        self.assertEqual(base, m.scoped(v4['candidate_efi_files']))
        staged = m.tree(V5 / 'EFI')
        self.assertEqual({n for n in base if staged.get(n) != base[n]}, {'OC/config.plist'})
        added = set(staged) - set(base)
        kext = {n for n in added if n.startswith('OC/Kexts/Navi48Bringup-contexts-0.0.669.kext/')}
        self.assertEqual(added, kext | {'RECOVERY/pre-contexts-669-config.plist'})
        self.assertEqual(self.manifest['add_files'], {n: staged[n] for n in added})
        before = plistlib.loads((V4 / 'EFI/OC/config.plist').read_bytes())
        after = plistlib.loads((V5 / 'EFI/OC/config.plist').read_bytes())
        self.assertEqual(m.diff_paths(before, after), ['/Kernel/Add/7/BundlePath'])
        self.assertEqual(after['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.669.kext')

    def test_the_payload_holds_no_path_outside_the_release_layout(self):
        self.assertEqual({p.name for p in V5.iterdir()}, {'EFI', 'system', 'evidence', 'manifest.json'})
        self.assertEqual({p.name for p in (V5 / 'EFI').iterdir()}, {'OC', 'RECOVERY'})
        self.assertEqual({p.relative_to(V5 / 'evidence').as_posix() for p in (V5 / 'evidence').rglob('*') if p.is_file()},
                         {'build-manifest.json', 'original-guard.sh', 'probe-self-test.log'})


if __name__ == '__main__':
    unittest.main()
