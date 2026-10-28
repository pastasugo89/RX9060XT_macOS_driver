#!/usr/bin/env python3
"""Assemble an offline eight-session + Metal performance candidate; no install."""
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / 'research/builds/macos-20261028'
EFI = WORK / 'gpu-eight-efi-v1'
PERF = WORK / 'performance-fix-v2'
APP = 'Library/Application Support/Navi44/accelerated-trial'
SHELL = APP + '/accelerated-reboot-trial.sh'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(root):
    output = {}
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()): raise ValueError('Unsafe payload file ' + str(p))
        if p.is_file(): output[p.relative_to(root).as_posix()] = sha(p)
    return output

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); output = a.output.resolve()
    if output.exists() or not output.is_relative_to((ROOT / 'research/builds').resolve()):
        p.error('Use a new output inside research/builds')
    spec = importlib.util.spec_from_file_location('performance', Path(__file__).with_name('prepare-performance-fix.py'))
    perf = importlib.util.module_from_spec(spec); spec.loader.exec_module(perf)
    perf.verify(PERF, baseline=True)
    e = json.loads((EFI / 'manifest.json').read_text())
    if e['status'] != 'prepared-not-installed' or tree(EFI / 'EFI') != e['candidate_efi_files']:
        raise ValueError('EFI candidate changed')
    if tree(Path('/Volumes/OCBOOT/EFI')) != e['baseline_efi_files']:
        raise ValueError('Live EFI baseline changed')
    candidate = EFI / 'EFI/OC/Kexts' / e['new_kext'] / 'Contents/MacOS/Navi48Bringup'
    if sha(candidate) != e['candidate_sha256']:
        raise ValueError('EFI driver differs from build')
    tool = WORK / 'gpu-eight-repro-v1/navi48test'
    installed_tool = Path('/') / APP / 'navi48test'
    if not tool.is_file() or not installed_tool.is_file(): raise ValueError('Missing diagnostic tool')
    output.mkdir(parents=True)
    shutil.copytree(EFI / 'EFI', output / 'EFI')
    shutil.copytree(PERF / 'system', output / 'system')
    tool_target = output / 'system' / APP / 'navi48test'
    shutil.copyfile(tool, tool_target); tool_target.chmod(0o755)
    boot = output / 'system' / SHELL
    content = boot.read_text()
    if content.count('stage23-performance-v1') != 1:
        raise ValueError('Unexpected boot profile')
    boot.write_text(content.replace('stage23-performance-v1', 'stage24-eight-session-v1'))
    subprocess.run(['/bin/bash', '-n', str(boot)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(output / 'system/Library/GPUBundles/Navi48Metal.bundle')], check=True)
    baseline_system = json.loads((PERF / 'manifest.json').read_text())['baseline_system_files']
    baseline_system[APP + '/navi48test'] = sha(installed_tool)
    data = {'status':'prepared-not-installed', 'profile':'stage24-eight-session-v1',
            'files':tree(output), 'baseline_system_files':baseline_system,
            'baseline_efi_files':e['baseline_efi_files'], 'candidate_kext_sha256':sha(candidate),
            'hardware_validation':'not performed', 'installation_and_automatic_rollback':'not implemented'}
    (output / 'manifest.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    print('Combined candidate staged:', len(data['files']), 'files. No live changes.')

if __name__ == '__main__': main()
