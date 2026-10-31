#!/usr/bin/env python3
"""Offline test for the bundle-31 guard edit (the step stage.sh runs via lib/payload_tool.py edit-guard).

Runs without root, without the GPU and without touching /Library: it reads the live guard
(read only) and copies it into a temporary directory. Fake bundles stand in for Navi48Metal.bundle.

Because fake binaries cannot match the real dylib hashes in the live guard, the positive fixture
re-points the two dylib constants at fake files (they stay unchanged by the edit). The real live
guard is still used for the refusal case, and for checking that a copy of it is accepted by the tool
logic up to the dylib comparison.

Usage: /usr/bin/python3 -I test-guard-edit.py
"""
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / 'lib' / 'payload_tool.py'
LIVE_GUARD = Path('/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh')
OLD_PROFILE = 'stage30-vonly-v1'
NEW_PROFILE = 'stage31-msaa-iosurface-v1'
OLD_VER, NEW_VER = '30', '31'
MAIN = 'Contents/MacOS/Navi48Metal'
VK = 'Contents/Resources/libvulkan_radeon.dylib'
XL = 'Contents/Resources/libn48xlate.dylib'
PY = sys.executable

failures = []


def check(label, condition, detail=''):
    if condition:
        print('PASS ' + label)
    else:
        print('FAIL ' + label + (': ' + detail if detail else ''))
        failures.append(label)


def run_tool(*args):
    return subprocess.run([PY, '-I', str(TOOL)] + [str(a) for a in args],
                          capture_output=True, text=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_bundle(root, version, main_bytes, vk_bytes, xl_bytes):
    b = Path(root, 'Navi48Metal.bundle')
    (b / 'Contents/MacOS').mkdir(parents=True)
    (b / 'Contents/Resources').mkdir(parents=True)
    with open(b / 'Contents/Info.plist', 'wb') as f:
        plistlib.dump({'CFBundleVersion': version, 'CFBundleIdentifier': 'test.navi48'}, f)
    (b / MAIN).write_bytes(main_bytes)
    (b / VK).write_bytes(vk_bytes)
    (b / XL).write_bytes(xl_bytes)
    return b


def expected_guard_lines(live_text, new_main_sha, old_main_sha):
    """Independent expectation: the live text with exactly three lines replaced."""
    out = []
    for line in live_text.splitlines(keepends=True):
        body = line.rstrip('\n')
        eol = '\n' if line.endswith('\n') else ''
        if body == 'PROFILE=' + OLD_PROFILE:
            out.append('PROFILE=' + NEW_PROFILE + eol)
        elif body == ('[[ "$bundle_version" == 30 ]] || { echo "STOP expected Stage30 Metal bundle version 30, '
                      'got: $bundle_version"; exit 1; }'):
            out.append('[[ "$bundle_version" == 31 ]] || { echo "STOP expected Stage31 Metal bundle version 31, '
                       'got: $bundle_version"; exit 1; }' + eol)
        elif old_main_sha in body and MAIN in body and 'shasum' in body:
            out.append(body.replace(old_main_sha, new_main_sha) + eol)
        else:
            out.append(line)
    return ''.join(out)


def diff_changes(diff_text):
    removed, added = [], []
    for line in diff_text.splitlines():
        if line.startswith('---') or line.startswith('+++'):
            continue
        if line.startswith('-'):
            removed.append(line[1:])
        elif line.startswith('+'):
            added.append(line[1:])
    return removed, added


def main():
    if not TOOL.is_file():
        print('FAIL payload tool missing: ' + str(TOOL))
        return 1
    work = Path(tempfile.mkdtemp(prefix='b31-guard-test.'))
    try:
        run_positive(work)
        run_negative(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print()
    if failures:
        print('FAILED: %d check(s)' % len(failures))
        return 1
    print('ALL CHECKS PASSED')
    return 0


def run_positive(work):
    print('== positive fixture (copy of the live guard, fake bundles)')
    if not LIVE_GUARD.is_file():
        print('SKIP live guard not readable: ' + str(LIVE_GUARD))
        return
    live_text = LIVE_GUARD.read_text()
    check('live guard has profile %s exactly once' % OLD_PROFILE,
          live_text.count('\nPROFILE=' + OLD_PROFILE + '\n') == 1)

    old_main_bytes = b'fake bundle 30 main binary'
    vk_bytes = b'fake vulkan radeon'
    xl_bytes = b'fake translator'
    v30 = make_bundle(work / 'v30', OLD_VER, old_main_bytes, vk_bytes, xl_bytes)
    v31 = make_bundle(work / 'v31', NEW_VER, b'fake bundle 31 main binary, different', vk_bytes, xl_bytes)
    old_main_sha, new_main_sha = sha(v30 / MAIN), sha(v31 / MAIN)

    # Fixture guard: a copy of the live guard whose three constants point at the fake v30 files.
    fixture = work / 'live-guard-copy.sh'
    lines = []
    for line in live_text.splitlines(keepends=True):
        if 'shasum -a 256' in line and VK in line:
            line = re.sub(r'== [0-9a-f]{64} \]\]', '== ' + sha(v30 / VK) + ' ]]', line)
        elif 'shasum -a 256' in line and XL in line:
            line = re.sub(r'== [0-9a-f]{64} \]\]', '== ' + sha(v30 / XL) + ' ]]', line)
        elif 'shasum -a 256' in line and MAIN in line:
            line = re.sub(r'== [0-9a-f]{64} \]\]', '== ' + old_main_sha + ' ]]', line)
        lines.append(line)
    fixture.write_text(''.join(lines))
    fixture_text = fixture.read_text()

    r = run_tool('guard-check', fixture, v30, OLD_VER)
    check('fixture guard matches fake v30 bundle', r.returncode == 0, r.stderr.strip())

    out_guard = work / 'GUARD-31.sh'
    out_diff = work / 'GUARD.diff'
    r = run_tool('edit-guard', fixture, v31, out_guard, out_diff, OLD_PROFILE, NEW_PROFILE, OLD_VER, NEW_VER)
    check('edit-guard accepts the fixture', r.returncode == 0, r.stdout + r.stderr)
    if r.returncode != 0:
        return

    new_text = out_guard.read_text()
    expected = expected_guard_lines(fixture_text, new_main_sha, old_main_sha)
    check('new guard equals the fixture with exactly the three expected lines replaced',
          new_text == expected)

    diff_text = out_diff.read_text()
    removed, added = diff_changes(diff_text)
    exp_removed = [
        'PROFILE=' + OLD_PROFILE,
        '[[ "$bundle_version" == 30 ]] || { echo "STOP expected Stage30 Metal bundle version 30, got: $bundle_version"; exit 1; }',
        '[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal" | cut -d " " -f 1) == %s ]] || { echo "STOP bundle component changed: MacOS/Navi48Metal"; exit 1; }' % old_main_sha,
    ]
    exp_added = [
        'PROFILE=' + NEW_PROFILE,
        '[[ "$bundle_version" == 31 ]] || { echo "STOP expected Stage31 Metal bundle version 31, got: $bundle_version"; exit 1; }',
        '[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal" | cut -d " " -f 1) == %s ]] || { echo "STOP bundle component changed: MacOS/Navi48Metal"; exit 1; }' % new_main_sha,
    ]
    check('GUARD.diff removes exactly the three old lines', sorted(removed) == sorted(exp_removed),
          repr(removed))
    check('GUARD.diff adds exactly the three new lines', sorted(added) == sorted(exp_added), repr(added))

    check('new guard sets the new profile', new_text.count('\nPROFILE=' + NEW_PROFILE + '\n') == 1)
    check('new guard has no old profile line', ('PROFILE=' + OLD_PROFILE) not in new_text)
    check('new guard checks version 31 only', new_text.count('bundle_version" == 31 ]]') == 1 and
          'bundle_version" == 30 ]]' not in new_text)
    check('new guard main constant is the new binary hash', ('== %s ]]' % new_main_sha) in new_text)
    check('new guard keeps the dylib constants', ('== %s ]]' % sha(v30 / VK)) in new_text and
          ('== %s ]]' % sha(v30 / XL)) in new_text)

    bash = subprocess.run(['bash', '-n', str(out_guard)], capture_output=True, text=True)
    check('new guard passes bash -n', bash.returncode == 0, bash.stderr)
    r = run_tool('guard-check', out_guard, v31, NEW_VER)
    check('guard-check accepts new guard against fake v31', r.returncode == 0, r.stderr.strip())
    r = run_tool('guard-check', out_guard, v31, OLD_VER)
    check('guard-check refuses version 30 for the new guard', r.returncode != 0)

    # Manifest of a payload holding the new bundle and guard.
    payload = work / 'payload'
    shutil.copytree(v31, payload / 'Navi48Metal.bundle')
    shutil.copy(out_guard, payload / 'accelerated-reboot-trial.sh')
    manifest = payload.parent / 'manifest.json'
    live_sha = sha(fixture)
    r = run_tool('manifest', manifest, payload, NEW_PROFILE, 'fixture-source', live_sha)
    check('manifest written', r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = json.loads(manifest.read_text())
        check('manifest records version 31 from the bundle', data.get('candidate_bundle_version') == '31')
        check('manifest records the live guard sha', data.get('live_guard_sha256') == live_sha)
        r = run_tool('manifest-get', manifest, 'live_guard_sha256')
        check('manifest-get returns the live guard sha', r.stdout.strip() == live_sha)
        r = run_tool('check', manifest, '', payload)
        check('payload verifies against its manifest', r.returncode == 0, r.stderr)
        (payload / 'accelerated-reboot-trial.sh').write_text(new_text + '# tampered\n')
        r = run_tool('check', manifest, '', payload)
        check('tampered guard is refused by the manifest check', r.returncode != 0)


def run_negative(work):
    print('== refusals (each must fail and write nothing)')
    if not LIVE_GUARD.is_file():
        print('SKIP live guard not readable: ' + str(LIVE_GUARD))
        return
    live_text = LIVE_GUARD.read_text()
    good_bundle = make_bundle(work / 'neg-good', NEW_VER, b'main-31', b'vk', b'xl')

    def refused(label, live_path, bundle, out_name):
        out_guard = work / (out_name + '.sh')
        out_diff = work / (out_name + '.diff')
        r = run_tool('edit-guard', live_path, bundle, out_guard, out_diff, OLD_PROFILE, NEW_PROFILE, OLD_VER, NEW_VER)
        check(label, r.returncode != 0 and not out_guard.exists() and not out_diff.exists(),
              'rc=%s out=%s' % (r.returncode, r.stdout.strip()))

    # 1. The real live guard against a fake bundle: the dylib constants do not match, so refused.
    refused('real live guard + fake bundle is refused (dylib constants differ)', LIVE_GUARD, good_bundle, 'n1')

    # 2. Version line changed in the copy (live guard says 29): the exact-line rule refuses.
    bad = work / 'bad-version.sh'
    bad.write_text(live_text.replace('== 30 ]] ||', '== 29 ]] ||', 1))
    refused('guard whose version line differs is refused', bad, good_bundle, 'n2')

    # 3. Duplicate profile line.
    bad = work / 'bad-profile.sh'
    bad.write_text(live_text.replace('\nPROFILE=' + OLD_PROFILE + '\n',
                                     '\nPROFILE=' + OLD_PROFILE + '\nPROFILE=' + OLD_PROFILE + '\n', 1))
    refused('guard with a duplicated profile line is refused', bad, good_bundle, 'n3')

    # 4. Bundle whose CFBundleVersion is not the new version.
    wrong_ver = make_bundle(work / 'neg-v30', OLD_VER, b'main-30', b'vk', b'xl')
    refused('bundle with version 30 is refused as the new bundle', LIVE_GUARD, wrong_ver, 'n4')

    # 5. A dylib that differs from the guard constant (fixture guard with the constants of vk-A, bundle has vk-B).
    fixture_bundle = make_bundle(work / 'neg-dylib', NEW_VER, b'main-31b', b'vk-B', b'xl')
    fixture = work / 'neg-dylib-guard.sh'
    fixture_text = live_text
    fixture_text = re.sub(r'== [0-9a-f]{64} \]\] \|\| \{ echo "STOP bundle component changed: Resources/libvulkan_radeon\.dylib"',
                          '== %s ]] || { echo "STOP bundle component changed: Resources/libvulkan_radeon.dylib"'
                          % hashlib.sha256(b'vk-A').hexdigest(), fixture_text)
    fixture.write_text(fixture_text)
    refused('a changed libvulkan_radeon in the new bundle is refused', fixture, fixture_bundle, 'n5')

    # 6. Same main binary as the live guard: nothing to stage, refused.
    same = make_bundle(work / 'neg-same', NEW_VER, b'x', b'y', b'z')
    fixture2 = work / 'neg-same-guard.sh'
    text2 = live_text
    text2 = re.sub(r'(shasum -a 256 "/Library/GPUBundles/Navi48Metal\.bundle/Contents/MacOS/Navi48Metal" \| cut -d " " -f 1\) == )[0-9a-f]{64}',
                   lambda m: m.group(1) + hashlib.sha256(b'x').hexdigest(), text2)
    text2 = re.sub(r'(shasum -a 256 "/Library/GPUBundles/Navi48Metal\.bundle/Contents/Resources/libvulkan_radeon\.dylib" \| cut -d " " -f 1\) == )[0-9a-f]{64}',
                   lambda m: m.group(1) + hashlib.sha256(b'y').hexdigest(), text2)
    text2 = re.sub(r'(shasum -a 256 "/Library/GPUBundles/Navi48Metal\.bundle/Contents/Resources/libn48xlate\.dylib" \| cut -d " " -f 1\) == )[0-9a-f]{64}',
                   lambda m: m.group(1) + hashlib.sha256(b'z').hexdigest(), text2)
    fixture2.write_text(text2)
    refused('new main binary identical to the live guard constant is refused', fixture2, same, 'n6')


if __name__ == '__main__':
    sys.exit(main())
