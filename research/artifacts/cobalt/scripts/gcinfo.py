import struct, sys
d = open(sys.argv[1],'rb').read()
off = 1000
tid, vmaj, vmin, size = struct.unpack_from('<IHHI', d, off)
print('gc table id %#x v%d.%d size %d' % (tid, vmaj, vmin, size))
names = ['num_se','num_wgp0_per_sa','num_wgp1_per_sa','num_rb_per_se','num_gl2c','num_gprs','num_max_gs_thds','gs_table_depth','gsprim_buff_depth','parameter_cache_depth','double_offchip_lds_buffer','wave_size','max_waves_per_simd','max_scratch_slots_per_cu','lds_size','num_sc_per_se','num_sa_per_se','num_packer_per_sc','num_gl2a','num_tcp_per_sa','num_sdp_interface','num_tcps','num_tcp_per_wpg','tcp_l1_size','num_sqc_per_wgp','l1_icache_per_sqc','l1_dcache_per_sqc','gl1c_per_sa','gl1c_size_per_instance','gl2c_per_gpu','tcp_size_per_cu','tcp_cache_line_size','icache_size_per_sqc','icache_line','sdcache_size_per_sqc','sdcache_line','tcc_size','tcc_line']
n = (size-12)//4
vals = struct.unpack_from('<%dI'%n, d, off+12)
for i,v in enumerate(vals):
    print('  %-28s %d' % (names[i] if i < len(names) else 'f%d'%i, v))
# harvest
off = 1164
sig, ver = struct.unpack_from('<II', d, off)
print('harvest sig %#x ver %d' % (sig, ver))
for i in range(32):
    hid, inst, rsv = struct.unpack_from('<HBB', d, off+8+4*i)
    if hid: print('  harvested hwid %d inst %d' % (hid, inst))
# vcn
off=1300
print('vcn', struct.unpack_from('<IHHI', d, off), struct.unpack_from('<%dI'%((96-12)//4), d, off+12))
off=1396
print('mall', struct.unpack_from('<IHHI', d, off), struct.unpack_from('<%dI'%((48-12)//4), d, off+12))
