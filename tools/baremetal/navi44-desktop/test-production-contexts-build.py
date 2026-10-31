#!/usr/bin/env python3
"""Check the candidate builder's provenance and source-preservation boundaries.

Uses temporary source/EFI fixtures. Does not build, install or access a GPU.
The actual baseline reproduction and candidate builds are separate checks.
"""
import importlib.util
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
        changed = build.overlay_candidate(candidate, source)
        self.assertEqual(set(changed), set(build.OVERLAY) | {'Info.plist', 'src/Navi48MetalNub.cpp'})
        for name, data in protected.items():
            self.assertEqual((candidate / name).read_bytes(), data)
        self.assertEqual((candidate / 'Info.plist').read_text().count('0.0.666'), 2)
        self.assertIn('kN1cKextBuild = 666;', (candidate / 'src/amd/native_s1c.h').read_text())
        self.assertEqual((candidate / 'src/Navi48MetalNub.cpp').read_text().count('666u'), 2)
        self.assertEqual(build.tree_files(baseline), before)

    def test_version_marker_mismatch_is_refused(self):
        path = self.root / 'version.h'
        path.write_text('an unexpected baseline')
        with self.assertRaises(ValueError):
            build.replace_exact(path, '664', '666', 1)
        self.assertEqual(path.read_text(), 'an unexpected baseline')


if __name__ == '__main__':
    unittest.main()
