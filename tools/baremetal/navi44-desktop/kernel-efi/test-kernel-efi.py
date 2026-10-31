#!/usr/bin/env python3
"""Offline tests for install-kernel-efi.py, restore-kernel-efi.py and the recovery startup script.

Every test works in a temporary sandbox: a fake EFI built from kernel-payload-v3's baseline, a temporary system
root and a temporary backup root. No real EFI, /Library or diskutil call is made. The payload directories are only read.
"""
import argparse
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PAYLOAD_SRC = REPO / 'research/builds/macos-20261031/production/kernel-payload-v3'
PAYLOAD_V2 = REPO / 'research/builds/macos-20261031/production/kernel-payload-v2'
INSTALL = HERE / 'install-kernel-efi.py'
RESTORE = HERE / 'restore-kernel-efi.py'
STARTUP = HERE / 'startup.nsh'
LOCAL_UUID = '97C4AA5C-B87D-3786-B1B3-F84A76840DEF'   # CachyOS EFI partition, v3 default
STICK_UUID = '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3'   # OCBOOT stick, only with --efi-uuid
CACHYOS_FILES = {
    'cachyos/grubx64.efi': b'cachyos grub loader',
    'cachyos/rx9060xt-vfio-test.env': b'VFIO_TEST=1\n',
    'boot/bootx64.efi': b'cachyos fallback loader',
    'navi44-grub/run-tahoe.sh': b'#!/bin/sh\necho grub\n',
    'System Volume Information/WPSettings.dat': b'svi',
}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inst = load('install_kernel_efi', INSTALL)
rest = load('restore_kernel_efi', RESTORE)
CONFIG = inst.CONFIG
MANIFEST = json.loads((PAYLOAD_SRC / 'manifest.json').read_text())
BUNDLE = 'Navi48Bringup-contexts-0.0.667.kext'
RECOVERY = 'RECOVERY/pre-contexts-667-config.plist'
FUNZIONANTE = 'RECOVERY/funzionante-665.plist'
STARTUP_EFI = 'OC/Tools/startup.nsh'
GUARD = 'Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'
NON_KEXT_ADDITIONS = sorted(k for k in MANIFEST['add_files'] if not k.startswith('OC/Kexts/'))


def slot(data, path):
    parts = path.split('/')
    node = data
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    return node, (int(last) if isinstance(node, list) else last)


def with_listed_edits(cfg):
    """The baseline configuration with every edit listed in the payload manifest applied."""
    for edit in MANIFEST['config_edits']:
        container, key = slot(cfg, edit['path'])
        assert container[key] == edit['old'], edit['path']
        container[key] = edit['new']
    return cfg


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
        for name in NON_KEXT_ADDITIONS:
            (self.efi / name).unlink()
        (self.efi / CONFIG).write_bytes((self.payload / 'EFI' / RECOVERY).read_bytes())
        self.baseline = MANIFEST['baseline_efi_files']
        self.candidate = MANIFEST['candidate_efi_files']
        self.assertEqual(inst.tree(self.efi), self.baseline)
        self.add_cachyos_volume()
        self.foreign_before = self.foreign_inventory()
        self.system = self.root / 'system'
        (self.system / inst.APP_REL).mkdir(parents=True)
        self.backup_root = self.system / inst.BACKUP_REL
        self.disable_activation()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def add_cachyos_volume(self):
        """The local ESP as it is: CachyOS files and scripts beside OC/ and RECOVERY/. No BOOT/ directory."""
        for name, data in CACHYOS_FILES.items():
            target = self.efi / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def top_names(self):
        return sorted(p.name for p in self.efi.iterdir())

    def foreign_inventory(self):
        """Every regular file on the volume outside OC/ and RECOVERY/: must never change."""
        return {p.relative_to(self.efi).as_posix(): inst.sha(p) for p in sorted(self.efi.rglob('*'))
                if p.is_file() and not p.relative_to(self.efi).as_posix().startswith(inst.SCOPE_PREFIXES)}

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

    def reseal_config(self, cfg):
        """Write a changed candidate config into the payload and its manifest (hashes only, edits untouched)."""
        data = plistlib.dumps(cfg, sort_keys=False)
        (self.payload / 'EFI' / CONFIG).write_bytes(data)
        m = json.loads((self.payload / 'manifest.json').read_text())
        m['candidate_efi_files'][CONFIG] = inst.sha_bytes(data)
        m['candidate_config_sha256'] = inst.sha_bytes(data)
        (self.payload / 'manifest.json').write_text(json.dumps(m))

    def candidate_cfg(self):
        return plistlib.loads((self.payload / 'EFI' / CONFIG).read_bytes())

    def baseline_cfg(self):
        return plistlib.loads((self.payload / 'EFI' / RECOVERY).read_bytes())

    def add_payload_file(self, name, data):
        """Add an unlisted file to the payload (inventory and manifest updated consistently)."""
        target = self.payload / 'EFI' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        m = json.loads((self.payload / 'manifest.json').read_text())
        m['candidate_efi_files'][name] = inst.sha_bytes(data)
        m['add_files'][name] = inst.sha_bytes(data)
        (self.payload / 'manifest.json').write_text(json.dumps(m))


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

    def test_refuses_config_change_beyond_listed_edits(self):
        # A manifest-consistent payload whose config changes a key that the manifest does not list.
        cfg = with_listed_edits(self.baseline_cfg())
        cfg['Misc']['Boot']['Timeout'] = 9
        self.reseal_config(cfg)
        with self.assertRaisesRegex(ValueError, 'differs from the listed edits'):
            inst.load_payload(self.payload)

    def test_refuses_listed_edit_that_is_not_applied(self):
        # The manifest lists the Tools edits, but the candidate config does not carry them.
        cfg = self.candidate_cfg()
        cfg['Misc']['Tools'][0]['Name'] = 'Ripristino EFI (UEFI Shell)'
        self.reseal_config(cfg)
        with self.assertRaisesRegex(ValueError, 'differs from the listed edits'):
            inst.load_payload(self.payload)

    def test_refuses_poll_apple_hotkeys_flip_unless_listed(self):
        # The former PollAppleHotKeys special case is gone: the flip is an ordinary unlisted edit and is refused.
        cfg = with_listed_edits(self.baseline_cfg())
        cfg['Misc']['Boot']['PollAppleHotKeys'] = True
        self.reseal_config(cfg)
        with self.assertRaisesRegex(ValueError, 'differs from the listed edits'):
            inst.load_payload(self.payload)

    def test_refuses_manifest_without_listed_edits(self):
        # kernel-payload-v2 (the 666 payload) predates the explicit list and is not installable by this installer.
        with self.assertRaises(ValueError):
            inst.load_payload(PAYLOAD_V2)

    def test_refuses_unlisted_extra_file_in_payload(self):
        self.add_payload_file('OC/Tools/other.nsh', b'echo x\r\n')
        with self.assertRaisesRegex(ValueError, 'Unexpected EFI addition'):
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

    def test_cachyos_files_present_and_untouched_by_install(self):
        self.assertEqual(self.foreign_inventory(), self.foreign_before)
        self.assertEqual(sorted(CACHYOS_FILES), sorted(k for k in self.foreign_before))
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertEqual(self.foreign_inventory(), self.foreign_before)
        for name, data in CACHYOS_FILES.items():
            self.assertEqual((self.efi / name).read_bytes(), data, name)

    def test_boot_directory_is_never_written(self):
        # FAT is case-insensitive: BOOT/ and boot/ are one directory here, so compare the top-level names.
        names = self.top_names()
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertEqual(self.top_names(), names)
        self.assertEqual((self.efi / 'boot/bootx64.efi').read_bytes(), CACHYOS_FILES['boot/bootx64.efi'])

    def test_stick_style_boot_directory_is_ignored(self):
        # The stick layout has BOOT/. It is outside the scope: present or not, it is neither read into the plan nor written.
        shutil.rmtree(self.efi / 'boot')          # on FAT, BOOT and boot are one directory
        (self.efi / 'BOOT').mkdir()
        (self.efi / 'BOOT' / 'BOOTx64.efi').write_bytes(b'stick loader')
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertEqual((self.efi / 'BOOT' / 'BOOTx64.efi').read_bytes(), b'stick loader')
        self.assertEqual(inst.tree(self.efi), self.candidate_scoped())

    def candidate_scoped(self):
        return {k: v for k, v in self.candidate.items() if k.startswith(inst.SCOPE_PREFIXES)}

    def test_extra_files_outside_scope_are_ignored(self):
        (self.efi / 'stray.txt').write_text('x')
        (self.efi / 'navi44-grub' / 'extra.sh').write_text('echo extra')
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertEqual((self.efi / 'stray.txt').read_text(), 'x')
        self.assertEqual((self.efi / 'navi44-grub' / 'extra.sh').read_text(), 'echo extra')

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'needs a non-root user to make a directory unreadable')
    def test_unreadable_system_volume_information_is_never_read(self):
        svi = self.efi / 'System Volume Information'
        svi.chmod(0)
        try:
            rc, report = self.install()
            self.assertEqual(rc, 0, report)
        finally:
            svi.chmod(0o755)

    def test_target_uuid_defaults_to_local_partition_and_flag_overrides(self):
        plan = inst.load_payload(self.payload)
        self.assertEqual(plan['uuid'], LOCAL_UUID)
        seen = []

        def fake_mount(uuid, writable):
            seen.append(uuid)
            raise RuntimeError('stop before mounting')

        with mock.patch.object(inst, 'mount_efi', side_effect=fake_mount):
            for efi_uuid in (None, STICK_UUID):
                args = argparse.Namespace(efi_root=None, efi_uuid=efi_uuid)
                with self.assertRaises(RuntimeError):
                    inst.resolve_efi(args, plan, writable=False)
            with self.assertRaisesRegex(ValueError, 'Not a volume UUID'):
                inst.resolve_efi(argparse.Namespace(efi_root=None, efi_uuid='nope'), plan, writable=False)
        self.assertEqual(seen, [LOCAL_UUID, STICK_UUID])

    def test_payload_listing_boot_files_is_refused(self):
        m = json.loads((self.payload / 'manifest.json').read_text())
        m['baseline_efi_files']['BOOT/BOOTx64.efi'] = '0' * 64
        (self.payload / 'manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'outside the OC/RECOVERY scope'):
            inst.load_payload(self.payload)

    def test_payload_lists_three_edits_and_three_extra_files(self):
        plan = inst.load_payload(self.payload)
        self.assertEqual([e[0] for e in plan['config_edits']],
                         ['Kernel/Add/7/BundlePath', 'Misc/Tools/0/Name', 'Misc/Tools/0/Comment'])
        self.assertEqual(sorted(plan['extra_bytes']), sorted([FUNZIONANTE, RECOVERY, STARTUP_EFI]))
        self.assertEqual(plan['extra_bytes'][FUNZIONANTE], (self.payload / 'EFI' / RECOVERY).read_bytes())

    def test_apply_installs_exact_candidate_with_listed_edits(self):
        before_payload = inst.tree(self.payload / 'EFI')
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertTrue(report['installed'])
        self.assertFalse(report['activated'])
        self.assertFalse(report['rebooted'])
        self.assertEqual(inst.tree(self.efi), self.candidate)
        self.assertEqual(inst.tree(self.payload / 'EFI'), before_payload)
        # The live config is exactly the baseline with the three listed edits.
        live_cfg = plistlib.loads((self.efi / CONFIG).read_bytes())
        self.assertEqual(live_cfg, with_listed_edits(plistlib.loads((self.payload / 'EFI' / RECOVERY).read_bytes())))
        original = plistlib.loads((self.payload / 'EFI' / RECOVERY).read_bytes())
        diffs = [(('/'.join(map(str, p))), o, n) for p, o, n in inst.leaf_diffs(original, live_cfg)]
        self.assertEqual(sorted(diffs), sorted((e['path'], e['old'], e['new']) for e in MANIFEST['config_edits']))
        # Kext and the extra files are byte-identical to the payload.
        self.assertEqual(inst.full_tree(self.efi / 'OC/Kexts' / BUNDLE), inst.full_tree(self.payload / 'EFI/OC/Kexts' / BUNDLE))
        for name in NON_KEXT_ADDITIONS:
            self.assertEqual((self.efi / name).read_bytes(), (self.payload / 'EFI' / name).read_bytes(), name)

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
        self.assertEqual(inst.tree(self.efi), self.baseline)  # no temp files, kext or extra files
        self.assertFalse((self.efi / 'OC/Kexts' / BUNDLE).exists())
        for name in NON_KEXT_ADDITIONS:
            self.assertFalse((self.efi / name).exists(), name)
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

    def test_restore_from_backup_gives_exact_baseline_bytes_and_keeps_additions(self):
        rc, report = self.restore('--apply', '--backup', str(self.backups()[0]))
        self.assertEqual(rc, 0, report)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.baseline_bytes)
        expected = {**self.baseline, **MANIFEST['add_files']}
        self.assertEqual(inst.tree(self.efi), expected)
        self.assertFalse(report['activated'])

    def test_restore_remove_kext_keeps_recovery_files(self):
        rc, report = self.restore('--apply', '--remove-kext', '--backup', str(self.backups()[0]))
        self.assertEqual(rc, 0, report)
        self.assertFalse((self.efi / 'OC/Kexts' / BUNDLE).exists())
        self.assertEqual(report['remaining_additions'], NON_KEXT_ADDITIONS)
        self.assertEqual((self.efi / RECOVERY).read_bytes(), self.baseline_bytes)
        self.assertEqual(inst.tree(self.efi), {**self.baseline, **{k: MANIFEST['add_files'][k] for k in NON_KEXT_ADDITIONS}})

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
        self.assertEqual(inst.tree(self.efi), {**self.baseline, **{k: MANIFEST['add_files'][k] for k in NON_KEXT_ADDITIONS}})

    def test_restore_leaves_cachyos_files_untouched(self):
        names = self.top_names()
        rc, report = self.restore('--apply', '--from-recovery')
        self.assertEqual(rc, 0, report)
        self.assertEqual(self.foreign_inventory(), self.foreign_before)
        self.assertEqual(self.top_names(), names)

    def test_restore_refuses_unexpected_addition(self):
        (self.efi / 'OC/stray.txt').write_text('x')
        rc, report = self.restore('--apply', '--from-recovery')
        self.assertNotEqual(rc, 0)
        self.assertEqual((self.efi / CONFIG).read_bytes(), self.candidate_bytes)


class StartupScript(unittest.TestCase):
    """Offline lint of OC/Tools/startup.nsh (UEFI Shell 2.x script). Structure only; it is not run."""
    ALLOWED = {'echo', 'for', 'endfor', 'if', 'endif', 'else', 'cp', 'stall', 'reset'}
    FS = 'fs0 fs1 fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9'
    CONDITIONS = {
        r'if exist %a:\EFI\RECOVERY\funzionante-665.plist then',
        r'if exist %a:\EFI\OC\Tools\OpenShell.efi then',
        r'if exist %a:\EFI\OC\config.plist then',
    }

    @classmethod
    def setUpClass(cls):
        cls.raw = STARTUP.read_bytes()
        cls.lines = cls.raw.decode('ascii').split('\r\n')[:-1]

    def test_same_file_in_source_and_payload(self):
        payload_copy = PAYLOAD_SRC / 'EFI' / STARTUP_EFI
        self.assertEqual(payload_copy.read_bytes(), self.raw)
        self.assertEqual(inst.sha_bytes(self.raw), MANIFEST['candidate_efi_files'][STARTUP_EFI])

    def test_crlf_and_ascii_only(self):
        self.raw.decode('ascii')
        self.assertEqual(self.raw.count(b'\n'), self.raw.count(b'\r\n'))
        self.assertTrue(self.raw.endswith(b'\r\n'))

    def test_only_allowed_commands(self):
        for line in self.lines:
            self.assertTrue(line, 'empty line')
            first = line.split()[0]
            self.assertIn(first, self.ALLOWED, line)

    def test_for_and_if_blocks_are_balanced_and_nested(self):
        stack = []
        for line in self.lines:
            words = line.split()
            if words[0] == 'for':
                self.assertEqual(line, 'for %a in ' + self.FS)
                stack.append('for')
            elif words[0] == 'endfor':
                self.assertEqual(stack.pop(), 'for', line)
            elif words[0] == 'if':
                self.assertIn(line, self.CONDITIONS, line)
                stack.append('if')
            elif words[0] == 'endif':
                self.assertEqual(stack.pop(), 'if', line)
            elif words[0] == 'else':
                self.assertEqual(stack[-1:], ['if'], line)
        self.assertEqual(stack, [])

    def test_copy_stall_reset_sit_inside_three_ifs_in_the_loop(self):
        stack = []
        seen = {}
        for line in self.lines:
            words = line.split()
            if words[0] in ('for', 'if'):
                stack.append(words[0])
            elif words[0] in ('endfor', 'endif'):
                stack.pop()
            elif words[0] in ('cp', 'stall', 'reset'):
                seen[words[0]] = list(stack)
        expected = ['for', 'if', 'if', 'if']
        self.assertEqual(seen, {'cp': expected, 'stall': expected, 'reset': expected})

    def test_exact_copy_and_timing_lines(self):
        self.assertEqual(sum(1 for l in self.lines if l.startswith('cp ')), 1)
        self.assertIn(r'cp -q %a:\EFI\RECOVERY\funzionante-665.plist %a:\EFI\OC\config.plist', self.lines)
        self.assertIn('stall 5000000', self.lines)
        self.assertEqual(sum(1 for l in self.lines if l == 'reset'), 1)
        self.assertLess(self.lines.index('stall 5000000'), self.lines.index('reset'))

    def test_manual_fallback_follows_the_loop(self):
        end = self.lines.index('endfor')
        after = self.lines[end + 1:]
        self.assertTrue(after and all(line.startswith('echo') for line in after))
        text = '\n'.join(after)
        for needed in ('map -r', r'ls \EFI\RECOVERY', r'cp -q \EFI\RECOVERY\funzionante-665.plist \EFI\OC\config.plist', 'reset'):
            self.assertIn(needed, text)

    def test_percent_only_as_loop_variable(self):
        for line in self.lines:
            self.assertEqual(re.sub(r'%a', '', line).count('%'), 0, line)


# 0.0.668 (payload v4): its baseline is payload v3's CANDIDATE, the EFI installed now (0.0.667 kext and configuration, recovery files).
PAYLOAD_V4 = REPO / 'research/builds/macos-20261031/production/kernel-payload-v4'
BUNDLE_668 = 'Navi48Bringup-contexts-0.0.668.kext'
BUNDLE_667 = BUNDLE
RECOVERY_668 = 'RECOVERY/pre-contexts-668-config.plist'


class V4Sandbox(Sandbox):
    """The live EFI is payload v3's candidate tree (the installed 0.0.667 state); the payload is payload v4."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='kernel-efi-v4-test-'))
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        shutil.copyfile(PAYLOAD_V4 / 'manifest.json', self.payload / 'manifest.json')
        shutil.copytree(PAYLOAD_V4 / 'EFI', self.payload / 'EFI', symlinks=False)
        shutil.copytree(PAYLOAD_V4 / 'system', self.payload / 'system', symlinks=False)
        self.efi = self.root / 'efi'
        shutil.copytree(PAYLOAD_SRC / 'EFI', self.efi, symlinks=False)
        self.manifest = json.loads((PAYLOAD_V4 / 'manifest.json').read_text())
        self.baseline = self.manifest['baseline_efi_files']
        self.candidate = self.manifest['candidate_efi_files']
        self.assertEqual(inst.tree(self.efi), self.baseline)
        self.add_cachyos_volume()
        self.foreign_before = self.foreign_inventory()
        self.system = self.root / 'system'
        (self.system / inst.APP_REL).mkdir(parents=True)
        self.backup_root = self.system / inst.BACKUP_REL
        self.disable_activation()


class V4InstallTests(V4Sandbox):
    def test_plan_swaps_the_installed_667_kext_for_668_with_one_config_edit(self):
        plan = inst.load_payload(self.payload)
        self.assertEqual(plan['bundle'], BUNDLE_668)
        self.assertEqual(plan['config_edits'], [('Kernel/Add/7/BundlePath', BUNDLE_667, BUNDLE_668)])
        self.assertEqual(plan['recovery'], RECOVERY_668)
        self.assertEqual(sorted(plan['add']), sorted(set(self.candidate) - set(self.baseline)))
        self.assertTrue(all(name.startswith(('OC/Kexts/' + BUNDLE_668 + '/', 'RECOVERY/')) for name in plan['add']))

    def test_dry_run_plans_from_the_installed_667_state_and_writes_nothing(self):
        before_efi, before_payload = self.snapshot()
        rc, report = self.run_cli(INSTALL)
        self.assertEqual(rc, 0, report)
        self.assertEqual(report['efi_state'], 'baseline')
        self.assertFalse(report['applied'])
        self.assertTrue(any(BUNDLE_668 in line for line in report['planned']), report['planned'])
        self.assertEqual(inst.tree(self.efi), before_efi)
        self.assertEqual(inst.tree(self.payload / 'EFI'), before_payload)
        self.assertEqual(self.backups(), [])

    def test_apply_installs_668_and_keeps_667_for_rollback(self):
        rc, report = self.install()
        self.assertEqual(rc, 0, report)
        self.assertEqual(inst.tree(self.efi), self.candidate)
        self.assertTrue((self.efi / 'OC/Kexts' / BUNDLE_667).is_dir())
        cfg = plistlib.loads((self.efi / CONFIG).read_bytes())
        self.assertEqual(cfg['Kernel']['Add'][7]['BundlePath'], BUNDLE_668)
        self.assertEqual(cfg['Misc']['Tools'][0]['Name'], 'Ripristino EFI: driver funzionanti (665)')
        self.assertEqual(self.foreign_inventory(), self.foreign_before)
        self.assertEqual(len(self.backups()), 1)

    def test_refuses_the_pre_667_configuration_as_the_live_state(self):
        # the 665 recovery configuration is neither the 667 state (the v4 baseline) nor the 668 candidate
        (self.efi / CONFIG).write_bytes((self.efi / FUNZIONANTE).read_bytes())
        before = inst.tree(self.efi)
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertIn('neither the baseline nor the candidate', report['error'])
        self.assertEqual(inst.tree(self.efi), before)
        self.assertEqual(self.backups(), [])

    def test_refuses_a_v4_payload_whose_668_kext_is_not_the_reviewed_binary(self):
        binary = self.payload / 'EFI/OC/Kexts' / BUNDLE_668 / 'Contents/MacOS/Navi48Bringup'
        binary.write_bytes(binary.read_bytes() + b'\0')
        rc, report = self.install()
        self.assertNotEqual(rc, 0)
        self.assertEqual(inst.tree(self.efi), self.baseline)
        self.assertEqual(self.backups(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
