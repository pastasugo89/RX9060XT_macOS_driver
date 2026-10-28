#!/usr/bin/env python3
"""Rebuild an eight-session Navi44 trial from the exact active source baseline.

Writes only to a new local research/builds directory. Never installs, loads or
reboots; successful compilation is not a hardware safety or performance test.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'research/builds/macos-20261028/unified/bringup-model'
BASE_BINARY = BASE / 'build-console-guard/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup'
BASE_SHA = '097b9b9fb73c04cb789d73d1a5ec930a4c21009f3a655eb08c97e39951639a16'
EFI = Path('/Volumes/OCBOOT/EFI/OC')
SDK = ROOT / 'research/builds/macos-20261027/sdk/MacKernelSDK'
SRC = ROOT / 'cobalt64/src/navi48-bringup'
BUILD_ROOT = (ROOT / 'research/builds').resolve()

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def replace_once(path, old, new, count=1):
    s = path.read_text()
    if s.count(old) != count:
        raise ValueError('Unexpected baseline contents: ' + str(path))
    path.write_text(s.replace(old, new))

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    if not out.is_relative_to(BUILD_ROOT) or out == BUILD_ROOT or out.exists():
        ap.error('Use a NEW output under research/builds')
    if sha(BASE_BINARY) != BASE_SHA:
        raise ValueError('Source baseline binary is not the installed build')
    config = plistlib.loads((EFI / 'config.plist').read_bytes())
    entries = [v for v in config['Kernel']['Add'] if v.get('Enabled') and 'Navi48Bringup' in v.get('BundlePath', '')]
    if len(entries) != 1:
        raise ValueError('Unexpected active Navi48Bringup entries')
    e = entries[0]
    current = EFI / 'Kexts' / e['BundlePath'] / e['ExecutablePath']
    if sha(current) != BASE_SHA:
        raise ValueError('Active EFI baseline differs; stop')
    out.mkdir(parents=True)
    for name in ('src', 'firmware', 'shaders', 'tools'):
        shutil.copytree(BASE / name, out / name, symlinks=False)
    shutil.copyfile(BASE / 'Info.plist', out / 'Info.plist')
    shutil.copyfile(SRC / 'Makefile', out / 'Makefile')
    for name in ('native_s1c.cpp', 'native_g2_pure.h'):
        shutil.copyfile(SRC / 'src/amd' / name, out / 'src/amd' / name)
    replace_once(out / 'Info.plist', '<string>0.0.664</string>', '<string>0.0.665</string>', 2)
    replace_once(out / 'src/amd/native_s1c.h', 'kN1cKextBuild = 664;', 'kN1cKextBuild = 665;')
    replace_once(out / 'src/Navi48MetalNub.cpp', 'sizeof(N48MetalOps), 664u', 'sizeof(N48MetalOps), 665u', 2)
    cmd = ['make', '-j4', 'NATIVE_SESSIONS=8', 'BUILD=build-eight', 'MKSDK=' + str(SDK),
           'XLAT12_DIR=' + str(ROOT / 'cobalt64/src/xlat12'),
           'SHADERCACHE_DIR=' + str(ROOT / 'cobalt64/src/shadercache'),
           'DCN41_DIR=' + str(ROOT / 'cobalt64/src/dcn41')]
    with (out / 'build.log').open('w') as log:
        subprocess.run(cmd, cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True)
    bundle = out / 'build-eight/Navi48Bringup.kext'
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    if info['CFBundleVersion'] != '0.0.665':
        raise ValueError('Build version mismatch')
    manifest = {'status':'candidate-not-installed', 'profile':'8 sessions; VMID 8..15',
                'baseline_kernel_sha256': BASE_SHA, 'baseline_config_sha256':sha(EFI / 'config.plist'),
                'baseline_bundle_path':e['BundlePath'], 'candidate_version':'0.0.665',
                'candidate_sha256':sha(bundle / 'Contents/MacOS/Navi48Bringup'),
                'hardware_validation':'not performed', 'build_command':cmd}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))

if __name__ == '__main__':
    main()
