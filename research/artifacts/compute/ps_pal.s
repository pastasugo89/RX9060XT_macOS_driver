	.amdgcn_target "amdgcn-amd-amdpal-unknown-gfx1200"
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
; TotalNumSgprs: 2
; NumVgprs: 4
; ScratchSize: 0
; MemoryBound: 0
; FloatMode: 240
; IeeeMode: 0
; LDSByteSize: 0 bytes/workgroup (compile time only)
; SGPRBlocks: 0
; VGPRBlocks: 0
; NumSGPRsForWavesPerEU: 2
; NumVGPRsForWavesPerEU: 4
; Occupancy: 16
; WaveLimiterHint : 0
; COMPUTE_PGM_RSRC2:SCRATCH_EN: 0
; COMPUTE_PGM_RSRC2:USER_SGPR: 0
; COMPUTE_PGM_RSRC2:TRAP_HANDLER: 0
; COMPUTE_PGM_RSRC2:TGID_X_EN: 0
; COMPUTE_PGM_RSRC2:TGID_Y_EN: 0
; COMPUTE_PGM_RSRC2:TGID_Z_EN: 0
; COMPUTE_PGM_RSRC2:TIDIG_COMP_CNT: 0
	.text
	.p2alignl 7, 3214868480
	.fill 96, 4, 3214868480
	.section	.AMDGPU.gpr_maximums,"",@progbits
	.set amdgpu.max_num_vgpr, 0
	.set amdgpu.max_num_agpr, 0
	.set amdgpu.max_num_sgpr, 0
	.set amdgpu.max_num_named_barrier, 0
	.text
	.section	".note.GNU-stack","",@progbits
	.amd_amdgpu_isa "amdgcn-amd-amdpal-unknown-gfx1200"
	.amdgpu_pal_metadata
---
amdpal.pipelines:
  - .hardware_stages:
      .ps:
        .entry_point:    _amdgpu_ps_main
        .entry_point_symbol: ps_main
        .scratch_memory_size: 0
        .sgpr_count:     0x2
        .vgpr_count:     0x4
    .registers:
      '0x2c0a (SPI_SHADER_PGM_RSRC1_PS)': 0x20f0000
      '0x2c0b (SPI_SHADER_PGM_RSRC2_PS)': 0
      '0xa1b3 (SPI_PS_INPUT_ENA)': 0x3
      '0xa1b4 (SPI_PS_INPUT_ADDR)': 0x3
      '0xa1b6 (SPI_PS_IN_CONTROL)': 0x8000
...
	.end_amdgpu_pal_metadata
