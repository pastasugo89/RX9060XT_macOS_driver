#!/usr/bin/env python3
"""Dump amdgpu firmware headers (layouts from drivers/gpu/drm/amd/amdgpu/amdgpu_ucode.h)."""
import struct, sys, os, zlib

PSP_FW = ["UNK","SOS","SYS_DRV","KDB","TOC","SPL","RL","SOC_DRV","INTF_DRV","DBG_DRV","RAS_DRV","IPKEYMGR_DRV","SPDM_DRV"]
TA_FW = {0:"UNK",1:"ASD",2:"XGMI",3:"RAS",4:"HDCP",5:"DTM",6:"RAP",7:"SECUREDISPLAY"}

def u32s(d, off, n): return struct.unpack_from('<%dI' % n, d, off)

def common(d):
    sb, hs, hvmaj, hvmin, ipmaj, ipmin, uver, usz, uoff, crc = struct.unpack_from('<IIHHHHIIII', d, 0)
    return dict(size_bytes=sb, header_size=hs, hdr_ver="%d.%d" % (hvmaj, hvmin), ip_ver="%d.%d" % (ipmaj, ipmin),
                ucode_version=hex(uver), ucode_size=usz, ucode_off=uoff, crc32=hex(crc)), (hvmaj, hvmin)

def dump(path):
    d = open(path, 'rb').read()
    name = os.path.basename(path)
    c, (hmaj, hmin) = common(d)
    crc_ok = ""
    if c['ucode_off'] + c['ucode_size'] <= len(d):
        calc = zlib.crc32(d[c['ucode_off']:c['ucode_off'] + c['ucode_size']]) & 0xffffffff
        crc_ok = " (crc32 calc %s)" % hex(calc)
    print("== %s  file=%d B" % (name, len(d)))
    print("   common: " + " ".join("%s=%s" % kv for kv in c.items()) + crc_ok)
    o = 32
    if '_rlc' in name:
        v = u32s(d, o, 18)
        print("   rlc v2.0: feature=%d jt_off=%d jt_size=%d save_restore_off=%d csd_off=%d scratch=%d restore_list_size=%d" % v[:7])
        print("             reg_list_format_size=%d @%d reg_list_size=%d @%d sep_fmt=%d @%d sep=%d @%d" % v[10:18])
        o2 = o + 18 * 4
        if (hmaj, hmin) >= (2, 1):
            v1 = u32s(d, o2, 13); o2 += 13 * 4
            print("   rlc v2.1: direct_len=%d srlc ver=%d size=%d @%d | srlg ver=%d size=%d @%d | srls ver=%d size=%d @%d" % (
                v1[0], v1[1], v1[3], v1[4], v1[5], v1[7], v1[8], v1[9], v1[11], v1[12]))
        if (hmaj, hmin) >= (2, 2):
            v2 = u32s(d, o2, 4); o2 += 16
            print("   rlc v2.2: iram size=%d @%d dram size=%d @%d" % v2)
        if (hmaj, hmin) == (2, 3) or (hmaj, hmin) == (2, 4):
            v3 = u32s(d, o2, 8); o2 += 32
            print("   rlc v2.3: rlcp ver=0x%x feat=%d size=%d @%d | rlcv ver=0x%x feat=%d size=%d @%d" % v3)
        if (hmaj, hmin) == (2, 4):
            v4 = u32s(d, o2, 10)
            print("   rlc v2.4: tap delays (size,off) global=%s se0=%s se1=%s se2=%s se3=%s" % (v4[0:2], v4[2:4], v4[4:6], v4[6:8], v4[8:10]))
        if (hmaj, hmin) == (2, 5):
            v5 = u32s(d, o2, 4)
            print("   rlc v2.5: rlc_1 iram size=%d @%d dram size=%d @%d" % v5)
    elif name.endswith(('_pfp.bin', '_me.bin', '_mec.bin')):
        if hmaj == 2:
            v = u32s(d, o, 7)
            print("   gfx v2.0 (RS64): feature=%d ucode size=%d @%d data size=%d @%d start_addr=0x%x_%08x" % (v[0], v[1], v[2], v[3], v[4], v[6], v[5]))
        else:
            v = u32s(d, o, 3)
            print("   gfx v1.0: feature=%d jt_off=%d jt_size=%d" % v)
    elif '_mes' in name:
        v = u32s(d, o, 10)
        print("   mes v1.0: ucode ver=0x%x size=%d @%d | data ver=0x%x size=%d @%d | uc_start=0x%x_%08x data_start=0x%x_%08x" % (
            v[0], v[1], v[2], v[3], v[4], v[5], v[7], v[6], v[9], v[8]))
    elif '_imu' in name:
        v = u32s(d, o, 4)
        print("   imu v1.0: iram size=%d @%d dram size=%d @%d" % v)
    elif name.startswith('sdma'):
        if hmaj == 3:
            v = u32s(d, o, 3)
            print("   sdma v3.0: feature=%d ucode @%d size=%d" % v)
        elif hmaj == 2:
            v = u32s(d, o, 7)
            print("   sdma v2.0: feature=%d ctx size=%d off=%d jt %d/%d ctl size=%d off=%d" % v)
    elif '_sos' in name or ('psp' in name and '_toc' in name):
        n = u32s(d, o, 1)[0]; p = o + 4
        if hmin == 1:
            aux = u32s(d, p, 1)[0]; p += 4
            print("   psp v2.1: bin_count=%d aux_index=%d" % (n, aux))
        else:
            print("   psp v%d.%d: bin_count=%d" % (hmaj, hmin, n))
        for i in range(n):
            t, ver, off, sz = u32s(d, p + 16 * i, 4)
            print("     bin[%d] type=%-12s ver=0x%08x off=%d size=%d" % (i, PSP_FW[t] if t < len(PSP_FW) else t, ver, off, sz))
    elif '_ta' in name:
        n = u32s(d, o, 1)[0]
        print("   ta v2.0: bin_count=%d" % n)
        for i in range(n):
            t, ver, off, sz = u32s(d, o + 4 + 16 * i, 4)
            print("     bin[%d] type=%-13s ver=0x%08x off=%d size=%d" % (i, TA_FW.get(t, t), ver, off, sz))
    elif name.startswith('smu'):
        start = u32s(d, o, 1)[0]
        print("   smc v1.0: ucode_start_addr=0x%x" % start)
        if (hmaj, hmin) == (2, 1):
            cnt, eoff = u32s(d, o + 4, 2)
            print("   smc v2.1: pptable_count=%d entry_off=%d" % (cnt, eoff))
            for i in range(cnt):
                pid, poff, psz = u32s(d, eoff + 12 * i, 3)
                print("     pptable id=%d off=%d size=%d" % (pid, poff, psz))
        elif (hmaj, hmin) == (2, 0):
            poff, psz = u32s(d, o + 4, 2)
            print("   smc v2.0: ppt off=%d size=%d" % (poff, psz))
    elif 'dmcub' in name:
        v = u32s(d, o, 2)
        print("   dmcub v1.0: inst_const_bytes=%d bss_data_bytes=%d" % v)
    elif name.startswith('vcn'):
        pass

for p in sys.argv[1:]:
    dump(p)
