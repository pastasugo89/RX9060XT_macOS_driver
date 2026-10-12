# 02 — Percorso display su Linux (amdgpu_dm + Display Core DCN 4.0.1) e requisiti per un IOFramebuffer macOS

Target: AMD Radeon RX 9060 XT (Navi 44, PCI 1002:7590 rev c0, Sapphire 1DA2:A493), GC 12.0.0, DMU 4.1.0 → DCN 4.0.1.
Sorgenti: `research/src/linux` (torvalds master 7.3-rc, ott. 2026), `research/refs/*` (Navi 48, non fidati, solo lettura),
dump hardware in `research/hw_dump/`. Convenzione: **[VERIFICATO]** = letto nel codice / nei dati / misurato;
**[INFERITO]** = deduzione non verificata su hardware.


## 0. Sintesi esecutiva

1. **Stesso DCN di Navi 48** [VERIFICATO]: la discovery dichiara DMU 4.1.0, che `amdgpu_discovery.c:2688-2690`
   rinomina DCN 4.0.1 → `dcn401_resource.c` + `dcn_4_0_1_dmcub.bin`. Basi di segmento (`0x12 0xc0 0x34c0 0x9000
   0x2403c00`), offset registri, numero di pipe (4 OTG/HUBP/DPP/OPP, 4 DSC, 4 HPO DP, 1 HPO FRL) e firmware DMCUB
   sono **identici** a Navi 48; tutti i registri DCN usati stanno in BAR5 (512 KiB).
2. **Trappola di naming** [VERIFICATO]: in DC `ASICREV_IS_GC_12_0_1_A0` è vero per **Navi 44** (`external_rev_id`
   0x41) e `ASICREV_IS_GC_12_0_0_A0` per Navi 48. Le uniche differenze codificate: MALL 8 canali (vs 16),
   `dcc_plane_width_limit = 7680`, soglie SMU diverse per idle DPM/DF throttle.
3. **La differenza vera è la scheda** [VERIFICATO, VBIOS]: 3 PHY (A, B, C); **DP-1 = UNIPHY_A/DDC1/HPD1 (≤ UHBR13.5),
   HDMI-A-1 = UNIPHY_B/DDC2/HPD2, HDMI-A-2 = UNIPHY_C/DDC3/HPD3 (FRL ≤ 10G/corsia)**. I riferimenti per Navi 48
   cablano un'altra topologia (DP su PHY B, HDMI su C/D): ogni mapping va derivato dal VBIOS.
4. **Niente command table display nel VBIOS** [VERIFICATO]: restano solo `asic_init` + 4 tabelle interne. Accensione
   PHY, swing/pre-emphasis e PLL TMDS passano dal **firmware DMCUB** (`DMUB_CMD__VBIOS` 128, sub-type
   `DIG1_TRANSMITTER_CONTROL` 1 e `SET_PIXEL_CLOCK` 2; `dmub_command_table = true`). Tutto il resto (HUBP/DPP/MPC/
   OPP/OTG/DIG/AUX/DDC/HPD/cursore/flip, DP DTO) è programmazione diretta di registri.
5. **DMCUB** [VERIFICATO]: Linux lo carica via PSP (firmware firmato, 256 B header + 256 B footer), ferma il DMCUB
   pre-OS (`DMUB_GPINT__STOP_FW`), copia il VBIOS in CW3 e usa ring inbox1/outbox1 da 8 KiB in CW4. Il GOP lascia un
   DMCUB pre-OS attivo con ring in `DMCUB_REGION4` che RDNA4FB/Cobalt64 hanno usato con successo su Navi 48.
6. **Linux non conserva l'immagine del GOP** su dGPU (`dcn401_init_hw`: `init_pipes` + `power_down`); un driver macOS
   invece può e deve partire **adottando** la pipe del GOP (modello RDNA4FB), poi aggiungere flip, modi fissi, modeset
   nativo (DMCUB + link training DP 8b/10b + HDMI TMDS/SCDC), multi-display, audio e S3.
7. **Parte più costosa**: i parametri di banda per pipe (DLG/TTU/RQ/watermark/DET) che Linux calcola con DML 2.1
   (52 102 righe, in virgola mobile, non usabile in un kext così com'è) → tabelle catturate su Linux per i modi
   dell'utente nei primi stadi.
8. **Stato misurato**: la RX 9060 XT è la GPU di boot (simpledrm sul framebuffer GOP), S3 funziona su Linux, ma al
   momento della lettura **nessun monitor era rilevato** su nessun connettore: le EDID dell'utente vanno ancora
   raccolte (sez. 10).

## 1. Risoluzione della versione DCN (DMU 4.1.0 vs DCN 4.0.1) e Navi 48

### 1.1 Da IP discovery a `DCN_VERSION_4_01` [VERIFICATO]

1. **Tabella IP discovery** (`hw_dump/ip_discovery_table.bin`, decodificata con il mio
   `scratchpad/display/scripts/ipdisc.py`): blocco `DMU` (HWID 271) **versione 4.1.0**, istanza 0,
   5 basi di segmento (in dword): `seg0=0x12  seg1=0xc0  seg2=0x34c0  seg3=0x9000  seg4=0x2403c00`.
   Sono presenti anche `DIO` (HWID 272, base `0x2404000`) e `DAZ` (HWID 274, audio Azalia,
   basi `0x4c0000 0x2404800`) con versione "127.127.63" (= campo non valorizzato). Tabella harvest vuota.
2. **Rimappatura nel kernel**: `drivers/gpu/drm/amd/amdgpu/amdgpu_discovery.c:2684-2690`
   (`amdgpu_discovery_set_display_ip_blocks()`):
   ```c
   case IP_VERSION(4, 1, 0):
   ...
       /* TODO: Fix IP version. DC code expects version 4.0.1 */
       if (adev->ip_versions[DCE_HWIP][0] == IP_VERSION(4, 1, 0))
           adev->ip_versions[DCE_HWIP][0] = IP_VERSION(4, 0, 1);
   ```
   Quindi "DMU 4.1.0" (nome hardware) e "DCN 4.0.1" (nome software di DC e del firmware
   `dcn_4_0_1_dmcub.bin`) sono **lo stesso blocco**. Gli header registri si chiamano invece
   `include/asic_reg/dcn/dcn_4_1_0_offset.h` / `dcn_4_1_0_sh_mask.h` (nome hardware): sono quelli usati
   da `dc/resource/dcn401/dcn401_resource.c:65-66`. Il codice esterno (Cobalt64) chiama il suo layer
   `dcn41` per lo stesso motivo.
3. **Selezione della versione DC**: `dc/core/dc_resource.c:257-260` (`resource_parse_asic_id()`):
   famiglia `AMDGPU_FAMILY_GC_12_0_0` (152 = 0x98, verificato in `gca_config.bin`) e
   `ASICREV_IS_GC_12_0_1_A0 || ASICREV_IS_GC_12_0_0_A0` → `DCN_VERSION_4_01` →
   `dcn401_create_resource_pool()` (`dc_resource.c:381-382`).
4. **amdgpu_dm**: `amdgpu_dm.c:2856-2862` fissa `num_crtc = 4`, `num_hpd = 4`, `num_dig = 4` per
   `IP_VERSION(4,0,1)`; registra gli handler IRQ DCN10-style (`amdgpu_dm_dcn10_register_irq_handlers`,
   r. 2643) e gli handler outbox DMUB (r. 2433-2449); PSR/Replay abilitati di default (r. 2460, inutili
   senza eDP); firmware `FIRMWARE_DCN_401_DMUB = "amdgpu/dcn_4_0_1_dmcub.bin"`
   (`amdgpu_dm_dmub.h:62`, `amdgpu_dm_dmub.c:559,754` → `DMUB_ASIC_DCN401`).

### 1.2 Navi 48 usa lo stesso DCN? Sì, con una trappola di naming [VERIFICATO]

- Navi 48 (GC 12.0.1) ha anch'esso DMU 4.1.0 → DCN 4.0.1: stesso `dcn401_resource.c`, stesso firmware
  DMCUB, stesse basi di segmento (Cobalt64 cabla `0x12 0xc0 0x34c0 0x9000 0x2403c00` e rifiuta valori
  diversi: `refs/Cobalt64/src/navi48-bringup/src/dcn/navi48_modetrial_tables.h:4`; vedi report 05 §7.4).
  **Il numero di registro assoluto di ogni registro DCN è identico su Navi 44 e Navi 48.**
- **Trappola**: i macro di DC hanno i nomi "invertiti" rispetto alle versioni IP.
  `display/include/dal_asic_id.h:289-298`:
  ```c
  GC_12_0_0_A0 = 0x50,
  GC_12_0_1_A0 = 0x40,
  #define ASICREV_IS_GC_12_0_1_A0(r) (r >= GC_12_0_1_A0 && r < GC_12_0_0_A0)   /* 0x40..0x4f */
  #define ASICREV_IS_GC_12_0_0_A0(r) (r >= GC_12_0_0_A0 && r < 0xFF)           /* 0x50..0xfe */
  ```
  mentre `amdgpu/soc24.c:366` assegna `external_rev_id = rev_id + 0x40` a **GC 12.0.0** e
  `soc24.c:387` `rev_id + 0x50` a **GC 12.0.1**. Il nostro `external_rev_id` misurato è **0x41**
  (`hw_dump/README.md`, `gca_config.bin`). Quindi, dentro DC:
  - `ASICREV_IS_GC_12_0_1_A0(...)` è **vero per Navi 44** (la nostra scheda);
  - `ASICREV_IS_GC_12_0_0_A0(...)` è **vero per Navi 48**.
  La conferma indipendente è il clamp dei canali MALL in `dcn401_resource.c:1463-1467`: il ramo
  "GC_12_0_0_A0" limita a 16 canali (Navi 48, 256 bit), il ramo "GC_12_0_1_A0" a **8 canali**
  (Navi 44, 128 bit = 4 UMC × 2 canali).
- **Differenze Navi 44 vs Navi 48 effettivamente codificate in DC** (tutte da leggere con la regola sopra):

| Punto | File:riga | Navi 44 (`hw_internal_rev` 0x41) | Navi 48 (0x5x) |
|---|---|---|---|
| Canali MALL disponibili | `dcn401_resource.c:1463-1467` | max **8** | max 16 |
| `dcc_plane_width_limit` | `dcn401_resource.c:2113-2114` | **7680** (DCC disabilitata su piani > 7680 px) | nessun limite |
| Idle DPM UCLK/FCLK | `dcn401_clk_mgr.c:128-133` | se SMU ≥ 0x661300 (nostra SMC 102.71.0 = 0x664700 → **sì**) | se SMU ≥ 0x681800 |
| DF throttle opt (SubVP) | `dcn401_clk_mgr.c:149-150` | se SMU ≥ 0x663500 (→ **sì**) | mai |

  Tutto il resto (`res_cap_dcn4_01`, sequenze hwseq, DMUB, DCCG, DIO, HPO) è **comune**.

### 1.3 Capacità di pipe per DCN 4.0.1 [VERIFICATO]

`dcn401_resource.c:705-720` (`res_cap_dcn4_01`), comune a Navi 44/48:
`num_timing_generator = 4`, `num_opp = 4`, `num_video_plane = 4`, `num_audio = 4`,
`num_stream_encoder = 4` (DIO), `num_hpo_frl = 1` (HDMI 2.1 FRL), `num_hpo_dp_stream_encoder = 4`,
`num_hpo_dp_link_encoder = 4` (DP 2.1 128b/132b), `num_pll = 4`, `num_dwb = 1`, `num_ddc = 4`,
`num_vmid = 16`, `num_mpc_3dlut = 4`, `num_dsc = 4`.
Il numero effettivo di pipe viene ridotto dai fuse: `read_pipe_fuses()` legge `CC_DC_PIPE_DIS & 0xf`
(`dcn401_resource.c:2001-2007`, `2049-2069`). Sul nostro chip il DTN log (`hw_dump/dm_dtn_log.txt`)
elenca **4 HUBP (0..3)** → nessuna pipe fusa, `pipe_count = 4`. Anche il VBIOS dice
`max_disp_pipe_num 4` (sez. 3). Altre caps: `max_cursor_size = 64` (HW 78×78, r. 2076),
`i2c_speed_in_khz = 95`, `dp_hpo = true`, `dp_hdmi21_pcon_support = true`, `dmcub_support = true`,
`max_v_total = 32767` (r. 2105-2111).

**Cosa cambia davvero per Navi 44 nel display** non è il blocco DCN ma la **scheda**: 3 PHY cablati
(A, B, C) invece dei 4 tipici di Navi 48, e i monitor dell'utente. Vedi sez. 3 e 8.

## 2. Stato misurato dei connettori e dei monitor

### 2.1 sysfs DRM (non privilegiato, letto il 12/10/2026) [VERIFICATO]

| Connettore (card1 = RX 9060 XT, `0000:03:00.0`) | connector_id | status | enabled | modes | EDID | Canale DDC/AUX |
|---|---|---|---|---|---|---|
| `card1-DP-1` | 449 | disconnected | disabled | 0 | 0 byte | DDC `i2c-3` "AMDGPU DM i2c hw bus 0" + AUX `drm_dp_aux0` / `i2c-7` "AMDGPU DM aux hw bus 0" |
| `card1-HDMI-A-1` | 459 | disconnected | disabled | 0 | 0 byte | DDC `i2c-4` "AMDGPU DM i2c hw bus 1" |
| `card1-HDMI-A-2` | 466 | disconnected | disabled | 0 | 0 byte | DDC `i2c-5` "AMDGPU DM i2c hw bus 2" |
| `card1-Writeback-1` | – | unknown | disabled | 0 | – | DWB (1 istanza, `num_dwb = 1`) |

Anche tutti i connettori dell'iGPU Raphael (`card0-DP-2/3/4`, `card0-HDMI-A-3`) risultano
`disconnected`. Al momento della lettura **nessun monitor era rilevato** (monitor spenti/in standby
profondo con HPD basso, o macchina usata da remoto); lo stesso valeva per il dump debugfs
`hw_dump/dm_dtn_log.txt` (tutte le HUBP/OTG idle, `blank_en 0`, `clock_en 0`). Di conseguenza **non è
stato possibile salvare le EDID dei monitor dell'utente**: va fatto con monitor accesi (vedi sez. 10).

Coerenza con il VBIOS (sez. 3): DP-1 ↔ path 0 (DDC1 → "hw bus 0", HPD1), HDMI-A-1 ↔ path 1 (DDC2 → bus 1,
HPD2), HDMI-A-2 ↔ path 2 (DDC3 → bus 2, HPD3). Il DP ha anche il canale AUX 0 (per DP il DDC hardware
viene comunque istanziato da DC ma l'EDID passa via AUX I2C-over-AUX).

### 2.2 Log del kernel (journalctl -k, non privilegiato) [VERIFICATO]

- `pci 0000:03:00.0: vgaarb: setting as boot VGA device` → la RX 9060 XT è la **GPU di boot** e il GOP
  UEFI ha scritto sul suo framebuffer: Linux crea `simple-framebuffer.0` (simpledrm, `fb0`) prima di amdgpu.
  È esattamente il framebuffer che un kext macOS deve "adottare" (OpenCore lo passa a XNU come
  `PE_Video`/boot console).
- `Loading DMUB firmware via PSP: version=0x0A004B00` → su questa scheda il firmware DMCUB è caricato
  **tramite PSP** (`AMDGPU_FW_LOAD_PSP`, sez. 5).
- `Display Core v3.2.384 initialized on DCN 4.0.1`, `DP-HDMI FRL PCON supported`,
  `DMUB hardware initialized: version=0x0A004B00`, poi `fb0: amdgpudrmfb` (fbcon prende il posto di simpledrm).
- `snd_hda_intel 0000:03:00.1: bound 0000:03:00.0 (ops amdgpu_dm_audio_component_bind_ops)`: l'audio HDMI/DP
  (`1002:ab40`, che `lspci` chiama "Navi 48 HDMI/DP Audio Controller": stesso ID su Navi 44 e 48) si lega
  al driver display tramite il componente audio DRM (ELD/notifiche di hotplug). `/proc/asound/card1`
  "HDA ATI HDMI", codec `ATI R6xx HDMI` vendor `0x1002aa01`, **4 pin** (`eld#0.0..0.3`, NID 0x3/0x5/0x7/0x9)
  = `num_audio = 4`; tutti `monitor_present 0`.
- Sospensione: `PM: suspend entry (deep)` → `Waking up from system sleep state S3` → di nuovo
  `DMUB hardware initialized` (22:03:34). `/sys/power/mem_sleep` = `s2idle [deep]`: **S3 funziona** su questa
  macchina con amdgpu, e al resume il DMUB viene re-inizializzato (rilevante per sleep/wake su macOS, sez. 7).
- Runtime PM della dGPU: `power/runtime_status = active`, `power_state = D0`.

## 3. VBIOS: cosa fornisce ancora (atomfirmware)

Parser scritto per questo report: `scratchpad/display/scripts/vbios_parse.py` (Python, `python3 -I`, solo
lettura di `hw_dump/vbios.rom`); output completo in `scratchpad/display/vbios_parse.out`. Struct di
riferimento: `drivers/gpu/drm/amd/include/atomfirmware.h`, `display/dc/bios/bios_parser2.c`.

### 3.1 Header [VERIFICATO]

- ROM 58 880 byte, firma `55AA`, PCIR @0x1c0 vendor `1002` device `7590`; ATOM ROM header @0x194
  (`atom_rom_header_v2_2`, rev 2.3): subsystem `1da2:a493`, `masterhwfunction_offset 0x26c0`,
  `masterdatatable_offset 0x300`, `pspdirtableoffset 0x9000000` (puntatore alla directory PSP nella SPI
  da 2 MB, `firmwareinfo.spi_rom_size 0x200000`: è lì che stanno i firmware pre-OS, incluso il DMCUB
  usato dal GOP; non è nell'immagine da 58 KB che abbiamo).
- Versione VBIOS (dmesg/README): `113-P816G493-S05`; `firmware_revision 0x17040044`.

### 3.2 Command table: ne restano solo 5, nessuna per il display [VERIFICATO]

`atom_master_list_of_command_functions_v2_1` @0x26c0: solo 5 slot su 79 sono non nulli:
`[0] asic_init` (290 B), `[6] cmd_function6`, `[22] cmd_function22`, `[53] cmd_function53`,
`[66] cmd_function66` (tutti "used as an internal one"). **Mancano** `digxencodercontrol` (4),
`setpixelclock` (12), `dig1transmittercontrol`, `enabledisppowergating`, `blankcrtc`, `enablecrtc`,
`setdceclock` ecc. Quindi su DCN 4.0.1 non si può guidare il display "alla vecchia" con AtomBIOS
(come facevano i kext Apple pre-Navi o `atombios_crtc.c` di radeon). DC lo sa:
`dcn401_resource.c:767` mette `.dmub_command_table = true`, e `bios/command_table2.c:382-412`
(`transmitter_control_v1_7`) inoltra la richiesta al **firmware DMCUB** come comando ring
`DMUB_CMD__VBIOS` (128) / `DMUB_CMD__VBIOS_DIG1_TRANSMITTER_CONTROL` (1) con payload
`struct dmub_dig_transmitter_control_data_v1_7` (`dmub_cmd.h:3046`: `phyid` 0=UNIPHYA…, `action`
ATOM_TRANSMITTER_ACTION_*, `digmode`/`dplaneset`/`txffe`, `lanenum`, `symclk_10khz` o `symclk_Hz` per FRL,
`hpdsel`, `digfe_sel`, `connobj_id`, `HPO_instance`, …). Il firmware DMCUB implementa le "command table"
che il VBIOS non contiene più. Se il DMCUB non gira, non si accendono i PHY (sez. 5 e 6).

### 3.3 Data table presenti [VERIFICATO]

`atom_master_list_of_data_tables_v2_1` @0x300:

| idx | Tabella | Offset | Byte | Rev | Uso per il display |
|---|---|---|---|---|---|
| 2 | `smc_dpm_info` | 0x23c0 | 532 | 6.0 | DPM SMU (non display) |
| 3/5/9/13/17/26 | `sw_datatable*` | – | – | – | interne |
| 4 | `firmwareinfo` | 0x2314 | 172 | **3.5** | caps (`FIRMWARE_POSTED`), MC base `0x80_0000_0000`, i2c scheda (`board_i2c_feature` gpio 0x97 slave 0x50 = EEPROM), `bios_scratch_reg_startaddr 0x4c`, `disp_phy_tunning_size 5656` |
| 6 | `lcd_info` | 0x1964 | 80 | 3.1 | inutile (nessun eDP) |
| 11 | `vram_usagebyfirmware` | 0x224c | 48 | 2.2 | tutto 0 (nessuna riserva FW in VRAM dichiarata qui) |
| 12 | `gpio_pin_lut` | 0x1a88 | 164 | 2.1 | **mappa HPD/DDC → registri GPIO** (vedi 3.5) |
| 14 | `gfx_info` | 0x25d4 | 136 | 3.1 | GFX |
| 22 | `displayobjectinfo` | 0x227c | 152 | **1.5** | **connettori/encoder** (vedi 3.4) |
| 23 | `indirectioaccess` | 0x1c90 | 8 | 1.1 | – |
| 24 | `umc_info` | 0x265c | 84 | 4.0 | memoria (DC lo usa per `vram_info.num_chans` → limiti richieste SDPIF) |
| 25 | `sw_datatable25` | 0x034c | **5656** | 1.2 | = dimensione `disp_phy_tunning_size` → **tabella di tuning PHY** letta dal DMCUB |
| 27 | `dce_info` | 0x19b4 | 212 | **4.5** | clock/limiti display (vedi 3.6) |

Assenti: `integratedsysteminfo` (solo APU), `smu_info`, `vram_info`, `powerplayinfo`, `voltageobject_info`,
`multimedia_info`, `asic_profiling_info`. Nota importante: `amdgpu_dm_dmub.c:219` copia **l'intera
immagine VBIOS** (`adev->bios`) nella finestra `DMUB_WINDOW_3_VBIOS` (CW3, base DMCUB `0x63000000`): il
firmware DMCUB legge da sé tabelle come quella di tuning PHY. Un driver macOS che (ri)carica il DMCUB deve
fornirgli il VBIOS nello stesso modo.

### 3.4 Object table: connettori ed encoder della Sapphire 1DA2:A493 [VERIFICATO]

`displayobjectinfo` v1.5 (`struct display_object_info_table_v1_5` / `atom_display_object_path_v3`),
`supporteddevices 0x0288` (= DFP1|DFP2|DFP3), `number_of_path 3`:

| Path | Connettore (object id) | Encoder (object id) | Transmitter / PHY | device_tag | DDC (i2c_id → GPIO) | HPD | Velocità max | Bracket |
|---|---|---|---|---|---|---|---|---|
| 0 | DISPLAYPORT enum1 (`0x3113`) | INTERNAL_UNIPHY enum1 (`0x211e`) | **UNIPHY_A (PHY A)** | 0x0008 DFP1 | 0x90 → `DC_GPIO_DDC1_A` (engine 1, line 0) | pin 0x01 → HPD1 | 13 500 (≤UHBR13.5) | conn 1, 18×9 |
| 1 | HDMI_TYPE_A enum2 (`0x320c`) | INTERNAL_UNIPHY enum2 (`0x221e`) | **UNIPHY_B (PHY B)** | 0x0080 DFP2 | 0x91 → `DC_GPIO_DDC2_A` (line 1) | pin 0x02 → HPD2 | 10 000 (FRL ≤10G/corsia) | conn 2, 18×9 |
| 2 | HDMI_TYPE_A enum3 (`0x330c`) | INTERNAL_UNIPHY1 enum1 (`0x2120`) | **UNIPHY_C (PHY C)** | 0x0200 DFP3 | 0x92 → `DC_GPIO_DDC3_A` (line 2) | pin 0x03 → HPD3 | 10 000 (FRL ≤10G/corsia) | conn 3, 15×7 |

Record per path: `I2C`, `HPD_INT`, `CONNECTOR_CAP` (0), `CONNECTOR_SPEED_UPTO`
(`atom_connector_speed_record`, usato da DC per limitare il link rate), `BRACKET_LAYOUT_V2`. Nessun
record di encoder esterno, nessun retimer/LTTPR dichiarato, nessun DPIA/USB-C.
Significato del record velocità **[VERIFICATO]** in `bios/bios_parser2.c:2497-2508`
(`bios_parser_get_disp_connector_caps_info`): `connector_max_speed` abilita i flag per soglia.
Per il DP (13 500) → `DP_HBR2_EN`, `DP_HBR3_EN`, `DP_UHBR10_EN`, `DP_UHBR13_5_EN` = 1, **`DP_UHBR20_EN` = 0**
(niente UHBR20 su questa scheda). Per gli HDMI (10 000) → `HDMI_6GB_EN`, `FRL_8G_EN`, `FRL_10G_EN` = 1,
**`FRL_12G_EN` = 0** (HDMI 2.1 FRL fino a 4 corsie × 10 Gbps = 40 Gbps).

**Confronto con Navi 48 (Cobalt64)**: sulla RX 9070 XT degli autori il DP è su DIG1/PHY B e gli HDMI su
PHY C e PHY D (report 05 §7.4). Sulla nostra scheda **DP = PHY A, HDMI = PHY B e PHY C, nessun PHY D**
(`dce_info.max_disp_phy_num = 3`). La mappatura connettore→PHY→DDC→HPD **va letta dal VBIOS a runtime**,
non cablata.

### 3.5 GPIO pin LUT (HPD e DDC) [VERIFICATO]

`gpio_pin_lut` v2.1, 20 voci; `data_a_reg_index` è un indice dword assoluto = base seg2 DCN (`0x34c0`) +
offset registro: `0x5db5 = 0x34c0 + 0x28f5` = `regDC_GPIO_HPD_A` (verificato in `dcn_4_1_0_offset.h`).
HPD1..HPD5 sono i bit 0/8/16/24/26 di `DC_GPIO_HPD_A`; DDC1..DDC4 = `DC_GPIO_DDC1_A..DDC4_A`
(`0x5d91/95/99/9d`), `0x97` = `DC_GPIO_DDCVGA_A` (usato come I2C della scheda per l'EEPROM). Il
blocco HPD vero e proprio (filtri, interrupt) è `HPDn_DC_HPD_INT_STATUS/_INT_CONTROL/_CONTROL`
(`dcn_4_1_0_offset.h`, 4 istanze HPD0..HPD3 = `num_hpd 4`; HPD1..HPD3 del VBIOS corrispondono alle istanze HPD0..HPD2).

### 3.6 `dce_info` v4.5 (`atom_display_controller_info_v4_5`) [VERIFICATO]

`display_caps 0x300`, `bootup_dispclk_10khz 62500` → **DISPCLK di boot 625 MHz**, `dce_refclk_10khz
10000` → **refclk 100 MHz**, `i2c_engine_refclk 50 MHz`, `dpphy_refclk 100 MHz`, spread spectrum DP
0.375 % @ 31.5 kHz (HDMI/DVI 0), `hw_chip_id 0x7590`, `dcnip_max_ver 0x4`, **`max_disp_pipe_num 4`,
`max_vbios_active_disp_pipe_num 1` (il GOP accende al massimo 1 pipe), `max_ppll_num 0`,
`max_disp_phy_num 3`, `max_aux_pairs 4`**, `dispclk_pll_vco_freq 450000` (×10 kHz = 4.5 GHz),
`aux_dphy_rx_control0_val 0x103d1110`, `aux_dphy_tx_control_val 0x00021c7a`,
`aux_dphy_rx_control1_val 0x00004500`, `dc_gpio_aux_ctrl_0..5`.
Riscontro incrociato: `enc401_hw_init()` (`dio/dcn401/dcn401_dio_link_encoder.c:79-121`) scrive
esattamente `AUX_DPHY_RX_CONTROL0 = 0x103d1110` e `AUX_DPHY_TX_CONTROL = 0x21c7a`: gli stessi valori del VBIOS.

## 4. Mappa del codice DC per DCN 4.0.1

### 4.1 Stack software Linux (dall'alto in basso) [VERIFICATO]

```
DRM atomic (KMS)  ──►  amdgpu_dm (35 108 righe .c: amdgpu_dm.c, _crtc, _plane, _connector, _irq, _dmub, _audio, _mst …)
                         │  traduce drm_atomic_state → dc_state (dc_stream_state + dc_plane_state)
                         ▼
Display Core (DC)  dc/core (25 709) / link/ (21 757) / dml2_0 (69 634 righe .c in totale, di cui dml21 52 102: bandwidth, watermark, DET, ODM, MALL)
                         │  resource pool  = dcn401_resource.c (2 485)
                         │  hw sequencer   = hwss/dcn401 (4 388) + funzioni ereditate dcn10/dcn20/dcn30/dcn32/dce110
                         │  clock manager  = clk_mgr/dcn401 (2 178) → SMU (mailbox DAL) + DCCG
                         ▼
Blocchi HW (ognuno = struct di registri + funcs): hubbub401, hubp401, dpp401, mpc401, opp20, optc401,
dsc401, dccg401, dio(dcn401 link/stream enc), hpo (dcn31 DP stream, dcn32 DP link, dcn401 FRL stream,
dcn30 FRL link), vpg31/afmt3/apg31 (infoframe+audio), dce_audio, dce_aux/dce_i2c (AUX/DDC HW), irq_service_dcn401
                         ▼
DMUB service (dmub/src/dmub_srv.c 1 546 + dmub_dcn401.c 686; protocollo in dmub/inc/dmub_cmd.h 8 366)
                         ▼
Firmware DMCUB (dcn_4_0_1_dmcub.bin 0x0A004B00) che gira sul microcontrollore DMCUB dentro il DMU
```

### 4.2 Blocchi istanziati da `dcn401_resource_construct()` [VERIFICATO]

| Blocco | Costruttore (riga in `dcn401_resource.c`) | Implementazione | Istanze su Navi 44 | Prefisso registri |
|---|---|---|---|---|
| HUBBUB (arbitro memoria, watermark, DET, CRB, MALL) | `hubbub401_construct` (932) | `hubbub/dcn401` (1 275) | 1 | `DCHUBBUB_*` |
| HUBP (fetch superficie, cursore, flip) | `hubp401_construct` (986) | `hubp/dcn401` (1 166) | 4 | `HUBP{0-3}_*`, `HUBPREQ{n}_*`, `CURSOR0_{n}_*` |
| DPP (scaler, CSC, gamma, cursore DPP) | `dpp401_construct` (1018) | `dpp/dcn401` (1 878) | 4 | `DPP_TOP{n}`, `CM{n}`, `DSCL{n}`, `CNVC_CFG{n}` |
| MPC (blending, OGAM, 3DLUT, RMCM) | `dcn401_mpc_construct` (1041) | `mpc/dcn401` (696) | 1 (4 MPCC) | `MPCC{n}_*` (seg3 `0x9000`) |
| OPP (FMT, dither, DPG test pattern, ODM) | `dcn20_opp_construct` (1069) | `opp/dcn20` | 4 | `OPP_PIPE{n}`, `FMT{n}`, `DPG{n}` |
| OPTC/OTG (timing generator) | `dcn401_timing_generator_create` (2310) | `optc/dcn401` (549) + dcn10/dcn32 | 4 | `OTG{0-3}_*`, `ODM{n}` |
| DSC | `dsc401_construct` (1756) | `dsc/dcn401` (400) | 4 | `DSC{n}` |
| DCCG (clock: DPPCLK DTO, DP DTO, DTBCLK, SYMCLK, PHY→DIG mux) | `dccg401_create` (2248) | `dccg/dcn401` (1 007) | 1 | `DCCG_*`, `DPPCLK*_DTO*`, `DP_DTO*`, `PHYxSYMCLK_CLOCK_CNTL` (seg1) |
| DIO link encoder (DIG BE + PHY via DMUB) | `dcn401_link_encoder_construct` (1145) | `dio/dcn401` (1 419) | 1 per connettore (3) | `DIG{n}_DIG_BE_*`, `DP{n}_*`, `DP_AUX{n}` |
| DIO stream encoder (DIG FE) | `dcn401_dio_stream_encoder_construct` (1295) | `dio/dcn401` | 4 | `DIG{n}_DIG_FE_*`, `DP{n}_DP_*`, `HDMI*` |
| HPO DP (128b/132b, UHBR) | `dcn31_hpo_dp_stream_encoder_construct` (1416), `hpo_dp_link_encoder32_construct` (1442) | `hpo/dcn31`, `hpo/dcn32` | 4+4 | `DP_STREAM_ENC{n}`, `DP_SYM32_ENC{n}`, `DP_LINK_ENC{n}` |
| HPO FRL (HDMI 2.1) | `dcn401_hpo_frl_stream_encoder_construct` (1336), `hpo_frl_link_encoder3_construct` (1360) | `hpo/dcn401` (907), `hpo/dcn30` | 1 | `HDMI_FRL_ENC*`, `HDMI_LINK_ENC*` |
| VPG/AFMT/APG (infoframe, audio packet) | `vpg31_construct` (1203), `afmt3_construct` (1228), `apg31_construct` (1252) | dcn30/dcn31 | 4+ | `VPG{n}`, `AFMT{n}`, `APG{n}` |
| Audio endpoint | `dce_audio_create` (1177) | `dce/dce_audio.c` | 4 | `AZF0ENDPOINT{n}_*` |
| AUX engine / HW I2C | `dce110_aux_engine_construct` (830), `dcn2_i2c_hw_construct` (869) | `dce/dce_aux.c`, `dce/dce_i2c_hw.c` | 4 + 4 | `DP_AUX{n}_*`, `DC_I2C_DDC{n}_*` |
| ABM (via DMUB) / PSR (via DMUB) | `dmub_abm_create` (2318), `dmub_psr_create` (2333) | `dce/dmub_abm.c`, `dce/dmub_psr.c` | – | inutili senza eDP |
| DWB + MMHUBBUB (writeback) | `dcn401_dwbc_create` (2359), `dcn401_mmhubbub_create` (2366) | dcn30/dcn401 | 1 | `DWB*`, `MCIF_WB*` |
| IRQ service | `dal_irq_service_dcn401_create` (2257) | `irq/dcn401` (416) | – | vedi sez. 7 |

Tabella hw sequencer (`hwss/dcn401/dcn401_init.c`): `init_hw = dcn401_init_hw`, `apply_ctx_to_hw =
dce110_apply_ctx_to_hw`, `program_front_end_for_ctx = dcn401_program_front_end_for_ctx`,
`update_plane_addr = dcn20_update_plane_addr` (flip), `enable_stream_timing = dcn401_enable_stream_timing`,
`enable_stream = dcn401_enable_stream`, `unblank_stream = dcn401_unblank_stream`,
`blank_stream = dce110_blank_stream`, `enable_audio_stream = dce110_enable_audio_stream`,
`set_cursor_position = dcn401_set_cursor_position`, `set_cursor_attribute = dcn10_set_cursor_attribute`,
`get_position = dcn10_get_position`, `set_drr = dcn10_set_drr`, `init_pipes = dcn10_init_pipes`,
`power_down = dce110_power_down`, `prepare/optimize_bandwidth = dcn401_*`, `update_odm = dcn401_update_odm`,
`hubp_pg_control/dsc_pg_control/enable_power_gating_plane = dcn32_*`.

### 4.3 Clock manager `clk_mgr/dcn401` [VERIFICATO]

- Il DCN non ha PLL propri programmati dal driver per DISPCLK/DPPCLK/DCFCLK/SOCCLK/DTBCLK: li chiede
  all'**SMU** tramite un mailbox dedicato a DAL (separato da quello del driver amdgpu):
  `dcn401_clk_mgr_smu_msg.c:13-15` → `mmDAL_MSG_REG 0x1628A`, `mmDAL_ARG_REG 0x16273`,
  `mmDAL_RESP_REG 0x16274` (indirizzi dword assoluti nello spazio MP1; protocollo: RESP=0, ARG, MSG,
  poll RESP==`DALSMC_Result_OK` 1).
- Messaggi (`clk_mgr/dcn401/dalsmc.h`): `GetSmuVersion 0x2`, `GetDriverIfVersion 0x3`,
  `SetDalDramAddrHigh/Low 0x5/0x6`, `TransferTableDram2Smu 0x8` (tabella watermark),
  **`SetHardMinByFreq 0x9`** (alza DISPCLK/DPPCLK/DCFCLK/UCLK…), `SetHardMaxByFreq 0xA`,
  `GetDpmFreqByIndex 0xB`, `GetDcModeMaxDpmFreq 0xC`, `SetMinDeepSleepDcfclk 0xD`, **`NumOfDisplays 0xE`**,
  `BacoAudioD3PME 0x10`, `SetFclkSwitchAllow 0x11`, `SetCabForUclkPstate 0x12`, `DcnExitReset 0x14`,
  `ReturnHardMinStatus 0x15`, `SetAlwaysWaitDmcubResp 0x16`, `IndicateDrrStatus 0x17`,
  `ActiveUclkFclk 0x18`, `IdleUclkFclk 0x19`, `SetUclkPstateAllow 0x1A`, `SubvpUclkFclk 0x1B`,
  `GetNumUmcChannels 0x1C`. Il parametro di `SetHardMinByFreq` è `(PPCLK_e << 16) | MHz`.
- SMU feature attive misurate (`hw_dump/pp_features.txt`): `DPM_DCN (7) enabled`, `DS_DCFCLK (14) enabled`,
  `DPM_UCLK (3)`, `DPM_SOCCLK (5)`, `FW_DSTATE (17)`, `BACO (19)`.
- Gli altri clock per pipe sono DTO nel DCCG programmati dal driver: DPPCLK DTO
  (`dcn401_update_clocks_update_dpp_dto`, `dcn401_clk_mgr.c:560`), DP DTO / pixel clock per DP e FRL
  (`dce_clock_source.c:1070` `dcn401_program_pix_clk`: "all but TMDS gets Driver to program DP_DTO without
  calling VBIOS Command table", sorgente DPREFCLK o DTBCLK0 per FRL), mentre per **TMDS** il pixel clock va
  al PLL del PHY tramite `bios->set_pixel_clock` → `set_pixel_clock_v7` → **`DMUB_CMD__VBIOS_SET_PIXEL_CLOCK`**
  (`bios/command_table2.c:467-561`).
- Clock di riferimento dal VBIOS: refclk 100 MHz, DISPCLK di boot 625 MHz (sez. 3.6).
- Senza SMU funzionante (= senza PSP/SMU bring-up) il driver **non può alzare DISPCLK/DPPCLK** sopra i valori
  lasciati dal GOP: per i modi ad alto pixel clock serve l'SMU (vedi sez. 9).

### 4.4 Indirizzi MMIO assoluti dei registri chiave (Navi 44 = Navi 48) [VERIFICATO]

Calcolati con `scratchpad/display/scripts/regabs.py` (base di segmento DMU dalla discovery + offset da
`dcn_4_1_0_offset.h`); indirizzo byte = dword × 4 dentro **BAR5 (512 KiB)**. Tutti i registri DCN usati stanno
nei segmenti 0-3 (nessun registro in seg4 `0x2403c00`) e quindi **sono raggiungibili direttamente da BAR5**
(il massimo è MPC in seg3 ≈ `0x24xxx` byte) senza finestra indiretta.

| Registro | seg | offset | dword assoluto | byte in BAR5 |
|---|---|---|---|---|
| `DCCG_GATE_DISABLE_CNTL` | 1 | 0x0074 | 0x00134 | 0x0004d0 |
| `DENTIST_DISPCLK_CNTL` | 1 | 0x0064 | 0x00124 | 0x000490 |
| `CC_DC_PIPE_DIS` | 2 | 0x00ca | 0x0358a | 0x00d628 |
| `DMU_CLK_CNTL` | 2 | 0x00cb | 0x0358b | 0x00d62c |
| `DMCUB_REGION3_CW0_BASE_ADDRESS` | 2 | 0x01a5 | 0x03665 | 0x00d994 |
| `DMCUB_INTERRUPT_ENABLE` | 2 | 0x01c5 | 0x03685 | 0x00da14 |
| `DMCUB_SEC_CNTL` | 2 | 0x01ce | 0x0368e | 0x00da38 |
| `DMCUB_INBOX1_BASE_ADDRESS` / `_WPTR` / `_RPTR` | 2 | 0x01d4 / 0x01d6 / 0x01d7 | 0x03694 / 0x03696 / 0x03697 | 0x00da50 / 0x00da58 / 0x00da5c |
| `DMCUB_OUTBOX1_WPTR` / `_RPTR` | 2 | 0x01de / 0x01df | 0x0369e / 0x0369f | 0x00da78 / 0x00da7c |
| `DMCUB_SCRATCH0` (boot status) | 2 | 0x01e3 | 0x036a3 | 0x00da8c |
| `DMCUB_CNTL` / `DMCUB_GPINT_DATAIN1` / `DMCUB_CNTL2` | 2 | 0x01f6 / 0x01f8 / 0x0200 | 0x036b6 / 0x036b8 / 0x036c0 | 0x00dad8 / 0x00dae0 / 0x00db00 |
| `AZF0ENDPOINT0_AZALIA_F0_CODEC_ENDPOINT_INDEX` | 2 | 0x0386 | 0x03846 | 0x00e118 |
| `DCHUBBUB_ARB_DRAM_STATE_CNTL` | 2 | 0x04fc | 0x039bc | 0x00e6f0 |
| `DCHUBBUB_GLOBAL_TIMER_CNTL` | 2 | 0x0527 | 0x039e7 | 0x00e79c |
| `HUBP0_DCSURF_SURFACE_CONFIG` | 2 | 0x05e5 | 0x03aa5 | 0x00ea94 |
| `HUBP0_DCSURF_PRI_VIEWPORT_DIMENSION` | 2 | 0x05eb | 0x03aab | 0x00eaac |
| `HUBP0_DCHUBP_CNTL` | 2 | 0x05f4 | 0x03ab4 | 0x00ead0 |
| `HUBPREQ0_DCSURF_SURFACE_PITCH` | 2 | 0x0607 | 0x03ac7 | 0x00eb1c |
| `HUBPREQ0_DCSURF_PRIMARY_SURFACE_ADDRESS` / `_HIGH` | 2 | 0x060a / 0x060b | 0x03aca / 0x03acb | 0x00eb28 / 0x00eb2c |
| `HUBPREQ0_DCSURF_FLIP_CONTROL` | 2 | 0x0613 | 0x03ad3 | 0x00eb4c |
| `CURSOR0_0_CURSOR_CONTROL` / `_SURFACE_ADDRESS` / `_POSITION` | 2 | 0x0679 / 0x067a / 0x067d | 0x03b39 / 0x03b3a / 0x03b3d | 0x00ece4 / 0x00ece8 / 0x00ecf4 |
| `HUBPREQ1_DCSURF_PRIMARY_SURFACE_ADDRESS` (stride HUBP = 0xdc dword) | 2 | 0x06e6 | 0x03ba6 | 0x00ee98 |
| `DPP_TOP0_DPP_CONTROL` | 2 | 0x0cc5 | 0x04185 | 0x010614 |
| `DP_AUX0_AUX_CONTROL` / `_SW_CONTROL` | 2 | 0x16b2 / 0x16b3 | 0x04b72 / 0x04b73 | 0x012dc8 / 0x012dcc |
| `OPP_PIPE0_OPP_PIPE_CONTROL` | 2 | 0x188c | 0x04d4c | 0x013530 |
| `OTG0_OTG_H_TOTAL` / `_V_TOTAL` | 2 | 0x1b2a / 0x1b2f | 0x04fea / 0x04fef | 0x013fa8 / 0x013fbc |
| `OTG0_OTG_CONTROL` (stride OTG = 0x80 dword) | 2 | 0x1b43 | 0x05003 | 0x01400c |
| `OTG0_OTG_STATUS_POSITION` | 2 | 0x1b4a | 0x0500a | 0x014028 |
| `OTG0_OTG_VERTICAL_INTERRUPT0_POSITION` | 2 | 0x1b5f | 0x0501f | 0x01407c |
| `OTG0_OTG_GLOBAL_SYNC_STATUS` (VSTARTUP/VUPDATE int) | 2 | 0x1b88 | 0x05048 | 0x014120 |
| `OTG1_OTG_CONTROL` / `OTG3_OTG_CONTROL` | 2 | 0x1bc3 / 0x1cc3 | 0x05083 / 0x05183 | 0x01420c / 0x01460c |
| `DIO_MEM_PWR_CTRL` | 2 | 0x1ede | 0x0539e | 0x014e78 |
| `DIG0_DIG_FE_CNTL` / `DIG0_DIG_FE_CLK_CNTL` | 2 | 0x2093 / 0x2094 | 0x05553 / 0x05554 | 0x01554c / 0x015550 |
| `DIG0_DIG_BE_CLK_CNTL` / `DIG0_DIG_BE_CNTL` | 2 | 0x20bb / 0x20bc | 0x0557b / 0x0557c | 0x0155ec / 0x0155f0 |
| `DC_GPIO_HPD_A` | 2 | 0x28f5 | 0x05db5 | 0x0176d4 |
| `MPCC0_MPCC_CONTROL` | 3 | 0x0003 | 0x09003 | 0x02400c |
| `DCCG_AUDIO_DTO_SOURCE` | 1 | 0x00ab | 0x0016b | 0x0005ac |

Nota: `DCN_VM_FB_LOCATION_BASE`/`DCN_VM_FB_OFFSET` (usati da `dmub_dcn401_get_fb_base_offset`) esistono nel
DCN (`dcn_4_1_0_offset.h`), così il DMCUB e l'HUBP vedono la VRAM nello stesso spazio MC del GMC
(`0x80_0000_0000`, VBIOS `firmwareinfo.mc_baseaddr hi 0x80`; dmesg: VRAM MC `0x8000000000-0x83FAFFFFFF`).

## 5. DMUB per DCN 4.0.1: firmware, caricamento, mailbox, comandi

### 5.1 Il firmware `dcn_4_0_1_dmcub.bin` [VERIFICATO]

Parsato con `scratchpad/display/scripts/dmcub_hdr.py` sul file decompresso
(`scratchpad/bringup/fw/dcn_4_0_1_dmcub.bin`, stesso file per Navi 44 e Navi 48):

- `struct dmcub_firmware_header_v1_0` (`amdgpu/amdgpu_ucode.h:425`): `size_bytes 368032`,
  header v1.0, IP v4.0, **`ucode_version 0x0a004b00`** (= `DMCUB 0x0a004b00` di `firmware_info.txt`),
  `ucode_array_offset_bytes 0x100`, `inst_const_bytes 367776`, **`bss_data_bytes 0`**.
- Il payload `inst_const` è firmato: 256 B di header PSP (`PSP_HEADER_BYTES_256`) + codice + 256 B di footer PSP
  (`dmub_srv.c:176-203` sottrae `PSP_FOOTER_BYTES_256`). Il blocco meta `struct dmub_fw_meta_info`
  (`dmub_cmd.h:1027`, magic `0x444D5542` "DMUB") si trova a fine codice (offset 4 nella finestra di ricerca a
  16 posizioni): `fw_region_size 107072`, `trace_buffer_size 65552`, `dal_fw 1`, `shared_state_size 1280`,
  `shared_state_features 4` (il campo `fw_version` del meta vale `0x0a001000`, diverso da `ucode_version`:
  lo riporto com'è).

### 5.2 Caricamento: PSP vs backdoor [VERIFICATO nel codice; INFERITO per macOS]

- **Linux su questa scheda**: `AMDGPU_FW_LOAD_PSP` (dmesg "Loading DMUB firmware via PSP"). In
  `dm_dmub_sw_init()` (`amdgpu_dm_dmub.c:578-588`) il firmware viene registrato come
  `AMDGPU_UCODE_ID_DMCUB` e il PSP lo carica (comando `LOAD_IP_FW`, tipo firmware DMUB; vedi report 01)
  nella regione CW0 dentro la TMR, verificandone la firma.
- `dm_dmub_hw_init()` (`amdgpu_dm_dmub.c:138-325`):
  1. `dmub_srv_hw_reset()` → `dmub_dcn401_reset()` (`dmub_dcn401.c:63-129`): se il DMCUB gira
     (`DMCUB_CNTL.DMCUB_ENABLE=1`, `DMCUB_CNTL2.DMCUB_SOFT_RESET=0`) invia GPINT `DMUB_GPINT__STOP_FW`
     su `DMCUB_GPINT_DATAIN1`, attende `DMCUB_SCRATCH7 == 0xDEADDEAD` e `DMCUB_PWAIT_MODE_STATUS`, poi
     `DMCUB_SOFT_RESET=1`, `DMCUB_ENABLE=0`, disabilita CW2..CW7, azzera INBOX1/OUTBOX1/OUTBOX0 RPTR/WPTR e
     `DMCUB_SCRATCH0`. **Cioè Linux ferma il DMCUB pre-OS del GOP e lo sostituisce con il proprio.**
  2. Se `load_type != PSP`: copia `inst_const` in `DMUB_WINDOW_0_INST_CONST` (backdoor). Con PSP no.
  3. Copia `bss_data` (qui 0 B), **copia l'intero VBIOS in `DMUB_WINDOW_3_VBIOS`**, azzera MAILBOX,
     TRACEBUFF, FW_STATE, SHARED_STATE.
  4. `hw_params`: `fb_base = adev->gmc.fb_start`, `fb_offset = adev->vm_manager.vram_base_offset`,
     `load_inst_const = (load_type != PSP)`, `psp_version`, opzioni (z10, dpia, ips…).
  5. `dmub_srv_hw_init()` (`dmub_srv.c:~800-970`): `reset`; se `load_inst_const`, `backdoor_load` =
     `dmub_dcn401_backdoor_load` (`dmub_dcn401.c:139-173`: `DMCUB_SEC_CNTL.DMCUB_SEC_RESET=1`,
     `DMCUB_ENABLE=0`, programma `DMCUB_REGION3_CW0/CW1_OFFSET(_HIGH)/BASE_ADDRESS/TOP_ADDRESS`, poi
     `DMCUB_SEC_RESET=0`, `DMCUB_MEM_UNIT_ID=0x20`); `setup_windows` CW3..CW6 + REGION5 (trace/outbox0) +
     REGION6 (shared state) (`dmub_dcn401.c:208-270`); `setup_outbox0`; `setup_mailbox`
     (`DMCUB_INBOX1_BASE_ADDRESS`, `DMCUB_INBOX1_SIZE`); `setup_out_mailbox` (`DMCUB_OUTBOX1_*`);
     abilita gli interrupt reg-inbox0/outbox0; boot options in `DMCUB_SCRATCH14`
     (`z10_disable`, `skip_phy_access`, `skip_phy_init_panel_sequence`); `reset_release`
     (`dmub_dcn401.c:131-137`: `MMHUBBUB_SOFT_RESET.DMUIF_SOFT_RESET=0`, `DMCUB_SCRATCH15 = psp_version &
     0x001100FF`, `DMCUB_ENABLE=1` + `DMCUB_TRACEPORT_EN=1`, `DMCUB_SOFT_RESET=0`).
  6. `dmub_srv_wait_for_auto_load()` (100 ms): attende in `DMCUB_SCRATCH0` (`union dmub_fw_boot_status`,
     `dmub_cmd.h:1088`) i bit `dal_fw` e `mailbox_rdy`. Altri bit: `optimized_init_done`, `restore_required`,
     `defer_load`, `fams_enabled`, `detection_required`, `hw_power_init_done`, `ono_regions_enabled`.
  7. `dc_dmub_srv_create()`; più avanti `dcn401_init_hw` invia `DMUB_CMD__QUERY_FEATURE_CAPS` (6) e legge
     `psr`, `fw_assisted_mclk_switch_ver` (FAMS) (`dcn401_hwseq.c:391-405`).
- `dmub_dcn401_is_hw_init()` = `DMCUB_CNTL.DMCUB_ENABLE && SCRATCH0.dal_fw`; `dmub_dcn401_is_supported()`
  = `CC_DC_PIPE_DIS.DC_DMCUB_ENABLE` (`dmub_dcn401.c:319-337`).
- **Backdoor load su DCN 4.0.1**: il codice esiste ed è usato da Linux quando `load_type != PSP`, ma su SOC24
  amdgpu usa sempre PSP. Se il DMCUB accetti codice non autenticato via backdoor (con `DMCUB_SEC_CNTL`
  scrivibile dall'host) su un chip di produzione **non è verificato**: va provato (sez. 10). Per macOS la via
  sicura è (a) **riusare il DMCUB pre-OS già in esecuzione** (lo fa Cobalt64), oppure (b) caricare
  `dcn_4_0_1_dmcub.bin` via PSP dopo aver portato su il PSP (TMR + ring KM, report 01).

### 5.3 Finestre di memoria del DMCUB (spazio di indirizzi interno del microcontrollore) [VERIFICATO]

`dmub_srv.c:57-89`, `amdgpu_dm_dmub.c:499-511` (tutte in VRAM, `DMUB_WINDOW_MEMORY_TYPE_FB`):

| Finestra | Base DMCUB | Contenuto / dimensione | Registri |
|---|---|---|---|
| CW0 `INST_CONST` | `0x60000000` | codice firmware (caricato da PSP) | `DMCUB_REGION3_CW0_*` (programmati da PSP o backdoor) |
| CW1 `STACK` | `0x61000000` | stack 128 KiB + context 512 KiB | `DMCUB_REGION3_CW1_*` |
| CW2 `BSS_DATA` | `0x60000000 + inst_size` | bss/data (0 B qui) | – |
| CW3 `VBIOS` | `0x63000000` | **copia del VBIOS** | `DMCUB_REGION3_CW3_*` |
| CW4 `MAILBOX` | `0x64000000` | inbox1 (8 KiB = 128 × 64 B) + outbox1 (8 KiB) | `DMCUB_REGION3_CW4_*`, `DMCUB_INBOX1_*`, `DMCUB_OUTBOX1_*` |
| CW5 `TRACEBUFF` | `0x65000000` | trace buffer = outbox0 (via REGION5 `0xA0000000`) | `DMCUB_REGION3_CW5_*`, `DMCUB_REGION5_*` |
| CW6 `FW_STATE` | `0x66000000` | stato firmware 64 KiB (debugfs `amdgpu_dm_dmub_fw_state`) | `DMCUB_REGION3_CW6_*` |
| REGION6 `SHARED_STATE` | `0xC0000000` | stato condiviso (IPS, cursor offload…) | `DMCUB_REGION6_*` |
| `SCRATCH_MEM`, `IB_MEM`, `LSDMA_BUFFER`, `CURSOR_OFFLOAD` | – | 1 KiB, FAMS2 config, 64 KiB, cursore | – |

Traduzione indirizzi: `offset_programmato = gpu_addr - fb_base + fb_offset`
(`dmub_dcn401_translate_addr`), con `fb_base` da `DCN_VM_FB_LOCATION_BASE << 24` e `fb_offset` da
`DCN_VM_FB_OFFSET << 24` se il driver non li fornisce (`dmub_dcn401.c:36-60`).

**Il DMCUB pre-OS (GOP) usa un'altra convenzione**: secondo Cobalt64 (misurato su Navi 48,
`refs/Cobalt64/src/navi48-bringup/src/dcn/navi48_dispread.h:461-497`, `navi48_dmubcmd.h:1-60`) il firmware del
VBIOS tiene il suo ring inbox1 all'inizio della finestra **`DMCUB_REGION4`** (`DMCUB_REGION4_OFFSET(_HIGH)`,
`DMCUB_REGION4_TOP_ADDRESS`, registri presenti in `dcn_4_1_0_offset.h`), ring di 0x2000 byte, più uno "stato ring
VBIOS" a REGION4+0x3114/0x3118/0x311c, un "mode block" a +0x4c00 e contesti per display a +0x6800/+0x7000/+0x7800.
**[INFERITO per Navi 44]**: lo stesso VBIOS-DMCUB (stessa generazione IFWI) dovrebbe usare lo stesso schema, ma
gli offset dei contesti dipendono dal numero di DFP della scheda (la nostra ha DFP1/2/3, la loro DFP2/3/4) e
vanno rimisurati.

### 5.4 Protocollo inbox/outbox [VERIFICATO]

- **Inbox1 (host → DMCUB)**: ring di `DMUB_RB_SIZE = 64 × 128 = 8192` byte (`dmub_cmd.h:1818-1828`). Ogni
  comando è un `union dmub_rb_cmd` di 64 byte con header `struct dmub_cmd_header` (`dmub_cmd.h:2070`):
  `type:8`, `sub_type:8`, `ret_status:1`, `multi_cmd_pending:1`, `is_reg_based:1`, `reserved:5`,
  `payload_bytes:6`, `reserved:2`. Invio: scrivi lo slot in VRAM a `rb_base + wptr`, poi
  `DMCUB_INBOX1_WPTR = wptr+64` (mod size); completamento quando `DMCUB_INBOX1_RPTR == WPTR`
  (`dmub_srv_wait_for_idle`, `dmub_srv.c:1157`); i comandi con risposta (`ret_status=1`) vengono ricopiati
  dal firmware nello slot.
- **Reg-inbox0** (mailbox a registri, `DMCUB_REG_INBOX0_*`, `dmub_dcn401_send_reg_inbox0_cmd_msg`
  `dmub_dcn401.c:534-600`): usato per i comandi urgenti/sincroni come `HW_LOCK` (lock delle pipe durante
  FAMS2/cursor offload, `dcn401_dmub_hw_control_lock` `dcn401_hwseq.c:1569-1604`).
- **Outbox1 (DMCUB → host)**: secondo ring da 8 KiB subito dopo inbox1 in CW4; interrupt
  `DMCUB_OUTBOX_LOW_PRIORITY_READY_INT` (src id **0x68**, enable `DMCUB_INTERRUPT_ENABLE.DMCUB_OUTBOX1_READY_INT_EN`,
  ack `DMCUB_INTERRUPT_ACK.DMCUB_OUTBOX1_READY_INT_ACK`, `irq_service_dcn401.c:267-272`). Porta notifiche:
  risposte AUX (se l'AUX passa dal DMCUB), HPD per DPIA (USB4), SET_CONFIG, fused I/O. Su una dGPU senza USB-C
  serve poco; amdgpu lo abilita comunque (`amdgpu_dm.c:2433-2449`, comando `DMUB_CMD__OUTBOX1_ENABLE` 71).
- **Outbox0**: trace/log del firmware (REGION5), solo debug.
- **GPINT** (`DMCUB_GPINT_DATAIN1`/`DMCUB_GPINT_DATAOUT`, risposta in `DMCUB_SCRATCH7`): comandi brevi
  (`DMUB_GPINT__GET_FW_VERSION` 1, `STOP_FW`, PSR/IPS residency…).

### 5.5 Comandi DMUB rilevanti per un driver desktop (tipi da `dmub_cmd.h:1856-2014`) [VERIFICATO]

| Tipo (valore) | Sotto-tipi | Chi lo usa su DCN 4.0.1 | Necessario per macOS? |
|---|---|---|---|
| `DMUB_CMD__VBIOS` (128) | `DIGX_ENCODER_CONTROL` 0, **`DIG1_TRANSMITTER_CONTROL` 1** (abilita/disabilita PHY, swing/pre-emphasis, FRL, `transmitter_control_v1_7`), **`SET_PIXEL_CLOCK` 2** (PLL PHY per TMDS), `ENABLE_DISP_POWER_GATING` 3, `LVTMA_CONTROL` 15, `TRANSMITTER_QUERY_DP_ALT` 26, `DOMAIN_CONTROL` 28, `TRANSMITTER_SET_PHY_FSM` 29 | `bios/command_table2.c` perché `dmub_command_table = true` | **Sì** (modeset nativo, accensione PHY) |
| `DMUB_CMD__QUERY_FEATURE_CAPS` (6) | – | `dcn401_init_hw` | utile |
| `DMUB_CMD__FW_ASSISTED_MCLK_SWITCH` (76) | `FAMS2_CONFIG` 4, `FAMS2_DRR_UPDATE` 5, `FAMS2_FLIP` 6, `FAMS2_IB_CONFIG` 7 | **FAMS2 v2.1 abilitato di default** (`dcn401_resource.c:795-805`: `enable`, `enable_offload_flip`, `enable_stall_recovery`); `dcn401_fams2_update_config` (`dcn401_hwseq.c:1606`) | No all'inizio: disabilitarlo e vietare il cambio UCLK con display attivo |
| `DMUB_CMD__HW_LOCK` (69) | – (via reg-inbox0) | lock pipe per FAMS2/cursor offload | No se FAMS2/offload spenti |
| `DMUB_CMD__CAB_FOR_SS` (75) | `CAB_NO_IDLE_OPTIMIZATION`, `CAB_NO_DCN_REQ`, `CAB_DCN_SS_FIT_IN_CAB`… | idle con scanout da MALL (`dcn401_apply_idle_power_optimizations`) | No (ottimizzazione energetica) |
| `DMUB_CMD__IDLE_OPT` (72), `DMUB_CMD__CLK_MGR` (73) | – | IPS/idle | No |
| `DMUB_CMD__UPDATE_CURSOR_INFO` (68) | – | cursore con PSR/Replay e cursor offload (`dcn401_update_cursor_offload_pipe` r. 3128) | No (cursore a registri) |
| `DMUB_CMD__DP_AUX_ACCESS` (70) | – | AUX via firmware (DPIA) | No: l'AUX nativo è `dce_aux` a registri |
| `DMUB_CMD__EDID_CEA` (79) | – | parsing AMD VSDB (FreeSync HDMI) | No |
| `DMUB_CMD__PSR` (64), `DMUB_CMD__REPLAY` (83), `DMUB_CMD__ABM` (66), `DMUB_CMD__PANEL_CNTL` (74) | – | solo eDP | **No** (nessun eDP) |
| `DMUB_CMD__DPIA` (77), `DPIA_HPD_INT_ENABLE` (86) | – | solo USB4/DPIA | **No** |
| `DMUB_CMD__MALL` (65) | – | cursore/self-refresh da MALL | No |
| `DMUB_CMD__SECURE_DISPLAY` (85), `CACP` (87), `PSP` (88), `FUSED_IO` (89) | – | HDCP/sicurezza | No |

Conclusione: per un framebuffer macOS il DMCUB è **indispensabile solo come esecutore delle ex-command table
VBIOS** (PHY on/off/swing e PLL TMDS). Tutto il resto (HUBP/DPP/MPC/OPP/OTG/DIG/AUX/HPD/cursore/flip) è
programmazione diretta di registri dall'host.

## 6. Sequenze minime

Notazione: "pipe" = HUBP*n* → DPP*n* → MPCC*n* (in MPC) → OPP*n* → OTG*n* → DIG FE (stream encoder) →
DIG BE (link encoder) → PHY. Su DCN 4.0.1 l'assegnazione stream encoder ↔ link encoder è dinamica
(`link_enc_cfg`, mux in `DIG_FE_CNTL`/DCCG), e le istanze PHY/DIG della nostra scheda sono A, B, C (sez. 3.4).

### 6.1 Cosa fa Linux all'avvio (e perché non conserva l'immagine del GOP) [VERIFICATO]

`dcn401_init_hw()` (`hwss/dcn401/dcn401_hwseq.c:140-411`), ordine:
1. `clk_mgr->init_clocks` (interroga l'SMU via mailbox DAL), `dccg_init`, ref clock da `fw_info`
   (xtal 100 MHz) → `dccg_ref`/`dchub_ref`.
2. Per ogni link fisico: `link_enc->hw_init` (`enc401_hw_init`: `AUX_DPHY_RX_CONTROL0 = 0x103d1110`,
   `AUX_DPHY_TX_CONTROL = 0x21c7a`, `TMDS_CTL0=1`, `dcn10_aux_initialize`); se `is_dig_enabled` (DIG lasciato
   acceso dal GOP) marca `link_active = true`, `SYMCLK_ON_TX_ON`.
3. `enable_power_gating_plane`, poi **`blank_all_dp_displays`**.
4. Poiché `seamless_boot_edp_requested` è falso (nessun eDP) **e/o** `is_accelerated_mode` (bit in
   `BIOS_SCRATCH_6`) → `init_pipes` (`dcn10_init_pipes`): spegne tutte le pipe; poi se un DIG è acceso
   → `hws->funcs.power_down` (= `dce110_power_down`: disabilita stream, link e PHY).
   Quindi **Linux su dGPU fa un "full power-down" e un mode set completo**: lo schermo del GOP si spegne e
   torna con il modo scelto da DRM (seamless boot è previsto solo per eDP).
5. `audio->hw_init`, `abm_init`, `dio->mem_pwr_ctrl` (memoria AFMT/HDMI), clock gating DCN
   (`DCFCLK_CNTL.DCFCLK_GATE_DIS=0`), `dcn401_setup_hpo_hw_control`, `init_watermarks` (se non in
   accelerated mode), `notify_wm_ranges` all'SMU, `init_crb`, `set_request_limit` (canali UMC da VBIOS),
   `DMUB_CMD__QUERY_FEATURE_CAPS`, configurazione FAMS2.

### 6.2 Adozione del framebuffer GOP (Stadio 1, nessuna scrittura di timing) [VERIFICATO sui registri; INFERITO come procedura]

Il GOP UEFI lascia accesa **una sola pipe** (`max_vbios_active_disp_pipe_num 1`), tipicamente OTG0/HUBP0
sul primo connettore con sink. Procedura raccomandata (stessa filosofia di Cobalt64, report 05 §7.4):
1. Mappare BAR5 (MMIO 512 KiB) e BAR0 (VRAM; con ReBAR 16 GiB tutto visibile, vedi sez. 10 per il limite
   macOS). Verificare le basi DMU dalla tabella discovery (`0x12 0xc0 0x34c0 0x9000 0x2403c00`).
2. Trovare la pipe attiva: per ogni OTG *n* leggere `OTGn_OTG_CONTROL.OTG_MASTER_EN`; per ogni HUBP
   `HUBPn_DCHUBP_CNTL` (`HUBP_BLANK_EN`, `HUBP_DISABLE`), `HUBPn_DCSURF_SURFACE_CONFIG`
   (`SURFACE_PIXEL_FORMAT`), `DCSURF_TILING_CONFIG.SW_MODE` (atteso lineare), `HUBPREQn_DCSURF_SURFACE_PITCH`,
   `HUBPn_DCSURF_PRI_VIEWPORT_DIMENSION`, `HUBPREQn_DCSURF_PRIMARY_SURFACE_ADDRESS(_HIGH)` (indirizzo MC
   `0x80_xxxx_xxxx`). Timing: `OTGn_OTG_H_TOTAL`, `_H_BLANK_START_END`, `_H_SYNC_A`, `_V_TOTAL`,
   `_V_BLANK_START_END`, `_V_SYNC_A` (vedi `optc1_program_timing` `optc/dcn10/dcn10_optc.c:193-275` per il
   significato). Link: `DIGn_DIG_BE_CNTL` (modo DP/HDMI, FE sorgente), `DIGn_DIG_FE_CNTL`. Linux ha le stesse
   letture in `hubp401_read_state` (`hubp/dcn401/dcn401_hubp.c:899`) e nel DTN log.
3. Indirizzo in BAR0 = `surface_addr_MC - FB_BASE_MC` (`DCN_VM_FB_LOCATION_BASE << 24`, qui
   `0x80_0000_0000`). Questo è lo stesso framebuffer che OpenCore/XNU passa come boot console
   (`PE_Video.v_baseAddr`): controllo di coerenza.
4. Esportare a IOFramebuffer **un solo modo** (quello letto), `kIO32BGRAPixelFormat`, `rowBytes = pitch ×
   4`. Nessun interrupt: il vblank si può simulare leggendo `OTGn_OTG_STATUS_POSITION` /
   `OTG_STATUS_FRAME_COUNT` da timer.
5. Primo "flip" (per passare a un buffer allocato dal driver o dall'acceleratore): stesso formato e pitch,
   solo nuovo indirizzo. `hubp401_program_surface_flip_and_addr` (`dcn401_hubp.c:482-632`):
   `DCSURF_FLIP_CONTROL.SURFACE_FLIP_TYPE = 0` (flip al VSYNC; 1 = immediato), poi
   `DCSURF_PRIMARY_SURFACE_ADDRESS_HIGH` **e poi** `DCSURF_PRIMARY_SURFACE_ADDRESS` (la scrittura low arma il
   flip); il completamento si legge da `HUBPREQn_DCSURF_FLIP_CONTROL.SURFACE_FLIP_PENDING` o dall'interrupt
   `HUBPn_FLIP_INTERRUPT`. I buffer devono rispettare allineamento a 256 B e restare nella VRAM vista dal DCN
   (MC address) — con GPUVM DCN disattivato il DCN legge indirizzi fisici MC.
Rischi: (a) il GOP potrebbe non aver acceso alcun display (nessun monitor all'avvio, come nella lettura di
sez. 2) → serve lo stadio 3; (b) se il driver GPU porta su l'SMU con `DPM_UCLK` e cambia la frequenza di memoria
mentre il GOP fa scanout senza watermark/FAMS adeguati, si vedono underflow/flicker → finché il display è in
stadio 1-2, chiedere all'SMU un UCLK fisso (`DALSMC_MSG_SetUclkPstateAllow 0` o hard-min UCLK massimo) **[INFERITO]**.

### 6.3 Cambio modo "fisso" sullo stesso link (Stadio 2) [VERIFICATO per le funzioni; INFERITO come scorciatoia]

Sequenza DC per abilitare uno stream (`dce110_apply_ctx_to_hw` → `dcn401_enable_stream_timing` r. 709-846 →
`link_set_dpms_on` in `link/link_dpms.c:2776`):
1. **Blank**: `hws->funcs.blank_pixel_data(..., true)` (`dcn20_blank_pixel_data`: OPP DPG genera colore nero,
   `OTG_BLANK_CONTROL`), `wait_for_blank_complete`.
2. **Clock**: `dccg->set_pixel_rate_div`, `set_dtbclk_p_src` (DPREFCLK o DTBCLK0), `enable_optc_clock`,
   `clock_source->program_pix_clk` (`dcn401_program_pix_clk`, `dce/dce_clock_source.c:1070`):
   DP/FRL → **DP DTO nel DCCG programmato dall'host**; HDMI TMDS → **`DMUB_CMD__VBIOS_SET_PIXEL_CLOCK`**.
   DISPCLK/DPPCLK devono essere ≥ requisito del modo: `SetHardMinByFreq` all'SMU + DPPCLK DTO.
3. **Timing**: `optc1_program_timing` (OTG_H_TOTAL/H_SYNC_A/H_BLANK_START_END/V_TOTAL/V_SYNC_A/
   V_BLANK_START_END/INTERLACE), `optc401_program_global_sync` (VSTARTUP, VUPDATE offset/width, VREADY:
   derivati da DML), `set_vtg_params`, eventuale `set_odm_combine` (ODM 2:1 per pixel rate oltre il limite
   DISPCLK di una pipe), `opp_pipe_clock_control`, `optc401_enable_crtc`.
4. **Front end** (`dcn401_program_front_end_for_ctx`/`dcn20_update_dchubp_dpp`): HUBP `program_surface_config`
   (formato, `DCSURF_TILING_CONFIG.SW_MODE`, pitch), `program_size`, `set_viewport`, `hubp401_setup`
   (registri **DLG/TTU/RQ** per pipe: `hubp401_program_requestor`/`program_deadline`), DPP (scaler/CSC/gamma;
   bypass se 1:1), MPC (`MPCCn_MPCC_CONTROL`, albero con 1 MPCC, OPP di uscita), HUBBUB (**watermark A-D, DET,
   CRB, arbitraggio**). Tutti i valori DLG/TTU/RQ/watermark/DET escono da **DML 2.1** (`dcn401_resource.c:783-784`: `using_dml2 = true`,
   `using_dml21 = true`; `dml2_0/dml21` = 52 102 righe .c, `dml2_0` totale 69 634, compilato con flag FPU):
   è la parte più pesante da portare. Scorciatoia per i primi modi: catturare su Linux il set completo di
   registri per ciascun modo dell'utente (debugfs `amdgpu_dm_dtn_log` stampa HUBP/RQ/DLG/TTU/WM/OTG; serve
   root, sez. 10) e riprodurli come tabelle ("golden register snapshot" per modo).
5. **Stream encoder / link** (`link_set_dpms_on`): DP → `DIG_FE` in modo DP, attributi MSA
   (`DP_MSA_*`), `DP_VID_STREAM_CNTL`; HDMI → infoframe AVI (VPG), modalità HDMI/DVI, eventualmente audio.
   Se il link non cambia (stesso link rate/lane DP, o HDMI con stesso clock TMDS) **non serve rifare il link**.
   Per HDMI TMDS il clock del link = pixel clock (× bpc/8): cambiare modo = cambiare clock PHY = disabilitare e
   ri-abilitare il PHY via DMUB.
6. **Unblank**: `dcn401_unblank_stream` (r. 1843) → DP: `DP_VID_STREAM_CNTL` enable, poi OPP DPG off.

### 6.4 DP: rilevamento e link training [VERIFICATO]

- **HPD**: `HPDn_DC_HPD_INT_STATUS.DC_HPD_SENSE` (livello), interrupt `DC_HPD_INT_CONTROL.DC_HPD_INT_EN`, ack
  `DC_HPD_INT_ACK`; long pulse = plug/unplug, short pulse (`DC_HPD_RX_INT_EN`) = IRQ_HPD del sink (link status,
  MST, CEC…). Filtri in `DC_HPD_TOGGLE_FILT_CNTL`. Mapping HPD1..3 del VBIOS → istanze HPD0..2.
- **AUX**: engine nativo `dce110_aux_engine` (`dce/dce_aux.c`), registri `DP_AUXn_AUX_CONTROL`,
  `_AUX_SW_CONTROL`, `_AUX_SW_DATA`, `_AUX_SW_STATUS`, `_AUX_LS_STATUS`, `_AUX_DPHY_RX/TX_CONTROL`: transazioni
  native AUX (DPCD) e I2C-over-AUX (EDID a 0x50, segment pointer 0x30). Timeout esteso supportato
  (`extended_aux_timeout_support`). Su DCN 4.0.1 **l'AUX non passa dal DMCUB** (a differenza dei DPIA USB4).
- **Capacità**: lettura DPCD 0x0000-0x000F (DPCD_REV, MAX_LINK_RATE, MAX_LANE_COUNT, TPS3/TPS4,
  `MAIN_LINK_CHANNEL_CODING` per 128b/132b), 0x2200 (extended caps), LTTPR 0xF0000-0xF0007
  (`link_dp_capability.c`). Il connettore DP della scheda è limitato a UHBR13.5 dal VBIOS.
- **Training 8b/10b** (`protocols/link_dp_training_8b_10b.c`, `link_dp_training.c`):
  `DPCD 0x100 LINK_BW_SET` (0x06/0x0A/0x14/0x1E = RBR/HBR/HBR2/HBR3), `0x101 LANE_COUNT_SET` (+ enhanced
  framing), `0x107 DOWNSPREAD_CTRL`, `0x108 MAIN_LINK_CHANNEL_CODING_SET = 1`; **clock recovery**: PHY in
  TPS1 (`dp_set_hw_training_pattern` → link encoder), `0x102 = TPS1 | scrambling off`, `0x103-0x106
  TRAINING_LANEx_SET` (VS/PE), attesa `TRAINING_AUX_RD_INTERVAL`, poll `0x202-0x203` (`LANEx_CR_DONE`), applica
  `0x206-0x207 ADJUST_REQUEST` → nuovo swing via **`DMUB_CMD__VBIOS_DIG1_TRANSMITTER_CONTROL` azione
  `SET_VOLTAGE_AND_PREEMPASIS`** (`dplaneset`); **channel EQ**: TPS2/TPS3/TPS4 (`decide_eq_training_pattern`
  r. 803), poll `CHANNEL_EQ_DONE`, `SYMBOL_LOCKED`, `0x204 INTERLANE_ALIGN_DONE`; fine: `0x102 = 0`
  (`dpcd_exit_training_mode` r. 1018). Fallback su link rate/lane più bassi. LTTPR: modo trasparente o
  non trasparente (`dp_decide_lttpr_mode` r. 840, training per repeater).
- **128b/132b (UHBR10/13.5)**: `link_dp_training_128b_132b.c` (268 righe), richiede HPO DP stream/link
  encoder, DTBCLK, `0x108 = 2`. **Da rimandare** (i primi stadi bastano con HBR3 8b/10b: 4 × 8.1 Gbps →
  4K@120 8 bpc con DSC, 4K@60 senza).
- **DSC**: 4 istanze DSC (`dsc401`), necessario solo per modi oltre la banda del link. Rimandare.

### 6.5 HDMI: TMDS e FRL [VERIFICATO]

- **TMDS** (`enable_link_hdmi`, `link/link_dpms.c:1857-1934`): niente link training. Se il pixel clock PHY
  > 340 MHz: scrambling + rapporto 1/40 tramite **SCDC** (`write_scdc_data`: I2C slave 0x54, registro 0x20
  `TMDS_Config`, bit1 = TMDS_Bit_Clock_Ratio, bit0 = Scrambling_Enable; poi `read_scdc_data`). Poi
  `setup_stream_encoder` (DIG FE HDMI, infoframe AVI/VSIF via VPG, GCP/deep color) e `enable_tmds_link_output`
  → `dcn10_link_encoder_enable_tmds_output` → **DMUB `DIG1_TRANSMITTER_CONTROL` ENABLE** con `symclk_10khz`.
  Limite TMDS 6 GHz (`phy_pix_clk > 6000000` rifiutato). Il clock PHY TMDS arriva da
  **`DMUB_CMD__VBIOS_SET_PIXEL_CLOCK`**.
- **FRL (HDMI 2.1)**: `protocols/link_hdmi_frl.c` (1 204 righe): capacità dal sink (`hdmi_frl_retrieve_link_cap`,
  HF-VSDB EDID + SCDC), `hdmi_frl_perform_link_training` (r. 430: scrittura SCDC `Config1` FRL_Rate/FFE, poll
  degli status flag `FLT_ready`/`LTP_req`, `hdmi_frl_poll_status_flag` r. 202), HPO FRL stream/link encoder (1
  istanza), DTBCLK, `symclk_Hz` nel comando DMUB. Su questa scheda max FRL 10G/corsia (sez. 3.4). **Da rimandare**:
  4K@60 8 bpc RGB (594 MHz) è ancora TMDS a 5.94 Gbps con scrambling.
- Cobalt64 dichiara "4K su HDMI: in corso" (report 05): il passaggio TMDS > 340 MHz (SCDC + scrambling) è
  esattamente ciò che manca.

### 6.6 EDID e DDC [VERIFICATO]

- HDMI: DDC hardware `dce_i2c_hw` (`dcn2_i2c_hw_construct`, 4 engine, `DC_I2C_DDCn_*`), velocità 95 kHz
  (`i2c_speed_in_khz`), pin da VBIOS (`DC_GPIO_DDC1..3_A`). EDID a 0x50 (+ segment 0x30 per E-EDID > 256 B);
  i blocchi CTA servono per HDMI (VSDB, HF-VSDB, audio SAD, YCbCr 4:2:0).
- DP: EDID via I2C-over-AUX sullo stesso indirizzo 0x50.
- Linux espone i bus come `i2c-3/4/5` ("AMDGPU DM i2c hw bus 0..2") e `i2c-7` (AUX), sez. 2.

### 6.7 Cursore hardware [VERIFICATO]

- Attributi: `dcn10_set_cursor_attribute` → `hubp32_cursor_set_attributes` (HUBP: `CURSOR0_n_CURSOR_SURFACE_ADDRESS(_HIGH)`,
  `CURSOR_SIZE`, `CURSOR_CONTROL` con `CURSOR_MODE` mono/2bpp/ARGB pre-moltiplicato o no, pitch potenza di 2)
  + DPP (`dpp401_set_cursor_attributes`, formato e matrice cursore). Dimensione massima esposta 64×64
  (`max_cursor_size = 64`, `dcn401_resource.c:2076`), superficie in VRAM allineata.
- Posizione: `dcn401_set_cursor_position` (`dcn401_hwseq.c:1040`) → `hubp401_cursor_set_position`
  (`dcn401_hubp.c:806`) + `dpp401_set_cursor_position`: `CURSOR0_n_CURSOR_POSITION`, `_HOT_SPOT`,
  `CURSOR_DST_OFFSET`, gestione di ODM/MPC combine (posizione relativa alla slice) e ingrandimento 2x
  (`adjust_hotspot_between_slices_for_2x_magnify` r. 968).
- Linux su DCN 4.0.1 ha anche il "cursor offload" verso il DMCUB (`dcn401_update_cursor_offload_pipe` r. 3128,
  `DMUB_CMD__UPDATE_CURSOR_INFO`), opzionale. Per macOS: cursore a registri (`CURSOR0_n_CURSOR_CONTROL` campi `CURSOR_ENABLE`, `CURSOR_MODE`, `CURSOR_PITCH`,
  `CURSOR_REQ_MODE`; `CURSOR0_0_CURSOR_SIZE` seg2 0x067c, `CURSOR0_0_CURSOR_HOT_SPOT` 0x067e), aggiornato sotto
  lock OTG (`optc3_lock`/`optc1_unlock`) per evitare strappi tra posizione e immagine.

### 6.8 Page flip e vblank [VERIFICATO]

- Flip: `dcn20_update_plane_addr` → `hubp401_program_surface_flip_and_addr` (6.2). Flip "a VSYNC" (latch alla
  VUPDATE/VSTARTUP successiva) o immediato (tearing). amdgpu_dm usa l'interrupt PFLIP (HUBP flip) per
  completare l'evento DRM e VSTARTUP come vblank.
- Interrupt usati da amdgpu_dm per DCN 4.0.1 (`amdgpu_dm_dcn10_register_irq_handlers`, sez. 7.1): VBLANK =
  **`OTG VSTARTUP`**, VUPDATE (VRR), PFLIP, VLINE0 (per CRC/secure display).
- Per WindowServer (`IOFramebuffer`) serve: interrupt vblank (`kIOFBVBLInterruptType`), un contatore frame
  (`OTG_STATUS_FRAME_COUNT` via `optc1_get_vblank_counter`) e la posizione (`optc1_get_position`:
  `OTG_STATUS_POSITION`, `OTG_NOM_VERT_POSITION`).

### 6.9 Multi-display [VERIFICATO per le risorse; INFERITO per la procedura]

4 OTG/pipe per 3 connettori fisici: ogni display = 1 pipe dedicata (senza ODM). Per ciascun display
aggiuntivo vanno fatti: allocazione stream encoder (DIG FE) e collegamento al DIG BE del PHY giusto
(A/B/C da VBIOS), pixel clock (DP DTO per DP; PLL TMDS via DMUB per HDMI: Linux sceglie il PHY PLL del link,
`hdmi_frl_find_matching_phypll`/`clock_source` per istanza `CLOCK_SOURCE_COMBO_PHY_PLL0..`), DET/watermark
ricalcolati per il **totale** delle pipe attive (DML 2.1 globale), audio endpoint per display. Cobalt64 accende
il 2°/3° display con sequenze cablate (OTG1/OPP1/DIG2→UNIPHY_C, OTG2/DIG3→PHY D) che **non corrispondono** alla
nostra scheda (sez. 8).

## 7. Interrupt display, power, sleep/wake, audio HDMI/DP

### 7.1 Interrupt [VERIFICATO]

Tutti gli interrupt DCN arrivano all'host tramite l'**IH ring** (OSSSYS/IH 7.0.0, report 01) con
**client id `SOC15_IH_CLIENTID_DCE` = 0x04** (`include/soc15_ih_clientid.h:37`); src id da
`include/ivsrcid/dcn/irqsrcs_dcn_1_0.h`, mappa in `irq/dcn401/irq_service_dcn401.c:27-100`, enable/ack nelle
macro `*_int_entry` (r. 195-272):

| Sorgente DC | src id (ctx id) | Enable / ack (registro.campo) | Uso |
|---|---|---|---|
| `DC_IRQ_SOURCE_VBLANK1..4` = OTG0..3 **VSTARTUP** | 0x3C, 0x3D, 0x3E, 0x3F | `OTGn_OTG_GLOBAL_SYNC_STATUS.VSTARTUP_INT_EN` / `.VSTARTUP_EVENT_CLEAR` | vblank DRM |
| `DC_IRQ_SOURCE_VUPDATE1..4` (no-lock) | 0x57..0x5A | `OTG_GLOBAL_SYNC_STATUS.VUPDATE_NO_LOCK_INT_EN` / `_EVENT_CLEAR` | VRR, latch doppio buffer |
| `DC_IRQ_SOURCE_PFLIP1..4` = HUBP0..3 flip | 0x4F..0x52 | `HUBPREQn_DCSURF_SURFACE_FLIP_INTERRUPT.SURFACE_FLIP_INT_MASK` / `.SURFACE_FLIP_CLEAR` | completamento flip |
| `DC_IRQ_SOURCE_DC1..4_VLINE0` | 0x1E..0x21 | `OTG_VERTICAL_INTERRUPT0_CONTROL.OTG_VERTICAL_INTERRUPT0_INT_ENABLE` / `_CLEAR` (+ `_POSITION`) | linea programmabile (CRC, alternativa al vblank) |
| `DC_IRQ_SOURCE_HPD1..4` | 9 (ctx 0..3) | `HPDn_DC_HPD_INT_CONTROL.DC_HPD_INT_EN` / `.DC_HPD_INT_ACK`, stato `DC_HPD_INT_STATUS` | plug/unplug |
| `DC_IRQ_SOURCE_HPD1RX..4RX` | 9 (ctx 6..9) | `DC_HPD_INT_CONTROL.DC_HPD_RX_INT_EN` / `DC_HPD_RX_INT_ACK` | IRQ_HPD (short pulse DP) |
| `DC_IRQ_SOURCE_DMCUB_OUTBOX` | 0x68 | `DMCUB_INTERRUPT_ENABLE.DMCUB_OUTBOX1_READY_INT_EN` / `DMCUB_INTERRUPT_ACK.DMCUB_OUTBOX1_READY_INT_ACK` | notifiche DMCUB |

Su macOS, finché l'IH non è portato su, si può: (a) emulare il vblank con un timer alla frequenza del modo
(come fa RDNA4FB con `rdna4-vbl=1`, `framebuffer.cpp:1502-1560`), allineandolo leggendo
`OTGn_OTG_STATUS_POSITION`/frame count; (b) fare polling di `DC_HPD_INT_STATUS.DC_HPD_SENSE` per l'hotplug.
Con l'IH attivo, l'handler MSI deve filtrare `client_id == 0x04` e smistare per src id.

### 7.2 Power del display e DPMS [VERIFICATO]

- **DPMS off (display sleep)**: Linux `link_set_dpms_off` (`link/link_dpms.c:2386`): blank/disable stream,
  per DP scrittura DPCD `0x600 SET_POWER = 2` (D3), disabilitazione del link (`dcn401_disable_link_output`
  `dcn401_hwseq.c:998` → PHY off via DMUB `DIG1_TRANSMITTER_CONTROL` DISABLE e SYMCLK off), OTG off.
  RDNA4FB fa la versione minima, verificata su hardware: bit `DP_VID_STREAM_ENABLE` di `DP0_DP_VID_STREAM_CNTL`
  (dword `0x2122` seg2) + DPCD 0x600 = 2/1 via AUX, senza toccare OTG/PHY (`framebuffer.cpp:1447-1500`).
  Per HDMI non c'è DPCD: bisogna blankare (OPP DPG/`OTG_BLANK`) o spegnere il PHY.
- **Power gating delle pipe**: `hubp_pg_control`/`dsc_pg_control`/`enable_power_gating_plane` = `dcn32_*`
  (dominio per HUBP/DPP, DSC), `enable_display_power_gating = dcn10_dummy_display_power_gating`.
  Pipe non usate restano spente: per accendere una seconda pipe occorre togliere il power gating del suo dominio.
- **Clock e risparmio**: DPM_DCN e DS_DCFCLK attivi nell'SMU; stutter/self-refresh (watermark SR enter/exit nel
  DTN log: `sr_enter 57.920 us`, `sr_exit 44.920 us`, `dram_clk_change 408.800 us`), MALL/CAB per idle
  (`dcn401_apply_idle_power_optimizations`), FAMS2 per il cambio UCLK. Tutto opzionale per un primo driver.
- `dc_set_power_state(D3)` in `dm_suspend` (`amdgpu_dm.c:1568-1640`); IPS/Z-state riguardano solo APU.

### 7.3 Sleep/wake (S3) [VERIFICATO in Linux; INFERITO per macOS]

- Questa macchina fa S3 "deep" con successo sotto Linux (sez. 2.2). In S3 la scheda perde alimentazione:
  al resume amdgpu esegue `amdgpu_device_asic_init()` (`amdgpu_device.c:958`): per GC ≥ 11
  `amdgpu_psp_wait_for_bootloader()` e poi **`amdgpu_atomfirmware_asic_init()`**, cioè interpreta l'unica
  command table rimasta (`asic_init`, sez. 3.2) con l'interprete AtomBIOS, poi ricarica PSP/SMU/…, e
  `dm_resume` (`amdgpu_dm.c:1846-1980`) → `dm_dmub_hw_resume` (r. 327: se il DMCUB non è inizializzato rifà
  `dm_dmub_hw_init`), `dc_set_power_state(D0)`, ri-detect dei link, `dc_commit_streams` dello stato salvato.
- Al resume da S3 **il GOP UEFI non viene rieseguito**: non c'è più una pipe accesa da adottare né un DMCUB
  pre-OS in esecuzione. Conseguenza per macOS: supportare lo sleep di sistema richiede il percorso nativo
  completo (re-POST con interprete AtomBIOS `asic_init`, PSP + caricamento `dcn_4_0_1_dmcub.bin`, SMU, modeset
  da zero). Fino ad allora: disabilitare lo sleep di sistema (`pmset`/`hibernatemode 0`, `sleep 0`) e offrire
  solo il display sleep (7.2).

### 7.4 Audio HDMI/DP [VERIFICATO in Linux; INFERITO per macOS]

- La funzione audio `03:00.1` (`1002:ab40`, codec HDA `0x1002aa01` "ATI R6xx HDMI", 4 pin) è un controller HDA
  separato, ma i dati del sink (ELD) e lo stato "presente/abilitato" del pin li scrive **il driver display**
  negli endpoint Azalia del DCN: `dce_audio.c` (`dce_aud_az_configure` r. 665: `AZALIA_F0_CODEC_PIN_CONTROL_
  AUDIO_DESCRIPTOR0..13` (SAD dall'EDID), `_CHANNEL_SPEAKER`, `_SINK_INFO0..8` (nome monitor, ID produttore),
  `_RESPONSE_LIPSYNC`, `_HOT_PLUG_CONTROL`; accesso indiretto tramite `AZF0ENDPOINTn_AZALIA_F0_CODEC_ENDPOINT_INDEX/
  DATA`, dword seg2 `0x0386` per l'endpoint 0), `dce_aud_az_enable` (r. 613), `dce_aud_wall_dto_setup` (r. 1072:
  DTO audio nel DCCG, `DCCG_AUDIO_DTO_SOURCE` seg1 0x00ab), pacchetti audio nel flusso via AFMT/APG
  (`afmt3`, `apg31`), abilitati da `dce110_enable_audio_stream`. In Linux il componente DRM-audio
  (`amdgpu_dm_audio.c`, bind visto in dmesg) notifica `snd_hda_intel` a ogni hotplug/modeset.
- Per macOS: AppleHDA dovrebbe pilotare il controller HDA (con `hda-gfx`/`layout-id` come per le AMD supportate),
  ma l'audio funzionerà solo se il framebuffer programma endpoint Azalia, AFMT/APG e DTO audio a ogni modeset
  (e usa la modalità HDMI, non DVI, nel DIG FE). Cobalt64 usa la modalità **DVI** per gli HDMI secondari
  (`navi48_disp2.h:8`: "DIG2 front end: source OTG1, DVI mode") → niente audio né infoframe. Stadio tardivo.

## 8. Confronto con i progetti di riferimento (Navi 48) e cosa cambia per Navi 44

### 8.1 RDNA4FB.kext / AMDRadeonRDNA4.kext [VERIFICATO]

- I due repository hanno **sorgenti e README identici** (`diff -r src` vuoto; stesso commit `5ff69aa`
  "Add BSD 3-Clause License"): sono lo stesso progetto sotto due nomi. ~3 900 righe (`src/framebuffer.cpp`
  2 424, `atombios.cpp` 369, `ipdiscovery.cpp` 153, `edid.cpp` 103, `otgtiming.cpp` 41, `dmub.hpp` 83).
- Cosa fa (README + codice): sottoclasse `IOFramebuffer` (installata in `/Library/Extensions`, Aux KC, perché
  IOGraphicsFamily sta nel System KC e OpenCore non può iniettarla), `IOPCIPrimaryMatch` 0x7550/0x7551.
  **Adotta** la scanout del GOP (`PE_state.video`, mascherando i bit flag bassi di `v_baseAddr`), espone **un solo
  modo**, `getApertureRange()` = BAR0 della scanout. Implementa: parser AtomBIOS e IP discovery (basi registri da
  discovery, anche leggendo la copia nella TMR via `MM_INDEX/MM_DATA`), **EDID via AUX** (engine
  `DP_AUXn`, `kAuxBase0 = 0x16b2`, stride 0x1c, `framebuffer.cpp:423-590`, porting di `dce_aux.c`) e **via DDC
  I2C** (`DC_I2C`, porting di `dce_i2c_hw.c`, r. 792), **display sleep** (7.2), **cursore HW** (opt-in,
  `initHWCursor`/`setCursorImage`/`setCursorState` r. 1652-1905), **VBL emulato** da timer (r. 1502), sonde
  read-only di PSP, SMU (TestMessage sul mailbox MP1), IH, DMUB.
- Scoperte utili verificate su Navi 48: (1) il DMCUB pre-OS lasciato dal GOP **serve il ring inbox1** (ha
  consumato 0x4c0 byte = 19 comandi del GOP) ma **ignora l'inbox0 a registri**; (2) il ring sta nella finestra
  `DMCUB_REGION4` (`regDMCUB_REGION4_OFFSET(_HIGH)` = seg2 0x0196/0x0197) in cima alla VRAM; indirizzo VRAM =
  `REGION4_MC − (DCN_VM_FB_LOCATION_BASE & 0xffffff) << 24` (`dmubHistory`, `framebuffer.cpp:1162-1210`);
  (3) **la storia dei comandi del GOP rimane leggibile nel ring** (`rdna4-dmubhist=1`): è la "ricetta" esatta
  (DIGX_ENCODER_CONTROL / DIG1_TRANSMITTER_CONTROL / SET_PIXEL_CLOCK con i loro payload) che il firmware ha
  accettato per accendere il display di boot; (4) `QUERY_FEATURE_CAPS` sul ring risponde (ping).
- Limiti: solo il display di boot, nessun modeset, nessuna accelerazione.

### 8.2 Cobalt64 `src/dcn41` + `src/navi48-bringup/src/dcn` [VERIFICATO; dettagli nel report 05 §7.4]

- `src/dcn41` (4 661 righe): layer registri generato da `dcn_4_1_0_offset.h`/`_sh_mask.h` con allowlist di
  scrittura, funzioni che rispecchiano singole funzioni Linux (`hubp401_program_surface_flip_and_addr`,
  `optc1_get_position`, …), layout DMUB verificati contro `dmub_cmd.h` (`dcn41_dmub_layout.h`: `sizeof(union
  dmub_rb_cmd) == 64`, `dmub_dig_transmitter_control_data_v1_7 == 60`, `set_pixel_clock_parameter_v1_7 == 16`…).
- `navi48_dcn.cpp`/`navi48_disp2.h`/`navi48_dmubcmd.h`: adozione della pipe GOP, flip di superfici, prove di modo
  da tabelle (`navi48_modetrial_tables.h`), accensione manuale di 2° e 3° display (OTG1/ODM1/OPP1/DPG1 + DIG2 →
  UNIPHY_C; OTG2/DIG3 → UNIPHY_D) con timing 1080p60/1440p60 delle EDID dei loro monitor; PHY e PLL accesi
  inviando al **DMCUB pre-OS** comandi `DMUB_CMD__VBIOS` mainline (sub-type 1 TRANSMITTER_CONTROL, 2
  SET_PIXEL_CLOCK, timeout 2 s) e comandi del "dialetto VBIOS" (header `0x04000a80` detect+EDID, `0x08000680`
  begin/end mode change, `0x08000580` set mode, `0x04000780`/`0x04000880` enable/disable output; contesti DFP a
  REGION4+0x6800/0x7000/0x7800), `navi48_dmubcmd.h:47-75`. HDMI secondari in modalità DVI. Nessun link training DP
  da zero, nessun DML/watermark, nessun DSC, niente HDMI > 340 MHz.

### 8.3 Tabella delle differenze Navi 48 → Navi 44 per il display

| Aspetto | Navi 48 (riferimenti) | Navi 44 (questa scheda) | Fonte / stato |
|---|---|---|---|
| IP display | DMU 4.1.0 → DCN 4.0.1 | **identico** | discovery; `amdgpu_discovery.c:2684-2690` [V] |
| Basi segmento DMU | `0x12 0xc0 0x34c0 0x9000 0x2403c00` | **identiche** | discovery [V] |
| Offset registri DCN | `dcn_4_1_0_offset.h` | **identici** | [V] |
| Pipe/OTG/HUBP/DPP/OPP | 4 (`res_cap_dcn4_01`) | **4**, nessun fuse (`CC_DC_PIPE_DIS` → 4 HUBP nel DTN log) | [V] |
| DSC | 4 | 4 | `res_cap_dcn4_01` [V] |
| HPO DP / HPO FRL | 4 / 1 | 4 / 1 | [V] |
| Stream encoder DIO / audio endpoint | 4 / 4 | 4 / 4 (codec HDA 4 pin) | [V] |
| PHY cablati | tipicamente 4 (A..D) | **3: A, B, C** (`max_disp_phy_num 3`) | VBIOS [V] |
| Connettori | ref. 9070 XT degli autori: DP su PHY B, HDMI su PHY C/D | **DP-1 = PHY A/DDC1/HPD1, HDMI-A-1 = PHY B/DDC2/HPD2, HDMI-A-2 = PHY C/DDC3/HPD3** | VBIOS [V] |
| Velocità max connettore | dipende dalla scheda | DP ≤ UHBR13.5 (no UHBR20); HDMI FRL ≤ 10G/corsia | VBIOS [V] |
| `external_rev_id` / macro DC | 0x5x → `ASICREV_IS_GC_12_0_0_A0` | **0x41 → `ASICREV_IS_GC_12_0_1_A0`** | [V] |
| Canali MALL per DC | 16 | **8** | `dcn401_resource.c:1463` [V] |
| `dcc_plane_width_limit` | nessuno | **7680** | `dcn401_resource.c:2113` [V] |
| Idle DPM UCLK/FCLK, DF throttle | SMU ≥ 0x681800 / no | SMU ≥ 0x661300 / ≥ 0x663500 (abilitati con SMC 102.71.0) | `dcn401_clk_mgr.c:128-150` [V] |
| Canali UMC (limite richieste SDPIF) | 16 (256 bit) | 8 (128 bit, 4 UMC) | `umc_info` / dmesg [V] |
| Firmware DMCUB | `dcn_4_0_1_dmcub.bin` | **stesso file** | [V] |
| DISPCLK boot / refclk | (VBIOS loro) | 625 MHz / 100 MHz | VBIOS [V] |
| Ring DMCUB pre-OS (REGION4), contesti DFP | ring 0x2000, contesti +0x6800/0x7000/0x7800 per DFP2/3/4 | ring atteso uguale; **contesti da rimisurare** (DFP1/2/3) | [I] |
| `PCI ID` nei kext | 0x7550/0x7551 | **0x7590** | [V] |

**Cosa va cambiato nel codice dei riferimenti per Navi 44**: (1) `IOPCIPrimaryMatch` 0x7590; (2) ogni costante
"istanza → DIG/PHY/DDC/HPD/AUX" va derivata dall'object table + GPIO LUT del VBIOS (sez. 3.4-3.5) invece che
cablata (in Cobalt: `N48D2_INST_MONA/MONB`, "istanza 2 = PHY D" non esiste); (3) il codice che assume il DP di
boot su uno specifico DIG/stream encoder (RDNA4FB `DP0_DP_VID_STREAM_CNTL`, Cobalt "DIG1/PHY B") va reso
dinamico leggendo `DIGn_DIG_BE_CNTL`/`DIGn_DIG_FE_CNTL`/`DIGn_STREAM_MAPPER_CONTROL` (seg2 0x1f0d + n); (4) offset dei contesti DFP del firmware
pre-OS da rimisurare; (5) i modi cablati vanno sostituiti con quelli delle EDID dei monitor dell'utente; (6) il
resto (basi, offset, layout DMUB, sequenze HUBP/OTG) è riusabile tale e quale.

## 9. Requisiti per un IOFramebuffer macOS e piano a stadi

### 9.1 Cosa deve implementare il driver display su macOS [INFERITO da IOGraphics + riferimenti]

- **Classe**: sottoclasse `IOFramebuffer` per ogni display/connettore (Cobalt64: `Navi48Framebuffer` con
  `Navi48DisplayIndex` 1/2 su un nub dedicato; RDNA4FB: una sola istanza). Installazione in
  `/Library/Extensions` (Aux KC) perché IOGraphicsFamily non è nel Boot KC (README RDNA4FB).
- **Metodi minimi** (quelli che RDNA4FB implementa, `framebuffer.cpp:2176-2424`): `enableController`,
  `isConsoleDevice`, `getApertureRange`/`getVRAMRange`, `getPixelFormats`, `getDisplayModeCount`/`getDisplayModes`,
  `getInformationForDisplayMode`, `getPixelFormatsForDisplayMode`, `getPixelInformation`,
  `getCurrentDisplayMode`/`setDisplayMode`, `getAttribute`/`setAttribute` (power), `getConnectionCount`,
  `getAttributeForConnection`/`setAttributeForConnection` (enable, sense HPD, power, probe),
  `hasDDCConnect`/`getDDCBlock` (EDID → IODisplay riconosce il monitor), `registerForInterruptType`
  (`kIOFBVBLInterruptType`, `kIOFBConnectInterruptType` per l'hotplug)/`setInterruptState`/`unregisterInterrupt`,
  `setCursorImage`/`setCursorState` (cursore HW), registrazione power management (stati sleep/doze/wake).
- **Per Metal/WindowServer accelerato**: il percorso di presentazione passa da `IOAccelDisplayPipe` (Cobalt64
  `Navi48DisplayPipe`) che il kext principale traduce in flip HUBP (6.8); il framebuffer deve condividere con
  l'acceleratore lo stesso allocatore VRAM (superfici di scanout in VRAM con indirizzo MC noto, pitch allineato a
  256 B, formato `ARGB8888`/`ARGB2101010` lineare o con swizzle GFX12 supportato dall'HUBP) e consegnare vblank
  reali (IH) per il pacing.
- **Vincoli kext**: niente FPU/SSE nel kernel (Cobalt `make kextcheck` lo verifica): **DML 2.1 non può girare nel
  kext così com'è** (è compilato con flag FPU in Linux, `dml2_0/Makefile:28-75`). Alternative: tabelle
  pre-calcolate su Linux, oppure eseguire DML in un demone user space che passa i risultati al kext, oppure un
  "DML ridotto" a interi per i casi semplici (1-3 pipe, nessun ODM/MALL/SubVP). Il codice DC è **MIT**
  (`SPDX-License-Identifier: MIT` in `dcn401_resource.c`, `dml2_wrapper.c`): portabile senza vincoli di licenza,
  ma è grande (`display/dc` 458 055 righe .c in totale, di cui per DCN 4.0.1 servono core 25 709 + link 21 757 +
  dml21 52 102 + blocchi dcn401/dcn10-32 ereditati + dmub 6 868).
- **ReBAR**: Linux vede BAR0 = 16 GiB. Cobalt64 raccomanda di limitarlo (≤ 1 GiB) per macOS (report 05); il
  framebuffer GOP deve restare nella parte di VRAM mappata.

### 9.2 Piano a stadi raccomandato

| Stadio | Obiettivo | Cosa serve (blocchi) | Dipendenze dal resto del driver | Riuso | Rischio |
|---|---|---|---|---|---|
| **0. Dati** (Linux) | EDID dei monitor, DTN log per ogni modo voluto, dump stato GOP e ring DMCUB pre-OS | sez. 10 | nessuna | – | basso |
| **1. Adozione GOP** | desktop macOS (rendering software) sul display di boot, 1 modo | lettura stato HUBP/OTG/DIG (6.2), `getApertureRange` = scanout, EDID via AUX/DDC (6.6), VBL emulato, display sleep DP (7.2), cursore HW (6.7) | nessuna (niente PSP/SMU/IH) | RDNA4FB quasi tutto (+ `0x7590`, mapping da VBIOS) | basso |
| **1b. Flip e vblank veri** | WindowServer accelerato su 1 display | flip HUBP (6.2/6.8), interrupt VSTARTUP/PFLIP via IH (7.1), allocazione superfici in VRAM | IH 7.0 + MSI (report 01), allocatore VRAM | Cobalt64 `dcn41` (flip), `SCAN_*` | medio |
| **2. Modi fissi** | cambiare risoluzione/refresh senza toccare il link | stesso link DP (stesso rate/lane) o stesso clock TMDS: timing OTG (6.3.3), DP DTO, HUBP size/viewport, DPP scaler o 1:1, **tabelle DLG/TTU/RQ/WM/DET catturate su Linux**; DISPCLK/DPPCLK sufficienti (eventuale `SetHardMinByFreq`) | SMU (mailbox DAL) se servono clock più alti | Cobalt64 "modetrial"/"same-mode re-timing" | medio |
| **3. Modeset nativo** | accendere un connettore da spento, hotplug | DMCUB (riuso pre-OS o caricamento via PSP + VBIOS in CW3), PHY on/off/swing via `DIG1_TRANSMITTER_CONTROL`, pixel clock (DP DTO / `SET_PIXEL_CLOCK`), **DP link training 8b/10b** (6.4), **HDMI TMDS + SCDC scrambling** (6.5), HPD IRQ, DIG FE/BE + stream mapper, infoframe AVI | PSP/SMU (report 01) se il DMCUB va ricaricato o se mancano clock; IH | Linux `link_dp_training*.c`, `link_dpms.c`; Cobalt64 `navi48_dmubcmd`/`disp2` come esempio | alto |
| **4. Multi-display** | 3 connettori contemporanei | 1 pipe per display, DET/WM globali, PLL/DTO per istanza, power gating domini pipe | stadi 3 | – | alto |
| **5. Completamento** | audio HDMI/DP, S3, 10 bpc/HDR, VRR, DSC, UHBR, FRL, MALL/FAMS2 | 7.3/7.4, HPO, DSC, DML | re-POST AtomBIOS `asic_init`, PSP/SMU completi | Linux DC | alto |

Indicazioni pratiche:
- Durante gli stadi 1-2 il driver GPU **non deve** resettare il DCN né il DMCUB (niente equivalente di
  `dmub_srv_hw_reset`), e deve evitare che l'SMU cambi UCLK sotto la scanout del GOP (6.2 rischi).
- Nello stadio 3 conviene prima provare a **riusare il DMCUB pre-OS** (ring REGION4) con i soli comandi mainline
  `DMUB_CMD__VBIOS` 1/2 (come Cobalt64), usando come ricetta la storia del ring lasciata dal GOP (RDNA4FB
  `rdna4-dmubhist`). Il caricamento via PSP del firmware Linux è il piano B (e il piano obbligato per lo S3).
- Nessun monitor all'avvio = nessuna pipe da adottare: lo stadio 1 deve degradare con grazia (macOS userà il suo
  framebuffer di fallback) finché non c'è lo stadio 3.
- Per HDMI 4K@60 serve TMDS 594 MHz con scrambling (SCDC); per DP 4K@60 basta HBR2 × 4 (8b/10b); 4K@120/144 su DP
  richiede HBR3 + DSC o UHBR (rimandare).

## 10. Domande aperte e dati privilegiati mancanti

Da raccogliere su Linux (servono root o un boot speciale; **non eseguiti** in questa analisi per le regole del task):
1. **EDID dei monitor dell'utente**: alla lettura tutti i connettori erano `disconnected` (sez. 2.1). Con i monitor
   accesi: `cat /sys/class/drm/card1-*/edid > ...` (non privilegiato) e `modes`; annotare quale monitor è su quale
   connettore (DP-1 / HDMI-A-1 / HDMI-A-2).
2. **DTN log per modo** (`/sys/kernel/debug/dri/1/amdgpu_dm_dtn_log`, root) con ciascun modo desiderato attivo:
   fornisce HUBP/RQ/DLG/TTU/WM/MPCC/OTG da riprodurre come tabelle nello stadio 2.
3. **Stato del GOP prima di amdgpu**: avviare Linux con `modprobe.blacklist=amdgpu` e leggere (root, `resource5`
   mmap in sola lettura) i registri OTG/HUBP/DIG/DCCG e `DMCUB_REGION4_OFFSET(_HIGH)`, `DMCUB_INBOX1_*`,
   `DMCUB_SCRATCH0..15`, poi il ring REGION4 in VRAM (`resource0`): quale pipe/DIG/PHY accende il GOP su questa
   scheda, con quale formato/pitch, e la sequenza di comandi DMUB del GOP (equivalente di `rdna4-dmubhist`).
   Ripetere con il monitor solo su DP e solo su HDMI.
4. `amdgpu_dm_dmub_fw_state` (root; in `hw_dump/dmub_fw_state.txt` la lettura è fallita con "Operation not
   permitted") e `amdgpu_dm_dmub_tracebuffer`.
5. **Backdoor load del DMCUB**: su DCN 4.0.1 di produzione `DMCUB_SEC_CNTL`/`REGION3_CW0` sono scrivibili
   dall'host e il DMCUB esegue codice non verificato dal PSP? Non verificabile senza esperimento rischioso.
6. Il DMCUB **pre-OS** di Navi 44 usa lo stesso "dialetto VBIOS" (header `0x04000a80`, `0x08000580`…) e gli
   stessi offset di contesto visti da Cobalt64 su Navi 48? Va misurato (punto 3).
7. Che cosa fa il GOP se il monitor è su HDMI a 4K: usa scrambling (SCDC) o sceglie un modo ≤ 340 MHz? (punto 3).
8. Valori di `DCN_VM_FB_LOCATION_BASE`/`DCN_VM_FB_OFFSET` e configurazione GPUVM del DCN (`DCN_VM_*`, contesti
   VMID dell'HUBP) lasciati dal GOP e da amdgpu (amdgpu usa superfici con indirizzi MC fisici o via GART?).
9. Verifica su hardware del comportamento di `CC_DC_PIPE_DIS` (atteso 0 nei 4 bit bassi, dedotto dal DTN log).
10. Limiti DISPCLK/DPPCLK/DTBCLK dell'SMU per questa scheda (`GetDpmFreqByIndex`/`GetDcModeMaxDpmFreq`, visibili nei log
    `DC_LOG_SMU` con `amdgpu.dc_debug`/dynamic debug, root).

## Appendice A. Comandi e strumenti usati in questa analisi (tutti non privilegiati)

- `cat /sys/class/drm/card1-*/{status,enabled,dpms,modes,connector_id}`, `wc -c edid`, `readlink ddc`,
  `/sys/bus/i2c/devices/i2c-*/name`, `/sys/class/drm/card1/device/power/runtime_status`.
- `journalctl -k -b` (righe amdgpu/vgaarb/simpledrm/PM), `cat /proc/asound/cards`, `/proc/asound/card1/eld#*`,
  `codec#0`, `lspci -s 03:00.1 -nn`, `cat /sys/power/mem_sleep`.
- Script propri in `scratchpad/display/scripts/`: `ipdisc.py` (tabella IP discovery), `vbios_parse.py` (atomfirmware:
  header, master command/data table, firmwareinfo v3.5, dce_info v4.5, gpio_pin_lut, displayobjectinfo v1.5 con
  record), `regabs.py` (indirizzi MMIO assoluti da `dcn_4_1_0_offset.h` + basi discovery), `dmcub_hdr.py` (header e
  meta del firmware DMCUB). Output VBIOS completo: `scratchpad/display/vbios_parse.out`.
- Dati già dumpati: `hw_dump/ip_discovery_table.bin`, `vbios.rom`, `dm_dtn_log.txt`, `dm_capabilities.txt`
  (`mall supported: yes, enabled: no`; `sub-viewport supported: yes, enabled: no`), `pp_features.txt`,
  `firmware_info.txt`, `gca_config.bin`.
- Nessuna scrittura su sysfs/debugfs, nessun reload di moduli, nessun programma eseguito dai progetti in `refs/`.
