#!/usr/bin/env python3
"""Resize only the isolated, unused RX9060XT BAR0 through Linux PCI sysfs.

8 = 256 MiB baseline, 10 = 1 GiB, 14 = restore the observed 16 GiB host size.
Requires root, VFIO ownership and no VM. Never unbind amdgpu or touch the iGPU.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('size_bit', type=int, choices=(8, 10, 14))
args = p.parse_args()
assert os.geteuid() == 0
assert 'rx9060xt_vfio_test=1' in Path('/proc/cmdline').read_text().split()
assert subprocess.run(['pgrep', '-f', '^qemu-system-x86_64'], capture_output=True).returncode == 1
dev = Path('/sys/bus/pci/devices/0000:03:00.0')
assert (dev / 'vendor').read_text().strip() == '0x1002'
assert (dev / 'device').read_text().strip() == '0x7590'
assert (dev / 'driver').resolve().name == 'vfio-pci'
group = (dev / 'iommu_group').resolve()
assert [x.name for x in (group / 'devices').iterdir()] == ['0000:03:00.0']
assert subprocess.run(['fuser', '-s', '/dev/vfio/' + group.name]).returncode == 1
assert int((dev / 'resource0_resize').read_text().strip(), 16) & (1 << args.size_bit)
for connector in Path('/sys/class/drm').glob('card*-*'):
    if (connector / 'status').exists() and (connector / 'status').read_text().strip() == 'connected':
        card = connector.name.split('-', 1)[0]
        assert (Path('/sys/class/drm') / card / 'device').resolve().name == '0000:0a:00.0'

before = (dev / 'resource').read_text()
old_override = (dev / 'driver_override').read_text().strip()
try:
    (dev / 'driver_override').write_text('vfio-pci\n')
    (dev / 'driver' / 'unbind').write_text('0000:03:00.0\n')
    (dev / 'resource0_resize').write_text(str(args.size_bit) + '\n')
finally:
    if not (dev / 'driver').exists():
        Path('/sys/bus/pci/drivers/vfio-pci/bind').write_text('0000:03:00.0\n')
    (dev / 'driver_override').write_text(('' if old_override in ('', '(null)') else old_override) + '\n')
after = (dev / 'resource').read_text()
bar = after.splitlines()[0].split()
assert int(bar[1], 16) - int(bar[0], 16) + 1 == 1 << (args.size_bit + 20)
assert (dev / 'driver').resolve().name == 'vfio-pci'
subprocess.run(['/usr/local/sbin/rx9060xt-vfio-access.py'], check=True)
record = {'size_bit': args.size_bit, 'bytes': 1 << (args.size_bit + 20), 'before': before, 'after': after, 'driver': 'vfio-pci'}
dest = Path('/mnt/vm/images/macos-gpu-test/diagnostics') / f'host-bar0-size-{args.size_bit}.json'
dest.write_text(json.dumps(record, indent=2))
os.chown(dest, 1000, 1000)
print(f'BAR0 verificato: {record["bytes"]} byte; VFIO ripristinato; iGPU non modificata.')
