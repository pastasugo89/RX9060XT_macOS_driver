#!/usr/bin/env python3
"""Payload helper for stage.sh, install-trial.sh and rollback-trial.sh (bundle 31).

Run only as:  /usr/bin/python3 -I payload_tool.py COMMAND ARGS...
It reads and writes only the paths named on the command line. It never touches
the GPU, WindowServer, launchd, or the network.
"""
import ctypes
import datetime
import difflib
import hashlib
import json
import os
import plistlib
import re
import stat
import sys
from pathlib import Path

BUNDLE = 'Navi48Metal.bundle'
GUARD_NAME = 'accelerated-reboot-trial.sh'
MANIFEST_NAME = 'manifest.json'
MAIN_KEY = 'Contents/MacOS/Navi48Metal'
KEYS = (MAIN_KEY,
        'Contents/Resources/libvulkan_radeon.dylib',
        'Contents/Resources/libn48xlate.dylib')
GUARD_RE = re.compile(
    r'shasum -a 256 "/Library/GPUBundles/Navi48Metal\.bundle/([^"]+)" \| cut -d " " -f 1\) == ([0-9a-f]{64}) \]\]')
# Exact text of the CFBundleVersion check line in the live guard (@V@ = version number).
VERSION_LINE = ('[[ "$bundle_version" == @V@ ]] || { echo "STOP expected Stage@V@ Metal bundle version @V@, '
                'got: $bundle_version"; exit 1; }')


def die(message):
    print('STOP: ' + message, file=sys.stderr)
    sys.exit(1)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def tree(root):
    """Relative path -> sha256 for every regular file. Symlinks and special files are refused."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        die('not a real directory: ' + str(root))
    files = {}
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        for name in dirnames + filenames:
            if Path(dirpath, name).is_symlink():
                die('symlink refused: ' + str(Path(dirpath, name)))
        for name in filenames:
            path = Path(dirpath, name)
            if not stat.S_ISREG(path.lstat().st_mode):
                die('special file refused: ' + str(path))
            files[path.relative_to(root).as_posix()] = sha256(path)
    return files


def load_json(path):
    return json.loads(Path(path).read_text())


def bundle_version(bundle):
    with open(Path(bundle, 'Contents', 'Info.plist'), 'rb') as stream:
        return str(plistlib.load(stream).get('CFBundleVersion', ''))


def guard_hashes(path):
    found = {}
    for rel, digest in GUARD_RE.findall(Path(path).read_text()):
        if rel in found:
            die('duplicate hash constant: ' + rel)
        found[rel] = digest
    if set(found) != set(KEYS):
        die('guard constants cover %s, expected %s' % (sorted(found), list(KEYS)))
    return found


def cmd_tree(args):
    print(json.dumps(tree(args[0]), indent=1, sort_keys=True))


def cmd_compare(args):
    first, second = load_json(args[0]), load_json(args[1])
    if first != second:
        only_first = sorted(set(first) - set(second))[:5]
        only_second = sorted(set(second) - set(first))[:5]
        changed = [k for k in first if k in second and first[k] != second[k]][:5]
        die('trees differ: only-first=%s only-second=%s changed=%s' % (only_first, only_second, changed))
    print('identical: %d files' % len(first))


def cmd_manifest(args):  # OUT PAYLOAD PROFILE SOURCE LIVE_GUARD_SHA256
    out, payload, profile, source, live_guard_sha = args
    files = tree(payload)
    files.pop(MANIFEST_NAME, None)
    for key in KEYS:
        if BUNDLE + '/' + key not in files:
            die('payload lacks ' + key)
    if GUARD_NAME not in files:
        die('payload lacks ' + GUARD_NAME)
    if not re.fullmatch(r'[0-9a-f]{64}', live_guard_sha):
        die('live guard sha256 is malformed')
    manifest = {
        'schema': 1,
        'candidate_bundle_version': bundle_version(Path(payload, BUNDLE)),
        'profile': profile,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'source_bundle': source,
        'live_guard_sha256': live_guard_sha,
        'key_files': {k: files[BUNDLE + '/' + k] for k in KEYS},
        'guard_sha256': files[GUARD_NAME],
        'files': files,
    }
    Path(out).write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print('manifest entries: %d' % len(files))


def cmd_manifest_get(args):  # MANIFEST KEY   (top-level scalar only)
    manifest_path, key = args
    manifest = load_json(manifest_path)
    if manifest.get('schema') != 1:
        die('unknown manifest schema')
    value = manifest.get(key)
    if not isinstance(value, str) or not value:
        die('manifest lacks string field ' + key)
    print(value)


def cmd_check(args):  # MANIFEST PREFIX DIR   (PREFIX '' = whole payload)
    manifest_path, prefix, directory = args
    manifest = load_json(manifest_path)
    if manifest.get('schema') != 1:
        die('unknown manifest schema')
    expected = {k[len(prefix):]: v for k, v in manifest['files'].items() if k.startswith(prefix)}
    if not expected:
        die('manifest has no entries under prefix %r' % prefix)
    actual = tree(directory)
    if prefix == '':
        actual.pop(MANIFEST_NAME, None)
    if set(actual) != set(expected):
        die('file set differs: missing=%s extra=%s' % (sorted(set(expected) - set(actual))[:5],
                                                       sorted(set(actual) - set(expected))[:5]))
    for rel in sorted(expected):
        if actual[rel] != expected[rel]:
            die('hash mismatch: ' + rel)
    print('verified %d files under prefix %r' % (len(expected), prefix))


def cmd_edit_guard(args):
    # LIVE_GUARD NEW_BUNDLE OUT_GUARD OUT_DIFF OLD_PROFILE NEW_PROFILE OLD_VERSION NEW_VERSION
    # Edits a COPY of the live guard. Allowed changes, and only these:
    #   1. the PROFILE= line (OLD_PROFILE -> NEW_PROFILE)
    #   2. the bundle_version check line, including its message (OLD_VERSION -> NEW_VERSION)
    #   3. the hash constant of Contents/MacOS/Navi48Metal (taken from NEW_BUNDLE)
    # The two dylib constants must already equal NEW_BUNDLE's files (they are not edited).
    live, new_bundle, out_guard, out_diff, old_prof, new_prof, old_ver, new_ver = args
    if bundle_version(new_bundle) != new_ver:
        die('new bundle CFBundleVersion is not ' + new_ver)
    old_text = Path(live).read_text()
    old_lines = old_text.splitlines(keepends=True)
    actual = tree(new_bundle)
    live_constants = guard_hashes(live)
    for key in KEYS[1:]:
        if live_constants[key] != actual.get(key):
            die('bundle %s differs from the live guard constant; the guard edit only changes the main binary' % key)
    new_main = actual[MAIN_KEY]
    if new_main == live_constants[MAIN_KEY]:
        die('new main binary has the same hash as the live guard; nothing to stage')

    old_profile_line = 'PROFILE=' + old_prof
    new_profile_line = 'PROFILE=' + new_prof
    old_version_line = VERSION_LINE.replace('@V@', old_ver)
    new_version_line = VERSION_LINE.replace('@V@', new_ver)
    counts = {'profile': 0, 'version': 0, 'main': 0}
    new_lines = []
    for line in old_lines:
        eol = '\n' if line.endswith('\n') else ''
        body = line[:-1] if eol else line
        match = GUARD_RE.search(body)
        if body == old_profile_line:
            counts['profile'] += 1
            new_lines.append(new_profile_line + eol)
        elif body == old_version_line:
            counts['version'] += 1
            new_lines.append(new_version_line + eol)
        elif match and match.group(1) == MAIN_KEY:
            counts['main'] += 1
            new_lines.append(body[:match.start(2)] + new_main + body[match.end(2):] + eol)
        else:
            new_lines.append(line)
    if counts != {'profile': 1, 'version': 1, 'main': 1}:
        die('live guard does not contain each expected line exactly once: %s' % counts)

    # Structural check: the only differences are three one-line replacements, nothing else.
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    changes = [op for op in matcher.get_opcodes() if op[0] != 'equal']
    if len(changes) != 3 or any(tag != 'replace' or i2 - i1 != 1 or j2 - j1 != 1
                                for tag, i1, i2, j1, j2 in changes):
        die('guard diff contains lines other than the three allowed ones')
    removed = [old_lines[i1] for _, i1, _, _, _ in changes]
    added = [new_lines[j1] for _, _, _, j1, _ in changes]
    removed_bodies = sorted(line.rstrip('\n') for line in removed)
    expected_bodies = sorted([old_profile_line, old_version_line,
                              next(line for line in old_lines if GUARD_RE.search(line)
                                   and GUARD_RE.search(line).group(1) == MAIN_KEY).rstrip('\n')])
    if removed_bodies != expected_bodies:
        die('guard diff removes unexpected lines')

    diff_text = ''.join(difflib.unified_diff(old_lines, new_lines,
                                             fromfile='live-guard', tofile='bundle-%s-guard' % new_ver, n=3))
    Path(out_guard).write_text(''.join(new_lines))
    Path(out_diff).write_text(diff_text)
    print('guard edited: 3 lines (profile, version, main binary hash); changed lines:')
    for line in removed:
        print('  - ' + line.rstrip('\n'))
    for line in added:
        print('  + ' + line.rstrip('\n'))


def cmd_guard_check(args):  # GUARD BUNDLE VERSION
    guard, bundle, version = args
    constants = guard_hashes(guard)
    actual = tree(bundle)
    for key in KEYS:
        if actual.get(key) != constants[key]:
            die('guard constant does not match bundle file: ' + key)
    text = Path(guard).read_text()
    if text.count('bundle_version" == %s ]]' % version) != 1:
        die('guard does not check CFBundleVersion == ' + version)
    print('guard constants match bundle; version check == %s' % version)


def cmd_phase(args):  # reads boot-state.py status JSON on stdin
    data = json.load(sys.stdin)
    print('absent' if data is None else str(data.get('phase', 'unknown')))


def cmd_swap(args):  # FIRST SECOND  (atomic exchange, RENAME_SWAP)
    first, second = args
    libc = ctypes.CDLL(None, use_errno=True)
    renamex = libc.renamex_np
    renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex.restype = ctypes.c_int
    if renamex(os.fsencode(first), os.fsencode(second), 0x2) != 0:
        die('atomic swap failed, errno %d' % ctypes.get_errno())
    print('swapped')


def cmd_hash(args):
    print(sha256(args[0]))


COMMANDS = {
    'tree': cmd_tree, 'compare': cmd_compare, 'manifest': cmd_manifest, 'manifest-get': cmd_manifest_get,
    'check': cmd_check, 'edit-guard': cmd_edit_guard, 'guard-check': cmd_guard_check,
    'phase': cmd_phase, 'swap': cmd_swap, 'hash': cmd_hash,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        die('usage: payload_tool.py {%s} ARGS' % '|'.join(sorted(COMMANDS)))
    COMMANDS[sys.argv[1]](sys.argv[2:])
