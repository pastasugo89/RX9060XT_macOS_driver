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
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'research/builds/macos-20261028/gpu-eight-repro-v6'
BASE_EXEC = Path('build-eight/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup')
BASE_SHA = '607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24'
BASE_CONFIG_SHA = '92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb'
BASE_BUNDLE = 'Navi48Bringup-eight-0.0.665.kext'
SOURCE = ROOT / 'cobalt64/src/navi48-bringup'
EFI = Path('/Volumes/OCBOOT/EFI/OC')
SDK = ROOT / 'research/builds/macos-20261027/sdk/MacKernelSDK'
BUILD_ROOT = ROOT / 'research/builds'
RELEASE = '0.0.666'   # default candidate; `--version 0.0.667` builds the admission candidate, `--version 0.0.668` the GPU-only placement
REQUIRED_STRINGS = (b'application budget', b'open refused (NoResources)', b'navi48-off',   # admission + kill switch
                    b'the hi pool could not take it')   # 0.0.668: the GPU-only fallback log (native_s1c.cpp place_fallback_log)
# 0.0.668 is built on the kernel installed by payload v3 (0.0.667): its binary and its boot configuration, both hashed in that payload's manifest.
INSTALLED_667 = {'bundle_path': 'Navi48Bringup-contexts-0.0.667.kext',
                 'kernel_sha256': '976b3375082c3f319f940b02f74fd5ff03155884a39feae771edfab62623f287',
                 'config_sha256': '5ea9932d7fd53e97062021a72c6613f76bb96a3ecccce12d942fa8b796d531c6', 'version': '0.0.667'}
OVERLAY = (
    'Makefile',
    'src/Navi48NativeABI.h',
    'src/Navi48NativeClient.cpp',          # 0.0.666 admission (c440e35)
    'src/Navi48NativeClient.hpp',          # 0.0.666 admission (c440e35): changes the client's layout
    'src/amd/native_s1c.cpp',
    'src/amd/native_s1c.h',
    'src/amd/native_g2_pure.h',
    'src/amd/native_g4_pure.h',            # 0.0.666 admission (c440e35): the application budget
    'src/amd/native_hostimport_pure.h',
    'src/amd/native_open_policy_pure.h',   # 0.0.666 admission (c440e35)
    'src/amd/production_vm_lease_pure.h',
    'src/amd/production_context_retire.h',
)
TREE_NAMES = ('src', 'firmware', 'shaders', 'tools')
TESTS = ('test-kernel-vmid-leases.py', 'test-kernel-context-close.py',
         'test-kernel-bo-release.py', 'test-kernel-wait-identity.py',
         'test-kernel-query-info.py', 'test-kernel-app-admission.py')


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


def release_build(version):
    """The build number that goes with a candidate version (0.0.666, 0.0.667, 0.0.668)."""
    if not re.fullmatch(r'0\.0\.66[678]', version):
        raise ValueError('Unsupported candidate version: ' + version)
    return int(version.rsplit('.', 1)[1])


def recorded_active_baseline(path):
    """EFI is not mounted: take the active 665 kernel from a verified earlier manifest instead of the live EFI."""
    recorded = json.loads(path.read_text())['active_baseline']
    expected = {'bundle_path': BASE_BUNDLE, 'kernel_sha256': BASE_SHA,
                'config_sha256': BASE_CONFIG_SHA, 'version': '0.0.665'}
    if recorded != expected:
        raise ValueError('Recorded active baseline is not the accelerated 665 kernel')
    return recorded


def recorded_active_release(path, version):
    """The kernel a candidate replaces. 0.0.666/0.0.667: the 665 baseline (a manifest's active_baseline). 0.0.668: the
    installed 0.0.667 candidate, taken from payload v3's manifest, whose candidate EFI must hold exactly the reviewed hashes."""
    if version != '0.0.668':
        return recorded_active_baseline(path)
    manifest = json.loads(path.read_text())
    efi = manifest.get('candidate_efi_files', {})
    kernel = 'OC/Kexts/%s/Contents/MacOS/Navi48Bringup' % INSTALLED_667['bundle_path']
    if (manifest.get('candidate_version') != '0.0.667' or efi.get('OC/config.plist') != INSTALLED_667['config_sha256']
            or efi.get(kernel) != INSTALLED_667['kernel_sha256']):
        raise ValueError('Manifest is not the installed 0.0.667 candidate (payload v3)')
    return dict(INSTALLED_667)


def overlay_candidate(candidate, source, version=RELEASE):
    """Preserve initialization/firmware; replace only the reviewed context files."""
    build = release_build(version)
    before = tree_files(candidate)
    for name in OVERLAY:
        shutil.copyfile(source / name, candidate / name)
    replace_exact(candidate / 'Info.plist', '<string>0.0.665</string>',
                  '<string>' + version + '</string>', 2)
    replace_exact(candidate / 'src/amd/native_s1c.h', 'kN1cKextBuild = 664;',
                  'kN1cKextBuild = %d;' % build, 1)
    replace_exact(candidate / 'src/Navi48MetalNub.cpp', 'sizeof(N48MetalOps), 665u',
                  'sizeof(N48MetalOps), %du' % build, 2)
    after = tree_files(candidate)
    changed = {p for p in before.keys() | after.keys()
               if before.get(p) != after.get(p)}
    allowed = set(OVERLAY) | {'Info.plist', 'src/Navi48MetalNub.cpp'}
    if changed - allowed:
        raise ValueError('Candidate changed files outside the reviewed overlay')
    return sorted(changed)


KILL_SWITCH_FILE = 'src/Navi48Bringup.cpp'
KILL_SWITCH_ANCHOR = 'if (!PE_parse_boot_argn("navi48bringup", &on, sizeof(on)) || on == 0) return nullptr;\n'
KILL_SWITCH_START = '\t// 0.0.667: recovery kill switch.'
KILL_SWITCH_END = 'if (PE_parse_boot_argn("-x"'


def kill_switch_block(committed):
    """The probe() kill switch as committed (db8b202): from its comment to the end of its `if` line."""
    start = committed.index(KILL_SWITCH_START)
    return committed[start:committed.index('\n', committed.index(KILL_SWITCH_END, start)) + 1]


def apply_kill_switch(path, committed):
    """Add only db8b202's probe() kill switch. HEAD's Navi48Bringup.cpp is not the 665 file plus that commit
    (it lacks the 665 console and safety gates), so the commit is applied as its own hunk to the 665-based source."""
    block = kill_switch_block(committed)
    text = path.read_text()
    if committed.count(block) != 1 or text.count(KILL_SWITCH_ANCHOR) != 1 or KILL_SWITCH_START in text:
        raise ValueError('Kill switch anchor or block is not as committed')
    path.write_text(text.replace(KILL_SWITCH_ANCHOR, KILL_SWITCH_ANCHOR + block))
    return hashlib.sha256(block.encode()).hexdigest()


def classify_overlay(committed, working, blobs, allow_working_tree):
    """The overlay inputs at HEAD (committed) against the working tree. Uncommitted files are refused unless the caller asks
    for them explicitly; then they are recorded with their sha256 and the git blob ids they will have once committed, so
    the commit can be checked against the candidate that was built from them."""
    uncommitted = sorted(name for name in OVERLAY if committed[name] != working[name])
    if uncommitted and not allow_working_tree:
        raise ValueError('Overlay input is not committed: ' + uncommitted[0])
    return {'source': 'working-tree' if uncommitted else 'committed', 'uncommitted': uncommitted,
            'sha256': {name: hashlib.sha256(working[name]).hexdigest() for name in OVERLAY},
            'blob_ids': dict(blobs)}


def overlay_provenance(allow_working_tree=False):
    """Reject uncommitted inputs instead of silently bundling unrelated work (unless --worktree-overlay is given)."""
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    committed, working, blobs = {}, {}, {}
    for name in OVERLAY:
        path = SOURCE / name
        committed[name] = subprocess.check_output(['git', 'show', revision + ':' + str(path.relative_to(ROOT))], cwd=ROOT)
        working[name] = path.read_bytes()
        blobs[name] = subprocess.check_output(['git', 'hash-object', str(path)], cwd=ROOT, text=True).strip()
    return revision, classify_overlay(committed, working, blobs, allow_working_tree)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', default=RELEASE, help='candidate CFBundleVersion: 0.0.666 (default), 0.0.667 or 0.0.668')
    parser.add_argument('--active-baseline-manifest', type=Path,
                        help='offline: the kernel the candidate replaces, from this verified manifest (EFI not mounted): the 665 '
                             'baseline manifest for 0.0.666/0.0.667; payload v3 (kernel-payload-v3/manifest.json) for 0.0.668, which is required there')
    parser.add_argument('--worktree-overlay', action='store_true',
                        help='accept overlay files that differ from HEAD (uncommitted review work); they are recorded with their sha256 and git blob ids')
    args = parser.parse_args()
    version = args.version
    release_build(version)
    out = output_directory(args.output)
    if sha(BASE / BASE_EXEC) != BASE_SHA:
        raise ValueError('Reference kernel binary changed')
    if version == '0.0.668' and not args.active_baseline_manifest:
        raise ValueError('0.0.668 is built on the installed 0.0.667 kernel: pass --active-baseline-manifest (payload v3 manifest)')
    if args.active_baseline_manifest:
        active = recorded_active_release(args.active_baseline_manifest, version)
        active_source = 'recorded:' + str(args.active_baseline_manifest)
    else:
        active = active_kernel(EFI)
        active_source = 'live-efi'
    revision, overlay = overlay_provenance(args.worktree_overlay)
    spec = importlib.util.spec_from_file_location('eight_repro', Path(__file__).with_name('build-eight-sessions.py'))
    repro = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repro)
    out.mkdir(parents=True)
    manifest = {'schema': 1, 'status': 'preparing-not-installable',
                'source_commit': revision, 'overlay': overlay, 'active_baseline': active,
                'preparer_sha256': sha(Path(__file__)),
                'test_scripts': {name: sha(ROOT / 'tools/baremetal/navi44-gpu-diagnostics' / name)
                                 for name in TESTS},
                'prepared_boot_uuid': subprocess.check_output(
                    ['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip(),
                'compiler': subprocess.check_output(['clang++', '--version'], text=True),
                'hardware_validation': 'not performed',
                'profile': {'hardware_slots': 8, 'logical_contexts': 64},
                'active_baseline_source': active_source,
                'candidate_version': version}

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
    manifest['changed_source_files'] = overlay_candidate(candidate, SOURCE, version)
    committed = subprocess.check_output(['git', 'show', revision + ':' + str((SOURCE / KILL_SWITCH_FILE).relative_to(ROOT))],
                                        cwd=ROOT, text=True)
    if kill_switch_block(committed) not in (SOURCE / KILL_SWITCH_FILE).read_text():
        raise ValueError('Working tree lacks the committed kill switch')
    manifest['kill_switch'] = {'commit': revision, 'file': KILL_SWITCH_FILE,
                               'block_sha256': apply_kill_switch(candidate / KILL_SWITCH_FILE, committed)}
    manifest['changed_source_files'] = sorted(manifest['changed_source_files'] + [KILL_SWITCH_FILE])
    manifest['candidate_inputs'] = tree_files(candidate)
    save()
    bundle = build(candidate, 64, 'candidate-build.log')
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    if info['CFBundleVersion'] != version:
        raise ValueError('Candidate package version mismatch')
    binary = (bundle / 'Contents/MacOS/Navi48Bringup').read_bytes()
    if any(text not in binary for text in REQUIRED_STRINGS):
        raise ValueError('Candidate binary lacks the required strings')
    manifest['required_strings'] = [text.decode() for text in REQUIRED_STRINGS]
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
    if active_source == 'live-efi' and active_kernel(EFI) != active:
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
