#!/usr/bin/env python3
"""Walk a MES scheduler ring dump (debugfs amdgpu_ring_mes_*) and list the
MES API packets (header: type:4 opcode:8 dwsize:8), with opcode names parsed
from linux amd/include/mes_v12_api_def.h.
Usage: decode_mes_ring.py <mes_v12_api_def.h> <ring.bin>"""
import re, struct, sys

def main():
    src = open(sys.argv[1]).read()
    names = {}
    for n, v in re.findall(r"MES_SCH_API_(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\b", src):
        names.setdefault(int(v, 0), n)
    data = open(sys.argv[2], "rb").read()
    w = struct.unpack("<%dI" % (len(data) // 4), data[: len(data) // 4 * 4])
    rptr, wptr = w[0], w[1]
    print("rptr=0x%x wptr=0x%x (dwords)" % (rptr, wptr))
    ring, i = w[3:], 0
    while i < min(wptr, len(ring)):
        h = ring[i]
        typ, op, size = h & 0xF, (h >> 4) & 0xFF, (h >> 12) & 0xFF
        if typ == 0 or size == 0:
            i += 1
            continue
        body = ring[i + 1 : i + size]
        print("%05x type=%d %-22s dwsize=%-3d %s" % (i, typ, names.get(op, "op_%d" % op), size,
              " ".join("%08x" % x for x in body[:10]) + (" ..." if len(body) > 10 else "")))
        i += size

if __name__ == "__main__":
    main()
