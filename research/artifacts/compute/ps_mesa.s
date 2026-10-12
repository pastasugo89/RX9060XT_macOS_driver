	.section	.AMDGPU.config,"",@progbits
	.long	45096
	.long	0
	.long	165608
	.long	0
	.long	45100
	.long	0
	.long	165580
	.long	3
	.long	165584
	.long	3
	.long	4
	.long	0
	.long	8
	.long	0
	.text
	.globl	ps_main                         ; -- Begin function ps_main
	.p2align	8
	.type	ps_main,@function
ps_main:                                ; @ps_main
; %bb.0:
	v_dual_mov_b32 v2, 0 :: v_dual_mov_b32 v3, 1.0
	; return to shader part epilog
.Lfunc_end0:
	.size	ps_main, .Lfunc_end0-ps_main
                                        ; -- End function
	.set .Lps_main.num_vgpr, 4
	.set .Lps_main.num_agpr, 0
	.set .Lps_main.numbered_sgpr, 0
	.set .Lps_main.num_named_barrier, 0
	.set .Lps_main.private_seg_size, 0
	.set .Lps_main.uses_vcc, 0
	.set .Lps_main.uses_flat_scratch, 0
	.set .Lps_main.has_dyn_sized_stack, 0
	.set .Lps_main.has_recursion, 0
	.set .Lps_main.has_indirect_call, 0
	.section	.AMDGPU.csdata,"",@progbits
; Kernel info:
; codeLenInByte = 8
; TotalNumSgprs: 4
; NumVgprs: 4
; ScratchSize: 0
; MemoryBound: 0
; FloatMode: 240
; IeeeMode: 0
; LDSByteSize: 0 bytes/workgroup (compile time only)
; SGPRBlocks: 0
; VGPRBlocks: 0
; NumSGPRsForWavesPerEU: 4
; NumVGPRsForWavesPerEU: 4
; Occupancy: 16
; WaveLimiterHint : 0
; COMPUTE_PGM_RSRC2:SCRATCH_EN: 0
; COMPUTE_PGM_RSRC2:USER_SGPR: 2
; COMPUTE_PGM_RSRC2:TRAP_HANDLER: 0
; COMPUTE_PGM_RSRC2:TGID_X_EN: 0
; COMPUTE_PGM_RSRC2:TGID_Y_EN: 0
; COMPUTE_PGM_RSRC2:TGID_Z_EN: 0
; COMPUTE_PGM_RSRC2:TIDIG_COMP_CNT: 0
	.section	.AMDGPU.gpr_maximums,"",@progbits
	.set amdgpu.max_num_vgpr, 0
	.set amdgpu.max_num_agpr, 0
	.set amdgpu.max_num_sgpr, 0
	.set amdgpu.max_num_named_barrier, 0
	.section	.AMDGPU.csdata,"",@progbits
	.section	".note.GNU-stack","",@progbits
	.amd_amdgpu_isa "amdgcn-mesa-mesa3d-unknown-gfx1200"
