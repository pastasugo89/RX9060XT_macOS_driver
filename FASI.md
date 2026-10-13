# Fasi di sviluppo: port di Cobalt64 su RX 9060 XT (Navi 44)

Base: `cobalt64/` (subtree dello snapshot `d6c9aed` del 9/10/2026, licenze MIT/BSD-3/LGPL rispettate).
Riferimenti tecnici: `PIANO_DRIVER_METAL_RX9060XT.md` (piano completo) e `research/reports/` (in particolare il 05,
che elenca con file:riga ogni valore Navi 48 cablato in Cobalt64 e il valore Navi 44 corrispondente).

Target macOS: **Tahoe 26.6.2 (build 25G83)**, la stessa di Cobalt64, perché il loro glue Metal/IOAccelerator è tarato lì.

Legenda stato: ⬜ da fare · 🟨 in corso · ✅ fatto

---

## Fase 0 — Ambiente e dati di riferimento

| # | Attività | Stato |
|---|---|---|
| 0.1 | Repository git del progetto con Cobalt64 come subtree, analisi e piano | ✅ |
| 0.2 | Repository GitHub privato collegato (`git remote add origin …`) | ⬜ (lo predispone l'utente) |
| 0.3 | Strumenti RE su Linux: Ghidra 12.1.2 + REA 6.4.0 (MCP `rea` + skill `reverse-engineer-anything` in Claude Code) | ✅ |
| 0.4 | Precauzioni BIOS/dischi (piano §12.4) e SSD dedicato a macOS | ⬜ |
| 0.5 | Dati display con la RX 9060 XT ancora primaria (`research/display/`): EDID, link DP, stato atomico, DTN log a 180 Hz ✅; **manca** lo stato GOP con `amdgpu` in blacklist (serve un riavvio) | 🟨 |
| 0.6 | VM macOS Tahoe 26.6.2 (build + test) con passthrough VFIO, seriale e gdbstub; workaround reset | ⬜ |
| 0.7 | Traccia d'oro MMIO di `amdgpu` in VM Linux, partendo da scheda mai inizializzata | ⬜ |
| 0.8 | Installer 25G83 verificato (SHA-1) ed estratto in `research/macos/` (fuori da git): kext grafici, kernel, Boot/System KC, driver Metal paravirtuale. REA via CLI con Ghidra 12.1.2 + JDK portatile. Mancano: kext come Mach-O singoli (fuori dalle KC), cryptex RIDIFF con Metal.framework, KDK. Dettagli: `research/reports/macos_25G83_re.md` | 🟨 |

**Uscita**: VM macOS 26.6.2 che avvia con la scheda assegnata e log seriale; binari Apple disponibili per l'analisi.

## Fase 1 — Pulizia e profilo ASIC (nessun hardware necessario)

| # | Attività | File principali in `cobalt64/` | Stato |
|---|---|---|---|
| 1.1 | Rotta Apple fuori dalla build (`make APPLE_ROUTE=0`, default): esclusi AppleHardwareHook, Navi48AccelPeer, Navi48Ttl, AppleTtlHook, xlat12, shadercache (~41 000 righe); `src/native/apple_route_off.cpp` dà ai 95 simboli ancora referenziati il comportamento di default, il codice nativo (limite RAM, uptime) è copiato lì; DisplayPipeGuard resta (AGDC nativo, scanout). Personality Apple già tolte dal plist. Dettagli: `research/reports/apple_route_split.md`. Cancellazione definitiva dopo i test su hardware | `src/native/`, `Makefile`, `Navi48Bringup.cpp` | ✅ |
| 1.2 | Profilo ASIC a compile time (`make ASIC=navi44` default / `navi48`): firmware, ID PCI in `probe()` e nel plist | `src/amd/asic_profile.h`, `Navi48Bringup.cpp`, `Info.plist`, `Makefile` | ✅ |
| 1.3 | Firmware per profilo: insieme Navi 44 (`gc_12_0_0_*`, `psp_14_0_2_*`, `smu_14_0_2`, `sdma_7_0_0`), sha256 verificati; `fetch-firmware.sh /usr/lib/firmware` | `Makefile`, `src/amd/fw_table.cpp`, `tools/fetch-firmware.sh` | ✅ |
| 1.4 | Caps GFX dalla tabella discovery (`IpDiscovery::gcInfo`, come Linux) con ripiego sul profilo e limiti sugli array | `src/ipdiscovery.*`, `amdgpu_regs.h`, `gfx_v12_0.cpp` | ✅ |
| 1.5 | Golden `DB_MEM_CONFIG |= 0x8000` (assente in Cobalt64) | `src/amd/gfx_v12_0.cpp`, `amdgpu_gfx.h` | ✅ |
| 1.6 | Shader di self-test: verificato che il codice per gfx1200 è identico byte per byte a quello per gfx1201 (nessuna modifica necessaria) | `shaders/*.bin` | ✅ |
| 1.7 | Test host: `tools/hosttests/run.sh` (discovery/gc_info sui dump reali) e `tools/hosttests/run-cobalt64-tests.py`, che esegue su Linux i 108 test di Cobalt64 per profilo e li confronta con `cobalt64-baseline.txt` (65 PASS su entrambi i profili; i 13 FAIL e 28 BUILD sono identici sull'albero originale d6c9aed: dipendono da file non pubblicati da Cobalt64) | `tools/hosttests/` | ✅ |
| 1.8 | Controllo di compilazione da Linux di tutti i sorgenti del kext (MacKernelSDK + clang) | `tools/linux-check-kext.sh` | ✅ |

**Uscita**: il kext compila per entrambi i profili (Navi 44 e Navi 48), test host verdi.

## Fase 2 — Bring-up hardware su Navi 44 (in VM)

| # | Attività | Stato |
|---|---|---|
| 2.0 | Stato iniziale: se `C2PMSG_81` ≠ 0 → mode1 via SMU + `asic_init` AtomBIOS (interprete minimo) | ⬜ |
| 2.1 | Scala `navi48-stage=1..17` su Navi 44: discovery, IH, GMC, PSP (sOS senza RAS/RL), SMU 14.0.2, IMU/RLC, CP, MES, SDMA. Preparazione da Linux ✅ (`research/reports/navi44_kernel_checks.md`): nessun controllo di versione esclude Navi 44; parser PSP e estrattore firmware del kext PASS sui blob reali; RAS/RL assenti gestiti. Esecuzione su hardware: da fare | 🟨 |
| 2.2 | SMU: verifica FAN_CONTROL/THROTTLERS/FW_CTF attivi prima di carichi prolungati | ⬜ |
| 2.3 | Confronto con la traccia d'oro e con MQD/ring di `research/hw_dump/` | ⬜ |
| 2.4 | Compute di test (`research/artifacts/compute/kernels/`) e self-test S1b (VMID 8) | ⬜ |
| 2.5 | ReBAR: Tahoe (IOPCIFamily di 25G83) non ridimensiona i BAR; decisione: OpenCore `ResizeGpuBars = 10` (BAR0 1 GiB), coerente con `rebar_pure.h` (`research/reports/macos_25G83_re.md` §4e) | ✅ |

**Uscita**: stage 17 + S1b positivi su Navi 44, 20 avvii consecutivi della VM.

## Fase 3 — RADV su macOS

| # | Attività | Stato |
|---|---|---|
| 3.1 | Patch Mesa 0010: profilo ASIC del backend Darwin (`ac_darwin_asic.h`, default gfx1200) e record canned gfx1200 con i valori reali; verificata con drm-shim (`tools/mesa-shim-check.sh`), test host Darwin e `-fsyntax-only` di entrambi i profili | ✅ |
| 3.2 | Id PCI reale `0x7590`, nome "AMD Radeon RX 9060 XT" (in 0010) | ✅ |
| 3.3 | `vulkaninfo` e sottoinsieme CTS confrontati con Linux | ⬜ |

## Fase 4 — Display (adozione del GOP)

| # | Attività | Stato |
|---|---|---|
| 4.1 | Mappa connettori dal VBIOS (`tools/vbios_display_objects.py`): DP = PHY A/AUX0/HPD1, HDMI = PHY B/HPD2 e PHY C/HPD3, niente PHY D ✅. Sostituzione delle costanti di `navi48_disp2.h`/`navi48_dmubcmd.h`/guardie: piano in `research/display/README.md` §4, dopo l'osservazione del GOP | 🟨 |
| 4.2 | Adozione della pipe GOP e flip su HUBP; RDNA4FB con `0x7590` per la console (RDNA4FB **non è nel repository pubblico** di Cobalt64: il Makefile lo cita solo per `MacKernelSDK`, da passare con `MKSDK=`) | ⬜ |
| 4.3 | Tabella dei modi per scheda: `ASIC=navi44 tools/dcn41/gen_modes.py` legge EDID (base, CTA, DisplayID) → `dcn41_modes_navi44.h` (5 modi fino a 180 Hz, registri OTG uguali al DTN log); `dcn41_modes.h` sceglie per profilo | ✅ |

### ⏸ In sospeso (decisione del 12/10/2026)

Il completamento di 0.5, 4.1 e 4.2 è **sospeso**. Serve un avvio con `amdgpu` disattivato per leggere, in sola
lettura, quale pipe (OTG / DIG / PHY) accende il GOP sulla nostra scheda; senza quel dato non si adattano le
guardie e le istanze di `navi48_disp2.h` / `navi48_dmubcmd.h` (piano in `research/display/README.md` §4).
Da riprendere quando l'utente può fare il riavvio. Fatto finora: mappa connettori, dati del monitor, tabella dei modi.

## Fase 5 — Acceleratore e bundle Metal

| # | Attività | Stato |
|---|---|---|
| 5.1 | Layout di IOAcceleratorFamily2 per 25G83. Fatto: modello `MTLIOAccel*` + ABI `IOAccelNewResourceArgs`/`IOAccelKernelCommand`/`IOAccelResourceList`, simboli e indirizzi delle 125 vtable (`research/macos/25G83/symbols/`). **Messo da parte (decisione utente 13/10/2026)**: il layout slot per slot delle vtable estratto dalle Kernel Collection, bloccato due volte dal controllo di sicurezza; da riprendere solo con il KDK (kext separati) o con un'esportazione fatta dall'utente con Ghidra | ⏸ |
| 5.2 | Compilare `tools/native/navi48accel` e verificare i "layout gate" a runtime | ⬜ |
| 5.3 | Bundle `navi48metal`: profilo ASIC (`n48_asic.h`, `build.sh ASIC=navi44` default): nome "AMD Radeon RX 9060 XT", controllo che il RADV incluso riporti 1002:7590; limiti verificati sul vulkaninfo reale ✅. Da fare su macOS: build con RADV patch 0001-0010, census dei selettori (`N48M_CENSUS=1`) per l'allineamento ai protocolli Metal di 25G83, poi WindowServer | 🟨 |

**Uscita**: desktop composto da WindowServer sulla RX 9060 XT.

## Fase 6 — Oltre Cobalt64

Reset/recupero, power management completo, multi-monitor sulla nostra scheda, HDMI 4K, Safari/Chromium, metal2vulkan
0.2, user queue, DCC: vedi piano §14 (M7-M9).
