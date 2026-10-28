#!/usr/bin/env python3
"""Prepare/check the measured bundle25 refinement; no install, service or GPU call."""
import argparse
import hashlib
import json
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / 'research/builds/macos-20261028'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
SCRIPT = 'Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'
OLD_MAIN = '664fdd194dfaaecb4cf25ef9e59c9f827c3267659db27708503fa19933cd5bd4'
CANDIDATE_MAIN = 'c9968d9c44d32c72568a165a57a42f75c654e5b47e644c0805e0ece750491dd2'
LIBS = {'libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
        'libn48xlate.dylib': '194c80d8b7a9f0c209adffd031602c1f83a8fb14de43eec39f49e860259b5890'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    result = {}
    if root.is_symlink():
        raise ValueError('Symlink root')
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ValueError('Special input: ' + str(p))
        if p.is_file():
            result[p.relative_to(root).as_posix()] = sha(p)
    return result


def verify(output, baseline=True):
    m = json.loads((output / 'manifest.json').read_text())
    if m['schema'] != 1 or m['profile'] != 'stage23-performance-v1' or m['status'] != 'prepared-not-installed':
        raise ValueError('Unexpected profile')
    actual = files(output); actual.pop('manifest.json')
    if actual != m['files']:
        raise ValueError('Payload content mismatch')
    system = files(output / 'system')
    if set(system) != set(m['baseline_system_files']):
        raise ValueError('Missing baseline')
    if any(not (p.startswith(METAL + '/') or p == SCRIPT) for p in system):
        raise ValueError('Unexpected installation target')
    bundle = output / 'system' / METAL
    if plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())['CFBundleVersion'] != '25':
        raise ValueError('Wrong bundle version')
    if sha(bundle / 'Contents/MacOS/Navi48Metal') != m['main_sha256']:
        raise ValueError('Wrong executable')
    for lib, expected in LIBS.items():
        if sha(bundle / 'Contents/Resources' / lib) != expected:
            raise ValueError('Wrong backend/translator')
    cache = bundle / 'Contents/Resources/spvcache'
    keys = {p.stem for p in cache.glob('*.spv')}
    if keys != {p.name[:-10] for p in cache.glob('*.meta.json')} or len(keys) != m['shader_pairs']:
        raise ValueError('Incomplete shader resource set')
    boot = (output / 'system' / SCRIPT).read_text()
    if ('PROFILE=stage23-performance-v1' not in boot or '"$bundle_version" == 25' not in boot or
            f'== {m["main_sha256"]} ]]' not in boot or OLD_MAIN in boot):
        raise ValueError('Boot guard differs from candidate')
    subprocess.run(['/bin/bash', '-n', str(output / 'system' / SCRIPT)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    if baseline:
        if subprocess.check_output(['sw_vers', '-buildVersion'], text=True).strip() != '25G83':
            raise ValueError('Different OS build')
        for relative, expected in m['baseline_system_files'].items():
            p = Path('/') / relative
            if p.is_symlink() or (sha(p) if p.is_file() else None) != expected:
                raise ValueError('Installed baseline changed: ' + relative)
        # Also catch removed/added baseline bundle entries, not just expected keys.
        if files(Path('/') / METAL) != m['baseline_metal_files']:
            raise ValueError('Installed bundle changed')
    return {'profile': m['profile'], 'bundle': 25, 'shader_pairs': m['shader_pairs'],
            'additional_observed_shaders': m['additional_observed_shaders'], 'files_verified': len(actual),
            'baseline_verified': baseline, 'installed': False, 'live_mutations': 0}


def prepare(output):
    output = output.absolute()
    if output.exists() or output.is_relative_to('/Library') or output.is_relative_to('/Volumes'):
        raise ValueError('Use a NEW local output directory')
    source = BUILD / 'postboot/perf-candidate/Navi48Metal.bundle'
    current = Path('/') / METAL
    if sha(current / 'Contents/MacOS/Navi48Metal') != OLD_MAIN or sha(source / 'Contents/MacOS/Navi48Metal') != CANDIDATE_MAIN:
        raise ValueError('Wrong working or candidate executable')
    # Snapshot only new pairs whose dumped AIR hash was independently checked.
    provenance = json.loads((BUILD / 'postboot/cache-provenance.json').read_text())
    target = output / 'system' / METAL
    shutil.copytree(source, target, copy_function=shutil.copyfile)
    cache = target / 'Contents/Resources/spvcache'
    count = 0
    for key, evidence in provenance.items():
        if not re.fullmatch('[a-f0-9]{64}', key) or evidence.get('air_sha256_verified') is not True:
            raise ValueError('Unverified AIR input')
        for ext in ('.spv', '.meta.json'):
            src, dst = Path('/private/var/tmp/n48m-spv') / (key + ext), cache / (key + ext)
            if src.is_symlink() or sha(src) != evidence['files'][ext]:
                raise ValueError('Runtime pair changed')
            if dst.exists() and sha(dst) != sha(src):
                raise ValueError('Conflicting translation for one AIR key')
        if not (cache / (key + '.spv')).exists():
            for ext in ('.spv', '.meta.json'):
                shutil.copyfile(Path('/private/var/tmp/n48m-spv') / (key + ext), cache / (key + ext))
            count += 1
    spvs = sorted(cache.glob('*.spv'))
    if {p.stem for p in spvs} != {p.name[:-10] for p in cache.glob('*.meta.json')}:
        raise ValueError('Unpaired shader metadata')
    for spv in spvs:
        metadata = json.loads(spv.with_suffix('.meta.json').read_text())
        if not isinstance(metadata, dict) or not isinstance(metadata.get('bindings'), list):
            raise ValueError('Malformed shader metadata')
        subprocess.run(['/usr/local/navi48/spirv-val', '--target-env', 'vulkan1.2', str(spv)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for p in target.rglob('*'):
        p.chmod(0o755 if p.is_dir() or p.name in ('Navi48Metal', *LIBS) else 0o644)
    subprocess.run(['xattr', '-cr', str(target)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(target)], check=True)
    main = sha(target / 'Contents/MacOS/Navi48Metal')
    installed_boot = Path('/') / SCRIPT
    boot = installed_boot.read_text()
    original_boot = (ROOT / 'tools/baremetal/navi44-desktop/accelerated-reboot-trial.sh').read_text()
    if boot != original_boot:
        raise ValueError('Installed activation job differs from reviewed source')
    for old, new in [('PROFILE=stage22-unified-v1', 'PROFILE=stage23-performance-v1'),
                     ('"$bundle_version" == 24', '"$bundle_version" == 25'), (OLD_MAIN, main)]:
        if boot.count(old) != 1:
            raise ValueError('Unexpected boot guard format')
        boot = boot.replace(old, new)
    boot = boot.replace('Stage22', 'Stage23').replace('version 24', 'version 25').replace('stage22', 'stage23')
    p = output / 'system' / SCRIPT; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(boot); p.chmod(0o644)
    review = output / 'review'; review.mkdir()
    for src in ('research/reports/cpu_gpu_optimization_research_20261028.md',
                'research/reports/postboot_driver_refinement_20261028.md', 'tools/baremetal/navi44-cppc/check.py'):
        shutil.copyfile(ROOT / src, review / Path(src).name)
    shutil.copyfile(BUILD / 'postboot/cache-provenance.json', review / 'cache-provenance.json')
    system = files(output / 'system')
    baseline = {relative: sha(Path('/') / relative) if (Path('/') / relative).is_file() else None for relative in system}
    manifest = {'schema': 1, 'profile': 'stage23-performance-v1', 'status': 'prepared-not-installed',
                'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'main_sha256': main, 'shader_pairs': len(spvs), 'additional_observed_shaders': count,
                'baseline_metal_files': files(current), 'baseline_system_files': baseline,
                'files': files(output), 'cpu_policy': 'retain verified autonomous EPP128',
                'requires_coordinated_install': [METAL, SCRIPT],
                'unproven': ['desktop performance improvement', 'black-band elimination', 'all future shaders/APIs']}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps(verify(output), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    if args.check:
        print(json.dumps(verify(args.output), indent=2))
    else:
        prepare(args.output)
