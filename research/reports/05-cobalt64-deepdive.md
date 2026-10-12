# 05 — Deep-dive su Cobalt64 (RDNA4 Navi 48 su macOS Tahoe) e sul fork 7000-macos

> Obiettivo: decidere se forkare/portare Cobalt64 su Navi 44 (RX 9060 XT, 1002:7590, GC 12.0.0) o ripartire da zero.
> Fonte: `research/refs/Cobalt64` (codice di terzi, NON fidato, solo letto) e `research/refs/7000-macos`.
> Legenda: **[VERIFICATO]** = letto nel codice / dato hardware / test eseguito; **[INFERITO]** = deduzione.

## 0. Sintesi esecutiva

- **Cos'è Cobalt64** **[VERIFICATO]**: snapshot pubblico (1 commit, 9 ott 2026) di un driver RDNA4 per macOS Tahoe 26.6.2 su x86_64/OpenCore, provato su **una** RX 9070 XT (Navi 48, `1002:7550`). Tre pezzi: (1) kext `Navi48Bringup` (IOService su `IOPCIDevice`, BSD-3) che porta su kernel x86 la scala di bring-up di `mac-amdgpu` (PSP 14 → SMU 14 → IMU/RLC/CP RS64 → MES 12 → GFX12 → SDMA 7), più un client "N48N" che imita le ioctl amdgpu DRM (GEM_CREATE/GEM_VA/CTX/CS/WAIT, userptr, scanout); (2) RADV portato su Darwin con 9 patch Mesa che parlano N48N; (3) un kext aux IOAccelerator + bundle Metal `Navi48Metal` (sottoclasse di `MTLIOAccelDevice`, modellata su `AppleParavirtGPU`) che esegue Metal sopra Vulkan, con shader AIR → metal2vulkan → SPIR-V → RADV/ACO. WindowServer compone il desktop su 3 display con questa rotta "nativa".
- **Rotta Apple** (hook in `AMDRadeonX6000` Navi 21, TTL sostitutiva, `xlat12` PM4 gfx10.3→gfx12, sostituzione shader): ~106 K righe di esperimento, mutuamente esclusiva con la rotta nativa, dipendente da asset Apple non distribuiti → **da scartare**.
- **Navi 44 è vicinissimo a Navi 48** **[VERIFICATO]**: stesse versioni di generazione di tutti i blocchi IP usati (GC 12.0.x, PSP/SMU 14.0.x, SDMA 7.0.x, MMHUB 4.1.0, NBIF 6.3.1, IH 7.0.0, DMU 4.1.0), basi registri DMU identiche (`0x12 0xc0 0x34c0 0x9000 0x2403c00`), offset dei registri cablati identici (PSP/SMU/NBIF/MMHUB), **stesso `GB_ADDR_CONFIG` 0x08200545**, stessa VRAM (16 GB, 16304 MiB visibili, stesso range MC), stessi formati header firmware; il container `psp_14_0_2_sos.bin` non ha RL né RAS_DRV ma il codice li salta.
- **Cosa cambia**: device id `0x7590`; 10 nomi firmware (`gc_12_0_0_*`, `psp_14_0_2_*`, `sdma_7_0_0`, `smu_14_0_2`); caps GFX cablate 4 SE → **2 SE** (32 CU, 8 RB); record canned Mesa `gfx1200` (non esiste: 2 SE, 32 CU, 8 RB, 128-bit, 16 TCC, L2 4 MB, MALL 32 MB, `external_rev 0x41`); stringhe "RX 9070 XT"; ReBAR da limitare a ≤1 GiB (oggi 16 GiB); **display**: mapping connettori della nostra Sapphire diverso (DP=PHY A, HDMI=PHY B/C, niente PHY D) e modi cablati per i monitor dello sviluppatore.
- **Bloccanti**: `tools/native/ioaccel-layout` (generatore del layout di IOAcceleratorFamily2) **non è nel repo** → il kext aux non compila; fragilità totale rispetto alla build macOS; nessun reset GPU.
- **Raccomandazione**: **fork selettivo della rotta nativa** (kext core + N48N + patch Mesa + aux/bundle Metal + dcn41), con profilo ASIC generico (idea di `7000-macos/asic_profile`, da estendere a firmware/caps/Mesa/display), chiedendo agli autori `ioaccel-layout` e possibilmente portando il supporto Navi 44 upstream. Stima: ~2-3 mesi-uomo per un desktop GPU su un display se si ottiene il layout, ~4-6 se va rifatto il RE; da zero 9-18 mesi-uomo.
- **7000-macos**: fork di uno snapshot più vecchio (0.0.621) che aggiunge solo `asic_profile` (identità + versioni attese, cross-check), tabella MMHUB per versione IP e un rilevamento read-only di Navi 33; firmware e caps restano cablati.

## 1. Struttura del repository, dimensioni, licenza, maturità

**[VERIFICATO]** Il repo `refs/Cobalt64` è un singolo commit git (`d6c9aed "README: drop the GPU badge"`, autore "Almosst", 9 ottobre 2026): è uno *snapshot* pubblico, non una storia di sviluppo. `CHANGES.md` lo dichiara "kext Navi48Bringup 0.0.664, Metal bundle revision 20, nove patch Mesa", cambiamenti rispetto allo snapshot precedente del 5 ottobre 2026. Il README lo etichetta *preview*: "Can I install this? Not yet".

Stato dichiarato (README.md "Status"): su UN PC x86_64 con UNA RX 9070 XT, macOS Tahoe 26.6.2 via OpenCore: desktop composto da WindowServer via Metal su tre display (1 DP + 2 HDMI), alcune app Apple (Maps, Preview, Photos, System Settings, Music) renderizzate sulla GPU, Resizable BAR. In corso: 4K su HDMI, frame pacing, Safari/Chromium/Electron, modi da EDID invece che fissi, decode video HW.

### 1.1 Componenti e dimensione (righe contate con `wc -l` su .c/.cpp/.h/.hpp/.m/.py/.sh)

| Percorso | Righe | File | Contenuto |
|---|---:|---:|---|
| `src/navi48-bringup/src` (totale) | 141 274 | 215 | kext principale `Navi48Bringup.kext` |
| ├ `src/amd` | 36 526 | 79 | porting dei blocchi IP amdgpu (psp_v14_0, smu_v14_0, gmc_v12_0, ih_v7_0, imu_v12_0, rlc_v12_0, cp_v12_0, mes_v12_1, sdma_v7_0, gfx_v12_0, nbif_v6_3_1) + "native" S1b/S1c (RADV backend lato kernel) |
| ├ `src/apple` | 79 674 | 98 | **rotta Apple**: hook dentro AMDRadeonX6000 (AppleHardwareHook.cpp da 2,4 MB da solo), TTL sostitutiva, decine di header "gfx_*" di esperimenti numerati |
| ├ `src/dcn` | 12 167 | 16 | display DCN 4.x nativo (navi48_dcn.cpp 204 KB, navi48_disp2.h 222 KB) |
| └ radice `src/` | ~13 000 | 22 | Navi48Bringup.cpp (8 971 righe, 540 KB), user client, nub Metal/Display, ABI |
| `src/navi48-bringup/tests` | 100 798 | 151 | test host (pure functions) + fixture "frozen" |
| `src/xlat12` | 26 206 | 35 | traduttore PM4/registri GFX10.3 → GFX12 (rotta Apple) |
| `src/dcn41` | 4 661 | 23 | layer registri DCN "4.1" generato + allowlist scritture |
| `src/shadercache`, `src/g2capture` | 1 213 | 5 | parser cache shader Apple; tool cattura record compilatore Apple |
| `tools/native/navi48metal` | 17 455 | 90 | bundle Metal (`Navi48Device.m` 6 293 righe) sopra Vulkan/RADV |
| `tools/native/navi48accel` | 3 225 | 21 | kext ausiliario IOAccelerator (Aux KC) |
| `tools/native/{autotranslate,mtlprobe}` | 4 314 | 13 | script AIR→SPIR-V, probe API Metal |
| `tools/pc`, `tools/conductor`, `tools/dcn41` | 18 750 | 119 | CLI di test lato PC (`navi48test.c` 314 KB), script run milestone M6, suite, mutation test |
| `third-party/metal2vulkan-n48` | 1 124 | 12 | wrapper LGPL `n48xlate` + patch a metal2vulkan (upstream NON incluso) |
| `mesa-patches/` | (9 patch, ~440 KB) | 9 | backend Darwin di RADV su Mesa `f5cb8ee032adabef599ae892ec4e42d796b84da9` (26.3.0-devel) |

### 1.2 Licenze **[VERIFICATO]**
- Radice: `LICENSE` MIT ("Copyright (c) 2026 Navi48-MacOS contributors").
- `src/navi48-bringup/LICENSE`: **BSD 3-Clause** ("the Navi48 project") — il kext ha una licenza diversa dal resto. `NOTICE`: `src/ipdiscovery.{hpp,cpp}` copiati verbatim da RDNA4FB (BSD-3), tecniche BAR5/MM_INDEX/discovery da RDNA4FB; sequenze IP (gfx/gmc/psp/smu/sdma/mes/ih) "derived from" lemonade-sdk/mac-amdgpu (MIT). Linux amdgpu dichiarato "solo come documentazione, nessun codice GPL copiato" (i file amdgpu sono in realtà per lo più MIT/X11, quindi il rischio è basso, ma i commenti citano righe di `gfx_v12_0.c` ecc.).
- `third-party/metal2vulkan-n48/`: LGPL-3.0 (wrapper `n48xlate`, caricato in-process dal bundle Metal tramite `n48_xlate.h`).
- Patch Mesa: MIT come Mesa.
- Firmware AMD: NON incluso (linux-firmware, licenza AMD), embedded nel kext al build.
- Esclusi deliberatamente (derivati da software Apple): `firmware/shadercache.bin`, 4 kernel blit gfx1201, fixture/catture IB Apple per i self-test di xlat12, `spvcache` (shader Apple tradotti), e — **[VERIFICATO]** — la directory `tools/native/ioaccel-layout/` (generatore di `IOAccelFamily2_decl.h`, `slots.json`, `forwarded.json` da disassemblato di IOAcceleratorFamily2) referenziata da `tools/native/navi48accel/Makefile:11,22,31`: **il kext ausiliario navi48accel non è compilabile dal repo così com'è**.

### 1.3 Maturità e qualità (giudizio) 
- **[VERIFICATO]** Codice estremamente "da laboratorio": ogni modifica è annotata col numero di build ("0.0.433 —", "MILESTONE 3 step 2 (0.0.239)", "Reviewer item 6"), riferimenti a "an internal design note", "notes/re/..." non pubblicati. Commenti lunghissimi (righe > 300 caratteri), centinaia di boot-arg (`navi48-*`), esperimenti numerati (`sk82`, `d84`, `cg84`, `tlb83`, `pf540`…) lasciati nel codice dietro switch.
- Punti positivi: molte decisioni sono isolate in header "pure" (`*_pure.h`) con test host e script di "planted break" (mutation test) — p.es. `src/navi48-bringup/src/amd/rebar_pure.h` (`plan_bar0`), `native_*_pure.h`, `tests/native_*_plant.sh`. Fail-closed sistematico (ogni verbo rifiuta su stato inatteso).
- Negativi: (1) monolite — `Navi48Bringup.cpp` 8 971 righe, `AppleHardwareHook.cpp` 2,4 MB; (2) due architetture sovrapposte (rotta Apple ~106 K righe tra `src/apple` + `xlat12`, rotta nativa); (3) build dipendente da parti non pubbliche (ioaccel-layout, shadercache, catture); (4) testato su un solo PC/una sola scheda; (5) molti valori Navi 48 cablati come costanti (Sez. 10).
- Sviluppo probabilmente molto assistito da agenti (stile dei commenti, "Rule 14", "review MUST-FIX 1-7") **[INFERITO]**.

## 2. Kext `src/navi48-bringup`: architettura

### 2.1 Bundle, personality IOKit, dipendenze **[VERIFICATO]** (`src/navi48-bringup/Info.plist`)
`CFBundleIdentifier com.navi48.bringup`, versione `0.0.664`, `OSBundleRequired Local-Root`, librerie `com.apple.iokit.IOPCIFamily 1.0`, `com.apple.kpi.{bsd,iokit,libkern,mach,unsupported} 20.0.0` (ABI minima macOS 11; build `-mmacosx-version-min`, `-mkernel -fapple-kext -std=c++17 -fno-exceptions -fno-rtti`, link `-lkmodc++ -lkmod` dal **MacKernelSDK preso da RDNA4FB** — `Makefile:103-110`). Il kext è iniettato da OpenCore dall'ESP ("ESP-injected: rebuilds are free", `Navi48MetalOps.h:2`), mentre il kext ausiliario `navi48accel` vive nell'Auxiliary Kernel Collection (ogni rebuild richiede il click "Allow" dell'utente).

Quattro personality, tutte con `IOPCIPrimaryMatch = "0x75501002 0x75511002"`:

| Personality | IOClass | IOMatchCategory | IOProbeScore | Ruolo |
|---|---|---|---:|---|
| `Navi48Bringup` | `Navi48Bringup` (nostro) | `Navi48Bringup` | 10000 | servizio principale su `IOPCIDevice` |
| `Navi48AccelPeer` | `Navi48AccelPeer` (nostro) | `ATIFramebuffer` | 5000 | finto "peer framebuffer" che risponde a `callPlatformFunction("SpecialAMDKey")` dell'acceleratore Apple |
| `Navi48AppleAccelExperiment` | `AMDRadeonX6000_AMDNavi21GraphicsAccelerator` (bundle `com.apple.kext.AMDRadeonX6000`, `IOPersonalityPublisher com.navi48.bringup`) | `IOAccelerator` | 100 | fa caricare l'acceleratore Apple Navi 21 sul nostro device id, solo se compare la proprietà `LoadAccelerator` (`IOPropertyMatch`) |
| `Navi48AppleHWServices` | `AMDRadeonX6000_AMDRadeonHWServicesNavi` (bundle `com.apple.kext.AMDRadeonX6000HWServices`) | `AMDRadeonX6000HWServices` | 65051 | carica HWServices Apple (fornisce la TTL che viene dirottata) |

Classi IOKit del kext (**[VERIFICATO]** grep `OSDefineMetaClassAndStructors`): `Navi48Bringup : IOService`, `Navi48UserClient : IOUserClient` (client di debug/test, tipo di default), `IOAccelNavi48NativeClient : IOUserClient` (client "N48N" per RADV), `Navi48MetalNub : IOService` (nub software su cui fa match il kext aux), `Navi48DisplayNub : IOService` (nub per `Navi48Framebuffer`, attaccato direttamente all'`IOPCIDevice` perché `IOAccelDisplayMachine::start` cerca il framebuffer solo due livelli sotto il provider), `Navi48AccelPeer : IOService`. In più `Navi48Ttl` (classe C++ che implementa la vtable della TTL Apple, `src/apple/Navi48Ttl.{hpp,cpp}`).

### 2.2 `probe()` / `start()` (`src/Navi48Bringup.cpp:7327-7495`)
- `probe`: richiede boot-arg `navi48bringup=1`, legge `configRead32(kIOPCIConfigVendorID)` e accetta **solo** `0x7550`/`0x7551` (righe 7334-7337) — doppio filtro oltre all'Info.plist.
- `start`: alloca lock globali; `latchPciBars()` (r. 90-119: censisce BAR0..5+ROM via `getDeviceMemoryWithRegister`, legge la capability ReBAR in config space); `mapRegisters()` (BAR5, `IODeviceMemory::map()`), `probeMemSize()` (legge `RCC_CONFIG_MEMSIZE` dal blocco NBIF via discovery, fallback `n48::kNbifMemsizeByteFallback`), `loadOnDieDiscovery()` (legge la tabella IP discovery dalla cima della VRAM — `vramMB<<20 - kDiscTmrOffset` — tramite la finestra indiretta `MM_INDEX/MM_INDEX_HI/MM_DATA`, r. 160-165, 486-503, poi `IpDiscovery::init` = codice RDNA4FB), `surveyIPs/PSP/SMU` (sola lettura), lettura boot-arg `navi48-stage=N`, `armInterrupts()` (MSI → `IOInterruptEventSource` su workloop proprio, default ON da 0.0.35), `stagePSP()` (solo con `navi48-psp=1` o `navi48-stage>=5`), `n48dcn::attach`, poi solo *flag* per gli esperimenti Apple (`navi48-accel-experiment`, `navi48-accel-gate`, `navi48-boot-chain`, `navi48-shader-cache`, `navi48-eop-bridge`), `registerService()`.
- Tutto ciò che scrive l'hardware è gated da boot-arg; per default il kext fa solo il survey.

### 2.3 Mappatura BAR e memoria
- **BAR5 (MMIO 512 KiB)**: mappata intera, accesso diretto `rmmio[off/4]`; accesso per IP via `regReadIp(hwId, inst, seg, dword)` che risolve la base da IP discovery (`Navi48Bringup.cpp:148-158`). I moduli `src/amd` usano `DeviceContext.ip` (tabella basi riempita da `amdgpu::fill_ip_base_table`).
- **BAR0 (VRAM)**: `mapVramAperture()` (r. 174-238) pianifica con `n48rebar::plan_bar0` (`src/amd/rebar_pure.h`) e mappa `kIOMapWriteCombineCache`. **Limite cruciale**: `kMaxBar0Map = 1 GiB` (`rebar_pure.h:20`, "Tahoe's IOPCIFamily cannot size a BAR above 1 GiB") e `plan_bar0` **rifiuta** (`kLenTooBig`, r. 85) una BAR0 più grande di 1 GiB. Quindi su macOS la ReBAR deve essere limitata (OpenCore `ResizeAppleGpuBars`/BIOS) a ≤1 GiB; con la nostra configurazione Linux attuale (BAR0 = 16 GiB) il kext rifiuterebbe. Sopra la finestra visibile esiste un "hi pool" di VRAM non mappata dalla CPU (`N48N_PLACED_HI_POOL`).
- Layout VRAM (bring-up): `vramBase` scelto sopra il framebuffer GOP (`captureBootFramebuffer()` via `PE_Video`/`getConsoleInfo`, r. 353-381; `chooseVramBase()` r. 383-422, `kBringupSpan = 32 MiB`, fallback 64 MiB); `apertureCheck` confronta scrittura BAR0 vs lettura MM_INDEX per provare che offset BAR0 == offset VRAM. Riserve in cima: `kVramHiTailReserve = 512 MiB` (TMR PSP a ~0x3f860_0000, discovery a ~0x3faff0000) + `kAppleArenaCarveReserve = 256 MiB` (`src/amd/amdgpu_gmc.h:60-63`). MC base da `MMHUB dword 0x0554` = `MMMC_VM_FB_LOCATION_BASE` (`buildDeviceContext`, r. 625-627: `vramMcBase = (fbBase & 0xFFFFFF) << 24`).
- **BAR2 (doorbell)**: mappata uncached (`mapDoorbells`, r. 255-280), con controllo che indirizzo IOPCIFamily == config space.
- **Memoria di sistema**: `amdgpu::sysmem_alloc` (`src/amd/amdgpu_sysmem.cpp`) = `IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task, kIOMemoryPhysicallyContiguous | kIOMemoryMapperNone, …)`: **fisicamente contigua, bypassa il mapper IOMMU** (presuppone VT-d/AMD-Vi disattivo o `DisableIoMapper`); il bus address è l'indirizzo fisico host, poi legato in GART (`gmc_bind_existing`). GART in VRAM.
- **VRAM allocator**: first-fit free-list (`src/amd/amdgpu_vram.h:56`), due pool (visibile BAR0 e hi).

### 2.4 Firmware
**[VERIFICATO]** Il firmware è **embedded nel binario** al build: `tools/embed-firmware.py` genera `src/fw/fw_<nome>.c` con `fw_<nome>[]`/`fw_<nome>_size` (`Makefile:21-24, 94-96`); `FW_REQUIRED` (`Makefile:27`) = `gc_12_0_1_{imu,me,mec,pfp,rlc,uni_mes}`, `psp_14_0_3_{sos,ta}`, `sdma_7_0_1`, `smu_14_0_3`. Tabella in `src/amd/fw_table.cpp:47-117` (simboli `extern` per ogni blob, `FwBlob{ptr,size,"nome",FwId}`); `gc_12_0_1_mes`/`mes1` sono voci nulle (si usa solo `uni_mes`), TOC non usato ("TOC is only loaded for psp_14_0_5", r. 95). Caricamento: bootloader PSP (`src/psp.cpp`) per i componenti pre-SOS dal container `psp_14_0_3_sos.bin` (KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV, DBG, RAS, IPKEYMGR poi SOS; commento "no SPDM_DRV: psp_14_0_3 ships none", r. 279), poi `LOAD_IP_FW` via ring GPCOM (`psp_v14_0.cpp`, `fw_loader.cpp`) per SMU, IMU, RLC, RS64 PFP/ME/MEC (+P0/P1 data), MES, SDMA. Nessun file su disco: cambiare ASIC = cambiare i simboli embedded.

### 2.5 Interrupt
MSI → `IOInterruptEventSource` (`armInterrupts`, r. 7257) → `handleInterrupt` (r. 7177) drena il ring IH v7.0 e classifica (src 181 = CP EOP, src 0 = UTCL2/VM fault). IH ring con `ENABLE_INTR=1, RPTR_REARM=1` solo se l'MSI è armato, altrimenti polling (`amdgpu_init.cpp:295-303`).

### 2.6 Nessun reset GPU
**[VERIFICATO]** `runStages` rifiuta di rieseguire la scala se la GPU è già stata provisionata in questo boot (commento `amdgpu_init.cpp:308-318`: rieseguire `LOAD_IP_FW` dell'SMU blocca il PSP). Non c'è mode-1/BACO reset: **ogni unload/reload del kext richiede un reboot**; anche il display (console GOP) resta sulla stessa GPU, e questo condiziona tutto il design (la scala gira "sotto" una console viva).

## 3. Sequenza di init hardware (PSP/SMU/GMC/IH/GFX/SDMA/MES) vs Linux

### 3.1 La scala `BringupStage` (`src/amd/amdgpu_init.h:33-52`, `amdgpu_init.cpp:287-766`)
Numerazione ereditata da mac-amdgpu; `navi48-stage=N` esegue fino a N:

| # | Stage | Implementazione | Note |
|---:|---|---|---|
| 1 | IPDiscovery | `ipdiscovery.cpp` (RDNA4FB, verbatim) | tabella letta on-die dalla cima VRAM |
| 2 | IHInit | `ih_init_full` (`ih_v7_0.cpp`) + `ensure_doorbell_path` (NBIF 6.3.1) | Linux fa NBIO/common prima |
| 3 | GMCInit | `gmc_init` (`gmc_v12_0.cpp`, MMHUB 4.1.0 + GFXHUB 12.0) | GART in VRAM |
| 4-8 | PSPInit / PSPLoadSOS / PSPRingCreate / TMRSetup / PSPFwLoad | `psp.cpp` (bootloader chain) + `psp_v14_0.cpp` (`psp_ring_create`, `psp_setup_tmr`, `psp_rl_load`, `psp_asd_initialize` non fatale "TA not ported", `psp_load_non_psp_fw`) | ordine Linux `psp_hw_start`: tmr_load → rl_load → asd |
| 9 | SMUInit | `smu_test_message`, `smu_get_version`, `smu_hw_init(full=navi48-smu-full)` | il setup completo (driver table, DcBtc, feature enable) è **opt-in**: per default l'SMU gira coi default PMFW/IFWI, nessun upload pptable |
| 10 | IMUInit | `imu_init_full` | sul percorso PSP il driver non scrive registri IMU, attende solo |
| 11 | RLCInit | `rlc_init_full` (CSB + attesa autoload) | |
| 12 | CPInit | `doorbell_init`, GART GFXHUB, cache RS64 dalle risposte `LOAD_IP_FW` (`tmr_fw_addr_by_type`), `cp_init_full` | |
| 13 | MESInit | `mes_init_full` (`mes_v12_1.cpp`, che però porta `mes_v12_0.c`) | `vmid_mask_{gfxhub,mmhub}=0xFE`, `gfx_hqd_mask[0]=0xFE`, `compute_hqd_mask=0xFC` (r. 1564-1594) |
| 14 | GFXInit | `gfx_constants_init` | caps **cablate** 4 SE / 2 SA / 8 CU / 4 RB-per-SE (Sez. 10) |
| 15 | SDMAInit | `sdma_v7_0.cpp` (implementazione che segue `sdma_v7_1.c`, tabelle registri scelte per versione GC) + self-test copia VRAM | |
| 16 | PM4Test | WRITE_DATA + EOP fence sul ring GFX | "nostro" |
| 17 | ComputeDispatch | shader gfx1201 `shaders/store_magic*.s` (bin pre-assemblati) scrive un valore | "Phase 3 finish line" |

Dopo lo stage 17, con `navi48-native=1`, `native_s1b.cpp` programma `GFXHUB CONTEXT8` (VMID 8, fuori dalla maschera MES 0xFE) con DEPTH 3 / BLOCK_SIZE 0 (4 livelli, come upstream) e fa un self-test (WRITE_DATA su VA bassi/alti, IB da VA alto, dispatch compute, un fault voluto): se passa (`S1B_POSITIVE`) il client N48N viene abilitato.

### 3.2 Fedeltà rispetto a Linux (giudizio) 
- **Ordine diverso**: Linux soc24 esegue `hw_init` nell'ordine dei blocchi: soc24_common (NBIO), gmc_v12_0, ih_v7_0, psp_v14_0 (che carica TUTTO il firmware incluso SMU), smu_v14_0, dm, gfx_v12_0 (RLC/IMU/CP), sdma_v7_0, vcn/jpeg, mes_v12_0. Cobalt fa IH prima di GMC e separa IMU/RLC/CP/MES/GFX in stage distinti; MES prima della configurazione GFX. Funziona su Navi 48 (provato), ma non è l'ordine di riferimento.
- **Omissioni [VERIFICATO]**: nessuna golden setting GC (`golden_settings_gc_12_0` in Linux `gfx_v12_0.c:259-261`: `DB_MEM_CONFIG 0x8000`; grep "golden" in `src/amd` = 0 risultati); SMU senza `SetDriverDramAddr`/pptable/feature enable per default; nessun clock/power gating (CG/PG); TA (ASD/HDCP/DTM/RAP/securedisplay) non portati; nessuna gestione RAS/ECC; nessun reset/recovery reale (solo `navi48-g1` sperimentale: MES RESET della coda legacy gfx).
- **Aggiunte**: tanti self-test (PDB0, SDMA queue1, SRBM_WRITE, "vmfrag"), quasi tutti per servire la rotta Apple.
- **Origine del codice**: i moduli `src/amd/*` sono port del dext DriverKit `lemonade-sdk/mac-amdgpu @3bdeed2` (R9700 / gfx1201 su Apple Silicon via TB5), adattati al kernel x86: niente DART → ogni buffer di sistema viene legato in GART (`mes_v12_1.cpp` deviazione 1, `sdma_v7_0.cpp` D2), PSP-load spostato in kernel (nessun userspace che carica firmware), alcune correzioni di BASE_IDX (`amdgpu_gfx.h:78-100`).

### 3.3 Cosa cambia per Navi 44 nella scala (da Linux) 
- PSP: `psp_v14_0.c:70-71` tratta 14.0.2 e 14.0.3 nello stesso ramo → stessi registri C2PMSG; serve `psp_14_0_2_sos.bin`/`psp_14_0_2_ta.bin` (il container può avere un insieme di sub-image diverso: il parser di Cobalt è generico per tipo, va verificato il log `parse: KDB … SOS …`).
- SMU: `smu_v14_0.c:181-182, 631-632` stesso ramo 14.0.2/14.0.3; unica differenza in `smu_v14_0_2_ppt.c:2112` (`enable_gfx_features` solo per 14.0.2, usato nel reset) e `:2175` (energy accumulator solo 14.0.3). Mailbox MP1 `C2PMSG_66/82/90` identica (stesso header `mp_14_0_2_offset.h`). Firmware `smu_14_0_2.bin` (nostro: SMC 102.71.0, driver_if 0x2e).
- GC: Linux usa gli stessi rami per 12.0.0 e 12.0.1 quasi ovunque (`gfx_v12_0.c:959,1416,1436,1452,1561,3679,4142,4381`, `imu_v12_0.c:376`, `gmc_v12_0.c:623,832`). Differenze reali: `soc24.c:349-389` (`external_rev_id = rev_id + 0x40` per 12.0.0 vs `+0x50`; pg_flags 12.0.1 ha in più `JPEG_DPG`), `gmc_v12_0.c:900` (client IH dell'interrupt ECC DF: `SOC21_IH_CLIENTID_DF` per 12.0.0), golden `rev0` solo se `rev_id==0` (il nostro `rev_id` = 1, `hw_dump/README.md:38`). Firmware `gc_12_0_0_*` (senza varianti `_kicker`: in Linux `amdgpu_ucode.c:33-36` il kicker riguarda solo 0x744B e 0x7551 rev 0xC8).
- SDMA 7.0.0 vs 7.0.1: `sdma_v7_0.c:1355-1356` stesso ramo; firmware `sdma_7_0_0.bin`.
- MES: `mes_v12_0.c:36-41` stessi nomi con prefisso `gc_12_0_0_`.
- **[VERIFICATO]** `GB_ADDR_CONFIG`: Cobalt documenta `0x08200545` letto sulla 9070 XT (`amdgpu_gfx.h:85-86`); il nostro dump Navi 44 dà lo **stesso valore** `0x08200545` (`hw_dump/README.md:36`). Quindi i parametri di swizzle (pipes, pkrs, interleave) coincidono; cambiano SE/CU/RB, che Linux prende dalla tabella discovery `gc_info`, non da GB_ADDR_CONFIG.

## 4. API user client N48N (selettori e struct)

### 4.1 Trasporto e controllo d'accesso **[VERIFICATO]**
- Header unico condiviso kext/Mesa: `src/navi48-bringup/src/Navi48NativeABI.h` (Mesa ne tiene una copia; devono avere la stessa ABI, oggi 1.11+). `N48N_UC_TYPE = 0x4E34384E` ('N48N'), `N48N_ABI_VERSION 1` (major), `N48N_ABI_MINOR 12`. Apertura: `IOServiceOpen(svc, task, 'N48N', &conn)` sul servizio `Navi48Bringup` **oppure** (ABI Metal 3, rotta "G6") sull'`IOAccelerator` del kext aux, il cui `newUserClient` (slot vtable 239) inoltra l'apertura al kext principale via `native_open` → così anche processi sandboxed possono aprirlo.
- Classe `IOAccelNavi48NativeClient` (`Navi48NativeClient.cpp`): `externalMethod` con controllo esatto della "forma" (numero scalari in/out, dimensioni struct, r. 148-151), nessun descrittore di memoria per le struct (solo inband). Ruoli: amministratore (tutti i selettori), utente uid 88 = `_windowserver` (selettori 0..14 e 21), "APP" (solo 0,1,3..8,21) ammesso da una allow-list per nome processo (`Navi48AppKey.h`: FNV-1a 60 bit di `proc_name()`, dichiaratamente "non un confine di sicurezza"); via route acceleratore solo il set APP.
- Limiti: `N48N_MAX_IBS 64`, `N48N_MAX_BOS 4096`, `N48N_MAX_CTX 64`, `N48N_FENCE_SLOTS 16`, wait max 2 s; cap GTT 512 MiB per client, import host 64 MiB per BO / 4 GiB per client; budget VRAM per sessioni non-WindowServer = 25 % dei pool.

### 4.2 Selettori

| Sel | Nome | Input | Output | Equivalente amdgpu DRM |
|---:|---|---|---|---|
| 0 | `HELLO` | scalari [client ABI=1, flags (bit 8 = riporta minor)] | [kernel ABI(|minor<<16), kext build, max IBs, vmid] | — |
| 1 | `QUERYINFO` | — | struct `n48n_info` 192 B | `AMDGPU_INFO` (sottoinsieme) |
| 2 | `READREGS` | [dword assoluto, count 1..16, instance] | `uint32_t[count]` | `AMDGPU_INFO_READ_MMR_REG` |
| 3 | `BOCREATE` | struct `n48n_gem_create_in` 32 B {bo_size, alignment, domains, domain_flags} | [handle, size, dominio, placed bits] | `DRM_AMDGPU_GEM_CREATE` |
| 4 | `BOFREE` | [handle] | — | `GEM_CLOSE` |
| 5 | `GEMVA` | struct `n48n_gem_va` 64 B (= `drm_amdgpu_gem_va`) | — | `DRM_AMDGPU_GEM_VA` (MAP/UNMAP; CLEAR/REPLACE non supportati) |
| 6 | `CTX` | struct `n48n_ctx` 16 B {op, flags, ctx_id, priority} | stessa struct | `DRM_AMDGPU_CTX` (ALLOC/FREE/QUERY_STATE2) |
| 7 | `SUBMIT` | struct `n48n_cs_in` 32 B + `num_ibs` × `n48n_cs_ib` 32 B (= `drm_amdgpu_cs_chunk_ib`) + fence (handle, offset) | [seqno] | `DRM_AMDGPU_CS` |
| 8 | `WAITSEQ` | [seqno, timeout ns, ctx] | [busy, retired, emitted] | `WAIT_CS` |
| 9-14 | `SCAN_QUERY/ACQUIRE/REGISTER/PRESENT/STATUS/RELEASE` (ABI 1.1) | `n48n_scan_query` 96 B, `n48n_scan_reg` 32 B, `n48n_scan_status` 256 B | slot/MC/present id/frame | scanout nativo su HUBP0/OTG0: flip di un BO VRAM visibile, ARGB8888 lineare, pitch/size = piano corrente, 3 slot |
| 15 | `DAL_STEP` (1.2) | [step E1b..E4] | `n48n_dal_result` 256 B | esperimento DISPCLK/DPPCLK via SMU (`smu_dal.cpp`) |
| 16 | `MODE_TRIAL` (1.3) | [row, dwell ms, flags] | `n48n_mode_result` 512 B | prova di modo (resync, vtotal, 50, 120 Hz) |
| 17-18 | `MODE_HOLD` / `MODE_RELEASE` (1.7) | | `n48n_mode_result` | |
| 19-20 | `METAL_NUB_PUBLISH` / `WITHDRAW` (1.8) | [flags] | [stato, registry id, `N48_METAL_ABI`, sizeof ops] | pubblica `Navi48MetalNub` (richiede `navi48-metal=1`, S1b positivo, GPU non HUNG) |
| 21 | `BO_IMPORT_HOST` (1.9) | [VA host 4K-aligned, size ≤64 MiB, flags, gpu VA] | [handle, size, GPU VA, placed] | userptr (`AMDGPU_GEM_USERPTR`): pagine del chiamante cablate e mappate SYSTEM|SNOOPED nel VMID |
| 22-26 | `SCANX_ACQUIRE/REGISTER/PRESENT/STATUS/RELEASE` (1.11/1.12) | [instance 2 o 1, …] | | scanout display 2 e 3 (HUBP1/OTG1 ecc.), "M6" multi-display |

Flag (`Navi48NativeABI.h:91-148`): domini GEM identici a amdgpu (`CPU 1, GTT 2, VRAM 4, GDS 8, GWS 0x10, OA 0x20, DOORBELL 0x40`), flag GEM con gli stessi bit di `AMDGPU_GEM_CREATE_*` (alcuni rifiutati: `CP_MQD_GFX9`, `ENCRYPTED`, `PREEMPTIBLE`; `GFX12_DCC` ignorato: "no DCC PTE bit in S1c" → **niente DCC/compressione**), MTYPE `NC/WC/CC/UC/RW`, solo `N48N_HW_IP_GFX = 0`.

### 4.3 Semantica del backend (`src/amd/native_s1c.cpp`) **[VERIFICATO]**
- **Una sola coda hardware**: tutte le submission di tutti i client vanno sul *kernel GFX ring* (KGQ, pipe 0 queue 0, mappato da MES) in ordine; fence = seqno scritto con RELEASE_MEM nel CP write-back page (`kCPWBOffsetNativeSeq`). Niente code compute/SDMA esposte a RADV, niente user queue, niente preemption.
- VM per client: VMID 8 (multi-sessione sperimentale `navi48-multisession=1`: VMID 8..11), albero a 4 livelli proprio in VRAM, `CONTEXT8 BASE/START/END` programmati all'open, flush TLB con `gmc_flush_gpu_tlb`. VA bassi `0x10000..0x7FFFFFFFFFFF`, alti `0xFFFF800000000000..` (stessa convenzione amdgpu).
- Recupero hang: latch "HUNG" sticky (proprietà `Navi48,Ready=0`), recupero G1 opzionale.
- **Implicazione per noi**: N48N è di fatto un "mini-amdgpu DRM" su IOUserClient, pensato per riusare `src/amd/vulkan/winsys/amdgpu` di RADV con poche modifiche. È riutilizzabile così com'è per Navi 44: nulla nell'ABI è specifico di Navi 48 (gc_version e GB_ADDR_CONFIG sono letti dal vivo in `n48n_info`).

### 4.4 Client di debug `Navi48UserClient` (`Navi48UserClientABI.h:20-62`)
Selettori 0-18: `GetInfo, AllocVRAM, FreeVRAM, WriteVRAM, ReadVRAM, SubmitIB, WaitFence, RegRead, SelfTest, GetCounters, ReadLog, Metrics (telemetria PMFW), PowerState, AccelExperiment (13: il "verbo" con >100 azioni usato da `navi48test accel …`), LogReset, LogConsume, ReadCap, CapConsume, ReadScanFull`. È l'interfaccia di laboratorio usata da `tools/pc/navi48test.c` (314 KB).

## 5. Hook nell'acceleratore Apple AMDRadeonX6000 e `src/xlat12` ("rotta Apple")

Cobalt64 contiene **due architetture** mutuamente esclusive per boot (**[VERIFICATO]** `src/amd/native_s1b_pure.h:155-169`: `gate_conflicts` rifiuta la rotta nativa se è armato uno qualsiasi tra `accelExperiment`, `bootChain`, `sdmaQ1/Qn`, `srbm`, `vmfrag`, `eopBridge`, `shaderCache`).

### 5.1 Cosa carica e cosa patcha **[VERIFICATO]**
- Kext Apple caricati tramite personality "pubblicate" dal nostro Info.plist (Sez. 2.1): `com.apple.kext.AMDRadeonX6000` (classe `AMDRadeonX6000_AMDNavi21GraphicsAccelerator`) e `com.apple.kext.AMDRadeonX6000HWServices` (`AMDRadeonX6000_AMDRadeonHWServicesNavi`). L'acceleratore fa match solo quando il nostro kext pubblica `LoadAccelerator` (`IOPropertyMatch`), cosa che avviene **solo su comando** dal user client (`navi48test accel fire`, `accelExperiment()`, `Navi48Bringup.cpp:7497`), mai al boot (un panic al boot si ripeterebbe a ogni avvio).
- **TTL sostitutiva** (`src/apple/Navi48Ttl.{hpp,cpp}`, `AmdTtlServicesABI.h`): la libreria Apple `AmdTtlServices` (AMDRadeonX6000HWLibs) si ferma a Navi 23 ("device table has no entry past 0x73FF", niente MES). Il kext ridirige `HWServices::getTtl()` sul proprio oggetto `Navi48Ttl`, che implementa i 16 metodi dell'interfaccia (initialize, queryHwBlockRegisterBase da IP discovery, getLocalMemoryInfo che riporta `reservedHiOffset = vramSize - kVramHiTailReserve`, …) usando il `BringupContext` della scala Linux-like.
- **Patch di vtable a runtime** (`src/apple/AppleHardwareHook.cpp`, 2,4 MB): dall'`RTHardware` (ottenuto da `pGmmCallbacks->context` in `TTL::initialize`) si agganciano slot della vtable (`AMDRadeonX6000_AMDHWGart::flushAndInvalidateCaches` → `GFX10Hardware::flushHDPCache` slot 0x1f0, `GFX10VMM::programAndInvalidateVM` 0x238 via accessor slot 93, `setMemoryAllocationsEnabled` slot 78, `appendToReservedVRAMOffset` slot 48 …) perché il codice Apple scrive registri a offset GFX10 e attende ACK che su GFX12 non arrivano mai (hang totale documentato al build 0.0.52). Tutte le scritture MMIO di Apple vengono **bloccate** (`hw_hook_reg_writes`), le page table Apple vengono rispecchiate in PTE GFX12, l'indirizzamento VRAM 0-based di Apple viene coperto con un PDB0 alias in VMID 0 ("option B'", `amdgpu_gmc.h` dopo r. 64), le submission SDMA vengono "drenate" e tradotte prima del doorbell (`sdma_drain_xlat.h`), le EOP IH vengono riportate al retire Apple (`navi48-eop-bridge`). `Navi48AccelPeer` (`IOMatchCategory ATIFramebuffer`) esiste solo per rispondere a `callPlatformFunction("SpecialAMDKey", waitForFunction=true)` che altrimenti blocca per sempre (`Navi48AccelPeer.hpp:1-30`).
- **xlat12** (`src/xlat12/xlat12.h:1-40`, `xlat12.c`, `xlat12_ib.c` 400 KB, `xlat12_tables.h` generata da Mesa `gfx103.json`/`gfx12.json`): traduttore PM4 **gfx10.3 → gfx12** registro per registro: classi `identical / moved / field_repack / absent / reused / legacy_vs / unknown`; regola NGG (gfx12 ha solo NGG: pipeline VS legacy rifiutate); `LOAD_*_REG`/`CLEAR_STATE` rifiutati (stub); split dei run `SET_*_REG` quando gli indirizzi gfx12 non sono contigui. Riconosce IB specifici di WindowServer (`xlat12_shader_ids.h`, `xlat12_dtable_rows.inc` generato da `tools/auto-ws/emit_ws.py`, non pubblicato).
- **Shader**: il compilatore Apple (libSC in `AMDRadeonX6000MTLDriver`) produce ISA **gfx10.3**, non eseguibile su gfx12. La rotta Apple quindi sostituisce gli shader al momento della copia di residenza con binari gfx1201 precompilati, indicizzati per hash (`src/shadercache/shadercache.h`, blob `firmware/shadercache.bin` NON pubblicato, 4 kernel blit gfx1201 NON pubblicati); `src/g2capture/g2capture.m` cattura i container shader Apple swizzlando `-[GFX10_GfxMtlFunctionVariant initWithCompilerOutput:…]` a indirizzo fisso (`0x7ffb11191a7a`, macOS 26.6.2 build 25G83).

### 5.2 Perché esiste e come convive con RADV
- Era la "Phase 4 / Milestone 2-3": misurare quanto il codice Apple *generation-agnostic* dell'acceleratore (92 delle sue 131 classi, commento `Navi48Bringup.cpp:7385-7400`) arriva su GFX12, per far girare WindowServer col driver Metal **di Apple**. Ha richiesto ~106 K righe (`src/apple` + `xlat12`) e funziona solo per un insieme chiuso di shader/IB catturati (quelli di SkyLight/WindowServer).
- **Non convive** con la rotta nativa nello stesso boot (gate sopra). Il desktop GPU attuale (README "Status") gira sulla **rotta nativa**: WindowServer usa il bundle `Navi48Metal` su RADV (CHANGES.md: fix "WindowServer import-memory exhaustion" nel bundle Metal). BUILDING.md lo conferma: shadercache e kernel blit "serve the older route … The native route (Mesa RADV plus the Metal bundle in tools/native) does not use them".
- **Raccomandazione per Navi 44**: la rotta Apple va **scartata** in un fork: è legata byte per byte a una build di macOS (offset vtable, indirizzi nel dyld shared cache), richiede asset derivati da Apple non distribuibili e non scala oltre gli shader catturati. I pochi pezzi riusabili sono l'idea del "peer" `SpecialAMDKey` (non serve senza acceleratore Apple) e le tabelle registri gfx10.3→gfx12 (utile solo come riferimento).

## 6. Bundle Metal `tools/native/navi48metal` (+ kext aux `navi48accel`)

### 6.1 Come si registra come device Metal **[VERIFICATO]**
1. Il kext principale pubblica su richiesta (`N48N_SEL_METAL_NUB_PUBLISH`, boot-arg `navi48-metal=1`, S1b positivo) un `Navi48MetalNub : IOService` (`Navi48MetalNub.hpp:1-12`), che risponde a `callPlatformFunction("n48.metal.ops")` con una tabella di funzioni versionata e append-only (`Navi48MetalOps.h`: magic `'N48O'`, `N48_METAL_ABI 3`, `kCfgBytes 0x90`, hook `populate_config`, `vhook`, `mm_hook`, `disp_hook`, `native_open`, factory mask `N48_FACT_*`).
2. Il kext aux `com.navi48.accelprobe` 0.0.7 (`tools/native/navi48accel/Info.plist`) fa match su `IOProviderClass Navi48MetalNub`, `IOMatchCategory IOAccelerator`, `IOProbeScore 1000`, classe `Navi48Accelerator`, e la personality porta le chiavi **`MetalPluginName = Navi48Metal`** e **`MetalPluginClassName = Navi48Device`**: è così che Metal.framework trova e carica il bundle `Navi48Metal.bundle`, installato in **`/Library/GPUBundles/Navi48Metal.bundle`** (**[VERIFICATO]**: path usato da `tools/pc/m6-stage1a-deploy.sh`, `tools/native/mtlprobe/mtlprobe.m`, `tools/native/autotranslate/pc-translate.sh`; è la directory dei GPU bundle di terze parti, quindi niente scrittura nel volume di sistema sigillato). Librerie: `com.apple.iokit.IOAcceleratorFamily2 2.0.0`, `com.apple.iokit.IOGraphicsFamily 1.0`.
3. `Navi48Accelerator` è una sottoclasse di `IOGraphicsAccelerator2` costruita **sul modello di `AppleParavirtGPU`** (la GPU paravirtualizzata delle VM macOS x86): i tipi di ritorno e il contenuto di `IOAccelConfig` sono ricavati dal disassemblato di `AppleParavirtAccelerator::populateAccelConfig` (`src/amd/native_metal_pure.h:62-112`: 12 store a offset `+0x00 name, +0x08 0x480000, +0x0c 7, +0x14 0x2000000000, +0x20 0x40000000, +0x28 0x100000000008, +0x30 0x40004000, +0x47 0 (headless), +0x5c 4, +0x64 2, +0x68 0x10000000a, +0x88 0`); vtable slot sovrascritti per indice (271, 273, 307, 310-314, 320-337, 348, `IOAccelEventMachine2` 35/72/73, `IOAccelDisplayPipe` 267/277-279, `newUserClient` 239…). Il layout viene da `IOAccelFamily2_decl.h` generato da `tools/native/ioaccel-layout/` (**non pubblicato**) e verificato a runtime da "gate" (`gates/gen_gate.py`, `layout_gate_host.py`).
4. Per i display c'è `Navi48Framebuffer : IOFramebuffer` (stesso kext aux) che fa match su `Navi48DisplayNub` con `Navi48DisplayIndex` 1 o 2, e `Navi48DisplayPipe : IOAccelDisplayPipe` per il percorso di presentazione di WindowServer (transaction/flip), che il kext principale traduce in flip HUBP.

### 6.2 Sottoclassi Metal (`Navi48Device.m`, 6 293 righe)
- `@interface Navi48Device : MTLIOAccelDevice` (classe ObjC esportata da Metal.framework, dichiarata senza ivar; stesso schema di `AppleParavirtGPUMetal`), più `N48Buffer`/`N48Texture : _MTLResource`, `N48Heap : _MTLHeap`, `N48CommandQueue : _MTLCommandQueue`, `N48CommandBuffer : _MTLCommandBuffer`, `N48RenderEncoder`/`N48ComputeEncoder`/`N48BlitEncoder : _MTLCommandEncoder`, `N48RenderPipelineState : _MTLRenderPipelineState`, `N48ComputePipelineState`, `N48SamplerState`, `N48DepthStencilState`, `N48Fence` (righe 73-104, 2041-5790). Eventi: `newEvent`/`newSharedEvent` restituiscono il `_MTLSharedEvent` generico di Metal (CPU-side, r. 4809).
- Proprietà dichiarate: `productName = "RX 9070 XT"` (r. 6262, nome → "AMD Radeon RX 9070 XT"), `featureProfile 10000`, `llvmVersion 0x7d17` (copiato da pvm.x86), `supportsFamily`: Mac2, Common1..3; **Metal3 solo per WindowServer** (per le app NO perché argument buffers/gpuAddress non implementati), `argumentBuffersSupport` Tier1 per le app, `hasUnifiedMemory NO`, `isHeadless` configurabile.
- Superficie implementata (grep): draw/drawIndexed, dispatch, blit, texture view, IOSurface-backed texture, occlusion query (`setVisibilityResultMode` su query pool Vulkan), MSAA/resolve, depth/stencil, heap, linked functions. **Non** implementati: `newIndirectCommandBuffer`, `newArgumentEncoder`, acceleration structure/ray tracing, mesh shader, rasterization rate map, counter sample buffer, binary archive, tile shader. Un "census" logga i selettori non implementati (`n48_census.h`).
- Back-end: carica RADV con `dlopen` e `vk_icdGetInstanceProcAddr` (r. 508-538), crea istanza/device Vulkan, traduce ogni oggetto Metal in oggetti Vulkan (render pass cache, descriptor set signature cache, pool slab 4 MiB, ledger degli import IOSurface).

### 6.3 Flusso shader (AIR → SPIR-V → RADV) **[VERIFICATO]**
1. Metal.framework compila MSL/carica metallib → **AIR bitcode** (front-end Apple); il bundle intercetta la creazione delle pipeline e calcola `sha256` del bitcode della funzione (`n48_sha256hex`, r. 1919).
2. Lookup in `spvcache/<sha>.spv` + `<sha>.meta.json` (sampler statici, contratto di dispatch compute, binding: render = set 1, compute = set 0): prima `Resources/spvcache` del bundle, poi la side-cache `/private/var/tmp/n48m-spv` (r. 3535-3549).
3. Miss in **WindowServer**: pipeline di *fallback* (render magenta / compute no-op), AIR scaricato in `/private/tmp/n48m/<uid>/<sha>.air`; il daemon `com.navi48.translate` (utente `nobody`, `sandbox-exec n48-translate.sb`, limiti CPU/RSS) esegue `pc-translate.py`: `n48-llvm-dis` (clang delle CommandLineTools come llvm-dis) → `metal2vulkan --emit-meta` → patch formato storage image → installa meta poi spv; il bundle fa **hot-swap** della pipeline (`n48_hotswap.h`). `n48-spirv-val-stub` dichiara sempre valido (validazione vera fatta sul Mac host).
4. Miss in un'**app ammessa** (bundle 14): traduzione in-process — il bitcode reader LLVM di sistema stampa l'AIR come testo LLVM e `Resources/libn48xlate.dylib` (LGPL, wrapper metal2vulkan, ABI 2 con linking di visible functions) produce SPIR-V, cache in `<user cache>/com.navi48.xlate/<K>/`.
5. `vkCreateShaderModule` → RADV/ACO compila SPIR-V → ISA gfx1201.
- **Per Navi 44**: tutta la catena è indipendente dall'ASIC fino a RADV; ACO conosce già gfx1200 (stesso ISA RDNA4). Le `.spv` sono riusabili 1:1. Va cambiato solo `productName` e gli id nelle cache pipeline (`test-t1.c` usa `0x1002:0x7550` nell'header della pipeline cache: con device id diverso la cache viene invalidata, comportamento corretto).

## 7. navi48accel, autotranslate, g2capture, shadercache, display DCN, infrastruttura di test

### 7.1 `tools/native/navi48accel` (kext aux, `com.navi48.accelprobe` 0.0.7) **[VERIFICATO]**
- `Navi48Accel.cpp` (786 righe) + `n48accel_pure.h`: grafo di classi IOAccelerator **fisso e "sottile"** (ogni rebuild richiede l'approvazione utente perché il kext sta nell'Auxiliary KC); ogni decisione è delegata alla tabella `N48MetalOps` del kext principale (copie byte-identiche di `Navi48MetalOps.h`/`Navi48DisplayOps.h` in entrambi gli alberi, verificate dai test host). Classi: `Navi48Accelerator` (IOGraphicsAccelerator2), trampolini per EventMachine, SharedUserClient, CommandQueue, VidMemory, Resource, Context2D, DisplayPipe (`N48_VC_*`), `Navi48Framebuffer` (IOFramebuffer, 2 personality con `Navi48DisplayIndex` 1/2).
- Gate di sicurezza: kill switch, "layout gate" a runtime che confronta gli slot vtable attesi con quelli della IOAcceleratorFamily2 caricata (generati da `gates/*.py` + `ioaccel-layout` non pubblicato) → se macOS cambia, l'acceleratore non parte (fail-closed).
- `verify.sh`, `tests/`: test host di `n48accel_pure.h`.

### 7.2 `tools/native/autotranslate`, `mtlprobe`
- Daemon di traduzione AIR→SPIR-V (`com.navi48.translate.plist`, `pc-translate.sh/.py`, `n48-translate.sb`, `n48-llvm-dis`, `n48-spirv-val-stub`, `overrides.txt` per le dimensioni threadgroup di alcuni kernel) e `air-pull.sh` (variante "host": ogni 5 s tira gli AIR dal PC, traduce sul Mac host, rispedisce `.spv`/`.meta.json`). Descritto in Sez. 6.3.
- `mtlprobe.m` (3 883 righe) + `tri.metal`: probe dell'API Metal (enumerazione device, triangolo, test hot-swap) per il bring-up del bundle.

### 7.3 `src/g2capture`, `src/shadercache`
Solo rotta Apple (Sez. 5): cattura container shader del compilatore Apple via swizzling ObjC a indirizzo fisso; parser di una cache hash→binario gfx1201 da sostituire nelle copie di residenza. Irrilevanti per un port nativo.

### 7.4 Display DCN (`src/dcn41`, `src/navi48-bringup/src/dcn`)
- **[VERIFICATO]** Non è un driver DC completo: è un layer di registri generato da `dcn_4_1_0_offset.h`/`_sh_mask.h` (`tools/dcn41/gen_regs.py`) con **allowlist di scrittura** (`dcn41_allow_ranges.h`, generata), e funzioni che rispecchiano singole funzioni Linux (`hubp401_program_surface_flip_and_addr`, `optc1_get_position`, …, `dcn41.h:8-25`), validate contro tracce di registri di Linux (`tools/dcn41/harness.py` + `linuxshim`).
- Modello: **adotta** la pipe accesa dal GOP UEFI (OTG0/HUBP0 + DIG1/PHY B sulla loro scheda), fa flip di superfici (`SCAN_*`), "same-mode re-timing" (`dcnmode`), prove di modo da tabelle fisse (`navi48_modetrial_tables.h`: righe 50/60/120 Hz) e accende a mano un secondo/terzo display (`navi48_disp2.h`: OTG1/ODM1/OPP1/DPG1 + DIG2 → UNIPHY_C, OTG2/DIG3 → PHY D, timing 1920×1080@60 CEA VIC16 e 2560×1440@60 dalle EDID dei *loro* monitor, accensione PHY e PLL delegata al DMUB tramite comandi inbox `navi48_dmubcmd.h`). Nessun link training DP da zero, nessun calcolo watermark/DML, nessun DSC, niente HDMI 4K (README "In progress").
- **[VERIFICATO] Basi DMU identiche**: Cobalt cabla le basi segmento DMU `0x12 0xc0 0x34c0 0x9000 0x2403c00` (`navi48_modetrial_tables.h:4`, `navi48_disp2.h:45,120`, rifiuto se diverse). La nostra tabella discovery (hwid 271, v4.1.0) ha **esattamente** `0x12 0xc0 0x34c0 0x9000 0x2403c00` → tutti i numeri di registro DCN assoluti restano validi su Navi 44.
- **[VERIFICATO] Topologia connettori diversa** (nostro VBIOS, `displayobjectinfo` v1.5, parse del run precedente in `scratchpad/display/vbios_parse.out`): path0 DP → `UNIPHY_A` (PHY A, DDC1, HPD1, 13.5 Gbps), path1 HDMI → `UNIPHY_B` (PHY B, DDC2, HPD2), path2 HDMI → `UNIPHY_C` (PHY C, DDC3, HPD3); `max_disp_phy_num 3`, `max_disp_pipe_num 4`. Sulla scheda di Cobalt: DP su DIG1/PHY B, HDMI su DIG2/PHY C e DIG3/PHY D (ddc3/hpd4). **Tutti i mapping istanza→DIG/PHY/DDC/HPD della milestone M6 vanno rifatti** (o meglio derivati dal VBIOS); la "istanza 2 = PHY D" non esiste sulla nostra scheda.
- DMUB: firmware `dcn_4_0_1_dmcub` (il nostro: 0x0A004B00) è caricato dal VBIOS/GOP; Cobalt non carica DMUB da sé, usa solo l'inbox (registro `DMCUB_INBOX1_WPTR` = `0x34c0+0x1d6`).

### 7.5 Infrastruttura di test
- **Host test** (`src/navi48-bringup/tests`, 100 K righe, `tools/conductor/suites.sh`): ogni header `*_pure.h` ha una suite C++ compilata sul Mac host; `*_plant.sh` / `tools/conductor/plant.py` fanno "planted break" (mutano il sorgente e pretendono che i test falliscano). `src/xlat12` ha `make test` (ASan/UBSan + fuzz) e `make kextcheck` (nessun simbolo indefinito, nessuna istruzione SSE/x87). `tools/dcn41/build.py all`.
- **Hardware loop** (`tools/stage-to-pc.sh`, `tools/pc/*`): sviluppo su un Mac arm64 ("RUN ON THE AIR"), cross-build x86_64, `ssh navi48` verso il PC di test, `esp-kext.sh install` copia il kext in `EFI/OC/Kexts/` (iniezione OpenCore, niente firma/approvazione), `esp-config.sh` scambia tre `config.plist` OpenCore, `reboot-pc.sh` (gates + snapshot), `navi48test.c` (CLI con decine di verbi `accel …`), script per milestone (`m6-stage1a/1b/2-*.sh`, fino a 150 KB l'uno) e un simulatore (`tools/pc/m6-stage2-sim`). `tools/pc/autoarm`: LaunchDaemon che a ogni boot pubblica il nub Metal, accende il desktop multi-display al login window e riavvia WindowServer una volta, con fallback al desktop CPU.
- **Mancano** test di conformità (CTS Vulkan, test Metal sistematici): la validazione è "il desktop funziona con le app Apple elencate".

## 8. Patch Mesa (RADV Darwin)

Base: Mesa `f5cb8ee032adabef599ae892ec4e42d796b84da9` (26.3.0-devel), 9 patch in `mesa-patches/` (`README.txt`). **[VERIFICATO]** dai diffstat:

| Patch | Contenuto | File principali |
|---|---|---|
| 0001 (147 KB) | backend Darwin con device **canned gfx1201**: `include/darwin/{amdgpu.h (2102 righe, libdrm_amdgpu riscritta), xf86drm.h, libsync.h}`, `src/amd/common/darwin/{ac_darwin_drm.c, ac_darwin_sync.c, amdgpu_vamgr.c}` (VA manager userspace), `ac_linux_drm.c` instradato su Darwin, `radv_physical_device.c` (`radv_darwin_enumerate_physical_devices`: finto `drmDevice` PCI `0x1002:0x7550` rev `0xC0`, solo con `RADV_DARWIN_FAKE=1` nella fase iniziale), cross-file `cross-x86_64.ini` | il device viene preso da `find_canned("gfx1201")` sulla tabella `src/amd/common/amdgpu_devices.c` di Mesa (quella del drm-shim) |
| 0002 (140 KB) | metà Mesa del kext: `navi48_native_abi.h` (copia di `Navi48NativeABI.h`), `ac_darwin_kext.c` (IOKit: `IOServiceOpen('N48N')`, `IOConnectCallMethod`), `ac_darwin_iokit.c`, `ac_darwin_mock.c` (mock per test host), BO = handle kext + mappa CPU + metadata locale, un solo client kext per processo condiviso da più `VkDevice` | `ACD_MARKETING_NAME "AMD Radeon RX 9070 XT"` |
| 0003 | API scanout (selettori 9-14) | |
| 0004 | userptr via `BO_IMPORT_HOST` (21) | |
| 0005 | `radv_amdgpu_cs.c`: i fallimenti di `cs_grow` ritornano invece di abortire | upstreamabile |
| 0006 | budget VRAM per sessione (ABI 1.10) → heap VRAM ridotti per le app | `ac_darwin_budget.h` |
| 0007 | `GB_ADDR_CONFIG` letto da `n48n_info` invece che da `READREGS` (vietato alle sessioni APP) | |
| 0008 | `radv_darwin_set_service_class`: `Navi48Bringup` (default) o `Navi48Accelerator` (app sandboxed, via IOAccelerator) | |
| 0009 | `radv_darwin_n48n_call` selettori 22-26 (scanout multi-display) | |

Osservazioni:
- **[VERIFICATO]** La tabella canned di Mesa `src/amd/common/amdgpu_devices.c` (nel nostro clone, r. 2575-2700) contiene `gfx1201` ma **non `gfx1200`**. Valori gfx1201: `device_id 0x7550`, `chip_rev 0x01`, `external_rev 0x51`, `num_shader_engines 4`, `num_shader_arrays_per_engine 2`, `cu_active_number 64`, `cu_bitmap 0xff,0xff ×4 SE`, `enabled_rb_pipes_mask 0xffff`, `num_rb_pipes 16`, `vram_type 9`, `vram_bit_width 256`, `num_tcc_blocks 32`, `gl2c_cache_size 8192`, `mall_size 64 MiB`, `max_engine_clock 2460000`, `max_memory_clock 1258000`, fw ME 2590/PFP 2630/MEC 2800, `mmr_regs {0x263e: 0x08200545}`. Per Navi 44 serve un nuovo record `gfx1200` (valori in Sez. 10), generabile su questa macchina Linux interrogando `AMDGPU_INFO_*` via libdrm su `renderD128` (non privilegiato).
- Il kernel accetta solo `ip_type == N48N_HW_IP_GFX`, `ring 0` (`native_s1c_pure.h:268`), mentre la tabella canned dichiara `hw_ip_compute.available_rings = 0xf`: le code compute di RADV non sono realmente servite **[INFERITO: il bundle usa solo la coda universale]**.
- La parte RADV/ACO per gfx12 è upstream: niente da portare per gfx1200 a parte il record canned e la stringa marketing.
- Licenza MIT, ma le patch includono un `amdgpu.h` riscritto di 2 102 righe (API libdrm): manutenzione non banale a ogni rebase di Mesa.

## 9. Versione macOS fissata (Tahoe 26.6.2) e punti di fragilità

**[VERIFICATO]** README: macOS **Tahoe 26.6.2**; build **25G83** citata in `src/g2capture/g2capture.m` e `src/xlat12/gen/gen_*.py`; `Navi48Metal` `LSMinimumSystemVersion 26.6`; 56+22+10 riferimenti "26.6.2" in `xlat12_readset.h`, `xlat12_abi_ptrs.h`, `xlat12_ib.c`. La cache di traduzione in-process include `kern.osversion` nella chiave (`n48_xlate.h:126-135`).

Punti fragili (in ordine di gravità per un port):
1. **Layout privati di IOAcceleratorFamily2** (indici di slot vtable 239, 267-279, 307-348…, tipi di ritorno "pinned" dal disassemblato di `AppleParavirtGPU`, `Navi48Accel.cpp:30-74`) e contenuto di `IOAccelConfig` (0x90 byte, `native_metal_pure.h:62-112`). Cambiano potenzialmente a ogni minor di macOS; il generatore `ioaccel-layout` non è pubblico. Il "layout gate" a runtime evita il panic ma non risolve.
2. **Classi Metal private**: `MTLIOAccelDevice`, `_MTLResource`, `_MTLHeap`, `_MTLCommandQueue`, `_MTLCommandBuffer`, `_MTLCommandEncoder`, `_MTLRenderPipelineState` sottoclassate senza header (`Navi48Device.m:73-104`), valori copiati da `pvm.x86` (`llvmVersion 0x7d17`, `featureProfile 10000`), selettori scoperti per disassemblato (es. `supportLazyInitialization` a `0x7ff80f5a9cd3`).
3. **Rotta Apple** (se mai usata): offset di `AMDRadeonX6000`/`HWServices`, indirizzi nel dyld shared cache (`g2capture`: `0x7ffb11191a7a`), righe IB di WindowServer: legati a 25G83 byte per byte.
4. **IOPCIFamily di Tahoe**: BAR > 1 GiB non dimensionabile (`rebar_pure.h:20`) → ReBAR limitata a ≤1 GiB; con BAR0 mappata ≤1 GiB la VRAM oltre è solo "hi pool" non CPU-visibile.
5. **Ambiente**: memoria DMA con `kIOMemoryMapperNone` + contigua (VT-d/AMD-Vi disattivo o `DisableIoMapper`), kext ad-hoc firmato iniettato da OpenCore (SIP/AMFI rilassati **[INFERITO]**), kext aux in Auxiliary KC (approvazione utente a ogni rebuild), RDNA4FB per la console (`rdna4-off=1` per disattivarlo), centinaia di boot-arg `navi48-*`, autoarm che riavvia WindowServer al login window.
6. **Nessun reset GPU**: un hang = reboot; display e calcolo sulla stessa GPU senza recovery robusto.
7. **Display**: modi fissi dalle EDID dei monitor dello sviluppatore, mapping connettori della loro scheda (Sez. 7.4).
8. **Hardware singolo**: "only been run on one x86_64 test PC with one RX 9070 XT" (`BUILDING.md`).
9. **Toolchain**: build richiede il MacKernelSDK di RDNA4FB e una revisione precisa di linux-firmware (sha256 in `tools/fetch-firmware.sh`).

Per noi (Hackintosh AM5 + Ryzen 7700): stesso modello x86_64 + OpenCore, quindi i punti 1-2 e 4-5 valgono identici; va scelta **una** release macOS e trattata come piattaforma fissa (Tahoe 26.6.2 è la scelta a rischio minimo perché tutto Cobalt è tarato lì).

## 10. Tabella completa degli hardcode Navi 48 → valore Navi 44

Percorsi relativi a `refs/Cobalt64/`. Colonna "Stato": **=** identico su Navi 44 (verificato), **Δ** da cambiare, **Δ!** da cambiare ed è rischioso, **n/a** solo rotta Apple/test.
Fonti Navi 44: `lspci`/dmesg (fatti misurati), `hw_dump/ip_discovery_table.bin` (decodificata con `scratchpad/cobalt/scripts/disc.py`, `gcinfo.py`), `hw_dump/README.md`, `scratchpad/cobalt/radv_info.txt` (RADV_DEBUG=info del run precedente), `scratchpad/display/vbios_parse.out`, sorgenti Linux.

### 10.1 Identità, firmware, nomi

| # | Cosa | Navi 48 in Cobalt | File:riga | Navi 44 (RX 9060 XT) | Stato |
|---:|---|---|---|---|---|
| 1 | Match PCI (4 personality) | `0x75501002 0x75511002` | `src/navi48-bringup/Info.plist:32,47,69,86` | `0x75901002` (rev c0, subsys 1DA2:A493) | Δ |
| 2 | Controllo device in `probe()` | `device != 0x7550 && device != 0x7551` → rifiuto | `src/navi48-bringup/src/Navi48Bringup.cpp:7334-7338` | `0x7590` | Δ |
| 3 | Nomi marketing | "RX 9070/XT", "R9700" (log); `productName` "RX 9070 XT"; `ACD_MARKETING_NAME "AMD Radeon RX 9070 XT"` | `Navi48Bringup.cpp:7338`; `tools/native/navi48metal/Navi48Device.m:6259-6262`; `mesa-patches/0001…patch:2884`, `0002…patch:271` | "AMD Radeon RX 9060 XT" | Δ |
| 4 | Identità PCI finta in RADV | `device_id 0x7550`, rev `0xC0`, subsys `0x1002:0` | `mesa-patches/0001…patch:4343-4348`, `0002…patch:3632` | `0x7590`, rev `0xC0`, subsys `0x1DA2:0xA493` | Δ |
| 5 | Device canned Mesa | `find_canned("gfx1201")` (tabella `src/amd/common/amdgpu_devices.c:2575-2700` di Mesa) | `mesa-patches/0001…patch:2930` | **non esiste "gfx1200"**: nuovo record (vedi 10.3) | Δ! |
| 6 | Firmware obbligatori embedded | `gc_12_0_1_{imu,me,mec,pfp,rlc,uni_mes}`, `psp_14_0_3_{sos,ta}`, `sdma_7_0_1`, `smu_14_0_3` | `src/navi48-bringup/Makefile:27-28` | `gc_12_0_0_{imu,me,mec,pfp,rlc,uni_mes}`, `psp_14_0_2_{sos,ta}`, `sdma_7_0_0`, `smu_14_0_2` (tutti in `/usr/lib/firmware/amdgpu`) | Δ |
| 7 | Tabella firmware (simboli `fw_*`, nomi) | `fw_psp_14_0_3_sos` … `fw_sdma_7_0_1`, voci nulle `gc_12_0_1_mes/mes1/toc` | `src/navi48-bringup/src/amd/fw_table.cpp:47-125`, `src/fw/fw_table.h` | idem con prefissi Navi 44 | Δ |
| 8 | SOS passato al bootloader | `psp.parseContainer(fw_psp_14_0_3_sos, …)` | `Navi48Bringup.cpp:43-44,586` | `fw_psp_14_0_2_sos` | Δ |
| 9 | Firmware nei test/tool | `hosttest/main.cpp:223-240`, `tools/fetch-firmware.sh:30+` (sha256 per revisione), commenti `amdgpu_sdma.h:561,911`, `BUILDING.md` | | nomi e sha256 Navi 44 | Δ |
| 10 | Varianti `_kicker` | non usate ("non-kicker", `fw_table.cpp:95`) | | Navi 44 non ha kicker (Linux `amdgpu_ucode.c:33-36`: solo 0x744B e 0x7551 rev C8) | = |
| 11 | Contenuto container SOS | commento "no SPDM_DRV: psp_14_0_3 ships none"; catena KDB,SPL,SYS,SOC,INTF,DBG,RAS,IPKEYMGR,SOS | `src/navi48-bringup/src/psp.cpp:275-291` | **[VERIFICATO, parse `scratchpad/cobalt/scripts/pspsos.py`]** `psp_14_0_2_sos.bin`: KDB, SYS_DRV, SOS, SOC_DRV, INTF_DRV, DBG_DRV, TOC, IPKEYMGR, SPL — **mancano RAS_DRV e RL** (presenti nel 14_0_3). `loadComponent` salta i sub-bin assenti (`psp.cpp:217`) e `psp_rl_load` ritorna successo se RL assente (`psp_v14_0.cpp:1176-1181`) → OK. Versione SOS 0x003b0f0d = quella caricata da Linux | = (verificare a runtime) |
| 12 | Formato header firmware | parser per IMU v1.0, RS64 v2.0, RLC v2.2, MES v1.0, SDMA v3.0, SMU v2.0, PSP v2.0 | `amdgpu_ucode_extract.cpp`, `amdgpu_ucode_psp.h` | **[VERIFICATO, `fwhdr.py`]** stessi identici `header_version` su tutti i blob `gc_12_0_0_*`, `sdma_7_0_0`, `smu_14_0_2`, `psp_14_0_2_*` | = |
| 13 | Shader di self-test | `.amdgcn_target "amdgcn-amd-amdhsa-unknown-gfx1201"` | `src/navi48-bringup/shaders/store_magic_hsa.s:7,25,151`, `metal_progress_track.s:1,125` | ri-assemblare `-mcpu=gfx1200` (ISA RDNA4 identico; solo metadati) | Δ (banale) |

### 10.2 Geometria GPU, registri, memoria, BAR

| # | Cosa | Navi 48 in Cobalt | File:riga | Navi 44 | Stato |
|---:|---|---|---|---|---|
| 14 | `max_shader_engines` | 4 | `src/navi48-bringup/src/amd/gfx_v12_0.cpp:372`; commenti `amdgpu_gfx.h:3-6,253-258,278` | **2** (gc_info `num_se 2`; dmesg 2 SE) | Δ |
| 15 | `max_sh_per_se` | 2 | `gfx_v12_0.cpp:373` | 2 (`num_sa_per_se 2`) | = |
| 16 | `max_backends_per_se` | 4 | `gfx_v12_0.cpp:374` | 4 (`num_rb_per_se 4`; 8 RB totali) | = |
| 17 | `max_cu_per_sh` | 8 | `gfx_v12_0.cpp:375` | 8 (`num_wgp0_per_sa 4` × 2) | = |
| 18 | `max_hw_contexts`, `sc_*_fifo_size` | 8; 0x20/0x100/0/0x4C0 | `gfx_v12_0.cpp:376-382` | Linux usa lo stesso ramo per 12.0.0 e 12.0.1 (`gfx_v12_0.c:1561-1562`) | = |
| 19 | Array harvest | `active_cu_bitmap[4][2]` | `amdgpu_gfx.h:280` | [2][2] sufficiente (dimensionare da discovery) | Δ (robustezza) |
| 20 | CU/RB attesi | 64 CU / 32 WGP, 16 RB | `amdgpu_gfx.h:253-254` | 32 CU / 16 WGP, 8 RB | Δ |
| 21 | `GB_ADDR_CONFIG` | 0x08200545 | `amdgpu_gfx.h:85-86`; Mesa canned `mmr_regs {0x263e, …, 0x08200545}` | **0x08200545** (`hw_dump/README.md:36`) | = |
| 22 | Golden settings GC | **nessuna applicata** | (grep "golden" = 0 in `src/amd`) | Linux: `golden_settings_gc_12_0` (`DB_MEM_CONFIG 0x8000`) per entrambi; `_rev0` solo `rev_id==0` (nostro rev_id 1) | Δ consigliato (entrambi) |
| 23 | Registri base (MM_INDEX/DATA/HI, NBIF MEMSIZE, PSP C2PMSG_35/64/69-71/81/58/59, SMU C2PMSG_66/82/90) | `0x0/0x4/0x18`; seg2 `0x00c3` fallback byte `0x378c`; `0x63/0x80/0x85-87/0x91/0x7a/0x7b`; seg1 `0x82/0x92/0x9a` | `src/navi48-bringup/src/regs.hpp:20-56` | **[VERIFICATO]** identici in `mp_14_0_2_offset.h:161,193,209,369,387,397,421`, `nbif_6_3_1_offset.h:1809-1810`; NBIF base[2] = `0xd20` nella nostra discovery → `(0xd20+0xc3)*4 = 0x378c` | = |
| 24 | `MMMC_VM_FB_LOCATION_BASE` | MMHUB dword `0x0554` | `Navi48Bringup.cpp:625` | `mmhub_4_1_0_offset.h:860` = 0x0554; nostro MMHUB 4.1.0, base `0x1a000` | = |
| 25 | Basi IP (via discovery a runtime) | lette on-die | `ipdiscovery.cpp`, `amdgpu::fill_ip_base_table` | GC `0x1260 0xa000 0x1c000 0x2402c00`, MMHUB `0x1a000`, NBIF `0x0 0x14 0xd20 0x10400 …`, OSSSYS v7.0.0 `0x10a0`, SDMA0/1 v7.0.0 come GC | = (runtime) |
| 26 | Discovery TMR | 64 KiB sotto la fine VRAM, 10 KiB | `regs.hpp:59-60` | idem (Linux `DISCOVERY_TMR_OFFSET`) | = |
| 27 | Dimensione VRAM e layout alto | `RCC_CONFIG_MEMSIZE` 16304 MiB, TMR PSP ~`0x3f860_0000`, discovery ~`0x3faff0000`, `kVramHiTailReserve 512 MiB` + `kAppleArenaCarveReserve 256 MiB`, PDB0 2 foglie da 8 GiB | `src/amd/amdgpu_gmc.h:53-63,197,269`; `rebar_pure.h:79`; `Navi48Ttl.cpp:544` | 16 GB: `vram_vis_size 16304 MB`, range MC `0x8000000000-0x83FAFFFFFF` (dmesg) → **identico**. (Una 9060 XT da 8 GB richiederebbe di rivedere TMR/foglie.) | = |
| 28 | Bus di memoria 256-bit / UMC | il kext non tocca UMC; solo Mesa canned `vram_bit_width 256` | Mesa `amdgpu_devices.c` (gfx1201) | 128-bit, 4× UMC 8.14.0 | Δ (solo Mesa) |
| 29 | BAR0 massima mappabile | `kMaxBar0Map = 1 GiB`, rifiuto se più grande (`kLenTooBig`) | `src/amd/rebar_pure.h:20,85` | oggi BAR0 = 16 GiB (Linux, ReBAR attivo) → su macOS va **ridotta a ≤1 GiB** (BIOS o OpenCore `ResizeAppleGpuBars`) | Δ! (config) |
| 30 | BAR2 doorbell / BAR5 MMIO | 256 MiB / 512 KiB (non cablati, letti da IOPCIFamily) | `mapDoorbells`, `mapRegisters` | 256 MiB / 512 KiB | = |
| 31 | Istanze SDMA | 2 (SDMA1 = SDMA0 + 0x600 dword) | `src/amd/amdgpu_sdma.h:85-89` | SDMA0/1 7.0.0 (stesso ramo Linux `sdma_v7_0.c:1355-1356`) | = |
| 32 | Maschere MES | `vmid_mask 0xFE`, `gfx_hqd_mask[0] 0xFE`, `compute_hqd_mask 0xFC` | `src/amd/mes_v12_1.cpp:1564-1594` | scelta di design (Linux su Navi 44: vmid 0xff00, gfx 0xfe, compute 0x0c, sdma 0xfc) | = |
| 33 | VMID nativo | 8 | `native_s1b_pure.h:28-35` | idem | = |
| 34 | Messaggi SMU (PPSMC) | `TestMessage 0x1`, `GetSmuVersion 0x2`, `GetDriverIfVersion 0x3`, `TransferTable* 0x12/0x13`, `SetSoft*ByFreq` | `regs.hpp:52-54`, `src/amd/amdgpu_smu.h:104-105` | stesso `smu_v14_0_2_ppsmc.h` per 14.0.2/14.0.3; differenza Linux solo `enable_gfx_features` (reset, `smu_v14_0_2_ppt.c:2112`) | = |
| 35 | Limiti Metal dipendenti da VRAM | `N48_MAX_BUFFER_LENGTH 4 GiB`, `N48_RECOMMENDED_WORKING_SET 12 GiB` | `Navi48Device.m:5948-5949` | 16 GB → valori ok | = |
| 36 | `external_rev_id` | Mesa canned `external_rev 0x51` | Mesa `amdgpu_devices.c` gfx1201 | **0x41** (`hw_dump/README.md:42`; Linux `soc24.c:366` = rev_id + 0x40, Navi 48 `:387` = +0x50) | Δ (Mesa) |

### 10.3 Record canned Mesa da creare (`gfx1200`) — valori Navi 44 **[VERIFICATO da RADV_DEBUG=info e discovery]**
`radeon_family CHIP_GFX1200`, `device_id 0x7590`, `pci_rev 0xc0`, `chip_rev 0x01`, `external_rev 0x41`, `family AMDGPU_FAMILY_GC_12_0_0 (0x98)`, `num_shader_engines 2`, `num_shader_arrays_per_engine 2`, `cu_active_number 32`, `cu_bitmap {0xff,0xff} × 2 SE`, `num_cu_per_sh 8`, `enabled_rb_pipes_mask 0xff`, `num_rb_pipes 8`, `vram_type 9` (GDDR6), `vram_bit_width 128`, `num_tcc_blocks 16`, `gl2c_cache_size 4096` KB, `mall_size 32 MiB` (RADV: `l3_cache_size = 32 MB`), `max_engine_clock 2700000` kHz (RADV `max_gpu_freq 2700 MHz`), `mmr_regs {0x263e: 0x08200545}`, fw ME `0xc12`/PFP `0xc76`/MEC `0xd7a` (dmesg). I campi heap/visibilità vanno dal kext a runtime (`n48n_info`), non dalla tabella. Il modo più sicuro è generarlo su questa macchina con un piccolo programma libdrm (`amdgpu_query_info`, `amdgpu_query_hw_ip_info`, `amdgpu_read_mm_registers`) sul render node — operazione non privilegiata, da fare nella fase di sviluppo.

### 10.4 Display (dipende da scheda e monitor, non solo dall'ASIC)

| # | Cosa | Cobalt (scheda/monitor dello sviluppatore) | File:riga | Navi 44 Sapphire 1DA2:A493 | Stato |
|---:|---|---|---|---|---|
| 37 | Basi segmento DMU | `0x12 0xc0 0x34c0 0x9000 0x2403c00` (rifiuto se diverse) | `src/navi48-bringup/src/dcn/navi48_modetrial_tables.h:4`, `navi48_disp2.h:45,120`, `dcn41_allow*.h` | **identiche** (hwid 271 v4.1.0: `0x12 0xc0 0x34c0 0x9000 0x2403c00`) | = |
| 38 | Inbox DMUB | `DMCUB_INBOX1_WPTR` = `0x34c0+0x1d6 = 0x3696` | `dcn/navi48_dmubcmd.h:40` | idem | = |
| 39 | Numero pipe | istanze ≥4 rifiutate | `src/dcn41/dcn41.h:24-25` | 4 (VBIOS `max_disp_pipe_num 4`; Linux `res_cap_dcn4_01.num_timing_generator 4`) | = |
| 40 | Pipe console (adottata) | OTG0/HUBP0 → DIG1 → **PHY B (DP)** | `navi48_disp2.h:16`, guardie "DIG1/PHY B" | quale OTG/DIG il GOP accende dipende dal connettore usato; sul nostro VBIOS il DP è su **PHY A** | Δ! |
| 41 | Monitor A | OTG1/ODM1/OPP1/DPG1 → DIG2 → **UNIPHY_C**, HDMI, SYMCLKC | `navi48_disp2.h:8,19,86` | HDMI-1 = **PHY B**, DDC2, HPD2; HDMI-2 = **PHY C**, DDC3, HPD3 | Δ! |
| 42 | Monitor B | OTG2/ODM2/…/DIG3 → **UNIPHY_D**, HDMI, ddc3/hpd4, SYMCLKD | `navi48_disp2.h:20,87` | **PHY D non esiste** (VBIOS `max_disp_phy_num 3`) | Δ! |
| 43 | Timing | 1920×1080@60 CEA VIC16 (148.5 MHz), 2560×1440@60 (241.5 MHz, raster 2720×1481), righe 50/60/120 Hz con clock DML precalcolati | `navi48_disp2.h` (op `timing`, `timing1440`), `navi48_modetrial_tables.h:117-122` | dipende dai monitor dell'utente: ricalcolare (EDID + DML) | Δ! |
| 44 | Allowlist scritture DCN | intervalli registri DIG1..DIG6, PHY, DCCG | `src/dcn41/dcn41_allow_ranges.h` (generato) | stesse basi → valida, ma le guardie per istanza vanno rifatte | Δ |

### 10.5 Solo rotta Apple / test (da rimuovere in un fork)
| # | Cosa | File | Stato |
|---:|---|---|---|
| 45 | Personality `AMDRadeonX6000_AMDNavi21GraphicsAccelerator`, `AMDRadeonX6000_AMDRadeonHWServicesNavi`, `Navi48AccelPeer` | `Info.plist:23-76` (personality alle righe 23, 38, 60) | n/a |
| 46 | Indirizzi/offset Apple 26.6.2 (TTL, vtable, IB WindowServer, `g2capture` `0x7ffb11191a7a`) | `src/apple/*`, `src/xlat12/*`, `src/g2capture/g2capture.m` | n/a |
| 47 | Header cache pipeline `0x1002:0x7550` | `tools/native/navi48metal/test-t1.c:30-47` | n/a (test) |
| 48 | Device canned 7000-macos: `kNavi48Rx9070 0x7550`, `kNavi48R9700 0x7551`, profilo `{12,0,1}`, `psp_14_0_3`… | `7000-macos/src/navi48-bringup/src/amd/asic_profile.cpp` | modello per il profilo Navi 44 |

## 11. Differenze del fork 7000-macos (asic_profile ecc.)

**[VERIFICATO]** `refs/7000-macos` è un singolo commit (`cc93e38`, autore "twhippp", 5 ottobre 2026, "asic_profile: format versions without stdio.h so the kext builds") su uno snapshot **più vecchio** di Cobalt: kext `0.0.621` (vs 0.0.664), 5 patch Mesa (vs 9), README "60 fps desktop su un display DP"; mancano rispetto a Cobalt 0.0.664: `rebar_pure.h` (ReBAR), M6 multi-display (`navi48_disp2*`, `navi48_scanx_flow.h`, `native_m6_pure.h`), G1-G5 (`native_g*_pure.h`: recovery, multisessione, app), `Navi48DisplayNub`, `navi48_dmubcmd*`, `navi48_dispread*` (diff completo in `scratchpad/cobalt/diff_q.txt`, 320 righe).

Cosa aggiunge per generalizzare l'ASIC:
1. **`src/navi48-bringup/src/amd/asic_profile.{h,cpp}`**: `enum GpuGeneration {Unknown, Navi33, Navi48}`, `struct PciIdentity {vendor, device, subsystem, subsystemVendor, revision}`, `struct AsicProfile {gen, name, bootArg, expectGfx/Psp/Smu/Sdma/Mmhub/Nbio (IPVersion), fwGfxPrefix, fwPspPrefix, fwSmuName, fwSdmaName, modulesAvailable}`; `profileForPci()`, `setActiveProfile()/activeProfile()`, `navi33KnownDeviceId()` (0x7480, 0x7481, 0x7483, 0x7489, 0x748B, 0x7499). Profili: Navi33 `{11.0.2, PSP 13.0.7, SMU 13.0.7, SDMA 6.0.2, MMHUB 3.0.0, NBIO 7.4.0, "gc_11_0_2", modulesAvailable=false}`, Navi48 `{12.0.1, 14.0.3, 14.0.3, 7.0.1, 4.1.0, NBIO "7.11.0" (sic: su RDNA4 il blocco è NBIF 6.3.1), "gc_12_0_1", true}`. Le versioni attese sono **solo un controllo incrociato loggato**: l'autorità resta la discovery (come `amdgpu_discovery.c`).
2. **`amdgpu_mmhub.{h,cpp}`**: tabella `MmhubRegs` selezionata dalla versione MMHUB scoperta (`mmhubRegsForVersion`): MMHUB 4.1.0 (`FB_LOCATION_BASE 0x0554`) vs 3.0.0 (`0x08ec`), sul modello di `gmc_v11_0.c:577-614`.
3. `Info.plist`: la personality `Navi48Bringup` accetta anche `0x74801002`; `probe()` arma Navi 33 solo con boot-arg `navi33bringup=1` e in tal caso `start()` si ferma dopo la discovery (survey read-only, nessun firmware caricato).
4. Test host `asic_profile` in `tools/conductor/suites.sh`; workflow GitHub `.github/workflows/build-kext.yml` (runner `macos-14`, clona RDNA4FB per il MacKernelSDK e linux-firmware, `make`) → build riproducibile senza un Mac.

Cosa **non** generalizza: `fw_table.cpp` e il `Makefile` sono invariati (firmware `gc_12_0_1_*` ancora cablato: i campi `fw*Prefix` del profilo non sono usati per l'embedding), le caps GFX (`gfx_v12_0.cpp:372-376`) restano cablate, nessun record Mesa per altri ASIC, display invariato. Per Navi 44 è il modello giusto (profilo per PCI id + selezione per versione IP), ma va esteso a: firmware embedded per profilo (o caricamento da file), caps GFX da `gc_info` della discovery, valori canned Mesa, mapping display dal VBIOS. Navi 44 è molto più vicino a Navi 48 di quanto lo sia Navi 33: stessa generazione per **ogni** blocco IP (GC 12.0.x, PSP/SMU 14.0.x, SDMA 7.0.x, MMHUB/ATHUB 4.1.0, NBIF 6.3.1, IH 7.0.0, HDP 7.0.0, DMU 4.1.0), quindi la tabella MMHUB di 7000-macos non serve nemmeno.

## 12. Stima effort del port su Navi 44, rischi, raccomandazione fork vs fresh

### 12.1 Cosa serve concretamente (rotta nativa soltanto)

| Lavoro | Dettaglio | Stima (1 dev esperto, con HW) | Confidenza |
|---|---|---|---|
| A. Profilo ASIC | estendere l'idea `asic_profile` di 7000-macos: match `0x7590`, firmware embedded per profilo (10 blob `gc_12_0_0_*`, `psp_14_0_2_*`, `sdma_7_0_0`, `smu_14_0_2`), nomi | 2-4 giorni | alta |
| B. Caps GFX dalla discovery | `max_shader_engines` ecc. da `gc_info` (num_se 2, sa/se 2, wgp/sa 4, rb/se 4), array harvest dimensionati, golden `DB_MEM_CONFIG` | 2-3 giorni | alta |
| C. Bring-up scala su HW | eseguire `navi48-stage=1..17` + S1b su Navi 44, correggere divergenze (PSP senza RL/RAS, SMU 14.0.2 PMFW 102.71, MES/SDMA 7.0.0) | 1-3 settimane | media (dipende da sorprese firmware) |
| D. Mesa | record canned `gfx1200` (generato da Linux), stringhe, rebase delle 9 patch se si cambia commit Mesa | 3-5 giorni | alta |
| E. Display | adattare l'adozione della pipe GOP al nostro mapping (DP=PHY A, HDMI=PHY B/C), rifare guardie per istanza, tabelle modi per i monitor dell'utente; multi-display M6 da riprogettare (oggi cablato su PHY C/PHY D) | 2-6 settimane (single display: 1-2) | media-bassa |
| F. Kext aux / layout IOAcceleratorFamily2 | **`tools/native/ioaccel-layout/` non pubblicato**: o lo si ottiene dall'autore, o si rigenera `IOAccelFamily2_decl.h`/`slots.json`/`forwarded.json` facendo RE di IOAcceleratorFamily2 e AppleParavirtGPU su 26.6.2 | 0 (se ottenuto) / 4-10 settimane (RE) | bassa |
| G. Bundle Metal | `productName`, verifica cache pipeline per device id; nient'altro ASIC-specifico | 1-2 giorni | alta |
| H. Ambiente | Hackintosh AM5 Tahoe 26.6.2 (patch AMD kernel), iGPU Raphael disabilitata o ignorata, ReBAR ≤1 GiB, AMD-Vi off/`DisableIoMapper`, RDNA4FB con `0x7590` aggiunto, Aux KC | 1-2 settimane | media |
| I. Pulizia | rimuovere rotta Apple (`src/apple`, `xlat12`, `shadercache`, `g2capture`, personality Apple, `Navi48AccelPeer`), centinaia di boot-arg di esperimenti | 1-2 settimane | alta |

**Totale "Cobalt su Navi 44, desktop GPU su un display"**: ~2-3 mesi-uomo se si ottiene `ioaccel-layout` (o se l'upstream pubblica una build con il supporto), ~4-6 mesi se va rifatto il RE del layout acceleratore. **Ripartire da zero** fino allo stesso punto (kext bring-up GC12 + VM + coda, ABI tipo DRM, backend Darwin di RADV, kext IOAccelerator, bundle Metal su Vulkan, traduzione AIR, display adottato) è stimabile in **9-18 mesi-uomo** **[INFERITO]**: Cobalt stesso dichiara 664 build e una catena di milestone (Phase 3, M2-M6, G1-G6, native #9-#12).

### 12.2 Rischi principali

1. **Parti mancanti** (alto): `ioaccel-layout` (kext aux non compilabile), note di design interne citate ovunque, generatori `tools/auto-ws`. Snapshot senza storia git: impossibile fare bisect o seguire upstream in modo pulito.
2. **Fragilità macOS** (alto): tutto il glue Metal/IOAccelerator è tarato su Tahoe 26.6.2 / 25G83; ogni aggiornamento può rompere layout vtable, `IOAccelConfig`, classi private `MTLIOAccelDevice`/`_MTL*`. Bisogna congelare la versione di macOS.
3. **Display specifico della scheda** (alto per multi-monitor, medio per singolo): mapping DIG/PHY/DDC/HPD e timing cablati per la RX 9070 XT e i monitor dello sviluppatore; la nostra Sapphire ha DP su PHY A e non ha PHY D. Nessun link training DP né calcolo DML generico.
4. **Firmware Navi 44** (medio): container SOS senza RL/RAS (gestito dal codice, ma mai provato), PMFW 14.0.2 diverso; nessuna golden; MES/RLC/IMU di gc_12_0_0 mai eseguiti da questo codice. Mitigazione: confrontare passo per passo con le tracce di Linux su questa stessa macchina (MQD e ring già dumpati in `hw_dump/mqd`, `hw_dump/rings`).
5. **ReBAR/IOPCIFamily** (medio): BAR0 ≤1 GiB obbligatoria; visibilità VRAM limitata.
6. **Assenza di reset/recovery** (medio): ogni hang = reboot; sviluppo lento (ciclo ESP + reboot).
7. **Prestazioni/compatibilità** (medio): una sola coda GFX, niente DCC, niente argument buffers Tier2/ICB/ray tracing; app non nella allow-list escluse; traduzione AIR→SPIR-V da metal2vulkan (LGPL, terzo).
8. **Licenze** (basso-medio): mix MIT (radice) + BSD-3 (kext) + LGPL-3 (n48xlate) + firmware AMD; codice derivato da mac-amdgpu (MIT) e RDNA4FB (BSD-3) con obblighi di attribuzione; asset derivati da Apple deliberatamente esclusi (vanno tenuti fuori anche da noi).
9. **Qualità/manutenibilità** (medio): file monolitici (8 971 righe, 2,4 MB), migliaia di commenti a numero di build; difficile da rivedere e da far evolvere.

### 12.3 Raccomandazione

**Fork selettivo della sola rotta nativa, non fork integrale e non ripartenza da zero.**
- Prendere da Cobalt (con attribuzione e licenze): `src/navi48-bringup/src/amd/*` tranne gli header `gfx_*`/Apple (scala PSP→SDMA, GMC/GART, IH, MES, native S1b/S1c), `Navi48NativeABI.h` + `Navi48NativeClient` (ABI N48N mantenuta **compatibile** per riusare le 9 patch Mesa), `Navi48MetalNub` + `Navi48MetalOps.h`, il kext aux e il bundle `navi48metal` (a condizione di ottenere/rigenerare `ioaccel-layout`), `src/dcn41` (layer registri + allowlist: le basi DMU sono identiche), l'infrastruttura di test host (`*_pure.h` + planted break) e `rebar_pure.h`.
- **Scartare**: `src/apple/*`, `src/xlat12`, `src/shadercache`, `src/g2capture`, personality Apple, esperimenti numerati, autoarm (da riscrivere più semplice).
- **Rifare in modo generico**: profilo ASIC (PCI id → firmware, caps da discovery, come 7000-macos ma completo), record Mesa `gfx1200`, display (mapping connettori dal `displayobjectinfo` del VBIOS — già parsato nel run precedente — invece di costanti; modi da EDID).
- **In parallelo**: contattare gli autori di Cobalt64 (che dichiarano di volere altre GPU "and someone with that hardware to test it") per ottenere `ioaccel-layout` e coordinare un supporto Navi 44 upstream: è il percorso con il miglior rapporto costo/rischio, perché Navi 44 condivide con Navi 48 **tutte** le versioni di blocco IP, le basi registri, il `GB_ADDR_CONFIG`, la dimensione VRAM (16 GB) e i formati firmware.
- Ripartire da zero ha senso solo se l'obiettivo è un'architettura diversa (es. DriverKit/PCIDriverKit come mac-amdgpu, o un approccio alla nullmoth con command buffer Metal → PM4 diretto senza Vulkan): in quel caso Cobalt resta comunque la miglior documentazione eseguibile del glue macOS (IOAccelerator/Metal plugin) per RDNA4.

## 13. Domande aperte e dati da raccogliere

1. Ottenere da Cobalt64 `tools/native/ioaccel-layout/` (`generated/IOAccelFamily2_decl.h`, `slots.json`, `forwarded.json`) e `tools/auto-ws/` — o pianificare il RE di IOAcceleratorFamily2/AppleParavirtGPU su 26.6.2.
2. Quale output accende il GOP UEFI della Sapphire 9060 XT con 1/2/3 monitor collegati (quale OTG/DIG/PHY risulta "lit" a inizio boot): serve per l'adozione della pipe console. Leggibile su Linux solo con debugfs/registri DCN (privilegiato) → da fare con l'utente.
3. Comportamento di IOPCIFamily di Tahoe con BAR0 da 16 GiB su questa scheda madre MSI B840 (Cobalt afferma limite 1 GiB): verificare su macOS installato; decidere tra ReBAR off (256 MiB) e `ResizeAppleGpuBars` a 1 GiB.
4. Verificare a runtime che il bootloader PSP 14.0.2 accetti la catena senza RAS_DRV/RL e che `psp_asd_initialize` non-op sia tollerato anche da SOS 0x003b0f0d.
5. Generare il record canned `gfx1200` interrogando libdrm su `renderD128` (non privilegiato) e confrontarlo con i valori di Sez. 10.3.
6. Confermare la topologia connettori finale con l'EDID dei monitor dell'utente (risoluzioni/refresh da supportare in prima battuta).
7. Licenze: chiarire con gli autori la coesistenza MIT (radice) / BSD-3 (kext) per un fork redistribuito.
