#!/usr/bin/env python3
"""Install an EFI kernel payload: copy the new kext, keep the pre-install config, swap one key.

Default is a dry run: every check runs and the planned actions are printed, nothing is written.
--apply performs the writes and requires root unless the test-only --efi-root is given.

EFI discovery: the unique EFI-type partition whose VolumeUUID equals the payload manifest's
efi_volume_uuid. Its volume is mounted only if it was not already mounted, and it is unmounted
again only in that case. The live NVRAM boot-args must equal the baseline config's NVRAM/Add
value, which shows that an OpenCore run with the baseline config booted this session.

Never loads or unloads kexts, starts services, changes boot-args or reboots. The activation
guard must be disabled (APP/disabled) or already be the reviewed system files; see RECOVERY.md.
"""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

DEFAULT_SYSTEM_ROOT = Path('/')
APP_REL = 'Library/Application Support/Navi44/accelerated-trial'
BACKUP_REL = 'Library/Application Support/Navi44'
BOOT_ARGS_GUID = '7C436110-AB2A-4BBB-A880-FE41995C9F82'
CONFIG = 'OC/config.plist'
PENDING = '.navi44-pending-'
MISSING = '<missing>'


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def safe_rel(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and p.as_posix() == name


def tree(root):
    """Exact inventory {relative path: sha256} of regular files; symlinks or special files refuse."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Missing or unsafe EFI tree: ' + str(root))
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ValueError('Unsafe entry (symlink or special file): ' + str(p))
        if p.is_file():
            result[p.relative_to(root).as_posix()] = sha(p)
    return result


def leaf_diffs(a, b, path=()):
    """Every differing leaf between two plist values, as (path, old, new)."""
    if type(a) is not type(b):
        return [(path, a, b)]
    if isinstance(a, dict):
        out = []
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                out.append((path + (key,), a.get(key, MISSING), b.get(key, MISSING)))
            else:
                out += leaf_diffs(a[key], b[key], path + (key,))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [(path, 'list of %d' % len(a), 'list of %d' % len(b))]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += leaf_diffs(x, y, path + (i,))
        return out
    return [] if a == b else [(path, a, b)]


def describe_mismatch(live, expected):
    missing = sorted(set(expected) - set(live))
    extra = sorted(set(live) - set(expected))
    changed = sorted(k for k in set(live) & set(expected) if live[k] != expected[k])
    return 'missing=%s extra=%s changed=%s' % (missing[:10], extra[:10], changed[:10])


def load_payload(payload):
    """Validate a prepared payload directory without touching any EFI. Returns a plan dict."""
    payload = Path(payload).absolute()
    if payload.is_symlink() or not payload.is_dir():
        raise ValueError('Payload must be a real directory: ' + str(payload))
    m = json.loads((payload / 'manifest.json').read_text())
    needed = ('schema', 'baseline_efi_files', 'candidate_efi_files', 'add_files',
              'baseline_config_sha256', 'candidate_config_sha256', 'efi_volume_uuid')
    if any(key not in m for key in needed) or m['schema'] != 1:
        raise ValueError('Unsupported payload manifest')
    base, cand, add = m['baseline_efi_files'], m['candidate_efi_files'], m['add_files']
    for name in set(base) | set(cand) | set(add):
        if not safe_rel(name):
            raise ValueError('Unsafe payload path: ' + name)
    efi_payload = payload / 'EFI'
    if tree(efi_payload) != cand:
        raise ValueError('Payload EFI tree differs from its candidate inventory')
    if base.get(CONFIG) != m['baseline_config_sha256'] or cand.get(CONFIG) != m['candidate_config_sha256']:
        raise ValueError('Config hashes differ from the manifest')
    if set(cand) - set(base) != set(add) or set(base) - set(cand):
        raise ValueError('Payload is not the baseline plus its declared additions')
    if any(name != CONFIG and cand[name] != digest for name, digest in base.items()):
        raise ValueError('Payload changes an original EFI file other than config.plist')
    if any(add[name] != cand[name] for name in add):
        raise ValueError('Declared additions differ from payload files')

    recovery = sorted(k for k in add if k.startswith('RECOVERY/'))
    kexts = sorted(k for k in add if k.startswith('OC/Kexts/'))
    if len(recovery) != 1 or recovery[0].count('/') != 1 or set(recovery) | set(kexts) != set(add):
        raise ValueError('Unexpected EFI additions: expected one RECOVERY file and one kext bundle')
    bundles = {k.split('/')[2] for k in kexts}
    if len(bundles) != 1:
        raise ValueError('Payload adds more than one kext bundle: ' + ', '.join(sorted(bundles)))
    bundle = bundles.pop()
    if not bundle.endswith('.kext') or any(not k.startswith('OC/Kexts/%s/' % bundle) for k in kexts):
        raise ValueError('Kext additions are not confined to one bundle')
    rec = recovery[0]

    baseline_bytes = (efi_payload / rec).read_bytes()
    if sha_bytes(baseline_bytes) != m['baseline_config_sha256'] or add[rec] != m['baseline_config_sha256']:
        raise ValueError('RECOVERY copy is not the baseline config')
    candidate_bytes = (efi_payload / CONFIG).read_bytes()
    base_cfg = plistlib.loads(baseline_bytes)
    cand_cfg = plistlib.loads(candidate_bytes)
    diffs = leaf_diffs(base_cfg, cand_cfg)
    # 0.0.667 payloads may also enable PollAppleHotKeys (Shift in the picker -> -x, the kext's recovery kill switch). Nothing else.
    hotkeys = [d for d in diffs if d == (('Misc', 'Boot', 'PollAppleHotKeys'), False, True)]
    diffs = [d for d in diffs if d not in hotkeys]
    if len(diffs) != 1:
        raise ValueError('Config must differ from baseline by exactly one key (plus PollAppleHotKeys false -> true), found %d: %r' % (len(diffs), diffs))
    path, old, new = diffs[0]
    if (len(path) != 4 or path[:2] != ('Kernel', 'Add') or not isinstance(path[2], int)
            or path[3] != 'BundlePath' or new != bundle or not isinstance(old, str)
            or not old.endswith('.kext') or old == new):
        raise ValueError('Config change is not the expected Kernel/Add BundlePath swap: %r' % (diffs,))

    bundle_dir = efi_payload / 'OC/Kexts' / bundle
    info = plistlib.loads((bundle_dir / 'Contents/Info.plist').read_bytes())
    if not info.get('CFBundleIdentifier') or str(info.get('CFBundleVersion')) not in bundle:
        raise ValueError('Kext identity does not match its bundle name')
    executable = 'OC/Kexts/%s/Contents/MacOS/%s' % (bundle, info.get('CFBundleExecutable', ''))
    if executable not in add or ('candidate_kernel_sha256' in m and add[executable] != m['candidate_kernel_sha256']):
        raise ValueError('Kext executable is not the reviewed binary')
    try:
        subprocess.run(['codesign', '--verify', '--strict', str(bundle_dir)], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise ValueError('Kext signature verification failed: ' + str(bundle_dir))

    system = m.get('system_before') or {}
    if not system:
        raise ValueError('Payload lacks the activation-guard dependency list')
    system_files = {}
    for name in system:
        if not safe_rel(name):
            raise ValueError('Unsafe system path: ' + name)
        digest = sha(payload / 'system' / name)
        if 'files' in m and m['files'].get('system/' + name) not in (None, digest):
            raise ValueError('System payload file differs from its manifest: ' + name)
        system_files[name] = digest

    boot_args = base_cfg.get('NVRAM', {}).get('Add', {}).get(BOOT_ARGS_GUID, {}).get('boot-args')
    if not isinstance(boot_args, str) or not boot_args.strip():
        raise ValueError('Baseline config has no NVRAM/Add boot-args to check against live NVRAM')

    return {'payload': payload, 'uuid': str(m['efi_volume_uuid']).upper(), 'baseline': base, 'candidate': cand,
            'add': add, 'bundle': bundle, 'recovery': rec, 'baseline_bytes': baseline_bytes,
            'candidate_bytes': candidate_bytes, 'candidate_cfg': cand_cfg, 'config_change': [path, old, new],
            'boot_args': boot_args, 'system_files': system_files}


def classify_install(efi, plan):
    live = tree(efi)
    if live == plan['baseline']:
        return 'baseline'
    if live == plan['candidate']:
        return 'candidate'
    raise ValueError('Live EFI is neither the baseline nor the candidate: ' + describe_mismatch(live, plan['baseline']))


def classify_restore(efi, plan):
    """Accept baseline, candidate, or any subset of additions with an unmodified baseline."""
    live = tree(efi)
    base, add = plan['baseline'], plan['add']
    if set(base) - set(live):
        raise ValueError('Live EFI is missing original files: ' + describe_mismatch(live, base))
    for name, digest in base.items():
        if name != CONFIG and live[name] != digest:
            raise ValueError('Live original file changed: ' + name)
    if live[CONFIG] not in (base[CONFIG], plan['candidate'][CONFIG]):
        raise ValueError('Live config.plist is neither the baseline nor the candidate')
    extras = sorted(set(live) - set(base))
    for name in extras:
        if name not in add or live[name] != add[name]:
            raise ValueError('Unexpected or changed EFI addition: ' + name)
    return {'config': 'candidate' if live[CONFIG] == plan['candidate'][CONFIG] else 'baseline', 'extras': extras}


def activation_guard(system_root, plan):
    """The persistent job must not run the new kernel with the old guard. Either disabled, or reviewed files."""
    app = Path(system_root) / APP_REL
    if os.path.lexists(app / 'disabled'):
        return 'disabled-marker'
    for name, digest in plan['system_files'].items():
        target = Path(system_root) / name
        if target.is_symlink() or not target.is_file() or sha(target) != digest:
            raise ValueError('Activation guard is not disabled and ' + str(target) +
                             ' is not the reviewed 666 file. Create APP/disabled first (see RECOVERY.md).')
    return 'reviewed-system-files-installed'


def diskutil_info(identifier):
    return plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', identifier]))


def find_efi_partition(uuid):
    # Only EFI-type partitions are inspected; other volumes (including personal media) are never read.
    listing = plistlib.loads(subprocess.check_output(['diskutil', 'list', '-plist']))
    matches = []
    for disk in listing.get('AllDisksAndPartitions', []):
        for part in disk.get('Partitions', []):
            if part.get('Content') != 'EFI':
                continue
            info = diskutil_info(part['DeviceIdentifier'])
            if str(info.get('VolumeUUID', '')).upper() == uuid:
                matches.append(info)
    if len(matches) != 1:
        raise ValueError('Expected one EFI partition with VolumeUUID %s, found %d' % (uuid, len(matches)))
    if matches[0].get('FilesystemType') != 'msdos':
        raise ValueError('The EFI partition is not FAT (msdos)')
    return matches[0]


def unmount(handle):
    if handle and handle['mounted_by_us']:
        subprocess.run(['diskutil', 'unmount', handle['identifier']], check=True, capture_output=True)
        handle['mounted_by_us'] = False


def mount_efi(uuid, writable):
    info = find_efi_partition(uuid)
    identifier = info['DeviceIdentifier']
    handle = {'identifier': identifier, 'mounted_by_us': False}
    if not info.get('MountPoint'):
        command = ['diskutil', 'mount'] + ([] if writable else ['readOnly']) + [identifier]
        subprocess.run(command, check=True, capture_output=True)
        handle['mounted_by_us'] = True
    try:
        info = diskutil_info(identifier)
        mount = Path(info.get('MountPoint') or '')
        if not mount.is_absolute() or mount.is_symlink() or not mount.is_dir():
            raise ValueError('EFI mount point unavailable')
        if str(info.get('VolumeUUID', '')).upper() != uuid:
            raise ValueError('Mounted volume UUID changed')
        if writable and not info.get('WritableVolume'):
            raise ValueError('EFI is mounted read-only; refusing to write')
        handle['mount'] = mount
        return handle
    except Exception:
        unmount(handle)
        raise


def check_live_opencore(plan):
    out = subprocess.run(['nvram', BOOT_ARGS_GUID + ':boot-args'], capture_output=True, text=True)
    if out.returncode != 0:
        raise ValueError('Cannot read live NVRAM boot-args')
    value = out.stdout.split('\t', 1)[-1].strip()
    if value != plan['boot_args'].strip():
        raise ValueError('Live NVRAM boot-args differ from the baseline OpenCore Add value; '
                         'this session did not boot the baseline config')


def resolve_efi(args, plan, writable):
    if args.efi_root is not None:
        return {'efi': args.efi_root.absolute(), 'discovery': 'test-root (not a booted-EFI proof)', 'handle': None}
    handle = mount_efi(plan['uuid'], writable)
    try:
        check_live_opencore(plan)
    except Exception:
        unmount(handle)
        raise
    return {'efi': handle['mount'] / 'EFI', 'discovery': 'unique EFI partition by VolumeUUID; live NVRAM matches baseline',
            'handle': handle}


def check_invocation(args):
    if args.efi_root is not None and args.system_root.absolute() == DEFAULT_SYSTEM_ROOT:
        raise ValueError('--efi-root is test-only and requires a sandboxed --system-root')
    if args.apply and args.efi_root is None and os.geteuid() != 0:
        raise ValueError('--apply requires root (sudo)')


def replace_file(destination, data):
    """Atomic replacement: temporary file in the same directory, fsync, rename over the target."""
    destination = Path(destination)
    if destination.is_symlink() or (os.path.lexists(destination) and not destination.is_file()):
        raise ValueError('Unsafe replacement target: ' + str(destination))
    fd, temporary = tempfile.mkstemp(prefix=PENDING, dir=str(destination.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def copy_tree_exclusive(source, destination):
    """Copy a directory without copying metadata (FAT rejects chmod/utime) and without overwrite."""
    source, destination = Path(source), Path(destination)
    destination.mkdir()
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in payload kext: ' + str(path))
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'rb') as source_stream, open(target, 'xb') as target_stream:
                shutil.copyfileobj(source_stream, target_stream)
                target_stream.flush()
                os.fsync(target_stream.fileno())
        else:
            raise ValueError('Special file in payload kext: ' + str(path))


def rollback(plan, efi, created):
    problems = []
    try:
        current = tree(efi).get(CONFIG)
        if current == plan['candidate'][CONFIG]:
            replace_file(efi / CONFIG, plan['baseline_bytes'])
        elif current != plan['baseline'][CONFIG]:
            problems.append('config.plist changed externally; not overwritten')
    except Exception as error:
        problems.append('config: ' + str(error))
    for path in reversed(created):
        try:
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except Exception as error:
            problems.append('%s: %s' % (path, error))
    try:
        if tree(efi) != plan['baseline']:
            problems.append('EFI differs from baseline after rollback')
    except Exception as error:
        problems.append('verify: ' + str(error))
    if problems:
        raise RuntimeError('ROLLBACK INCOMPLETE, restore from the backup: ' + '; '.join(problems))


def apply_install(plan, efi, backup_root):
    if classify_install(efi, plan) == 'candidate':
        return {'already_installed': True, 'changes': []}
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    backup_root = Path(backup_root)
    if backup_root.is_symlink():
        raise ValueError('Unsafe backup root: ' + str(backup_root))
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / ('efi-backup-' + stamp)
    if os.path.lexists(backup):
        raise ValueError('Backup already exists: ' + str(backup))
    backup.mkdir(mode=0o700)
    for name in plan['baseline']:
        target = backup / 'EFI' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(efi / name, target)
    if tree(backup / 'EFI') != plan['baseline']:
        raise ValueError('Backup verification failed; nothing was written to the EFI')
    replace_file(backup / 'backup-manifest.json', (json.dumps({
        'schema': 1, 'created_utc': stamp, 'payload': str(plan['payload']), 'efi': str(efi),
        'baseline_config_sha256': plan['baseline'][CONFIG], 'candidate_config_sha256': plan['candidate'][CONFIG],
        'bundle': plan['bundle'], 'recovery': plan['recovery'],
        'restore': 'restore-kernel-efi.py PAYLOAD --backup THIS_DIRECTORY --apply'}, indent=2, sort_keys=True) + '\n').encode())
    if classify_install(efi, plan) != 'baseline':
        raise ValueError('EFI changed while the backup was made; nothing was written to the EFI')

    created, changes = [], []
    kext_dir = efi / 'OC/Kexts' / plan['bundle']
    pending = efi / 'OC/Kexts' / (PENDING + plan['bundle'])
    recovery = efi / plan['recovery']
    try:
        if os.path.lexists(kext_dir) or os.path.lexists(pending) or os.path.lexists(recovery):
            raise ValueError('Target EFI path already exists')
        created.append(pending)
        copy_tree_exclusive(plan['payload'] / 'EFI/OC/Kexts' / plan['bundle'], pending)
        os.rename(pending, kext_dir)
        created[-1] = kext_dir
        changes.append('copied kext OC/Kexts/' + plan['bundle'])
        created.append(recovery)
        with open(recovery, 'xb') as stream:
            stream.write(plan['baseline_bytes'])
            stream.flush()
            os.fsync(stream.fileno())
        changes.append('kept pre-install config at ' + plan['recovery'])
        if tree(efi) != {**plan['baseline'], **plan['add']}:
            raise ValueError('Unexpected EFI state after additions')
        replace_file(efi / CONFIG, plan['candidate_bytes'])
        path, old, new = plan['config_change']
        changes.append('replaced OC/config.plist atomically: %s %r -> %r' % ('/'.join(map(str, path)), old, new))
        if tree(efi) != plan['candidate'] or plistlib.loads((efi / CONFIG).read_bytes()) != plan['candidate_cfg']:
            raise ValueError('Final EFI verification failed')
    except Exception as error:
        try:
            rollback(plan, efi, created)
        except RuntimeError as rollback_error:
            raise RuntimeError('%s; %s' % (error, rollback_error)) from error
        raise
    return {'installed': True, 'activated': False, 'rebooted': False, 'backup': str(backup), 'changes': changes}


def planned_actions(plan, state, backup_root):
    if state == 'candidate':
        return ['none: the EFI already holds the candidate']
    path, old, new = plan['config_change']
    return [
        'create private backup %s/efi-backup-<timestamp>/ (EFI baseline, %d files, plus manifest)' % (backup_root, len(plan['baseline'])),
        'copy OC/Kexts/%s (exclusive, via pending name)' % plan['bundle'],
        'create %s (baseline config bytes, exclusive)' % plan['recovery'],
        'atomically replace OC/config.plist: %s %r -> %r' % ('/'.join(map(str, path)), old, new),
        'verify exact EFI inventory against the candidate (%d files)' % len(plan['candidate']),
        'unmount only if this run mounted the volume',
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('payload', type=Path, help='prepared payload directory (e.g. kernel-payload-v2)')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true', help='perform the writes (default is a dry run)')
    group.add_argument('--dry-run', action='store_true', help='explicit default: checks and plan only')
    parser.add_argument('--system-root', type=Path, default=DEFAULT_SYSTEM_ROOT)
    parser.add_argument('--backup-root', type=Path, help='default: SYSTEM_ROOT/' + BACKUP_REL)
    parser.add_argument('--efi-root', type=Path, help='TEST ONLY: EFI directory instead of the mounted volume')
    args = parser.parse_args(argv)
    system_root = args.system_root.absolute()
    backup_root = (args.backup_root or system_root / BACKUP_REL).absolute()
    report = {'mode': 'apply' if args.apply else 'dry-run'}
    handle = None
    try:
        check_invocation(args)
        plan = load_payload(args.payload)
        resolved = resolve_efi(args, plan, writable=args.apply)
        handle = resolved['handle']
        state = classify_install(resolved['efi'], plan)
        report.update(efi=str(resolved['efi']), discovery=resolved['discovery'], efi_state=state,
                      activation_guard=activation_guard(system_root, plan),
                      planned=planned_actions(plan, state, backup_root))
        if args.apply and state == 'baseline':
            report.update(apply_install(plan, resolved['efi'], backup_root))
        report['applied'] = bool(args.apply and state == 'baseline')
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError, KeyError) as error:
        report['error'] = str(error)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    finally:
        unmount(handle)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
