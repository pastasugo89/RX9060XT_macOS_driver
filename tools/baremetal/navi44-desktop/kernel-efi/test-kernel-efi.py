#!/usr/bin/env python3
"""Offline tests for install-kernel-efi.py and restore-kernel-efi.py.

Every test works in a temporary sandbox: a fake EFI built from kernel-payload-v2's baseline,
a temporary system root and a temporary backup root. No real EFI, /Library or diskutil call
is made. The payload directory is only read.
"""
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
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PAYLOAD_SRC = REPO / 'research/builds/macos-20261031/production/kernel-payload-v2'
INSTALL = HERE / 'install-kernel-efi.py'
RESTORE = HERE / 'restore-kernel-efi.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inst = load('install_kernel_efi', INSTALL)
rest = load('restore_kernel_efi', RESTORE)
CONFIG = inst.CONFIG
MANIFEST = json.loads((PAYLOAD_SRC / 'manifest.json').read_text())
BUNDLE = 'Navi48Bringup-contexts-0.0.666.kext'
RECOVERY = 'RECOVERY/pre-contexts-666-config.plist'
GUARD = 'Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='kernel-efi-test-'))
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        shutil.copyfile(PAYLOAD_SRC / 'manifest.json', self.payload / 'manifest.json')
        shutil.copytree(PAYLOAD_SRC / 'EFI', self.payload / 'EFI', symlinks=False)
        shutil.copytree(PAYLOAD_SRC / 'system', self.payload / 'system', symlinks=False)
        self.efi = self.root / 'efi'
        shutil.copytree(self.payload / 'EFI', self.efi, symlinks=False)
        # Make the live fake EFI the baseline: no additions, original config bytes.
        shutil.rmtree(self.efi / 'OC/Kexts' / BUNDLE)
        (self.efi / RECOVERY).unlink()
        (self.efi / CONFIG).write_bytes((self.payload / 'EFI' / RECOVERY).read_bytes())
        self.baseline = MANIFEST['baseline_efi_files']
        self.candidate = MANIFEST['candidate_efi_files']
        self.assertEqual(inst.tree(self.efi), self.baseline)
        self.system = self.root / 'system'
        (self.system / inst.APP_REL).mkdir(parents=True)
        self.backup_root = self.system / inst.BACKUP_REL
        self.disable_activation()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def disable_activation(self):
        (self.system / inst.APP_REL / 'disabled').write_text('')

    def run_cli(self, script, *args):
        result = subprocess.run([sys.executable, '-I', str(script), str(self.payload),
                                 '--efi-root', str(self.efi), '--system-root', str(self.system), *args],
                                capture_output=True, text=True)
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = {'raw': result.stdout}
        return result.returncode, report

    def install(self, *extra):
        return self.run_cli(INSTALL, '--apply', *extra)

    def backups(self):
        if not self.backup_root.exists():
            return []
        return sorted(p for p in self.backup_root.glob('efi-backup-*'))

    def snapshot(self):
        return inst.tree(self.efi), inst.tree(self.payload / 'EFI')


class InstallTests(Sandbox):
    def test_dry_run_writes_nothing(self):
        before_efi, before_payload = self.snapshot()
        rc, report = self.run_cli(INSTALL)
        self.assertEqual(rc, 0, report)
        self.assertEqual(report['mode'], 'dry-run')
        self.assertEqual(report['efi_state'], 'baseline')
        self.assertFalse(report['applied'])
        self.assertTrue(any('replace OC/config.plist' in line for line in report['planned']))
        self.assertEqual(inst.tree(self.efi), before_efi)
        self.assertEqual(inst.tree(self.payload / 'EFI'), before_payload)
        self.assertEqual(self.backups(), [])

    def test_refuses_wrong_baseline_config(self):
        cfg = plistlib.loads((self.efi / CONFIG).read_bytes())
        cfg['Misc']['Boot']['Timeout'] = 7
        (self.efi / CONFIG).write_bytes(plistlib.dumps(cfg, sort_keys=False))
        before = inst.tree(self.efi)
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertIn('neither the baseline nor the candidate', report['error'])
        self.assertEqual(inst.tree(self.efi), before)
        self.assertEqual(self.backups(), [])

    def test_refuses_extra_file_on_efi(self):
        (self.efi / 'OC/extra.txt').write_text('x')
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertFalse((self.efi / 'OC/Kexts' / BUNDLE).exists())
        self.assertEqual(self.backups(), [])

    def test_refuses_tampered_payload_kext(self):
        binary = self.payload / 'EFI/OC/Kexts' / BUNDLE / 'Contents/MacOS/Navi48Bringup'
        binary.write_bytes(binary.read_bytes() + b'\0')
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertEqual(inst.tree(self.efi), self.baseline)
        self.assertEqual(self.backups(), [])

    def test_refuses_config_change_beyond_bundle_path(self):
        # Manifest-consistent payload whose config changes a second key: must fail the exact-diff rule.
        cfg = plistlib.loads((self.payload / 'EFI' / CONFIG).read_bytes())
        cfg['Misc']['Boot']['Timeout'] = 9
        data = plistlib.dumps(cfg, sort_keys=False)
        (self.payload / 'EFI' / CONFIG).write_bytes(data)
        m = json.loads((self.payload / 'manifest.json').read_text())
        m['candidate_efi_files'][CONFIG] = inst.sha_bytes(data)
        m['candidate_config_sha256'] = inst.sha_bytes(data)
        (self.payload / 'manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'exactly one key'):
            inst.load_payload(self.payload)

    def _payload_with_hotkeys(self, value):
        cfg = plistlib.loads((self.payload / 'EFI' / CONFIG).read_bytes())
        cfg['Misc']['Boot']['PollAppleHotKeys'] = value
        data = plistlib.dumps(cfg, sort_keys=False)
        (self.payload / 'EFI' / CONFIG).write_bytes(data)
        m = json.loads((self.payload / 'manifest.json').read_text())
        m['candidate_efi_files'][CONFIG] = inst.sha_bytes(data)
        m['candidate_config_sha256'] = inst.sha_bytes(data)
        (self.payload / 'manifest.json').write_text(json.dumps(m))

    def test_accepts_poll_apple_hotkeys_enabled_beside_bundle_path(self):
        # 0.0.667 recovery kill switch: PollAppleHotKeys false -> true is the one extra change allowed.
        self._payload_with_hotkeys(True)
        inst.load_payload(self.payload)

    def test_refuses_poll_apple_hotkeys_other_change(self):
        cfg = plistlib.loads((self.payload / 'EFI' / CONFIG).read_bytes())
        cfg['Misc']['Boot']['PollAppleHotKeys'] = True
        cfg['Misc']['Boot']['Timeout'] = 9
        data = plistlib.dumps(cfg, sort_keys=False)
        (self.payload / 'EFI' / CONFIG).write_bytes(data)
        m = json.loads((self.payload / 'manifest.json').read_text())
        m['candidate_efi_files'][CONFIG] = inst.sha_bytes(data)
        m['candidate_config_sha256'] = inst.sha_bytes(data)
        (self.payload / 'manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'exactly one key'):
            inst.load_payload(self.payload)

    def test_refuses_symlink_on_efi(self):
        (self.efi / 'OC/link').symlink_to(self.efi / CONFIG)
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertIn('Unsafe', report['error'])

    def test_refuses_when_activation_guard_is_live_and_old(self):
        (self.system / inst.APP_REL / 'disabled').unlink()
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertIn('Activation guard', report['error'])
        self.assertEqual(inst.tree(self.efi), self.baseline)

    def test_reviewed_system_files_allow_install_without_disable_marker(self):
        (self.system / inst.APP_REL / 'disabled').unlink()
        for name in MANIFEST['system_before']:
            target = self.system / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.payload / 'system' / name, target)
        rc, report = self.run_cli(INSTALL)
        self.assertEqual(rc, 0, report)
        self.assertEqual(report['activation_guard'], 'reviewed-system-files-installed')

    def test_test_root_requires_sandboxed_system_root(self):
        result = subprocess.run([sys.executable, '-I', str(INSTALL), str(self.payload), '--efi-root', str(self.efi)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('test-only', json.loads(result.stdout)['error'])

    def test_apply_installs_exact_candidate_with_single_key_change(self):
        before_payload = inst.tree(self.payload / 'EFI')
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertTrue(report['installed'])
        self.assertFalse(report['activated'])
        self.assertFalse(report['rebooted'])
        self.assertEqual(inst.tree(self.efi), self.candidate)
        self.assertEqual(inst.tree(self.payload / 'EFI'), before_payload)
        # Exact single-key diff against the baseline bytes.
        original = plistlib.loads((self.payload / 'EFI' / RECOVERY).read_bytes())
        live_cfg = plistlib.loads((self.efi / CONFIG).read_bytes())
        expected = plistlib.loads((self.payload / 'EFI' / RECOVERY).read_bytes())
        expected['Kernel']['Add'][7]['BundlePath'] = BUNDLE
        self.assertEqual(live_cfg, expected)
        diffs = inst.leaf_diffs(original, live_cfg)
        self.assertEqual([(p, o, n) for p, o, n in diffs],
                         [(('Kernel', 'Add', 7, 'BundlePath'), 'Navi48Bringup-eight-0.0.665.kext', BUNDLE)])
        # Kext and RECOVERY are byte-identical to the payload.
        self.assertEqual(inst.tree(self.efi / 'OC/Kexts' / BUNDLE),
                         inst.tree(self.payload / 'EFI/OC/Kexts' / BUNDLE))
        self.assertEqual((self.efi / RECOVERY).read_bytes(), (self.payload / 'EFI' / RECOVERY).read_bytes())

    def test_backup_contains_full_baseline_and_manifest(self):
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual(inst.tree(backup / 'EFI'), self.baseline)
        self.assertEqual((backup / 'EFI' / CONFIG).read_bytes(), (self.payload / 'EFI' / RECOVERY).read_bytes())
        meta = json.loads((backup / 'backup-manifest.json').read_text())
        self.assertEqual(meta['baseline_config_sha256'], MANIFEST['baseline_config_sha256'])

    def test_second_apply_is_a_no_op(self):
        self.assertEqual(self.install()[0], 0)
        before = inst.tree(self.efi)
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertEqual(report['efi_state'], 'candidate')
        self.assertFalse(report['applied'])
        self.assertEqual(inst.tree(self.efi), before)
        self.assertEqual(len(self.backups()), 1)

    def test_failed_config_commit_rolls_back_everything(self):
        plan = inst.load_payload(self.payload)
        real_replace = os.replace
        target = (self.efi / CONFIG).resolve()
        calls = []

        def failing_replace(source, destination, *args, **kwargs):
            if Path(destination).resolve() == target and not calls:
                calls.append(destination)
                raise OSError('injected failure at config commit')
            return real_replace(source, destination, *args, **kwargs)

        with mock.patch.object(os, 'replace', side_effect=failing_replace):
            with self.assertRaisesRegex(OSError, 'injected'):
                inst.apply_install(plan, self.efi, self.backup_root)
        self.assertEqual(len(calls), 1)  # the injected failure hit the config commit exactly once
        self.assertEqual(inst.tree(self.efi), self.baseline)  # includes no temp files, no kext, no RECOVERY
        self.assertFalse((self.efi / 'OC/Kexts' / BUNDLE).exists())
        self.assertFalse((self.efi / RECOVERY).exists())
        self.assertEqual((self.efi / CONFIG).read_bytes(), (self.payload / 'EFI' / RECOVERY).read_bytes())

    def test_config_replacement_is_atomic_rename(self):
        before_inode = os.stat(self.efi / CONFIG).st_ino
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertNotEqual(os.stat(self.efi / CONFIG).st_ino, before_inode)
        leftovers = [p for p in self.efi.rglob('*') if p.name.startswith(inst.PENDING)]
        self.assertEqual(leftovers, [])

    def test_live_nvram_must_match_baseline_boot_args(self):
        plan = inst.load_payload(self.payload)
        good = subprocess.CompletedProcess([], 0, stdout='%s:boot-args\t%s\n' % (inst.BOOT_ARGS_GUID, plan['boot_args']), stderr='')
        bad = subprocess.CompletedProcess([], 0, stdout='%s:boot-args\t-v\n' % inst.BOOT_ARGS_GUID, stderr='')
        with mock.patch.object(inst.subprocess, 'run', return_value=good):
            inst.check_live_opencore(plan)
        with mock.patch.object(inst.subprocess, 'run', return_value=bad):
            with self.assertRaisesRegex(ValueError, 'did not boot the baseline'):
                inst.check_live_opencore(plan)

    def test_efi_discovery_requires_exactly_one_uuid_match(self):
        uuid = MANIFEST['efi_volume_uuid']
        infos = {'disk9s1': {'DeviceIdentifier': 'disk9s1', 'VolumeUUID': 'AAAAAAAA-0000-0000-0000-000000000000', 'FilesystemType': 'msdos'},
                 'disk2s1': {'DeviceIdentifier': 'disk2s1', 'VolumeUUID': uuid, 'FilesystemType': 'msdos'}}
        listing = {'AllDisksAndPartitions': [{'Partitions': [
            {'Content': 'EFI', 'DeviceIdentifier': 'disk9s1'}, {'Content': 'EFI', 'DeviceIdentifier': 'disk2s1'},
            {'Content': 'Apple_APFS', 'DeviceIdentifier': 'disk3s2'}]}]}

        def fake(args, **kwargs):
            if args[:3] == ['diskutil', 'list', '-plist']:
                return plistlib.dumps(listing)
            if args[:3] == ['diskutil', 'info', '-plist']:
                return plistlib.dumps(infos[args[-1]])
            raise AssertionError('unexpected command ' + str(args))

        with mock.patch.object(inst.subprocess, 'check_output', side_effect=fake):
            self.assertEqual(inst.find_efi_partition(uuid)['DeviceIdentifier'], 'disk2s1')
            infos['disk9s1']['VolumeUUID'] = uuid
            with self.assertRaisesRegex(ValueError, 'found 2'):
                inst.find_efi_partition(uuid)

    def test_mounted_by_us_flag_controls_unmount(self):
        with mock.patch.object(inst.subprocess, 'run') as run:
            inst.unmount({'identifier': 'disk2s1', 'mounted_by_us': False})
            run.assert_not_called()
            handle = {'identifier': 'disk2s1', 'mounted_by_us': True}
            inst.unmount(handle)
            run.assert_called_once()
            self.assertFalse(handle['mounted_by_us'])


class RestoreTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.install()[0], 0)
        self.candidate_bytes = (self.efi / CONFIG).read_bytes()
        self.baseline_bytes = (self.payload / 'EFI' / RECOVERY).read_bytes()

    def restore(self, *extra):
        return self.run_cli(RESTORE, *extra)

    def test_dry_run_writes_nothing(self):
        before = inst.tree(self.efi)
        rc, report = self.restore('--backup', str(self.backups()[0]))
        self.assertEqual(rc, 0, report)
        self.assertFalse(report['restored'])
        self.assertEqual(inst.tree(self.efi), before)

    def test_restore_from_backup_gives_exact_baseline_bytes_and_keeps_kext(self):
        rc, report = self.restore('--apply', '--backup', str(self.backups()[0]))
        self.assertEqual(rc, 0, report)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.baseline_bytes)
        expected = {**self.baseline, **{k: v for k, v in MANIFEST['add_files'].items()}}
        self.assertEqual(inst.tree(self.efi), expected)
        self.assertFalse(report['activated'])

    def test_restore_remove_kext_keeps_recovery(self):
        rc, report = self.restore('--apply', '--remove-kext', '--backup', str(self.backups()[0]))
        self.assertEqual(rc, 0, report)
        self.assertFalse((self.efi / 'OC/Kexts' / BUNDLE).exists())
        self.assertEqual(report['remaining_additions'], [RECOVERY])
        self.assertEqual((self.efi / RECOVERY).read_bytes(), self.baseline_bytes)
        self.assertEqual(inst.tree(self.efi), {**self.baseline, RECOVERY: MANIFEST['add_files'][RECOVERY]})

    def test_restore_from_recovery_when_backup_is_gone(self):
        shutil.rmtree(self.backup_root)
        rc, report = self.restore('--apply', '--from-recovery')
        self.assertEqual(rc, 0, report)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.baseline_bytes)

    def test_restore_refuses_bad_recovery_copy_without_writing(self):
        (self.efi / RECOVERY).write_bytes(self.baseline_bytes + b' ')
        before = inst.tree(self.efi)
        rc, report = self.restore('--apply', '--from-recovery')
        self.assertNotEqual(rc, 0)
        self.assertIn('does not match the baseline', report['error'])
        self.assertEqual(inst.tree(self.efi), before)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.candidate_bytes)

    def test_restore_refuses_backup_for_other_baseline(self):
        meta_path = self.backups()[0] / 'backup-manifest.json'
        meta = json.loads(meta_path.read_text())
        meta['baseline_config_sha256'] = '0' * 64
        meta_path.write_text(json.dumps(meta))
        rc, report = self.restore('--apply', '--backup', str(self.backups()[0]))
        self.assertNotEqual(rc, 0)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.candidate_bytes)

    def test_restore_is_idempotent(self):
        self.assertEqual(self.restore('--apply', '--backup', str(self.backups()[0]))[0], 0)
        rc, report = self.restore('--apply', '--remove-kext', '--backup', str(self.backups()[0]))
        self.assertEqual(rc, 0, report)
        self.assertEqual(report['changes'], ['OC/config.plist already equals the baseline; not rewritten',
                                             'removed OC/Kexts/' + BUNDLE])
        self.assertEqual(inst.tree(self.efi), {**self.baseline, RECOVERY: MANIFEST['add_files'][RECOVERY]})

    def test_restore_refuses_unexpected_addition(self):
        (self.efi / 'OC/stray.txt').write_text('x')
        rc, report = self.restore('--apply', '--from-recovery')
        self.assertNotEqual(rc, 0)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.candidate_bytes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
