#!/usr/bin/env python3
"""Minimal PM4 type-3 decoder for amdgpu debugfs ring dumps (amdgpu_ring_*).
The dump starts with 3 dwords (rptr, wptr, driver wptr) followed by the ring.
Opcode names are parsed from linux amdgpu/nvd.h.
Usage: decode_pm4.py <nvd.h> <ring.bin> [max_packets]"""
import re, struct, sys

def opcodes(nvd):
    names = {}
    for m in re.finditer(r"#define\s+PACKET3_(\w+)\s+(0x[0-9A-Fa-f]+)\s*$", open(nvd).read(), re.M):
        names.setdefault(int(m.group(2), 16), m.group(1))
    return names

def main():
    names = opcodes(sys.argv[1])
    data = open(sys.argv[2], "rb").read()
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    w = struct.unpack("<%dI" % (len(data) // 4), data[: len(data) // 4 * 4])
    print("rptr=0x%x wptr=0x%x drv_wptr=0x%x (dwords)" % w[:3])
    ring, i, n = w[3:], 0, 0
    while i < len(ring) and n < limit:
        h = ring[i]
        t = h >> 30
        if t == 3:
            cnt, op = (h >> 16) & 0x3FFF, (h >> 8) & 0xFF
            body = ring[i + 1 : i + 2 + cnt]
            print("%05x T3 %-28s cnt=%-3d %s" % (i, names.get(op, "op_0x%02x" % op), cnt,
                  " ".join("%08x" % x for x in body[:6]) + (" ..." if len(body) > 6 else "")))
            i += cnt + 2
        elif t == 2 or h == 0xFFFF1000:
            i += 1  # filler / NOP
        else:
            print("%05x T%d raw 0x%08x" % (i, t, h))
            i += 1
        n += 1

if __name__ == "__main__":
    main()
