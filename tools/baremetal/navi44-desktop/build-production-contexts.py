#!/usr/bin/env python3
"""Build the logical-context kernel on the reproducible, accelerated 665 base.

Creates a new local directory only. Never writes EFI, installs/loads a kext or
reboots. A successful build and CPU tests do not qualify physical GPU behavior.
"""
import argparse
import hashlib
import importlib.util
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'research/builds/macos-20261028/gpu-eight-repro-v6'
BASE_EXEC = Path('build-eight/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup')
BASE_SHA = '607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24'
SOURCE = ROOT / 'cobalt64/src/navi48-bringup'
EFI = Path('/Volumes/OCBOOT/EFI/OC')
SDK = ROOT / 'research/builds/macos-20261027/sdk/MacKernelSDK'
BUILD_ROOT = ROOT / 'research/builds'
OVERLAY = (
    'Makefile',
    'src/Navi48NativeABI.h',
    'src/amd/native_s1c.cpp',
    'src/amd/native_s1c.h',
    'src/amd/native_g2_pure.h',
    'src/amd/native_hostimport_pure.h',
    'src/amd/production_vm_lease_pure.h',
    'src/amd/production_context_retire.h',
)
TREE_NAMES = ('src', 'firmware', 'shaders', 'tools')
TESTS = ('test-kernel-vmid-leases.py', 'test-kernel-context-close.py',
         'test-kernel-bo-release.py', 'test-kernel-wait-identity.py',
         'test-kernel-query-info.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_files(path):
    return {str(p.relative_to(path)): sha(p)
            for name in (*TREE_NAMES, 'Makefile', 'Info.plist')
            for p in ([path / name] if (path / name).is_file()
                      else sorted((path / name).rglob('*')))
            if p.is_file()}


def active_kernel(efi, expected_sha=BASE_SHA):
    config = efi / 'config.plist'
    data = plistlib.loads(config.read_bytes())
    entries = [e for e in data['Kernel']['Add'] if e.get('Enabled') and
               'Navi48Bringup' in e.get('BundlePath', '')]
    if len(entries) != 1:
        raise ValueError('Expected exactly one enabled Navi48Bringup entry')
    entry = entries[0]
    bundle = efi / 'Kexts' / entry['BundlePath']
    binary = bundle / entry['ExecutablePath']
    if not bundle.resolve().is_relative_to((efi / 'Kexts').resolve()):
        raise ValueError('Kernel bundle escapes EFI/Kexts')
    if not binary.resolve().is_relative_to(bundle.resolve()):
        raise ValueError('Kernel executable escapes its bundle')
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    if info['CFBundleVersion'] != '0.0.665' or sha(binary) != expected_sha:
        raise ValueError('Active EFI kernel differs from accelerated baseline 665')
    return {'bundle_path': entry['BundlePath'], 'kernel_sha256': sha(binary),
            'config_sha256': sha(config), 'version': info['CFBundleVersion']}


def copy_source(source, target):
    target.mkdir()
    for name in TREE_NAMES:
        shutil.copytree(source / name, target / name, symlinks=False)
    for name in ('Makefile', 'Info.plist'):
        shutil.copyfile(source / name, target / name)


def output_directory(path, build_root=BUILD_ROOT):
    out, allowed = path.resolve(), build_root.resolve()
    if not out.is_relative_to(allowed) or out == allowed or out.exists():
        raise ValueError('Use a NEW directory under research/builds')
    return out


def replace_exact(path, old, new, count):
    contents = path.read_text()
    if contents.count(old) != count:
        raise ValueError('Unexpected version markers in ' + str(path))
    path.write_text(contents.replace(old, new))


def overlay_candidate(candidate, source):
    """Preserve initialization/firmware; replace only the reviewed context files."""
    before = tree_files(candidate)
    for name in OVERLAY:
        shutil.copyfile(source / name, candidate / name)
    replace_exact(candidate / 'Info.plist', '<string>0.0.665</string>',
                  '<string>0.0.666</string>', 2)
    replace_exact(candidate / 'src/amd/native_s1c.h', 'kN1cKextBuild = 664;',
                  'kN1cKextBuild = 666;', 1)
    replace_exact(candidate / 'src/Navi48MetalNub.cpp', 'sizeof(N48MetalOps), 665u',
                  'sizeof(N48MetalOps), 666u', 2)
    after = tree_files(candidate)
    changed = {p for p in before.keys() | after.keys()
               if before.get(p) != after.get(p)}
    allowed = set(OVERLAY) | {'Info.plist', 'src/Navi48MetalNub.cpp'}
    if changed - allowed:
        raise ValueError('Candidate changed files outside the reviewed overlay')
    return sorted(changed)


def committed_overlay():
    """Reject uncommitted inputs instead of silently bundling unrelated work."""
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    for name in OVERLAY:
        path = SOURCE / name
        contents = subprocess.check_output(['git', 'show', revision + ':' +
                                            str(path.relative_to(ROOT))], cwd=ROOT)
        if contents != path.read_bytes():
            raise ValueError('Overlay input is not committed: ' + name)
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = output_directory(args.output)
    if sha(BASE / BASE_EXEC) != BASE_SHA:
        raise ValueError('Reference kernel binary changed')
    active = active_kernel(EFI)
    revision = committed_overlay()
    spec = importlib.util.spec_from_file_location('eight_repro', Path(__file__).with_name('build-eight-sessions.py'))
    repro = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repro)
    out.mkdir(parents=True)
    manifest = {'schema': 1, 'status': 'preparing-not-installable',
                'source_commit': revision, 'active_baseline': active,
                'preparer_sha256': sha(Path(__file__)),
                'test_scripts': {name: sha(ROOT / 'tools/baremetal/navi44-gpu-diagnostics' / name)
                                 for name in TESTS},
                'prepared_boot_uuid': subprocess.check_output(
                    ['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip(),
                'compiler': subprocess.check_output(['clang++', '--version'], text=True),
                'hardware_validation': 'not performed',
                'profile': {'hardware_slots': 8, 'logical_contexts': 64},
                'candidate_version': '0.0.666'}

    def save():
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    def build(directory, profile, logname):
        command = ['make', '-j4', 'NATIVE_SESSIONS=8', 'LOGICAL_CONTEXTS='+str(profile),
                   'BUILD=build', 'MKSDK='+str(SDK),
                   'XLAT12_DIR='+str(ROOT / 'cobalt64/src/xlat12'),
                   'SHADERCACHE_DIR='+str(ROOT / 'cobalt64/src/shadercache'),
                   'DCN41_DIR='+str(ROOT / 'cobalt64/src/dcn41')]
        manifest.setdefault('build_commands', {})[logname] = command
        with (out / logname).open('w') as log:
            subprocess.run(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=True)
        return directory / 'build/Navi48Bringup.kext'

    save()
    baseline = out / 'baseline-source'
    copy_source(BASE, baseline)
    manifest['baseline_inputs'] = tree_files(baseline)
    bundle = build(baseline, 8, 'baseline-build.log')
    sections = repro.mach_sections(bundle / 'Contents/MacOS/Navi48Bringup')
    if sections != repro.mach_sections(BASE / BASE_EXEC):
        raise ValueError('Rebuilt baseline sections differ from active kernel')
    if tree_files(baseline) != manifest['baseline_inputs']:
        raise ValueError('Baseline build changed recorded source inputs')
    manifest['baseline_sections'] = {'/'.join(part.decode() for part in k): v
                                     for k, v in sections.items()}
    candidate = out / 'candidate-source'
    copy_source(baseline, candidate)
    manifest['changed_source_files'] = overlay_candidate(candidate, SOURCE)
    manifest['candidate_inputs'] = tree_files(candidate)
    save()
    bundle = build(candidate, 64, 'candidate-build.log')
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    if info['CFBundleVersion'] != '0.0.666':
        raise ValueError('Candidate package version mismatch')
    manifest['cpu_tests'] = []
    for test in TESTS:
        command = ['python3', str(ROOT / 'tools/baremetal/navi44-gpu-diagnostics' / test),
                   '--kernel-source', str(candidate)]
        with (out / (test + '.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        manifest['cpu_tests'].append(test)
        save()
    if tree_files(candidate) != manifest['candidate_inputs']:
        raise ValueError('Candidate build changed recorded source inputs')
    if active_kernel(EFI) != active:
        raise ValueError('Active EFI changed during preparation')
    if subprocess.check_output(['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip() != manifest['prepared_boot_uuid']:
        raise ValueError('Boot session changed during preparation')
    manifest['candidate_binary_sha256'] = sha(bundle / 'Contents/MacOS/Navi48Bringup')
    manifest['candidate_bundle'] = str(bundle.relative_to(out))
    manifest['status'] = 'built-cpu-tested-not-installed-hardware-unverified'
    save()
    print(json.dumps({k: v for k, v in manifest.items() if not k.endswith('_inputs')}, indent=2))


if __name__ == '__main__':
    main()
