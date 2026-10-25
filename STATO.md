# Stato del progetto — 25 ottobre 2026

Driver Metal per **AMD Radeon RX 9060 XT** (Navi 44, `1002:7590`) su macOS Tahoe 26.6.2 (build 25G83), come port di
[Cobalt64](cobalt64/README.md) (RX 9070 XT). Dettaglio fase per fase in [`FASI.md`](FASI.md); qui il quadro d'insieme.

## In una riga

Lo stack del driver funziona sulla GPU (bring-up, compute, Metal headless verificato), ma **il desktop accelerato a
video non è ancora stato ottenuto**: in VM WindowServer non manda lavoro al nostro display, e il passaggio al bare
metal è fermo a un blocco del kernel durante l'avvio del ripristino di macOS.

## Cosa funziona (verificato su hardware, nella VM con la GPU in passthrough)

| Area | Risultato | Riferimento |
|---|---|---|
| Bring-up GPU | PSP, SMU, IMU/RLC, GFX, MES, SDMA fino allo stage 17; ACK GFXHUB | `research/reports/gfxhub_ack_compute.md` |
| Compute | shader baseline 32/32, `vadd_ir` gfx1200 corretto, VMID8 positivo e recupero da fault | `research/reports/phase2_mes_fault_checkpoint.md` |
| Acceleratore IOAccelerator | layout da `ioaccel-layout` upstream: MATCH 3150 slot; kext aux compilato, gate A/B/C verdi, caricato in macOS | `research/reports/ioaccel_layout_upstream.md` |
| **Metal headless (P0)** | `MTLDevice` "AMD Radeon RX 9060 XT"; quadrato e triangolo identici al pixel al riferimento; compute PASS; hot-swap shader PASS | `research/reports/p0_headless_metal.md` |
| Display (lettura) | il GOP accende OTG0/HUBP0/DIG0/PHY A (DP) a 2560x1440@120; superficie ARGB8888 lineare pitch 2560 | `research/display/gop_vm_readout_plan.md` |
| Display (macOS) | RDNA4FB v8 su `0x7590`: modo 2560x1440@120 installato, monitor **display principale** anche dopo il riavvio di WindowServer; VBL emulato attivo; pipe adottata/armata, AGDC pubblicato | `research/reports/p1_p2_display.md` |
| Sicurezza della scheda | watchdog nel kext (sensore THM, TRIP 80 °C) + watchdog host (chiude la VM); protezioni firmware verificate attive; nessuna scrittura di tensioni, clock, curve ventola o flash | `research/reports/gpu_safety.md` |

## Dove siamo bloccati

### 1. Desktop accelerato in VM (P2)

WindowServer attiva il compositor Metal sul nostro device e il nostro monitor è principale, ma **non arriva nessuna
transazione alla display pipe** (`command_buffers=0`, `frames=0`, `submit 0`). A video: login window ridisegnata,
orologio assente, nessuna trasparenza. Provati senza esito: VBL emulato (`rdna4-vbl=1`), boot-arg della ricetta
Cobalt64 (`navi48-multisession`, `navi48-apps`, `npci`). Analisi: `research/reports/compositor_diag.md`,
`research/reports/p2_vs_cobalt_recipe.md`, `research/reports/coredisplay_re.md`.

Ipotesi di fondo: alcune differenze dell'ambiente VM (GPU sul bus 0, SMC emulato, nessuna topologia PCIe reale) che
Cobalt64 su bare metal non ha. Per questo il lavoro si è spostato sul bare metal.

### 2. Bare metal (dal 23/10)

Chiavetta di avvio con OpenCore 1.0.8 + ripristino di Tahoe 25G83. Dopo sei avvii:

- risolti l'abort di `boot.efi` e lo `STOP 0x16` (memoria) con `DevirtualiseMmio`;
- **il kernel parte** sul Ryzen 7 7700 (patch AMD tutte applicate);
- **blocco totale dopo `CoreAnalyticsHub start completed`** (tastiera morta), invariato con: grafica integrata spenta,
  `-amd_no_dgpu_accel`, due patch ACPI della DSDT AGESA.

Report completo, cronologia, ipotesi e passi successivi: [`research/reports/baremetal_bringup.md`](research/reports/baremetal_bringup.md).

**Prossimo passo proposto**: avvio 7 con **Resizable BAR disattivato** e **porta seriale disattivata** nel BIOS
(configurazione delle EFI AM5 funzionanti), senza toccare la chiavetta.

## Promemoria operativi

- **BIOS ora**: grafica integrata **disattivata** (da riattivare per le prove in VM con VFIO).
- Le prove in VM richiedono la voce GRUB VFIO "una tantum" (`tools/vm/prepare-vfio-test-boot.py arm` + riavvio), poi
  BAR0 a 256 MiB (`tools/vm/resize-vfio-bar.py 8`) e `memlock` ≥ 14 GiB per il processo che lancia la VM.
- La chiavetta da 128 GB contiene dati personali: si scrive solo nella cartella `macOS-Tahoe-25G83-installer/`.
- Ultimo commit: `41ea997` (21/10). Il lavoro successivo (RDNA4FB v2–v8, sicurezza, stack Metal, tool VM, EFI bare
  metal) è nel working tree, non ancora committato; le EFI e i log hardware sotto `research/ext/` restano fuori da git.
