# Preparare la VM macOS Tahoe 25G83

Aggiornato il 20/10/2026. Il percorso usa direttamente l'installer Tahoe già
scaricato: **non occorre scaricare o installare Sequoia**. Le precedenti
istruzioni che lo proponevano come sistema di appoggio sono ritirate.

## Stato verificato

- Storage Btrfs separato in `/mnt/vm` e strumenti host installati.
- Disco guest qcow2 vuoto da 128 GiB, copie di firmware e NVRAM.
- BaseSystem x86-64 ricostruito dal pacchetto locale e verificato con lo
  SHA-1 contenuto nella patch Apple; il suo SystemVersion.plist riporta
  **26.6.2 / 25G83**. La conversione raw risulta identica al contenuto DMG.
- App completa di installazione e SharedSupport riuniti in un supporto
  ISO/HFS+ locale; SHA-1 del SharedSupport letto dall'ISO verificato.
- EFI virtuale aggiornata a MacPro7,1 e verificata dall'immagine effettiva.
- QEMU inizializzato in pausa con QMP: nessun codice del guest eseguito.
  L'avvio macOS e l'installazione completa sono ancora da verificare.

I supporti sono in `/mnt/vm/installers/tahoe-25G83/`; la VM è in
`/mnt/vm/images/macos-build/`. Tutti i dischi collegati alla VM sono file:
nessuna partizione fisica Windows o Linux è assegnata al guest.

## 1. Aprire il Terminale di Linux

Premere Ctrl+Alt+T oppure aprire Konsole dal menu applicazioni.

```bash
cd ~/Documenti/rx9060xt_metal_driver
bash tools/vm/prepare-build-vm.sh
```

Lo script conserva il disco guest esistente, verifica i supporti già preparati
per 25G83 e aggiorna il launcher. Non scarica altri sistemi operativi.

Configurazione iniziale:

| Risorsa | Impostazione |
|---|---|
| RAM | 12 GiB |
| CPU | 8 vCPU, 1 socket / 4 core / 2 thread |
| Modello CPU | Skylake-Client, vendor GenuineIntel, TSX e PCID disabilitati |
| Disco guest | 128 GiB virtuali qcow2, a crescita dinamica |
| Firmware | OVMF + OpenCore, SMBIOS MacPro7,1 |
| Display | QEMU GTK, vmware-svga emulata |
| Rete | NAT, SSH guest 22 su 127.0.0.1:2222 |
| GPU fisica | Resta al desktop Linux in questa fase |

## 2. Avviare QEMU

Il parametro KVM richiesto da OSX-KVM risulta ancora disattivato. Applicarlo
nel proprio terminale; vale fino al riavvio Linux e non modifica file di sistema:

```bash
printf '1\n' | sudo tee /sys/module/kvm/parameters/ignore_msrs
bash tools/vm/start-build-vm.sh
```

QEMU si avvia come utente normale, con una finestra grafica. Lasciare aperto
il terminale. Per questo avvio diretto non occorrono libvirtd, virt-manager o
l'aggiunta a nuovi gruppi, dato che KVM è già accessibile.

Il launcher controlla il mount corretto, l'accesso a KVM, i supporti, la RAM
disponibile e che la VM non sia già aperta. Se il server Minecraft è acceso,
potrebbe essere necessario arrestarlo regolarmente per liberare RAM.

## 3. Entrare nel sistema di avvio Tahoe

Nel menu OpenCore selezionare BaseSystem/macOS Base System/Recovery.
Premere Spazio se le voci ausiliarie sono nascoste. In caso di menu diverso
o errore, annotare il testo prima di procedere.

Avvio verificato fino alla schermata Recovery il 20 ottobre 2026. Il launcher
usa `OpenCore.verbose.qcow2`, con i riferimenti ai kext corretti e la modalità
verbose attiva. La precedente `OpenCore.tahoe.qcow2` è conservata come backup
ma contiene riferimenti errati. Dettagli in `research/reports/tahoe_installer_media.md`.

## 4. Inizializzare il solo disco virtuale

1. Aprire Utility Disco, Vista → Mostra tutti i dispositivi.
2. Selezionare il disco QEMU da **128 GiB**, che può comparire come circa
   **137 GB**. OpenCore è un altro piccolo disco da circa 384 MiB; il supporto
   Tahoe è da circa 18 GB e il BaseSystem da circa 1,5 GB.
3. Inizializzare quel solo disco vuoto: nome `macOS`, formato APFS,
   schema Mappa partizione GUID.
4. Chiudere Utility Disco.

Questo passaggio si esegue una sola volta sul disco vuoto. Non ripeterlo
quando la VM contiene già un sistema operativo o dati da conservare.

## 5. Avviare l'installer completo locale

Dal menu Utility del sistema di avvio aprire Terminale. Controllare i volumi:

```bash
ls /Volumes
```

Il supporto aggiuntivo dovrebbe essere montato come `Tahoe25G83`. Avviare:

```bash
sh "/Volumes/Tahoe25G83/run-tahoe-installer.sh"
```

Lo script sul supporto lancia l'InstallAssistant dell'app Tahoe completa,
con il SharedSupport del nostro pacchetto 25G83. Questo è il percorso locale
previsto; il comportamento dell'installer nella VM resta da verificare.
Se il volume o lo script non compaiono, fermarsi e controllare l'elenco dei
volumi anziché avviare un aggiornamento online a una build non verificata.

Nella finestra dell'installer scegliere il volume `macOS` e seguire la
procedura. Durante i riavvii, OpenCore può mostrare `macOS Installer`:
sceglierlo finché l'installazione è in corso, poi scegliere `macOS`.

## 6. Primo accesso

Creare un account amministratore locale chiamato `test`; l'accesso Apple
non è necessario per l'installazione. Nel Terminale di macOS:

```bash
sw_vers
sysctl -n hw.model
```

Attesi: **ProductVersion 26.6.2**, **BuildVersion 25G83**, modello **MacPro7,1**.
Disattivare gli aggiornamenti automatici di macOS per conservare l'ABI su cui
si basa il progetto. La grafica può essere lenta: l'accelerazione Metal
sulla RX 9060 XT è l'obiettivo del driver, non una funzione già disponibile.

## 7. Abilitare SSH e trasferire i sorgenti

In macOS: Impostazioni di Sistema → Generali → Condivisione → Login remoto,
consentito al solo utente test. Da Linux:

```bash
ssh -p 2222 test@127.0.0.1
```

Sorgenti e dipendenze possono essere trasferiti con scp/rsync via quella
porta. Un clone git da solo non include firmware, MacKernelSDK e le altre
cartelle locali escluse dal versionamento.

## 8. Toolchain di compilazione

Verificato il 20/10/2026: le Command Line Tools installate in
`/Library/Developer/CommandLineTools` (Apple clang 21.0.0) sono sufficienti
per compilare e firmare `Navi48Bringup.kext` (`make all ASIC=navi44 APPLE_ROUTE=0`).
La firma ad hoc e i 412 simboli importati sono stati verificati nella VM.
L’Xcode completo descritto sotto è un passaggio distinto per gli strumenti Metal,
non un requisito della build kext già riuscita.

SSH automatizzato dall’host con chiave dedicata (permessi 600):

```bash
ssh -i /mnt/vm/builds/build-vm-ed25519 -p 2222 test@127.0.0.1
```

Sorgenti guest: `~/Developer/rx9060xt`; backup kext e log sull’host:
`/mnt/vm/builds/Navi48Bringup-navi44-build.tar.gz`.


Installare **Xcode 26.6 completo** in `/Applications/Xcode.app` dai download
Apple Developer, evitando simulatori non necessari. Poi nel guest:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch
xcodebuild -downloadComponent MetalToolchain
xcodebuild -version
xcrun --sdk macosx --show-sdk-path
xcrun -f metal
```

Serviranno anche:

- KDK della build **25G83**, verificandone la disponibilità nei download Apple;
- Rust/rustup con target x86_64-apple-darwin;
- Meson, Ninja, pkgconf, CMake e header Vulkan;
- MacKernelSDK e firmware già disponibili nel progetto;
- Mesa con le patch Darwin del progetto 0001–0010.

Su macOS Intel Homebrew usa normalmente `/usr/local`: alcuni script del
bundle hanno default `/opt/homebrew`, da adattare al momento della build.
L'acceleratore richiede ancora gli header ioaccel-layout in ricostruzione:
la disponibilità della VM non completa automaticamente quella parte del driver.

## 9. Punto di ripristino pulito

Spegnere macOS dal suo menu e attendere che QEMU termini. Solo a VM spenta:

```bash
cd /mnt/vm/images/macos-build
qemu-img snapshot -c tahoe-clean mac_hdd_ng.img
cp -n OpenCore/OpenCore.tahoe.qcow2 OpenCore/OpenCore.tahoe.clean.qcow2
cp -n OVMF_VARS-1920x1080.fd OVMF_VARS.clean.fd
```

Non eseguire snapshot/check/convert sull'immagine mentre la VM è in funzione.
EFI e NVRAM sono file separati e vanno conservati insieme allo snapshot del
disco. Controllare lo spazio in `/mnt/vm`, perché anche gli snapshot qcow2
occupano spazio fisico.

SIP/AMFI restano alle impostazioni iniziali della VM di build. Caricamento
kext, passthrough VFIO, seriale e debugger si prepareranno successivamente
su una VM di test.

## Fonti e dettagli

- [Preparazione locale e hash](research/reports/tahoe_installer_media.md).
- [OSX-KVM](https://github.com/kholia/OSX-KVM).
- [Requisiti Xcode](https://developer.apple.com/xcode/system-requirements).
- [Componenti aggiuntivi Xcode](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components).
