import struct, sys
d = open(sys.argv[1], 'rb').read()
print("rom sig", d[0:2].hex(), "size", len(d))
rh = struct.unpack_from('<H', d, 0x48)[0]
size, frev, crev = struct.unpack_from('<HBB', d, rh)
print("rom header @0x%x size=%d rev=%d.%d sig=%r" % (rh, size, frev, crev, d[rh+4:rh+8]))
mdt = struct.unpack_from('<H', d, rh + 32)[0]
mcmd = struct.unpack_from('<H', d, rh + 30)[0]
print("masterhwfunction(cmd table) @0x%x  masterdatatable @0x%x" % (mcmd, mdt))
fwi = struct.unpack_from('<H', d, mdt + 4 + 2 * 4)[0]
size, frev, crev = struct.unpack_from('<HBB', d, fwi)
print("firmwareinfo @0x%x size=%d rev=%d.%d" % (fwi, size, frev, crev))
rev, bsclk, bmclk, cap, prot, scratch = struct.unpack_from('<IIIIII', d, fwi + 4)
print(" firmware_revision=0x%x bootup_sclk_10khz=%d bootup_mclk_10khz=%d capability=0x%x fw_protect_kb=%d bios_scratch_reg_startaddr=0x%x" % (rev, bsclk, bmclk, cap, prot, scratch))
mc_hi, mc_lo = struct.unpack_from('<II', d, fwi + 4 + 24 + 8 + 4)
print(" mc_baseaddr_high=0x%x low=0x%x" % (mc_hi, mc_lo))
# asic_init command table index 0 in master command list v2_1
ai = struct.unpack_from('<H', d, mcmd + 4)[0]
if ai:
    size, frev, crev = struct.unpack_from('<HBB', d, ai)
    print("cmd table asic_init @0x%x size=%d rev=%d.%d" % (ai, size, frev, crev))
