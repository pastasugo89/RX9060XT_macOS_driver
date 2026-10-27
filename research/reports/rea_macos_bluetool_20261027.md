# REA/Ghidra su macOS: BlueTool — 2026-10-27

## Scopo

Preparata una toolchain REA isolata nel progetto e usata per un'analisi statica di `/usr/sbin/BlueTool`, utility macOS relativa al Bluetooth. Nessun kext è stato caricato; il binario BlueTool non è stato eseguito. Nessuna modifica a EFI, servizi, profili shell o configurazione dei client Codex/Claude.

## Toolchain isolata

Directory: `research/ext/rea-macos-toolchain-20261027/`.

| Componente | Versione / verifica |
|---|---|
| Node.js | 24.22.1, macOS x86_64, SHA-256 `d132557e7ee2b85af08b0c8c34338e65c6430f2238d01f727728ef42dc83b035` |
| npm | 11.19.1, incluso con Node |
| Eclipse Temurin JDK | 21.0.12.1+1, macOS x86_64, SHA-256 `44db0f08196daf19a47f90d13388b0c943b67663cb537f998fe29e836fa842ce` |
| Ghidra | 12.1.4, release ufficiale NSA, SHA-256 archivio `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db` |
| REA | `rea-agents` 6.8.0; integrity npm `sha512-9QDeRnGqEDzABZyr04eLnBXBv/c6I9/TWu/6M0MD4pEfkySI/BIgwTODIbAReX3C1x6hjw9+Jlx4A2yUSPZ9ww==` |

Node, JDK e Ghidra sono stati scaricati in `downloads/` e verificati contro gli hash pubblicati dai rispettivi progetti. Il pacchetto Ghidra ufficiale non contiene il decompiler nativo macOS x86_64 richiesto da REA. L'ho compilato dalla copia locale dei sorgenti inclusi nella release, con il Makefile upstream e `make -j2 ghidra_opt`; exit code 0. L'eseguibile risultante è Mach-O x86_64, SHA-256 `531aa56ea8c3d96a87cefa342282e282d7115f9403e183215ad9f8573e6cbe7f`, aggiunto solo allo staging Ghidra.

Il controllo `rea doctor --provider ghidra --json` rileva Node, JDK, Ghidra e decompiler compatibili e segna il provider Ghidra `available: true`. L'ambiente complessivo è indicato come non integro perché mancano registrazione/skill dei client, Hopper e provider opzionali; non ho eseguito `rea setup`, che avrebbe modificato le configurazioni dei client. npm ha segnalato che lo script d'installazione della dipendenza `frida` non era approvato. È rimasto disabilitato: l'analisi statica Ghidra è comunque riuscita.

## Target e risultati

Il target originale è un Mach-O universale x86_64/arm64e, SHA-256 `297accfb7614c591b6c55169979a713130233b4f1f23ab6aa3f1b39bf3b5397e`. REA/Ghidra rifiuta l'import del Mach-O universale perché non può imporre la slice selezionata. Ho creato nella sola directory di analisi una copia sottile x86_64 con `lipo -thin`; SHA-256 `99e6f395f4ce60ba38f3fbb7f6a302fa3556dfae8f1393c52378adfc51b4bf00`.

L'analisi REA è terminata con exit code 0 e ha prodotto l'evidence `ev_f7785b1ca42741af43ff1e1f2acddf4d48d3179e44f9728a994d02d47bf3d79a`: 25 segmenti, 2.225 procedure e 5.063 stringhe definite da Ghidra. Snapshot: `research/ext/rea-macos-toolchain-20261027/analysis/BlueTool-x86_64.snapshot`.

La ricerca REA nelle stringhe con i termini Bluetooth/HCI/USB/trasporto/firmware restituisce 208 corrispondenze ampie. Tra le stringhe osservate ci sono `AppleConvergedTransport`, `AppleBluetoothModule`, `Bluetooth USB Host Controller`, `Broadcom Bluetooth Download Device` e percorsi firmware Broadcom come `BCM4350-*`, `BCM4364*`, `BCM4355-*`, oltre a firmware `20702`/`20703`. Una ricerca case-insensitive specifica per `WCN`, `QCA` o `Qualcomm` non trova corrispondenze nella string inventory. La ricerca di nomi di procedure con gli stessi termini restituisce zero risultati.

Evidence e output completi sono sotto `research/ext/rea-macos-toolchain-20261027/analysis/`:

- `BlueTool-analyze.json` registra il rifiuto della slice universale da parte di REA.
- `BlueTool-x86_64-analyze.json`, `BlueTool-strings-search.json` e `BlueTool-procedures-search.json` contengono le analisi riuscite.
- `BlueTool.x86_64` è la copia sottile locale, non una modifica a `/usr/sbin/BlueTool`.

## Interpretazione e limiti

Le stringhe osservate mostrano che BlueTool contiene percorsi Bluetooth legati ai trasporti Apple e a firmware Broadcom. Non dimostrano che il sistema abbia un controller Broadcom fisico, né provano una compatibilità generale o l'assenza di supporto Qualcomm. L'assenza di stringhe WCN/QCA/Qualcomm è un indizio limitato all'inventario definito da Ghidra; codice non identificato, dipendenze caricate dinamicamente o un altro driver possono non comparire in questa ricerca. BlueTool è un'utility user space, non il driver USB del controller Qualcomm.

Questa analisi statica quindi non cambia la diagnosi hardware: il Bluetooth Linux `0489:e10a` deve prima essere enumerato come USB in macOS; l'enumerazione, da sola, non dimostrerebbe che firmware o stack macOS siano compatibili.

## Fonti ufficiali

- [REA: installazione, requisiti Node/Ghidra/JDK e provider](https://github.com/NabilRFG12/Reverse-Engineer-anything/blob/main/docs/installation.md)
- [Node.js 24.22.1 e checksum di release](https://nodejs.org/en/blog/release/v24.22.1/)
- [Temurin 21.0.12.1+1 — release Adoptium](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1)
- [Ghidra 12.1.4 — release NSA](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build)
