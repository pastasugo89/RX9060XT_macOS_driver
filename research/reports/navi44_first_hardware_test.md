# Primo test hardware Navi44 in macOS — 20 ottobre 2026

## Esito

**Il kext Navi48Bringup 0.0.664 è caricato e attivo sulla vera RX9060XT
1002:7590 revc0 in macOS Tahoe26.6.2, build25G83. Discovery stage1 terminata.**
Conferme indipendenti: seriale `start: done`, kmutil showloaded, servizio IOKit
registrato/matched/active e proprietà MMIO,Verified=Yes. Nel primo test BAR0 presentava un conflitto: risolto nella prosecuzione con apertura host da256MiB.
Stage5 PSP SOS successivamente riuscito; prove seguenti in corso. Nessuna accelerazione grafica o Metal
ancora dimostrata. Vedere `navi44_bringup_progress.md` per lo stato successivo a questo primo test.

| Dato nel guest | Osservato |
|---|---|
| PCI match | 0x75901002, revc0, subsystem Sapphire1da2:a493 |
| BAR5 | 512KiB, mappato e verificato dal driver |
| VRAM RCC_CONFIG_MEMSIZE | 16304MiB |
| Discovery | on-die TMR valido,42IP |
| GC / PSP / SMU | 12.0.0 /14.0.2 /14.0.2 |
| SDMA /IH /NBIF | 7.0.0 /7.0.0 /6.3.1 |
| MMHUB /DCN /HDP /UMC | 4.1.0 /4.1.0 /7.0.0 /8.14.0 |
| Boot args | navi48bringup=1 navi48-stage=1 navi48-interrupts=0 |
| Stage IOKit | survey-readonly (nome del driver; discovery usa anche registri indiretti) |
| MSI control |128: bit enable0, capacità64bit presente |
| PSP letto dal survey | bootloader READY, sOS down |

## Preparazione host e prove VFIO

Boot_id nuovo `5381cd45-5f57-45bb-8608-692271210fd3`. Avvio one-shot VFIO
attivo. iGPU0a:00.0 ora boot_vga=1, driver amdgpu, monitor HDMI e framebuffer
Linux su iGPU. RX03:00.0 boot_vga=0 e audio03:00.1 su vfio-pci, gruppi15 e16
isolati. Servizio ACL completato con0/SUCCESS; KVM ignore_msrs=Y.
Heartbeat di ripresa messo PAUSED, nessuna nuova ricorrenza attiva.

Primo probe QEMU -S fallito prima di eseguire codice guest per MEMLOCK8MiB,
confermato dal kernel RLIMIT_MEMLOCK8388608. Portato a unlimited il limite
**soltanto dei processi di test**, tramite prlimit root su shell UID1000;
nessuna modifica globale limits.conf o privilegi di esecuzione QEMU root.
Launcher aggiornato per diagnosticare il limite prima dell’avvio.

Probe in pausa riuscito: status=prelaunch/running=false, GPU e audio enumerati,
reset done per entrambi all’apertura e al rilascio. Nessun fault IOMMU osservato.
Questo non prova reset/recupero da un hang GPU sotto carico.

## BAR16GiB e correzione di configurazione

Primo avvio macOS con BAR0 host16GiB ha abortito QEMU:
`KVM_SET_USER_MEMORY_REGION failed`, slot7, GPA0x8108800000000000,
size0x400000000. Nessuna discovery verificabile prodotta in quel tentativo.
Il solo ResizeGpuBars=10 in EFI non aveva ridotto la risorsa esposta da VFIO.

Usata l’interfaccia Linux PCI sysfs documentata resource0_resize, bit10=1GiB:
https://kernel.org/doc/html/latest/admin-guide/abi-testing.html
Script `tools/vm/resize-vfio-bar.py 10`: soltanto GPU isolata, con QEMU assente,
nessun utente VFIO, driver iniziale vfio-pci e monitor verificato su iGPU.
Unbind temporaneo vfio, resize e rebind vfio, ACL ripristinate. Nessun amdgpu
distaccato, nessuna modifica firmware o partizioni. Ripristino16GiB disponibile
con bit14, a VM spenta; lasciato1GiB per il prossimo test nella sessione VFIO.

BAR0 host ora0x880000000 +1GiB. Nuovo probe-S conferma1GiB e reset corretti.
Con questa configurazione il guest ha raggiunto login e SSH e il kext ha
completato discovery. Il confronto è tra configurazioni osservate: non attribuire
con certezza la causa interna dell’abort a uno specifico driver Apple senza
ulteriore analisi.

## Blocco BAR0 da risolvere prima del client nativo

Log esatto:
```
pci bars: BAR0 union [0x800000000, +0x40000000)
(IOPCIFamily [0, +0), config space 0x800000000, ReBAR size 0x40000000) - DISAGREE
native-s1c: BAR0 latch: IOPCIFamily and config space DISAGREE
(native client opens are refused) on BAR0
```

IORegistry GPU S30@6 conferma `assigned-addresses` senza BAR0; IODeviceMemory
contiene BAR2, I/O e BAR5. La configurazione PCI/QMP vede invece il BAR0 da1GiB.
La protezione di latch è rimasta attiva e **non è stata aggirata**.
Da capire perché IOPCIFamily non pubblica la risorsa64bit, prima di modificare
il driver o eseguire altri stage. Nessun tentativo IOServiceOpen nativo effettuato.

## Chiusura ed evidenza

Guest raggiungibile e discovery stabile per alcuni minuti. Richiesto shutdown
regolare. Dopo `vfs_unmountall(system) end` ricompare il panic di spegnimento già
osservato nella VM build: Ticket lock unexpectedly owned, dopo AppleSMC/SMCWDT.
Non è stato attribuito al nuovo kext. QEMU terminato via QMP soltanto dopo
smontaggio dei volumi; reset done GPU/audio. Overlay qemu-img check senza errori.
Stato finale: VM spente, Linux su iGPU, RX/audio ancora VFIO, BAR0 runtime1GiB.

Artefatti in `/mnt/vm/images/macos-gpu-test/diagnostics/`:
- probe-status.json, probe-pci.json, probe-kernel.log: probe16GiB;
- stage1-attempt1-bar16g.log e core QEMU46MiB in /var/lib/systemd/coredump;
- host-bar0-size-10.json: risorse PCI prima/dopo resize;
- probe-1g-status.json, probe-1g-pci.json;
- stage1-bar1g-serial.log, stage1-guest-summary.txt, stage1-gpu-node.txt;
- stage1-pci-ioreg.txt, stage1-assigned-pci.json;
- stage1-shutdown.log, hardware-session-kernel.log;
- screenshot stage1-bar1g-system.png (login guest).

Snapshot e dischi base/VM build non usati per scritture dal test; solo overlay,
EFI e NVRAM dedicati. Nessuna modifica Windows. Non dichiarare superate fasi
GMC/PSP/SMU/compute/display/Metal sulla base di questo risultato.
