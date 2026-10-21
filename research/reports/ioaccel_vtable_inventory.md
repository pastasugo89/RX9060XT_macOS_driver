# Inventario osservato delle vtable IOAccel — macOS 25G83

Analisi statica ripresa su richiesta esplicita dell'utente il 13/10/2026. È stato recuperato
l'inventario delle **13 classi base / 2720 slot** usate da
`cobalt64/tools/native/navi48accel/gates/leaves.py`, compresi **IOAccelDisplayPipe: 306** e
**IOFramebuffer: 350**. Ogni slot non nullo appartiene a una catena di fixup valida e risolve
all'indirizzo esatto di un simbolo nel livello corretto della Kernel Collection. Gli slot
non risolti sono **0**; gli slot con più simboli allo stesso indirizzo sono **0**.

Queste osservazioni provengono dal parser locale deterministico
[`tools/kc_vtable_inventory.py`](../../tools/kc_vtable_inventory.py), non da una decompilazione
REA/MCP e non da un'esecuzione del kext. Non sono associate a Evidence ID di REA. L'inventario
completo è locale e ignorato da git:
`research/macos/25G83/rea/new_layout/vtable_inventory.json`.

## Artefatti e riproduzione

| Artefatto | Dimensione | SHA-256 |
|---|---:|---|
| BootKernelExtensions.kc | 67 584 000 byte | `c80161fa3065883753fc285339281361a8469cbb6fb27653c88e2a22eb4807a4` |
| SystemKernelExtensions.kc | 361 922 560 byte | `fbab2d48bf1470fb0ec15dd62a6bb90c39d8bb45ed68240d3c73f1e43e770dee` |

I percorsi sono sotto `research/macos/25G83/root/System/Library/KernelCollections/`.
Il JSON conserva anche UUID, numero di voci fileset, hash della specifica `leaves.py`,
simbolo della vtable, offset del file e VA di ogni slot, parola grezza, campi del fixup,
indirizzo di destinazione, simboli esatti e confine nullo osservato.

```sh
python3 tools/kc_vtable_inventory.py \
  --boot research/macos/25G83/root/System/Library/KernelCollections/BootKernelExtensions.kc \
  --system research/macos/25G83/root/System/Library/KernelCollections/SystemKernelExtensions.kc \
  --output research/macos/25G83/rea/new_layout/vtable_inventory.json

python3 -m unittest discover -s tools/hosttests -p test_kc_vtable_inventory.py -v
```

Risultati: inventario **MATCH 13 / 2720**; **15 test sintetici superati**. I test verificano
separazione dei livelli della cache, limiti di file e stringhe, dimensioni dei load command,
catene fuori pagina, offset di segmento, formato dei fixup, destinazioni non eseguibili o
non mappate, slot fuori catena e parole nulle che appartengono a una catena. Verificano
anche che simboli assenti restino sconosciuti, gli alias restino espliciti e gli slot puri
richiedano la destinazione simbolica esatta.

## Metodo e controlli

Il tool legge il Mach-O `MH_FILESET` x86_64 e i load command di ogni immagine incorporata.
Gli offset dei segmenti e di `LC_SYMTAB` sono assoluti rispetto al file KC, come verificato
su questi artefatti. Legge direttamente le tabelle simboli, senza dipendere da `llvm-nm`,
Ghidra o dall'esecuzione di script dei progetti di riferimento.

La struttura delle catene e dei rebasing segue l'intestazione ufficiale Apple
[`mach-o/fixup-chains.h`](https://github.com/apple-oss-distributions/dyld/blob/main/include/mach-o/fixup-chains.h):
formato `DYLD_CHAINED_PTR_X86_64_KERNEL_CACHE = 11`, avanzamento in byte, destinazione
relativa alla base scelta dal campo `cacheLevel`. Il parser verifica gli starts e segue
ogni catena dell'immagine proprietaria. Non tratta parole arbitrarie come puntatori.

Le basi usate sono ricavate dal VA minimo dei segmenti esterni con dati nel file:
Boot/livello 0 = `0xffffff8000100000` (`__HIB`), System/livello 1 = `0`. Questa scelta di
base è un'inferenza di layout, corroborata dalla risoluzione esatta di tutti i 2720 slot.
Usare il solo `__TEXT` della Boot KC, a `0xffffff8000200000`, sposterebbe gli indirizzi di
1 MiB e produrrebbe risultati errati. Ogni livello mantiene il proprio spazio dei simboli.

Per ogni vtable richiesta, le prime due parole osservate sono nulle. Gli slot iniziano
16 byte dopo il simbolo `__ZTV…`; il conteggio prosegue fino a una parola nulla che non
appartiene a una catena. Il parser rifiuta il superamento del simbolo definito successivo
e impone un limite di scansione. Tutte le destinazioni sono in segmenti eseguibili.
Un metodo è classificato puro soltanto quando la destinazione ha il simbolo esatto
`___cxa_pure_virtual` nel livello corretto della cache.

## Conteggi osservati

Gli indici sono a base zero, come nelle gate del progetto.

| Classe base | Slot | Indici puri |
|---|---:|---|
| IOGraphicsAccelerator2 | 350 | 271, 273, 307, 310, 312–314, 320, 324–328, 332–334, 337 |
| IOAccelEventMachineFast2 | 95 | 84–87 |
| IOAccelTask | 51 | nessuno |
| IOAccelDisplayMachine | 284 | 269, 270 |
| IOAccelSysMemory | 66 | nessuno |
| IOAccelMemoryMap | 57 | 46–48 |
| IOAccelVidMemory | 69 | 43, 61, 62 |
| IOAccelResource2 | 79 | 58, 60–65 |
| IOAccel2DContext2 | 368 | 360, 361 |
| IOAccelSharedUserClient2 | 308 | nessuno |
| IOAccelCommandQueue | 337 | nessuno |
| IOAccelDisplayPipe | 306 | nessuno |
| IOFramebuffer | 350 | 309, 312–318 |
| **Totale** | **2720** | **46 slot puri** |

La vtable di `IOAccelDisplayPipe` ha il simbolo a `0x145ff5d8`. Lo slot 277 risolve a
`__ZN18IOAccelDisplayPipe18performTransactionEP30IOAccelDisplayPipeTransaction2`
(`0x145cfcf4`, System/livello 1). Questo conferma l'associazione dello slot con
`performTransaction(IOAccelDisplayPipeTransaction2 *)`; **non determina il tipo di ritorno**.
Gli otto slot puri di IOFramebuffer coincidono con `FB_PURE` in `leaves.py`.

## Cosa resta da ricostruire

Il conteggio e l'ordine delle destinazioni delle vtable sono ora osservati sul target.
Resta incompleto il modulo privato `tools/native/ioaccel-layout` atteso dai consumer di
Cobalt64: questo JSON è un inventario di evidenza, **non** un `model.json` o `slots.json`
compatibile con quel generatore.

- Dimensioni delle classi e layout dei campi non sono stati ricavati.
- I nomi mangled possono descrivere parametri, ma non il tipo di ritorno ordinario, né
  tutti i vincoli ABI delle dichiarazioni. Non sono stati generati header o placeholder.
- Restano da verificare le dichiarazioni dei metodi non esportati e la scelta dei
  forwarder prima di ricostruire `gen_header.py` e `forwarded.json`.
- Il confine nullo è un dato osservato: Mach-O non fornisce qui una lunghezza esplicita
  delle vtable. Il totale confrontato con `leaves.py` è un controllo indipendente della
  scansione, non prova di compatibilità ABI completa o di funzionamento a runtime.
- I gate del kext, la compilazione macOS e il bring-up sulla RX 9060 XT richiedono ancora
  il modello completo e l'ambiente previsti dal piano.

Nessun binario Apple, payload di firmware o dichiarazione ricostruita è aggiunto a git.
