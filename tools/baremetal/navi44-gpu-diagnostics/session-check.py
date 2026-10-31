#!/usr/bin/env python3
"""Read-only diagnostic for native GPU sessions. Does not open a GPU session.

The admin sessstat verb samples kernel counters and updates its diagnostic fault
baseline. It does not submit GPU work or change display/driver settings.
"""
import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

TOOL = Path('/Library/Application Support/Navi44/accelerated-trial/navi48test')
UNASSIGNED_VMID = (1 << 32) - 1

def pages_for_profile(capacity):
    if capacity == 4: return (0,1,2,3)
    if capacity == 8: return (0,1,2,3,6,7,8,9)
    if capacity == 64: return tuple(range(32,96))
    raise ValueError('Unsupported context profile')

def capture(argv):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=20, check=False)
    if result.returncode: raise ValueError('Command failed (%d): %s' % (result.returncode, result.stderr.strip()[:300]))
    return result.stdout

def parse_global(text, capacity=8):
    def fields(pattern):
        match = re.search(pattern, text, re.M)
        if not match: raise ValueError('Missing or malformed global session statistics')
        return tuple(map(int, match.groups()))
    opened, dead, hung = fields(r'^\s*open / DEAD slots / HUNG:\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$')
    emitted, retired = fields(r'^\s*seq emitted / retired\s*:\s*(\d+)\s*/\s*(\d+)\s*$')
    if opened + dead > capacity or hung > 1 or retired > emitted:
        raise ValueError('Invalid global counters')
    match=re.search(r'^\s*non-WS visible VRAM\s*:\s*(\d+) KiB held of a (\d+) MiB cap',text,re.M)
    visible = {'held_kib':int(match.group(1)), 'cap_mib':int(match.group(2))} if match else None
    return {'open':opened, 'dead':dead, 'hung':bool(hung), 'emitted':emitted, 'retired':retired,
            'non_ws_visible_vram':visible}

def parse_slot(page, text, capacity=8, dynamic=False):
    match = re.search(r'^\s*slot / VMID / session\s*:\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$',text,re.M)
    state = re.search(r'^\s*state\s*:\s*(.+)$',text,re.M)
    if not match or not state: raise ValueError('Missing or malformed slot statistics for page %d' % page)
    slot, vmid, sid = map(int,match.groups())
    if page not in pages_for_profile(capacity):
        raise ValueError('Wrong diagnostic page for context profile')
    expected = page - 32 if capacity == 64 else page if page < 4 else page - 2
    valid_vmid = (vmid == UNASSIGNED_VMID or 8 <= vmid <= 15) if dynamic else vmid == slot + 8
    if slot != expected or slot >= capacity or not valid_vmid:
        raise ValueError('Wrong slot or VMID for page %d' % page)
    label = state.group(1)
    if label.startswith('OPEN'): status='open'
    elif label.startswith('free'): status='free'
    elif label.startswith('DEAD'): status='dead'
    else: raise ValueError('Unknown slot state on page %d' % page)
    if status == 'open' and sid == 0: raise ValueError('Open session has no identity')
    return {'slot':slot,'vmid':None if vmid == UNASSIGNED_VMID else vmid,
            'session_id':sid,'status':status,'windowserver':'WindowServer' in label,'poisoned':'POISONED' in label}

def assess(before, after, slots, capacity=8, dynamic=False):
    active=[x for x in slots if x['status']=='open']
    ids=[x['session_id'] for x in active]
    vmids=[x['vmid'] for x in active]
    indices=[x['slot'] for x in slots]
    if len(indices)!=len(set(indices)) or len(ids)!=len(set(ids)):
        raise ValueError('Repeated logical slot or active identity')
    if not dynamic and len(vmids)!=len(set(vmids)):
        raise ValueError('Repeated permanently assigned VMID')
    complete=set(indices)==set(range(capacity))
    return {'all_requested_pages_read':complete,
            'logical_context_capacity':capacity, 'dynamic_vmids':dynamic,
            'all_eight_pages_read':complete if capacity==8 else None,
            'active_slots_4_to_7':[x['slot'] for x in active if 4<=x['slot']<=7],
            'active_slots_above_seven':[x['slot'] for x in active if x['slot']>=8],
            'unbound_active_contexts':[x['slot'] for x in active if x['vmid'] is None],
            'counter_progress':after['retired']>before['retired'], 'hung':before['hung'] or after['hung'],
            'poisoned_slots':[x['slot'] for x in active if x['poisoned']],
            'counts_consistent_during_sampling':complete and len(active)==before['open']==after['open'],
            'limitations':'Counts and VMID bindings are sampled sequentially and may race. A VMID may legitimately change owner between pages; this census cannot prove simultaneous binding uniqueness or GPU isolation. Progress does not prove rendering or video decode.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--interval',type=float,default=2.0)
    p.add_argument('--slots',type=int,choices=(4,8,64),default=8,
                   help='4/8: fixed-VMID profiles; 64: logical contexts with dynamic VMIDs (pages 32..95)')
    args=p.parse_args()
    if os.geteuid()!=0: p.error('Requires root to query the admin diagnostics')
    if not 0.1<=args.interval<=10: p.error('interval must be between 0.1 and 10 seconds')
    def query(page): return capture([str(TOOL),'accel','sessstat',str(page)])
    pages=pages_for_profile(args.slots);dynamic=args.slots==64
    before=parse_global(query(4),args.slots)
    slots=[parse_slot(page,query(page),args.slots,dynamic) for page in pages]
    time.sleep(args.interval);after=parse_global(query(4),args.slots)
    print(json.dumps({'before':before,'after':after,'slots':slots,
                      'assessment':assess(before,after,slots,args.slots,dynamic)},indent=2))

if __name__=='__main__': main()
