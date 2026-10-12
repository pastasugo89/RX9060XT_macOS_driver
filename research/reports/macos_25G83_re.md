# macOS Tahoe 26.6.2 (25G83): estrazione dei binari e primo reverse engineering

Data: 12/10/2026. Fonte: `InstallAssistant.pkg` scaricato con gibMacOS
(`research/ext/gibMacOS/macOS Downloads/publicrelease/140-93587 - 26.6.2 macOS Tahoe (25G83)/`).
I binari Apple estratti stanno in `research/macos/` (escluso da git, mai ridistribuiti; uso per interoperabilità).

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

## 5. Bloccato o rimandato

- **Kext dentro le KC**: per analizzarli con REA servono come Mach-O singoli. Il tentativo di scrivere un estrattore
  apposito è stato interrotto durante la sessione e non è stato ripreso. Strade alternative: le
  analizza una sessione con gli strumenti MCP di REA caricati (dopo il riavvio), oppure il loader "file system" di
  Ghidra per le kernel collection, oppure il KDK di 25G83 (kext con simboli completi, da developer.apple.com).
- **Cryptex x86_64 (RIDIFF10)**: intestazione e sezioni identificate (offset a 0x1e/0x26/0x2e; sezione 0 pbzx da
  1 317 571 byte di metadati, sezione 1 da 16 byte, sezione 2 pbzx con 5902 blocchi, 6,19 GB decompressi). Lo
  strumento `ipsw` applica queste patch solo su macOS. Serve per Metal.framework e i driver Metal AMD.
