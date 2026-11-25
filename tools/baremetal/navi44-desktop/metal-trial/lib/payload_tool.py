#!/usr/bin/env python3
"""Payload helper for stage.sh, install-trial.sh and rollback-trial.sh (generic: live bundle N -> N+1).

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
XLATE_KEY = 'Contents/Resources/libn48xlate.dylib'
KEYS = (MAIN_KEY,
        'Contents/Resources/libvulkan_radeon.dylib',
        XLATE_KEY)
GUARD_RE = re.compile(
    r'shasum -a 256 "/Library/GPUBundles/Navi48Metal\.bundle/([^"]+)" \| cut -d " " -f 1\) == ([0-9a-f]{64}) \]\]')
# Exact text of the CFBundleVersion check line (@V@ = version number).
VERSION_LINE = ('[[ "$bundle_version" == @V@ ]] || { echo "STOP expected Stage@V@ Metal bundle version @V@, '
                'got: $bundle_version"; exit 1; }')
# The same line as a regular expression; group 1 is the version and \1 must repeat it.
VERSION_RE = re.compile(
    r'\[\[ "\$bundle_version" == ([1-9][0-9]*) \]\] \|\| \{ echo "STOP expected Stage\1 Metal bundle version \1, '
    r'got: \$bundle_version"; exit 1; \}')
# Profile names: stage<version>-<name>, with lower-case letters, digits and hyphens (stage32-dualsrc-v1).
PROFILE_RE = re.compile(r'stage([1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*')


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


def version_int(text, label):
    if not isinstance(text, str) or not re.fullmatch(r'[1-9][0-9]*', text):
        die('%s is not a positive integer: %r' % (label, text))
    return int(text)


def profile_check(name, version):
    """Refuse a guard profile name that is not stage<version>-<name>."""
    match = PROFILE_RE.fullmatch(name or '')
    if not match or int(match.group(1)) != int(version):
        die('profile %r is not stage%s-<name>' % (name, version))
    return name


def guard_version(path):
    """The single bundle_version check line of a guard, as the version it requires."""
    lines = [line for line in Path(path).read_text().splitlines() if 'bundle_version" ==' in line]
    if len(lines) != 1:
        die('guard has %d bundle_version check lines, expected 1' % len(lines))
    match = VERSION_RE.fullmatch(lines[0])
    if not match:
        die('bundle_version check line has an unexpected form')
    return match.group(1)


def guard_profile(path):
    """The single PROFILE= line of a guard, as the profile name."""
    names = [line[len('PROFILE='):] for line in Path(path).read_text().splitlines() if line.startswith('PROFILE=')]
    if len(names) != 1:
        die('guard has %d PROFILE= lines, expected 1' % len(names))
    if not PROFILE_RE.fullmatch(names[0]):
        die('guard profile has an unexpected form: %r' % names[0])
    return names[0]


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


def check_transition(old, new, flags):
    old_number = version_int(old, 'live bundle version')
    new_number = version_int(new, 'candidate bundle version')
    if new_number <= old_number or (new_number != old_number + 1 and '--allow-skip' not in flags):
        die('new version %s is not live %d + 1; an explicit newer version requires --allow-skip' % (new, old_number))
    return old_number, new_number


def cmd_manifest(args):  # OUT PAYLOAD PROFILE SOURCE LIVE_GUARD_SHA256 LIVE_VERSION LIVE_PROFILE [--allow-skip]
    out, payload, profile, source, live_guard_sha, live_version, live_profile, *flags = args
    if set(flags) - {'--allow-skip'}:
        die('unknown manifest option')
    candidate = bundle_version(Path(payload, BUNDLE))
    live_number, candidate_number = check_transition(live_version, candidate, flags)
    profile_check(profile, candidate_number)
    profile_check(live_profile, live_number)
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
        'live_bundle_version': live_version,
        'live_profile': live_profile,
        'candidate_bundle_version': candidate,
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
    # LIVE_GUARD NEW_BUNDLE OUT_GUARD OUT_DIFF OLD_PROFILE NEW_PROFILE OLD_VERSION NEW_VERSION [flags]
    live, new_bundle, out_guard, out_diff, old_prof, new_prof, old_ver, new_ver, *flags = args
    if set(flags) - {'--allow-skip', '--allow-radv-change'}:
        die('unknown guard edit option')
    old_number, new_number = check_transition(old_ver, new_ver, flags)
    profile_check(old_prof, old_number)
    profile_check(new_prof, new_number)
    if bundle_version(new_bundle) != new_ver:
        die('new bundle CFBundleVersion is not ' + new_ver)
    old_lines = Path(live).read_text().splitlines(keepends=True)
    actual = tree(new_bundle)
    live_constants = guard_hashes(live)
    if any(key not in actual for key in live_constants):
        die('new bundle lacks a component pinned by the live guard')
    if actual[MAIN_KEY] == live_constants[MAIN_KEY]:
        die('new main binary has the same hash as the live guard; nothing to stage')
    changed_hashes = {key: actual[key] for key, digest in live_constants.items() if actual[key] != digest}
    if set(changed_hashes) - {MAIN_KEY, XLATE_KEY} and '--allow-radv-change' not in flags:
        die('bundle libvulkan_radeon.dylib differs from the live guard constant; use --allow-radv-change')

    replacements = {
        'PROFILE=' + old_prof: 'PROFILE=' + new_prof,
        VERSION_LINE.replace('@V@', old_ver): VERSION_LINE.replace('@V@', new_ver),
    }
    for line in old_lines:
        body = line.rstrip('\n')
        match = GUARD_RE.search(body)
        if match and match.group(1) in changed_hashes:
            replacements[body] = body[:match.start(2)] + changed_hashes[match.group(1)] + body[match.end(2):]

    counts = dict.fromkeys(replacements, 0)
    new_lines, removed, added = [], [], []
    for line in old_lines:
        body = line.rstrip('\n')
        if body in replacements:
            counts[body] += 1
            new_line = replacements[body] + ('\n' if line.endswith('\n') else '')
            removed.append(line)
            added.append(new_line)
            new_lines.append(new_line)
        else:
            new_lines.append(line)
    if len(replacements) != 2 + len(changed_hashes) or any(count != 1 for count in counts.values()):
        die('live guard does not contain each expected line exactly once: %s' % counts)

    diff_text = ''.join(difflib.unified_diff(old_lines, new_lines,
                                             fromfile='live-guard', tofile='bundle-%s-guard' % new_ver, n=3))
    Path(out_guard).write_text(''.join(new_lines))
    Path(out_diff).write_text(diff_text)
    print('guard edited: %d lines (profile, version, component hashes); changed lines:' % len(removed))
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


def cmd_guard_version(args):  # GUARD -> the version its bundle_version check requires
    print(guard_version(args[0]))


def cmd_guard_profile(args):  # GUARD -> its PROFILE= name
    print(guard_profile(args[0]))


def cmd_profile_check(args):  # NAME VERSION -> prints NAME if it is stage<VERSION>-<name>
    print(profile_check(args[0], args[1]))


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
    'guard-version': cmd_guard_version, 'guard-profile': cmd_guard_profile, 'profile-check': cmd_profile_check,
    'phase': cmd_phase, 'swap': cmd_swap, 'hash': cmd_hash,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        die('usage: payload_tool.py {%s} ARGS' % '|'.join(sorted(COMMANDS)))
    COMMANDS[sys.argv[1]](sys.argv[2:])
