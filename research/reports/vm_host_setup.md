# Software host per la VM macOS

Verifica del 18/10/2026 su CachyOS, su richiesta dell'utente.

## Installazione completata

- QEMU desktop e qemu-img 11.1.2.
- OVMF (`edk2-ovmf` 202608).
- libvirt 12.8.0, virt-manager 5.1.0 e virt-viewer 11.0.
- libisoburn/xorriso e openbsd-netcat.
- Già disponibili: 7zip, dnsmasq, git, Python, curl, wget, OpenSSH,
  rsync, socat e nftables.
- OSX-KVM e il submodule OcBinaryData scaricati in
  `research/ext/OSX-KVM/` (fuori da git). L'immagine
  `OpenCore/OpenCore.qcow2` supera `qemu-img check`.

L'installazione con pacman è terminata con codice 0; le dipendenze sono
state installate senza un aggiornamento generale del sistema.

## Verifiche host

`virt-host-validate qemu` conferma virtualizzazione SVM, accesso a `/dev/kvm`,
presenza di vhost-net/tun e IOMMU attivo. I warning riguardano il controller
cgroup devices nella verifica senza privilegi e le funzionalità confidential
computing, non necessarie per questa VM.

La sandbox non espone `/dev/kvm`: il controllo è stato eseguito sul sistema
host fuori dalla sandbox. Non dedurre dall'assenza del device nella sandbox
che KVM non funzioni.

## Configurazione ancora da fare

Il controllo automatico di approvazione ha rifiutato il comando proposto
che avrebbe aggiunto l'utente ai gruppi kvm/libvirt, abilitato
`libvirtd.socket` e impostato `kvm ignore_msrs=1` a runtime e in
`/etc/modprobe.d/90-macos-kvm.conf`. Il motivo è che l'autorizzazione a
installare software non è stata considerata sufficiente per queste modifiche
permanenti all'host. Il comando non è stato eseguito: serve autorizzazione
esplicita prima di applicare queste modifiche. L'accesso KVM per l'utente
risulta già disponibile durante la verifica.

Non sono stati modificati binding VFIO, bootloader o configurazione GPU.
Non sono state create VM, immagini del disco macOS o nuovi installer.

Restano circa **9,5 GiB liberi** sulla partizione Linux. Installer convertiti,
dischi della VM e snapshot richiedono altro spazio. Il pacchetto completo
25G83 è già presente nel percorso documentato in `macos_25G83_re.md`.
Xcode, Metal Toolchain e KDK andranno installati nel guest macOS.

## Aggiornamento del 20/10/2026: storage pronto

Su richiesta esplicita dell'utente è stata creata nello spazio non allocato
del Lexar una partizione Btrfs separata da 200 GiB, montata automaticamente
in `/mnt/vm`. Circa 198 GiB disponibili; cartelle images/installers/builds/backups
scrivibili dall'utente. Le sei partizioni preesistenti mantengono geometria,
UUID e attributi originali. Backup GPT sul Samsung e dettagli dei controlli
in [vm_storage_partition.md](vm_storage_partition.md).

Nessuna VM creata e nessun file del progetto trasferito. La configurazione
KVM/libvirt descritta come non applicata il 18/10 non è stata cambiata.
