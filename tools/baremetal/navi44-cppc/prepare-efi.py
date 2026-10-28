#!/usr/bin/env python3
"""Add the staged CPPC candidate to a NEW local combined EFI, never the boot disk."""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source_efi', type=Path)
p.add_argument('kext', type=Path)
p.add_argument('output_efi', type=Path)
a = p.parse_args()
source, kext, out = [x.resolve() for x in (a.source_efi, a.kext, a.output_efi)]
if out.exists() or out == source or source in out.parents or out.is_relative_to('/Volumes'):
    raise SystemExit('Output must be a NEW local staging directory outside source/Volumes')
info = plistlib.loads((kext / 'Contents/Info.plist').read_bytes())
assert info['CFBundleIdentifier'] == 'com.navi44.cppc' and info['CFBundleVersion'] == '0.0.1'
assert info['IOKitPersonalities']['Navi44CPPC']['IOPropertyMatch'] == {'processor-index': 0}
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(kext)], check=True)
config = plistlib.loads((source / 'OC/config.plist').read_bytes())
entries = config['Kernel']['Add']
assert any(x['Enabled'] and x['BundlePath'] == 'Lilu.kext' for x in entries)
assert not any(x['Enabled'] and any(s in x['BundlePath'] for s in ('Navi44CPPC', 'AMDRyzenCPUPowerManagement', 'AMDCpuPowerManagement')) for x in entries)
assert not (source / 'OC/Kexts/Navi44CPPC.kext').exists()
guid = '7C436110-AB2A-4BBB-A880-FE41995C9F82'
args = config['NVRAM']['Add'][guid]['boot-args'].split()
assert not any(x.startswith('n44-cppc=') or x == '-n44cppcoff' for x in args)
args.append('n44-cppc=1')
config['NVRAM']['Add'][guid]['boot-args'] = ' '.join(args)
entries.append({'Arch': 'x86_64', 'BundlePath': 'Navi44CPPC.kext', 'Comment': 'Ryzen7700 autonomous balanced CPPC candidate',
                'Enabled': True, 'ExecutablePath': 'Contents/MacOS/Navi44CPPC', 'MinKernel': '25.6.0',
                'MaxKernel': '25.6.99', 'PlistPath': 'Contents/Info.plist'})
shutil.copytree(source, out)
shutil.copytree(kext, out / 'OC/Kexts/Navi44CPPC.kext')
(out / 'OC/config.plist').write_bytes(plistlib.dumps(config, sort_keys=False))
manifest = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file()}
out.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared local combined candidate:', out)
