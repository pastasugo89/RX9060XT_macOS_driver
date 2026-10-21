# Linux oracle RX 9060 XT — preparazione e acquisizione runtime

## Acquisizione runtime del 20 ottobre 2026

Il runner è stato avviato una volta, in una VM Linux effimera, dopo il completamento
delle prove macOS. Output: `research/hw_dump/linux-oracle-20261020T181307Z/`;
`runtime-result.txt` riporta `guest_poweroff_qemu_exit_0`. Kernel guest
`7.2.10-1-cachyos`, amdgpu `3.64.0`, PCI `1002:7590`, MES firmware `0x93`,
SMC `102.71.0`. Il filtro `dmesg-target.txt` non mostra fault GCVM/UTCL2 durante
l'inizializzazione idle amdgpu/MES; il timeout headless CRTC è separato e non
è un fault GPU VM. Questa è una baseline idle, senza queue utente/compute e non
prova l'assenza di fault nel percorso macOS.

Il ring MES 3.1.0 acquisito via debugfs è un dump binario di dword, preceduto
da rptr/wptr/wptr_cpu; contiene 22 frame attivi da 64 dword, inclusi
`SET_HW_RESOURCES`, query e `SET_HW_RESOURCES_1`. Nel primo SET, scheduler/query
pointer `0x1660/0x1680`, status `0x17e0`, flags `0x80447` e oversubscription
50. Nel SET1 il KIQ unmap timeout è `0xA` (dw13). I dump MQD/ring supplementari
sono invece rappresentazioni debugfs testuali e non erano attive queue utente.
`gpu_metrics.bin` è una tabella già tradotta dal driver Linux, 120 byte,
header 1.3, SHA-256 `14ec566cb2e5da80d3b35f727b86eaa0d53c888ea23dc5f8c81f294954a47713`;
hwmon idle: edge 29 C, junction 30 C, memoria 30 C, SoC circa 8 W e GPU load 0.
Non è raw SMU e non valida indipendentemente il layout IF0x33.

I blob del firmware host decompressi corrispondono byte per byte ai blob
embedded nel progetto: uni-MES `ee058438467479d05d3d54ec9b0a592cac50bfa3834e65c6e90bd0e675c087d1`,
ME `17487eb283d479ddb6331bc850a623e3f1217907e25aa5acf89602fb3eaeaf94`,
MEC `28b1e5bae440044887bab53a374db7bb971f7cc2780ab2b55c561e19f24d7fac`,
SMU `1b2054e3f710d1ab8dbdf6ff35914ad376b51caa6337831260c955add874b2ee`.
Il guest è terminato con exit QEMU 0; un warning QEMU indicava che il reset
della sola GPU dipendeva dal gruppo 16 non posseduto. Il journal host registra
successivamente reset VFIO GPU/audio (`reset done`), ma questo non dimostra un
reset ASIC completo.

Il GART oracle è `0..0x1fffffff` (512 MiB); il range macOS corrente è
`0x8400000000..0x840fffffff` (256 MiB). La differenza rende il contratto
della PTE all'indirizzo zero e il posizionamento GART il prossimo confronto
utile; non prova causalità e non giustifica un alias VA0 arbitrario. Initramfs
offline preliminare: `/mnt/vm/builds/linux-oracle-offline-validation/initramfs.img`,
43,320,788 byte, SHA-256
`1fbfeb1f1fe4acfc3f38347823deca43786176c522f78613b2b10adf22478dca`.
Il runner runtime ha costruito l'immagine temporanea descritta nei propri
artefatti `initramfs.sha256`; il file offline è un controllo precedente e
non va confuso con l'immagine effettivamente avviata.

Il runner passa attualmente la GPU senza la funzione audio. QEMU ha emesso il
warning di reset gruppo16; per una futura esecuzione, se autorizzata, rivedere
il passaggio coordinato GPU+audio prima di avviare e mantenere la VM effimera.
Non ripetere ora: la richiesta corrente impone stop alle prove.

La preparazione è offline e non ha avviato una VM. Il runner ha `--check` come modalità predefinita; solo `--start` costruisce una initramfs temporanea ed esegue QEMU. Il guest riceve la sola funzione GPU `0000:03:00.0` (`1002:7590`) già assegnata a VFIO. Non sono configurati dischi o rete, non vengono cambiati binding, impostazioni host o firmware e l'host non viene riavviato.

## Fattibilità host

- Kernel in esecuzione: `7.2.10-1-cachyos`, con albero moduli corrispondente in `/lib/modules/7.2.10-1-cachyos`; `/boot/vmlinuz-linux-cachyos` è leggibile.
- Sono presenti QEMU x86_64, KVM, `mkinitcpio`, `cpio`, `zstd` e il BusyBox integrato di mkinitcpio (`/usr/lib/initcpio/busybox`). Non è installato `/usr/bin/busybox`.
- L'albero moduli locale include `amdgpu`, VFIO e i moduli 9p. I firmware Navi 44 richiesti dal modulo amdgpu sono presenti localmente sotto `/usr/lib/firmware/amdgpu`; non è necessario scaricare o installare pacchetti. L'initramfs host/VFIO in `/boot` è root-only e non viene riutilizzata.
- La GPU attesa è nel gruppo IOMMU isolato 15 e già legata a `vfio-pci`; l'audio resta nel gruppo 16 e non viene passato. La iGPU `1002:164e` resta associata al driver host `amdgpu`.
- L'output previsto è una nuova directory privata `research/hw_dump/linux-oracle-<UTC>` condivisa col guest tramite 9p. Il runner non apre immagini o dispositivi a blocchi host. Le acquisizioni previste sono dmesg completo e filtro GPU/firmware, identificativi PCI, moduli/interrupt/iomem, `gpu_metrics.bin` grezzo e sysfs/hwmon, più le interfacce debugfs amdgpu disponibili per firmware, GPU, VM, fence, MES, ring e MQD. I dump MQD/ring sono le rappresentazioni testuali fornite da debugfs, non dati binari grezzi; possono non esistere quando non sono attive queue. I nomi di debugfs variano col kernel. Il log mkinitcpio, SHA-256 dell'initramfs e `runtime-result.txt` restano nell'output.

## Progettazione runner e controllo offline storico

`tools/vm/linux-oracle.sh --check` controlla kernel/moduli/firmware, KVM, GPU/VFIO, memoria, memlock, storage di destinazione, preflight display e lock. Trattiene distinti i due file descriptor dei lock build e GPU test per tutta la durata del controllo o della VM. Blocca QEMU già attivi e stampa solo PID e nome, mai la command line. Un controllo precedente era bloccato dal memlock di 8192 KiB contro i 6 GiB richiesti; successivamente il runner è stato avviato nella finestra hardware autorizzata e ha prodotto l'acquisizione sopra. Il valore storico del preflight non descrive lo stato attuale.

Per l'avvio serve che compute_next abbia terminato regolarmente ogni VM concorrente e che il coordinatore riveda prima il runner. La initramfs esplicita `virtio_pci`, che in questo kernel risulta built-in (`CONFIG_VIRTIO_PCI=y`), mentre 9p e `9pnet_virtio` sono moduli inclusi. Il guest è limitato da un watchdog di 240 secondi; il launcher conserva un socket QMP privato e, su interruzione, chiede `quit`, poi usa TERM come ripiego. Al timeout termina QEMU e scrive l'esito.

È stato completato un build non privilegiato con la stessa configurazione del launcher. Artefatti e log sono in `/mnt/vm/builds/linux-oracle-offline-validation/`; `mkinitcpio.log` riporta `Initcpio image generation successful`. L'immagine offline è 43,320,788 byte, SHA-256 `1fbfeb1f1fe4acfc3f38347823deca43786176c522f78613b2b10adf22478dca`. `lsinitcpio` conferma amdgpu, 9p, firmware Navi44 e interprete. Tale validazione è distinta dall'esecuzione runtime e dai risultati limitati sopra.
