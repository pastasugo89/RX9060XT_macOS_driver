# GFXHUB ACK e primo compute Navi44 — 20 ottobre 2026

## Stato corrente — boot13, 20 ottobre 2026

L'ACK mancante è risolto senza aggirare il controllo: RS64 viene predisposto
prima del GFXHUB. Sono stati completati 13 boot stage17 sulla RX9060XT reale
1002:7590, Tahoe 26.6.2/25G83. Compute baseline32/32; le20 ripetizioni
compute sono solo nei boot1–2, non sono boot. S1b VMID8 è PASS completo nel
boot6 (positive4/4, fault e recovery EOP). Il kernel aggiuntivo `vadd_ir`
gfx1200 ha PASS definitivo al boot12: 32 somme e canary corretto.

Il boot13 ha stage17 result0 e compute32/32, ma non è pulito: IH6/7 con EOP4,
fault3 e CP-error0. I fault spontanei sono GFX ring169 VMID0 VA0 write dopo
SET_HW_RSRC (`0x40b52`), poi ring153 VMID0 VA0 read e ring169 write dopo
SET_HW_RSRC_1 (`0x40b53`). Il timeout KIQ SET1 è stato corretto a `0xA` da
Linux `mes_v12_0.c`; i fault persistono e il primo precede SET1. Non avviare
la serie di20 boot consecutivi finché questo esito non è classificato.

Oracle Linux idle ha inizializzato MES senza fault, con stessi blob firmware;
GART Linux è `0..0x1fffffff` (512 MiB) contro GART locale alto
`0x8400000000..0x840fffffff` (256 MiB). Contratto PTE0/placement è la prossima
indagine, non una causa dimostrata e nessun alias è stato aggiunto. Reset VFIO
GPU/audio registrato, ma reset ASIC completo non provato. VM spenta, EFI stage17
senza IRQ/native/vadd opt-in. Fase2 resta aperta; nessun IOAccelerator, Metal o
WindowServer sulla RX.

Dettagli e piano di ripresa: [`phase2_mes_fault_checkpoint.md`](phase2_mes_fault_checkpoint.md).
Le sezioni seguenti riportano la cronologia dei boot antecedenti e non
sostituiscono lo stato aggiornato sopra.

## Causa e correzione

Il percorso originale attivava GFXHUB e attendeva l'invalidazione prima di
preparare i front end RS64. Richiesta0x00f80001 a dword0x28b8, ACK0 a0x28ca,
anche dopo l'attesa: CPInit arrestato con reached11. GFXOFF disabilitato
con risposta SMU positiva da solo non aveva risolto il problema.

In `research/src/linux/drivers/gpu/drm/amd/amdgpu/gfx_v12_0.c`,
`gfx_v12_0_hw_init` configura RS64 prima di `gfx_v12_0_gfxhub_enable` sul
percorso PSP. [Sorgente Linux ufficiale](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/gfx_v12_0.c).
Gli indirizzi/mask della richiesta corrispondono anche al dump Linux locale
`research/hw_dump/rings/decoded_mes_3.1.0.txt`.

Nuovo `cp_prepare_rs64`: arresta PFP/ME/MEC, configura cache e PC/reset RS64,
senza allocare/mappare queue né avviarle. CPInit lo chiama dopo aver copiato
gli indirizzi firmware PSP e prima di `ensure_gfxhub_gart`. `cp_init_full`
riusa la preparazione già conclusa e non ripete il reset dopo l'ACK.
Il flush obbligatorio restituisce ora `req=0xf80001 acked`; lettura tardiva
0x28ca=1 in entrambi i test compute. Questo conferma la correzione nel
percorso provato; non dimostra un reset completo indipendente dallo stato ereditato.

Aggiunto anche il ripristino del limite Low sul percorso di errore della scala
quando SMU è disponibile, per mantenere il limite richiesto anche se uno stage fallisce.

## Prove e identità build

Prima build con ordine corretto:
`92a15b2e78ab48a8d57e3a9ddd4c5a5a7cc02c59c72170b0836f3baff91d0400`.
Passa stage12, poi stage17 e10ripetizioni.

Build finale (anche messaggio shader reso indipendente dal nome RX9070XT):
`15ceb12ceb2b2fe05b49268b094e066b7392e0716895f993488c1fda30b4d1e2`.
Passa un secondo avvio stage17 e10ripetizioni. Entrambe sono build Navi44,
APPLE_ROUTE=0, x86_64, firma ad hoc verificata; versione comune0.0.664,
quindi usare il digest per distinguerle.

Stage16: queue GFX mappata da MES, fetch/scratch PM4 passati, EOP fence
completata, WRITE_DATA VRAM corretto, queue compute mappata e MEC WRITE_DATA passato.
Stage17: shader scrive `0xca11ed47+lane` in VRAM,32valori corretti su32,
lettura attraverso MM_INDEX e verifica dei limiti della scrittura.
IORegistry: StageReached17, StageResult0, ComputeDispatch/SDMACopy/CPRing/
CPEop/CPWriteData/ComputeQueue passati, ComputeLanesCorrect32.

Dopo ciascun lotto da10: ACK0x28ca=1; fault status GFXHUB0x2830=0 e
MMHUB0x1a4f0=0. I contatori interrupt sono0 perché la CPU lavora in polling:
non usarli da soli come prova di assenza di fault. Durante l'inizializzazione
è stato osservato uno stato GCVM precedente ai test (0x00040b53, pagina0),
azzerato dal driver: resta da chiarire, quindi non si dichiara startup senza fault.
Il tempo0us è granularità della misura/polling, non un benchmark.

## Riproduzione e artefatti

`tools/vm/prepare-gpu-test-stage.py 17 --kext PERCORSO_BUNDLE` richiede VM
spente e lock, valida bundle/PCI/MachO, inietta tre file e li rilegge byte per
byte, verifica qcow2 e salva digest EFI. Il launcher accetta ora16/17 su
richiesta esplicita compute, mantenendo interrupt e stack Metal esclusi.
Per la verifica VMID8 la preparazione stage17 accetta anche `--native-s1b`,
che aggiunge solo `navi48-native=1`; il launcher verifica la corrispondenza tra
il flag nel piano e l'EFI. Dopo la prova il piano è tornato a stage17 senza
questo opt-in.

Host stesso bootVFIO `5381cd45-5f57-45bb-8608-692271210fd3`, Linux su iGPU,
GPU/audio vfio-pci, BAR0 256MiB, VM separata con overlay sul backup
`/mnt/vm/backups/macos-build-20261020-165434`. Nessun riavvio host o modifica Windows.

Log in `/mnt/vm/images/macos-gpu-test/diagnostics/`:

- `ack-rs64-stage12-{serial.log,ioreg.txt,driver.log,shutdown.log}`.
- `ack-compute-stage17-{serial.log,ioreg.txt,before-repeat.log,after-repeat.log}`.
- `ack-compute-repeat-first.txt`: primo lotto10/10 e ACK1.
- `ack-compute-first-post-fault.txt`: letture tardive GFXHUB/MMHUB0 del primo lotto.
- `ack-compute-final-{serial.log,ioreg.txt,repeat.txt,driver.log,shutdown.log}`:
  secondo avvio e lotto10/10 con letture fault dopo compute.

Build finalizzata anche in `/mnt/vm/builds/Navi48Bringup-rs64-order-final.tar.gz`.
Controlli: build e firma reali macOS; sintassi dei due moduli CP/init da Linux
sia Navi44 sia Navi48; Python compilabile, bash-n e git diff --check.
Il percorso di errore con nuovo idle clamp non è stato provocato artificialmente.

Chiusura: guest arrestato e `vfs_unmountall(system) end` osservato; poi ricorre
il problema SMC/nested panic già noto e QMP quit chiude QEMU. Reset VFIO
GPU/audio completati, nessun fault IOMMU o errore VFIO nei log host della
sessione. Overlay e snapshot: qemu-img check senza errori. VM spenta, EFI
stage17 ripreparata senza l'opt-in S1b e digest verificato; shell con MEMLOCK
illimitato chiusa. Il launcher richiede ancora `--start` esplicito.

## S1b/VMID8 — risultato completo boot6, 20 ottobre 2026

Nel terzo boot stage17 è stato abilitato `navi48-native=1`, con interrupt CPU
sempre disabilitati. Gate accettato; GFXHUB CONTEXT8 è passata da
`0x03fffd73` a `0x03fffc07` (DEPTH3, BLOCK0, RETRY0) e l'invalidazione TLB
`req=0xf80100` ha ricevuto ACK. Le quattro prove positive lowwrite, highwrite,
mixed e compute sono passate: rispettivamente0/16,0/16,0/32 e0/32 valori errati.
La prova compute ha scritto `0xca11ed47 + lane` in tutte32lane attraverso la
page table del VMID8; non sono comparsi fault GFXHUB.

Il fault leg è stato **REFUSED** prima di inviare l'IB, perché
`CP_DEBUG.CPG_UTCL1_ERROR_HALT_DISABLE` era clear (`CP_DEBUG=0x20400400`). Il
kext non scrive CP_DEBUG; non è stato forzato alcun fault. Perciò il risultato
è `POSITIVE PASS (fault leg REFUSED)` ma `RESULT FAIL`: il compute VMID8 è
verificato, il requisito S1b completo resta aperto. La seriale è conservata in
`/mnt/vm/images/macos-gpu-test/diagnostics/native-s1b-stage17-serial.log`.

### Quarto boot e RADV direct-ICD smoke — 20 ottobre 2026

Un quarto boot stage17 ha ripetuto le quattro prove positive S1b su VMID8
(incluse 32/32 lane compute); il fault è stato nuovamente rifiutato con
`CP_DEBUG=0x20400400`, quindi S1b resta complessivamente FAIL. Nello stesso
boot, un harness ha chiamato direttamente `vk_icdGetInstanceProcAddr` dalla
dylib RADV compilata: `vkCreateInstance`, enumerazione del profilo, coda
compute e `vkCreateDevice`/`vkGetDeviceQueue` sono passati come amministratore.
Nessuna command buffer è stata sottomessa. La property Vulkan per nome e PCI ID
è canned dal profilo gfx1200; l'identità fisica `1002:7590` è confermata
separatamente dall'host. L'apertura N48N da utente ordinario è stata rifiutata
dalla policy predefinita “needs root”; non sono stati attivati i boot-arg app
né modificata la allow-list. La prova non è `vulkaninfo`, CTS o compute Vulkan.
Log e limiti sono in `radv_icd_smoke.md`; il conteggio è quattro boot stage17
complessivi, mentre le20ripetizioni compute restano limitate ai primi due.

### Boot diagnostico8: fault MES/GCVM con IRQ — 20 ottobre 2026

Con strumentazione read-only prima/dopo `SET_HW_RSRC` e `SET_HW_RSRC_1`, il
boot8 stage17 ha localizzato tre fault GCVM spontanei: ring169 write dopo
`SET_HW_RSRC`, poi ring153 read e ring169 write dopo `SET_HW_RSRC_1`, tutti
client GFX, VMID0, VA0. Lo status passa da zero a `0x40b52` e poi `0x40b53`
(`more=1`); il GART VMID0 copre `0x8400000000..0x840fffffff`, quindi VA0 è
fuori dal range. Le API MES completano, i fence EOP e lo shader 32/32 passano,
ma ciò non annulla il fault. Il packet successivo è query scheduler e non
aggiunge fault. IH riporta 6 interrupt/7 entries (EOP4, fault3, CP-error0).

Kext diagnostico SHA-256
`ac9eb4568d662d06a94553c047b80a37762a4c5e04911dfd5cd0ac0d9826b884`; log
`research/hw_dump/phase2_stage17_irq_diag_boot8_serial.log`, SHA-256
`dae6790802afd36ad51fabba482cc2c3b47cfecb8ef1c9fef5ae62d8ebe7dbb0`.
Guest shutdown ha completato `vfs_unmountall(system) end`; QEMU è uscito dopo il
poweroff guest. EFI stage17 è stata ripreparata senza native e IRQ opt-in; il
controllo launcher e `qemu-img check` passano. L'ottavo boot non appartiene a
una serie consecutiva e le20 ripetizioni compute sono solo nei primi due.
Cause escluse/mancanti e stato reset sono descritti in
`phase2_mes_fault_checkpoint.md`.

## Prossimi passi verso l'accelerazione grafica

Completare il fault leg S1b solo quando il controllo CP_DEBUG lo consente senza
alterare il comportamento del CP; aggiungere gli altri kernel; ricostruire gli
header/generatori privati IOAccelerator e sbloccare i gap ABI/RADV e packaging
cache Metal. Seguono creazione del device Metal, rendering, adattamento del
display/GOP Navi44 e composizione WindowServer. Il piano originale descrive il
port completo in mesi-uomo; il residuo non è stimabile in modo affidabile finché
restano irrisolti i blocchi ABI IOAccelerator e RADV. Il compute VMID8 non
consente una data per il primo desktop accelerato.
