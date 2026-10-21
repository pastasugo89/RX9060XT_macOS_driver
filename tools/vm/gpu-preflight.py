#!/usr/bin/env python3
"""Read-only inventory for this host's first Navi44 passthrough test.

No binding changes, MMIO reads, device resets, VM control or privilege escalation.
Exit 2 means blockers exist; it never means the driver is ready for hardware.
"""
import argparse
import json
from pathlib import Path
import re


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def device_info(address):
    path = Path('/sys/bus/pci/devices') / address
    if not path.exists():
        return {'address': address, 'present': False}
    group = path / 'iommu_group'
    return {
        'address': address, 'present': True,
        'vendor': read(path / 'vendor'), 'device': read(path / 'device'),
        'driver': (path / 'driver').resolve().name if (path / 'driver').exists() else None,
        'boot_vga': read(path / 'boot_vga'),
        'reset_method': read(path / 'reset_method'),
        'iommu_group': group.resolve().name if group.exists() else None,
        'group_members': sorted(p.name for p in (group / 'devices').glob('*')),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    gpu = device_info('0000:03:00.0')
    audio = device_info('0000:03:00.1')
    igpu = device_info('0000:0a:00.0')
    connectors = []
    for path in sorted(Path('/sys/class/drm').glob('card*-*')):
        if not re.fullmatch(r'card\d+-.+', path.name):
            continue
        card = path.name.split('-', 1)[0]
        dev = Path('/sys/class/drm') / card / 'device'
        connectors.append({
            'name': path.name, 'pci': dev.resolve().name if dev.exists() else None,
            'status': read(path / 'status'), 'enabled': read(path / 'enabled'),
        })
    blockers = []
    warnings = []
    host_display = any(c['pci'] == igpu['address'] and c['status'] == 'connected' and c['enabled'] == 'enabled' for c in connectors)
    framebuffers = [p.resolve().name for p in Path('/sys/class/graphics').glob('fb*/device')]
    if (gpu.get('vendor'), gpu.get('device')) != ('0x1002', '0x7590'):
        blockers.append('La GPU attesa non corrisponde a 1002:7590: fermarsi.')
    if any(c['pci'] == gpu['address'] and c['status'] == 'connected' for c in connectors):
        blockers.append('Monitor collegato alla RX: predisporre prima il display host sulla iGPU.')
    if gpu.get('boot_vga') == '1':
        if gpu.get('driver') == 'vfio-pci' and host_display and framebuffers and all(p == igpu['address'] for p in framebuffers):
            warnings.append('RX primaria nel firmware, ma VFIO la possiede e display/framebuffer Linux sono sulla iGPU.')
        else:
            blockers.append('RX ancora GPU di boot: verificare console/framebuffer e GPU primaria prima del distacco.')
    for device in (gpu, audio):
        if device.get('driver') != 'vfio-pci':
            blockers.append(f"{device['address']} non è assegnato a vfio-pci.")
        if not device.get('iommu_group'):
            blockers.append(f"{device['address']}: gruppo IOMMU assente.")
        elif len(device['group_members']) != 1:
            blockers.append(f"{device['address']}: riesaminare tutti i membri del gruppo IOMMU.")
    result = {'gpu': gpu, 'audio': audio, 'igpu': igpu, 'connectors': connectors,
              'framebuffers': framebuffers, 'warnings': warnings,
              'blockers': blockers, 'hardware_test_validated': False,
              'note': 'Questo inventario non valida reset, policy kext, snapshot o driver.'}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for device in (gpu, audio, igpu):
            print(f"{device['address']}: driver={device.get('driver')} gruppo={device.get('iommu_group')}")
        for message in blockers:
            print('BLOCCO:', message)
        for message in warnings:
            print('NOTA:', message)
        print(result['note'])
    return 2 if blockers else 0


if __name__ == '__main__':
    raise SystemExit(main())
