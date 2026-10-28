#!/usr/bin/env python3
"""Seed the existing Cobalt APP admission list before login; never submit GPU work.

Uses only root appallow add/remove/list. Display ownership/registers are untouched.
On failure, removes only names added by this attempt and verifies restoration.
The name list is containment for honest programs, not a code-signing boundary.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def comm_key(name):
    h = 0xcbf29ce484222325
    for c in name.encode('utf-8')[:16]:
        h = ((h ^ c) * 0x100000001b3) & ((1 << 64) - 1)
    return h & ((1 << 60) - 1) or 1


def load_names(path):
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or not isinstance(data.get('names'), list):
        raise ValueError('Unexpected allowlist schema')
    names = data['names']
    if not names or len(names) > 32 or any(not isinstance(n, str) or not n or '\x00' in n or '\n' in n or not n.isascii() for n in names):
        raise ValueError('Invalid executable names')
    if len({comm_key(n) for n in names}) != len(names):
        raise ValueError('Duplicate truncated executable-name keys')
    return names


def run(tool, *args):
    result = subprocess.run([str(tool), 'accel', 'appallow', *args], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('appallow failed: ' + result.stdout + result.stderr)
    return result.stdout


def listed(tool):
    keys = set()
    for page in range(4):
        output = run(tool, 'list', str(page))
        if not re.search(r'code\s*:\s*0\s*\(ok\)', output):
            raise RuntimeError('APP role not ready')
        slots = re.findall(r'^\s*slot\s+\d+\s*:\s*(0x[0-9a-f]+|0)\s*$', output, re.M)
        if len(slots) != 9:
            raise RuntimeError('Unexpected appallow output; no mutation')
        keys.update(int(x, 0) for x in slots if int(x, 0))
    return keys


def seed(tool, names):
    original = listed(tool)
    expected = {comm_key(n) for n in names}
    if len(original | expected) > 32:
        raise RuntimeError('Existing entries leave insufficient list capacity')
    attempted = []
    try:
        for name in names:
            if comm_key(name) in original:
                continue
            attempted.append(name)  # include a failed call in rollback: its outcome may be partial
            output = run(tool, 'add', name)
            if not re.search(r'code\s*:\s*(0|4)\s*\(', output):
                raise RuntimeError('Unexpected add result')
        if listed(tool) != original | expected:
            raise RuntimeError('Admission list readback mismatch')
    except Exception as error:
        failures = []
        for name in reversed(attempted):
            try:
                run(tool, 'remove', name)
            except Exception as rollback_error:
                failures.append(str(rollback_error))
        try:
            if listed(tool) != original:
                failures.append('Rollback readback mismatch')
        except Exception as rollback_error:
            failures.append(str(rollback_error))
        raise RuntimeError(str(error) + ('; ROLLBACK FAILED: ' + '; '.join(failures) if failures else '; original list restored')) from error
    print('GPU_APP_LIST_VERIFIED entries=' + str(len(original | expected)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', type=Path, required=True)
    parser.add_argument('--names', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    if subprocess.check_output(['who'], text=True).strip():
        raise SystemExit('Refused: user session already present')
    boot = subprocess.check_output(['nvram', 'boot-args'], text=True).split()[1:]
    for token in ('navi48-multisession=1', 'navi48-apps=1', 'navi48-g5=1'):
        if token not in boot:
            raise SystemExit('Required boot argument absent: ' + token)
    seed(args.tool, load_names(args.names))


if __name__ == '__main__':
    main()
