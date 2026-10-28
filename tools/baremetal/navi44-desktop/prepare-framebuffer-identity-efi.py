#!/usr/bin/env python3
"""Stage the PCI-bound framebuffer identity correction through the enabled bringup.

The approved auxiliary framebuffer stays in place; this does not rebuild AuxKC.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source_efi', type=Path)
p.add_argument('bringup_kext', type=Path)
p.add_argument('output_efi', type=Path)
a = p.parse_args()
source, kext, out = [x.resolve() for x in (a.source_efi, a.bringup_kext, a.output_efi)]
if out.exists() or source == out or source in out.parents or out.is_relative_to('/Volumes'):
    raise SystemExit('Output must be a NEW local staging directory outside source/Volumes')
config = plistlib.loads((source / 'OC/config.plist').read_bytes())
entries = [e for e in config['Kernel']['Add'] if e['BundlePath'] == 'Navi48Bringup.kext' and e['Enabled']]
assert len(entries) == 1
old = source / 'OC/Kexts/Navi48Bringup.kext'
assert hashlib.sha256((old / 'Contents/MacOS/Navi48Bringup').read_bytes()).hexdigest() == 'ab6e1f7aa0f61c7e38019342d8c9a6e68266d7a069a59fa9b758f593cd52f722'
info = plistlib.loads((kext / 'Contents/Info.plist').read_bytes())
assert info['CFBundleIdentifier'] == 'com.navi48.bringup' and info['CFBundleVersion'] == '0.0.664'
assert b'Navi44,FramebufferIdentityVerified' in (kext / 'Contents/MacOS/Navi48Bringup').read_bytes()
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(kext)], check=True)
shutil.copytree(source, out)
shutil.rmtree(out / 'OC/Kexts/Navi48Bringup.kext')
shutil.copytree(kext, out / 'OC/Kexts/Navi48Bringup.kext')
manifest = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file()}
out.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared local framebuffer identity profile:', out)
