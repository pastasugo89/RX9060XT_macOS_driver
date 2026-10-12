import struct, sys
d = open(sys.argv[1],'rb').read()
(size, hsize, hvmaj, hvmin, ipmaj, ipmin, ucver, ucsize, ucoff, crc) = struct.unpack_from('<IIHHHHIIII', d, 0)
inst, bss = struct.unpack_from('<II', d, 32)
print('file %d B; size_bytes %d header %d hdr v%d.%d ip v%d.%d ucode_version %#010x ucode_size %d array_off %#x crc %#x' % (len(d), size, hsize, hvmaj, hvmin, ipmaj, ipmin, ucver, ucsize, ucoff, crc))
print('inst_const_bytes %d bss_data_bytes %d' % (inst, bss))
PSP=256
blob = d[ucoff+PSP: ucoff+inst]   # inst_const without 256B PSP header (as amdgpu_dm does)
print('PSP header (first 16 B of payload):', d[ucoff:ucoff+16].hex())
# meta: union dmub_fw_meta = 64 reserved + info? size = sizeof(info)+64 ; search 16 alignments from end
MAGIC=0x444D5542
for i in range(64):
    for metasz in (28+64, 92, 96, 128):
        pass
# brute search for magic in last 4 KiB
tail = blob[-8192:]
pos = tail.rfind(struct.pack('<I', MAGIC))
if pos >= 0:
    m = struct.unpack_from('<IIIIB3xIHH', tail, pos)
    print('meta @ inst_const_end-%d: fw_region_size %d trace_buffer_size %d fw_version %#010x dal_fw %d shared_state_size %d shared_state_features %d' % (len(tail)-pos, m[1], m[2], m[3], m[4], m[5], m[6]))
else:
    print('meta magic not found in tail')
