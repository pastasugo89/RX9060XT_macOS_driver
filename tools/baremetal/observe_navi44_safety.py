#!/usr/bin/env python3
"""Collect current-boot Navi44/watchdog evidence. No direct GPU access."""
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path


def run(argv, timeout=20):
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
        return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr[:1000]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'returncode': None, 'stdout': '', 'stderr': str(exc)}


def main():
    bt = run(['/usr/sbin/sysctl', '-n', 'kern.boottime'])
    match = re.search(r'sec\s*=\s*(\d+)', bt['stdout'])
    if not match:
        print('STOP: could not determine current boot time', file=sys.stderr)
        return 2
    boot = int(match.group(1))
    start = dt.datetime.fromtimestamp(boot).strftime('%Y-%m-%d %H:%M:%S')
    predicate = 'process == "kernel" AND (eventMessage CONTAINS[c] "N4X-SAFETY" OR eventMessage CONTAINS[c] "navi48")'
    data = {
        'boot_epoch': boot,
        'boot_args': run(['/usr/sbin/nvram', 'boot-args']),
        'driver': run(['/usr/sbin/ioreg', '-r', '-c', 'Navi48Bringup', '-l', '-w0']),
        'kernel_log': run(['/usr/bin/log', 'show', '--start', start, '--style', 'compact', '--predicate', predicate]),
        'dmesg': run(['/usr/bin/sudo', '-n', '/sbin/dmesg']),
    }
    # dmesg is current boot by definition. Retain only targeted lines.
    dmesg = data['dmesg']['stdout'].splitlines()
    data['dmesg']['stdout'] = '\n'.join(x for x in dmesg if re.search(r'n4x-safety|navi48', x, re.I))
    lines = (data['kernel_log']['stdout'] + '\n' + data['dmesg']['stdout']).splitlines()
    events = [line for line in lines if 'N4X-SAFETY' in line]
    heartbeats = [line for line in events if re.search(r'hotspot=\S+.*state=(OK|WARN|TRIP|STOP)', line)]
    data['assessment'] = {
        'watchdog_events': len(events), 'heartbeat_count': len(heartbeats),
        'latest_heartbeat': heartbeats[-1] if heartbeats else None,
        'sensor_validation': 'UNKNOWN: compare with an independent reading; log presence does not prove safety',
        'limitations': 'N4X-SAFETY is not a shutdown mechanism; old messages within the current boot may be stale.',
    }
    target = Path('research/hw_dump') / ('navi44-safety-observe-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S'))
    target.mkdir(parents=True, exist_ok=False)
    (target / 'observation.json').write_text(json.dumps(data, indent=2) + '\n')
    print('Saved:', target / 'observation.json')
    print('Watchdog evidence:', 'FOUND' if heartbeats else 'UNKNOWN / no heartbeat observed')
    if heartbeats:
        print('Last heartbeat:', heartbeats[-1])
    print('Temperature validity and protective effect: UNKNOWN')
    return 0 if heartbeats else 2


if __name__ == '__main__':
    sys.exit(main())
