#!/usr/bin/env python3
"""Resolve register names to absolute MMIO offsets for this Navi 44 board.

usage: regres.py <IP> <offset_header.h> REG [REG...]
The per-IP base table is taken from the parsed ip_discovery_table.bin of this card.
abs_dword = base[IP][BASE_IDX] + reg ; byte = abs_dword*4 ; direct if byte < 512 KiB (BAR5 size)
"""
import re, sys

BASES = {
    'GC':     [0x00001260, 0x0000a000, 0x0001c000, 0x02402c00],
    'SDMA0':  [0x00001260, 0x0000a000, 0x0001c000, 0x02402c00],
    'SDMA1':  [0x00001260, 0x0000a000, 0x0001c000, 0x02402c00],
    'MMHUB':  [0x0001a000, 0x02408800],
    'ATHUB':  [0x00000c00, 0x02408c00],
    'OSSSYS': [0x000010a0, 0x0240a000],
    'HDP':    [0x00000f20, 0x0240a400],
    'NBIO':   [0x00000000, 0x00000014, 0x00000d20, 0x00010400, 0x0241b000, 0x04040000],
    'MP0':    [0x00016000, 0x00016200, 0x0001ce00, 0x00dc0000, 0x00e00000, 0x00e40000, 0x00e80000, 0x00ec0000, 0x00f00000, 0x02400400, 0x0243fc00, 0x0244d400, 0x03200000, 0x03240000, 0x03280000],
    'MP1':    [0x00016000, 0x00016200, 0x0001ce00, 0x00dc0000, 0x00e00000, 0x00e40000, 0x00e80000, 0x00ec0000, 0x00f00000, 0x02400400, 0x0243fc00, 0x0244d400, 0x03200000, 0x03240000, 0x03280000],
    'SMUIO':  [0x00016800, 0x00016a00, 0x02401000, 0x03440000],
    'THM':    [0x00016600, 0x02400c00],
    'DCE':    [0x00000012, 0x000000c0, 0x000034c0, 0x00009000, 0x02403c00],
    'VCN':    [0x00007800, 0x00007e00],
    'LSDMA':  [0x00011400, 0x02456800],
    'PCIE':   [0x02411800, 0x068c0000, 0x20000000],
    'UMC':    [0x00014000, 0x002d6000, 0x02425800],
    'DF':     [0x00007000, 0x00c00000, 0x0240b800, 0x07c00000, 0x12400000],
}
BAR5 = 512 * 1024

def main():
    ip, hdr = sys.argv[1], sys.argv[2]
    txt = open(hdr).read()
    defs = dict(re.findall(r'#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)', txt))
    for r in sys.argv[3:]:
        key = r if r.startswith('reg') or r.startswith('mm') else 'reg' + r
        if key not in defs:
            print("%-50s NOT FOUND" % r); continue
        off = int(defs[key], 0)
        bi = int(defs.get(key + '_BASE_IDX', '0'), 0)
        base = BASES[ip][bi]
        ad = base + off
        print("%-50s off=0x%05x idx=%d base=0x%08x -> dword 0x%07x byte 0x%08x %s" % (
            key, off, bi, base, ad, ad * 4, "MMIO" if ad * 4 < BAR5 else "INDIRECT(pcie idx/data)"))

if __name__ == '__main__':
    main()
