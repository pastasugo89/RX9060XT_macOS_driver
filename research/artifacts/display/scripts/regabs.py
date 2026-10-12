import re, sys
# usage: regabs.py offset.h name1 name2 ...  (exact names without 'reg' prefix)
base = [0x12, 0xc0, 0x34c0, 0x9000, 0x2403c00]   # DMU 4.1.0 bases from ip_discovery_table.bin (VERIFIED)
txt = open(sys.argv[1]).read()
off = dict(re.findall(r'#define reg(\w+)\s+(0x[0-9a-fA-F]+)\n', txt))
idx = dict(re.findall(r'#define reg(\w+)_BASE_IDX\s+(\d+)', txt))
for n in sys.argv[2:]:
    if n not in off: print('%-45s MISSING' % n); continue
    o = int(off[n],16); s = int(idx[n]); a = base[s] + o
    print('%-45s seg%d off 0x%04x -> dword 0x%05x byte 0x%06x' % (n, s, o, a, a*4))
