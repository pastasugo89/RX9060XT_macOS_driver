#!/usr/bin/env python3
"""Validate offline trial and current baseline; no installation or GPU calls."""
import argparse
import hashlib
import json
import os
import plistlib
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
APP = 'Library/Application Support/Navi44/accelerated-trial'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
JOB = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
EFI = Path('/Volumes/OCBOOT/EFI')
NEW = 'Navi48Bringup-eight-0.0.665.kext'
OLD = 'Navi48Bringup-unified-20261028.kext'
UUID = '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(root):
    out = {}
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_dir() or p.is_file()): raise ValueError('Unsafe file: ' + str(p))
        if p.is_file(): out[p.relative_to(root).as_posix()] = sha(p)
    return out

def safe(rel):
    p = PurePosixPath(rel)
    return bool(rel) and not p.is_absolute() and '..' not in p.parts and '\\' not in rel and p.as_posix() == rel

def check(payload, live):
    if payload.is_symlink(): raise ValueError('Payload root is a symlink')
    payload = payload.resolve()
    m = json.loads((payload/'manifest.json').read_text())
    if m.get('schema') != 1 or m.get('status') != 'prepared-not-installed' or m.get('profile') != 'stage24-eight-session-v1':
        raise ValueError('Wrong candidate profile')
    actual = tree(payload); actual.pop('manifest.json')
    if actual != m['files'] or set(m['file_modes']) != set(actual): raise ValueError('Candidate files differ')
    for name in actual:
        if not safe(name) or (payload/name).stat().st_mode & 0o777 != m['file_modes'][name]:
            raise ValueError('Candidate path or mode differs: ' + name)
    plan = json.loads((payload/'efi-install-plan.json').read_text())
    if tree(payload/'EFI') != plan['all_files'] or plan['all_files']['OC/config.plist'] != plan['config_sha256']:
        raise ValueError('EFI plan differs')
    base = m['baseline_efi_files']; additions = {k:v for k,v in plan['all_files'].items() if k not in base}
    if additions != plan['add_files'] or any(not (k.startswith('OC/Kexts/'+NEW+'/') or k == 'RECOVERY/pre-eight-config.plist') for k in additions):
        raise ValueError('Unexpected EFI additions')
    if additions.get('RECOVERY/pre-eight-config.plist') != base['OC/config.plist']:
        raise ValueError('Recovery config is not the exact baseline')
    for k,v in base.items():
        if k != 'OC/config.plist' and plan['all_files'].get(k) != v: raise ValueError('EFI baseline changed: '+k)
    if plan['baseline_config_sha256'] != base['OC/config.plist']: raise ValueError('Bad original config')
    bundle = payload/'EFI/OC/Kexts'/NEW
    if sha(bundle/'Contents/MacOS/Navi48Bringup') != m['candidate_kext_sha256']:
        raise ValueError('Wrong kernel binary')
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != 'com.navi48.bringup' or info['CFBundleVersion'] != '0.0.665':
        raise ValueError('Wrong kernel identity')
    subprocess.run(['codesign','--verify','--strict',str(bundle)], check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(payload/'system'/METAL)], check=True)
    boot = (payload/'system'/APP/'accelerated-reboot-trial.sh').read_text()
    if 'PROFILE=stage24-eight-session-v1' not in boot or '"$bundle_version" == 25' not in boot:
        raise ValueError('Guard profile mismatch')
    metal_hash = sha(payload/'system'/METAL/'Contents/MacOS/Navi48Metal')
    if metal_hash not in boot: raise ValueError('Guard does not pin staged Metal')
    subprocess.run(['/bin/bash','-n',str(payload/'system'/APP/'accelerated-reboot-trial.sh')],check=True)
    system = {k[7:]:v for k,v in actual.items() if k.startswith('system/')}
    if set(system) != set(m['baseline_system_files']) or set(system) != set(m['baseline_system_modes']):
        raise ValueError('System target set differs')
    if any(not (k.startswith(METAL+'/') or k in (APP+'/navi48test', APP+'/accelerated-reboot-trial.sh', JOB)) for k in system):
        raise ValueError('Unexpected system target')
    if m['efi_volume_uuid'] != UUID: raise ValueError('Wrong EFI UUID')
    if live:
        if os.geteuid()!=0: raise ValueError('Live state verification requires root')
        if subprocess.check_output(['sw_vers','-buildVersion'],text=True).strip()!='25G83': raise ValueError('Different OS build')
        disk=plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(EFI.parent)]))
        if str(disk.get('VolumeUUID','')).upper()!=UUID or disk.get('MountPoint')!=str(EFI.parent): raise ValueError('Wrong EFI volume')
        if tree(EFI)!=base: raise ValueError('Live EFI baseline differs')
        current_config=plistlib.loads((EFI/'OC/config.plist').read_bytes())
        enabled=[e for e in current_config['Kernel']['Add'] if e.get('Enabled') and e.get('BundlePath')==OLD]
        if len(enabled)!=1: raise ValueError('Unexpected baseline kernel entry')
        enabled[0]['BundlePath']=NEW
        staged_config=plistlib.loads((payload/'EFI/OC/config.plist').read_bytes())
        if current_config!=staged_config: raise ValueError('Candidate changed unrelated boot configuration')
        if tree(Path('/')/METAL)!=m['working_metal_files']: raise ValueError('Live Metal baseline differs')
        for name, expected in m['baseline_system_files'].items():
            p=Path('/')/name
            if p.is_symlink() or (p.exists() and not p.is_file()): raise ValueError('Unsafe live target: '+name)
            if (sha(p) if p.is_file() else None)!=expected: raise ValueError('Live target differs: '+name)
            if (p.stat().st_mode & 0o777 if p.exists() else None)!=m['baseline_system_modes'][name]: raise ValueError('Live mode differs: '+name)
        now=subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],text=True).strip().lower()
        if now!=m['prepared_boot_uuid'].lower(): raise ValueError('Candidate prepared in a different boot')
        state=json.loads((Path('/')/APP/'boot-state.json').read_text())
        if state.get('phase')!='stable' or state.get('boot','').lower()!=now: raise ValueError('Current boot not marked stable')
        if (Path('/')/APP/'disabled').exists(): raise ValueError('GPU activation disabled')
    return {'profile':m['profile'],'files_verified':len(actual),'live_verified':live,'installed':False}

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('payload',type=Path);ap.add_argument('--live',action='store_true')
    a=ap.parse_args();print(json.dumps(check(a.payload,a.live),indent=2))
