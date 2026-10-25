# rx9060xt_metal_driver

Progetto per portare la **AMD Radeon RX 9060 XT** (Navi 44, RDNA 4, `1002:7590`) su macOS con accelerazione Metal,
sul modello di quanto fatto da NullMoth per le GeForce RTX e da Cobalt64 per la RX 9070 XT.

**Stato (25/10/2026): stack del driver verificato sulla GPU (bring-up, compute, Metal headless), desktop accelerato
non ancora ottenuto.** In VM con la GPU in passthrough: bring-up fino allo stage 17, compute corretto, acceleratore
IOAccelerator caricato, Metal headless con rendering identico al pixel al riferimento; con RDNA4FB v8 il monitor DP è
display principale a 2560x1440@120, ma WindowServer non invia frame alla nostra display pipe. Dal 23/10 si prova il
bare metal: il kernel di macOS parte sul Ryzen 7 7700 ma si blocca dopo `CoreAnalyticsHub start completed`.
Quadro sintetico in [`STATO.md`](STATO.md); fasi in [`FASI.md`](FASI.md); bare metal in
[`baremetal_bringup.md`](research/reports/baremetal_bringup.md).

## Da dove partire

- [`PIANO_DRIVER_METAL_RX9060XT.md`](PIANO_DRIVER_METAL_RX9060XT.md): il piano di sviluppo (architettura, strategia,
  ambiente, milestone, test, rischi, licenze, prime azioni).
- [`STATO.md`](STATO.md): dove siamo arrivati, cosa funziona e dove siamo bloccati, in una pagina.
- [`FASI.md`](FASI.md): le fasi di sviluppo e il loro stato, compresi i punti sospesi e il motivo.
- [`VM_MACOS.md`](VM_MACOS.md): istruzioni per avviare direttamente Tahoe 25G83 con i supporti estratti dall'installer locale; toolchain e snapshot. Installazione e primo login completati; build del kext verificata, riavvio automatico della VM ancora difettoso.
- [`gfxhub_ack_compute.md`](research/reports/gfxhub_ack_compute.md): ACK GFXHUB risolto, 13 boot stage17, prove compute e limiti MES/Fase2.
- [`navi44_bringup_progress.md`](research/reports/navi44_bringup_progress.md): cronologia BAR0, PSP/SMU/RLC, SDMA e risoluzione GFXHUB.
- [`navi44_first_hardware_test.md`](research/reports/navi44_first_hardware_test.md): prima discovery sulla vera RX9060XT in macOS; risultati e blocco BAR0.
- [`macos_build_validation.md`](research/reports/macos_build_validation.md): prima build macOS del kext, verifica import, RADV e n48xlate compilati; blocchi ABI/cache dei componenti acceleratore e Metal.
- [`radv_icd_smoke.md`](research/reports/radv_icd_smoke.md): test RADV direct-ICD su GPU passthrough, prerequisito root-only, identità profilo, code e limiti della prova.
- [`research/reports/`](research/reports/): gli 8 report dell'analisi più i resoconti dello sviluppo (`apple_route_split.md`,
  `macos_25G83_re.md`, `navi44_kernel_checks.md`) e il piano del display in `research/display/README.md`.
- Reverse engineering ripreso con REA MCP: [`ioaccelerator_abi_re.md`](research/reports/ioaccelerator_abi_re.md)
  (ABI e mismatch `lazyInitialize`), [`ioaccel_vtable_inventory.md`](research/reports/ioaccel_vtable_inventory.md)
  (13 vtable / 2720 slot) e [`metal_selector_audit.md`](research/reports/metal_selector_audit.md)
  (override, ereditarietà e gap del bundle).
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
