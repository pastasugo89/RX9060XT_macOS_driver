#!/usr/bin/env python3
"""Prepare/check the logical-context kernel trial (0.0.666 or 0.0.667) without changing EFI or the live system.

`prepare --baseline-payload <verified earlier payload>` builds the baseline EFI from that payload's recorded hashes
instead of the mounted EFI (the EFI is not mounted and must not be touched). Such a payload is marked
live_efi_verified: false; installation must run `check --live` against the real EFI.
"""
import argparse
import copy
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'
PROBE = APP + '/context-isolation-probe'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
JOB = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
CRITICAL = (JOB, APP+'/boot-state.py', APP+'/navi48test', APP+'/n48nub', APP+'/seed-gpu-apps.py', APP+'/app-allowlist.json')
EFI = Path('/Volumes/OCBOOT/EFI')
UUID = '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3'
PROFILE = 'stage26-logical-contexts-v1'
OLD = 'Navi48Bringup-eight-0.0.665.kext'
BASE_SHA = '607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24'
BASE_CONFIG_SHA = '92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb'
# Each release: its kext bundle, its recovery copy of the 665 config, the reviewed kernel binary, the CPU-test count,
# the strings its binary must contain, and the exact list of config paths it changes (checked, never assumed).
RELEASES = {
    '0.0.666': {'new': 'Navi48Bringup-contexts-0.0.666.kext', 'recovery': 'RECOVERY/pre-contexts-666-config.plist',
                'kernel_sha': '3ddcb7b087683c0e7a6416232534569d3aca37b747787669711db34d8f2d5f51', 'tests': 5,
                'strings': (), 'edits': ['Kernel/Add/7/BundlePath'], 'guard': 'stage26', 'metal': None},
    '0.0.667': {'new': 'Navi48Bringup-contexts-0.0.667.kext', 'recovery': 'RECOVERY/pre-contexts-667-config.plist',
                'kernel_sha': '976b3375082c3f319f940b02f74fd5ff03155884a39feae771edfab62623f287',   # reviewed 0.0.667 build (db8b202)
                'tests': 6, 'strings': ('navi48-off', 'application budget', 'open refused (NoResources)'),
                'edits': ['Kernel/Add/7/BundlePath', 'Misc/Boot/PollAppleHotKeys'],
                # the LIVE bundle-30 guard (stage30-vonly-v1) is the base; its Metal expectations are bundle 30
                'guard': 'live', 'metal': {'Contents/MacOS/Navi48Metal': '8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230',
                                           'Contents/Resources/libn48xlate.dylib': '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a'}},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and p.as_posix() == name


def tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Missing/unsafe tree: '+str(root))
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ValueError('Unsafe file: '+str(p))
        if p.is_file(): result[p.relative_to(root).as_posix()] = sha(p)
    return result


def metadata(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Unsafe target: '+str(path))
    return {'sha256': sha(path), 'mode': path.stat().st_mode & 0o777} if path.exists() else None


def boot_uuid():
    return subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],text=True).strip().lower()


def baseline_config(data):
    entries = [e for e in data['Kernel']['Add'] if e.get('Enabled') and 'Navi48Bringup' in e.get('BundlePath','')]
    if len(entries) != 1 or entries[0]['BundlePath'] != OLD:
        raise ValueError('Expected exactly one active baseline-665 entry')
    return entries[0]


def diff_paths(a, b, prefix=''):
    """Paths (like Kernel/Add/7/BundlePath) at which two plist values differ."""
    if type(a) is not type(b):
        return [prefix]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f'{prefix}/{k}')
            else:
                out += diff_paths(a[k], b[k], f'{prefix}/{k}')
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [prefix]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f'{prefix}/{i}')
        return out
    return [] if a == b else [prefix]


def expected_config(original, rel):
    """The baseline boot configuration with exactly the release's listed edits."""
    config = copy.deepcopy(original)
    baseline_config(config)['BundlePath'] = rel['new']
    if 'Misc/Boot/PollAppleHotKeys' in rel['edits']:
        if config['Misc']['Boot'].get('PollAppleHotKeys') is not False:
            raise ValueError('Baseline PollAppleHotKeys is not false')
        config['Misc']['Boot']['PollAppleHotKeys'] = True   # Shift in the OpenCore picker boots with -x
    return config


PROBE_BLOCK = r'''[[ $(shasum -a 256 "$APP/context-isolation-probe" | cut -d " " -f 1) == PROBE_DIGEST ]] || { echo 'STOP context profile checker changed'; exit 1; }
profilecheck=$("$APP/context-isolation-probe" --check-profile 2>&1) || { echo "STOP dynamic context profile: $profilecheck"; exit 1; }
echo "CONTEXT_PROFILE_VERIFIED=$profilecheck"
logicalpage=$("$NT" accel sessstat 95 2>&1) || { echo "STOP logical context diagnostic page: $logicalpage"; exit 1; }
printf '%s\n' "$logicalpage" | grep -Eq 'slot / VMID / session[[:space:]]*:[[:space:]]*63[[:space:]]*/' || { echo 'STOP missing logical context 63'; exit 1; }
echo 'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64'
'''


def guard_live(original, probe_sha, version):
    """The live bundle-30 guard plus only the 0.0.667 expectations: the loaded-kext version and the capability probe
    (dynamic VMID, logical context 63). Profile name, Metal hashes and everything else are the live file's own."""
    build = version.rsplit('.', 1)[1]
    version_re = version.replace('.', r'\.')
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    marker = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    replace(marker, marker + '\n' + r'''printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(@RE@\)' || { echo 'STOP expected kernel @BUILD@'; exit 1; }'''
            .replace('@RE@', version_re).replace('@BUILD@', build))
    marker = 'fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)'
    replace(marker, PROBE_BLOCK.replace('PROBE_DIGEST', probe_sha) + '\n' + marker)
    return original


def make_guard(rel, original, probe_sha, version):
    return guard_live(original, probe_sha, version) if rel['guard'] == 'live' else guard_text(original, probe_sha, version)


def guard_text(original, probe_sha, version):
    """The stage26 guard transformation (0.0.666 payload only)."""
    build = version.rsplit('.', 1)[1]
    version_re = version.replace('.', r'\.')
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    replace('PROFILE=stage25-archive-boundary-v1', 'PROFILE='+PROFILE)
    replace("echo 'CANDIDATE=stage25-archive-boundary'", "echo 'CANDIDATE=stage26-logical-contexts'")
    marker = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    replace(marker, marker + '\n' + r'''printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(@RE@\)' || { echo 'STOP expected kernel @BUILD@'; exit 1; }'''
            .replace('@RE@', version_re).replace('@BUILD@', build))
    marker = 'fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)'
    probe = r'''[[ $(shasum -a 256 "$APP/context-isolation-probe" | cut -d " " -f 1) == PROBE_DIGEST ]] || { echo 'STOP context profile checker changed'; exit 1; }
profilecheck=$("$APP/context-isolation-probe" --check-profile 2>&1) || { echo "STOP dynamic context profile: $profilecheck"; exit 1; }
echo "CONTEXT_PROFILE_VERIFIED=$profilecheck"
logicalpage=$("$NT" accel sessstat 95 2>&1) || { echo "STOP logical context diagnostic page: $logicalpage"; exit 1; }
printf '%s\n' "$logicalpage" | grep -Eq 'slot / VMID / session[[:space:]]*:[[:space:]]*63[[:space:]]*/' || { echo 'STOP missing logical context 63'; exit 1; }
echo 'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64'
'''.replace('PROBE_DIGEST', probe_sha)
    replace(marker, probe+'\n'+marker)
    return original


def release_of(m):
    version = m.get('candidate_version', '0.0.666')
    if version not in RELEASES:
        raise ValueError('Unknown candidate release: '+version)
    return version, RELEASES[version]


def baseline_sources(snapshot):
    """The baseline EFI as recorded by an earlier verified payload: its baseline_efi_files (hashed from the live EFI
    when that payload was prepared). OC/config.plist comes from that payload's recovery copy. Returns {path: source}."""
    verify(snapshot, live=False)
    m = json.loads((snapshot/'manifest.json').read_text())
    _, rel = release_of(m)
    sources = {}
    for name, digest in m['baseline_efi_files'].items():
        if not safe(name):
            raise ValueError('Unsafe baseline path: '+name)
        path = snapshot/'EFI'/rel['recovery'] if name == 'OC/config.plist' else snapshot/'EFI'/name
        if sha(path) != digest:
            raise ValueError('Snapshot differs from its recorded baseline: '+name)
        sources[name] = path
    return sources


def verify(payload, live=False, efi=EFI, system_root=Path('/')):
    if payload.is_symlink(): raise ValueError('Symlink payload')
    m = json.loads((payload/'manifest.json').read_text())
    if m.get('schema') != 1 or m.get('profile') != PROFILE or m.get('status') != 'prepared-not-installed':
        raise ValueError('Unexpected kernel payload profile')
    version, rel = release_of(m)
    actual = tree(payload); actual.pop('manifest.json')
    if actual != m['files'] or set(actual) != set(m['file_modes']): raise ValueError('Payload inventory changed')
    for name in actual:
        if not safe(name) or not name.startswith(('EFI/','system/','evidence/')) or (payload/name).stat().st_mode & 0o777 != m['file_modes'][name]:
            raise ValueError('Payload path/mode changed: '+name)
    system = {p[7:] for p in actual if p.startswith('system/')}
    if system != {GUARD,PROBE} or set(m['system_before']) != system or set(m['critical_system_files']) != set(CRITICAL):
        raise ValueError('Unexpected system write or dependency set')
    if any(m['file_modes']['system/'+name] != 0o755 for name in system):
        raise ValueError('System executables require mode 755')
    base, staged = m['baseline_efi_files'], tree(payload/'EFI')
    if staged != m['candidate_efi_files'] or base['OC/config.plist'] != m['baseline_config_sha256'] or staged['OC/config.plist'] != m['candidate_config_sha256']:
        raise ValueError('EFI inventory changed')
    if base['OC/config.plist'] != BASE_CONFIG_SHA:
        raise ValueError('Baseline boot configuration is not the reviewed 665 configuration')
    for name, digest in base.items():
        if not safe(name) or (name != 'OC/config.plist' and staged.get(name) != digest):
            raise ValueError('Original EFI path changed: '+name)
    additions = {k:v for k,v in staged.items() if k not in base}
    if additions != m['add_files'] or any(not (k.startswith('OC/Kexts/'+rel['new']+'/') or k == rel['recovery']) for k in additions):
        raise ValueError('Unexpected EFI additions')
    if additions.get(rel['recovery']) != base['OC/config.plist']: raise ValueError('Recovery config differs from original')
    original = plistlib.loads((payload/'EFI'/rel['recovery']).read_bytes())
    staged_config = plistlib.loads((payload/'EFI/OC/config.plist').read_bytes())
    if [d[1:] for d in diff_paths(original, staged_config)] != rel['edits'] or staged_config != expected_config(original, rel):
        raise ValueError('Boot configuration differs from the reviewed edits')
    bundle = payload/'EFI/OC/Kexts'/rel['new']
    if rel['kernel_sha'] is None or sha(bundle/'Contents/MacOS/Navi48Bringup') != rel['kernel_sha']:
        raise ValueError('Unexpected kernel binary')
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != 'com.navi48.bringup' or info['CFBundleVersion'] != version:
        raise ValueError('Unexpected kernel identity')
    for name, digest in (rel['metal'] or {}).items():
        if m['working_metal_files'].get(name) != digest: raise ValueError('Working Metal is not the reviewed bundle 30: '+name)
    subprocess.run(['codesign','--verify','--strict',str(bundle)],check=True)
    guard = (payload/'system'/GUARD).read_text()
    old_guard = payload/'evidence/original-guard.sh'
    if sha(old_guard) != m['system_before'][GUARD]['sha256'] or guard != make_guard(rel, old_guard.read_text(), sha(payload/'system'/PROBE), version):
        raise ValueError('Activation guard differs from the reviewed transformation')
    subprocess.run(['/bin/bash','-n',str(payload/'system'/GUARD)],check=True)
    if m['efi_volume_uuid'] != UUID: raise ValueError('Unexpected EFI volume identity')
    if live:
        if boot_uuid() != m['prepared_boot_uuid']: raise ValueError('Payload prepared in another boot')
        if subprocess.check_output(['sw_vers','-buildVersion'],text=True).strip() != '25G83': raise ValueError('Different macOS build')
        volume = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(efi.parent)]))
        if volume.get('MountPoint') != str(efi.parent) or volume.get('VolumeUUID','').upper() != UUID or volume.get('FilesystemType') != 'msdos':
            raise ValueError('Wrong mounted EFI volume')
        if tree(efi) != base: raise ValueError('Live EFI differs from baseline')
        if tree(system_root/METAL) != m['working_metal_files']: raise ValueError('Working Metal changed')
        for name, expected in {**m['system_before'], **m['critical_system_files']}.items():
            if not safe(name) or metadata(system_root/name) != expected: raise ValueError('Live system dependency changed: '+name)
    return m


def prepare(candidate, output, baseline_payload=None):
    buildroot = (ROOT/'research/builds').resolve()
    output = output.resolve(); candidate = candidate.resolve()
    if output == buildroot or not output.is_relative_to(buildroot) or output.exists() or not candidate.is_relative_to(buildroot):
        raise ValueError('Use a new output and existing candidate under research/builds')
    build = json.loads((candidate/'manifest.json').read_text())
    version, rel = release_of(build)
    if (build.get('status') != 'built-cpu-tested-not-installed-hardware-unverified' or build.get('profile') != {'hardware_slots':8,'logical_contexts':64}
            or rel['kernel_sha'] is None or build.get('candidate_binary_sha256') != rel['kernel_sha'] or len(build.get('cpu_tests',[])) != rel['tests']
            or len(build.get('baseline_sections',{})) != 7 or not set(rel['strings']) <= set(build.get('required_strings', []))):
        raise ValueError('Candidate is not the verified kernel-%s build' % version)
    if build['prepared_boot_uuid'].lower() != boot_uuid(): raise ValueError('Build belongs to another boot')
    source = candidate/'candidate-source'
    for name, digest in build['candidate_inputs'].items():
        if not safe(name) or sha(source/name) != digest: raise ValueError('Candidate source changed')
    bundle = candidate/build['candidate_bundle']
    if not bundle.resolve().is_relative_to(candidate) or sha(bundle/'Contents/MacOS/Navi48Bringup') != rel['kernel_sha']:
        raise ValueError('Candidate bundle changed')
    if baseline_payload is None:
        sources = None
        before = tree(EFI)
        config_bytes = (EFI/'OC/config.plist').read_bytes()
    else:
        sources = baseline_sources(baseline_payload)
        before = {name: sha(path) for name, path in sources.items()}
        config_bytes = sources['OC/config.plist'].read_bytes()
    config = plistlib.loads(config_bytes); entry = baseline_config(config)
    if before.get('OC/Kexts/'+OLD+'/'+entry['ExecutablePath']) != BASE_SHA or before['OC/config.plist'] != build['active_baseline']['config_sha256']:
        raise ValueError('Working EFI is not the compiled baseline')
    if any(k.startswith('OC/Kexts/'+rel['new']+'/') or k == rel['recovery'] for k in before):
        raise ValueError('Candidate/recovery EFI paths already exist')
    if any(x.get('BundlePath') == rel['new'] for x in config['Kernel']['Add']): raise ValueError('Candidate already listed in config')
    original_guard = (Path('/')/GUARD).read_text()
    baseline_system = {name:metadata(Path('/')/name) for name in (GUARD,PROBE)}
    critical = {name:metadata(Path('/')/name) for name in CRITICAL}
    if any(v is None for v in critical.values()) or baseline_system[GUARD] is None: raise ValueError('Missing boot dependency')
    metal = tree(Path('/')/METAL)
    output.mkdir(parents=True)
    (output/'evidence').mkdir()
    shutil.copyfile(candidate/'manifest.json',output/'evidence/build-manifest.json')
    (output/'evidence/original-guard.sh').write_text(original_guard)
    efi_out = output/'EFI'
    if sources is None:
        shutil.copytree(EFI, efi_out)
    else:
        for name, path in sources.items():
            (efi_out/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, efi_out/name)
    if tree(efi_out) != before: raise ValueError('Staged baseline differs from the recorded baseline')
    shutil.copytree(bundle, efi_out/'OC/Kexts'/rel['new'])
    (efi_out/rel['recovery']).parent.mkdir(parents=True, exist_ok=True)
    (efi_out/rel['recovery']).write_bytes(config_bytes)
    (efi_out/'OC/config.plist').write_bytes(plistlib.dumps(expected_config(config, rel), sort_keys=False))
    verifier = ROOT/'research/ext/navi44-baremetal-stage1-candidate-20261027/tools/ocvalidate'
    subprocess.run([str(verifier), str(efi_out/'OC/config.plist')], check=True)
    target = output/'system'/PROBE; target.parent.mkdir(parents=True)
    probe_source = ROOT/'tools/baremetal/navi44-gpu-diagnostics/context-isolation-probe.cpp'
    command = ['clang++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(source/'src'),str(probe_source),'-framework','IOKit','-framework','CoreFoundation','-o',str(target)]
    subprocess.run(command,check=True);target.chmod(0o755)
    with (output/'evidence/probe-self-test.log').open('w') as log:
        subprocess.run([str(target),'--self-test'],stdout=log,stderr=subprocess.STDOUT,check=True)
    guard = output/'system'/GUARD
    if rel['metal'] and '"$bundle_version" == 30 ' not in original_guard: raise ValueError('Live guard does not expect Metal bundle 30')
    guard.write_text(make_guard(rel, original_guard, sha(target), version)); guard.chmod(0o755)
    staged = tree(efi_out)
    files = tree(output)
    m = {'schema':1,'status':'prepared-not-installed','profile':PROFILE,'candidate_version':version,
         'prepared_boot_uuid':boot_uuid(),'efi_volume_uuid':UUID,
         'baseline_efi_files':before,'candidate_efi_files':staged,
         'baseline_config_sha256':before['OC/config.plist'],
         'candidate_config_sha256':staged['OC/config.plist'],
         'config_edits':rel['edits'],
         'baseline_source':'live-efi' if sources is None else 'recorded-payload:'+baseline_payload.name,
         'live_efi_verified': sources is None,
         'add_files':{k:v for k,v in staged.items() if k not in before},
         'system_before':baseline_system,'critical_system_files':critical,
         'working_metal_files':metal,'files':files,
         'file_modes':{k:(output/k).stat().st_mode & 0o777 for k in files},
         'candidate_kernel_sha256':rel['kernel_sha'],'probe_build_command':command,
         'probe_source_sha256':sha(probe_source),'preparer_sha256':sha(Path(__file__)),
         'hardware_validation':'not performed','installation':'not performed'}
    (output/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    verify(output, live=sources is None)
    return m


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prep = commands.add_parser('prepare');prep.add_argument('--candidate',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    prep.add_argument('--baseline-payload',type=Path,help='offline: take the baseline EFI from this verified payload instead of the mounted EFI')
    check = commands.add_parser('check');check.add_argument('payload',type=Path);check.add_argument('--live',action='store_true')
    args = parser.parse_args()
    m = prepare(args.candidate,args.output,args.baseline_payload) if args.command == 'prepare' else verify(args.payload,args.live)
    print(json.dumps({'profile':m['profile'],'candidate_version':m.get('candidate_version','0.0.666'),'files_verified':len(m['files']),
                      'live_efi_verified':m.get('live_efi_verified',True),'installed':False,'hardware_validation':m['hardware_validation']},indent=2))


if __name__ == '__main__': main()
