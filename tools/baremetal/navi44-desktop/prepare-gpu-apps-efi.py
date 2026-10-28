#!/usr/bin/env python3
"""Enable the audited Cobalt session/app/scheduling gates in a NEW local EFI.

Kernel defaults and isolation code are unchanged. The guarded boot job must also
seed the APP name list before login; flags alone do not admit any application.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source_efi', type=Path)
parser.add_argument('output_efi', type=Path)
a = parser.parse_args()
source, output = a.source_efi.resolve(), a.output_efi.resolve()
if output.exists() or output == source or source in output.parents or output.is_relative_to('/Volumes'):
    raise SystemExit('Output must be a NEW local staging directory outside source/Volumes')
config = plistlib.loads((source / 'OC/config.plist').read_bytes())
found = []
for entry in config['Kernel']['Add']:
    if not entry['Enabled']:
        continue
    info_path = source / 'OC/Kexts' / entry['BundlePath'] / entry['PlistPath']
    info = plistlib.loads(info_path.read_bytes())
    if info.get('CFBundleIdentifier') == 'com.navi48.bringup':
        assert info['CFBundleVersion'] == '0.0.664'
        found.append(entry)
assert len(found) == 1, 'Expected exact audited bringup build'
guid = '7C436110-AB2A-4BBB-A880-FE41995C9F82'
args = config['NVRAM']['Add'][guid]['boot-args'].split()
for name in ('navi48-multisession', 'navi48-apps', 'navi48-g5'):
    assert not any(x.startswith(name + '=') for x in args), 'Conflicting/repeated gate: ' + name
    args.append(name + '=1')
assert not any(x.startswith('navi48-g5credit=') for x in args), 'Use audited default one-job credit'
config['NVRAM']['Add'][guid]['boot-args'] = ' '.join(args)
shutil.copytree(source, output)
(output / 'OC/config.plist').write_bytes(plistlib.dumps(config, sort_keys=False))
manifest = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.rglob('*') if p.is_file()}
output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared local GPU application profile:', output)
