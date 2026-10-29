#!/usr/bin/env python3
"""Exercise post-boot restoration on isolated copies; root, no live writes."""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('recovery', HERE / 'install-eight-combined.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
payload = ROOT / 'research/builds/macos-20261028/gpu-eight-combined-v8'
manifest = json.loads((payload/'manifest.json').read_text())
plan = json.loads((payload/'efi-install-plan.json').read_text())
old_boot = manifest['prepared_boot_uuid'].lower()
new_boot = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'

for restored_config in (False, True):
    with tempfile.TemporaryDirectory(prefix='navi44-postboot-test-', dir='/private/tmp') as tmp:
        base = Path(tmp); root = base/'root'; efi = base/'EFI'
        root.mkdir(); shutil.copytree('/Volumes/OCBOOT/EFI', efi)
        shutil.copytree(Path('/')/m.installer.check.METAL, root/m.installer.check.METAL)
        for name, expected in manifest['baseline_system_files'].items():
            if name.startswith(m.installer.check.METAL+'/') or expected is None: continue
            dest = root/name; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(Path('/')/name,dest)
        app = root/m.installer.check.APP
        app.mkdir(parents=True,exist_ok=True)
        state = app/'boot-state.json'
        saved = {'schema':1,'profile':'stage22-test','boot':old_boot,'phase':'stable'}
        m.state_api.write(state,saved)
        with patch.object(m.installer,'safe_parents',return_value=None), \
             patch.object(m.installer,'verify_fat_mount',return_value=None), \
             patch.object(m,'APP',app), patch.object(m,'EFI',efi), patch.object(m,'STATE',state), \
             patch.object(m,'SYSTEM_ROOT',root), patch.object(m,'current_boot',return_value=new_boot):
            tx=m.installer.Transaction(payload,efi,root,manifest,plan)
            m.installer.atomic_file(tx.work/'original-boot-state.json',(json.dumps(saved)+'\n').encode(),0o600)
            tx.run()
            trial={'schema':1,'profile':'stage24-eight-session-v1','boot':new_boot,'phase':'failed'}
            m.state_api.write(state,trial)
            if restored_config:
                shutil.copyfile(efi/'RECOVERY/pre-eight-config.plist',efi/'OC/config.plist')
            journal=json.loads((tx.work/'journal.json').read_text())
            assert journal['changed_system_files']
            changed=root/journal['changed_system_files'][0]
            original=changed.read_bytes(); changed.write_bytes(original+b'corrupt')
            try:
                m.restore(tx.work,False,True)
            except ValueError:
                pass
            else:
                raise AssertionError('Modified rollback target accepted')
            changed.write_bytes(original)
            report=m.restore(tx.work,False,True)
            assert report['restore_preflight'] and not report['mutations']
            report=m.restore(tx.work,True,True)
            assert report['restored'] and not report['rebooted']
            assert m.state_api.read(state)==saved
            assert json.loads((tx.work/'recovery-boot-state.json').read_text())==trial
            assert m.installer.check.digest(efi/'OC/config.plist')==plan['baseline_config_sha256']
            assert m.installer.check.hashes(root/m.installer.check.METAL)==manifest['working_metal_files']
            print('PASS post-boot restore with', 'baseline' if restored_config else 'candidate', 'EFI config')
