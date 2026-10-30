# Recupero del login accelerato — 30 ottobre 2026

## Diagnosi osservata

- Primo boot: UUID `62feb406-1ece-49e1-8e2a-3cc6d0aa44e5`. Il job attiva il bundle 25, riavvia WindowServer (PID 609) e rileva il login alle 14:06:44 locali. Il monitoraggio termina prima della sua conclusione; lo stato rimane `pending`.
- I report di iconservicesagent e Spotlight mostrano abort ripetuti in `+[MTLLoader sliceIDForDevice:legacyDriverVersion:airntDriverVersion:]`, chiamato da `_MTLBinaryArchive` e da `RB::FunctionLibrary::FunctionLibrary`. Il log unificato conserva l'assert **`Target device architecture is nil`**. Sono crash dei servizi, non prova di un nuovo crash di WindowServer o dell'unica causa della schermata vuota.
- Secondo boot: UUID `c3d1a193-84ba-48d9-a609-97216e0ce638`. Alle 14:09:32 il job rifiuta la riattivazione con `Previous GPU attempt is pending; reviewed reset required`. Crea/conserva `/private/tmp/n48m-off`. Nessun nub Metal/client nativo presente; il bring-up hardware raggiunge comunque lo stage 17 con i controlli di base passati. Questo spiega la modalità software attuale.
- Il bundle installato era ancora 25, SHA256 `ed45a207dd742f74c3d3b2dccc6d9a214d919a7dd1109a30618bb0c60fcb5c3e`: i candidati browser 26/27 non erano stati lasciati installati.

## Contratto individuato

Il bundle non implementava `newBinaryArchiveWithDescriptor:error:`. La factory ereditata costruisce l'archivio Apple; il getter base `targetDeviceArchitecture` restituisce nil e il loader esegue l'assert prima di poter restituire un NSError.

Analisi del framework Metal estratto 25G83 con LLVM/otool: `-[_MTLDevice targetDeviceArchitecture]` a `0x7ff80f590a0c` restituisce zero; factory ereditata a `0x7ff80f592fc0`; loader a `0x7ff80f5cb33f`. Il framework nel crash ha UUID `5d64fa80-29ce-32aa-bab6-4e5034132c0b`.

È stata seguita la skill REA; gli strumenti MCP REA non sono disponibili in questa sessione. Queste osservazioni sono analisi LLVM e report locali, non Evidence prodotte dal server REA. Una lettura limitata del RenderBox caricato in un processo di analisi ha verificato l'UUID `dcd1950c-4c90-3ccc-821f-eb54c4f1b193` e ispezionato 1500 byte del costruttore al relativo offset `0x6b354`: dopo la factory esistono controlli nil/errore. Non è stato eseguito quel costruttore né provato il rendering di RenderBox con il candidato.

## Modifica e limiti

La factory del nostro device ora restituisce nil e un NSError nel dominio `MTLBinaryArchiveDomain`, prima di entrare nel loader nativo. La modifica vale per tutti i chiamanti; non usa nomi di processi, URL o hash shader. Non inventa un'architettura AMD nativa compatibile con binari che questo backend AIR/SPIR-V non sa consumare.

**Questo è un contenimento corretto del crash, non l'implementazione completa degli archivi binari Metal.** La ripresa del login e la capacità dei framework chiamanti di continuare senza quell'archivio restano da verificare al prossimo avvio. Il comportamento documentato dell'API prevede un risultato e un errore; la cache di binari GPU è distinta dalla compilazione delle librerie. Fonti: [archivi Metal](https://developer.apple.com/documentation/metal/creating-binary-archives-from-device-built-pipeline-state-objects), [dominio degli errori](https://developer.apple.com/documentation/metal/mtlbinaryarchivedomain).

## Candidato installato per il prossimo avvio

- Bundle **28**, profilo guardia `stage25-archive-boundary-v1`.
- Main SHA256 `0363d9963e3f09197f64c52fdbff3418ed622efac89a9f8167f9246dc95a8421`.
- Sorgente di staging derivato dal bridge HEAD con la sola nuova factory; librerie RADV e n48xlate copiate dal bundle 25 e verificate identiche. I cambiamenti sperimentali cache/dual-source/allocazioni presenti nel worktree non sono inclusi in questo candidato di recupero.
- Backup privato: `/Library/Application Support/Navi44/accelerated-trial/archive-recovery-ptjs1i4s`. Contiene bundle 25 originale, script originale, record pending abbandonato, manifest e log precedente.
- Il record pending del vecchio boot è stato archiviato e rimosso dopo la verifica del candidato. Non è stato etichettato `stable`. Il prossimo boot dovrà creare un nuovo record pending con la guardia ordinaria.
- Il kill switch rimane presente durante la sessione corrente; WindowServer mantiene PID 201. Nessun kickstart, logout o riavvio eseguito. EFI, kernel, audio, rete e timing display non modificati.

Staging locale: `research/builds/macos-20261030/archive-recovery/`, con manifest, log dell'assert, sorgente esatto del candidato e artefatti di analisi non redistribuibili.

## Verifiche eseguite

- Build Objective-C x86_64 con `-Wall -Wextra -Werror`; compatibilità del codice errore con il deployment target gestita tramite availability.
- Firma ad hoc e verifica `codesign --verify --deep --strict` prima e dopo l'installazione; hash dei tre componenti verificati.
- `archive-boundary-probe.m` carica il vero bundle in un processo isolato e invoca la nuova factory sei volte, con descriptor vuoto, URL inesistente e URL di archivio di sistema, con/senza puntatore NSError. Tutti ritornano nil/errore senza abort.
- Il probe usa un ricevitore non inizializzato esclusivamente per questa factory indipendente dallo stato; non apre client GPU e non misura rendering o fallback dei framework. Non presenta questa verifica come test di un device completo.
- Sintassi dello script di avvio e del tool di installazione verificata; rilettura post-installazione conferma versione 28, nuovo hash/profilo, kill switch presente e medesimo WindowServer.

## Verifica richiesta al prossimo boot

Avvio normale, login, icone e finestre visibili; controllare che Spotlight/iconservicesagent non ripetano l'assert e che il nuovo record raggiunga realmente `stable`. Il sistema deve mantenere l'accelerazione e il contenuto deve essere disegnato, non soltanto lasciare WindowServer vivo. I precedenti problemi browser/video e il piano complessivo di completezza rimangono aperti.
