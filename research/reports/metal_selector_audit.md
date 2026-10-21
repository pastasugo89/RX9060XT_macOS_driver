# Audit dei selettori Metal e del contratto del bundle (25G83)

Data: 13/10/2026. Analisi statica locale, senza esecuzione del bundle e senza modifiche al driver.
Fonti: `cobalt64/tools/native/navi48metal/` e metadati Objective-C già estratti in
`research/macos/25G83/rea/classdump/{metal/Metal,amdx6000mtl/AMDRadeonX6000MTLDriver}/`.
Questo audit indipendente non ha aperto sessioni native REA; non ha analizzato firmware,
interni dei kext Apple o codice in `research/refs/`. Per `lazyInitialize` integra inoltre
l'evidence statica Metal prodotta dall'indagine principale con MCP REA/Ghidra e
risoluzione dei selector refs sul DSC originale (vedi `ioaccelerator_abi_re.md`).
Non sono state effettuate osservazioni runtime macOS.

## 1. Il confronto «24/164» non misura API mancanti

Il report `macos_25G83_re.md` §4h confronta gli override del device AMD con quelli di
Navi48Device. La catena reale del device è `Navi48Device → MTLIOAccelDevice → _MTLDevice → NSObject`.
Un metodo assente dal sorgente del plugin può essere ereditato, oppure appartenere
soltanto al backend AMD. La sua assenza non dimostra un `doesNotRecognizeSelector:`.

Ricontrollo locale delle dichiarazioni `- (...)` nei due header AMD e dei metodi
in `@implementation Navi48Device` (deduplicazione per selettore, senza macro):

| Confine del conteggio | Risultato |
|---|---:|
| Metodi di istanza espliciti nei due device AMD | 162 |
| Metodi espliciti di Navi48Device | 60 |
| Selettori comuni | 23 |
| Metodi AMD senza override Navi48 | 139 |
| Di questi, dichiarati in MTLIOAccelDevice o _MTLDevice | 65 |

Includendo i getter delle proprietà dichiarate e i setter delle proprietà non readonly,
i device AMD espongono 527 selettori; 499 non hanno override esplicito Navi48 e **430 di
questi hanno già una dichiarazione nelle basi**. Sono conteggi di metadati, non percentuali
di implementazione: non includono categorie esterne, metodi dinamici, macro, né validano i corpi.
La differenza da 164/24 può dipendere dal vecchio parser e dalla sua deduplicazione.
Riproduzione: `python3 tools/metal_selector_audit.py --summary`; senza `--summary`
si ottengono selettori, dichiarazioni, percorsi, righe e SHA-256 degli input. È uno
strumento di inventario limitato alle dichiarazioni su una riga, non un parser ObjC
generale. Le proprietà con tipi struct e senza attributi sono comprese.

Esempi dichiarati dalla base che il vecchio confronto segnalava:

| Selettore | Fonte nei metadati Metal |
|---|---|
| `supportsRaytracing`, `supportsInt64`, `supportsFunctionPointers`, `supportsDynamicLibraries` | `_MTLDevice.h:413`, `:111`, `:223`, `:224` (proprietà/getter) |
| `minLinearTextureAlignmentForPixelFormat:` | `_MTLDevice.h:518` |
| `sampleTimestamps:gpuTimestamp:` | `_MTLDevice.h:635` |
| `newArgumentEncoderWithLayout:` | `MTLIOAccelDevice.h:91`, `_MTLDevice.h:534` |
| `newIndirectCommandBufferWithDescriptor:maxCommandCount:options:` | `MTLIOAccelDevice.h:78` |
| `compiler`, `newSharedEvent`, `newSharedEventWithHandle:` | `_MTLDevice.h:385`, `:614`, `:615` |
| `computeFunctionKeyWithComputePipelineDescriptor:options:keySize:` | `_MTLDevice.h:683` |
| `newComputePipelineWithDescriptor:variant:` | `_MTLDevice.h:742` |
| `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:` | `_MTLDevice.h:757` |

**Limite:** una dichiarazione ereditata può avere un corpo astratto, un errore, un risultato
nil o dipendere da risorse IOAccel non inizializzate. I corpi e le precondizioni restano da verificare.

## 2. Gap prioritari verificabili

### A. Firma ABI di `lazyInitialize` incoerente

**Osservato:** `MTLIOAccelDevice.h:133` dichiara `- (signed char)lazyInitialize`;
`Navi48Device.m:76` lo ridefinisce nel forward header come `void`, e l'override a
`:6009` restituisce `void`, chiamando la base senza preservarne il risultato.

**Confermato dall'indagine principale (statica REA):** il metodo Apple a
`0x7ff80f5a9a2a` restituisce 0 sui fallimenti shared/dirty-ring/pool e 1 al successo,
con `MOVZX EAX,R14B` (Evidence
`ev_4f0340b1e8e4bb52a0fac6c4b4118d58e0e132858c532cee918bc285603654ef`).
Il base init a `0x7ff80f47e7cf` consuma `AL` dopo l'invio di `lazyInitialize` e decide
se accettare o rilasciare il device (Evidence
`ev_f745f5ac2a9b7bf21954d5f84e36a230fe94a21e10d6c89a66c89d1d5d042ce8`).
I selector refs sono risolti sul cache originale: `0x7ff841206ae0` è
`supportLazyInitialization`, `0x7ff841206ae8` è `lazyInitialize`.

**Conseguenza:** con la variante supportata `N48_LAZY=0`, questo percorso iniziale
consuma un valore che l'override `void` non garantisce. Il default `N48_LAZY=1`
salta quel ramo; eventuali consumi successivi del ritorno restano da verificare.
Il compilatore locale non rileva il conflitto perché vede soltanto il forward header
incompleto. L'effetto concreto del bundle compilato non è stato riprodotto su macOS.

**Prossimo passo:** correggere dichiarazione e override preservando il risultato della
base, poi verificare entrambe le varianti su 25G83. La presente indagine lascia il
driver invariato; vedi `ioaccelerator_abi_re.md` per provenienza e limiti del disassemblato.

### B. Il census verifica presenza, non ABI o semantica

**Osservato:** `n48_census.h:34-44` usa `class_respondsToSelector`, che considera
correttamente l'ereditarietà. Il device registra il census a `Navi48Device.m:5989-5999`,
ma soltanto per `MTLDevice`; adotta anche `MTLDeviceSPI` a `:5965-5970`.
Non confronta type encoding/argomenti/ritorno e non verifica le precondizioni della base.
Un protocollo inesistente restituisce zero a `n48_census.h:36-37`.

**Conseguenza:** il census può essere verde per il caso A o per un metodo ereditato
che fallisce. Non copre tutti gli SPI adottati né selettori privati fuori protocollo.
Non esiste un forwarding generico: `test-census.m:85-87` controlla espressamente
questa scelta; `doesNotRecognizeSelector:` del device (`Navi48Device.m:6236`) termina
nell'eccezione standard. È un census diagnostico, non una rete di compatibilità.

**Prossimo passo:** eseguire `N48M_CENSUS=1` sulla build macOS effettiva, poi confrontare
gli encoding dei metodi locali con le basi e con i protocolli SPI raggiunti. Classificare
i risultati in assente, ereditato compatibile, ereditato dipendente da IOAccel, e stub/fallback.

### C. Esistenza delle factory ereditate ≠ supporto di argument buffer/ICB

**Osservato:** `Navi48Device.m:2069` restituisce sempre zero da `gpuAddress`;
`:4162` e `:4353` dichiarano `supportIndirectCommandBuffers = NO` nelle pipeline.
`:6276-6290` e `n48_gate.h:204-209` negano Metal3 alle app ma lo dichiarano a WindowServer,
mantengono Mac2/Common1..3 e riportano Tier1 alle app. Il ramo WindowServer lascia
`argumentBuffersSupport` alla base. Le factory di argument encoder/ICB non sono override locali.

**Inferenza:** la semantica di indirizzi GPU/bindless e ICB è un gap concreto del runtime
attuale, anche se alcune factory rispondono al selettore. Il valore dei getter di capacità
ereditati non è stato osservato qui. Il Tier1 dichiarato non prova che gli encoder ereditati
funzionino con le risorse Vulkan del plugin.

**Prossima indagine:** getter effettivi su 25G83 e percorso di
`newArgumentEncoderWithArguments:` → `newArgumentEncoderWithLayout:`; verificare quali
risorse IOAccel la factory richiede. Allineare le capacità soltanto a percorsi realmente validati.

### D. Compiler/reflection: gap già documentato dal sorgente, aggirato in parte

**Osservato nel codice, non riprodotto:** `Navi48Device.m:1932-1941` documenta un
crash CoreImage con `[device compiler] == nil` e applica il workaround
`CI_USE_MTL_DAG_FOR_CIKL_SRC=0` (`n48_cienv.h:11`). Le factory compute/render locali
ignorano options e output reflection (`Navi48Device.m:6095-6111`, `:6219-6231`);
i callback con reflection ricevono nil. Le pipeline sono create tramite traduzione
AIR/SPIR-V e Vulkan, quindi non occorre copiare tutti gli hook del compilatore AMD.

**Prossima indagine:** identificare precisamente i percorsi CoreImage/MPS che richiedono
reflection dal compilatore e quelli serviti dal frontend Metal ereditato. Ricostruire
il contratto minimo necessario; non usare gli hook AMD mancanti come checklist indiscriminata.

### E. Eventi e fence: presenza API con semantica limitata

**Osservato:** wait/signal di evento sono accumulati per command buffer
(`Navi48Device.m:4813-4845`): il wait precede l'invio e il signal segue il completamento,
indipendentemente dalla posizione dell'encode. `encodeWaitForEvent:value:` impone 60 s.
Le fence render ignorano oggetto e stage (`:5398-5399`). `newFence` è un override
proprio (`:6175`); il sorgente annota che la factory ereditata dereferenzia una coda NULL.
Lo stesso vale per `currentAllocatedSize` e `_purgeDevice` (`:6176-6177`, `:6186-6188`).

**Inferenza:** l'ordine intra-command-buffer di eventi/fence non è equivalente a quello
Metal generale. Va provato con dipendenze tra code e con producer/consumer nello stesso
buffer. La semplice risposta al selettore non garantisce progressione o assenza di timeout.

## 3. Confine di architettura da correggere nella documentazione

Il report `macos_25G83_re.md` §4i descrive `MTLIOAccelCommandBuffer` e conclude che
il nostro bundle riempie kernel command buffer e segment list, che il kext traduce in PM4.
È il modello osservato dei driver Apple; non è il percorso render nativo del plugin corrente.

**Osservato:** `N48CommandBuffer : _MTLCommandBuffer` (`Navi48Device.m:4403`),
`N48CommandQueue : _MTLCommandQueue` (`:4364`) e `N48RenderEncoder : _MTLCommandEncoder`
(`:5134`); il worker invia con `vkQueueSubmit` (`:4519`). Le risorse derivano da
`_MTLResource`, non da `MTLIOAccelBuffer/Texture`. RADV parla al canale N48N; la
compatibilità IOAccel resta necessaria per il device e per il display, ma i dati dei
command buffer Apple non sono automaticamente il formato che questo bundle deve emettere.

## 4. Stato e limiti

La domanda «quali selettori mancano davvero?» è **parzialmente risolta**: corretta
la distinzione fra override AMD, metodi ereditati e gap semantici, e confermato un
conflitto di firma con un chiamante che consuma il ritorno. Rimangono aperti gli
eventuali consumi tardivi di `lazyInitialize`, corpi/precondizioni delle factory ereditate, getter di capacità
runtime, census SPI, e validazione su macOS con device inizializzato. Nessuna conclusione
qui equivale a un test sulla RX 9060 XT sotto macOS.
