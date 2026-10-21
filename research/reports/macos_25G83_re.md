# macOS Tahoe 26.6.2 (25G83): estrazione dei binari e primo reverse engineering

Data: 12/10/2026. Fonte: `InstallAssistant.pkg` scaricato con gibMacOS
(`research/ext/gibMacOS/macOS Downloads/publicrelease/140-93587 - 26.6.2 macOS Tahoe (25G83)/`).
I binari Apple estratti stanno in `research/macos/` (escluso da git, mai ridistribuiti; uso per interoperabilità).

Aggiornamento 13/10/2026: indagine ripresa su richiesta esplicita dell'utente con MCP REA disponibile.
Risultati nuovi in [ioaccelerator_abi_re.md](ioaccelerator_abi_re.md),
[ioaccel_vtable_inventory.md](ioaccel_vtable_inventory.md) e
[metal_selector_audit.md](metal_selector_audit.md). Le note di fermo sottostanti descrivono
la sessione precedente; il generatore C++ completo resta da ricostruire.

## 1. Integrità e struttura dell'installer

| Strato | Formato | Verifica |
|---|---|---|
| `InstallAssistant.pkg` (18,38 GB) | xar | TOC letto: `SharedSupport.dmg` salvato non compresso all'offset 17 953 771 |
| `SharedSupport.dmg` | UDIF con soli blocchi raw/zero, partizione HFS+ | **SHA-1 = `65adfb41…abfef`, uguale a quello dichiarato nel TOC** |
| asset `com_apple_MobileAsset_MacSoftwareUpdate/60533a8a….zip` | zip64, 2483 membri | letto sul posto (nessuna copia: sul disco restano 18 GB liberi) |
| `AssetData/payloadv2/payload.000…042` | pbzx (blocchi xz) → archivio YAA1 | 458 716 voci, 19,3 GB decompressi, attraversati in streaming |
| `AssetData/payloadv2/image_patches/cryptex-system-x86_64` (1,5 GB) | RIDIFF10 (patch su immagine vuota) | **non decodificato** (vedi §5) |

Elenco completo dei file del sistema: `research/macos/25G83/payload_index.tsv`.
Script (locali, fuori da git): `research/macos/tools/`.

## 2. Cosa è stato estratto (423 file, 1,2 GB)

- **Kext grafici** (bundle con Info.plist): IOAcceleratorFamily2, IOGPUFamily, IOGraphicsFamily, IOSurface,
  IONDRVSupport, AppleParavirtGPU, AppleParavirtGPUIOGPUFamily, AppleGraphicsControl (AGDC, GPUWrangler),
  AppleGraphicsPowerManagement, AppleDisplayManager/Crossbar, AppleMCCSControl; driver AMD di Apple
  (AMDRadeonX4000/X5000/X6000 + HWServices/Framebuffer, AMDSupport, AMDFramebuffer) come riferimento.
- **Kernel e Kernel Collection x86_64**: `System/Library/Kernels/kernel`, `BootKernelExtensions.kc` (67 MB,
  204 voci, base 0xffffff8000200000), `SystemKernelExtensions.kc` (362 MB, 172 voci, base 0). Elenco delle voci:
  `research/macos/25G83/{Boot,System}KernelExtensions.entries`.
  - Su macOS 11+ gli eseguibili dei kext di sistema stanno **solo** nelle KC. IOAcceleratorFamily2
    (`0x14582000`), IOGPUFamily, IOGraphicsFamily, AppleParavirtGPU, AGDC/GPUWrangler e AMDRadeonX6000 sono nella
    System KC; IOSurface è nella Boot KC.
  - La voce IOAcceleratorFamily2 ha una propria tabella dei simboli (**4705 simboli**) e chained fixups in formato
    11 (`DYLD_CHAINED_PTR_X86_64_KERNEL_CACHE`, solo rebase; livello 0 = Boot KC, livello 1 = System KC).
- **Driver Metal in spazio utente disponibili su disco**: `AppleParavirtGPUMetal.bundle`,
  `AppleParavirtGPUMetalIOGPUFamily.bundle`, `IOAccelerator2D.plugin` (universali, ridotti a x86_64 in
  `research/macos/25G83/rea/thin/`). I driver Metal AMD e Metal.framework stanno nel dyld shared cache, dentro il
  cryptex RIDIFF (§5).

## 3. Strumenti REA in questa sessione

- Il server MCP `rea` risulta "Connected", ma è stato registrato dopo l'avvio della sessione: i suoi strumenti non
  sono caricati qui. Va riavviata la sessione di Claude Code. Nel frattempo si è usata la CLI di REA 6.4.0 con lo
  stesso motore.
- Il provider Ghidra era "non disponibile" perché il sistema ha solo il runtime Java. È stato scaricato un **JDK
  Temurin 21.0.12.1 portatile** (SHA-256 verificato con l'API Adoptium) in `research/ext/jdk/`, senza modificare il
  sistema. Con `JAVA_HOME` puntato lì, REA segnala Ghidra 12.1.2 disponibile.
- Limite: l'analisi dell'intera System KC (362 MB) supera il timeout di REA (330 s su `list_documents`). Per i
  singoli kext serve un Mach-O per voce (vedi §5).

## 4. Risultati: il modello del driver Metal di Apple (AppleParavirtGPUMetal, x86_64)

Evidence REA (Ghidra 12.1.2, snapshot `research/macos/25G83/rea/pvgmetal.snapshot`):
`ev_30ff362c…` (overview), `ev_9f262cc4…` (stringhe IO), `ev_f5783d5f…` (strutture), `ev_47b618cf…` (procedure),
`ev_a2bb1bf5…` (decompilazione).

**Osservato:**
1. Il driver è un bundle che **eredita dalle classi base `MTLIOAccel*` esportate da Metal.framework**:
   `MTLIOAccelDevice`, `MTLIOAccelCommandQueue`, `MTLIOAccelCommandBuffer`, `MTLIOAccelBuffer`,
   `MTLIOAccelTexture`, `MTLIOAccelHeap`, `MTLIOAccelResource`, `MTLIOAccelPooledResource`,
   `MTLIOAccelResourcePool` (simboli `_OBJC_CLASS_$_…` importati). Si collega a
   `/System/Library/PrivateFrameworks/IOAccelerator.framework` e IOSurface.framework.
2. Interfaccia verso il kernel: `IOConnectCallMethod`, `IOAccelSharedGetConnect`,
   `IOAccelResourceListAddResource`, `IOAccelResourceListMergeLists`, `IOAccelResourceGetClientSharedPrivate`,
   `IOAccelDeviceGetNextGlobalTraceID`.
3. Strutture dell'ABI di IOAcceleratorFamily2, dalle stringhe di tipo Objective-C:
   - `IOAccelNewResourceArgs = { IOAccelNewResourceData = IISSSSQQCCCCIQQQ (union {QQQQI} | {II[3Q]} | {IIII[2Q]} | {II[3Q]}) }`
   - `IOAccelKernelCommand = { II[0I] }` (intestazione dei comandi nel buffer, con payload a lunghezza variabile)
   - `IOAccelResourceList = { [256S], IOAccelSegmentResourceDescriptorGroup *, QQIIIIIII, fn*, void* }`
   - comando del driver: `AppleParavirtCommandExecIndirect = { IOAccelKernelCommand, I, [0 { II }] }`.
4. `AppleParavirtPooledBuffer -initWithDevice:options:args:argsSize:` accetta solo `argsSize == 0x80`. Copia la
   struttura, inserisce il proprio ID di risorsa (preso da `[[device serializer] newBufferRef]`) e chiama
   `-[MTLIOAccelBuffer initWithDevice:options:args:argsSize:]` con 0x80 byte.

5. Inizializzazione del device (`ev_47c17f49…`, `-[AppleParavirtDevice initWithAcceleratorPort:]`):
   `[super initWithAcceleratorPort:]` (MTLIOAccelDevice, che apre la connessione al servizio IOAccelerator) →
   `_segmentByteThreshold = 0x40000000` → `setupDeviceInfo` → `setupCompiler` (se fallisce il device viene
   rilasciato) → `setupResourcePools` → oggetti del driver (allocatore di riferimenti, serializer, heap dei
   descrittori). `AppleParavirtCommandQueue -initWithDevice:descriptor:` è un semplice passaggio a
   `MTLIOAccelCommandQueue` (`ev_095e63db…`).
6. Variante ARM (`AppleParavirtGPUMetalIOGPUFamily`, `ev_ba12b8e0…`): stesso disegno con classi `IOGPUMetal*`
   (IOGPU.framework) e strutture `IOGPUNewResourceArgs`, `IOGPUKernelCommand`, `IOGPUResourceList` (layout diversi).
   Su x86 Tahoe il driver paravirtuale usa IOAcceleratorFamily2: per la RX 9060 XT la strada è `MTLIOAccel*`.

**Dedotto (da verificare):**
- `IOAccelNewResourceData` è lunga 104 byte con l'allineamento x86_64: campi fino a 0x40, poi union da 40 byte.
  Gli altri 24 byte fino a 0x80 sono dati privati del driver, letti da `param_5[1]`.
- Per il nostro bundle (`navi48metal`) la strada è la stessa: sottoclassi `MTLIOAccel*` più argomenti
  `IOAccelNewResourceArgs` coerenti con IOAcceleratorFamily2 di 25G83. È il "layout gate" della fase 5.

## 4b. Come un servizio IOAccelerator aggancia il suo driver Metal (dagli Info.plist di 25G83)

**Osservato:**
- `AppleParavirtGPU` (v15.0.0, x86, PCI `0xEEEE106B`, `IOClass AppleParavirtGPUControl`) dichiara
  `AcceleratorProperties = { IOMatchCategory = IOAccelerator, MetalPluginName = "AppleParavirtGPUMetal",
  MetalPluginClassName = "AppleParavirtDevice", IOAccelDisplayPipeCapabilities = { DisplayPipeSupported = true,
  TransactionsSupported = true } }`. Metal cerca il bundle per nome in `/System/Library/Extensions` e istanzia
  quella classe, una sottoclasse di `MTLIOAccelDevice`.
- `AMDRadeonX6000` (v7.0.1) si attacca al dispositivo PCI solo con `IOPropertyMatch = { LoadAccelerator = true }`,
  lo stesso interruttore che Cobalt64 pubblica. Il nome del plugin Metal non è nell'Info.plist: lo imposta il kext a
  runtime.
- Versioni da dichiarare in `OSBundleLibraries` per 25G83: IOAcceleratorFamily2 487.4.3 (compatibile 2.0.0),
  IOGPUFamily 130.16.4 (2.0.0), IOGraphicsFamily 600 (1.0.0b1), IOSurface 393.5.8 (1.0); i kext grafici chiedono
  `com.apple.iokit.IOSurface` ≥ 87.0 e `com.apple.kpi.*` 9.0.0b1/16.7.

## 4c. System KC analizzata con REA; simboli per kext

- Con `REA_GHIDRA_STARTUP_TIMEOUT_MS` = 4 h e `GHIDRA_HEADLESS_MAXMEM` = 8G (non 16G: sulla macchina gira un altro
  servizio Java dell'utente), REA/Ghidra ha caricato tutta la System KC (`ev_f43deaa1…`): 2343 segmenti,
  245 186 procedure, 355 866 stringhe. Le sezioni di IOAcceleratorFamily2 sono al loro posto (`__text`
  0x14582600-0x145d9a00), ma Ghidra non dà alle funzioni i nomi delle tabelle dei simboli dei singoli kext.
- Le stringhe contengono le firme complete dei metodi (`ev_94a7387e…`), per esempio
  `IOAccelSharedUserClient2::new_resource(IOAccelNewResourceArgs *, struct IOAccelNewResourceReturnData *, …)` e
  `s_new_resource(IOAccelSharedUserClient2 *, void *, IOExternalMethodArguments *)`.
- `llvm-nm` legge i simboli di ogni voce del fileset: in `research/macos/25G83/symbols/` (fuori da git) ci sono
  IOAcceleratorFamily2 (4167 simboli, 125 vtable tra classi e MetaClass: IOAccelDevice2, IOAccelContext2,
  IOAccelSurfaceMTL, IOAccelSubmitter2, IOAccelEventMachine2, IOAccelMemory, …), IOGPUFamily (3067),
  IOGraphicsFamily (1590), AppleParavirtGPU (1229), AMDRadeonX6000 (4877) e la Boot KC (kernel compreso).

**Messo da parte (decisione dell'utente, 13/10/2026):** il layout slot per slot delle vtable. Il lavoro sulle Kernel Collection oltre a questo punto è stato
interrotto due volte durante la sessione e lasciato in sospeso, in attesa di una decisione dell'utente. Fonte più
pulita: il KDK di 25G83, che contiene i kext già separati e con simboli.

## 4d. Verifica del codice di Cobalt64 contro 25G83

- `tools/native/navi48accel/Info.plist`: la personality `Navi48Accelerator` (IOMatchCategory `IOAccelerator`)
  pubblica `MetalPluginName = Navi48Metal` e `MetalPluginClassName = Navi48Device`. È lo stesso meccanismo di
  `AppleParavirtGPU` (§4b).
- `tools/native/navi48metal/Navi48Device.m`: `Navi48Device : MTLIOAccelDevice`, con ingresso
  `-initWithAcceleratorPort:` che chiama `super`, come `AppleParavirtDevice` (§4, punto 5). Cobalt64 documenta che
  i resource pool IOAccel non ci sono (`-currentAllocatedSize`, `-newFence` vanno in crash): è coerente con il fatto
  che nel driver Apple li crea `setupResourcePools`, che Cobalt64 non usa.
- Librerie: navi48accel richiede IOAcceleratorFamily2 2.0.0 (25G83: 487.4.3, compatibile 2.0.0) e IOGraphicsFamily
  1.0 (25G83: 600, compatibile 1.0.0b1); il kext di bring-up dichiara IOPCIFamily 1.0 e kpi 20.0.0. Tutte compatibili.

Conclusione: il modello "accelerator + bundle Metal `MTLIOAccel*`" di Cobalt64 è confermato sui binari di 25G83, in
modo indipendente. Per la RX 9060 XT cambiano solo il nome del prodotto e l'id del device (fase 5.3).

## 4e. Controlli di compatibilità del nostro kext con 25G83

1. **Simboli del kernel.** Il kext di bring-up (`APPLE_ROUTE=0`, profilo navi44), compilato da Linux con i flag del
   Makefile, importa **419 simboli esterni**: tutti presenti nei simboli del kernel e delle famiglie IOKit di 25G83
   (`llvm-nm` su Boot e System KC). Senza `-fno-c++-static-destructors` comparirebbero `___cxa_atexit` e
   `___dso_handle`, che un kext non può importare: il Makefile vero li evita già.
2. **Resizable BAR (fase 2.5).** IOPCIFamily di 25G83 esporta solo gli ID delle capability
   (`gIOPCIExpressCapabilityIDResizableBARSym`, `…VFResizableBAR…`); nelle sue sezioni le uniche stringhe sul tema
   sono "ResizableBAR"/"VFResizableBAR", senza boot-arg, proprietà o messaggi di ridimensionamento. Dedotto: Tahoe non
   ridimensiona i BAR da sé e usa le dimensioni impostate dal firmware o da OpenCore. È coerente con Cobalt64
   (`rebar_pure.h`: un BAR sopra 1 GiB risulta di lunghezza 0 per IOPCIFamily). **Decisione per la RX 9060 XT**, che
   sotto Linux ha BAR0 = 16 GiB: OpenCore `UEFI → Quirks → ResizeGpuBars = 10` (2^10 MiB = 1 GiB). Il kext la verifica
   già incrociando la capability ReBAR (`kRebarMismatch`).
   **Aggiornamento hardware20/10:** la precedente scelta1GiB non basta nella VM: BAR0 a0x800000000
   manca in IOPCIFamily. Riduzione host VFIO a256MiB, con ResizeGpuBars=8: BAR0 guest0x90000000
   viene pubblicato correttamente, latch concorde e tre aperture check passano. Non è ancora isolato
   il contributo della dimensione rispetto al posizionamento sotto4GiB. Dettagli: `navi44_bringup_progress.md`.
3. **AGDC.** La `ConfigMap` di AppleGraphicsDevicePolicy (8.1.12) elenca 22 board-id con Config1-4/none; **MacPro7,1
   (`Mac-27AD2F918AE68F61`) non c'è**: nessuna politica di display applicata alla nostra scheda, non serve
   `agdpmod=pikera`. Conferma la scelta di SMBIOS del piano.

## 4f. Fermo nella sessione precedente (13/10/2026); inventario ripreso

Un terzo intervento del controllo di sicurezza è arrivato mentre si confrontavano i nomi dei metodi di
AMDRadeonX6000 con quelli di IOAcceleratorFamily2. È stato fermato anche il controllo dei simboli importati da
`navi48accel`: richiede le intestazioni generate da `ioaccel-layout`, non pubblico, cioè di fatto il layout delle vtable.
La sessione precedente aveva quindi sospeso questo filone fino al KDK o a una decisione esplicita dell'utente.
La nuova richiesta dell'utente di caricare REA e studiare ciò che manca ha ripreso l'indagine: un parser statico
legge direttamente le KC locali e ha recuperato tutte le vtable richieste dall'acceleratore, senza estrarre
o eseguire i kext. Vedi [inventario](ioaccel_vtable_inventory.md). Il generatore degli header resta incompleto.

## 4g. Cryptex x86_64: dyld shared cache ricostruito (13/10/2026)

- La patch `cryptex-system-x86_64` (RIDIFF10) applica a un'immagine vuota uno stream dati di 6 188 664 275 byte
  (sezione 2). La lunghezza è registrata nella sezione 1, e la sezione 0 contiene l'hash, la dimensione 0x96400000 e
  le tabelle degli extent. Lo stream decompresso alterna blob grezzi e voci Apple Archive (`AA01`).
- Non è servito ricostruire il volume APFS. I file del dyld shared cache stanno nello stream come blob grezzi, e la loro
  dimensione si ricava dall'intestazione (offset della firma del codice più la sua dimensione). Dal quarto file in poi
  sono contigui esattamente.
- Risultato in `research/macos/25G83/cryptex/dsc/` (fuori da git): `dyld_shared_cache_x86_64h` (UUID
  `F25A411F-0E2B-394F-861B-412F1A52F90D`, lo stesso del `.plist` nel cryptex) più `.01`–`.06` e `.symbols`;
  3626 immagini. Validato con **ipsw 3.1.737** (strumento open source MIT, Linux, SHA-256 verificato, in
  `research/ext/ipsw/`): `ipsw dyld info` legge l'intero set con i 6 sotto-cache.
- Estratti con `ipsw dyld extract` in `research/macos/25G83/dylibs/`: Metal (373.7), IOAccelerator (487.4.3, la stessa
  versione del kext), IOGPU (130.16.4), AMDRadeonX6000MTLDriver e AMDMTLBronzeDriver (7.1.6), AMDShared,
  libAppleParavirtCompilerPlugin.
- **IOAccelerator.framework 487.4.3** analizzato con REA/Ghidra (`ev_38a0d871…`): 279 procedure `IOAccel*`
  (elenco in `research/macos/25G83/rea/ioaccelfw_api.txt`, fuori da git). È l'API C con cui Metal e i driver in spazio
  utente parlano con IOAcceleratorFamily2: device (`IOAccelDeviceCreate`, `…GetConfig64`, `…GetConnect`), shared
  (`IOAccelSharedCreate`, `…GetConnect`, `…AllocateFenceMemory`), risorse (`IOAccelResourceCreate`,
  `…GetGPUVirtualAddress`, `…SetPurgeable`), liste di risorse (`IOAccelResourceListInit/AddResource/Reset`), code
  (`IOAccelCommandQueueCreateWithQoS`, `IOAccelCommandQueueSubmitCommandBuffers`) e contesti GL/video. Per noi è il
  confine da rispettare: il kext acceleratore deve rispondere a queste chiamate come IOAcceleratorFamily2.
- Resta da capire a cosa servono il file da 26 MB con il suo `.symbols` (un secondo cache principale, piccolo) e i
  160 MB finali dello stream. Non servono per Metal.framework.

## 4h. Driver Metal AMD di Apple (AMDRadeonX6000MTLDriver 7.1.6, dal dyld cache)

- REA/Ghidra (`ev_a61ae545…`): 13 283 procedure, 32 009 stringhe. Le decompilazioni dei metodi Objective-C non sono
  affidabili su una libreria estratta dal dyld cache: gli stub verso le altre librerie (es. `objc_msgSendSuper2`)
  risultano chiamate senza ritorno verso simboli sbagliati (`ev_b217bf20…`, `ev_acb2f2f4…`). Per la struttura si sono
  usati i metadati Objective-C (`ipsw class-dump`, 128 header in `research/macos/25G83/rea/classdump/`, fuori da git).
- **Classi e base di Metal.framework** (`ev_3edc1447…` e class-dump):
  `GFXAAMD_MtlDevice : MTLIOAccelDevice` (sottoclasse `GFX10_MtlDevice`), `GFXAAMD_MtlCmdQueue : MTLIOAccelCommandQueue`,
  `GFXAAMD_MtlCmdBuffer : MTLIOAccelCommandBuffer` (→ `GFX10_MtlCmdBuffer`), `GFXAAMD_MtlBuffer : MTLIOAccelBuffer`,
  `GFXAAMD_MtlTexture : MTLIOAccelTexture` (→ `GFX10_MtlTexture`), `GFXAAMD_MtlHeap : MTLIOAccelHeap`,
  `GFXAAMD_MtlBlitCmdEncoder : MTLIOAccelBlitCommandEncoder`, `GFX10_MtlRenderCmdEncoder : MTLIOAccelRenderCommandEncoder`,
  `GFX10_MtlComputeCmdEncoder : MTLIOAccelComputeCommandEncoder`, `GFXAAMD_MtlIndirectCmdBuffer`,
  `GFXAAMD_MtlIndirectArgumentBufferEncoder`, `GFX10_MTLAccelerationStructure`, tabelle di funzioni visibili e di
  intersezione; pipeline, sampler e depth/stencil derivano da `_MTLRenderPipelineState`, `_MTLComputePipelineState`,
  `_MTLSamplerState`, `_MTLDepthStencilState`.
- **Schema a due livelli**: `GFXAAMD_*` contiene la logica comune sopra `MTLIOAccel*`, `GFX10_*` la specializza per
  generazione. Per la RX 9060 XT il nostro bundle può seguire lo stesso schema (una base comune più una classe RDNA4).
- **IOAccelerator.framework usato da AMD**: un sottoinsieme ridotto (`IOAccelDeviceGetConnect`, `…GetMaxResourceSize`,
  `IOAccelSharedGetConnect`, `…SetupDirtyRing`, `IOAccelResourceList*`, `IOAccelResourceDirty*`, `…TestEvent`).
- **Copertura del device rispetto a Cobalt64**: il device AMD dichiara 164 metodi (`GFXAAMD` + `GFX10`), il
  `Navi48Device` di Cobalt64 ne copre 24. Il confronto è fatto per selettore con regex, quindi i metodi in categorie
  potrebbero sfuggire. **Questo conteggio storico misura gli override, non le API mancanti**: il nuovo audit
  conta 162 dichiarazioni esplicite AMD e 23 override comuni, e 65 dei 139 selettori senza override sono già
  dichiarati dalle basi. La presenza di una dichiarazione non prova che il metodo funzioni col backend nativo.
  Vedi [audit riproducibile](metal_selector_audit.md). Gruppi da verificare per la fase 5.3: aggancio al compilatore
  (`…FunctionKeyWith…Descriptor…`, `…VariantWithCompilerOutput:…`,
  `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:`, `newComputePipelineWithDescriptor:variant:`),
  capacità (`supportsRaytracing`, `supportsFunctionPointers`, `supportsDynamicLibraries`, `supportsInt64`,
  `minLinearTextureAlignmentForPixelFormat:`, `sparseTileSize…`), indirect command buffer e argument encoder,
  `sampleTimestamps:gpuTimestamp:`. Elenco completo: `research/macos/25G83/rea/amd_device_methods_missing.txt`.

## 4i. Classi base `MTLIOAccel*` di Metal.framework 373.7 (metadati Objective-C)

`ipsw class-dump` di Metal dal dyld cache (565 header, 35 classi `MTLIOAccel*`, in `research/macos/25G83/rea/classdump/metal/`).

- `MTLIOAccelDevice : _MTLDevice` (25 ivar, 67 metodi). Configurazione che il driver imposta:
  `initialKernelCommandShmemSize`, `initialSegmentListShmemSize`, `setSegmentListShmemSize:`,
  `setComputePipelineStateCommandShmemSize:`, `setHwResourcePool:count:`, `updateResourcePoolPurgeability`;
  gestione: `_setAcceleratorService:`, `lazyInitialize`, `newFence`/`releaseFenceIndex:`, `kickCleanupQueue`,
  `retain/releasePeerConnection:`, `newArgumentEncoderWithLayout:`.
- `MTLIOAccelCommandBuffer : _MTLCommandBuffer` (7 ivar, 43 metodi): **modello di invio**.
  - **Kernel command buffer** in memoria condivisa: il driver ci scrive i propri comandi (`IOAccelKernelCommand`)
    con `_reserveKernelCommandBufferSpace:`, `getCurrentKernelCommandBufferPointer:end:`,
    `setCurrentKernelCommandBufferPointer:`, `growKernelCommandBuffer:`, `kernelCommandCollectTimeStamp`.
  - **Segment list**: per ogni segmento le risorse usate (`beginSegment:`, `endCurrentSegment`, `growSegmentList`,
    `getSegmentListPointerStart:current:end:`). Il layout esposto da `getSegmentListHeader`:
    `IOAccelSegmentListHeader { u64; u32; u32; IOAccelSegmentResourceListHeader[] }`,
    `IOAccelSegmentResourceListHeader { u64; u32 ×4; IOAccelSegmentResourceDescriptorGroup[] }`,
    `IOAccelSegmentResourceDescriptorGroup { u32[6]; u64[6]; u16[6]; u16; u16 }` (6 risorse per gruppo).
  - Invio: `commit`, `commitAndReset`, `commitEncoder`; completamento:
    `didCompleteWithStartTime:endTime:error:`; eventi: `encodeSignalEvent:value:`, `encodeWaitForEvent:value:`.
- **Confine del modello:** questi kernel command buffer e segment list descrivono i driver Apple che usano
  `MTLIOAccelCommandBuffer`. Il bundle nativo corrente usa invece `N48CommandBuffer : _MTLCommandBuffer` e
  `N48CommandQueue : _MTLCommandQueue`, inviando tramite `vkQueueSubmit` → RADV → N48N. La famiglia IOAccel
  resta necessaria per inizializzare il device e per il display; il formato di submission Apple non va assunto
  come formato render del bundle nativo. Vedi [ABI REA](ioaccelerator_abi_re.md) e [audit](metal_selector_audit.md).

## 5. Bloccato o rimandato

- **Kext dentro le KC**: l'inventario delle 13 vtable dell'acceleratore è ora recuperato direttamente dalle KC
  con `tools/kc_vtable_inventory.py` (2720 slot). La decompilazione mirata dei singoli kext e il generatore C++
  completo restano da affrontare: dimensioni delle classi, firme e forwarder non sono risolti dall'inventario.
  Il KDK o il loader fileset di Ghidra restano alternative per questi passi successivi.
- **Cryptex x86_64 (RIDIFF10)**: RISOLTO, vedi §4g. Storico: intestazione e sezioni identificate (offset a 0x1e/0x26/0x2e; sezione 0 pbzx da
  1 317 571 byte di metadati, sezione 1 da 16 byte, sezione 2 pbzx con 5902 blocchi, 6,19 GB decompressi). Lo
  strumento `ipsw` applica queste patch solo su macOS. Serve per Metal.framework e i driver Metal AMD.
