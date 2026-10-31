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
    def test_dynamic_logical_page_accepts_any_current_hardware_binding(self):
        for vmid in (*range(8,16),m.UNASSIGNED_VMID):
            text='slot / VMID / session : 63 / %d / 129\nstate : OPEN, hello\n'%vmid
            value=m.parse_slot(95,text,64,True)
            self.assertEqual(value['slot'],63)
            self.assertEqual(value['vmid'],None if vmid==m.UNASSIGNED_VMID else vmid)
        for vmid in (0,7,16,71,m.UNASSIGNED_VMID+1):
            with self.subTest(vmid=vmid),self.assertRaises(ValueError):
                m.parse_slot(95,'slot / VMID / session : 63 / %d / 129\nstate : OPEN\n'%vmid,64,True)
    def test_dynamic_page_layout_keeps_global_and_fairness_separate(self):
        self.assertEqual(m.pages_for_profile(64),tuple(range(32,96)))
        for page in (4,5,31,96):
            with self.subTest(page=page),self.assertRaises(ValueError):
                m.parse_slot(page,'slot / VMID / session : 0 / 8 / 1\nstate : OPEN\n',64,True)
        with self.assertRaises(ValueError):
            m.parse_slot(95,'slot / VMID / session : 62 / 8 / 1\nstate : OPEN\n',64,True)
    def test_dynamic_global_counts_are_logical_counts(self):
        text='open / DEAD slots / HUNG: 60 / 4 / 0\nseq emitted / retired: 123 / 122\n'
        self.assertEqual(m.parse_global(text,64)['open'],60)
        with self.assertRaises(ValueError): m.parse_global(text,8)
        with self.assertRaises(ValueError): m.parse_global(text.replace('60 / 4','61 / 4'),64)
    def test_dynamic_vmids_can_be_reused_between_sequential_samples(self):
        counters={'open':64,'dead':0,'hung':False,'emitted':100,'retired':100}
        slots=[{'slot':i,'vmid':8+i%8,'session_id':i+1,'status':'open','poisoned':False} for i in range(64)]
        slots[63]['vmid']=None
        result=m.assess(counters,counters,slots,64,True)
        self.assertTrue(result['all_requested_pages_read'])
        self.assertTrue(result['counts_consistent_during_sampling'])
        self.assertEqual(result['active_slots_above_seven'],list(range(8,64)))
        self.assertEqual(result['unbound_active_contexts'],[63])
        self.assertIn('cannot prove simultaneous binding uniqueness',result['limitations'])
        slots[63]['session_id']=slots[0]['session_id']
        with self.assertRaises(ValueError):m.assess(counters,counters,slots,64,True)
    def test_incomplete_census_does_not_claim_consistent_counts(self):
        counters={'open':0,'dead':0,'hung':False,'emitted':1,'retired':1}
        result=m.assess(counters,counters,[],64,True)
        self.assertFalse(result['all_requested_pages_read'])
        self.assertFalse(result['counts_consistent_during_sampling'])
if __name__=='__main__': unittest.main()
