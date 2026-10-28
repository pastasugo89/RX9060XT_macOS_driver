#!/usr/bin/env python3
"""Host-only lifecycle/ownership/fault tests for the persistent GPU attempt latch."""
import concurrent.futures
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('state', Path(__file__).with_name('boot-state.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
A, B = '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222'


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_first_boot_pending(self):
        m.begin(self.path, 'profile', A)
        self.assertEqual(m.read(self.path)['phase'], 'pending')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_pending_blocks_retries_and_new_profile(self):
        m.begin(self.path, 'profile', A)
        for profile, boot in [('profile', A), ('profile', B), ('new-profile', B)]:
            with self.subTest(profile=profile, boot=boot), self.assertRaises(m.Blocked):
                m.begin(self.path, profile, boot)
        self.assertEqual(m.read(self.path)['boot'], A)

    def test_failure_blocks_next_boot(self):
        m.begin(self.path, 'profile', A)
        m.finish(self.path, 'profile', A, 'failed', 'windowserver-changed')
        with self.assertRaises(m.Blocked):
            m.begin(self.path, 'profile', B)
        self.assertEqual(m.read(self.path)['observation'], 'windowserver-changed')

    def test_stable_allows_new_boot_once(self):
        m.begin(self.path, 'profile', A)
        m.finish(self.path, 'profile', A, 'stable', 'desktop-120s')
        with self.assertRaises(m.Blocked):
            m.begin(self.path, 'profile', A)
        m.begin(self.path, 'profile', B)
        self.assertEqual(m.read(self.path)['boot'], B)

    def test_orderly_stop_is_not_claimed_stable(self):
        m.begin(self.path, 'profile', A)
        m.finish(self.path, 'profile', A, 'stopped', 'activation-exit-143')
        self.assertEqual(m.read(self.path)['phase'], 'stopped')
        with self.assertRaises(m.Blocked):
            m.begin(self.path, 'profile', A)
        m.begin(self.path, 'profile', B)
        self.assertEqual(m.read(self.path)['phase'], 'pending')

    def test_stop_cannot_clear_previous_failure(self):
        m.begin(self.path, 'profile', A)
        m.finish(self.path, 'profile', A, 'failed', 'crash')
        with self.assertRaises(m.Blocked):
            m.finish(self.path, 'profile', A, 'stopped', 'fake-stop')
        self.assertEqual(m.read(self.path)['phase'], 'failed')

    def test_loginwindow_observation_stays_distinct(self):
        m.begin(self.path, 'profile', A)
        m.finish(self.path, 'profile', A, 'stable', 'login-window-stable-300s')
        self.assertNotIn('desktop', m.read(self.path)['observation'])

    def test_stale_or_wrong_profile_cannot_finish(self):
        m.begin(self.path, 'profile', A)
        for profile, boot in [('other', A), ('profile', B)]:
            with self.subTest(profile=profile, boot=boot), self.assertRaises(m.Blocked):
                m.finish(self.path, profile, boot, 'stable', 'desktop')
        self.assertEqual(m.read(self.path)['phase'], 'pending')

    def test_missing_attempt_cannot_finish(self):
        with self.assertRaises(m.Blocked):
            m.finish(self.path, 'profile', A, 'stable', 'desktop')
        self.assertFalse(self.path.exists())

    def test_malformed_state_refused(self):
        self.path.write_text('{bad')
        self.path.chmod(0o600)
        with self.assertRaises(ValueError):
            m.begin(self.path, 'profile', A)
        self.assertEqual(self.path.read_text(), '{bad')

    def test_bad_phase_refused(self):
        m.begin(self.path, 'profile', A)
        with self.assertRaises(ValueError):
            m.finish(self.path, 'profile', A, 'success-ish', 'desktop')
        self.assertEqual(m.read(self.path)['phase'], 'pending')

    def test_symlink_not_followed(self):
        target = Path(self.temp.name) / 'target'
        target.write_text('unchanged')
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            m.begin(self.path, 'profile', A)
        self.assertEqual(target.read_text(), 'unchanged')

    def test_world_writable_parent_refused(self):
        self.path.parent.chmod(0o777)
        with self.assertRaises(ValueError):
            m.begin(self.path, 'profile', A)
        self.assertFalse(self.path.exists())
        self.path.parent.chmod(0o700)

    def test_insecure_state_mode_refused(self):
        m.begin(self.path, 'profile', A)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            m.finish(self.path, 'profile', A, 'stable', 'desktop')

    def test_symlink_lock_refused(self):
        target = Path(self.temp.name) / 'target'
        target.write_text('unchanged')
        self.path.with_name('state.json.lock').symlink_to(target)
        with self.assertRaises(OSError):
            m.begin(self.path, 'profile', A)
        self.assertFalse(self.path.exists())
        self.assertEqual(target.read_text(), 'unchanged')

    def test_concurrent_begin_has_one_winner(self):
        barrier = threading.Barrier(2)
        def attempt(_):
            barrier.wait()
            try:
                m.begin(self.path, 'profile', A)
                return True
            except m.Blocked:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(m.read(self.path)['phase'], 'pending')

    def test_replace_failure_keeps_previous_state(self):
        m.begin(self.path, 'profile', A)
        before = self.path.read_bytes()
        original = m.os.replace
        def fail(*args):
            raise OSError('injected write failure')
        m.os.replace = fail
        try:
            with self.assertRaisesRegex(OSError, 'injected'):
                m.finish(self.path, 'profile', A, 'stable', 'desktop')
        finally:
            m.os.replace = original
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('.boot-state-*')), [])


if __name__ == '__main__':
    unittest.main()
