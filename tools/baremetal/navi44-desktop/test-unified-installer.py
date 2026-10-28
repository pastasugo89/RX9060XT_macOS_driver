#!/usr/bin/env python3
"""Exercise actual directory swaps/rollback in temporary trees; no GPU/service calls."""
import importlib.util
import json
import tempfile
import plistlib
from unittest.mock import patch
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('installer', Path(__file__).with_name('install-unified-payload.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Installation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.payload, self.efi, self.root = [self.base / x for x in ('payload', 'EFI', 'system')]
        self.helper = m.check.APP + '/boot-state.py'
        self.new = m.check.APP + '/seed-gpu-apps.py'
        self.metal = m.check.METAL + '/Contents/MacOS/Metal'
        self.put(self.root / self.metal, b'old-metal', 0o755)
        self.put(self.root / self.helper, b'old-helper', 0o640)
        self.put(self.efi / 'OC/config.plist', b'old-config')
        self.put(self.efi / 'OC/old.efi', b'untouched')
        for path, data, mode in [(self.metal, b'new-metal', 0o755), (self.helper, b'new-helper', 0o755),
                                 (self.new, b'new-seeder', 0o755), (m.check.BOOT, b'new-job', 0o644)]:
            self.put(self.payload / 'system' / path, data, mode)
        self.put(self.payload / 'EFI/OC/config.plist', b'new-config')
        self.put(self.payload / 'EFI/OC/new.efi', b'addition')
        files = m.check.hashes(self.payload)
        baseline = {p[7:]: m.check.digest(self.root / p[7:]) if (self.root / p[7:]).exists() else None
                    for p in files if p.startswith('system/')}
        self.manifest = {'files': files, 'file_modes': {p: (self.payload / p).stat().st_mode & 0o777 for p in files},
                         'baseline_system_files': baseline,
                         'baseline_system_modes': {p: (self.root / p).stat().st_mode & 0o777 if sha else None for p, sha in baseline.items()},
                         'working_metal_files': m.check.hashes(self.root / m.check.METAL)}
        self.manifest['prepared_boot_uuid'] = 'test-boot'
        self.manifest['efi_volume_uuid'] = 'test-efi'
        self.plan = {'baseline_config_sha256': m.check.digest(self.efi / 'OC/config.plist'),
                     'config_sha256': files['EFI/OC/config.plist'],
                     'add_files': {'OC/new.efi': files['EFI/OC/new.efi']},
                     'all_files': {'OC/new.efi': files['EFI/OC/new.efi'], 'OC/config.plist': files['EFI/OC/config.plist'],
                                   'OC/old.efi': m.check.digest(self.efi / 'OC/old.efi')}}

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, data, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)

    def transaction(self, hook=lambda phase: None):
        return m.Transaction(self.payload, self.efi, self.root, self.manifest, self.plan, hook)

    def assert_original(self):
        self.assertEqual((self.root / self.metal).read_bytes(), b'old-metal')
        self.assertEqual((self.root / self.helper).read_bytes(), b'old-helper')
        self.assertEqual((self.root / self.helper).stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.root / self.new).exists())
        self.assertFalse((self.root / m.check.BOOT).exists())
        self.assertEqual((self.efi / 'OC/config.plist').read_bytes(), b'old-config')
        self.assertEqual((self.efi / 'OC/old.efi').read_bytes(), b'untouched')

    def test_success_then_explicit_rollback(self):
        t = self.transaction()
        backup = t.run()
        self.assertEqual((self.root / self.metal).read_bytes(), b'new-metal')
        self.assertEqual((self.efi / 'OC/config.plist').read_bytes(), b'new-config')
        self.assertEqual(json.loads((backup / 'journal.json').read_text())['phase'], 'installed-not-activated')
        t.rollback()
        self.assert_original()

    def test_each_phase_failure(self):
        # Every attempt starts from the original system; additive EFI files may remain.
        for phase in ('staged-and-backed-up', 'efi-additions-verified', 'metal-swapped', 'system-files-written',
                      'config-written', 'boot-job-written', 'installed-not-activated'):
            with self.subTest(phase=phase):
                def fault(at):
                    if at == phase:
                        raise RuntimeError('injected')
                t = self.transaction(fault)
                with self.assertRaisesRegex(RuntimeError, 'injected'):
                    t.run()
                self.assert_original()
                self.assertEqual(json.loads((t.work / 'journal.json').read_text())['phase'], 'rolled-back')

    def test_staging_content_race(self):
        (self.payload / 'system' / self.helper).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'private staging'):
            self.transaction().run()
        self.assert_original()

    def test_external_change_preserved_during_rollback(self):
        def fault(phase):
            if phase == 'boot-job-written':
                (self.root / self.helper).write_bytes(b'external-change')
                raise RuntimeError('injected')
        t = self.transaction(fault)
        with self.assertRaisesRegex(RuntimeError, 'Rollback requires review'):
            t.run()
        self.assertEqual((self.root / self.helper).read_bytes(), b'external-change')
        self.assertEqual((self.root / self.metal).read_bytes(), b'old-metal')
        self.assertEqual((self.efi / 'OC/config.plist').read_bytes(), b'old-config')
        self.assertFalse((self.root / m.check.BOOT).exists())

    def test_restore_preflight_and_changed_boot_refusal(self):
        t = self.transaction()
        t.run()
        (t.work / 'staged/efi-install-plan.json').write_text(json.dumps(self.plan))
        replies = ['test-boot\n', plistlib.dumps({'VolumeUUID': 'test-efi', 'WritableVolume': True})]
        # The real target UUID is uppercase; use the identical canonical representation.
        metadata = json.loads((t.work / 'original-manifest.json').read_text())
        metadata['efi_volume_uuid'] = 'TEST-EFI'
        (t.work / 'original-manifest.json').write_text(json.dumps(metadata))
        with patch('subprocess.check_output', side_effect=replies):
            result = m.restore_backup(t.work)
        self.assertEqual(result['mutations'], 0)
        with patch('subprocess.check_output', return_value='new-boot\n'):
            with self.assertRaisesRegex(ValueError, 'after a reboot'):
                m.restore_backup(t.work)

    def test_fat_mount_requires_actual_uuid_type_and_mountpoint(self):
        mount = self.efi.parent
        good = {'MountPoint': str(mount), 'VolumeUUID': 'EXPECTED', 'FilesystemType': 'msdos', 'WritableVolume': True}
        try:
            with patch('subprocess.check_output', return_value=plistlib.dumps(good)):
                m.verify_fat_mount(self.efi, 'expected')
            self.assertEqual(m.VERIFIED_FAT_ROOT, mount)
            for key, value in [('VolumeUUID', 'OTHER'), ('FilesystemType', 'apfs'),
                               ('WritableVolume', False), ('MountPoint', '/wrong')]:
                bad = dict(good, **{key: value})
                with patch('subprocess.check_output', return_value=plistlib.dumps(bad)):
                    with self.assertRaisesRegex(ValueError, 'FAT EFI mount'):
                        m.verify_fat_mount(self.efi, 'expected')
        finally:
            m.VERIFIED_FAT_ROOT = None

    def test_symlinked_destination_parent_refused(self):
        actual = self.root / 'elsewhere'
        actual.mkdir()
        link = self.root / 'linked'
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Unsafe destination ancestor'):
            m.atomic_file(link / 'file', b'no', 0o644)
        self.assertFalse((actual / 'file').exists())

    def test_efi_addition_conflict_preserved(self):
        self.put(self.efi / 'OC/new.efi', b'external')
        with self.assertRaisesRegex(ValueError, 'addition conflicts'):
            self.transaction().run()
        self.assert_original()
        self.assertEqual((self.efi / 'OC/new.efi').read_bytes(), b'external')


if __name__ == '__main__':
    unittest.main()
