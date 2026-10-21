# Primo test RX 9060 XT — preparazione del 20/10/2026

## Stato misurato e confine

RX 9060 XT 1002:7590 a 0000:03:00.0, gruppo IOMMU15 isolato, driver amdgpu,
boot_vga=1. Audio 03:00.1 in gruppo16 isolato, snd_hda_intel. iGPU Raphael
0a:00.0 presente, tutte uscite scollegate. Unico monitor attivo su RX DP-1.
`reset_method` esposto: bus (non presupporre FLR). L’utente ha confermato di
poter collegare il monitor alla scheda madre. Nessun cambio di binding eseguito.

Prima prova prevista: **discovery stage1**, non driver grafico funzionante.
Flag `navi48bringup=1 navi48-stage=1 navi48-interrupts=0`.
Il probe è opt-in; start mappa BAR5 ed esegue discovery/survey. Non chiamare
questa operazione MMIO strettamente read-only: usa registri indiretti indice/dato
e abilita memoria PCI. PSP, compute, stack acceleratore/Metal e display nativo
non vengono richiesti da questa configurazione. La fase1 non richiede gli
header IOAccelerator ancora mancanti.

## Ripristino e dischi

macOS arrestato regolarmente con shutdown; QEMU è uscito, socket scomparso.
Con lock esclusivo sulla VM e QEMU assente, qemu-img check: zero errori.
Copia reflink Btrfs dei file disco/EFI/NVRAM/firmware/launcher in:
`/mnt/vm/backups/macos-build-20261020-165434`.
Controllo qcow2 della copia: zero errori. Reflink = inode separati con COW,
non hard link. È un punto di ripristino locale sullo stesso SSD, non backup
contro guasto del supporto. La VM build è stata riaperta e ha raggiunto desktop.

Test separato in `/mnt/vm/images/macos-gpu-test`: disco overlay sul qcow2 della
copia spenta, NVRAM autonoma, EFI autonoma con kext bringup compilato e flag
stage1. EFI riletto e percorsi di ogni kext abilitato verificati. ResizeGpuBars=10
(1 GiB nel piano target), da verificare sul device: il BAR host osservato era16GiB.
Grafica emulata mantenuta; GPU e audio configurati come vfio-pci, ROM BAR disabilitato
per questa prova non-GOP. SSH2223, QMP e seriale separati, gdbstub localhost1234.
Nessuna VM hardware di test avviata, reset VFIO e caricamento kext non verificati.

Launcher con default **solo controlli**, nessun binding automatico:

```
bash tools/vm/start-gpu-test-vm.sh --check
```

Attualmente termina2 con blocchi attesi: monitor sulla RX, RX primaria di boot,
driver host ancora attivi e VM build accesa. `--start` è un’azione esplicita e
richiede controlli positivi, VM build spenta, VFIO accessibile, RAM e KVM.
Tiene il lock della VM build durante il test per evitare avvii concorrenti.
Il preflight in sola lettura è `tools/vm/gpu-preflight.py`; inventario JSON locale:
`/mnt/vm/builds/gpu-preflight-20261020.json`.

## Sequenza ancora da eseguire

1. Salvare lavoro, arrestare VM build e predisporre iGPU primaria in firmware;
   collegare monitor alla scheda madre e tornare in Linux.
2. Confermare desktop/renderer/console host sull’iGPU e assenza di processi che
   usano i nodi DRM della RX. Il solo spostamento del cavo non dimostra questo.
3. Preparare binding VFIO per GPU/audio con recupero documentato. Non distaccare
   il display host. Verificare aperture MMIO e dimensione BAR nel guest.
4. Validare passthrough e reset/recupero, preferibilmente con VM Linux oracolo,
   prima del test macOS. Nessun reset hardware è stato provato in questa sessione.
5. In VM test verificare effettiva policy/caricamento kext e log di discovery;
   arrestarsi al primo errore. Non aumentare gli stage automaticamente.
6. Solo dopo discovery: scala stage progressivi, SMU/ventole e self-test compute.
   Per desktop/Metal restano ABI IOAccel, shader cache, SPI e display GOP.

Il passaggio all’iGPU richiede l’intervento fisico dell’utente e forse il firmware:
non può essere sostituito da un comando remoto mentre la RX pilota il monitor.

## Avanzamento dopo spostamento cavo

Il20/10 l’utente ha collegato il monitor a iGPU e autorizzato riavvio/prosecuzione.
Nessun monitor RX, ma renderer/app ancora sulla RX nella sessione originaria:
preparato avvio VFIO separato one-shot anziché distacco live. Dettagli e ripresa
in `vfio_reboot_checkpoint.md`. Non è stato ancora eseguito il test GPU.
