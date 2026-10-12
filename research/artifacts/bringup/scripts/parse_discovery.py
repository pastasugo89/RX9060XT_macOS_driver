#!/usr/bin/env python3
"""Parse an AMD IP discovery binary (layout from drivers/gpu/drm/amd/include/discovery.h)."""
import struct, sys

HWID = {1:"MP1",2:"MP2",3:"THM",4:"SMUIO",5:"FUSE",6:"CLKA",10:"PWR",11:"GC",12:"UVD/VCN",13:"AUDIO_AZ",
14:"ACP",15:"DCI",271:"DMU",16:"DCO",272:"DIO",17:"XDMA",18:"DCEAZ",274:"DAZ",19:"SDPMUX",20:"NTB",21:"VPE",
22:"UMSCH",24:"IOHC",28:"L2IMU",32:"VCE",34:"MMHUB",35:"ATHUB",36:"DBGU_NBIO",37:"DFX",38:"DBGU0",39:"DBGU1",
40:"OSSSYS",41:"HDP",42:"SDMA0",43:"SDMA1",44:"ISP",45:"DBGU_IO",46:"DF",47:"CLKB",48:"FCH",49:"DFX_DAP",
50:"L1IMU_PCIE",51:"L1IMU_NBIF",52:"L1IMU_IOAGR",66:"WAFLC",67:"FCH_USB_PD",68:"SDMA2",69:"SDMA3",70:"PCIE",
80:"PCS",89:"DDCL",90:"SST",91:"LSDMA",100:"IOAGR",108:"NBIF",124:"IOAPIC",128:"SYSTEMHUB",144:"NTBCCP",
150:"UMC",168:"SATA",170:"USB",176:"CCXSEC",200:"XGMI",216:"XGBE",255:"MP0",294:"ATU",295:"AIGC"}
for i in range(53,66): HWID[i]="L1IMU%d"%(i-50)

def csum(b):
    return sum(b) & 0xffff

def main(path):
    d = open(path,'rb').read()
    print("file size", len(d))
    sig, vmaj, vmin, bcs, bsize = struct.unpack_from('<IHHHH', d, 0)
    print("binary_header: signature=0x%08x (expect 0x28211407) version=%d.%d checksum=0x%04x size=%d" % (sig, vmaj, vmin, bcs, bsize))
    print("  computed checksum over [10:%d] = 0x%04x" % (bsize, csum(d[10:bsize])))
    if vmaj == 2:
        ntab, pad = struct.unpack_from('<HH', d, 12)
        toff = 16
    else:
        ntab = 6; toff = 12
    names = ["IP_DISCOVERY","GC","HARVEST_INFO","VCN_INFO","MALL_INFO","NPS_INFO"]
    tables = []
    for i in range(ntab):
        off, cs, sz, pad = struct.unpack_from('<HHHH', d, toff + 8*i)
        tables.append((off, cs, sz))
        print("  table[%d] %-12s offset=0x%04x checksum=0x%04x size=%d" % (i, names[i] if i < 6 else '?', off, cs, sz))
    # IP discovery
    off = tables[0][0]
    sig, ver, size, tid, ndies = struct.unpack_from('<IHHIH', d, off)
    print("\nip_discovery_header @0x%x: signature=0x%08x ver=%d size=%d id=0x%x num_dies=%d" % (off, sig, ver, size, tid, ndies))
    print("  computed checksum = 0x%04x (expected 0x%04x)" % (csum(d[off:off+size]), tables[0][1]))
    dies = []
    for i in range(16):
        did, doff = struct.unpack_from('<HH', d, off + 14 + 4*i)
        if i < ndies: dies.append((did, doff))
    flags = d[off + 14 + 64]
    base64 = (ver == 4) and (flags & 1)
    print("  die_info:", dies, " base_addr_64_bit:", bool(base64), "(raw byte 0x%02x)" % flags)
    for did, doff in dies:
        die_id, nips = struct.unpack_from('<HH', d, doff)
        print("\n  die %d @0x%x num_ips=%d" % (die_id, doff, nips))
        p = doff + 4
        print("  %-4s %-11s %-4s %-3s %-10s %-4s %-4s %s" % ("hwid","name","inst","nba","version","sub","var","base addresses (dword offsets)"))
        for j in range(nips):
            hw_id, inst, nba, maj, mn, rev, b7 = struct.unpack_from('<HBBBBBB', d, p)
            if ver >= 3:
                sub = b7 & 0xf; var = (b7 >> 4) & 0xf; harv = None
            else:
                harv = b7 & 0xf; sub = var = 0
            p += 8
            bases = []
            for k in range(nba):
                if base64:
                    v = struct.unpack_from('<Q', d, p)[0]; p += 8
                    bases.append("0x%x" % v)
                else:
                    v = struct.unpack_from('<I', d, p)[0]; p += 4
                    bases.append("0x%08x" % v)
            extra = ""
            if hw_id == 12:
                extra = " (vcn_config bits[7:6]=0x%x)" % (rev & 0xc0)
            print("  %-4d %-11s %-4d %-3d %2d.%d.%-5d %-4d %-4d %s%s" % (hw_id, HWID.get(hw_id, '?'), inst, nba, maj, mn, rev & (0x3f if hw_id == 12 else 0xff), sub, var, " ".join(bases), extra))
    # GC info
    off, cs, sz = tables[1]
    if off:
        tid, vmaj, vmin, size = struct.unpack_from('<IHHI', d, off)
        print("\ngc_info @0x%x: table_id=0x%x version=%d.%d size=%d computed csum(size&0xffff)=0x%04x expected=0x%04x" % (off, tid, vmaj, vmin, size, csum(d[off:off+(size & 0xffff)]), cs))
        if vmaj == 1:
            f = ["gc_num_se","gc_num_wgp0_per_sa","gc_num_wgp1_per_sa","gc_num_rb_per_se","gc_num_gl2c","gc_num_gprs",
                 "gc_num_max_gs_thds","gc_gs_table_depth","gc_gsprim_buff_depth","gc_parameter_cache_depth",
                 "gc_double_offchip_lds_buffer","gc_wave_size","gc_max_waves_per_simd","gc_max_scratch_slots_per_cu",
                 "gc_lds_size","gc_num_sc_per_se","gc_num_sa_per_se","gc_num_packer_per_sc","gc_num_gl2a"]
            if vmin >= 1: f += ["gc_num_tcp_per_sa","gc_num_sdp_interface","gc_num_tcps"]
            if vmin >= 2: f += ["gc_num_tcp_per_wpg","gc_tcp_l1_size","gc_num_sqc_per_wgp","gc_l1_instruction_cache_size_per_sqc",
                                "gc_l1_data_cache_size_per_sqc","gc_gl1c_per_sa","gc_gl1c_size_per_instance","gc_gl2c_per_gpu"]
            if vmin >= 3: f += ["gc_tcp_size_per_cu","gc_tcp_cache_line_size","gc_instruction_cache_size_per_sqc",
                                "gc_instruction_cache_line_size","gc_scalar_data_cache_size_per_sqc","gc_scalar_data_cache_line_size",
                                "gc_tcc_size","gc_tcc_cache_line_size"]
            for i, n in enumerate(f):
                if 12 + 4*i + 4 <= size:
                    v = struct.unpack_from('<I', d, off + 12 + 4*i)[0]
                    print("  %-40s %d (0x%x)" % (n, v, v))
            rem = size - 12 - 4*len(f)
            if rem > 0:
                print("  extra trailing bytes in table:", d[off+12+4*len(f):off+size].hex())
    # Harvest
    off, cs, sz = tables[2]
    if off:
        sig, ver = struct.unpack_from('<II', d, off)
        print("\nharvest_table @0x%x signature=0x%08x (expect 0x56524148) version=%d computed csum=0x%04x expected=0x%04x" % (off, sig, ver, csum(d[off:off+8+32*4]), cs))
        for i in range(32):
            hw_id, inst, res = struct.unpack_from('<HBB', d, off + 8 + 4*i)
            if hw_id == 0:
                print("  (end of list at entry %d)" % i); break
            print("  harvested: hw_id=%d (%s) instance=%d" % (hw_id, HWID.get(hw_id, '?'), inst))
    # VCN info
    off, cs, sz = tables[3]
    if off:
        tid, vmaj, vmin, size = struct.unpack_from('<IHHI', d, off)
        n = struct.unpack_from('<I', d, off + 12)[0]
        print("\nvcn_info @0x%x table_id=0x%x ver=%d.%d size=%d num_instances=%d" % (off, tid, vmaj, vmin, size, n))
        for i in range(min(n, 4)):
            inum, fuse, r0, r1 = struct.unpack_from('<IIII', d, off + 16 + 16*i)
            print("  instance %d fuse=0x%x (av1_dis=%d vp9_dis=%d hevc_dis=%d h264_dis=%d)" % (inum, fuse, fuse & 1, (fuse >> 1) & 1, (fuse >> 2) & 1, (fuse >> 3) & 1))
    # MALL info
    off, cs, sz = tables[4]
    if off:
        tid, vmaj, vmin, size = struct.unpack_from('<IHHI', d, off)
        print("\nmall_info @0x%x table_id=0x%x ver=%d.%d size=%d" % (off, tid, vmaj, vmin, size))
        vals = struct.unpack_from('<' + 'I' * ((size - 12) // 4), d, off + 12)
        print("  raw dwords:", [hex(v) for v in vals])
        if vmaj == 1:
            print("  mall_size_per_m=%d (0x%x) m_s_present=0x%x m_half_use=0x%x m_mall_config=0x%x" % (vals[0], vals[0], vals[1], vals[2], vals[3]))
        elif vmaj == 2:
            print("  mall_size_per_umc=%d bytes (%d MiB)" % (vals[0], vals[0] >> 20))
    if len(tables) > 5:
        off, cs, sz = tables[5]
        if off:
            tid, vmaj, vmin, size = struct.unpack_from('<IHHI', d, off)
            print("\nnps_info @0x%x table_id=0x%x ver=%d.%d size=%d" % (off, tid, vmaj, vmin, size))

if __name__ == '__main__':
    main(sys.argv[1])
