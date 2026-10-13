# Codice kernel su Navi 44: verifiche da Linux (fase 2, preparazione)

Data: 13/10/2026. Kext: `cobalt64/src/navi48-bringup/` (profilo navi44). Test: `tools/hosttests/run.sh`.

## 1. Versioni IP della RX 9060 XT (tabella discovery reale)

| IP (hwId) | Navi 44 | Navi 48 (Cobalt64) |
|---|---|---|
| GC (11) | 12.0.0 | 12.0.1 |
| MP0 / PSP (255) | 14.0.2 | 14.0.3 |
| MP1 / SMU (1) | 14.0.2 | 14.0.3 |
| SDMA (42/43) | 7.0.0 | 7.0.1 |
| MMHUB (34) | 4.1.0 | 4.1.0 |
| OSSSYS / IH (40) | 7.0.0 | 7.0.0 |
| HDP (41) | 7.0.0 | 7.0.0 |
| NBIF (108) | 6.3.1 | 6.3.1 |
| UMC (150) | 8.14.0 | — |
| DMU (271) | 4.1.0 | 4.1.0 |
| VCN (12) | 5.0.0 | — |

## 2. Dove il codice dipende dalla versione

- `amd/amdgpu_ip.h` `kIP_*` (GFX 12.0.1, SDMA 7.0.1, PSP/SMU 14.0.3, MES 12.0.1): **solo per i log**, più un ramo
  `kIP_PSP.major == 14` in `psp_v14_0.cpp`, vero per entrambe le schede.
- Le scelte sulle versioni scoperte sono per famiglia: SDMA e GFX usano la tabella 12.0.x (`sdma_pick_reg_table`), NBIF
  quella diretta (6.3.1 < 7.11.4, uguale per entrambe). **Nessun controllo esclude Navi 44.**
- SMU 14.0.2 contro 14.0.3 in Linux (`smu_v14_0_2_ppt.c`): l'unica differenza funzionale è `enable_gfx_features`
  (`SMU_MSG_EnableAllSmuFeatures` con `FEATURE_PWR_GFX`, solo su 14.0.2). È usata solo dal percorso di reset
  (`asic_reset_enable_gfx_features`), che in questo kernel ha un solo chiamante, SMU 13.0.10: **non serve nel
  bring-up**. Da ricordare per il recupero dopo un reset (fase 6).

## 3. Firmware PSP (`psp_14_0_2_sos.bin`)

Parser del kext (`psp.cpp` `PspLoader::parseContainer`) eseguito sul blob installato (linux-firmware 20260916):

| Sotto-immagine | 14.0.2 (Navi 44) | 14.0.3 (Navi 48) |
|---|---|---|
| kdb / spl / sys_drv / sos / soc_drv / intf_drv / dbg_drv / ipkeymgr / toc | presenti | presenti |
| **ras_drv** | **assente** | 12 704 B |
| **rl** | **assente** | 1 712 B |
| spdm | assente | assente |

La catena del kext salta i componenti assenti (`psp.cpp` `loadComponent`: "not in container, skipping";
`psp_v14_0.cpp` `rl_load`: "psp.rl absent … skipping"), come Linux. Prerequisiti presenti: PASS.

## 4. Firmware GC e SDMA (`amd/amdgpu_ucode_extract.cpp`)

Estrattore del kext sui blob di entrambe le schede: stesso numero di payload per file (RLC 5, IMU 2, MES unificato 4,
PFP 2, ME 2, MEC 3, SDMA 1). Tutti i payload sono non vuoti e dentro il file: **PASS**. Cambiano solo le dimensioni
(es. MEC 455 648 B contro 451 552 B).

## 5. Infrastruttura dei test host

`tools/hosttests/stub/IOKit/` contiene i sostituti minimi di `IOLib.h` (`IOLog`, `IOSleep`, `IODelay`) e
`IOReturn.h` (tipi e codici). Bastano per compilare su Linux i moduli puri del kext che li includono. Servono
`clang++` (per la dichiarazione di `memcpy` del kext senza `noexcept`) e `zstd` per i blob installati.
