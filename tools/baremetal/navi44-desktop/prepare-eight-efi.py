#!/usr/bin/env python3
"""Prepare an offline EFI trial tree; do not mount, install, or reboot."""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EFI = Path('/Volumes/OCBOOT/EFI')
BUILD = ROOT / 'research/builds/macos-20261028/gpu-eight-repro-v5'
OUTPUT_ROOT = (ROOT / 'research/builds').resolve()
NEW = 'Navi48Bringup-eight-0.0.665.kext'
RECOVERY = 'RECOVERY/pre-eight-config.plist'
EXPECTED_CONFIG = '8968c7e8f6a96670b374a39678b2ed9fb044848fe80e3c578313572287287d71'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(root):
    out = {}
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ValueError('Special file or symlink: ' + str(p))
        if p.is_file(): out[p.relative_to(root).as_posix()] = sha(p)
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(OUTPUT_ROOT):
        ap.error('Use a new path inside research/builds')
    config_path = EFI / 'OC/config.plist'
    if sha(config_path) != EXPECTED_CONFIG:
        raise ValueError('Live EFI config changed')
    manifest = json.loads((BUILD / 'manifest.json').read_text())
    if manifest['status'] != 'candidate-not-installed' or manifest.get('baseline_sections_verified') != 7:
        raise ValueError('Candidate baseline was not verified')
    bundle = BUILD / 'build-eight/Navi48Bringup.kext'
    candidate = bundle / 'Contents/MacOS/Navi48Bringup'
    if sha(candidate) != manifest['candidate_sha256']:
        raise ValueError('Candidate changed')
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    baseline = tree(EFI)
    config = plistlib.loads(config_path.read_bytes())
    matches = [x for x in config['Kernel']['Add'] if x.get('Enabled') and x.get('BundlePath') == manifest['baseline_bundle_path']]
    if len(matches) != 1:
        raise ValueError('Expected one active baseline entry')
    if NEW in {x['BundlePath'] for x in config['Kernel']['Add']} or (EFI / 'OC/Kexts' / NEW).exists():
        raise ValueError('Candidate path already exists')
    out.mkdir(parents=True)
    shutil.copytree(EFI, out / 'EFI', symlinks=False)
    shutil.copytree(bundle, out / 'EFI/OC/Kexts' / NEW, symlinks=False)
    recovery = out / 'EFI' / RECOVERY
    if recovery.exists(): raise ValueError('Recovery config already exists')
    recovery.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, recovery)
    if sha(recovery) != EXPECTED_CONFIG: raise ValueError('Recovery config differs from active config')
    matches[0]['BundlePath'] = NEW
    dest = out / 'EFI/OC/config.plist'
    dest.write_bytes(plistlib.dumps(config, sort_keys=False))
    verifier = ROOT / 'research/ext/navi44-baremetal-stage1-candidate-20261027/tools/ocvalidate'
    subprocess.run([str(verifier), str(dest)], check=True)
    candidate_files = tree(out / 'EFI')
    for name, digest in baseline.items():
        if name != 'OC/config.plist' and candidate_files.get(name) != digest:
            raise ValueError('Unrelated EFI file changed: ' + name)
    if tree(EFI) != baseline:
        raise ValueError('Live EFI changed during preparation')
    data = {'status':'prepared-not-installed', 'baseline_efi_files':baseline,
            'candidate_efi_files':candidate_files, 'candidate_sha256':manifest['candidate_sha256'],
            'old_kext_retained':manifest['baseline_bundle_path'], 'new_kext':NEW,
            'hardware_validation':'not performed', 'rollback':'not installed or automated'}
    (out / 'manifest.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    print('EFI staged; baseline files retained:', len(baseline), 'candidate files:', len(candidate_files))

if __name__ == '__main__': main()
