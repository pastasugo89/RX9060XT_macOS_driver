# Passaggio allo stack GPU per uso generale

Avviato il 30 ottobre 2026 su richiesta dell'utente. Obiettivo di completezza: [checklist delle capacità](COMPLETEZZA_DRIVER_GPU.md). La GPU deve servire le normali applicazioni tramite contratti generali; il numero di identificatori hardware non deve determinare quante applicazioni possono aprirla.

## Fase di sviluppo e criterio di rilascio

La fase principale è **lo sviluppo del driver per uso generale**. L'accelerazione confermata dall'utente è il punto di partenza: non occorre ricominciare il bring-up o continuare a trattare ogni applicazione come un caso speciale. Il nome storico della directory `navi48-bringup` non definisce la maturità né il target hardware del prodotto.

Questo passaggio non dichiara il driver già pronto per la produzione. La base installata resta il riferimento di recupero; i nuovi componenti diventano candidati installabili dopo build riproducibile, verifica dell'ABI e test pertinenti. Le prove sul dispositivo qualificano poi stabilità, isolamento e prestazioni. I test CPU e la compilazione non chiudono quelle verifiche.

Il primo modulo strutturale è la gestione di più client: contesti logici indipendenti dagli otto VMID utilizzati dal driver, assegnazione al submit, sincronizzazione e rilascio sicuro delle risorse. Il codice del profilo 64 descritto sotto è già integrato nei sorgenti, ma non nel kernel attualmente avviato. Il limite di 64 record è provvisorio e configurabile; non è un limite di otto applicazioni né una promessa di capacità illimitata.

Le consegne successive seguono le dipendenze: memoria/contesti/sincronizzazione; compilazione shader e contratto Metal; presentazione e timing del display; video hardware e integrazione con i framework. Browser, Finder e altre app sono carichi di verifica di queste capacità. Ogni consegna deve indicare separatamente cosa è implementato, cosa è provato sulla GPU e cosa rimane aperto nella checklist completa.

## Base attualmente installata e verificata

Boot `CE6DAB32-C985-4109-ACDA-096A043974BE`, Metal bundle 28, profilo `stage25-archive-boundary-v1`. La guardia registra `desktop-stable-120s` e l'utente conferma il login accelerato. Il precedente assert sugli archivi nativi non compare nei nuovi report osservati. Restano difetti reali: icona Finder non visibile, Finder crashato dopo il rifiuto del backend e un componente Dock crashato in RADV. Questa è una base di recupero, non un driver completo.

Le modifiche di questo passaggio sono nei sorgenti/staging. Non sono ancora state installate nel kernel né nel bundle di avvio; non richiedono un riavvio ora.

## 1. Contesti software separati dai VMID hardware

Nel driver installato `Session.slot` e `Session.vmid` sono legati per tutta la vita della sessione. `gSlot`, `gWin`, code di fairness e diverse statistiche usano lo stesso indice. Aprire un client occupa immediatamente un VMID fra 8 e 15. L'esaurimento di otto sessioni appare quindi anche con poche app visibili: wallpaper, notifiche, servizi delle icone e processi del browser sono client distinti. Il nuovo profilo nei sorgenti sostituisce questo legame come descritto sotto.

La nuova struttura deve avere:

1. **Registro dei contesti logici:** identità con generazione, credenziali, page table, buffer, mappe, riferimenti e sequenze; allocazione indipendente dal numero dei VMID.
2. **Tabella delle assegnazioni hardware:** otto slot gestiti separatamente; assegnazione temporanea del VMID quando serve eseguire lavoro.
3. **Scheduler dei submit:** coda dei contesti pronti, priorità del compositor, dipendenze e timeout; un contesto in attesa di hardware rimane valido.
4. **Cambio sicuro di proprietario:** attendere il ritiro delle sequenze del proprietario precedente, programmare la nuova root, ricevere l'ACK dell'invalidazione TLB, poi pubblicare l'assegnazione.
5. **Chiusura e fault:** nessuna liberazione delle page table prima di park/ACK; quarantena delle risorse se lo stato hardware è incerto.

### Primo componente implementato

`cobalt64/src/navi48-bringup/src/amd/production_vm_lease_pure.h` contiene la politica di assegnazione, priva di MMIO e chiamate del sistema. Il componente riserva il primo slot al compositor, trova slot vuoti o ritirati per le applicazioni, attende una sequenza quando necessario e usa ticket con generazione per rifiutare operazioni vecchie. L'assegnazione passa per uno stato Binding prima delle scritture hardware; un ACK fallito conserva vecchia e nuova root in quarantena.

Il test `production_vm_lease_test.cpp` passa con ASan/UBSan: mille identità logiche alternate, ticket obsoleti, acquisizioni concorrenti simulate, attese di retirement, riserva del compositor e chiusura subordinata all'ACK. **Non prova mille applicazioni sul kernel attuale.** La politica è ora collegata al profilo kernel a contesti virtuali descritto sotto; non è ancora installata sul sistema avviato.

### Registro dei contesti implementato

`production_context_pure.h` aggiunge il ciclo di vita dei contesti logici su una tabella fornita dal chiamante, senza derivarne la capacità dagli otto VMID. Ogni record ha identità monotona, proprietario, root, ultima sequenza e riferimenti alle operazioni CPU in corso. Una chiusura impedisce nuove operazioni ma conserva le risorse fino al rilascio degli ultimi riferimenti, al retirement e alla scomparsa delle root da tutte le assegnazioni hardware, comprese quelle in Binding e Quarantined. Lo stato Destroying impedisce di riciclare il record prima che il kernel abbia realmente distrutto le risorse.

`production_context_test.cpp` mantiene **mille record applicazione aperti contemporaneamente**, più il compositor, e ne esegue il lavoro simulato riutilizzando sette VMID applicazione. ASan/UBSan verificano anche riferimenti obsoleti con il medesimo proprietario, rifiuto di ticket appartenenti ad altri contesti, race fra close e operazione CPU, fallimento del cambio root con conservazione di entrambe le page table, e mancato riuso delle identità dopo overflow. Il test controlla le politiche CPU: **non apre mille client IOAccel e non esegue comandi sulla GPU**. Questo modulo rimane un modello isolato del ciclo di vita; il percorso kernel conserva i record `Session` stabili e i riferimenti `N1cRef` autenticati dall'IOUserClient.

Il contratto richiede un token proprietario ricavato dall'IOUserClient autenticato, un contatore delle identità unico per il boot, il lock comune registro/lease e l'accounting del submit ordinato con la pubblicazione sul ring. Il profilo kernel descritto sotto integra le identità `N1cRef`, i lock e tale ordine; la qualificazione concorrente IOAccel rimane aperta. La politica non sostituisce questi obblighi con dati ricevuti dall'ioctl.

### Chiusura dei contesti collegata al percorso kernel

`production_context_retire.h` è usato da `native_s1c.cpp` nella chiusura effettiva. Prima della modifica il percorso liberava i BO, poi cancellava le PTE della finestra fence condivisa di VMID 0 e ignorava il risultato della relativa invalidazione. Ora, dopo il retirement del lavoro del client, parcheggia la root privata, cancella le PTE fence e verifica l'ACK di VMID 0 **prima** di rilasciare i BO e le page table. Un fallimento conserva risorse e record delle fence e rende non riutilizzabile lo slot.

`test-kernel-context-close.py` esegue il vero corpo di `n1c_close` e i callback `ContextRetireEnv` con IO controllato: 32 percorsi, ruoli e profili legacy/multisessione, fence presenti/assenti, errori di retirement e ACK, chiusura ripetuta. ASan/UBSan passano; ogni free richiede il retirement e gli ACK pertinenti. I test esistenti G2 e host import sono aggiornati al nuovo ordine senza rimuovere il vincolo di invalidazione. Il kext completo x86_64 a otto sessioni compila e la firma ad hoc si verifica in `build-production-contexts`; è solo un artefatto locale, non installato. Questa chiusura è ora usata anche dall'integrazione del profilo 64 riportata sotto; il suo riuso sicuro sulla GPU resta da qualificare.

Anche `bo_release` in modalità Normal richiede ora gli ACK prima di restituire memoria a entrambi i pool VRAM. Il vecchio controllo conservava GTT/import host ma restituiva ugualmente VRAM dopo un'invalidazione fallita. `test-kernel-bo-release.py` esegue il blocco reale con 40 combinazioni di mapping, fence e ACK: memoria e budget rimangono trattenuti quando una traduzione è incerta. Non è un meccanismo di recupero della memoria in quarantena; il percorso attuale la conserva fino al reboot. Test ASan/UBSan e compilazione kernel passano, verifica hardware ancora aperta.

### Profilo kernel con 64 contesti logici e otto VMID

Il profilo di build `NATIVE_SESSIONS=8 LOGICAL_CONTEXTS=64`, con i ruoli applicativi/multisessione già attivi, usa ora la politica di lease nel percorso effettivo di `native_s1c.cpp`:

- `n1c_open` alloca il record e la root senza assegnare un VMID né programmare CONTEXT; l'esaurimento del contatore identità a 32 bit rifiuta nuovi open, senza wrap/ABA.
- `ring_submit_production` prende i lock nell'ordine registro → ring. Controlla spazio, fairness e retirement; assegna o riusa un VMID soltanto per eseguire lavoro. Le attese rilasciano entrambi i lock.
- `session_bind_locked` verifica la geometria del contesto hardware, programma la root e richiede l'ACK TLB prima di pubblicare il ticket. `ring_put_locked` aggiorna l'ultima sequenza del lease prima di scrivere e notificare il ring.
- `session_flush_locked` invalida soltanto un VMID attualmente appartenente alla root chiamante. Una root espulsa non invalida il VMID passato ad altri; il suo prossimo bind farà l'invalidazione. La chiusura parcheggia solo l'assegnazione ancora posseduta, oppure conferma che la root non è più referenziata. Binding incerti conservano entrambe le root.
- Il budget globale delle page table è 256 MiB, separato sia dai 64 record sia dagli otto VMID; rimane anche il limite per-client. I blocchi fisici sono allocati al bisogno. Le finestre fence rimangono per record logico, con invalidazione prima del riuso; l'allocatore dinamico indipendente dei loro indirizzi resta da realizzare.
- Hello/QueryInfo riportano `N48N_VMID_DYNAMIC` e il flag `N48N_INFO_DYNAMIC_VMID`, senza dichiarare un VMID permanente. Layout e major ABI restano invariati. Le pagine diagnostiche 0–9 conservano il significato storico; 32–95 espongono tutti i record del profilo 64. Il VMID diagnostico è una fotografia dell'assegnazione corrente o il sentinel non assegnato.
- Le identità del log delle sequenze e le code di fairness usano l'indice logico. Il primo slot hardware resta riservato al compositor anche se un'app occupa il primo record software. Le vecchie prove G1 che scrivono direttamente VMID 8 sono rifiutate in questo profilo; le statistiche restano disponibili.

`test-kernel-vmid-leases.py` esegue i veri binder, scheduler, writer del ring, flush e park con MMIO simulato, usando i veri builder PM4 e le politiche G2/G5. Verifica 64 record, riuso dopo retirement, VMID codificato nell'IB, proprietario/sequenza prima di ogni doorbell, attese senza lock, ticket obsoleti, fairness, timeout, quarantena, overflow delle sequenze, app prima del compositor e sostituzione del compositor con altri client vivi. ASan/UBSan passano. I cinque test esistenti G2/G4/G5/host import/S1c passano; il kext completo del profilo 64 compila su macOS x86_64. **Non è una prova di 64 open IOAccel reali, isolamento sulla GPU o stabilità del desktop.** Il profilo è locale e non installato; il numero 64 è un limite di metadata configurato, non la capacità hardware né una dichiarazione di supporto illimitato.

Il Makefile registra il profilo delle capacità e forza la ricompilazione degli oggetti quando cambia, anche se i cambi avvengono entro lo stesso secondo. Questo impedisce di mescolare unità compilate con capacità diverse riusando una cartella BUILD. `test-kernel-build-profile.py` compila il vero oggetto kernel in una cartella temporanea: il profilo invariato conserva mtime/hash, 64 → 8 cambia l'oggetto e 8 → 64 riproduce il primo hash. La prova richiede SDK/firmware locali e non carica kext.

Il confronto hardware è tracciato contro Linux commit `d89e1d186ec9271bf78e62771779e9fc03bf0fc3`: [gestione dei VMID](https://github.com/torvalds/linux/blob/d89e1d186ec9271bf78e62771779e9fc03bf0fc3/drivers/gpu/drm/amd/amdgpu/amdgpu_ids.c), [flush VM](https://github.com/torvalds/linux/blob/d89e1d186ec9271bf78e62771779e9fc03bf0fc3/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.c), [GFX12](https://github.com/torvalds/linux/blob/d89e1d186ec9271bf78e62771779e9fc03bf0fc3/drivers/gpu/drm/amd/amdgpu/gfx_v12_0.c). Linux ordina il flush sul ring e sincronizza PFP/ME; il nostro cambio attende il retirement sulla CPU e programma/invalida prima della nuova doorbell. La correttezza di questa sequenza sul dispositivo va ancora provata con indirizzi virtuali uguali in root diverse, dati e shader distinti, ricambio ripetuto, concorrenza e fault. Il confronto del sorgente e i test CPU non sostituiscono quelle prove.

### Attese concorrenti alla chiusura

`n1c_wait` acquisisce ora una fotografia di identità, Hello, poison e contatori sotto un breve lock del registro. Il lock è rilasciato prima delle attese e del controllo/recovery globale. `LAST` viene risolto una sola volta dalla sequenza della sessione iniziale; una chiusura o riapertura dello stesso record fa abortire l'attesa, senza seguire il nuovo proprietario o il suo reset del contatore globale. La validità è controllata anche dopo `hang_poll`.

`test-kernel-wait-identity.py` esegue il vero helper e il vero WaitSeq in 21 percorsi controllati, con close/reopen alle fotografie, al sonno e durante il controllo del blocco. Le mutazioni del registro sono rinviate finché il lock è rilasciato; ogni attesa e controllo hang verifica che il lock non sia trattenuto. Copre anche nuove submission dello stesso proprietario, conclusione, polling, timeout, poison, HUNG, registro non inizializzato e riferimenti non validi. ASan/UBSan passano. Rimangono da qualificare le chiamate IOAccel realmente concorrenti e gli altri lettori diagnostici del record.

### Candidato riproducibile dalla base accelerata

Il 31 ottobre il sistema è avviato nuovamente con kernel 665, UUID Mach-O `7CB8DDF0-FAD7-31A3-9439-1F056AABAAE3`, e bundle Metal 28. L'eseguibile abilitato nella EFI ha SHA256 `607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24`. I suoi sorgenti conservati in `gpu-eight-repro-v6` differiscono dal repository principale anche nell'inizializzazione PSP/SMU, nel caricamento firmware e nelle protezioni della console: la build diretta del solo repository non è quindi una sostituzione verificata della base installata.

`tools/baremetal/navi44-desktop/build-production-contexts.py` ricompila quella base e richiede che tutte le sette sezioni Mach-O con contenuto coincidano con il binario di riferimento. Conserva inizializzazione e firmware e applica soltanto otto file espliciti relativi a capacità/ABI, contesti, rilascio e attese, più i marcatori coerenti di versione 666 nel plist, nella risposta nativa e nelle due tabelle ops. Rifiuta input dell'overlay non committati, una base EFI diversa, output preesistente o esterno a `research/builds`, e modifiche dei sorgenti durante la compilazione. Non modifica la EFI, non installa/carica kext e non riavvia.

Il primo candidato è in `research/builds/macos-20261031/production/kernel-contexts-v1`: versione 666, 64 contesti logici, otto VMID, SHA256 binario `2f4edf9337319376e3a9ce9565f0cc10ab10fdfa3c7a17ca6b1193ea4d23d58d`. Build completa e verifica della firma passano. I quattro test kernel eseguono ora il codice estratto **dai sorgenti del candidato**, selezionati con `--kernel-source`, e passano con ASan/UBSan. Il manifest conserva inventario/hash degli input, sezioni della base, comandi, profilo e risultati; il suo stato distingue build/test CPU da verifica hardware. Sei test locali del preparatore coprono identità/versione della base, voci duplicate, percorsi esterni, conservazione dell'inizializzazione e coerenza dei marcatori. Il candidato non è installato: isolamento, ricambio dei VMID sulla GPU e convivenza con il desktop rimangono da verificare prima del rilascio.

### Integrazione kernel da completare prima del rilascio

Assegnazione al submit, accounting prima della doorbell, invalidazioni legate al proprietario corrente, chiusura e log delle identità sono implementati nel profilo 64. Le caselle sotto restano aperte finché l'integrazione e le prove complete corrispondenti non le qualificano; non sono il conteggio dei soli file scritti.

- [ ] Separare `N1cRef`/registro logico da indice hardware e VMID. Definire la compatibilità della versione ABI; Hello/QueryInfo non devono fingere un VMID permanente.
- [ ] Separare i budget globali/per-client dal numero di slot hardware. Una nuova sessione logica non deve riservare inutilmente tutta la capacità di page table.
- [ ] Separare la fence window globale dei BO accessibili a VMID 0 dall'indice del contesto logico; non riciclare indirizzi con lavoro ancora in volo.
- [ ] Inserire claim/binding/ACK nel percorso di submit, con ordine dei lock fra sessione, lease, TLB e ring verificato.
- [ ] Pubblicare l'ultima sequenza sotto lo stesso confine che rende visibile il submit; impedire il riuso del VMID durante quella finestra.
- [ ] Rendere GemVa/import/free consapevoli dell'assegnazione corrente: nessuna invalidazione del VMID ormai passato a un altro proprietario.
- [ ] Conservare associazione sequenza → contesto anche dopo un cambio di VMID, per attribuire i fault al lavoro giusto.
- [ ] Adeguare fairness, timeout, recovery, statistiche e chiusura ai contesti logici; nessun indice di client usato per accedere a un array hardware di otto elementi.
- [ ] Verificare la gestione del compositor e della presentazione prima di abilitare il nuovo percorso sul desktop.
- [ ] Eseguire test kernel/memoria/ABI e poi carichi reali con più di otto processi, crash/riavvii dei client, pressione di memoria e confronto dei risultati grafici.
- [ ] Verificare l'identità delle chiamate WaitSeq concorrenti a close/riapertura del record, oltre ai percorsi di submit e import già coperti; completare la prova del ciclo di vita IOAccel reale.

Questa sostituzione riguarda gestione della memoria e scheduling; alzare una costante da otto a un numero maggiore non realizza il progetto. Riferimento architetturale: [AMDGPU, VM e code](https://docs.kernel.org/gpu/amdgpu/driver-core.html).

## 2. Device Metal coerente con il backend

Nei log del 30 ottobre Finder riceve inizialmente il device, poi il backend non riesce ad aprire un contesto e RenderBox termina perché non può creare l'index buffer. La verifica preliminare APP apre e chiude una sessione, mentre Mesa apre quella effettiva più tardi: esiste una finestra di competizione.

Il sorgente ora riserva il backend reale prima di esporre un device Metal ai processi diversi da WindowServer. Un errore restituisce nil dalla factory del device. Il percorso di inizializzazione della base è conservato e quello di WindowServer rimane lazy. Questo elimina l'incoerenza iniziale; **non sostituisce la virtualizzazione dei contesti e non risolve la capacità complessiva**.

`test-device-reservation.py` compila il vero corpo dell'inizializzatore con superclass/backend controllati e verifica sedici combinazioni di rifiuto, errore, ruolo e inizializzazione. Passa con ASan/UBSan; verifica l'ordine e il risultato della factory, non l'integrazione IOAccel dal vivo.

## 3. Errori di allocazione shader propagati

Il nuovo crash di `com.apple.dock.extra` è in `radv_CreateGraphicsPipelines+7454`: l'istruzione legge a offset `0x212` tramite un puntatore shader nullo. Nel sorgente RADV esiste un percorso concreto in cui la creazione degli shader ritorna un puntatore nullo, ma la pipeline continua e può essere inserita nella cache come riuscita. È compatibile con il crash osservato; la causa iniziale di quella specifica allocazione resta da dimostrare con una prova controllata.

La patch locale `cobalt64/mesa-patches/0011-radv-propagate-graphics-shader-allocation-failure.patch`:

- rende esplicito il risultato della creazione degli shader grafici e del GS copy shader;
- propaga il fallimento ai chiamanti pipeline e shader object;
- evita di inserire una pipeline parziale in cache dopo quel fallimento;
- gestisce il ramo uncached prima di dereferenziare uno shader nullo.

La verifica del percorso di upload ha trovato anche una doppia responsabilità di distruzione: alcuni errori liberavano lo shader dentro `radv_shader_binary_upload`, poi la factory lo liberava nuovamente. Ora gli helper restituiscono l'errore e la factory usa la distruzione ordinaria dell'oggetto inizializzato. Questa rilascia arena, copia del codice, dati debug e mutex. I dati debug passano esplicitamente di proprietà e il record sorgente viene svuotato; una creazione fallita pulisce anche gli stage non ancora visitati. Il ramo senza supporto RTLD restituisce un errore con output nullo. Le pipeline compute e gli shader object propagano a loro volta l'allocazione fallita; i dump diagnostici verificano l'esistenza dello shader.

Verifiche CPU con ASan/UBSan:

- `test-radv-shader-oom.py`: vera factory grafica, fallimento in ciascuno degli otto stage e nel GS copy, percorsi vuoto/riuscito, dati debug nei percorsi cached/uncached.
- `test-radv-shader-lifetime.py`: vera factory uncached, helper di upload e distruttore; 46 percorsi complessivi con/senza RTLD e memoria visibile/invisibile. Fallimenti di oggetto, arena, copia del codice, DMA, RTLD e replay: nessuna allocazione, mutex o cache object tracciato rimane posseduto all'uscita.
- `test-radv-compute-oom.py`: blocco di compilazione/cleanup della pipeline compute e funzioni complete di creazione shader object compute/binario; otto percorsi controllati, errore propagato, nessuna cache di successo dopo il fallimento e nessun dump di shader nullo.

La build nativa macOS di RADV passa. Il nuovo SHA256 è `dc733788a2302fc29dfd7498dcdf27c749bf1830a201b1833026ca7b9db05bbe`. Il binario **non è installato**. Queste prove non qualificano il teardown di un intero device Vulkan, tutte le possibili allocazioni del compilatore/parser, vecchie cache parziali già persistite, né la pressione di memoria sulla GPU reale: quelle verifiche restano aperte.

## 4. Regola per le prossime consegne

Consegne per capacità: memoria, contesti, sincronizzazione, compilatore, Metal, display, video e framework. Ogni difetto di un'app diventa un riproduttore di quel contratto. I test nelle applicazioni verificano l'integrazione, senza regole di rendering basate sul loro nome.

Le richieste audio, Bluetooth Qualcomm, Wi-Fi/AirDrop, sensori, CPU, refresh a 60 Hz e spegnimento restano nel goal e nella checklist principale. La prima priorità operativa rimane rendere affidabili allocazione/esecuzione/rendering GPU. Il successo di questo primo modulo non chiude il goal.
