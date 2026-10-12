s_wait_loadcnt 0x0
s_wait_kmcnt 0x0
buffer_load_b32 v1, v2, s[4:7], null offen
image_sample v[0:3], [v4, v5], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D
v_mov_b32 v0, v1
