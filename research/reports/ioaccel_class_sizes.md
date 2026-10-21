# Dimensioni e superclassi IOAccel — macOS Tahoe 25G83

20 ottobre 2026. Analisi statica dei due KC x86_64 locali esplicitamente selezionati.
**Recuperate dimensione di allocazione registrata e superclasse per tutte le 13 classi dell’inventario vtable. Non è un ABI completo né un header compilabile.**

## Provenienza e metodo

I risultati qui sotto derivano dal parser locale `tools/kc_vtable_inventory.py`,
da finestre dei byte originali e da GNU objdump. **Non attribuire a questi risultati Evidence ID di REA.**
La skill `reverse-engineer-anything` è stata letta e il target SystemKC aperto anche con REA/Ghidra;
la sua analisi ampia non è necessaria per i risultati riproducibili qui descritti.
La ricerca MCP `search_procedures` ha raggiunto il timeout client di 300 secondi durante
autoanalisi Ghidra: nessuna conclusione sulle classi è ricavata da un risultato REA parziale.
Sessione REA chiusa correttamente; snapshot salvato come
`new_layout/metaclass_search_20261020.snapshot` (381979 byte, 0 primitive nuove,
1 workflow/4 record già conservati). `binary_session` successivo conferma `open=false`.
Lo snapshot non contiene la ricerca interrotta dal timeout e non viene usato come prova delle dimensioni.

| Input | SHA-256 |
|---|---|
| BootKernelExtensions.kc | `c80161fa3065883753fc285339281361a8469cbb6fb27653c88e2a22eb4807a4` |
| SystemKernelExtensions.kc | `fbab2d48bf1470fb0ec15dd62a6bb90c39d8bb45ed68240d3c73f1e43e770dee` |

Tutti i costruttori selezionati sono in SystemKC: dodici in `com.apple.iokit.IOAcceleratorFamily2`,
`IOFramebuffer` in `com.apple.iokit.IOGraphicsFamily`. BootKC serve anche a risolvere
OSMetaClass, OSObject, IOService e IOUserClient nel corretto livello della cache.

Per ciascuna classe il prefisso lineare di `MetaClass::MetaClass()` variante C2:

1. Carica in RSI l’indirizzo di una stringa, letta dal file e verificata uguale al nome della classe.
2. Carica in RDX l’indirizzo della `gMetaClass` del genitore (LEA diretto o MOV da GOT).
3. Carica in ECX un immediato, passato come quarto argomento.
4. Chiama uno stub il cui JMP indiretto/GOT viene risolto attraverso una catena fixup validata,
   fino al simbolo esatto `__ZN11OSMetaClassC2EPKcPKS_j` nella BootKC a `0xffffff8000a19880`.
5. Come controllo indipendente, il puntatore statico `class::superClass` risolve alla stessa
   `gMetaClass` del terzo argomento per tutte le tredici classi.

L’intestazione locale MacKernelSDK `Headers/libkern/c++/OSMetaClass.h:1211–1223`
documenta il quarto argomento come `unsigned int classSize`, dimensione di allocazione
della classe rappresentata. Il nome mangled del costruttore risolto è coerente con questa firma.
Il dato osservato è quindi la dimensione registrata da OSMetaClass per **questa build**,
non una ricostruzione degli offset dei campi. Nessun nome della superclasse è dedotto dalla somiglianza dei nomi.

## Risultati

| Classe | Dimensione (byte) | Esadecimale | Superclasse osservata | VA costruttore C2 | VA MOV ECX |
|---|---:|---|---|---|---|
| IOGraphicsAccelerator2 | 3544 | `0xdd8` | IOAccelerator | `0x145bc258` | `0x145bc26f` |
| IOAccelEventMachineFast2 | 3376 | `0xd30` | IOAccelEventMachine2 | `0x145b1ede` | `0x145b1ef5` |
| IOAccelTask | 600 | `0x258` | OSObject | `0x145bac6c` | `0x145bac83` |
| IOAccelDisplayMachine | 376 | `0x178` | IOService | `0x1458fb5c` | `0x1458fb73` |
| IOAccelSysMemory | 408 | `0x198` | IOAccelMemory | `0x145d5d80` | `0x145d5d97` |
| IOAccelMemoryMap | 280 | `0x118` | OSObject | `0x145d40d4` | `0x145d40eb` |
| IOAccelVidMemory | 272 | `0x110` | IOAccelMemory | `0x145d799e` | `0x145d79b5` |
| IOAccelResource2 | 384 | `0x180` | OSObject | `0x145a3078` | `0x145a308f` |
| IOAccel2DContext2 | 4352 | `0x1100` | IOAccelContext2 | `0x14584ac6` | `0x14584add` |
| IOAccelSharedUserClient2 | 360 | `0x168` | IOUserClient | `0x145acebc` | `0x145aced3` |
| IOAccelCommandQueue | 1704 | `0x6a8` | IOAccelSubmitter2 | `0x145c6392` | `0x145c63a9` |
| IOAccelDisplayPipe | 792 | `0x318` | IOService | `0x145cb1be` | `0x145cb1d5` |
| IOFramebuffer | 464 | `0x1d0` | IOGraphicsDevice | `0x1470ceb2` | `0x1470cec9` |

## Evidenza locale e riproduzione

Dati fuori da git, sotto `research/macos/25G83/rea/new_layout/`:

- `metaclass_symbol_windows.json`: simboli esatti C2, immagine proprietaria, VA/offset e 96 byte originali.
- `metaclass_bytes/<Classe>.bin` e `.asm`: finestre originali e disassembly objdump con VA originale.
- `metaclass_observations.json`: dimensioni, stringhe, argomenti RDX, fixup/GOT, simboli di destinazione,
  controllo `superClass`, identità dei KC e hash dello script.
- `observe_metaclass.py`: osservatore deterministico che verifica i prefissi e i controlli indicati.

```sh
python3 research/macos/25G83/rea/new_layout/observe_metaclass.py
```

Lo script usa il parser KC già verificato per l’inventario vtable; segue soltanto puntatori appartenenti
a catene fixup e mantiene separate le basi dei livelli 0/1. Le finestre di 96 byte possono contenere
l’inizio di funzioni successive: l’interpretazione è limitata al prefisso fino alla prima CALL del costruttore.

## Limiti e lavoro restante

- Non è stato eseguito alcun codice dei KC o del driver, né letto/scritto MMIO della GPU.
- Non sono ricavati offset dei membri, allineamento completo, packing, firme dei metodi o tipi di ritorno.
- `sizeof` ricostruito tramite questi argomenti è una conclusione sul contratto di registrazione/allocazione;
  non sostituisce il confronto di layout e i gate runtime A/B/C del progetto.
- Restano da ricostruire le dichiarazioni necessarie al generatore `ioaccel-layout` e validarle sulla VM.
- Nessun header, stub o placeholder è stato generato; la build dell’acceleratore rimane distinta da questo inventario.
