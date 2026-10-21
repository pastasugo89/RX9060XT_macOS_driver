# Checkpoint — riavvio host per VFIO, 20 ottobre 2026

L’utente ha spostato il monitor sulla scheda madre e ha autorizzato riavvio e
prosecuzione. Stato prima del riavvio: boot_id
`df891565-0164-49b0-806a-732ca165335a`, kernel7.2.10-1-cachyos.
Monitor attivo iGPU0a:00.0 HDMI; dGPU03:00.0 senza cavi ma ancora amdgpu,
boot_vga=1 e applicazioni (anche Codex/ChatGPT, browser, Plasma) sul suo renderD128.
RenderD129 è iGPU. Nessun distacco live/reset eseguito. VM spente.

## Avvio preparato e recupero

Script root `tools/vm/prepare-vfio-test-boot.py` (prepare/arm/disarm/rollback).
Prepare completato: initramfs separato da54.8MB con vfio_pci/vfio/vfio_iommu_type1
prima dei driver grafici. Kernel normale, initramfs normale, /etc/default/grub,
/etc/mkinitcpio.conf hash-identici. Voce normale Linux preservata esattamente e
voce Windows verificata presente nel nuovo GRUB. Nessuna modifica partizioni.
Backup/stato: `/mnt/vm/backups/vfio-test-boot-state.json`, copia originale GRUB
in `/mnt/vm/backups/host-vfio-20261020-170657/grub.cfg`.

Voce test `rx9060xt-vfio-test` in `/etc/grub.d/42_rx9060xt_vfio_test`.
Usa `/boot/initramfs-linux-cachyos-vfio-test.img`, kernel normale e flag:
`vfio-pci.ids=1002:7590,1002:ab40 vfio-pci.disable_vga=1 initcall_blacklist=sysfb_init kvm.ignore_msrs=1 rx9060xt_vfio_test=1`.
Il caricamento framebuffer firmware viene escluso per evitare la GPU boot
trattenuta da sysfb; amdgpu resta disponibile per la iGPU.

Selettore one-shot `/etc/grub.d/09_rx9060xt_vfio_once`: legge soltanto il flag
rx9060xt_vfio_once dal file FAT Linux ESP
`/boot/efi/EFI/cachyos/rx9060xt-vfio-test.env` (UUID04BD-A73B, Samsungnvme0n1p1,
non ESP Windows Lexar). Se1, lo azzera e salva PRIMA di selezionare il test.
Se save_env fallisce, non seleziona il test: default normale. Nessun uso di
next_entry su grubenv Btrfs, evitando scritture GRUB non supportate su Btrfs.
Al prossimo riavvio normale è atteso Linux standard senza binding VFIO.
La sintassi GRUB è stata validata; il boot test resta da osservare.

Unit `rx9060xt-vfio-access.service`: abilitata ma condizionata al marker kernel
rx9060xt_vfio_test=1; verifica IDs/driver/gruppi isolati GPU/audio e concede ACL
rw al solo uid1000 sui due nodi VFIO. Non carica driver né resetta dispositivi.
Esito atteso `/mnt/vm/builds/vfio-boot-result.json` con nuovo boot_id.

Per annullare PRIMA del riavvio:
`pkexec python3 /home/pastasugo89/Documenti/rx9060xt_metal_driver/tools/vm/prepare-vfio-test-boot.py disarm`.
Rollback completo disponibile con stessa invocazione e `rollback` (rifiuta
backup obsoleto se kernel/GRUB sono cambiati successivamente).

## Ripresa autorizzata

Heartbeat corrente `riprendi-test-rx-dopo-riavvio` ogni5min in questa chat.
Finché boot_id non cambia: nessuna azione e silenzio. Al primo boot nuovo,
mettere PAUSED questa automazione tramite automation_update, preservando campi
originali da automation.toml (non mutare TOML a mano), poi procedere una volta.

1. Verificare cmdline marker e IDs VFIO. Se marker assente, leggere flag ESP e
log: non ripetere reboot automaticamente. Non avviare VM build che consumerebbe RAM.
2. `python3 tools/vm/gpu-preflight.py --json`; `systemctl status rx9060xt-vfio-access.service`;
verificare monitor/framebuffer su iGPU, gruppi15/16 (o quelli correnti), ACL
rw e KVM ignore_msrs=Y. boot_vga può restare1 come dato firmware: preflight lo
accetta soltanto con VFIO proprietario e display+framebuffer Linux sulla iGPU.
3. Primo tentativo hardware: `bash tools/vm/start-gpu-test-vm.sh --probe` in
PTY, QEMU in pausa via N48_START_PAUSED=1 / -S. Socket QMP
`/mnt/vm/images/macos-gpu-test/qmp.sock`. Verificare query-status, query-pci,
VFIO/errors e poi quit. Nessun codice guest deve essere eseguito nel probe.
Raccogliere errori reset nel journal kernel; fermarsi se VFIO/reset falliscono.
4. Solo se probe corretto: `bash tools/vm/start-gpu-test-vm.sh --start`,
selezionare macOS in OpenCore. QMP è separato dalla vecchia VM. Log:
`/mnt/vm/images/macos-gpu-test/diagnostics/serial.log`. SSH2223, utente test,
chiave `/mnt/vm/builds/build-vm-ed25519`. Password guest già autorizzata in chat,
non salvata in file. Non caricare librerie Metal o acceleratore.
5. Verificare kmutil showloaded e ioreg, log bringup/discovery. Il kext è già
iniettato nell’EFI e ha soltanto stage1, interrupt0; non passare ad altri stage.
Se nessun caricamento, diagnosticare policy/injection prima di qualsiasi escalation.
6. Salvare report ed esito esatto. Test discovery non prova compute/display/Metal.

Snapshot overlay e dettagli: `research/reports/first_gpu_test_plan.md`.
La VM build e snapshot rimangono separati. Kext, RADV, n48xlate compilati;
lazyInitialize BOOL corretto/testato e13class sizes recuperate. Metal completo
resta bloccato da ABI/generatori e spvcache; non confondere queste attività con stage1.

## Esecuzione armata

Prepare completato senza errori, arm completato. Timer root systemd
`rx9060xt-vfio-reboot.timer` avviato per reboot dopo45secondi; comando
`/usr/bin/systemctl reboot`. Inhibitor osservati soltanto delay di salvataggio
browser/Codex, nessun blocco shutdown. Il flag FAT è stato riletto=1 prima del timer.
Alla ripresa verificare esito reale: non assumere che reboot o boot VFIO siano riusciti.

## Ripresa eseguita

Boot VFIO nuovo5381cd45-5f57-45bb-8608-692271210fd3 verificato. Ricorrenza PAUSED.
Probe e primo test stage1 completati: kext attivo,42IP,16304MiB, MMIO verificato.
BAR0 IOPCIFamily mancante: client nativo rifiutato, nessuno stage aumentato.
Guest fermato dopo smontaggio (panicSMC preesistente, poi QMPquit), reset VFIO
completati e overlay check senza errori. Dettagli in `navi44_first_hardware_test.md`.

## Prosecuzione successiva autorizzata

L'utente ha poi richiesto i prossimi passi. BAR0256MiB risolve il conflitto;
PSP/SMU/IMU/RLC e copieSDMA provate, ora blocco ACKGFXHUB obbligatorio primaCP.
VM spente, fallbackEFIstage11. Vedi navi44_bringup_progress.md per esiti,
revisioni kext e stato persistente: il primo checkpoint stage1 è storico.

## ACK e compute risolti nella prosecuzione del20/10

L'utente ha autorizzato esplicitamente la risoluzione ACK e i test compute.
Ordine RS64/GFXHUB corretto come Linux: stage12 e due avvii stage17 passano,
shader32/32 lane, ulteriori20/20ripetizioni compute corrette, zero timeout.
Nessun interrupt CPU o stack Metal. Il blocco e fallbackstage11 sopra sono
storici: vedere `gfxhub_ack_compute.md` per build, log, limiti e stato corrente.
