# 01 - Sequenza di bring-up amdgpu (Linux) per Navi 44 / GC 12.0.0 (RX 9060 XT)

Obiettivo: documentare, con riferimenti file:riga al sorgente Linux in
`research/src/linux/drivers/gpu/drm/amd` (master 7.3-rc, ott. 2026), cosa deve replicare un kext macOS
scritto da zero per portare la GPU dallo stato post-VBIOS all'esecuzione di command buffer.

Legenda: **[VERIFICATO]** = letto nel codice / nei dati hardware dumpati / test eseguito;
**[INFERITO]** = deduzione non verificata direttamente.
Percorsi relativi: `amd/` = `research/src/linux/drivers/gpu/drm/amd/`.

## Indice
0. Sintesi
1. (a) IP discovery
2. (b) Sequenza di init ordinata
3. (c) Formati firmware
4. (d) Doorbell, reset, recovery
5. (e) Differenze GC 12.0.0 vs 12.0.1
6. Checklist minima di bring-up per un driver IOKit
7. Domande aperte e rischi

## 0. Sintesi

- **Discovery-driven**: per GC 12.0.0 Linux non ha quasi costanti hardware; tutto (base registri per IP,
  versioni, topologia 2 SE / 4 SA / 32 CU / 8 RB, 4 UMC, 32 MiB MALL) viene dalla tabella IP discovery in cima
  alla VRAM (10 KiB a `VRAM - 64 KiB`). Il dump di questa scheda e' stato decodificato e verificato (checksum ok,
  harvest table vuota). DMU 4.1.0 viene riscritto in DCN 4.0.1 da `amdgpu_discovery.c:2688-2690`.
- **Ordine di bring-up** (`amdgpu_device_init`): soc24 common -> GMC (GART MMHUB) -> IH -> **PSP** (boot sOS +
  caricamento di *tutti* i firmware via `LOAD_IP_FW` + `AUTOLOAD_RLC`) -> SMU -> DM -> GFX (attesa autoload RLC,
  GART GFXHUB, CP RS64, MES KIQ, KCQ/KGQ via MES) -> SDMA -> MES sched.
- **Il PSP e' obbligatorio**: firmware GC/SDMA/MES/IMU/RLC firmati; il PSP 14.0.2 usa TMR riservato dall'IFWI
  (niente `SETUP_TMR`), chiede le regioni FW riservate (cmd 0x50/0x51) e accetta i firmware nell'ordine di
  `enum AMDGPU_UCODE_ID`. Il set di file per Navi 44 e' `gc_12_0_0_*`, `psp_14_0_2_*`, `smu_14_0_2`,
  `sdma_7_0_0`, `dcn_4_0_1_dmcub`, `vcn_5_0_0`; MES in modalita' **uni-MES** (`gc_12_0_0_uni_mes.bin`, fw 0x93).
- **MES gestisce tutte le code**: la KIQ "classica" non e' mai usata; la pipe MES 1 fa da KIQ e mappa la pipe
  scheduler e le code kernel con `ADD_QUEUE(map_legacy_kq=1)`.
- **Reset**: default mode1 via debug mailbox SMU (msg 2 su `C2PMSG_75`); nessun mode2; reset per-coda via MES.
  Il recupero completo richiede rieseguire `asic_init` AtomBIOS e l'intero boot PSP.
- **Navi 44 vs Navi 48**: stessa logica di driver; cambiano i dati (nomi firmware, assenza kicker per 0x7590,
  `external_rev_id` +0x40, PG flag JPEG_DPG, gfx1200 vs gfx1201, sOS senza RAS_DRV/RL, RAS non supportato su MP0
  14.0.2, `enable_gfx_features` solo su MP1 14.0.2). Nessun firmware 12.0.1/14.0.3 e' riusabile.
- Tutti i registri necessari al bring-up (GC, MMHUB, OSSSYS, NBIF, MP0/MP1) sono raggiungibili direttamente in
  BAR5 (512 KiB); solo `RCC_DEV0_EPF2_STRAP2` e i registri SMN dello SMU (`MP1_FIRMWARE_FLAGS`) richiedono
  l'accesso indiretto `RSMU_INDEX/DATA`.
- La checklist operativa per il kext e' nella sezione 6 (33 passi + reset).

## 1. (a) IP discovery

### 1.1 Dove si trova la tabella e come la legge Linux [VERIFICATO]

`amd/amdgpu/amdgpu_discovery.c`:

- `amdgpu_discovery_get_tmr_info()` (righe 288-376):
  1. attende fino a 2 s che `MP0_SMN_C2PMSG_33` (dword `0x16061`, define locale a riga 143) abbia il bit 31
     (IFWI/PSP bootloader ha finito l'init; rilevante solo per hot-plug, su una scheda gia' POSTata dal
     VBIOS/UEFI GOP e' gia' a 1);
  2. legge `RCC_CONFIG_MEMSIZE` (dword `0xde3`, riga 142) = dimensione VRAM in MB;
  3. offset di default della tabella = `(vram_size << 20) - DISCOVERY_TMR_OFFSET`, con
     `DISCOVERY_TMR_OFFSET = 64 KiB` e `DISCOVERY_TMR_SIZE = 10 KiB` (`amdgpu_discovery.h:29-30`);
  4. se a quell'offset c'e' `BINARY_SIGNATURE 0x28211407` la usa; altrimenti legge
     `DRIVER_SCRATCH_0/1/2` (dword `0x94/0x95/0x96`, righe 148-150) = offset lo/hi e size forniti dal PSP.
- `amdgpu_discovery_read_binary_from_mem()` (righe 396-417) copia i 10 KiB dalla VRAM con
  `amdgpu_device_vram_access()` (BAR0 visibile, oppure `MM_INDEX`/`MM_INDEX_HI`/`MM_DATA` dword 0x0/0x6/0x1,
  righe 144-146) e marca `discovery.reserve_tmr = true` (la regione va riservata nell'allocatore VRAM:
  `amdgpu_ttm.c:1768` riserva `DISCOVERY_TMR_OFFSET` in cima alla VRAM).
- `amdgpu_discovery_init()` (righe 703-773): verifica signature, checksum del binario (somma a 16 bit dei
  byte da `binary_checksum+2` a `binary_size`, `amdgpu_discovery_calculate_checksum` riga 461) e poi le
  checksum di ogni tabella `IP_DISCOVERY..MALL_INFO` (`amdgpu_discovery_table_check`, riga 618).

**Per il kext macOS**: su questa scheda `mem_info_vram_total` (sysfs, letto senza privilegi) =
17095983104 byte = **16304 MiB** (= 16 GiB - 80 MiB), quindi `RCC_CONFIG_MEMSIZE` = 16304 e la tabella sta
all'offset VRAM `16304 MiB - 64 KiB = 0x3_FAFF_0000` [VERIFICATO valore sysfs; INFERITO che MEMSIZE coincida,
perche' `mc_vram_size = get_memsize() * 1 MiB`, `gmc_v12_0.c:733-734`]. Con Resizable BAR attivo (BAR0 = 16 GiB)
e' leggibile direttamente da BAR0 a quell'offset senza `MM_INDEX`. Il dump `ip_discovery_table.bin` e' di 10240
byte = `DISCOVERY_TMR_SIZE`. Cross-check: `/sys/class/drm/card1/device/ip_discovery/die/0/<hwid>/0/` riporta
per GC, DMU, NBIF e OSSSYS esattamente versioni e base del mio parser [VERIFICATO].

### 1.2 Strutture binarie (`amd/include/discovery.h`) [VERIFICATO]

| Struct | Righe | Note |
|---|---|---|
| `binary_header` (v1) | 56-65 | `signature`, `version_major/minor`, `binary_checksum`, `binary_size`, `table_list[TOTAL_TABLES=6]` di `table_info{offset,checksum,size,padding}` (48-54) |
| `binary_header_v2` | 67-78 | aggiunge `num_tables` (non usato da questa scheda: versione 1.3) |
| `ip_discovery_header` | 87-103 | signature `0x53445049` ("IPDS"), `version`, `size`, `id`, `num_dies`, `die_info[16]`, flag `base_addr_64_bit` solo se version==4 |
| `ip` (v1/v2) | 105-121 | `hw_id`, `number_instance`, `num_base_address`, `major/minor/revision`, `harvest:4` |
| `ip_v3` | 123-139 | come sopra ma il nibble basso e' `sub_revision`, l'alto `variant` |
| `ip_v4` | 141-159 | come v3, base address a 32 o 64 bit |
| `die_header` | 161-165 | `die_id`, `num_ips` |
| `gc_info_v1_3` | 274-315 | campi `gc_num_se` ... `gc_tcc_cache_line_size` |
| `harvest_table` | 368-382 | signature `0x56524148` ("HARV"), 32 entry `{hw_id, number_instance, reserved}` |
| `mall_info_v2_0` | 400-406 | `mall_size_per_umc` |
| `vcn_info_v1_0` | 408-438 | fuse per istanza (codec disabilitati) |

Il parser unico e' `amdgpu_discovery_reg_base_init()` (righe 1733-1937), che usa sempre il layout
`ip_v4` (compatibile con v3 se `base_addr_64_bit==0`).

### 1.3 Come le versioni IP diventano registri e IP block [VERIFICATO]

1. Per ogni IP entry: `hw_id_map[]` (righe 255-286) traduce l'HWID hardware nell'indice interno
   `*_HWIP` (es. `DCE_HWIP = DMU_HWID 271`, `NBIO_HWIP = NBIF_HWID 108`, `MP0_HWIP = 255`, `MP1_HWIP = 1`).
2. `adev->reg_offset[hw_ip][instance] = ip->base_address` (riga ~1897): puntatore all'array di base
   address (in **dword**) di quella istanza.
3. `adev->ip_versions[hw_ip][inst] = IP_VERSION_FULL(major, minor, revision, variant, subrev)`.
4. Casi speciali nel loop: VCN revision bit[7:6] = capability encode/decode (righe 1805-1826); SDMA0/1
   incrementano `sdma.num_instances`; UMC incrementa `gmc.num_umc`; GC setta `gfx.xcc_mask`.
5. Indirizzo di un registro: `SOC15_REG_OFFSET(ip, inst, reg) = adev->reg_offset[ip##_HWIP][inst][reg##_BASE_IDX] + reg`
   (`amd/amdgpu/soc15_common.h:36`). L'offset `reg` e il `reg_BASE_IDX` vengono dagli header generati
   `amd/include/asic_reg/<ip>/<ip>_<ver>_offset.h` (es. `gc/gc_12_0_0_offset.h`).
6. Accesso: `amdgpu_device_rreg()` (`amd/amdgpu/amdgpu_reg_access.c:363-387`): se `reg*4 < rmmio_size`
   (BAR5 = 512 KiB, cioe' dword < `0x20000`) lettura diretta MMIO, altrimenti `amdgpu_reg_pcie_rd32()` =
   accesso indiretto tramite la coppia PCIE index/data di NBIF (installata in `soc24_common_early_init`,
   `amd/amdgpu/soc24.c:331-345`: `amdgpu_device_indirect_rreg/wreg`).
   Conseguenza pratica: tutte le base con valori `0x024xxxxx`/`0x03xxxxxx` (secondo/terzo segmento) non
   sono raggiungibili da BAR5 e passano per l'indirect (SMN).

Ordine di aggiunta degli IP block per questo ASIC (`amdgpu_discovery_set_ip_blocks`, righe 3085-3735;
selettori: common 2377-2379, gmc 2440-2442, ih 2488-2490, psp 2552-2553, smu 2620-2623, dm 2684-2694,
gfx 2772-2774, sdma 2833-2835, mm 2864-2960, mes 2994-2996; ordine delle chiamate 3654-3730):

| # | IP block | selezionato da | file |
|---|---|---|---|
| 1 | `soc24_common_ip_block` | GC 12.0.0 | `soc24.c` |
| 2 | `gmc_v12_0_ip_block` | GC 12.0.0 | `gmc_v12_0.c` (+ `mmhub_v4_1_0.c`, `gfxhub_v12_0.c`) |
| 3 | `ih_v7_0_ip_block` | OSSSYS 7.0.0 | `ih_v7_0.c` |
| 4 | `psp_v14_0_ip_block` | MP0 14.0.2 | `psp_v14_0.c` + `amdgpu_psp.c` |
| 5 | `smu_v14_0_ip_block` | MP1 14.0.2 | `pm/swsmu/smu14/smu_v14_0.c`, `smu_v14_0_2_ppt.c` |
| 6 | `dm_ip_block` | DCE(DMU) 4.1.0 -> 4.0.1 | `amd/display/amdgpu_dm/` |
| 7 | `gfx_v12_0_ip_block` | GC 12.0.0 | `gfx_v12_0.c` (+ `imu_v12_0.c`) |
| 8 | `sdma_v7_0_ip_block` | SDMA0 7.0.0 | `sdma_v7_0.c` |
| 9 | `vcn_v5_0_0` / `jpeg_v5_0_0` | VCN 5.0.0 | non necessari per il bring-up |
| 10 | `mes_v12_0_ip_block` | GC 12.0.0 | `mes_v12_0.c` |

Funzioni "non-block" assegnate nello stesso punto (righe 3395-3650): `adev->family = AMDGPU_FAMILY_GC_12_0_0`
(0x98, coerente con `family 0x98` di `gca_config.bin`), `nbio.funcs = nbif_v6_3_1_funcs` +
`hdp_flush_reg = nbif_v6_3_1_hdp_flush_reg` (NBIF 6.3.1, riga 3502), `hdp.funcs = hdp_v7_0_funcs` (HDP 7.0.0),
`df.funcs = df_v4_15_funcs` (DF 4.15.0, riga 3572), `smuio.funcs = smuio_v14_0_2_funcs`,
`lsdma.funcs = lsdma_v7_0_funcs`.

### 1.4 DMU 4.1.0 nella tabella vs DCN 4.0.1 nel driver [VERIFICATO]

`amd/amdgpu/amdgpu_discovery.c:2684-2690`, in `amdgpu_discovery_set_display_ip_blocks()`:

```c
		case IP_VERSION(4, 1, 0):
		...
			/* TODO: Fix IP version. DC code expects version 4.0.1 */
			if (adev->ip_versions[DCE_HWIP][0] == IP_VERSION(4, 1, 0))
				adev->ip_versions[DCE_HWIP][0] = IP_VERSION(4, 0, 1);
```

Cioe' l'hardware dichiara DMU (HWID 271) 4.1.0, ma tutto il codice DC (resource `dcn401`, firmware
`dcn_4_0_1_dmcub.bin`) e' indicizzato come DCN 4.0.1: la riscrittura avviene *dopo* il parse e *prima*
dell'aggiunta di `dm_ip_block`. Navi 44 e Navi 48 condividono lo stesso DCN (401); non c'e' alcuna variante
per Navi 44 nel display. Nota: IH 7.0.0 e SDMA 7.0.0 non vanno confusi con le righe 3132-3182 (rimappature
4.0.1/4.1.0 per Vega legacy).

### 1.5 Contenuto del dump `research/hw_dump/ip_discovery_table.bin` [VERIFICATO]

Parser scritto ad hoc (riusato dalla run precedente):
`/tmp/claude-1000/-home-pastasugo89-Documenti-rx9060xt-metal-driver/75517241-da08-4a95-9813-eba8a30820e6/scratchpad/bringup/scripts/parse_discovery.py`
(output completo in `.../bringup/discovery_parsed.txt`). Tutte le checksum verificano.

- `binary_header`: signature `0x28211407`, versione **1.3**, checksum `0x6e43`, size 1444 byte.
  Tabelle: IP_DISCOVERY @0x3c (940 B), GC @0x3e8 (164 B), HARVEST_INFO @0x48c (136 B), VCN_INFO @0x514
  (96 B), MALL_INFO @0x574 (48 B), NPS_INFO assente.
- `ip_discovery_header`: versione **3** (=> `ip_v3`, base address a 32 bit), id `0x66c5dfb0`, 1 die, 42 IP.

Base address (dword) degli IP rilevanti per il bring-up (`reg_offset[ip][0][BASE_IDX]`):

| IP (HWID) | versione | BASE_IDX 0 | 1 | 2 | 3 | 4.. |
|---|---|---|---|---|---|---|
| GC (11) | 12.0.0 | 0x00001260 | 0x0000a000 | 0x0001c000 | 0x02402c00 | |
| SDMA0/SDMA1 (42/43) | 7.0.0 | stesse base di GC (SDMA vive nello spazio GC) | | | | |
| MMHUB (34) | 4.1.0 | 0x0001a000 | 0x02408800 | | | |
| ATHUB (35) | 4.1.0 | 0x00000c00 | 0x02408c00 | | | |
| OSSSYS/IH (40) | 7.0.0 | 0x000010a0 | 0x0240a000 | | | |
| HDP (41) | 7.0.0 | 0x00000f20 | 0x0240a400 | | | |
| NBIF (108) | 6.3.1 | 0x00000000 | 0x00000014 | 0x00000d20 | 0x00010400 | 0x0241b000, 0x04040000 |
| MP0 (255) = MP1 (1) | 14.0.2 | 0x00016000 | 0x00016200 | 0x0001ce00 | 0x00dc0000 | ... 15 base |
| SMUIO (4) | 14.0.2 | 0x00016800 | 0x00016a00 | 0x02401000 | 0x03440000 | |
| THM (3) | 14.0.2 | 0x00016600 | 0x02400c00 | | | |
| DMU (271) | 4.1.0 | 0x00000012 | 0x000000c0 | 0x000034c0 | 0x00009000 | 0x02403c00 |
| LSDMA (91) | 7.0.0 | 0x00011400 | 0x02456800 | | | |
| UVD/VCN (12) | 5.0.0 (variant 2) | 0x00007800 | 0x00007e00 | | | |
| DF (46) | 4.15.0 | 0x00007000 | 0x00c00000 | 0x0240b800 | 0x07c00000 | 0x12400000 |
| UMC (150) x4 | 8.14.0 | 0x00014000 / 0x00054000 / 0x00094000 / 0x000d4000 (inst 0..3) | | | | |
| PCIE (70) | 6.1.0 | 0x02411800 | 0x068c0000 | 0x20000000 | | |

Altri IP presenti: CLKA x9 (14.0.2), FUSE, DFX, DFX_DAP, DBGU_NBIO, SYSTEMHUB 2.3.0, DIO/DAZ (versione
127.127.63 = placeholder), PWR 9.0.0 (0 base), e 4 HWID non presenti in `soc15_hw_ip.h`
(273 v1.0.3, 282 v14.0.2, 286 v5.0.0, 293 v1.0.0) che Linux ignora.

Helper per risolvere nomi registro -> indirizzo assoluto su questa scheda:
`.../scratchpad/bringup/scripts/regres.py <IP> <offset.h> REG...` (stampa dword, byte e se e' raggiungibile
da BAR5 o richiede l'indirect).

**gc_info v1.3** (`struct gc_info_v1_3`, letto da `amdgpu_discovery_get_gfx_info`, righe 1995-2103):

| campo | valore | uso in Linux |
|---|---|---|
| gc_num_se | 2 | `max_shader_engines` |
| gc_num_wgp0_per_sa / wgp1 | 4 / 0 | `max_cu_per_sh = 2*(4+0) = 8` (riga 2018) |
| gc_num_sa_per_se | 2 | `max_sh_per_se` |
| gc_num_rb_per_se | 4 | `max_backends_per_se` (8 RB totali, = `num_rbs 8` in gca_config) |
| gc_num_gl2c | 16 | `max_texture_channel_caches` |
| gc_num_gprs | 1536 | VGPR per SIMD (wave32) |
| gc_num_max_gs_thds / gs_table_depth | 32 / 32 | |
| gc_gsprim_buff_depth | 1792 | |
| gc_parameter_cache_depth | 256 | |
| gc_double_offchip_lds_buffer | 64 | |
| gc_wave_size | 32 | |
| gc_max_waves_per_simd | 16 | |
| gc_max_scratch_slots_per_cu | 32 | |
| gc_lds_size | 64 (KiB per WGP) | |
| gc_num_sc_per_se / packer_per_sc | 1 / 4 | |
| gc_num_gl2a | 4 | |
| gc_num_tcp_per_sa / tcps | 8 / 32 | |
| gc_num_sdp_interface | 18 | |
| gc_tcp_l1_size / tcp_size_per_cu | 32 KiB | |
| gc_gl1c_per_sa / size | 4 / 64 KiB | |
| gc_gl2c_per_gpu | 4096 KiB | L2 = 4 MiB |
| gc_tcc_size / tcc_cache_line_size | 1024 / 256 B | |
| gc_instruction / scalar cache | 32 KiB (line 128) / 16 KiB (line 64) | |

Totale: 2 SE x 2 SA x 8 CU = **32 CU** (= dmesg). Su Navi 48 (gfx1201) i valori sono 4 SE, 64 CU; il
codice Linux non ha costanti hardcoded per nessuno dei due: tutto viene da questa tabella.

**Harvest table**: signature "HARV" valida, **nessuna entry** (lista vuota alla entry 0): nessun IP
harvestato (niente VCN/DMU/UMC disabilitati). La gestione e' in `amdgpu_discovery_read_from_harvest_table()`
(righe 870-971: VCN -> `vcn.harvest_config`, DMU -> `harvest_ip_mask` display, UMC -> `umc_harvest_config`,
GC -> nulla). L'harvesting dei CU **non** sta qui: su gfx12 si legge da `CC_GC_SHADER_ARRAY_CONFIG` /
`GC_USER_SHADER_ARRAY_CONFIG` (vedi sez. 2.8). [VERIFICATO dmesg: 32 CU attivi = die Navi 44 completo.]

**MALL info v2.0**: `mall_size_per_umc = 8 MiB` x 4 UMC = **32 MiB Infinity Cache** (Navi 48: 64 MiB, 8 UMC
[INFERITO dalle specifiche pubbliche]). **VCN info**: 1 istanza, fuse 0 (nessun codec disabilitato).

## 2. (b) Sequenza di init ordinata

### 2.0 Lo scheletro: `amdgpu_device_init()` [VERIFICATO]

File `amd/amdgpu/amdgpu_device.c`:

1. Mappa BAR5 come `rmmio` (righe 3908-3917; su soc24 il registro MMIO e' BAR5, 512 KiB).
2. `amdgpu_device_ip_early_init()` (riga 1980, chiamata a 3958): `amdgpu_discovery_set_ip_blocks()` (riga 2056,
   sez. 1.3), poi `early_init` di ogni blocco (riga 2105); subito dopo l'`early_init` del blocco COMMON legge il
   VBIOS (`amdgpu_get_bios`, riga 2132) e inizializza l'interprete AtomBIOS (`amdgpu_atombios_init`, riga 2141).
3. **Reset all'init** (righe 4046-4066): se `amdgpu_asic_need_reset_on_init()` ->
   `soc24_need_reset_on_init()` (`soc24.c:242-257`) legge `MPASP_SMN_C2PMSG_81` (sign-of-life del sOS PSP):
   se != 0 un driver precedente ha gia' caricato il sOS e Linux esegue un reset ASIC (mode1) prima di
   procedere. **Per macOS e' critico**: dopo un warm reboot da Linux/Windows senza power-cycle il sOS puo'
   essere ancora vivo [INFERITO: dipende da cosa resetta PERST# su questa scheda; da misurare].
4. **Post** (righe 4068-4080): `amdgpu_device_need_post()` (riga 1190) -> per CIK+ guarda il bit
   `ATOM_S7_ASIC_INIT_COMPLETE` in `BIOS_SCRATCH_7` (`amdgpu_atombios.c:1634-1642`). Se manca, per GC >= 11
   `amdgpu_device_asic_init()` (righe 958-985) attende il bootloader PSP (`amdgpu_psp_wait_for_bootloader`)
   ed esegue la command table AtomBIOS `asic_init` v2.1 con sclk/mclk di boot presi da `firmwareinfo` v3.1
   (`amdgpu_atomfirmware_asic_init`, `amdgpu_atomfirmware.c:1062-1110`). Con avvio UEFI + GOP (OpenCore)
   la scheda arriva gia' postata; serve un interprete AtomBIOS (`atom.c`) solo per il recupero dopo un
   mode1 reset (vedi sez. 4).
5. `amdgpu_device_ip_init()` (righe 2369-2510):
   - `sw_init` di ogni blocco in ordine; subito dopo il `sw_init` di COMMON ne esegue l'`hw_init`
     (doorbell/HDP remap pronti per GMC); subito dopo il `sw_init` di GMC: `amdgpu_device_mem_scratch_init`
     (pagina scratch in VRAM per il default address del system aperture), **`gmc hw_init`** (GART MMHUB),
     `amdgpu_wb_init` (writeback slots in GTT), CSA statica se MCBP, `seq64`;
   - `amdgpu_ib_pool_init`, `amdgpu_ucode_create_bo` (BO unico in VRAM/GTT con tutti i firmware da
     passare al PSP);
   - `hw_init_phase1` (righe 2187-2215): solo COMMON e **IH** (PSP solo in SR-IOV);
   - `amdgpu_device_fw_loading` (righe 2242-2290): **`psp hw_init`** (boot sOS + caricamento di tutti i
     firmware, sez. 2.6) e poi `amdgpu_pm_load_smu_firmware` (per SMU 14.0.2 il FW SMU e' gia' caricato da
     PSP/IFWI, sez. 2.12);
   - `hw_init_phase2` (righe 2217-2240): tutti gli altri nell'ordine della lista: **SMU** -> DM -> **GFX**
     -> **SDMA** -> VCN/JPEG -> **MES**.
6. `amdgpu_device_ip_late_init()` (riga 2742): clock/power gating, `gmc_v12_0_late_init`
   (alloca gli invalidation engine per ring, abilita l'IRQ VM fault), `soc24_common_late_init`
   (abilita il self-ring doorbell aperture), ecc.

Ordine effettivo osservato in dmesg su questa macchina: `soc24_common, gmc_v12_0, ih_v7_0, psp_v14_0,
smu_v14_0, dm, gfx_v12_0, sdma_v7_0, vcn_v5_0_0, jpeg_v5_0_0, mes_v12_0` (= tabella 1.3).

### 2.1 soc24 common [VERIFICATO]

`amd/amdgpu/soc24.c`:

- `soc24_common_early_init` (331-400): `nbio.funcs->set_reg_remap()`; installa gli accessor indiretti
  PCIE; `rev_id` da `RCC_STRAP0_RCC_DEV0_EPF0_STRAP0.STRAP_ATI_REV_ID` (`nbif_v6_3_1_get_rev_id`, nbif
  112-127). **GC 12.0.0: `external_rev_id = rev_id + 0x40`** (Navi 48/12.0.1: `+ 0x50`). Il dump dice
  `external_rev_id 0x41` => `rev_id = 1`. cg_flags identici fra 12.0.0 e 12.0.1; pg_flags: 12.0.1 ha in piu'
  `AMD_PG_SUPPORT_JPEG_DPG`.
- `soc24_common_hw_init` (437-459): ASPM (`nbif_v6_3_1_program_aspm`), `nbif_v6_3_1_init_registers`
  (azzera `STRAP_NO_SOFT_RESET_DEV0_F2` in `RCC_DEV0_EPF2_STRAP2`), `remap_hdp_registers`, `df hw_init`,
  `enable_doorbell_aperture(true)`.
- `soc24_common_late_init` (402-425): `enable_doorbell_selfring_aperture(true)` (dopo l'eventuale resize BAR).
- `soc24_init_doorbell_index` (267-300): layout doorbell (sez. 4.1).
- `soc24_asic_reset_method` (173-196): **MP1 14.0.2 -> sempre MODE1** (niente BACO di default).

### 2.2 NBIF 6.3.1 [VERIFICATO]

`amd/amdgpu/nbif_v6_3_1.c`. Indirizzi assoluti calcolati con le base della tabella discovery (tutti in BAR5
tranne dove indicato):

| Funzione (righe) | Registro | dword / byte BAR5 |
|---|---|---|
| indirect index/data (449-463) | `BIF_BX_PF0_RSMU_INDEX` / `_DATA` (NBIF < 7.11.4) | 0x14 / 0x15 (byte 0x50/0x54) |
| `get_memsize` (148-151) | `RCC_DEV0_EPF0_RCC_CONFIG_MEMSIZE` (MB) | 0xde3 (0x378c) |
| `enable_doorbell_aperture` (311-316) | `RCC_DEV0_EPF0_RCC_DOORBELL_APER_EN.BIF_DOORBELL_APER_EN` | 0xde0 (0x3780) |
| `enable_doorbell_selfring_aperture` (318-339) | `BIF_BX_PF0_DOORBELL_SELFRING_GPA_APER_{BASE_LOW,BASE_HIGH,CNTL}` (EN=1, MODE=1, SIZE=0, base = indirizzo fisico BAR2) | CNTL 0xe15 |
| `gc_doorbell_init` (300-309) | `GDC_S2A0_S2A_DOORBELL_ENTRY_0_CTRL = 0x30000007`, `ENTRY_3_CTRL = 0x3000000d` | 0xeeb / 0xeee |
| `ih_doorbell_range` (341-384) | `GDC_S2A0_S2A_DOORBELL_ENTRY_1_CTRL`: PORT1_ENABLE=1, AWID=0, RANGE_OFFSET=indice IH, RANGE_SIZE=2, AWADDR_31_28=0 | 0xeec |
| `sdma_doorbell_range` (153-199) | `GDC_S2A0_S2A_DOORBELL_ENTRY_2_CTRL`: PORT2_ENABLE=1, AWID=0xe, RANGE_OFFSET, RANGE_SIZE (=20), AWADDR_31_28=3 | 0xeed |
| `ih_control` (386-413) | `BIF_BX0_INTERRUPT_CNTL2 = dummy_page >> 8`; `BIF_BX0_INTERRUPT_CNTL`: IH_DUMMY_RD_OVERRIDE=0, IH_REQ_NONSNOOP_EN=0 | 0xe12 / 0xe11 |
| HDP flush (433-447, 465-478) | `BIF_BX_PF0_GPU_HDP_FLUSH_REQ` / `_DONE`, maschere CP0..CP9, SDMA0, SDMA1 | 0xe26 / 0xe27 |
| `remap_hdp_registers` (97-110) | `BIF_BX0_REMAP_HDP_MEM_FLUSH_CNTL` / `REG_FLUSH_CNTL` = `rmmio_remap.reg_offset + KFD_MMIO_REMAP_HDP_*` | 0xe4d / 0xe4e |
| `mc_access_enable` (129-146) | `BIF_BX0_BIF_FB_EN` FB_READ_EN/FB_WRITE_EN | 0xe20 |
| `init_registers` (480-487) | `RCC_DEV0_EPF2_STRAP2` | **indiretto** (dword 0x404d102) |

`set_reg_remap` (615-629): con pagine da 4 KiB `rmmio_remap.reg_offset = MMIO_REG_HOLE_OFFSET =
0x80000 - PAGE_SIZE = 0x7F000` (riga 613): l'ultima pagina di BAR5 diventa la pagina "HDP flush" che puo'
essere mappata in user space (KFD/Mesa la usano per scrivere 0 e flushare l'HDP dopo scritture CPU in VRAM).
**Per macOS** (x86_64, pagine da 4 KiB) lo stesso valore vale.

### 2.3 GMC v12 + MMHUB 4.1.0 + GFXHUB 12.0 [VERIFICATO]

**sw_init** (`gmc_v12_0.c:808-973`):
- `amdgpu_vm_adjust_size(adev, 256*1024, 9, 3, 48)` (righe 831-844, chiamata a riga 841): VA 48 bit (256 TiB), block 9 bit,
  4 livelli (PDB2, PDB1, PDB0, PTB), `pte_addr_mask = 0x0000FFFFFFFFF000` (PA 48 bit), DMA mask **44 bit**.
  (= dmesg "VM 4 levels, 9-bit block".) GC 12.1.0 (MI4xx) usa 5 livelli/57 bit: non ci riguarda.
- IRQ: `SOC21_IH_CLIENTID_VMC / VMC_1_0__SRCID__VM_FAULT`, `SOC21_IH_CLIENTID_GFX / UTCL2_1_0__SRCID__FAULT`,
  per **GC 12.0.0 soltanto** `SOC21_IH_CLIENTID_DF` src 0 per ECC (12.0.1 usa `SOC_V1_0_IH_CLIENTID_DF`,
  righe 898-904; entrambe le costanti valgono 0x17, quindi la differenza e' solo formale).
- `gmc_v12_0_mc_init` (723-769): `mc_vram_size = RCC_CONFIG_MEMSIZE * 1 MiB`; tenta il resize del BAR0
  (`amdgpu_device_resize_fb_bar`); GART = **512 MiB**; `gmc_v12_0_vram_gtt_location` (688-713):
  `fb_base = MMMC_VM_FB_LOCATION_BASE.FB_BASE << 24` (programmato dal VBIOS, **non** riscritto dal driver
  in bare-metal), GART posizionata in basso (`AMDGPU_GART_PLACEMENT_LOW` -> 0x0), AGP di default,
  `vram_base_offset = MMMC_VM_FB_OFFSET << 24`. dmesg: VRAM `0x8000000000-0x83FAFFFFFF`, GART 512M @0.
- `gmc_v12_0_gart_init` (771-806): tabella GART in VRAM, 8 byte per pagina 4 KiB (1 MiB per 512 MiB),
  `gart_pte_flags = MTYPE_UC | EXECUTABLE | IS_PTE`; VMID0 page table depth 0 (tabella piatta).
- VMID: 0 = kernel/GART, 1-7 = amdgpu gfx, 8-15 = KFD (`first_kfd_vmid = 8`, righe 950-958). Coerente con
  `MES vmid_mask 0xff00`.
- `gmc_v12_0_get_dcc_alignment` (556-571): solo 12.0.0/12.0.1, dipende da `max_texture_channel_caches`
  (16 su Navi 44 => alignment = 16/4 = 4 => 4*16*1K = 64 KiB) [VERIFICATO calcolo dal codice].

**hw_init** (`gmc_v12_0.c:1037-1060`): golden registers vuoti (993-996), poi `gmc_v12_0_gart_enable`
(1002-1035) che programma **solo MMHUB** (`mmhub_v4_1_0_gart_enable`, `mmhub_v4_1_0.c:368-382`), flusha
HDP, abilita i fault default, flush TLB VMID0 su MMHUB. La GFXHUB viene programmata da `gfx_v12_0_hw_init`
tramite `gfx_v12_0_gfxhub_enable` (`gfx_v12_0.c:3603-3621`) *dopo* il caricamento dei firmware GC
(perche' i registri GCVM sono nel power domain GFX gestito da RLC/IMU).

Sequenza `*_gart_enable` (identica per MMHUB `mmhub_v4_1_0.c:121-382` e GFXHUB `gfxhub_v12_0.c:126-386`,
sostituendo il prefisso `MM` con `GC`):

1. `init_gart_aperture_regs`: `VM_CONTEXT0_PAGE_TABLE_BASE_ADDR_LO32/HI32 = pd_addr(gart.bo)` (con flag PDE),
   `CONTEXT0_PAGE_TABLE_START_ADDR = gart_start >> 12`, `END_ADDR = gart_end >> 12`.
2. `init_system_aperture_regs`: `MC_VM_AGP_BASE = 0`, `AGP_BOT/TOP = agp_start/end >> 24`,
   `SYSTEM_APERTURE_LOW/HIGH_ADDR = min/max(fb, agp) >> 18`, `SYSTEM_APERTURE_DEFAULT_ADDR_LSB/MSB` =
   pagina scratch in VRAM, `VM_L2_PROTECTION_FAULT_DEFAULT_ADDR` = dummy page in RAM,
   `PROTECTION_FAULT_CNTL2.ACTIVE_PAGE_MIGRATION_PTE_READ_RETRY = 1`.
3. `init_tlb_regs`: `MC_VM_MX_L1_TLB_CNTL`: ENABLE_L1_TLB=1, SYSTEM_ACCESS_MODE=3,
   ENABLE_ADVANCED_DRIVER_MODEL=1, SYSTEM_APERTURE_UNMAPPED_ACCESS=0, MTYPE=UC.
4. `init_cache_regs`: `VM_L2_CNTL` (ENABLE_L2_CACHE=1, ENABLE_DEFAULT_PAGE_OUT_TO_SYSTEM_MEMORY=1,
   CONTEXT1_IDENTITY_ACCESS_MODE=1), `VM_L2_CNTL2` invalidate all, `VM_L2_CNTL3` BANK_SELECT=9 /
   BIGK_FRAGMENT_SIZE=6 (translate_further e' falso su gfx12: viene settato solo in `gmc_v9_0.c`),
   `CNTL4` PDE/PTE request non fisiche, `CNTL5` SMALLK_FRAGMENT_SIZE=0.
5. `enable_system_domain`: `VM_CONTEXT0_CNTL` ENABLE_CONTEXT=1, PAGE_TABLE_DEPTH=0.
6. `disable_identity_aperture`: `VM_L2_CONTEXT1_IDENTITY_APERTURE_LOW = 0xF_FFFFFFFF`, HIGH = 0, offset 0.
7. `setup_vmid_config` per VMID 1..15: `VM_CONTEXT1_CNTL` + i*ctx_distance: ENABLE_CONTEXT=1,
   PAGE_TABLE_DEPTH=num_level (3), tutti i `*_PROTECTION_FAULT_ENABLE_DEFAULT=1`,
   PAGE_TABLE_BLOCK_SIZE = block_size-9 = 0, RETRY_PERMISSION_OR_INVALID_PAGE_FAULT = !noretry;
   START_ADDR=0, END_ADDR = max_pfn-1. La base del page directory per-VMID viene scritta a runtime nel ring
   (`gmc_v12_0_emit_flush_gpu_tlb`, righe 388-434) o da MES per le user queue.
8. `program_invalidation`: per gli engine 0..17 `VM_INVALIDATE_ENGx_ADDR_RANGE = 0xffffffff / 0x1f`.

Invalidazione TLB da CPU (`gmc_v12_0_flush_vm_hub`, righe 213-303): engine **17** riservato alla GART;
(semaforo `VM_INVALIDATE_ENG17_SEM` solo su MMHUB), scrittura `VM_INVALIDATE_ENG17_REQ = inv_req`
(`*_get_invalidate_req`: PER_VMID_INVALIDATE_REQ = 1<<vmid, FLUSH_TYPE, INVALIDATE_L2_PTES/PDE0/PDE1/PDE2,
L1_PTES, CLEAR_PROTECTION_FAULT_STATUS_ADDR), poll di `VM_INVALIDATE_ENG17_ACK` bit vmid; per MMHUB
anche la "private invalidation" bit 25 di `vm_l2_bank_select_reserved_cid2`.

Indirizzi su questa scheda (tutti in BAR5):

| Registro | dword | byte |
|---|---|---|
| `MMMC_VM_FB_LOCATION_BASE/TOP` | 0x1a554/0x1a555 | 0x69550 |
| `MMMC_VM_FB_OFFSET` | 0x1a4c7 | 0x6931c |
| `MMMC_VM_AGP_BASE` (BOT/TOP seguono) | 0x1a558 | 0x69560 |
| `MMMC_VM_SYSTEM_APERTURE_LOW_ADDR` | 0x1a559 | 0x69564 |
| `MMMC_VM_MX_L1_TLB_CNTL` | 0x1a55b | 0x6956c |
| `MMVM_L2_CNTL` | 0x1a4e4 | 0x69390 |
| `MMVM_CONTEXT0_CNTL` / `CONTEXT1_CNTL` | 0x1a564 / 0x1a565 | 0x69590 |
| `MMVM_CONTEXT0_PAGE_TABLE_BASE_ADDR_LO32` | 0x1a5cf | 0x6973c |
| `MMVM_CONTEXT0_PAGE_TABLE_START_ADDR_LO32` | 0x1a5ef | 0x697bc |
| `MMVM_INVALIDATE_ENG17_SEM/REQ/ACK` | 0x1a586/0x1a598/0x1a5aa | |
| `MMVM_L2_PROTECTION_FAULT_STATUS_LO32` | 0x1a4f0 | 0x693c0 |
| `GCMC_VM_FB_LOCATION_BASE` | 0x2874 | 0xa1d0 |
| `GCMC_VM_MX_L1_TLB_CNTL` | 0x287b | 0xa1ec |
| `GCVM_L2_CNTL` | 0x2824 | 0xa090 |
| `GCVM_CONTEXT0_CNTL` | 0x2884 | 0xa210 |
| `GCVM_CONTEXT0_PAGE_TABLE_BASE_ADDR_LO32` | 0x28ef | 0xa3bc |
| `GCVM_INVALIDATE_ENG17_REQ/ACK` | 0x28b8/0x28ca | |
| `GCVM_L2_PROTECTION_FAULT_STATUS_LO32` | 0x2830 | 0xa0c0 |

### 2.4 Layout PTE/PDE gfx12 e MTYPE [VERIFICATO]

`amd/amdgpu/amdgpu_vm.h:57-141`, `gmc_v12_0.c:485-549`:

| bit | PTE gfx12 | note |
|---|---|---|
| 0 | VALID | |
| 1 | SYSTEM (pagina in RAM host via PCIe) | |
| 2 | SNOOPED (coerente con cache CPU) | |
| 3 | TMZ | |
| 4 | EXECUTABLE | |
| 5 / 6 | READABLE / WRITEABLE | |
| 7-11 | FRAG (log2 del fragment in pagine 4K) | |
| 12-47 | indirizzo fisico (mask `0x0000FFFFFFFFF000`) | |
| **54-55** | **MTYPE** (`AMDGPU_PTE_MTYPE_GFX12`, shift 54, 2 bit) | su gfx10/11 era bit 48-50 |
| **56** | PRT (`AMDGPU_PTE_PRT_GFX12`) | su gfx9-11 era bit 51 |
| 58 | DCC (compressione gestita dal MC, novita' gfx12) | `AMDGPU_GEM_CREATE_GFX12_DCC` |
| 58 | NOALLOC (`AMDGPU_PTE_NOALLOC`, riga 84) | **stesso bit di DCC**: su gfx12 Linux lo setta/azzera in `get_vm_pte` (righe 530-533) prima di valutare DCC; un driver nuovo non deve usare NOALLOC su gfx12 [INFERITO] |
| 59 | BUS_ATOMICS | |
| **63** | IS_PTE (`AMDGPU_PTE_IS_PTE` / `AMDGPU_PDE_PTE_GFX12`: un PDE marcato come PTE = huge page) | |
| 58-62 (PDE) | BFS = block fragment size (`AMDGPU_PDE_BFS_GFX12`) | |

MTYPE (`amd/include/soc24_enum.h:610-614`, enum `TCC_MTYPE`): **NC=0, WC=1, CC=2**; `MTYPE_UC = 3` e' definito nello stesso header alla riga 282 (enum `MTYPE`). Policy Linux in `gmc_v12_0_get_vm_pte`: default e NC -> `MTYPE_NC`; UC su
richiesta (`AMDGPU_VM_MTYPE_UC` o `AMDGPU_GEM_CREATE_UNCACHED`); niente RW/CC per dGPU. La GART usa sempre
`MTYPE_UC | EXECUTABLE | IS_PTE` (riga 795-797). `gmc_v12_0_get_vm_pde` (485-505): converte l'indirizzo
VRAM MC in offset fisico (`vram_base_offset + addr - vram_start`), richiede allineamento 64 B e PA < 48 bit.
"Hole" VA canonico per 4 livelli: `AMDGPU_GMC_HOLE_START = 0x0000800000000000`, `HOLE_END =
0xffff800000000000` (`amdgpu_gmc.h:36-49`).

### 2.5 IH v7.0 (OSSSYS 7.0.0) [VERIFICATO]

`amd/amdgpu/ih_v7_0.c`:

- `sw_init` (587-633): IRQ self `SOC21_IH_CLIENTID_IH` src 0; ring IH0 **256 KiB** (`amdgpu_ih_ring_init`,
  `use_bus_addr = (load_type != PSP)` => con PSP l'anello e' in memoria GPU, cioe' in GTT/VRAM indirizzata
  via MC), doorbell = `doorbell_index.ih << 1`; ring IH1 (`IH_RING_SIZE`, solo dGPU) doorbell
  `(ih+1) << 1`; ring software `ih_soft` di una pagina.
- `enable_ring` (237-280): `IH_RB_BASE = gpu_addr >> 8`, `IH_RB_BASE_HI = (gpu_addr >> 40) & 0xff`,
  `IH_RB_CNTL` (`ih_v7_0_rb_cntl` 187-208): MC_SPACE = 4 (GPU VA via MC) o 2 (bus addr), WPTR_OVERFLOW_CLEAR=1,
  WPTR_OVERFLOW_ENABLE=1, RB_SIZE = log2(dimensione/4), WPTR_WRITEBACK_ENABLE=1, MC_SNOOP=1, MC_RO=0, MC_VMID=0;
  RPTR_REARM = msi_enabled; per IH1: WPTR_OVERFLOW_ENABLE=0, RB_FULL_DRAIN_ENABLE=1.
  `IH_RB_WPTR_ADDR_LO/HI` = indirizzo writeback del wptr (solo IH0), `IH_RB_WPTR = IH_RB_RPTR = 0`,
  `IH_DOORBELL_RPTR` (OFFSET = indice doorbell, ENABLE=1).
- `irq_init` (310-431): disabilita, `nbio.ih_control` (sez. 2.2), (`IH_CHICKEN.MC_SPACE_GPA_ENABLE` solo per
  load DIRECT/BACKDOOR con bus addr), abilita i ring, `nbio.ih_doorbell_range`,
  `IH_STORM_CLIENT_LIST_CNTL.CLIENT18_IS_STORM_CLIENT=1`, `IH_INT_FLOOD_CNTL.FLOOD_CNTL_ENABLE=1`,
  `IH_MSI_STORM_CTRL.DELAY=3`, per IH1 `IH_RING1_CLIENT_CFG_INDEX=0` + `CLIENT_CFG_DATA` (CLIENT_ID=0xa (GFX/UTCL2),
  SOURCE_ID=0, MATCH_ENABLE=1): **IH1 riceve i retry fault di pagina**; `pci_set_master`; abilita
  (`IH_RB_CNTL.RB_ENABLE`, `ENABLE_INTR`); self-IRQ di test (`force_update_wptr_for_self_int`).
- `get_wptr` (453-498): legge il wptr dal writeback, gestisce l'overflow (bit `RB_OVERFLOW`, ripartenza da
  wptr+32 entry).

Formato IV (8 dword, 32 byte; `amdgpu_ih.c:280-292`, `amdgpu_ih_decode_iv_helper`):
dw0 = `client_id[7:0] | src_id[15:8] | ring_id[23:16] | vmid[27:24] | vmid_src[31]`; dw1 + dw2[15:0] =
timestamp (48 bit), dw2[31] = timestamp_src; dw3 = `pasid[15:0] | node_id[23:16]`; dw4..7 = src_data[0..3].

Indirizzi IH su questa scheda (dword in BAR5): `IH_RB_CNTL 0x1120`, `IH_RB_RPTR 0x1121`, `IH_RB_WPTR 0x1122`,
`IH_RB_BASE 0x1123`, `IH_RB_BASE_HI 0x1124`, `IH_RB_WPTR_ADDR_HI 0x1125`, `IH_RB_WPTR_ADDR_LO 0x1126`,
`IH_DOORBELL_RPTR 0x1127`, `IH_RB_CNTL_RING1 0x112c`, `IH_CNTL 0x1148`, `IH_STORM_CLIENT_LIST_CNTL 0x114a`,
`IH_STATUS 0x1162`, `IH_INT_FLOOD_CNTL 0x1175`, `IH_MSI_STORM_CTRL 0x1191`, `IH_RING1_CLIENT_CFG_INDEX 0x1223`,
`IH_CHICKEN 0x122a`.

Client/source id rilevanti (client da `amd/include/soc15_ih_clientid.h:86-108`, src da
`amd/include/ivsrcid/gfx/irqsrcs_gfx_12_0_0.h`):

| Evento | client_id | src_id | registrato in |
|---|---|---|---|
| CP End-Of-Pipe (fence gfx/compute) | `SOC21_IH_CLIENTID_GRBM_CP` 0x14 | 181 (0xB5) | `gfx_v12_0.c:1474` |
| CP bad opcode / priv reg / priv instr | 0x14 | 183 / 184 / 185 | `gfx_v12_0.c:1481-1495` |
| CP generic (MES/userq) | 0x14 | 177 (0xB1) | |
| SDMA trap (fence) | `SOC21_IH_CLIENTID_GFX` 0x0a | 49 (0x31) | `sdma_v7_0.c:1302` |
| SDMA user fence | 0x0a | 70 (0x46) | `sdma_v7_0.c:1309` |
| VM fault MMHUB | `SOC21_IH_CLIENTID_VMC` 0x12 | 0 | `gmc_v12_0.c:866-868` |
| VM fault GFXHUB (UTCL2) | 0x0a | 0 | `gmc_v12_0.c:891-893` |
| ECC (DF) | `SOC21_IH_CLIENTID_DF` 0x17 | 0 | `gmc_v12_0.c:900-901` |
| SMU -> driver (PMFW) | `SOC15_IH_CLIENTID_MP1` 0x1f | 0xFE (`SMU_IH_INTERRUPT_ID_TO_DRIVER`) | `smu_v14_0.c:915` |
| Termico L2H / H2L | `SOC15_IH_CLIENTID_THM` 0x0f | 0 / 1 | `smu_v14_0.c:903-909` |
| DCN: VSTARTUP OTGn, VUPDATE, PFLIP HUBPn, HPDn, DMCUB outbox | `SOC15_IH_CLIENTID_DCE` 0x04 | es. 0x3C (OTG0 VSTARTUP), 0x4F (HUBP0 flip), 0x68 (DMCUB outbox low prio) | `amd/display/amdgpu_dm/amdgpu_dm_irq.c:2509-2610` |

### 2.6 PSP v14.0.2 (MP0 14.0.2): boot del sOS, ring, TMR, caricamento firmware [VERIFICATO]

Configurazione per MP0 14.0.2 (`amd/amdgpu/amdgpu_psp.c`): `psp_early_init` (178-189) setta
`autoload_supported = true`, `boot_time_tmr = true` e per 14.0.2 (righe 268-271) non li cambia (solo
`sup_ifwi_up`); `pmfw_centralized_cstate_management = false` (righe 108-134). Conseguenze:
- **TMR**: `psp_skip_tmr()` (righe 931-939) ritorna true (boot_time_tmr && autoload) => il driver **non**
  alloca ne' invia `GFX_CMD_ID_SETUP_TMR`; il TMR e' riservato dall'IFWI al boot. Invece
  `psp_update_fw_reservation()` (1059-1121, attiva per 14.0.2 con sOS >= 0x3b0e0d; qui 0x3b0f0d) chiede al
  PSP `GFX_CMD_ID_FB_FW_RESERV_ADDR (0x50)` e `_EXT_ADDR (0x51)` e marca come riservate quelle regioni in cima
  alla VRAM (deve valere `reserv_addr == real_vram_size - reserv_size`).
- **SMU FW**: caricato come primo firmware non-PSP (`psp_load_non_psp_fw`, 3515-3593: con autoload e senza
  cstate centralizzato chiama `psp_load_smu_fw` prima del loop).

Funzioni hardware-specifiche (`amd/amdgpu/psp_v14_0.c`):
- `psp_v14_0_init_microcode` (61-94): per 14.0.2/14.0.3 `psp_init_sos_microcode` + `psp_init_ta_microcode`
  (file `psp_14_0_2_sos.bin`, `psp_14_0_2_ta.bin`; niente TOC/kicker per 14.0.2: le varianti `_kicker` esistono
  solo per 14.0.3, righe 34-41).
- `is_sos_alive` (96-104): `MPASP_SMN_C2PMSG_81 != 0`.
- `wait_for_bootloader` (106-125): fino a 10 tentativi di `psp_wait_for(C2PMSG_35, bit31 == 1)`.
- `bootloader_load_component` (127-159) — usato per KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV, DBG_DRV, RAS_DRV,
  IPKEYMGR_DRV: se il sOS e' vivo non fa nulla; altrimenti attende il bootloader, copia il binario nel
  buffer `fw_pri` (1 MiB, allineato 1 MiB, in VRAM), scrive `C2PMSG_36 = fw_pri_mc_addr >> 20` e
  `C2PMSG_35 = comando` (`enum psp_bootloader_cmd`, `amdgpu_psp.h:96-108`: SYSDRV 0x10000, SOSDRV 0x20000,
  KEY_DATABASE 0x80000, SOCDRV 0xB0000, DBGDRV 0xC0000, INTFDRV 0xD0000, RASDRV 0xE0000, IPKEYMGRDRV 0xF0000,
  TOS_SPL_TABLE 0x10000000, SPDMDRV 0x20000000), poi riattende bit31.
- `bootloader_load_sos` (202-237): come sopra con `PSP_BL__LOAD_SOSDRV`, `mdelay(20)`, poi attende che
  `C2PMSG_81` cambi valore (sign-of-life).
- `ring_create` (270-338, bare metal): attende `C2PMSG_64` con `MBOX_TOS_READY_FLAG` (bit31 risposta, status
  0); `C2PMSG_69/70 = ring_mem_mc_addr lo/hi`, `C2PMSG_71 = ring_size`, `C2PMSG_64 = ring_type << 16`
  (`PSP_RING_TYPE__KM = 2`, `amdgpu_psp.h:118`, quindi si scrive 0x20000), `mdelay(20)`, attende risposta su C2PMSG_64.
  `ring_stop`: `C2PMSG_64 = GFX_CTRL_CMD_ID_DESTROY_RINGS (0x30000)`.
- wptr del ring: `C2PMSG_67` (get/set, righe 358-381).

Ordine `psp_hw_start` (`amdgpu_psp.c:2952-3050`): KDB -> SPL -> SYS_DRV -> SOC_DRV -> INTF_DRV -> DBG_DRV ->
RAS_DRV -> IPKEYMGR_DRV -> SPDM_DRV -> **SOS** (ognuno solo se presente nel file) -> `psp_ring_create(KM)` ->
`psp_update_fw_reservation` -> `psp_tmr_init` (no-op qui) -> `psp_tmr_load` (saltato). Poi `psp_load_fw`
(3595-3684): `psp_load_non_psp_fw` -> `psp_asd_initialize` (TA ASD) -> `psp_rl_load` -> TA RAS/HDCP/DTM/RAP/
SECUREDISPLAY (opzionali, per il bring-up minimo **non servono**; HDCP/DTM servono a DC per HDCP).

Contenuto reale di `psp_14_0_2_sos.bin` (dump del mio script, sez. 3): KDB, SYS_DRV, SOS, SOC_DRV,
INTF_DRV, DBG_DRV, TOC (non usato da 14.0.2), IPKEYMGR_DRV, SPL. **Niente RAS_DRV e niente RL** (presenti
invece in `psp_14_0_3_sos.bin` di Navi 48).

Formato dei comandi (`amd/amdgpu/psp_gfx_if.h`):
- frame del ring `struct psp_gfx_rb_frame` (497-512, 64 byte): `cmd_buf_addr_lo/hi`, `cmd_buf_size`,
  `fence_addr_lo/hi`, `fence_value`, ...; il ring e' in VRAM, il wptr si scrive in `C2PMSG_67` (in dword).
- buffer comando `struct psp_gfx_cmd_resp` (466-489, 1024 byte): `buf_size`, `buf_version`, `cmd_id` (+8),
  `cmd` union (+28), risposta `resp` a +864 (status, `fw_addr_lo/hi`, `tmr_size`, ...).
- `GFX_CMD_ID_LOAD_IP_FW = 6` con `struct psp_gfx_cmd_load_ip_fw` (315-322): `fw_phy_addr_lo/hi` (indirizzo MC,
  allineato 4 KiB), `fw_size`, `fw_type` (`enum psp_gfx_fw_type`, 209-312).
- `GFX_CMD_ID_AUTOLOAD_RLC = 0x21`: "tutti i FW GFX caricati, avvia l'autoload RLC".
- Altri: `LOAD_TA 1`, `LOAD_ASD 4`, `SETUP_TMR 5`, `LOAD_TOC 0x20`, `BOOT_CFG 0x22`.
- Submit: `psp_cmd_submit_buf()` (`amdgpu_psp.c:726`): copia il cmd nel buffer cmd, scrive un frame, avanza
  wptr, attende che il fence in memoria raggiunga il valore, controlla `resp.status`.

Mappa ucode -> `fw_type` per il set di firmware di GC 12.0.0 (in ordine di caricamento = ordine di
`enum AMDGPU_UCODE_ID`, `amdgpu_ucode.h:478-554`; i valori `GFX_FW_TYPE_*` da `psp_gfx_if.h`):

| # | AMDGPU_UCODE_ID | GFX_FW_TYPE | sorgente |
|---|---|---|---|
| 0 | `SMC` (caricato per primo, fuori loop) | `SMU` = 18 | `smu_14_0_2.bin` |
| 1 | `SDMA_RS64` (header SDMA v3.0, `amdgpu_sdma.c:291-295`) | `SDMA_UCODE_TH0` = 71 | `sdma_7_0_0.bin` |
| 2 | `CP_RS64_PFP` | `RS64_PFP` = 87 | `gc_12_0_0_pfp.bin` (ucode) |
| 3 | `CP_RS64_ME` | `RS64_ME` = 88 | `gc_12_0_0_me.bin` |
| 4 | `CP_RS64_MEC` | `RS64_MEC` = 89 | `gc_12_0_0_mec.bin` |
| 5 | `CP_RS64_PFP_P0_STACK` | 90 | pfp (data) |
| 6 | `CP_RS64_ME_P0_STACK` | 92 | me (data) |
| 7 | `CP_RS64_MEC_P0_STACK`, `P1_STACK` | 94, 95 | mec (data) |
| 8 | `CP_MES`, `CP_MES_DATA` | `CP_MES` 33, `MES_STACK` 34 | `gc_12_0_0_uni_mes.bin` (uni-MES, default) |
| 9 | `CP_MES1`, `CP_MES1_DATA` | `CP_MES_KIQ` 81, `MES_KIQ_STACK` 82 | stesso `uni_mes` in modalita' uni (altrimenti `mes1.bin`) (`mes_v12_0_early_init` chiama `amdgpu_mes_init_microcode` per entrambe le pipe; con `enable_uni_mes` il nome file e' sempre `%s_uni_mes.bin`, `amdgpu_mes.c:780-782`; versione letta in `ucode[24] & 0xfff` = 0x93, uguale a quella in `firmware_info.txt`) |
| 10 | `IMU_I`, `IMU_D` | 68, 69 | `gc_12_0_0_imu.bin` |
| 11a | `RLC_RESTORE_LIST_GPM_MEM` (2560 B), `RLC_RESTORE_LIST_SRM_MEM` (23472 B) | 20, 21 | `gc_12_0_0_rlc.bin` (header v2.1; `RESTORE_LIST_CNTL` ha size 0 e non viene caricato) |
| 11b | `RLC_IRAM`, `RLC_DRAM` (header v2.2) | 26 (`RLC_IRAM`), 48 (`RLC_DRAM_BOOT`) | `gc_12_0_0_rlc.bin` |
| 12 | `RLC_G` | `RLC_G` = 8 -> poi **`GFX_CMD_ID_AUTOLOAD_RLC`** | `gc_12_0_0_rlc.bin` |
| 13 | `DMCUB` | `DMUB` = 51 | `dcn_4_0_1_dmcub.bin` |
| 14 | `VCN` | 13 | `vcn_5_0_0.bin` (opzionale) |

Mappatura verificata in `amdgpu_psp_get_fw_type()` (`amdgpu_psp.c:3051-3300`: RS64 PFP/ME/MEC e stack
righe 3257-3287, IMU 3251-3254). `psp_rlc_autoload_start` invia `GFX_CMD_ID_AUTOLOAD_RLC` (riga 3907). Le sotto-immagini RLC vengono registrate solo se la loro size e' != 0 (`amdgpu_gfx_rlc_init_microcode_v2_1/_v2_2`,
`amd/amdgpu/amdgpu_rlc.c:345-430`).

### 2.7 IMU v12 + RLC autoload / backdoor [VERIFICATO]

Tre modalita' (`amdgpu_ucode_get_load_type`, `amdgpu_ucode.c:556-598`; parametro `amdgpu_fw_load_type`
default -1 => **PSP**; 0 => DIRECT; 3 => RLC_BACKDOOR_AUTO):

1. **PSP (default, quella usata su questa macchina)**: tutti i firmware GC (incluso IMU) sono consegnati
   al PSP con `LOAD_IP_FW`; quando arriva `RLC_G` il driver manda `GFX_CMD_ID_AUTOLOAD_RLC`
   (`psp_load_non_psp_fw`, riga ~3585). PSP+IMU accendono il GFX, l'RLC carica ME/PFP/MEC/MES dalla sua
   tabella. `gfx_v12_0_hw_init` (`gfx_v12_0.c:3767`) poi attende `gfx_v12_0_wait_for_rlc_autoload_complete`
   (2331-2358): `CP_STAT == 0` e `RLC_RLCS_BOOTLOAD_STATUS.BOOTLOAD_COMPLETE == 1`.
2. **RLC_BACKDOOR_AUTO**: il driver costruisce in VRAM l'immagine di autoload secondo la TOC
   (`gc_12_0_0_toc.bin`, `gfx_v12_0_init_toc_microcode`), programma la RLC RAM tramite IMU
   (`imu_v12_0_program_rlc_ram`, `imu_v12_0.c:367-398`: `GFX_IMU_RLC_RAM_INDEX/ADDR_HIGH/ADDR_LOW/DATA`; per
   **entrambi** 12.0.0 e 12.0.1 usa la stessa tabella `imu_rlc_ram_golden_12_0_1`, righe 177-255) e avvia
   (`gfx_v12_0_rlc_backdoor_autoload_enable`). Richiede che il PSP NON sia usato: incompatibile con il TMR /
   firmware firmati? [INFERITO: con PSP 14 i firmware GC sono firmati e la modalita' backdoor e' pensata per
   emulazione/bring-up interno; su silicio di produzione non e' garantita].
3. **DIRECT**: il driver scrive IMU (`imu_v12_0_load_microcode`, 87-122), `imu_v12_0_setup` (144-161:
   `GFX_IMU_C2PMSG_ACCESS_CTRL0/1`), `imu_v12_0_start` (163-175: azzera bit0 di `GFX_IMU_CORE_CTRL`, attende
   `GFX_IMU_GFX_RESET_CTRL & 0x1f == 0x1f`), RLC e CP via registri. Su gfx12 "rlc firmware loading relies on smu
   firmware is loaded firstly" (commento in `gfx_v12_0_hw_init`).

**Per macOS la scelta e' obbligata: modalita' PSP**, identica a Linux (i firmware sono firmati; il PSP li
verifica). Questo rende il PSP il primo vero ostacolo del bring-up.

### 2.8 GFX v12 (GC 12.0.0): golden, CP, KIQ, ring gfx/compute, MQD [VERIFICATO]

`amd/amdgpu/gfx_v12_0.c`.

**Firmware** (`gfx_v12_0_init_microcode`, 589-680): `gc_12_0_0_pfp.bin`, `_me.bin`, `_mec.bin` (header v2.0 =>
`rs64_enable = true`: CP RS64 a 64 bit, niente CE, niente jump table), `_rlc.bin` (su 12.0.1 eventualmente
`_rlc_kicker.bin`), `_toc.bin` solo per RLC_BACKDOOR_AUTO, IMU via `imu_v12_0_init_microcode`. Un solo MEC
(`mec2_fw = NULL`).

**Topologia code** (`gfx_v12_0_sw_init`, riga 1405, switch alle righe ~1413-1430): ME: 1 ME x 1 pipe x 8 queue; MEC: 1 MEC x 2 pipe x 4 queue.
`GFX12_NUM_GFX_RINGS = 1` (riga 50), compute ring = min(`amdgpu_num_kcq`=8, 2*4/2) = **4** (righe 1465-1470),
`GFX12_MEC_HPD_SIZE = 2048` (EOP buffer per coda). Coerente con i dump: `amdgpu_ring_gfx_0.0.0` +
`amdgpu_ring_comp_1.0.0/1.0.1/1.1.0/1.1.1`.

**Soglie firmware per funzionalita'** (`gfx_v12_0_sw_init`, righe ~1432-1460): user queue MES abilitate se ME >= 3090, PFP >= 3190,
MEC >= 3450, MES >= 147 (0x93); cleaner shader se ME >= 2480, PFP >= 2530, MEC >= 2680, MES >= 100. Con i
firmware installati (ME 0xc12 = 3090, PFP 0xc76 = 3190, MEC 0xd7a = 3450, MES 0x93 = 147) **siamo
esattamente sulla soglia delle user queue** [VERIFICATO aritmetica con `firmware_info.txt`].

**Golden registers** (`gfx_v12_0_init_golden_registers`, 3673-3693; tabelle 253-261) — **identici per 12.0.0
e 12.0.1**:
- sempre: `DB_MEM_CONFIG` mask 0x00008000 val 0x00008000;
- solo se `rev_id == 0`: `DB_MEM_CONFIG` 0xf/0xf, `CB_HW_CONTROL_1` 0x03000000/0x03000000,
  `GL2C_CTRL5` mask 0x70 val 0x20. **Questa scheda ha rev_id = 1, quindi il set rev0 NON si applica.**
- `soc15_program_register_sequence`: `reg = (reg & ~and_mask) | (or_mask & and_mask)` [formula standard di
  `soc15.c`, INFERITO non riletta qui].

**hw_init** (`gfx_v12_0_hw_init`, 3767-3860), in modalita' PSP:
1. `gfx_v12_0_wait_for_rlc_autoload_complete` (2331-2358).
2. golden registers; `is_poweron = true`.
3. `get_gb_addr_config` (3625-3660): legge `GB_ADDR_CONFIG` (dword 0x263e, byte 0x98f8) =
   **0x08200545** su questa scheda (dump), da cui `num_pipes`, `num_pkrs`, `num_rb_per_se`, `num_se`,
   `pipe_interleave_size`, `max_compress_frags`.
4. `gfx_v12_0_config_gfx_rs64` (2142-2230): per pipe 0/1 (via `soc24_grbm_select`) scrive
   `CP_PFP_PRGRM_CNTR_START = (start_hi << 30) | (start_lo >> 2)`, `CP_PFP_PRGRM_CNTR_START_HI = start_hi >> 2`,
   poi pulse `CP_ME_CNTL.PFP_PIPE0/1_RESET`; idem ME e MEC (`CP_MEC_RS64_PRGRM_CNTR_START`). Valori dal
   firmware: start = 0x0007_0000_0000_3000 per PFP, ME e MEC (sez. 3).
5. `gfx_v12_0_gfxhub_enable` (3603-3621): GART GFXHUB (sez. 2.3).
6. `gfx_v12_0_constants_init` (1824-1870): `GRBM_CNTL.READ_TIMEOUT = 0xff`, `setup_rb`, `get_cu_info`,
   `DB_RING_CONTROL.COUNTER_CONTROL = 1` (una sola pipe gfx), e per ogni VMID (via GRBM select):
   `SH_MEM_CONFIG = DEFAULT_SH_MEM_CONFIG` (ADDRESS_MODE_64, ALIGNMENT_MODE_UNALIGNED, INITIAL_INST_PREFETCH=3;
   righe 263-266), per VMID != 0 `SH_MEM_BASES` con PRIVATE_BASE = 0x1000 (aperture private
   0x1000000000000000) e SHARED_BASE = 0x2000 (`gmc_v12_0_early_init`, 659-672).
7. `nbif_v6_3_1_gc_doorbell_init` (S2A doorbell entry 0 e 3).
8. `gfx_v12_0_rlc_resume` (2104-2141): in PSP mode solo `gfx_v12_0_init_csb` (riga 1938; clear state buffer: indirizzo
   in `RLC_CSIB_ADDR_LO/HI`, `RLC_CSIB_LENGTH`) + `gfx_v12_0_rlc_enable_srm` (riga 2000).
9. `gfx_v12_0_tcp_harvest` (1815-1818): vuota ("harvest feature to be added later").
10. `gfx_v12_0_cp_resume` (3524-3590): disabilita GUI idle IRQ; `gfx_v12_0_cp_set_doorbell_range` (2988-3001):
    `CP_RB_DOORBELL_RANGE_LOWER/UPPER = (gfx_ring0*2)<<2 .. (gfx_userqueue_end*2)<<2` e
    `CP_MEC_DOORBELL_RANGE_LOWER/UPPER = (kiq*2)<<2 .. (userqueue_end*2)<<2`; con `amdgpu_async_gfx_ring=1`
    (default, `amdgpu_drv.c:223`) abilita subito CP compute e gfx; poi **`amdgpu_mes_kiq_hw_init`** (sez. 2.9:
    con MES la KIQ e' una pipe MES, il driver non usa mai la KIQ "classica"); `gfx_v12_0_kcq_resume`
    (3508-3522: MQD per i 4 KCQ + `amdgpu_gfx_enable_kcq` -> con `mes.enable_legacy_queue_map` diventa
    `amdgpu_gfx_mes_enable_kcq`, `amdgpu_gfx.c:744-745`); `gfx_v12_0_cp_async_gfx_ring_resume` (3130-3141: MQD
    gfx + `amdgpu_gfx_enable_kgq` -> `amdgpu_mes_map_legacy_queue`, `amdgpu_gfx.c:812-819`); ring test.

**CU attivi / harvest**: `gfx_v12_0_get_wgp_active_bitmap_per_sh` combina `CC_GC_SHADER_ARRAY_CONFIG`
(dword 0x226f, fuse) e `GC_USER_SHADER_ARRAY_CONFIG` (dword 0xfb90, override driver) per SE/SH selezionati
via `GRBM_GFX_INDEX` (dword 0xc200). Su Navi 44 completo: 4 WGP per SA => 8 CU.

**MQD** (`amd/include/v12_structs.h`): `struct v12_gfx_mqd` (riga 27), `struct v12_sdma_mqd` (542),
`struct v12_compute_mqd` (674). Init: `gfx_v12_0_gfx_mqd_init` (3003-3100), `gfx_v12_0_compute_mqd_init`
(3178-3300). Dump reali e decodificati in `research/hw_dump/mqd/decoded_*.txt` (es. compute:
`cp_hqd_pq_control=0xd030890a`, `cp_hqd_persistent_state=0x0be05501`,
`cp_hqd_pq_doorbell_control=0x60000018` -> DOORBELL_OFFSET = 6 dword = indice 64-bit 3 =
`AMDGPU_NAVI10_DOORBELL_MEC_RING0`, coerente con la sez. 4.1 [VERIFICATO incrocio dump/codice]).

### 2.9 MES v12 (uni-MES) [VERIFICATO]

`amd/amdgpu/mes_v12_0.c`, `amd/include/mes_v12_api_def.h`.

- Abilitazione (`amdgpu_discovery.c:2994-3001`): `enable_mes = enable_mes_kiq = true`; `amdgpu_uni_mes = 1`
  di default (`amdgpu_drv.c:227`) => `enable_uni_mes = true`.
- Firmware: entrambe le pipe caricano **`gc_12_0_0_uni_mes.bin`** (`amdgpu_mes.c:780-782`); versione = dword
  24 del payload & 0xfff = **0x93** (verificato sul file; i file `gc_12_0_0_mes.bin` = 0x50 e `_mes1.bin` = 0xa1
  sono usati solo con `uni_mes=0`). Start: `uc_start = 0xFFFFFFFF_F0005000`, `data_start = 0xFFFFFFFF_F0100000`.
- Pipe: `AMDGPU_MES_SCHED_PIPE = 0`, `AMDGPU_MES_KIQ_PIPE = 1` (`amdgpu_mes.h:61-68`); ring `me = 3`
  (`mes_v12_0_ring_init`, 1741-1749): nomi debugfs `mes_3.0.0` (sched) e `mes_3.1.0` (KIQ).
- `mes_v12_0_kiq_hw_init` (1956-2010), chiamato da `gfx_v12_0_cp_resume`:
  1. `mes_v12_0_kiq_setting`: `RLC_CP_SCHEDULERS = (3 << 5) | (1 << 3) | 0 | 0x80` (KIQ = me3/pipe1/queue0);
  2. `mes_v12_0_enable(true)` (1303-1365): per pipe 0 e 1: `soc24_grbm_select(3, pipe, 0, 0)`, opzionale
     `CP_MES_MSCRATCH_LO/HI` (log), `CP_MES_CNTL.MES_PIPEx_RESET = 1`,
     `CP_MES_PRGRM_CNTR_START/_HI = uc_start >> 2`, poi `CP_MES_CNTL = MES_PIPE0_ACTIVE (| MES_PIPE1_ACTIVE)`;
     attesa 500 us in uni-MES;
  3. `mes_v12_0_queue_init(KIQ)` (1682-1730): MQD MES (`mes_v12_0_mqd_init`, 1486) e programmazione diretta
     degli HQD registers della pipe KIQ (`mes_v12_0_queue_init_register`, 1595); legge `CP_MES_GP3_LO` =
     versione;
  4. uni-MES: `SET_HW_RSRC` + `SET_HW_RSRC_1` sulla pipe KIQ (maschere vuote: lo conferma il dump
     `rings/decoded_mes_3.1.0.txt`);
  5. `mes_v12_0_hw_init` (2036-2088): `enable_unmapped_doorbell_handling`, `queue_init(SCHED)` (MQD + in uni-MES
     `amdgpu_mes_map_legacy_queue` della coda scheduler **tramite la pipe KIQ**), `SET_HW_RSRC` sulla pipe sched
     (`mes_v12_0_set_hw_resources`, 936-1060: `vmid_mask_mmhub/gfxhub = 0xff00`, `gds_size`, `compute_hqd_mask`,
     `gfx_hqd_mask`, `sdma_hqd_mask`, `aggregated_doorbells[]`, `g_sch_ctx_gpu_mc_ptr`,
     `query_status_fence_gpu_mc_ptr`, **`gc_base[5]`, `mmhub_base[5]`, `osssys_base[5]` = le base della tabella
     discovery**, `disable_reset=1`, `use_different_vmid_compute=1`, `enable_reg_active_poll=1`,
     `oversubscription_timer = 50` (se rev >= 0x8b), `unmapped_doorbell_handling = 2`), `SET_HW_RSRC_1`
     (sched >= 0x4b), aggregated doorbell, `QUERY_SCHEDULER_STATUS`, enforce isolation.
- Valori nel dump del ring sched (`rings/decoded_mes_kiq_head.txt`): vmid_mask 0xff00, compute_hqd_mask 0x0c
  (MEC pipe0: code 2,3 libere per MES; 0,1 ai KCQ del kernel), gfx_hqd_mask 0xfe (coda 0 al KGQ), sdma_hqd_mask
  0xfc (code SDMA 0,1 al kernel) = dmesg.
- Mappatura code kernel (`mes_v12_0_map_legacy_queue`, 694-728): `MES_SCH_API_ADD_QUEUE` con `map_legacy_kq=1`,
  `pipe_id`, `queue_id`, `doorbell_offset`, `mqd_addr`, `wptr_addr`, `queue_type`. In uni-MES il sorgente 7.3
  manda la coda MES alla pipe KIQ e tutte le altre alla pipe sched; nel dump (kernel 7.2.9) gli `ADD_QUEUE`
  compaiono nel ring `mes_3.1.0` (KIQ) [INFERITO: differenza di versione del kernel; da tenere presente].
- Protocollo (`mes_v12_0_submit_pkt_and_poll_completion`, 152-300): ogni pacchetto API (64 dword,
  `API_FRAME_SIZE_IN_DWORDS`) porta `api_status.api_completion_fence_addr/value` (slot writeback); viene seguito
  da un `QUERY_SCHEDULER_STATUS` con fence del ring; commit (doorbell) e polling (timeout 2.1 s).
- Opcode (`mes_v12_api_def.h:50-71`): SET_HW_RSRC 0, SET_SCHEDULING_CONFIG 1, ADD_QUEUE 2, REMOVE_QUEUE 3,
  PERFORM_YIELD 4, SET_GANG_PRIORITY_LEVEL 5, SUSPEND 6, RESUME 7, RESET 8, SET_LOG_BUFFER 9,
  CHANGE_GANG_PRORITY 10, QUERY_SCHEDULER_STATUS 11, SET_DEBUG_VMID 13, MISC 14, UPDATE_ROOT_PAGE_TABLE 15,
  AMD_LOG 16, SET_SE_MODE 17, SET_GANG_SUBMIT 18, SET_HW_RSRC_1 19, INV_TLBS 20.

### 2.10 SDMA v7.0 (SDMA0/1 7.0.0) [VERIFICATO]

`amd/amdgpu/sdma_v7_0.c`:
- Firmware `sdma_7_0_0.bin`, header **v3.0** (un solo blob RS64 per entrambe le istanze) -> ucode
  `AMDGPU_UCODE_ID_SDMA_RS64` -> `GFX_FW_TYPE_SDMA_UCODE_TH0` (`amdgpu_sdma.c:291-295`).
- I registri SDMA stanno nello spazio GC: `sdma_v7_0_get_reg_offset` (125-141): base `GC[0]` (o `GC[1]` per il
  range HYP_DEC), istanza 1 = `+ SDMA1_REG_OFFSET`.
- `sdma_v7_0_start` (820-850, PSP mode): `sdma_v7_0_enable(true)`, `ctx_switch_enable(true)`,
  `sdma_v7_0_gfx_resume` -> `gfx_resume_instance` (474-630) per ogni istanza, queue0 programmata via MMIO:
  `SDMA0_QUEUE0_RB_CNTL` (RB_SIZE, RB_SWAP_ENABLE, RB_PRIV=1, RPTR_WRITEBACK_ENABLE, MCU_WPTR_POLL_ENABLE),
  `RB_RPTR/RPTR_HI/WPTR/WPTR_HI = 0`, `RB_RPTR_ADDR_LO/HI` (writeback), `RB_WPTR_POLL_ADDR_LO/HI`,
  `RB_BASE = gpu_addr >> 8`, `RB_BASE_HI = gpu_addr >> 40`, `MINOR_PTR_UPDATE` 1->0 attorno alla scrittura del
  wptr, `SDMA0_QUEUE0_DOORBELL.ENABLE=1`, `DOORBELL_OFFSET`, `nbio.sdma_doorbell_range(i, ..., 20*num_inst)`,
  `SDMA0_WATCHDOG_CNTL.QUEUE_HANG_COUNT`, `SDMA0_UTCL1_CNTL` (RESP_MODE=3, REDO_DELAY=9), `SDMA0_UTCL1_PAGE`,
  `SDMA0_MCU_CNTL` HALT=0 RESET=0, infine `RB_CNTL.RB_ENABLE=1` e `IB_CNTL`.
- Doorbell: `sDMA_ENGINE0 = 0x100`, `sDMA_ENGINE1 = 0x10A` (indici 64-bit, sez. 4.1).
- Reset per coda: `sdma_v7_0_reset_queue` -> `amdgpu_mes_reset_legacy_queue` (riga 801).

### 2.11 HDP v7.0 [VERIFICATO]

`amd/amdgpu/hdp_v7_0.c` (132 righe): solo clock gating (`HDP_CLK_CNTL`, `HDP_MEM_POWER_CTRL`) e
`flush_hdp = amdgpu_hdp_generic_flush` (`amdgpu_hdp.c:51-67`): da CPU scrive 0 a
`(rmmio_remap.reg_offset + KFD_MMIO_REMAP_HDP_MEM_FLUSH_CNTL) >> 2` (cioe' alla pagina remappata in fondo a
BAR5, byte 0x7F000 + 0) e rilegge `RCC_CONFIG_MEMSIZE` come barriera; da ring emette un `WRITE_DATA`/wreg allo
stesso indirizzo. I ring CP usano invece la coppia `GPU_HDP_FLUSH_REQ/DONE` con le maschere CPx/SDMAx (sez. 2.2).
`KFD_MMIO_REMAP_HDP_MEM_FLUSH_CNTL = 0`, `_REG_FLUSH_CNTL = 4` [INFERITO: definiti in
`include/uapi/linux/kfd_ioctl.h`, non presente nel clone sparse]. **Regola per il driver macOS**: dopo ogni
scrittura CPU in VRAM via BAR0 che la GPU deve vedere, flush HDP; dopo scritture GPU che la CPU legge via BAR0,
invalidazione HDP (`amdgpu_hdp_invalidate`).

### 2.12 SMU v14.0.2 (MP1 14.0.2) [VERIFICATO]

`amd/pm/swsmu/smu14/smu_v14_0_2_ppt.c`, `smu_v14_0.c`, `amd/pm/swsmu/amdgpu_smu.c`.

- **Mailbox** (`smu_v14_0_2_init_msg_ctl`, 2119-2140): messaggio `MP1_SMN_C2PMSG_66` (dword 0x16282),
  argomento `MP1_SMN_C2PMSG_82` (0x16292), risposta `MP1_SMN_C2PMSG_90` (0x1629a); **debug mailbox**:
  param `C2PMSG_53` (0x16275), msg `C2PMSG_75` (0x1628b), resp `C2PMSG_54` (0x16276). Timeout = 20 x usec_timeout.
- Protocollo `smu_msg_v1` (`smu_cmn.c:311-330`, 459-600): attendi che resp != 0 (messaggio precedente finito),
  `resp = 0`, scrivi arg, scrivi msg index, poll resp: `0x1 OK`, `0xFF Failed`, `0xFE UnknownCmd`,
  `0xFD CmdRejectedPrereq`, `0xFC CmdRejectedBusy` (`smu_v14_0_2_ppsmc.h:30-34`); il valore di ritorno si
  rilegge dal registro argomento. Debug msg: `param`, `msg`, poi `resp = 0` (`smu_cmn.c:96-98`).
- **driver_if**: `SMU14_DRIVER_IF_VERSION_SMU_V14_0_2 = 0x2E` (riga 74, assegnato a riga 2940; vale anche per
  14.0.3). dmesg: SMC 102.71.0, `driver_if 0x2e`, `fw_if 0x33`: il driver accetta il mismatch con un warning
  (`smu_cmn_check_fw_version`, `smu_cmn.c:1084`, agganciato a `smu_v14_0_2_ppt.c:2877`).
- Firmware: `smu_14_0_2.bin` v2.0 (start 0x20000, soft PPTable 5812 B @327424). Caricato via PSP come `SMU`;
  per 14.0.2 non si usa mai il custom pptable se SCPM (`smu_v14_0.c:176-183`); il PPTable effettivo e' letto
  dal PMFW con `TransferTableSmu2Dram(TABLE_COMBO_PPTABLE)` (`smu_v14_0_2_get_pptable_from_pmfw`, 336-352;
  `smu_cmn_get_combo_pptable`, `smu_cmn.c:1227`).
- **Sequenza `smu_hw_init`** (`amdgpu_smu.c:1955`): `smu_start_smc_engine` (1916-1953: `check_fw_status` =
  `MP1_FIRMWARE_FLAGS.INTERRUPTS_ENABLED` letto via SMN indiretto `MP1_Public | smnMP1_FIRMWARE_FLAGS` =
  0x03b00000 | 0x3010024, `smu_v14_0.c:219-226`; poi `smu_check_fw_version` con `GetDriverIfVersion`) ->
  allowed feature mask -> `smu_smc_hw_setup` (1698-1914): `set_driver_table_location`
  (`SetDriverDramAddrHigh/Low` 0xE/0xF), `set_tool_table_location` (0x10/0x11), `notify_memory_pool_location`,
  `setup_pptable`, (`write_pptable` / `run_btc`), `SetAllowedFeaturesMaskLow/High` (4/5), PCIe parameters,
  `EnableAllSmuFeatures` (6), lettura feature abilitate, default DPM table, soglie termiche, display change.
- **Set minimo di messaggi per il boot** [INFERITO dall'analisi della sequenza: il PMFW e' gia' in esecuzione
  dopo il POST]: `TestMessage` (0x1), `GetSmuVersion` (0x2), `GetDriverIfVersion` (0x3),
  `SetDriverDramAddrHigh/Low` (0xE/0xF), `TransferTableSmu2Dram` (0x12) per PPTable/metriche,
  `SetAllowedFeaturesMaskLow/High` (0x4/0x5), `EnableAllSmuFeatures` (0x6). Senza `EnableAllSmuFeatures` la GPU
  resta ai clock di boot (funziona, ma lenta) [INFERITO]. Per lo spegnimento: `PrepareMp1ForUnload` (0x2E).
- Altri ID utili: `UseDefaultPPTable 0x14`, `EnterBaco 0x15`, `ExitBaco 0x16`, `ArmD3 0x17`,
  `SetHardMinByFreq 0x1B`, `AllowGfxOff 0x28`, `DisallowGfxOff 0x29`, `PowerUpVcn 0x2A`,
  `SetSystemVirtualDramAddrHigh/Low 0x30/0x31`, `GetAllRunningSmuFeatures 0x54`; totale `PPSMC_Message_Count 0x59`.
- Solo 14.0.2: `smu_v14_0_2_enable_gfx_features` (2108-2116) invia `EnableAllSmuFeatures(FEATURE_PWR_GFX)`
  (ritorna -EOPNOTSUPP su 14.0.3). Solo 14.0.3: `energy_accumulator` nelle metriche con PMFW >= 0x00685000.

## 3. (c) Formati dei file firmware

Strumento: `/tmp/claude-1000/-home-pastasugo89-Documenti-rx9060xt-metal-driver/75517241-da08-4a95-9813-eba8a30820e6/scratchpad/bringup/scripts/fwhdr.py`
(scritto per questa analisi, layout da `amd/amdgpu/amdgpu_ucode.h`), eseguito sulle copie decompresse in
`.../scratchpad/bringup/fw/` (da `/usr/lib/firmware/amdgpu/*.bin.zst`). [VERIFICATO]

### 3.1 Header comune e varianti (`amd/amdgpu/amdgpu_ucode.h`)

`struct common_firmware_header` (righe 30-41, 32 byte): `size_bytes`, `header_size_bytes`,
`header_version_major/minor` (u16), `ip_version_major/minor` (u16), `ucode_version`, `ucode_size_bytes`,
`ucode_array_offset_bytes` (sempre 256 su questi file), `crc32`. Nota: il campo `crc32` **non** coincide con lo
zlib CRC32 del payload per nessun file tranne `vcn_5_0_0.bin` [VERIFICATO col mio script]; Linux non lo
controlla, quindi non va usato come checksum.

| Header | righe | campi dopo il common |
|---|---|---|
| `gfx_firmware_header_v2_0` (RS64 PFP/ME/MEC) | 189-199 | `ucode_feature_version`, `ucode_size_bytes`, `ucode_offset_bytes`, `data_size_bytes`, `data_offset_bytes`, `ucode_start_addr_lo/hi` |
| `rlc_firmware_header_v2_0/2_1/2_2` | 226-275 | v2.0: feature, jt, save/restore, CSD, liste registri; v2.1: `save_restore_list_{cntl,gpm,srm}_{ucode_ver,feature_ver,size,offset}`; v2.2: `rlc_iram/dram_ucode_size/offset` |
| `imu_firmware_header_v1_0` | 432-439 | `imu_iram_ucode_size/offset`, `imu_dram_ucode_size/offset` |
| `mes_firmware_header_v1_0` | 201-214 | `mes_ucode_version/size/offset`, `mes_ucode_data_version/size/offset`, `mes_uc_start_addr_lo/hi`, `mes_data_start_addr_lo/hi` |
| `sdma_firmware_header_v3_0` | 371-376 | `ucode_feature_version`, `ucode_offset_bytes`, `ucode_size_bytes` |
| `psp_firmware_header_v2_0` (sOS) | 136-141 | `psp_fw_bin_count` + array `psp_fw_bin_desc{fw_type, fw_version, offset_bytes, size_bytes}` (`enum psp_fw_type` 118-134) |
| `ta_firmware_header_v2_0` | 174-179 | `ta_fw_bin_count` + `psp_fw_bin_desc[]` (`enum ta_fw_type` 160-172) |
| `smc_firmware_header_v2_0` | 57-61 | `ucode_start_addr` (v1.0) + `ppt_offset_bytes`, `ppt_size_bytes` |
| `dmcub_firmware_header_v1_0` | 425-429 | `inst_const_bytes`, `bss_data_bytes` |

### 3.2 Contenuto dei firmware di Navi 44 (GC 12.0.0) [VERIFICATO]

Offset relativi all'inizio del payload (= file offset 256), salvo diversa indicazione.

| File (decompresso) | byte | hdr | ucode_version | dettagli |
|---|---|---|---|---|
| `gc_12_0_0_pfp.bin` | 354912 | gfx v2.0 | 0xc76 (3190) | feature 29; ucode 92512 B @256; data (stack) 262144 B @92768; start 0x0007_0000_0000_3000 |
| `gc_12_0_0_me.bin` | 463392 | gfx v2.0 | 0xc12 (3090) | feature 29; ucode 200992 B; data 262144 B; start idem |
| `gc_12_0_0_mec.bin` | 455648 | gfx v2.0 | 0xd7a (3450) | feature 29; ucode 193248 B; data 262144 B; start idem |
| `gc_12_0_0_rlc.bin` | 150704 | rlc v2.2 | 0xbde160 | feature 1000; RLC_G 25088 B @256; restore_list_size 314; SRLC 0 B; SRLG 2560 B @25344; SRLS 23472 B @27904; IRAM 66048 B @51376; DRAM 33280 B @117424 (offset dal file) |
| `gc_12_0_0_imu.bin` | 132352 | imu v1.0 | 0x0c2c2500 | IRAM 66048 B @0, DRAM 66048 B @66048 (dal payload) |
| `gc_12_0_0_uni_mes.bin` | 734432 | mes v1.0 | (hdr 0) fw 0x93 | ucode 209888 B @256; data 524288 B @210144; uc_start 0xFFFFFFFF_F0005000; data_start 0xFFFFFFFF_F0100000 |
| `gc_12_0_0_mes.bin` | 636048 | mes v1.0 | fw 0x50 | ucode 111504 B; data 524288 B (solo con `uni_mes=0`) |
| `gc_12_0_0_mes1.bin` | 609840 | mes v1.0 | fw 0xa1 | ucode 85296 B; data 524288 B (KIQ, solo con `uni_mes=0`) |
| `gc_12_0_0_toc.bin` | 2048 | psp v1.0 | 0xb | TOC RLC autoload (0x700 B), solo backdoor |
| `sdma_7_0_0.bin` | 47872 | sdma v3.0 | 0x00798e96 | feature 813272726; ucode 47616 B @256 |
| `psp_14_0_2_sos.bin` | 421216 | psp v2.0 | 0x003b0f0d | 9 bin: KDB (0x703b0001, 6816 B), SYS_DRV (78272 B), **SOS** (125472 B), SOC_DRV (103792 B), INTF_DRV (37280 B), DBG_DRV (53344 B), TOC (2304 B), IPKEYMGR_DRV (12848 B), SPL (0x01003b00, 832 B) |
| `psp_14_0_2_ta.bin` | 274668 | ta v2.0 | - | ASD 0x21000118 (243488 B), HDCP 0x17000053 (25220 B), DTM 0x1200001f (5704 B) |
| `smu_14_0_2.bin` | 333236 | smc v2.0 | 0x00664700 (102.71.0) | ucode 327168 B, start 0x20000; soft PPTable 5812 B @327424 |
| `dcn_4_0_1_dmcub.bin` | 368032 | dmcub v1.0 | 0x0a004b00 | inst_const 367776 B, bss 0 |
| `vcn_5_0_0.bin` | 438288 | common v1.0 | 0x0910c01a | |

Tutte le versioni coincidono con `research/hw_dump/firmware_info.txt` (ME 0xc12, PFP 0xc76, MEC 0xd7a, RLC
0x00bde160, IMU 0x0c2c2500, SOS 0x003b0f0d, ASD 0x21000118, HDCP 0x17000053, DTM 0x1200001f, SMC 0x00664700,
SDMA 0x00798e96, MES/MES_KIQ 0x93, DMCUB 0x0a004b00, VCN 0x0910c01a): **il firmware sul disco e' quello
effettivamente caricato** (incluso uni-MES).

Come Linux spezza i file in "ucode" da passare al PSP: `amdgpu_ucode_init_single_fw()` (`amd/amdgpu/amdgpu_ucode.c:851`) calcola, per ciascun `AMDGPU_UCODE_ID_*`, puntatore e dimensione dentro il file
usando i campi sopra (es. `CP_RS64_PFP` = `ucode_offset/size`, `CP_RS64_PFP_P0_STACK` = `data_offset/size`;
`RLC_IRAM/DRAM` dai campi v2.2; `IMU_I/IMU_D` dai campi imu; `CP_MES`/`CP_MES_DATA` dai campi mes) e li copia
allineati a pagina in un unico BO (`amdgpu_ucode_create_bo` riga 1148, `amdgpu_ucode_init_bo` riga 1175, chiamato da `psp_hw_init`).

### 3.3 Confronto con i firmware Navi 48 (GC 12.0.1) [VERIFICATO]

| File 12.0.1 | ucode_version | differenze vs 12.0.0 |
|---|---|---|
| `gc_12_0_1_pfp.bin` | 0xc76 | stessa versione, stessa dimensione |
| `gc_12_0_1_me.bin` | 0xc12 | stessa versione, ucode 201024 B (vs 200992): binario diverso |
| `gc_12_0_1_mec.bin` | 0xd7a | stessa versione, ucode 189152 B (vs 193248) |
| `gc_12_0_1_rlc.bin` / `_rlc_kicker.bin` | 0xbe7da0 / 0xbe7e04 | SRLS 23616 B; offset IRAM/DRAM spostati |
| `gc_12_0_1_imu.bin` / `_imu_kicker.bin` | 0x0c302b00 | IMU diverso |
| `gc_12_0_1_mes.bin` / `_mes1.bin` | fw 0x55 / 0xb2 | |
| `sdma_7_0_1.bin` | 0x00798e96 | stessa versione, ucode 46848 B (vs 47616) |
| `psp_14_0_3_sos.bin` | 0x003a1214 | 11 bin: in piu' **RAS_DRV** e **RL** |
| `smu_14_0_3.bin` | 0x00685000 (104.80.0) | PMFW diverso |

Conclusione: **nessun firmware Navi 48 e' riutilizzabile su Navi 44**, anche dove la versione coincide (i
binari differiscono, e il PSP 14.0.2 verifica le firme). Un port (es. Cobalt64) che carica `gc_12_0_1_*` o
`psp_14_0_3_*` non funzionera' su questa scheda senza cambiare il set di file.

## 4. (d) Doorbell, metodi di reset, recupero da hang

### 4.1 Layout doorbell soc24 [VERIFICATO]

BAR2 = aperture doorbell (256 MiB su questa scheda), ogni doorbell e' una dword; Linux usa indici "64-bit"
(`enum AMDGPU_NAVI10_DOORBELL_ASSIGNMENT`, `amd/amdgpu/amdgpu_doorbell.h:186-236`) e li moltiplica per 2 per
ottenere l'indice in dword (`ring->doorbell_index = idx << 1`); offset in byte in BAR2 = idx64 * 8.
`soc24_init_doorbell_index` (`soc24.c:267-300`) usa la tabella Navi10:

| uso | idx64 | dword | byte BAR2 |
|---|---|---|---|
| KIQ | 0x000 | 0x000 | 0x0000 |
| HIQ / DIQ | 0x001 / 0x002 | | |
| MEC_RING0..7 (KCQ) | 0x003..0x00A | 0x006..0x014 | 0x0018.. |
| MES_RING0 / MES_RING1 | 0x00B / 0x00C | 0x016 / 0x018 | 0x0058 / 0x0060 |
| USERQUEUE_START..END (compute) | 0x00D..0x08A | | |
| GFX_RING0 / GFX_RING1 | 0x08B / 0x08C | 0x116 / 0x118 | 0x0458 |
| GFX_USERQUEUE_START..END | 0x08D..0x0FF | | |
| sDMA_ENGINE0 / 1 | 0x100 / 0x10A | 0x200 / 0x214 | 0x0800 / 0x0850 |
| IH (ring0), IH1 = IH+1 | 0x178 | 0x2F0 | 0x0BC0 |
| VCN0_1 .. VCNe_f | 0x188..0x18F | | |
| VPE / MAX_ASSIGNMENT | 0x190 | | |

`max_assignment = 0x190 << 1`, `sdma_doorbell_range = 20` (dword per istanza). Allocazione
(`amd/amdgpu/amdgpu_doorbell_mgr.c`): `num_kernel_doorbells = min(BAR2/4, max_assignment+1) + 0x400`
(righe 211-227), arrotondato a pagina = 2 pagine = 0x800 dword, poi **una pagina extra per MES**:
`mes.db_start_dw_offset = 0x800` (righe 159-163) e `aggregated_doorbells[prio] = 0x800 + 2*prio`
(`amdgpu_mes.c:54-57`). Il dump del ring MES conferma `aggregated_doorbells = 0x800, 0x802, 0x804, 0x806,
0x808` [VERIFICATO]. Le doorbell delle user queue/processi vengono allocate a pagine dopo questa zona.

Programmazione hardware necessaria perche' le doorbell funzionino:
1. `RCC_DEV0_EPF0_RCC_DOORBELL_APER_EN.BIF_DOORBELL_APER_EN = 1` (`soc24_common_hw_init`);
2. range S2A in NBIF: entry0 (CP) `0x30000007`, entry3 `0x3000000d` (`gc_doorbell_init`), entry1 (IH),
   entry2 (SDMA) (sez. 2.2);
3. range CP: `CP_RB_DOORBELL_RANGE_LOWER/UPPER` e `CP_MEC_DOORBELL_RANGE_LOWER/UPPER` (sez. 2.8);
4. per ogni coda: `CP_HQD_PQ_DOORBELL_CONTROL` nella MQD (DOORBELL_OFFSET in dword, DOORBELL_EN) o
   `SDMA0_QUEUE0_DOORBELL(_OFFSET)`, `IH_DOORBELL_RPTR`;
5. self-ring aperture (`BIF_BX_PF0_DOORBELL_SELFRING_GPA_APER_*`) per le doorbell scritte dalla GPU stessa
   (es. MES), in `late_init`;
6. MES: `enable_unmapped_doorbell_handling` + `unmapped_doorbell_handling = 2` in SET_HW_RSRC (una doorbell su
   coda non mappata sveglia MES).

### 4.2 Metodi di reset per questo ASIC [VERIFICATO]

- `soc24_asic_reset_method` (`soc24.c:173-196`): con MP1 14.0.2/14.0.3 il default e' **MODE1** (BACO solo se
  forzato via `amdgpu_reset_method`). Il dump sysfs `reset_method` = `bus` e' l'attributo PCI-core
  (solo Secondary Bus Reset disponibile, niente FLR) [VERIFICATO in `hw_dump/sysfs_power.txt:69-70`]; le maschere
  `gfx/compute/sdma_reset_mask = queue full` indicano reset per-coda e completo supportati.
- **Mode1 via SMU** (`amdgpu_device_mode1_reset`, `amdgpu_device.c:4937`; `smu_v14_0_2_mode1_reset`,
  `smu_v14_0_2_ppt.c:2079-2097`): `amdgpu_atombios_scratch_regs_engine_hung(true)`, salva PCI config,
  `pci_clear_master`, poi messaggio sulla **debug mailbox**: `C2PMSG_53 = 0` (param), `C2PMSG_75 =
  DEBUGSMC_MSG_Mode1Reset (2)`, `C2PMSG_54 = 0`; `no_hw_access = true`, `msleep(1000)`. Poi ripristino PCI
  config, `amdgpu_psp_wait_for_bootloader` (C2PMSG_35 bit31), attesa che `RCC_CONFIG_MEMSIZE != 0xffffffff`,
  scratch "engine hung" = false. `smu_v14_0_2_is_mode1_reset_supported` ritorna sempre true (1908-1913).
- Alternativa PSP: `psp_gpu_reset` -> `psp_mode1_reset` (`amdgpu_psp.c:3888-3900`), usata solo se lo SMU non
  supporta mode1.
- BACO (`smu_v14_0_2_baco_enter/exit`, 1883-1906; feature PMFW `BACO`, `BACO_MPCLK_DS`, `BACO_CG` attive in
  `hw_dump/pp_features.txt`): usato da Linux per runtime PM, non come reset di default.
- Mode2: `smu_v14_0_2_mode2_reset` e' un TODO vuoto (2099-2104): **non esiste un reset "leggero" del solo GFX**
  su questo ASIC in Linux.
- Reset per coda (soft recovery, prima scelta in `amdgpu_job_timedout`): gfx `gfx_v12_0_reset_kgq` ->
  `amdgpu_gfx_mes_reset_queue`, compute `gfx_v12_0_reset_kcq` -> `amdgpu_gfx_reset_mes_compute`
  (`gfx_v12_0.c:5306-5322`), SDMA `sdma_v7_0_reset_queue` -> `amdgpu_mes_reset_legacy_queue` (`sdma_v7_0.c:801`):
  tutti passano da MES (`MES_SCH_API_RESET` / `RESET` legacy queue).

### 4.3 Cosa serve per recuperare una GPU appesa [VERIFICATO sequenza; INFERITO adattamento macOS]

Sequenza Linux dopo un full reset (`amdgpu_device_reinit_after_reset`, `amdgpu_device.c:5116-5215`):
1. `amdgpu_device_asic_init` -> attesa bootloader PSP + **AtomBIOS `asic_init`** (riesegue l'init della
   memoria/clock di boot dal VBIOS);
2. `ip_resume_phase1` (COMMON, GMC, IH), controllo "VRAM lost" (`amdgpu_device_check_vram_lost`, riga 2577: confronta
   un magic scritto in VRAM; dopo mode1 la VRAM e' di norma persa);
3. `amdgpu_device_fw_loading`: **di nuovo tutto il boot PSP** (il sOS muore con mode1: KDB..SOS, ring, LOAD_IP_FW
   di tutti i firmware, AUTOLOAD_RLC) e SMU;
4. `ip_resume_phase2/3` (SMU, DM, GFX, SDMA, MES...), late init, ripristino delle page table/BO in VRAM.

Implicazioni per un kext macOS: (a) serve un interprete AtomBIOS (o almeno l'esecuzione della command table
`asic_init`) per il recupero, oppure si accetta che un hang richieda il riavvio; (b) tutto lo stato in VRAM
(page table, ring, MQD, firmware BO) deve essere ricostruibile da RAM di sistema; (c) l'ordine e' lo stesso del
primo boot, quindi conviene implementare il bring-up come funzione rieseguibile. Prima ancora del reset completo,
il reset per-coda via MES copre i casi comuni (shader in loop, page fault).

## 5. (e) Differenze GC 12.0.0 (Navi 44) vs GC 12.0.1 (Navi 48) nel codice

Metodo: script `.../scratchpad/bringup/scripts/unpaired.py` che elenca ogni `IP_VERSION(12, 0, 0)` senza un
`IP_VERSION(12, 0, 1)` entro +-3 righe (e viceversa) in tutto `drivers/gpu/drm/amd`, piu' lo stesso per
MP 14.0.2/14.0.3 e controllo manuale di SDMA 7.0.0/7.0.1. I falsi positivi (MP0 12.0.1 = Renoir, UMC 12.0.0 =
MI300, confronti `>=`) sono stati scartati. [VERIFICATO]

### 5.1 Differenze reali

| Area | GC 12.0.0 / Navi 44 (questa scheda) | GC 12.0.1 / Navi 48 | Dove |
|---|---|---|---|
| External rev id | `rev_id + 0x40` (qui 0x41) | `rev_id + 0x50` | `soc24.c:349-366` vs `368-386` |
| PG flags | VCN, JPEG, VCN_DPG | + **JPEG_DPG** | `soc24.c:363-365` vs `382-385` |
| CG flags | identici | identici | `soc24.c:350-362` |
| Golden GC | `golden_settings_gc_12_0` (+ `_rev0` se rev_id==0) | identico | `gfx_v12_0.c:253-261, 3673-3693` |
| IRQ ECC DF | `SOC21_IH_CLIENTID_DF` | `SOC_V1_0_IH_CLIENTID_DF` (stesso valore 0x17) | `gmc_v12_0.c:898-904` |
| Target KFD/ISA | `gfx_target_version = 120000` (**gfx1200**) | 120001 (**gfx1201**) | `amdkfd/kfd_device.c:464-471` |
| Firmware GC | `gc_12_0_0_{pfp,me,mec,rlc,toc,imu,mes,mes1,uni_mes}.bin` | `gc_12_0_1_*` + `gc_12_0_1_rlc_kicker.bin`, `gc_12_0_1_imu_kicker.bin` | `gfx_v12_0.c:73-83`, `imu_v12_0.c:35-37`, `mes_v12_0.c:36-41` |
| Firmware PSP | `psp_14_0_2_{sos,ta}.bin` (MP0 14.0.2) | `psp_14_0_3_{sos,ta}.bin` + `_kicker` | `psp_v14_0.c:34-39` |
| Firmware SMU | `smu_14_0_2.bin` (MP1 14.0.2) | `smu_14_0_3.bin` + `smu_14_0_3_kicker.bin` | `smu_v14_0.c:63-65, 83-88` |
| Firmware SDMA | `sdma_7_0_0.bin` (SDMA 7.0.0) | `sdma_7_0_1.bin` (SDMA 7.0.1); stesso driver `sdma_v7_0` | `sdma_v7_0.c:48-49, 1355-1356` |
| Firmware DCN/VCN | `dcn_4_0_1_dmcub.bin`, `vcn_5_0_0.bin` | stessi | |
| Kicker firmware | **mai**: 0x7590 non e' in `kicker_device_list` | solo device 0x7551 rev 0xC8 (`{0x744B,0x00}` e' Navi 31) | `amdgpu_ucode.c:33-36, 1432-1443` |
| PSP fw reservation | attiva con sOS >= 0x3b0e0d | attiva con sOS >= 0x3a0e14 | `amdgpu_psp.c:1077-1086` |
| Contenuto sOS | 9 bin (niente RAS_DRV, RL) | 11 bin (+RAS_DRV, +RL) | sez. 3.3 |
| RAS | MP0 14.0.2 **non** in `amdgpu_ras_asic_supported` | MP0 14.0.3 supportato | `amdgpu_ras.c:3298-3310` |
| SMU gfx features | `smu_v14_0_2_enable_gfx_features` -> `EnableAllSmuFeatures(FEATURE_PWR_GFX)` | -EOPNOTSUPP | `smu_v14_0_2_ppt.c:2108-2116` |
| SMU metriche | - | `energy_accumulator` se PMFW >= 0x00685000 | `smu_v14_0_2_ppt.c:2175-2176` |
| DCC alignment | funzione comune, ma dipende da `max_texture_channel_caches` = 16 => 64 KiB | stessa formula, valore da discovery | `gmc_v12_0.c:556-571` |
| Topologia | 2 SE, 4 SA, 32 CU, 8 RB, 16 GL2C, 4 UMC, 32 MiB MALL | [INFERITO dalle specifiche] 4 SE, 64 CU, 16 RB, 8 UMC, 64 MiB MALL | tutto da IP discovery (sez. 1.5), nessuna costante nel codice |
| IMU RLC RAM golden (solo backdoor) | usa `imu_rlc_ram_golden_12_0_1` | idem | `imu_v12_0.c:177-255, 367-398` |
| DMU/DCN | DMU 4.1.0 -> DCN 4.0.1 | identico | `amdgpu_discovery.c:2684-2690` |

### 5.2 Cio' che e' identico (e quindi riusabile da un port Navi 48)

Selezione degli IP block (soc24, gmc_v12_0 + mmhub_v4_1_0 + gfxhub_v12_0, ih_v7_0, psp_v14_0, smu_v14_0
con `smu_v14_0_2_ppt`, dm/dcn401, gfx_v12_0, sdma_v7_0, mes_v12_0), sequenze di init, layout PTE, doorbell,
MQD v12, protocollo PSP/SMU/MES, golden registers, topologia ME/MEC (1x1x8, 1x2x4), soglie firmware per user
queue/cleaner shader, metodo di reset (mode1 via SMU). Le differenze sono quasi tutte **dati** (nomi firmware,
tabella discovery, rev id) e non logica.

### 5.3 Attenzione ai riferimenti terzi

`research/refs/Cobalt64/src/navi48-bringup/src/amd/amdgpu_ip.h:28-41` (codice non verificato) dichiara
"GC 12.0.1 -> gfx_v12_1" e "SDMA 7.0.1 -> sdma_v7_1": **nel kernel non e' cosi'** (12.0.1 usa `gfx_v12_0`,
`amdgpu_discovery.c:2772-2774`; SDMA 7.0.1 usa `sdma_v7_0`, righe 2833-2835; `gfx_v12_1`/`sdma_v7_1` sono per
GC 12.1.0 / SDMA 7.1.0, cioe' MI4xx). Indica anche "NBIO 7.11" per Navi 48, mentre su Navi 44 la discovery
dice NBIF 6.3.1 (stesso driver `nbif_v6_3_1` per 6.3.1 e 7.11.4/7.11.5, con varianti di registro per >= 7.11.4,
sez. 2.2). Inoltre Cobalt64 incorpora i firmware `psp_14_0_3_*`, `smu_14_0_3*`, `gc_12_0_1_*`: su Navi 44 vanno
sostituiti con il set 14_0_2 / 12_0_0.

## 6. Checklist minima di bring-up per un driver IOKit (macOS) su Navi 44

Indirizzi = dword in BAR5 (byte = dword x 4) calcolati con le base della tabella discovery di questa scheda;
tutti < 0x20000 (accesso diretto) salvo dove indicato "SMN" (indiretto via `BIF_BX_PF0_RSMU_INDEX/DATA`,
dword 0x14/0x15). Ogni passo cita la funzione Linux di riferimento. Le marcature [V]/[I] = verificato/inferito.

### Fase A - PCI e scoperta
1. **Attach PCI** 1002:7590: abilita memory space + bus master; mappa BAR0 (VRAM 16 GiB, ReBAR), BAR2 (doorbell
   256 MiB), BAR5 (MMIO 512 KiB). Salva la PCI config per i reset. [V `amdgpu_device.c:3908-3917`]
2. **Stato iniziale**: leggi `MPASP_SMN_C2PMSG_81` (0x16091). Se != 0 il sOS e' gia' vivo (driver precedente):
   esegui un mode1 reset (passo R) prima di proseguire. [V `soc24.c:242-257`]
3. **POST**: verifica `BIOS_SCRATCH_7` (base scratch dal VBIOS `firmwareinfo` v3.5 =
   `bios_scratch_reg_startaddr` 0x4c => SCRATCH_7 = 0x53) bit `ATOM_S7_ASIC_INIT_COMPLETE_MASK` (0x200, `amd/include/atombios.h:7075`); con boot UEFI+GOP
   deve essere gia' settato. Altrimenti serve eseguire la command table AtomBIOS `asic_init` v2.1 (offset
   0x2764 nel `vbios.rom` dumpato) dopo aver atteso il bootloader PSP. [V lettura VBIOS con
   `.../scripts/atomfw.py`; `amdgpu_atombios.c:1634-1642`, `amdgpu_device.c:958-985`]
4. **Attesa IFWI**: `MP0_SMN_C2PMSG_33` (0x16061) bit31 = 1. [V `amdgpu_discovery.c:304-309`]
5. **IP discovery**: `RCC_CONFIG_MEMSIZE` (0xde3) in MB (atteso 16304); leggi 10 KiB a VRAM offset
   `memsize*1MiB - 64 KiB` (= 0x3_FAFF_0000) via BAR0; verifica signature 0x28211407 e checksum; costruisci `reg_offset[ip][inst][base_idx]` e le
   versioni. Rimappa DMU 4.1.0 -> DCN 4.0.1. Riserva gli ultimi 64 KiB di VRAM. [V sez. 1]
6. Leggi `MMMC_VM_FB_LOCATION_BASE` (0x1a554) -> `fb_start = (val & FB_BASE) << 24` (= 0x80_0000_0000, uguale
   a `mc_baseaddr_high = 0x80` nel VBIOS) e `MMMC_VM_FB_OFFSET` (0x1a4c7) << 24. [V]

### Fase B - common / NBIF / memoria
7. `soc24_common_early_init` + `hw_init`: ASPM opzionale; `RCC_DEV0_EPF2_STRAP2` (SMN) clear
   `STRAP_NO_SOFT_RESET_DEV0_F2`; HDP remap: `BIF_BX0_REMAP_HDP_MEM_FLUSH_CNTL` (0xe4d) = 0x7F000 + 0,
   `BIF_BX0_REMAP_HDP_REG_FLUSH_CNTL` (0xe4e) = 0x7F000 + 4; `RCC_DEV0_EPF0_RCC_DOORBELL_APER_EN` (0xde0) = 1.
   [V sez. 2.1-2.2]
8. Alloca in VRAM: pagina scratch (default page del system aperture), GART table (512 MiB -> 1 MiB di PTE,
   flag `MTYPE_UC|EXECUTABLE|IS_PTE|VALID|SYSTEM|SNOOPED` per pagine host), dummy page in RAM host. [V sez. 2.3]
9. **GART MMHUB** (`mmhub_v4_1_0_gart_enable`): aperture regs, system aperture, `MMMC_VM_MX_L1_TLB_CNTL`
   (0x1a55b), `MMVM_L2_CNTL..CNTL5` (0x1a4e4..), `MMVM_CONTEXT0_CNTL` (0x1a564) enable depth 0, identity aperture
   off, VMID1-15 `MMVM_CONTEXT1_CNTL` (0x1a565 + i*distance) depth 3, invalidation range engine 0..17; flush HDP;
   invalidazione TLB con engine 17 (`MMVM_INVALIDATE_ENG17_SEM/REQ/ACK` 0x1a586/0x1a598/0x1a5aa). [V sez. 2.3]
10. Writeback page in GTT (rptr/wptr/fence slots). [V `amdgpu_wb_init`]

### Fase C - interrupt
11. **IH v7**: ring 256 KiB in memoria GPU; `BIF_BX0_INTERRUPT_CNTL2` (0xe12) = dummy >> 8, `INTERRUPT_CNTL`
    (0xe11); `IH_RB_BASE/BASE_HI` (0x1123/0x1124), `IH_RB_CNTL` (0x1120: MC_SPACE=4, RB_SIZE, WPTR_WRITEBACK,
    MC_SNOOP, overflow), `IH_RB_WPTR_ADDR_LO/HI` (0x1126/0x1125), `IH_RB_RPTR/WPTR = 0`, `IH_DOORBELL_RPTR`
    (0x1127, offset 0x178<<1, enable), NBIF `GDC_S2A0_S2A_DOORBELL_ENTRY_1_CTRL` (0xeec); storm/flood control;
    abilita `RB_ENABLE`/`ENABLE_INTR`; MSI/MSI-X lato IOKit. Test con self-IRQ (client 0 src 0). [V sez. 2.5]

### Fase D - PSP e firmware
12. Buffer PSP in VRAM: `fw_pri` 1 MiB allineato 1 MiB, ring KM (frame da 64 B), cmd buffer 4 KiB, fence 4 KiB.
13. **Boot sOS** (`psp_hw_start`): per KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV, DBG_DRV, IPKEYMGR_DRV (da
    `psp_14_0_2_sos.bin`): attendi `C2PMSG_35` (0x16063) bit31, copia il bin in `fw_pri`,
    `C2PMSG_36` (0x16064) = `fw_pri_mc >> 20`, `C2PMSG_35` = comando (0x80000, 0x10000000, 0x10000, 0xB0000,
    0xD0000, 0xC0000, 0xF0000), riattendi bit31. Infine SOS con 0x20000, poi attendi che `C2PMSG_81` (0x16091)
    cambi. [V sez. 2.6]
14. **Ring KM**: attendi `C2PMSG_64` (0x16080) ready (bit31, status 0); `C2PMSG_69/70` (0x16085/0x16086) =
    ring MC lo/hi, `C2PMSG_71` (0x16087) = size, `C2PMSG_64 = 0x20000`; attendi risposta. Wptr in
    `C2PMSG_67` (0x16083). [V]
15. `GFX_CMD_ID_FB_FW_RESERV_ADDR` (0x50) e `_EXT_ADDR` (0x51): riserva quelle regioni in cima alla VRAM.
    Niente `SETUP_TMR` (TMR di boot). [V `amdgpu_psp.c:1059-1121, 931-939`]
16. **LOAD_IP_FW** (cmd 6) in quest'ordine: SMU (18), SDMA_UCODE_TH0 (71), RS64_PFP (87), RS64_ME (88),
    RS64_MEC (89), RS64_PFP_P0_STACK (90), RS64_ME_P0_STACK (92), RS64_MEC_P0/P1_STACK (94/95), CP_MES (33) +
    MES_STACK (34) e CP_MES_KIQ (81) + MES_KIQ_STACK (82) da `gc_12_0_0_uni_mes.bin`, IMU_I/IMU_D (68/69),
    RLC restore list GPM/SRM (20/21), RLC_IRAM (26), RLC_DRAM_BOOT (48), RLC_G (8) **seguito da
    `GFX_CMD_ID_AUTOLOAD_RLC` (0x21)**, DMUB (51) se si usa il display, VCN (13) opzionale. Ogni immagine in un
    buffer allineato 4 KiB in VRAM (o GTT). [V sez. 2.6]
17. (Opzionale per il minimo) TA ASD (`LOAD_ASD`); HDCP/DTM solo per HDCP. [V]

### Fase E - SMU
18. `MP1_FIRMWARE_FLAGS` (SMN 0x03b00000|0x3010024) bit INTERRUPTS_ENABLED = 1. [V]
19. Mailbox (msg 0x16282, arg 0x16292, resp 0x1629a): `TestMessage` (1), `GetSmuVersion` (2) atteso 0x00664700,
    `GetDriverIfVersion` (3) (driver 0x2E, fw 0x33: mismatch tollerato), `SetDriverDramAddrHigh/Low` (0xE/0xF)
    con un buffer tabelle in VRAM/GTT, `TransferTableSmu2Dram` (0x12) del COMBO_PPTABLE, `SetAllowedFeaturesMask
    Low/High` (4/5), `EnableAllSmuFeatures` (6). Senza i passi 19b la GPU resta ai clock di boot. [V sequenza /
    I minimo indispensabile]

### Fase F - GFX
20. Attendi `CP_STAT` (0x21a0) == 0 e `RLC_RLCS_BOOTLOAD_STATUS.BOOTLOAD_COMPLETE` (0xee7c). [V]
21. Golden: `DB_MEM_CONFIG` |= 0x8000 (il set rev0 non serve: rev_id = 1). Leggi `GB_ADDR_CONFIG` (0x263e)
    = 0x08200545. [V]
22. RS64 start PC: per pipe 0/1 (`GRBM_GFX_CNTL` 0xa900 per selezionare me/pipe/queue/vmid)
    `CP_PFP_PRGRM_CNTR_START` (0x30a4) = 0xC00, `_HI` (0x30b9) = 0x1C000, idem ME (0x30a5) e MEC
    (`CP_MEC_RS64_PRGRM_CNTR_START` 0xc900), con pulse dei bit PIPEx_RESET in `CP_ME_CNTL` (0xa803) /
    `CP_MEC_RS64_CNTL` (0xc904). [V `gfx_v12_0.c:2142-2230`]
23. **GART GFXHUB** (stessa sequenza del passo 9 sui registri `GCVM_*`/`GCMC_*`: 0x2824.., 0x2884.., 0x28b8..).
24. `GRBM_CNTL.READ_TIMEOUT = 0xff` (0x2000); `SH_MEM_CONFIG` (0xa9e4) / `SH_MEM_BASES` (0xa9e3) per VMID;
    NBIF `S2A_DOORBELL_ENTRY_0/3` = 0x30000007/0x3000000d; CSB (`RLC_CSIB_ADDR_LO/HI/LENGTH`, 0xa987/0xa988/0xa989); SRM
    enable. [V]
25. `CP_RB_DOORBELL_RANGE_LOWER/UPPER` (0x305a/0x305b) = 0x458 / 0x7f8, `CP_MEC_DOORBELL_RANGE_LOWER/UPPER`
    (0x305c/0x305d) = 0x0 / 0x450 (`(idx*2)<<2`: gfx_ring0 0x8B, gfx_userqueue_end 0xFF, kiq 0, userqueue_end
    0x8A). [V formula `gfx_v12_0.c:2988-3001`; valori calcolati]

### Fase G - MES e code
26. `RLC_CP_SCHEDULERS` (0xa98a) = 0x80 | (3<<5) | (1<<3) = 0xE8 (KIQ = MES pipe 1). [V]
27. `mes_v12_0_enable`: per pipe 0 e 1 (`GRBM_GFX_CNTL` me=3, pipe), `CP_MES_CNTL` (0xc807) PIPEx_RESET,
    `CP_MES_PRGRM_CNTR_START/_HI` (0xc800/0xc89d) = 0xFFFFFFFF_F0005000 >> 2 (lo 0xFC001400, hi 0x3FFFFFFF), poi `CP_MES_CNTL` =
    MES_PIPE0_ACTIVE|MES_PIPE1_ACTIVE; attesa 500 us. Versione in `CP_MES_GP3_LO` (0xc849). [V]
28. Pipe KIQ: MQD MES + programmazione diretta HQD; `SET_HW_RSRC` + `SET_HW_RSRC_1` (maschere vuote). [V]
29. Pipe sched: MQD; `ADD_QUEUE(map_legacy_kq=1, queue_type=MES)` inviato sulla pipe KIQ; poi `SET_HW_RSRC`
    con vmid_mask 0xff00, gfx_hqd 0xfe, compute_hqd 0x0c, sdma_hqd 0xfc, aggregated doorbells 0x800..0x808,
    `gc_base/mmhub_base/osssys_base` = base discovery; `SET_HW_RSRC_1`; `QUERY_SCHEDULER_STATUS`. Ogni pacchetto
    con fence di completamento in writeback. [V sez. 2.9]
30. Mappa le code kernel via MES `ADD_QUEUE(map_legacy_kq=1)`: almeno 1 compute (MEC pipe 0 queue 0, doorbell
    0x003<<1, MQD `v12_compute_mqd`, EOP 2 KiB), 1 gfx (doorbell 0x08B<<1, MQD `v12_gfx_mqd`), SDMA0 queue0
    programmata via MMIO (passo 31). [V]
31. SDMA0: `SDMA0_QUEUE0_RB_*` (base GC, offset per istanza), doorbell 0x100<<1, `nbio.sdma_doorbell_range`
    (`GDC_S2A0_S2A_DOORBELL_ENTRY_2_CTRL` 0xeed), `SDMA0_MCU_CNTL` unhalt, `RB_ENABLE`. [V sez. 2.10]
32. **Ring test**: sul compute ring `WRITE_DATA` su uno slot writeback + doorbell; poi un IB con
    `RELEASE_MEM` + EOP IRQ (client 0x14 src 181) per validare fence e interrupt. Su SDMA un `SDMA_OP_WRITE` /
    fence + trap (client 0x0a src 49). [I: stessa logica di `amdgpu_ring_test_helper` / `amdgpu_ib_ring_tests`]

### Fase H - per-processo / command buffer
33. Per ogni contesto utente: page directory a 4 livelli (PDB2..PTB, 9 bit per livello, PTE gfx12 sez. 2.4),
    VMID 1-7 (o user queue MES con VMID dinamici 8-15), flush TLB con `VM_INVALIDATE_ENGx`. Submission:
    `INDIRECT_BUFFER` sul ring kernel (via doorbell) oppure user queue MES (`ADD_QUEUE` con MQD per-processo,
    firmware gia' sopra soglia: ME 3090/PFP 3190/MEC 3450/MES 0x93). [V soglie; I architettura]

### R - Reset/recupero
- Mode1: debug mailbox SMU `C2PMSG_53 = 0`, `C2PMSG_75 = 2`, `C2PMSG_54 = 0`; niente MMIO per ~1 s; ripristina
  PCI config; attendi `C2PMSG_35` bit31 e `RCC_CONFIG_MEMSIZE != 0xffffffff`; riesegui `asic_init` AtomBIOS e
  tutto da passo 5. Reset per coda: MES `RESET`/legacy queue reset. [V sez. 4.2-4.3]

## 7. Domande aperte e rischi

1. **Stato dopo warm reboot da Linux**: `MPASP_SMN_C2PMSG_81` resta != 0? Se si', il kext deve fare mode1 reset
   al primo avvio (e quindi gia' avere il percorso di recupero completo). Da misurare (lettura MMIO privilegiata,
   non eseguita qui).
2. **VRAM utilizzabile**: `mem_info_vram_total` = 16304 MiB e la finestra MC in dmesg 0x80_0000_0000-
   0x83_FAFF_FFFF coincidono (16 GiB - 80 MiB nascosti dall'IFWI), mentre il VBIOS `firmwareinfo` v3.5 riporta
   `fw_protect_region_size_in_kb = 524288`; resta da leggere `RCC_CONFIG_MEMSIZE`, `DRIVER_SCRATCH_0..2` e le
   risposte PSP 0x50/0x51 per sapere esattamente quali regioni in cima alla VRAM sono riservate (MMIO/debugfs
   privilegiato).
3. **AtomBIOS `asic_init` v2.1** (offset 0x2764 nel `vbios.rom`): `firmwareinfo` v3.5 ha `bootup_sclk/mclk = 0`
   (campi "reserved"); verificare che l'esecuzione della tabella con parametri 0 sia cio' che fa Linux su questa
   scheda (dmesg con `amdgpu.dc_log`/trace atom, privilegiato).
4. **Differenza uni-MES 7.2.9 vs 7.3**: nel dump gli `ADD_QUEUE` delle code kernel sono sul ring della pipe KIQ,
   nel sorgente 7.3 sulla pipe sched; entrambe funzionano col firmware 0x93, ma va scelta una delle due e
   testata.
5. **Accesso PSP da macOS**: il PSP richiede indirizzi MC per `fw_pri`, ring e buffer; la VRAM deve essere
   gestita dal kext prima del boot del sOS (nessun allocatore Apple). Rischio: errori del PSP poco diagnosticabili
   (solo `resp.status`).
6. **MSI/MSI-X su macOS** per l'IH: va verificato che IOPCIDevice fornisca MSI per 1002:7590 dietro lo switch
   PCIe interno della GPU.
7. **CU harvest**: `gfx_v12_0_tcp_harvest` e' vuota e la harvest table non ha entry; su una scheda con CU
   fusi (non questa) i bitmap vanno letti da `CC_GC_SHADER_ARRAY_CONFIG`.
8. Dati privilegiati utili da raccogliere su Linux (sola lettura, root): `C2PMSG_81/35/33/64` a GPU inizializzata,
   `RCC_CONFIG_MEMSIZE`, `BIOS_SCRATCH_7`, `MMMC_VM_FB_LOCATION_BASE/TOP`, `MMMC_VM_FB_OFFSET`, `GB_ADDR_CONFIG`,
   `CC_GC_SHADER_ARRAY_CONFIG` per SE/SH, il log `amdgpu.debug`/`drm.debug=0x1ff` del boot (ordine reale dei
   `LOAD_IP_FW`), e un trace `amdgpu_dm`/`psp` via ftrace.
