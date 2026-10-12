import struct, sys
d = open(sys.argv[1], 'rb').read()
sig, vmaj, vmin, csum, size = struct.unpack_from('<IHHHH', d, 0)
print('binary_header sig=%#x ver=%d.%d size=%d' % (sig, vmaj, vmin, size))
off = 12
names = ['IP_DISCOVERY','GC','HARVEST_INFO','VCN_INFO','MALL_INFO','NPS_INFO']
tables = {}
for i, n in enumerate(names):
    o, c, s, p = struct.unpack_from('<HHHH', d, off + i*8)
    tables[n] = (o, s)
    print(' table %-12s off=%#x size=%d' % (n, o, s))
o, s = tables['GC']
tid, vmaj, vmin, tsize = struct.unpack_from('<IHHI', d, o)
print('GC table id=%#x ver=%d.%d size=%d' % (tid, vmaj, vmin, tsize))
if vmaj == 2:
    f = ['num_se','num_cu_per_sh','num_sh_per_se','num_rb_per_se','num_tccs','num_gprs','num_max_gs_thds','gs_table_depth','gsprim_buff_depth','parameter_cache_depth','double_offchip_lds_buffer','wave_size','max_waves_per_simd','max_scratch_slots_per_cu','lds_size','num_sc_per_se','num_packer_per_sc','num_tcp_per_sh','tcp_size_per_cu','num_sdp_interface','num_cu_per_sqc','instruction_cache_size_per_sqc','scalar_data_cache_size_per_sqc','tcc_size']
else:
    f = ['num_se','num_wgp0_per_sa','num_wgp1_per_sa','num_rb_per_se','num_gl2c','num_gprs','num_max_gs_thds','gs_table_depth','gsprim_buff_depth','parameter_cache_depth','double_offchip_lds_buffer','wave_size','max_waves_per_simd','max_scratch_slots_per_cu','lds_size','num_sc_per_se','num_sa_per_se','num_packer_per_sc','num_gl2a','num_tcp_per_sa','num_sdp_interface','num_tcps','num_tcp_per_wpg','tcp_l1_size','num_sqc_per_wgp','l1_icache_per_sqc','l1_dcache_per_sqc','gl1c_per_sa','gl1c_size_per_instance','gl2c_per_gpu','tcp_size_per_cu','tcp_cache_line','icache_per_sqc','icache_line','sdcache_per_sqc','sdcache_line','tcc_size','tcc_cache_line']
n = (tsize - 12)//4
vals = struct.unpack_from('<%dI' % min(n, len(f)), d, o+12)
for k, v in zip(f, vals):
    print('  %-28s %d' % (k, v))
