# Preparazione locale per Navi44 discovery stage1 — 2026-10-27

## Esito

Ho preparato una EFI di prova e una copia separata di rollback **solo nello staging locale**: [candidato e rollback](../ext/navi44-baremetal-stage1-candidate-20261027/). Non ho scritto su `/Volumes/OCBOOT`, installato/caricato kext o riavviato. Il kext candidato è quello storico preservato, non la build Navi44 appena ricompilata.

## OCBOOT e backup

`diskutil info /Volumes/OCBOOT` identifica una FAT32 montata con il flag `read-only`. La directory EFI e i metadati del file `EFI/OC/config.plist` (35.594 byte) sono leggibili con `ls`, ma il tentativo di calcolare l'hash del contenuto, limitato a 8 secondi, è stato interrotto dal timer (exit 142). Ho fermato le letture della chiavetta. Nessuna scrittura è stata tentata.

L'ultimo record di deployment dice che la configurazione all-threads con hash `06d041bc…b64a188` fu installata al posto della BOOT17 (`55d53e17…120ac25`) lasciando invariati gli altri 27 payload EFI, con manifest 28/28 e `ocvalidate` 1.0.8 PASS (`research/ext/opcore-all-threads-candidate-20261026/deployment-result.json`). La copia locale BOOT17 è stata ricostruita applicando quella configurazione e corrisponde al manifest storico all-threads 28/28. Questo prova la coerenza della ricostruzione con il record; il blocco di lettura impedisce di attestare che siano i byte attuali della chiavetta.

`rollback/EFI` è una copia locale separata dalla candidata di prova, ma risiede sullo stesso filesystem del progetto: non è un supporto fisico indipendente. Non ho trovato qui un'immagine/snapshot APFS verificato dell'installazione bare metal; `/mnt/vm` non è presente su questo Mac. Per questo la chiavetta attuale non va usata come destinazione della candidata.

## Confronto delle build Navi44

| Artefatto | Binario / Info.plist SHA-256 | Stato verificato |
|---|---|---|
| Build macOS attuale `research/builds/macos-20261027/src/cobalt64/src/navi48-bringup/build/Navi48Bringup.kext` | `bf8f7fcb…3fb18ae6` / `e1789e56…b6dd10e` | x86_64; `make all ASIC=navi44 APPLE_ROUTE=0` exit 0; `0x75901002`; firma ad hoc e import kernel verificati. |
| Bundle preservato `research/builds/macos-20261027/reference/builds/navi48-full-20261021/Navi48Bringup.kext` | `d186c77f…3f3a22846d` / `e1789e56…b6dd10e` | x86_64; versione 0.0.664; stesso match `0x75901002`; firma valida e `kmutil libraries` exit 0 con 412 simboli risolti contro le KC 25G83. |

La nuova build contiene `n4x_safety.o`, ma cinque blob opzionali di shader sono vuoti per mancanza degli input: `shadercache.bin` e i quattro `shader_blit_*_gfx1201.bin` (build log, righe 121–150). Il log preservato non registra blob mancanti e incorpora quei firmware shader. I firmware GPU GC 12.0.0, PSP 14.0.2, SDMA 7.0.0 e SMU 14.0.2 sono presenti in entrambi i log: le cinque assenze della build nuova sono shader, non firmware core PSP/GC/SMU.

I due eseguibili hanno hash diversi pur condividendo Info.plist, versione e ID PCI; non sono binariamente equivalenti. Il report `gpu_safety.md` afferma che il bundle preservato precede il watchdog. La candidata stage1 usa quel bundle storico per mantenere il riferimento archiviato e per evitare di scambiare la nuova build incompleta per la build precedente; non va usata oltre discovery e non offre il watchdog termico della revisione più recente.

La prova `navi44_first_hardware_test.md` registra il caricamento della versione 0.0.664 durante un test macOS con la RX reale in passthrough VM, ma non salva l'hash dell'eseguibile. `metal_deploy_plan.md` associa `d186c77…` alla build Navi44 completa del 21/10; non ho trovato una digest del binario nei log stage1 che dimostri che fosse proprio quello usato in quel boot. Quindi l'artefatto storico è verificato come build/signature/import, ma non posso affermare che sia identico ai byte usati in una specifica prova runtime. Tutte le prove di bring-up/compute documentate sono in VM; la baseline bare metal 27/10 riporta RX primaria, `IONDRVFramebuffer` e `No Kext Loaded`.

## Contenuto e verifiche della candidata

`candidate/EFI` parte dalla ricostruzione all-threads e aggiunge il bundle storico, una voce `Kernel/Add` x86_64 limitata a Darwin `25.0.0+` e i soli boot args `navi48bringup=1 navi48-stage=1 navi48-interrupts=0`. Mantiene gli argomenti già presenti, compreso `-amd_no_dgpu_accel`. Non include Navi48Accel, RDNA4FB o il bundle Metal.

- Rollback baseline: manifest 28/28 PASS; `ocvalidate` 1.0.8 PASS.
- Candidata: manifest 31/31 PASS; `plutil -lint` e `ocvalidate` 1.0.8 PASS.
- Kext nella candidata: SHA `d186c77…3f3a22846d`; `codesign --verify --strict --deep` PASS; `kmutil libraries --arch x86_64 --undef-symbols` exit 0, 412 simboli risolti e nessun simbolo irrisolto nel log.
- `ocvalidate` originale nel repository non aveva il bit eseguibile: ho usato una copia locale in `tools/`, stesso SHA-256 `c76f907d…d0bb0b38`; l'originale non è stato modificato.

Log di verifica e manifest sono in `research/ext/navi44-baremetal-stage1-candidate-20261027/tools/` e nelle rispettive directory `rollback/`/`candidate/`.

## Limiti e prerequisiti per il primo test

La baseline GPU bare metal del 27/10 mostra la RX come display principale; il BIOS documentato ha iGPU Raphael disabilitata. Prima di avviare la candidata servono iGPU abilitata, monitor sull'uscita della scheda madre e un **secondo supporto di test**, lasciando OCBOOT intatta. BOOT17 ha permesso all'utente di raggiungere Recovery e usare input USB, ma non è un backup APFS.

La discovery stage1 non è una lettura hardware innocua: il piano prevede mapping BAR5, accesso a registri indiretti e abilitazione della memoria PCI. I boot args in candidata disattivano gli interrupt e fissano stage1; non significano che ogni accesso sia read-only. Il test non deve aumentare stage o avviare shader/compute/Metal. Il bundle storico scelto non ha watchdog termico, quindi la sessione andrebbe mantenuta breve e senza carico.

Rollback verificabile per un futuro test su supporto separato:

1. Verificare l'identità della chiavetta di test prima di copiare qualsiasi file; tenere OCBOOT scollegata o comunque intatta.
2. Prima dell'avvio, eseguire sul supporto di test i controlli manifest 31/31, `ocvalidate` e `codesign` documentati nel [README candidato](../ext/navi44-baremetal-stage1-candidate-20261027/README.md).
3. Se il boot di prova fallisce, spegnere e selezionare nel picker la OCBOOT originale. Non riprovare stage superiori.
4. Per ripristinare il supporto di test, ricopiare l'intero `rollback/EFI` dopo aver verificato UUID e smontaggio del dispositivo; poi ripetere il manifest 28/28 e `ocvalidate` prima di riavviare.

La copia rollback è validata rispetto al manifest di progetto, non al contenuto live illeggibile della OCBOOT. Non è stata distribuita né avviata alcuna EFI candidata.

## Deploy controllato su OCBOOT — 27 ottobre 2026

L'utente ha autorizzato il primo test e ha indicato che sono disponibili solo OCBOOT e la chiavetta personale da 128 GB. Dopo smontaggio/rimontaggio, OCBOOT è tornata leggibile: l'intera EFI effettiva corrisponde al manifest originale 28/28, senza file aggiuntivi; config `06d041bc…b64a188`. La verifica del filesystem in sola lettura è passata. L'archivio reale dei 28 file è stato salvato e riletto integralmente su `/Volumes/Untitled 1/macOS-Tahoe-25G83-installer/OCBOOT-backup-verified-20261027.tar`, SHA-256 `c5c3ffd6ba5aeaa142084f7dca0b184d20e13e4cadaaa5ab50e20f0d75e5b707`. Accanto si trova uno script di ripristino da Linux che verifica UUID FAT `A140-3052`, archivio e config prima di ripristinare il solo config; `bash -n` passa, ma il ripristino effettivo su Linux non è stato provato. Un kext di prova lasciato su disco diventa inerte con la config originale.

Su OCBOOT UUID macOS `7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3`, disk4s1, è stata distribuita la candidata con `deploy_stage1_ocboot.py`; il tool ha verificato backup, identità, manifest originale, manifest candidata, scritto il kext e sostituito il config per ultimo. Risultato `DEPLOY_OK`, tutti i 31 file della candidata coincidono; config attiva `7f15135dad4501d3e0dd9ebccf49b855925b875216a2c5f343f7bcf57c838d36`. `ocvalidate` 1.0.8 e verifica firma live passano; il volume è stato smontato. Nessun riavvio o test eseguito ancora. La chiavetta originale ora contiene temporaneamente la variante stage1: in caso di fallimento usare la voce Linux nel menu firmware e ripristinare dal backup indipendente. Non confondere questa EFI di sola discovery con il driver Metal.
