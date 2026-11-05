#!/usr/bin/env python3
"""Offline tests for the generic guard edit: live Metal bundle N -> N+1.

Covers the step stage.sh runs (lib/payload_tool.py edit-guard, guard-check, manifest) and the
refusals that stage.sh makes before it writes anything.

Runs without root and without the GPU. It never writes to /Library: it reads the live guard and the
live bundle's dylibs (read only) and copies them into a temporary directory. Fake main binaries stand in
for Navi48Metal; the dylibs are copies of the live ones, so the live guard's dylib constants still match.
N is read from the live guard, so the test follows the installed bundle (31 now, 32 after its install).

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
STAGE = HERE / 'stage.sh'
LIVE_BUNDLE = Path('/Library/GPUBundles/Navi48Metal.bundle')
LIVE_GUARD = Path('/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh')
MAC = Path('/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/builds/macos-20261031')
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
    return subprocess.run([PY, '-I', str(TOOL)] + [str(a) for a in args], capture_output=True, text=True)


def run_stage(*args):
    return subprocess.run(['bash', str(STAGE)] + [str(a) for a in args], capture_output=True, text=True)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def version_line(v):
    return ('[[ "$bundle_version" == %s ]] || { echo "STOP expected Stage%s Metal bundle version %s, '
            'got: $bundle_version"; exit 1; }' % (v, v, v))


def main_line(digest):
    return ('[[ $(shasum -a 256 "/Library/GPUBundles/Navi48Metal.bundle/Contents/MacOS/Navi48Metal" | '
            'cut -d " " -f 1) == %s ]] || { echo "STOP bundle component changed: MacOS/Navi48Metal"; exit 1; }' % digest)


def make_bundle(root, version, main_bytes, vk_bytes, xl_bytes):
    b = Path(root, 'Navi48Metal.bundle')
    (b / 'Contents/MacOS').mkdir(parents=True)
    (b / 'Contents/Resources/spvcache').mkdir(parents=True)
    with open(b / 'Contents/Info.plist', 'wb') as f:
        plistlib.dump({'CFBundleVersion': str(version), 'CFBundleIdentifier': 'test.navi48'}, f)
    (b / MAIN).write_bytes(main_bytes)
    (b / VK).write_bytes(vk_bytes)
    (b / XL).write_bytes(xl_bytes)
    return b


def expected_guard(text, n, old_profile, new, new_profile, old_main, new_main):
    """Independent expectation: the live text with exactly three lines replaced."""
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\n')
        eol = '\n' if line.endswith('\n') else ''
        if body == 'PROFILE=' + old_profile:
            out.append('PROFILE=' + new_profile + eol)
        elif body == version_line(n):
            out.append(version_line(new) + eol)
        elif body == main_line(old_main):
            out.append(main_line(new_main) + eol)
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


def with_constants(text, main_digest, vk_digest, xl_digest):
    """Copy of a guard whose three bundle constants are replaced (the rest is untouched)."""
    out = []
    for line in text.splitlines(keepends=True):
        if 'shasum -a 256' in line:
            digest = None
            if 'MacOS/Navi48Metal"' in line:
                digest = main_digest
            elif 'libvulkan_radeon.dylib"' in line:
                digest = vk_digest
            elif 'libn48xlate.dylib"' in line:
                digest = xl_digest
            if digest:
                line = re.sub(r'== [0-9a-f]{64} \]\]', '== %s ]]' % digest, line)
        out.append(line)
    return ''.join(out)


def snapshot(path):
    entries = {}
    if path.is_dir():
        for root, dirs, files in os.walk(str(path)):
            for name in dirs + files:
                p = Path(root, name)
                entries[str(p.relative_to(path))] = p.lstat().st_mtime_ns
    return entries


def read_live():
    """Live guard and bundle, read only. Returns None (with SKIP) when they are not readable."""
    try:
        text = LIVE_GUARD.read_text()
        info = plistlib.loads((LIVE_BUNDLE / 'Contents/Info.plist').read_bytes())
        main_live = (LIVE_BUNDLE / MAIN).read_bytes()
        vk_live = (LIVE_BUNDLE / VK).read_bytes()
        xl_live = (LIVE_BUNDLE / XL).read_bytes()
    except OSError as error:
        print('SKIP live guard or bundle not readable: %s' % error)
        return None
    versions = re.findall(r'^\[\[ "\$bundle_version" == ([0-9]+) \]\]', text, re.M)
    profiles = re.findall(r'^PROFILE=(\S+)$', text, re.M)
    main_digests = re.findall(r'MacOS/Navi48Metal" \| cut -d " " -f 1\) == ([0-9a-f]{64}) \]\]', text)
    check('live guard has exactly one bundle_version check', len(versions) == 1, repr(versions))
    check('live guard has exactly one PROFILE= line', len(profiles) == 1, repr(profiles))
    check('live guard has exactly one main binary constant', len(main_digests) == 1, repr(main_digests))
    if len(versions) != 1 or len(profiles) != 1 or len(main_digests) != 1:
        return None
    n = int(versions[0])
    check('live bundle CFBundleVersion equals the live guard version (N=%d)' % n,
          str(info.get('CFBundleVersion')) == str(n), repr(info.get('CFBundleVersion')))
    check('live guard main constant is the live main binary', main_digests[0] == sha_bytes(main_live))
    return {'text': text, 'ver': n, 'profile': profiles[0], 'main_sha': main_digests[0],
            'vk': vk_live, 'xl': xl_live}


def run_positive(work, live):
    n, old_profile = live['ver'], live['profile']
    new = n + 1
    new_profile = 'stage%d-dualsrc-test-v1' % new
    print('== case N=%d->%d with a copy of the live guard' % (n, new))
    d = work / 'positive'
    d.mkdir()
    guard = d / 'live-guard-copy.sh'
    shutil.copyfile(str(LIVE_GUARD), str(guard))
    check('the copy of the live guard is byte-identical', sha(guard) == sha(LIVE_GUARD))
    r = run_tool('guard-check', guard, LIVE_BUNDLE, n)
    check('live guard matches the live bundle (guard-check %d)' % n, r.returncode == 0, r.stderr.strip())

    main_new = b'fake bundle %d main binary (test)' % new
    main_new_sha = sha_bytes(main_new)
    bundle_new = make_bundle(d / 'new', new, main_new, live['vk'], live['xl'])
    out_guard, out_diff = d / 'GUARD-new.sh', d / 'GUARD.diff'
    r = run_tool('edit-guard', guard, bundle_new, out_guard, out_diff, old_profile, new_profile, n, new)
    check('edit-guard accepts the live guard copy for N=%d->%d' % (n, new), r.returncode == 0,
          r.stdout + r.stderr)
    if r.returncode != 0:
        return
    new_text = out_guard.read_text()
    expected = expected_guard(live['text'], n, old_profile, new, new_profile, live['main_sha'], main_new_sha)
    check('new guard equals the live guard with exactly the three expected lines replaced',
          new_text == expected)
    removed, added = diff_changes(out_diff.read_text())
    check('GUARD.diff removes exactly the three live lines',
          sorted(removed) == sorted(['PROFILE=' + old_profile, version_line(n), main_line(live['main_sha'])]),
          repr(removed))
    check('GUARD.diff adds exactly the three new lines',
          sorted(added) == sorted(['PROFILE=' + new_profile, version_line(new), main_line(main_new_sha)]),
          repr(added))
    check('new guard has the new profile once and not the old one',
          new_text.count('\nPROFILE=' + new_profile + '\n') == 1 and 'PROFILE=' + old_profile + '\n' not in new_text)
    check('new guard checks version %d only' % new,
          new_text.count('bundle_version" == %d ]]' % new) == 1 and
          new_text.count('bundle_version" == %d ]]' % n) == 0)
    check('new guard main constant is the new binary hash', ('== %s ]]' % main_new_sha) in new_text)
    check('new guard keeps the two dylib constants',
          ('== %s ]]' % sha_bytes(live['vk'])) in new_text and ('== %s ]]' % sha_bytes(live['xl'])) in new_text)
    bash = subprocess.run(['bash', '-n', str(out_guard)], capture_output=True, text=True)
    check('new guard passes bash -n', bash.returncode == 0, bash.stderr)
    r = run_tool('guard-check', out_guard, bundle_new, new)
    check('guard-check accepts the new guard against bundle %d' % new, r.returncode == 0, r.stderr.strip())
    r = run_tool('guard-check', out_guard, bundle_new, n)
    check('guard-check refuses version %d for the new guard' % n, r.returncode != 0)
    r = run_tool('guard-version', out_guard)
    check('guard-version reads %d from the new guard' % new, r.stdout.strip() == str(new), r.stderr.strip())
    r = run_tool('guard-profile', out_guard)
    check('guard-profile reads the new profile', r.stdout.strip() == new_profile, r.stderr.strip())

    payload = d / 'payload'
    shutil.copytree(str(bundle_new), str(payload / 'Navi48Metal.bundle'))
    shutil.copy(str(out_guard), str(payload / 'accelerated-reboot-trial.sh'))
    manifest = d / 'manifest.json'
    live_sha = sha(guard)
    r = run_tool('manifest', manifest, payload, new_profile, 'test-source', live_sha, str(n), old_profile)
    check('manifest written', r.returncode == 0, r.stderr)
    if r.returncode == 0:
        data = json.loads(manifest.read_text())
        check('manifest records live %d and candidate %d' % (n, new),
              data.get('live_bundle_version') == str(n) and data.get('candidate_bundle_version') == str(new))
        check('manifest records the live guard sha', data.get('live_guard_sha256') == live_sha)
        r = run_tool('manifest-get', manifest, 'profile')
        check('manifest-get returns the new profile', r.stdout.strip() == new_profile, r.stderr.strip())
        r = run_tool('check', manifest, '', payload)
        check('payload verifies against its manifest', r.returncode == 0, r.stderr)
        (payload / 'accelerated-reboot-trial.sh').write_text(new_text + '# tampered\n')
        r = run_tool('check', manifest, '', payload)
        check('tampered guard is refused by the manifest check', r.returncode != 0)


def run_live_refusals(work, live):
    print('== refusals with the live guard (each must fail and write nothing)')
    n, old_profile = live['ver'], live['profile']
    new = n + 1
    good_profile = 'stage%d-dualsrc-test-v1' % new
    d = work / 'refusals'
    d.mkdir()

    def refused(label, guard_path, bundle, out_name, reason, old_p=old_profile, new_p=good_profile,
                old_v=str(n), new_v=str(new)):
        out_guard, out_diff = d / (out_name + '.sh'), d / (out_name + '.diff')
        r = run_tool('edit-guard', guard_path, bundle, out_guard, out_diff, old_p, new_p, old_v, new_v)
        check(label, r.returncode != 0 and reason in r.stderr and not out_guard.exists() and not out_diff.exists(),
              'rc=%s err=%s' % (r.returncode, r.stderr.strip()))

    refused('real live guard + fake dylibs is refused (dylib constants differ)', LIVE_GUARD,
            make_bundle(d / 'fake-dylib', new, b'x', b'vk-fake', b'xl-fake'), 'r1',
            'differs from the live guard constant')
    refused('a changed libvulkan_radeon in the new bundle is refused', LIVE_GUARD,
            make_bundle(d / 'vk-changed', new, b'x', b'changed', live['xl']), 'r2',
            'libvulkan_radeon.dylib')
    xl_bundle = make_bundle(d / 'xl-changed', new, b'x', live['vk'], b'xl-new')
    r = run_tool('edit-guard', LIVE_GUARD, xl_bundle, d / 'xl.sh', d / 'xl.diff', old_profile, good_profile, str(n), str(new))
    xl_text = (d / 'xl.sh').read_text() if r.returncode == 0 else ''
    check('a changed libn48xlate is accepted and only its constant changes besides the three lines',
          r.returncode == 0 and hashlib.sha256(b'xl-new').hexdigest() in xl_text
          and hashlib.sha256(live['xl']).hexdigest() not in xl_text
          and hashlib.sha256(live['vk']).hexdigest() in xl_text,
          'rc=%s err=%s' % (r.returncode, r.stderr.strip()))
    bad = d / 'bad-version.sh'
    bad.write_text(live['text'].replace(version_line(n), version_line(n - 1), 1))
    refused('guard whose version line differs is refused', bad,
            make_bundle(d / 'ok-a', new, b'x', live['vk'], live['xl']), 'r3', 'exactly once')
    bad = d / 'bad-profile.sh'
    bad.write_text(live['text'].replace('\nPROFILE=' + old_profile + '\n',
                                        '\nPROFILE=%s\nPROFILE=%s\n' % (old_profile, old_profile), 1))
    refused('guard with a duplicated profile line is refused', bad,
            make_bundle(d / 'ok-b', new, b'x', live['vk'], live['xl']), 'r4', 'exactly once')
    refused('bundle with version N (%d) is refused as the new bundle' % n, LIVE_GUARD,
            make_bundle(d / 'v-old', n, b'x', live['vk'], live['xl']), 'r5', 'CFBundleVersion is not')
    refused('wrong N+1: bundle version %d with N+1=%d is refused' % (n + 2, new), LIVE_GUARD,
            make_bundle(d / 'v-wrong', n + 2, b'x', live['vk'], live['xl']), 'r6', 'CFBundleVersion is not')
    refused('wrong N+1: NEW_VERSION %d (not N+1) is refused even with a matching bundle' % (n + 2), LIVE_GUARD,
            make_bundle(d / 'v-wrong2', n + 2, b'x', live['vk'], live['xl']), 'r7', 'is not live',
            new_v=str(n + 2))
    fixture = d / 'same-main-guard.sh'
    fixture.write_text(with_constants(live['text'], sha_bytes(b'x'), sha_bytes(b'y'), sha_bytes(b'z')))
    refused('new main binary identical to the live guard constant is refused', fixture,
            make_bundle(d / 'same', new, b'x', b'y', b'z'), 'r8', 'same hash as the live guard')
    refused('profile that is not stage%d-<name> is refused' % new, LIVE_GUARD,
            make_bundle(d / 'ok-c', new, b'x', live['vk'], live['xl']), 'r9', 'is not stage',
            new_p='stage%d-x-v1' % n)
    refused('empty new profile is refused', LIVE_GUARD,
            make_bundle(d / 'ok-d', new, b'x', live['vk'], live['xl']), 'r10', 'is not stage', new_p='')


def run_synthetic(work, live):
    print('== synthetic case N=9->10 (two-digit boundary; guard derived from the live copy)')
    if live is None:
        print('SKIP needs the live guard text and dylibs')
        return
    d = work / 'synthetic'
    d.mkdir()
    text = live['text'].replace(version_line(live['ver']), version_line(9), 1)
    text = text.replace('PROFILE=' + live['profile'] + '\n', 'PROFILE=stage9-synthetic-v1\n', 1)
    guard = d / 'guard9.sh'
    guard.write_text(text)
    bundle = make_bundle(d / 'n10', 10, b'fake main 10', live['vk'], live['xl'])
    out_guard, out_diff = d / 'GUARD-10.sh', d / 'GUARD.diff'
    r = run_tool('edit-guard', guard, bundle, out_guard, out_diff, 'stage9-synthetic-v1',
                 'stage10-synthetic-v1', '9', '10')
    check('edit-guard accepts N=9->10 (synthetic guard)', r.returncode == 0, r.stdout + r.stderr)
    if r.returncode == 0:
        new_text = out_guard.read_text()
        check('N=9->10 guard checks version 10 only',
              version_line(10) in new_text and version_line(9) not in new_text)
        removed, added = diff_changes(out_diff.read_text())
        check('N=9->10 diff has exactly three removed and three added lines',
              len(removed) == 3 and len(added) == 3, repr(removed))
        r = run_tool('guard-check', out_guard, bundle, 10)
        check('N=9->10 guard-check accepts bundle 10', r.returncode == 0, r.stderr.strip())
    r = run_tool('edit-guard', guard, bundle, d / 'x.sh', d / 'x.diff', 'stage9-synthetic-v1',
                 'stage11-synthetic-v1', '9', '11')
    check('N=9->11 (skipping a version) is refused', r.returncode != 0 and 'is not live' in r.stderr, r.stderr.strip())


def run_stage_refusals(work, live):
    print('== stage.sh refusals (each must fail before anything is written)')
    n = live['ver']
    new = n + 1
    d = work / 'stage'
    d.mkdir()
    out_dir = MAC / ('trial-b%d' % new)
    before_mac = sorted(os.listdir(str(MAC)))
    before_out = snapshot(out_dir)
    good_profile = 'stage%d-dualsrc-test-v1' % new
    bundle_new = make_bundle(d / 'new', new, b'x', live['vk'], live['xl'])
    bundle_wrong = make_bundle(d / 'wrong', n + 2, b'x', live['vk'], live['xl'])
    bundle_old = make_bundle(d / 'old', n, b'x', live['vk'], live['xl'])

    def stage_refused(label, args, reason):
        r = run_stage(*args)
        check(label, r.returncode != 0 and reason in r.stderr, 'rc=%s err=%s' % (r.returncode, r.stderr.strip()))

    stage_refused('stage.sh with no arguments is refused (usage)', [], 'STOP: usage')
    stage_refused('stage.sh without the profile argument is refused (usage)', [bundle_new], 'STOP: usage')
    stage_refused('stage.sh with an empty profile argument is refused', [bundle_new, ''], 'is not stage')
    stage_refused('stage.sh with a profile of another version is refused',
                  [bundle_new, 'stage%d-x-v1' % n], 'is not stage')
    stage_refused('stage.sh with bundle %d (wrong N+1) is refused' % (n + 2),
                  [bundle_wrong, good_profile], "expected %d" % new)
    stage_refused('stage.sh with bundle %d (= N) is refused' % n,
                  [bundle_old, good_profile], "expected %d" % new)
    stage_refused('stage.sh with a missing bundle path is refused',
                  [d / 'missing' / 'Navi48Metal.bundle', good_profile], 'no such directory')

    after_mac = sorted(os.listdir(str(MAC)))
    check('stage.sh refusals created or removed nothing under the build dir', before_mac == after_mac)
    check('stage.sh refusals left trial-b%d untouched' % new, snapshot(out_dir) == before_out)


def main():
    if not TOOL.is_file() or not STAGE.is_file():
        print('FAIL missing: %s or %s' % (TOOL, STAGE))
        return 1
    work = Path(tempfile.mkdtemp(prefix='metal-trial-test.'))
    try:
        live = read_live()
        if live is None:
            print('SKIP live cases (live guard or bundle not readable or not in the expected form)')
        else:
            print('== live state: N=%d, profile %s' % (live['ver'], live['profile']))
            run_positive(work, live)
            run_live_refusals(work, live)
            run_stage_refusals(work, live)
        run_synthetic(work, live)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    print()
    if failures:
        print('FAILED: %d check(s)' % len(failures))
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
