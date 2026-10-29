# Profilo sperimentale a otto sessioni GPU

Il sistema osservato aveva quattro sessioni occupate (WindowServer, Wallpaper,
Warp e VTDecoder), e Brave ha ripiegato sul compositing software. La modifica
consente un profilo di build opt-in `NATIVE_SESSIONS=8`, mantenendo quattro
sessioni come valore predefinito. Le sessioni aggiuntive utilizzano VMID 12–15,
fuori dalla maschera MES 1–7 impostata dal driver. Questo è un controllo statico,
non una prova che i VMID aggiuntivi funzionino sull'hardware.

Le pagine statistiche storiche 0–3, globale 4 e G5 5 mantengono il significato;
le sessioni 4–7 sono esposte su 6–9. Gli slot DEAD e la riserva per WindowServer
restano applicati a tutti gli slot. Ogni slot aggiuntivo richiede una finestra
GART, un contesto VMID e allocazioni proprie; i limiti restano condivisi. Il tool utente aggiornato distingue le pagine 6–9 dalla globale e da G5
usando la pagina richiesta, non il numero dello slot restituito.

Test host con ASan/UBSan: test G2 originale 250 verifiche e test dedicato al
profilo a otto sessioni superati. Build completa x86_64 su copia del sorgente di bring-up effettivo con profilo 8,
firma verificata. Il binario è sperimentale e non costituisce una prova hardware.
I 28 indirizzi CONTEXT relativi ai VMID 12–15 coincidono con gli offset GC 12.0
negli header Linux per control, base, start ed end.

Da completare: audit delle risorse VMID 12–15 e delle finestre GART,
verifica del profilo completo rispetto ai componenti installati, test concorrenti e isolamento dei contesti su hardware,
integrazione con guardia di avvio e rollback. Non installato; non riavviare per
questo candidato. VideoToolbox e decodifica video richiedono valutazione separata.


## Diagnosi video iniziale

`VTIsHardwareDecodeSupported` chiamato il 28 ottobre dal processo di test
non autorizzato e con quattro sessioni occupate ha restituito false per H.264,
HEVC, VP9 e AV1. Il processo ha contemporaneamente ricevuto il rifiuto N48N.
Il risultato è specifico alla configurazione e al processo al momento del test:
non prova che l'hardware non possa decodificare né che aumentare gli slot attivi
una pipeline VideoToolbox. Dopo l'avvio del candidato occorre ripetere il test
e misurare codec, frame persi, CPU e decoder durante la riproduzione YouTube.

## Ulteriore verifica VCN

Il solo aumento delle sessioni non implementa un decoder hardware. Il codice
corrente dichiara esplicitamente che le doorbell VCN/VPE non sono portate
(`amd/nbif_v6_3_1.h`); riferimenti VCN nel percorso Apple non provano che il
percorso nativo le inizializzi o registri un decoder. AMD/Linux descrive VCN
come motore separato di codifica/decodifica, collegato a MMHUB
([documentazione del driver AMDGPU](https://docs.kernel.org/gpu/amdgpu/driver-core.html)).
La disponibilità di un decoder VideoToolbox dipende anche dal formato e dalle
risorse ([Apple: richiesta decodifica hardware](https://developer.apple.com/documentation/videotoolbox/kvtvideodecoderspecification_requirehardwareacceleratedvideodecoder)).
Un risultato negativo attuale non autorizza ad annunciare che YouTube userà VCN
solo perché Brave ottiene un contesto Metal.

Il censimento IP precedente identifica sul dispositivo VCN 5.0.0. Linux usa
un percorso dedicato per inizializzare il motore, predisporre la coda e il
firmware ([sorgente upstream VCN 5.0.0](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/vcn_v5_0_0.c));
questo è un riferimento per il porting, non prova un'integrazione VideoToolbox.
La sonda `video-codec-probe.c` verifica ora anche la creazione di sessioni con
accelerazione consentita o obbligatoria e interroga la proprietà ufficiale
`UsingHardwareAcceleratedVideoDecoder`. Il 29 ottobre, con quattro sessioni
GPU occupate e processo non ammesso, la descrizione generica 1080p H.264 ha
creato una sessione consentita ma la proprietà è risultata non disponibile;
le sessioni obbligatorie sono state rifiutate per tutti e quattro i codec.
La sonda non contiene parametri del codec e non decodifica fotogrammi: questi
esiti non identificano da soli il motivo del rifiuto o il percorso di YouTube.
Va rieseguita con un contesto ammesso e sessioni libere dopo la prova GPU.

Per misurare lo stutter reale, `tools/baremetal/navi44-gpu-diagnostics/browser-frame-probe.js`
campiona per 15 secondi i tempi di animazione della scheda visibile e, se presente,
il delta dei fotogrammi video prodotti e persi. Si esegue nella console di sviluppo
con video già in riproduzione; va confrontato sullo stesso video, qualità e durata.
Registra il tempo in background e segnala i task lunghi quando l'API è disponibile.
I valori non identificano da soli né l'uso della GPU né il decoder; per questo
vanno affiancati alle informazioni GPU del browser e alla verifica VideoToolbox.
Il conteggio è stato esercitato con un ambiente JavaScript simulato, non ancora
su YouTube durante questa sessione.

Il 29 ottobre `brave-probe.py` ha avviato una finestra Brave con profilo
temporaneo su `https://vorssaint.com` e raccolto 15,1 secondi in primo piano:
216 callback, 14,3 callback/s, intervallo p95 133,4 ms, 112 intervalli sopra
50 ms. Chromium segnalava compositing e rasterizzazione software, WebGL
disattivato e decodifica video software. Questa singola misura documenta il
carico della pagina nello stato attuale, non prova un FPS universale né attribuisce
con certezza ogni ritardo alla GPU. Il processo e il profilo di prova sono stati
chiusi; il profilo personale non è stato modificato. Ripetere lo stesso comando
dopo il candidato, con condizioni di visibilità e durata comparabili.

Una seconda esecuzione ha verificato URL finale, caricamento completo e viewport
1200×1162 a DPR 1; ha misurato 8,1 callback/s e p95 135,1 ms su 15,1 secondi.
Resta compositing software. La differenza rispetto a 14,3 callback/s nella prima
prova mostra variabilità sostanziale; il primo campione non registrava viewport
né stato di caricamento e non consente un confronto rigoroso. La sonda ora salva
questi dati e rifiuta una pagina non completamente caricata. Occorrono più
campioni comparabili prima e dopo, con visibilità e carico controllati.

## Audit aggiuntivo del recupero concorrente

Nel sorgente G2, `stall_handle` legge senza `gCliLock` puntatore, apertura e
identità della sessione responsabile; `g2_recover` acquisisce successivamente
il lock del ring e scrive `poisoned` sul puntatore. La chiusura può rilasciare
uno slot e l'apertura successiva riutilizza la stessa struttura; `gRecovering`
serializza i recuperi ma non compare nel percorso `n1c_open`. Un possibile
interleaving è: identificazione del vecchio proprietario, avanzamento tardivo
del ring, chiusura e riapertura dello slot, quindi scrittura del flag sul nuovo
proprietario. L'effettiva raggiungibilità richiede ulteriori verifiche delle
temporizzazioni e dei lock; non è stata osservata in esecuzione e non va
presentata come causa dello stutter. I test puri di ammissione non coprono
questa interazione. Prima di dichiarare sicuro il candidato a otto sessioni
occorre dimostrare l'invariante di identità o correggere il percorso, includendo
chiusura, riapertura, rilettura del progresso e ordine dei lock.

Nel sorgente candidato è ora presente una difesa mirata: mentre `gRecovering`
è attivo, `n1c_open` rifiuta nuove sessioni sotto `gCliLock`; il recupero
acquisisce lo stesso lock per verificare puntatore e identità, poi lo rilascia
prima delle attese GPU. Così un'apertura già iniziata termina prima della
verifica, mentre una successiva non può riutilizzare lo slot fino al termine
del recupero. Il test sorgente verifica ordine di lock e controlli; i 252
controlli G2 e 30.000 casi di ammissione a otto sessioni passano con i
sanitizer. Questo non dimostra tutte le interazioni concorrenti né impedisce
di per sé un recupero non più necessario se il ring riprende dopo il campione;
servono ulteriori prove e una valutazione del progresso tardivo. Il binario
ricostruito e il pacchetto `gpu-eight-combined-v7` restano non installati.

Una revisione successiva controlla il progresso dopo il rilevamento e dopo la
verifica dell'identità; per un recupero attribuito a un'app controlla ancora,
sotto il lock del ring, se la sequenza sospetta è già terminata. In tal caso
evita scrub, penalità e reset. Il completamento GPU può comunque avvenire dopo
l'ultimo controllo: i test host non eliminano questa finestra temporale né
simulano MES o l'hardware. Il candidato `gpu-eight-combined-v8` compila e passa
253 controlli G2, 11.011 G4, i casi a otto sessioni e le prove di transazione
su copie; non è installato.

L'audit ha rilevato anche che la ricerca del proprietario leggeva `gOwners`
senza il lock usato per scriverlo. Nel candidato successivo la copia della voce
avviene sotto `gRingLock`, rilasciato prima di acquisire `gCliLock`: non vengono
annidati nell'ordine inverso. Build e controlli host passano, inclusi 254 G2 e
11.011 G4; il pacchetto locale `gpu-eight-combined-v9` ha superato i controlli
e la transazione su copie. Non è un test di concorrenza kernel su hardware.

Il modello `test_recovery_interleavings.py` esplora 40 sequenze valide di
apertura, chiusura, identificazione e recupero con il protocollo di lock:
nessuna applica il recupero a una nuova identità; senza la guardia il modello
trova un interleaving in cui accade. Il modello astrae esplicitamente il
completamento GPU, MES e l'implementazione reale dei lock: è una verifica della
logica del protocollo, non una riproduzione del difetto sul dispositivo.

Il driver limita inoltre a 64 MiB complessivi la VRAM visibile alla CPU per
le sessioni diverse da WindowServer. Nel campione live del 29 ottobre risultano
1.080 KiB occupati e quattro sessioni aperte: il limite non era raggiunto in
quel momento. Il campione non include Brave accelerato, che non ha ottenuto una
sessione; non consente quindi di escludere pressione sul limite dopo il cambio.
La sonda sessioni salva ora questi valori per confrontarli durante la prova,
senza cambiare il limite protettivo di WindowServer.

Il candidato riproducibile `build-eight-sessions.py` controlla che il binario
base nella EFI corrente corrisponda a quello della build sorgente 0.0.664,
quindi costruisce separatamente una 0.0.665 con otto sessioni e verifica la
firma. Il processo ricompila anche la base in una cartella isolata e confronta tutte
le sette sezioni compilate di codice e dati con il binario installato; il
controllo passa e rileva una modifica di prova al codice. Firma, UUID e debug
non sono confrontati. Il candidato
rimane privo di installazione e richiede verifiche ABI, integrazione e rollback.

## Pacchetto combinato locale

`prepare-eight-efi.py` ha creato una copia EFI con una sola entry attiva per
0.0.665, conservando tutti gli 81 file della base (incluso il vecchio kext).
Il config modificato supera `ocvalidate` 1.0.8. `prepare-eight-combined.py`
verifica la base EFI corrente e il candidato Metal 25, quindi assembla insieme
EFI, 230 coppie shader, guardia `stage24-eight-session-v1` e tool diagnostico
aggiornato. Il manifest copre 551 file; firme, contenuti, entry e sintassi della
guardia sono stati controllati. La creazione resta solo locale, senza deploy.

Questo pacchetto è una base per una prova, non un fix completamente validato:
non ha ancora un installer transazionale e non ha ripristino automatico se il
nuovo kext impedisce l'avvio prima della guardia userspace. Il vecchio kext
conservato da solo non attiva automaticamente il ritorno alla vecchia entry.
Servono controlli di avvio e recupero e, dopo il riavvio concordato, prove di
concorrenza, rendering Brave, latenza e video.

## Verifica transazione dopo il riavvio del 29 ottobre

La sessione è cambiata: il candidato combinato è stato rigenerato per la nuova
boot UUID dopo che il processo della guardia stage22 ha terminato con successo.
Il controllo root ha verificato EFI e Metal attivi, tutti i 553 file del
pacchetto, versione macOS, permessi, stato stabile della guardia e identità della
sessione. Il config modificato cambia esclusivamente il percorso del kext GPU.

L'installer transazionale esistente è stato esercitato su copie temporanee
complete del pacchetto e degli attuali file, senza scrivere destinazioni live:
installazione e rollback esplicito sono passati; guasti simulati dopo lo scambio
Metal e dopo il cambio config hanno ripristinato i file precedenti. Un config
modificato nel pacchetto è stato rifiutato dalla preflight. Questi test non
verificano un guasto prima dell'avvio di macOS e non installano un recupero
UEFI automatico. Il vecchio helper di ripristino richiede adattamento allo stato
`stable` persistente attuale; non deve cancellare o azzerare la guardia.

## Installer e ripristino nello stesso avvio

`install-eight-combined.py` usa la transazione già esercitata sulle copie del
pacchetto, serializzata con il lock della guardia di boot. Registra una copia
privata dello stato stabile originale; il ripristino automatico è ammesso solo
se boot UUID e stato restano identici, la EFI ha lo stesso UUID e i file non sono
cambiati esternamente. Non cancella né reimposta la guardia. I test verificano
che uno stato pending o failed blocchi l'operazione e che la preflight acquisisca
il lock; la preflight root sul sistema attuale passa. Non è stato eseguito apply.

Il ripristino proposto è circoscritto alla stessa sessione di avvio. Non è un
meccanismo di recupero automatico UEFI da un errore del kernel al riavvio.

## Analisi del recupero prima di macOS

Il 29 ottobre la EFI verificata è montata in sola lettura, UUID
`7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3`. Il config usa OpenCore 1.0.8 con
`RequestBootVarRouting=true`, picker attivo, timeout 5 secondi e una voce
OpenShell di recupero. La lettura NVRAM con il GUID UEFI restituisce `BootOrder`
0x0080; `BootNext` e `BootCurrent` non risultano leggibili/presenti attraverso
quella richiesta. Non è stata scritta alcuna variabile.

Il sorgente OpenCore installato spiega che `RequestBootVarRouting` reindirizza
le variabili Boot dal GUID UEFI al namespace OpenCore (`OCBt*`). Quindi leggere
`BootOrder` da macOS non prova quale entry usi direttamente il firmware, né che
scrivere `BootNext` possa selezionare una seconda EFI a prova di errore. La
[documentazione OpenCore](https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/Configuration.tex)
distingue inoltre scelta della voce primaria e avvio tramite picker.

Una voce di ripristino manuale o il vecchio kext mantenuto sul disco non sono
rollback automatico. Un eventuale loader di prova che consumi una richiesta una
sola volta prima del caricamento del kernel richiede un proprio test UEFI e una
verifica della modalità di avvio effettiva della scheda. Non modificare
BootOrder, BootNext o il loader sulla base di questa sola analisi.

Il pacchetto successivo `gpu-eight-combined-v6` include in aggiunta la copia
byte per byte del config attualmente attivo in `EFI/RECOVERY/pre-eight-config.plist`.
Il controllo confronta il suo SHA-256 con l'originale e rifiuta alterazioni;
la prova transazionale su copie verifica che il file arrivi sulla EFI simulata
prima della sostituzione del config. Il vecchio kext resta anch'esso sulla EFI.
Questo consente, con accesso fisico e una shell UEFI o un altro sistema che
monti la stessa partizione, di ripristinare il vecchio config. Non ripristina
da solo il bundle Metal, lo script o lo stato di boot di macOS e non è un
rollback automatico. Nessun percorso UEFI di recupero è stato ancora provato
sulla scheda: la copia è un mezzo di recupero aggiuntivo, non una garanzia di
avvio o una ragione per riavviare senza poter intervenire fisicamente.

L'installer dispone ora anche di un percorso esplicito `--restore-backup ...
--after-reboot`, con preflight senza `--apply`: accetta solo la transazione
registrata, lo stato del candidato o quello stabile originale e un config EFI
esattamente uguale all'originale o al candidato. Dopo il ripristino confronta
i file e i permessi originali e archivia lo stato del tentativo prima di
ripristinare la guardia precedente. I controlli di identità dello stato sono
stati testati. Il test `test-eight-postboot-restore.py` esegue installazione e
ripristino su copie reali dei file, simulando un nuovo UUID di avvio e provando
sia il config candidato sia quello già ripristinato; una modifica a un file
interessato viene rifiutata dalla preflight. Il test non avvia UEFI o macOS e
non prova il recupero su hardware o guasti durante il ripristino stesso.

## Compatibilità del RADV installato con VMID diversi da 8

La libreria attiva `libvulkan_radeon.dylib` ha SHA-256
`f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155`.
Il sorgente Darwin RADV controlla la versione ABI e confronta il VMID con 8,
ma un valore diverso produce soltanto una riga diagnostica prima di proseguire
con `QueryInfo`. È stato controllato anche il binario installato: nel percorso
`acd_device_initialize` il confronto con 8 e 64 porta a `fprintf` e poi converge
sulla chiamata `acd_kext_query_info`; non esce dal ramo per il solo VMID diverso.
Questo elimina quel controllo specifico come causa certa di rifiuto dei VMID
9–15. Non prova che l'intera libreria o ogni shader siano privi di altri limiti,
né che i contesti 12–15 funzionino realmente sulla GPU.

## Scheduler con otto sessioni

Il test host del profilo otto copre anche sette sessioni applicative in attesa:
l'ordine cronologico, la rimozione progressiva dalla coda e l'identificazione
del proprietario delle submission più vecchie. La verifica usa ASan/UBSan e
non simula le temporizzazioni reali della GPU.

Una lettura `sessstat 5` sul sistema attuale con quattro sessioni ha rilevato
credito G5 pari a 1, 349 submit ritardate su 24.694 ammesse, 368 ms totali,
massimo 6 ms e nessun timeout. È un dato cumulativo di quella sessione, non una
misura sincronizzata con YouTube; non dimostra che G5 causi o risolva lo stutter.
Il limite di credito è condiviso e resta invariato nel candidato a otto sessioni.

## Controllo dopo la prova

`tools/baremetal/navi44-gpu-diagnostics/session-check.py` campiona le pagine
statistiche 0–3 e 6–9, verifica slot e VMID 8–15, identità uniche delle sessioni
attive e campiona il progresso della coda. Segnala gli slot aggiuntivi attivi,
HUNG e sessioni avvelenate. Le letture sono sequenziali: cambiamenti di sessione
possono rendere incoerenti i conteggi e vengono segnalati come tali. Il check
non apre una nuova sessione GPU e non dimostra la correttezza del rendering;
la lettura diagnostica aggiorna il riferimento interno dell'ultimo fault.
Il parser ha test per VMID errato, ID duplicato, contatori inconsistenti e
assenza di progresso. Deve essere eseguito con il tool aggiornato dopo l'avvio
del candidato e con più applicazioni effettivamente in uso.
