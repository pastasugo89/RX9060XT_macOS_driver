#!/usr/bin/env python3
"""Tests for apply_refresh_guard.py.

Run:  python3 -B test-apply-refresh-guard.py [-v] [--guard PATH]

The guard is only read (default: the live boot guard). The gating tests run
refresh_begin / refresh_revert in a bash sandbox with stub navi48test, kmutil and
root_flag_valid, so nothing touches the GPU, the kernel or /Library. Every write
goes to a tempfile directory that is removed afterwards.
"""
import difflib
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apply_refresh_guard as rg  # noqa: E402

LIVE_GUARD = '/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'
REPO_GUARD = os.path.join(HERE, '..', 'accelerated-reboot-trial.sh')
LIVE_SHA256 = 'eaf88b0ab3a2711531c02efe22bc61bdf0012c1f0f2089fe8dd8ebd960ffd948'   # the 0.0.668 review's guard (= the payload v4 copy)
# The reviewed input: the payload-v4 copy of that guard. The live file is NOT a stable input (it is redeployed by other work), so the
# tests pin the reviewed copy and only report the live file's hash.
REVIEWED_GUARD = os.path.join(HERE, '..', '..', '..', '..', 'research', 'builds', 'macos-20261031', 'production', 'kernel-payload-v4',
                              'system', 'Library', 'Application Support', 'Navi44', 'accelerated-trial', 'accelerated-reboot-trial.sh')
CLI = os.path.join(HERE, 'apply_refresh_guard.py')
PIPERELOAD = '"$NT" accel pipereload || { echo \'STOP pipereload failed\'; exit 1; }'

GUARD = REVIEWED_GUARD
if '--guard' in sys.argv:
    _i = sys.argv.index('--guard')
    GUARD = sys.argv[_i + 1]
    del sys.argv[_i:_i + 2]

_STATE = {}


def _load_guard():
    try:
        with open(GUARD, 'rb') as f:
            return f.read(), GUARD
    except OSError as exc:
        sys.stderr.write(f'\nNOTICE: {GUARD} is not readable ({exc}); using the repo copy {REPO_GUARD}\n')
        with open(REPO_GUARD, 'rb') as f:
            return f.read(), REPO_GUARD + ' (repo copy, NOT the live file)'


def state():
    if not _STATE:
        raw, label = _load_guard()
        source = raw.decode('utf-8')
        _STATE.update(raw=raw, label=label, source=source, output=rg.apply_refresh_patch(source))
    return _STATE


def function_body(text, name):
    lines = text.splitlines()
    start = lines.index(name + '() {')
    end = lines.index('}', start)
    return '\n'.join(lines[start:end + 1]) + '\n'


def verify_ordering(text):
    """Refresh call after pipereload and before the WindowServer restart kill; confirm after READY."""
    lines = text.splitlines()

    def only(pred, what):
        hits = [i for i, line in enumerate(lines) if pred(line.strip())]
        if len(hits) != 1:
            raise AssertionError(f'{what}: expected exactly one line, found {len(hits)}')
        return hits[0]

    reload_i = only(lambda s: s == PIPERELOAD, 'pipereload line')
    call_i = only(lambda s: s == 'refresh_begin || true', 'refresh_begin call')
    kill_i = next((i for i, line in enumerate(lines)
                   if i > reload_i and line.strip().startswith('killall -9 WindowServer')), None)
    if kill_i is None:
        raise AssertionError('no killall -9 WindowServer after pipereload')
    if not reload_i < call_i < kill_i:
        raise AssertionError(f'refresh call {call_i} is not between pipereload {reload_i} and the kill {kill_i}')
    ready_i = only(lambda s: s.startswith('echo "WINDOWSERVER_READY'), 'WINDOWSERVER_READY echo')
    confirm_i = only(lambda s: '"$NT" accel refresh confirm' in s, 'confirm call')
    if not confirm_i > ready_i:
        raise AssertionError(f'confirm call {confirm_i} is not after WINDOWSERVER_READY {ready_i}')


def verify_gating(text):
    """Flag exists -> flag valid -> kexts 0.0.669 + RDNA4FB 0.0.9 -> request; each gate returns 0."""
    body = function_body(text, 'refresh_begin')
    flag_i = body.index('[[ ! -e "$REFRESH_FLAG" && ! -L "$REFRESH_FLAG" ]]')
    valid_i = body.index('root_flag_valid "$APP/refresh-60"')
    kext_i = body.index('kmutil showloaded --list-only')
    req_i = body.index('"$NT" accel refresh 60 "$REFRESH_TIMEOUT"')
    if not flag_i < valid_i < kext_i < req_i:
        raise AssertionError('refresh_begin gates are not ordered: flag exists, flag valid, kexts, request')
    if 'return 0' not in body[valid_i:kext_i] or 'return 0' not in body[kext_i:req_i]:
        raise AssertionError('a gate does not return before the request')
    for needle in (r'com\.navi48\.bringup[[:space:]]+\(0\.0\.669\)',
                   r'com\.hackintosh\.RDNA4FB[[:space:]]+\(0\.0\.9\)'):
        if needle not in body:
            raise AssertionError(f'kext check lacks {needle}')
    lines = text.splitlines()
    confirm = [i for i, line in enumerate(lines) if '"$NT" accel refresh confirm' in line]
    if len(confirm) != 1 or not any('(( refresh_active == 1 ))' in line
                                    for line in lines[max(0, confirm[0] - 3):confirm[0]]):
        raise AssertionError('the confirm call is not gated on refresh_active')


def verify_failsafe(text):
    """refresh_revert sits inside FAILSAFE_BEGIN..FAILSAFE_DONE, after pipearm 0, before the kill."""
    lines = text.splitlines()
    begin = [i for i, line in enumerate(lines) if 'FAILSAFE_BEGIN' in line]
    done = [i for i, line in enumerate(lines) if line.strip() == "echo 'FAILSAFE_DONE'"]
    if len(begin) != 1 or len(done) != 1:
        raise AssertionError(f'FAILSAFE markers: {len(begin)} BEGIN, {len(done)} DONE')
    # Two calls by design: this failsafe one, and the one after a failed confirmation (test_10). Only the failsafe one is checked here.
    calls = [i for i, line in enumerate(lines) if line.strip() == 'refresh_revert || true'
             and begin[0] < i < done[0]]
    if len(calls) != 1:
        raise AssertionError(f'refresh_revert call count inside FAILSAFE is {len(calls)}')
    rev = calls[0]
    if not begin[0] < rev < done[0]:
        raise AssertionError('refresh_revert is outside the FAILSAFE block')
    kills = [i for i in range(begin[0], done[0]) if 'killall -9 WindowServer' in lines[i]]
    if not kills or rev > kills[0]:
        raise AssertionError('refresh_revert is not before the WindowServer kill')
    pipearm = [i for i, line in enumerate(lines) if line.strip() == '"$NT" accel pipearm 0 || true']
    if len(pipearm) != 1 or pipearm[0] >= rev:
        raise AssertionError('refresh_revert does not follow the pipearm 0 failsafe line')
    body = function_body(text, 'refresh_revert')
    if '[[ "$refresh_active" == 1 ]]' not in body or '"$NT" accel refresh 120' not in body:
        raise AssertionError('refresh_revert is not gated on refresh_active or does not send 120 Hz')


GOOD_KEXTS = (
    '  92    0 0xffffff8004240000 0x7eb000   0x7eb000   com.navi48.bringup (0.0.669) 9716F9B9-A7FA-3BC4-9A9D-2CCC29AF069F <19 9 7 6 3 1>\n'
    ' 120    0 0xffffff7f966d2000 0xc674     0xc674     com.hackintosh.RDNA4FB (0.0.9) 3903CBE3-AAC0-36A1-B1B9-F29C53FD49EF <119 19 9 7 6 3>\n'
)
KEXTS_668 = GOOD_KEXTS.replace('(0.0.669)', '(0.0.668)')
FB_008 = GOOD_KEXTS.replace('(0.0.9)', '(0.0.8)')
SKIP_FLAG = 'REFRESH60_SKIPPED flag is not a root-owned 0644 regular file'
SKIP_KEXT = 'REFRESH60_SKIPPED loaded kexts are not 0.0.669 and RDNA4FB 0.0.9'
REQ = 'accel refresh 60 120'
REVERT = 'accel refresh 120'

CASES = [
    dict(name='flag absent: silent no-op', flag='none', valid=True, kexts=GOOD_KEXTS, rc=0,
         script=['refresh_begin'], want=[], forbid=['REFRESH60'], calls=[], state='0'),
    dict(name='flag is a symlink: refused', flag='symlink', valid=False, kexts=GOOD_KEXTS, rc=0,
         script=['refresh_begin'], want=[SKIP_FLAG], forbid=[], calls=[], state='0'),
    dict(name='flag not root-owned: refused', flag='file', valid=False, kexts=GOOD_KEXTS, rc=0,
         script=['refresh_begin'], want=[SKIP_FLAG], forbid=[], calls=[], state='0'),
    dict(name='kext 0.0.668: refused, no request', flag='file', valid=True, kexts=KEXTS_668, rc=0,
         script=['refresh_begin'], want=[SKIP_KEXT], forbid=[], calls=[], state='0'),
    dict(name='RDNA4FB 0.0.8: refused, no request', flag='file', valid=True, kexts=FB_008, rc=0,
         script=['refresh_begin'], want=[SKIP_KEXT], forbid=[], calls=[], state='0'),
    dict(name='no kmutil output: refused, no request', flag='file', valid=True, kexts='', rc=0,
         script=['refresh_begin'], want=[SKIP_KEXT], forbid=[], calls=[], state='0'),
    dict(name='all gates pass: requested, pending', flag='file', valid=True, kexts=GOOD_KEXTS, rc=0,
         script=['refresh_begin'], want=['REFRESH60_REQUESTED refresh: code 0'], forbid=['REFRESH60_FAILED'],
         calls=[REQ], state='1'),
    dict(name='request refused: back to 120 Hz, no abort', flag='file', valid=True, kexts=GOOD_KEXTS, rc=3,
         script=['refresh_begin'], want=['REFRESH60_FAILED'], forbid=['REFRESH60_REQUESTED'],
         calls=[REQ, REVERT], state='0'),
    dict(name='revert once after a request', flag='file', valid=True, kexts=GOOD_KEXTS, rc=0,
         script=['refresh_begin', 'refresh_revert', 'refresh_revert'], want=['REFRESH60_REVERTED'], forbid=[],
         calls=[REQ, REVERT], state='0', count=('REFRESH60_REVERTED', 1)),
    dict(name='revert without a request: no call', flag='file', valid=True, kexts=GOOD_KEXTS, rc=0,
         script=['refresh_revert'], want=[], forbid=['REFRESH60_REVERTED'], calls=[], state='0'),
]

FAKE_NT = r'''#!/bin/bash
printf '%s\n' "$*" >> "$CALLS_LOG"
if [[ "$*" == "accel refresh 60 "* ]]; then
  if [[ "${FAKE_NT_RC:-0}" == 0 ]]; then
    echo "refresh: code 0 (ok) active 60 Hz V_TOTAL 3050 MSA 3050 state pending, auto-revert in 120 s"
  else
    echo "accel: call FAILED (0x10000003)"
  fi
  exit "${FAKE_NT_RC:-0}"
fi
echo "refresh: code 0 (ok) active 120 Hz V_TOTAL 3050 MSA 3050 state 120 Hz GOP"
exit 0
'''
FAKE_KMUTIL = '#!/bin/bash\ncat "$FAKE_KMUTIL_FILE"\n'
HARNESS_HEAD = '''set -Eeuo pipefail
PATH="$FAKEBIN:/usr/bin:/bin:/usr/sbin:/sbin"
APP="$TESTAPP"
NT="$FAKEBIN/navi48test"
REFRESH_TIMEOUT=120
REFRESH_FLAG="$APP/refresh-60"
refresh_active=0
root_flag_valid() { [[ "${FAKE_FLAG_VALID:-0}" == 1 ]]; }
'''


def run_sandbox(funcs, case):
    with tempfile.TemporaryDirectory() as td:
        app = os.path.join(td, 'app')
        bindir = os.path.join(td, 'bin')
        os.makedirs(app)
        os.makedirs(bindir)
        calls_log = os.path.join(td, 'calls.log')
        kfile = os.path.join(td, 'kexts.txt')
        with open(kfile, 'w', encoding='utf-8') as f:
            f.write(case['kexts'])
        for name, body in (('navi48test', FAKE_NT), ('kmutil', FAKE_KMUTIL)):
            p = os.path.join(bindir, name)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(body)
            os.chmod(p, 0o755)
        flag = os.path.join(app, 'refresh-60')
        if case['flag'] == 'file':
            open(flag, 'w').close()
        elif case['flag'] == 'symlink':
            target = os.path.join(app, 'target')
            open(target, 'w').close()
            os.symlink(target, flag)
        harness = os.path.join(td, 'harness.sh')
        with open(harness, 'w', encoding='utf-8') as f:
            f.write(HARNESS_HEAD + funcs + '\n'.join(case['script']) + '\necho "STATE active=$refresh_active"\n')
        env = {'PATH': '/usr/bin:/bin', 'FAKEBIN': bindir, 'TESTAPP': app, 'CALLS_LOG': calls_log,
               'FAKE_KMUTIL_FILE': kfile, 'FAKE_FLAG_VALID': '1' if case['valid'] else '0',
               'FAKE_NT_RC': str(case['rc'])}
        r = subprocess.run(['/bin/bash', harness], env=env, capture_output=True, text=True, timeout=60)
        calls = []
        if os.path.exists(calls_log):
            with open(calls_log, encoding='utf-8') as f:
                calls = f.read().splitlines()
        return r, calls


class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = state()

    def test_01_patch_applies_to_the_guard(self):
        s = self.s
        sha = hashlib.sha256(s['raw']).hexdigest()
        print(f'\n[guard] {s["label"]} sha256={sha} bytes={len(s["raw"])}', file=sys.stderr)
        if s['label'] == LIVE_GUARD:
            print(f'[guard] live guard sha256 {sha}: ' + ('the reviewed one' if sha == LIVE_SHA256 else 'NOT the reviewed one; not an input'), file=sys.stderr)
        else:
            self.assertEqual(sha, LIVE_SHA256, 'the reviewed guard copy differs from the 0.0.668 review; stop')
        self.assertNotIn(rg.MARKER, s['source'])
        self.assertEqual(s['output'].count(rg.MARKER), 1)

    def test_02_additions_only(self):
        a = self.s['source'].splitlines(keepends=True)
        b = self.s['output'].splitlines(keepends=True)
        ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        self.assertEqual([op for op in ops if op[0] not in ('equal', 'insert')], [],
                         'replace or delete opcodes present')
        self.assertEqual(sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == 'equal'), len(a))
        print(f'\n[additions] {len(b) - len(a)} lines added, 0 changed, 0 removed', file=sys.stderr)

    def test_03_bash_n_accepts_output(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'accelerated-reboot-trial.sh')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.s['output'])
            r = subprocess.run(['/bin/bash', '-n', path], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_04_refresh_call_and_confirm_placement(self):
        verify_ordering(self.s['output'])

    def test_05_every_hook_is_gated(self):
        verify_gating(self.s['output'])

    def test_05b_gating_runtime_sandbox(self):
        funcs = function_body(self.s['output'], 'refresh_revert') + function_body(self.s['output'], 'refresh_begin')
        for case in CASES:
            with self.subTest(case['name']):
                r, calls = run_sandbox(funcs, case)
                self.assertEqual(r.returncode, 0, f'set -e abort: {r.stderr}')
                for w in case['want']:
                    self.assertIn(w, r.stdout)
                for f in case['forbid']:
                    self.assertNotIn(f, r.stdout)
                self.assertEqual(calls, case['calls'])
                self.assertIn(f'STATE active={case["state"]}', r.stdout)
                if 'count' in case:
                    text, n = case['count']
                    self.assertEqual(r.stdout.count(text), n)

    def test_06_missing_or_duplicate_anchor_refuses(self):
        lines = self.s['source'].splitlines(keepends=True)

        def idx(pred):
            return next(i for i, line in enumerate(lines) if pred(line.strip()))

        profile = idx(lambda s: s.startswith('PROFILE='))
        pipearm = idx(lambda s: s == '"$NT" accel pipearm 0 || true')
        cases = {
            'pipereload missing': [x for x in lines if x.strip() != PIPERELOAD],
            'rollback definition missing': [x for x in lines if x.strip() != 'rollback() {'],
            'RESTART_WINDOWSERVER missing': [x for x in lines
                                             if not x.strip().startswith('echo "RESTART_WINDOWSERVER old=')],
            'WINDOWSERVER_READY missing': [x for x in lines
                                           if not x.strip().startswith('echo "WINDOWSERVER_READY pid=')],
            'PROFILE duplicated': lines[:profile + 1] + [lines[profile]] + lines[profile + 1:],
            'pipearm failsafe duplicated': lines[:pipearm + 1] + [lines[pipearm]] + lines[pipearm + 1:],
        }
        for name, mutated in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    rg.apply_refresh_patch(''.join(mutated))
        with self.subTest('CRLF input'):
            with self.assertRaises(ValueError):
                rg.apply_refresh_patch(self.s['source'].replace('\n', '\r\n'))

    def test_07_reapply_refuses(self):
        with self.assertRaisesRegex(ValueError, rg.MARKER):
            rg.apply_refresh_patch(self.s['output'])

    def test_08_failsafe_reverts_before_wind_server_kill(self):
        verify_failsafe(self.s['output'])

    def test_10_failed_confirm_reverts_at_once(self):
        # A failed confirmation reverts to 120 Hz immediately (never left to the kernel timeout mid-login); the revert sits in the else branch.
        out = self.s['output']
        lines = out.splitlines()
        confirm = [i for i, line in enumerate(lines) if '"$NT" accel refresh confirm' in line]
        self.assertEqual(len(confirm), 1)
        block = '\n'.join(lines[confirm[0]:confirm[0] + 8])
        self.assertIn('REFRESH60_CONFIRM_FAILED', block)
        self.assertIn('refresh_revert || true', block)
        self.assertLess(block.index('REFRESH60_CONFIRM_FAILED'), block.index('refresh_revert || true'))
        without_revert = out.replace('    refresh_revert || true\n', '', 1)
        self.assertNotEqual(without_revert, out)

    def test_09_planted_defect_is_caught(self):
        out = self.s['output']
        without_confirm = ''.join(x for x in out.splitlines(keepends=True) if '"$NT" accel refresh confirm' not in x)
        self.assertNotEqual(without_confirm, out)
        with self.assertRaises(AssertionError):
            verify_ordering(without_confirm)
        without_call = out.replace('refresh_begin || true\n', '', 1)
        self.assertNotEqual(without_call, out)
        with self.assertRaises(AssertionError):
            verify_ordering(without_call)
        verify_ordering(out)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.src = os.path.join(self.td.name, 'guard.sh')
        self.dst = os.path.join(self.td.name, 'patched.sh')
        with open(self.src, 'wb') as f:
            f.write(state()['raw'])

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', CLI, *args], capture_output=True, text=True, timeout=60)

    def test_cli_writes_only_out_and_prints_both_sha256(self):
        raw = state()['raw']
        r = self.run_cli('--in', self.src, '--out', self.dst)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.src, 'rb') as f:
            self.assertEqual(f.read(), raw)
        with open(self.dst, 'rb') as f:
            out = f.read()
        self.assertEqual(out.decode('utf-8'), state()['output'])
        self.assertIn(hashlib.sha256(raw).hexdigest(), r.stdout)
        self.assertIn(hashlib.sha256(out).hexdigest(), r.stdout)
        self.assertEqual(sorted(os.listdir(self.td.name)), ['guard.sh', 'patched.sh'])

    def test_cli_refuses_existing_out(self):
        with open(self.dst, 'wb') as f:
            f.write(b'keep me')
        r = self.run_cli('--in', self.src, '--out', self.dst)
        self.assertNotEqual(r.returncode, 0)
        with open(self.dst, 'rb') as f:
            self.assertEqual(f.read(), b'keep me')

    def test_cli_refuses_out_equal_to_in(self):
        before = state()['raw']
        r = self.run_cli('--in', self.src, '--out', self.src)
        self.assertNotEqual(r.returncode, 0)
        with open(self.src, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_cli_refuses_bad_anchor_and_writes_nothing(self):
        bad = ''.join(x for x in state()['source'].splitlines(keepends=True) if x.strip() != PIPERELOAD)
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(bad)
        r = self.run_cli('--in', self.src, '--out', self.dst)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('exactly one', r.stderr)
        self.assertFalse(os.path.exists(self.dst))


if __name__ == '__main__':
    unittest.main()
