# 07 - Stack AMD di Apple su macOS e approccio Lilu: fattibilita' per RDNA4 / Navi 44

> Stato: completo (2026-10-12), **rivisto** dopo la verifica. Legenda: **[VERIFICATO]** = controllato su codice locale, dati hardware o test eseguito; **[INFERITO]** = deduzione/ricostruzione, da confermare; **[WEB]** = fonte web citata.
>
> **Nota di revisione (licenze)**: una prima versione di questo report citava dettagli ricavati dal codice sorgente di
> NootRX e NootedRed. Quei progetti sono distribuiti con la "ChefKiss Open Knowledge License v1", che vieta le opere
> derivate e **qualsiasi uso del codice con strumenti di IA**, compresi lettura e analisi (§2-§3 della licenza). Quei
> dettagli sono stati **rimossi** e i cloni locali cancellati; il report si basa ora solo su fonti compatibili: pagine e
> discussioni pubbliche (issue GitHub #144, guide Dortania e ChefKiss), WhateverGreen (BSD-3), OpenCore Legacy Patcher,
> documentazione OpenCore, sorgenti Linux/Mesa e test eseguiti su questa macchina. Il contenuto rimosso non va
> ricostruito né riusato.

## 0. Sommario esecutivo

1. **Lo stack AMD di Apple e' legato a versioni IP precise**, non e' un driver Navi generico: `AMDRadeonX6000Framebuffer`
   (display DCN 2.x/3.x), `AMDRadeonX6000HWServices` + plugin HWLibs per chip (inizializzazione ASIC con firmware incorporati),
   `AMDRadeonX6000` (IOAccelerator), e in user space `AMDRadeonX6000MTLDriver.bundle` (Metal + compilatore AMD gfx10),
   `GLDriver`, `VADriver2`, `Shared`. Correzione al brief: `AMDMTLBronzeDriver.bundle` e' il driver Metal **GCN/Polaris**, non
   quello Navi. **[VERIFICATO sugli inventari OCLP e WhateverGreen]**
2. **NootRX e NootedRed** (plugin Lilu di ChefKiss) estendono lo stack Apple a Navi 22 / ID Navi 2x non Apple e agli APU Vega.
   Per dichiarazione pubblica del maintainer, Navi 22 funziona perche' e' "interfacciata a livello hardware come gli altri Navi 2x
   supportati da Apple"; RDNA 3/4 richiederebbero modifiche a HWLibs, framebuffer e bundle user space (AddrLib) e, per RDNA 4,
   *"a whole lot more work"*, senza piani. **[WEB, issue #144]**
3. **Per RDNA4 nessuna precondizione dell'approccio Lilu e' vera**: Apple non ha codice per GC 12, SDMA 7, PSP 14, SMU 14, MES 12,
   IH 7, GMC 12 (nuovo layout PTE: MTYPE bit 54-55, PRT 56, IS_PTE 63), DCN 4.0.1, VCN 5, AddrLib Gfx12; e l'ISA gfx12 e' binariamente
   incompatibile con gfx10 per load/store/sample/wait (test `llvm-mc` eseguito). **[VERIFICATO + WEB]**
4. **macOS x86 finisce con Tahoe 26** (macOS 27 e' solo Apple silicon, pagina Apple salvata). I kext AMD Apple sono ancora in
   Tahoe (Mac Pro 2019/iMac 2020 li richiedono) ma non evolveranno piu'. Un driver GPU deve essere un kext (DriverKit non ha
   famiglie grafiche) caricato via AuxKC, sul percorso `IOGraphicsFamily` + `IOAcceleratorFamily2`.
5. **Piattaforma**: Ryzen 7 7700 -> AMD Vanilla con patch IOPCIFamily Zen 4 e core count `BA 08 00 00 00`, `ProvideCurrentCpuInfo`;
   SMBIOS **MacPro7,1** (iMacPro1,1 non e' in Tahoe); Wi-Fi/BT **Qualcomm WCN785x (17cb:1107, 0489:e10a) senza driver macOS**;
   Ethernet RTL8125 (LucyRTL8125); USB <= 14 porte per controller; iGPU Raphael senza driver (disabilitarla o usarla come console GOP).
   **La board ha una COM1 16550A vera a 0x3F8/IRQ4**: kprintf su seriale a costo zero. GPU sola nel suo IOMMU group: passthrough in VM
   e' un'opzione di sviluppo concreta. **[VERIFICATO su questa macchina]**
6. **Verdetto: route custom RADV-based** (kext proprio + RADV/ACO Darwin + plugin Metal che traduce AIR), sul modello nullmoth/Cobalt64.
   Il riuso dei kext Apple AMDRadeonX6000 per Navi 44 non e' praticabile; Lilu resta utile solo come utility (AMFIPass, eventuali
   patch board-id/DRM).

## 1. Componenti AMD di Apple e loro ruoli

### 1.1 Fonti usate e limiti

Non c'e' un macOS installato su questa macchina, quindi i binari Apple non sono stati esaminati qui. Fonti:

- **OpenCore Legacy Patcher** (patchset `amd_navi.py`, `amd_polaris.py`, `amd_vega.py`, `amd_legacy_gcn.py`, `tahoe_graphics.py`
  salvati nella scratchpad della sessione): elencano *per nome* i bundle AMD che OCLP reinstalla sul volume di sistema, quindi sono
  l'inventario piu' affidabile dei file Apple AMD per versione di macOS **[VERIFICATO sui file salvati]**.
- **WhateverGreen** (`research/refs/WhateverGreen`, BSD-3, `kern_rad.cpp`) per i nomi dei kext acceleratore per generazione.
- **Dortania GPU Buyers Guide** e pagina di compatibilita' ChefKiss per le GPU supportate.
- Issue pubblica NootRX #144 per le dichiarazioni del maintainer su RDNA 3/4.

### 1.2 Inventario dei componenti (x86_64, macOS 11-26)

| Componente | Tipo | Ruolo | Evidenza |
|---|---|---|---|
| `AMDSupport.kext` | kext | base comune "legacy" (framebuffer GCN, `AMD*Controller.kext`); **non** usato dal percorso Navi | OCLP `amd_legacy_gcn.py`/`amd_polaris.py` lo reinstallano con i Controller GCN; `amd_navi.py` no **[VERIFICATO]** |
| `AMDRadeonX6000Framebuffer.kext` | kext (IOFramebuffer) | display per RDNA1/RDNA2 (DCN 2.0/2.1/3.0/3.0.2), con codice derivato dal Display Core AMD [INFERITO] | OCLP `amd_navi.py` **[VERIFICATO nome]** |
| `AMDRadeonX6000HWServices.kext` (+ librerie HWLibs per chip) | kext | HAL di inizializzazione ASIC per blocchi IP con firmware incorporati e PowerPlay [INFERITO] | OCLP `amd_navi.py` **[VERIFICATO nome di HWServices]**; nomi delle HWLibs e ruolo [INFERITO] |
| `AMDRadeonX6000.kext` | kext (IOAccelerator) | acceleratore: canali PM4/SDMA, memoria GPU, user client per i driver user space, video VCN, AddrLib Gfx10 [INFERITO] | OCLP; WEG `kern_rad.cpp` |
| `AMDRadeonX6000GLDriver.bundle` | user space | driver OpenGL | OCLP `amd_navi.py` **[VERIFICATO nome]** |
| `AMDRadeonX6000MTLDriver.bundle` | user space | **driver Metal (UMD) per Navi** con il compilatore shader AMD che abbassa l'AIR a ISA gfx10 [INFERITO per la collocazione del compilatore] | OCLP `amd_navi.py` (varianti "12.5-24"/"12.5-25" per Sequoia/Tahoe) **[VERIFICATO nome]** |
| `AMDMTLBronzeDriver.bundle` | user space | driver Metal **GCN** (Polaris/X4000), *non* Navi; Vega usa `AMDRadeonX5000MTLDriver.bundle` | OCLP `amd_polaris.py`, `amd_legacy_gcn.py`, `amd_vega.py` **[VERIFICATO]** |
| `AMDRadeonX6000Shared.bundle`, `AMDShared.bundle` | user space | librerie condivise tra GL/Metal/VA [INFERITO] | OCLP (AMDShared ha una variante "12.5-25" per Tahoe) **[VERIFICATO nome]** |
| `AMDRadeonVADriver2.bundle` | user space | VideoToolbox decode/encode HW (VCN 2/3) | OCLP **[VERIFICATO nome]** |
| `AppleGraphicsDevicePolicy.kext` (in `AppleGraphicsControl.kext`) | kext | policy per board-id: su SMBIOS iMac/iMacPro puo' spegnere le uscite della dGPU (da cui `agdpmod=pikera`) | WEG `README.md` **[VERIFICATO]** |

Famiglie Apple Radeon per generazione (WEG `kern_rad.cpp:23-40`): `AMDRadeonX3000` (TeraScale 2), `X4000` (GCN 1-4, Polaris),
`X5000` (Vega/GFX9), `X6000` (Navi/GFX10). Non esiste un `X7000`/`X8000`: Apple non ha mai scritto un acceleratore per GFX11 (RDNA3)
o GFX12 (RDNA4) **[VERIFICATO per assenza in WEG e OCLP; coerente con la guida Dortania]**.

### 1.3 GPU supportate nativamente dallo stack X6000

| Chip | gfx | Device ID (esempi) | Mac reale | Stato in macOS |
|---|---|---|---|---|
| Navi 10 | gfx1010 | 0x731F (RX 5700/XT, W5700X) | Mac Pro 2019 (MPX W5700X), iMac 2020 | nativo da 10.15.1 [WEB: Dortania] |
| Navi 14 | gfx1012 | 0x7340 (RX 5500, Pro 5300M/5500M) | MacBook Pro 16" 2019, iMac 2020 | nativo [INFERITO] |
| Navi 12 | gfx1011 | 0x7360 (Pro 5600M HBM2) | MacBook Pro 16" 2020 | nativo [INFERITO] |
| Navi 21 | gfx1030 | 0x73BF (RX 6800/XT/6900 XT), 0x73A3 (W6800) | Mac Pro 2019 (W6800X/W6900X) | nativo da 11.4 [WEB: Dortania] |
| Navi 23 | gfx1032 | 0x73FF (RX 6600/XT), 0x73E3 (W6600) | Mac Pro 2019 (W6600X) | nativo da 12.1 [WEB: Dortania] |
| Navi 22 | gfx1031 | 0x73DF (RX 6700/XT) | nessuno | **non** nativo: solo con NootRX [WEB: compatibilita' ChefKiss] |
| Navi 24 | gfx1034 | 0x743F (RX 6400/6500) | nessuno | non supportato [WEB: compatibilita' ChefKiss] |

### 1.4 Implicazione

Lo stack Apple non e' "un driver Navi generico": ogni livello (HAL, framebuffer, acceleratore, AddrLib, bundle Metal/GL/VA) e'
scritto per *specifiche versioni IP* (GC 10.1/10.3.x, SDMA 5.x, PSP 11, SMU 11.0.x, DCN 2.x/3.x, VCN 2/3). Puo' funzionare per un
chip non supportato solo se esiste gia' un percorso per una versione IP gemella (coerente con le dichiarazioni pubbliche del
maintainer di NootRX, issue #144).

## 2. L'approccio Lilu (NootRX / NootedRed): cosa si sa da fonti pubbliche

- **NootRX**: plugin Lilu che abilita le GPU RDNA 2 dedicate non supportate da Apple (Navi 22 e ID Navi 21/23 non Apple) sullo stack
  `AMDRadeonX6000`; Navi 24 e RDNA 3 non supportate [WEB: pagina di compatibilita' ChefKiss, kext.me].
- **NootedRed**: plugin Lilu per gli APU basati su Vega (Raven/Renoir); non copre Raphael (RDNA 2 integrata del Ryzen 7000) [WEB].
- **Perche' Navi 22 funziona**: secondo il maintainer e un partecipante all'issue #144, perche' e' interfacciata a livello hardware
  come gli altri Navi 2x supportati da Apple (stesse generazioni IP, solo versioni minori diverse) e serve "incollare" la logica e i
  firmware mancanti [WEB, commenti del 2026-06-23 e 2026-07-29].
- **Condizioni generali** (nostro ragionamento, basato sulle versioni IP di Linux e sui test ISA): un approccio "patch dello stack
  Apple" funziona solo se (1) l'HAL Apple contiene gia' un percorso per versioni IP vicine; (2) il firmware si carica con lo stesso
  protocollo PSP/SMU; (3) il display e' una variante del DCN gia' presente; (4) **l'ISA e' compatibile** con quella per cui il
  compilatore shader chiuso del bundle Metal/GL genera codice; (5) AddrLib conosce la famiglia di swizzle; (6) la gestione delle code
  e' quella attesa dall'acceleratore Apple (PM4 diretto, niente MES). Per Navi 22 sono vere; per RDNA 4 nessuna (sez. 3).
- Licenza: "ChefKiss Open Knowledge License v1" (nessuna opera derivata, nessun uso con IA): il codice non va usato ne' analizzato.

## 3. Perche' RDNA3 e' difficile e RDNA4 ancora di piu'

### 3.1 Cosa dice il maintainer di NootRX nell'issue pubblica #144 "Navi 3x support" [WEB]

Issue aperta il 2026-02-19 (RX 7700 XT), ancora aperta; dati salvati in scratchpad `apple-amd-lilu/web/issue144*.json`.
Punti tecnici del maintainer (VisualEhrmanntraut, MEMBER):

- 2026-06-23: *"RDNA3/4 is a derivative of RDNA 2 with different firmware, display hardware, and additional instructions.
  Technically speaking, it is possible to fully support (excluding Raytracing) RDNA 3, and maybe even RDNA 4 with a whole lot
  more work. But at the end of the day, what would the benefit be, since x86 macOS is going fully EOL in around 3 years?"*
- 2026-07-12: *"for RDNA 4 the work is a matter of changes to the Hardware Abstraction Library (`AMDRadeon*HWLibs.kext`), the
  framebuffer (`AMDRadeonX6000Framebuffer.kext`), and the userspace bundle (the Metal and OpenGL implementations,
  `AMDRadeon*MTLDriver.bundle`/`AMDRadeon*GLDriver.bundle`) mainly due to differences with AddrLib"*.
- 2026-07-29 (in risposta a metacollin, che nota che tutto sarebbe patch binarie su codice chiuso e *"totally unrealistic to
  expect one person unpaid, let alone a team of people working full time"*): *"All known/obvious information ... there's no team
  (anymore ...), it's just me"*; e su un'eventuale apertura del codice Apple: *"They will never"*.
- 2026-10-09: risposta a chi cita il driver NVIDIA (nullmoth) chiedendo RX 9000: posta screenshot di un punteggio Metal
  pessimo e un altro membro (EAZYBLACK) commenta *"The metal score shown in the screenshot is worse than a GT 710. Its unusable."*
  Sono le uniche dichiarazioni pubbliche su RDNA4: nessun lavoro in corso.

Nota di lettura: "possibile ... with a whole lot more work" e' detto da chi conosce gli internals meglio di chiunque, ma con
l'esclusione del ray tracing e senza piani concreti. Le sezioni seguenti quantificano quel "whole lot".

### 3.2 Distanza IP per IP: chip supportati da Apple vs RDNA3 vs Navi 44

| Blocco | Navi 21 / 22 / 23 (Apple) | RDNA3 (Navi 31/32/33) | **Navi 44 (questa scheda)** | Navi 48 | Codice Apple esistente? |
|---|---|---|---|---|---|
| GC / ISA | 10.3.0 / 10.3.2 / 10.3.4, gfx1030/1031/1032 | 11.0.0/11.0.3/11.0.2, gfx1100-1102 | **12.0.0, gfx1200** | 12.0.1, gfx1201 | solo GC 9.x/10.x |
| famiglia (`FAMILY_*`) | `AMDGPU_FAMILY_NV` 0x8F (Linux `include/uapi/drm/amdgpu_drm.h`) | `FAMILY_NV3` 0x91 | **`FAMILY_NV4` 0x98** (gca_config, `hw_dump/README.md`; `amdgpu_asic_addr.h:36`), ext rev 0x41 in `AMDGPU_GFX1200_RANGE 0x40..0x50` | stessa famiglia, range GFX1201 0x50.. | solo famiglie fino a NV [INFERITO] |
| SDMA | 5.2.0/5.2.2/5.2.4 | 6.0.x | **7.0.0** | 7.0.1 | solo 4.x/5.x |
| PSP (MP0) | 11.0.7/11.0.11/11.0.12 | 13.0.0/13.0.7/13.0.10 | **14.0.2** | 14.0.3 | solo 3.1/10/11/12 |
| SMU (MP1) | 11.0.7/11.0.11/11.0.12 (Linux `sienna_cichlid_ppt.c`) | 13.0.0/13.0.7/13.0.10 | **14.0.2** (driver_if 0x2E, SCPM, PPTable solo da PMFW) | 14.0.3 | solo SMU fino all'11 [INFERITO] |
| Display | DCN 3.0 / 3.0 / 3.0.2 + DMCUB | DCN 3.2 / 3.2.1 | **DCN 4.0.1** (DMU 4.1.0 in discovery, riscritto in 4.0.1 dal driver, report 01 §1.4) | DCN 4.0.1 | DCN 1/2/2.1/3.0/3.0.2 nel DC Apple |
| Code/scheduler | PM4 su HQD programmate dal driver [INFERITO] | **MES 11** (Linux: `enable_mes=true` per tutti i GC 11.x) | **MES 12** (Linux: `amdgpu_discovery.c:2994-3001`, `enable_mes = enable_mes_kiq = true`, uni-MES; la KIQ classica non e' mai usata, report 01 §2.9) | MES 12 | nessuno |
| CP firmware | F32 (CE/PFP/ME/MEC) | RS64 PFP/ME/MEC + IMU, niente CE | **RS64 + IMU** (`gc_12_0_0_{imu,me,mec,mes,mes1,pfp,rlc,toc,uni_mes}`) | `gc_12_0_1_*` (+ `_kicker`) | formato F32 |
| GMC / PTE | GMC 10, MTYPE bit 48-50 (`AMDGPU_PTE_MTYPE_NV10`, `amdgpu_vm.h:114`), PRT bit 51 | GMC 11 (layout NV10) | **GMC 12: MTYPE bit 54-55, PRT bit 56, DCC/NOALLOC bit 58, IS_PTE/PDE_PTE bit 63** (`amdgpu_vm.h:121-140`; report 01 §2.4) | idem | layout gfx10 |
| IH | OSSSYS 5.x | 6.0 | **7.0.0** | 7.0.0 | no |
| Video | VCN 3.0 | VCN 4.0 | **VCN 5.0.0 / JPEG 5.0.0** | 5.0.0 (stesso `vcn_5_0_0.bin`) | VCN 2/3 |
| AddrLib | `Gfx10Lib` (swizzle `SW_64KB_R_X` ecc.) | `Gfx11Lib` | **`Gfx12Lib`/Addr3**: solo `LINEAR, 256B_2D, 4KB_2D, 64KB_2D, 256KB_2D, 4KB_3D, 64KB_3D, 256KB_3D` (`addrlib/inc/addrtypes.h:285-296`), DCC trasparente via PTE | idem | solo Gfx9/Gfx10 |

Fonti: hardware facts misurati (brief), `hw_dump/README.md`, report 01; Linux `amdgpu_discovery.c`, `amdgpu_vm.h`,
`sienna_cichlid_ppt.c`; Mesa `addrlib`. Le versioni RDNA3/Navi48 sono da Linux (case `IP_VERSION` in discovery) **[VERIFICATO
per gfx12 e Navi2x; RDNA3 riportato per confronto]**.

**Differenze Navi 44 vs Navi 48 rilevanti qui**: nessuna cambia la conclusione. Navi 44 e' GC 12.0.0 (firmware `gc_12_0_0_*`,
`psp_14_0_2_*`, `smu_14_0_2`), Navi 48 e' GC 12.0.1 (`gc_12_0_1_*` + varianti `_kicker`, PSP/SMU 14.0.3); 32 CU / 2 SE / 8 RB,
GDDR6 128-bit. Per l'approccio Lilu sarebbero due "porting" distinti delle stesse tabelle, come Navi21 vs Navi23 per Apple.

### 3.3 Perche' RDNA3 e' "difficile" (gia' fuori portata Lilu classica)

1. **ISA gfx11**: nuove codifiche (VOPD dual-issue, `s_delay_alu`, export/LDS rinnovati, ecc.). Il compilatore shader
   dentro `AMDRadeonX6000MTLDriver.bundle`/`GLDriver` emette solo gfx10: servirebbe un backend nuovo dentro un binario chiuso.
2. **MES 11 + RS64**: il firmware CP cambia architettura (RS64), sparisce il CE, le code sono pensate per essere mappate da MES.
   L'acceleratore Apple programma direttamente ring/HQD [INFERITO].
3. **PSP 13 / SMU 13 / DCN 3.2 / VCN 4 / SDMA 6 / IH 6**: nessuna versione gemella in HWLibs/framebuffer -> ogni blocco IP da
   reimplementare, per *tutti* i blocchi, con struct interne Apple non documentate.
4. **AddrLib Gfx11**: nuove modalita' swizzle; serve sia nel kernel (`AMDRadeonX6000.kext` include AddrLib) sia nei bundle.

### 3.4 Perche' RDNA4 (Navi 44) e' "piu' difficile" ancora

Oltre a tutti i punti RDNA3, per gfx12:

1. **ISA gfx12 incompatibile a livello binario con gfx10** per gli accessi a memoria e i contatori di attesa. Test eseguito
   con `llvm-mc` 23.1.1 (scratchpad `apple-amd-lilu/isa/a.s`, `b.s`) **[VERIFICATO]**:

   | Istruzione | gfx1030 (RDNA2) | gfx1200 (Navi 44) |
   |---|---|---|
   | wait | `s_waitcnt vmcnt(0) lgkmcnt(0)` -> `[0x70,0x00,0x8c,0xbf]` | contatori separati: `s_wait_loadcnt 0x0` -> `[0x00,0x00,0xc0,0xbf]`, `s_wait_kmcnt 0x0` -> `[0x00,0x00,0xc7,0xbf]` (non esistono su gfx1030: *"instruction not supported on this GPU (gfx1030)"*) |
   | buffer load | `buffer_load_dword v1, v2, s[4:7], 0 offen` MUBUF 8 byte `[0x00,0x10,0x30,0xe0,...]` | MUBUF rifiutato (*"operands are not valid for this GPU"*); `buffer_load_b32 ... null offen` VBUFFER **12 byte** `[0x7c,0x00,0x05,0xc4,...]` |
   | image sample | MIMG `[0x08,0x0f,0x80,0xf0,...]` | rifiutato in forma gfx10; VSAMPLE `[0x01,0xc0,0xc6,0xe7,...]` |
   | VALU semplice | `v_mov_b32 v0, v1` -> `[0x01,0x03,0x00,0x7e]` | identico |

   Cioe' qualunque shader prodotto dal compilatore Apple per gfx10 andrebbe in fault/hang sulla 9060 XT al primo accesso a
   memoria. Non e' patchabile "a byte": serve un compilatore gfx12 (in Mesa: ACO; in LLVM: target `gfx1200`).
2. **Descrittori e DCC**: gfx12 cambia il layout dei resource descriptor e sposta la compressione in un modello
   "trasparente" (PTE bit 58 + `COMPRESSION_EN`, metadati nascosti, report 03 punto 4). Il codice Apple che costruisce
   descrittori (bundle Metal/GL) e gestisce i metadati DCC (kernel + user-space) e' da riscrivere.
3. **Niente CLEAR_STATE/shadowing FW**: su gfx12 l'IB utente programma ring NGG e scratch con `SET_*_REG_PAIRS` (report 03).
   L'acceleratore Apple presuppone il modello gfx10.
4. **MES 12 obbligatorio nel modello Linux** e uni-MES: Apple non ha codice MES (su RDNA 2 le code sono programmate direttamente [INFERITO]).
5. **PSP 14 / SMU 14 con SCPM**: firmware firmati, PPTable letta solo dal PMFW, protocollo mailbox `MP1_SMN_C2PMSG_66`
   (report 01 §SMU). Il caricamento firmware dell'HAL Apple e' pensato per PSP 11; PSP 14 ha
   un TOC diverso (`gc_12_0_0_toc`), IMU, autoload RLC.
6. **DCN 4.0.1**: il DC Apple e' un fork vecchio del DC AMD; DCN 4 (DCN401 in Linux) aggiunge nuovi blocchi (MPC/DPP/
   OPTC rinnovati, DML2) e un DMCUB nuovo (`dcn_4_0_1_dmcub`, fw 0x0A004B00). Report 02 copre i dettagli.
7. **Nuovo PTE format**: tutto il codice di page table dell'acceleratore/HWLibs (VMID, GART) va rifatto per MTYPE/PRT/IS_PTE
   ai bit gfx12.
8. **Ray tracing**: Apple non ha mai esposto RT su AMD; RDNA4 ha BVH8/RT 3.1 (report 03) che non sarebbe usabile comunque.

### 3.5 Stima di lavoro (route Lilu per Navi 44) [INFERITO]

Per adattare lo stack Apple a Navi 44 bisognerebbe reimplementare **dentro i binari Apple, via hook**:
GMC12/MMHUB 4.1, IH 7, PSP 14 + IMU + RLC autoload, SMU 14.0.2, GFX12 CP RS64, MES 12, SDMA 7, DCN 4.0.1 (dentro il DC
Apple), VCN 5 (opzionale), e **sostituire integralmente** il compilatore shader e la costruzione di descrittori/PM4 nei
bundle Metal/GL user-space. In pratica si scriverebbe un driver nuovo ma con l'handicap di doverlo incastrare in struct e
vtable Apple non documentate, che cambiano a ogni point release.
A quel punto "riusare Apple" significa riusare soltanto lo scheletro IOKit (sottoclassi framebuffer e IOAccelerator, user client) e non il sapere hardware, che e' esattamente la parte di valore.

## 4. Panorama versioni macOS x86: Sequoia 15, Tahoe 26, kext deprecation, AuxKC, IOGraphics

### 4.1 Linea temporale rilevante per un driver GPU x86

| macOS | Darwin | Fatto rilevante | Fonte |
|---|---|---|---|
| 11 Big Sur | 20 | Kernel Collections (Boot KC, System KC, **Auxiliary KC** per kext di terze parti); Navi21 nativo da 11.4 | report 06 §8.1; Dortania [WEB] |
| 12 Monterey | 21 | Navi23 nativo da 12.1 | [WEB: Dortania] |
| 13 Ventura | 22 | *"Apple no longer provides standalone kexts in the base OS"*: i binari dei kext stanno solo nelle KC, per estrarli serve il **KDK** (`amd_navi.py`, `requires_kernel_debug_kit`); *"In Ventura, Apple added AVX2.0 code to AMD's OpenCL/GL compilers"* (Zen 4 ha AVX2/AVX-512: `/proc/cpuinfo` **[VERIFICATO]**) | OCLP **[VERIFICATO]** |
| 15 Sequoia | 24 | target del driver NVIDIA nullmoth; OCLP ha varianti `"12.5-24"` dei bundle Metal AMD | report 06; `amd_navi.py` |
| **26 Tahoe** | 25 | **ultima release Intel**; Mac Intel supportati: MacBook Pro 16" 2019, MacBook Pro 13" 2020 (4 TB3), **iMac 2020**, **Mac Pro 2019**; nuova UI Liquid Glass: OCLP deve sostituire `RenderBox.framework/.../default.metallib` per GPU Metal "3802" (`tahoe_graphics.py`) | 9to5Mac 2026-05-18 salvato (`web/9165eb06.html`) **[WEB]**; OCLP **[VERIFICATO]** |
| 27 "Golden Gate" | 26 | **solo Apple silicon**: la pagina Apple elenca solo MacBook Neo/Air/Pro, iMac, Mac mini, Mac Studio, Mac Pro *with Apple silicon* | `web/c1413815.html` (apple.com) **[WEB, VERIFICATO sul file salvato]** |

Conseguenza: la finestra di vita di un driver GPU x86 e' **Tahoe 26.x** (aggiornamenti di sicurezza tipicamente per ~2 anni dopo
il successore, cioe' fino a circa fine 2028 [INFERITO dalla prassi Apple]); il maintainer di NootRX, nell'issue #144, parla di
fully EOL in around 3 years"* (#144). Lato positivo: dopo l'ultima point release le ABI di `IOAcceleratorFamily2`/`IOGraphicsFamily`
di Tahoe smetteranno di muoversi, cosa che favorisce un driver custom a lunga vita [INFERITO].

### 4.2 I kext AMD Apple sono ancora in Tahoe? E dopo?

- **Si', in Tahoe 26 (x86)** [INFERITO, alta confidenza]: tre dei quattro Mac Intel supportati hanno GPU AMD che usano esattamente
  lo stack descritto (iMac 2020: Radeon Pro 5300/5500 XT/5700/5700 XT = Navi14/Navi10; MacBook Pro 16" 2019: Pro 5300M/5500M/5600M
  = Navi14/Navi12; Mac Pro 2019: 580X Polaris, Vega II, W5500X/W5700X, W6600X/W6800X/W6900X = X4000/X5000/X6000). Conferme indirette:
  OCLP mantiene varianti Tahoe (`"12.5-25"`) dei bundle AMD **[VERIFICATO sui file OCLP]**.
- **No, da macOS 27**: senza x86 non esiste piu' nessun kext AMD (gli Apple silicon non supportano GPU esterne). Lo stack Apple AMD
  quindi **non ricevera' mai** supporto RDNA3/RDNA4 e dal 2026 in poi riceve al massimo fix di sicurezza.
- I kext Apple **non fanno match** con la 9060 XT (1002:7590): nessuna personality Apple contiene 0x7590 (le liste viste vanno da
  0x731F a 0x73FF) [INFERITO]. Quindi un driver custom non entra in
  conflitto con lo stack Apple; per sicurezza esiste comunque `-amd_no_dgpu_accel` (boot-arg Apple, OpenCore `Configuration.tex`
  riga ~5228) per inibire l'acceleratore AMD Apple.

### 4.3 Deprecazione dei kext, DriverKit, AuxKC

- Apple ha deprecato i kext dal 10.15 a favore di DriverKit, ma **DriverKit non ha famiglie grafiche** (niente `IOFramebuffer`,
  `IOAccelerator`, `IOSurface` lato driver): un driver che deve pilotare il display e far girare Metal per WindowServer **deve
  essere un kext** [INFERITO, conoscenza consolidata; coerente con nullmoth e Cobalt64 che usano kext]. PCIDriverKit basta solo per
  compute "di lato" (cosi' fa `refs/mac-amdgpu` su Apple silicon via Thunderbolt).
- Su x86 Tahoe i kext di terze parti si caricano ancora: o iniettati da OpenCore nella Boot KC (come Lilu), o installati in
  `/Library/Extensions` e linkati nell'**AuxKC** con `kmutil` + approvazione utente. Nullmoth ha dovuto usare l'AuxKC perche' i suoi
  kext display linkano `IOGraphicsFamily`/`IOAcceleratorFamily2` presenti solo nelle KC di sistema (report 06 §8.1, con la procedura
  `kmutil create -n aux ...` dettagliata). Lo stesso vale per noi.
- Requisiti di sicurezza (report 06 §8.2): `SecureBootModel=Disabled`, SIP parziale (`csr-active-config` 0x0A43 nel caso nullmoth),
  AMFI rilassato (`amfi_get_out_of_my_way=0x1` o AMFIPass) perche' il plugin Metal non firmato Apple venga caricato da WindowServer.

### 4.4 IOGraphics vs IOMobileFramebuffer su x86

- **x86 (Intel e AMD/NVIDIA dGPU)**: display tramite `IOGraphicsFamily` (`IOFramebuffer` per ogni head, `IODisplay`), policy/AGDC
  tramite `AppleGraphicsControl` (AGDP/AGDC), accelerazione tramite `IOAcceleratorFamily2` (`IOGraphicsAccelerator2`, user client
  condivisi, `IOSurface`). E' cio' che usano `AMDRadeonX6000Framebuffer` e `AMDRadeonX6000` [INFERITO], il driver nullmoth (report 06 §2-3) e Cobalt64 (report 05).
- **Apple silicon**: `IOMobileFramebuffer` (DCP, `AppleCLCD2`) + AGX; non esiste su x86 e non serve a noi [INFERITO].
- Tahoe x86 mantiene il percorso IOFramebuffer (gli iMac 2020/Mac Pro 2019 lo usano) [INFERITO]. Il blueprint nullmoth (Sequoia 15,
  NVAccel distinto per 15 e 26 in `/Library/NullMoth/kexts/{15,26}/`, report 06 §8.1) indica pero' che **l'ABI di IOAccelerator
  cambia tra 15 e 26**: un driver che vuole entrambe le release dovra' compilare due varianti dell'acceleratore.

### 4.5 Quale macOS puntare

| Opzione | Pro | Contro |
|---|---|---|
| **Tahoe 26** (raccomandato come target finale) | ultima release x86, vita piu' lunga, ABI che si congelera'; Cobalt64 (RDNA4) punta gia' a Tahoe (report 05) | UI Liquid Glass piu' pesante su Metal (patch RenderBox in OCLP), meno anni di esperienza della comunita' |
| **Sequoia 15** (utile come primo banco) | nullmoth dimostrato su 15; tooling e KDK maturi; UI piu' leggera | supporto di sicurezza finisce prima; due ABI da mantenere se poi si passa a 26 |

Suggerimento: sviluppare il kext su **Tahoe 26** e tenere Sequoia solo come fallback di confronto se un comportamento di
`IOAcceleratorFamily2` diverge [INFERITO].

## 5. Requisiti OpenCore per Ryzen 7 7700 / MSI B840 Gaming Plus WiFi

### 5.1 Inventario hardware rilevante (misurato su questa macchina, utente non privilegiato) [VERIFICATO]

`lspci -nn`, `lsusb`, `/sys/bus/usb/devices/usb*/maxchild`, `/sys/class/tty/ttyS*`, `/sys/bus/pnp/devices`, `/proc/cpuinfo`:

| Dispositivo | ID | Supporto macOS | Azione |
|---|---|---|---|
| CPU Ryzen 7 7700 (Zen 4, 8C/16T, AVX2+AVX-512) | fam 19h | via AMD Vanilla patches | core count **0x08** |
| RX 9060 XT (Navi 44) | 1002:7590 rev c0, audio 1002:ab40 | **nessun driver** (oggetto del progetto); boot framebuffer GOP | IOMMU group 15 da sola (audio group 16), `reset_method = bus` |
| iGPU Raphael (gfx1036, RDNA2) | 1002:164e rev c5, audio 1002:1640 | **nessun driver** (NootedRed copre solo gli APU Vega, non RDNA 2 integrata) [WEB] | disabilitare in BIOS o usarla come console GOP (5.4) |
| Ethernet Realtek RTL8125 (2.5 GbE, rev 0c = RTL8125BG) | 10ec:8125 | kext di terze parti `LucyRTL8125Ethernet` [INFERITO] | ok per rete, **probabilmente senza KDP** (sez. 6) |
| Wi-Fi **Qualcomm FastConnect 7800 / WCN785x** (Wi-Fi 7) | 17cb:1107 | **nessun driver macOS** (itlwm/AirportItlwm sono solo Intel) [INFERITO] | sostituire il modulo M.2 con Broadcom BCM94360NG/BCM943602 o vivere senza Wi-Fi |
| Bluetooth (parte del modulo Qualcomm) | USB 0489:e10a (Foxconn) | nessun driver | come sopra |
| xHCI chipset B840 | 1022:43ef (05:00.0): 10 porte USB2 + 4 USB3 = 14 | AppleUSBXHCIPCI generico | **<=15 porte per controller**: `XhciPortLimit` non serve; mappa comunque (USBToolBox/UTBMap) |
| xHCI CPU | 1022:15b6 (2+2), 1022:15b7 (2+2), 1022:15b8 (1 USB2) | generico | idem |
| SATA chipset | 1022:43eb | AHCI generico | — |
| NVMe Lexar NM790 (Maxio) / Samsung 980 (DRAM-less) | 1d97:1602 / 144d:a809 | NVMe generico | compatibilita' da verificare (domande aperte); `NVMeFix` |
| Audio Realtek ALC897 (HDA 1022:15e3) | — | AppleALC (layout da scegliere) [WEB: specifiche retailer] | opzionale |
| **UART 16550A COM1** | ACPI `PNP0501`, io 0x3f8-0x3ff irq 4, `ttyS0 type=4` | supportato nativamente da XNU per `serial=`/kprintf | **chiave per il debugging** (sez. 6); header JCOM1 [WEB: retailer cita "1x Com Port (JCOM)"] |

### 5.2 Patch kernel AMD Vanilla e quirk (Zen 4) [VERIFICATO sui file salvati `web/amd_vanilla_readme.md`, `web/oc_zen.md`]

- Patch `Kernel > Patch` da AMD_Vanilla (supporto dichiarato da 10.13 a **Tahoe 26**); richiedono **`Kernel > Quirks >
  ProvideCurrentCpuInfo = YES`** (*"or the system won't boot"*).
- **Zen 4**: la patch per `IOPCIFamily.kext` e' abilitata di default e va tenuta (*"for Zen 4 stability"*; serve anche per board
  MSI A520/B550/X570). Il B840 usa un chipset della linea Promontory (SATA 1022:43eb e' lo stesso ID dei chipset 500 [INFERITO dal
  nome PCI]), quindi la patch e' doppiamente pertinente.
- **Core count**: nelle quattro patch `algrey - Force cpuid_cores_per_package` sostituire solo `Replace`; per macOS 13.3+ (quindi
  Sequoia/Tahoe) il valore e' `BA <core> 0000 00` -> **`BA 08 00 00 00`** per 8 core fisici (non 16 thread).
- PAT: tenere la patch `mtrr_update_action - fix PAT` di algrey (default, compatibile con tutto); Sequoia ha la sua variante.
  L'alternativa di Shaneee migliora le prestazioni GPU AMD *Apple* ma non ci riguarda.
- Patch "Fix PCI bus enumeration" solo per board AM5 con Thunderbolt/USB4 on-board: non e' il nostro caso (disabilitata).
- Quirk Kernel (Dortania Zen): `DummyPowerManagement=YES`, `PanicNoKextDump=YES`, `PowerTimeoutKernelPanic=YES`,
  `ProvideCurrentCpuInfo=YES`, `XhciPortLimit=NO` (11.3+), `DisableIoMapper=NO`, `AppleXcpmCfgLock=NO`, `LapicKernelPanic=NO`.
- Quirk Booter: `RebuildAppleMemoryMap=YES`, `SyncRuntimePermissions=YES`, `SetupVirtualMap=YES` (*"X570, B550, A520 ... might need
  this disabled"*: da provare), `EnableWriteUnprotector=NO`, `DevirtualiseMmio=NO` (solo TRx40).
- SSDT: `SSDT-EC-USBX` obbligatorio; `SSDT-CPUR` e' indicato per B550/A520 (definizioni CPU): da verificare sul DSDT della B840 se
  i processori sono dichiarati come `Device (ACPI0007)` (serve il dump ACPI, privilegiato: domande aperte).

### 5.3 SMBIOS

| SMBIOS | Pro | Contro |
|---|---|---|
| **MacPro7,1** (raccomandato) | supportato da **Tahoe** (Mac Pro 2019 e' nella lista dei 4 Mac Intel, sez. 4.1); Mac senza iGPU, pensato per dGPU AMD; la policy AGDP non spegne le uscite della dGPU [INFERITO] | avvisi su memoria/PCI da silenziare con `RestrictEvents.kext` [INFERITO] |
| iMacPro1,1 | usato da nullmoth su Sequoia (report 06) | **non supportato da Tahoe** (l'iMac Pro non e' tra i 4 Mac Intel di Tahoe) -> servirebbe `-no_compat_check`/spoof; AGDP richiede `agdpmod=pikera` |

### 5.4 iGPU Raphael: disabilitarla o lasciarla "non reclamata"

macOS non ha alcun driver per gfx1036; il rischio e' che il firmware la scelga come display primario (GOP) o che macOS provi a usare
il suo framebuffer UEFI. Due strategie:

1. **Disabilitarla in BIOS** (Integrated Graphics = Disabled / Primary = PCIe): configurazione piu' pulita, la 9060 XT e' il
   display GOP di avvio; la sua audio 1002:1640 sparisce. **Consigliata per l'uso normale e per l'installazione.**
2. **Lasciarla attiva come display primario "console"** [INFERITO, da provare]: macOS userebbe il framebuffer GOP della Raphael
   (non accelerato, lentissimo ma visibile) mentre la 9060 XT resta *secondaria e non reclamata* da qualunque driver: e' la
   configurazione ideale **durante lo sviluppo del kext**, perche' un crash/hang del nostro driver non toglie l'unico display.
   Va verificato che OpenCore/macOS accettino un boot display su una GPU senza driver e che il BIOS MSI permetta "IGD primario" con
   dGPU presente.

In entrambi i casi niente `disable-gpu` sulla 9060 XT; `-wegnoigpu` (WhateverGreen) non serve se WEG non e' caricato.

### 5.5 Resizable BAR

Stato attuale (Linux): ReBAR attivo, **BAR0 = 16 GB** (tutta la VRAM), BAR2 = 256 MB doorbell, BAR5 = 512 KB MMIO; GPU dietro lo
switch PCIe interno (fatti hardware del brief). OpenCore (`web/oc_config.tex:1843-1872, 9304-9350`) **[VERIFICATO]**:

- `Booter > Quirks > ResizeAppleGpuBars` riduce le BAR *solo per macOS*: *"While Apple macOS supports a theoretical 1 GB maximum,
  in practice all non-default values may not work correctly ... the only supported value ... is 0"*; `-1` = lascia stare.
  Il limite di 1 GB riguarda i driver AMD/Apple esistenti; un driver nostro puo' gestire una BAR grande.
- `UEFI > Quirks > ResizeGpuBars` imposta la dimensione per tutti gli OS (0 = 1 MB ... 19 = 512 GB).

Raccomandazione [INFERITO, da validare]: per l'**installer** e i primi boot senza driver usare `ResizeAppleGpuBars=0` (come
nullmoth: il framebuffer GOP sopravvive al setup PCI solo con BAR piccola, report 06 §8.2); con il **nostro kext** passare a
`ResizeAppleGpuBars=-1` per avere BAR0 = 16 GB (accesso CPU diretto a tutta la VRAM, utile per upload e per il backing di
IOSurface) e verificare in `ioreg` che IOPCIFamily assegni la BAR sopra 4 GB anche attraverso i bridge dello switch interno.
In alternativa, BAR0 = 256 MB con aperture mobile e DMA via SDMA (come i driver Apple storici).

### 5.6 Kext di terze parti e impostazioni BIOS

- Kext OpenCore minimi: `Lilu` (+ `AMFIPass` se si segue lo schema nullmoth), `VirtualSMC`, `AppleALC` (ALC897),
  `LucyRTL8125Ethernet`, `NVMeFix`, `RestrictEvents`, mappa USB (USBToolBox + `UTBMap.kext`). **Non** servono WhateverGreen,
  NootRX o NootedRed (nessuno supporta i nostri due GPU); il nostro driver andra' nell'AuxKC (sez. 4.3).
- BIOS (Dortania "AMD BIOS Settings" + nostre aggiunte): Above 4G Decoding **ON**, Re-Size BAR **ON** (gestita poi dai quirk),
  CSM **OFF**, Secure Boot **OFF**, Fast Boot **OFF**, IOMMU **OFF** per macOS (Dortania; su Linux serve se si usa VFIO, vedi sez. 6.5),
  XHCI hand-off ON, SATA AHCI; **COM port: lasciarla ABILITATA** (Dortania suggerisce di disabilitarla, ma per noi e' lo strumento di
  debug principale).

## 6. Setup di kernel debugging su Hackintosh AMD

### 6.1 Seriale (kprintf) - lo strumento principale

**Hardware [VERIFICATO]**: la board espone un 16550A legacy a **I/O 0x3F8, IRQ 4** (`/sys/class/tty/ttyS0/type = 4`, ACPI
`PNP0501` attivo). E' esattamente la porta che XNU usa di default, quindi **non** servono `CustomPciSerialDevice` ne' schede PCIe.
Serve un cavo dall'header JCOM1 (livelli RS-232, non TTL [INFERITO: header COM standard MSI]) a una porta seriale/USB-RS232 sul PC
host Linux (`picocom -b 115200 /dev/ttyUSB0`). Nota OpenCore: su molte board TX/GND sono etichettati male
(`oc_config.tex` ~riga 9840).

**Boot-args** (OpenCore `Configuration.tex` **[VERIFICATO]**; bit da `osfmk/kern/debug.h` di XNU **[WEB, raw GitHub
apple-oss-distributions/xnu]**):

| Boot-arg | Effetto |
|---|---|
| `serial=3` | `SERIALMODE_OUTPUT` (0x1) + `SERIALMODE_INPUT` (0x2); `0x4` drain sincrono, `0x10` niente IOLog su seriale |
| `debug=0x8` | `DB_KPRT`: `kprintf` va sulla seriale (richiesto per l'output kernel) |
| `debug=0x108 serial=5 msgbuf=1048576` | ricetta OpenCore per i fallimenti di boot precoci (0x100 = vecchio `DB_LOG_PI_SCRN`, "no reboot on panic" secondo Dortania) |
| `keepsyms=1`, `-v` | simboli nel panic e verbose |
| `debug=0x2` | `DB_PRT`: panic sempre stampato su seriale |
| `debug=0x44` | `DB_NMI` (0x4) + `DB_ARP` (0x40): attesa debugger su NMI, risposta ARP per KDP di rete |
| `debug=0x1` | `DB_HALT`: si ferma al boot aspettando il debugger (solo kernel DEVELOPMENT/DEBUG) |
| `debug=0x400`/`0x2000` | core dump / invio paniclog su panic |
| `-liludbgall liludump=N` | log Lilu (versioni DEBUG) se si usano plugin Lilu |

Nel nostro kext: `kprintf()` per tracce sincrone (sopravvivono ai panic, utili per la sequenza PSP/SMU/GFX), `IOLog()` per
`log show/stream`.

### 6.2 KDK e kernel DEVELOPMENT

- Scaricare dal portale Apple Developer il **Kernel Debug Kit della build esatta** (es. `KDK_26.x_<build>.kdk`): contiene kernel
  RELEASE/DEVELOPMENT/DEBUG/KASAN con DWARF, `lldbmacros`, e - da Ventura - i **binari standalone dei kext Apple** (serve anche per
  disassemblare `IOAcceleratorFamily2`/`IOGraphicsFamily` e, se interessa, `AMDRadeonX6000*`) [INFERITO; il fatto dei kext standalone e'
  la motivazione di OCLP `requires_kernel_debug_kit` **VERIFICATO**].
- Per avviare il kernel DEVELOPMENT su Big Sur+: SIP con `CSR_ALLOW_UNAUTHENTICATED_ROOT` (0x800, gia' nel set nullmoth 0x0A43),
  ricostruire Boot/System KC con `kmutil create ... --kernel <KDK>/kernel.development` e usare `kcsuffix=development` [INFERITO dalla
  ReadMe dei KDK; da verificare su Tahoe]. `kmutil` vuole il KDK anche per creare l'AuxKC (`--allow-missing-kdk` in nullmoth).

### 6.3 lldb remoto (KDP)

- **KDP via Ethernet**: richiede un driver NIC con supporto KDP in modalita' polled; i driver Apple nativi lo hanno (es. Intel I210,
  Aquantia AQC107 dei Mac Pro/iMac Pro, adattatori Thunderbolt-Ethernet Apple) [INFERITO]; `LucyRTL8125Ethernet` molto probabilmente no.
  Il Wi-Fi non e' supportato (blog Quarkslab "An overview of macOS kernel debugging" **[WEB]**). Opzione economica: una
  **Intel I210-T1 PCIe** dedicata al debug, poi `debug=0x44 kdp_match_name=en1` e da host `lldb` -> `kdp-remote <ip>`.
- **KDP via seriale**: XNU incapsula KDP (UDP finto) sulla seriale; sul host un proxy (*SerialKDPProxy*, D. Elliott) traduce
  seriale <-> UDP e `lldb` si collega a `kdp-remote localhost` **[WEB]**; boot-arg `kdp_match_name=serial` [INFERITO dal nome
  della funzione, da verificare]. Con una COM1 vera e' la soluzione a costo zero, ma a 115200 baud e' lenta.
- Il host di sviluppo e' Linux: `lldb` non e' installato qui (verificato: `lldb not found`) e il plugin KDP (`ProcessKDP`,
  "MacOSX-Kernel") potrebbe non essere compilato nelle build Linux di LLDB -> **domanda aperta**; in alternativa lldb su un secondo
  Mac/VM macOS.
- Limite noto: dopo `continue` il debugger remoto non puo' fermare il kernel; serve un breakpoint o un **NMI** (`DB_NMI` 0x4; su
  hardware reale combinazione tasti/pulsante con `DB_NMI_BTN_ENA` 0x8000) **[WEB Quarkslab + debug.h]**.

### 6.4 Panic log

- Con NVRAM funzionante il panic viene salvato e al riavvio compare in `/Library/Logs/DiagnosticReports/*.panic` (Console.app).
  OpenCore puo' salvarlo anche sulla ESP (`Misc > Debug > ApplePanic`, citato nei "Tips and Tricks" di `Configuration.tex`).
- Per i panic dentro il nostro kext: `keepsyms=1` + simbolizzazione con il dSYM del kext e `atos`/`lldb` sul `kernelcache`.
- La seriale con `debug=0x2` (`DB_PRT`) stampa il panic anche se il disco non e' raggiungibile.

### 6.5 Opzione fortemente consigliata per la fase iniziale: macOS in VM con passthrough della 9060 XT [INFERITO]

Dati a favore misurati qui: la 9060 XT e' **sola nel suo IOMMU group (15)**, la sua audio nel 16, `reset_method = bus` (secondary
bus reset tramite lo switch interno) **[VERIFICATO]**. Un macOS x86 in QEMU/KVM (OpenCore, CPU host Zen 4) con la GPU in VFIO
darebbe: **gdbstub di QEMU** sul kernel macOS (breakpoint hardware, nessuna dipendenza da KDP/NIC), snapshot della VM, nessun
reboot dell'host a ogni panic, seriale virtuale per `kprintf`. Rischi: reset GPU tra un run e l'altro (con PSP/SMU 14 un
"bus reset" potrebbe non bastare a riportare la GPU allo stato pulito: il driver dovra' gestire una GPU gia' inizializzata o forzare
un mode1 reset via PSP), IOMMU da abilitare in BIOS lato Linux, `AppleVTD`/IOMMU da disattivare nel guest. Da validare in un passo
dedicato (non eseguito ora: le regole vietano di toccare lo stato della GPU).

## 7. Verdetto: riuso kext Apple vs percorso custom (RADV-based)

### 7.1 Matrice di confronto

| Criterio | Route A: riuso stack Apple X6000 via Lilu | Route B: driver custom (kext + RADV/ACO + layer Metal) |
|---|---|---|
| Conoscenza hardware gfx12 disponibile | **zero** nei binari Apple (nessun GC 11/12, SDMA 6/7, PSP 13/14, SMU 13/14, MES, DCN 3.2/4, IH 6/7, GMC 11/12, AddrLib Gfx11/12) | completa e aperta: Linux amdgpu (report 01/02), Mesa RADV/ACO + addrlib gfx12 (report 03), dump reali di MQD/ring/firmware (`hw_dump/`) |
| Compilatore shader | Apple/AMD solo gfx10 (dentro `AMDRadeonX6000MTLDriver.bundle`); gfx12 binariamente incompatibile (test `llvm-mc` sez. 3.4) | ACO/LLVM gfx1200 gia' funzionanti su questa macchina (report 03/04) |
| Code e firmware | nessun MES; caricamento firmware PSP 11-style; da riscrivere dentro HWLibs con hook | sequenza Linux PSP14->SMU14->GMC12->IH7->GFX12/MES12->SDMA7 documentata (report 01) e gia' portata a Darwin per Navi 48 da Cobalt64 (report 05) |
| Display | DC Apple vecchio senza DCN 4 | DCN 4.0.1 dal DC Linux (report 02) o, all'inizio, solo framebuffer GOP + scanout minimo (RDNA4FB per Navi48 come riferimento) |
| Manutenzione | patch binarie per ogni point release su codice chiuso | sorgente nostro; dipende solo dalle ABI pubbliche di IOKit/IOAcceleratorFamily2 (che su Tahoe dovrebbero congelarsi) |
| Licenza/legale | redistribuzione di firmware/binari Apple modificati in memoria; il codice NootRX/NootedRed e' sotto licenza ChefKiss (nessuna opera derivata, nessun uso con IA) | Linux amdgpu MIT (per la maggior parte), Mesa MIT, firmware AMD ridistribuibile in binario (linux-firmware) |
| Precedenti | nessun precedente RDNA3/4; maintainer unico, *"it's just me"* (issue #144) | nullmoth (NVIDIA Turing+ su Sequoia, Metal via traduzione a Vulkan/NVK, report 06) e Cobalt64 (RDNA4 Navi48 su Tahoe, kext + RADV Darwin, report 05) dimostrano l'architettura |
| Prestazioni attese | se mai funzionasse, Metal nativo AMD (ottimo) | Metal sopra Vulkan: overhead di traduzione AIR->SPIR-V/NIR; prestazioni da misurare (il punteggio "peggiore di una GT 710" citato in #144 riguarda un driver diverso, non e' un limite intrinseco) |

### 7.2 Verdetto

**Route A (riuso dei kext Apple AMDRadeonX6000 per Navi 44) non e' praticabile.** Motivazione in una riga per livello:

1. **HAL (HWLibs)**: un approccio a patch funziona solo se nei binari Apple esiste gia' un percorso per una versione IP *gemella*;
   per GC 12.0.0 / SDMA 7.0 / PSP 14.0.2 / SMU 14.0.2 /
   MES 12 / IH 7 / GMC 12 non esiste nulla da riusare: andrebbe riscritto ogni blocco
   dentro struct Apple non documentate.
2. **Framebuffer**: il DC Apple non contiene DCN 4.0.1; il display andrebbe riscritto comunque.
3. **Acceleratore + AddrLib kernel**: modello gfx10 (HQD diretti, CE, PTE NV10, swizzle Gfx10) contro gfx12 (MES, RS64, PTE con
   MTYPE a bit 54-55, Addr3 con 8 modalita', DCC trasparente via PTE bit 58).
4. **Bundle Metal/GL/VA**: il compilatore AMD dentro il bundle genera gfx10; MUBUF/MIMG/`s_waitcnt` non esistono piu' in gfx12.
   Questo da solo e' un blocco totale: non si patcha un compilatore chiuso per un nuovo ISA.
5. **Orizzonte temporale**: x86 macOS finisce con Tahoe 26; lo stack Apple AMD non evolvera' piu'.

Di Apple resta riusabile **solo cio' che e' di Apple e generico**: `IOPCIFamily`, `IOGraphicsFamily` (IOFramebuffer),
`IOAcceleratorFamily2`, `IOSurface`, `AppleGraphicsControl`, Metal.framework con il suo meccanismo di plugin (`/Library/GPUBundles`,
report 06 §5), `MTLCompilerService` come front-end MSL->AIR. Cioe' il "contratto" macOS, non il sapere AMD.

**Route B (custom, RADV-based) e' la strada raccomandata per Navi 44**, nella forma gia' validata da nullmoth (NVIDIA) e Cobalt64
(Navi 48): kext proprio (PCI/BAR/IRQ + init PSP14/SMU14/GMC12/IH7/GFX12+MES12/SDMA7 dal codice Linux + IOFramebuffer DCN 4.0.1 +
IOAccelerator/user client) + RADV/ACO portato a Darwin (winsys sopra il nostro user client) + plugin Metal in `/Library/GPUBundles`
che traduce AIR in Vulkan/SPIR-V (report 08). Specificita' Navi 44 da rispettare rispetto ai riferimenti Navi 48: firmware
`gc_12_0_0_*`/`psp_14_0_2_*`/`smu_14_0_2`/`sdma_7_0_0`/`dcn_4_0_1_dmcub`/`vcn_5_0_0` (niente varianti `_kicker`), GC 12.0.0 con
2 SE x 2 SH x 8 CU = 32 CU, 8 RB, `gb_addr_config 0x08200545`, info device gfx1200 (non le info canned gfx1201 di Cobalt64, report 03).

### 7.3 Cosa prendere comunque dall'ecosistema Lilu (uso "utility", non riuso dello stack AMD)

- **Lilu come libreria di patch** per eventuali controlli Apple che ostacolano una GPU non-Apple (board-id/AGDP, DRM)
  e come base di AMFIPass, gia' usato da nullmoth (report 06 §8.2).
- **Tecniche di debug**: log strutturati via `kprintf` nel nostro kext.
- I simboli dei kext AMD Apple (da KDK) restano un **riferimento utile per il contratto IOAccelerator lato AMD** (come un driver AMD
  "vero" espone user client, proprieta' `MetalPluginName`, `IOGVACodec`, `IOVARendererID`, AGDC): da consultare, non da riusare.

## 8. Domande aperte

Richiedono macOS installato, privilegi o hardware aggiuntivo (nessuna e' stata eseguita: regole della fase).

1. **ACPI della B840** (privilegiato: `/sys/firmware/acpi/tables/DSDT` richiede root): i processori sono `Processor` o
   `Device (ACPI0007)`? Determina se serve `SSDT-CPUR`. Serve anche per l'`SSDT-EC-USBX` (nome del device EC/LPC).
2. **Comportamento di IOPCIFamily con BAR0 = 16 GB** dietro lo switch interno della GPU, con `ResizeAppleGpuBars=-1`
   (va provato su macOS: `ioreg -l -p IODeviceTree`, log `IOPCIFamily` con `debug`); e se il GOP sopravvive all'installer con BAR grande.
3. **Boot display su iGPU Raphael senza driver** (strategia 5.4.2): il BIOS MSI permette IGD primario con dGPU installata?
   macOS usa il framebuffer GOP della Raphael come console?
4. **Compatibilita' NVMe**: Lexar NM790 (Maxio MAP1602, 1d97:1602) e Samsung 980 (144d:a809) con Sequoia/Tahoe; quale disco dedicare a macOS.
5. **Header JCOM1**: conferma dal manuale MSI (pinout, livelli RS-232) e disponibilita' di un bracket DB9 + adattatore USB-RS232.
6. **KDP**: il plugin `ProcessKDP` e' disponibile in LLDB per Linux (pacchetto `lldb` di CachyOS)? Altrimenti serve un host macOS
   per `kdp-remote`. Il boot-arg esatto per KDP su seriale (`kdp_match_name=serial`) va verificato sul sorgente XNU di Tahoe.
7. **NIC per KDP**: `LucyRTL8125Ethernet` implementa l'interfaccia polled di `IOKernelDebugger`? Se no, acquistare Intel I210.
8. **Tahoe vs Sequoia per l'ABI IOAcceleratorFamily2**: quante differenze reali (nullmoth compila NVAccel separati per 15 e 26)?
   Da misurare con i KDK delle due release.
9. **VM con passthrough** (sez. 6.5): la 9060 XT torna in uno stato pulito dopo `reset_method=bus`, o serve un mode1 reset via PSP
   prima di ogni avvio del guest? Test da fare in una fase in cui e' permesso toccare la GPU.
10. **Wi-Fi/BT**: accettabile restare su Ethernet, o sostituire il modulo Qualcomm WCN785x con un Broadcom supportato?
11. **Contenuto esatto di `AMDShared.bundle`/`AMDRadeonX6000Shared.bundle`** e collocazione del compilatore shader AMD (solo
    interesse documentale, estraibile dal KDK/sistema una volta installato macOS).

## 9. Fonti

Locali (lette, mai eseguite):
- `research/refs/WhateverGreen/WhateverGreen/kern_rad.cpp`, `kern_weg.cpp`, `README.md`.
- Linux `drivers/gpu/drm/amd/amdgpu/{amdgpu_discovery.c,amdgpu_vm.h}`, `pm/swsmu/smu11/sienna_cichlid_ppt.c`;
  Mesa `src/amd/addrlib/{inc/addrtypes.h,src/amdgpu_asic_addr.h}`.
- Report del progetto: 01 (bring-up Linux), 02 (DCN 4.0.1), 03 (Mesa gfx12), 05 (Cobalt64), 06 (nullmoth).

Web (salvate in scratchpad `apple-amd-lilu/web/` dalla sessione precedente o consultate ora):
- NootRX issue #144 "Navi 3x support": https://github.com/ChefKissInc/NootRX/issues/144 (`issue144.json`, `issue144_comments.json`).
- Dortania GPU Buyers Guide, sezione AMD (`gpu_buyers_amd.md`); Dortania OpenCore Install Guide, Ryzen 17h/19h (`oc_zen.md`).
- AMD_Vanilla README: https://github.com/AMD-OSX/AMD_Vanilla (`amd_vanilla_readme.md`).
- OpenCorePkg `Docs/Configuration.tex` (`oc_config.tex`).
- OpenCore Legacy Patcher patchset grafiche (`oclp/*.py`, `oclp_tree.json`): https://github.com/dortania/OpenCore-Legacy-Patcher.
- Apple, pagina macOS 27 "Golden Gate" (compatibilita') (`c1413815.html`); 9to5Mac, "macOS 27 will drop support for these four
  Mac models", 2026-05-18 (`9165eb06.html`).
- XNU `osfmk/kern/debug.h`: https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/osfmk/kern/debug.h
- Quarkslab, "An overview of macOS kernel debugging": https://blog.quarkslab.com/an-overview-of-macos-kernel-debugging.html
- Specifiche retailer MSI B840 Gaming Plus WiFi (RTL8125BG, ALC897, "1x Com Port (JCOM)"): https://www.memoryexpress.com/Products/MX00132295 ,
  https://store.area9.com.au/products/msi-b840-gaming-plus-wifi-2197846
