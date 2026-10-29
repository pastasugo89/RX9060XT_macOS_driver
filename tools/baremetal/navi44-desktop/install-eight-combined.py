#!/usr/bin/env python3
"""Install or restore the staged GPU trial, without rebooting or resetting state.

Default is read-only preflight. Apply requires root and an already-writable,
UUID-verified EFI. Recovery here is limited to the original, still-stable boot.
"""
import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
APP=Path('/Library/Application Support/Navi44/accelerated-trial')
EFI=Path('/Volumes/OCBOOT/EFI')
STATE=APP/'boot-state.json'

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

installer=module('installer',HERE/'install-unified-payload.py')
checker=module('eight_checker',HERE/'check-eight-combined.py')
state_api=module('state_api',HERE/'boot-state.py')

def current_boot():
    return subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],text=True).strip().lower()

def validate_stable(data,boot):
    if not data or data.get('phase')!='stable' or data.get('boot','').lower()!=boot.lower():
        raise ValueError('GPU boot state is not stable in this boot')
    return data

def install(payload, apply):
    if os.geteuid()!=0: raise ValueError('Root is required to verify persistent boot state')
    with state_api.transaction(STATE):
        before=validate_stable(state_api.read(STATE),current_boot())
        report=checker.check(payload,True)
        if not apply: return report
        m=json.loads((payload/'manifest.json').read_text())
        plan=json.loads((payload/'efi-install-plan.json').read_text())
        installer.verify_fat_mount(EFI,m['efi_volume_uuid'])
        tx=installer.Transaction(payload.resolve(),EFI,Path('/'),m,plan)
        installer.atomic_file(tx.work/'original-boot-state.json',(json.dumps(before,sort_keys=True)+'\n').encode(),0o600)
        work=tx.run()  # Transaction.run rolls back its own failures.
        try:
            if state_api.read(STATE)!=before or current_boot()!=m['prepared_boot_uuid'].lower():
                raise ValueError('Boot state changed during installation')
        except Exception:
            tx.rollback()
            raise
        return {'installed':True,'activated':False,'rebooted':False,'backup':str(work)}

def restore(work,apply):
    if os.geteuid()!=0: raise ValueError('Root is required to verify persistent boot state')
    work=work.absolute()
    if work.parent!=APP or not work.name.startswith('deployment-') or work.is_symlink():
        raise ValueError('Backup must be an original private deployment directory')
    installer.safe_parents(work/'journal.json')
    if not work.is_dir() or work.stat().st_uid!=0 or work.stat().st_mode & 0o077:
        raise ValueError('Unsafe backup directory')
    def read_meta(name):
        p=work/name
        if p.is_symlink() or not p.is_file() or p.stat().st_uid!=0 or p.stat().st_nlink!=1 or p.stat().st_mode & 0o077:
            raise ValueError('Unsafe backup metadata: '+name)
        return json.loads(p.read_text())
    with state_api.transaction(STATE):
        journal=read_meta('journal.json'); manifest=read_meta('original-manifest.json'); saved=read_meta('original-boot-state.json')
        boot=current_boot(); before=validate_stable(state_api.read(STATE),boot)
        if before!=saved or manifest['prepared_boot_uuid'].lower()!=boot:
            raise ValueError('Boot state changed since installation')
        if journal['phase']!='installed-not-activated': raise ValueError('Transaction is not restorable automatically')
        if journal['efi']!=str(EFI) or manifest['efi_volume_uuid']!=checker.UUID: raise ValueError('Wrong EFI target')
        plan=json.loads((work/'staged/efi-install-plan.json').read_text())
        if installer.check.digest(work/'original-config.plist')!=plan['baseline_config_sha256']:
            raise ValueError('EFI backup digest differs')
        system={p[7:]:v for p,v in manifest['files'].items() if p.startswith('system/')}
        if any(not installer.check.system_allowed(p) for p in system) or any(p not in system for p in journal['changed_system_files']):
            raise ValueError('Unexpected rollback targets')
        if not apply: return {'restore_preflight':True,'mutations':0,'backup':str(work)}
        installer.verify_fat_mount(EFI,manifest['efi_volume_uuid'])
        tx=installer.Transaction.__new__(installer.Transaction)
        tx.work,tx.efi,tx.root=work,EFI,Path('/')
        tx.manifest,tx.plan,tx.system=manifest,plan,system
        tx.changed=journal['changed_system_files']
        tx.config_changed,tx.metal_swapped=journal['config_changed'],journal['metal_swapped']
        tx.metal_backup=work/'metal-exchange.bundle'
        tx.rollback()
        return {'restored':True,'activated':False,'rebooted':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('payload',type=Path,nargs='?');p.add_argument('--restore-backup',type=Path);p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if bool(a.payload)==bool(a.restore_backup): p.error('Specify exactly one of payload or --restore-backup')
    print(json.dumps(restore(a.restore_backup,a.apply) if a.restore_backup else install(a.payload,a.apply),indent=2))
