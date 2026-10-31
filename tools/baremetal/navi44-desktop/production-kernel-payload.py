#!/usr/bin/env python3
"""Prepare/check the logical-context kernel trial (0.0.666, 0.0.667 or 0.0.668) without changing EFI or the live system.

`prepare --baseline-payload <verified earlier payload>` builds the baseline EFI from that payload's recorded hashes
instead of the mounted EFI (the EFI is not mounted and must not be touched). Such a payload is marked
live_efi_verified: false; installation must run `check --live` against the real EFI.
`--baseline-state candidate` takes the EFI that the earlier payload installs (0.0.668 is built on payload v3 that way).
The activation guard is derived from the live guard at prepare time: if that guard changes before installation,
prepare again (`check --live` refuses a stale guard).
"""
import argparse
import copy
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'
PROBE = APP + '/context-isolation-probe'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
JOB = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
CRITICAL = (JOB, APP+'/boot-state.py', APP+'/navi48test', APP+'/n48nub', APP+'/seed-gpu-apps.py', APP+'/app-allowlist.json')
# The payload owns only OC/ and RECOVERY/ on the EFI volume. Everything else on it (CachyOS loader and scripts, BOOT/,
# System Volume Information) is never read, listed, required or written.
SCOPE = ('OC/', 'RECOVERY/')
STICK_UUID = '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3'   # OCBOOT USB stick (earlier target)
LOCAL_UUID = '97C4AA5C-B87D-3786-B1B3-F84A76840DEF'   # CachyOS EFI partition (disk1s1): default for new payloads
EFI_UUIDS = (LOCAL_UUID, STICK_UUID)
UUID = LOCAL_UUID
PROFILE = 'stage26-logical-contexts-v1'
OLD = 'Navi48Bringup-eight-0.0.665.kext'
BASE_SHA = '607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24'
BASE_CONFIG_SHA = '92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb'
# Each release: its kext bundle, its recovery copy of the 665 config, the reviewed kernel binary, the CPU-test count,
# the strings its binary must contain, the exact list of config edits (path, old, new: checked, never assumed), and the
# extra EFI files it adds: 'baseline' means the baseline config bytes, otherwise the sha256 of the reviewed source file.
STARTUP = 'OC/Tools/startup.nsh'
STARTUP_SOURCE = Path(__file__).resolve().parent/'kernel-efi/startup.nsh'
STARTUP_SHA = '318f9fb9dc8e4419b9a8a33f58f866b961ddf7fc72fa93a178bfe71a6bbd5753'
EXTRA_SOURCES = {STARTUP: STARTUP_SOURCE}
# The 0.0.667 recovery entry (Misc/Tools[0]); 0.0.668 inherits it from its baseline and checks it.
RECOVERY_ENTRY = {'Name': 'Ripristino EFI: driver funzionanti (665)',
                  'Comment': 'Restores RECOVERY/funzionante-665.plist (kernel 665) and reboots'}
# 0.0.668 replaces the kernel that payload v3 installs (its candidate EFI is the live EFI state the baseline is taken from).
BUNDLE_667 = 'Navi48Bringup-contexts-0.0.667.kext'
KERNEL_667_SHA = '976b3375082c3f319f940b02f74fd5ff03155884a39feae771edfab62623f287'
CONFIG_667_SHA = '5ea9932d7fd53e97062021a72c6613f76bb96a3ecccce12d942fa8b796d531c6'
PROBE_667_SHA = '5afe2b52b0c0adc7a4bf1ea8f8e07437929ed9cfe066fa1f56a39240ceb000c5'   # the probe digest the 0.0.667 capability block pins
# the Metal components the live bundle-33 guard pins (stage33-memtype-v1; its Info.plist version is 33)
METAL_33 = {'Contents/MacOS/Navi48Metal': '85c7d8bdfe8c681503a5701afc09ce3b5cddf3ef124fca587913d261c7b4fd5f',
            'Contents/Resources/libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
            'Contents/Resources/libn48xlate.dylib': '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a'}
RELEASES = {
    '0.0.666': {'new': 'Navi48Bringup-contexts-0.0.666.kext', 'recovery': 'RECOVERY/pre-contexts-666-config.plist',
                'from': OLD, 'from_kernel_sha': BASE_SHA, 'from_config_sha': BASE_CONFIG_SHA,
                'kernel_sha': '3ddcb7b087683c0e7a6416232534569d3aca37b747787669711db34d8f2d5f51', 'tests': 5,
                'strings': (), 'guard': 'stage26', 'metal': None, 'metal_version': None,
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': OLD, 'new': 'Navi48Bringup-contexts-0.0.666.kext'}],
                'extras': {'RECOVERY/pre-contexts-666-config.plist': 'baseline'}},
    '0.0.667': {'new': 'Navi48Bringup-contexts-0.0.667.kext', 'recovery': 'RECOVERY/pre-contexts-667-config.plist',
                'from': OLD, 'from_kernel_sha': BASE_SHA, 'from_config_sha': BASE_CONFIG_SHA,
                'kernel_sha': '976b3375082c3f319f940b02f74fd5ff03155884a39feae771edfab62623f287',   # reviewed 0.0.667 build (db8b202)
                'tests': 6, 'strings': ('navi48-off', 'application budget', 'open refused (NoResources)'),
                'edits': [
                    {'path': 'Kernel/Add/7/BundlePath', 'old': OLD, 'new': 'Navi48Bringup-contexts-0.0.667.kext'},
                    {'path': 'Misc/Tools/0/Name', 'old': 'Ripristino EFI (UEFI Shell)',
                     'new': 'Ripristino EFI: driver funzionanti (665)'},
                    {'path': 'Misc/Tools/0/Comment', 'old': 'Recovery shell: restore stage17 config',
                     'new': 'Restores RECOVERY/funzionante-665.plist (kernel 665) and reboots'}],
                'extras': {'RECOVERY/pre-contexts-667-config.plist': 'baseline',
                           'RECOVERY/funzionante-665.plist': 'baseline', STARTUP: STARTUP_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                # the LIVE bundle-30 guard (stage30-vonly-v1) is the base; its Metal expectations are bundle 30
                'guard': 'live', 'metal_version': '30',
                'metal': {'Contents/MacOS/Navi48Metal': '8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230',
                          'Contents/Resources/libn48xlate.dylib': '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a'}},
    # The baseline is payload v3's candidate EFI (the live state): its 0.0.667 bundle and configuration, its recovery entry and files.
    # The only config edit is the kext's BundlePath. The recovery copy kept here is the 0.0.667 configuration (the baseline bytes).
    # kernel_sha: the 0.0.668 binary of kernel-contexts-v4 (built from the working-tree overlay recorded in its manifest).
    '0.0.668': {'new': 'Navi48Bringup-contexts-0.0.668.kext', 'recovery': 'RECOVERY/pre-contexts-668-config.plist',
                'from': BUNDLE_667, 'from_kernel_sha': KERNEL_667_SHA, 'from_config_sha': CONFIG_667_SHA,
                'kernel_sha': 'ab4c7fed6dd6c6ee52096da25d78f50bc515a51fdbfe8f591654143afe9ccb6d', 'tests': 6,
                # the reviewed probe of payload v3 (its code equals a fresh build of the committed probe source; see same_except_uuid)
                'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_667, 'new': 'Navi48Bringup-contexts-0.0.668.kext'}],
                'extras': {'RECOVERY/pre-contexts-668-config.plist': 'baseline'},
                # carried from the baseline (payload v3): the startup script, the 665 recovery copy and the 667 configuration copy
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                # the CURRENT live guard, which already holds the 0.0.667 capability block: only that block's kernel match moves
                'guard': 'live-668', 'metal_version': '33', 'metal': METAL_33},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and p.as_posix() == name


def tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Missing/unsafe tree: '+str(root))
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ValueError('Unsafe file: '+str(p))
        if p.is_file(): result[p.relative_to(root).as_posix()] = sha(p)
    return result


def metadata(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Unsafe target: '+str(path))
    return {'sha256': sha(path), 'mode': path.stat().st_mode & 0o777} if path.exists() else None


def scoped(inventory):
    return {k: v for k, v in inventory.items() if k.startswith(SCOPE)}


def scoped_tree(root):
    """Inventory of the payload-owned EFI paths (OC/ and RECOVERY/) only; the rest of the volume is never read."""
    result = {}
    for top in ('OC', 'RECOVERY'):
        base = root/top
        if base.is_symlink() or not base.is_dir(): raise ValueError('Missing/unsafe tree: '+str(base))
        for p in sorted(base.rglob('*')):
            if p.is_symlink() or not (p.is_file() or p.is_dir()): raise ValueError('Unsafe file: '+str(p))
            if p.is_file(): result[p.relative_to(root).as_posix()] = sha(p)
    return result


def efi_mount(uuid):
    """Mount point of the single mounted EFI partition with this VolumeUUID (the mount root; EFI/ is below it)."""
    listing = plistlib.loads(subprocess.check_output(['diskutil','list','-plist']))
    matches = []
    for disk in listing.get('AllDisksAndPartitions', []):
        for part in disk.get('Partitions', []):
            if part.get('Content') != 'EFI': continue
            info = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',part['DeviceIdentifier']]))
            if str(info.get('VolumeUUID','')).upper() == uuid: matches.append(info)
    if len(matches) != 1 or not matches[0].get('MountPoint'):
        raise ValueError('Expected one mounted EFI partition with VolumeUUID %s' % uuid)
    return Path(matches[0]['MountPoint'])


def boot_uuid():
    return subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],text=True).strip().lower()


def baseline_config(data, bundle=OLD):
    entries = [e for e in data['Kernel']['Add'] if e.get('Enabled') and 'Navi48Bringup' in e.get('BundlePath','')]
    if len(entries) != 1 or entries[0]['BundlePath'] != bundle:
        raise ValueError('Expected exactly one active baseline entry: ' + bundle)
    return entries[0]


def diff_paths(a, b, prefix=''):
    """Paths (like Kernel/Add/7/BundlePath) at which two plist values differ."""
    if type(a) is not type(b):
        return [prefix]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f'{prefix}/{k}')
            else:
                out += diff_paths(a[k], b[k], f'{prefix}/{k}')
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [prefix]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f'{prefix}/{i}')
        return out
    return [] if a == b else [prefix]


def path_slot(data, path):
    """(container, key) for a slash path such as Kernel/Add/7/BundlePath; list indexes are integers."""
    parts = path.split('/')
    node = data
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    return node, (int(last) if isinstance(node, list) else last)


def expected_config(original, rel):
    """The baseline boot configuration with exactly the release's listed edits; each edit must find its listed old value."""
    config = copy.deepcopy(original)
    for edit in rel['edits']:
        container, key = path_slot(config, edit['path'])
        if container[key] != edit['old']:
            raise ValueError('Baseline value differs from the listed edit: ' + edit['path'])
        container[key] = edit['new']
    return config


PROBE_BLOCK = r'''[[ $(shasum -a 256 "$APP/context-isolation-probe" | cut -d " " -f 1) == PROBE_DIGEST ]] || { echo 'STOP context profile checker changed'; exit 1; }
profilecheck=$("$APP/context-isolation-probe" --check-profile 2>&1) || { echo "STOP dynamic context profile: $profilecheck"; exit 1; }
echo "CONTEXT_PROFILE_VERIFIED=$profilecheck"
logicalpage=$("$NT" accel sessstat 95 2>&1) || { echo "STOP logical context diagnostic page: $logicalpage"; exit 1; }
printf '%s\n' "$logicalpage" | grep -Eq 'slot / VMID / session[[:space:]]*:[[:space:]]*63[[:space:]]*/' || { echo 'STOP missing logical context 63'; exit 1; }
echo 'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64'
'''


# Inserted before the live guard's fbidentity line. Loaded 0.0.667: the capability checks (dynamic VMID, logical
# context 63). Loaded 0.0.665 (the recovery entry restored that configuration): the checks are skipped and the live guard
# runs as it always has. Any other kernel stops. Only additions: no live line is removed or changed.
KERNEL_BRANCH = r'''if printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(0\.0\.667\)'; then
PROBE_BLOCK_HERE
elif printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(0\.0\.665\)'; then
echo 'CAPABILITY_CHECKS=skipped for kernel 0.0.665 (recovery configuration)'
else
echo 'STOP expected kernel 667 or 665'; exit 1
fi
'''
# 0.0.668: the same block with its kernel match and its STOP text moved to 0.0.668 (the 0.0.665 branch stays).
KERNEL_BRANCH_668 = KERNEL_BRANCH.replace(r'\(0\.0\.667\)', r'\(0\.0\.668\)').replace('STOP expected kernel 667 or 665', 'STOP expected kernel 668 or 665')


def capability_block(branch, probe_sha):
    """A kernel branch with its probe check filled in: the block as guard_live inserts it."""
    return branch.replace('PROBE_BLOCK_HERE\n', PROBE_BLOCK.replace('PROBE_DIGEST', probe_sha))


def bump_guard(original, probe_sha):
    """0.0.668: the live guard with its reviewed 0.0.667 capability block replaced by the 0.0.668 block. Only that block
    changes: its kernel match and STOP text move to 0.0.668, the 0.0.665 branch stays, and the probe digest follows the staged
    probe (identical when the probe is byte-identical). The block must be there exactly once, as the reviewed 0.0.667 insertion
    with the 0.0.667 probe digest; everything else in the guard is kept byte for byte."""
    old = capability_block(KERNEL_BRANCH, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.667 capability block')
    return original.replace(old, capability_block(KERNEL_BRANCH_668, probe_sha))


def guard_live(original, probe_sha, version):
    """The live bundle-30 guard plus only the 0.0.667 branch (see KERNEL_BRANCH). Profile name, Metal hashes and every
    other live line are the live file's own."""
    if version != '0.0.667': raise ValueError('The live guard is only derived for 0.0.667')
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    kext_check = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    if original.count(kext_check) != 1: raise ValueError('Unexpected kext check in the live guard')
    marker = 'fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)'
    branch = capability_block(KERNEL_BRANCH, probe_sha)
    replace(marker, branch + marker)
    return original


def make_guard(rel, original, probe_sha, version):
    if rel['guard'] == 'live-668':
        if version != '0.0.668': raise ValueError('The live-668 guard is only derived for 0.0.668')
        return bump_guard(original, probe_sha)
    return guard_live(original, probe_sha, version) if rel['guard'] == 'live' else guard_text(original, probe_sha, version)


def guard_text(original, probe_sha, version):
    """The stage26 guard transformation (0.0.666 payload only)."""
    build = version.rsplit('.', 1)[1]
    version_re = version.replace('.', r'\.')
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    replace('PROFILE=stage25-archive-boundary-v1', 'PROFILE='+PROFILE)
    replace("echo 'CANDIDATE=stage25-archive-boundary'", "echo 'CANDIDATE=stage26-logical-contexts'")
    marker = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    replace(marker, marker + '\n' + r'''printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(@RE@\)' || { echo 'STOP expected kernel @BUILD@'; exit 1; }'''
            .replace('@RE@', version_re).replace('@BUILD@', build))
    marker = 'fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)'
    probe = r'''[[ $(shasum -a 256 "$APP/context-isolation-probe" | cut -d " " -f 1) == PROBE_DIGEST ]] || { echo 'STOP context profile checker changed'; exit 1; }
profilecheck=$("$APP/context-isolation-probe" --check-profile 2>&1) || { echo "STOP dynamic context profile: $profilecheck"; exit 1; }
echo "CONTEXT_PROFILE_VERIFIED=$profilecheck"
logicalpage=$("$NT" accel sessstat 95 2>&1) || { echo "STOP logical context diagnostic page: $logicalpage"; exit 1; }
printf '%s\n' "$logicalpage" | grep -Eq 'slot / VMID / session[[:space:]]*:[[:space:]]*63[[:space:]]*/' || { echo 'STOP missing logical context 63'; exit 1; }
echo 'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64'
'''.replace('PROBE_DIGEST', probe_sha)
    replace(marker, probe+'\n'+marker)
    return original


def release_of(m):
    version = m.get('candidate_version', '0.0.666')
    if version not in RELEASES:
        raise ValueError('Unknown candidate release: '+version)
    return version, RELEASES[version]


def baseline_sources(snapshot, state='baseline'):
    """The live EFI as recorded by an earlier verified payload. state 'baseline': the EFI before that payload's release (its
    baseline_efi_files, hashed from the live EFI when it was prepared; OC/config.plist from its recovery copy). state
    'candidate': the EFI that payload installs, i.e. the live state once it is installed (its candidate_efi_files, as staged).
    Returns {path: source}."""
    if state not in ('baseline', 'candidate'):
        raise ValueError('Unknown baseline state: ' + state)
    verify(snapshot, live=False)
    m = json.loads((snapshot/'manifest.json').read_text())
    _, rel = release_of(m)
    sources = {}
    recorded = scoped(m['candidate_efi_files'] if state == 'candidate' else m['baseline_efi_files'])
    for name, digest in recorded.items():
        if not safe(name):
            raise ValueError('Unsafe baseline path: '+name)
        path = snapshot/'EFI'/rel['recovery'] if (state == 'baseline' and name == 'OC/config.plist') else snapshot/'EFI'/name
        if sha(path) != digest:
            raise ValueError('Snapshot differs from its recorded %s state: %s' % (state, name))
        sources[name] = path
    return sources


def verify(payload, live=False, efi=None, system_root=Path('/')):
    if payload.is_symlink(): raise ValueError('Symlink payload')
    m = json.loads((payload/'manifest.json').read_text())
    if m.get('schema') != 1 or m.get('profile') != PROFILE or m.get('status') != 'prepared-not-installed':
        raise ValueError('Unexpected kernel payload profile')
    version, rel = release_of(m)
    actual = tree(payload); actual.pop('manifest.json')
    if actual != m['files'] or set(actual) != set(m['file_modes']): raise ValueError('Payload inventory changed')
    for name in actual:
        if not safe(name) or not name.startswith(('EFI/','system/','evidence/')) or (payload/name).stat().st_mode & 0o777 != m['file_modes'][name]:
            raise ValueError('Payload path/mode changed: '+name)
    system = {p[7:] for p in actual if p.startswith('system/')}
    if system != {GUARD,PROBE} or set(m['system_before']) != system or set(m['critical_system_files']) != set(CRITICAL):
        raise ValueError('Unexpected system write or dependency set')
    if any(m['file_modes']['system/'+name] != 0o755 for name in system):
        raise ValueError('System executables require mode 755')
    base, staged = m['baseline_efi_files'], tree(payload/'EFI')
    if staged != m['candidate_efi_files'] or base['OC/config.plist'] != m['baseline_config_sha256'] or staged['OC/config.plist'] != m['candidate_config_sha256']:
        raise ValueError('EFI inventory changed')
    if base['OC/config.plist'] != rel['from_config_sha']:
        raise ValueError('Baseline boot configuration is not the reviewed configuration of release ' + version)
    for name, digest in base.items():
        if not safe(name) or (name != 'OC/config.plist' and staged.get(name) != digest):
            raise ValueError('Original EFI path changed: '+name)
    additions = {k:v for k,v in staged.items() if k not in base}
    kexts = {k for k in additions if k.startswith('OC/Kexts/'+rel['new']+'/')}
    if not kexts or additions != m['add_files'] or set(additions) != kexts | set(rel['extras']):
        raise ValueError('Unexpected EFI additions')
    for name, want in rel['extras'].items():
        if additions[name] != (base['OC/config.plist'] if want == 'baseline' else want):
            raise ValueError('Unexpected content for EFI addition: '+name)
    original = plistlib.loads((payload/'EFI'/rel['recovery']).read_bytes())
    staged_config = plistlib.loads((payload/'EFI/OC/config.plist').read_bytes())
    listed = sorted(e['path'] for e in rel['edits'])
    if sorted(d[1:] for d in diff_paths(original, staged_config)) != listed or staged_config != expected_config(original, rel):
        raise ValueError('Boot configuration differs from the reviewed edits')
    if 'config_edits' in m and m['config_edits'] != rel['edits']:
        raise ValueError('Manifest config edits differ from the reviewed edits')
    if 'recovery_entry' in rel:   # the recovery entry (Misc/Tools[0]) and the recovery files it restores are reviewed text
        entry = staged_config['Misc']['Tools'][0]
        if {k: entry.get(k) for k in ('Name', 'Comment')} != rel['recovery_entry'] or entry.get('Path') != 'OpenShell.efi':
            raise ValueError('Recovery entry differs from the reviewed text')
    for name, digest in rel.get('carried', {}).items():
        if staged.get(name) != digest:
            raise ValueError('Recovery file carried from the baseline differs: ' + name)
    bundle = payload/'EFI/OC/Kexts'/rel['new']
    if rel['kernel_sha'] is None or sha(bundle/'Contents/MacOS/Navi48Bringup') != rel['kernel_sha']:
        raise ValueError('Unexpected kernel binary')
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != 'com.navi48.bringup' or info['CFBundleVersion'] != version:
        raise ValueError('Unexpected kernel identity')
    for name, digest in (rel['metal'] or {}).items():
        if m['working_metal_files'].get(name) != digest: raise ValueError('Working Metal is not the reviewed bundle %s: %s' % (rel['metal_version'], name))
    subprocess.run(['codesign','--verify','--strict',str(bundle)],check=True)
    if rel.get('probe_reuse') and sha(payload/'system'/PROBE) != rel['probe_reuse']:
        raise ValueError('Probe is not the reviewed binary of this release')
    guard = (payload/'system'/GUARD).read_text()
    old_guard = payload/'evidence/original-guard.sh'
    if sha(old_guard) != m['system_before'][GUARD]['sha256'] or guard != make_guard(rel, old_guard.read_text(), sha(payload/'system'/PROBE), version):
        raise ValueError('Activation guard differs from the reviewed transformation')
    if rel['metal'] and any(digest not in guard for digest in rel['metal'].values()):
        raise ValueError('Activation guard does not pin the reviewed Metal components')
    subprocess.run(['/bin/bash','-n',str(payload/'system'/GUARD)],check=True)
    if m['efi_volume_uuid'] not in EFI_UUIDS: raise ValueError('Unexpected EFI volume identity')
    if live:
        if boot_uuid() != m['prepared_boot_uuid']: raise ValueError('Payload prepared in another boot')
        if subprocess.check_output(['sw_vers','-buildVersion'],text=True).strip() != '25G83': raise ValueError('Different macOS build')
        if efi is None: efi = efi_mount(m['efi_volume_uuid'])/'EFI'
        volume = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(efi.parent)]))
        if volume.get('MountPoint') != str(efi.parent) or volume.get('VolumeUUID','').upper() != m['efi_volume_uuid'] or volume.get('FilesystemType') != 'msdos':
            raise ValueError('Wrong mounted EFI volume')
        if scoped_tree(efi) != scoped(base): raise ValueError('Live EFI differs from baseline')
        if tree(system_root/METAL) != m['working_metal_files']: raise ValueError('Working Metal changed')
        for name, expected in {**m['system_before'], **m['critical_system_files']}.items():
            if not safe(name) or metadata(system_root/name) != expected: raise ValueError('Live system dependency changed: '+name)
    return m


def same_except_uuid(a, b):
    """True when two 64-bit little-endian Mach-O files differ only in their LC_UUID load command: the link step's UUID is
    not reproducible from the same source, the code and data are."""
    def uuid_span(data):
        if len(data) < 32 or struct.unpack_from('<I', data, 0)[0] != 0xfeedfacf:
            raise ValueError('Not a 64-bit little-endian Mach-O file')
        off, spans = 32, []
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            cmd, size = struct.unpack_from('<II', data, off)
            if size < 8 or off + size > len(data):
                raise ValueError('Malformed Mach-O load commands')
            if cmd == 0x1b:   # LC_UUID: the 16 UUID bytes follow the 8-byte command header
                spans.append((off + 8, off + 24))
            off += size
        if len(spans) != 1:
            raise ValueError('Expected exactly one LC_UUID load command')
        return spans[0]
    if len(a) != len(b):
        return False
    (s, e), (s2, e2) = uuid_span(a), uuid_span(b)
    return (s, e) == (s2, e2) and a[:s] + a[e:] == b[:s] + b[e:]


def prepare(candidate, output, baseline_payload=None, baseline_state='baseline'):
    buildroot = (ROOT/'research/builds').resolve()
    output = output.resolve(); candidate = candidate.resolve()
    if output == buildroot or not output.is_relative_to(buildroot) or output.exists() or not candidate.is_relative_to(buildroot):
        raise ValueError('Use a new output and existing candidate under research/builds')
    build = json.loads((candidate/'manifest.json').read_text())
    version, rel = release_of(build)
    if (build.get('status') != 'built-cpu-tested-not-installed-hardware-unverified' or build.get('profile') != {'hardware_slots':8,'logical_contexts':64}
            or rel['kernel_sha'] is None or build.get('candidate_binary_sha256') != rel['kernel_sha'] or len(build.get('cpu_tests',[])) != rel['tests']
            or len(build.get('baseline_sections',{})) != 7 or not set(rel['strings']) <= set(build.get('required_strings', []))):
        raise ValueError('Candidate is not the verified kernel-%s build' % version)
    if build['prepared_boot_uuid'].lower() != boot_uuid(): raise ValueError('Build belongs to another boot')
    source = candidate/'candidate-source'
    for name, digest in build['candidate_inputs'].items():
        if not safe(name) or sha(source/name) != digest: raise ValueError('Candidate source changed')
    bundle = candidate/build['candidate_bundle']
    if not bundle.resolve().is_relative_to(candidate) or sha(bundle/'Contents/MacOS/Navi48Bringup') != rel['kernel_sha']:
        raise ValueError('Candidate bundle changed')
    live = baseline_payload is None
    if live:
        live_efi = efi_mount(UUID)/'EFI'
        sources = {name: live_efi/name for name in scoped_tree(live_efi)}
    else:
        sources = baseline_sources(baseline_payload, baseline_state)
    before = {name: sha(path) for name, path in sources.items()}
    config_bytes = sources['OC/config.plist'].read_bytes()
    config = plistlib.loads(config_bytes); entry = baseline_config(config, rel['from'])
    if (before.get('OC/Kexts/'+rel['from']+'/'+entry['ExecutablePath']) != rel['from_kernel_sha'] or before['OC/config.plist'] != build['active_baseline']['config_sha256']
            or build['active_baseline']['kernel_sha256'] != rel['from_kernel_sha'] or build['active_baseline']['config_sha256'] != rel['from_config_sha']):
        raise ValueError('Working EFI is not the compiled baseline')
    if any(k.startswith('OC/Kexts/'+rel['new']+'/') or k in rel['extras'] for k in before):
        raise ValueError('Candidate/recovery EFI paths already exist')
    if any(x.get('BundlePath') == rel['new'] for x in config['Kernel']['Add']): raise ValueError('Candidate already listed in config')
    original_guard = (Path('/')/GUARD).read_text()
    baseline_system = {name:metadata(Path('/')/name) for name in (GUARD,PROBE)}
    critical = {name:metadata(Path('/')/name) for name in CRITICAL}
    if any(v is None for v in critical.values()) or baseline_system[GUARD] is None: raise ValueError('Missing boot dependency')
    metal = tree(Path('/')/METAL)
    output.mkdir(parents=True)
    (output/'evidence').mkdir()
    shutil.copyfile(candidate/'manifest.json',output/'evidence/build-manifest.json')
    (output/'evidence/original-guard.sh').write_text(original_guard)
    efi_out = output/'EFI'
    for name, path in sources.items():
        (efi_out/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, efi_out/name)
    if tree(efi_out) != before: raise ValueError('Staged baseline differs from the recorded baseline')
    shutil.copytree(bundle, efi_out/'OC/Kexts'/rel['new'])
    for name, want in rel['extras'].items():
        data = config_bytes if want == 'baseline' else EXTRA_SOURCES[name].read_bytes()
        if want != 'baseline' and hashlib.sha256(data).hexdigest() != want: raise ValueError('Not the reviewed file: '+name)
        (efi_out/name).parent.mkdir(parents=True, exist_ok=True)
        (efi_out/name).write_bytes(data)
    (efi_out/'OC/config.plist').write_bytes(plistlib.dumps(expected_config(config, rel), sort_keys=False))
    verifier = ROOT/'research/ext/navi44-baremetal-stage1-candidate-20261027/tools/ocvalidate'
    subprocess.run([str(verifier), str(efi_out/'OC/config.plist')], check=True)
    target = output/'system'/PROBE; target.parent.mkdir(parents=True)
    probe_source = ROOT/'tools/baremetal/navi44-gpu-diagnostics/context-isolation-probe.cpp'
    command = ['clang++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(source/'src'),str(probe_source),'-framework','IOKit','-framework','CoreFoundation','-o',str(target)]
    subprocess.run(command,check=True);target.chmod(0o755)
    probe_reuse_record = None
    if rel.get('probe_reuse'):
        # The reviewed probe is reused when a fresh build of this source differs from it only in its LC_UUID; then the probe file,
        # and the guard's probe digest, stay exactly as reviewed. Any other difference refuses the release.
        reviewed_source = (baseline_payload/'system'/PROBE) if baseline_payload is not None else (Path('/')/PROBE)
        reviewed = reviewed_source.read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != rel['probe_reuse'] or not same_except_uuid(target.read_bytes(), reviewed):
            raise ValueError('The reviewed probe is not a fresh build of this source (apart from its UUID)')
        target.write_bytes(reviewed); target.chmod(0o755)
        probe_reuse_record = {'reviewed_sha256': rel['probe_reuse'], 'reviewed_from': str(reviewed_source),
                              'checked': 'identical to a fresh build of the probe source except LC_UUID'}
    with (output/'evidence/probe-self-test.log').open('w') as log:
        subprocess.run([str(target),'--self-test'],stdout=log,stderr=subprocess.STDOUT,check=True)
    guard = output/'system'/GUARD
    if rel['metal'] and ('"$bundle_version" == %s ' % rel['metal_version']) not in original_guard:
        raise ValueError('Live guard does not expect Metal bundle %s' % rel['metal_version'])
    guard.write_text(make_guard(rel, original_guard, sha(target), version)); guard.chmod(0o755)
    staged = tree(efi_out)
    files = tree(output)
    m = {'schema':1,'status':'prepared-not-installed','profile':PROFILE,'candidate_version':version,
         'prepared_boot_uuid':boot_uuid(),'efi_volume_uuid':UUID,
         'baseline_efi_files':before,'candidate_efi_files':staged,
         'baseline_config_sha256':before['OC/config.plist'],
         'candidate_config_sha256':staged['OC/config.plist'],
         'config_edits':rel['edits'],'recovery_copy':rel['recovery'],
         'baseline_source':'live-efi' if live else 'recorded-payload:%s%s' % (baseline_payload.name, '' if baseline_state == 'baseline' else ':' + baseline_state),
         'live_efi_verified': live,
         'add_files':{k:v for k,v in staged.items() if k not in before},
         'system_before':baseline_system,'critical_system_files':critical,
         'working_metal_files':metal,'files':files,
         'file_modes':{k:(output/k).stat().st_mode & 0o777 for k in files},
         'candidate_kernel_sha256':rel['kernel_sha'],'probe_build_command':command,'probe_reuse':probe_reuse_record,
         'probe_source_sha256':sha(probe_source),'preparer_sha256':sha(Path(__file__)),
         'hardware_validation':'not performed','installation':'not performed'}
    (output/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    verify(output, live=live)
    return m


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prep = commands.add_parser('prepare');prep.add_argument('--candidate',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    prep.add_argument('--baseline-payload',type=Path,help='offline: take the baseline EFI from this verified payload instead of the mounted EFI')
    prep.add_argument('--baseline-state',choices=('baseline','candidate'),default='baseline',
                      help="which EFI state of --baseline-payload is the live one: its baseline (default) or its candidate (0.0.668 on payload v3)")
    check = commands.add_parser('check');check.add_argument('payload',type=Path);check.add_argument('--live',action='store_true')
    args = parser.parse_args()
    m = prepare(args.candidate,args.output,args.baseline_payload,args.baseline_state) if args.command == 'prepare' else verify(args.payload,args.live)
    print(json.dumps({'profile':m['profile'],'candidate_version':m.get('candidate_version','0.0.666'),'files_verified':len(m['files']),
                      'live_efi_verified':m.get('live_efi_verified',True),'installed':False,'hardware_validation':m['hardware_validation']},indent=2))


if __name__ == '__main__': main()
