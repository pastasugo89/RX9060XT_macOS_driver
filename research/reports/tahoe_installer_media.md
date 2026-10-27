# Supporti locali Tahoe 26.6.2 / 25G83 per QEMU

20/10/2026. Correzione del percorso inizialmente proposto con Sequoia:
non è necessario un sistema macOS di appoggio per i supporti qui preparati.
Non è stato scaricato alcun ulteriore sistema operativo.

## Fonte e dati estratti

Fonte locale: `research/ext/gibMacOS/macOS Downloads/publicrelease/140-93587 - 26.6.2 macOS Tahoe (25G83)/InstallAssistant.pkg`.
Dimensione 18 384 624 402 byte. L'originale non è stato modificato.

La TOC XAR identifica SharedSupport.dmg all'offset 17 953 771, lunghezza
18 366 669 607 byte, non compresso. SHA-1 dichiarato e verificato:
`65adfb4192ad9e8b6282f3ecc480cd3cafdabfef`.

Il volume HFS+ dentro il DMG contiene il software update asset ZIP già
individuato nell'analisi precedente. Il suo membro
`AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg` è BXDIFF50
con control size zero: una sostituzione completa, che non richiede una
vecchia immagine BaseSystem. L'intestazione di 60 byte è seguita da PBZX.

Decomprimendo i blocchi con il parser PBZX già presente nel progetto:

- BaseSystem.dmg risultante: **1 464 762 142 byte**;
- SHA-1 calcolato uguale a quello nell'intestazione BXDIFF:
  `2a6d9bc3ad569778e86706ad65b51ef0da980ab0`;
- SystemVersion.plist estratto con 7z dal volume APFS interno: **26.6.2 / 25G83**;
- convertito con `qemu-img convert -f dmg -O raw` in BaseSystem.img;
- `qemu-img compare -f dmg -F raw` conferma identità dei contenuti virtuali.

Il Payload XAR, offset 54 673 e lunghezza 17 897 996, è PBZX → cpio;
decompresso ed estratto con bsdtar, fornisce l'app originale
`Install macOS Tahoe.app`. SharedSupport.dmg è stato aggiunto alla sua
directory `Contents/SharedSupport`.

## Supporto completo

Creato `/mnt/vm/installers/tahoe-25G83/Tahoe25G83.iso`, 18 424 877 056 byte,
con Rock Ridge, ISO level 3 e HFS+ tramite xorriso. Include l'app completa e
`run-tahoe-installer.sh`, che esegue il suo InstallAssistant_springboard.
Gli avvisi Joliet riguardano link simbolici e percorsi lunghi omessi soltanto
da quel namespace; i namespace Rock Ridge/HFS+ sono presenti.

Il SharedSupport letto nuovamente dall'ISO con 7z ha SHA-1
`65adfb4192ad9e8b6282f3ecc480cd3cafdabfef`: coincide con il contenuto sorgente.
Il supporto completo si collega come CD SATA readonly; l'avvio avviene dal
BaseSystem x86-64 separato, non dall'ISO da sola.

Il manifest locale è `/mnt/vm/installers/tahoe-25G83/media-manifest.json`.
L'estrazione di lavoro di SharedSupport può essere rigenerata dall'originale;
la copia di lavoro duplicata viene rimossa dopo la verifica dell'ISO, per
non occupare inutilmente altri 17 GiB.

## EFI e launcher

La vera EFI dentro OpenCore.qcow2, non soltanto il plist di esempio esterno,
usava iMac19,1. È stata convertita una copia in raw, aggiornata tramite
mtools nel filesystem FAT all'offset 1 MiB e riconvertita in qcow2:

- nuova immagine: `OpenCore/OpenCore.tahoe.qcow2`;
- modello MacPro7,1, PlatformInfo.Automatic true, SecureBootModel Disabled;
- plist riletto dall'immagine e verificato;
- `qemu-img check` senza errori;
- immagine OpenCore originale conservata.

Il launcher collega l'EFI corretta, il BaseSystem ricostruito, il disco guest
qcow2 da 128 GiB e l'ISO readonly. Mantiene 12 GiB RAM, 8 vCPU, NAT/SSH su
localhost:2222 e grafica emulata. PCID è mascherato nel modello Skylake perché
il controllo QEMU mostrava che l'host non espone la feature richiesta.

`tools/vm/prepare-build-vm.sh` non scarica più Sequoia: conserva i dischi,
verifica i supporti locali e configura il launcher. `start-build-vm.sh`
controlla gli asset e il parametro KVM prima dell'avvio.

## Verifica iniziale in pausa

QEMU è stato inizializzato in pausa (`-S`, display disattivato), interrogato
via QMP e terminato regolarmente: stato prelaunch, running=false.
**Non è stato eseguito codice macOS e non è stata completata un'installazione.**
Restano da verificare il boot effettivo, il montaggio del supporto nel guest
e l'avvio dell'InstallAssistant locale. Guida aggiornata: `VM_MACOS.md`.

Nessuna modifica a dischi fisici, partizioni Windows, impostazioni KVM
dell'host, binding VFIO o servizi di sistema durante questa preparazione.

## Boot verbose verificato — 20 ottobre 2026

La VM ha raggiunto la schermata grafica Recovery di macOS Tahoe dopo la
correzione della configurazione EFI. Installazione completa ancora da eseguire.

Configurazione attiva: `/mnt/vm/images/macos-build/OpenCore/OpenCore.verbose.qcow2`.
Boot args: `keepsyms=1 -v debug=0x108 serial=3 msgbuf=1048576`.

L’EFI distribuita conteneva riferimenti a kext assenti. OpenCore si arrestava
con `Halting on critical error` sul VoodooPS2Controller mancante. Disabilitati
VoodooPS2Controller e relativo plugin tastiera, USBToolBox e UTBMap, assenti;
la VM dispone di tastiera e mouse USB emulati. Il riferimento
`AppleMCEReporterDisabler.kext` è stato corretto in `MCEReporterDisabler.kext`,
realmente incluso nell’EFI, con ExecutablePath vuoto (kext solo plist).
Senza quest’ultimo componente il kernel arrivava a launchd, poi andava in panic;
con il riferimento corretto Recovery viene visualizzata correttamente.

Backup EFI, NVRAM, launcher, plist e log degli esperimenti:
`/mnt/vm/images/macos-build/diagnostics/verbose-20261020-151445/`.
Screenshot Recovery: `/mnt/vm/images/macos-build/diagnostics/screen-007.png`.
Seriale attivo: `xnu-serial.log` nella directory diagnostica, sovrascritto a ogni
nuovo avvio. QMP locale: `/mnt/vm/images/macos-build/qmp.sock`.
L’EFI Tahoe originale è conservata ma contiene ancora i riferimenti errati:
non usarla per ripristinare un boot funzionante. Il launcher usa la copia verbose.

## Correzione del supporto completo — errore installer 255

Il primo tentativo è fallito con `pkgdmg is missing a footer`, operazione
`OSISVerifySystemOperation`, codice 255. La verifica SHA-1 precedente provava
l’integrità del DMG estratto ma non la struttura richiesta dall’installer.
Lo script originale Apple `Scripts/postinstall_actions/link_shared_support.bash`
copia/collega **l’intero InstallAssistant.pkg** in `Contents/SharedSupport/SharedSupport.dmg`.
Il primo supporto conteneva invece soltanto il membro XAR SharedSupport.dmg:
preparazione errata, ora corretta senza scaricare nuovamente il pacchetto.

ISO canonica ricostruita con l’intero pacchetto. Il digest
`376923d7494cfa32b69f383bcfdce46aeedb609fe6a242ea12a6e015bfb77ba4` è
registrato per l’`InstallAssistant.pkg` completo in SharedSupport (18 384 624 402
byte), non costituisce un hash dell’intera ISO. La ISO presente sulla SanDisk
personale è stata verificata solo tramite dimensione (18 442 831 872 byte),
volume ID e nomi nella radice; non è stato calcolato un hash completo né
confrontata byte per byte con la copia di build.
La vecchia ISO è conservata come `Tahoe25G83-invalid-inner-dmg.iso`.
Supporto sostituito nella VM a caldo tramite QMP dopo detach del volume
Shared Support ed eject. Disco guest APFS già inizializzato dall’utente.
Nuovo tentativo d’installazione ancora da verificare.

## Installazione completata fino a Setup Assistant

Il 20 ottobre 2026 la VM ha raggiunto la schermata “Select Your Country or
Region” del sistema installato (screenshot `diagnostics/setup-current.png`).
Durante i passaggi finali si è ripetuto un panic al riavvio, dopo lo smontaggio
dei volumi: `Ticket lock ... unexpectedly owned ... lock_ticket.c:155`.
Reset QMP eseguiti soltanto dopo tale arresto; il primo ha permesso il boot
`macOS` (non più `macOS Installer`), un ulteriore reset dopo il riavvio richiesto
dai task finali ha portato a Setup Assistant. Problema del riavvio automatico
ancora irrisolto; nessuna causa verificata per il simbolo di divieto segnalato
dall’utente. Durante l’ispezione il log mostrava installazione attiva, poi
bless del volume e riavvio. Non formattare né reinstallare.
Log conservato: `diagnostics/installer-stage2-reboot.log` nella directory VM.

## Blocco finale Setup Assistant e primo login

Dopo oltre 10 minuti sulla pagina aggiornamenti automatici, rete virtuale
scollegata temporaneamente via QMP: nessuno sblocco. Scorciatoie Terminale e
uscita forzata senza effetto visibile; ACPI powerdown senza effetto visibile.
Log salvato in `diagnostics/setup-updates-stall.log`. Eseguito reset QMP:
il sistema ha raggiunto il login dell’utente `test`, quindi la creazione
account era stata salvata. Screenshot `diagnostics/setup-restart.png`.
Rete virtuale riattivata dopo il test. Login e desktop ancora da verificare.
