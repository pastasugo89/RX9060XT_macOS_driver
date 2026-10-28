#!/usr/bin/env python3
"""Prepare a new EFI whose installation adds files and replaces only config.plist.

Changed existing kext bundles receive versioned paths. Old boot files remain
intact, so a later installer can copy/verify additions before the config commit.
This tool never modifies either input, mounts a volume, or installs anything.
"""
import argparse
import hashlib
import json
import plistlib
import re
import shutil
from pathlib import Path

BASE_SHA = 'b8351af96eda59bdb278b48ed70a96fa0a02f6906dbbeb527c20a21112a9701d'


def files(root):
    result = {}
    for item in root.rglob('*'):
        if item.is_symlink():
            raise ValueError('Symlink in EFI input: ' + str(item))
        if item.is_file():
            result[item.relative_to(root).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
        elif not item.is_dir():
            raise ValueError('Special file in EFI input: ' + str(item))
    return result


def prepare(baseline, candidate, output, tag):
    baseline, candidate, output = [p.resolve() for p in (baseline, candidate, output)]
    if output.exists() or output in (baseline, candidate) or baseline in output.parents or candidate in output.parents or output.is_relative_to('/Volumes'):
        raise ValueError('Output must be a NEW local directory outside both inputs/Volumes')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', tag):
        raise ValueError('Invalid version tag')
    old = files(baseline)
    new = files(candidate)
    if old.get('OC/config.plist') != BASE_SHA:
        raise ValueError('Baseline differs from inspected OCBOOT config')
    config = plistlib.loads((candidate / 'OC/config.plist').read_bytes())
    mapping, bundles = {}, {}
    for entry in config['Kernel']['Add']:
        name = entry['BundlePath']
        if name in bundles:
            continue
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.suffix != '.kext':
            raise ValueError('Unexpected kext path')
        prefix = 'OC/Kexts/' + name + '/'
        contents = {p[len(prefix):]: sha for p, sha in new.items() if p.startswith(prefix)}
        if not contents:
            raise ValueError('Missing candidate bundle: ' + name)
        previous = {p[len(prefix):]: sha for p, sha in old.items() if p.startswith(prefix)}
        destination = name
        if previous and contents != previous:
            destination = str(path.with_name(path.stem + '-' + tag + '.kext'))
        target = 'OC/Kexts/' + destination + '/'
        if destination != name and any(p.lower().startswith(target.lower()) for p in old):
            raise ValueError('Versioned destination already exists')
        mapping[name] = destination
        bundles[name] = contents
    # Validate every non-kext candidate change before creating output.
    additions = []
    for path, sha in new.items():
        if path == 'OC/config.plist' or path.startswith('OC/Kexts/'):
            continue
        if path in old and old[path] != sha:
            raise ValueError('Would overwrite an existing boot file: ' + path)
        if path not in old:
            additions.append(path)
    for path in new:
        if path.startswith('OC/Kexts/') and not any(path.startswith('OC/Kexts/' + name + '/') for name in bundles):
            if new[path] != old.get(path):
                raise ValueError('Unreferenced changed kext file: ' + path)
    shutil.copytree(baseline, output)
    for name, destination in mapping.items():
        source = candidate / 'OC/Kexts' / name
        target = output / 'OC/Kexts' / destination
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
    for path in additions:
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate / path, target)
    for entry in config['Kernel']['Add']:
        entry['BundlePath'] = mapping[entry['BundlePath']]
    (output / 'OC/config.plist').write_bytes(plistlib.dumps(config, sort_keys=False))
    final = files(output)
    overwritten = sorted(p for p in old if final.get(p) != old[p])
    if overwritten != ['OC/config.plist']:
        raise ValueError('Output changed baseline files beyond the config: ' + str(overwritten))
    plan = {'schema': 1, 'baseline_config_sha256': BASE_SHA, 'config_sha256': final['OC/config.plist'],
            'bundle_paths': mapping, 'replace_last': 'OC/config.plist',
            'add_files': {p: sha for p, sha in final.items() if p not in old},
            'all_files': final}
    output.with_suffix('.install-plan.json').write_text(json.dumps(plan, indent=2, sort_keys=True) + '\n')
    print('Prepared additive EFI:', output)
    print('Changed bundle paths:', {a: b for a, b in mapping.items() if a != b})
    print('Existing boot files replaced: OC/config.plist only; new files:', len(plan['add_files']))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--tag', required=True)
    a = p.parse_args()
    prepare(a.baseline, a.candidate, a.output, a.tag)
