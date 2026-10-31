#!/usr/bin/env python3
"""Restore the pre-install EFI config: OC/config.plist becomes the exact baseline bytes.

Source of the baseline bytes, which must hash to the payload's baseline_config_sha256:
  --backup DIR     a backup made by install-kernel-efi.py (default: newest under the backup root)
  --from-recovery  the RECOVERY copy kept on the EFI itself

The new kext is kept unless --remove-kext is given. The RECOVERY copies and OC/Tools/startup.nsh are never removed
(the startup script only copies the 665 configuration, which is the baseline bytes, so it is harmless to keep).
Default is a dry run. Never loads kexts, changes boot-args, touches the activation job or reboots.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('install_kernel_efi', HERE / 'install-kernel-efi.py')
inst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inst)
CONFIG = inst.CONFIG


def newest_backup(backup_root):
    found = sorted(p for p in Path(backup_root).glob('efi-backup-*') if p.is_dir() and not p.is_symlink())
    if not found:
        raise ValueError('No backup found under ' + str(backup_root) + '; use --from-recovery')
    return found[-1]


def backup_baseline_bytes(backup, plan):
    manifest_path = backup / 'backup-manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('Backup manifest missing: ' + str(backup))
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('baseline_config_sha256') != plan['baseline'][CONFIG]:
        raise ValueError('Backup was made for a different baseline')
    if inst.tree(backup / 'EFI') != plan['baseline']:
        raise ValueError('Backup EFI tree differs from the payload baseline')
    return (backup / 'EFI' / CONFIG).read_bytes()


def recovery_baseline_bytes(efi, plan):
    target = efi / plan['recovery']
    if target.is_symlink() or not target.is_file():
        raise ValueError('RECOVERY copy missing on the EFI: ' + plan['recovery'])
    data = target.read_bytes()
    if inst.sha_bytes(data) != plan['baseline'][CONFIG]:
        raise ValueError('RECOVERY copy on the EFI does not match the baseline')
    return data


def restore(plan, efi, source, remove_kext):
    live = inst.classify_restore(efi, plan)
    changes = []
    if live['config'] == 'candidate':
        inst.replace_file(efi / CONFIG, source)
        changes.append('restored OC/config.plist to the baseline bytes')
    else:
        changes.append('OC/config.plist already equals the baseline; not rewritten')
    if (efi / CONFIG).read_bytes() != plan['baseline_bytes']:
        raise ValueError('Restored config is not the exact baseline bytes')
    kext_rel = 'OC/Kexts/' + plan['bundle']
    if remove_kext and os.path.lexists(efi / kext_rel):
        shutil.rmtree(efi / kext_rel)
        changes.append('removed ' + kext_rel)
    final = inst.tree(efi)
    allowed = {k: v for k, v in plan['add'].items() if not (remove_kext and k.startswith(kext_rel + '/'))}
    extras = {k: v for k, v in final.items() if k not in plan['baseline']}
    if set(plan['baseline']) - set(final) or final[CONFIG] != plan['baseline'][CONFIG]:
        raise ValueError('Final EFI is missing original files or config is not the baseline')
    if any(k not in allowed or allowed[k] != v for k, v in extras.items()):
        raise ValueError('Final EFI has additions other than the expected kext/RECOVERY files')
    return changes, sorted(extras)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('payload', type=Path, help='the payload the EFI was installed from (defines the baseline)')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--backup', type=Path, help='backup directory from install-kernel-efi.py')
    source.add_argument('--from-recovery', action='store_true', help='use RECOVERY/ on the EFI')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true', help='perform the writes (default is a dry run)')
    group.add_argument('--dry-run', action='store_true', help='explicit default: checks and plan only')
    parser.add_argument('--remove-kext', action='store_true', help='also remove the new kext bundle')
    parser.add_argument('--system-root', type=Path, default=inst.DEFAULT_SYSTEM_ROOT)
    parser.add_argument('--backup-root', type=Path, help='default: SYSTEM_ROOT/' + inst.BACKUP_REL)
    parser.add_argument('--efi-root', type=Path, help='TEST ONLY: EFI directory instead of the mounted volume')
    parser.add_argument('--efi-uuid', help='target EFI partition VolumeUUID (default: the payload manifest efi_volume_uuid)')
    args = parser.parse_args(argv)
    system_root = args.system_root.absolute()
    backup_root = (args.backup_root or system_root / inst.BACKUP_REL).absolute()
    report = {'mode': 'apply' if args.apply else 'dry-run', 'remove_kext': args.remove_kext}
    handle = None
    try:
        inst.check_invocation(args)
        plan = inst.load_payload(args.payload)
        if args.from_recovery:
            report['source'] = 'EFI RECOVERY copy'
        else:
            backup = args.backup.absolute() if args.backup else newest_backup(backup_root)
            report['source'] = 'backup ' + str(backup)
        resolved = inst.resolve_efi(args, plan, writable=args.apply)
        handle = resolved['handle']
        efi = resolved['efi']
        report.update(efi=str(efi), discovery=resolved['discovery'])
        source_bytes = recovery_baseline_bytes(efi, plan) if args.from_recovery else backup_baseline_bytes(backup, plan)
        report['planned'] = ['restore OC/config.plist to baseline bytes (sha256 %s)' % plan['baseline'][CONFIG],
                             'remove the kext bundle' if args.remove_kext else 'keep the kext bundle',
                             'keep RECOVERY/ on the EFI', 'verify exact final inventory']
        if args.apply:
            changes, additions = restore(plan, efi, source_bytes, args.remove_kext)
            report.update(restored=True, activated=False, rebooted=False, changes=changes, remaining_additions=additions)
        else:
            report.update(restored=False, note='dry run: nothing was written')
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError, KeyError) as error:
        report['error'] = str(error)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    finally:
        inst.unmount(handle)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
