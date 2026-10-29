#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('probe',Path(__file__).with_name('session-check.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Parsing(unittest.TestCase):
    def test_visible_memory_is_captured_when_reported(self):
        x=m.parse_global('open / DEAD slots / HUNG: 4 / 0 / 0\nseq emitted / retired: 8 / 8\n'
                         '  non-WS visible VRAM : 1080 KiB held of a 64 MiB cap (boot-arg)\n')
        self.assertEqual(x['non_ws_visible_vram'],{'held_kib':1080,'cap_mib':64})
    def test_extra_slot_page_is_not_global(self):
        x=m.parse_slot(6,'  slot / VMID / session   : 4 / 12 / 33\n  state                   : OPEN, hello\n')
        self.assertEqual((x['slot'],x['vmid'],x['status']),(4,12,'open'))
    def test_wrong_vmid_refused(self):
        with self.assertRaises(ValueError): m.parse_slot(6,'  slot / VMID / session : 4 / 8 / 33\n  state : OPEN\n')
    def test_global_bad_counters_refused(self):
        with self.assertRaises(ValueError): m.parse_global('open / DEAD slots / HUNG: 1 / 0 / 0\nseq emitted / retired: 3 / 4\n')
    def test_does_not_claim_activity_from_zero_delta(self):
        x={'open':0,'dead':0,'hung':False,'emitted':1,'retired':1}
        slots=[{'slot':i,'vmid':8+i,'session_id':0,'status':'free','poisoned':False} for i in range(8)]
        self.assertFalse(m.assess(x,x,slots)['counter_progress'])
    def test_duplicate_sessions_refused(self):
        x={'open':2,'dead':0,'hung':False,'emitted':1,'retired':1}
        slots=[{'slot':0,'vmid':8,'session_id':2,'status':'open','poisoned':False},{'slot':1,'vmid':9,'session_id':2,'status':'open','poisoned':False}]
        with self.assertRaises(ValueError): m.assess(x,x,slots)
if __name__=='__main__': unittest.main()
