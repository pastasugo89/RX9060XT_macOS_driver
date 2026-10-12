# rx9060xt_metal_driver

Progetto per portare la **AMD Radeon RX 9060 XT** (Navi 44, RDNA 4, `1002:7590`) su macOS con accelerazione Metal,
sul modello di quanto fatto da NullMoth per le GeForce RTX e da Cobalt64 per la RX 9070 XT.

**Stato: fase di analisi completata, sviluppo non ancora iniziato.** Nessun driver è stato scritto o installato.

## Da dove partire

- [`PIANO_DRIVER_METAL_RX9060XT.md`](PIANO_DRIVER_METAL_RX9060XT.md): il piano di sviluppo (architettura, strategia,
  ambiente, milestone, test, rischi, licenze, prime azioni).
- [`research/reports/`](research/reports/): gli 8 report tecnici dettagliati su cui si basa il piano.
- [`research/hw_dump/README.md`](research/hw_dump/README.md): i dati hardware misurati sulla scheda.

## Contenuto

| Cartella | Cosa contiene |
|---|---|
| `research/reports/` | analisi: bring-up Linux, display DCN 4.0.1, Mesa/RADV, compute/ROCm/LLVM, Cobalt64, driver NVIDIA NullMoth, stack Apple/OpenCore, livello Metal |
| `research/hw_dump/` | dump in sola lettura della scheda (IP discovery, VBIOS, firmware, MQD, ring, power, display) |
| `research/tools/` | decoder per MQD, ring PM4 e pacchetti MES |
| `research/artifacts/` | script e output prodotti durante l'analisi (parser, dump `AMDGPU_INFO`, vulkaninfo, ISA) |
| `research/notes/` | misure varie (dimensione del codice amdgpu) |
| `research/src/` | sorgenti di riferimento: Linux (`drivers/gpu/drm/amd`) e Mesa (`src/amd`), clone sparse |
| `research/refs/` | progetti di riferimento clonati (codice di terzi: solo lettura, non eseguire) |

## Avvertenze

- I kext che programmano la GPU possono bloccare la macchina: lo sviluppo va fatto in una VM con passthrough o su un
  macOS dedicato (vedi piano, §13).
- I firmware AMD si usano così come sono: la loro licenza vieta reverse engineering e disassemblaggio.
- Il codice di NullMoth è sotto licenza PolyForm Noncommercial: va letto, non copiato (vedi piano, §17).
- NootRX e NootedRed hanno una licenza che vieta qualsiasi uso con strumenti di IA: non vanno clonati in questa cartella
  né dati in analisi a un assistente (vedi piano, §17).
