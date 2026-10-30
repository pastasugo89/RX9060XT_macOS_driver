# Passaggio allo stack GPU per uso generale

Avviato il 30 ottobre 2026 su richiesta dell'utente. Obiettivo di completezza: [checklist delle capacità](COMPLETEZZA_DRIVER_GPU.md). La GPU deve servire le normali applicazioni tramite contratti generali; il numero di identificatori hardware non deve determinare quante applicazioni possono aprirla.

## Base attualmente installata e verificata

Boot `CE6DAB32-C985-4109-ACDA-096A043974BE`, Metal bundle 28, profilo `stage25-archive-boundary-v1`. La guardia registra `desktop-stable-120s` e l'utente conferma il login accelerato. Il precedente assert sugli archivi nativi non compare nei nuovi report osservati. Restano difetti reali: icona Finder non visibile, Finder crashato dopo il rifiuto del backend e un componente Dock crashato in RADV. Questa è una base di recupero, non un driver completo.

Le modifiche di questo passaggio sono nei sorgenti/staging. Non sono ancora state installate nel kernel né nel bundle di avvio; non richiedono un riavvio ora.

## 1. Contesti software separati dai VMID hardware

Nel driver attuale `Session.slot` e `Session.vmid` sono legati per tutta la vita della sessione. `gSlot`, `gWin`, code di fairness e diverse statistiche usano lo stesso indice. Aprire un client occupa immediatamente un VMID fra 8 e 15. L'esaurimento di otto sessioni appare quindi anche con poche app visibili: wallpaper, notifiche, servizi delle icone e processi del browser sono client distinti.

La nuova struttura deve avere:

1. **Registro dei contesti logici:** identità con generazione, credenziali, page table, buffer, mappe, riferimenti e sequenze; allocazione indipendente dal numero dei VMID.
2. **Tabella delle assegnazioni hardware:** otto slot gestiti separatamente; assegnazione temporanea del VMID quando serve eseguire lavoro.
3. **Scheduler dei submit:** coda dei contesti pronti, priorità del compositor, dipendenze e timeout; un contesto in attesa di hardware rimane valido.
4. **Cambio sicuro di proprietario:** attendere il ritiro delle sequenze del proprietario precedente, programmare la nuova root, ricevere l'ACK dell'invalidazione TLB, poi pubblicare l'assegnazione.
5. **Chiusura e fault:** nessuna liberazione delle page table prima di park/ACK; quarantena delle risorse se lo stato hardware è incerto.

### Primo componente implementato

`cobalt64/src/navi48-bringup/src/amd/production_vm_lease_pure.h` contiene la politica di assegnazione, priva di MMIO e chiamate del sistema. Il componente riserva il primo slot al compositor, trova slot vuoti o ritirati per le applicazioni, attende una sequenza quando necessario e usa ticket con generazione per rifiutare operazioni vecchie. L'assegnazione passa per uno stato Binding prima delle scritture hardware; un ACK fallito conserva vecchia e nuova root in quarantena.

Il test `production_vm_lease_test.cpp` passa con ASan/UBSan: mille identità logiche alternate, ticket obsoleti, acquisizioni concorrenti simulate, attese di retirement, riserva del compositor e chiusura subordinata all'ACK. **Non prova mille applicazioni sul kernel attuale. Il modulo non è ancora collegato a native_s1c.cpp.**

### Registro dei contesti implementato

`production_context_pure.h` aggiunge il ciclo di vita dei contesti logici su una tabella fornita dal chiamante, senza derivarne la capacità dagli otto VMID. Ogni record ha identità monotona, proprietario, root, ultima sequenza e riferimenti alle operazioni CPU in corso. Una chiusura impedisce nuove operazioni ma conserva le risorse fino al rilascio degli ultimi riferimenti, al retirement e alla scomparsa delle root da tutte le assegnazioni hardware, comprese quelle in Binding e Quarantined. Lo stato Destroying impedisce di riciclare il record prima che il kernel abbia realmente distrutto le risorse.

`production_context_test.cpp` mantiene **mille record applicazione aperti contemporaneamente**, più il compositor, e ne esegue il lavoro simulato riutilizzando sette VMID applicazione. ASan/UBSan verificano anche riferimenti obsoleti con il medesimo proprietario, rifiuto di ticket appartenenti ad altri contesti, race fra close e operazione CPU, fallimento del cambio root con conservazione di entrambe le page table, e mancato riuso delle identità dopo overflow. Il test controlla le politiche CPU: **non apre mille client IOAccel e non esegue comandi sulla GPU**. Registro e lease attendono ancora l'integrazione kernel descritta sotto.

Il kernel dovrà fornire il token proprietario ricavato dall'IOUserClient autenticato, usare un contatore delle identità unico per il boot, mantenere il lock comune registro/lease e ordinare l'accounting del submit con la pubblicazione sul ring. La politica non sostituisce questi obblighi con dati ricevuti dall'ioctl.

### Chiusura dei contesti collegata al percorso kernel

`production_context_retire.h` è usato da `native_s1c.cpp` nella chiusura effettiva. Prima della modifica il percorso liberava i BO, poi cancellava le PTE della finestra fence condivisa di VMID 0 e ignorava il risultato della relativa invalidazione. Ora, dopo il retirement del lavoro del client, parcheggia la root privata, cancella le PTE fence e verifica l'ACK di VMID 0 **prima** di rilasciare i BO e le page table. Un fallimento conserva risorse e record delle fence e rende non riutilizzabile lo slot.

`test-kernel-context-close.py` esegue il vero corpo di `n1c_close` e i callback `ContextRetireEnv` con IO controllato: 32 percorsi, ruoli e profili legacy/multisessione, fence presenti/assenti, errori di retirement e ACK, chiusura ripetuta. ASan/UBSan passano; ogni free richiede il retirement e gli ACK pertinenti. I test esistenti G2 e host import sono aggiornati al nuovo ordine senza rimuovere il vincolo di invalidazione. Il kext completo x86_64 a otto sessioni compila e la firma ad hoc si verifica in `build-production-contexts`; è solo un artefatto locale, non installato. Il registro logico e l'assegnazione dinamica dei VMID restano da collegare: questa chiusura è un prerequisito per il loro riuso sicuro.

### Integrazione kernel da completare prima del rilascio

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
