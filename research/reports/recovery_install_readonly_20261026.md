# Installazione bare metal e Setup Assistant — 26/10/2026

## Prove CPU: `cpus=2` non testata, all-threads attiva

L'utente riferisce che Shift+Invio nel picker non seleziona la voce: la modalità sicura non è stata verificata. Dopo il test offline negativo, OCBOOT (UUID A140-3052) aveva ricevuto una prova `cpus=2`, ma quella configurazione **non è stata avviata**. In seguito l'utente ha chiesto di usare tutti i core; la configurazione attiva ora rimuove l'argomento `cpus=2` per lasciare a XNU il conteggio logico abilitato dal firmware. È un passaggio da due processori logici al massimo a tutti quelli esposti, non un'impostazione “8 core”. Il Ryzen 7 7700 ha 8 core fisici/16 thread; l'eventuale uso di tutti e 16 dipende dall'esposizione ACPI/firmware. XNU applica `cpus` al massimo dei processori logici, e la documentazione OpenCore definisce `cpus=VALUE` come massimo numero di CPU utilizzate ([XNU i386_init.c](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/i386/i386_init.c#L3741-L3748), [OpenCore Configuration §9.5](https://dortania.github.io/docs/latest/Configuration.html#other-variables)). La patch AMD che espone 8 core fisici è rimasta invariata.

La prova all-threads è stata scritta atomicamente su OCBOOT: config SHA-256 `06d041bc12305a87eb98a66514b67431defddad390699625f6b169c81b64a188`; soltanto `EFI/OC/config.plist` cambia rispetto al precedente stato `cpus=2`, 27 altri file invariati. Manifest 28/28 e `ocvalidate` 1.0.8 PASS; chiavetta smontata, nessun reset NVRAM. Backup `cpus=2` sulla chiavetta fuori da EFI e nella cartella candidata; backup BOOT17 `cpus=1` verificato con SHA-256 `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`, sia locale sia fuori da EFI. Dettagli e manifest in `research/ext/opcore-all-threads-candidate-20261026/`; il deployment precedente e backup sono in `research/ext/opcore-cpus2-candidate-20261026/`. La prova hardware all-threads resta **pendente**. Boot11 senza `cpus=1` mancava della whitelist MMIO `F7000000`; Boot12 aveva `cpus=1` senza whitelist e panic; Boot13 aveva `cpus=1` con whitelist e arrivava alla GUI. Questi avvii sono confondenti e non stimano il rischio del test attuale.

**Ripristino BOOT17 (`cpus=1`) da Linux:** montare solo la partizione OCBOOT e verificare UUID `A140-3052`; usare il backup locale `research/ext/opcore-cpus2-candidate-20261026/config.plist.boot17-base-55d53e17.backup` (SHA sopra), scriverlo in modo atomico su `EFI/OC/config.plist`, controllare hash e `ocvalidate`, quindi `sync` e smontare. Non serve né va eseguito un reset NVRAM. Il backup `cpus=2` si conserva separatamente se serve ripristinare la prova precedente.

## Stato confermato

L’utente conferma che BOOT17 ha input USB funzionante e ha raggiunto macOS Recovery. In seguito ha installato Tahoe sul volume APFS preparato: Setup Assistant è arrivato alla scelta della regione e, al primo resoconto, puntatore e rotella rispondevano mentre la schermata caricava. Dopo circa 30 minuti il puntatore si è fermato e il sistema è rimasto completamente bloccato; ha riavviato ed è tornato a Linux. Primo login non raggiunto. Nel boot registrato da IMG_0681 Ethernet era scollegata prima dell’avvio, ma lo stallo e il freeze si sono ripetuti offline.

## Storage Linux host prima dell’installazione — 26/10/2026

Su autorizzazione dell’utente è stata sostituita la vecchia Btrfs p7 da 200 GiB, che conteneva le VM. La procedura di
partizionamento si è fermata dopo la nuova GPT e la creazione della p7; non è stata rilanciata. Una procedura separata
di solo ripristino ha estratto gli archivi selezionati e aggiornato `/etc/fstab`.

| Partizione Lexar live nell’host Linux | Stato verificato |
|---|---|
| p1–p6 | Record GPT conservati dal controllo approvato della procedura; nessuna formattazione richiesta o eseguita su queste partizioni. |
| p7 `/dev/nvme1n1p7` | Btrfs, 50 GiB, UUID `0ae89dbc-e934-4c12-a6bd-90d01e5bd0da`, montata su `/mnt/vm`. Gli archivi principale (445 elementi) e GRUB protetto (2 file) hanno superato `tar --compare`; i 445 hash passano come utente. Corrette solo 51 directory genitore implicite per l’accesso. |
| p8 `/dev/nvme1n1p8` | 150 GiB, PARTUUID `2cdc5f53-02b8-43db-863f-aa3ca5676577`, tipo GPT Apple APFS, filesystem assente e nessun mountpoint. È il candidato per Tahoe, non ancora formattato. |

`/etc/fstab` differisce dal backup solo per la sostituzione dell’UUID della vecchia p7 con quello nuovo. L’esito del
comando è registrato in `research/ext/vm-preservation-20261026/lexar-restore-20261026T161046Z/progress.jsonl`.
Questi erano metadati del Linux host prima dell’installazione, non una lettura della Recovery.

## Inventario preinstallazione letto dalla shell Linux della workspace

La shell gira su `Linux MSI-Desktop` (CachyOS x86_64), separata dall’interfaccia Recovery riportata dall’utente. Questi dati descrivono solo i block device esposti al Linux host.

| Dispositivo host | Stato letto senza montare | Nota |
|---|---|---|
| SanDisk Cruzer Fit `/dev/sda1`, 14,3 GiB, FAT32, UUID `A140-3052` | OCBOOT senza mountpoint | La chiavetta BOOT17 risulta smontata in questa shell. |
| Samsung `MZVLQ256HBJD-00BH1`, 238,5 GiB | EFI FAT32 512 MiB; Btrfs 238 GiB montato come `/` | Disco dell’host Linux; non candidato all’installazione. |
| Lexar EQ790 1 TB, 931,5 GiB | p1 FAT32 100 MiB, p2 16 MiB, p3 NTFS 728,1 GiB, p4 NTFS 823 MiB, p5 FAT32 1 GiB, p6 NTFS 742 MiB; p7 Btrfs 50 GiB; p8 150 GiB tipo GPT Apple APFS senza filesystem | Metadati letti dopo la ricreazione delle partizioni. p8 è un candidato host: la corrispondenza con un identificatore `diskutil` va verificata in Recovery. |
| Lexar p7, UUID `0ae89dbc-e934-4c12-a6bd-90d01e5bd0da`, mount `/mnt/vm` | Btrfs 50 GiB | Archivio dei materiali selezionati ripristinato e confrontato; i dischi VM non sono stati ripristinati. `/etc/fstab` punta al nuovo UUID. |
| SanDisk USB personale 128 GB, UUID `48AD-071D` | exFAT; montata temporaneamente in `/run/media/pastasugo89/48AD-071D`, poi smontata | Ho verificato solo metadati e contenuto ISO autorizzata; gli altri contenuti non sono stati elencati né letti. |

Il dato dei dischi Linux non sostituisce l’inventario di macOS Recovery. I nomi `/dev/nvme…` e `/dev/sda` potrebbero non corrispondere ai nomi che mostrerà `diskutil`.

## ISO e percorso documentato

La sola ISO autorizzata sulla SanDisk è `macOS-Tahoe-25G83-installer/Tahoe25G83.iso`, **18 442 831 872 byte**. xorriso ne rileva il volume ID `Tahoe25G83` e, nella radice ISO, `run-tahoe-installer.sh` e `Install macOS Tahoe.app`. La chiavetta è stata smontata dopo questa verifica; non è stato calcolato un hash completo della ISO. La dimensione differisce da quella della ISO prodotta e registrata nei documenti della VM (`18 424 877 056` byte), quindi la sola corrispondenza di nome e volume label non prova identità byte per byte. Il digest `376923d7494cfa32b69f383bcfdce46aeedb609fe6a242ea12a6e015bfb77ba4` citato nel report build riguarda l’`InstallAssistant.pkg` completo in SharedSupport (18 384 624 402 byte), **non** la ISO.

Montando l’ISO con volume `Tahoe25G83`, il percorso del launcher documentato e verificato nella radice del supporto è:

```sh
sh "/Volumes/Tahoe25G83/run-tahoe-installer.sh"
```

La VM ha completato l’installazione fino a Setup Assistant. Sul PC bare metal l’utente ha avviato il launcher locale e installato Tahoe; la shell Linux non ha verificato se macOS abbia avuto connettività Ethernet.

## Diagnosi e prossimo test singolo

Separatamente dal cambiamento di partizioni appena riportato, dopo la scelta della regione la GUI è rimasta in caricamento per circa 30 minuti. Il puntatore inizialmente rispondeva; in seguito si è fermato e il sistema si è bloccato completamente. Nel boot del video Ethernet era scollegata prima dell’avvio e il problema si è ripetuto, quindi il test offline non ha risolto lo stallo. Non abbiamo uno screenshot della schermata Setup Assistant né log macOS che ne identifichino la causa. Il video `IMG_0681.mov` è una ripresa distinta di verbose startup: mostra messaggi rossi di caricamento kext, ma non la schermata Setup Assistant né un panic leggibile. La clip è stata campionata lungo tutta la durata; nessun panic header/backtrace è leggibile e l’ultimo frame è nero. Dettagli e frame estratti in `research/ext/boot-setup-video-0681/analysis.md`.

La shell Linux ha letto solo metadati block/APFS, senza montare il volume: il disco è il Lexar EQ790 1 TB, seriale `QBA343R000865P220C`. `lsblk` mostra `/dev/nvme1n1p4` Btrfs da 50 GiB (UUID archivio `0ae89dbc-e934-4c12-a6bd-90d01e5bd0da`) e `/dev/nvme1n1p5` APFS, label `macOS`, APFS UUID `cdf0d2d1-dc04-4164-8ab2-3ef22ebf917c`, PARTUUID `2009c655-127a-4b08-9b5b-67cfbc6ee147`, start LBA `1632114688`, size `161924251648` byte (circa 150.8 GiB). Rispetto ai 150 GiB preparati (`161061273600` byte), il p5 è più grande di `862978048` byte, esattamente la dimensione della vecchia Windows Recovery p4 (GUID `dba4e46d-4faa-43cf-bb70-5faa20407517`). Non compaiono neppure i record della seconda Windows Recovery p6 (GUID `49bdb186-3af2-4739-94a8-b26cc147727d`). Sono invece presenti la partizione NTFS Windows da `781832397312` byte e l’EFI da 1 GiB (UUID FAT `F183-A4C4`). L’archivio Btrfs da 50 GiB conserva UUID e start LBA attesi. Il report preinstallazione indicava come target p8/PARTUUID `2cdc5f53-02b8-43db-863f-aa3ca5676577`: la discrepanza corrente non è una semplice rinumerazione, ma i metadati da soli non spiegano quale passaggio l’abbia causata. `sfdisk` non era leggibile senza privilegi. Il volume APFS non è stato montato e nessun comando ha scritto sui dischi; non tentare riparazioni GPT che potrebbero sovrapporsi all’installazione.

Apple documenta che Setup Assistant richiede Internet solo in alcuni casi specifici, come enrollment organizzativo o aggiornamento obbligatorio; non indica che la schermata regione dipenda dalla rete. La guida Apple colloca la scelta della regione all’inizio del flusso, prima dei passaggi successivi e della configurazione di rete. Non abbiamo trovato una fonte primaria che documenti questo preciso stallo su Ryzen/Tahoe. AMD_Vanilla documenta i requisiti patch Zen 4 e il supporto Tahoe, ma non attribuisce a `cpus=1` o alle patch AMD un blocco in questa schermata. Dortania descrive `revpatch=sbvmm` con RestrictEvents per aggiornamenti OTA su modelli non supportati: non è una correzione pertinente alla schermata regione, e qui non si era ancora arrivati agli aggiornamenti automatici. Non cambiare ora EFI, `cpus=1` o RestrictEvents.

**Prossimo test singolo proposto:** tentare Safe Boot selezionando Tahoe nel picker OpenCore mentre si tiene premuto Shift, senza modificare BOOT17 o altri file EFI. È un confronto reversibile con le restrizioni di avvio sicuro, non una correzione identificata. La configurazione ha `PollAppleHotKeys=False` e `EnableSafeModeSlide=True`; il picker potrebbe non intercettare Shift, quindi se Tahoe parte in modalità normale il tentativo è inconclusivo. Lilu documenta che in Safe Boot la maggior parte dei plugin viene disabilitata; VirtualSMC dipende da Lilu per la piena funzionalità. I kext iniettati hanno `OSBundleRequired=Root`, tranne RTL812xLucy (`Network-Root`), quindi non sappiamo esattamente quali componenti cambieranno. Se l’input sparisce o la GUI si blocca ancora, riavviare normalmente; non attribuire la causa a un singolo componente da questo test.

## Riferimenti

- [Apple: reinstallare macOS da Recovery](https://support.apple.com/it-it/102655) — flusso generale; la rete della Recovery in questo PC non è ancora verificata.
- [Apple: gestire Setup Assistant](https://support.apple.com/guide/deployment/depdeff4a547/web) — Internet è necessario in alcuni casi specifici, inclusi enrollment organizzativo o aggiornamenti obbligatori.
- [Apple: configurare il Mac](https://support.apple.com/en-ca/guide/imac/apd831707cb3/mac) — la regione è all’inizio del flusso e precede le schermate di configurazione successive.
- [Dortania: macOS 26 Tahoe](https://dortania.github.io/OpenCore-Install-Guide/extras/tahoe.html) — `revpatch=sbvmm` riguarda aggiornamenti OTA, non Setup Assistant alla schermata regione.
- [OpenCore Configuration](https://dortania.github.io/docs/latest/Configuration.html) — `PollAppleHotKeys` controlla il polling dei tasti rapidi nel picker; il test Shift è da considerare non garantito con l’impostazione corrente. `EnableSafeModeSlide` è attivo nella config.
- [Acidanthera RestrictEvents](https://github.com/acidanthera/RestrictEvents) — `sbvmm` forza il modello VMM per gli aggiornamenti OTA su macOS 11.3+.
- [Acidanthera Lilu](https://github.com/acidanthera/Lilu) — la modalità sicura disabilita la maggior parte dei plugin; il risultato del test non isola un singolo kext.
- [AMD-OSX AMD_Vanilla](https://github.com/AMD-OSX/AMD_Vanilla) — patch IOPCIFamily richiesta per Zen 4 e supporto dichiarato Tahoe; non documenta questo specifico stallo.
- [Apple: formati APFS in Utility Disco](https://support.apple.com/it-it/guide/disk-utility/dskua9e6a110/mac) — riferimento sul filesystem. Le istruzioni Apple di inizializzazione dell’intero dispositivo non si applicano al dual-boot Windows/Linux di questa macchina.
- `VM_MACOS.md` §5 e `research/reports/tahoe_installer_media.md` — supporto ISO, launcher e verifica nella VM.
- `research/reports/vm_storage_partition.md` — cronologia storage, geometria p7/p8 e ripristino dell’archivio.
