#!/usr/bin/env python3
"""Read-only unified payload/live-baseline preflight. No install, mount or GPU call."""
import argparse
import hashlib
import json
import plistlib
import re
import subprocess
from pathlib import Path, PurePosixPath

APP = 'Library/Application Support/Navi44/accelerated-trial'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
BOOT = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
APP_FILES = {'accelerated-reboot-trial.sh', 'seed-gpu-apps.py', 'app-allowlist.json', 'boot-state.py', 'cppc-check.py', 'navi48test', 'n48nub'}
TRANSLATOR_FILES = {'metal2vulkan', 'n48-llvm-dis', 'n48-spirv-val-stub', 'n48-translate.sb', 'overrides.txt', 'pc-translate.py', 'pc-translate.sh', 'spirv-val'}


def relative(value):
    if not isinstance(value, str):
        raise ValueError('Payload path is not text')
    p = PurePosixPath(value)
    if not isinstance(value, str) or not value or p.is_absolute() or '..' in p.parts or '\\' in value or '\x00' in value or p.as_posix() != value:
        raise ValueError('Unsafe/noncanonical payload path')
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root):
    out = {}
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ValueError('Symlink/special payload entry: ' + str(p))
        if p.is_file():
            out[p.relative_to(root).as_posix()] = digest(p)
    return out


def system_allowed(value):
    relative(value)
    return (value.startswith(METAL + '/') or value in (BOOT, 'Library/LaunchDaemons/com.navi48.translate.plist') or
            value in {APP + '/' + name for name in APP_FILES} or
            value in {'usr/local/navi48/' + name for name in TRANSLATOR_FILES})


def verify_config(payload, config):
    enabled = {}
    for index, entry in enumerate(config['Kernel']['Add']):
        if not entry['Enabled']:
            continue
        relative(entry['BundlePath'])
        relative(entry['PlistPath'])
        bundle = payload / 'EFI/OC/Kexts' / entry['BundlePath']
        info = plistlib.loads((bundle / entry['PlistPath']).read_bytes())
        identifier = info['CFBundleIdentifier']
        if identifier in enabled:
            raise ValueError('Duplicate enabled bundle identifier')
        enabled[identifier] = (index, info, bundle)
    required = {'as.vit9696.Lilu': '1.7.3', 'com.navi48.bringup': '0.0.664',
                'com.navi44.cppc': '0.0.1', 'as.acidanthera.BlueToolFixup': '2.7.3',
                'com.zxystd.IntelBTPatcher': '2.5.0', 'com.razvanccr.BluetoothWCN7850': '1.0.0',
                'com.f0xeri.QwzWifi': '0.0.26', 'com.f0xeri.QwzAirport': '0.3.16',
                'com.dhinakg.USBToolBox.map': '1.1'}
    for identifier, version in required.items():
        if identifier not in enabled or enabled[identifier][1]['CFBundleVersion'] != version:
            raise ValueError('Required unified driver absent/version mismatch: ' + identifier)
    for identifier in ('com.navi44.cppc', 'as.acidanthera.BlueToolFixup', 'com.zxystd.IntelBTPatcher'):
        if enabled[identifier][0] <= enabled['as.vit9696.Lilu'][0]:
            raise ValueError('Lilu plugin precedes Lilu')
    kernel = enabled['com.navi48.bringup'][2] / 'Contents/MacOS/Navi48Bringup'
    if digest(kernel) != '097b9b9fb73c04cb789d73d1a5ec930a4c21009f3a655eb08c97e39951639a16':
        raise ValueError('Wrong bringup identity/session candidate')
    cppc = enabled['com.navi44.cppc'][1]['IOKitPersonalities']['Navi44CPPC']
    if cppc['IOProviderClass'] != 'IOACPIPlatformDevice' or cppc['IOPropertyMatch'] != {'processor-index': 0}:
        raise ValueError('Wrong CPPC provider profile')
    for personality in enabled['com.f0xeri.QwzAirport'][1]['IOKitPersonalities'].values():
        if personality['QwzAirportBuilds'] != ['25G83']:
            raise ValueError('Wi-Fi ABI allowlist mismatch')
    bt = enabled['com.razvanccr.BluetoothWCN7850'][1]['IOKitPersonalities']
    if len(bt) != 1 or [(v.get('idVendor'), v.get('idProduct')) for v in bt.values()] != [(0x489, 0xe10a)]:
        raise ValueError('Wrong integrated Bluetooth USB match')
    usb = enabled['com.dhinakg.USBToolBox.map'][1]['IOKitPersonalities']
    expected = {'XH00': ('5:0:0', 14), 'XHC0': ('10:0:3', 4), 'XHC1': ('10:0:4', 4), 'XHC2': ('11:0:0', 1)}
    if set(usb) != set(expected):
        raise ValueError('USB controller map mismatch')
    for name, (bdf, count) in expected.items():
        if usb[name]['IOParentMatch'] != {'IOPropertyMatch': {'pcidebug': bdf}} or int.from_bytes(usb[name]['IOProviderMergeProperties']['port-count'], 'little') != count:
            raise ValueError('USB parent/count mismatch')
    acpi = config['ACPI']['Add']
    if any(x['Enabled'] for x in acpi if x['Path'] == 'SSDT-Disable_Network_GPP7.aml'):
        raise ValueError('Integrated Wi-Fi is still masked')
    if len([x for x in acpi if x['Enabled'] and x['Path'] == 'SSDT-B840-USB-S5.aml']) != 1:
        raise ValueError('Missing S5 candidate')
    patches = [x for x in config['ACPI']['Patch'] if x['Enabled'] and x.get('Find') == b'_PTS\x01']
    if len(patches) != 1 or patches[0]['Replace'] != b'ZPTS\x01' or patches[0]['Count'] != 1 or patches[0]['TableLength'] != 450765 or patches[0]['TableSignature'] != b'DSDT':
        raise ValueError('S5 rename scope mismatch')
    return len(required)


def verify_payload(payload):
    if payload.is_symlink():
        raise ValueError('Payload root must be a real directory')
    payload = payload.resolve()
    manifest_path = payload / 'manifest.json'
    if manifest_path.is_symlink():
        raise ValueError('Symlink manifest')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 1 or manifest.get('profile') != 'stage22-unified-v1' or manifest.get('status') != 'candidate-not-deployed':
        raise ValueError('Unknown payload schema/profile')
    actual = hashes(payload)
    actual.pop('manifest.json')
    expected = manifest['files']
    for path, sha in expected.items():
        relative(path)
        if not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('Invalid payload digest')
    if actual != expected:
        raise ValueError('Payload contents differ from manifest')
    modes = {p: (payload / p).stat().st_mode & 0o7777 for p in actual}
    if modes != manifest['file_modes'] or any(mode not in (0o644, 0o755) for mode in modes.values()):
        raise ValueError('Payload file modes differ or are unsafe')
    system = hashes(payload / 'system')
    if set(system) != set(manifest['baseline_system_files']) or set(system) != set(manifest['baseline_system_modes']):
        raise ValueError('Missing baseline for a system target')
    if any(not system_allowed(p) for p in system):
        raise ValueError('Unexpected system write target')
    required = ({APP + '/' + n for n in APP_FILES} | {'usr/local/navi48/' + n for n in TRANSLATOR_FILES} |
                {BOOT, 'Library/LaunchDaemons/com.navi48.translate.plist', METAL + '/Contents/Info.plist',
                 METAL + '/Contents/MacOS/Navi48Metal', METAL + '/Contents/Resources/libvulkan_radeon.dylib',
                 METAL + '/Contents/Resources/libn48xlate.dylib', METAL + '/Contents/_CodeSignature/CodeResources'})
    if not required <= set(system):
        raise ValueError('Incomplete unified system payload')
    info = plistlib.loads((payload / 'system' / METAL / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleVersion') != '24':
        raise ValueError('Unexpected Metal bundle version')
    if (manifest.get('os_build') != '25G83' or manifest.get('os_version') != '26.6.2' or
            manifest.get('efi_volume_uuid') != '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3'):
        raise ValueError('Different machine/build profile')
    for executable in (APP + '/navi48test', APP + '/n48nub', METAL + '/Contents/MacOS/Navi48Metal',
                       'usr/local/navi48/metal2vulkan', 'usr/local/navi48/spirv-val', 'usr/local/navi48/n48-llvm-dis'):
        if modes['system/' + executable] != 0o755:
            raise ValueError('Executable permission missing')
    if manifest['install_boot_job_last'] != BOOT:
        raise ValueError('Wrong boot job commit path')
    plan = json.loads((payload / 'efi-install-plan.json').read_text())
    if plan.get('baseline_config_sha256') != 'b8351af96eda59bdb278b48ed70a96fa0a02f6906dbbeb527c20a21112a9701d':
        raise ValueError('Unknown EFI baseline')
    for group in ('all_files', 'add_files'):
        for p in plan[group]:
            relative(p)
    if plan.get('schema') != 1 or plan['replace_last'] != 'OC/config.plist' or hashes(payload / 'EFI') != plan['all_files']:
        raise ValueError('EFI contents differ from additive install plan')
    if any(plan['all_files'].get(p) != sha for p, sha in plan['add_files'].items()):
        raise ValueError('Inconsistent EFI additions')
    if plan['config_sha256'] != plan['all_files']['OC/config.plist']:
        raise ValueError('Inconsistent config digest')
    config = plistlib.loads((payload / 'EFI/OC/config.plist').read_bytes())
    verify_config(payload, config)
    args = config['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82']['boot-args'].split()
    for token in ('navi48-multisession=1', 'navi48-apps=1', 'navi48-g5=1', 'n44-cppc=1', '-qwzon', '-btlfxboardid'):
        if token not in args:
            raise ValueError('Missing unified boot argument: ' + token)
    job = plistlib.loads((payload / 'system' / BOOT).read_bytes())
    if not job.get('RunAtLoad') or job.get('KeepAlive') is not False or job.get('UserName') != 'root':
        raise ValueError('Unexpected startup lifecycle/identity')
    return manifest, plan, system


def preflight(payload, efi):
    manifest, plan, system = verify_payload(payload)
    if subprocess.check_output(['sw_vers', '-buildVersion'], text=True).strip() != manifest['os_build']:
        raise ValueError('Different macOS build')
    info = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(efi.parent)]))
    if str(info.get('VolumeUUID', '')).upper() != manifest['efi_volume_uuid'] or efi.resolve() != Path(info['MountPoint']) / 'EFI':
        raise ValueError('Different EFI volume/mount path')
    for path, expected in manifest['dependency_hashes'].items():
        if digest(Path(path)) != expected:
            raise ValueError('Live dependency changed: ' + path)
    if hashes(Path('/') / METAL) != manifest['working_metal_files']:
        raise ValueError('Working Metal bundle changed')
    for path, expected in manifest['baseline_system_files'].items():
        target = Path('/') / path
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('Unexpected live target type: ' + path)
        actual = digest(target) if target.exists() else None
        if actual != expected:
            raise ValueError('Installed target changed: ' + path)
        if target.exists() and (target.stat().st_mode & 0o7777) != manifest['baseline_system_modes'][path]:
            raise ValueError('Installed target mode changed: ' + path)
    for path, expected in plan['all_files'].items():
        target = efi / path
        if path in plan['add_files']:
            if target.exists() and (not target.is_file() or target.is_symlink() or digest(target) != expected):
                raise ValueError('New EFI path conflicts: ' + path)
        else:
            old = plan['baseline_config_sha256'] if path == 'OC/config.plist' else expected
            if target.is_symlink() or not target.is_file() or digest(target) != old:
                raise ValueError('Baseline EFI changed: ' + path)
    if any((Path('/') / APP / name).exists() or (Path('/') / APP / name).is_symlink() for name in ('boot-state.json', 'disabled')):
        raise ValueError('Existing activation state/disable marker needs review; never reset automatically')
    return {'payload_files': len(manifest['files']), 'system_files': len(system), 'efi_additions': len(plan['add_files']),
            'efi_uuid_verified': True, 'efi_writable_now': bool(info.get('WritableVolume')),
            'baseline_verified': True, 'boot_session_unchanged': subprocess.check_output(['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip() == manifest['prepared_boot_uuid'],
            'unproven': manifest['unproven'], 'mutations': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    parser.add_argument('--efi', type=Path, default=Path('/Volumes/OCBOOT/EFI'))
    args = parser.parse_args()
    print(json.dumps(preflight(args.payload, args.efi), indent=2))
