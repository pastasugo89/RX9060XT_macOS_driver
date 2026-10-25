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
  navi48-agdc=1            src/navi48-bringup/src/apple/DisplayPipeGuard.cpp:2011 (AGDC publish; test VM only, --agdc, approved 21/10)

  DeviceProperties on the RX 9060 XT (PciRoot(0x0)/Pci(0x6,0x0)), read by RDNA4FB at start (patch 0006):
                           --rdna4fb-tr KEY=VALUE (repeatable) and --rdna4fb-tr-blob FILE, see apply_rdna4fb_tr()
                           Without them the script removes its own rdna4fb-tr-* keys: the kext uses its defaults.

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
                 'navi48-metal', 'navi48-metal-ws', 'navi48-metal-disp', 'navi48-aux', 'navi48-agdc',
                 'navi48-multisession', 'navi48-apps')
MANAGED_PREFIXES = tuple(k + '=' for k in ADMITTED_KEYS)
DEFAULT_VM = Path('/mnt/vm/images/macos-gpu-test')
# Boot KC membership of macOS 25G83, extracted locally (research/macos/25G83, not in git): one "address<TAB>size<TAB>bundle-id" per line.
BOOT_KC_ENTRIES = Path(__file__).resolve().parents[2] / 'research/macos/25G83/BootKernelExtensions.entries'


# ---- RDNA4FB IOFBTimingRange configuration (OpenCore DeviceProperties; patch 0006 reads them in RDNA4FB::start) ----
# Path of the RX 9060 XT in the test VM: pcidebug "0:6:0" and acpi-path "IOACPIPlane:/_SB/PCI0/S30@60000" in
# research/hw_dump/p2_boot40/ioreg_full_boot40.txt (the IOService path there is .../PCI0/AppleACPIPCI/S30@6/RDNA4FB).
RDNA4_TR_PATH = 'PciRoot(0x0)/Pci(0x6,0x0)'
RDNA4_TR_BLOB_SIZE = 0x138                      # sizeof(IODisplayTimingRangeV2), IOGraphicsTypes.h:796
RDNA4_TR_SCALARS = {'disable': 4, 'version': 4, 'maxnumlinks': 4, 'maxbandwidth': 8, 'clock-min': 4, 'clock-max': 4,
                    'encodings': 2, 'bpc': 2, 'colorimetry': 2, 'dynrange': 2}   # key -> width in bytes (the kext's types)
RDNA4_TR_DEFAULTS = {'version': 2, 'minclk': 497250000, 'maxclk': 498250000, 'minl0': 497250, 'maxl0': 498250,
                     'maxnumlinks': 0, 'maxbw': 25920000000, 'enc': 0x1, 'bpc': 0x2, 'col': 0x3, 'dyn': 0x1}
RDNA4_TR_GOP_HZ = 497750000
RDNA4_TR_CLOCK_CAP_HZ = 600000000               # the kext's limits (framebuffer.cpp, rdna4_range_refusal)
RDNA4_TR_BANDWIDTH_CAP = 25920000000            # HBR3 x4 payload with 8b/10b


def rdna4_tr_refusal(f):
    """Same limits as the kext: returns why a range is refused, or None."""
    if f['version'] not in (0, 2):
        return 'version is neither 0 nor 2'
    if f['minclk'] == 0 or f['minclk'] > f['maxclk']:
        return 'empty clock band'
    if f['maxclk'] > RDNA4_TR_CLOCK_CAP_HZ:
        return 'clock above 600 MHz'
    if not f['minclk'] <= RDNA4_TR_GOP_HZ <= f['maxclk']:
        return 'the GOP clock (497.75 MHz) is outside the band'
    if f['minl0'] > f['maxl0']:
        return 'empty link-0 band'
    if f['maxnumlinks'] > 1:
        return 'more than one link'
    if f['maxbw'] > RDNA4_TR_BANDWIDTH_CAP:
        return 'bandwidth above HBR3 x4'
    if f['enc'] == 0 or f['enc'] & ~0x1:
        return 'encoding other than RGB444'
    if f['bpc'] == 0 or f['bpc'] & ~0x2:
        return 'bits per component other than 8'
    if f['col'] == 0 or f['col'] & ~0x3:
        return 'colorimetry other than native RGB or sRGB'
    if f['dyn'] == 0 or f['dyn'] & ~0x1:
        return 'dynamic range other than SDR'
    return None


def rdna4_tr_blob_fields(blob):
    """The limited fields of an IODisplayTimingRangeV2 blob (little-endian offsets of the header)."""
    import struct
    return {'version': struct.unpack_from('<I', blob, 0x08)[0], 'minclk': struct.unpack_from('<Q', blob, 0x20)[0],
            'maxclk': struct.unpack_from('<Q', blob, 0x28)[0], 'maxnumlinks': struct.unpack_from('<I', blob, 0xd0)[0],
            'minl0': struct.unpack_from('<I', blob, 0xd4)[0], 'maxl0': struct.unpack_from('<I', blob, 0xd8)[0],
            'enc': struct.unpack_from('<H', blob, 0xe4)[0], 'bpc': struct.unpack_from('<H', blob, 0xe6)[0],
            'col': struct.unpack_from('<H', blob, 0xe8)[0], 'dyn': struct.unpack_from('<H', blob, 0xea)[0],
            'maxbw': struct.unpack_from('<Q', blob, 0xf0)[0]}


def apply_rdna4fb_tr(cfg, tr_set, blob):
    """Writes the rdna4fb-tr-* DeviceProperties of RDNA4_TR_PATH (Data, little-endian) or removes them; returns a summary.
    Any value that the kext would refuse is an error here: nothing is written to the EFI."""
    add = cfg.setdefault('DeviceProperties', {}).setdefault('Add', {})
    entry = {k: v for k, v in add.get(RDNA4_TR_PATH, {}).items() if not k.startswith('rdna4fb-tr-')}
    scalars = {k: v for k, v in tr_set.items() if k != 'disable'}
    assert not (blob is not None and scalars), '--rdna4fb-tr-blob replaces the scalar keys: use one or the other'
    fields = dict(RDNA4_TR_DEFAULTS)
    props = {}
    if blob is not None:
        assert len(blob) == RDNA4_TR_BLOB_SIZE, f'--rdna4fb-tr-blob: {len(blob)} bytes, need {RDNA4_TR_BLOB_SIZE}'
        fields = rdna4_tr_blob_fields(blob)
        props['rdna4fb-tr-blob'] = blob
    for key, value in tr_set.items():
        width = RDNA4_TR_SCALARS[key]
        assert 0 <= value < (1 << (8 * width)), f'--rdna4fb-tr {key}: does not fit {width} bytes'
        props['rdna4fb-tr-' + key] = value.to_bytes(width, 'little')
        if blob is None:
            if key == 'version': fields['version'] = value
            elif key == 'maxnumlinks': fields['maxnumlinks'] = value
            elif key == 'maxbandwidth': fields['maxbw'] = value
            elif key == 'clock-min': fields['minclk'], fields['minl0'] = value, value // 1000
            elif key == 'clock-max': fields['maxclk'], fields['maxl0'] = value, value // 1000
            elif key == 'encodings': fields['enc'] = value
            elif key == 'bpc': fields['bpc'] = value
            elif key == 'colorimetry': fields['col'] = value
            elif key == 'dynrange': fields['dyn'] = value
    why = rdna4_tr_refusal(fields)
    assert why is None, f'IOFBTimingRange refused: {why}'
    if not props:
        if entry:
            add[RDNA4_TR_PATH] = entry
        else:
            add.pop(RDNA4_TR_PATH, None)
        return 'default'
    for key, value in props.items():
        entry[key] = bytes(value)   # plistlib.dumps writes bytes as <data> (plistlib.Data is gone since Python 3.9)
    add[RDNA4_TR_PATH] = entry
    return ', '.join(f"{k[len('rdna4fb-tr-'):]}={'blob' if k == 'rdna4fb-tr-blob' else int.from_bytes(v, 'little')}"
                     for k, v in props.items())


def boot_kc_missing(info):
    """Non-kernel libraries of a kext that are not in the Boot KC. OpenCore Kernel->Add injects only into the Boot KC,
    so any missing one makes the prelink fail (boot25/boot28 OC logs: 'Prelinked injection RDNA4FB.kext ... Invalid Parameter')."""
    in_boot_kc = {line.split('\t')[2].strip() for line in BOOT_KC_ENTRIES.read_text().splitlines() if line.count('\t') >= 2}
    libraries = [name for name in info.get('OSBundleLibraries', {}) if not name.startswith(('com.apple.kpi.', 'com.apple.kernel'))]
    return [name for name in libraries if name not in in_boot_kc]

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
p.add_argument('--rdna4fb', type=Path, help='Inject a locally built RDNA4FB.kext (Navi 44 match 0x75901002) into EFI/OC/Kexts and add its Kernel->Add entry, while the VM is off')
p.add_argument('--agdc', action='store_true', help='With --metal: boot-arg navi48-agdc=1, the AGDC publish that pipeagdc needs (test VM only; approved 21/10)')
p.add_argument('--rdna4-vbl', action='store_true', help='Boot-arg rdna4-vbl=1: arms the RDNA4FB emulated VBL timer (framebuffer.cpp:2075, :1522). Without it the compositor produces no frames (research/reports/compositor_diag.md). The previous rdna4-vbl value is always removed, so the flag is explicit on every run.')
p.add_argument('--multisession', action='store_true', help='Boot-arg navi48-multisession=1 (G2 session array, up to four clients; amd/native_g2_pure.h, Navi48UserClient.cpp:13). Latched once at boot. Cobalt desktop variant ms-apps (research/reports/p2_vs_cobalt_recipe.md, row 9).')
p.add_argument('--apps', action='store_true', help='Boot-arg navi48-apps=1 (G4 user-application role, amd/native_g4_pure.h). Requires --multisession: with either absent nothing is reachable.')
p.add_argument('--npci', action='store_true', help='Boot-arg npci=0x2000 (PCI configuration, as in the Cobalt ReBAR variants: native_rebar_plant.sh:140). Written only with this flag; any other npci value is removed.')
p.add_argument('--vm-dir', type=Path, default=DEFAULT_VM, help='VM image directory (default: the test image). A copy can be used for tests.')
p.add_argument('--csr-active-config', type=lambda v: int(v, 0), choices=(0x01, 0x02, 0x03), default=None,
               help='TEST VM ONLY, explicit opt-in (default: unchanged). Writes csr-active-config (SIP bits): 0x01 = CSR_ALLOW_UNTRUSTED_KEXTS '
                    '(ad-hoc aux kext loads), 0x02 = CSR_ALLOW_UNRESTRICTED_FS (write /Library/GPUBundles), 0x03 = both. Restore 0 from the EFI backup.')
p.add_argument('--amfi-get-out-of-my-way', action='store_true',
               help='TEST VM ONLY, explicit opt-in (default: unchanged). Adds boot-arg amfi_get_out_of_my_way=1 (as in Cobalt64 display variants); needed only if AMFI blocks the ad-hoc bundle/dylibs.')
p.add_argument('--rdna4fb-tr', action='append', default=[], metavar='KEY=VALUE',
               help='RDNA4FB IOFBTimingRange override as an OpenCore DeviceProperty of the RX 9060 XT (patch 0006). KEY: '
                    + ', '.join(sorted(RDNA4_TR_SCALARS)) + '. Repeatable. Values the kext would refuse stop the script.')
p.add_argument('--rdna4fb-tr-blob', type=Path, help='RDNA4FB IOFBTimingRange as a whole 0x138-byte blob (rdna4fb-tr-blob); not with the scalar keys')
p.add_argument('--dry-run', action='store_true', help='Compute and print the boot-args and the checks, write nothing')
args = p.parse_args()
tr_set = {}
for item in args.rdna4fb_tr:
    key, sep, value = item.partition('=')
    assert sep and key in RDNA4_TR_SCALARS, f'--rdna4fb-tr: unknown key {key!r}; admitted: {sorted(RDNA4_TR_SCALARS)}'
    assert key not in tr_set, f'--rdna4fb-tr: duplicate key {key}'
    tr_set[key] = int(value, 0)
tr_blob = args.rdna4fb_tr_blob.read_bytes() if args.rdna4fb_tr_blob else None

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
assert not args.agdc or args.metal, '--agdc follows --metal (pipeagdc is part of the Metal desktop path)'
assert not args.apps or args.multisession, '--apps requires --multisession (G4 needs both latches, native_g4_pure.h:6-8)'

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
    if args.rdna4fb:
        # RDNA4FB: the framebuffer that the display pipe adopts (fb name RDNA4FB, see research/reports/p1_p2_display.md).
        # Injected through the OpenCore Kernel->Add table like Navi48Bringup. Its IOGraphicsFamily dependency may not resolve
        # in the Boot KC: if so the kernel log names the missing dependency and the consent route (Privacy & Security) is needed.
        kext = args.rdna4fb.resolve()
        info = plistlib.loads((kext / 'Contents/Info.plist').read_bytes())
        assert info['CFBundleIdentifier'] == 'com.hackintosh.RDNA4FB', 'not RDNA4FB'
        # Refuse before any EFI write: IOGraphicsFamily is in SystemKernelExtensions.kc only (25G83), so the OpenCore injection
        # always fails at prelink. Measured: 6 boots with injection, 6 times 'Prelinked injection ... - Invalid Parameter'.
        missing = boot_kc_missing(info)
        assert not missing, f'RDNA4FB injection refused: libraries not in the Boot KC {missing}. See research/reports/rdna4fb_injection.md; use the /Library/Extensions consent path.'
        assert any('0x75901002' in p.get('IOPCIPrimaryMatch', '').split() for p in info['IOKitPersonalities'].values()), 'RDNA4FB without the Navi 44 match'
        binary = (kext / 'Contents/MacOS/RDNA4FB').read_bytes()
        assert binary[:8] == bytes.fromhex('cffaedfe07000001'), 'RDNA4FB is not an x86_64 Mach-O'
        dest = '::/EFI/OC/Kexts/RDNA4FB.kext'
        for directory in (dest, dest + '/Contents', dest + '/Contents/MacOS', dest + '/Contents/_CodeSignature'):
            subprocess.run(['mmd', '-i', fat, directory], check=False)   # exists already: mmd fails, harmless
        for relative in ('Contents/Info.plist', 'Contents/MacOS/RDNA4FB', 'Contents/_CodeSignature/CodeResources'):
            source = kext / relative
            destination = dest + '/' + relative
            subprocess.run(['mcopy', '-o', '-i', fat, str(source), destination], check=True)
            assert subprocess.check_output(['mtype', '-i', fat, destination]) == source.read_bytes()
        kernel_add = [e for e in cfg['Kernel']['Add'] if e.get('BundlePath') != 'RDNA4FB.kext']
        kernel_add.append({'BundlePath': 'RDNA4FB.kext', 'ExecutablePath': 'Contents/MacOS/RDNA4FB', 'PlistPath': 'Contents/Info.plist',
                           'Enabled': True, 'Arch': 'x86_64', 'MinKernel': '25.6.0', 'MaxKernel': '25.6.99',
                           'Comment': 'RDNA4FB Navi 44 match 0x75901002 (cobalt64 patch 0001), test VM P2'})
        cfg['Kernel']['Add'] = kernel_add
        plan['rdna4fb_sha256'] = hashlib.sha256(binary).hexdigest()
    if not args.rdna4fb:
        # Without --rdna4fb the OpenCore injection is removed: RDNA4FB then comes only from /Library/Extensions (consent path),
        # so the same bundle never loads twice.
        cfg['Kernel']['Add'] = [e for e in cfg['Kernel']['Add'] if e.get('BundlePath') != 'RDNA4FB.kext']
    # UEFI Output: Max when the RX 9060 XT is the only display (the GOP mode then matches the panel); empty otherwise (the bring-up default).
    cfg['UEFI']['Output']['Resolution'] = 'Max' if args.primary else ''
    # The picker must appear on its own: Timeout > 0, shown, default entry = the normal boot (macOS).
    assert cfg['Misc']['Boot']['Timeout'] > 0 and cfg['Misc']['Boot']['ShowPicker'] is True, 'picker does not start by itself'
    nvram = cfg['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82']
    original_flags = nvram['boot-args'].split()
    assert 'navi48bringup=1' in original_flags
    assert any(f in ('navi48-interrupts=0', 'navi48-interrupts=1') for f in original_flags)
    flags = [f for f in original_flags if not f.startswith(MANAGED_PREFIXES) and not f.startswith('amfi_get_out_of_my_way=')
             and not f.startswith('rdna4-vbl=') and not f.startswith('npci=')]
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
    if args.agdc:
        flags.append('navi48-agdc=1')
    if args.aux_kill:
        flags.append('navi48-aux=0')
    managed = [f for f in flags if f.startswith('navi48-')]
    assert all(f.split('=')[0] in ADMITTED_KEYS and f.count('=') == 1 for f in managed), f'boot-arg outside the admitted list: {managed}'
    assert len({f.split('=')[0] for f in managed}) == len(managed), f'duplicate navi48 key: {managed}'
    if args.amfi_get_out_of_my_way:
        flags.append('amfi_get_out_of_my_way=1')
    if args.rdna4_vbl:
        flags.append('rdna4-vbl=1')
    if args.multisession:
        flags.append('navi48-multisession=1')
    if args.apps:
        flags.append('navi48-apps=1')
    if args.npci:
        flags.append('npci=0x2000')
    if args.csr_active_config is not None:
        nvram['csr-active-config'] = args.csr_active_config.to_bytes(4, 'little')
        # csr-active-config already exists in the persistent NVRAM (OVMF_VARS): OpenCore Add never overwrites it, so Delete it
        # first (NVRAM > Delete runs before Add at every boot). Without this the new value is silently ignored.
        deletes = cfg['NVRAM']['Delete'].setdefault('7C436110-AB2A-4BBB-A880-FE41995C9F82', [])
        if 'csr-active-config' not in deletes:
            deletes.append('csr-active-config')
    nvram['boot-args'] = ' '.join(flags)
    tr_summary = apply_rdna4fb_tr(cfg, tr_set, tr_blob)
    assert cfg['UEFI']['Quirks']['ResizeGpuBars'] == plan['resize_gpu_bars']
    config_path = Path(td) / 'config.plist'
    config_path.write_bytes(plistlib.dumps(cfg))
    print('boot-args:', nvram['boot-args'])
    print(f'rdna4fb-tr ({RDNA4_TR_PATH}):', tr_summary)
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
            amfi_get_out_of_my_way=args.amfi_get_out_of_my_way, rdna4_vbl=args.rdna4_vbl,
            multisession=args.multisession, apps=args.apps, npci=args.npci,
            stage=args.stage, smu_full=args.smu_full, smu_full_effective=args.smu_full or args.stage >= 11,
            native_s1b=args.native_s1b, vadd_ir=args.vadd_ir, gopsnap=args.gopsnap, primary_display=args.primary, interrupts=args.interrupts,
            metal=args.metal, metal_disp=args.metal_disp, metal_ws=args.metal_ws, aux_kill=args.aux_kill, phase=phase, agdc=args.agdc,
            rdna4fb=bool(args.rdna4fb), rdna4fb_timing_range=tr_summary,
            boot_args=nvram['boot-args'], efi_sha256=hashlib.sha256(efi.read_bytes()).hexdigest(), vm_running=False,
            status=f'Prepared stage{args.stage} ({phase})' + (' with bounded native S1b VMID8 test' if args.native_s1b else '') +
                   (' with Metal nub' if args.metal else '') + (' and native display route' if args.metal_disp else '') +
                   (' and WindowServer client' if args.metal_ws else '') + (' with aux kill switch' if args.aux_kill else '') +
                   (' with bounded vadd_ir compute test' if args.vadd_ir else '') +
                   (' and IH/MSI interrupts enabled' if args.interrupts else ' with interrupts disabled') + '; execution not yet observed')
plan_path.write_text(json.dumps(plan, indent=2) + '\n')
print(f'Prepared stage{args.stage} ({phase}), interrupts {"enabled" if args.interrupts else "disabled"}, EFI digest verified. VM remains off.')
