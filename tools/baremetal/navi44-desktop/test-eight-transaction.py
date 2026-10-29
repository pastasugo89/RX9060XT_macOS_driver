#!/usr/bin/env python3
"""Exercise the real staged candidate on temporary copies, never live targets."""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('installer', HERE / 'install-unified-payload.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
check = installer.check
payload = ROOT / 'research/builds/macos-20261028/gpu-eight-combined-v6'
manifest = json.loads((payload / 'manifest.json').read_text())
plan = json.loads((payload / 'efi-install-plan.json').read_text())
assert manifest['status'] == 'prepared-not-installed'
assert check.hashes(payload / 'EFI') == plan['all_files']
assert check.hashes(Path('/Volumes/OCBOOT/EFI')) == manifest['baseline_efi_files']
assert check.hashes(Path('/') / check.METAL) == manifest['working_metal_files']
for rel, expected in manifest['baseline_system_files'].items():
    p = Path('/') / rel
    assert (check.digest(p) if p.is_file() else None) == expected, rel

for fail_at in (None, 'metal-swapped', 'config-written'):
    with tempfile.TemporaryDirectory(prefix='navi44-transaction-check-') as tmp:
        base = Path(tmp).resolve(); efi = base / 'EFI'; system = base / 'system'; system.mkdir()
        shutil.copytree('/Volumes/OCBOOT/EFI', efi)
        shutil.copytree(Path('/') / check.METAL, system / check.METAL)
        for rel, expected in manifest['baseline_system_files'].items():
            if rel.startswith(check.METAL + '/') or expected is None: continue
            target = system / rel; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path('/') / rel, target)
        def hook(phase):
            if phase == fail_at: raise RuntimeError('injected failure')
        tx = installer.Transaction(payload, efi, system, manifest, plan, hook)
        if fail_at:
            try: tx.run()
            except RuntimeError as e: assert str(e) == 'injected failure'
            else: raise AssertionError('injected failure not detected')
            assert check.digest(efi / 'OC/config.plist') == plan['baseline_config_sha256']
            assert check.hashes(system / check.METAL) == manifest['working_metal_files']
            for rel, expected in manifest['baseline_system_files'].items():
                p = system / rel
                assert (check.digest(p) if p.is_file() else None) == expected, rel
            print('PASS rollback after', fail_at)
        else:
            tx.run()
            assert check.hashes(efi) == plan['all_files']
            backup_config = efi / 'RECOVERY/pre-eight-config.plist'
            assert check.digest(backup_config) == plan['baseline_config_sha256']
            for rel in manifest['baseline_system_files']:
                assert check.digest(system / rel) == manifest['files']['system/' + rel], rel
            tx.rollback()
            assert check.digest(efi / 'OC/config.plist') == plan['baseline_config_sha256']
            assert check.hashes(system / check.METAL) == manifest['working_metal_files']
            print('PASS install and explicit rollback on real-payload copies')
