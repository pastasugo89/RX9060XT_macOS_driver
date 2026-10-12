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
| 0.5 | Dati display con la RX 9060 XT ancora primaria: EDID, log DTN per modo, stato GOP con `amdgpu` in blacklist | ⬜ |
| 0.6 | VM macOS Tahoe 26.6.2 (build + test) con passthrough VFIO, seriale e gdbstub; workaround reset | ⬜ |
| 0.7 | Traccia d'oro MMIO di `amdgpu` in VM Linux, partendo da scheda mai inizializzata | ⬜ |
| 0.8 | KDK di 25G83 + estrazione dei binari Apple da analizzare (IOAcceleratorFamily2, IOGraphicsFamily, AppleParavirtGPU, Metal.framework dal dyld shared cache) | ⬜ |

**Uscita**: VM macOS 26.6.2 che avvia con la scheda assegnata e log seriale; binari Apple disponibili per l'analisi.

## Fase 1 — Pulizia e profilo ASIC (nessun hardware necessario)

| # | Attività | File principali in `cobalt64/` | Stato |
|---|---|---|---|
| 1.1 | Rimuovere la "rotta Apple" — **parziale**: tolte dal plist le 3 personality che caricavano i kext AMD di Apple; il codice resta perché anche la rotta nativa usa header in `apple/` (da separare a passi) (hook in AMDRadeonX6000, xlat12, shadercache, g2capture, personality Apple, AccelPeer) | `src/navi48-bringup/src/apple/`, `src/xlat12/`, `src/shadercache/`, `src/g2capture/`, `Info.plist` | ⬜ |
| 1.2 | Profilo ASIC a compile time (`make ASIC=navi44` default / `navi48`): firmware, ID PCI in `probe()` e nel plist | `src/amd/asic_profile.h`, `Navi48Bringup.cpp`, `Info.plist`, `Makefile` | ✅ |
| 1.3 | Firmware per profilo: insieme Navi 44 (`gc_12_0_0_*`, `psp_14_0_2_*`, `smu_14_0_2`, `sdma_7_0_0`), sha256 verificati; `fetch-firmware.sh /usr/lib/firmware` | `Makefile`, `src/amd/fw_table.cpp`, `tools/fetch-firmware.sh` | ✅ |
| 1.4 | Caps GFX dalla tabella discovery (`IpDiscovery::gcInfo`, come Linux) con ripiego sul profilo e limiti sugli array | `src/ipdiscovery.*`, `amdgpu_regs.h`, `gfx_v12_0.cpp` | ✅ |
| 1.5 | Golden `DB_MEM_CONFIG |= 0x8000` (assente in Cobalt64) | `src/amd/gfx_v12_0.cpp`, `amdgpu_gfx.h` | ✅ |
| 1.6 | Shader di self-test: verificato che il codice per gfx1200 è identico byte per byte a quello per gfx1201 (nessuna modifica necessaria) | `shaders/*.bin` | ✅ |
| 1.7 | Test host dei parser con i dump reali: `tools/hosttests/run.sh` (discovery/gc_info) — da estendere | `tools/hosttests/` | 🟨 |
| 1.8 | Controllo di compilazione da Linux di tutti i sorgenti del kext (MacKernelSDK + clang) | `tools/linux-check-kext.sh` | ✅ |

**Uscita**: il kext compila per entrambi i profili (Navi 44 e Navi 48), test host verdi.

## Fase 2 — Bring-up hardware su Navi 44 (in VM)

| # | Attività | Stato |
|---|---|---|
| 2.0 | Stato iniziale: se `C2PMSG_81` ≠ 0 → mode1 via SMU + `asic_init` AtomBIOS (interprete minimo) | ⬜ |
| 2.1 | Scala `navi48-stage=1..17` su Navi 44: discovery, IH, GMC, PSP (sOS senza RAS/RL), SMU 14.0.2, IMU/RLC, CP, MES, SDMA | ⬜ |
| 2.2 | SMU: verifica FAN_CONTROL/THROTTLERS/FW_CTF attivi prima di carichi prolungati | ⬜ |
| 2.3 | Confronto con la traccia d'oro e con MQD/ring di `research/hw_dump/` | ⬜ |
| 2.4 | Compute di test (`research/artifacts/compute/kernels/`) e self-test S1b (VMID 8) | ⬜ |
| 2.5 | ReBAR: decidere la dimensione di BAR0 accettata da IOPCIFamily di Tahoe (`rebar_pure.h` limita a 1 GiB) | ⬜ |

**Uscita**: stage 17 + S1b positivi su Navi 44, 20 avvii consecutivi della VM.

## Fase 3 — RADV su macOS

| # | Attività | Stato |
|---|---|---|
| 3.1 | Applicare le 9 patch Mesa su `f5cb8ee` e sostituire il canned `gfx1201` con i valori reali gfx1200 (`research/artifacts/mesa-radv/gfx1200_canned_dump.txt`) o con un `QUERY_DEVICE` dal kext | ⬜ |
| 3.2 | Id PCI reale `0x7590`, nome "AMD Radeon RX 9060 XT" | ⬜ |
| 3.3 | `vulkaninfo` e sottoinsieme CTS confrontati con Linux | ⬜ |

## Fase 4 — Display (adozione del GOP)

| # | Attività | Stato |
|---|---|---|
| 4.1 | Mappa connettori dal VBIOS (DP = PHY A, HDMI = PHY B/C; niente PHY D) al posto delle costanti di `navi48_disp2.h` | ⬜ |
| 4.2 | Adozione della pipe GOP e flip su HUBP; RDNA4FB con `0x7590` per la console | ⬜ |
| 4.3 | Modi dalle EDID dei monitor dell'utente (dati della fase 0.5) | ⬜ |

## Fase 5 — Acceleratore e bundle Metal

| # | Attività | Stato |
|---|---|---|
| 5.1 | Ricostruire il layout di IOAcceleratorFamily2 per 25G83 (il generatore `tools/native/ioaccel-layout` di Cobalt64 non è pubblico): header, `slots.json`, `forwarded.json` | ⬜ |
| 5.2 | Compilare `tools/native/navi48accel` e verificare i "layout gate" a runtime | ⬜ |
| 5.3 | Bundle `navi48metal`: nome prodotto, id device, poi WindowServer | ⬜ |

**Uscita**: desktop composto da WindowServer sulla RX 9060 XT.

## Fase 6 — Oltre Cobalt64

Reset/recupero, power management completo, multi-monitor sulla nostra scheda, HDMI 4K, Safari/Chromium, metal2vulkan
0.2, user queue, DCC: vedi piano §14 (M7-M9).
