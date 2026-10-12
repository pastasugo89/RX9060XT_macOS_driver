s_waitcnt vmcnt(0) lgkmcnt(0)
buffer_load_dword v1, v2, s[4:7], 0 offen
image_sample v[0:3], v[4:5], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D
v_mov_b32 v0, v1
