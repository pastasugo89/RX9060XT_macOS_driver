# rx9060xt_metal_driver

Progetto per portare la **AMD Radeon RX 9060 XT** (Navi 44, RDNA 4, `1002:7590`) su macOS con accelerazione Metal,
sul modello di quanto fatto da NullMoth per le GeForce RTX e da Cobalt64 per la RX 9070 XT.

**Stato: sviluppo in corso, nessun test su hardware ancora.** Il port di Cobalt64 (`cobalt64/`) è parametrizzato per la
RX 9060 XT e verificato da Linux (compilazione, test host, firmware reale). Mancano la VM macOS e il bring-up sulla scheda.
Nessun driver è stato installato. Stato fase per fase: [`FASI.md`](FASI.md).

## Da dove partire

- [`PIANO_DRIVER_METAL_RX9060XT.md`](PIANO_DRIVER_METAL_RX9060XT.md): il piano di sviluppo (architettura, strategia,
  ambiente, milestone, test, rischi, licenze, prime azioni).
- [`FASI.md`](FASI.md): le fasi di sviluppo e il loro stato, compresi i punti sospesi e il motivo.
- [`research/reports/`](research/reports/): gli 8 report dell'analisi più i resoconti dello sviluppo (`apple_route_split.md`,
  `macos_25G83_re.md`, `navi44_kernel_checks.md`) e il piano del display in `research/display/README.md`.
- [`research/hw_dump/README.md`](research/hw_dump/README.md): i dati hardware misurati sulla scheda.

## Contenuto

| Cartella | Cosa contiene |
|---|---|
| `cobalt64/` | il codice: subtree di Cobalt64 con le modifiche per Navi 44 (profili `ASIC=navi44` default / `navi48`) |
| `tools/` | strumenti del progetto: test host, controllo di compilazione del kext da Linux, verifica RADV, parser VBIOS |
| `research/reports/` | analisi: bring-up Linux, display DCN 4.0.1, Mesa/RADV, compute/ROCm/LLVM, Cobalt64, driver NVIDIA NullMoth, stack Apple/OpenCore, livello Metal |
| `research/hw_dump/` | dump in sola lettura della scheda (IP discovery, VBIOS, firmware, MQD, ring, power, display) |
| `research/tools/` | decoder per MQD, ring PM4 e pacchetti MES |
| `research/artifacts/` | script e output prodotti durante l'analisi (parser, dump `AMDGPU_INFO`, vulkaninfo, ISA) |
| `research/notes/` | misure varie (dimensione del codice amdgpu) |
| `research/src/` | sorgenti di riferimento: Linux (`drivers/gpu/drm/amd`) e Mesa (`src/amd`), clone sparse |
| `research/refs/` | progetti di riferimento clonati (codice di terzi: solo lettura, non eseguire) |
| `research/display/` | dati display della scheda (EDID, link DP, DTN log) e mappa dei connettori dal VBIOS |

Non versionati (vedi `.gitignore`): `research/ext/` (Mesa con le patch Darwin, MacKernelSDK, JDK, ipsw, gibMacOS),
`research/macos/` (binari estratti da macOS 25G83: solo uso locale, mai ridistribuire), `research/src/`, `research/refs/`.

## Avvertenze

- I kext che programmano la GPU possono bloccare la macchina: lo sviluppo va fatto in una VM con passthrough o su un
  macOS dedicato (vedi piano, §13).
- I firmware AMD si usano così come sono: la loro licenza vieta reverse engineering e disassemblaggio.
- Il codice di NullMoth è sotto licenza PolyForm Noncommercial: va letto, non copiato (vedi piano, §17).
- NootRX e NootedRed hanno una licenza che vieta qualsiasi uso con strumenti di IA: non vanno clonati in questa cartella
  né dati in analisi a un assistente (vedi piano, §17).
