#!/usr/bin/env python3
"""Negative tests against a cloned actual payload. No live-system changes."""
import copy
import importlib.util
import json
import os
import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('checker', Path(__file__).with_name('check-unified-payload.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SOURCE = Path(__file__).resolve().parents[3] / 'research/builds/macos-20261028/unified/payload-v3'


class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / 'payload'
        shutil.copytree(SOURCE, cls.root)
        cls.original_manifest = (cls.root / 'manifest.json').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.changed = {}
        self.manifest = json.loads(self.original_manifest)

    def tearDown(self):
        for relative, original in self.changed.items():
            path = self.root / relative
            if path.is_symlink() or path.exists():
                path.unlink()
            if original is not None:
                data, mode = original
                path.write_bytes(data)
                path.chmod(mode)
        (self.root / 'manifest.json').write_bytes(self.original_manifest)

    def remember(self, relative):
        if relative not in self.changed:
            path = self.root / relative
            self.changed[relative] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None

    def put(self, relative, data):
        self.remember(relative)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def reseal(self):
        # Recompute metadata intentionally: semantic checks must still reject a
        # self-consistent but incomplete/wrong-hardware package.
        plan_path = 'efi-install-plan.json'
        self.remember(plan_path)
        plan = json.loads((self.root / plan_path).read_text())
        plan['all_files'] = m.hashes(self.root / 'EFI')
        plan['add_files'] = {p: plan['all_files'][p] for p in plan['add_files']}
        plan['config_sha256'] = plan['all_files']['OC/config.plist']
        (self.root / plan_path).write_text(json.dumps(plan))
        files = m.hashes(self.root)
        files.pop('manifest.json')
        self.manifest['files'] = files
        self.manifest['file_modes'] = {p: (self.root / p).stat().st_mode & 0o777 for p in files}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))

    def mutate_config(self, callback):
        path = 'EFI/OC/config.plist'
        d = plistlib.loads((self.root / path).read_bytes())
        callback(d)
        self.put(path, plistlib.dumps(d, sort_keys=False))
        self.reseal()

    def test_actual_payload(self):
        manifest, plan, system = m.verify_payload(self.root)
        self.assertEqual(len(system), 462)
        self.assertEqual(len(plan['add_files']), 42)
        self.assertIn('black-band cause/removal', manifest['unproven'])

    def test_tampered_boot_script(self):
        self.put('system/' + m.APP + '/accelerated-reboot-trial.sh', b'bad')
        with self.assertRaisesRegex(ValueError, 'contents differ'):
            m.verify_payload(self.root)

    def test_missing_helper_even_with_rebuilt_manifest(self):
        path = m.APP + '/seed-gpu-apps.py'
        self.remember('system/' + path)
        (self.root / 'system' / path).unlink()
        del self.manifest['baseline_system_files'][path]
        del self.manifest['baseline_system_modes'][path]
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            m.verify_payload(self.root)

    def test_wrong_system_target_even_when_resealed(self):
        self.put('system/etc/sudoers', b'never installed')
        self.manifest['baseline_system_files']['etc/sudoers'] = None
        self.manifest['baseline_system_modes']['etc/sudoers'] = None
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'Unexpected system write'):
            m.verify_payload(self.root)

    def test_disabled_cpu_driver_is_not_completion(self):
        def mutate(d):
            for e in d['Kernel']['Add']:
                if e['BundlePath'] == 'Navi44CPPC.kext':
                    e['Enabled'] = False
        self.mutate_config(mutate)
        with self.assertRaisesRegex(ValueError, 'Required unified driver.*com.navi44.cppc'):
            m.verify_payload(self.root)

    def test_wrong_wifi_abi_is_refused(self):
        path = 'EFI/OC/Kexts/QwzAirport.kext/Contents/Info.plist'
        info = plistlib.loads((self.root / path).read_bytes())
        for p in info['IOKitPersonalities'].values():
            p['QwzAirportBuilds'] = ['25G241']
        self.put(path, plistlib.dumps(info))
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'Wi-Fi ABI'):
            m.verify_payload(self.root)

    def test_wrong_usb_merge_is_refused(self):
        path = 'EFI/OC/Kexts/USBMapB840-unified-20261028.kext/Contents/Info.plist'
        info = plistlib.loads((self.root / path).read_bytes())
        info['IOKitPersonalities']['XH00']['IOProviderMergeProperties']['port-count'] = bytes([1, 0, 0, 0])
        self.put(path, plistlib.dumps(info))
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'USB parent/count'):
            m.verify_payload(self.root)

    def test_symlink_refused(self):
        relative = 'system/' + m.APP + '/seed-gpu-apps.py'
        self.remember(relative)
        path = self.root / relative
        path.unlink()
        path.symlink_to(SOURCE / relative)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            m.verify_payload(self.root)

    def test_missing_exec_bit_even_when_resealed(self):
        relative = 'system/' + m.APP + '/navi48test'
        self.remember(relative)
        (self.root / relative).chmod(0o644)
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'Executable permission'):
            m.verify_payload(self.root)

    def test_noncanonical_paths(self):
        for value in ('../bad', '/absolute', 'a/../b', 'a//b', 'a/./b', 'a\\b', '', 4):
            with self.subTest(path=value), self.assertRaises(ValueError):
                m.relative(value)


if __name__ == '__main__':
    unittest.main()
