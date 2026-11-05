#!/usr/bin/env python3
"""0.0.669/0.0.670 CPU test: compile and run the 60 Hz host test (cobalt64/src/navi48-bringup/tests/refresh60_test.cpp) against the PURE HEADER OF
THE CANDIDATE being built, not the repo copy. The test drives the real decisions and sequences (classify, set 60, restore 120, rollback,
session) against a register model, checks every written register against the real dcn41 write allowlist, and carries a planted defect
(a writer that skips the OTG lock must be caught). Sanitizers: ASan, UBSan (fail on the first report).
"""
from pathlib import Path
import argparse
import hashlib
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernel-source', type=Path, required=True, help='the candidate tree (its src/dcn/navi48_refresh_pure.h is tested)')
args = parser.parse_args()
cand = args.kernel_source.resolve()
repo_test = root / 'cobalt64/src/navi48-bringup/tests/refresh60_test.cpp'
repo_dcn41 = root / 'cobalt64/src/dcn41'
header = cand / 'src/dcn/navi48_refresh_pure.h'
failures = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if sha(header) != sha(root / 'cobalt64/src/navi48-bringup/src/dcn/navi48_refresh_pure.h'):
    failures.append('the candidate pure header differs from the repo header')
with tempfile.TemporaryDirectory(prefix='refresh60-') as tmp:
    tmp = Path(tmp)
    # the test's relative includes: ../src/dcn/ (the header) and ../../dcn41/ (the allowlist), i.e. the cobalt64 layout
    nav = tmp / 'cobalt64/src/navi48-bringup'
    (nav / 'src/dcn').mkdir(parents=True)
    (nav / 'tests').mkdir()
    (tmp / 'cobalt64/src/dcn41').mkdir(parents=True)
    shutil.copyfile(header, nav / 'src/dcn/navi48_refresh_pure.h')
    shutil.copyfile(repo_test, nav / 'tests/refresh60_test.cpp')
    for name in ('dcn41_allow.c', 'dcn41_allow.h', 'dcn41_allow_ranges.h'):
        shutil.copyfile(repo_dcn41 / name, tmp / 'cobalt64/src/dcn41' / name)
    obj = tmp / 'dcn41_allow.o'
    binary = tmp / 'refresh60_test'
    steps = [
        ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-c', str(tmp / 'cobalt64/src/dcn41/dcn41_allow.c'), '-o', str(obj)],
        ['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
         str(nav / 'tests/refresh60_test.cpp'), str(obj), '-o', str(binary)],
    ]
    for step in steps:
        r = subprocess.run(step, capture_output=True, text=True)
        if r.returncode != 0:
            failures.append('build failed: ' + ' '.join(step[:2]) + '\n' + r.stderr[-2000:])
            break
    else:
        r = subprocess.run([str(binary)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode != 0 or ' 0 failures' not in r.stdout:
            failures.append('refresh60_test failed (exit %d)\n%s%s' % (r.returncode, r.stdout[-1500:], r.stderr[-1500:]))
if failures:
    print('FAIL test-kernel-refresh60.py')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('PASS test-kernel-refresh60.py: the host test of the candidate pure header passed, with ASan/UBSan and the allowlist')
