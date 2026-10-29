#!/usr/bin/env python3
"""Exercise guard-state preservation; no live installation or privileged access."""
import contextlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('eight',Path(__file__).with_name('install-eight-combined.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BOOT='11111111-1111-1111-1111-111111111111'
STABLE={'schema':1,'phase':'stable','boot':BOOT,'profile':'existing'}

class GuardTests(unittest.TestCase):
    def test_accepts_only_current_stable_state(self):
        self.assertEqual(m.validate_stable(STABLE,BOOT),STABLE)
        for value,boot in [(None,BOOT),({**STABLE,'phase':'pending'},BOOT),({**STABLE,'phase':'failed'},BOOT),
                           (STABLE,'22222222-2222-2222-2222-222222222222')]:
            with self.assertRaises(ValueError): m.validate_stable(value,boot)

    def test_preflight_takes_guard_lock_without_mutation(self):
        calls=[]
        @contextlib.contextmanager
        def lock(path): calls.append(('lock',path));yield;calls.append(('unlock',path))
        def check(path,live): calls.append(('check',live));return {'installed':False}
        with patch.object(m.os,'geteuid',return_value=0), patch.object(m.state_api,'transaction',lock), \
             patch.object(m.state_api,'read',return_value=STABLE), patch.object(m,'current_boot',return_value=BOOT), \
             patch.object(m.checker,'check',side_effect=check):
            self.assertEqual(m.install(Path('/tmp/no-mutation'),False),{'installed':False})
        self.assertEqual([x[0] for x in calls],['lock','check','unlock'])

    def test_preflight_refuses_pending_before_check(self):
        with patch.object(m.os,'geteuid',return_value=0), patch.object(m.state_api,'transaction',return_value=contextlib.nullcontext()), \
             patch.object(m.state_api,'read',return_value={**STABLE,'phase':'pending'}), patch.object(m,'current_boot',return_value=BOOT), \
             patch.object(m.checker,'check') as check:
            with self.assertRaises(ValueError): m.install(Path('/tmp/no-mutation'),False)
            check.assert_not_called()

if __name__=='__main__': unittest.main()
