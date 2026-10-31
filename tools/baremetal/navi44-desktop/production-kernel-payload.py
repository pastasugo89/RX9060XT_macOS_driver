#!/usr/bin/env python3
"""Prepare/check the kernel-666 trial without changing EFI or the live system."""
import argparse
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
NEW = 'Navi48Bringup-contexts-0.0.666.kext'
RECOVERY = 'RECOVERY/pre-contexts-666-config.plist'
KERNEL_SHA = '3ddcb7b087683c0e7a6416232534569d3aca37b747787669711db34d8f2d5f51'
BASE_SHA = '607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24'


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


def guard_text(original, probe_sha):
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    replace('PROFILE=stage25-archive-boundary-v1', 'PROFILE='+PROFILE)
    replace("echo 'CANDIDATE=stage25-archive-boundary'", "echo 'CANDIDATE=stage26-logical-contexts'")
    marker = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    replace(marker, marker + '\n' + r'''printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(0\.0\.666\)' || { echo 'STOP expected kernel 666'; exit 1; }''')
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


def verify(payload, live=False, efi=EFI, system_root=Path('/')):
    if payload.is_symlink(): raise ValueError('Symlink payload')
    m = json.loads((payload/'manifest.json').read_text())
    if m.get('schema') != 1 or m.get('profile') != PROFILE or m.get('status') != 'prepared-not-installed':
        raise ValueError('Unexpected kernel payload profile')
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
    for name, digest in base.items():
        if not safe(name) or (name != 'OC/config.plist' and staged.get(name) != digest):
            raise ValueError('Original EFI path changed: '+name)
    additions = {k:v for k,v in staged.items() if k not in base}
    if additions != m['add_files'] or any(not (k.startswith('OC/Kexts/'+NEW+'/') or k == RECOVERY) for k in additions):
        raise ValueError('Unexpected EFI additions')
    if additions.get(RECOVERY) != base['OC/config.plist']: raise ValueError('Recovery config differs from original')
    original = plistlib.loads((payload/'EFI'/RECOVERY).read_bytes())
    baseline_config(original)['BundlePath'] = NEW
    if original != plistlib.loads((payload/'EFI/OC/config.plist').read_bytes()):
        raise ValueError('Unrelated boot configuration changed')
    bundle = payload/'EFI/OC/Kexts'/NEW
    if sha(bundle/'Contents/MacOS/Navi48Bringup') != KERNEL_SHA: raise ValueError('Unexpected kernel binary')
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != 'com.navi48.bringup' or info['CFBundleVersion'] != '0.0.666':
        raise ValueError('Unexpected kernel identity')
    subprocess.run(['codesign','--verify','--strict',str(bundle)],check=True)
    guard = (payload/'system'/GUARD).read_text()
    old_guard = payload/'evidence/original-guard.sh'
    if sha(old_guard) != m['system_before'][GUARD]['sha256'] or guard != guard_text(old_guard.read_text(),sha(payload/'system'/PROBE)):
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


def prepare(candidate, output):
    buildroot = (ROOT/'research/builds').resolve()
    output = output.resolve(); candidate = candidate.resolve()
    if output == buildroot or not output.is_relative_to(buildroot) or output.exists() or not candidate.is_relative_to(buildroot):
        raise ValueError('Use a new output and existing candidate under research/builds')
    build = json.loads((candidate/'manifest.json').read_text())
    if build.get('status') != 'built-cpu-tested-not-installed-hardware-unverified' or build.get('profile') != {'hardware_slots':8,'logical_contexts':64} or build.get('candidate_binary_sha256') != KERNEL_SHA or len(build.get('cpu_tests',[])) != 5 or len(build.get('baseline_sections',{})) != 7:
        raise ValueError('Candidate is not the verified kernel-666 build')
    if build['prepared_boot_uuid'].lower() != boot_uuid(): raise ValueError('Build belongs to another boot')
    source = candidate/'candidate-source'
    for name, digest in build['candidate_inputs'].items():
        if not safe(name) or sha(source/name) != digest: raise ValueError('Candidate source changed')
    bundle = candidate/build['candidate_bundle']
    if not bundle.resolve().is_relative_to(candidate) or sha(bundle/'Contents/MacOS/Navi48Bringup') != KERNEL_SHA:
        raise ValueError('Candidate bundle changed')
    before = tree(EFI)
    config = plistlib.loads((EFI/'OC/config.plist').read_bytes()); entry = baseline_config(config)
    if sha(EFI/'OC/Kexts'/OLD/entry['ExecutablePath']) != BASE_SHA or before['OC/config.plist'] != build['active_baseline']['config_sha256']:
        raise ValueError('Working EFI is not the compiled baseline')
    if (EFI/'OC/Kexts'/NEW).exists() or (EFI/RECOVERY).exists(): raise ValueError('Candidate/recovery EFI paths already exist')
    if any(x.get('BundlePath') == NEW for x in config['Kernel']['Add']): raise ValueError('Candidate already listed in config')
    original_guard = (Path('/')/GUARD).read_text()
    baseline_system = {name:metadata(Path('/')/name) for name in (GUARD,PROBE)}
    critical = {name:metadata(Path('/')/name) for name in CRITICAL}
    if any(v is None for v in critical.values()) or baseline_system[GUARD] is None: raise ValueError('Missing boot dependency')
    metal = tree(Path('/')/METAL)
    output.mkdir(parents=True)
    (output/'evidence').mkdir()
    shutil.copyfile(candidate/'manifest.json',output/'evidence/build-manifest.json')
    (output/'evidence/original-guard.sh').write_text(original_guard)
    shutil.copytree(EFI,output/'EFI')
    shutil.copytree(bundle,output/'EFI/OC/Kexts'/NEW)
    shutil.copyfile(EFI/'OC/config.plist',output/'EFI'/RECOVERY)
    entry['BundlePath'] = NEW
    (output/'EFI/OC/config.plist').write_bytes(plistlib.dumps(config,sort_keys=False))
    verifier = ROOT/'research/ext/navi44-baremetal-stage1-candidate-20261027/tools/ocvalidate'
    subprocess.run([str(verifier),str(output/'EFI/OC/config.plist')],check=True)
    target = output/'system'/PROBE; target.parent.mkdir(parents=True)
    probe_source = ROOT/'tools/baremetal/navi44-gpu-diagnostics/context-isolation-probe.cpp'
    command = ['clang++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(source/'src'),str(probe_source),'-framework','IOKit','-framework','CoreFoundation','-o',str(target)]
    subprocess.run(command,check=True);target.chmod(0o755)
    with (output/'evidence/probe-self-test.log').open('w') as log:
        subprocess.run([str(target),'--self-test'],stdout=log,stderr=subprocess.STDOUT,check=True)
    guard = output/'system'/GUARD
    guard.write_text(guard_text(original_guard,sha(target)));guard.chmod(0o755)
    staged = tree(output/'EFI')
    files = tree(output)
    m = {'schema':1,'status':'prepared-not-installed','profile':PROFILE,
         'prepared_boot_uuid':boot_uuid(),'efi_volume_uuid':UUID,
         'baseline_efi_files':before,'candidate_efi_files':staged,
         'baseline_config_sha256':before['OC/config.plist'],
         'candidate_config_sha256':staged['OC/config.plist'],
         'add_files':{k:v for k,v in staged.items() if k not in before},
         'system_before':baseline_system,'critical_system_files':critical,
         'working_metal_files':metal,'files':files,
         'file_modes':{k:(output/k).stat().st_mode & 0o777 for k in files},
         'candidate_kernel_sha256':KERNEL_SHA,'probe_build_command':command,
         'probe_source_sha256':sha(probe_source),'preparer_sha256':sha(Path(__file__)),
         'hardware_validation':'not performed','installation':'not performed'}
    (output/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    verify(output,True)
    return m


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prep = commands.add_parser('prepare');prep.add_argument('--candidate',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    check = commands.add_parser('check');check.add_argument('payload',type=Path);check.add_argument('--live',action='store_true')
    args = parser.parse_args()
    m = prepare(args.candidate,args.output) if args.command == 'prepare' else verify(args.payload,args.live)
    print(json.dumps({'profile':m['profile'],'files_verified':len(m['files']),'installed':False,'hardware_validation':m['hardware_validation']},indent=2))


if __name__ == '__main__': main()
