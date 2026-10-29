#!/usr/bin/env python3
"""Host-only fault tests: no kernel client, admission changes or GPU commands."""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('seed', Path(__file__).with_name('seed-gpu-apps.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.old = m.run
        self.keys = {m.comm_key('existing')}
        self.original = set(self.keys)
        self.calls = []
        self.fail = None
        self.failed = False
        self.drop = False
        self.bad_restore = False
        self.bad_list = False
        m.run = self.run_fake

    def tearDown(self):
        m.run = self.old

    def run_fake(self, tool, op, arg):
        self.calls.append((op, arg))
        if op == 'list':
            if self.bad_list:
                return 'code : 1 (OFF)\n'
            rows = sorted(self.keys) + [0] * 36
            page = int(arg)
            return 'code : 0 (ok)\n' + ''.join(f' slot {page*9+i} : {hex(x) if x else "0"}\n' for i, x in enumerate(rows[page*9:page*9+9]))
        key = m.comm_key(arg)
        if op == 'add':
            if not self.drop:
                self.keys.add(key)
            if self.fail == arg and not self.failed:
                self.failed = True
                raise RuntimeError('injected partial add failure')
        elif op == 'remove':
            if self.bad_restore:
                raise RuntimeError('injected remove failure')
            self.keys.discard(key)
        return 'code : 0 (ok)\n'

    def seed(self, names):
        with contextlib.redirect_stdout(io.StringIO()):
            m.seed(Path('/unused/fake-tool'), names)

    def test_seed_and_idempotence(self):
        self.seed(['existing', 'stable', 'Safari'])
        expected = self.original | {m.comm_key('stable'), m.comm_key('Safari')}
        self.assertEqual(self.keys, expected)
        self.calls.clear()
        self.seed(['stable', 'Safari'])
        self.assertTrue(all(op == 'list' for op, _ in self.calls))

    def test_every_partial_failure_restores_existing(self):
        names = ['stable', 'Safari', 'mtlprobe']
        for name in names:
            with self.subTest(name=name):
                self.keys = set(self.original)
                self.fail, self.failed = name, False
                with self.assertRaisesRegex(RuntimeError, 'original list restored'):
                    self.seed(names)
                self.assertEqual(self.keys, self.original)

    def test_missing_add_detected(self):
        self.drop = True
        with self.assertRaisesRegex(RuntimeError, 'readback mismatch.*original list restored'):
            self.seed(['stable'])
        self.assertEqual(self.keys, self.original)

    def test_rollback_failure_reported(self):
        self.fail, self.bad_restore = 'Safari', True
        with self.assertRaisesRegex(RuntimeError, 'ROLLBACK FAILED'):
            self.seed(['stable', 'Safari'])
        self.assertIn(m.comm_key('existing'), self.keys)

    def test_capacity_refuses_before_add(self):
        self.keys = set(range(1, 33))
        with self.assertRaisesRegex(RuntimeError, 'capacity'):
            self.seed(['stable'])
        self.assertTrue(all(op == 'list' for op, _ in self.calls))

    def test_off_refuses_before_add(self):
        self.bad_list = True
        with self.assertRaisesRegex(RuntimeError, 'not ready'):
            self.seed(['stable'])
        self.assertTrue(all(op == 'list' for op, _ in self.calls))

    def test_name_truncation(self):
        self.assertEqual(m.comm_key('Brave Browser Helper (GPU)'), m.comm_key('Brave Browser Helper'))
        self.assertNotEqual(m.comm_key('Safari'), m.comm_key('stable'))

    def test_actual_manifest(self):
        names = m.load_names(Path(__file__).with_name('app-allowlist.json'))
        self.assertEqual(len(names), 25)
        self.assertTrue({"stable", "Brave Browser Helper (GPU)", "ControlCenter"}.issubset(names))
        self.assertTrue({"VTDecoderXPCService", "WallpaperSequoiaExtension", "mediaanalysisd", "Brave Browser"}.isdisjoint(names))
        self.seed(names)
        self.assertEqual(len(self.keys), 26)

    def test_duplicate_truncation_rejected(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'names.json'
            path.write_text(json.dumps({'schema': 1, 'names': ['Brave Browser Helper', 'Brave Browser Helper (GPU)']}))
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                m.load_names(path)


if __name__ == '__main__':
    unittest.main()
