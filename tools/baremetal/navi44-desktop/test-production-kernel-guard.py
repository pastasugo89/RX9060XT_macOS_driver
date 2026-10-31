#!/usr/bin/env python3
"""Check that the trial guard qualifies the new kernel before display activation, for both releases, and that the
recovery configuration's kernel (0.0.665) still reaches the live guard path.

0.0.666: the stage26 guard (stage25 original, transformed) and the listed boot-configuration edit.
0.0.667: the live bundle-30 guard (stage30-vonly-v1) plus one branch: loaded 0.0.667 runs the capability checks;
         loaded 0.0.665 skips them and runs the live guard unchanged; anything else stops. Three listed config edits.
The bash checks run the guard text with fake kmutil / NT / probe binaries (macOS shasum required; skipped otherwise).
"""
import difflib
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('payload',Path(__file__).with_name('production-kernel-payload.py'))
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
R666, R667 = m.RELEASES['0.0.666'], m.RELEASES['0.0.667']
PRODUCTION = Path(__file__).resolve().parents[3] / 'research/builds/macos-20261031/production'
BASE_666 = PRODUCTION / 'kernel-payload-v2/EFI/RECOVERY/pre-contexts-666-config.plist'
BASE_667 = PRODUCTION / 'kernel-payload-v3/EFI/RECOVERY/pre-contexts-667-config.plist'
BASE = '''PROFILE=stage25-archive-boundary-v1
echo 'CANDIDATE=stage25-archive-boundary'
loaded=$(kmutil showloaded --list-only)
[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo 'STOP bringup or RDNA4FB kext missing'; exit 1; }
fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)
adopt=$("$NT" accel pipeadopt)
arm=$("$NT" accel pipearm 1)
'''
# the live bundle-30 guard shape: profile stage30, no kernel or probe lines yet
LIVE = BASE.replace('PROFILE=stage25-archive-boundary-v1', 'PROFILE=stage30-vonly-v1')
HARNESS = r'''kmutil() { printf '%s\n' "$FAKE_LOADED"; }
ioreg() { :; }
'''
FAKE_NT = r'''#!/bin/bash
echo "$*" >> "$CALLS"
case "$*" in
  "accel pipeadopt") echo adopted ;;
  "accel pipearm 1") echo armed ;;
  "accel sessstat 95") echo "slot / VMID / session : $FAKE_SESSION" ;;
esac
'''
FAKE_PROBE = '#!/bin/bash\nif [ "$1" = "--check-profile" ]; then echo PROFILE_OK; fi\n'
KERNEL_667 = 'com.navi48.bringup (0.0.667)'
KERNEL_665 = 'com.navi48.bringup (0.0.665)'
KERNEL_666 = 'com.navi48.bringup (0.0.666)'
RDNA = 'com.hackintosh.RDNA4FB (1.0.0)'


def baseline_666():
    return plistlib.loads(BASE_666.read_bytes())


def baseline_667():
    return plistlib.loads(BASE_667.read_bytes())


class Guard(unittest.TestCase):
    def test_kernel_and_dynamic_profile_precede_display_changes(self):
        result = m.guard_text(BASE,'a'*64,'0.0.666')
        tokens = ['expected kernel 666','a'*64,'--check-profile','accel sessstat 95',
                  'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64','fbidentity=','accel pipeadopt','accel pipearm 1']
        positions = [result.index(token) for token in tokens]
        self.assertEqual(positions,sorted(positions))
        self.assertEqual(result.count('PROFILE='+m.PROFILE),1)
        self.assertIn('|| { echo "STOP dynamic context profile:',result)

    def test_changed_or_duplicate_baseline_is_refused(self):
        for changed in (BASE.replace('stage25-archive-boundary-v1','unknown'),
                        BASE+'\nPROFILE=stage25-archive-boundary-v1\n',
                        BASE.replace('fbidentity=$','identity=$')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                m.guard_text(changed,'b'*64,'0.0.666')

    def test_667_guard_derives_from_live_bundle_30_guard(self):
        result = m.guard_live(LIVE,'c'*64,'0.0.667')
        tokens = [r'\(0\.0\.667\)','c'*64,'--check-profile','accel sessstat 95',
                  'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64','elif printf',r'\(0\.0\.665\)','STOP expected kernel 667 or 665',
                  'fbidentity=','accel pipeadopt','accel pipearm 1']
        positions = [result.index(token) for token in tokens]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('PROFILE=stage30-vonly-v1', result)
        self.assertNotIn('expected kernel 666', result)
        self.assertNotIn('stage26', result)
        # additions only: removing the inserted lines returns the live guard exactly
        changes = [l for l in difflib.ndiff(LIVE.splitlines(), result.splitlines()) if l[:1] in '+-?']
        self.assertTrue(changes and all(l[0] == '+' for l in changes))
        self.assertTrue(any('CAPABILITY_CHECKS=skipped' in l for l in changes))
        self.assertTrue(any('context-isolation-probe' in l for l in changes))

    def test_667_guard_refuses_unexpected_live_text(self):
        for changed in (LIVE.replace('fbidentity=$','identity=$'),
                        LIVE.replace('fbidentity=$', '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }\nfbidentity=$')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                m.guard_live(changed,'d'*64,'0.0.667')

    def test_667_guard_refuses_other_versions(self):
        with self.assertRaises(ValueError):
            m.guard_live(LIVE,'d'*64,'0.0.666')

    def test_release_guards_are_dispatched_by_release(self):
        self.assertEqual(m.make_guard(R666, BASE, 'e'*64, '0.0.666'), m.guard_text(BASE,'e'*64,'0.0.666'))
        self.assertEqual(m.make_guard(R667, LIVE, 'e'*64, '0.0.667'), m.guard_live(LIVE,'e'*64,'0.0.667'))

    def test_bundle_30_metal_expectations_are_pinned_for_667(self):
        self.assertEqual(R667['metal']['Contents/MacOS/Navi48Metal'],
                         '8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230')
        self.assertEqual(R667['metal']['Contents/Resources/libn48xlate.dylib'],
                         '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a')
        self.assertIsNone(R666['metal'])

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum (macOS guard)')
    def test_667_guard_branches_behave_as_specified(self):
        """Run the derived guard for each loaded kernel. 665 must reach the live guard with the same NT call sequence."""
        with tempfile.TemporaryDirectory(prefix='guard-branch-') as work:
            work = Path(work)
            app = work/'app'; app.mkdir()
            (app/'context-isolation-probe').write_text(FAKE_PROBE)
            (app/'context-isolation-probe').chmod(0o755)
            probe_sha = hashlib.sha256((app/'context-isolation-probe').read_bytes()).hexdigest()
            nt = work/'nt'; nt.write_text(FAKE_NT); nt.chmod(0o755)
            derived = m.guard_live(LIVE, probe_sha, '0.0.667')
            def last(result):
                return result[0], result[1].splitlines()[-1]
            def run(guard_text, loaded, session='63 / 9 / 1'):
                script = work/'guard.sh'
                script.write_text(HARNESS + guard_text)
                calls = work/'calls.txt'
                calls.unlink(missing_ok=True)
                env = {'PATH': os.environ['PATH'], 'APP': str(app), 'NT': str(nt), 'CALLS': str(calls),
                       'FAKE_LOADED': loaded, 'FAKE_SESSION': session}
                result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
                return result.returncode, result.stdout.strip(), calls.read_text() if calls.exists() else ''
            loaded_with = lambda kernel: '  12 0 0x0 0x0 %s 1 UUID\n  13 0 0x0 0x0 %s 1 UUID' % (kernel, RDNA)
            live = run(LIVE, loaded_with(KERNEL_665))
            self.assertEqual(live[0], 0)
            recovery = run(derived, loaded_with(KERNEL_665))
            self.assertEqual(recovery[0], 0)
            self.assertEqual(recovery[1], live[1] + '\nCAPABILITY_CHECKS=skipped for kernel 0.0.665 (recovery configuration)')
            self.assertEqual(recovery[2], live[2])            # same NT calls, same order, as the live guard
            current = run(derived, loaded_with(KERNEL_667))
            self.assertEqual(current[0], 0)
            self.assertIn('CONTEXT_PROFILE_VERIFIED=PROFILE_OK', current[1])
            self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', current[1])
            self.assertIn('accel sessstat 95', current[2])
            self.assertEqual(last(run(derived, loaded_with(KERNEL_666))), (1, 'STOP expected kernel 667 or 665'))
            self.assertEqual(last(run(derived, '  13 0 0x0 0x0 %s 1 UUID' % RDNA)), (1, 'STOP bringup or RDNA4FB kext missing'))
            self.assertEqual(last(run(derived, loaded_with(KERNEL_667), session='12 / 9 / 1')), (1, 'STOP missing logical context 63'))
            self.assertEqual(last(run(m.guard_live(LIVE, 'f'*64, '0.0.667'), loaded_with(KERNEL_667))), (1, 'STOP context profile checker changed'))

    def test_667_boot_configuration_is_exactly_the_three_listed_edits(self):
        original = baseline_667()
        expected = m.expected_config(original, R667)
        self.assertEqual(sorted(d[1:] for d in m.diff_paths(original, expected)),
                         sorted(e['path'] for e in R667['edits']))
        self.assertEqual(expected['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.667.kext')
        self.assertEqual(expected['Misc']['Tools'][0]['Name'], 'Ripristino EFI: driver funzionanti (665)')
        self.assertEqual(expected['Misc']['Tools'][0]['Comment'],
                         'Restores RECOVERY/funzionante-665.plist (kernel 665) and reboots')
        self.assertIs(expected['Misc']['Boot']['PollAppleHotKeys'], False)   # no hotkey change
        self.assertEqual(expected['Misc']['Tools'][0]['Path'], 'OpenShell.efi')
        self.assertEqual(original['Kernel']['Add'][7]['BundlePath'], m.OLD)  # original not mutated

    def test_666_boot_configuration_changes_only_bundle_path(self):
        original = baseline_666()
        expected = m.expected_config(original, R666)
        self.assertEqual([d[1:] for d in m.diff_paths(original, expected)], ['Kernel/Add/7/BundlePath'])
        self.assertEqual(expected['Kernel']['Add'][7]['BundlePath'], R666['new'])
        self.assertIs(expected['Misc']['Boot']['PollAppleHotKeys'], False)

    def test_listed_edits_refuse_a_baseline_that_does_not_match(self):
        for path, value in (('Kernel/Add/7/BundlePath', 'Unknown.kext'),
                            ('Misc/Tools/0/Name', 'Renamed by someone else')):
            data = baseline_667()
            container, key = m.path_slot(data, path)
            container[key] = value
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'differs from the listed edit'):
                m.expected_config(data, R667)

    def test_667_lists_the_recovery_extras(self):
        self.assertEqual(R667['extras'], {'RECOVERY/pre-contexts-667-config.plist': 'baseline',
                                          'RECOVERY/funzionante-665.plist': 'baseline',
                                          'OC/Tools/startup.nsh': m.STARTUP_SHA})
        self.assertEqual(R666['extras'], {'RECOVERY/pre-contexts-666-config.plist': 'baseline'})
        self.assertEqual(hashlib.sha256(m.STARTUP_SOURCE.read_bytes()).hexdigest(), m.STARTUP_SHA)

    def test_only_bundle_path_changes_in_boot_configuration(self):
        data = {'Kernel':{'Add':[{'Enabled':True,'BundlePath':m.OLD,'ExecutablePath':'Contents/MacOS/Navi48Bringup'}]},
                'unrelated':{'refresh':120,'audio':'original'}}
        m.baseline_config(data)['BundlePath'] = R666['new']
        self.assertEqual(data['unrelated'],{'refresh':120,'audio':'original'})
        with self.assertRaises(ValueError):m.baseline_config(data)


# 0.0.668: built on payload v3's candidate (the installed 0.0.667 state). Fixtures are the reviewed payload files, not the live system.
R668 = m.RELEASES['0.0.668']
V3 = PRODUCTION / 'kernel-payload-v3'
V4 = PRODUCTION / 'kernel-payload-v4'
GUARD_REL = 'Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'
V3_GUARD = (V3 / 'system' / GUARD_REL).read_text()
V4_GUARD = (V4 / 'system' / GUARD_REL).read_text()
LIVE_BASE_OF_V4 = (V4 / 'evidence/original-guard.sh').read_text()   # the live guard payload v4 was prepared from
KERNEL_BRANCH_668_NAME = 'com.navi48.bringup (0.0.668)'


def guard_changes(before, after):
    diff = [l for l in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm='', n=0)
            if l[:1] in '+-' and l[:3] not in ('+++', '---')]
    return [l[1:] for l in diff if l[0] == '-'], [l[1:] for l in diff if l[0] == '+']


class Release668(unittest.TestCase):
    def test_the_0_0_667_capability_block_is_the_reviewed_insertion(self):
        self.assertEqual(V3_GUARD.count(m.capability_block(m.KERNEL_BRANCH, m.PROBE_667_SHA)), 1)
        self.assertEqual(LIVE_BASE_OF_V4.count(m.capability_block(m.KERNEL_BRANCH, m.PROBE_667_SHA)), 1)

    def test_bump_changes_only_the_kernel_match_and_its_stop_text(self):
        removed, added = guard_changes(V3_GUARD, m.bump_guard(V3_GUARD, m.PROBE_667_SHA))
        self.assertEqual(len(removed), 2)
        self.assertEqual(len(added), 2)
        self.assertTrue(any(r'\(0\.0\.667\)' in l for l in removed) and any(r'\(0\.0\.668\)' in l for l in added))
        self.assertTrue(any("'STOP expected kernel 667 or 665'" in l for l in removed))
        self.assertTrue(any("'STOP expected kernel 668 or 665'" in l for l in added))
        self.assertIn("'CAPABILITY_CHECKS=skipped for kernel 0.0.665 (recovery configuration)'", m.bump_guard(V3_GUARD, m.PROBE_667_SHA))

    def test_bump_follows_a_different_staged_probe_digest(self):
        bumped = m.bump_guard(V3_GUARD, 'c' * 64)
        self.assertEqual(bumped.count('== ' + 'c' * 64 + ' ]]'), 1)
        self.assertNotIn(m.PROBE_667_SHA, bumped)

    def test_bump_refuses_a_guard_without_the_reviewed_block(self):
        with self.assertRaises(ValueError):
            m.bump_guard(LIVE, 'a' * 64)                          # the stage30 base, before the 0.0.667 insertion
        with self.assertRaises(ValueError):
            m.bump_guard(V3_GUARD.replace(m.PROBE_667_SHA, 'b' * 64), m.PROBE_667_SHA)   # a probe digest the block does not pin

    def test_payload_v4_guard_is_the_bump_of_the_live_guard_it_was_prepared_from(self):
        self.assertEqual(V4_GUARD, m.bump_guard(LIVE_BASE_OF_V4, m.PROBE_667_SHA))
        self.assertEqual(m.make_guard(R668, LIVE_BASE_OF_V4, m.PROBE_667_SHA, '0.0.668'), V4_GUARD)

    def test_668_metal_pins_are_the_bundle_33_components_the_live_guard_pins(self):
        self.assertEqual(R668['metal_version'], '33')
        self.assertIn('"$bundle_version" == 33 ', LIVE_BASE_OF_V4)
        for name, digest in R668['metal'].items():
            with self.subTest(name=name):
                self.assertIn(digest, LIVE_BASE_OF_V4)
        self.assertEqual(R668['metal']['Contents/MacOS/Navi48Metal'],
                         '85c7d8bdfe8c681503a5701afc09ce3b5cddf3ef124fca587913d261c7b4fd5f')

    def test_668_boot_configuration_is_exactly_the_bundle_path_edit(self):
        original = plistlib.loads((V3 / 'EFI/OC/config.plist').read_bytes())
        expected = m.expected_config(original, R668)
        self.assertEqual([d[1:] for d in m.diff_paths(original, expected)], ['Kernel/Add/7/BundlePath'])
        self.assertEqual(expected['Kernel']['Add'][7]['BundlePath'], 'Navi48Bringup-contexts-0.0.668.kext')
        self.assertEqual(expected['Misc']['Tools'][0]['Name'], 'Ripristino EFI: driver funzionanti (665)')
        self.assertEqual(expected['Misc']['Tools'][0]['Path'], 'OpenShell.efi')

    def test_668_carries_the_recovery_features_of_payload_v3(self):
        self.assertEqual(R668['extras'], {'RECOVERY/pre-contexts-668-config.plist': 'baseline'})
        self.assertEqual(R668['recovery_entry'], m.RECOVERY_ENTRY)
        for name, digest in R668['carried'].items():
            with self.subTest(name=name):
                self.assertEqual(m.sha(V3 / 'EFI' / name), digest)
        self.assertEqual(R668['carried'][m.STARTUP], m.STARTUP_SHA)

    def test_668_probe_is_the_reviewed_binary_in_both_payloads(self):
        self.assertEqual(R668['probe_reuse'], m.PROBE_667_SHA)
        self.assertEqual(m.sha(V3 / 'system' / 'Library/Application Support/Navi44/accelerated-trial/context-isolation-probe'), m.PROBE_667_SHA)
        self.assertEqual(m.sha(V4 / 'system' / 'Library/Application Support/Navi44/accelerated-trial/context-isolation-probe'), m.PROBE_667_SHA)

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum (macOS guard)')
    def test_668_capability_block_runs_as_specified(self):
        """Run the 0.0.668 block alone (the Metal checks need the real bundle): 668 passes, 665 skips, 667 and others stop."""
        with tempfile.TemporaryDirectory(prefix='guard-668-') as work:
            work = Path(work)
            app = work/'app'; app.mkdir()
            (app/'context-isolation-probe').write_text(FAKE_PROBE)
            (app/'context-isolation-probe').chmod(0o755)
            probe_sha = hashlib.sha256((app/'context-isolation-probe').read_bytes()).hexdigest()
            nt = work/'nt'; nt.write_text(FAKE_NT); nt.chmod(0o755)
            def run(block, loaded, session='63 / 9 / 1'):
                script = work/'block.sh'
                script.write_text(HARNESS + 'loaded=$(kmutil showloaded --list-only)\n' + block)
                calls = work/'calls.txt'
                calls.unlink(missing_ok=True)
                env = {'PATH': os.environ['PATH'], 'APP': str(app), 'NT': str(nt), 'CALLS': str(calls),
                       'FAKE_LOADED': loaded, 'FAKE_SESSION': session}
                result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True)
                return result.returncode, result.stdout.strip(), calls.read_text() if calls.exists() else ''
            block = m.capability_block(m.KERNEL_BRANCH_668, probe_sha)
            current = run(block, '  12 0 0x0 0x0 ' + KERNEL_BRANCH_668_NAME + ' 1 UUID')
            self.assertEqual(current[0], 0)
            self.assertIn('CONTEXT_PROFILE_VERIFIED=PROFILE_OK', current[1])
            self.assertIn('LOGICAL_CONTEXT_CAPACITY_VERIFIED=64', current[1])
            self.assertIn('accel sessstat 95', current[2])
            recovery = run(block, '  12 0 0x0 0x0 ' + KERNEL_665 + ' 1 UUID')
            self.assertEqual(recovery[0], 0)
            self.assertIn('CAPABILITY_CHECKS=skipped for kernel 0.0.665', recovery[1])
            for loaded in (KERNEL_667, KERNEL_666):
                with self.subTest(loaded=loaded):
                    stop = run(block, '  12 0 0x0 0x0 ' + loaded + ' 1 UUID')
                    self.assertEqual((stop[0], stop[1].splitlines()[-1]), (1, 'STOP expected kernel 668 or 665'))
            wrong = run(m.capability_block(m.KERNEL_BRANCH_668, 'f' * 64), '  12 0 0x0 0x0 ' + KERNEL_BRANCH_668_NAME + ' 1 UUID')
            self.assertEqual((wrong[0], wrong[1].splitlines()[-1]), (1, 'STOP context profile checker changed'))
            missing = run(block, '  12 0 0x0 0x0 ' + KERNEL_BRANCH_668_NAME + ' 1 UUID', session='12 / 9 / 1')
            self.assertEqual((missing[0], missing[1].splitlines()[-1]), (1, 'STOP missing logical context 63'))

    def test_probe_reuse_ignores_only_the_link_uuid(self):
        probe = (V4 / 'system/Library/Application Support/Navi44/accelerated-trial/context-isolation-probe').read_bytes()
        self.assertTrue(m.same_except_uuid(probe, probe))
        uuid_byte = bytearray(probe)
        uuid_byte[0x420] ^= 0xFF                      # inside LC_UUID (the reviewed binary's UUID bytes)
        self.assertTrue(m.same_except_uuid(probe, bytes(uuid_byte)))
        code_byte = bytearray(probe)
        code_byte[-1] ^= 0x01                         # outside it: refused
        self.assertFalse(m.same_except_uuid(probe, bytes(code_byte)))
        self.assertFalse(m.same_except_uuid(probe, probe[:-1]))
        with self.assertRaises(ValueError):
            m.same_except_uuid(b'not a binary' * 8, b'not a binary' * 8)

    def test_668_kernel_and_payload_match_the_built_candidate(self):
        build = json.loads((PRODUCTION / 'kernel-contexts-v4/manifest.json').read_text())
        self.assertEqual(build['candidate_binary_sha256'], R668['kernel_sha'])
        self.assertEqual(build['active_baseline']['kernel_sha256'], R668['from_kernel_sha'])
        self.assertEqual(build['active_baseline']['config_sha256'], R668['from_config_sha'])
        self.assertEqual(len(build['cpu_tests']), R668['tests'])
        self.assertIn('the hi pool could not take it', build['required_strings'])

    def test_668_payload_verifies_with_its_recorded_inputs(self):
        m.verify(V4, live=False)

    def test_baseline_of_668_is_the_candidate_state_of_payload_v3(self):
        sources = m.baseline_sources(V3, 'candidate')
        self.assertEqual(m.sha(sources['OC/config.plist']), R668['from_config_sha'])
        self.assertEqual(m.sha(sources['OC/Kexts/' + R668['from'] + '/Contents/MacOS/Navi48Bringup']), R668['from_kernel_sha'])
        self.assertNotIn('OC/Kexts/Navi48Bringup-contexts-0.0.668.kext/Contents/Info.plist', sources)
        with self.assertRaises(ValueError):
            m.baseline_sources(V3, 'unknown')


if __name__ == '__main__': unittest.main()
