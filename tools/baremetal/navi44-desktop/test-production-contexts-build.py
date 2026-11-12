#!/usr/bin/env python3
"""Check the candidate builder's provenance and source-preservation boundaries.

Uses temporary source/EFI fixtures. Does not build, install or access a GPU.
The actual baseline reproduction and candidate builds are separate checks.
"""
import importlib.util
import json
import plistlib
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'production_build', Path(__file__).with_name('build-production-contexts.py'))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class CandidateBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='navi44-candidate-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def efi(self):
        efi = self.root / 'EFI/OC'
        binary = efi / 'Kexts/Navi48Bringup-eight.kext/Contents/MacOS/Navi48Bringup'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'pinned baseline executable')
        info = binary.parent.parent / 'Info.plist'
        info.write_bytes(plistlib.dumps({'CFBundleVersion': '0.0.665'}))
        entry = {'Enabled': True, 'BundlePath': 'Navi48Bringup-eight.kext',
                 'ExecutablePath': 'Contents/MacOS/Navi48Bringup'}
        config = efi / 'config.plist'
        config.write_bytes(plistlib.dumps({'Kernel': {'Add': [entry]}}))
        return efi, binary, info, config, entry

    def test_active_baseline_is_hashed_and_versioned(self):
        efi, binary, info, config, _ = self.efi()
        self.assertEqual(build.active_kernel(efi, build.sha(binary)), {
            'bundle_path': 'Navi48Bringup-eight.kext',
            'kernel_sha256': build.sha(binary),
            'config_sha256': build.sha(config), 'version': '0.0.665'})
        with self.assertRaises(ValueError):
            build.active_kernel(efi, '0' * 64)
        info.write_bytes(plistlib.dumps({'CFBundleVersion': '0.0.664'}))
        with self.assertRaises(ValueError):
            build.active_kernel(efi, build.sha(binary))

    def test_duplicate_and_missing_enabled_entries_are_refused(self):
        efi, binary, _, config, entry = self.efi()
        for entries in ([], [entry, entry], [{**entry, 'Enabled': False}]):
            with self.subTest(entries=entries):
                config.write_bytes(plistlib.dumps({'Kernel': {'Add': entries}}))
                with self.assertRaises(ValueError):
                    build.active_kernel(efi, build.sha(binary))

    def test_path_escapes_are_refused(self):
        efi, binary, _, config, entry = self.efi()
        for field, path in [('BundlePath', '../../outside.kext'),
                            ('ExecutablePath', '../../../outside')]:
            with self.subTest(field=field):
                config.write_bytes(plistlib.dumps({'Kernel': {'Add': [{**entry, field: path}]}}))
                with self.assertRaises(ValueError):
                    build.active_kernel(efi, build.sha(binary))

    def test_output_must_be_new_and_inside_build_root(self):
        allowed = self.root / 'builds'
        allowed.mkdir()
        self.assertEqual(build.output_directory(allowed / 'new', allowed), (allowed / 'new').resolve())
        (allowed / 'escape').symlink_to(self.root, target_is_directory=True)
        for path in (allowed, self.root / 'outside', allowed / 'escape/new'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                build.output_directory(path, allowed)

    def test_overlay_preserves_initialization_firmware_and_version_consistency(self):
        baseline, source, candidate = (self.root / name for name in ('baseline', 'source', 'candidate'))
        baseline.mkdir()
        source.mkdir()
        for name in build.TREE_NAMES:
            (baseline / name).mkdir()
        protected = {'src/Navi48Bringup.cpp': b'working initialization',
                     'src/amd/fw_loader.cpp': b'working firmware protocol',
                     'firmware/gc_12_0_0_mec.bin': b'reference firmware',
                     'shaders/default.bin': b'reference shader',
                     'tools/embed-firmware.py': b'reference embedding tool'}
        for name, data in protected.items():
            p = baseline / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (baseline / 'Info.plist').write_text('<string>0.0.665</string>\n' * 2)
        (baseline / 'src/Navi48MetalNub.cpp').write_text('sizeof(N48MetalOps), 665u\n' * 2)
        for name in build.OVERLAY:
            p = source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('new context implementation\n')
            if 'production_' not in name:
                q = baseline / name
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text('old context implementation\n')
        (source / 'src/amd/native_s1c.h').write_text('kN1cKextBuild = 664;\n')
        build.copy_source(baseline, candidate)
        before = build.tree_files(baseline)
        changed = build.overlay_candidate(candidate, source, '0.0.667')
        self.assertEqual(set(changed), set(build.OVERLAY) | {'Info.plist', 'src/Navi48MetalNub.cpp'})
        for name, data in protected.items():
            self.assertEqual((candidate / name).read_bytes(), data)
        self.assertEqual((candidate / 'Info.plist').read_text().count('0.0.667'), 2)
        self.assertIn('kN1cKextBuild = 667;', (candidate / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((candidate / 'src/Navi48MetalNub.cpp').read_text().count('667u'), 2)
        self.assertEqual(build.tree_files(baseline), before)

    def test_admission_commit_files_are_overlaid(self):
        # every kernel source file changed by c440e35 (the application budget); tests/ is userspace and not in the kext
        admission = {'src/Navi48NativeClient.cpp', 'src/Navi48NativeClient.hpp', 'src/amd/native_g4_pure.h',
                     'src/amd/native_open_policy_pure.h', 'src/amd/native_s1c.cpp', 'src/amd/native_s1c.h'}
        self.assertLessEqual(admission, set(build.OVERLAY))
        self.assertEqual(len(build.OVERLAY), len(set(build.OVERLAY)))
        self.assertIn('test-kernel-app-admission.py', build.TESTS)

    def test_kill_switch_is_the_committed_hunk_only(self):
        block = ('\t// 0.0.667: recovery kill switch.\n\tchar safeBoot[4] = {};\n'
                 '\tif (PE_parse_boot_argn("-x", safeBoot, sizeof(safeBoot))) return nullptr;\n')
        anchor = build.KILL_SWITCH_ANCHOR
        committed = 'head\n' + anchor + block + '\tif (!super::probe(provider, score)) return nullptr;\n'
        path = self.root / 'Navi48Bringup.cpp'
        path.write_text('head\n' + anchor + '\tif (!super::probe(provider, score)) return nullptr;\n')
        self.assertEqual(build.kill_switch_block(committed), block)
        build.apply_kill_switch(path, committed)
        self.assertEqual(path.read_text(), committed)
        with self.assertRaises(ValueError):
            build.apply_kill_switch(path, committed)   # already applied: refused

    def test_release_version_is_limited_and_sets_its_build_number(self):
        self.assertEqual(build.release_build('0.0.666'), 666)
        self.assertEqual(build.release_build('0.0.667'), 667)
        self.assertEqual(build.release_build('0.0.668'), 668)
        self.assertEqual(build.release_build('0.0.669'), 669)   # refresh-60 (0.0.669 is a supported candidate since the refresh overlay)
        self.assertEqual(build.release_build('0.0.670'), 670)   # refresh-60b: the same overlay with the frame-total fix
        self.assertEqual(build.release_build('0.0.671'), 671)   # refresh-60b + the GTT fix (wired, non-contiguous GTT BOs): built on the 0.0.670 tree
        self.assertEqual(build.release_build('0.0.672'), 672)   # black band: the 0.0.671 tree plus the reviewed black-band patch
        self.assertEqual(build.release_build('0.0.673'), 673)   # display arbitration: the 0.0.672 tree plus the reviewed 0.0.673 patch
        self.assertEqual(build.release_build('0.0.674'), 674)   # two-stage fallback: the 0.0.673 tree plus the reviewed 0.0.674 patch
        self.assertEqual(build.release_build('0.0.675'), 675)   # clock gating + thermal policy: the 0.0.674 tree plus the reviewed 0.0.675 patch
        for version in ('0.0.665', '0.0.676', '0.0.667.1', '0.1.668'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                build.release_build(version)

    def test_blackband_overlay_refuses_another_version_and_an_unreviewed_patch(self):
        candidate = self.root / 'candidate-blackband'
        candidate.mkdir()
        patch = self.root / 'unreviewed.diff'
        patch.write_text('not the reviewed black-band patch\n')
        with self.assertRaises(ValueError):
            build.blackband_overlay(candidate, patch, '0.0.671')
        with self.assertRaises(ValueError):   # the pinned sha256 of PATCH-vs-671-deployed.diff does not match this file
            build.blackband_overlay(candidate, patch, '0.0.672')
        self.assertEqual(sorted(p.name for p in candidate.iterdir()), [])   # nothing written before the checks pass

    def test_disparb_overlay_refuses_another_version_and_an_unreviewed_patch(self):
        candidate = self.root / 'candidate-disparb'
        candidate.mkdir()
        patch = self.root / 'unreviewed-673.diff'
        patch.write_text('not the reviewed display-arbitration patch\n')
        with self.assertRaises(ValueError):
            build.disparb_overlay(candidate, patch, '0.0.672')
        with self.assertRaises(ValueError):   # the pinned sha256 of kernel-0.0.673-over-0.0.672.diff does not match this file
            build.disparb_overlay(candidate, patch, '0.0.673')
        self.assertEqual(sorted(p.name for p in candidate.iterdir()), [])   # nothing written before the checks pass

    def test_disparb_patch_is_the_pinned_file_and_touches_only_the_reviewed_files(self):
        patch = build.ROOT / 'research/builds/macos-20261112/kernel-673/PATCHES/kernel-0.0.673-over-0.0.672.diff'
        if not patch.exists():
            self.skipTest('the 0.0.673 patch is a local (git-ignored) research file')
        self.assertEqual(build.sha(patch), build.DISPARB_PATCH_SHA)
        touched = sorted(line.split()[-1][2:] for line in patch.read_text().splitlines() if line.startswith('diff -ruN '))
        self.assertEqual(touched, sorted(build.DISPARB_FILES))

    def test_fallback_overlay_refuses_another_version_and_an_unreviewed_patch(self):
        candidate = self.root / 'candidate-fallback'
        candidate.mkdir()
        patch = self.root / 'unreviewed-674.diff'
        patch.write_text('not the reviewed two-stage fallback patch\n')
        with self.assertRaises(ValueError):
            build.fallback_overlay(candidate, patch, '0.0.673')
        with self.assertRaises(ValueError):   # the pinned sha256 of kernel-0.0.674-over-0.0.673.diff does not match this file
            build.fallback_overlay(candidate, patch, '0.0.674')
        self.assertEqual(sorted(p.name for p in candidate.iterdir()), [])   # nothing written before the checks pass

    def test_fallback_patch_is_the_pinned_file_and_touches_only_the_reviewed_files(self):
        patch = build.ROOT / 'research/builds/macos-20261112/kernel-674/PATCHES/kernel-0.0.674-over-0.0.673.diff'
        if not patch.exists():
            self.skipTest('the 0.0.674 patch is a local (git-ignored) research file')
        self.assertEqual(build.sha(patch), build.FALLBACK_PATCH_SHA)
        touched = sorted(line.split()[-1][2:] for line in patch.read_text().splitlines() if line.startswith('diff -ruN '))
        self.assertEqual(touched, sorted(build.FALLBACK_FILES))

    def test_gating_overlay_refuses_another_version_and_an_unreviewed_patch(self):
        candidate = self.root / 'candidate-gating'
        candidate.mkdir()
        patch = self.root / 'unreviewed-675.diff'
        patch.write_text('not the reviewed clock-gating patch\n')
        with self.assertRaises(ValueError):
            build.gating_overlay(candidate, patch, '0.0.674')
        with self.assertRaises(ValueError):   # the pinned sha256 of kernel-0.0.675-over-0.0.674.diff does not match this file
            build.gating_overlay(candidate, patch, '0.0.675')
        self.assertEqual(sorted(p.name for p in candidate.iterdir()), [])   # nothing written before the checks pass

    def test_gating_patch_is_the_pinned_file_and_touches_only_the_reviewed_files(self):
        patch = build.ROOT / 'research/builds/macos-20261112/kernel-675/PATCHES/kernel-0.0.675-over-0.0.674.diff'
        if not patch.exists():
            self.skipTest('the 0.0.675 patch is a local (git-ignored) research file')
        self.assertEqual(build.sha(patch), build.GATING_PATCH_SHA)
        touched = sorted(line.split()[-1][2:] for line in patch.read_text().splitlines() if line.startswith('diff -ruN '))
        self.assertEqual(touched, sorted(build.GATING_FILES))

    def test_668_overlay_sets_its_version_and_build_number(self):
        baseline, source, candidate = (self.root / name for name in ('baseline668', 'source668', 'candidate668'))
        baseline.mkdir()
        source.mkdir()
        for name in build.TREE_NAMES:
            (baseline / name).mkdir()
        (baseline / 'Info.plist').write_text('<string>0.0.665</string>\n' * 2)
        (baseline / 'Makefile').write_text('all:\n')
        (baseline / 'src/Navi48MetalNub.cpp').write_text('sizeof(N48MetalOps), 665u\n' * 2)
        (baseline / 'src/amd').mkdir(parents=True)
        (baseline / 'src/amd/native_s1c.h').write_text('kN1cKextBuild = 664;\n')
        for name in build.OVERLAY:
            p = source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('0.0.668 placement implementation\n')
        (source / 'src/amd/native_s1c.h').write_text('kN1cKextBuild = 664;\n')
        build.copy_source(baseline, candidate)
        build.overlay_candidate(candidate, source, '0.0.668')
        self.assertEqual((candidate / 'Info.plist').read_text().count('<string>0.0.668</string>'), 2)
        self.assertIn('kN1cKextBuild = 668;', (candidate / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((candidate / 'src/Navi48MetalNub.cpp').read_text().count('668u'), 2)

    def test_uncommitted_overlay_is_refused_unless_recorded_explicitly(self):
        committed = {name: b'committed ' + name.encode() for name in build.OVERLAY}
        working = dict(committed)
        blobs = {name: 'b' * 40 for name in build.OVERLAY}
        self.assertEqual(build.classify_overlay(committed, dict(committed), blobs, False)['source'], 'committed')
        working['src/amd/native_s1c.cpp'] = b'reviewed but uncommitted'
        with self.assertRaises(ValueError):
            build.classify_overlay(committed, working, blobs, False)
        record = build.classify_overlay(committed, working, blobs, True)
        self.assertEqual(record['source'], 'working-tree')
        self.assertEqual(record['uncommitted'], ['src/amd/native_s1c.cpp'])
        self.assertEqual(record['sha256']['src/amd/native_s1c.cpp'],
                         build.hashlib.sha256(b'reviewed but uncommitted').hexdigest())
        self.assertEqual(record['blob_ids'], blobs)

    def test_668_active_kernel_is_the_installed_0_0_667_candidate(self):
        production = Path(build.__file__).resolve().parents[3] / 'research/builds/macos-20261031/production'
        payload_v3 = production / 'kernel-payload-v3/manifest.json'
        self.assertEqual(build.recorded_active_release(payload_v3, '0.0.668'), build.INSTALLED_667)
        manifest = json.loads(payload_v3.read_text())
        manifest['candidate_efi_files']['OC/config.plist'] = '0' * 64
        other = self.root / 'other.json'
        other.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            build.recorded_active_release(other, '0.0.668')
        # 0.0.666 and 0.0.667 keep the 665 baseline record
        manifest_665 = self.root / 'manifest665.json'
        manifest_665.write_text(json.dumps({'active_baseline': {'bundle_path': build.BASE_BUNDLE, 'kernel_sha256': build.BASE_SHA,
                                                             'config_sha256': build.BASE_CONFIG_SHA, 'version': '0.0.665'}}))
        self.assertEqual(build.recorded_active_release(manifest_665, '0.0.667')['version'], '0.0.665')

    def test_recorded_active_baseline_must_be_the_accelerated_665_kernel(self):
        manifest = self.root / 'manifest.json'
        good = {'bundle_path': build.BASE_BUNDLE, 'kernel_sha256': build.BASE_SHA,
                'config_sha256': build.BASE_CONFIG_SHA, 'version': '0.0.665'}
        manifest.write_text(json.dumps({'active_baseline': good}))
        self.assertEqual(build.recorded_active_baseline(manifest), good)
        manifest.write_text(json.dumps({'active_baseline': {**good, 'kernel_sha256': '0' * 64}}))
        with self.assertRaises(ValueError):
            build.recorded_active_baseline(manifest)

    def test_version_marker_mismatch_is_refused(self):
        path = self.root / 'version.h'
        path.write_text('an unexpected baseline')
        with self.assertRaises(ValueError):
            build.replace_exact(path, '664', '666', 1)
        self.assertEqual(path.read_text(), 'an unexpected baseline')


if __name__ == '__main__':
    unittest.main()
