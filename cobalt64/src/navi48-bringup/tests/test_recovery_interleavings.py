#!/usr/bin/env python3
"""Model the lock/identity protocol; does not execute kernel or GPU code."""
import itertools
import unittest

EVENTS = ('claim', 'close', 'open_lock', 'open_check', 'open_commit',
          'snapshot', 'apply', 'release')


def simulate(events, guarded):
    state = {'recovering':False, 'client_locked':False, 'open':True,
             'identity':1, 'allowed':False, 'selected':False, 'wrong':False}
    for event in events:
        if event == 'claim': state['recovering'] = True
        elif event == 'close':
            if state['client_locked']: return None
            state['open'] = False
        elif event == 'open_lock':
            if state['client_locked']: return None
            state['client_locked'] = True
        elif event == 'open_check':
            state['allowed'] = not guarded or not state['recovering']
        elif event == 'open_commit':
            if state['allowed']:
                state['identity'] = 2
                state['open'] = True
            state['client_locked'] = False
        elif event == 'snapshot':
            if guarded and state['client_locked']: return None
            state['selected'] = state['open'] and state['identity'] == 1
        elif event == 'apply':
            if state['selected'] and state['identity'] != 1: state['wrong'] = True
        elif event == 'release': state['recovering'] = False
    return state


class RecoveryInterleavings(unittest.TestCase):
    def test_slot_identity_is_not_reused_while_selected(self):
        explored = 0
        unsafe_without_guard = 0
        for seq in itertools.permutations(EVENTS):
            at = {event:i for i,event in enumerate(seq)}
            if not (at['claim'] < at['snapshot'] < at['apply'] < at['release'] and
                    at['close'] < at['open_lock'] < at['open_check'] < at['open_commit']):
                continue
            original = simulate(seq, False)
            guarded = simulate(seq, True)
            if original and original['wrong']: unsafe_without_guard += 1
            if guarded:
                explored += 1
                self.assertFalse(guarded['wrong'], str(seq))
        self.assertGreater(explored, 0)
        self.assertGreater(unsafe_without_guard, 0)
        print('Explored', explored, 'valid guarded interleavings;', unsafe_without_guard,
              'unguarded interleavings select a reused slot')


if __name__ == '__main__': unittest.main()
