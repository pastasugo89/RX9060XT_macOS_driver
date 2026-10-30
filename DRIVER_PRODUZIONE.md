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

La build nativa macOS di RADV passa. `test-radv-shader-oom.py` estrae la vera factory modificata e inietta fallimenti di allocazione in ciascuno degli otto stage e nel GS copy, oltre ai percorsi vuoto e riuscito; passa con ASan/UBSan. Restano da qualificare la pulizia completa dei dati debug nei percorsi di errore, il teardown Vulkan e la pressione di memoria sul device reale. Il RADV ricostruito ha SHA256 `48c302b6bf982d37df9d7f3ec87ac0808f8e1272778aaa7cde062d8fd240c11a` e non è installato.

## 4. Regola per le prossime consegne

Consegne per capacità: memoria, contesti, sincronizzazione, compilatore, Metal, display, video e framework. Ogni difetto di un'app diventa un riproduttore di quel contratto. I test nelle applicazioni verificano l'integrazione, senza regole di rendering basate sul loro nome.

Le richieste audio, Bluetooth Qualcomm, Wi-Fi/AirDrop, sensori, CPU, refresh a 60 Hz e spegnimento restano nel goal e nella checklist principale. La prima priorità operativa rimane rendere affidabili allocazione/esecuzione/rendering GPU. Il successo di questo primo modulo non chiude il goal.
