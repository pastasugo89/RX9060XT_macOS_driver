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
EFI = WORK / 'gpu-eight-efi-v4'
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
    installed_tool = Path('/') / APP / 'navi48test'
    if not installed_tool.is_file(): raise ValueError('Missing diagnostic tool')
    output.mkdir(parents=True)
    shutil.copytree(EFI / 'EFI', output / 'EFI')
    shutil.copytree(PERF / 'system', output / 'system')
    tool_target = output / 'system' / APP / 'navi48test'
    subprocess.run(['clang', '-arch', 'x86_64', '-mmacosx-version-min=12.0', '-O2', '-Wall', '-Wextra',
                    '-I', str(ROOT / 'cobalt64/src/navi48-bringup/src/apple'), '-framework', 'IOKit',
                    '-framework', 'CoreFoundation', '-o', str(tool_target),
                    str(ROOT / 'cobalt64/tools/pc/navi48test.c')], check=True)
    tool_target.chmod(0o755)
    job = Path('/Library/LaunchDaemons/org.navi44.accelerated-trial.plist')
    if job.is_symlink() or not job.is_file(): raise ValueError('Missing boot job')
    job_target = output / 'system/Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
    job_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(job, job_target); job_target.chmod(0o644)
    boot = output / 'system' / SHELL
    content = boot.read_text()
    if content.count('stage23-performance-v1') != 1:
        raise ValueError('Unexpected boot profile')
    boot.write_text(content.replace('stage23-performance-v1', 'stage24-eight-session-v1'))
    subprocess.run(['/bin/bash', '-n', str(boot)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(output / 'system/Library/GPUBundles/Navi48Metal.bundle')], check=True)
    baseline_system = json.loads((PERF / 'manifest.json').read_text())['baseline_system_files']
    baseline_system[APP + '/navi48test'] = sha(installed_tool)
    job_rel = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
    baseline_system[job_rel] = sha(job)
    modes = {}
    for rel, expected in baseline_system.items():
        target = Path('/') / rel
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('Unexpected system target type: ' + rel)
        if (sha(target) if target.is_file() else None) != expected:
            raise ValueError('System baseline changed: ' + rel)
        modes[rel] = target.stat().st_mode & 0o777 if target.exists() else None
    config_rel = 'OC/config.plist'
    old_efi, new_efi = e['baseline_efi_files'], e['candidate_efi_files']
    if set(old_efi) - set(new_efi): raise ValueError('EFI candidate removed files')
    additions = {k:v for k,v in new_efi.items() if k not in old_efi}
    if any(not (k.startswith('OC/Kexts/' + e['new_kext'] + '/') or k == 'RECOVERY/pre-eight-config.plist') for k in additions):
        raise ValueError('Unexpected EFI addition')
    if additions.get('RECOVERY/pre-eight-config.plist') != old_efi[config_rel]:
        raise ValueError('Recovery config is not the exact baseline')
    plan = {'baseline_config_sha256':old_efi[config_rel], 'config_sha256':new_efi[config_rel],
            'add_files':additions, 'all_files':new_efi}
    (output / 'efi-install-plan.json').write_text(json.dumps(plan, indent=2, sort_keys=True) + '\n')
    files = tree(output)
    data = {'schema':1, 'status':'prepared-not-installed', 'profile':'stage24-eight-session-v1',
            'files':files, 'file_modes':{k:(output/k).stat().st_mode & 0o777 for k in files},
            'prepared_boot_uuid':subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'], text=True).strip(),
            'efi_volume_uuid':'7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3',
            'baseline_system_files':baseline_system, 'baseline_system_modes':modes,
            'working_metal_files':tree(Path('/Library/GPUBundles/Navi48Metal.bundle')),
            'baseline_efi_files':old_efi, 'candidate_kext_sha256':sha(candidate),
            'hardware_validation':'not performed', 'installation_and_automatic_rollback':'not implemented'}
    (output / 'manifest.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    print('Combined candidate staged:', len(data['files']), 'files. No live changes.')

if __name__ == '__main__': main()
