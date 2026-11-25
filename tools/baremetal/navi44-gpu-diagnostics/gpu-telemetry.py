#!/usr/bin/env python3
"""Read Navi48 telemetry as JSON lines. Use --sample to refresh it as an administrator."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time


TOOL = '/Library/Application Support/Navi44/accelerated-trial/navi48test'
PROPERTY = 'Navi48,Telemetry'
METRICS = (
    (r'clocks\s+gfx\s+(\d+) MHz\s+soc\s+(\d+) MHz\s+mem\s+(\d+) MHz\s+fclk\s+(\d+) MHz',
     ('GFXClockMHz', 'SoCClockMHz', 'MemoryClockMHz', 'FabricClockMHz')),
    (r'temps\s+edge\s+(\d+) C\s+hotspot\s+(\d+) C\s+mem\s+(\d+) C\s+fan (\d+) rpm \((\d+)%\)',
     ('SMUEdgeC', 'SMUHotspotC', 'SMUMemoryC', 'FanRPM', 'FanPWMPercent')),
    (r'power\s+socket\s+(\d+) W\s+board\s+(\d+) W\s+busy gfx\s+(\d+)%\s+mem\s+(\d+)%',
     ('SocketPowerW', 'BoardPowerW', 'GPUActivityPercent', 'MemoryActivityPercent')),
    (r'link\s+PCIe gen (\d+) x(\d+)\s+\(snapshot \d+\)', ('PCIeGeneration', 'PCIeLanes')),
)


def command(*args):
    return subprocess.check_output(args, timeout=8)


def registry_sample():
    entries = plistlib.loads(command('/usr/sbin/ioreg', '-a', '-r', '-c', 'Navi48Bringup', '-d', '1'))
    samples = [entry[PROPERTY] for entry in entries if PROPERTY in entry]
    if not samples:
        return None
    if len(samples) != 1 or not isinstance(samples[0], dict) or samples[0].get('Schema') != 1:
        raise ValueError('Unexpected Navi48 telemetry registry schema')
    return {**samples[0], 'Source': 'IORegistry'}


def legacy_sample(metrics, vram):
    mismatch = re.search(r'driver-interface version (0x[0-9a-f]+).*?range check: (passed|FAILED)', metrics, re.S)
    if 'UNVERIFIED' in metrics and not mismatch:
        raise ValueError('Unrecognized firmware layout warning')
    sample = {'Schema': 1, 'Source': 'navi48test', 'SMUStatus': 0,
              'SMULayoutVerified': int(not mismatch)}
    if mismatch:
        sample['SMUInterfaceVersion'] = int(mismatch[1], 16)
    values = {}
    if not mismatch or mismatch[2] == 'passed':
        for pattern, keys in METRICS:
            match = re.search(pattern, metrics)
            if not match:
                raise ValueError(f'Missing Navi48 metric {keys[0]}')
            values.update(zip(keys, map(int, match.groups())))
    plausible = bool(values) and (values['GFXClockMHz'] <= 4000 and values['MemoryClockMHz'] <= 4000 and
        values['SMUEdgeC'] <= values['SMUHotspotC'] <= 125 and values['GPUActivityPercent'] <= 100 and
        values['MemoryActivityPercent'] <= 100)
    sample['SMUValuesPlausible'] = int(plausible)
    if plausible:
        sample.update(values)
    physical = re.search(r', VRAM (\d+) MiB,', vram)
    if physical:
        sample['PhysicalVRAMBytes'] = int(physical[1]) << 20
    for label, key in (('visible', 'Visible'), ('hi', 'High')):
        pool = re.search(rf'{label} pool\s*:\s+(\d+) bytes total \(\d+ MiB\), (\d+) bytes free', vram)
        if pool:
            sample[f'VRAM{key}TotalBytes'], sample[f'VRAM{key}FreeBytes'] = map(int, pool.groups())
        elif label == 'hi' and re.search(r'hi pool\s*:\s+not created', vram):
            sample['VRAMHighTotalBytes'] = sample['VRAMHighFreeBytes'] = 0
    return sample


def add_allocator_usage(sample):
    keys = ('VRAMVisibleTotalBytes', 'VRAMHighTotalBytes', 'VRAMVisibleFreeBytes', 'VRAMHighFreeBytes')
    if all(isinstance(sample.get(key), int) for key in keys):
        visible, high, visible_free, high_free = (sample[key] for key in keys)
        if 0 <= visible_free <= visible and 0 <= high_free <= high:
            sample['VRAMAllocatorUsedBytes'] = visible - visible_free + high - high_free


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', action='store_true', help='refresh with the installed read-only diagnostic verbs')
    parser.add_argument('--count', type=int, default=1, help='number of samples, or 0 to watch until interrupted')
    parser.add_argument('--interval', type=float, default=2, help='seconds between samples, at least 1')
    args = parser.parse_args()
    if args.count < 0 or not 1 <= args.interval <= 300:
        parser.error('use a non-negative count and an interval from 1 to 300 seconds')
    if args.sample and os.geteuid() != 0:
        parser.error('--sample requires macOS administrator privileges')
    if args.sample and not Path(TOOL).is_file():
        parser.error('the installed navi48test tool is missing')
    try:
        remaining = args.count
        while args.count == 0 or remaining:
            metrics = command(TOOL, 'metrics', '1').decode() if args.sample else None
            sample = registry_sample()
            if sample is None:
                if metrics is None:
                    raise ValueError('No cached Navi48 sample. Run once with sudo and --sample.')
                sample = legacy_sample(metrics, command(TOOL, 'accel', 'vramstat').decode())
            add_allocator_usage(sample)
            print(json.dumps(sample, sort_keys=True), flush=True)
            if args.count:
                remaining -= 1
            if args.count == 0 or remaining:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'GPU telemetry: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
