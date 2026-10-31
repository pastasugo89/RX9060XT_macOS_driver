#!/usr/bin/env python3
"""Check that the trial guard qualifies the new kernel before display activation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('payload',Path(__file__).with_name('production-kernel-payload.py'))
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BASE = '''PROFILE=stage25-archive-boundary-v1
echo 'CANDIDATE=stage25-archive-boundary'
loaded=$(kmutil showloaded --list-only)
[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo 'STOP bringup or RDNA4FB kext missing'; exit 1; }
fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)
adopt=$("$NT" accel pipeadopt)
arm=$("$NT" accel pipearm 1)
'''


class Guard(unittest.TestCase):
    def test_kernel_and_dynamic_profile_precede_display_changes(self):
        result = m.guard_text(BASE,'a'*64)
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
                m.guard_text(changed,'b'*64)

    def test_only_bundle_path_changes_in_boot_configuration(self):
        data = {'Kernel':{'Add':[{'Enabled':True,'BundlePath':m.OLD,'ExecutablePath':'Contents/MacOS/Navi48Bringup'}]},
                'unrelated':{'refresh':120,'audio':'original'}}
        m.baseline_config(data)['BundlePath'] = m.NEW
        self.assertEqual(data['unrelated'],{'refresh':120,'audio':'original'})
        with self.assertRaises(ValueError):m.baseline_config(data)


if __name__ == '__main__': unittest.main()
