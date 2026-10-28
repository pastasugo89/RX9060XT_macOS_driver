#!/usr/bin/env python3
"""Exercise boot recovery with fake GPU tools; root cases touch only temp flags."""
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name('accelerated-reboot-trial.sh').read_text()
FLAGS = SOURCE[SOURCE.index('root_flag_valid() {'):SOURCE.index('verify_fbname() {')]
ROLLBACK = SOURCE[SOURCE.index('rollback() {'):SOURCE.index('\ntrap rollback EXIT')]


@unittest.skipIf(os.geteuid() == 0, 'Run rollback mocks without root')
class RollbackTests(unittest.TestCase):
    def simulate(self, logged_in, ordered=False, state_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            trace = base / 'trace'
            helper = base / 'boot-state.py'
            helper.write_text('import os,sys\nwith open(os.environ["TRACE"],"a") as f:f.write("STATE:"+sys.argv[1]+"\\n")\nsys.exit(' + str(int(state_failure)) + ')\n')
            nt = base / 'fake-nt'
            nt.write_text('#!/bin/bash\nprintf "NT:%s\\n" "$*" >> "$TRACE"\n')
            nt.chmod(0o700)
            # This test never runs the top-level script. Every GPU/signal command
            # in the extracted cleanup function is replaced; WindowServer is uid88.
            script = '\n'.join([
                'set -Eeuo pipefail',
                'APP=' + shlex.quote(directory), 'NT=' + shlex.quote(str(nt)),
                'STATE=' + shlex.quote(str(base / 'state')), 'PROFILE=test',
                'FLAG=' + shlex.quote(str(base / 'flag')), 'KILL=' + shlex.quote(str(base / 'kill')),
                'state_started=1; active=1; renamed=1; headless=1; guard_checked=1',
                'ordered_stop=' + str(int(ordered)),
                'who() { ' + ('echo user;' if logged_in else ':;') + ' }',
                'killall() { echo KILLWS >> "$TRACE"; }',
                'make_root_flag() { echo FLAG >> "$TRACE"; }',
                ROLLBACK,
                'trap rollback EXIT; exit ' + ('143' if ordered else '1')])
            result = subprocess.run(['bash', '-c', script], env=dict(os.environ, TRACE=str(trace)), capture_output=True, text=True)
            return result, trace.read_text().splitlines()

    def test_active_user_is_not_logged_out(self):
        result, events = self.simulate(True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('KILLWS', events)
        self.assertIn('STATE:failed', events)
        self.assertIn('NT:accel pipearm 0', events)
        self.assertIn('NT:accel fbname 0', events)
        self.assertIn('FAILSAFE_DEFERRED_USER_SESSION_PRESENT', result.stdout)

    def test_loginwindow_can_return_to_software(self):
        result, events = self.simulate(False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('KILLWS', events)
        self.assertLess(events.index('NT:accel pipearm 0'), events.index('KILLWS'))
        self.assertIn('STATE:failed', events)

    def test_orderly_stop_is_not_a_crash(self):
        result, events = self.simulate(True, ordered=True)
        self.assertEqual(result.returncode, 143)
        self.assertIn('STATE:stopped', events)
        self.assertNotIn('STATE:failed', events)
        self.assertNotIn('KILLWS', events)

    def test_state_write_failure_still_disarms(self):
        result, events = self.simulate(True, state_failure=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('BOOT_STATE_FAILURE_RECORD_FAILED', result.stdout)
        self.assertIn('NT:accel pipearm 0', events)
        self.assertNotIn('KILLWS', events)


@unittest.skipUnless(os.geteuid() == 0, 'Root-only temp-file ownership checks')
class RootFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, path):
        return subprocess.run(['bash', '-c', FLAGS + '\nmake_root_flag ' + shlex.quote(str(path))], capture_output=True, text=True)

    def test_missing_flag_is_created_once(self):
        flag = self.base / 'flag'
        self.assertEqual(self.invoke(flag).returncode, 0)
        inode = flag.stat().st_ino
        self.assertEqual(flag.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.invoke(flag).returncode, 0)
        self.assertEqual(flag.stat().st_ino, inode)

    def test_symlink_target_is_not_changed(self):
        target = self.base / 'private'
        target.write_text('private')
        target.chmod(0o600)
        flag = self.base / 'flag'
        flag.symlink_to(target)
        self.assertNotEqual(self.invoke(flag).returncode, 0)
        self.assertEqual(target.read_text(), 'private')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_user_owned_flag_is_not_changed(self):
        flag = self.base / 'flag'
        flag.touch(mode=0o644)
        os.chown(flag, 501, 20)
        self.assertNotEqual(self.invoke(flag).returncode, 0)
        self.assertEqual(flag.stat().st_uid, 501)

    def test_nonempty_or_linked_flag_is_refused(self):
        flag = self.base / 'flag'
        flag.write_text('not-a-flag')
        flag.chmod(0o644)
        self.assertNotEqual(self.invoke(flag).returncode, 0)
        self.assertEqual(flag.read_text(), 'not-a-flag')
        flag.write_text('')
        os.link(flag, self.base / 'other')
        self.assertNotEqual(self.invoke(flag).returncode, 0)
        self.assertEqual(flag.stat().st_nlink, 2)


if __name__ == '__main__':
    unittest.main()
