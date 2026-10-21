#!/usr/bin/env python3
"""Prepare an offline EFI for a bounded Navi44 bring-up boot.

Boot-arg written by this script, and where the code reads each one (paths under cobalt64/):
  navi48bringup=1          src/navi48-bringup/src/Navi48Bringup.cpp:7351  (probe: off without it)
  navi48-stage=N           Navi48Bringup.cpp:7395
  navi48-interrupts=0|1    Navi48Bringup.cpp:7405  (always written; absent would mean 1)
  navi48-smu-full=1        Navi48Bringup.cpp:6939  (stage 9 only)
  navi48-vadd-ir=1         Navi48Bringup.cpp:6958  (stage 17 only)
  navi48-native=1          Navi48Bringup.cpp:6889  (S1b gate; conflict mask at :6902)
  navi48-gopsnap=1         src/navi48-bringup/src/dcn/navi48_dcn.cpp:322,344 (stage 1, read-only)
  navi48-metal=1           src/navi48-bringup/src/Navi48MetalNub.cpp:214 (publish gate; needs S1b kGateOn)
  navi48-metal-ws=1        src/navi48-bringup/src/Navi48NativeClient.cpp:64 (latched once; admits uid 88) and
                           tools/native/navi48accel/src/Navi48Accel.cpp:620 (ANY value blocks the aux framebuffer start)
  navi48-metal-disp=1      src/navi48-bringup/src/amd/native_disp.cpp:573 (native display route; flip GOP still open, FASI 4.2)
  navi48-aux=1|0           tools/native/navi48accel/src/Navi48Accel.cpp:86 (aux_enabled: only navi48-aux=0 turns it off)

Phases (metal_deploy_plan.md section 8, as corrected on 21/10/2026):
  P0  headless Metal, no display:  --native-s1b --metal
  P1  display adoption:            P0 + --primary --metal-disp   (blocked until the GOP flip, FASI 4.2)
  P2  WindowServer:                P1 + --metal-ws
  Recovery: --aux-kill (navi48-aux=0), a stage without --metal.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

# The complete set of navi48-* keys this script may write. Any other navi48-* flag in the result is refused.
ADMITTED_KEYS = ('navi48-stage', 'navi48-interrupts', 'navi48-smu-full', 'navi48-native', 'navi48-vadd-ir', 'navi48-gopsnap',
                 'navi48-metal', 'navi48-metal-ws', 'navi48-metal-disp', 'navi48-aux')
MANAGED_PREFIXES = tuple(k + '=' for k in ADMITTED_KEYS)
DEFAULT_VM = Path('/mnt/vm/images/macos-gpu-test')

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('stage', type=int, choices=(1, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17))
p.add_argument('--smu-full', action='store_true', help='Stage9 only: initialise default PMFW power management')
p.add_argument('--native-s1b', action='store_true', help='Stage17 only: run the bounded native VMID8 self-test (navi48-native=1)')
p.add_argument('--vadd-ir', action='store_true', help='Stage17 only: run bounded gfx1200 vadd_ir after baseline dispatch')
p.add_argument('--metal', action='store_true', help='Stage17 + --native-s1b: publish the Metal nub (navi48-metal=1), phase P0')
p.add_argument('--metal-disp', action='store_true', help='With --metal and --primary: native display route (navi48-metal-disp=1), phase P1')
p.add_argument('--metal-ws', action='store_true', help='With --metal and --primary: admit the WindowServer client (navi48-metal-ws=1), phase P2')
p.add_argument('--aux-kill', action='store_true', help='Kill switch for the aux kext Navi48Accel (navi48-aux=0); not with --metal')
p.add_argument('--primary', action='store_true', help='OpenCore UEFI Output Resolution=Max and a visible picker (Timeout > 0), for the RX 9060 XT as the only display (launcher N4X_GPU_PRIMARY=1)')
p.add_argument('--gopsnap', action='store_true', help='Stage1 only: read-only GOP snapshot at kext attach (navi48-gopsnap=1), no register write')
p.add_argument('--interrupts', action='store_true', help='Enable the kext IH/MSI path for this bounded boot (navi48-interrupts=1)')
p.add_argument('--kext', type=Path, help='Inject a locally built Navi44 Navi48Bringup.kext while the VM is off')
p.add_argument('--vm-dir', type=Path, default=DEFAULT_VM, help='VM image directory (default: the test image). A copy can be used for tests.')
p.add_argument('--csr-active-config', type=lambda v: int(v, 0), choices=(0x01, 0x02, 0x03), default=None,
               help='TEST VM ONLY, explicit opt-in (default: unchanged). Writes csr-active-config (SIP bits): 0x01 = CSR_ALLOW_UNTRUSTED_KEXTS '
                    '(ad-hoc aux kext loads), 0x02 = CSR_ALLOW_UNRESTRICTED_FS (write /Library/GPUBundles), 0x03 = both. Restore 0 from the EFI backup.')
p.add_argument('--amfi-get-out-of-my-way', action='store_true',
               help='TEST VM ONLY, explicit opt-in (default: unchanged). Adds boot-arg amfi_get_out_of_my_way=1 (as in Cobalt64 display variants); needed only if AMFI blocks the ad-hoc bundle/dylibs.')
p.add_argument('--dry-run', action='store_true', help='Compute and print the boot-args and the checks, write nothing')
args = p.parse_args()

# ---- combinations: each assertion names the rule it enforces ----
assert not args.smu_full or args.stage == 9
assert not args.native_s1b or args.stage == 17, '--native-s1b requires stage17'
assert not args.vadd_ir or args.stage == 17, '--vadd-ir requires stage17'
assert not args.gopsnap or args.stage == 1, '--gopsnap is an observation boot: stage 1 only'
assert not (args.native_s1b and args.vadd_ir), 'keep the independent native S1b and vadd tests separate'
assert not args.metal or (args.stage == 17 and args.native_s1b), '--metal needs stage17 with --native-s1b (navi48-metal gate, Navi48MetalNub.cpp:214)'
assert not (args.metal_disp or args.metal_ws) or args.metal, '--metal-disp and --metal-ws follow --metal (phases P1 and P2)'
assert not (args.metal_disp or args.metal_ws) or args.primary, '--metal-disp and --metal-ws need --primary: the RX 9060 XT must be the only display'
assert not args.aux_kill or not args.metal, '--aux-kill and --metal are contradictory'
assert not args.gopsnap or not args.metal, 'gopsnap is an observation boot, not a Metal boot'

vm = args.vm_dir.resolve()
assert subprocess.check_output(['findmnt', '-n', '-o', 'UUID', '--target', '/mnt/vm'], text=True).strip() == 'be2a9624-d2c1-4778-ac99-fcf9258d3328'
locks = []
if not args.dry_run:
    assert subprocess.run(['pgrep', '-f', '^qemu-system-x86_64'], capture_output=True).returncode == 1, 'a QEMU process is running'
    for path in (Path('/mnt/vm/images/macos-build/.vm.lock'), vm / '.vm.lock'):
        handle = path.open('r')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locks.append(handle)
plan_path = vm / 'test-plan.json'
plan = json.loads(plan_path.read_text())
efi = vm / plan['efi']
digest = hashlib.sha256(efi.read_bytes()).hexdigest()
backup = vm / 'OpenCore' / f'backup-stage{plan["stage"]}-{digest[:12]}.qcow2'
if not args.dry_run and not backup.exists():
    shutil.copy2(efi, backup)
with tempfile.TemporaryDirectory(dir=vm / 'staging', prefix='prepare-stage-') as td:
    raw = Path(td) / 'OpenCore.raw'
    subprocess.run(['qemu-img', 'convert', '-O', 'raw', str(efi), str(raw)], check=True)
    fat = str(raw) + '@@1048576'
    cfg = plistlib.loads(subprocess.check_output(['mtype', '-i', fat, '::/EFI/OC/config.plist']))
    if args.kext:
        kext = args.kext.resolve()
        info = plistlib.loads((kext / 'Contents/Info.plist').read_bytes())
        assert info['CFBundleIdentifier'] == 'com.navi48.bringup'
        assert any(p.get('IOPCIPrimaryMatch', '').split() == ['0x75901002'] for p in info['IOKitPersonalities'].values()), 'Not the Navi44 build'
        binary = (kext / 'Contents/MacOS/Navi48Bringup').read_bytes()
        assert binary[:8] == bytes.fromhex('cffaedfe07000001'), 'Not an x86_64 Mach-O'
        for relative in ('Contents/Info.plist', 'Contents/MacOS/Navi48Bringup', 'Contents/_CodeSignature/CodeResources'):
            source = kext / relative
            destination = '::/EFI/OC/Kexts/Navi48Bringup.kext/' + relative
            subprocess.run(['mcopy', '-o', '-i', fat, str(source), destination], check=True)
            assert subprocess.check_output(['mtype', '-i', fat, destination]) == source.read_bytes()
        plan['current_kext_sha256'] = hashlib.sha256(binary).hexdigest()
    # UEFI Output: Max when the RX 9060 XT is the only display (the GOP mode then matches the panel); empty otherwise (the bring-up default).
    cfg['UEFI']['Output']['Resolution'] = 'Max' if args.primary else ''
    # The picker must appear on its own: Timeout > 0, shown, default entry = the normal boot (macOS).
    assert cfg['Misc']['Boot']['Timeout'] > 0 and cfg['Misc']['Boot']['ShowPicker'] is True, 'picker does not start by itself'
    nvram = cfg['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82']
    original_flags = nvram['boot-args'].split()
    assert 'navi48bringup=1' in original_flags
    assert any(f in ('navi48-interrupts=0', 'navi48-interrupts=1') for f in original_flags)
    flags = [f for f in original_flags if not f.startswith(MANAGED_PREFIXES) and not f.startswith('amfi_get_out_of_my_way=')]
    assert not any(f.startswith('navi48-') for f in flags), 'Unexpected hardware opt-in'
    flags.append(f'navi48-stage={args.stage}')
    flags.append(f'navi48-interrupts={int(args.interrupts)}')
    if args.smu_full:
        flags.append('navi48-smu-full=1')
    if args.native_s1b:
        flags.append('navi48-native=1')
    if args.vadd_ir:
        flags.append('navi48-vadd-ir=1')
    if args.gopsnap:
        flags.append('navi48-gopsnap=1')
    if args.metal:
        flags.append('navi48-metal=1')
        flags.append('navi48-aux=1')          # explicit: the aux kext is part of the Metal path (absent would also mean on)
    if args.metal_ws:
        flags.append('navi48-metal-ws=1')
    if args.metal_disp:
        flags.append('navi48-metal-disp=1')
    if args.aux_kill:
        flags.append('navi48-aux=0')
    managed = [f for f in flags if f.startswith('navi48-')]
    assert all(f.split('=')[0] in ADMITTED_KEYS and f.count('=') == 1 for f in managed), f'boot-arg outside the admitted list: {managed}'
    assert len({f.split('=')[0] for f in managed}) == len(managed), f'duplicate navi48 key: {managed}'
    if args.amfi_get_out_of_my_way:
        flags.append('amfi_get_out_of_my_way=1')
    if args.csr_active_config is not None:
        nvram['csr-active-config'] = args.csr_active_config.to_bytes(4, 'little')
        # csr-active-config already exists in the persistent NVRAM (OVMF_VARS): OpenCore Add never overwrites it, so Delete it
        # first (NVRAM > Delete runs before Add at every boot). Without this the new value is silently ignored.
        deletes = cfg['NVRAM']['Delete'].setdefault('7C436110-AB2A-4BBB-A880-FE41995C9F82', [])
        if 'csr-active-config' not in deletes:
            deletes.append('csr-active-config')
    nvram['boot-args'] = ' '.join(flags)
    assert cfg['UEFI']['Quirks']['ResizeGpuBars'] == plan['resize_gpu_bars']
    config_path = Path(td) / 'config.plist'
    config_path.write_bytes(plistlib.dumps(cfg))
    print('boot-args:', nvram['boot-args'])
    if args.dry_run:
        print('dry-run: EFI, test-plan.json and staging not written; VM not touched.')
        raise SystemExit(0)
    subprocess.run(['mcopy', '-o', '-i', fat, str(config_path), '::/EFI/OC/config.plist'], check=True)
    assert subprocess.check_output(['mtype', '-i', fat, '::/EFI/OC/config.plist']) == config_path.read_bytes()
    output = Path(td) / 'OpenCore.qcow2'
    subprocess.run(['qemu-img', 'convert', '-O', 'qcow2', str(raw), str(output)], check=True)
    subprocess.run(['qemu-img', 'check', str(output)], check=True, stdout=subprocess.DEVNULL)
    output.replace(efi)
    shutil.copy2(config_path, vm / 'staging' / f'config.stage{args.stage}.plist')
phase = 'P2' if args.metal_ws else 'P1' if args.metal_disp else 'P0' if args.metal else 'bring-up'
plan.update(csr_active_config=(f'{args.csr_active_config:#04x}' if args.csr_active_config is not None else 'unchanged'),
            amfi_get_out_of_my_way=args.amfi_get_out_of_my_way,
            stage=args.stage, smu_full=args.smu_full, smu_full_effective=args.smu_full or args.stage >= 11,
            native_s1b=args.native_s1b, vadd_ir=args.vadd_ir, gopsnap=args.gopsnap, primary_display=args.primary, interrupts=args.interrupts,
            metal=args.metal, metal_disp=args.metal_disp, metal_ws=args.metal_ws, aux_kill=args.aux_kill, phase=phase,
            boot_args=nvram['boot-args'], efi_sha256=hashlib.sha256(efi.read_bytes()).hexdigest(), vm_running=False,
            status=f'Prepared stage{args.stage} ({phase})' + (' with bounded native S1b VMID8 test' if args.native_s1b else '') +
                   (' with Metal nub' if args.metal else '') + (' and native display route' if args.metal_disp else '') +
                   (' and WindowServer client' if args.metal_ws else '') + (' with aux kill switch' if args.aux_kill else '') +
                   (' with bounded vadd_ir compute test' if args.vadd_ir else '') +
                   (' and IH/MSI interrupts enabled' if args.interrupts else ' with interrupts disabled') + '; execution not yet observed')
plan_path.write_text(json.dumps(plan, indent=2) + '\n')
print(f'Prepared stage{args.stage} ({phase}), interrupts {"enabled" if args.interrupts else "disabled"}, EFI digest verified. VM remains off.')
