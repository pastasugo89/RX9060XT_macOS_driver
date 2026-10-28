#!/usr/bin/env python3
"""Assemble the complete local unified candidate. Never install, load or reboot."""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DESKTOP = Path(__file__).resolve().parent
BUILD = ROOT / 'research/builds/macos-20261028/unified'
APP = 'Library/Application Support/Navi44/accelerated-trial'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
BOOT = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
EXPECTED_METAL = {'Contents/MacOS/Navi48Metal': '664fdd194dfaaecb4cf25ef9e59c9f827c3267659db27708503fa19933cd5bd4',
                  'Contents/Resources/libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
                  'Contents/Resources/libn48xlate.dylib': '194c80d8b7a9f0c209adffd031602c1f83a8fb14de43eec39f49e860259b5890'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source, target):
    if source.is_symlink():
        raise ValueError('Symlink in payload input: ' + str(source))
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True, mode=0o755)
        for child in source.iterdir():
            copy(child, target / child.name)
    elif source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
    else:
        raise ValueError('Missing/special payload input: ' + str(source))


def hashes(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*') if p.is_file()}


def assemble(output):
    output = output.resolve()
    if output.exists() or output.is_relative_to('/Volumes') or output == ROOT or output in ROOT.parents:
        raise ValueError('Use a NEW local output directory')
    efi = BUILD / 'efi-release/EFI'
    plan_path = efi.with_suffix('.install-plan.json')
    plan = json.loads(plan_path.read_text())
    if hashes(efi) != plan['all_files']:
        raise ValueError('EFI differs from verified additive install plan')
    metal = BUILD / 'stage22-compile-wait/Navi48Metal.bundle'
    for relative, expected in EXPECTED_METAL.items():
        if sha(metal / relative) != expected:
            raise ValueError('Metal candidate component differs: ' + relative)
    if plistlib.loads((metal / 'Contents/Info.plist').read_bytes())['CFBundleVersion'] != '24':
        raise ValueError('Unexpected Metal candidate version')
    installed_app = Path('/') / APP
    translator = Path('/usr/local/navi48')
    if sha(translator / 'pc-translate.sh') != sha(ROOT / 'cobalt64/tools/native/autotranslate/pc-translate.sh'):
        raise ValueError('Installed translator differs from reviewed source')
    # The payload is local to this inspected machine/build; preserve exact
    # dependency hashes rather than promising a portable installer.
    dependencies = {str(p): sha(p) for p in (
        Path('/Library/Developer/CommandLineTools/usr/bin/clang'),
        Path('/Library/Developer/CommandLineTools/usr/bin/python3'),
        Path('/Library/Extensions/RDNA4FB-0.0.8-n44.kext/Contents/MacOS/RDNA4FB'),
        Path('/Library/Extensions/Navi48Accel-0.0.7.kext/Contents/MacOS/Navi48Accel'))}
    baseline_metal = {p: sha(Path('/') / METAL / p) for p in EXPECTED_METAL}
    if baseline_metal['Contents/MacOS/Navi48Metal'] != 'edc7255882ae823299212cde384a0bb89047de62c993cc618766302087e6e0cb':
        raise ValueError('Installed Metal no longer matches the working bundle23 baseline')
    copy(efi, output / 'EFI')
    copy(plan_path, output / 'efi-install-plan.json')
    copy(metal, output / 'system' / METAL)
    for name in ('accelerated-reboot-trial.sh', 'seed-gpu-apps.py', 'app-allowlist.json', 'boot-state.py'):
        copy(DESKTOP / name, output / 'system' / APP / name)
    for name in ('navi48test', 'n48nub'):
        copy(installed_app / name, output / 'system' / APP / name)
    copy(ROOT / 'tools/baremetal/navi44-cppc/check.py', output / 'system' / APP / 'cppc-check.py')
    copy(DESKTOP / 'org.navi44.accelerated-trial.plist', output / 'system' / BOOT)
    copy(DESKTOP / 'com.navi48.translate.plist', output / 'system/Library/LaunchDaemons/com.navi48.translate.plist')
    for file in translator.iterdir():
        if not file.is_file():
            raise ValueError('Unexpected translator directory entry')
        copy(file, output / 'system/usr/local/navi48' / file.name)
    for source in (DESKTOP / 'BOOT-STATE.md', DESKTOP / 'GPU-APPLICATIONS.md', DESKTOP / 'UNIFIED-DEPLOYMENT.md',
                   ROOT / 'tools/baremetal/qualcomm-wcn785x/README.md',
                   ROOT / 'tools/baremetal/navi44-cppc/README.md',
                   ROOT / 'research/reports/unified_repair_20261028.md'):
        name = source.parent.name + '-' + source.name
        copy(source, output / 'review' / name)
    copy(ROOT / 'cobalt64/LICENSE', output / 'review/LICENSE-Cobalt64.txt')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(output / 'system' / METAL)], check=True)
    subprocess.run([str(ROOT / 'research/ext/navi44-baremetal-stage1-candidate-20261027/tools/ocvalidate'),
                    str(output / 'EFI/OC/config.plist')], check=True)
    body = hashes(output)
    baseline_system, baseline_modes = {}, {}
    for relative in hashes(output / 'system'):
        target = Path('/') / relative
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('Unexpected installed target type: ' + str(target))
        baseline_system[relative] = sha(target) if target.exists() else None
        baseline_modes[relative] = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    manifest = {'schema': 1, 'profile': 'stage22-unified-v1', 'status': 'candidate-not-deployed',
                'os_build': '25G83', 'os_version': '26.6.2',
                'efi_volume_uuid': '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3',
                'prepared_boot_uuid': subprocess.check_output(['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip(),
                'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'dependency_hashes': dependencies, 'working_metal_hashes': baseline_metal,
                'install_boot_job_last': BOOT, 'files': body,
                'file_modes': {p: stat.S_IMODE((output / p).stat().st_mode) for p in body},
                'baseline_system_files': baseline_system, 'baseline_system_modes': baseline_modes,
                'working_metal_files': hashes(Path('/') / METAL),
                'unproven': ['black-band cause/removal', 'all future shader/API paths', 'physical wireless association/pairing',
                             'real CPPC energy/frequency behavior', 'fast-login and multi-boot graphics behavior']}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print('Assembled local candidate:', output)
    print('Manifest files:', len(body), '; no live installation or boot-state mutation')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    assemble(p.parse_args().output)
