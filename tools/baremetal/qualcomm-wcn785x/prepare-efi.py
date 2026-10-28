#!/usr/bin/env python3
"""Prepare Qualcomm drivers in a NEW local EFI; never install or load them.

Requires QwzAirport ABI check/return review on 25G83 before running.
Use the combined USB/PCI visibility candidate as input.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
for n in ('efi', 'qwz', 'bluetooth', 'companions', 'out'):
    p.add_argument('--' + n, type=Path, required=True)
a = p.parse_args()
efi, qwz, bluetooth, companions, out = [getattr(a, n).resolve() for n in ('efi', 'qwz', 'bluetooth', 'companions', 'out')]
if out.exists() or efi == out or efi in out.parents or out.is_relative_to('/Volumes'):
    raise SystemExit('Output must be a NEW local staging directory outside source/Volumes')
rev = subprocess.check_output(['git', '-C', str(qwz), 'rev-parse', 'HEAD'], text=True).strip()
assert rev == '3e2841227669e6c91ff39c4e7636c56d4d1dc8a2'
assert subprocess.check_output(['sysctl', '-n', 'kern.osversion'], text=True).strip() == '25G83'
for check in ('--check', '--returns'):
    result = subprocess.run(['python3', 'scripts/kc-abi.py', check], cwd=qwz, capture_output=True, text=True, check=True)
    if 'ERROR' in result.stdout or 'ERROR' in result.stderr:
        raise SystemExit('ABI check reported errors')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix('.abi' + check + '.log').write_text(result.stdout + result.stderr)
config = plistlib.loads((efi / 'OC/config.plist').read_bytes())
assert not any(x['Enabled'] and x['Path'] == 'SSDT-Disable_Network_GPP7.aml' for x in config['ACPI']['Add'])
usb = plistlib.loads((efi / 'OC/Kexts/USBMapB840.kext/Contents/Info.plist').read_bytes())
for name, bdf in {'XH00': '5:0:0', 'XHC0': '10:0:3', 'XHC1': '10:0:4', 'XHC2': '11:0:0'}.items():
    assert usb['IOKitPersonalities'][name]['IOParentMatch'] == {'IOPropertyMatch': {'pcidebug': bdf}}
modules = [('BlueToolFixup', companions / 'BlueToolFixup.kext'),
           ('IntelBTPatcher', companions / 'IntelBTPatcher.kext'),
           ('BluetoothWCN7850', bluetooth / 'BluetoothWCN7850.kext'),
           ('QwzWifi', qwz / 'build/QwzWifi.kext'), ('QwzAirport', qwz / 'build/QwzAirport.kext')]
existing = config['Kernel']['Add']
conflicts = ('Qwz', 'WCN7850', 'IntelBluetooth', 'IntelBTPatcher', 'BlueToolFixup', 'itlwm', 'AirportItlwm', 'BrcmPatchRAM')
assert not any(x['Enabled'] and any(s.lower() in x['BundlePath'].lower() for s in conflicts) for x in existing)
assert any(x['Enabled'] and x['BundlePath'] == 'Lilu.kext' for x in existing)
for name, source in modules:
    info = plistlib.loads((source / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleExecutable'] == name
    assert not (efi / 'OC/Kexts' / (name + '.kext')).exists()
shutil.copytree(efi, out)
for name, source in modules:
    bundle = out / 'OC/Kexts' / (name + '.kext')
    shutil.copytree(source, bundle)
    info_path = bundle / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    if name == 'QwzAirport':
        for personality in info['IOKitPersonalities'].values():
            assert personality['QwzAirportBuilds'] == ['25G241']
            personality['QwzAirportBuilds'] = ['25G83']
    if name == 'BluetoothWCN7850':
        match = info['IOKitPersonalities']['BluetoothWCN7850_0489_e10a']
        assert match['idVendor'] == 0x489 and match['idProduct'] == 0xe10a
        info['IOKitPersonalities'] = {'BluetoothWCN7850_0489_e10a': match}
    info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
    resources = bundle / 'Contents/Resources'
    resources.mkdir(exist_ok=True)
    if name.startswith('Qwz'):
        shutil.copyfile(qwz / 'LICENSE', resources / 'LICENSE-QwzWifi.txt')
        shutil.copyfile(qwz / 'NOTICE.md', resources / 'NOTICE-QwzWifi.md')
        shutil.copyfile(qwz / 'firmware/Notice.txt', resources / 'Notice-Qualcomm.txt')
        shutil.copyfile(qwz / 'airport/CREDITS', resources / 'CREDITS-Airport.txt')
    elif name == 'BluetoothWCN7850':
        # Sources/firmware notices are supplied explicitly alongside the built output.
        for file in ('LICENSE', 'LICENSE.QualcommAtheros_ath10k', 'NOTICE.Qualcomm-firmware.txt'):
            src = bluetooth / file
            if not src.is_file():
                raise SystemExit('Missing Bluetooth license input: ' + str(src))
            shutil.copyfile(src, resources / file)
    subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    existing.append({'Arch': 'x86_64', 'BundlePath': name + '.kext', 'Comment': 'WCN785x integrated candidate; hardware validation pending',
                     'Enabled': True, 'ExecutablePath': 'Contents/MacOS/' + name, 'MinKernel': '25.6.0',
                     'MaxKernel': '25.6.99', 'PlistPath': 'Contents/Info.plist'})
guid = '7C436110-AB2A-4BBB-A880-FE41995C9F82'
nv = config['NVRAM']['Add'].setdefault(guid, {})
args = nv.get('boot-args', '').split()
assert not any(x in args for x in ('-qwzoff', '-qcabtoff', '-qwzprobe'))
for arg in ('-qwzon', '-btlfxboardid'):
    if arg not in args:
        args.append(arg)
nv['boot-args'] = ' '.join(args)
nv['bluetoothExternalDongleFailed'] = b'\x00'
nv['bluetoothInternalControllerInfo'] = bytes(14)
delete = config['NVRAM']['Delete'].setdefault(guid, [])
for key in ('bluetoothExternalDongleFailed', 'bluetoothInternalControllerInfo'):
    if key not in delete:
        delete.append(key)
(out / 'OC/config.plist').write_bytes(plistlib.dumps(config, sort_keys=False))
manifest = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file()}
out.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared local candidate:', out)
