#!/usr/bin/env python3
"""Stage a controller-specific analog audio trial. Never install or load it."""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
import zipfile
from pathlib import Path

ARCHIVE_SHA = '9aaa01b245f4827b2de5edfdc028700b9bc8823f03bfb1daf280b8571f88adb0'
URL = 'https://github.com/CloverHackyColor/VoodooHDA/releases/download/Release368/VoodooHDA.kext-368.zip'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--archive', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
if hashlib.sha256(a.archive.read_bytes()).hexdigest() != ARCHIVE_SHA:
    p.error('Upstream release digest differs')
out = a.output.resolve()
if out.exists() or any(out.is_relative_to(base) for base in ['/Library', '/System', '/Volumes']):
    p.error('Use a NEW workspace staging directory')
with zipfile.ZipFile(a.archive) as z:
    for member in z.infolist():
        name = Path(member.filename)
        mode = member.external_attr >> 16
        if name.is_absolute() or '..' in name.parts or mode & 0o170000 == 0o120000:
            p.error('Unsafe archive entry')
    out.mkdir(parents=True)
    z.extractall(out / 'upstream')
bundle = out / 'candidate/VoodooHDA-Navi44Analog.kext'
bundle.parent.mkdir()
shutil.copytree(out / 'upstream/VoodooHDA.kext', bundle)
info = bundle / 'Contents/Info.plist'
d = plistlib.loads(info.read_bytes())
if d['CFBundleVersion'] != '3.6.8' or d['CFBundleIdentifier'] != 'org.voodoo.driver.VoodooHDA':
    raise ValueError('Unexpected upstream driver')
profile = d['IOKitPersonalities']['VoodooHDA']
profile.pop('IONameMatch', None)
profile['IOPCIPrimaryMatch'] = '0x15e31022'
profile['IOPCISecondaryMatch'] = '0xee571462'
profile['Boost'] = 0
profile['MixerValues']['PCM'] = 75
# Only the real integrated controller; no AMD GPU HDMI personality, no rename.
d['IOKitPersonalities'] = {'Navi44-Rear-Analog': profile}
info.write_bytes(plistlib.dumps(d, sort_keys=False))
# zipfile does not preserve executable modes; kext discovery needs them.
for entry in bundle.rglob('*'):
    entry.chmod(0o755 if entry.is_dir() else 0o644)
bundle.chmod(0o755)
(bundle / 'Contents/MacOS/VoodooHDA').chmod(0o755)
subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
manifest = {'status': 'prepared-not-installed', 'upstream_url': URL,
            'archive_sha256': ARCHIVE_SHA, 'os_build': '25G83',
            'controller': '1022:15e3', 'subsystem': '1462:ee57',
            'codec': 'MSI specification: ALC897; codec verb ID still unverified',
            'connector': 'rear jack', 'version': '3.6.8',
            'installation': 'Requires coordinated AuxKC trial; not an EFI-only payload',
            'runtime_validation': 'NOT TESTED', 'live_mutations': 0,
            'files': {str(f.relative_to(bundle)): hashlib.sha256(f.read_bytes()).hexdigest()
                      for f in bundle.rglob('*') if f.is_file()}}
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({k: manifest[k] for k in ['status', 'controller', 'subsystem', 'runtime_validation', 'live_mutations']}))
