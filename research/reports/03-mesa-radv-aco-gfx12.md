# 03 — Mesa userspace per gfx1200 (RADV/ACO) e requisiti kernel per un port Darwin

> Target: AMD Radeon RX 9060 XT (Navi 44, PCI 1002:7590, GC 12.0.0 / gfx1200, DCN 4.0.1, SDMA 7.0.0).
> Fonti: mesa main (Oct 2026) in `research/src/mesa`, linux master 7.3-rc in `research/src/linux`, riferimenti in `research/refs/` (non fidati, sola lettura).
> Legenda: **[VERIFICATO]** = letto nel codice / misurato su questa macchina / test eseguito; **[INFERITO]** = deduzione non verificata direttamente.

## 0. Sommario esecutivo

1. **RADV su gfx1200 è maturo** [VERIFICATO]: Mesa 26.3-devel espone sulla RX 9060 XT Vulkan 1.4.363 con 247 estensioni,
   incluse ray tracing (BVH8, `RT_3_1`), mesh/task shader, cooperative matrix, bfloat16/float8, descriptor heap. radeonsi
   usa ACO. Il compilatore e il driver userspace **non hanno codice specifico Navi 44 vs Navi 48**: le differenze passano solo
   da `radeon_info` (2 vs 4 SE, 32 vs 64 CU, 128 vs 256 bit, MALL 32 vs 64 MiB). L'ISA è identica (llvm-mc `gfx1200` e
   `gfx1201` producono encoding identici). Addrlib GFX12 non usa GB_ADDR_CONFIG: layout tiled identico sulle due GPU.
2. **Il confine kernel di RADV è piccolo e già astratto** [VERIFICATO]: tutte le chiamate kernel passano per 59
   funzioni `ac_drm_*` (`src/amd/common/ac_linux_drm.h`), di cui RADV + `ac_gpu_info.c` ne usano ~48; esistono già due
   backend (libdrm e virtio native context, che con soli 10 comandi `AMDGPU_CCMD_*` fa girare RADV in una VM). La sync
   passa da `util_sync_provider` (15 callback), sostituibile in userspace. Un port Darwin = **terzo backend sotto
   `ac_drm`** + piccole modifiche a enumerazione/meson; RADV/ACO/addrlib (~354 k righe) restano intatti.
3. **Semantica kernel da garantire** [VERIFICATO]: VA scelti da userspace (range HIGH `0xffff8000_00000000+`, 32-bit
   `address32_hi=0xffff8000`), `GEM_VA` MAP/UNMAP (+PRT/CLEAR/REPLACE per sparse), BO VRAM/GTT con flag
   `AMDGPU_GEM_CREATE_*` incluso **`GFX12_DCC` → PTE bit 58**, CS con chunk IB/FENCE/SYNCOBJ/BO_HANDLES e **gang submit**
   multi-IP (task shader), fence seqno per ring, reset di contesto con `-ECANCELED/-ENODATA/-ETIME`. Implicit sync non
   necessaria su macOS (RADV marca tutti i BO interni `EXPLICIT_SYNC`). User queue: RADV non le usa (solo radeonsi con
   `AMD_USERQ=1`); sul kernel misurato `userq_ip_mask=0`.
4. **GFX12 sposta lavoro verso userspace e page table** [VERIFICATO]: niente CLEAR_STATE né shadowing FW
   (`has_kernelq_reg_shadowing=0`), ring NGG (attribute/pos/prim) e scratch programmati dall'IB utente con
   `SET_*_REG_PAIRS` (`0xB8/0xBA/0xBE`); DCC "trasparente" controllata da `PTE.D && COMPRESSION_EN`, metadati nascosti
   all'userspace; il kernel ricomprime/decomprime con SDMA 7.0 durante i move.
5. **Cobalt64 ha già fatto il port RADV-Darwin per Navi 48** [VERIFICATO]: 9 patch, +8205 righe (≈3 k di backend reale,
   ≈0.5 k di modifiche a file Mesa), esattamente con l'architettura di cui sopra (dispatch in `ac_linux_drm.c`, VA
   manager libdrm vendorizzato, sync provider userspace, ABI kext "N48N" con struct gemelle di `DRM_AMDGPU_*`, 9 selettori
   base). 7000-macos ne è una copia identica (5 patch) senza supporto RDNA3 in Mesa. Limiti da superare per Navi 44:
   **info device canned gfx1201** (sbagliate per Navi 44), solo ring GFX (niente compute/gang → niente task shader),
   niente PRT/sparse, DCC ignorato, sync non condivisibile tra processi.
6. **Stima** [INFERITO]: un backend Darwin per RADV su Navi 44 è ~4 k righe minime (fase 1) fino a ~6-9 k con mock/test e
   tutte le funzioni; ABI kext di ~12-16 selettori (§7.2). È la parte più piccola del progetto; i rischi veri sono nel
   kext (bring-up, VM, ring/MES, IRQ) e nel layer Metal.

## 1. Test eseguiti su questa macchina (vulkaninfo, RADV_DEBUG=info, glxinfo)

Tutti i test sono stati eseguiti come utente non privilegiato. Gli output completi sono in
`/tmp/claude-1000/-home-pastasugo89-Documenti-rx9060xt-metal-driver/75517241-da08-4a95-9813-eba8a30820e6/scratchpad/mesa-radv/`
(`vulkaninfo_summary.txt`, `vulkaninfo_full.txt`, `gpu0_full.txt`, `VP_VULKANINFO_*.json`,
`radv_debug_info.txt`, `amd_debug_info.txt`, `glxinfo_B.txt`, `gfx1200_canned_dump.txt`).

### 1.1 Dump read-only di tutte le query `AMDGPU_INFO` (strumento scritto ad hoc) [VERIFICATO]

`scratchpad/mesa-radv/dumpinfo/dumpinfo.c` (~250 righe, compilato con `-ldrm -ldrm_amdgpu`) apre
`/dev/dri/renderD128` e chiama **solo** `DRM_IOCTL_VERSION`, `DRM_IOCTL_GET_CAP` e `DRM_IOCTL_AMDGPU_INFO`
(nessuna BO, nessuna CS). Stampa i valori nello stesso formato degli initializer di
`src/amd/common/amdgpu_devices.c` (i "canned devices" usati da `src/amd/drm-shim/amdgpu_noop_drm_shim.c`; `AMD_FORCE_FAMILY` è stato rimosso, `ac_gpu_info.c:224-235`, e in `amdgpu_devices.c` esiste `gfx1201` ma **non** `gfx1200`): è
quindi direttamente la **tabella di valori che un winsys Darwin deve restituire** a `ac_query_gpu_info()`.
Output: `gfx1200_canned_dump.txt`. Valori chiave:

| Query | Valore misurato su RX 9060 XT | Note |
|---|---|---|
| DRM version | amdgpu **3.64.0** | RADV legge `drm_minor` per abilitare feature |
| `DRM_CAP_SYNCOBJ` / `_TIMELINE` | 1 / 1 | RADV richiede syncobj timeline |
| `AMDGPU_INFO_DEV_INFO` (`struct drm_amdgpu_info_device`, sizeof=448) | device_id 0x7590, chip_rev 1, external_rev **0x41**, pci_rev 0xc0, family **152 (0x98, AMDGPU_FAMILY_GC_12_0_0)** | external_rev 0x41 = chip_rev(1)+0x40 → CHIP_GFX1200 |
| num_shader_engines / arrays_per_engine | 2 / 2 | |
| cu_active_number / cu_bitmap | 32 / `{0xff,0xff}` per SE0,SE1 | 8 CU per SA |
| enabled_rb_pipes_mask / num_rb_pipes | 0xff / 8 | |
| gpu_counter_freq | 100000 kHz (100 MHz) | → `timestampPeriod = 10` ns |
| max_engine_clock / max_memory_clock | 0x2932e0 = 2700000 kHz / 0x133210 = 1258000 kHz | |
| min_engine_clock / min_memory_clock | 500 MHz / 96 MHz | |
| ids_flags | 0x18 | 0x8 = `AMDGPU_IDS_FLAGS_CONFORMANT_TRUNC_COORD`, 0x10 = `AMDGPU_IDS_FLAGS_GANG_SUBMIT` (definito in linux `include/uapi/drm/amdgpu_drm.h:1096`, non ancora nella copia uapi di Mesa); FUSION(0x1)=0 → dGPU, PREEMPTION(0x2)=0 (niente MCBP), TMZ(0x4)=0 |
| virtual_address_offset / _max / _alignment | 0x10000 / 0x800000000000 / 4096 | 47 bit low VA |
| high_va_offset / high_va_max | 0xffff800000000000 / 0xffffffffffbf0000 | |
| pte_fragment_size / gart_page_size | 2 MiB / 4 KiB | |
| vram_type / vram_bit_width | 9 (`AMDGPU_VRAM_TYPE_GDDR6`) / 128 | |
| wave_front_size / num_shader_visible_vgprs | 32 / 1536 | |
| num_tcc_blocks / tcc_disabled_mask | 16 / 0 | |
| gc_double_offchip_lds_buf | 64 | |
| tcp/sqc_data/sqc_inst/gl1c/gl2c cache (KB) | 32 / 16 / 32 / 256 / 4096 | |
| mall_size | 0x2000000 = **32 MiB** (Infinity Cache) | |
| shadow_size / csa_size | 0 / 0 | niente FW shadowing su GFX12 kernel queue |
| **userq_ip_mask** | **0** | user queue NON abilitate su questo kernel |
| `GB_ADDR_CONFIG` (READ_MMR_REG 0x263e) | **0x08200545** | num_pipes 32, pipe_interleave 256B, num_pkrs 32 |
| `AMDGPU_INFO_HW_IP_INFO` GFX | 12.0, `available_rings 0x1`, ib align 32/32, ip_discovery_version 0xc0000 | |
| COMPUTE | 12.0, rings 0xf (4) | |
| DMA (SDMA) | 7.0, rings 0x3 (2), ib_start_alignment 256, size_align 4 | |
| VCN_DEC/ENC/JPEG | 5.0 (VCN unificato), JPEG rings 0x1 | |
| `AMDGPU_INFO_FW_VERSION` | ME 3090(0xc12)/feat 29, PFP 3190(0xc76)/29, MEC 3450(0xd7a)/29, RLC 0xbde160, SMC 0x664700, SDMA 0x798e96, SOS 0x3b0f0d, VCN 0x910c01a, DMCUB 0xa004b00, MES 0x93, MES_KIQ 0x93, IMU 0xc2c2500 | RADV usa ME/PFP/MEC version+feature |
| `AMDGPU_INFO_MAX_IBS` | GFX 192, COMPUTE 125, SDMA 49, ... | |
| `AMDGPU_INFO_MEMORY` | vram total 17095983104, usable 17027702784, max_alloc 12770777088; cpu_accessible_vram = vram (ReBAR attivo); gtt total 16321708032 | |
| `AMDGPU_INFO_VRAM_GTT` | vram 17027702784, vis 17027702784, gtt 16306204672 | |
| `AMDGPU_INFO_SW_INFO` address32_hi | 0xffff8000 | |
| `amdgpu_va_range_query` | [0x10000, 0x800000000000) | |

### 1.2 `RADV_DEBUG=info vulkaninfo` (dGPU, `radv_debug_info.txt` riga 228+) [VERIFICATO]

`radeon_info` derivato da Mesa per la RX 9060 XT:
- `name = GFX1200`, `family = 99` (`CHIP_GFX1200` nell'enum `radeon_family`), `gfx_level = 17` (`GFX12`), `family_id = 152`, `chip_external_rev = 65`.
- `num_se 2, num_rb 8, num_cu 32`, `max_gpu_freq 2700 MHz`, `max_gflops 22118`.
- Cache: `l2_cache_size 4096 KB`, `l3_cache_size 32 MB` (MALL), `tcp 32 KB`, `tcc_cache_line_size 256`, `memory_channels 16 (TCC blocks)`.
- Memoria: `vram_size 16384 MB`, `vram_vis_size 16304 MB`, `all_vram_visible = 1`, `has_dedicated_vram = 1`, `gart_size 15566 MB`, `vram_type 9`, `memory_bus_width 128`, `memory_bandwidth 323 GB/s`, `max_memory_clock 1258 MHz`.
- Flag GFX12: `has_set_context_pairs = 1`, `has_set_sh_pairs = 1`, `has_set_uconfig_pairs = 1`, `has_out_of_order_uncached_l2 = 1`, `cp_sdma_ge_use_system_memory_scope = 1`, `has_attr_ring = 1`, `has_image_bvh_intersect_ray = 1`, `has_smem_with_null_prt_bug = 1`, `conformant_trunc_coord = 1`, `has_scratch_base_registers = 1`, `has_clear_state = 0` (non stampato perché 0: su GFX12 niente CLEAR_STATE), `has_load_ctx_reg_pkt = 1`.
- IP: `GFX 12.0 queues:1 align:256 pad_dw:0x7`, `COMPUTE 12.0 queues:4`, `SDMA 7.0 queues:2 pad_dw:0xf`, `VCN 5.0 (vcn_unified=1)`, `VCN_JPEG 5.0`.
- Kernel caps: `drm 3.64.0`, `has_userptr 1`, `has_timeline_syncobj 1`, `has_vm_always_valid 1`, `has_sparse 1`, `has_kernelq_reg_shadowing 0`, `has_tmz_support 0`, `kernel_has_modifiers 1`. "Userqueue info:" vuoto.
- Compiler: `num_physical_sgprs_per_simd 1728`, `num_physical_wave64_vgprs_per_simd 768` (gfx1200 ha VGPR file 1.5x come gfx1100: 192 KB/SIMD), `wave64_vgpr_alloc_granularity 12`, `max_scratch_waves 1024`, `lds_size_per_workgroup 65536`.
- Ring: `attribute_ring_size_per_se 1408 KB`, `pos_ring 256 KB/SE`, `prim_ring 64 KB/SE`, `total_attribute_pos_prim_ring_size 4096 KB`, `tess_factor_ring 96 KB`, `tess_offchip_ring 4096 KB`.
- Render backend: `num_tile_pipes 32`, `enabled_rb_mask 0xff`, `max_alignment 262144` (256 KiB swizzle).
- Modifier DRM elencati (32bpp): `GFX12,64KB_2D,DCC,DCC_MAX_COMPRESSED_BLOCK=256B` (0x200000000082305), `...=128B`, `GFX12,256KB_2D,DCC`, `GFX12,4KB_2D,DCC`, `GFX12,256B_2D,DCC`, `GFX12,64KB_2D`, `GFX11,64KB_D` (0x200000000000a04, compat), `GFX12,256B_2D`, `LINEAR`.

Nota: il device 0 per RADV è l'iGPU Raphael (gfx1036, `renderD129`); la RX 9060 XT è `renderD128`, PCI 0000:03:00.0.

### 1.3 vulkaninfo (GPU0 = RX 9060 XT, `gpu0_full.txt`) [VERIFICATO]

- `apiVersion 1.4.363`, `driverVersion 26.2.99`, `driverInfo "Mesa 26.3.0-devel (git-8ea6e9dd41)"`, `deviceName "AMD Radeon RX 9060 XT (RADV GFX1200)"`, `driverID DRIVER_ID_MESA_RADV`, `conformanceVersion 1.4.5.3`, `deviceUUID 00000000-0300-0000-...` (derivato dal bus PCI: il winsys Darwin deve fornire PCI bus info o un UUID stabile).
- **Device extensions: 247**, tra cui `VK_KHR_ray_query`, `VK_KHR_ray_tracing_pipeline`, `VK_KHR_ray_tracing_position_fetch`, `VK_KHR_ray_tracing_maintenance1`, `VK_EXT_mesh_shader`, `VK_KHR_cooperative_matrix`, `VK_KHR_shader_bfloat16`, `VK_EXT_shader_float8`, `VK_KHR_shader_float16_int8`, `VK_EXT_descriptor_heap`, `VK_EXT_shader_object`, `VK_KHR_maintenance10`, `VK_EXT_device_fault`, `VK_KHR_present_wait2`, video decode AV1/H264/H265/VP9 + encode AV1/H264/H265. Estensioni dipendenti da Linux da rimpiazzare/disattivare su Darwin: `VK_KHR_external_memory_fd`, `VK_EXT_external_memory_dma_buf`, `VK_EXT_image_drm_format_modifier`, `VK_EXT_external_memory_host` (userptr), `VK_EXT_acquire_drm_display`, `VK_KHR_display`.
- Limiti: `maxImageDimension2D 32768`, `maxFramebufferWidth 16384`, `maxColorAttachments 8`, `maxBoundDescriptorSets 32`, `maxPushConstantsSize 256`, `maxComputeSharedMemorySize 65536`, `maxComputeWorkGroupInvocations 1024`, `maxStorageBufferRange 4294967295`, `maxMemoryAllocationCount 4294967295`, `bufferImageGranularity 1`, `sparseAddressSpaceSize 0x800000000000` (= virtual_address_max), `minUniform/StorageBufferOffsetAlignment 4`, `nonCoherentAtomSize 64`, `timestampPeriod 10`, `maxSamplerAnisotropy 16`, `maxViewports 16`, `maxBufferSize 0xfffffffc`.
- Subgroup: `subgroupSize 64` (default per compute), `minSubgroupSize 32`, `maxSubgroupSize 64` (wave32/wave64 selezionabili).
- Mesh: `maxTaskWorkGroupInvocations 1024`, `maxMeshWorkGroupInvocations 256`, `maxMeshOutputVertices 256`.
- RT: `shaderGroupHandleSize 32`, `maxRayRecursionDepth 31`, `maxGeometryCount 16777215`, `maxPrimitiveCount 536870911`.
- Feature: `shaderFloat64/Int64/Int16/Float16/Int8 = true`, `rayQuery/rayTracingPipeline/accelerationStructure = true`, `meshShader/taskShader = true`, `cooperativeMatrix = true`, `shaderBFloat16Type = true`, `shaderFloat8 = true`, `descriptorBuffer = true`, `bufferDeviceAddress = true`, `timelineSemaphore = true`, `dynamicRendering = true`, `shaderObject = true`, `sparseBinding = true`, `shaderBufferInt64Atomics = true`, `shaderBufferFloat32AtomicAdd = true`, `shaderSharedFloat64Atomics = true`, `shaderSubgroupClock = true`, `integerDotProduct8BitUnsignedAccelerated = true`.
- **Memory heaps**: heap0 = 16321708032 B (15.20 GiB, GTT, nessun flag), heap1 = 17095983104 B (15.92 GiB, `DEVICE_LOCAL`).
- **Memory types (7)**: [0] DEVICE_LOCAL (heap1), [1] DEVICE_LOCAL (heap1, variante 32-bit VA), [2] HOST_VISIBLE|HOST_COHERENT (heap0, GTT WC), [3] DEVICE_LOCAL|HOST_VISIBLE|HOST_COHERENT (heap1, ReBAR), [4] idem (32-bit), [5] HOST_VISIBLE|HOST_COHERENT|HOST_CACHED (heap0, GTT cached), [6] HOST_VISIBLE|HOST_COHERENT (heap0, 32-bit). Il mapping heap→dominio (VRAM vs GTT, `AMDGPU_GEM_CREATE_CPU_GTT_USWC`, `AMDGPU_GEM_CREATE_32BIT`) è tutto calcolato da `radv_physical_device.c` sui valori `vram_size`/`vram_vis_size`/`gart_size` del winsys.
- Queue families: [0] GRAPHICS|COMPUTE|TRANSFER|SPARSE ×1, [1] COMPUTE|TRANSFER|SPARSE ×4, [2] VIDEO_DECODE ×1, [3] VIDEO_ENCODE ×1, [4] SPARSE_BINDING ×1 (coda sparse "virtuale", nessun ring HW). Nessuna famiglia TRANSFER-only: RADV non espone SDMA per default su GFX12 [VERIFICATO sull'output; motivazione in §3.6].

### 1.4 `glxinfo -B` [VERIFICATO]

`OpenGL renderer string: AMD Radeon RX 9060 XT (radeonsi, gfx1200, ACO, DRM 3.64, 7.2.9-1-cachyos)`,
`4.6 (Core Profile) Mesa 26.3.0-devel (git-8ea6e9dd41)`, `Video memory: 16384MB`, `Unified memory: no`.
radeonsi su gfx1200 usa **ACO** (non LLVM) per default: lo stesso compilatore di RADV.

## 2. ac_gpu_info.c per GFX12 / CHIP_GFX1200: cosa RADV ricava dal kernel

File: `research/src/mesa/src/amd/common/ac_gpu_info.c` (2635 righe). Punto d'ingresso
`ac_query_gpu_info(int fd, void *dev_p, struct radeon_info *info, bool require_pci_bus_info, bool compiler_compat_mode)`
(riga 1461), chiamato da `radv_amdgpu_winsys_query_info()` (`src/amd/vulkan/winsys/amdgpu/radv_amdgpu_winsys.c`).
**Novità importante rispetto a Mesa 23/24 [VERIFICATO]**: la funzione è stata spezzata in sotto-funzioni pure che
prendono solo struct già popolate (`ac_fill_compiler_info` r.238, `ac_fill_tiling_info` r.454, `ac_fill_hw_ip_info`
r.492, `ac_fill_memory_info` r.551, `ac_identify_chip` r.663, `ac_fill_bug_info` r.942, `ac_fill_feature_info` r.1089,
`ac_fill_hw_info` r.1209, `ac_fill_tess_info` r.1384). Tutti gli accessi al kernel passano per `ac_drm_*`
(`ac_linux_drm.h`). Un port Darwin quindi **non deve toccare ac_gpu_info.c**: basta che le `ac_drm_query_*`
restituiscano struct `drm_amdgpu_*` con i valori di §1.1.

### 2.1 Sequenza esatta delle query in `ac_query_gpu_info()` [VERIFICATO, righe 1461-1830]

| # | Chiamata | Struct / valore | Uso / note GFX12 |
|---|---|---|---|
| 1 | `handle_env_var_force_family()` | env `AMD_FORCE_FAMILY` | ora rifiutato: "use AMDGPU drm-shim" (r.224-235) |
| 2 | `ac_drm_query_pci_bus_info()` | `info->pci.{domain,bus,dev,func}` via `drmGetDevice2` | se `require_pci_bus_info` e fallisce → errore. Serve per `deviceUUID` e `VK_EXT_pci_bus_info` |
| 3 | drm version (già in `ac_drm_device_initialize`) | `drm_major == 3`, `drm_minor >= AC_AMDGPU_DRM_MINOR` | `amd_family.h:16-17`: **minimo 3.59** ("kernel 6.11.2+"). Il winsys Darwin deve dichiarare 3.64 (o ≥3.60 per `gfx12_supports_dcc_write_compress_disable`, r.1189) |
| 4 | `ac_drm_device_get_sync_provider(dev)->wait != NULL` | `util_sync_provider` | **syncobj obbligatori** (r.1502) |
| 5 | `ac_drm_query_gpu_info(dev, &amdinfo)` | `struct amdgpu_gpu_info`; per family ≥ AI legge **un solo registro**: `GB_ADDR_CONFIG` (dword 0x263e, `READ_MMR_REG`, instance 0xffffffff) | `ac_linux_drm.c:677-750`; su GFX12 niente `gb_tile_mode`/`mc_arb_ramcfg` |
| 6 | `ac_drm_query_info(AMDGPU_INFO_DEV_INFO)` | `struct drm_amdgpu_info_device` (448 B su 3.64) | cuore di tutto, v. 2.2 |
| 7 | `userq_ip_mask` | da dev_info, ma **solo se `AMD_USERQ=1`** e mai per SDMA (r.1520-1529); richiede drm ≥ 3.65 | RADV non usa userq |
| 8 | per ogni IP 0..9: `ac_drm_query_hw_ip_info()` + `ac_drm_query_hw_ip_count()` | `drm_amdgpu_info_hw_ip` (`hw_ip_version_major/minor`, `ib_start_alignment`, `ib_size_alignment`, `available_rings`, `ip_discovery_version`) | `ac_fill_hw_ip_info` (r.492): GFX12 → `ib_alignment` forzato a 256 (stampato `align:256`), padding da `ac_ip_type_dw_padding_minus_1[]` (GFX/COMPUTE 0x7, SDMA 0xf) |
| 9 | `ac_drm_query_firmware_version(AMDGPU_INFO_FW_GFX_ME / MEC / PFP)` | version+feature | obbligatorie (errore se falliscono). Usate per workaround CP (es. `has_cp_dma`, gating di pacchetti) |
| 10 | `AMDGPU_INFO_FW_VCN` (se VCN presente) | 0x0910c01a → `vcn_dec_version 9`, `vcn_enc_major 1`, `vcn_enc_minor 12` | solo video |
| 11 | `ac_drm_query_sw_info(amdgpu_sw_info_address32_hi)` | 0xffff8000 | base del range VA 32-bit (descrittori, shader) |
| 12 | `ac_drm_query_info(AMDGPU_INFO_MEMORY)` | `drm_amdgpu_memory_info` {vram, cpu_accessible_vram, gtt} | `ac_fill_memory_info` |
| 13 | `ac_identify_chip()` | `family 0x98 = FAMILY_NV4` + `ip[GFX].ver_minor == 0` + `ASICREV_IS(external_rev, GFX1200)` | **Navi 44: external_rev ∈ [0x40,0x50) → CHIP_GFX1200; Navi 48: ≥0x50 → CHIP_GFX1201** (`addrlib/src/amdgpu_asic_addr.h:121-122`, `ac_gpu_info.c:766-771`). GC 12.1 → CHIP_GFX1210 |
| 14 | `ac_drm_get_marketing_name()` | "AMD Radeon RX 9060 XT" | libdrm `amdgpu.ids`; su Darwin stringa statica |
| 15 | `has_timeline_syncobj = sync_provider->timeline_wait != NULL` | | RADV usa timeline per tutte le sync |
| 16 | `ac_drm_query_has_vm_always_valid()` | drm_minor ≥ ... | abilita `AMDGPU_GEM_CREATE_VM_ALWAYS_VALID` (BO locali, fuori dalla BO list) |
| 17 | `ac_fill_hw_info/tiling/feature/bug/tess/compiler/video` | puro calcolo | v. 2.3 |
| 18 | `ac_drm_query_info(AMDGPU_INFO_MAX_IBS)` | GFX 192, COMPUTE 125, SDMA 49 | limite IB per CS |
| 19 | (solo userq) `ac_drm_query_uq_fw_area_info()` | shadow/CSA size | non usato da RADV |
| 20 | `ac_drm_query_sw_info(amdgpu_sw_info_address_prt_wa_control_bit)` | **nuovo, GFX10-12** (`has_smem_with_null_prt_bug`) | bit che separa VA "LOW"/"HIGH" per il workaround SMEM su pagine PRT NULL (r.1815-1826); calcolato da libdrm, non dal kernel. **Misurato: 46** (programma `scratchpad/mesa-radv/swinfo/swinfo.c`, libdrm 2.4.134) [VERIFICATO] |

### 2.2 Campi di `struct drm_amdgpu_info_device` effettivamente letti da Mesa [VERIFICATO]

Grep di `device_info->` in `ac_gpu_info.c` + `ac_linux_drm.c:677-750`:
`device_id`, `chip_rev`, `external_rev`, `pci_rev`, `family`, `num_shader_engines`, `num_shader_arrays_per_engine`,
`gpu_counter_freq`, `max_engine_clock`, `max_memory_clock`, `cu_active_number`, `cu_ao_mask`, `cu_bitmap[4][4]`,
`enabled_rb_pipes_mask`, `enabled_rb_pipes_mask_hi`, `num_rb_pipes`, `num_hw_gfx_contexts`, `ids_flags`,
`virtual_address_offset/max/alignment`, `high_va_offset/max`, `pte_fragment_size`, `gart_page_size`, `vram_type`,
`vram_bit_width`, `vce_harvest_config`, `wave_front_size`, `num_shader_visible_vgprs`, `num_cu_per_sh`,
`num_tcc_blocks`, `tcc_disabled_mask`, `pa_sc_tile_steering_override`, `tcp_cache_size`, `num_sqc_per_wgp`,
`sqc_data_cache_size`, `sqc_inst_cache_size`, `gl1c_cache_size`, `gl2c_cache_size`, `mall_size`, `pcie_gen`,
`pcie_num_lanes`, `userq_ip_mask`, `shadow_size/csa_size` (solo userq). **Non** letti su GFX12: `prim_buf_*`,
`pos_buf_*`, `param_buf_*`, `cntl_sb_buf_*` (erano per GFX11 "attribute ring" kernel-side; GFX12 alloca i ring in userspace), `ce_ram_size` (CE rimosso da GFX11).

Il kernel Linux li riempie in `amdgpu_kms.c` `amdgpu_info_ioctl()` case `AMDGPU_INFO_DEV_INFO` (≈ righe 930-1080 di
`research/src/linux/drivers/gpu/drm/amd/amdgpu/amdgpu_kms.c`); gran parte proviene da `adev->gfx.config` e
`adev->gfx.cu_info`, che a loro volta vengono dalla **IP discovery table** (`gc_info` v2: `gc_num_se`, `gc_num_cu_per_sh`,
`gc_num_rb_per_se`, `gc_num_tccs`, `gc_gl2c_per_gpu`, `gc_tcp_size_per_cu`, ...) e dai registri `CC_GC_SHADER_ARRAY_CONFIG`/
`GC_USER_SHADER_ARRAY_CONFIG` (harvest CU). Su Darwin il kext deve rifare questo parsing (o leggere `ip_discovery_table.bin`).

### 2.3 Valori derivati (calcolati in userspace, NON servono dal kernel) [VERIFICATO]

- `gfx_level = GFX12` da `hw_ip_version 12.0` (r.783-785). `rt_ip_version = RT_3_1` per GFX12 (r.928-929).
- `sdma_ip_version = SDMA_7_0` da HW_IP DMA 7.0.
- `num_physical_wave64_vgprs_per_simd = 768` hardcoded per GFX12 (r.290-292), `num_physical_sgprs_per_simd 1728`.
- `has_out_of_order_uncached_l2 = (gfx_level == GFX12)` (r.585): su GFX12 letture/scritture uncached allo stesso indirizzo possono riordinarsi → ACO aggiunge `s_wait` extra se la memoria UC è esposta.
- `tcc_cache_line_size = 256` su GFX12 (r.592), `tcc_rb_non_coherent = 0` (r.1234), `cp_sdma_ge_use_system_memory_scope = 1` (r.1237).
- `has_set_context_pairs/sh_pairs/uconfig_pairs = true` (r.1199-1202): GFX12 usa i pacchetti PM4 `SET_*_REG_PAIRS` (non packed) — v. §4.4.
- `has_clear_state = false` (GFX ≥ 11), `has_tc_compatible_htile = false` su GFX12 (r.1143), `has_db_force_stencil_valid_bug`, `has_vrs_export_bug` = GFX12 (r.996, 1036).
- `gfx12_supports_dcc_write_compress_disable = drm_minor >= 60` (r.1189).
- Ring NGG GFX12: `attribute_ring_size_per_se = 1400 KiB` (→ 1408 allineato 64K), `pos_ring = 16384*16`, `prim_ring = 16368*4` (r.1719-1760); commento "Navi48 results" — i valori sono tarati su Navi 48 e applicati identici a Navi 44.
- `se_tile_repeat = 32 * max_se`, `num_tile_pipes = 1 << NUM_PIPES(gb_addr_config)` = 32.
- Mask RB trimmate per SE disabilitati su GFX12 (r.1289-1296).

### 2.4 Cosa deve fare il winsys Darwin per ciascun gruppo

| Gruppo | Sorgente su Linux | Darwin: fonte proposta | Fake possibile? |
|---|---|---|---|
| Identità (device_id, external_rev 0x41, family 0x98, pci_rev) | PCI config + IP discovery | kext: PCI config space + `ip_discovery_table` | No: deve essere reale (external_rev decide CHIP_GFX1200) |
| Topologia SE/SA/CU/RB, cu_bitmap, harvest | `gfx.config`, `cu_info` | kext: IP discovery `gc_info` + registri harvest | Per Navi 44 full (32 CU, nessun harvest) si può hardcodare `{0xff,0xff}`; per SKU harvested (9060 non-XT?) servono i registri |
| GB_ADDR_CONFIG | MMIO GC | kext: `regGB_ADDR_CONFIG` = 0x13de nel segmento GC 0 (`gc_12_0_0_offset.h:7589`; base GC seg0 0x1260 → dword assoluto 0x263e, quello che Mesa chiede). Linux lo ha in allowlist `soc24.c:133` e lo restituisce dalla cache `gfx.config.gb_addr_config` (`soc24.c:143`, letto in `gfx_v12_0.c:3628`). Oppure costante 0x08200545 | Sì (costante per Navi 44 128-bit). Navi 48 (256-bit) ha valore diverso |
| Cache size, mall_size | IP discovery `gc_info` | kext o tabella statica | Sì |
| Clock (max sclk/mclk, gpu_counter_freq 100 MHz) | SMU/pptable | kext; gpu_counter_freq è fisso 100 MHz | Sì (solo per stime/statistiche); `gpu_counter_freq` deve essere corretto per i timestamp |
| VA layout (0x10000..2^47, high VA, address32_hi 0xffff8000) | VM manager | kext: deve **garantire** questo layout nel GPUVM della task | Valori sì, ma il kext deve onorarli |
| Memoria (vram/gtt/visible) | TTM | kext | Valori sì; GTT su macOS = memoria wired/IOMMU-mapped |
| FW version ME/PFP/MEC (+feature 29) | fw headers | kext: dalla versione dei blob caricati | Sì ma devono corrispondere al FW reale: Mesa usa `mec_fw_feature`/`pfp_fw_version` per gating |
| HW IP info (versione, rings, align) | `amdgpu_hw_ip_info` | kext | Sì |
| MAX_IBS | sched | statico | Sì |
| Sensori/timestamp | SMU, `RLC_GPU_CLOCK_COUNT` | kext | TIMESTAMP deve essere reale (query `vkGetCalibratedTimestamps`, `RADEON_TIMESTAMP`) |
| PCI bus info | drmGetDevice2 | IOKit `IOPCIDevice` location | Sì |
| marketing name | libdrm ids | stringa | Sì |

## 3. Interfaccia winsys: ioctl DRM_AMDGPU usati e semantica da preservare

### 3.1 Architettura a tre livelli (Mesa main, ottobre 2026) [VERIFICATO]

```
RADV core (radv_*.c)                      -> struct radeon_winsys (vtable, radv_radeon_winsys.h:226-328, 50 hook)
  winsys/amdgpu/radv_amdgpu_{winsys,bo,cs}.c  (3664 righe)  -> API ac_drm_* (59 funzioni MESAPROC, ac_linux_drm.h:338-457)
     common/ac_linux_drm.c (1129 righe)     -> libdrm_amdgpu (amdgpu.h) + ioctl DRM_AMDGPU_* diretti
     common/virtio/*.c (1606 righe)          -> virtio-gpu native context (AMDGPU_CCMD_*), alternativa a ioctl
  util_sync_provider (src/util/u_sync_provider.h, 15 callback) -> DRM_IOCTL_SYNCOBJ_* oppure vpipe
```

Conseguenze per Darwin:
1. `radeon_winsys` è l'unico confine tra RADV e il kernel *per BO/CS*; ma RADV chiama anche **direttamente**
   `ac_drm_*` in `radv_physical_device.c` (`ac_drm_device_initialize` r.3253, `radv_query_heap_info` →
   `ac_drm_query_heap_info`), `drmGetVersion`/`drmGetDeviceFromDevId`/`drmFreeDevice` (r.2611-2646, 3238), e
   `drm_ioctl_write(wsi_master_fd, DRM_AMDGPU_INFO, ACCEL_WORKING)` (r.~2715) per `VK_KHR_display`.
   File di RADV fuori da winsys che includono DRM: `radv_physical_device.c/.h`, `radv_image.c`, `radv_formats.c`
   (modifier DRM / `ac_drm_fourcc.h`), `radv_android.c`.
2. Il punto d'innesto più pulito è **sotto** `ac_drm_*`: Mesa ha già due backend (`amdgpu_device_handle` e
   `amdvgpu_device_handle` per virtio, union in `struct ac_drm_device`, `ac_linux_drm.c:21-31`). Un terzo backend
   `HAVE_AMDGPU_DARWIN` con `amddgpu_device_handle` che parla a un `IOUserClient` è l'approccio a patch minima: RADV,
   `radv_amdgpu_*`, `ac_gpu_info.c` restano intatti.
3. Su `_WIN32` tutte le `ac_drm_*` diventano stub `static inline { return -1; }` (`u_stub.h`, `__U_STUB__`). È il
   precedente upstream di "piattaforma senza DRM": lo stesso meccanismo può essere usato per compilare su Darwin
   senza libdrm e poi sostituire gli stub con l'implementazione IOKit.

### 3.2 Tabella completa `ac_drm_*` → ioctl Linux [VERIFICATO, `ac_linux_drm.c`]

| ac_drm_* | ioctl / libdrm | Note semantiche |
|---|---|---|
| `ac_drm_device_initialize` | `amdgpu_device_initialize` (→ `DRM_IOCTL_VERSION`, dedup per fd) | restituisce drm major/minor; crea `util_sync_provider_drm(fd)` |
| `ac_drm_device_get_fd/cookie/deinitialize/get_sync_provider` | — | cookie = identità device per condivisione BO tra istanze |
| `ac_drm_query_info` | `DRM_AMDGPU_INFO` (0x05) | subquery: `DEV_INFO 0x16`, `MEMORY 0x19`, `VRAM_GTT 0x14`, `MAX_IBS 0x22`, `TIMESTAMP 0x05`, `NUM_BYTES_MOVED 0x0f`, `NUM_EVICTIONS 0x18`, `NUM_VRAM_CPU_PAGE_FAULTS 0x1e`, `GPUVM_FAULT 0x23`, `ACCEL_WORKING 0x00`, `VIDEO_CAPS 0x21`, `UQ_FW_AREAS 0x24` |
| `ac_drm_query_hw_ip_info` / `_count` | `DRM_AMDGPU_INFO` `HW_IP_INFO 0x02` / `HW_IP_COUNT 0x03` | |
| `ac_drm_query_firmware_version` | `DRM_AMDGPU_INFO` `FW_VERSION 0x0e` + `fw_type` | ME/PFP/MEC/VCN obbligatori |
| `ac_drm_read_mm_registers` | `DRM_AMDGPU_INFO` `READ_MMR_REG 0x15` | solo GB_ADDR_CONFIG su GFX12 (+ `radv_amdgpu_winsys_read_registers` per debug/hang report) |
| `ac_drm_query_sensor_info` | `DRM_AMDGPU_INFO` `SENSOR 0x1d` | GFX_SCLK, GFX_MCLK, GPU_TEMP |
| `ac_drm_query_heap_info` | `INFO_VRAM_GTT` + `INFO_VRAM_USAGE/VIS_VRAM_USAGE/GTT_USAGE` | budget `VK_EXT_memory_budget` |
| `ac_drm_query_gpu_info` | `INFO_DEV_INFO` + `READ_MMR_REG(0x263e)` | riscritta in Mesa (non più libdrm) |
| `ac_drm_query_sw_info` | libdrm `amdgpu_query_sw_info` (userspace) | `address32_hi`, `address_prt_wa_control_bit` |
| `ac_drm_query_gpuvm_fault_info` | `INFO_GPUVM_FAULT` | per `VK_EXT_device_fault` |
| `ac_drm_query_video_caps_info` | `INFO_VIDEO_CAPS` | solo video |
| `ac_drm_bo_alloc` | libdrm `amdgpu_bo_alloc` → `DRM_AMDGPU_GEM_CREATE` (0x00) | v. 3.3 |
| `ac_drm_bo_free` | `amdgpu_bo_free` → `DRM_IOCTL_GEM_CLOSE` (+ munmap) | |
| `ac_drm_bo_cpu_map/unmap` | `amdgpu_bo_cpu_map` → `DRM_AMDGPU_GEM_MMAP` (0x01) + `mmap(fd, offset)` | refcount di mappatura in libdrm |
| `ac_drm_bo_export` | `amdgpu_bo_export` (KMS handle / flink / `DRM_IOCTL_PRIME_HANDLE_TO_FD`) | RADV usa `kms` handle per GEM_VA e BO list; `dma_buf_fd` per export |
| `ac_drm_bo_import` | `amdgpu_bo_import` (`DRM_IOCTL_PRIME_FD_TO_HANDLE`, `GEM_OPEN`) | |
| `ac_drm_create_bo_from_user_mem` | `amdgpu_create_bo_from_user_mem` → `DRM_AMDGPU_GEM_USERPTR` (0x11) | `VK_EXT_external_memory_host`; `has_userptr = !is_virtio` |
| `ac_drm_bo_set_metadata` | `DRM_AMDGPU_GEM_METADATA` (0x06) SET | tiling_info (64 bit, campi GFX12 v. §4.2) + 64 dword UMD metadata |
| `ac_drm_bo_query_info` | `GEM_METADATA` GET + `DRM_AMDGPU_GEM_OP` (0x10) `GET_GEM_CREATE_INFO` | usato su BO importati (dominio, flag, tiling) |
| `ac_drm_bo_wait_for_idle` | `DRM_AMDGPU_GEM_WAIT_IDLE` (0x07) | |
| `ac_drm_bo_va_op_raw` | `DRM_AMDGPU_GEM_VA` (0x08) | ops MAP/UNMAP/CLEAR/REPLACE |
| `ac_drm_bo_va_op_raw2` | `DRM_AMDGPU_GEM_VA` con `vm_timeline_syncobj_out`, `vm_timeline_point`, `input_fence_syncobj_handles` | VM update asincrono con fence su timeline syncobj |
| `ac_drm_va_range_alloc/free/query` | libdrm `amdgpu_va_range_*` (**allocatore VA interamente in userspace**) | il kernel non sceglie mai il VA |
| `ac_drm_cs_ctx_create2` / `_free` | `DRM_AMDGPU_CTX` (0x02) `ALLOC_CTX`/`FREE_CTX` con priority | priorità HIGH/REALTIME richiedono privilegi |
| `ac_drm_cs_query_reset_state2` | `DRM_AMDGPU_CTX` `QUERY_STATE2` | flag RESET/GUILTY/VRAMLOST → `VK_ERROR_DEVICE_LOST` |
| `ac_drm_cs_ctx_stable_pstate` | `DRM_AMDGPU_CTX` `SET/GET_STABLE_PSTATE` | profiling (SQTT), opzionale |
| `ac_drm_cs_submit_raw2` | `DRM_AMDGPU_CS` (0x04) | v. 3.4 |
| `ac_drm_cs_chunk_fence_info_to_data` | — | riempie `drm_amdgpu_cs_chunk_fence {handle, offset}` |
| `ac_drm_cs_query_fence_status` | `DRM_AMDGPU_WAIT_CS` (0x09) | attende seq_no su (ctx, ip, ring) |
| `ac_drm_cs_*syncobj*` (create2, destroy, wait, timeline_wait, query2, transfer, import, export/import_sync_file, export_sync_file2) | `util_sync_provider` → `DRM_IOCTL_SYNCOBJ_CREATE/DESTROY/WAIT/TIMELINE_WAIT/QUERY/TRANSFER/HANDLE_TO_FD/FD_TO_HANDLE/RESET/SIGNAL/TIMELINE_SIGNAL` | ioctl DRM core, non amdgpu |
| `ac_drm_vm_reserve_vmid/unreserve` | `DRM_AMDGPU_VM` (0x13) `RESERVE_VMID` | SQTT/RGP, opzionale |
| `ac_drm_create/free_userqueue`, `ac_drm_userq_signal/wait` | `DRM_AMDGPU_USERQ` (0x16), `USERQ_SIGNAL` (0x17), `USERQ_WAIT` (0x18) | **usati solo da radeonsi** (gallium); RADV non ha percorso userq (grep `userq` in `src/amd/vulkan`: 0 risultati) |
| `ac_drm_query_pci_bus_info` | `drmGetDevice2` (sysfs) | |
| `ac_drm_query_has_vm_always_valid` | check `drm_minor` | |
| `ac_drm_get_marketing_name` | libdrm `amdgpu.ids` | |

**Non usati da RADV**: `DRM_AMDGPU_BO_LIST` (0x03, sostituito dal chunk inline `BO_HANDLES`), `DRM_AMDGPU_WAIT_FENCES`
(0x12), `DRM_AMDGPU_FENCE_TO_HANDLE` (0x14; `has_fence_to_handle=true` in `ac_gpu_info.c` ma RADV usa syncobj
timeline), `DRM_AMDGPU_SCHED` (0x15), userq (0x16-0x18), `AMDGPU_CHUNK_ID_DEPENDENCIES` (0x03),
`AMDGPU_CHUNK_ID_CP_GFX_SHADOW` (0x0a).

### 3.3 BO: domini, flag e mapping RADV → kernel [VERIFICATO, `radv_amdgpu_bo.c:515-703`]

`radv_amdgpu_winsys_bo_create()`:
1. **Prima** alloca un VA: `ac_drm_va_range_alloc(amdgpu_gpu_va_range_general, size(+pad), virt_alignment, replay_address, flags = AMDGPU_VA_RANGE_HIGH | [AMDGPU_VA_RANGE_32_BIT se RADEON_FLAG_32BIT] | [AMDGPU_VA_RANGE_REPLAYABLE])`. RADV usa sempre il **range HIGH** (0xffff8000_00000000+) e il range 32-bit `address32_hi=0xffff8000` per descrittori/shader. Allineamento VA ottimale da `radv_amdgpu_get_optimal_vm_alignment` (r.774: frammenti 2 MiB = `pte_fragment_size`).
2. `amdgpu_bo_alloc_request {alloc_size, phys_alignment, preferred_heap, flags}`:
   - `RADEON_DOMAIN_VRAM` → `AMDGPU_GEM_DOMAIN_VRAM | AMDGPU_GEM_DOMAIN_GTT` (GTT aggiunto sempre, salvo `RADV_PERFTEST=nogttspill`, per rendere i BO "spillable": il kernel preferisce VRAM ma può spostarli in GTT sotto pressione, `radv_amdgpu_bo.c:565-585`) — **un kext senza eviction deve trattare questa combinazione come "VRAM preferita"**; `RADEON_DOMAIN_GTT` → `AMDGPU_GEM_DOMAIN_GTT`; `GDS`/`OA` (solo streamout NGG ≤ GFX11; GFX12 non usa GDS).
   - `RADEON_FLAG_CPU_ACCESS` → `AMDGPU_GEM_CREATE_CPU_ACCESS_REQUIRED` (1<<0); `NO_CPU_ACCESS` → (1<<1); `GTT_WC` → `CPU_GTT_USWC` (1<<2); assenza di `RADEON_FLAG_IMPLICIT_SYNC` → `EXPLICIT_SYNC` (1<<7); BO locali → `VM_ALWAYS_VALID` (1<<6); `DISCARDABLE` (1<<12); **`RADEON_FLAG_GFX12_ALLOW_DCC` → `AMDGPU_GEM_CREATE_GFX12_DCC` (1<<16)**, con assert `gfx_level >= GFX12 && VRAM && NO_CPU_ACCESS`; `ENCRYPTED` (1<<10, TMZ, non disponibile qui).
3. `ac_drm_bo_export(kms)` per ottenere il GEM handle, poi `GEM_VA MAP` con flag `AMDGPU_VM_PAGE_READABLE | EXECUTABLE | [WRITEABLE se !READ_ONLY] | [AMDGPU_VM_MTYPE_UC se RADEON_FLAG_GL2_BYPASS]` (r.33-80). Opzionale `RADEON_FLAG_VM_PAD_1PAGE`: mappa una pagina extra read-only dopo il BO.
4. BO list per submit = BO aggiunti al command stream (`cs_add_buffer`) + **global BO list** (`radv_amdgpu_global_bo_list_add`, r.315), che contiene i BO resi residenti con `buffer_make_resident` (r.1199-1222: le allocazioni `VkDeviceMemory` dell'app, necessarie per buffer device address) o tutti i BO con `RADV_DEBUG=allbos`; i BO "local" (`VM_ALWAYS_VALID`) non ci entrano perché il kernel li tiene sempre validi. Il tutto è inviato come `BO_HANDLES` (con `bo_priority`). Un kext senza eviction può ignorare la lista (Cobalt64 lo fa, §5.3).

Semantica kernel da riprodurre in Darwin [VERIFICATO in `gmc_v12_0.c:506-549`]:
- `AMDGPU_VM_MTYPE_DEFAULT` e `NC` → PTE `MTYPE_NC` (GFX12: campo `AMDGPU_PTE_MTYPE_GFX12` bit 54-55); `UC` → `MTYPE_UC`; BO `UNCACHED` → UC.
- `AMDGPU_VM_PAGE_PRT` → `AMDGPU_PTE_PRT_GFX12 | SNOOPED | SYSTEM | IS_PTE` e **VALID=0** (pagina "null": letture 0, scritture scartate) — usato per sparse (`radv_amdgpu_virtual_bo_init_mapping`, r.169).
- BO con `GFX12_DCC` → **`AMDGPU_PTE_DCC` (bit 58)** in ogni PTE: su GFX12 la compressione DCC è decisa dalla page table, non dal descrittore. Inoltre il kernel, quando sposta/evicta un BO DCC in VRAM, usa SDMA con `AMDGPU_COPY_FLAGS_READ_DECOMPRESSED`/`WRITE_COMPRESSED` + parametri presi dal tiling metadata (`amdgpu_ttm.c:354-370`): **un kext Darwin che fa eviction deve replicarlo o non evictare mai BO DCC**.
- `EXECUTABLE` → `AMDGPU_PTE_EXECUTABLE`; `NOALLOC` → `AMDGPU_PTE_NOALLOC` (bypass MALL).
- Workaround `has_smem_with_null_prt_bug` (GFX10-12, include gfx1200): per sparse con residency emulata RADV mappa la metà "LOW" del VA (bit `address_prt_wa_control_bit` azzerato) su un BO VRAM da 8 MiB di zeri (`radv_amdgpu_init_null_prt_bo`, r.406-434; `radv_amdgpu_virtual_bo_bind_low_null_prt`, r.143-166). Il kext deve quindi accettare **molte mappature dello stesso BO** a VA diversi.

### 3.4 Command submission [VERIFICATO, `radv_amdgpu_cs.c:1750-1905`]

`ac_drm_cs_submit_raw2(dev, ctx_id, bo_list_handle=0, num_chunks, chunks, &seq_no)` con chunk:
- N × `AMDGPU_CHUNK_ID_IB` (0x01): `drm_amdgpu_cs_chunk_ib {va_start, ib_bytes, ip_type, ip_instance, ring, flags}`; `va_start` allineato a `ib_alignment` (256 su GFX12); flag `AMDGPU_IB_FLAG_PREEMPT` (r.1137), `AMDGPU_IB_FLAGS_SECURE` (TMZ). Gli IB sono **IB1 nel VA dell'utente**; il kernel li lancia con `INDIRECT_BUFFER` dal proprio ring (con VMID dell'utente). IB2/chaining sono interni agli IB (RADV fa `cs_chain` via pacchetti `INDIRECT_BUFFER` con CHAIN=1; `can_chain_ib2=1`).
- **Gang submit**: IB con `ip_type` diversi nello stesso CS (es. COMPUTE/ACE per task shader + GFX); "l'ultimo CS è il gang leader" (r.1032, r.1105). Linux lo segnala con `AMDGPU_IDS_FLAGS_GANG_SUBMIT` (0x10, presente in `ids_flags=0x18`). Su Darwin: o lo si implementa (sottomissione atomica su 2 ring, con sincronizzazione), o si disabilitano task shader (`VK_EXT_mesh_shader` taskShader) [INFERITO].
- 0/1 × `AMDGPU_CHUNK_ID_FENCE` (0x02): user fence in un BO di RADV (`ctx->fence_bo`), offset `(ip_type*MAX_RINGS_PER_TYPE+ring)*4` QWORD; 4 QWORD: completed / preempted / reset / preempted-then-reset. Il kernel ci scrive il seq_no a fine IB (via `RELEASE_MEM`).
- 0/1 × `AMDGPU_CHUNK_ID_SYNCOBJ_TIMELINE_WAIT` (0x08) o `SYNCOBJ_IN` (0x04): `drm_amdgpu_cs_chunk_syncobj {handle, flags, point}`; flag `DRM_SYNCOBJ_WAIT_FLAGS_WAIT_FOR_SUBMIT` semantica "wait-before-signal".
- 0/1 × `AMDGPU_CHUNK_ID_SYNCOBJ_TIMELINE_SIGNAL` (0x09) o `SYNCOBJ_OUT` (0x05). RADV aggiunge sempre un `queue_syncobj` per coda per ordinare submit successivi.
- 1 × `AMDGPU_CHUNK_ID_BO_HANDLES` (0x06): `drm_amdgpu_bo_list_in {operation=~0, list_handle=~0, bo_number, bo_info_size=sizeof(drm_amdgpu_bo_list_entry), bo_info_ptr}`.
- Errori: `-ENOMEM` → retry ogni 1 ms per 1 s; `-ECANCELED` (contesto innocente perso), `-ENODATA` (soft recovery colpevole), `-ETIME` (hard recovery colpevole) → `VK_ERROR_DEVICE_LOST`.

### 3.5 Sincronizzazione: fence, timeline, implicit sync

- RADV implementa `VkSemaphore`/`VkFence` con `vk_drm_syncobj` (runtime Vulkan comune) sopra `util_sync_provider`; `pdev->syncobj_sync_type` viene da `winsys_info.syncobj_sync_type` (`radv_physical_device.c` ~r.2690). Timeline nativa (`has_timeline_syncobj=1`) → niente emulazione `vk_sync_timeline`.
- Il kernel deve offrire: oggetti syncobj con **payload dma_fence + timeline** (catena di punti), `WAIT` con `WAIT_ALL`/`WAIT_FOR_SUBMIT`/`WAIT_AVAILABLE`, `QUERY` (ultimo punto segnalato), `TRANSFER` (binary↔timeline), `SIGNAL/RESET`, export/import come fd (`handle_to_fd`) e **sync_file** (per WSI/external semaphore).
- Il percorso virtio (`vdrm_vpipe_get_sync`, `amdgpu_virtio_device.c:199-202`) dimostra che il sync provider **può essere implementato fuori dal DRM**: su Darwin un `util_sync_provider_darwin` può mappare syncobj su oggetti kernel del kext (fence seqno per ring + timeline in memoria condivisa + `IOUserClient` wait con timeout) senza fd.
- **Implicit sync**: tutti i BO interni hanno `EXPLICIT_SYNC`; solo BO WSI/esterni (`RADEON_FLAG_IMPLICIT_SYNC`) partecipano alla sincronizzazione implicita via `dma_resv`. Su macOS non c'è un compositor DRM che condivida BO: il WSI Darwin (CAMetalLayer/IOSurface) deve fare sync esplicita (attesa fence prima di presentare) → il kext **può ignorare l'implicit sync** [INFERITO].
- `RADEON_FLAG_VM_UPDATE_WAIT`: `GEM_VA` con `vm_timeline_syncobj_out` + wait (r.46-66). Senza, gli update VM sono "delayed" e completati dal kernel prima del prossimo CS sullo stesso VM: **il kext deve garantire che ogni CS veda tutti i MAP precedenti** (barriera VM implicita al submit).

### 3.6 Code esposte e ring kernel

- RADV usa: GFX ring 0 (`AMDGPU_HW_IP_GFX`, 1 ring), COMPUTE ring 0..3 (`available_rings 0xf`), SDMA solo con `RADV_EXPERIMENTAL=transfer_queue` o drirc (`radv_transfer_queue_enabled`, `radv_physical_device.c:110-124`), VCN/JPEG per video. La coda sparse binding non usa HW (solo `GEM_VA`).
- Con kernel queue (modello attuale) il kext deve gestire ring GFX/compute propri (o via MES `ADD_QUEUE` come Linux su GFX12, v. report bring-up/compute), inserire IB dell'utente con `INDIRECT_BUFFER` + `vmid`, fare VM flush e `RELEASE_MEM` fence → interrupt.
- I dati misurati confermano che su Linux 7.2.9 `userq_ip_mask=0`: user queue non attive per gfx1200 su questo kernel; RADV non le userebbe comunque.

### 3.7 Altre dipendenze Linux di RADV da sostituire su Darwin

- Enumerazione: `vk_instance` → `try_create_for_drm = create_drm_physical_device` (`radv_instance.c:322`), basata su `drmGetDevices2`; su Darwin serve un `enumerate` custom (IOServiceMatching del kext).
- `VK_EXT_physical_device_drm` (`drmPrimaryMajor/Minor` da `stat()` dei nodi, r.2481-2489): disattivare.
- `VK_KHR_display`/`VK_EXT_acquire_drm_display` (`wsi_master_fd`): disattivare.
- `VK_KHR_external_memory_fd`, `VK_EXT_external_memory_dma_buf`, `VK_EXT_image_drm_format_modifier`, `VK_KHR_external_semaphore_fd`/`fence_fd`: sostituire con `VK_EXT_metal_objects` / IOSurface (export) oppure disattivare nella prima fase.
- `VK_EXT_external_memory_host` (userptr): richiede `GEM_USERPTR` equivalente (wiring di pagine utente via `IOMemoryDescriptor::withAddressRange` + `prepare()`); opzionale.
- WSI: `src/vulkan/wsi/wsi_common_metal.c` + `wsi_common_metal_layer.m` esistono upstream [VERIFICATO con `git ls-tree`] (`VK_EXT_metal_surface` su `CAMetalLayer`, usato da KosmicKrisp), richiede copia o import di immagini in IOSurface; per RADV serve un percorso "blit to IOSurface-backed BO" (v. §5 per come lo fa Cobalt64).

## 4. Funzionalità specifiche gfx12 in RADV/ACO/addrlib

### 4.1 Navi 44 vs Navi 48 in Mesa: praticamente nessun codice specifico [VERIFICATO]

`grep CHIP_GFX1200|CHIP_GFX1201` in `src/amd` (escluso `amd_family.h`) dà solo: `amd_family.c:198-201` (nome LLVM
"gfx1200"/"gfx1201"), `amdgpu_devices.c:2576` (canned device solo gfx1201), test ACO che usano GFX1201. Le
differenze reali tra le due GPU in RADV derivano **solo da `radeon_info`** (num_se 2 vs 4, CU 32 vs 64, RB 8 vs 16,
bus 128 vs 256 bit, MALL 32 vs 64 MiB, `num_tcc_blocks` 16 vs 32 [INFERITO per Navi 48], GB_ADDR_CONFIG). Unica
condizione per revisione: `ac_surface.c:3719` disabilita HiZ se `gfx_level == GFX12 && chip_rev == 0` (silicio A0);
la nostra scheda ha `chip_rev = 1` → HiZ attivo.

ISA: `llvm-mc -mcpu=gfx1200` e `-mcpu=gfx1201` producono **encoding identici** per tutte le 19 istruzioni GFX12
di prova (file `scratchpad/mesa-radv/isa/enc_gfx120{0,1}.txt`, `diff` vuoto) [VERIFICATO, LLVM 23.1.1]. Shader ACO
compilati per una delle due GPU girano sull'altra.

### 4.2 Swizzle mode e addrlib GFX12 [VERIFICATO]

- Enum `Addr3SwizzleMode` (`addrlib/inc/addrtypes.h:285-296`): `ADDR3_LINEAR=0`, `ADDR3_256B_2D=1`, `ADDR3_4KB_2D=2`,
  `ADDR3_64KB_2D=3`, `ADDR3_256KB_2D=4`, `ADDR3_4KB_3D=5`, `ADDR3_64KB_3D=6`, `ADDR3_256KB_3D=7`. Spariscono i modi
  `_S/_D/_R/_X/_T` di GFX9-11: un solo layout "2D" e uno "3D" per dimensione di blocco. Nuovo blocco 256 KiB
  (`max_alignment = 262144`).
- `Gfx12Lib::HwlInitGlobalParams()` (`addrlib/src/gfx12/gfx12addrlib.cpp:1213-1220`) **non legge GB_ADDR_CONFIG**:
  inizializza solo tabelle di equazioni fisse (`gfx12SwizzlePattern.h`, 279 righe); `PipeInterleaveLog2 = 8` è una
  costante (`addrlib/src/core/addrlib3.h:165`). Conseguenza: il layout tiled è **indipendente dal numero di pipe**,
  quindi identico su Navi 44 e Navi 48; GB_ADDR_CONFIG serve solo a `num_tile_pipes` (usato in
  `radv_cmd_buffer.c:4876` `WALK_FENCE_SIZE` e nei path GFX9-11). Il PipeBankXor si applica solo a 4K/64K/256K.
- `ac_surface.c`: `gfx12_select_swizzle_mode()` (r.3423) chiama `Addr3GetPossibleSwizzleModes`; `gfx12_compute_surface()`
  (r.3896), `gfx12_compute_miptree()` (r.3773), `gfx12_compute_hiz_info()` (r.3712: HiZ/HiS sostituiscono HTILE).
- Tiling flags kernel GFX12 (`amdgpu_drm.h:672-688`): `SWIZZLE_MODE` 3 bit, `DCC_MAX_COMPRESSED_BLOCK` 2 bit
  (0:64B,1:128B,2:256B), `DCC_NUMBER_TYPE` 3 bit, `DCC_DATA_FORMAT` 6 bit, `DCC_WRITE_COMPRESS_DISABLE` bit 14,
  `SCANOUT` bit 63. Sono metadati per il kernel/display (e per la ricompressione SDMA durante i move), non per la GPU.
- Modifier DRM GFX12 (`ac_surface.c:940-960`): `AMD_FMT_MOD_TILE_VER_GFX12` con `TILE_GFX12_{256B,4K,64K,256K}_2D` +
  `DCC_MAX_COMPRESSED_BLOCK`; elenco misurato in §1.2.

### 4.3 DCC su GFX12: compressione "trasparente" decisa dalla page table [VERIFICATO]

Commento chiave in `common/ac_descriptors.c:707-723`: su GFX12 `COMPRESSION_ENABLED = PTE.D && COMPRESSION_EN` per
shader/CB/DB/SC; il Central Hub (CP, SDMA, index fetch) ignora PTE.D. **Il buffer DCC/HTILE non è più allocato da
userspace**: la storage dei metadati è nascosta (gestita dal memory controller). Quindi:
1. `radv_device_memory.c:160-176`: allocazioni VRAM `NO_CPU_ACCESS` ricevono `RADEON_FLAG_GFX12_ALLOW_DCC` se
   `gfx12_supports_dcc_write_compress_disable` (drm ≥ 3.60) e DCC non disabilitato (`radv_is_dcc_disabled`).
2. Winsys → `AMDGPU_GEM_CREATE_GFX12_DCC` → kernel mette `AMDGPU_PTE_DCC` (bit 58) su ogni PTE del BO
   (`gmc_v12_0.c:544-545`).
3. Descrittori immagine: `S_00A018_COMPRESSION_EN(1) | S_00A018_WRITE_COMPRESS_ENABLE(...)` (`ac_descriptors.c:726`);
   buffer: `S_008F28_COMPRESSION_EN(1)` (r.289, 780).
4. Per le allocazioni dedicate a un'immagine RADV imposta il metadata BO (tiling flags DCC) perché "the kernel requires a
   DCC view for recompression" (`radv_device_memory.c:201-210`): VRAM→GTT decomprime, GTT→VRAM ricomprime con SDMA
   (`SDMA_7_0_DCC_*`, `sid.h:426-433`: `READ_CM` 2 = decompress se PTE.D, `WRITE_CM` 1 = write compressed se PTE.D).
5. `gfx12_enable_dcc` per superfici (`ac_surface.c:3982-3989`): sempre per Z/S e MSAA, e per color non lineari;
   `max_compressed_block_size = 256B` (128B se scanout e drm < 3.63, r.4004-4015).

**Implicazioni per il kext Darwin**: (a) deve supportare il bit PTE DCC per-BO; (b) l'eviction VRAM→sistema di BO DCC
deve decomprimere (SDMA con `READ_CM=2`) o essere vietata (pinning); (c) l'inizializzazione della "compression
metadata" nascosta è lavoro GMC/MMHUB kernel (da approfondire nel report bring-up); (d) in un primo stadio si può
disabilitare DCC lato RADV (`RADV_DEBUG=nodcc` → `radv_is_dcc_disabled`) e non implementare nulla di questo, al costo di
banda [INFERITO: perdita di prestazioni stimata significativa su un bus a 128 bit].

### 4.4 Differenze PM4 su GFX12 [VERIFICATO, `common/sid.h`, `ac_cmdbuf*.c`]

| Aspetto | GFX12 (gfx1200) | Riferimento |
|---|---|---|
| Set registri | `PKT3_SET_CONTEXT_REG_PAIRS 0xB8`, `PKT3_SET_SH_REG_PAIRS 0xBA`, **`PKT3_SET_UCONFIG_REG_PAIRS 0xBE` (GFX12+)**; le varianti `_PACKED` (0xB9, 0xBB, 0xBD) "don't exist on GFX12" | `sid.h:245-271`, `ac_gpu_info.c:1199-1202` |
| Dispatch | nuovi `PKT3_DISPATCH_DIRECT_INTERLEAVED 0xA7`, `PKT3_DISPATCH_INDIRECT_INTERLEAVED 0xA8` | `sid.h:229-230` |
| HiZ | `PKT3_UPDATE_DB_SUMMARIZER_TIMEOUT 0xEF` (GFX12+), emesso **solo se `pfp_fw_version >= 2680`** (workaround hang HiZ) | `sid.h:297`, `ac_cmdbuf_cp.c:328-337` |
| CLEAR_STATE | assente (`has_clear_state = false` per GFX ≥ 11): RADV emette un preamble completo | `ac_gpu_info.c:1129`, `gfx12_init_graphics_preamble_state` (`ac_cmdbuf.c:629`) |
| Shadowing registri FW | `has_kernelq_reg_shadowing = 0` (serve `AMDGPU_IDS_FLAGS_PREEMPTION`); niente `CP_GFX_SHADOW` chunk | `ac_gpu_info.c:1195` |
| Cache flush | `RELEASE_MEM` con GCR ops anche su `PS_DONE`/`CS_DONE` (solo GFX12+); campi `GLM_WB/GLM_INV/GL1_INV` rimossi dal GCR_CNTL GFX12 | `ac_cmdbuf_cp.c:195-220, 479-481` |
| Ring NGG in memoria utente | `GE_POS_RING_BASE`/`GE_PRIM_RING_BASE` (`R_0309A0..0309AC`, UCONFIG) + attribute ring (`0x1544D`/`R_03111C`) programmati **dall'IB utente** con scope/temporal hint GFX12 | `ac_cmdbuf_cp.c:300-326` |
| SQ events | `R_031120_SPI_SQG_EVENT_CTL` sostituisce `SPI_CONFIG_CNTL` | `ac_cmdbuf_cp.c:625-640` |
| Memory temporal hints | `DB_MEM_TEMPORAL`, `SC_MEM_TEMPORAL`, `SC_MEM_SPEC_READ`, `DB_GL1_INTERFACE_CONTROL` nel preamble | `ac_cmdbuf.c:629+` |
| Scratch | `has_scratch_base_registers = 1`: base scratch scritta via registri (`COMPUTE_TMPRING_SIZE`, `SPI_GFX_SCRATCH_BASE_LO/HI`) dall'IB utente | RADV info |
| SDMA 7.0 | DCC-aware copy (`SDMA_7_0_DCC_*`) | `sid.h:426-433`, `ac_cmdbuf_sdma.c` |

Conseguenza per il kernel Darwin: RADV scrive da IB utente registri UCONFIG/SH/CONTEXT (incluso il setup ring NGG):
il CP deve eseguire gli IB utente con i permessi standard di una kernel queue amdgpu. Il kext deve solo
programmare lo stato per-VMID privilegiato (`SH_MEM_CONFIG`, `SH_MEM_BASES`, aperture, `GRBM_GFX_INDEX`, golden
settings) come fa `gfx_v12_0.c`/MES [INFERITO dalla divisione dei compiti; dettagli nel report bring-up].

### 4.5 ISA GFX12 gestita da ACO [VERIFICATO: codice ACO + llvm-mc]

| Cambiamento | ACO | Verifica llvm-mc gfx1200 |
|---|---|---|
| Contatori di attesa separati: `s_wait_loadcnt/storecnt/samplecnt/bvhcnt/expcnt/dscnt/kmcnt` + combinati `s_wait_loadcnt_dscnt`, `s_wait_storecnt_dscnt` (sostituiscono `s_waitcnt vmcnt/lgkmcnt`) | `aco_opcodes.py:809-817`; eventi `event_vmem_sample`, `event_vmem_bvh` (`aco_insert_waitcnt.cpp:58-59`); limiti `sample=63, bvh=7, km=31` (`aco_ir.cpp:1490-1492`) | `s_wait_loadcnt 0x0` → `[0x00,0x00,0xc0,0xbf]`, `s_wait_bvhcnt` → `0xc3bf` |
| Niente ordinamento in-order VMEM: `mem_ordered = gfx10..11 only` | `aco_insert_waitcnt.cpp:674`, 417-439 | — |
| `s_wait_alu` (dipendenze ALU, ex `s_delay_alu`/VA_VDST) | `aco_insert_NOPs.cpp:1480-1490, 1851` | `s_wait_alu 0xfffe` → `0x88bf` |
| Nuovi encoding VMEM: VBUFFER/VIMAGE/VSAMPLE (MUBUF/MTBUF/MIMG riformattati) | `emit_mubuf_instruction_gfx12`, `emit_mtbuf_instruction_gfx12`, `emit_mimg_instruction_gfx12` (`aco_assembler.cpp:1368-1391`) | `buffer_load_b32 ... offset:8388607` (offset 23 bit) |
| Cache policy: `scope:SCOPE_{CU,SE,DEV,SYS}` + `th:TH_*` sostituiscono GLC/SLC/DLC | `aco_assembler.cpp:280-284, 545` | `global_load_b32 ... th:TH_LOAD_NT scope:SCOPE_SYS` |
| Offset immediati 24 bit (buffer/SMEM `0x7fffff`, scratch/global ±8 MiB) | `aco_ir.cpp:126-150` | sì |
| NSA max 3 VGPR extra (VSAMPLE) | `aco_ir.cpp:155-157` | — |
| Barriere split: `s_barrier_signal`, `s_barrier_signal_isfirst`, `s_barrier_wait` | `aco_opcodes.py:692-693, 807`; `aco_lower_to_hw_instr.cpp:2969` | `s_barrier_signal -1` → `[0xc1,0x4e,0x80,0xbe]` |
| Prefetch `s_prefetch_inst/data(_pc_rel)` | `aco_opcodes.py:922-926` | sì |
| FP64 VOP2 nativi (`v_add_f64`, `v_mul_f64`, `v_min/max_f64` invece delle forme e64) | `aco_lower_to_hw_instr.cpp:317-324` | — |
| WMMA GFX12 (input non duplicati), SWMMAC (sparse), FP8/BF8 (`v_cvt_pk_fp8_f32`, `v_cvt_f32_fp8`) → `VK_KHR_cooperative_matrix`, `VK_EXT_shader_float8`, bfloat16 | `aco_opcodes.py:1124, 1261-1271, 1476` | `v_wmma_f32_16x16x16_f16`, `v_swmmac_f32_16x16x32_f16`, `v_cvt_pk_fp8_f32` OK |
| `v_permlane16_var_b32`, `s_sleep_var`, `global_load_tr_b64/b128` | `aco_opcodes.py:698, 1474, 2044-2045` | `global_load_tr_b128` OK |
| Export/LDSDIR, VGPR file 1.5x (768 wave64 VGPR/SIMD) | `aco_insert_NOPs.cpp:1446`, `ac_gpu_info.c:290` | — |

Nessuna di queste differenze tocca il kernel: sono interamente in ACO. L'unico requisito kernel è che il **trap handler**
(opzionale, `has_trap_handler_support = false` tranne GFX8) e il setup `SH_MEM_CONFIG` siano compatibili con ACO.

### 4.6 Ray tracing: BVH8 su GFX12 [VERIFICATO]

- `rt_ip_version = RT_3_1` per GFX12 (`ac_gpu_info.c:928`). `radv_use_bvh8()` = `gfx_level >= GFX12 && !emulate_rt && !RADV_DEBUG=bvh4` (`radv_physical_device.c:282-286`).
- Nodi: `struct radv_gfx12_box_node` (8 figli, compressi, `internal_base_id`, `primitive_base_id`, `parent_id`, ...), `radv_gfx12_instance_node` (`wto_matrix`, `pointer_flags_bvh_addr`), `radv_gfx12_primitive_node` (32 dword, triangoli compressi) — `bvh/bvh_defines.h:156-193`. Allineamento 128 B (`radv_acceleration_structure.c:155`).
- Build: shader `bvh/encode_gfx12.comp`, `encode_triangles_gfx12.comp`, `update_gfx12.comp`; traversal `nir/radv_nir_rt_common.c`; RRA dump `tools/radv_rra_gfx12.c`.
- ISA: `image_bvh8_intersect_ray` (gfx12 op 0x81), `image_bvh_dual_intersect_ray` (0x80), `ds_bvh_stack_push8_pop1_rtn_b32` (0xe1), `ds_bvh_stack_push8_pop2_rtn_b64` (0xe2) (`aco_opcodes.py:1676-1678, 1914-1915`). llvm-mc: `image_bvh8_intersect_ray v[0:9], [v[10:11], v[12:13], v[14:16], v[17:19], v20], s[0:3]` → `[0x10,0x40,0xe0,0xd3,...]`; `ds_bvh_stack_push8_pop2_rtn_b64` → `[0x00,0x00,0x88,0xdb,...]`.
- Requisiti kernel: nessuno oltre a compute queue e memoria; RT pipeline usa solo compute shader + BDA.

### 4.7 Mesh/task shader su GFX12 [VERIFICATO]

- `radv_taskmesh_enabled()` (`radv_physical_device.c:67-76`): richiede NGG, ACO, `gfx_level >= GFX10_3`, **compute queue abilitata** e nessun `has_taskmesh_indirect0_bug`. Limiti misurati: `maxMeshWorkGroupInvocations 256`, `maxTaskWorkGroupInvocations 1024`, `maxMeshOutputVertices 256`.
- I task shader girano sull'ACE (compute ring) e sono sincronizzati con la GFX ring tramite **gang submit** (CS con IB di ip_type diversi, §3.4) e un task ring in memoria (`ac_get_task_info`, `ac_gpu_info.c:2550`).
- Su GFX12 l'output NGG/mesh usa attribute ring + pos/prim ring in memoria (1408 KiB + 256 KiB + 64 KiB per SE) programmati dall'IB utente (§4.4).
- Requisito kernel Darwin: gang submit atomico GFX+COMPUTE, altrimenti spegnere `taskShader` (mesh shader senza task funziona solo su GFX ring) [INFERITO].

## 5. Cobalt64 e 7000-macos: le mesa-patches Darwin

Fonte: `research/refs/Cobalt64/mesa-patches/` (9 patch) e `research/refs/7000-macos/mesa-patches/` (5 patch). Codice di
terzi NON fidato, solo letto. Base dichiarata: mesa `f5cb8ee032adabef599ae892ec4e42d796b84da9` (26.3.0-devel), quindi
quasi coincidente con il nostro clone (`745709a0`, 11 ottobre 2026) [VERIFICATO in README.txt delle patch].

### 5.1 Relazione tra i due progetti [VERIFICATO]

`diff` delle patch 0001-0005: 7000-macos è **identico byte per byte** a Cobalt64 a parte numerazione "N/5" vs "N/9",
righe `Co-Authored-By` e 2 commenti che citano una nota di design interna. 7000-macos (fork per RX 7000) non ha alcun
adattamento Mesa per gfx11: il suo README dichiara RDNA3 "In progress ... Only the detection stage exists so far"
(`7000-macos/README.txt:39-47`). Quindi esiste **un solo port RADV-Darwin reale**, quello di Cobalt64, pensato per
Navi 48 (gfx1201).

### 5.2 Dimensione [VERIFICATO, conteggio delle righe `+`]

74 modifiche a file, **+8205 / −276** righe in totale:

| Categoria | Righe + |
|---|---:|
| Backend Darwin (`src/amd/common/darwin/ac_darwin_{drm,iokit,kext,sync,budget}`) | 2900 |
| `include/darwin/amdgpu.h` (header libdrm_amdgpu copiato verbatim) | 2102 |
| Mock in-process del kext + test host | 1381 |
| `include/darwin/navi48_native_abi.h` (copia dell'header del kext, cresciuto da 1.0 a 1.11) | 586 |
| VA manager di libdrm vendorizzato (`amdgpu_vamgr.c`, `amdgpu_vamgr_internal.h`, `libdrm_util_double_list.h`) | 565 |
| **Modifiche a file upstream RADV/ac** | **534** |
| Build/include/altro | 137 |

Cioè: il codice "vero" scritto per il port è ~3.0 k righe di backend + ~0.5 k di modifiche a Mesa; il resto è
vendoring, header ABI e test.

### 5.3 Patch per patch

**0001 — "radv: Darwin (macOS) backend with canned gfx1201 device info (Navi48 S1a)"** (22 file, +3783/−35)
- `meson.build`: `with_amdgpu_darwin = with_amd_vk and host_machine.system() == 'darwin'`; `-DHAVE_TSERVER` (addrlib
  `addrtypes.h` include un header solo-Apple `addrExtDef.h` su `__APPLE__`); esclude libdrm dai check per RADV.
- `include/meson.build`: aggiunge `include/darwin` (header sostitutivi `xf86drm.h` 54 righe con `drmIoctl` → -1,
  `drmGetCap` → -EINVAL; `libsync.h` con `sync_wait/merge` → -ENOSYS; `amdgpu.h` di libdrm verbatim).
- `src/amd/common/ac_linux_drm.c` (+170): campo `acd_device_handle ddev` + `bool is_darwin` nella union di
  `struct ac_drm_device`; wrapper `ac_drm_ioctl_write/_write_read()` che su Darwin chiamano
  `acd_ioctl(dev->ddev, DRM_AMDGPU_*, data, size)` invece di `drm_ioctl_*`; `ac_drm_device_initialize` ignora fd/is_virtio
  e chiama `acd_device_initialize()`; tutte le funzioni libdrm (`amdgpu_bo_alloc`, `amdgpu_va_range_alloc`, ...) dirottate
  su `acd_*`. **È esattamente il "terzo backend sotto ac_drm" proposto in §3.1**.
- `src/amd/common/darwin/ac_darwin_drm.{c,h}`: emula le ioctl `DRM_AMDGPU_*` (S1a: info dal canned `gfx1201` di
  `amdgpu_devices.c`, `CTX` solo userspace, kernel stub `-ENODEV`).
- `ac_darwin_sync.c`: `util_sync_provider` interamente userspace (binary + timeline, niente sync_file).
- `amdgpu_vamgr.c`: allocatore VA di libdrm vendorizzato (il kernel non sceglie mai i VA).
- `ac_gpu_info.c` (+4): `has_userptr = false` su Darwin.
- `radv_instance.c` (+3): `instance->vk.physical_devices.enumerate = radv_darwin_enumerate_physical_devices`.
- `radv_physical_device.c` (+50): nuovo `RADV_DRM_DEVICE_AMDGPU_DARWIN` (fd sempre −1), path fittizio "darwin",
  enumerazione con `drmDevice` finto **PCI 1002:7550 rev 0xC0** (RX 9070 XT) e niente nodi DRM; disattiva il blocco
  `wsi_master_fd`/`VK_KHR_display`.
- `radv_amdgpu_bo.c` (+11): `bo_map` sempre via `ac_drm_bo_cpu_map` (niente mmap su fd).
- `radv_amdgpu_winsys.c`: `syncobj_sync_type = vk_drm_syncobj_get_type_from_provider(provider)` (no fd DRM).
- `src/vulkan/runtime/meson.build`: compila `vk_drm_syncobj.c` anche senza libdrm. Link `-Wl,-undefined,dynamic_lookup`
  come KosmicKrisp.

**0002 — "radv: Darwin native backend, Mesa half of the Navi48 kext ABI (S1c)"** (14 file, +2946/−187)
- `ac_darwin_iokit.c`: `IOServiceOpen(Navi48Bringup, task, 'N48N'=0x4E34384E, &conn)` + `HELLO`; trasporto
  `IOConnectCallMethod` (≤16 scalari, struct ≤4096 B inline) e `IOConnectMapMemory64(conn, memoryType = BO handle)`.
- `ac_darwin_kext.{c,h}`: marshaller con `_Static_assert` che **ogni struct N48N è layout-identica al gemello DRM**
  (`n48n_gem_create_in` = `drm_amdgpu_gem_create_in` 32 B, `n48n_gem_va` = `drm_amdgpu_gem_va` 64 B, `n48n_ctx` =
  `union drm_amdgpu_ctx` 16 B, `n48n_cs_ib` = `drm_amdgpu_cs_chunk_ib` 32 B) e che le costanti valgono come in
  `amdgpu_drm.h`.
- ABI 1.0 = **9 selettori**: `HELLO 0`, `QUERYINFO 1` (`struct n48n_info` 192 B: gb_addr_config, gc_version, VRAM visibile/
  "hi pool", GTT, page-table, seq emitted/retired, VA low/high), `READREGS 2`, `BOCREATE 3`, `BOFREE 4`, `GEMVA 5`,
  `CTX 6`, `SUBMIT 7` (`n48n_cs_in` 32 B + 32 B×IB, max 64 IB, fence opzionale), `WAITSEQ 8` (attesa seqno con cap 2 s).
- `acd_cmd_cs()`: classifica i chunk in userspace (`acd_cs_plan_init`): IB → array, `FENCE` → handle/offset,
  `BO_HANDLES`/`DEPENDENCIES` **ignorati** ("one ring, always-valid": niente eviction, tutti i BO sempre mappati),
  `SYNCOBJ_IN`/`TIMELINE_WAIT` → attesa CPU se il punto non è ancora sottomesso (dipendenze dello stesso client sono già
  ordinate sull'unico ring), `SYNCOBJ_OUT`/`TIMELINE_SIGNAL` → il seqno restituito viene "attaccato" al (handle, point);
  `CP_GFX_SHADOW` → `-EINVAL`. >64 IB divisi in più submit con fence sull'ultimo.
- Limiti del kext S1c (dall'header): IB solo `ip_type == GFX`, ring 0 (il mock rifiuta altro); `VA_OP_CLEAR/REPLACE` e
  `VM_PAGE_PRT` **Unsupported** (→ niente sparse/PRT, e il workaround null-PRT GFX12 non funziona); `GFX12_DCC` **"ignored: no
  DCC PTE bit in S1c"**; `ENCRYPTED/CP_MQD/PREEMPTIBLE` rifiutati; timeline syncobj nel `GEM_VA` gestiti da Mesa (MAP/UNMAP
  sono sincroni nel kext, il punto viene segnalato subito).
- Errori: `Timeout → -ETIME`, `Aborted → -ECANCELED` (mappatura alla semantica `radv_amdgpu_cs_submit`).
- `ac_darwin_sync.c` riscritto: payload segnalato dalla CPU o da un seqno del kext; "WAIT_FOR_SUBMIT" emulato bloccando
  finché un submit non attacca il punto; poll a fette di 20 ms (`ACD_SYNC_POLL_NS`); i clone condividono lo spazio handle.
- `ac_darwin_mock.c` (600 righe) + `test/acd_kext_test.c`: `RADV_DARWIN_MOCK=1` esegue i selettori in-process per test
  end-to-end su host senza GPU.
- `radv_amdgpu_bo.c`: `size = align64(size, 4096)` invece di `getpagesize()` (16 KiB su Apple Silicon nel mock arm64).

**0003 — "radv: Darwin scanout API on the N48N connection, ABI 1.1 (Navi48 S2b)"** (+639): selettori 9..14
`SCAN_QUERY/ACQUIRE/REGISTER/PRESENT/STATUS/RELEASE` ed export di `radv_darwin_scanout_*` da `libvulkan_radeon`
(VkDevice/VkDeviceMemory → BO handle) per presentare sull'unica connessione per processo; il mock simula 60 Hz.
Selettori successivi del kext visibili nell'header: `DAL_STEP 15`, `MODE_TRIAL 16`, `MODE_HOLD 17`, `MODE_RELEASE 18`,
`METAL_NUB_WITHDRAW 20`.

**0004 — "darwin: host-pointer import (userptr) via N48N BoImportHost"** (+420): selettore `BO_IMPORT_HOST 21`
(VA host 4 KiB-allineato nello spazio del chiamante, 1 pagina..64 MiB, flag VM opzionali); `ac_drm_darwin_has_userptr()`
nuova in `ac_linux_drm.h` e `ac_query_gpu_info` setta `has_userptr` se ABI ≥ 1.9 → `VK_EXT_external_memory_host` e
`newBufferWithBytesNoCopy` lato Metal.

**0005 — "radv/amdgpu: cs_grow failure paths return instead of writing before the IB"** (+51/−3,
`radv_amdgpu_cs.c`): bugfix generico (scrittura a `buf[cdw-4]` con cdw=0 su fallimento di allocazione/map IB;
osservato come SEGV di WindowServer). Upstreamabile indipendentemente.

**0006 — "report the kext's per-session VRAM budget (ABI 1.10) as the app's VRAM heap"** (+160): `ac_darwin_budget.h`;
`AMDGPU_INFO_MEMORY`/`VRAM_USAGE` riportano il budget per sessione → `VkPhysicalDeviceMemoryProperties` heap VRAM per
processo.

**0007 — "take GB_ADDR_CONFIG from QueryInfo"** (+10/−6): `READREGS` è root-only e rifiutato per sessioni app
sandboxed; GB_ADDR_CONFIG preso da `n48n_info.gb_addr_config`, `READREGS` solo come fallback se 0. Stampa un warning se il
valore vivo ≠ canned gfx1201.

**0008 — "radv_darwin_set_service_class"** (+80): scelta del servizio IOKit (`Navi48Bringup` di default o
`Navi48Accelerator` per app sandboxed attraverso la connessione IOAccelerator).

**0009 — "radv_darwin_n48n_call (selectors 22..26) + radv_darwin_n48n_bo_handle"** (+116): scanout del secondo monitor
(`SCANX_ACQUIRE 22`, `SCANX_REGISTER 23`, `SCANX_PRESENT 24`, `SCANX_STATUS 25`, `SCANX_RELEASE 26`), ABI 1.11.

### 5.4 Cosa riusare e cosa cambiare per Navi 44 [VERIFICATO sui sorgenti + INFERITO dove indicato]

1. **Info device**: Cobalt64 risponde a `AMDGPU_INFO_DEV_INFO`, `HW_IP_INFO`, `FW_VERSION` dal canned `gfx1201`
   (`find_canned("gfx1201")`), con solo memoria e GB_ADDR_CONFIG presi dal kext. Su Navi 44 questo darebbe
   `external_rev ≥ 0x50` (CHIP_GFX1201), 4 SE/64 CU/16 RB, device_id 0x7550: **sbagliato** (CU mask e RB mask errate →
   hang o corruzioni nei dispatch con CU inesistenti; `num_se` errato → ring per-SE dimensionati male). Serve o un canned
   `gfx1200` (il nostro `gfx1200_canned_dump.txt` è già nel formato giusto) o, meglio, un selettore kext che restituisca
   `drm_amdgpu_info_device` + `hw_ip` + `fw` reali [INFERITO].
2. **Single GFX ring**: niente compute queue né SDMA; con il canned gfx1201 RADV esporrebbe 4 code compute i cui IB il
   kext rifiuta. Per Navi 44 si dovrà o mettere `available_rings=0` per COMPUTE (perdendo async compute e
   **task/mesh shader**, §4.7) o implementare il ring compute (MEC/MES) nel kext [INFERITO].
3. **BO sempre residenti, BO_HANDLES ignorato**: semplice e corretto finché la VRAM basta; nessuna eviction → nessun
   problema DCC/ricompressione, ma `vkAllocateMemory` oltre la VRAM fallisce.
4. **Sparse/PRT non supportati**: `sparseBinding`, `sparseResidency*` andrebbero spenti (`has_sparse = false` nel
   backend) — oggi RADV li espone perché `has_sparse` dipende solo dalla family (`ac_gpu_info.c:1112`).
5. **DCC ignorato**: la patch non disattiva DCC lato RADV; il kext semplicemente non mette PTE.D, quindi i descrittori con
   `COMPRESSION_EN` lavorano su dati non compressi (corretto: `COMPRESSION_ENABLED = PTE.D && COMPRESSION_EN`).
6. Riutilizzabili quasi verbatim: meson/headers sostitutivi, dispatch in `ac_linux_drm.c`, VA manager, sync provider,
   marshaller con static-assert di layout, mock per test host, fix 0005.

## 6. nvidia-macos-driver: come patcha NVK (confronto)

Fonte: `research/refs/nvidia-macos-driver/nvk/nvk-macos.patch` (12 183 righe, base in `nvk/MESA_BASE`). Analisi per
file del run precedente in `scratchpad/nvidia-deepdive/sec7.md` e `nvkparts/`; i punti sotto sono stati ricontrollati
con grep in questo run [VERIFICATO: righe 6478, 6654-6661, 11627, 11680-11695, 11718, 11743 della patch].

| Aspetto | NVK su macOS (nullmoth) | RADV su macOS (Cobalt64 / nostro piano) |
|---|---|---|
| Punto d'innesto | backend nuovo `nvkmd/nvrm` dell'astrazione upstream `nvkmd` (NVK kernel mode driver): `nvkmd_enum_pdev()` → `nvkmd_nvrm_enum_pdev()` (patch r.6654-6661), `subdir('drm')`/`subdir('winsys')` disattivati | backend nuovo sotto `ac_drm_*` (`HAVE_AMDGPU_DARWIN`), RADV/`radeon_winsys` invariati |
| Protocollo kernel | **ABI dell'RM NVIDIA proprietario** (`NV_ESC_RM_ALLOC/CONTROL/MAP_MEMORY`, classi `NV01_MEMORY_LOCAL_USER`, `*_USERMODE_A`), derivato dal port Haiku (`nv-haiku.h`) | ABI `DRM_AMDGPU_*` "rivestita" (struct gemelle, §5.3) |
| Trasporto | `nvrm_xnu.c` (193 righe): `IOServiceOpen(NVAccel, 0x4E560000|type)` con fallback su `NVRM` (r.11680-11695); fd segnaposto `open("/dev/null", O_RDONLY)` legato con `SEL_BINDFD` perché l'RM ragiona per fd; `IOConnectCallMethod(conn, SEL_ESC=1, &cmd, 1, data, size, ..., data, &out)` (r.11718); `IOConnectMapMemory64` con `kIOMapWriteCombineCache` (r.11743); selettore 6 `sWaitEvent` al posto di `poll()` | `IOServiceOpen(Navi48Bringup, 'N48N')`, un selettore per comando, `IOConnectMapMemory64(memoryType = BO handle)` |
| Submission | **interamente in user space**: GPFIFO per canale + doorbell scrivendo in `usermodeMap + NVC361_NOTIFY_CHANNEL_PENDING` (`nvkmd_nvrm_ctx.c`, 1155 righe) | kernel-mediated (`SUBMIT` → ring GFX del kext). L'analogo AMD della submission user-mode sono le **user queue MES** (`DRM_AMDGPU_USERQ 0x16`, doorbell BAR2 256 MB), non usate da RADV |
| Sync | `vk_sync_type` propria su "semaphore surface" RM (`nvRmSemSurf.c`), timeline/binary/GPU wait | `util_sync_provider` userspace + seqno del kext |
| Memoria esterna | import host (`NV01_MEMORY_SYSTEM_OS_DESCRIPTOR`), **import IOSurface zero-copy** via escape privata `NVRM_ESC_SURF_VRAM 0xE2` / `SURF_DIRTY 0xE3` (`nvrm_surfshare_abi.h`) e `VkImportMemoryFdInfoKHR` con fd fittizio "staged" | `BO_IMPORT_HOST` (selettore 21); nessun import IOSurface nelle patch Mesa (lo scanout passa da selettori dedicati) |
| Compilatore | patch a NAK (+1411 righe) per esigenze Metal, `nv_libelf_mini.c` (niente libelf su macOS) | ACO non richiede patch per Darwin (nessuna dipendenza da libelf/LLVM; `-DHAVE_TSERVER` solo per addrlib) |
| Dimensione | ~12.2 k righe di diff, di cui ~4.3 k winsys nvrm, ~2.4 k core NVK, ~1.7 k RT, ~1.4 k NAK | ~8.2 k righe di diff, di cui ~3 k backend + ~0.5 k core |

Lezioni per il nostro piano:
1. Entrambi i progetti hanno scelto di **non riscrivere il winsys del driver Mesa** ma di aggiungere un backend sotto
   l'astrazione kernel esistente (`nvkmd` per NVK, `ac_drm` per RADV) — conferma che per RADV il punto giusto è `ac_drm_*`.
2. nullmoth ha potuto riusare un'ABI kernel già esistente e completa (l'RM NVIDIA gira su macOS come kext): per AMD
   **l'ABI kernel la dobbiamo scrivere noi**, quindi conviene renderla un sottoinsieme 1:1 di `DRM_AMDGPU_*` (come Cobalt64)
   per riusare semantica, test e strumenti Linux (es. replay dei submit catturati su Linux).
3. La parte cross-process (IOSurface/WindowServer) richiede in entrambi i casi escape private: per RADV andrà aggiunto un
   selettore "import/export BO come IOSurface/global handle" e la relativa via in `radv_amdgpu_winsys_bo_from_fd`.
4. Il WSI upstream `wsi_common_metal.c` (1145 righe) presuppone un driver che possa `bind_drawable_to_vkimage`,
   `encode_drawable_present` e `cmd_blit_image` (`wsi_common.h:149-163`, hook pensati per KosmicKrisp su Metal): per
   RADV nativo non serve finché il consumatore è il nostro bundle Metal-su-Vulkan, che presenta tramite il kext
   (come Cobalt64, patch 0003) [INFERITO].

## 7. ABI surface esatta di un winsys Darwin per RADV su Navi 44 + stima dimensione patch

### 7.1 Livello 1: le funzioni `ac_drm_*` che il backend Darwin deve implementare [VERIFICATO: grep degli usi]

Delle 59 funzioni di `ac_linux_drm.h`, **RADV ne chiama direttamente 39** (grep `ac_drm_[a-z_]*(` in `src/amd/vulkan`)
e `ac_gpu_info.c` altre 9; userq (4), `ac_drm_bo_va_op`, `ac_drm_va_range_query`, `ac_drm_cs_import_syncobj`,
`ac_drm_query_gpuvm_fault_info`, `ac_drm_query_uq_fw_area_info` non servono a RADV.
Legenda: **K** = richiede una chiamata al kext; **U** = solo userspace; **S** = stub accettabile in prima fase.

| Gruppo | Funzione | Tipo | Implementazione Darwin |
|---|---|---|---|
| Device | `ac_drm_device_initialize(fd, is_virtio, &maj, &min, &dev)` | K | `IOServiceOpen` + `HELLO`; riportare **drm 3.64** (≥3.59 obbligatorio, ≥3.60 per DCC write-compress-disable, ≥3.63 per DCC 256B scanout) |
| | `ac_drm_device_deinitialize`, `_get_fd` (−1), `_get_cookie`, `_get_sync_provider` | U | |
| | `ac_drm_query_pci_bus_info` | K/U | dal registry IOKit (`IOPCIDevice` "reg"/location) → `deviceUUID`, `VK_EXT_pci_bus_info` |
| | `ac_drm_get_marketing_name` | U | "AMD Radeon RX 9060 XT" |
| | `ac_drm_query_has_vm_always_valid` | U | true |
| Info | `ac_drm_query_info(DEV_INFO)` | K | `struct drm_amdgpu_info_device` (448 B) reale: device_id 0x7590, external_rev 0x41, family 0x98, 2 SE × 2 SA × 8 CU, `cu_bitmap`, RB 0xff/8, cache, `mall_size` 32 MiB, VA layout, `ids_flags` (no GANG_SUBMIT se non implementato) |
| | `ac_drm_query_info(MEMORY / VRAM_GTT / VRAM_USAGE / VIS_VRAM_USAGE / GTT_USAGE)` | K | contatori dinamici del kext |
| | `ac_drm_query_info(MAX_IBS)` | U | GFX 192, COMPUTE 125, SDMA 49 (o i limiti del kext) |
| | `ac_drm_query_info(TIMESTAMP)` | K | contatore GPU 100 MHz (`gpu_counter_freq`) — usato per `vkGetCalibratedTimestampsKHR` |
| | `ac_drm_query_info(NUM_BYTES_MOVED / NUM_EVICTIONS / NUM_VRAM_CPU_PAGE_FAULTS)` | S | 0 |
| | `ac_drm_query_info(GPUVM_FAULT)` | K/S | per `VK_EXT_device_fault`; 0 all'inizio |
| | `ac_drm_query_info(ACCEL_WORKING)` | U | 1 (solo per `wsi_master_fd`, disattivato) |
| | `ac_drm_query_hw_ip_info` / `_hw_ip_count` | K/U | GFX 12.0 rings 0x1; COMPUTE 12.0 rings 0xf (o 0 se non implementato); DMA 7.0 rings 0x3 (o 0); VCN/JPEG 0 nella prima fase |
| | `ac_drm_query_firmware_version` (ME/PFP/MEC obbligatori, VCN se video) | K | versioni reali dei blob caricati: ME 3090, PFP 3190 (≥2680 per `UPDATE_DB_SUMMARIZER_TIMEOUT`), MEC 3450, feature 29 |
| | `ac_drm_query_gpu_info` | U | ricostruito da DEV_INFO + GB_ADDR_CONFIG |
| | `ac_drm_read_mm_registers` (GB_ADDR_CONFIG 0x263e; altri solo per debug) | K | valore da QueryInfo (come Cobalt64 0007) |
| | `ac_drm_query_sensor_info` (SCLK, MCLK, TEMP) | K/S | |
| | `ac_drm_query_heap_info` | K | |
| | `ac_drm_query_sw_info` (`address32_hi`, `address_prt_wa_control_bit`) | U | dal VA manager userspace |
| | `ac_drm_query_video_caps_info` | S | 0 (niente video in fase 1) |
| BO | `ac_drm_bo_alloc(amdgpu_bo_alloc_request)` | K | `BO_CREATE` con domain VRAM/GTT e flag `AMDGPU_GEM_CREATE_*` (§3.3), incluso `GFX12_DCC` |
| | `ac_drm_bo_free` | K | |
| | `ac_drm_bo_cpu_map` / `_cpu_unmap` | K | `IOConnectMapMemory64(memoryType = handle)` / `IOConnectUnmapMemory64`; VRAM via BAR0 (ReBAR 16 GB: tutta la VRAM mappabile), GTT = memoria di sistema wired, WC per `CPU_GTT_USWC` |
| | `ac_drm_bo_export` (kms / handle globale) | U/K | kms = handle locale; export cross-process → selettore share (IOSurface/global id) |
| | `ac_drm_bo_import` | K | idem |
| | `ac_drm_create_bo_from_user_mem` | K | `BO_IMPORT_HOST` (wiring pagine utente) — opzionale (`has_userptr=false`) |
| | `ac_drm_bo_set_metadata` / `ac_drm_bo_query_info` | U→K | in fase 1 tenuti in userspace; nel kext solo se serve condivisione o eviction DCC |
| | `ac_drm_bo_wait_for_idle` | K | attesa sull'ultimo seqno che ha usato il BO (o su tutto il contesto) |
| VA | `ac_drm_va_range_alloc` / `_free` | U | VA manager libdrm vendorizzato (range HIGH + 32-bit `0xffff8000`) |
| | `ac_drm_bo_va_op_raw` (MAP/UNMAP, poi CLEAR/REPLACE per sparse) | K | `GEM_VA` con flag R/W/X, MTYPE (NC default, UC), `PRT`, `NOALLOC`; PTE.D da `GFX12_DCC` |
| | `ac_drm_bo_va_op_raw2` (con `vm_timeline_syncobj_out`) | K/U | se il kext fa MAP sincroni, il punto timeline si segnala subito in userspace (Cobalt64) |
| Ctx/CS | `ac_drm_cs_ctx_create2` / `_free` / `_query_reset_state2` | K | id contesto, priorità, stato reset/guilty/VRAM lost |
| | `ac_drm_cs_ctx_stable_pstate` | S | no-op |
| | `ac_drm_cs_submit_raw2(ctx, 0, chunks)` | K | chunk IB (multi-IP per gang), FENCE, SYNCOBJ_*; `BO_HANDLES` può essere ignorato se tutti i BO sono residenti |
| | `ac_drm_cs_chunk_fence_info_to_data` | U | |
| | `ac_drm_cs_query_fence_status(ctx, ip, ring, seq, timeout)` | K | `WAIT_SEQ` per (ip, ring) |
| Sync | `ac_drm_cs_create_syncobj2`, `_destroy_syncobj`, `_syncobj_wait`, `_syncobj_timeline_wait`, `_syncobj_query2`, `_syncobj_transfer` | U (+K per wait) | `util_sync_provider` Darwin: payload = (ring, seqno) o segnale CPU; wait bloccante via `WAIT_SEQ` |
| | `_syncobj_export_sync_file(2)`, `_syncobj_import_sync_file` | S | −ENOSYS (niente sync_file su macOS) → disattivare `VK_KHR_external_semaphore_fd`/`fence_fd` |
| VM | `ac_drm_vm_reserve_vmid` / `_unreserve_vmid` | S | solo SQTT/RGP |

### 7.2 Livello 2: selettori del kext (IOUserClient) proposti per Navi 44

Ricavati dalla tabella sopra e confrontati con N48N 1.0 (§5.3). Le struct sono **layout-identiche ai gemelli DRM** per
poter riusare codice di test Linux:

| Sel. | Nome | Input → Output | Fase | Differenza rispetto a N48N |
|---|---|---|---|---|
| 0 | `HELLO` | abi, flags → abi kernel, build, vmid, caps (bitmask: compute, sdma, gang, prt, dcc, userptr) | 1 | + bitmask capability |
| 1 | `QUERY_DEVICE` | → blob statico: `drm_amdgpu_info_device` (448 B) + 10× `drm_amdgpu_info_hw_ip` + fw ME/PFP/MEC/MES/... + `GB_ADDR_CONFIG` + VA layout | 1 | **nuovo**: elimina il canned gfx1201 |
| 2 | `QUERY_DYNAMIC` | → `drm_amdgpu_memory_info`, usage, timestamp, sensori, contatori seq | 1 | ≈ QUERYINFO |
| 3 | `BO_CREATE` | `drm_amdgpu_gem_create_in` → handle, size, domain, bits | 1 | + supporto `GFX12_DCC` |
| 4 | `BO_FREE` | handle | 1 | = |
| 5 | (map) | `IOConnectMapMemory64(memoryType = handle)` | 1 | = |
| 6 | `GEM_VA` | `drm_amdgpu_gem_va` | 1 (MAP/UNMAP), 2 (PRT, CLEAR, REPLACE) | + PRT/CLEAR/REPLACE |
| 7 | `CTX` | `union drm_amdgpu_ctx` | 1 | = |
| 8 | `SUBMIT` | header + N× `drm_amdgpu_cs_chunk_ib` (ip GFX/COMPUTE, ring) + fence | 1 (GFX), 2 (COMPUTE + gang) | + multi-IP/gang |
| 9 | `WAIT_SEQ` | (ip, ring, seq, timeout) → stato | 1 | + per-ring |
| 10 | `BO_WAIT_IDLE` | handle, timeout | 1 | nuovo |
| 11 | `BO_IMPORT_HOST` | VA host, size, flags → handle | 2 | = selettore 21 di N48N |
| 12 | `BO_SHARE` / `BO_OPEN` | handle → global id/IOSurface; id → handle | 2 | nuovo (interop WindowServer/Metal) |
| 13 | `BO_METADATA` | `drm_amdgpu_gem_metadata` | 3 (solo con eviction DCC o sharing) | nuovo |
| 14 | `READ_REGS` | offset, count (root-only, debug) | debug | = |
| 15 | `RESERVE_VMID` | | 3 (SQTT) | nuovo |
| 16+ | scanout/present | | display (altro report) | ≈ selettori 9-14, 22-26 |

### 7.3 Livello 3: modifiche a file upstream Mesa (oltre al backend)

Elenco minimo, ricavato da Cobalt64 e dai punti DRM-dipendenti trovati in §3.7:
1. `meson.build`, `include/meson.build`, `src/amd/common/meson.build`, `src/amd/vulkan/meson.build`,
   `src/vulkan/runtime/meson.build`: `with_amdgpu_darwin`, `-DHAVE_AMDGPU_DARWIN`, `-DHAVE_TSERVER`, niente libdrm,
   `vk_drm_syncobj.c` senza libdrm, `-Wl,-undefined,dynamic_lookup`.
2. `include/darwin/{xf86drm.h,amdgpu.h,libsync.h}` (stand-in; `amdgpu.h` si può ridurre alle sole dichiarazioni usate).
3. `src/amd/common/ac_linux_drm.c`: union `ddev` + `is_darwin`, wrapper ioctl, dispatch delle funzioni libdrm.
4. `src/amd/common/ac_gpu_info.c`: `has_userptr` da capability; opzionale `has_sparse` da capability PRT.
5. `src/amd/vulkan/radv_instance.c`: hook `enumerate`.
6. `src/amd/vulkan/radv_physical_device.{c,h}`: tipo `RADV_DRM_DEVICE_AMDGPU_DARWIN`, enumerazione via IOKit (PCI
   1002:7590 reale dal registry, non un id finto), niente `wsi_master_fd`, disattivazione di `EXT_physical_device_drm`,
   `KHR_display`, `EXT_acquire_drm_display`, `KHR_external_memory_fd`, `EXT_external_memory_dma_buf`,
   `EXT_image_drm_format_modifier`, `KHR_external_semaphore_fd`, `KHR_external_fence_fd`.
7. `src/amd/vulkan/winsys/amdgpu/radv_amdgpu_bo.c`: map sempre via `ac_drm_bo_cpu_map`; `align64(size, 4096)`.
8. `src/amd/vulkan/winsys/amdgpu/radv_amdgpu_winsys.c`: `syncobj_sync_type` dal provider.
9. (bugfix) `radv_amdgpu_cs.c` `cs_grow` (Cobalt64 0005).
10. Disattivazioni di feature non supportate dal kext nella fase 1 (via capability del backend): compute queue / task
    shader (se niente gang), sparse, transfer queue, video.

### 7.4 Stima dimensione [INFERITO, calibrata su Cobalt64 VERIFICATO]

| Componente | Cobalt64 (misurato) | Nostro port Navi 44 (stima) | Note |
|---|---:|---:|---|
| Backend Darwin (`ac_darwin_*`: device/info, BO, VA, CS planner, sync provider, IOKit transport) | 2900 | 3000-3800 | + multi-ring/gang, info device da kext, BO wait, share |
| VA manager vendorizzato | 565 | 565 | identico (o riuso del file Cobalt64, MIT) |
| Header libdrm stand-in | 2102 | 300-2100 | ridotto alle dichiarazioni usate |
| Header ABI kext (copia) | 586 | 300-500 | senza i selettori display sperimentali |
| Modifiche a file upstream | 534 | 500-700 | §7.3 |
| Mock + test host | 1381 | 1000-1500 | fortemente consigliati (CI senza GPU) |
| **Totale righe nuove** | **8205** | **~5.5-9 k** | di cui codice "vero" ~3.5-4.5 k |

Con la riduzione degli header e senza mock, un port minimo funzionante (fase 1: GFX ring, BO residenti, niente sparse/DCC/
video) è dell'ordine di **~4 k righe**, di cui ~0.5 k di modifiche a file Mesa esistenti — tutto il resto di RADV/ACO/
addrlib resta invariato (misurato su questo clone: `src/amd/vulkan` 119.8 k righe, `compiler` (ACO) 80.2 k, `common` 86.8 k,
`addrlib` 67.0 k: ~354 k righe; `src/amd` totale ~459 k). È il pezzo più piccolo dell'intero progetto: il grosso del
lavoro è nel kext (bring-up PSP/SMU/IMU/RLC/MES, GMC/VM, ring, IRQ, display) e nel layer Metal.

## 8. Rischi, domande aperte e passi raccomandati

### 8.1 Rischi tecnici

1. **Info device errate = hang**: `cu_bitmap`, `enabled_rb_pipes_mask`, `num_se` alimentano CU mask dei dispatch
   (`COMPUTE_STATIC_THREAD_MGMT_SE*`), dimensionamento dei ring per-SE e mask RB. Usare il canned gfx1201 di Cobalt64 su
   Navi 44 (2 SE) è un rischio concreto [INFERITO]. Mitigazione: selettore `QUERY_DEVICE` reale o canned `gfx1200` dal
   nostro dump.
2. **Firmware version gating**: Mesa abilita pacchetti in base a `pfp_fw_version` (es. ≥2680 per
   `UPDATE_DB_SUMMARIZER_TIMEOUT`, workaround hang HiZ). Il kext deve caricare FW ≥ quelli misurati (PFP 0xc76=3190) e
   riportare la versione vera.
3. **Gang submit / task shader**: senza sottomissione atomica GFX+ACE, `VK_EXT_mesh_shader` (task) va disattivato. Metal
   "object/mesh shaders" (Metal 3) ne dipendono [INFERITO].
4. **DCC**: senza PTE.D il rendering funziona ma la banda effettiva cala su un bus a 128 bit (323 GB/s teorici). Con PTE.D
   l'eviction deve decomprimere via SDMA (`amdgpu_ttm.c:354-370`). Fase 1: BO pinnati, PTE.D facoltativo.
5. **Sparse/PRT e workaround null-PRT**: `has_smem_with_null_prt_bug=1` su gfx1200; supportare PRT richiede che il kext
   gestisca PTE "PRT" (VALID=0) e mappature multiple dello stesso BO. Altrimenti spegnere sparse (oggi RADV lo espone
   per family).
6. **Out-of-order uncached L2 su GFX12** (`has_out_of_order_uncached_l2`): memoria `MTYPE_UC` esposta ad API richiede
   cautela (ACO inserisce attese); vale anche per eventuali buffer coerenti con la CPU usati dal layer Metal.
7. **Sincronizzazione cross-process**: il provider userspace di Cobalt64 non supporta sync_file né condivisione tra
   processi; WindowServer + app richiedono fence condivisibili (servono oggetti fence nel kext).
8. **Licenze**: le patch Cobalt64 dichiarano MIT (come Mesa); il resto del repo Cobalt64 va verificato prima di riusare
   codice del kext.

### 8.2 Domande aperte (richiedono dati privilegiati o decisioni)

- (Risolta in questo run) `amdgpu_sw_info_address_prt_wa_control_bit` = **46** su questa macchina (libdrm 2.4.134,
  `scratchpad/mesa-radv/swinfo/swinfo.c`): il VA "LOW" di un BO sparse è `va & ~(1ull << 46)`. Il VA manager Darwin
  deve riprodurre lo stesso valore.
- Layout della "compression metadata" nascosta di GFX12 (dove risiede in VRAM, chi la inizializza: GMC/MMHUB 4.1.0) —
  serve per decidere se PTE.D è attivabile dal kext senza ulteriore setup (lettura registri MMHUB/GCMC richiede debugfs
  root: `amdgpu_regs2` / `umr`).
- Comportamento esatto del CP gfx12 con IB utente che scrivono registri UCONFIG privilegiati da kernel queue (verificato
  indirettamente: RADV su Linux lo fa; per il kext serve la stessa configurazione `CP_*_PRIV`/`SH_MEM_CONFIG`).
- Se usare kernel queue (ring + MES `ADD_QUEUE` come Linux) o user queue MES con doorbell BAR2 per Darwin: RADV non ha
  path userq; radeonsi sì (solo con `AMD_USERQ=1` e drm ≥ 3.65).
- Ring dumps/MQD reali in `research/hw_dump/mqd` e `rings/` mostrano come Linux crea le code gfx/compute via MES: da
  incrociare con il report compute/bring-up per definire il `SUBMIT` del kext.

### 8.3 Passi raccomandati (ordine)

1. **Host-side, senza GPU**: applicare (in un clone separato) le patch Cobalt64 0001-0002/0005 su Mesa main a scopo di
   studio; sostituire il canned `gfx1201` con un canned `gfx1200` generato da `gfx1200_canned_dump.txt`; compilare
   RADV per macOS x86_64 e farlo girare contro il **mock** (`RADV_DARWIN_MOCK=1`) per vedere `vulkaninfo` con
   "RADV GFX1200". Questo valida build, enumerazione, info device e flussi BO/VA/CS senza kext.
2. Definire l'ABI kext v1 (§7.2) come sottoinsieme 1:1 di `DRM_AMDGPU_*`, con `QUERY_DEVICE` reale e capability bits.
3. Su Linux (questa macchina), registrare tracce dei submit RADV di test semplici (clear, compute vadd) con
   `RADV_DEBUG=hang`/`AMD_PARSE_IB`/dump IB per avere "golden" IB gfx1200 da riprodurre via kext (replay).
4. Kext fase 1: un ring GFX (o compute), BO residenti, VA MAP/UNMAP, fence seqno + IRQ → primo `vkQueueSubmit` reale.
5. Fase 2: compute ring + gang submit (task shader), PRT/sparse, `BO_IMPORT_HOST`, condivisione BO/fence cross-process.
6. Fase 3: DCC PTE.D + eviction DCC-aware, SDMA transfer queue, video (VCN 5.0), SQTT.
