#!/usr/bin/env python3
"""Check that the trial guard qualifies the new kernel before display activation, for both releases.

0.0.666: the stage26 guard (stage25 original, transformed) and the single-key boot-configuration edit.
0.0.667: the live bundle-30 guard (stage30-vonly-v1) plus only the 0.0.667 expectations, and the two-key edit
         (the kext entry and Misc/Boot/PollAppleHotKeys, so Shift in the picker boots with -x).
"""
import difflib
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('payload',Path(__file__).with_name('production-kernel-payload.py'))
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
R666, R667 = m.RELEASES['0.0.666'], m.RELEASES['0.0.667']
BASE = '''PROFILE=stage25-archive-boundary-v1
echo 'CANDIDATE=stage25-archive-boundary'
loaded=$(kmutil showloaded --list-only)
[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo 'STOP bringup or RDNA4FB kext missing'; exit 1; }
fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)
adopt=$("$NT" accel pipeadopt)
arm=$("$NT" accel pipearm 1)
'''
# the live bundle-30 guard shape: profile stage30, no kernel or probe lines yet
LIVE = BASE.replace('PROFILE=stage25-archive-boundary-v1', 'PROFILE=stage30-vonly-v1').replace(
    "echo 'CANDIDATE=stage25-archive-boundary'", "echo 'CANDIDATE=stage25-archive-boundary'")


def baseline_data(poll=False):
    return {'Kernel':{'Add':[{'Enabled':True,'BundlePath':m.OLD,'ExecutablePath':'Contents/MacOS/Navi48Bringup'}]},
            'Misc':{'Boot':{'PollAppleHotKeys':poll,'Timeout':5}},
            'unrelated':{'refresh':120,'audio':'original'}}


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
        tokens = ['expected kernel 667','c'*64,'--check-profile','accel sessstat 95',
                  'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64','fbidentity=','accel pipeadopt','accel pipearm 1']
        positions = [result.index(token) for token in tokens]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('PROFILE=stage30-vonly-v1', result)
        self.assertNotIn('expected kernel 666', result)
        self.assertNotIn('stage26', result)
        # only the added kernel check and probe block: removing them returns the live guard exactly
        changes = [l for l in difflib.ndiff(LIVE.splitlines(), result.splitlines()) if l[:1] in '+-?']
        self.assertTrue(changes and all(l[0] == '+' for l in changes))   # additions only, nothing removed
        self.assertTrue(any('expected kernel 667' in l for l in changes))
        self.assertTrue(any('context-isolation-probe' in l for l in changes))

    def test_667_guard_refuses_unexpected_live_text(self):
        for changed in (LIVE.replace('fbidentity=$','identity=$'),
                        LIVE.replace('fbidentity=$', '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }\nfbidentity=$')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                m.guard_live(changed,'d'*64,'0.0.667')

    def test_release_guards_are_dispatched_by_release(self):
        self.assertEqual(m.make_guard(R666, BASE, 'e'*64, '0.0.666'), m.guard_text(BASE,'e'*64,'0.0.666'))
        self.assertEqual(m.make_guard(R667, LIVE, 'e'*64, '0.0.667'), m.guard_live(LIVE,'e'*64,'0.0.667'))

    def test_bundle_30_metal_expectations_are_pinned_for_667(self):
        self.assertEqual(R667['metal']['Contents/MacOS/Navi48Metal'],
                         '8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230')
        self.assertEqual(R667['metal']['Contents/Resources/libn48xlate.dylib'],
                         '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a')
        self.assertIsNone(R666['metal'])

    def test_666_boot_configuration_changes_only_bundle_path(self):
        data = baseline_data()
        expected = m.expected_config(data, R666)
        self.assertEqual([d[1:] for d in m.diff_paths(data, expected)], ['Kernel/Add/0/BundlePath'])
        self.assertEqual(expected['Kernel']['Add'][0]['BundlePath'], R666['new'])
        self.assertEqual(expected['Misc']['Boot']['PollAppleHotKeys'], False)
        self.assertEqual(data['Kernel']['Add'][0]['BundlePath'], m.OLD)   # original not mutated
        self.assertEqual(data['unrelated'],{'refresh':120,'audio':'original'})

    def test_667_boot_configuration_changes_two_keys(self):
        data = baseline_data()
        expected = m.expected_config(data, R667)
        self.assertEqual([d[1:] for d in m.diff_paths(data, expected)],
                         ['Kernel/Add/0/BundlePath', 'Misc/Boot/PollAppleHotKeys'])
        self.assertEqual(expected['Kernel']['Add'][0]['BundlePath'], R667['new'])
        self.assertIs(expected['Misc']['Boot']['PollAppleHotKeys'], True)
        self.assertEqual(expected['unrelated'], {'refresh':120,'audio':'original'})

    def test_667_refuses_unexpected_poll_state_and_unknown_entry(self):
        with self.assertRaises(ValueError):
            m.expected_config(baseline_data(poll=True), R667)
        data = baseline_data()
        data['Kernel']['Add'][0]['BundlePath'] = 'Unknown.kext'
        with self.assertRaises(ValueError):
            m.expected_config(data, R667)

    def test_only_bundle_path_changes_in_boot_configuration(self):
        data = {'Kernel':{'Add':[{'Enabled':True,'BundlePath':m.OLD,'ExecutablePath':'Contents/MacOS/Navi48Bringup'}]},
                'unrelated':{'refresh':120,'audio':'original'}}
        m.baseline_config(data)['BundlePath'] = R666['new']
        self.assertEqual(data['unrelated'],{'refresh':120,'audio':'original'})
        with self.assertRaises(ValueError):m.baseline_config(data)


if __name__ == '__main__': unittest.main()
