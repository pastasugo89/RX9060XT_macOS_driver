#!/usr/bin/env python3
"""Adds the refresh-60 hook to the Navi44 accelerated-reboot guard (additions only).

apply_refresh_patch(text) returns the guard text with the refresh-60 lines inserted.
No existing line is changed, removed or reordered. It raises ValueError when an
anchor line does not match exactly once, or when the text already carries MARKER.

CLI:  apply_refresh_guard.py --in <guard> --out <new file>
      --in is read and never written; --out must not exist and is created exclusively.
      The sha256 of the input and of the output are printed.
"""
import argparse
import hashlib
import os
import sys

MARKER = 'REFRESH60_INSTALLED'

PROFILE_PREFIX = 'PROFILE='
ROLLBACK_DEF = 'rollback() {'
PIPEARM_FAILSAFE = '"$NT" accel pipearm 0 || true'
PIPERELOAD = '"$NT" accel pipereload || { echo \'STOP pipereload failed\'; exit 1; }'
RESTART_PREFIX = 'echo "RESTART_WINDOWSERVER old=$oldpid'
READY_PREFIX = 'echo "WINDOWSERVER_READY pid=$newpid'

# Inserted after the PROFILE= line.
VARIABLES = '''# refresh-60: kernel revert timeout (seconds), flag file, and whether 60 Hz is active.
REFRESH_TIMEOUT=120
REFRESH_FLAG="$APP/refresh-60"
refresh_active=0
'''

# Inserted before the rollback() definition (both helpers are defined before any use).
FUNCTIONS = r'''
# REFRESH60_INSTALLED: 60 Hz scanout hook (tools/baremetal/navi44-desktop/refresh-60).
# Opt-in only: it runs when the root-owned flag file "$APP/refresh-60" is a valid
# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.669 and
# com.hackintosh.RDNA4FB 0.0.9. It never fails the boot: a refusal, an error or a
# missing precondition leaves 120 Hz in place, and a stable boot keeps 60 Hz.
# The request arms the kernel's own timeout, which reverts to 120 Hz unless the
# confirmation arrives. refresh_revert is the failsafe revert on every exit path
# of rollback. Both helpers return 0 on every path, so set -e cannot abort the
# guard through them.
refresh_revert() {
  if [[ "$refresh_active" == 1 ]]; then
    "$NT" accel refresh 120 || true
    refresh_active=0
    echo 'REFRESH60_REVERTED'
  fi
  return 0
}
refresh_begin() {
  local kexts out rc
  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.669\)'
  local re_fb='com\.hackintosh\.RDNA4FB[[:space:]]+\(0\.0\.9\)'
  if [[ ! -e "$REFRESH_FLAG" && ! -L "$REFRESH_FLAG" ]]; then
    return 0
  fi
  if ! root_flag_valid "$APP/refresh-60"; then
    echo 'REFRESH60_SKIPPED flag is not a root-owned 0644 regular file'
    return 0
  fi
  kexts=$(kmutil showloaded --list-only 2>/dev/null || true)
  if ! [[ $kexts =~ $re_bringup && $kexts =~ $re_fb ]]; then
    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.669 and RDNA4FB 0.0.9'
    return 0
  fi
  if out=$("$NT" accel refresh 60 "$REFRESH_TIMEOUT" 2>&1); then
    rc=0
  else
    rc=$?
  fi
  if (( rc == 0 )); then
    refresh_active=1
    printf 'REFRESH60_REQUESTED %s\n' "$out"
  else
    printf 'REFRESH60_FAILED %s\n' "$out"
    "$NT" accel refresh 120 || true
  fi
  return 0
}

'''

# Inserted before the RESTART_WINDOWSERVER line, after pipereload and the oldpid checks.
BEFORE_RESTART = '''# refresh-60: request 60 Hz before WindowServer restarts (never fatal; see refresh_begin).
refresh_begin || true
'''

# Inserted after the pipearm failsafe line inside rollback(), before the WindowServer kill.
FAILSAFE = '''    refresh_revert || true
'''

# Inserted after the WINDOWSERVER_READY line.
AFTER_READY = r'''# refresh-60: confirm 60 Hz now that WindowServer is back. A failed confirmation reverts to 120 Hz at once, so no revert is left to the
# kernel timeout in the middle of a login; the kernel timeout remains the last line of defence. Neither path fails the boot.
if (( refresh_active == 1 )); then
  if confirm_out=$("$NT" accel refresh confirm 2>&1); then
    echo 'REFRESH60_CONFIRMED'
  else
    printf 'REFRESH60_CONFIRM_FAILED %s\n' "$confirm_out"
    refresh_revert || true
  fi
  "$NT" accel refresh status 2>&1 || true
fi
'''


def _only(lines, label, match):
    """Index of the single line whose stripped text satisfies match; ValueError otherwise."""
    hits = [i for i, line in enumerate(lines) if match(line.strip())]
    if len(hits) != 1:
        raise ValueError(f'anchor {label!r} must match exactly one line; matched {len(hits)}')
    return hits[0]


def apply_refresh_patch(text):
    """Return text with the refresh-60 hook inserted. Only added lines; no line changed."""
    if not isinstance(text, str):
        raise TypeError('guard text must be a str')
    if MARKER in text:
        raise ValueError(f'{MARKER} is already present: the refresh-60 hook is applied; refusing to apply it twice')
    if '\r' in text:
        raise ValueError('guard text contains CR characters; CRLF line endings are not supported')
    lines = text.splitlines(keepends=True)

    i_profile = _only(lines, PROFILE_PREFIX, lambda s: s.startswith(PROFILE_PREFIX))
    i_rollback = _only(lines, ROLLBACK_DEF, lambda s: s == ROLLBACK_DEF)
    i_pipearm = _only(lines, PIPEARM_FAILSAFE, lambda s: s == PIPEARM_FAILSAFE)
    i_reload = _only(lines, PIPERELOAD, lambda s: s == PIPERELOAD)
    i_restart = _only(lines, RESTART_PREFIX, lambda s: s.startswith(RESTART_PREFIX))
    i_ready = _only(lines, READY_PREFIX, lambda s: s.startswith(READY_PREFIX))

    i_end = next((i for i in range(i_rollback + 1, len(lines)) if lines[i].rstrip('\n') == '}'), None)
    if i_end is None:
        raise ValueError('rollback() has no closing brace at column 0')
    if not i_profile < i_rollback:
        raise ValueError('PROFILE= must precede rollback() in the guard')
    if not i_rollback < i_pipearm < i_end:
        raise ValueError('the pipearm failsafe line is not inside rollback()')
    if not i_reload < i_restart < i_ready:
        raise ValueError('anchors out of order: pipereload, RESTART_WINDOWSERVER, WINDOWSERVER_READY')
    for i in (i_profile, i_pipearm, i_ready):
        if not lines[i].endswith('\n'):
            raise ValueError('an anchor line has no trailing newline; refusing to insert after it')

    before = {i_rollback: FUNCTIONS, i_restart: BEFORE_RESTART}
    after = {i_profile: VARIABLES, i_pipearm: FAILSAFE, i_ready: AFTER_READY}
    out = []
    for i, line in enumerate(lines):
        if i in before:
            out.append(before[i])
        out.append(line)
        if i in after:
            out.append(after[i])
    return ''.join(out)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _same_file(a, b):
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    if os.path.exists(a) and os.path.exists(b):
        return os.path.samefile(a, b)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description='Write a copy of the guard with the refresh-60 hook.')
    parser.add_argument('--in', dest='src', required=True, help='guard to read (never written)')
    parser.add_argument('--out', dest='dst', required=True, help='new file to create (must not exist)')
    args = parser.parse_args(argv)

    if _same_file(args.src, args.dst):
        print('REFUSED: --out is the same file as --in; the input is never overwritten', file=sys.stderr)
        return 2
    if os.path.lexists(args.dst):
        print(f'REFUSED: --out already exists: {args.dst}', file=sys.stderr)
        return 2
    try:
        with open(args.src, 'rb') as f:
            raw = f.read()
        patched = apply_refresh_patch(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 2
    data = patched.encode('utf-8')
    try:
        fd = os.open(args.dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except OSError as exc:
        print(f'REFUSED: cannot create --out: {exc}', file=sys.stderr)
        return 1
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    print(f'input  sha256 {_sha256(raw)} {len(raw)} bytes {args.src}')
    print(f'output sha256 {_sha256(data)} {len(data)} bytes {args.dst}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
