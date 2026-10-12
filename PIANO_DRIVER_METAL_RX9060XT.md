# Piano di sviluppo: driver Metal per AMD Radeon RX 9060 XT (Navi 44, RDNA 4) su macOS

> Versione 1.0, 12 ottobre 2026. Documento di partenza per lo sviluppo: raccoglie l'analisi del driver Linux
> (`amdgpu`, Mesa RADV/ACO, ROCm), dei progetti esistenti per GPU non supportate su macOS (NullMoth per NVIDIA,
> Cobalt64 per RDNA 4, RDNA4FB, mac-amdgpu, NootRX/NootedRed) e definisce architettura, strategia, ambiente di
> sviluppo, milestone e test.
>
> Tutti i dati hardware citati sono stati **misurati su questa macchina** (Linux 7.2.9-cachyos) in sola lettura.
> I report tecnici completi, con riferimenti file:riga al codice, sono in `research/reports/` (vedi §21).

---

## Indice

0. [In breve](#0-in-breve)
1. [Obiettivo e definizione di "primo abbozzo"](#1-obiettivo-e-definizione-di-primo-abbozzo)
2. [Fattibilità: verdetto onesto](#2-fattibilità-verdetto-onesto)
3. [La scheda: dati misurati](#3-la-scheda-dati-misurati)
4. [Stato dell'arte (ottobre 2026)](#4-stato-dellarte-ottobre-2026)
5. [Architettura target](#5-architettura-target)
6. [Cosa fa Linux per accendere la GPU (amdgpu)](#6-cosa-fa-linux-per-accendere-la-gpu-amdgpu)
7. [Display: DCN 4.0.1](#7-display-dcn-401)
8. [Vulkan sotto Metal: RADV/ACO e backend Darwin](#8-vulkan-sotto-metal-radvaco-e-backend-darwin)
9. [Il livello Metal](#9-il-livello-metal)
10. [Compute, ROCm e toolchain ISA gfx1200](#10-compute-rocm-e-toolchain-isa-gfx1200)
11. [Strategia: opzioni valutate e decisione](#11-strategia-opzioni-valutate-e-decisione)
12. [Versione di macOS e configurazione OpenCore](#12-versione-di-macos-e-configurazione-opencore)
13. [Ambiente di sviluppo e di test](#13-ambiente-di-sviluppo-e-di-test)
14. [Roadmap a milestone](#14-roadmap-a-milestone)
15. [Strategia di test e verifica](#15-strategia-di-test-e-verifica)
16. [Rischi e mitigazioni](#16-rischi-e-mitigazioni)
17. [Licenze e aspetti legali](#17-licenze-e-aspetti-legali)
18. [Struttura del repository proposta](#18-struttura-del-repository-proposta)
19. [Prime azioni concrete](#19-prime-azioni-concrete)
20. [Decisioni che spettano a te](#20-decisioni-che-spettano-a-te)
21. [Materiale prodotto da questa analisi](#21-materiale-prodotto-da-questa-analisi)
- [Appendice A: firmware Navi 44](#appendice-a-firmware-navi-44)
- [Appendice B: registri chiave del bring-up](#appendice-b-registri-chiave-del-bring-up)
- [Appendice C: ABI kernel-userspace proposta](#appendice-c-abi-kernel-userspace-proposta)
- [Appendice D: fonti](#appendice-d-fonti)

---

## 0. In breve

- **Si può fare: secondo quanto dichiarato dagli autori (README, non riprodotto da noi) è già stato fatto due volte.**
  NullMoth ha portato le GeForce (fino alle RTX 50, testato su RTX 5060) su macOS 15 Sequoia con Metal; Cobalt64 ha fatto girare il desktop di macOS Tahoe 26.6.2, composto da
  WindowServer via Metal, su una RX 9070 XT (Navi 48, RDNA 4, la "sorella maggiore" della tua scheda). Nessuno ha
  ancora fatto funzionare una **Navi 44 / RX 9060 XT**.
- **Navi 44 è quasi identica a Navi 48 per il driver**: stesse generazioni di tutti i blocchi IP (GC 12.0.x,
  PSP/SMU 14.0.x, SDMA 7.0.x, MMHUB 4.1.0, IH 7.0, NBIF 6.3.1, DCN 4.0.1), stesse basi dei registri display, stesso
  `GB_ADDR_CONFIG` (0x08200545), stessa VRAM (16 GB). Cambiano **dati, non logica**: device id `0x7590`, firmware
  (`gc_12_0_0_*`, `psp_14_0_2_*`, `smu_14_0_2`, `sdma_7_0_0`: si usa solo l'insieme Navi 44, Appendice A), 2 shader engine
  invece di 4 (32 CU), bus a 128 bit, cablaggio dei connettori (DP su PHY A, HDMI su PHY B/C).
- **L'architettura vincente è nota** (la stessa di NullMoth e Cobalt64): un kext che accende la GPU, un
  `IOFramebuffer` per i display, un `IOGraphicsAccelerator2` per WindowServer/IOSurface, uno shim AGDC per la
  display policy, un bundle Metal in `/Library/GPUBundles` che implementa `MTLDevice` sopra Vulkan, il driver Vulkan
  **RADV** di Mesa portato su macOS (backend "Darwin" sotto `ac_drm_*`), e un traduttore di shader
  **Apple AIR → SPIR-V** (metal2vulkan). ACO compila poi SPIR-V in ISA gfx1200.
- **Strategia raccomandata**: architettura modulare stile NullMoth, con il **core kernel e le patch Mesa derivati dalla
  "rotta nativa" di Cobalt64** (licenze MIT/BSD-3), parametrizzati per Navi 44 tramite un profilo ASIC e la tabella
  IP discovery; Linux `amdgpu` (MIT) come specifica di riferimento; come motore del bundle Metal il nuovo
  **metal2vulkan 0.2** (traduttore per pipeline + runtime Metal-su-Vulkan; versione alpha non ancora rilasciata, la cui
  documentazione cita shader reali di Tahoe 26.6.2). Scartare la "rotta Apple" di Cobalt64 (riuso di `AMDRadeonX6000`): non scala ed è legata byte per byte a una
  build di macOS.
- **macOS target: Tahoe 26.x** (ultima release per Intel, ABI che dovrebbe congelarsi), congelata su una build precisa, SMBIOS
  **MacPro7,1**, OpenCore con patch AMD Vanilla per il Ryzen 7 7700.
- **Ambiente**: sviluppo e bring-up in una **VM macOS con la RX 9060 XT in passthrough VFIO** su questo stesso PC
  (gruppi IOMMU già isolati, KVM attivo, iGPU per il desktop Linux): log seriale del kernel, debugger, tracce MMIO e
  una "traccia d'oro" dell'init di Linux da confrontare passo passo. Poi bare metal con OpenCore; la scheda madre ha una
  **vera porta seriale COM1** (header JCOM1) per i log del kernel anche su bare metal.
- **Già verificato su questa macchina**: ROCm/HIP girano sulla scheda (~300 GB/s, 94% del picco); **kernel Metal reali
  (AIR compilato da Apple) sono stati eseguiti correttamente sulla RX 9060 XT** passando per LLVM AMDGPU; RADV espone
  Vulkan 1.4 con tutte le 14 estensioni che il plugin Metal di NullMoth richiede (§9.2 per i dettagli su metal2vulkan).
- **Primo abbozzo** (milestone M1-M3): il kext inizializza la Navi 44 su macOS fino a eseguire un compute shader, e
  RADV su macOS vede la GPU (`vulkaninfo` + un compute Vulkan). In parallelo, la traduzione Metal→Vulkan si valida già
  su Linux. Desktop accelerato: M6.
- **Sforzo stimato**: secondo la roadmap di §14, M0-M6 richiedono **circa 24-45 settimane-uomo (≈ 6-11 mesi-uomo)**
  per un desktop accelerato su un monitor con l'opzione raccomandata. Per confronto, il report 05 stima 2-3 mesi-uomo per
  un port quasi diretto di Cobalt64 *se* gli autori forniscono il generatore del layout di IOAcceleratorFamily2
  (`tools/native/ioaccel-layout`), 4-6 mesi-uomo se quel layout va ricostruito, 9-18 mesi-uomo partendo da zero. Per un
  progetto personale part-time i tempi di calendario sono più lunghi.

---

## 1. Obiettivo e definizione di "primo abbozzo"

**Obiettivo finale.** macOS (x86_64, Hackintosh con OpenCore) usa la RX 9060 XT come GPU Metal di sistema:
WindowServer compone il desktop sulla GPU, le app Metal/Core Animation/Core Image girano accelerate, i monitor
collegati alla scheda funzionano con i loro modi nativi.

**Cosa NON è nell'obiettivo iniziale**: decodifica/codifica video hardware (VCN 5.0), ray tracing Metal, HDCP,
sleep/wake perfetto, multi-GPU, prestazioni allo stato dell'arte. Vengono dopo.

**Primo abbozzo (deliverable delle prime milestone)**, in ordine:

| # | Deliverable | Prova che funziona |
|---|---|---|
| A1 | Kext `RX9060Core` che fa match su `1002:7590`, mappa i BAR, legge la IP discovery, e **non fa danni** (sola lettura) | log seriale con la tabella IP identica a quella di Linux (`research/hw_dump/`) |
| A2 | Bring-up hardware: PSP (boot sOS + caricamento firmware), SMU, GMC/GART, IH, RLC/IMU/CP, MES, SDMA | ring test: `WRITE_DATA` + fence `RELEASE_MEM` + interrupt EOP; SDMA copy; MQD e pacchetti MES confrontati con i dump Linux |
| A3 | Primo compute shader gfx1200 eseguito dal kext | un kernel scrive un valore magico in memoria |
| A4 | User client con ABI tipo `DRM_AMDGPU_*` + RADV con backend Darwin | `vulkaninfo` su macOS mostra "AMD Radeon RX 9060 XT (RADV GFX1200)"; un compute Vulkan restituisce risultati corretti |

Il resto (display nativo, acceleratore, bundle Metal, WindowServer) è descritto in §14.

---

## 2. Fattibilità: verdetto onesto

**Fattibile**, con queste precisazioni:

1. **La parte più difficile è il kernel, non Metal.** NullMoth ha potuto *portare* il resource manager open di NVIDIA,
   che delega quasi tutto l'init al firmware GSP. Per AMD non esiste un firmware "che fa tutto": il driver deve
   caricare e pilotare PSP, SMU, IMU/RLC, MES, SDMA e programmare GMC/IH/display. Questo lavoro però **è già stato
   fatto per Navi 48** da Cobalt64 (che a sua volta deriva da mac-amdgpu) ed è documentato riga per riga in Linux.
2. **Il layer Metal-su-Vulkan è vendor-neutrale.** Il contratto macOS (IOAccelerator + plugin `MTLIOAccelDevice` +
   IOSurface + display pipe) è lo stesso per NVIDIA e AMD; RADV su gfx1200 espone **tutte** le estensioni Vulkan che il
   plugin NullMoth richiede (verificato con `vulkaninfo` su questa macchina).
3. **Il display è il componente più grande** (il Display Core di Linux, `display/dc`, è ~458 mila righe di C). Si parte "adottando" lo
   schermo acceso dal GOP UEFI e cambiando solo la superficie (flip), poi si aggiunge il mode-setting nativo.
4. **Fragilità macOS**: IOAcceleratorFamily2, `MTLIOAccelDevice` e AGDC sono API private senza header; layout delle
   vtable e offset vanno ricostruiti per la versione di macOS scelta, che va **congelata**.
5. **Sicurezza ridotta**: servono SIP rilassato, AMFI disattivato (+AMFIPass), Secure Boot di OpenCore disattivato.
   Inevitabile finché il bundle non è firmato da Apple (cioè sempre).
6. **Reset**: Navi 44 non ha un reset "leggero" del solo GFX (mode2 non esiste in Linux); il recupero completo
   richiede mode1 via SMU + `asic_init` AtomBIOS + di nuovo tutto il boot del PSP. All'inizio un blocco = riavvio
   (o riavvio della VM).

---

## 3. La scheda: dati misurati

Raccolti l'11-12/10/2026 su questa macchina (dump completi in `research/hw_dump/`, decodifiche in
`research/hw_dump/README.md`).

### 3.1 Identità e bus

| Voce | Valore |
|---|---|
| Modello | Sapphire Radeon RX 9060 XT 16 GB (subsystem `1DA2:A493`) |
| PCI | `03:00.0` `1002:7590` rev `c0` (VGA), `03:00.1` `1002:ab40` (audio HDMI/DP) |
| Topologia PCIe | dietro lo switch interno della GPU: `00:01.1 → 01:00.0 (upstream) → 02:00.0 (downstream) → 03:00.0` |
| Link | verso la CPU **PCIe 4.0 x16**: la root port della B840 (`00:01.1`) arriva a 16 GT/s (la scheda supporta 5.0) e in idle il link scende a 2,5 GT/s per il DPM; il collegamento interno switch→GPU è a 32 GT/s. AtomicOps 32/64 bit: richiesti dall'endpoint, instradati dagli switch interni e accettati come completer dalla root port; **niente FLR**; reset PCI disponibile: bus (`research/hw_dump/lspci_vvv_*.txt`) |
| BAR | BAR0 = **16 GB** (VRAM, Resizable BAR attivo; supporta 256 MB…16 GB), BAR2 = 256 MB (doorbell), BAR4 = I/O 256 B, BAR5 = **MMIO 512 KB**, ROM 128 KB |
| IOMMU | GPU sola nel gruppo 15, audio solo nel gruppo 16 (ideale per VFIO) |
| VBIOS | `113-P816G493-S05`, build 00145996, 2025/04/01 (58 880 byte, ATOM) |
| Memoria | 16 GB GDDR6 Samsung, bus 128 bit, 4 × UMC 8.14.0; VRAM riportata 16 304 MiB (= 16 GiB − 80 MiB, presumibilmente riservati dall'IFWI [INFERITO]); altre regioni riservate al PSP (cmd 0x50/0x51, TMR) stanno sotto questo limite e vanno lette a runtime |
| Range MC VRAM | `0x80_0000_0000 – 0x83_FAFF_FFFF`; GART 512 MiB a `0x0` |
| Infinity Cache (MALL) | 32 MiB (8 MiB × 4 UMC) |

### 3.2 Blocchi IP (tabella IP discovery, versione 1.3 / IP header v3, checksum verificate)

| IP | Versione | Driver Linux | Note |
|---|---|---|---|
| GC (grafica/compute) | **12.0.0** → ISA **gfx1200** | `gfx_v12_0.c`, `imu_v12_0.c` | Navi 48 = 12.0.1 / gfx1201 |
| SDMA0/1 | 7.0.0 | `sdma_v7_0.c` | Navi 48 = 7.0.1, stesso driver |
| MP0 (PSP) | 14.0.2 | `psp_v14_0.c` | Navi 48 = 14.0.3 |
| MP1 (SMU) | 14.0.2 | `smu_v14_0.c` + `smu_v14_0_2_ppt.c` | Navi 48 = 14.0.3 |
| DMU (display) | 4.1.0 in tabella → **DCN 4.0.1** nel driver | `display/dc/*/dcn401` | rimappatura in `amdgpu_discovery.c:2688-2690`; uguale su Navi 48 |
| MMHUB / ATHUB | 4.1.0 / 4.1.0 | `mmhub_v4_1_0.c` | |
| OSSSYS (IH) | 7.0.0 | `ih_v7_0.c` | |
| HDP | 7.0.0 | `hdp_v7_0.c` | |
| NBIF | 6.3.1 | `nbif_v6_3_1.c` | |
| VCN / JPEG | 5.0.0 / 5.0.0 | `vcn_v5_0_0.c` | non necessari per il bring-up |
| LSDMA | 7.0.0 | `lsdma_v7_0.c` | |
| SMUIO/THM/FUSE/CLKA | 14.0.2 | | |
| DF | 4.15.0 | `df_v4_15.c` | |
| UMC | 8.14.0 × 4 | | Navi 48 ha 8 UMC |
| Harvest table | vuota | | die completo, nessun IP disabilitato |

Basi dei registri (in dword) usate più spesso: GC `0x1260 / 0xa000 / 0x1c000 / 0x2402c00`, MMHUB `0x1a000`,
OSSSYS `0x10a0`, HDP `0xf20`, NBIF `0x0 / 0x14 / 0xd20 / 0x10400`, MP0=MP1 `0x16000 / 0x16200 / 0x1ce00 / …`,
DMU `0x12 / 0xc0 / 0x34c0 / 0x9000 / 0x2403c00` (**identiche a Navi 48**). Tutti i registri del bring-up stanno
nei primi 512 KB (BAR5) tranne pochi registri SMN (vedi Appendice B).

### 3.3 Configurazione grafica (`gc_info` v1.3 + `gca_config` + RADV)

| Voce | Navi 44 (questa scheda) | Navi 48 |
|---|---|---|
| Shader engine × SA × CU | **2 × 2 × 8 = 32 CU** (16 WGP) | 4 × 2 × 8 = 64 CU |
| Render backend | 8 (`enabled_rb_pipes_mask 0xff`) | 16 |
| `GB_ADDR_CONFIG` | **0x08200545** | 0x08200545 |
| L2 / MALL | 4 MiB / 32 MiB | 8 MiB / 64 MiB |
| Wave | wave32 nativo, 1536 VGPR, 16 wave/SIMD; LDS 64 KiB massimo per workgroup (128 KiB fisici per WGP) | idem |
| Clock max | GFX 2700 MHz, memoria 1258 MHz | |
| `family` / `external_rev_id` | 0x98 (`AMDGPU_FAMILY_GC_12_0_0`) / **0x41** (`rev_id 1 + 0x40`) | 0x98 / 0x5x |
| Topologia code CP | ME 1×1×8, MEC 1×2×4 (4 compute ring kernel), 1 gfx ring | idem |

`external_rev_id` è ciò che fa riconoscere a Mesa la scheda come `CHIP_GFX1200` (0x40-0x4f) anziché `CHIP_GFX1201`.

### 3.4 Firmware effettivamente caricati da Linux

ME 0xc12 (3090), PFP 0xc76 (3190), MEC 0xd7a (3450), RLC 0x00bde160, IMU 0x0c2c2500, SOS 0x003b0f0d, ASD
0x21000118, TA HDCP 0x17000053, TA DTM 0x1200001f, SMC 102.71.0 (0x00664700, driver_if 0x2e / fw_if 0x33), SDMA
0x00798e96, MES e MES_KIQ 0x93 (**uni-MES**), DMCUB 0x0a004b00, VCN 0x0910c01a. I file in
`/usr/lib/firmware/amdgpu/` (linux-firmware 20260916) sono **esattamente** questi (verificato confrontando gli header).
Dettaglio in Appendice A.

### 3.5 Display

- Connettori (dal VBIOS, tabella `displayobjectinfo` v1.5): **DP-1 → UNIPHY_A** (PHY A, DDC1, HPD1),
  **HDMI-A-1 → UNIPHY_B** (DDC2, HPD2), **HDMI-A-2 → UNIPHY_C** (DDC3, HPD3). 3 PHY, 4 pipe (HUBP/DPP/MPCC/OTG),
  4 DSC, 4 encoder HPO DP (stream + link, DP 2.1 128b/132b) e 1 encoder HPO FRL (HDMI 2.1).
- DMUB firmware `dcn_4_0_1_dmcub.bin` 0x0A004B00.
- Al momento del dump tutti i connettori risultavano "disconnected" (monitor spento): il log DTN mostra pipe idle.

### 3.6 Piattaforma host

Ryzen 7 7700 (Zen 4, 8 core) con iGPU Raphael (`1002:164e`, anch'essa su `amdgpu`, card0), MSI **B840 GAMING PLUS
WIFI** (AM5, BIOS 2.A53), 32 GB RAM, UEFI. Rete: Realtek **RTL8125** 2.5 GbE (funziona su macOS con kext di terze
parti), Wi-Fi Qualcomm **WCN785x** Wi-Fi 7 (nessun driver macOS). Dischi: Linux su NVMe da 238 GB (35 GB liberi),
Windows su NVMe da 1 TB. **Nessun macOS installato.**

---

## 4. Stato dell'arte (ottobre 2026)

| Progetto | Cosa fa | Stato | Cosa ci insegna / cosa riusiamo | Licenza |
|---|---|---|---|---|
| **Driver Apple AMD** (`AMDRadeonX6000*.kext` + `AMDRadeonX6000MTLDriver.bundle`; `AMDMTLBronzeDriver` è il driver Metal GCN/Polaris) | GPU AMD fino a RDNA 2 (Navi 2x) | ufficiale, fino a macOS 26 (ultimo per Intel) | riferimento canonico di come un vendor implementa IOAcceleratorFamily2; il loro compilatore produce ISA gfx10.3, **inutilizzabile su gfx12** | proprietaria Apple |
| **NullMoth** `nvidia-macos-driver` | GeForce GTX 16 … RTX 50 su macOS 15 con Metal 3 (testato su 15.7.x/15.8.1; l'installer accetta anche 26 con un acceleratore dedicato, ma Tahoe non è qualificato) | funzionante (release 1.13.0, 10/10/2026), testato su RTX 5060 | **l'architettura completa**: 4 kext (core, accel, framebuffer, AGDC) in Auxiliary KC, plugin Metal su Vulkan (NVK), traduttore AIR→SPIR-V, installer e recovery | core e plugin PolyForm **Noncommercial**; traduttore LGPL-3.0+; patch NVK: i file Mesa originali sono MIT, ma le parti scritte da NullMoth (es. `nvrm_xnu.c`) non hanno una licenza esplicita e vanno considerate PolyForm NC salvo conferma degli autori |
| **Cobalt64** | RDNA 4 Navi 48 (RX 9070 XT) su macOS Tahoe 26.6.2: kext di bring-up, RADV Darwin, bundle Metal su Vulkan, display DCN | preview (snapshot 9/10/2026): desktop composto su 3 monitor, alcune app Apple | **la base più vicina**: scala di bring-up PSP→SMU→GMC→IH→RLC→CP→MES→SDMA per RDNA 4, ABI "N48N" gemella di `DRM_AMDGPU_*`, 9 patch Mesa, kext acceleratore + bundle Metal. Manca il generatore del layout di IOAcceleratorFamily2 (`tools/native/ioaccel-layout`) | MIT (radice) + BSD-3 (kext) + LGPL (wrapper traduttore) |
| **7000-macos** | fork di Cobalt64 per RX 7000 | solo rilevamento RDNA 3 | l'idea del **profilo ASIC** (`asic_profile`) per supportare più GPU | come Cobalt64 |
| **RDNA4FB / AMDRadeonRDNA4.kext** | framebuffer solo-display per Navi 48 (`IOFramebuffer` che adotta il GOP, EDID via AUX/DDC, sleep display) | funziona su Big Sur 11.7 | parser IP discovery e AtomBIOS freestanding, accesso DCN guidato da discovery, perché il kext display va in Aux KC e non va iniettato da OpenCore | BSD-3 |
| **mac-amdgpu** (lemonade-sdk) | driver **PCIDriverKit** + runtime HSA per R9700 (gfx1201) su Apple Silicon via Thunderbolt 5 | inferenza LLM funzionante | il bring-up RDNA 4 da cui deriva Cobalt64; prova che si può fare compute da DriverKit | MIT |
| **metal2vulkan** (steelbrain) | traduttore Apple AIR (bitcode LLVM) → SPIR-V Vulkan 1.2 | 0.1 usata da NullMoth e Cobalt64; 0.2 (alpha) aggiunge un runtime Metal-su-Vulkan | il traduttore/runtime da usare | 0.1: LGPL-3.0+; 0.2: GPL-2.0+ OR LGPL-3.0+ (usata come LGPL) |
| **NootRX / NootedRed / WhateverGreen** | patch Lilu dei kext Apple AMD per Navi 22/RDNA 2 e APU Vega | maturi | come si "convincono" i kext Apple: utile solo per RDNA 2; per RDNA 3/4 la strada è chiusa (ISA, MES, PTE, DCN, PSP diversi) | NootRX, NootedRed: ChefKiss Open Knowledge License v1 (nessuna opera derivata, nessun uso con IA: **non** vanno usati né analizzati); WhateverGreen: BSD-3 |

---

## 5. Architettura target

### 5.1 Schema a blocchi

```
 ┌──────────────────────── ogni processo Metal (app, WindowServer, Safari GPU process, …) ────────────────────────┐
 │ Metal.framework  ── legge MetalPluginName/MetalPluginClassName dall'IOAccelerator ──▶ carica il nostro bundle │
 │   MTLLibrary/MTLFunction restano di Apple (MSL→AIR via MTLCompilerService, reflection, function constants)    │
 │                                                                                                              │
 │ RX9060Metal.bundle  (/Library/GPUBundles)                                                                    │
 │   shim ObjC: RX9060Device : MTLIOAccelDevice (-initWithAcceleratorPort:), allow-list, census/forwarding SPI, │
 │              limiti/feature gfx1200, IOSurface ↔ texture, presentazione, gating                              │
 │   libm2v.dylib (LGPL): metal2vulkan 0.2 = traduttore AIR→SPIR-V per pipeline + runtime Metal-su-Vulkan        │
 │                        (hazard tracking, eventi = timeline semaphore, argument buffer, ICB, formati XR10)    │
 │   libvulkan_radeon.dylib: RADV + ACO (Mesa) con backend "Darwin" sotto ac_drm_*  → PM4 gfx12, ISA gfx1200    │
 └──────────────────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                                │ IOConnectCallMethod / IOConnectMapMemory64
                                                │ (aperto attraverso l'IOAccelerator o con classe `IOAccel*`:
                                                │  il sandbox di WindowServer ammette solo quelle)
 ═══════════════════════════════════════════════╪══════════════ kernel: Auxiliary KC (/Library/Extensions) ═════
 ┌────────────────────────────┐  callPlatformFunction  ┌──────────────────────────────────────────────────────┐
 │ RX9060Accel.kext           │  + struct versionate   │ RX9060Core.kext                                      │
 │  IOGraphicsAccelerator2    │◀──────────────────────▶│  IOPCIDevice 1002:7590: BAR0 VRAM, BAR2 doorbell,    │
 │  (17 metodi puri), event   │  (VRAM, VA GPU, share  │  BAR5 MMIO, MSI; IP discovery + profilo ASIC;        │
 │  machine, task/VA, risorse │   IOSurface, flip, VBL)│  PSP 14.0.2 → SMU 14.0.2 → GMC 12/GART → IH 7 →     │
 │  IOSurface, display pipe,  │                        │  IMU/RLC/CP RS64 → MES 12 → SDMA 7; VM per processo;│
 │  user client "carrier"     │                        │  ring/code, fence, IRQ, reset; firmware da disco;   │
 └─────────────┬──────────────┘                        │  user client "DRM-like" per RADV (Appendice C)      │
               │ found_framebuffer / transazioni         └────────────────────────────┬─────────────────────────┘
 ┌─────────────▼──────────────┐  ┌─────────────────────────┐                          │ MMIO / doorbell / DMA
 │ RX9060FB.kext              │  │ RX9060AGDC.kext         │                          ▼
 │  IOFramebuffer ×3 + claim  │  │  AppleGraphicsDevice-   │      Radeon RX 9060 XT (Navi 44, GC 12.0.0,
 │  DCN 4.0.1: HUBP/OTG/DIG,  │  │  Control (vendor 0x1002,│      32 CU, 16 GB GDDR6, DCN 4.0.1)
 │  EDID AUX/DDC, VBL, cursore│  │  mappa framebuffer)     │
 └────────────────────────────┘  └─────────────────────────┘
```

### 5.2 Responsabilità e interfacce

| Componente | Responsabilità | Interfacce |
|---|---|---|
| `RX9060Core.kext` | possiede la GPU: init hardware, memoria (allocatore VRAM, GTT, GART, VM a 4 livelli per processo), code (ring kernel via MES, poi user queue), fence e interrupt, firmware, reset; espone l'ABI "DRM-like" | user client (Appendice C); ABI kext↔kext versionate; boot-arg e sysctl di gating |
| `RX9060FB.kext` | un `IOFramebuffer` per connettore: adozione della pipe GOP, modi, EDID, vblank, cursore, power del display; "claim" che ritira `IONDRVFramebuffer` | IOGraphicsFamily; chiede VRAM e flip al Core |
| `RX9060Accel.kext` | ciò che Metal.framework e WindowServer cercano: `IOGraphicsAccelerator2` + classi della famiglia (event machine, task, memorie, risorse, display machine/pipe); backing in VRAM delle IOSurface; instradamento degli user client dei processi sandboxed verso il Core | IOAcceleratorFamily2 (layout privati ricostruiti per la build scelta) |
| `RX9060AGDC.kext` | risponde alla display policy di macOS (vendor info, mappa framebuffer) | AppleGraphicsDeviceControl |
| `RX9060Metal.bundle` | `MTLDevice` privato sopra Vulkan; gating per processo; IOSurface; presentazione | Metal.framework (SPI `MTLIOAccelDevice`), Vulkan (RADV), C ABI di `libm2v` |
| `libm2v.dylib` | traduzione AIR→SPIR-V per pipeline e semantica Metal su Vulkan | C ABI; LGPL, sostituibile |
| RADV Darwin | Vulkan 1.4 su gfx1200; backend Darwin sotto `ac_drm_*`; export privati (scanout, import IOSurface, budget) | user client del Core |

### 5.3 Scelte di progetto principali

1. **Submission**: fase 1 come Linux con kernel queue: un ring GFX (e poi compute) mappato da MES con
   `ADD_QUEUE(map_legacy_kq=1)`, IB utente lanciati con `INDIRECT_BUFFER` e il VMID del processo, fence `RELEASE_MEM` +
   interrupt EOP. Fase 2: coda compute + gang submit (task/mesh shader). Fase 3: **user queue MES** (modello
   `amdgpu_userq` di Linux per gfx12: coda PM4 in memoria utente, doorbell in BAR2 mappata nel processo, fence in
   memoria), **opzionale**: i firmware installati sono esattamente sulla soglia richiesta, ma RADV oggi non usa le user
   queue (solo radeonsi con `AMD_USERQ=1`) e sul kernel misurato `userq_ip_mask = 0`: servono modifiche a RADV e una
   validazione preliminare su Linux con `amdgpu.user_queue=1`.
2. **Memoria**: VRAM gestita dal Core (allocatore proprio, regioni riservate in cima alla VRAM rispettate: discovery,
   TMR PSP, regioni FW), GTT con `IOBufferMemoryDescriptor` + GART/page table. macOS non usa l'IOMMU AMD-Vi: gli
   indirizzi DMA sono fisici (in VM sono gli indirizzi fisici del guest, tradotti dall'IOMMU dell'host).
3. **Firmware da disco** (es. `/Library/Application Support/RX9060/firmware/`, verificati con sha256) caricati dal Core
   su un thread dopo l'avvio, con boot hold (`adjustBusy`) come NullMoth: niente blob AMD dentro il binario del kext.
4. **Display**: si parte adottando la pipe accesa dal GOP (nessun reset del DCN), poi flip e vblank veri, poi
   mode-setting nativo riusando il DMCUB pre-OS e, più avanti, caricando `dcn_4_0_1_dmcub.bin` via PSP (§7).
5. **Gating e sicurezza operativa**: boot-arg di abilitazione per ogni kext (`rx9060=1`, `-rx9060off`), sysctl per
   abilitare ogni stadio, `MetalPluginName` pubblicato solo a display armato, allow-list per processo, voce EFI di
   recovery, "layout gate" che confronta a runtime gli slot vtable attesi con quelli di IOAcceleratorFamily2 caricata
   (fail-closed).
6. **Niente costanti per ASIC**: tutto da IP discovery, VBIOS e profilo ASIC (§11.2).

---

## 6. Cosa fa Linux per accendere la GPU (amdgpu)

Sintesi del report `research/reports/01-linux-amdgpu-bringup.md` (1 100 righe, con indirizzi calcolati su questa
scheda). Percorsi relativi a `research/src/linux/drivers/gpu/drm/amd/`.

### 6.1 Tutto parte dalla IP discovery

Per GC 12.0.0 Linux non ha quasi costanti hardware: versioni, basi dei registri per ogni blocco, topologia
(SE/SA/CU/RB), cache e MALL vengono dalla tabella binaria in cima alla VRAM (10 KiB a `VRAM − 64 KiB`, cioè offset
`0x3_FAFF_0000` su questa scheda), con firma `0x28211407` e checksum (`amdgpu_discovery.c:288-773`,
`include/discovery.h`). Un registro si indirizza come `base[ip][istanza][BASE_IDX] + offset` (header generati
`include/asic_reg/<ip>/<ip>_<ver>_offset.h`). **Il nostro kext farà lo stesso**: niente offset cablati per ASIC.

### 6.2 Ordine di inizializzazione (osservato in dmesg e nel codice)

```
soc24_common (NBIF: doorbell, remap HDP)  ->  gmc_v12_0 (GART MMHUB, VMID0)  ->  ih_v7_0 (ring interrupt)
  ->  psp_v14_0 (boot del sOS + caricamento di TUTTI i firmware via LOAD_IP_FW + AUTOLOAD_RLC)
  ->  smu_v14_0 (mailbox, tabelle, feature)  ->  dm (display)
  ->  gfx_v12_0 (attesa autoload RLC, golden, CP RS64, GART GFXHUB; poi MES: amdgpu_mes_kiq_hw_init attiva le
                pipe MES, inizializza la pipe KIQ e SUBITO DOPO la pipe scheduler (mes_v12_0_hw_init, SET_HW_RSRC);
                solo allora mappa le code kernel compute/gfx via MES ADD_QUEUE)
  ->  sdma_v7_0  ->  (vcn/jpeg)  ->  mes_v12_0 (hw_init già eseguito dentro gfx: salta)
```

### 6.3 I punti chiave per un driver scritto da zero

| Blocco | Cosa serve | Riferimento |
|---|---|---|
| **Stato iniziale** | se `MPASP_SMN_C2PMSG_81` ≠ 0 il sOS del PSP è già vivo (ad es. dopo un warm reboot da Linux/Windows o dopo che la scheda è stata usata dall'host prima del passthrough [INFERITO, da misurare]): mode1 reset prima di tutto, seguito da `asic_init` AtomBIOS. Con boot UEFI+GOP la scheda dovrebbe essere già "postata" (`BIOS_SCRATCH_7` bit `ASIC_INIT_COMPLETE`, da verificare) | `soc24.c:242-257`, `amdgpu_device.c:1190` (`need_post`), `amdgpu_atombios.c:1634-1642`, `amdgpu_device.c:958-985` (`asic_init`) |
| **NBIF 6.3.1** | abilitare l'apertura doorbell, programmare i range S2A (CP, IH, SDMA), remap della pagina HDP flush in fondo a BAR5 (`0x7F000`) | `nbif_v6_3_1.c` |
| **GMC 12** | VA 48 bit, 4 livelli (blocco 9 bit), GART 512 MiB in VRAM (tabella piatta VMID0), system aperture, VMID 1-15; invalidazione TLB con engine 17 | `gmc_v12_0.c`, `mmhub_v4_1_0.c`, `gfxhub_v12_0.c` |
| **PTE gfx12** | **MTYPE nei bit 54-55** (prima 48-50), **PRT bit 56**, **DCC bit 58** (compressione decisa dalla page table), IS_PTE bit 63 | `amdgpu_vm.h:57-141`, `gmc_v12_0.c:485-549` |
| **IH 7.0** | ring 256 KiB, writeback del wptr, doorbell, MSI. Eventi: CP EOP (client 0x14, src 181), SDMA trap (0x0a/49), VM fault, SMU (0x1f/0xFE), DCN (0x04) | `ih_v7_0.c` |
| **PSP 14.0.2** | **obbligatorio** (firmware firmati). Bootloader: KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV, DBG_DRV, IPKEYMGR_DRV, poi SOS (`C2PMSG_35/36/81`); ring KM (`C2PMSG_64/67/69/70/71`); niente `SETUP_TMR` (TMR riservato dall'IFWI) ma richiesta delle regioni riservate (cmd 0x50/0x51); `LOAD_IP_FW` di SMU, SDMA, CP RS64 (PFP/ME/MEC + stack), MES (uni-MES), IMU, RLC; `AUTOLOAD_RLC`. Il `psp_14_0_2_sos.bin` **non contiene RAS_DRV né RL** (Navi 48 sì) | `psp_v14_0.c`, `amdgpu_psp.c:2952-3684`, `psp_gfx_if.h` |
| **SMU 14.0.2** | mailbox `C2PMSG_66/82/90`; minimo [INFERITO, da verificare]: Test, GetSmuVersion, GetDriverIfVersion, SetDriverDramAddr, TransferTable, SetAllowedFeaturesMask, EnableAllSmuFeatures. Senza quest'ultima la GPU presumibilmente resta ai clock di boot; poiché la stessa chiamata abilita anche THROTTLERS, FW_CTF e FAN_CONTROL, **nessun carico prolungato** prima di averla inviata e verificato con `GetRunningSmuFeatures` (0x54) e la tabella metriche che ventole e protezioni termiche siano attive. Mode1 reset tramite debug mailbox (`C2PMSG_75` = 2) | `smu_v14_0_2_ppt.c`, `smu_cmn.c` |
| **IMU/RLC** | modalità PSP (quella usata da Linux e l'unica compatibile con i firmware firmati; la modalità RLC backdoor su silicio di produzione non è garantita [INFERITO]): si attende `RLC_RLCS_BOOTLOAD_STATUS.BOOTLOAD_COMPLETE` | `gfx_v12_0.c:2331-2358` |
| **GFX 12** | golden `DB_MEM_CONFIG |= 0x8000` (il set `rev0` non serve: rev_id = 1), PC di partenza RS64 per PFP/ME/MEC, GART GFXHUB, `SH_MEM_CONFIG/BASES` per VMID, CSB, range doorbell CP | `gfx_v12_0.c:3767-3860` |
| **MES 12 (uni-MES)** | MES gestisce **tutte** le code: pipe 1 = KIQ, pipe 0 = scheduler; `SET_HW_RSRC` (vmid_mask 0xff00, gfx_hqd 0xfe, compute_hqd 0x0c, sdma_hqd 0xfc, basi GC/MMHUB/OSSSYS), `ADD_QUEUE(map_legacy_kq=1)` per le code kernel | `mes_v12_0.c`, `mes_v12_api_def.h` |
| **SDMA 7.0** | registri nello spazio GC; queue0 via MMIO; doorbell `0x100`/`0x10A` | `sdma_v7_0.c` |
| **HDP** | dopo ogni scrittura CPU in VRAM che la GPU deve vedere: flush HDP (scrittura alla pagina remappata) | `hdp_v7_0.c`, `amdgpu_hdp.c` |
| **Doorbell** | tabella soc24/Navi10 (KIQ 0x0, MEC 0x3-0xA, MES 0xB/0xC, GFX 0x8B, SDMA 0x100/0x10A, IH 0x178; indici ×2 = dword), pagina MES a `0x800` | `amdgpu_doorbell.h`, `soc24.c:267-300` |
| **Reset** | default **mode1** via SMU; per coda via MES; **niente mode2**. Dopo mode1: `asic_init` AtomBIOS, VRAM persa, di nuovo tutto il boot PSP | `soc24.c:173-196`, `amdgpu_device.c:5116-5215` |

**Soglie firmware**: le user queue MES richiedono ME ≥ 3090, PFP ≥ 3190, MEC ≥ 3450, MES ≥ 0x93: i firmware
installati sono **esattamente** sulla soglia.

**Checklist operativa** in 33 passi con indirizzi di registro calcolati per questa scheda: report 01 §6.

### 6.4 Navi 44 contro Navi 48 nel codice Linux

| Area | Navi 44 (GC 12.0.0) | Navi 48 (GC 12.0.1) |
|---|---|---|
| `external_rev_id` | `rev_id + 0x40` | `rev_id + 0x50` |
| Firmware | `gc_12_0_0_*`, `psp_14_0_2_*`, `smu_14_0_2`, `sdma_7_0_0` | `gc_12_0_1_*` (+ `_kicker`), `psp_14_0_3_*`, `smu_14_0_3`, `sdma_7_0_1` |
| Kicker firmware | mai (0x7590 non in lista) | solo 0x7551 rev 0xC8 |
| Contenuto sOS | 9 componenti (niente RAS_DRV, RL) | 11 |
| RAS | non supportato su MP0 14.0.2 | supportato |
| SMU | `enable_gfx_features` solo 14.0.2 | energy accumulator solo 14.0.3 |
| PG flags | senza `JPEG_DPG` | con `JPEG_DPG` |
| Topologia | 2 SE, 32 CU, 8 RB, 4 UMC, 32 MiB MALL | 4 SE, 64 CU, 16 RB, 8 UMC, 64 MiB |
| Display Core (`hw_internal_rev` 0x41 → `ASICREV_IS_GC_12_0_1_A0`, nomi invertiti) | max 8 canali MALL, `dcc_plane_width_limit` 7680, soglie PMFW idle DPM ≥ 0x661300 e DF throttle ≥ 0x663500 | 16 canali MALL, nessun limite, idle DPM ≥ 0x681800, DF throttle mai |
| PSP fw reservation (cmd 0x50/0x51) | se sOS ≥ 0x3b0e0d | se sOS ≥ 0x3a0e14 |
| KFD `gfx_target_version` | 120000 | 120001 |
| Tutto il resto | **identico** (selezione IP block, sequenze, PTE, doorbell, MQD, protocolli PSP/SMU/MES, golden, reset) | |

---

## 7. Display: DCN 4.0.1

Sintesi del report `research/reports/02-linux-display-dcn401.md`.

### 7.1 Cosa sappiamo

- **Stesso DCN di Navi 48**: DMU 4.1.0 in tabella = DCN 4.0.1 nel software (`dcn401_resource.c`,
  `dcn_4_0_1_dmcub.bin`); basi dei segmenti, offset dei registri, 4 pipe (HUBP/DPP/OPP/OTG), 4 DSC, 4 HPO DP, 1 HPO FRL,
  4 endpoint audio: **identici**. Tutti i registri DCN usati stanno in BAR5.
- **Trappola dei nomi**: nel Display Core `ASICREV_IS_GC_12_0_1_A0` è vero per **Navi 44** (external_rev 0x40-0x4f) e
  `ASICREV_IS_GC_12_0_0_A0` per Navi 48: nomi invertiti rispetto alle versioni IP. Differenze codificate per Navi 44:
  8 canali MALL (invece di 16), DCC disattivata su piani più larghi di 7680 px, soglie SMU diverse per idle DPM e DF
  throttle.
- **La differenza vera è la scheda**: 3 PHY. DP-1 = UNIPHY_A/DDC1/HPD1 (fino a UHBR13.5, niente UHBR20), HDMI-A-1 =
  UNIPHY_B/DDC2/HPD2, HDMI-A-2 = UNIPHY_C/DDC3/HPD3 (FRL fino a 10 Gbps per corsia). I riferimenti Navi 48 cablano
  un'altra topologia (DP su PHY B, HDMI su C e D): **ogni mappatura va letta dal VBIOS** (object table + GPIO LUT).
- **Il VBIOS non ha più command table per il display** (solo `asic_init` e 4 tabelle interne): accensione dei PHY,
  swing/pre-emphasis e PLL TMDS passano dal **firmware DMCUB** (`DMUB_CMD__VBIOS` 128, sottotipi
  `DIG1_TRANSMITTER_CONTROL` e `SET_PIXEL_CLOCK`). Tutto il resto (HUBP/DPP/MPC/OPP/OTG/DIG/AUX/DDC/HPD/cursore/flip,
  DP DTO) è programmazione diretta di registri.
- **DMCUB**: Linux lo carica via PSP (firmware firmato), ferma quello pre-OS lasciato dal GOP, copia il VBIOS nella
  finestra CW3 e usa ring inbox/outbox da 8 KiB. Su Navi 48 il GOP lascia un DMCUB pre-OS attivo con il ring in
  `DMCUB_REGION4` e la **storia dei comandi con cui ha acceso lo schermo ancora leggibile**: RDNA4FB e Cobalt64 l'hanno
  riusato con successo. Su Navi 44 è atteso uguale ma **va verificato nello stadio 0**; gli offset dei contesti DFP vanno
  rimisurati (DFP1/2/3 invece di DFP2/3/4).
- **Clock del display**: DISPCLK/DPPCLK/DCFCLK si chiedono all'SMU tramite un mailbox dedicato al display
  (`DAL_MSG/ARG/RESP` = `0x1628A/0x16273/0x16274`, `SetHardMinByFreq` ecc.): senza SMU funzionante restano quelli del
  GOP.
- **Banda per pipe**: watermark, DET e i registri DLG/TTU/RQ escono da **DML 2.1** (52 mila righe in virgola mobile):
  **non può girare in un kext** (niente FPU nel kernel). Si useranno tabelle catturate su Linux per i modi
  dell'utente, poi eventualmente DML in un demone user-space.
- **Linux non conserva l'immagine del GOP** su una dGPU (spegne tutto e rifà il modeset); il nostro driver invece deve
  partire **adottando** la pipe del GOP.
- **S3**: al risveglio non c'è più GOP né DMCUB pre-OS: lo sleep di sistema richiede il percorso completo (interprete
  AtomBIOS per `asic_init`, PSP, caricamento DMCUB, SMU, modeset da zero). Fino ad allora: sleep di sistema
  disattivato, solo display sleep.
- **Audio HDMI/DP** (`03:00.1`): funziona solo se il framebuffer programma endpoint Azalia, AFMT/APG e DTO audio a
  ogni modeset, in modalità HDMI (non DVI come fa Cobalt64 sugli HDMI secondari).

### 7.2 Piano a stadi per il display

| Stadio | Obiettivo | Cosa serve | Riuso |
|---|---|---|---|
| 0. Dati (su Linux) | EDID dei monitor, log DTN per ogni modo voluto, stato del GOP e ring DMCUB pre-OS prima di `amdgpu` | §19 | — |
| 1. Adozione GOP | desktop macOS (rendering CPU) sul display di boot, un modo | lettura HUBP/OTG/DIG, `getApertureRange` = scanout, EDID via AUX/DDC, vblank emulato da timer, display sleep DP, cursore HW | RDNA4FB quasi tutto (+ `0x7590`, mappa dal VBIOS) |
| 1b. Flip e vblank veri | WindowServer accelerato su un display | flip HUBP (scrittura `PRIMARY_SURFACE_ADDRESS_HIGH` poi `_ADDRESS`), interrupt VSTARTUP/PFLIP via IH (client 0x04), superfici in VRAM allineate a 256 B | Cobalt64 `src/dcn41` |
| 2. Modi fissi | cambiare risoluzione/refresh sullo stesso link | timing OTG, DP DTO, HUBP/DPP, tabelle DLG/TTU/RQ/WM/DET catturate su Linux, `SetHardMinByFreq` | Cobalt64 "mode trial" |
| 3. Modeset nativo | accendere un connettore spento, hotplug | DMCUB (pre-OS o caricato via PSP), PHY via `DIG1_TRANSMITTER_CONTROL`, pixel clock, **link training DP 8b/10b**, **HDMI TMDS + SCDC** (scrambling sopra 340 MHz, necessario per 4K60 HDMI) | Linux `link_dp_training*.c`, `link_dpms.c` |
| 4. Multi-display | tre connettori insieme | una pipe per display, watermark/DET globali, PLL/DTO per istanza | — |
| 5. Completamento | audio, S3, 10 bit/HDR, VRR, DSC, UHBR, FRL | Display Core di Linux (MIT) o porting selettivo | Linux DC |

Durante gli stadi 1-2 il driver **non deve** resettare DCN o DMCUB, e deve impedire all'SMU di cambiare la frequenza
della memoria sotto la scanout del GOP (watermark non adeguati → sfarfallio): UCLK fisso finché il display non è
nativo.

---

## 8. Vulkan sotto Metal: RADV/ACO e backend Darwin

Sintesi del report `research/reports/03-mesa-radv-aco-gfx12.md`.

### 8.1 RADV su gfx1200 è pronto

Su questa macchina RADV (Mesa 26.3-devel) espone sulla RX 9060 XT **Vulkan 1.4.363 con 247 estensioni**: ray
tracing (BVH8, RT 3.1), mesh/task shader, cooperative matrix, bfloat16/float8, descriptor heap, buffer device
address, timeline semaphore, sparse. radeonsi usa lo stesso compilatore ACO. In Mesa **non c'è codice specifico
Navi 44 contro Navi 48**: le differenze passano solo da `radeon_info` (SE, CU, RB, bus, MALL). L'ISA è identica
(`llvm-mc -mcpu=gfx1200` e `gfx1201` producono gli stessi encoding). Addrlib GFX12 non dipende da `GB_ADDR_CONFIG`:
il layout delle texture è lo stesso sulle due GPU.

### 8.2 Il confine con il kernel è piccolo

Tutte le chiamate al kernel di RADV passano per **59 funzioni `ac_drm_*`** (`src/amd/common/ac_linux_drm.h`); RADV
e `ac_gpu_info.c` ne usano ~48. Esistono già due backend (libdrm e virtio native context); la sincronizzazione passa
da `util_sync_provider` (15 callback) ed è sostituibile in userspace. **Il port Darwin è un terzo backend sotto
`ac_drm_*`** più piccole modifiche a enumerazione e build: RADV, ACO e addrlib (~354 mila righe) restano intatti.
Cobalt64 l'ha già fatto per Navi 48 (9 patch, ~3 000 righe di backend reale + ~500 righe di modifiche a Mesa).

### 8.3 Cosa il kernel deve garantire a RADV

- **VA scelti dall'userspace** (range alto `0xffff8000_00000000+`, range 32 bit con `address32_hi = 0xffff8000`;
  il kernel non sceglie mai un VA), `GEM_VA` MAP/UNMAP (poi PRT/CLEAR/REPLACE per lo sparse).
- **BO** in VRAM/GTT con i flag `AMDGPU_GEM_CREATE_*`, incluso `GFX12_DCC` (→ bit 58 nelle PTE). "VRAM|GTT" va trattato
  come "VRAM preferita" se il kext non fa eviction.
- **Submit** con chunk IB / FENCE / SYNCOBJ / BO_HANDLES; IB utente lanciati con `INDIRECT_BUFFER` dal ring kernel
  con il VMID del processo; fence seqno per ring; reset di contesto (`-ECANCELED/-ENODATA/-ETIME`). **Task e mesh
  shader** (`VK_EXT_mesh_shader`) sono attivi in RADV solo se il kext dichiara almeno una coda compute
  (`radv_taskmesh_enabled` → `radv_compute_queue_enabled`); RADV non controlla il flag `GANG_SUBMIT`, quindi dichiarare
  la coda compute implica supportare il gang submit GFX+compute. Fase 1: nessuna coda compute dichiarata (mesh/task
  spenti).
- **Sync**: syncobj timeline (implementabili in userspace sopra i seqno del kext); niente implicit sync (RADV marca
  tutti i BO interni come `EXPLICIT_SYNC`); niente `sync_file` su macOS.
- **Info device reali**: `drm_amdgpu_info_device` con device_id 0x7590, external_rev 0x41, family 0x98, 2 SE × 2 SA ×
  8 CU, `cu_bitmap`, RB 0xff, cache, MALL, layout VA, versioni firmware ME/PFP/MEC. **Usare i valori canned gfx1201 di
  Cobalt64 su Navi 44 sarebbe un errore** (maschere CU/RB sbagliate → hang). I valori giusti sono già stati estratti
  da questa macchina con un tool non privilegiato: `research/artifacts/mesa-radv/gfx1200_canned_dump.txt`.

### 8.4 Novità GFX12 rilevanti per il kernel

- Niente `CLEAR_STATE` né shadowing dei registri da firmware: RADV emette un preamble completo; i ring NGG
  (attribute/pos/prim) e lo scratch sono programmati **dall'IB utente** con `SET_*_REG_PAIRS` (0xB8/0xBA/0xBE).
- **DCC "trasparente"**: compressione attiva se `PTE.D && COMPRESSION_EN`; i metadati sono nascosti all'userspace; il
  kernel deve decomprimere con SDMA quando sposta un BO compresso fuori dalla VRAM (o non spostarlo mai). Fase 1:
  BO sempre residenti, DCC disattivabile (`RADV_DEBUG=nodcc`).
- `has_smem_with_null_prt_bug` su gfx1200: lo sparse richiede mappature multiple dello stesso BO (bit di controllo
  VA misurato: 46).
- RADV compila in **wave64 di default** compute, pixel e shader geometrici (VS/GS/NGG); solo il ray tracing usa wave32.
  Il layer Metal deve chiedere `requiredSubgroupSize = 32` per gli stadi che usano operazioni `simd_*` (possibile solo in
  fragment, compute, task e mesh) e usare operazioni "clustered" a 32 negli altri; nel nostro RADV Darwin valutare
  `cs/ps/ge_wave_size = 32` di default (Metal assume simdgroup = 32).

### 8.5 ABI del kext per RADV (proposta)

Sottoinsieme 1:1 di `DRM_AMDGPU_*` con struct identiche (per riusare test e strumenti Linux): `HELLO` (con bitmask
di capacità), `QUERY_DEVICE` (blob reale: info device + hw_ip + firmware + `GB_ADDR_CONFIG`), `QUERY_DYNAMIC`,
`BO_CREATE`, `BO_FREE`, mapping via `IOConnectMapMemory64`, `GEM_VA`, `CTX`, `SUBMIT` (multi-IP), `WAIT_SEQ`,
`BO_WAIT_IDLE`, poi `BO_IMPORT_HOST`, `BO_SHARE/OPEN` (IOSurface), `BO_METADATA`, `READ_REGS` (debug). Dettaglio in
Appendice C. Stima del backend Mesa: **~4 000 righe** in fase 1, fino a 6-9 mila con mock e test.

---

## 9. Il livello Metal

Sintesi dei report `research/reports/08-metal-translation-layer.md` e `06-nvidia-macos-driver-deepdive.md`.

### 9.1 Il contratto macOS per una GPU di terze parti (vendor-neutrale)

1. Un `IOGraphicsAccelerator2` attaccato all'`IOPCIDevice` con `IOMatchCategory=IOAccelerator`, `MetalPluginName` e
   `MetalPluginClassName`. Su Tahoe 26.6.2 Cobalt64 usa come `MetalPluginName` il solo nome del bundle (`Navi48Metal`)
   installato in `/Library/GPUBundles`; NullMoth su Sequoia usa il percorso relativo
   `../../../Library/GPUBundles/NVMTLDriver` (relativo a `/System/Library/Extensions`). Va verificato quale forma accetta
   la build scelta. I metodi puri da implementare sono 17; il resto lo fornisce
   la famiglia. Apple non pubblica header: layout e vtable vanno ricostruiti dal binario (nomi presi dai simboli dei
   kext AMD di Apple) per ogni versione di macOS (NullMoth spedisce un acceleratore diverso per 15 e per 26).
2. Un plugin che eredita la classe privata `MTLIOAccelDevice` e risponde a `-initWithAcceleratorPort:`; gli altri
   oggetti possono essere `NSObject` conformi ai protocolli pubblici `MTL*` (NullMoth) o sottoclassi delle classi
   private `_MTL*` (Cobalt64), più una rete di forwarding per i selettori privati non implementati (un selettore
   mancante = crash di WindowServer).
3. Front-end MSL di Apple (MTLCompilerService), back-end nostro: AIR → SPIR-V → RADV/ACO → gfx1200. Il compilatore AMD
   di Apple produce solo gfx10.3 e non serve.
4. **IOSurface come valuta comune**; presentazione di WindowServer tramite **display pipe transactions** su un
   `IOAccelDisplayPipe` legato a un `IOFramebuffer` vero.
5. Gating: `MetalPluginName` solo quando il display è pronto (altrimenti CoreDisplay va in crash loop), allow-list per
   processo, boot hold.
6. AGDC shim per la display policy.
7. Firma: bundle ad-hoc caricato da WindowServer (platform binary) ⇒ SIP rilassato + `amfi_get_out_of_my_way=0x1
   amfi=0x80` + **AMFIPass**; `ipc_control_port_options=0` per non far crashare Firefox e app hardened.

### 9.2 AIR e traduzione

- **AIR** = bitcode LLVM del fork Apple dentro un container `MTLB` (un modulo per funzione). **Verificato**: LLVM 23.1
  upstream legge l'AIR 2.8 di macOS 26 (`air64_v28-apple-macosx26.0.0`, metalfe-32023.921).
- **metal2vulkan è cambiato**: NullMoth e Cobalt64 usano la 0.1 (testo LLVM → SPIR-V per funzione); l'upstream 0.2
  (non ancora rilasciata: snapshot del commit `13b279d` dell'11/10/2026, da fissare a un commit preciso) è una riscrittura con lettore bitcode proprio, compilazione **per pipeline**, binding plan e un
  **runtime Metal-su-Vulkan** completo (hazard tracking, eventi come timeline semaphore, ICB, argument buffer, formati
  XR10/YCbCr). La documentazione cita shader reali di macOS 26 (pipeline del login di 26.6.2, frammenti CoreAnimation),
  ma la suite di validazione e il corpus non sono pubblici e la classificazione "reach = system" è una stima manuale. Copertura
  API: 957 voci implementate, 829 mancanti, 349 fuori scope (IOSurface, drawable, ray tracing API). Stato "alpha".
- **RADV gfx1200 non ha gap hardware per Metal 3**: delle 29 feature e 2 estensioni Vulkan nominate da metal2vulkan,
  25 sono presenti come feature RADV, 3 sono di `portability_subset` (implicite su un driver completo) e
  `rasterizationOrderColorAttachmentAccess` manca su gfx1200 (framebuffer fetch e raster order group passano da
  `fragmentShaderPixelInterlock`); presenti anche le 2 estensioni (bindless via buffer device address + descriptor heap, atomici a 64 bit e float, subgroup size control,
  mesh, ray query, sparse, pixel interlock per il framebuffer fetch, cooperative matrix, bfloat16). I gap sono nel
  software: `simdgroup_matrix` non implementata nel traduttore, build delle acceleration structure, ICB codificati
  dalla GPU, Metal 4, e varie dipendenze dal kext (VA stabili, userptr, syncobj timeline, coda compute + gang submit,
  PRT, fence per BO).
- **simdgroup = 32**: RADV usa wave64 di default per compute, pixel e shader geometrici; il layer deve chiedere
  `requiredSubgroupSize = 32` (possibile solo in fragment, compute, task e mesh) e usare operazioni "clustered" a 32
  negli altri stadi, oppure compilare il nostro RADV Darwin con wave32 di default.
- Formati: `Depth24Stencil8` **non** esiste su gfx12 (rispondere NO); 4:2:2 Apple ed XR10 vanno emulati.

### 9.3 Cosa serve per un desktop, poi per le app

| Tappa | Deve funzionare |
|---|---|
| T0 "il device esiste" | registry + plugin + `initWithAcceleratorPort:` + `featureProfile`/`initLimits` (senza, CoreImage rifiuta di disegnare) + forwarding SPI |
| T1 WindowServer | texture su IOSurface (anche multi-plane), render pass colore con blend, **framebuffer fetch e formati XR10** (usati dal login di Tahoe), heap per MPS, depth/stencil state, sampler bicubico, blit/fill, compute semplice, `commit`/attese, presentazione su display pipe ordinata rispetto alla fence, **mai restituire nil** |
| T2 CoreImage/Anteprima/Foto | kernel `air.ci`, function constants, YCbCr, `newBufferWithBytesNoCopy:`, `newLibraryWithSource:` |
| T3 Browser | traduzione **in-process** nel sandbox, MSL a runtime, `MTLSharedEvent` cross-process, argument buffer tier 1, IOSurface tra processi |
| T4 Metal 3 per le app | argument buffer tier 2, `gpuAddress`/`gpuResourceID`, `useResource/useHeap`, residency set, ICB, sparse, dichiarazione `MTLGPUFamilyMetal3` (solo quando passa i test: Cobalt64 insegna che dichiararla prima rompe le app) |
| T5 Avanzato | ray tracing (build AS + `VK_KHR_ray_query`), `simdgroup_matrix` (cooperative matrix), Metal 4 |

### 9.4 IOSurface e presentazione

Tre modelli: (A) **memoria di sistema importata** con userptr e copia per frame in VRAM verso lo scanout (Cobalt64:
semplice, robusto); (B) **VRAM zero-copy** tramite la famiglia IOAccelerator e flip diretto della superficie composta
(NullMoth: veloce ma legato ai layout privati); (C) immagine privata + copie (fallback). Su una dGPU lo scanout DCN legge
solo dalla VRAM. Raccomandazione: (A) per il bring-up, (B) + **fence per BO nel kext** per le prestazioni. All'inizio
WindowServer attende il completamento GPU prima dello swap (come NullMoth), poi il flip viene ordinato dopo la fence
lato kernel.

### 9.5 Architettura raccomandata per il bundle

Shim ObjC sul modello del bundle di Cobalt64 (MIT): le librerie e le funzioni restano quelle di Apple (massima
compatibilità con reflection, `newLibraryWithSource:` di WebKit/ANGLE/Dawn, librerie CoreImage); il nostro codice
interviene alla creazione della pipeline prendendo l'AIR (`-[MTLFunction bitcodeData]`, con ripiego via
`libraryDataContents`). Come motore: **`metal2vulkan-runtime` 0.2** che adotta il `VkDevice` di RADV (LGPL, dylib
separata); come rete di sicurezza: solo il traduttore + encoder nostri (modello Cobalt64/NullMoth). Per WindowServer:
cache di pipeline precompilata + traduzione asincrona con pipeline di fallback. **Le tappe di traduzione si possono
validare su Linux con RADV sulla stessa scheda** prima ancora di avere macOS o il kext (tappe L0-L1 del report 08 §9).

---

## 10. Compute, ROCm e toolchain ISA gfx1200

Sintesi del report `research/reports/04-rocm-kfd-llvm-gfx1200.md`.

### 10.1 Risultati dei test su questa macchina

- **ROCm 7.2.4 funziona pienamente** sulla RX 9060 XT: `rocminfo` vede l'agent `gfx1200` (32 CU, wave32, L2 4 MB, MALL
  32 MB, ISA `gfx1200` + `gfx12-generic`); un **vector-add HIP** scritto per il test gira a **~300 GB/s** (94% del
  picco GDDR6 a 128 bit) con **~3,8 µs per lancio**: è il riferimento di banda e latenza da eguagliare su macOS.
- **Toolchain LLVM verificata**: clang 23.1.1 e rocm-llvm 22 generano code object **v6** per gfx1200 (`EF_AMDGPU_MACH
  0x48`; `gfx12-generic` = 0x59 copre sia gfx1200 sia gfx1201), wave32 di default, kernel descriptor da 64 byte con i
  campi gfx12. L'ISA mostra le novità gfx12: contatori di attesa separati, barriere split, ID del workgroup in
  TTMP7/TTMP9 (il trap handler deve preservarli).
- **AIR di Apple → LLVM AMDGPU → gfx1200 funziona**: tre kernel MSL reali (compilati dal compilatore Metal di Apple,
  AIR 2.8) sono stati abbassati con una trasformazione meccanica (triple, address space, builtin, barriere, atomici,
  LDS dinamica) e **eseguiti correttamente sulla RX 9060 XT** (tutti PASS). Pipeline riproducibile e script in
  `research/artifacts/compute/`.

### 10.2 Conclusioni per il progetto

1. **KFD non va portato** (dipende da tutto il core amdgpu, sysfs, HMM). Da KFD si prendono: logica `add_queue_mes` e
   MQD v12, il **trap handler CWSR gfx12** (blob MIT riusabile così com'è, save area di 15 351 808 byte per coda con
   32 CU, valore calcolato e confermato in sysfs), lo schema fence/eventi (signal page + EOP).
2. **mac-amdgpu è la migliore "specifica eseguibile" del bring-up RDNA 4 fuori da Linux** (15 stage); per gfx1200
   cambiano ID, nomi firmware, PSP/SMU 14.0.2 e il MACH ELF. Il passaggio da DriverKit/Apple Silicon a kext/x86 cambia le
   API ma semplifica (MMIO diretto, DMA host normale, doorbell mappabili). Gap principale: tutto gira in VMID0, senza VM
   per processo.
3. **Milestone compute-first**: il primo traguardo funzionale su macOS è un dispatch compute (prima del display
   accelerato), con i kernel già validati su Linux come oracolo (`research/artifacts/compute/kernels/`).
4. **Formato delle code per Metal: PM4**, non AQL (AQL serve solo all'ABI HSA). Le user queue PM4 gfx+compute via MES
   di Linux sono il modello di riferimento.
5. **PCIe AtomicOps** non necessari: con firmware MEC ≥ 2090 (installato: 3450) KFD stesso non li richiede.
6. **Compilatore**: per la grafica la via principale resta AIR → SPIR-V → ACO (Mesa gestisce già NGG, export,
   interpolazione per gfx12); il percorso **AIR → LLVM AMDGPU** dimostrato qui è un ottimo oracolo e un'alternativa per
   kernel compute pesanti, e permette di testare il compute del kext con kernel Metal reali.

---

## 11. Strategia: opzioni valutate e decisione

### 11.1 Le opzioni

| # | Opzione | Pro | Contro | Verdetto |
|---|---|---|---|---|
| A | **Riusare i kext Apple AMD** (stile NootRX: spoof del device id, iniezione firmware, patch Lilu) | stack Apple completo e firmato (Metal, WindowServer, OpenCL) | Apple si ferma a RDNA 2: libreria TTL senza voci oltre Navi 23, niente MES, PTE e DCN diversi, **il compilatore shader di Apple produce ISA gfx10.3**, che gfx12 non esegue. Cobalt64 ci ha provato ("rotta Apple"): ~106 mila righe di hook, traduzione PM4 gfx10.3→gfx12, sostituzione di shader catturati, il tutto legato byte per byte a macOS 26.6.2 build 25G83 | **scartata** |
| B | **Fork integrale di Cobalt64** cambiando id e firmware | il più veloce per vedere qualcosa | eredita la rotta Apple, file monolitici (8 971 righe in un `.cpp`, 2,4 MB un altro), centinaia di boot-arg sperimentali, display cablato su un'altra scheda e su altri monitor, **manca `tools/native/ioaccel-layout`** (il kext acceleratore non compila), nessun reset GPU | sconsigliata così com'è |
| **C** | **Fork selettivo della "rotta nativa" di Cobalt64 dentro un'architettura modulare stile NullMoth**, parametrizzata per ASIC | riusa il lavoro difficile già validato su RDNA 4 (scala di bring-up, ABI gemella di DRM, patch Mesa, bundle Metal), Navi 44 condivide tutte le generazioni IP con Navi 48, licenze permissive (MIT/BSD-3), architettura pulita e manutenibile | va comunque ricostruito il layout privato di IOAcceleratorFamily2 per la nostra build di macOS; display da rifare per la nostra scheda | **raccomandata** |
| D | **Portare `amdgpu` intero su XNU** con uno strato di compatibilità Linux (alla FreeBSD LinuxKPI, o come NullMoth con l'RM NVIDIA) | display completo (DC), power management, reset, tutto "gratis" | `amdgpu` dipende da DRM, TTM, dma-fence, drm_sched, workqueue, kthread…: anni di lavoro. Unica eccezione interessante: il **Display Core** è progettato per essere indipendente dal sistema operativo (strato `dm_services`, condiviso con il driver Windows) e potrebbe essere portato da solo in M8 | scartata per il core; **valutare per il solo DC** in M8 |
| E | **DriverKit / PCIDriverKit** (come mac-amdgpu) | niente kext, niente panic del kernel | DriverKit non ha le famiglie IOAccelerator/IOGraphics/IOFramebuffer: va bene per il compute, non per un device Metal di sistema e i display | scartata per il desktop (ok per un eventuale side-project compute) |
| F | **Tutto da zero** | licenze pulite, conoscenza totale | 9-18 mesi-uomo per arrivare dove Cobalt64 è già | sconsigliata |

### 11.2 La decisione: opzione C

Principi guida:

1. **Architettura NullMoth, implementazione ispirata a Cobalt64, specifica = Linux.** Quattro kext con ruoli separati e
   ABI interne versionate (`callPlatformFunction` + struct versionate), bundle Metal in `/Library/GPUBundles`, Mesa
   come libreria dinamica caricata dal bundle. Il codice NullMoth si **legge** ma non si copia (licenza
   Noncommercial), salvo che tu decida di rilasciare l'intero progetto con licenza non commerciale (§17).
2. **Niente costanti per ASIC nel codice.** Tutto da IP discovery (basi registri, versioni, SE/CU/RB, MALL) e da un
   **profilo ASIC** (`device id → nomi firmware, nome marketing, differenze note`), idea presa da 7000-macos ed estesa.
   Così lo stesso driver può supportare in futuro anche Navi 48 (e magari ricevere contributi da Cobalt64).
3. **Ogni passo verificato contro Linux sulla stessa scheda** (dump, tracce MMIO, MQD, pacchetti MES, IB di RADV).
4. **Gating ovunque**: boot-arg di abilitazione, kill switch, boot hold con timeout, `MetalPluginName` pubblicato solo
   quando il display è pronto, allow-list per processo, voce di recovery nel boot picker. Mai un boot loop.
5. **Collaborare con Cobalt64.** Il loro README indica le altre famiglie (es. RDNA 3) come lavoro futuro che richiede
   bring-up dedicato "e qualcuno con quell'hardware per testarlo"; Navi 44 è della stessa famiglia RDNA 4 e potrebbe
   interessare. Chiedere loro `tools/native/ioaccel-layout` e proporre il supporto Navi 44: se l'upstream lo accetta, il
   progetto può diventare "supporto Navi 44 dentro Cobalt64" invece di un fork. Decisione tua (§20).

### 11.3 Cosa prendere da dove

| Componente | Fonte principale | Fonte secondaria / riferimento | Lavoro specifico Navi 44 |
|---|---|---|---|
| Parser IP discovery, AtomBIOS | RDNA4FB (BSD-3) / Cobalt64 | `amdgpu_discovery.c`, `atom.c` | nessuno (dati a runtime) |
| Scala di bring-up (NBIF, GMC, IH, PSP, SMU, IMU/RLC, CP, MES, SDMA) | Cobalt64 `src/navi48-bringup/src/amd` (BSD-3, derivato da mac-amdgpu MIT) | Linux `gfx_v12_0.c`, `psp_v14_0.c`, `mes_v12_0.c`, … | firmware 12.0.0/14.0.2/7.0.0, caps da `gc_info`, golden `DB_MEM_CONFIG`, sOS senza RAS/RL, reset mode1 |
| ABI kernel-userspace | Cobalt64 `Navi48NativeABI.h` (N48N) | `include/uapi/drm/amdgpu_drm.h` | `QUERY_DEVICE` reale, capability bit, multi-ring |
| Backend Darwin di RADV | patch Mesa di Cobalt64 0001-0009 (MIT) | `ac_linux_drm.c`, backend virtio | info device gfx1200 reali, niente id finti |
| Framebuffer | RDNA4FB + Cobalt64 `src/dcn41`, `src/dcn` | Linux `dc/*/dcn401`, `dmub` | mappa connettori dal VBIOS (DP=PHY A, HDMI=PHY B/C), modi da EDID |
| Acceleratore (IOGraphicsAccelerator2) | ricostruzione nostra del layout (stesso metodo di NullMoth/Cobalt64) | NullMoth `kexts/NVRM/accel` (solo lettura), Cobalt64 `tools/native/navi48accel`, `AMDRadeonX6000.kext` di Apple come esempio vivo | nessuno (vendor-neutrale) |
| AGDC shim | ricostruzione nostra | NullMoth `NVRMAGDC` (solo lettura) | vendorID 0x1002 |
| Bundle Metal (shim ObjC, gating, IOSurface, presentazione) | Cobalt64 `tools/native/navi48metal` (MIT) | NullMoth `plugin/` (solo lettura) | nome, id `0x7590`, wave32, limiti |
| Motore Metal-su-Vulkan + traduttore AIR→SPIR-V | **metal2vulkan 0.2** upstream (runtime + traduttore per pipeline; GPL-2.0+ OR LGPL-3.0+, usato come LGPL in una dylib) | metal2vulkan 0.1 (usato da NullMoth e Cobalt64) come ripiego | profilo device RDNA4 da aggiungere alla loro validazione (`research/artifacts/metal-xlate/vkprofile_gpu0.json`) |
| Trap handler CWSR | Linux `amdkfd/cwsr_trap_handler.h` (`cwsr_trap_gfx12_hex`, MIT) | — | nessuno (stesso per gfx1200/gfx1201) |
| Installer/recovery | nostro | procedura NullMoth (Aux KC, AMFIPass, entry EFI di recovery) | nessuno |

**Da non usare**: NootRX/NootedRed ("ChefKiss Open Knowledge License v1": nessun diritto di creare opere derivate e
divieto di qualsiasi uso con IA, inclusi lettura e analisi da parte di assistenti; i cloni sono stati rimossi da
`research/refs/` e il report 07 è stato ripulito dai dettagli ricavati dal loro codice) e il codice NullMoth (PolyForm
Noncommercial) salvo la scelta di §20.

---

## 12. Versione di macOS e configurazione OpenCore

Sintesi del report `research/reports/07-apple-amd-stack-and-lilu.md`.

### 12.1 Quale macOS

- **macOS 26 Tahoe è l'ultima versione per Mac Intel**: macOS 27 è solo Apple silicon (pagina Apple di compatibilità).
  I Mac Intel supportati da Tahoe sono MacBook Pro 16" 2019, MacBook Pro 13" 2020, iMac 2020 e **Mac Pro 2019**. I kext
  AMD di Apple ci sono ancora in Tahoe ma non evolveranno più (e non riconoscono `0x7590`: nessun conflitto).
- Dopo l'ultima point release, le ABI private di IOAcceleratorFamily2/IOGraphicsFamily di Tahoe **dovrebbero smettere
  di muoversi** (inferenza: gli aggiornamenti di sicurezza possono comunque toccare questi kext): un vantaggio per un
  driver che dipende da layout privati.

| Opzione | Pro | Contro |
|---|---|---|
| **Tahoe 26.x (raccomandata)** | ultima release x86, ABI che dovrebbe congelarsi, vita più lunga (aggiornamenti di sicurezza presumibilmente fino a ~2028); Cobalt64 (RDNA 4) è tarato su Tahoe 26.6.2 e la documentazione di metal2vulkan 0.2 cita shader di 26.6.2; NullMoth ha una variante dell'acceleratore per 26 ma è qualificato solo su Sequoia | UI Liquid Glass più pesante per la GPU; meno esperienza della comunità |
| Sequoia 15.7.x | NullMoth è nato qui; tooling maturo | supporto più breve; ABI IOAccelerator diversa da 26 (andrebbero mantenute due varianti) |

**Raccomandazione**: **Tahoe 26.x, congelata su una build precisa** (es. la 26.6.2 usata da Cobalt64, oppure l'ultima
disponibile all'avvio dello sviluppo) con aggiornamenti automatici disattivati. Sequoia solo come confronto se un
comportamento di IOAcceleratorFamily2 diverge.

### 12.2 OpenCore per Ryzen 7 7700 / MSI B840 GAMING PLUS WIFI

| Area | Impostazione |
|---|---|
| Patch kernel | **AMD_Vanilla** (supporta fino a Tahoe 26) con `Kernel > Quirks > ProvideCurrentCpuInfo = YES`; patch IOPCIFamily per Zen 4 abilitata; core count nelle quattro patch `cpuid_cores_per_package`: **`BA 08 00 00 00`** (8 core fisici) |
| Quirk kernel | `DummyPowerManagement`, `PanicNoKextDump`, `PowerTimeoutKernelPanic`, `ProvideCurrentCpuInfo` = YES; `XhciPortLimit`, `DisableIoMapper`, `AppleXcpmCfgLock` = NO |
| Quirk booter | `RebuildAppleMemoryMap`, `SyncRuntimePermissions` = YES; `SetupVirtualMap` da provare; `EnableWriteUnprotector`, `DevirtualiseMmio` = NO |
| SSDT | `SSDT-EC-USBX`; `SSDT-CPUR` se nel DSDT i processori sono `Device (ACPI0007)` (da verificare sul DSDT della B840) |
| SMBIOS | **MacPro7,1** (supportato da Tahoe, pensato per dGPU AMD, la display policy non spegne le uscite). `iMacPro1,1` (usato da NullMoth su Sequoia) **non** è supportato da Tahoe |
| Kext | Lilu, **AMFIPass**, VirtualSMC, AppleALC (Realtek ALC897), LucyRTL8125Ethernet, NVMeFix, RestrictEvents, mappa USB (USBToolBox + UTBMap). Non servono WhateverGreen/NootRX/NootedRed. I nostri kext vanno nell'**Auxiliary KC** (`/Library/Extensions`, `kmutil`, approvazione utente), non iniettati da OpenCore, perché linkano IOGraphicsFamily/IOAcceleratorFamily2 |
| Sicurezza | `SecureBootModel = Disabled`; SIP con `csr-active-config` tipo `0x0A43` (kext non firmati, root non autenticata per KC/KDK); boot-args `amfi_get_out_of_my_way=0x1 amfi=0x80 ipc_control_port_options=0` |
| Resizable BAR | `UEFI > Quirks > ResizeGpuBars` e `Booter > Quirks > ResizeAppleGpuBars`. Installer e primi boot senza driver: `ResizeAppleGpuBars = 0` (il framebuffer GOP sopravvive al setup PCI solo con BAR piccola); col nostro driver: da 256 MB a 1 GB secondo quanto accetta IOPCIFamily (Cobalt64 riporta un limite di 1 GiB su Tahoe), 16 GB da verificare |
| Display | `Kernel > Block com.apple.iokit.IONDRVSupport` (Exclude) quando il nostro framebuffer è pronto, altrimenti il framebuffer firmware si prende l'indice 0 |
| iGPU Raphael | nessun driver macOS: disattivarla nel BIOS per l'uso normale; **in sviluppo** può essere utile tenerla come console GOP (display di riserva non accelerato) lasciando la RX 9060 XT secondaria e non reclamata, così un crash del nostro driver non toglie l'unico schermo (da verificare che il BIOS MSI lo consenta). **Attenzione**: in questa configurazione il GOP della RX 9060 XT potrebbe non accendere alcun monitor, e senza una pipe accesa non c'è nulla da adottare (stadio 1 di §7.2): lo stadio 1 va provato con la dGPU primaria |
| Rete | Ethernet RTL8125 ok con kext di terze parti; **Wi-Fi/Bluetooth Qualcomm WCN785x senza driver macOS** (eventuale sostituzione del modulo M.2 con un Broadcom supportato) |
| USB | ≤ 15 porte per controller: `XhciPortLimit` non serve, mappatura comunque consigliata |
| BIOS | Above 4G Decoding ON, Re-Size BAR ON, CSM OFF, Secure Boot OFF, Fast Boot OFF, IOMMU OFF per macOS (ON su Linux se si usa VFIO), **porta COM lasciata abilitata** (strumento di debug, §13). **Prima di cambiare il BIOS** vedi le precauzioni in §12.4 |

### 12.3 Perché i kext Apple non si possono riusare (in breve)

Lo stack AMD di Apple (`AMDRadeonX6000*`, HWLibs, `AMDRadeonX6000MTLDriver.bundle`; correzione: `AMDMTLBronzeDriver` è
il driver Metal GCN/Polaris) è fatto di tabelle e dispatch per versioni IP precise (GC 10.x, SDMA 5.x, PSP 11, SMU
11.0.x, DCN 2-3, AddrLib Gfx10). Secondo le dichiarazioni pubbliche del maintainer (issue #144), NootRX funziona
per Navi 22 perché è interfacciata a livello hardware come gli altri Navi 2x: stesse generazioni IP, solo versioni minori
diverse. Per RDNA 4 **nessuna** precondizione è vera: nessun codice Apple per GC 12, SDMA 7, PSP 14, SMU 14, MES, IH 7,
GMC 12, DCN 4, AddrLib Gfx12, e l'ISA gfx12 è incompatibile con gfx10 per load/store/sample/wait (verificato con
`llvm-mc`). Il maintainer di NootRX stesso considera RDNA 4 possibile solo "with a whole lot more work", senza piani.
Lilu resta utile solo come libreria di utilità (AMFIPass, eventuali patch board-id/DRM).

### 12.4 Precauzioni prima di toccare BIOS, dischi e bootloader (per non danneggiare Linux e Windows)

1. **Backup** dei dati di Linux e Windows e copia delle partizioni EFI esistenti (`nvme0n1p1`, `nvme1n1p1`, `nvme1n1p5`).
2. **Windows/BitLocker**: in Windows eseguire `manage-bde -status`; se BitLocker o la crittografia del dispositivo sono
   attivi, salvare la chiave di ripristino e sospendere la protezione (`manage-bde -protectors -disable C:`) **prima** di
   cambiare Secure Boot, CSM o l'ordine di avvio, altrimenti Windows può chiedere la chiave di ripristino al riavvio.
3. Verificare che Windows e Linux siano installati in modalità **UEFI/GPT** prima di disattivare il CSM (dalle partizioni
   EFI presenti sembra di sì, ma va confermato).
4. **Annotare o salvare il profilo BIOS attuale** per poterlo ripristinare. Secure Boot OFF disattiva i giochi con
   anti-cheat che lo richiedono; IOMMU OFF impedisce il passthrough VFIO su Linux: cambiarli solo per le sessioni bare metal.
5. **OpenCore solo nella ESP del disco macOS dedicato**: mai nella ESP di Windows o di Linux, nessuna sovrascrittura di
   `EFI/BOOT/BOOTx64.efi` altrui.
6. Durante l'installazione di macOS **scollegare fisicamente** (o disattivare nel BIOS) gli NVMe di Linux e Windows, per
   non cancellare per errore il disco sbagliato.
7. Avviare Windows e Linux dal **boot menu del firmware**, non da OpenCore (che inietterebbe ACPI/SMBIOS anche negli
   altri sistemi).

---

## 13. Ambiente di sviluppo e di test

### 13.1 Perché serve un ambiente dedicato

Un kext che programma la GPU può bloccare la macchina, lasciare la GPU in uno stato incoerente o mandare in panic il
kernel a ogni tentativo. Per non fare danni e iterare velocemente servono **isolamento** (un crash non deve toccare
Linux, Windows o i loro dischi), **osservabilità** (log seriale, debugger, traccia degli accessi MMIO) e un
**oracolo** con cui confrontare ogni passo (lo stato che `amdgpu` ottiene su questa stessa scheda).

### 13.2 Configurazione raccomandata: Linux host + VM macOS con la RX 9060 XT in passthrough (VFIO)

Verificato su questa macchina:
- IOMMU attivo; la GPU `03:00.0` è da sola nel **gruppo IOMMU 15** e l'audio HDMI `03:00.1` nel **gruppo 16**
  (isolamento perfetto, niente ACS override).
- KVM disponibile (`/dev/kvm`, `kvm_amd npt=Y`).
- La CPU ha una iGPU (Raphael) che può tenere il desktop Linux mentre la dGPU va alla VM.
- La scheda **non supporta FLR** → rischio "reset bug" allo spegnimento della VM (noto per la RX 9070 XT nel 2026; per la 9060 XT da verificare).
  Workaround documentati dalla comunità: lasciare `amdgpu` legato all'avvio e passare la scheda alla VM
  dinamicamente, sganciarla prima dello stop della VM, oppure un breve suspend-to-RAM dell'host per resettarla.
  **Da verificare in M0** (è il primo esperimento da fare).

Vantaggi per questo progetto:
- **Seriale virtuale**: XNU scrive i log del kernel su una UART 16550 emulata (`-serial file:xnu.log`, boot-args
  `debug=0x8 serial=3 -v keepsyms=1`): nessun bisogno di un header COM fisico.
- **Debug del kernel macOS**: gdbstub di QEMU (`-s`) + KDK Apple della build esatta + `lldb` (`gdb-remote
  localhost:1234`): breakpoint nel nostro kext, ispezione dopo un panic.
- **Traccia MMIO del nostro driver**: con `-device vfio-pci,host=03:00.0,x-no-mmap=true` ogni accesso ai BAR passa da
  QEMU ed è registrabile con i trace event `vfio_region_read/vfio_region_write` (lento: solo per le sessioni di
  traccia dell'init).
- **"Traccia d'oro" di Linux**: stessa configurazione ma con una VM **Linux** che carica `amdgpu` → si ottiene la
  sequenza degli accessi MMIO della CPU (BAR5, incluse le coppie indice/dato) fatti da Linux durante l'init di Navi 44,
  da confrontare riga per riga con quella del driver macOS. Restano escluse le scritture eseguite dai firmware o via
  pacchetti PM4/SDMA e i contenuti dei buffer in memoria (da salvare a parte, es. via debugfs nella VM). Lo **stato
  iniziale** va documentato: per la traccia del percorso "a freddo" la VM deve partire con la scheda mai toccata da
  `amdgpu` (solo GOP), altrimenti Linux esegue prima un mode1 reset (`soc24_need_reset_on_init`). Le scritture di
  `amdgpu_dm` (che ferma il DMCUB pre-OS e spegne le pipe) vanno escluse dal confronto finché il nostro display adotta
  il GOP. Nella VM Linux si possono leggere registri e VRAM via debugfs con rischio contenuto alla VM (con GFXOFF
  disattivato; un hang può comunque richiedere il reset della scheda o il riavvio dell'host).
- Un crash della VM non tocca i dischi reali; snapshot dei dischi della VM prima di ogni prova.
- **Due VM macOS**: una di **build** senza GPU (sorgenti e artefatti persistenti) e una di **test** con la GPU in
  passthrough e snapshot; kext e bundle si copiano dalla prima alla seconda (un rollback dopo un panic non deve far
  perdere il lavoro).

Note pratiche:
- macOS in VM su host AMD: progetto OSX-KVM (supporta Sequoia; per Tahoe va verificato), modello CPU tipo
  `Haswell-noTSX`/`Skylake-Client` con `vendor=GenuineIntel` (i macOS recenti richiedono AVX2). Nel guest: `AppleVTD`/IOMMU disattivato; verificare che l'IOPCIDevice riceva MSI
  attraverso lo switch PCIe interno della GPU. Che Tahoe giri bene in KVM su host AMD con passthrough non è ancora
  verificato: è il primo esperimento di M0 (Sequoia come ripiego per il solo bring-up del core).
- OVMF deve avere una finestra MMIO a 64 bit abbastanza grande per il BAR0
  (`-fw_cfg opt/ovmf/X-PciMmio64Mb,string=65536`). In alternativa ridurre il BAR0 prima del passthrough
  (`/sys/bus/pci/devices/0000:03:00.0/resource0_resize`, con la scheda non legata a nessun driver): utile anche perché
  Cobalt64 riporta che l'IOPCIFamily di Tahoe non dimensiona BAR oltre 1 GiB.
- **Disco della VM**: **mai** sulla radice btrfs di Linux (solo 35 GB liberi: riempirla può rendere Linux inutilizzabile).
  Usare fin da M0 il SSD dedicato a macOS (§13.3), assegnato alla VM come disco raw o in passthrough NVMe, così lo stesso
  disco serve poi per il bare metal; immagini, snapshot e tracce MMIO vanno lì o su un disco esterno.
- Monitor: oggi la RX 9060 XT è la scheda video primaria del BIOS (boot VGA) e Linux mette il framebuffer di sistema sul
  suo GOP, che occupa parte del BAR0. Per il passthrough impostare nel BIOS l'**iGPU come scheda primaria** (o disattivare
  il framebuffer di sistema sulla dGPU, es. `initcall_blacklist=sysfb_init`) e spostare il desktop Linux sulle uscite
  della scheda madre; un secondo monitor (o un secondo ingresso) sulla RX 9060 XT per la VM. Nella VM OVMF deve eseguire
  la option ROM UEFI della scheda (`rombar=1`, o `romfile` con la ROM completa: `research/hw_dump/vbios.rom` è
  probabilmente solo l'immagine ATOM) perché il GOP accenda il monitor. **I dati display dello stadio 0 vanno raccolti
  prima** di questo cambio (§19).
- Legare la dGPU a `vfio-pci` (`vfio-pci.ids=1002:7590,1002:ab40` o binding dinamico) è una modifica di sistema:
  va fatta consapevolmente, con una voce di boot di ripiego. **Non è stata fatta in questa analisi.**

### 13.3 Bare metal (dalla milestone M4-M5 in poi)

Serve per prestazioni reali, ReBAR completo, sleep/wake e test finali:
- **disco dedicato a macOS** (consigliato un SSD separato: il disco Linux ha solo 35 GB liberi e quello Windows va
  lasciato stare);
- OpenCore configurato per Ryzen 7 7700 / B840 (dettagli in §12);
- iGPU Raphael disattivata nel BIOS o ignorata (macOS non ha driver per lei e non deve contenderle il framebuffer);
  in sviluppo può fare da console di riserva (§12.2);
- BIOS: Above 4G Decoding ON, Resizable BAR ON (dimensione da decidere, §12), CSM OFF;
- **debug via seriale**: la scheda madre espone una **UART 16550A vera** (COM1, I/O `0x3F8`, IRQ 4, header **JCOM1**;
  verificato su Linux: `ttyS0` tipo 16550A, ACPI `PNP0501`), cioè proprio la porta che XNU usa di default. Serve un
  bracket DB9 per JCOM1 (livelli RS-232), un cavo o adattatore **null-modem** (DB9 femmina-femmina, TX/RX incrociati) e
  un adattatore USB-RS232 sul PC di appoggio (`picocom -b 115200`). Boot-args
  `debug=0x8 serial=3 -v keepsyms=1` (o `debug=0x108 serial=5 msgbuf=1048576` per i fallimenti precoci); `kprintf()`
  nel kext per tracce sincrone che sopravvivono ai panic. Lasciare la porta COM **abilitata** nel BIOS;
- **lldb remoto**: KDP via Ethernet richiede una NIC con supporto KDP (la RTL8125 con kext di terze parti
  probabilmente no; una Intel I210 dedicata probabilmente sì, da verificare il supporto KDP in modalità polled), oppure KDP su seriale tramite un proxy; per i casi difficili si torna
  nella VM con il gdbstub di QEMU;
- panic log in `/Library/Logs/DiagnosticReports` e, con OpenCore, anche sulla ESP.

### 13.4 Toolchain

- Kext e bundle Metal si compilano **su macOS** (Xcode o Command Line Tools; per i kext MacKernelSDK di acidanthera; il
  KDK della build scelta per i simboli). La VM macOS fa da host di build e da target di test; i sorgenti stanno in git
  sull'host Linux (cartella condivisa o push/pull).
- Mesa (RADV) per Darwin si compila su macOS con meson/ninja (come fanno Cobalt64 e NullMoth).
- Su Linux restano: sorgenti `amdgpu`/Mesa (già clonati in `research/src/`), i decoder e gli script di
  `research/tools/` e `research/artifacts/`, LLVM con target AMDGPU per assemblare gli shader di test
  (`llvm-mc -mcpu=gfx1200`), `umr` (da compilare, per letture di registri sulla GPU inizializzata da Linux, con cautela
  e GFXOFF disattivato), e la VM Linux per la traccia d'oro.
- Reverse engineering delle API private Apple (IOAcceleratorFamily2, Metal.framework, AppleGraphicsDeviceControl):
  Ghidra o IDA + `class-dump`/`ipsw` per estrarre classi, vtable e selettori dalla build scelta; script nostri che
  generano gli header (stesso approccio di `gen_virtuals.py` di NullMoth). **I firmware AMD non vanno mai
  disassemblati** (lo vieta la loro licenza, §17).

### 13.5 Strumenti da installare per iniziare

| Dove | Strumenti |
|---|---|
| Linux (host) | QEMU + OVMF (edk2) + OSX-KVM; Rust ≥ 1.98 (rustup) + `cargo-nextest` per metal2vulkan 0.2; header/loader Vulkan e validation layers; build di VK-GL-CTS (`deqp-vk`) per la baseline; `lldb`, `picocom`; Ghidra e `ipsw` per il reverse engineering delle API Apple; `umr` (da compilare). Già presenti: LLVM/clang 23 con target AMDGPU, ROCm/HIP, Mesa, vulkaninfo |
| macOS (VM di build) | **Xcode completo** con il Metal toolchain (le sole Command Line Tools non bastano per compilare `.metal`/metallib di test); KDK della build esatta; MacKernelSDK; Rust con target `x86_64-apple-darwin` (per `libm2v`); meson/ninja per Mesa |
| Hardware | SSD dedicato a macOS; bracket DB9 per JCOM1 + cavo null-modem + adattatore USB-RS232; eventualmente una NIC Intel I210 per KDP; un secondo monitor o un monitor con due ingressi |

---

## 14. Roadmap a milestone

Stime in settimane-uomo per uno sviluppatore esperto con l'hardware disponibile; per un progetto part-time
moltiplicare. Ogni milestone ha un criterio di uscita misurabile.

### M0 — Fondamenta (2-4 settimane)

- Scegliere e congelare la versione di macOS (§12) e la build esatta; scaricare il KDK corrispondente. Applicare le
  precauzioni di §12.4 prima di toccare BIOS e dischi.
- **Dati display (stadio 0, su Linux) — per primi**, finché la RX 9060 XT è ancora la scheda primaria e guidata da
  `amdgpu` (vedi punto dedicato più sotto).
- **Esperimento VFIO**: spostare il desktop Linux sull'iGPU, passare `03:00.0`/`03:00.1` a una VM Linux, avviare e
  fermare la VM 10 volte verificando che la scheda torni utilizzabile; scegliere il workaround per il reset. Misurare
  `C2PMSG_81` all'avvio della VM dopo un uso precedente della scheda: il solo riavvio della VM **non** resetta PSP/SMU.
  Provare subito anche l'avvio di Tahoe in KVM su host AMD.
- **Traccia d'oro**: nella VM Linux con `x-no-mmap=true`, registrare tutti gli accessi a BAR5 durante il caricamento
  di `amdgpu`; salvarla in `golden/` insieme a dmesg con `drm.debug`, `amdgpu_firmware_info`, MQD, ring, e una
  lettura delle regioni VRAM rilevanti (ring PSP, buffer comandi).
- Installare macOS nella VM (e preparare il disco per il bare metal); seriale e gdbstub funzionanti.
- Repository (§18), CI con test host (Linux e macOS), licenze e attribuzioni.
- Estrarre dalla build scelta (dal KDK e dal dyld shared cache) i binari di IOAcceleratorFamily2, IOGraphicsFamily,
  AppleGraphicsDeviceControl, Metal.framework e, come riferimento vivo, `AMDRadeonX6000.kext` +
  `AMDRadeonX6000MTLDriver.bundle`.
- **Dati display (stadio 0, su Linux)**: con i monitor accesi salvare le EDID (`/sys/class/drm/card1-*/edid`, non
  privilegiato) annotando quale monitor è su quale connettore; salvare il log DTN (`amdgpu_dm_dtn_log`) per ogni modo
  che si vuole supportare; avviare una volta Linux con `amdgpu` in blacklist e leggere in sola lettura lo stato lasciato
  dal GOP (registri OTG/HUBP/DIG, `DMCUB_REGION4_*`, `DMCUB_INBOX1_*`, `DMCUB_SCRATCH*`) e il ring DMCUB pre-OS in VRAM,
  con il monitor solo su DP e poi solo su HDMI. Nota: `modprobe.blacklist=amdgpu` disattiva anche l'iGPU Raphael (resta
  solo la console del framebuffer di sistema).
- Contattare gli autori di Cobalt64 (`ioaccel-layout`, coordinamento Navi 44).

**Uscita**: VM macOS che avvia con la RX 9060 XT assegnata e log seriale; traccia d'oro Linux salvata; dati display
raccolti; procedura di reset della scheda nota e ripetibile.

### L — Traccia parallela "traduzione Metal" su Linux (da M0 in poi, 3-6 settimane)

Indipendente dal kext, usa RADV su Linux con la stessa scheda:
- **L0**: revisione del codice di metal2vulkan 0.2 (codice di terzi), build, aggiunta del profilo RDNA4 RADV
  (`research/artifacts/metal-xlate/vkprofile_gpu0.json`) alla loro validazione, esecuzione dei test senza GPU e delle
  lane con GPU reale sulla RX 9060 XT; elenco delle "driver deviation" RDNA4 (lane simdgroup, NaN, denormali).
- **L1a** (da M0): estrarre staticamente i `.metallib` di sistema della build congelata (WindowServer/SkyLight,
  CoreDisplay, RenderBox, CoreImage, MPS) e tradurli/compilarli su Linux con RADV gfx1200.
- **L1b**: la cattura a runtime delle pipeline effettive (vertex descriptor, formati, function constants) richiede un Mac
  reale con GPU Metal sulla stessa build, oppure il nostro bundle caricato (dopo M5): un macOS senza device Metal non
  crea pipeline da catturare.
- In parallelo, estendere il prototipo AIR → LLVM AMDGPU (`research/artifacts/compute/scripts/air2amdgpu.py`) come
  oracolo per i kernel compute.

**Uscita**: 100% dei metallib di sistema tradotti e compilati per gfx1200 su Linux (o con fallback documentato); le
pipeline runtime di WindowServer solo dopo M5 o con un Mac reale.

### M1 — Kext core in sola lettura (1-2 settimane) → deliverable A1

- `RX9060Core.kext`: match `1002:7590`, mappa BAR0/BAR2/BAR5, legge la IP discovery (via BAR0 o `MM_INDEX`), costruisce
  la tabella delle basi, rimappa DMU 4.1.0→DCN 4.0.1, legge lo stato (`C2PMSG_81/35/33`, `BIOS_SCRATCH_7`,
  `MMMC_VM_FB_LOCATION_BASE/OFFSET`, `RCC_CONFIG_MEMSIZE`), **nessuna scrittura di stato**: le uniche scritture ammesse
  sono i registri indice dell'accesso indiretto (`MM_INDEX`/`MM_INDEX_HI`, `BIF_BX_PF0_RSMU_INDEX`), necessari se il BAR0
  è più piccolo della VRAM. Boot-arg `rx9060=1` obbligatorio,
  `-rx9060off` per spegnerlo.
- Profilo ASIC (Navi 44; voce Navi 48 per compatibilità futura).
- Test host dei parser usando i file di `research/hw_dump/` (discovery, VBIOS, header firmware).

**Uscita**: il log del kext coincide con `research/hw_dump/` e con `/sys/class/drm/card1/device/ip_discovery`.

### M2 — Bring-up hardware (5-10 settimane) → deliverable A2 e A3

Ordine e verifiche (checklist completa nel report 01 §6):
0. **Stato iniziale e reset** (prima del PSP): se `C2PMSG_81` ≠ 0, mode1 via debug mailbox SMU, attesa del bootloader
   PSP ed esecuzione della command table AtomBIOS `asic_init` (interprete minimo portato da `atom.c` /
   `amdgpu_atomfirmware.c`, MIT). Bring-up scritto come funzione rieseguibile: con il passthrough la scheda arriva
   normalmente già inizializzata, quindi questo passo serve da subito.
1. NBIF (doorbell, S2A, remap HDP) → confronto con traccia d'oro.
2. GMC/GART MMHUB, pagina scratch, writeback → test: lettura/scrittura via GART.
3. IH v7 con MSI → test: self-interrupt.
4. PSP: bootloader (KDB…SOS), ring KM, riserva FW (0x50/0x51), `LOAD_IP_FW` dei firmware necessari al bring-up (SMU,
   SDMA, RS64 PFP/ME/MEC + stack, MES/MES_KIQ, IMU, RLC → `AUTOLOAD_RLC`), **esclusi DMUB e VCN** finché il display
   adotta il GOP → test: `resp.status == 0` per ogni comando; sequenza identica alla traccia d'oro (al netto di DMUB/VCN).
5. SMU: Test, versioni, tabelle, poi `SetAllowedFeaturesMask` + `EnableAllSmuFeatures` (con il DPM della memoria escluso
   o UCLK bloccato finché la scanout è del GOP), quindi `GetRunningSmuFeatures` (0x54) per verificare che FAN_CONTROL,
   THROTTLERS e FW_CTF siano attivi; lettura periodica della temperatura dalla tabella metriche fin da qui → test:
   versione 0x00664700, feature attese attive. **Nessun carico prolungato finché queste verifiche non passano.**
6. GFX: attesa autoload RLC, golden, PC RS64, GART GFXHUB, `SH_MEM_*`, CSB, range doorbell.
7. MES (uni-MES): KIQ + scheduler, `SET_HW_RSRC`, `ADD_QUEUE` delle code kernel → test: **MQD e pacchetti MES
   byte per byte uguali** a `research/hw_dump/mqd` e `rings/` (a meno degli indirizzi). Va scelta una variante: i dump
   vengono dal kernel 7.2.9, che invia gli `ADD_QUEUE` delle code kernel sulla pipe KIQ, mentre il sorgente 7.3 li invia
   sulla pipe scheduler; la VM Linux "oracolo" deve usare lo stesso kernel dei dump di riferimento.
8. SDMA0 → test: copia VRAM↔GTT.
9. Ring test GFX/compute (`WRITE_DATA`, `RELEASE_MEM` + IRQ EOP), poi un compute shader gfx1200 che scrive un valore
   magico, poi i kernel già validati su Linux (`research/artifacts/compute/kernels/vadd_ir.hsaco`, che non richiede
   kernarg impliciti HSA, e i kernel derivati da AIR in `air_kernels.hsaco`) lanciati con PM4 `SET_SH_REG` +
   `DISPATCH_DIRECT` a partire dal loro kernel descriptor.
10. Recupero da hang: reset per coda via MES; in alternativa il percorso del passo 0 (mode1 + `asic_init` + bring-up).

**Uscita**: ring test + compute + SDMA + IRQ funzionanti; 20 avvii consecutivi della VM senza errori.

### M3 — User client + RADV su macOS (3-5 settimane) → deliverable A4

- ABI v1 (Appendice C): BO VRAM/GTT, `GEM_VA`, contesti, VMID per processo, `SUBMIT` sul ring GFX (poi compute),
  fence seqno + attesa, `QUERY_DEVICE` con valori reali.
- Mesa: backend Darwin (dalle patch Cobalt64, con info gfx1200 reali), build per macOS x86_64, test con mock, poi sul
  kext.
- Test: `vulkaninfo`; compute Vulkan semplici; un sottoinsieme della **Vulkan CTS** (`dEQP-VK.api.*`,
  `dEQP-VK.compute.*`, `dEQP-VK.memory.*`) confrontato con lo stesso sottoinsieme eseguito **oggi su Linux** con la
  stessa scheda (lista dei test attesi).

**Uscita**: `vulkaninfo` corretto su macOS; i test compute della CTS passano come su Linux.

### M4 — Display di base (3-6 settimane)

- `RX9060FB.kext` (`IOFramebuffer`, in Auxiliary KC): adotta la pipe accesa dal GOP (rileva quale OTG/HUBP/DIG è
  attivo), espone il modo corrente, flip della superficie via registri HUBP, VBL (interrupt DCN via IH o timer),
  EDID via AUX/DDC, cursore hardware, "claim" che ritira `IONDRVFramebuffer`, boot hold.
- Mappa dei connettori dal VBIOS (DP=PHY A, HDMI=PHY B/C).

**Uscita**: desktop macOS (ancora renderizzato dalla CPU) sul nostro framebuffer, flip sincronizzati al vblank, EDID
del monitor visibile nelle Impostazioni.

### M5 — Kext acceleratore + AGDC (4-8 settimane)

- `RX9060Accel.kext`: sottoclasse di `IOGraphicsAccelerator2` (i 17 metodi puri) con header ricostruiti per la build
  scelta; event machine, task/VA, memoria video/di sistema, risorse (IOSurface in memoria di sistema importate con userptr,
  modello A di §9.4, con copia nello scanout in VRAM), memory map, display machine e
  **display pipe con transazioni** (prima copia, poi flip zero-copy); `MetalPluginName` trattenuto finché il display
  non è armato; user client "carrier" per i processi sandboxed.
- `RX9060AGDC.kext`: risposte a `vendor info` (cmd 1) e `GPU capability` (0x980).

**Uscita**: `ioreg` mostra l'acceleratore; WindowServer usa le display pipe transactions (con copia).

### M6 — Bundle Metal e WindowServer (6-10 settimane)

- `RX9060Metal.bundle`: sottoclasse di `MTLIOAccelDevice` (shim ObjC), motore **metal2vulkan-runtime 0.2** sul
  `VkDevice` di RADV (con il solo traduttore + encoder nostri come ripiego), cache delle pipeline precompilata per
  WindowServer + traduzione asincrona con pipeline di fallback, allow-list per processo, rete di forwarding per le SPI
  private, IOSurface (modello A: userptr + copia nello scanout), wave32 per gli stadi `simd_*`, presentazione via
  display pipe, ordinamento con fence (all'inizio WindowServer attende il completamento GPU).
- Scala di test: `mtlprobe` (CLI) → esempi Metal semplici → Core Image → app nell'allow-list → **WindowServer**.

**Uscita**: desktop composto da WindowServer sulla GPU a 60 Hz su un monitor, stabile per un'ora.

### M7 — Robustezza e power management (continuo)

SMU completo (DPM, clock dinamici, GFXOFF), monitoraggio termico/ventole, reset per coda via MES, recupero completo
robusto (mode1 + `asic_init` + ricostruzione dello stato in VRAM), sleep/wake (all'inizio con veto, come RDNA4FB), log.

**Uscita**: un hang indotto viene recuperato senza riavvio (reset per coda, poi mode1 + `asic_init`); temperature e
ventole come su Linux sotto carico; sleep di sistema con veto funzionante.

### M8 — Display completo

Mode-setting nativo su tutti e tre i connettori, multi-monitor, HDMI 4K (TMDS 594 MHz con scrambling SCDC) e FRL, DSC,
poi HDR. Due strade: comandi DMUB (riusando il DMCUB pre-OS e la "ricetta" dei comandi lasciata dal GOP, poi il DMCUB
caricato via PSP) + programmazione registri (approccio Cobalt64/RDNA4FB), oppure port del **Display Core** di Linux
(dcn401 + DMUB service, licenza MIT) con uno strato `dm_services` per XNU, come fa AMD per Windows. Il calcolo di banda
DML 2.1 usa la virgola mobile e non può girare nel kext: tabelle catturate su Linux per i modi dell'utente, poi DML in un
demone user-space che passa i risultati al kext. Audio HDMI/DP (`03:00.1`): endpoint Azalia + AFMT/APG + DTO audio a
ogni modeset.

**Uscita**: tre monitor con modi da EDID, hotplug, 4K60 su HDMI con SCDC, audio HDMI.

### M9 — Compatibilità e prestazioni

Code compute + gang submit (task/mesh shader), DCC con PTE.D (ed eventuale eviction con decompressione SDMA), coda di
trasferimento SDMA, sparse/PRT, argument buffer tier 2, indirect command buffer, ray tracing (`VK_KHR_ray_query`),
profilazione; **IOSurface in VRAM (modello B) con flip zero-copy e fence per BO nel kext**; user queue MES (opzionali,
§5.3); Safari/WebKit, Chromium/Electron; eventualmente video VCN 5.0.

**Uscita**: Safari e Chromium con WebGL/WebGPU funzionanti; sottoinsiemi CTS sparse/compute come su Linux; nessuna
copia per frame verso lo scanout.

---

## 15. Strategia di test e verifica

| Livello | Cosa si testa | Come |
|---|---|---|
| Test host (senza GPU) | parser IP discovery/VBIOS/firmware, encoder PTE, costruttori di MQD, PM4 e pacchetti MES, piani BAR | funzioni pure in C/C++ con suite sul Mac e su Linux; **confronto byte per byte con i dump Linux** di `research/hw_dump/` (MQD, ring PM4, ring MES); "planted break" (mutare il sorgente e pretendere che i test falliscano), come Cobalt64 |
| Differenziale MMIO | sequenza di scritture del kext | diff tra la traccia QEMU del kext (VM macOS) e la traccia d'oro di `amdgpu` (VM Linux) |
| Hardware nel kext | ring, fence, IRQ, SDMA, compute, page fault voluti | verbi di self-test sul client di debug, attivati da boot-arg |
| Mesa/RADV | backend Darwin | mock in-process (CI senza GPU), poi Vulkan CTS su macOS confrontata con la CTS su Linux sulla stessa scheda |
| Traduzione Metal (su Linux) | AIR → SPIR-V → gfx1200, semantica Metal | validazione di metal2vulkan con il profilo RDNA4 sulla RX 9060 XT sotto Linux; corpus AIR reale di WindowServer/CoreImage tradotto e compilato; kernel compute eseguiti via HIP come oracolo (pipeline già funzionante per 3 kernel) |
| Replay | IB generati da RADV su Linux | catture con `RADV_DEBUG=hang`/`AMD_DEBUG` su Linux, rieseguite sul kext macOS: stesso output atteso |
| Display | modi, flip, vblank, EDID | CRC hardware DCN (`MPC_CRC_RESULT_*`, `DPP_CRC_VAL_*`) confrontati con i frame attesi, come fa Cobalt64 |
| Metal | API e shader | `mtlprobe`, esempi Apple, test di rendering con immagini di riferimento, census dei selettori non implementati |
| Stabilità | lunga durata | soak test (ore), loop di riavvio della VM, stress di allocazione VRAM |

Regola: **nessuna funzionalità entra senza un test** che la esercita e un confronto con Linux dove possibile.

---

## 16. Rischi e mitigazioni

| Rischio | Impatto | Probabilità | Mitigazione |
|---|---|---|---|
| Il PSP 14.0.2 rifiuta la sequenza (componenti sOS diversi da Navi 48, firmware, indirizzi) | blocca tutto | media | traccia d'oro di Linux, confronto comando per comando, lettura di `resp.status`; partire dalla sequenza Linux esatta |
| Reset bug della scheda in VFIO | rallenta lo sviluppo | alta | workaround (binding dinamico, suspend dell'host); in ultima istanza riavvio dell'host |
| "sOS già vivo" dopo warm reboot | il kext non riesce a inizializzare | media | rilevamento `C2PMSG_81` + mode1 via SMU fin da M2 |
| Layout privati di IOAcceleratorFamily2/Metal cambiano tra build | panic o crash di WindowServer | alta a ogni aggiornamento | versione di macOS congelata, header generati da script, `static_assert` sulle dimensioni, "layout gate" a runtime (fail-closed) |
| `ioaccel-layout` di Cobalt64 non disponibile | +4-10 settimane | media | ricostruzione con il metodo NullMoth; chiedere agli autori |
| Display specifico della scheda/monitor | schermo nero | media | partire dall'adozione della pipe GOP; mappa connettori dal VBIOS; modi da EDID; CRC |
| IOPCIFamily non accetta BAR0 da 16 GB (limite 1 GiB riportato su Tahoe) | VRAM non tutta visibile dalla CPU | media | BAR0 a 256 MB-1 GB (BIOS/OpenCore `ResizeAppleGpuBars`); il resto della VRAM come pool non mappato |
| Nessun reset leggero del GFX | ogni hang = riavvio | alta all'inizio | reset per coda MES, poi mode1 + `asic_init`; lavorare in VM |
| Info device errate verso RADV | hang del GPU | media | `QUERY_DEVICE` reale dal kext, mai valori canned di un'altra GPU |
| Sicurezza ridotta (SIP/AMFI) | rischio per l'utente | certa | documentarlo; installare solo su macOS dedicato; recovery |
| Licenze incompatibili mescolate | problemi di distribuzione | media | tenere separati i moduli LGPL (dylib), non copiare codice NC, attribuzioni (§17) |
| Aggiornamenti macOS (Tahoe è l'ultima per Intel) | rottura del driver | bassa dopo il congelamento | bloccare gli aggiornamenti automatici; ricostruire header per ogni build supportata |
| metal2vulkan 0.2 è "alpha" (API instabile, un solo autore, ~1,25 M righe Rust) | regressioni, manutenzione | media | fissare un commit e vendorizzarlo; tenere il ripiego "solo traduttore + encoder nostri"; contribuire il profilo RDNA4 a monte |
| DML 2.1 (calcolo watermark/DET) non eseguibile nel kernel | modi limitati | certa | tabelle catturate su Linux per i modi dell'utente; poi DML in user space |
| DMCUB pre-OS non riutilizzabile su Navi 44 o assente (nessun monitor all'avvio) | niente modeset nativo | media | stadio 1 che degrada con grazia; piano B: DMCUB caricato via PSP (obbligatorio comunque per lo S3) |
| Sleep di sistema (S3) | schermo nero al risveglio | alta finché manca il percorso completo | sleep disattivato fino a interprete AtomBIOS + PSP + DMCUB + modeset nativi |
| Latenza di traduzione degli shader al primo avvio di WindowServer | desktop con artefatti/pipeline di fallback | alta all'inizio | cache di pipeline precompilata per il nostro profilo, distribuita col bundle |
| Sincronizzazione tra processi assente nei progetti esistenti | sfarfallio, latenza | media | prima WindowServer sincrono, poi fence per BO nel kext |
| Messaggi SMU errati (power limit, overdrive, ventole) o SMU fermato con GPU sotto carico | rischio termico/hardware | bassa | solo il set minimo di messaggi usato da Linux (allowlist nel kext), mai overdrive/ventole/power limit; verifica di FAN_CONTROL/THROTTLERS/FW_CTF e controllo delle temperature durante i test (M2 punto 5) |
| macOS Tahoe non avviabile o instabile in VM KVM su host AMD con passthrough | blocca M0-M3 | media | provarlo come primo passo di M0; Sequoia come ripiego per il solo bring-up del core; piano B: bare metal con seriale COM1 |
| Modifiche a BIOS/dischi che compromettono Windows o Linux (BitLocker, CSM, ESP sovrascritta) | perdita di accesso ai sistemi esistenti | media se ignorato | precauzioni di §12.4 (backup, chiave BitLocker, OpenCore solo sulla ESP del disco macOS, dischi scollegati durante l'installazione) |
| Scope creep (video, RT, HDR…) | mai finire | alta | milestone con uscite misurabili; il resto in M9 |

---

## 17. Licenze e aspetti legali

| Componente | Licenza | Cosa comporta |
|---|---|---|
| Linux `amdgpu` (file usati: `gfx_v12_0.c`, `psp_v14_0.c`, `mes_v12_0.c`, `gmc_v12_0.c`, `amdgpu_discovery.c`, `discovery.h`, Display Core, …) | MIT/X11 ("Permission is hereby granted…", verificato negli header) | si può portare codice nel kext mantenendo le note di copyright |
| Mesa (RADV, ACO, addrlib) | MIT | idem; le patch Darwin restano MIT |
| Cobalt64 | MIT (radice), **BSD-3-Clause** (kext `src/navi48-bringup`), LGPL-3.0 (wrapper `n48xlate`) | riuso permesso con attribuzione; tenere separata la parte LGPL |
| RDNA4FB | BSD-3-Clause | idem |
| WhateverGreen | BSD-3-Clause | idem (solo se si prende codice) |
| 7000-macos (snapshot precedente di Cobalt64) | MIT (radice) / BSD-3 (kext) | idem |
| mac-amdgpu | MIT | idem |
| metal2vulkan | 0.1.x: **LGPL-3.0-or-later**; 0.2 (upstream attuale): **GPL-2.0-or-later OR LGPL-3.0-or-later** | usarlo sotto LGPL-3.0 come libreria dinamica sostituibile (`dlopen`), pubblicando le modifiche alla libreria |
| Trap handler CWSR gfx12 (`cwsr_trap_gfx12_hex`) | MIT (header di `cwsr_trap_handler.h`) | riusabile così com'è nel kext |
| NootRX / NootedRed | "ChefKiss Open Knowledge License v1": vieta le opere derivate e **qualsiasi uso con strumenti di IA**, compresi lettura, riassunto e analisi (§3 c) e l'uso di output derivati (§3 e) | **non** vanno letti né analizzati da agenti IA né usati. In questa analisi erano stati analizzati per errore: i cloni sono stati rimossi da `research/refs/` e il report 07 è stato riscritto senza i dettagli ricavati dal loro codice, che non vanno ricostruiti né riusati |
| NullMoth (plugin, kext, installer) | **PolyForm Noncommercial 1.0.0** | solo uso non commerciale; **non copiare codice** in un progetto che vuoi poter licenziare liberamente; architettura e procedure non sono protette |
| NullMoth patch NVK | file Mesa originali MIT; le parti scritte da NullMoth (es. `nvrm_xnu.c`) non hanno una licenza esplicita | considerarle PolyForm Noncommercial salvo conferma degli autori: riusare solo l'idea, non il codice |
| Firmware AMD (`linux-firmware`, `LICENSE.amdgpu`) | ridistribuzione in binario consentita con la nota di copyright; **vietati reverse engineering, decompilazione e disassemblaggio** | il kext carica i blob così come sono (da file o incorporati); si leggono solo gli header documentati in Linux |
| Software Apple | EULA Apple | non ridistribuire binari, shader o asset Apple (Cobalt64 li esclude di proposito: fare lo stesso); gli header ricostruiti si generano localmente dallo script. L'EULA vieta decompilazione e reverse engineering salvo quanto consentito dalla legge: in Italia/UE la decompilazione è ammessa per l'interoperabilità (art. 64-quater L. 633/1941, art. 6 Direttiva 2009/24/CE), limitata alle informazioni necessarie e non altrimenti disponibili; non pubblicare disassemblati o binari Apple, solo gli script. Nota: l'EULA di macOS non permette l'installazione su hardware non Apple; il progetto, come ogni Hackintosh, è per uso personale e di ricerca |

Suggerimento: codice del progetto sotto **MIT** (compatibile con tutto il resto), moduli LGPL in librerie separate,
file `NOTICE` con tutte le attribuzioni.

---

## 18. Struttura del repository proposta

```
rx9060xt_metal_driver/
├── PIANO_DRIVER_METAL_RX9060XT.md      questo documento
├── README.md                           panoramica e stato
├── LICENSE, NOTICE                     MIT + attribuzioni (amdgpu, Mesa, Cobalt64, RDNA4FB, mac-amdgpu, metal2vulkan)
├── kexts/
│   ├── RX9060Core/                     PCI, IP discovery, profilo ASIC, PSP/SMU/GMC/IH/GFX/MES/SDMA, user client
│   │   ├── src/amd/                    blocchi IP (da Cobalt64/Linux), header registri generati
│   │   ├── src/pure/                   funzioni pure testabili su host (parser, PTE, MQD, PM4, MES)
│   │   └── tests/
│   ├── RX9060FB/                       IOFramebuffer + claim, DCN 4.0.1, EDID, VBL, cursore
│   ├── RX9060Accel/                    IOGraphicsAccelerator2 e classi della famiglia
│   └── RX9060AGDC/                     shim AppleGraphicsDeviceControl
├── include/abi/                        ABI versionate kext↔kext e kext↔userspace (condivise con Mesa)
├── metal/
│   ├── RX9060Metal.bundle/             MTLIOAccelDevice e oggetti Metal su Vulkan
│   └── translator/                     wrapper del traduttore AIR→SPIR-V (LGPL, dylib separata)
├── mesa/                               patch del backend Darwin di RADV + commit Mesa di riferimento
├── firmware/README.md                  come ottenere i firmware Navi 44 da linux-firmware (non versionati)
├── tools/
│   ├── re/                             script che generano gli header delle API private Apple dalla build scelta
│   ├── trace/                          cattura e diff delle tracce MMIO (QEMU), decoder PM4/MES/MQD
│   ├── vm/                             script QEMU/VFIO per VM macOS e VM Linux "oracolo"
│   └── install/                        installer, Aux KC, recovery EFI
├── golden/                             dati di riferimento da Linux (tracce, dump) per i test
└── research/                           tutto il materiale di questa analisi (§21)
```

---

## 19. Prime azioni concrete

Nell'ordine, per le prime 3-6 settimane (M0 + M1):

1. **Decidere** le questioni di §20 (versione macOS, rapporto con Cobalt64, licenza).
2. **Precauzioni** di §12.4 (backup, BitLocker, profilo BIOS) e **acquisto del materiale** di §13.5 (SSD dedicato, cavo
   seriale null-modem).
3. **Raccogliere i dati display** finché la RX 9060 XT è ancora la scheda primaria guidata da `amdgpu`, con i monitor
   accesi: EDID per connettore, log DTN per modo, stato del GOP con `amdgpu` in blacklist (§14, M0).
4. **Eseguire su Linux** il sottoinsieme della Vulkan CTS che useremo in M3, per avere la lista dei test attesi;
   avviare la traccia L (metal2vulkan 0.2 con il profilo RDNA4 sulla scheda).
5. **Preparare la VM** sul SSD dedicato: iGPU come scheda primaria nel BIOS, desktop Linux sulle uscite della scheda
   madre, passthrough di `03:00.0`/`03:00.1` con una voce di boot di ripiego, ciclo avvio/arresto con una VM Linux e
   workaround per il reset; poi **registrare la traccia d'oro** di `amdgpu` nella VM Linux (BAR5 con `x-no-mmap=true`,
   partendo dalla scheda mai toccata da `amdgpu`), più dmesg con `drm.debug`.
6. **Installare macOS** nella VM (VM di build e VM di test), con log seriale e gdbstub; installare Xcode completo e il
   KDK della build.
7. **Creare lo scheletro del repository** (§18) con CI e i primi test host che usano `research/hw_dump/`.
8. **Scrivere `RX9060Core` in sola lettura** (M1) e confrontare il log con i dump di Linux.
9. **Scrivere agli autori di Cobalt64** (layout IOAcceleratorFamily2, supporto Navi 44).

---

## 20. Decisioni che spettano a te

1. **Versione di macOS**: Tahoe 26.x (allineata a Cobalt64, ultima release per Intel, SMBIOS MacPro7,1) oppure
   Sequoia 15.7.x (come NullMoth). Raccomandazione in §12.
2. **Rapporto con Cobalt64**: progetto separato che riusa il loro codice (opzione C) oppure contributo diretto del
   supporto Navi 44 al loro repository. Il secondo è il più rapido se gli autori sono disponibili.
3. **Licenza del progetto**: MIT consigliata. Se invece accetti un progetto **non commerciale** puoi riusare anche il
   codice NullMoth (plugin Metal, kext acceleratore), risparmiando tempo, ma con un vincolo permanente.
4. **Ambiente**: VM con VFIO (consigliata per il bring-up) e/o bare metal subito; disco dedicato per macOS.
5. **ABI kext↔RADV**: mantenere compatibile l'ABI "N48N" di Cobalt64 (riuso diretto delle 9 patch Mesa e possibile
   upstream in Cobalt64) oppure adottare l'ABI nuova dell'Appendice C (`QUERY_DEVICE` reale, capability, multi-ring)
   riscrivendo il trasporto delle patch. Una via di mezzo: tenere i selettori N48N 0-8 e 21 e aggiungere i nuovi in coda.
6. **Dimensione della ReBAR** su macOS: 256 MB (massima compatibilità), 1 GB (compromesso), 16 GB (da verificare con
   IOPCIFamily).

---

## 21. Materiale prodotto da questa analisi

| Percorso | Contenuto |
|---|---|
| `research/reports/01-linux-amdgpu-bringup.md` | bring-up Linux completo per GC 12.0.0: IP discovery, ordine di init, PSP/SMU/GMC/IH/GFX/MES/SDMA, formati firmware, doorbell, reset, differenze 12.0.0/12.0.1, checklist in 33 passi con indirizzi |
| `research/reports/02-linux-display-dcn401.md` | display DCN 4.0.1, DMUB, VBIOS, connettori, confronto con RDNA4FB/Cobalt64 |
| `research/reports/03-mesa-radv-aco-gfx12.md` | RADV/ACO su gfx1200, interfaccia kernel `ac_drm_*`, novità GFX12, patch Darwin di Cobalt64, ABI proposta |
| `research/reports/04-rocm-kfd-llvm-gfx1200.md` | amdkfd, mac-amdgpu, LLVM gfx1200, test HIP, AIR→AMDGPU diretto |
| `research/reports/05-cobalt64-deepdive.md` | analisi completa di Cobalt64 e 7000-macos, tabella di tutti i valori Navi 48 cablati con il valore Navi 44 |
| `research/reports/06-nvidia-macos-driver-deepdive.md` | come NullMoth rende una GPU di terze parti un device Metal: IOAccelerator, framebuffer, AGDC, plugin, NVK, installazione |
| `research/reports/07-apple-amd-stack-and-lilu.md` | stack AMD di Apple, NootRX/NootedRed, versioni macOS, OpenCore per Ryzen 7000/B840 |
| `research/reports/08-metal-translation-layer.md` | AIR, metal2vulkan, API Metal richieste da WindowServer, IOSurface e presentazione |
| `research/hw_dump/` | dump hardware della scheda (IP discovery, VBIOS, firmware, MQD, ring, power, display, `lspci -vvv`) + `README.md` |
| `research/tools/` | `decode_mqd.py`, `decode_pm4.py`, `decode_mes_ring.py` |
| `research/artifacts/` | script degli agenti (parser discovery/VBIOS/firmware/sOS, risolutore registri), dump `AMDGPU_INFO` (`gfx1200_canned_dump.txt`), vulkaninfo, `RADV_DEBUG=info`, encoding ISA gfx1200 vs gfx1201, risultati compute |
| `research/notes/amdgpu_sloc.txt` | dimensione del codice amdgpu per componente |
| `research/src/linux`, `research/src/mesa` | sorgenti di riferimento (clone sparse, ottobre 2026) |
| `research/refs/` | progetti di riferimento clonati (codice di terzi, solo lettura): nvidia-macos-driver, Cobalt64, 7000-macos, RDNA4FB, AMDRadeonRDNA4.kext, mac-amdgpu, metal2vulkan, WhateverGreen. NootRX e NootedRed sono stati rimossi per la loro licenza (§17) |

### 21.1 Test eseguiti durante l'analisi (tutti non distruttivi)

- Lettura di IP discovery, VBIOS, firmware info, configurazione GFX, power, MQD e ring via sysfs/debugfs (sola
  lettura, con `sudo` solo per debugfs); decodifica di MQD (`v12_gfx_mqd`, `v12_compute_mqd`), ring PM4 e pacchetti MES
  con gli script di `research/tools/`.
- Parsing della tabella IP discovery (checksum verificate), del VBIOS (tabelle dati, oggetti connettore) e degli
  header di tutti i firmware Navi 44 e Navi 48.
- Dump non privilegiato di tutte le query `AMDGPU_INFO` sul render node (nessuna allocazione, nessun submit).
- `vulkaninfo` completo, `RADV_DEBUG=info`, `AMD_DEBUG=info`, `glxinfo -B`.
- Assemblaggio con `llvm-mc` di istruzioni GFX12 per gfx1200 e gfx1201 (encoding identici) e confronto con gfx1030
  (RDNA 2): load/store/sample/wait incompatibili, a conferma che il compilatore Apple non serve.
- Compilazione per gfx1200 con clang 23 e rocm-llvm (OpenCL, IR LLVM, HIP; code object v4/v5/v6, generic), analisi di
  header ELF, note msgpack, kernel descriptor e ISA.
- `rocminfo` e topologia KFD; **vector-add HIP sulla RX 9060 XT: ~300 GB/s, 3,8 µs per lancio, nessun errore**.
- **AIR reale di Apple (Metal 4, AIR 2.8) letto da LLVM 23, abbassato a gfx1200 ed eseguito sulla scheda: 3 kernel su 3
  corretti.**
- Confronto dei requisiti di metal2vulkan con il profilo Vulkan misurato: 29/29 feature e 2/2 estensioni presenti.
- Parsing del firmware DMCUB e del VBIOS (object table, GPIO LUT, `dce_info`), calcolo degli indirizzi assoluti dei
  registri DCN per questa scheda.
- Inventario non privilegiato della piattaforma per OpenCore (PCI, USB, seriale COM1).
- Verifica dei gruppi IOMMU e di KVM per il passthrough.

---

## Appendice A: firmware Navi 44

File in `/usr/lib/firmware/amdgpu/` (linux-firmware 20260916, compressi `.zst`), versioni verificate sia negli header
sia in `amdgpu_firmware_info`. Ordine di caricamento via PSP: SMU per primo (fuori ciclo), poi l'ordine di
`enum AMDGPU_UCODE_ID` (SDMA, CP RS64 + stack, MES, IMU, RLC, RLC_G → `AUTOLOAD_RLC`, poi VCN e infine DMUB; questi
ultimi due esclusi finché il display adotta il GOP).

| File | Header | Versione | Contenuto | Caricamento (PSP `LOAD_IP_FW` fw_type) |
|---|---|---|---|---|
| `psp_14_0_2_sos.bin` | psp v2.0 | sOS 0x003b0f0d | KDB, SYS_DRV, SOS, SOC_DRV, INTF_DRV, DBG_DRV, TOC, IPKEYMGR_DRV, SPL (**niente RAS_DRV, RL**) | bootloader PSP (`C2PMSG_35/36`) |
| `psp_14_0_2_ta.bin` | ta v2.0 | ASD 0x21000118, HDCP 0x17000053, DTM 0x1200001f | trusted application | `LOAD_ASD` / `LOAD_TA` (opzionali per il minimo) |
| `smu_14_0_2.bin` | smc v2.0 | 0x00664700 (102.71.0) | PMFW 327 168 B, PPTable soft 5 812 B | `SMU` (18), per primo |
| `sdma_7_0_0.bin` | sdma v3.0 | 0x00798e96 | RS64 unico per SDMA0/1 | `SDMA_UCODE_TH0` (71) |
| `gc_12_0_0_pfp.bin` | gfx v2.0 (RS64) | 0xc76 (3190), feature 29 | ucode 92 512 B + stack 256 KiB, start 0x0007_0000_0000_3000 | `RS64_PFP` (87) + `P0_STACK` (90) |
| `gc_12_0_0_me.bin` | gfx v2.0 | 0xc12 (3090) | ucode 200 992 B + stack | `RS64_ME` (88) + (92) |
| `gc_12_0_0_mec.bin` | gfx v2.0 | 0xd7a (3450) | ucode 193 248 B + stack | `RS64_MEC` (89) + (94/95) |
| `gc_12_0_0_uni_mes.bin` | mes v1.0 | 0x93 | ucode 209 888 B + data 512 KiB; uc_start 0xFFFFFFFF_F0005000 | `CP_MES` (33) + `MES_STACK` (34), `CP_MES_KIQ` (81) + (82) |
| `gc_12_0_0_mes.bin` / `_mes1.bin` | mes v1.0 | 0x50 / 0xa1 | solo con uni-MES disattivato | — |
| `gc_12_0_0_imu.bin` | imu v1.0 | 0x0c2c2500 | IRAM 66 048 B + DRAM 66 048 B | `IMU_I` (68), `IMU_D` (69) |
| `gc_12_0_0_rlc.bin` | rlc v2.2 | 0x00bde160, feature 1000 | RLC_G, restore list GPM/SRM, IRAM, DRAM | (20), (21), `RLC_IRAM` (26), `RLC_DRAM_BOOT` (48), `RLC_G` (8) → **`AUTOLOAD_RLC`** (0x21) |
| `gc_12_0_0_toc.bin` | psp v1.0 | 0xb | TOC per autoload backdoor | non usato in modalità PSP |
| `dcn_4_0_1_dmcub.bin` | dmcub v1.0 | 0x0a004b00 | firmware del microcontroller display | `DMUB` (51) |
| `vcn_5_0_0.bin` | common v1.0 | 0x0910c01a | video | `VCN` (13), opzionale |

Il kext deve usare solo l'insieme Navi 44 (`gc_12_0_0_*`, `psp_14_0_2_*`, `smu_14_0_2`, `sdma_7_0_0`): quasi tutti i
binari Navi 48 differiscono anche a parità di versione e il PSP verifica le firme. Eccezioni: `gc_12_0_1_uni_mes.bin` e
`gc_12_0_1_toc.bin` sono identici byte per byte ai corrispondenti `gc_12_0_0_*` (in linux-firmware 20260916 sono symlink).

## Appendice B: registri chiave del bring-up

Indirizzi in **dword** dentro BAR5 (byte = dword × 4), calcolati con le basi della IP discovery di questa scheda
(report 01 §6). "SMN" = accesso indiretto via `BIF_BX_PF0_RSMU_INDEX/DATA` (dword 0x14/0x15).

| Funzione | Registro | Dword |
|---|---|---|
| Accesso indiretto VRAM | `MM_INDEX` / `MM_DATA` / `MM_INDEX_HI` | 0x0 / 0x1 / 0x6 |
| Dimensione VRAM (MB) | `RCC_DEV0_EPF0_RCC_CONFIG_MEMSIZE` | 0xde3 |
| Apertura doorbell | `RCC_DEV0_EPF0_RCC_DOORBELL_APER_EN` | 0xde0 |
| Remap HDP flush | `BIF_BX0_REMAP_HDP_MEM_FLUSH_CNTL` / `REG_FLUSH_CNTL` | 0xe4d / 0xe4e |
| HDP flush (ring) | `BIF_BX_PF0_GPU_HDP_FLUSH_REQ` / `_DONE` | 0xe26 / 0xe27 |
| Interrupt NBIF | `BIF_BX0_INTERRUPT_CNTL` / `_CNTL2` | 0xe11 / 0xe12 |
| Range doorbell S2A | `GDC_S2A0_S2A_DOORBELL_ENTRY_0..3_CTRL` | 0xeeb / 0xeec / 0xeed / 0xeee |
| Stato IFWI | `MP0_SMN_C2PMSG_33` (bit 31) | 0x16061 |
| PSP bootloader | `C2PMSG_35` (cmd/stato) / `C2PMSG_36` (indirizzo >> 20) | 0x16063 / 0x16064 |
| PSP ring KM | `C2PMSG_64` (ctrl) / `_67` (wptr) / `_69`, `_70` (ring lo/hi) / `_71` (size) | 0x16080 / 0x16083 / 0x16085, 0x16086 / 0x16087 |
| sOS vivo | `MPASP_SMN_C2PMSG_81` | 0x16091 |
| SMU mailbox | `MP1_SMN_C2PMSG_66` (msg) / `_82` (arg) / `_90` (resp) | 0x16282 / 0x16292 / 0x1629a |
| SMU debug mailbox (mode1) | `C2PMSG_75` (msg) / `_53` (param) / `_54` (resp) | 0x1628b / 0x16275 / 0x16276 |
| SMU firmware flags | `MP1_FIRMWARE_FLAGS` | SMN 0x03b00000 \| 0x3010024 |
| Posizione VRAM | `MMMC_VM_FB_LOCATION_BASE` / `_TOP` / `MMMC_VM_FB_OFFSET` | 0x1a554 / 0x1a555 / 0x1a4c7 |
| GART MMHUB | `MMVM_CONTEXT0_CNTL` / `_PAGE_TABLE_BASE_ADDR_LO32` / `_START_ADDR_LO32` | 0x1a564 / 0x1a5cf / 0x1a5ef |
| TLB MMHUB | `MMVM_INVALIDATE_ENG17_SEM/REQ/ACK` | 0x1a586 / 0x1a598 / 0x1a5aa |
| GART GFXHUB | `GCVM_L2_CNTL` / `GCVM_CONTEXT0_CNTL` / `_PAGE_TABLE_BASE_ADDR_LO32` | 0x2824 / 0x2884 / 0x28ef |
| TLB GFXHUB | `GCVM_INVALIDATE_ENG17_REQ/ACK` | 0x28b8 / 0x28ca |
| IH | `IH_RB_CNTL` / `RPTR` / `WPTR` / `BASE` / `BASE_HI` / `WPTR_ADDR_HI` / `WPTR_ADDR_LO` / `DOORBELL_RPTR` | 0x1120 … 0x1127 |
| Config GFX | `GB_ADDR_CONFIG` (= 0x08200545) | 0x263e |
| Stato CP / RLC | `CP_STAT` / `RLC_RLCS_BOOTLOAD_STATUS` | 0x21a0 / 0xee7c |
| Selezione GRBM | `GRBM_GFX_CNTL` / `GRBM_GFX_INDEX` | 0xa900 / 0xc200 |
| PC RS64 | `CP_PFP_PRGRM_CNTR_START` / `_HI`, `CP_ME_PRGRM_CNTR_START` / `_HI`, `CP_MEC_RS64_PRGRM_CNTR_START` / `_HI` | 0x30a4 / 0x30b9, 0x30a5 / 0x30d9, 0xc900 / 0xc938 |
| Memoria shader | `SH_MEM_CONFIG` / `SH_MEM_BASES` | 0xa9e4 / 0xa9e3 |
| CSB | `RLC_CSIB_ADDR_LO/HI/LENGTH` | 0xa987 / 0xa988 / 0xa989 |
| Range doorbell CP | `CP_RB_DOORBELL_RANGE_LOWER/UPPER`, `CP_MEC_DOORBELL_RANGE_LOWER/UPPER` | 0x305a/0x305b, 0x305c/0x305d |
| MES | `RLC_CP_SCHEDULERS` / `CP_MES_CNTL` / `CP_MES_PRGRM_CNTR_START(_HI)` / `CP_MES_GP3_LO` | 0xa98a / 0xc807 / 0xc800, 0xc89d / 0xc849 |
| Harvest CU | `CC_GC_SHADER_ARRAY_CONFIG` / `GC_USER_SHADER_ARRAY_CONFIG` | 0x226f / 0xfb90 |
| Inbox DMUB | `DMCUB_INBOX1_WPTR` | 0x3696 |

## Appendice C: ABI kernel-userspace proposta

User client del Core (aperto anche attraverso l'acceleratore per i processi sandboxed). Il sandbox di WindowServer e dei
processi GPU ammette `iokit-open` solo per classi `IOAccel*`: la classe va chiamata ad es. `IOAccelRX9060CoreClient`
(come `IOAccelNavi48NativeClient` di Cobalt64), oppure esposta solo tramite l'acceleratore. Le struct dovranno essere
**layout-identiche** ai gemelli `DRM_AMDGPU_*` (da imporre con `_Static_assert` sugli offset campo per campo, come fa
Cobalt64), per riusare il codice di RADV e i test Linux. **Nota**: questa numerazione non è compatibile con N48N 1.x di
Cobalt64 (QUERYINFO da 192 B al selettore 1, READREGS al 2, scanout 9-14, BO_IMPORT_HOST al 21): se si sceglie questa
ABI le patch Mesa 0002-0009 vanno adattate (decisione in §20).

| Sel. | Nome | Input → Output | Gemello DRM | Fase |
|---|---|---|---|---|
| 0 | `HELLO` | versione ABI client, flag → versione kernel, build, capability (compute, sdma, gang, prt, dcc, userptr, share) | `DRM_IOCTL_VERSION` | M3 |
| 1 | `QUERY_DEVICE` | → `drm_amdgpu_info_device` (448 B nell'header Mesa con cui compila RADV, 440 B nell'uapi di Linux 7.3-rc: stessi offset, cambia solo il padding; il kext copia `min(return_size, sizeof)` come `amdgpu_info_ioctl`) + 10 × `drm_amdgpu_info_hw_ip` + versioni firmware + `GB_ADDR_CONFIG` + layout VA | `AMDGPU_INFO` (`DEV_INFO`, `HW_IP_INFO`, `FW_VERSION`, `READ_MMR_REG`) | M3 |
| 2 | `QUERY_DYNAMIC` | → `drm_amdgpu_memory_info`, uso VRAM/GTT, timestamp GPU (100 MHz), sensori | `AMDGPU_INFO` (`MEMORY`, `VRAM_GTT`, `TIMESTAMP`, `SENSOR`) | M3 |
| 3 | `BO_CREATE` | `drm_amdgpu_gem_create_in` → handle, size, dominio | `GEM_CREATE` (0x00) | M3 |
| 4 | `BO_FREE` | handle | `GEM_CLOSE` | M3 |
| — | mapping CPU | `IOConnectMapMemory64(memoryType = handle)` | `GEM_MMAP` (0x01) + `mmap` | M3 |
| 5 | `GEM_VA` | `drm_amdgpu_gem_va` (MAP/UNMAP; poi CLEAR/REPLACE/PRT) | `GEM_VA` (0x08) | M3 / M9 |
| 6 | `CTX` | `union drm_amdgpu_ctx` (alloc/free/query reset) | `CTX` (0x02) | M3 |
| 7 | `SUBMIT` | header + N × `drm_amdgpu_cs_chunk_ib` + fence (handle, offset) → seqno | `CS` (0x04) | M3 (GFX), M9 (compute, gang) |
| 8 | `WAIT_SEQ` | (ip, ring, seqno, timeout) → stato | `WAIT_CS` (0x09) | M3 |
| 9 | `BO_WAIT_IDLE` | handle, timeout | `GEM_WAIT_IDLE` (0x07) | M3 |
| 10 | `BO_IMPORT_HOST` | VA utente, size, flag → handle | `GEM_USERPTR` (0x11) | M6 |
| 11 | `BO_SHARE` / `BO_OPEN` | handle ↔ id globale / IOSurface | `PRIME` | M6 |
| 12 | `BO_METADATA` | `drm_amdgpu_gem_metadata` | `GEM_METADATA` (0x06) | M9 |
| 13 | `READ_REGS` | offset, count (solo root, debug) | `READ_MMR_REG` | M2 |
| 14+ | scanout/present (debug, prima dell'acceleratore) | | — | M4 |

ABI interne kext↔kext (stile NullMoth): `callPlatformFunction` con struct versionate per allocare VRAM, mappare VA
GPU, condividere superfici, fare flip; ogni struct con campo `version` e rifiuto esplicito in caso di mismatch.

## Appendice D: fonti

Codice e documentazione locali: `research/src/linux` (torvalds/linux, 7.3-rc, 11/10/2026), `research/src/mesa` (mesa
main, 11/10/2026), `research/refs/*`.

Progetti:
- NullMoth, driver NVIDIA per macOS: <https://github.com/nullmoth/nvidia-macos-driver>
- Cobalt64: <https://github.com/Almosst-DEV/Cobalt64> — sito <https://cobalt64.com>
- 7000-macos: <https://github.com/twhippp/7000-macos>
- RDNA4FB / AMDRadeonRDNA4.kext: <https://github.com/somestupidgirl/RDNA4FB>, <https://github.com/RX4Darwin/AMDRadeonRDNA4.kext>
- mac-amdgpu: <https://github.com/lemonade-sdk/mac-amdgpu>
- metal2vulkan: <https://github.com/steelbrain/metal2vulkan>
- NootRX: <https://github.com/ChefKissInc/NootRX> (discussione RDNA 3: <https://github.com/ChefKissInc/NootRX/issues/144>)
- NootedRed: <https://github.com/ChefKissInc/NootedRed>; WhateverGreen: <https://github.com/acidanthera/WhateverGreen>
- Linux kernel: <https://github.com/torvalds/linux>; Mesa: <https://gitlab.freedesktop.org/mesa/mesa>
- OSX-KVM: <https://github.com/kholia/OSX-KVM>; OpenCore Install Guide: <https://dortania.github.io/OpenCore-Install-Guide/>

Articoli e discussioni (consultati direttamente via web durante l'analisi; i report citano le altre fonti):
- Notebookcheck, "New driver brings Nvidia GeForce RTX to Hackintosh": <https://www.notebookcheck.net/New-driver-brings-Nvidia-GeForce-RTX-to-Hackintosh.1420428.0.html>
- InsanelyMac, "Nvidia RTX 5060 Driver for Hackintosh (Sequoia)": <https://www.insanelymac.com/forum/topic/363320-nvidia-rtx-5060-driver-for-hackintosh-sequioa>
- Proxmox forum, reset bug delle Radeon in passthrough: <https://forum.proxmox.com/threads/amd-radeon-gpu-passthrough-infamous-reset-bug.186112/>
- Level1Techs, passthrough 9070 XT su kernel recenti: <https://forum.level1techs.com/t/9070xt-passthrough-on-latest-kernels-improvements/252915>
- AMD_Vanilla (patch kernel per CPU AMD): <https://github.com/AMD-OSX/AMD_Vanilla>
- OpenCorePkg, `Docs/Configuration.tex` (quirk ResizeGpuBars/ResizeAppleGpuBars, debug): <https://github.com/acidanthera/OpenCorePkg>
- OpenCore Legacy Patcher (inventario dei bundle AMD di Apple per versione): <https://github.com/dortania/OpenCore-Legacy-Patcher>
- XNU `osfmk/kern/debug.h` (boot-arg `debug=`): <https://github.com/apple-oss-distributions/xnu>
- Quarkslab, "An overview of macOS kernel debugging": <https://blog.quarkslab.com/an-overview-of-macos-kernel-debugging.html>
- 9to5Mac, "macOS 27 will drop support for these four Mac models" (18/05/2026) e pagina Apple di compatibilità di macOS 27
- Apple, Metal Feature Set Tables: <https://developer.apple.com/metal/feature-sets>
- WebKit, supporto argument buffer tier 1 in WebGPU: <https://bugs.webkit.org/show_bug.cgi?id=250123>
- Mozilla bug con i messaggi `MTLIOAccelDevice` di Metal.framework: <https://bugzilla.mozilla.org/show_bug.cgi?id=1701080>
- Skia Graphite, `MtlCaps.mm` (famiglie Metal e D24S8): <https://skia.googlesource.com/skia/+/chrome/m153/src/gpu/graphite/mtl/MtlCaps.mm>
