s_wait_loadcnt 0x0
s_wait_samplecnt 0x0
s_wait_bvhcnt 0x0
s_wait_kmcnt 0x0
s_wait_dscnt 0x0
s_wait_alu 0xfffe
global_load_b32 v1, v[2:3], off scope:SCOPE_SYS th:TH_LOAD_NT
buffer_load_b32 v1, off, s[4:7], s8 offset:8388607
ds_bvh_stack_push8_pop2_rtn_b64 v[0:1], v2, v3, v[4:11]
v_wmma_f32_16x16x16_f16 v[0:7], v[8:11], v[12:15], v[0:7]
v_swmmac_f32_16x16x32_f16 v[0:7], v[8:11], v[12:19], v20
v_cvt_pk_fp8_f32 v1, v2, v3
s_barrier_signal -1
s_barrier_wait 0xffff
s_prefetch_data s[0:1], 0x0, null, 0
global_load_tr_b128 v[0:3], v[4:5], off
image_bvh8_intersect_ray v[0:9], [v[10:11], v[12:13], v[14:16], v[17:19], v20], s[0:3]
image_bvh_dual_intersect_ray v[0:9], [v[10:11], v[12:13], v[14:16], v[17:19], v[20:21]], s[0:3]
image_bvh64_intersect_ray v[0:3], [v[4:5], v6, v[7:9], v[10:12], v[13:15]], s[0:3]
