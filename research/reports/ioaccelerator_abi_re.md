# IOAccelerator e Metal 25G83: ABI verificata con REA MCP

Data: 13/10/2026. Indagine richiesta dall'utente, analisi statica di binari locali
per interoperabilità. Nessun kext installato, nessuna esecuzione del driver o accesso
MMIO. Il server MCP REA 6.4.0 e il provider Ghidra 12.1.2 sono disponibili nella
sessione Codex; non è necessaria una nuova installazione.

## 1. Confine e domande

| Domanda | Esito |
|---|---|
| Quale componente non pubblicato impedisce la build dell'acceleratore? | `tools/native/ioaccel-layout`: header, modelli e strumenti importati dai gate. Confermato nel Makefile e in `gates/common.py`. |
| Sono recuperabili le vtable dai binari già presenti? | Sì: 13 classi, 2720 slot; inventario completo per questo confine in [ioaccel_vtable_inventory.md](ioaccel_vtable_inventory.md). Il generatore C++ resta da costruire. |
| Quali connessioni richiede il frontend Metal alla famiglia IOAccel? | Ricostruite aperture device/shared/queue e alcuni messaggi, vedi §2. Non è un inventario completo degli user client. |
| `lazyInitialize` deve restituire un valore? | Sì: metadati, assembly e chiamante concordano sul ritorno di un byte; §3. |
| Il confronto fra override AMD e Navi48 misura le API mancanti? | No: molte dichiarazioni sono ereditate, e la presenza non prova la semantica; [audit](metal_selector_audit.md). |
| Si può completare il bring-up/display su questa sessione Linux? | Non dai soli binari: restano VM macOS, avvio GOP senza amdgpu e test sulla scheda. |

## 2. IOAccelerator.framework 487.4.3

Artefatto: `research/macos/25G83/dylibs/IOAccelerator`, estratto dal dyld cache di
25G83. SHA-256 `a89ba09649a6366c31ebf3ca2e9d0a161f4753b0c529d9107e79303de818b0f3`.
Riutilizzato lo snapshot `rea/ioaccelfw.snapshot`, aprendo il binario con
`open_binary(provider_id="ghidra", snapshot_path=...)` e analizzando direttamente
le funzioni selezionate. Nessuna esecuzione dell'artefatto.

Le osservazioni seguenti riguardano il client in spazio utente. I numeri di metodo
sono **locali a ogni connessione**, non un'unica tabella globale.

| Funzione e indirizzo | Osservazione nelle istruzioni | Evidence REA |
|---|---|---|
| `IOAccelDeviceCreateWithAPIProperty`, `0x7ff80f474f60` | `IOServiceOpen` tipo **5**; se presente, stringa API di 16 byte con metodo **9**; interrogazioni metodi **2**, **0**, **7**. | `ev_81cb5a6cdff0412d7f827a031025f40b690b0324691e71878a9ac1a37349dd15` |
| `IOAccelSharedCreate`, `0x7ff80f475431` | `IOServiceOpen` tipo **6**; metodo struct **9** per dati condivisi. | `ev_c8f0463448aa2db13e58420b4f2b46078ba37349786c97a830ce9773b25478ec` |
| `IOAccelCommandQueueCreateWithQoS`, `0x7ff80f4763c4` | `IOServiceOpen` tipo **8**; associazione con shared tramite `IOConnectAddClient`; metodo async scalar **0** per notifiche; struct **5**, input **0x404**, output **8** byte. | `ev_63be408442647c82ce9d76285a094e78909a892cd136fabadf0dfa71ec4e7f88` |
| `IOAccelCommandQueueSubmitCommandBuffers`, `0x7ff80f476dd7` | Metodo **1** della queue; count letto come i32 a input+4; lunghezza struct **8 + 24 × count**; nessun input scalar/output. Due retain per elemento, annullati in caso di errore. | `ev_d2bc149fbe38758641f82b294d63b67debf99d60d3a2f42edf69d236c700a9a2` |
| `IOAccelSharedCreateDeviceShmem`, `0x7ff80f4767a7` | Metodo **7** della shared; un input scalar (argomento ridotto a 32 bit e allargato a 64); output struct **16** byte, restituito come u64 + u32 + u32. | `ev_8d4278cd8ba5d07180d1817b51abb170b28526b8e8f340e404dd4cef3b502f93` |
| `IOAccelResourceCreate`, `0x7ff80f475fe7` | Metodo **0** della shared; input struct della lunghezza passata dal chiamante; output **0x58 + privateSize**, con privateSize dal device+0x3c. | `ev_366731c6380dc8bdf499020a89d50e671d9f7b54ea0df78adff46934b8df78c2` |
| `IOAccelResourceListAddResource`, `0x7ff80f476a90` | Gruppi di **0x58** byte, fino a **6** risorse: ID a +0, flags u16 a +0x48, indice successivo +0x54, count +0x56. | `ev_b797434c9143f32698804cb01077eb88560c0f9e1e8106136915f162ac365d2d` |
| `ioAccelCommandQueueBlockFenceCallback`, `0x7ff80f476e98` | Sul completamento riuscito invoca il block, lo rilascia e rilascia la queue. Non osservati runtime o payload prodotti dal kernel. | `ev_c3a56b93b0a341e4ad816b222e41d37182f38a2f0116d977aea05eb1a4b77b57` |

**Limiti:** le firme di Ghidra sono inferenze del decompilatore. In particolare
`IOAccelResourceCreate` usa una dimensione di stack dinamica: gli offset del buffer
di risposta sono stati controllati nell'assembly, non dedotti dai nomi dei locali.
Non sono attribuiti nomi semantici ai tre campi shmem senza corroborazione del kernel.
Un count negativo nella submission non autorizza a inventare un validatore: qui
si registra soltanto il comportamento statico del client Apple.

**Implicazione per il progetto:** `MTLIOAccelDevice` usa realmente la connessione
tipo 5 durante la propria inizializzazione. Il bundle nativo corrente usa invece
`_MTLCommandBuffer`, `_MTLCommandQueue` e `vkQueueSubmit` tramite RADV/N48N per i
comandi grafici. Il payload Apple `8 + 24 × count` è una descrizione del percorso
Apple, non un requisito di formato da imporre al backend RADV.

## 3. `lazyInitialize`: mismatch di ritorno confermato

Artefatto: `research/macos/25G83/dylibs/Metal`, versione 373.7, SHA-256
`89032654dd427ffed1c5b3722fbddabd2ed333b429c15db25ca15af13b2f5210`.

**Osservato nei metadati:** il class-dump di `metal/Metal/MTLIOAccelDevice.h:133`
dichiara `- (signed char)lazyInitialize`. Il sorgente locale
`cobalt64/tools/native/navi48metal/Navi48Device.m:76` e `:6009` usa invece `void`.
Il census cerca soltanto la presenza del selettore, quindi non rileva questo caso.

**Osservato nel corpo:** `-[MTLIOAccelDevice lazyInitialize]`, `0x7ff80f5a9a2a`,
restituisce zero se falliscono shared/dirty ring o command-buffer pool, e uno alla
fine del percorso riuscito. L'epilogo usa `MOVZX EAX,R14B`; il percorso di successo
imposta `R14B=1`. Evidence
`ev_4f0340b1e8e4bb52a0fac6c4b4118d58e0e132858c532cee918bc285603654ef`.

**Osservato nel chiamante:** `-[MTLIOAccelDevice initWithAcceleratorPort:]`,
`0x7ff80f47e7cf`, invia `supportLazyInitialization` e controlla `AL` a
`0x7ff80f47e9b5`. Se falso, invia `lazyInitialize` e controlla nuovamente `AL` a
`0x7ff80f47e9c9`; se falso rilascia l'oggetto e restituisce nil. Evidence
`ev_f745f5ac2a9b7bf21954d5f84e36a230fe94a21e10d6c89a66c89d1d5d042ce8`.
Il metodo base `supportLazyInitialization` restituisce zero, Evidence
`ev_b5df825ade5f115ad9ae0a862f1604d4bf93f5b33f7cf2159c9a6513a2053e95`.

Ghidra mostra i selref come puntatori codificati verso indirizzi non caricati.
I nomi **non** sono stati assegnati dal solo pseudocodice: `ipsw` legge i riferimenti
Objective-C nel cache originale e li risolve così:

| Selref | Selettore |
|---|---|
| `0x7ff841206ad8` | `updateGPUSelectionProperties` |
| `0x7ff841206ae0` | `supportLazyInitialization` |
| `0x7ff841206ae8` | `lazyInitialize` |

Comando riproducibile, eseguito con ipsw 3.1.737:

```sh
research/ext/ipsw/ipsw dyld macho \
  research/macos/25G83/cryptex/dsc/dyld_shared_cache_x86_64h \
  /System/Library/Frameworks/Metal.framework/Versions/A/Metal \
  --objc --objc-refs --no-color
```

Estratto locale salvato in `rea/metal_init_selrefs_20261013.txt`. Lettura dei 24 byte
dei tre selref anche tramite REA, Evidence
`ev_57e9d0251834d332d46edcba7615cfb489a400fbe34d6bb3fcb8fad5f2b7dd6e`.

**Conseguenza:** l'override `void` non garantisce il byte di risultato richiesto
dal chiamante Apple. Con `N48_LAZY=0` questo ramo viene raggiunto nell'init; il
default `N48_LAZY=1` evita il ramo durante l'init. Non sono stati osservati qui
tutti i percorsi successivi di inizializzazione differita o un crash runtime.
Correzione indicata: dichiarazione/override con ritorno BOOL coerente per x86_64,
preservando il ritorno della base e restituendo NO quando la base non esiste;
poi build e verifica delle varianti 0/1 su macOS 25G83. In questa indagine il
sorgente del driver non è stato modificato.

Ulteriore controesempio alla sola presenza: la factory base
`-[_MTLDevice newCommandQueueWithDescriptor:]` a `0x7ff80f5976be` contiene
`XOR EAX,EAX; RET`, Evidence
`ev_3a34554edc0bb343d07e390076f849562bb5fad7f7ab9fa7d7d016b11d60d22f`.
Navi48 la sostituisce: questo caso dimostra uno stub nella base, non un nuovo
difetto della coda Navi48.

## 4. Conservazione e lavoro restante

Evidence canonica completa esportata, solo locale e fuori da git:

- `research/macos/25G83/rea/ioaccelerator_abi_20261013.evidence.json` (12 record).
- `research/macos/25G83/rea/metal_init_20261013.evidence.json` (14 record di Metal;
  i record di IOAccelerator sono conservati nell'esportazione precedente).
- `research/macos/25G83/rea/metal_20261013.snapshot` per riprendere Metal con Ghidra.

Entrambe le sessioni native aperte sono state chiuse. I binari Apple non sono
inclusi nei file versionati. L'inventario KC è un'osservazione del parser locale,
con hash/UUID/offset propri; non gli viene attribuito un Evidence ID MCP.

Ordine di prosecuzione: dimensioni/superclassi e firme dei metodi richiesti dal
generatore `ioaccel-layout`; dichiarazioni e verifica delle vtable compilate;
build dell'acceleratore e gate A/B/C; verifica del mismatch `lazyInitialize` e
factory realmente usate su macOS. Bring-up, GOP, display e WindowServer restano
da provare sull'ambiente dedicato previsto nel piano.

## Aggiornamento implementativo — 20/10/2026

Mismatch lazyInitialize corretto nel sorgente; prova macOS 25G83 sul binario
prepatch fallisce (v/c), entrambe varianti compilate postpatch PASS (c/c,
NO/YES della base preservati). È una prova di ABI/dispatch in processo isolato,
non dell’inizializzazione GPU reale. Dettagli in `macos_build_validation.md`.
Dimensioni e superclassi osservate delle13classi: `ioaccel_class_sizes.md`.
