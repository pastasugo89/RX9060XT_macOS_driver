# Dump hardware RX 9060 XT (raccolti l'11/10/2026 su Linux 7.2.9-cachyos)

Tutti i dati sono stati letti in **sola lettura** (sysfs/debugfs) con `amdgpu` caricato e la GPU
inizializzata da Linux. Servono come riferimento ("oracolo") per il bring-up su macOS: il driver
macOS dovrà arrivare allo stesso stato.

| File | Origine | Contenuto |
|---|---|---|
| `ip_discovery_table.bin` | debugfs `amdgpu_discovery` | tabella IP discovery binaria (10240 byte) letta dalla VRAM riservata |
| `vbios.rom` | debugfs `amdgpu_vbios` | VBIOS 113-P816G493-S05 (58880 byte, ATOM, device 0x7590) |
| `firmware_info.txt` | debugfs `amdgpu_firmware_info` | versioni dei firmware caricati (ME/PFP/MEC/RLC/IMU/SOS/SMC/SDMA/MES/DMCUB/VCN) |
| `gca_config.bin` | debugfs `amdgpu_gca_config` | configurazione GFX (decodifica sotto) |
| `pm_info.txt`, `pp_features.txt`, `sysfs_power.txt` | debugfs/sysfs | clock DPM, feature SMU, profili di potenza, metodo di reset |
| `gpu_metrics.bin` | sysfs `gpu_metrics` | struct gpu_metrics v1.3 |
| `vm_info.txt`, `gem_info.txt`, `sa_info.txt`, `fence_info.txt` | debugfs | stato memoria/BO/fence al momento del dump |
| `dm_dtn_log.txt`, `dm_capabilities.txt`, `dmub_fw_state.txt` | debugfs | stato pipeline display DCN (monitor spenti al momento del dump: pipe idle); la lettura di `dmub_fw_state` è fallita ("Operation not permitted") |
| `lspci_vvv_03_00_0.txt`, `lspci_vvv_03_00_1.txt`, `lspci_vvv_upstream_ports.txt` | `lspci -vvv` (root, sola lettura) | capability PCIe complete: ReBAR (BAR0 256 MB…16 GB), AtomicOps (endpoint requester, switch routing, root port completer 32/64 bit), niente FLR, link (root port a 16 GT/s, link interno a 32 GT/s) |
| `mqd/*.bin` + `mqd/decoded_*.txt` | debugfs `amdgpu_mqd_*` | MQD reali delle code gfx e compute (struct `v12_gfx_mqd` / `v12_compute_mqd`) |
| `rings/*.bin` + `rings/decoded_*.txt` | debugfs `amdgpu_ring_*` (primi 64 KiB) | contenuto dei ring: PM4 per gfx/compute, pacchetti API MES per i ring MES |

## Decodifica `gca_config.bin` (formato v5, `amdgpu_debugfs_gca_config_read`)

| Campo | Valore |
|---|---|
| max_shader_engines | 2 |
| max_tile_pipes | 32 |
| max_cu_per_sh | 8 |
| max_sh_per_se | 2 |
| max_backends_per_se | 4 |
| max_texture_channel_caches | 16 |
| max_gprs | 1536 |
| max_gs_threads | 32 |
| max_hw_contexts | 8 |
| sc_prim_fifo_size_frontend / backend | 0x20 / 0x100 |
| sc_earlyz_tile_fifo_size | 0x4c0 |
| backend_enable_mask | 0xff |
| gb_addr_config | 0x08200545 |
| num_rbs | 8 |
| rev_id | 1 |
| pg_flags | 0x0002c000 |
| cg_flags | 0x3_b430030d |
| family | 0x98 (AMDGPU_FAMILY_GC_12_0_0) |
| external_rev_id | 0x41 |
| PCI device / revision | 0x7590 / 0xc0 |
| subsystem | 0x1da2:0xa493 (Sapphire) |
| APU | no |

## Strumenti di decodifica (in `../tools/`)

- `decode_mqd.py <v12_structs.h> <struct> <mqd.bin>`: decodifica una MQD usando le struct del kernel.
- `decode_pm4.py <nvd.h> <ring.bin>`: elenca i pacchetti PM4 type-3 di un ring gfx/compute.
- `decode_mes_ring.py <mes_v12_api_def.h> <ring.bin>`: elenca i pacchetti API MES (SET_HW_RSRC, ADD_QUEUE, ...).

Esempi di quello che mostrano:

- ring gfx: `COND_EXEC`, `WAIT_REG_MEM`, `WRITE_DATA`, `PFP_SYNC_ME`, `RELEASE_MEM` (fence),
  `CONTEXT_CONTROL`, `INDIRECT_BUFFER`: la sequenza che il kernel emette per ogni job.
- ring MES scheduler: `SET_HW_RSRC` con vmid_mask 0xff00, compute_hqd_mask 0x0c, gfx_hqd_mask 0xfe,
  sdma_hqd_mask 0xfc; poi `SET_HW_RSRC_1`, `ADD_QUEUE` (6 code), `MISC`, `QUERY_SCHEDULER_STATUS`.
- MQD compute: `cp_hqd_pq_control=0xd030890a`, `cp_hqd_persistent_state=0x0be05501`,
  `cp_hqd_pq_doorbell_control=0x60000018`, MQD in VRAM a 0x83_da94b000.
