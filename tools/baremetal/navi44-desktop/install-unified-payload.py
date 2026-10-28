#!/usr/bin/env python3
"""Install the inspected candidate with rollback; never start services or reboot.

Default is read-only preflight. --apply additionally requires root and an already
writable, UUID-verified EFI. Mount/repair and boot-state reset are never implicit.
"""
import argparse
import ctypes
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('payload_check', Path(__file__).with_name('check-unified-payload.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

# FAT exposes synthetic ownership; set only after verifying the mounted volume.
VERIFIED_FAT_ROOT = None


def copy_file(source, destination):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Nonregular source: ' + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(source.stat().st_mode & 0o777)


def safe_parents(destination):
    # Refuse symlinked ancestors before creating/replacing root-owned files.
    for parent in (destination.parent, *destination.parent.parents):
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError('Unsafe destination ancestor: ' + str(parent))
        if os.geteuid() == 0 and parent.exists():
            metadata = parent.stat()
            synthetic_fat_owner = VERIFIED_FAT_ROOT is not None and (parent == VERIFIED_FAT_ROOT or parent.is_relative_to(VERIFIED_FAT_ROOT))
            if (metadata.st_uid != 0 and not synthetic_fat_owner) or metadata.st_mode & 0o022:
                raise ValueError('Untrusted root destination ancestor: ' + str(parent))


def atomic_file(destination, data, mode):
    safe_parents(destination)
    if destination.is_symlink():
        raise ValueError('Symlink target: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.navi44-pending-', dir=str(destination.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), 0, 0)
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def swap_directories(a, b):
    # Darwin SDK sys/stdio.h: RENAME_SWAP=2. No non-atomic rename fallback.
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.renamex_np
    function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    if function(os.fsencode(a), os.fsencode(b), 2):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


class Transaction:
    def __init__(self, payload, efi, system_root, manifest, plan, hook=lambda phase: None):
        self.payload, self.efi, self.root = payload, efi, system_root
        self.manifest, self.plan, self.hook = manifest, plan, hook
        self.changed = []
        self.metal_swapped = self.config_changed = False
        parent = self.root / check.APP
        safe_parents(parent / 'deployment')
        parent.mkdir(parents=True, exist_ok=True)
        required = sum((self.payload / p).stat().st_size for p in manifest['files']) * 3 + 32 * 1024 * 1024
        if shutil.disk_usage(parent).free < required:
            raise ValueError('Insufficient free space for private staging and rollback')
        self.work = Path(tempfile.mkdtemp(prefix='deployment-', dir=str(parent)))
        self.work.chmod(0o700)
        self.stage = self.work / 'staged'
        self.metal_backup = self.work / 'metal-exchange.bundle'
        self.journal('created')

    def journal(self, phase, error=None):
        data = {'schema': 1, 'phase': phase, 'efi': str(self.efi), 'metal_swapped': self.metal_swapped,
                'config_changed': self.config_changed, 'changed_system_files': list(self.changed),
                'metal_backup': str(self.metal_backup), 'error': error}
        atomic_file(self.work / 'journal.json', (json.dumps(data, indent=2) + '\n').encode(), 0o600)

    def point(self, phase):
        self.journal(phase)
        self.hook(phase)

    def stage_and_backup(self):
        for relative, expected in self.manifest['files'].items():
            check.relative(relative)
            source, target = self.payload / relative, self.stage / relative
            copy_file(source, target)
            if check.digest(target) != expected or (target.stat().st_mode & 0o777) != self.manifest['file_modes'][relative]:
                raise ValueError('Source changed during private staging: ' + relative)
        config = self.efi / 'OC/config.plist'
        if check.digest(config) != self.plan['baseline_config_sha256']:
            raise ValueError('EFI changed before backup')
        copy_file(config, self.work / 'original-config.plist')
        for relative, expected in self.manifest['baseline_system_files'].items():
            if relative.startswith(check.METAL + '/') or expected is None:
                continue
            source = self.root / relative
            if check.digest(source) != expected:
                raise ValueError('System target changed before backup: ' + relative)
            copy_file(source, self.work / 'original-system' / relative)
        # Keep immutable metadata for manual recovery, including absent old files.
        atomic_file(self.work / 'original-manifest.json', (json.dumps(self.manifest, indent=2) + '\n').encode(), 0o600)
        self.point('staged-and-backed-up')

    def write_system(self, relative):
        source, target = self.stage / 'system' / relative, self.root / relative
        expected_new = self.manifest['files']['system/' + relative]
        old = self.manifest['baseline_system_files'][relative]
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('System target type changed')
        actual = check.digest(target) if target.exists() else None
        if actual != old:
            raise ValueError('System target changed before commit: ' + relative)
        desired_mode = self.manifest['file_modes']['system/' + relative]
        if actual == expected_new and target.stat().st_mode & 0o777 == desired_mode:
            return
        atomic_file(target, source.read_bytes(), desired_mode)
        self.changed.append(relative)

    def rollback(self):
        failures = []
        if self.config_changed:
            try:
                path = self.efi / 'OC/config.plist'
                if check.digest(path) != self.plan['config_sha256']:
                    raise ValueError('Config changed externally; refusing overwrite')
                atomic_file(path, (self.work / 'original-config.plist').read_bytes(), 0o644)
                self.config_changed = False
            except Exception as error:
                failures.append('EFI: ' + str(error))
        for relative in reversed(self.changed):
            try:
                target = self.root / relative
                if check.digest(target) != self.manifest['files']['system/' + relative]:
                    raise ValueError('Target changed externally; refusing overwrite')
                old = self.manifest['baseline_system_files'][relative]
                if old is None:
                    target.unlink()
                else:
                    source = self.work / 'original-system' / relative
                    if check.digest(source) != old:
                        raise ValueError('Backup digest mismatch')
                    atomic_file(target, source.read_bytes(), self.manifest['baseline_system_modes'][relative])
            except Exception as error:
                failures.append(relative + ': ' + str(error))
        if self.metal_swapped:
            try:
                target = self.root / check.METAL
                expected = {p[len(check.METAL) + 1:]: sha for p, sha in self.system.items() if p.startswith(check.METAL + '/')}
                if check.hashes(target) != expected or check.hashes(self.metal_backup) != self.manifest['working_metal_files']:
                    raise ValueError('Metal target/backup changed; refusing swap')
                swap_directories(target, self.metal_backup)
                self.metal_swapped = False
            except Exception as error:
                failures.append('Metal: ' + str(error))
        self.journal('rollback-failed' if failures else 'rolled-back', '; '.join(failures) or None)
        if failures:
            raise RuntimeError('Rollback requires review: ' + '; '.join(failures))
        # New EFI files intentionally remain unreferenced. Old boot paths were
        # never replaced; deleting additions during failure would add risk.

    def run(self):
        self.system = {p[len('system/'):]: sha for p, sha in self.manifest['files'].items() if p.startswith('system/')}
        try:
            self.stage_and_backup()
            for relative, expected in self.plan['add_files'].items():
                target = self.efi / relative
                safe_parents(target)
                if target.exists():
                    if target.is_symlink() or not target.is_file() or check.digest(target) != expected:
                        raise ValueError('EFI addition conflicts')
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation, not an overwrite of an old boot path.
                with target.open('xb') as stream:
                    stream.write((self.stage / 'EFI' / relative).read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                if check.digest(target) != expected:
                    raise ValueError('EFI copy verification failed')
            self.point('efi-additions-verified')
            metal = self.root / check.METAL
            if check.hashes(metal) != self.manifest['working_metal_files']:
                raise ValueError('Working Metal changed before swap')
            (self.stage / 'system' / check.METAL).rename(self.metal_backup)
            swap_directories(metal, self.metal_backup)
            self.metal_swapped = True
            self.point('metal-swapped')
            for relative in self.system:
                if not relative.startswith(check.METAL + '/') and relative != check.BOOT:
                    self.write_system(relative)
            self.point('system-files-written')
            config = self.efi / 'OC/config.plist'
            if check.digest(config) != self.plan['baseline_config_sha256']:
                raise ValueError('EFI changed before config commit')
            atomic_file(config, (self.stage / 'EFI/OC/config.plist').read_bytes(), 0o644)
            self.config_changed = True
            self.point('config-written')
            self.write_system(check.BOOT)  # Job becomes available only after all components/config.
            self.point('boot-job-written')
            for relative, expected in self.system.items():
                target = self.root / relative
                if check.digest(target) != expected or target.stat().st_mode & 0o777 != self.manifest['file_modes']['system/' + relative]:
                    raise ValueError('Final system verification failed')
            for relative, expected in self.plan['all_files'].items():
                if check.digest(self.efi / relative) != expected:
                    raise ValueError('Final EFI verification failed')
            self.point('installed-not-activated')
            return self.work
        except Exception as error:
            try:
                self.rollback()
            except Exception as rollback_error:
                raise RuntimeError(str(error) + '; ' + str(rollback_error)) from error
            raise


def verify_fat_mount(efi, expected_uuid):
    import subprocess
    import plistlib
    global VERIFIED_FAT_ROOT
    VERIFIED_FAT_ROOT = None
    mount = efi.parent.absolute()
    volume = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(mount)]))
    if (mount.is_symlink() or str(mount) != volume.get('MountPoint') or
            volume.get('VolumeUUID', '').upper() != expected_uuid.upper() or
            volume.get('FilesystemType') != 'msdos' or not volume.get('WritableVolume')):
        raise ValueError('Expected writable FAT EFI mount unavailable')
    VERIFIED_FAT_ROOT = mount


def restore_backup(work, apply=False):
    """Restore only a completed, unactivated transaction in its original boot."""
    work = work.absolute()
    safe_parents(work / 'journal.json')
    if work.is_symlink() or work.stat().st_mode & 0o077:
        raise ValueError('Backup must be a private directory')
    for name in ('journal.json', 'original-manifest.json'):
        path = work / name
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('Unsafe backup metadata')
        if os.geteuid() == 0 and path.stat().st_uid != 0:
            raise ValueError('Backup metadata not root-owned')
    state = json.loads((work / 'journal.json').read_text())
    manifest = json.loads((work / 'original-manifest.json').read_text())
    if state['phase'] != 'installed-not-activated':
        raise ValueError('Interrupted/previously restored transaction requires manual review')
    import subprocess
    boot = subprocess.check_output(['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip()
    if boot != manifest['prepared_boot_uuid']:
        raise ValueError('Backup restoration after a reboot requires manual review')
    for name in ('boot-state.json', 'disabled'):
        path = Path('/') / check.APP / name
        if path.exists() or path.is_symlink():
            raise ValueError('Activation/state appeared; refusing automatic restoration')
    system = {p[7:]: sha for p, sha in manifest['files'].items() if p.startswith('system/')}
    if any(not check.system_allowed(p) for p in system) or any(p not in system for p in state['changed_system_files']):
        raise ValueError('Unexpected backup write targets')
    efi = Path(state['efi'])
    # Recheck the actual volume UUID before changing even a single EFI file.
    import plistlib
    volume = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(efi.parent)]))
    if volume.get('VolumeUUID', '').upper() != manifest['efi_volume_uuid'] or not volume.get('WritableVolume'):
        raise ValueError('Original writable EFI volume unavailable')
    plan = json.loads((work / 'staged/efi-install-plan.json').read_text())
    if check.digest(work / 'original-config.plist') != plan['baseline_config_sha256']:
        raise ValueError('Original EFI backup digest differs')
    if not apply:
        return {'restore_preflight': True, 'mutations': 0, 'backup': str(work)}
    if os.geteuid() != 0:
        raise ValueError('Restore requires root')
    verify_fat_mount(efi, manifest['efi_volume_uuid'])
    t = Transaction.__new__(Transaction)
    t.work, t.efi, t.root = work, efi, Path('/')
    t.manifest, t.plan, t.system = manifest, plan, system
    t.changed = state['changed_system_files']
    t.config_changed, t.metal_swapped = state['config_changed'], state['metal_swapped']
    t.metal_backup = work / 'metal-exchange.bundle'
    t.rollback()
    return {'restored': True, 'activated': False, 'rebooted': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('payload', type=Path, nargs='?')
    p.add_argument('--efi', type=Path, default=Path('/Volumes/OCBOOT/EFI'))
    p.add_argument('--restore-backup', type=Path)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    if a.restore_backup:
        if a.payload:
            p.error('Choose payload installation OR backup restoration')
        print(json.dumps(restore_backup(a.restore_backup, a.apply), indent=2))
    else:
        if not a.payload:
            p.error('A payload is required')
        report = check.preflight(a.payload, a.efi)
        if not a.apply:
            print(json.dumps(report, indent=2))
        else:
            if os.geteuid() != 0 or not report['efi_writable_now']:
                raise SystemExit('Apply requires root and an already writable verified EFI; nothing installed')
            manifest, plan, _ = check.verify_payload(a.payload)
            verify_fat_mount(a.efi, manifest['efi_volume_uuid'])
            transaction = Transaction(a.payload.resolve(), a.efi.resolve(), Path('/'), manifest, plan)
            backup = transaction.run()
            print(json.dumps({'installed': True, 'activated': False, 'rebooted': False, 'backup': str(backup)}, indent=2))
