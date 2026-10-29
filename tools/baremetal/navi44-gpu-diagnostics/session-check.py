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

def capture(argv):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=20, check=False)
    if result.returncode: raise ValueError('Command failed (%d): %s' % (result.returncode, result.stderr.strip()[:300]))
    return result.stdout

def parse_global(text):
    def fields(pattern):
        match = re.search(pattern, text, re.M)
        if not match: raise ValueError('Missing or malformed global session statistics')
        return tuple(map(int, match.groups()))
    opened, dead, hung = fields(r'^\s*open / DEAD slots / HUNG:\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$')
    emitted, retired = fields(r'^\s*seq emitted / retired\s*:\s*(\d+)\s*/\s*(\d+)\s*$')
    if opened > 8 or dead > 8 or hung > 1 or retired > emitted:
        raise ValueError('Invalid global counters')
    return {'open':opened, 'dead':dead, 'hung':bool(hung), 'emitted':emitted, 'retired':retired}

def parse_slot(page, text):
    match = re.search(r'^\s*slot / VMID / session\s*:\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$',text,re.M)
    state = re.search(r'^\s*state\s*:\s*(.+)$',text,re.M)
    if not match or not state: raise ValueError('Missing or malformed slot statistics for page %d' % page)
    slot, vmid, sid = map(int,match.groups()); expected = page if page < 4 else page - 2
    if slot != expected or vmid != slot + 8 or slot > 7: raise ValueError('Wrong slot or VMID for page %d' % page)
    label = state.group(1)
    if label.startswith('OPEN'): status='open'
    elif label.startswith('free'): status='free'
    elif label.startswith('DEAD'): status='dead'
    else: raise ValueError('Unknown slot state on page %d' % page)
    if status == 'open' and sid == 0: raise ValueError('Open session has no identity')
    return {'slot':slot,'vmid':vmid,'session_id':sid,'status':status,'windowserver':'WindowServer' in label,'poisoned':'POISONED' in label}

def assess(before, after, slots):
    active=[x for x in slots if x['status']=='open']
    ids=[x['session_id'] for x in active]
    vmids=[x['vmid'] for x in active]
    if len(ids)!=len(set(ids)) or len(vmids)!=len(set(vmids)): raise ValueError('Repeated active identity or VMID')
    return {'all_eight_pages_read':len(slots)==8, 'active_slots_4_to_7':[x['slot'] for x in active if x['slot']>=4],
            'counter_progress':after['retired']>before['retired'], 'hung':before['hung'] or after['hung'],
            'poisoned_slots':[x['slot'] for x in active if x['poisoned']],
            'counts_consistent_during_sampling':len(active)==before['open']==after['open'],
            'limitations':'Counts are sampled sequentially and may race; progress does not prove rendering or video decode.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--interval',type=float,default=2.0)
    p.add_argument('--slots',type=int,choices=(4,8),default=8,
                   help='Use 4 for the currently installed four-session driver, 8 for the experimental profile')
    args=p.parse_args()
    if os.geteuid()!=0: p.error('Requires root to query the admin diagnostics')
    if not 0.1<=args.interval<=10: p.error('interval must be between 0.1 and 10 seconds')
    def query(page): return capture([str(TOOL),'accel','sessstat',str(page)])
    pages=(0,1,2,3) if args.slots==4 else (0,1,2,3,6,7,8,9)
    before=parse_global(query(4));slots=[parse_slot(page,query(page)) for page in pages]
    time.sleep(args.interval);after=parse_global(query(4))
    print(json.dumps({'before':before,'after':after,'slots':slots,'assessment':assess(before,after,slots)},indent=2))

if __name__=='__main__': main()
