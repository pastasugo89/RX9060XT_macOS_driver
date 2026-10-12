# 08 - Lato Metal dello stack: dal MTLDevice alla GPU gfx12 (Navi 44)

Stato: scrittura incrementale (2026-10-12). Legenda: **[VERIFICATO]** = letto nel codice/dati locali o testato su questa macchina; **[INFERITO]** = deduzione o conoscenza generale non verificata localmente; **[WEB]** = fonte web citata.
Report correlati (non ripetuti qui): `05-cobalt64-deepdive.md` (kext + bundle Navi48Metal), `06-nvidia-macos-driver-deepdive.md` (NullMoth: NVAccel, NVMTLDriver.bundle, traduttore), `03-mesa-radv-aco-gfx12.md` (RADV/ACO gfx1200, winsys Darwin).
Percorsi abbreviati: `M2V/` = `research/refs/metal2vulkan/`, `NVM/` = `research/refs/nvidia-macos-driver/`, `COB/` = `research/refs/Cobalt64/`, `MESA/` = `research/src/mesa/`.

## 0. Sommario esecutivo

1. **Come arriva il lavoro alla GPU**: Metal.framework trova il device leggendo `MetalPluginName`/`MetalPluginClassName` da un servizio IOAccelerator e carica un bundle vendor in **ogni** processo Metal (WindowServer incluso); la classe plugin deriva dalla privata `MTLIOAccelDevice` (`-initWithAcceleratorPort:`). Apple non ha un compilatore AIR->gfx12 (libSC AMD si ferma a gfx10.3), quindi la strada praticabile, adottata sia da NullMoth (NVIDIA) sia da Cobalt64 (Navi 48), è: bundle nostro -> AIR -> **metal2vulkan** -> SPIR-V -> **RADV/ACO** -> gfx1200 -> winsys Darwin -> kext. [VERIFICATO nei due repo]
2. **AIR**: LLVM bitcode del fork Apple dentro un container `MTLB` (un modulo per funzione, tag `NAME/TYPE/HASH/MDSZ/OFFT/VERS`, metadata `CNST/VATT`), address space 0-4,6,7, metadata ABI chiuso (`air.kernel/vertex/fragment/...`, `air.buffer/texture/sampler/indirect_buffer`, kernel CoreImage `air.ci`). **Verificato**: LLVM upstream 23.1.1 legge l'AIR 2.8 di macOS 26 (`air64_v28-apple-macosx26.0.0`, metalfe-32023.921.6).
3. **metal2vulkan è cambiato radicalmente**: NullMoth e Cobalt64 usano la 0.1 (testo LLVM -> SPIR-V per singola funzione, LGPL); l'upstream attuale 0.2 (11-10-2026) è una riscrittura con lettore bitcode proprio, compilazione per **pipeline** (render/tess/tile/mesh), binding plan, e un **runtime Metal-su-Vulkan** completo (hazard tracking, eventi come timeline semaphore, ICB, argument buffer, formati XR10/YCbCr), validato sul traffico reale di WindowServer/CoreAnimation/CoreImage di Tahoe 26.6.2. Copertura: 957 voci API implementate, 829 mancanti, 349 fuori scope (IOSurface, drawable, ray tracing API).
4. **RADV gfx1200 non ha gap hardware/driver per Metal 3**: tutte le 29 feature e 2 estensioni che metal2vulkan nomina come requisito sono presenti sul RX 9060 XT (verificato sul profilo misurato); bindless (BDA + descriptor indexing + `VK_EXT_descriptor_heap`), int64/float atomics, subgroup size control (32 pinnabile in FS/CS/task/mesh), maximal reconvergence, mesh, ray query, sparse, POPS (framebuffer fetch), cooperative matrix, bfloat16. I veri gap sono **nel software**: simdgroup_matrix non implementata nel traduttore, build di acceleration structure e intersection function table, ICB GPU-encoded, Metal 4, e varie **dipendenze dal kext** (VA stabili, userptr, syncobj timeline, coda compute + gang submit per mesh/task, PRT per sparse, fence per BO). Navi 44 e Navi 48 sono identici per tutto lo strato Metal (stesso gfx_level GFX12).
5. **Desktop minimo (WindowServer)**: texture su IOSurface (anche multi-plane), render pass colore, framebuffer fetch e blend su formati XR10 (login di Tahoe), heap MPS, depth/stencil state, sampler bicubico, LUT R32Float 16384x1 di CoreDisplay, mai restituire nil, `commitAndWaitUntilSubmitted` + presentazione via `IOAccelDisplayPipe`. Le app aggiungono: compilazione MSL a runtime (WebKit/ANGLE/Dawn), traduzione in-process nel sandbox, `MTLSharedEvent` cross-process, argument buffer tier 1/2, `MTLGPUFamilyMac2` (Skia/Chromium) e poi Metal 3.
6. **IOSurface**: tre modelli osservati: memoria di sistema importata con userptr + copia per frame in VRAM (Cobalt64, semplice), VRAM zero-copy via la famiglia IOAccelerator + flip diretto (NullMoth, veloce ma fragile), immagine privata + copie (fallback). Per una dGPU lo scanout DCN è solo da VRAM (verificato nel driver Linux).
7. **Raccomandazione**: bundle ObjC sul modello Cobalt64 (MIT) che lascia ad Apple librerie/funzioni (front-end MSL, reflection, function constants) e prende l'AIR alla creazione pipeline, con **metal2vulkan-runtime 0.2 come motore** (adotta il `VkDevice` RADV, LGPL) e il solo traduttore come ripiego; IOSurface modello A per il bring-up, modello B + fence per BO per le prestazioni. Le tappe di traduzione L0-L1 si possono validare **su Linux con RADV sulla stessa scheda** prima di avere macOS o il kext (§9).

## 1. Come il lavoro di un'app Metal arriva alla GPU su macOS (catena Apple e catena sostitutiva)

### 1.1 Catena Apple originale (driver AMD x86 di Apple) [INFERITO salvo dove indicato]

```
App / WindowServer / CoreAnimation / CoreImage / MPS / WebKit GPU process
   |  MTLCreateSystemDefaultDevice / MTLCopyAllDevices
   v
Metal.framework (classi pubbliche MTL* + classi private _MTL*/MTLIOAccel*)
   |  enumera i servizi IOAccelerator (sottoclassi di IOGraphicsAccelerator2) nel registry,
   |  legge MetalPluginName / MetalPluginClassName                         [VERIFICATO: NVM e COB lo sfruttano]
   v
Bundle driver Metal del vendor: /System/Library/Extensions/AMDRadeonX6000MTLDriver.bundle (Navi 1x/2x)
   |  classe device : MTLIOAccelDevice, -initWithAcceleratorPort:          [VERIFICATO: NVM/plugin/NVMTLDevice.m:136-140]
   |  encoder -> PM4 gfx10.x scritto direttamente in user space dentro buffer condivisi IOAccel
   |  shader: MTLCompilerService (XPC) = front-end MSL->AIR + back-end vendor (libSC AMD) AIR->ISA gfx10.3
   v                                                                        [VERIFICATO in 05 §5.1: libSC produce gfx10.3]
IOAccelerator family (IOAcceleratorFamily2.kext): user client SharedUserClient (risorse), CommandQueue (submit),
   |  EventMachine (stamp/fence), DisplayPipe (transazioni di presentazione di WindowServer)
   v
AMDRadeonX6000.kext + AMDRadeonX6000HWServices/HWLibs (TTL)  -> ring PM4 / SDMA -> GPU
IOSurface.kext: le superfici (drawable CAMetalLayer, layer CoreAnimation, frame video) sono IOSurface;
il kext acceleratore ne fornisce il backing GPU (IOAccelResource, "deviceCacheForIOSurface")  [VERIFICATO: 06 §2.5]
```

Punti chiave per noi:
- **Il "driver Metal" è un bundle user space caricato in OGNI processo che usa Metal**, WindowServer incluso. Il kernel vede solo submission e gestione memoria/superfici tramite la famiglia IOAccelerator.
- **Il compilatore AIR->ISA è del vendor**: per Navi 1x/2x Apple distribuisce libSC che emette gfx10.x. Non esiste un back-end Apple per gfx11/gfx12, quindi la rotta "riuso del driver Metal di Apple" richiede di sostituire gli shader (Cobalt64 lo fa solo per un insieme chiuso di shader catturati, `05 §5.1`), cosa non scalabile.
- Metal.framework fornisce già gran parte del "front-end" in modo vendor-neutrale: oggetti descriptor, `_MTLCommandBuffer`, `_MTLSharedEvent` CPU-side (Cobalt64 li riusa, `COB/tools/native/navi48metal/Navi48Device.m:4809`), compilazione MSL->AIR via MTLCompilerService (NullMoth la riusa, `06 §5.3`).

### 1.2 Catena sostitutiva adottata da NullMoth e Cobalt64 (e raccomandata per noi) [VERIFICATO nei due repo]

```
App / WindowServer
   v
Metal.framework  --(MetalPluginName dal NOSTRO IOAccelerator)-->  /Library/GPUBundles/<Nostro>.bundle
   |   classe : MTLIOAccelDevice (+ oggetti conformi ai protocolli MTL* o sottoclassi _MTL*)
   |   shader: metallib/AIR  --(metal2vulkan)-->  SPIR-V  --(vkCreateShaderModule)-->  ACO  -> ISA gfx1200
   |   comandi: encoder Metal -> VkCommandBuffer (RADV)  -> PM4 gfx12 generato da RADV
   v
RADV (libvulkan_radeon.dylib, dlopen senza loader) + winsys Darwin (sostituisce libdrm_amdgpu)
   v   IOUserClient del nostro kext (BO alloc/map/VA, CS submit, fence/syncobj, query info)
Nostro kext (bring-up GC 12.0.0 / MES / SDMA 7.0 / GMC 12 / IH 7 / PSP 14.0.2 / SMU 14.0.2 / DCN 4.0.1)
   v
RX 9060 XT (Navi 44, 1002:7590)
```

- NullMoth: `NVMTLDevice : MTLIOAccelDevice`, oggetti `NSObject <MTLBuffer>` ecc., NVK caricato con `dlopen` (`06 §5.1-5.4`).
- Cobalt64: `Navi48Device : MTLIOAccelDevice` + sottoclassi `_MTLResource`, `_MTLCommandBuffer`, `_MTLCommandEncoder` (`05 §6.2`), RADV caricato con `dlopen` + `vk_icdGetInstanceProcAddr` (`Navi48Device.m:508-538`).
- In entrambi **l'unica parte GPU-specifica sopra Vulkan è minima** (NullMoth: ~33 righe in `nvmtl_vk.c`; Cobalt64: export `radv_darwin_scanout_*` per il flip, `Navi48Device.m:1026-1030`). Il resto (Metal->Vulkan e AIR->SPIR-V) è vendor-neutrale e quindi è la parte del nostro progetto che si può **riusare quasi integralmente** da progetti esistenti.

## 2. Formato AIR e metallib

Fonte principale: il front-end AIR indipendente di metal2vulkan 0.2 (`M2V/crates/metal2vulkan-air/src/`), scritto da osservazione dell'output Apple (formati 2.7-2.9, M3 Max/M4). Tutto quanto segue è **[VERIFICATO]** sul codice del parser salvo dove marcato.

### 2.1 Le quattro forme di input (`container/mod.rs:1-25`)

| Primi byte | Forma | Note |
|---|---|---|
| `MTLB` | metallib eseguibile: un modulo bitcode **per funzione** | prodotto da `metal`/`metallib`, è ciò che `newLibraryWithData:` / `newDefaultLibrary` caricano |
| `CB FE BA BE` (BE) | metallib "universal": slice per AIR e per GPU | scritto da `MTLDynamicLibrary serializeToURL:`; la slice con CPU type **`0x01000017`** è l'AIR, le altre sono codice GPU (ignorate) |
| `DE C0 17 0B` | bitcode wrapper `0x0B17C0DE` (file `.air`) | header wrapper: version, offset, size, cputype |
| `BC C0 DE` | bitcode LLVM nudo | |

### 2.2 Struttura MTLB (`container/mtlb.rs:1-28`, `container/tags.rs`)

- **Header 0x58 byte** little-endian: `"MTLB"`, `platform u16`, `version u16 u16` (solo major 2 accettato), `file_type u8` (0 = libreria eseguibile, 2 = dinamica, `MTLLibraryTypeDynamic`), `os u8`, `os_version u16 u16`, `file_size u64`, poi coppie `(offset,size)` per: function list, public metadata, private metadata, sezione bitcode.
- **Function list**: `u32 count`, poi per funzione `u32 entry_size` + tag list. Ogni tag = fourcc + `u16` lunghezza + byte; la lista termina con `ENDT` (senza lunghezza). Tag per funzione (`mtlb.rs:527-532`): `NAME` (nome), `TYPE` (stadio: 0 vertex, 1 fragment, 2 kernel, 3 exported, 4 visible, 6 intersection, 7 mesh, 8 object; `container/mod.rs:142-153`), `HASH` (SHA-256 del bitcode, verificato), `MDSZ` (dimensione bitcode), `OFFT` (offset public md / private md / bitcode relativi alle sezioni), `VERS` (versioni AIR e linguaggio).
- **Public metadata** per funzione: `CNST` (function constants: nome, tipo, indice), `VATT`/`VATY` (attributi vertex e tipi) (`mtlb.rs:652-683`).
- **Extended header**: `HDYN` (install name + `DYNL` per ogni dynamic library linkata) e `ILST` (simboli importati) (`mtlb.rs:22-28`).
- Due convenzioni per la dimensione dei record metadata (con o senza la word di size) a seconda che il file venga da `metallib` o da `metal` (`mtlb.rs:617-623`): dettaglio che un parser scritto da zero sbaglierebbe facilmente.

### 2.3 Il modulo AIR: LLVM bitcode del fork Apple

- Triple `air64-apple-macosNN.0` (es. `air64-apple-macos15.0` nelle fixture), datalayout fisso
  `e-p:64:64:64-i1:8:8-i8:8:8-i16:16:16-i32:32:32-i64:64:64-f32:32:32-f64:64:64-v16:16:16-...-v1024:1024:1024-n8:16:32` (`ir/tests.rs:402-404`).
- Il bitcode è emesso dal front-end Apple ("metalfe", LLVM interno; Cobalt64 riporta `llvmVersion = 0x7d17` = 32023, copiato dal driver paravirt, `Navi48Device.m:6266`). Coesistono bitcode a **puntatori tipizzati** (AIR più vecchio) e a **puntatori opachi**: metal2vulkan li canonicalizza in modo identico (`canon/mod.rs:20-22`). [INFERITO] Il lettore bitcode di LLVM upstream non legge sempre il bitcode Apple più recente (record/attributi del fork): per questo NullMoth usa `libLLVM.dylib` incluso nel bundle e Cobalt64 il bitcode reader di sistema; metal2vulkan 0.2 ha **un proprio lettore bitcode** e non dipende da LLVM a runtime (`docs/ARCHITECTURE.md`, "The library runs no external tool").
- **Address space** (`ir/types.rs:150-193`): 0 `thread` (privato), 1 `device` (buffer globali), 2 `constant`, 3 `threadgroup` (LDS), 4 `threadgroup_imageblock` (tile memory), 6 `object_data` (payload object->mesh), 7 mesh output. Il 5 e gli spazi della libreria AGX sono rifiutati (`REFUSALS.md`, variante `AddressSpace`).
- **Metadata ABI** (closed grammar, `abi/mod.rs:1-40`, `abi/module.rs`): named metadata a livello modulo `air.vertex`, `air.fragment`, `air.kernel`, `air.mesh`, `air.object`, `air.visible`, `air.patch`, `air.version`, `air.language_version`, `air.compile_options` (`air.compile.fast_math_enable/disable`, `framebuffer_fetch_enable`, `denorms_disable`), `air.function_constants`, `air.sampler_states`, `air.global_bindings`, `air.max_device_buffers/max_textures/max_samplers/max_work_group_size/...`, `llvm.module.flags`, `llvm.ident`.
  Per argomento (`abi/keys.rs`): `air.buffer` + `air.location_index` + `air.read`/`air.read_write` + `air.arg_type_size` + `air.arg_type_align_size` + `air.struct_type_info`; `air.texture`; `air.sampler`; argument buffer `air.indirect_buffer` con membri `air.indirect_argument` / `air.indirect_constant`; built-in (`air.thread_position_in_grid`, `air.threads_per_simdgroup`, `air.thread_index_in_simdgroup`, `air.position`, `air.render_target`, `air.sample_mask`, `air.primitive_id`, `air.barycentric_coord`, `air.stage_in`, `air.vertex_id`, `air.instance_id`, ...); oggetti GPU-side (`air.command_buffer`, `air.render_pipeline_state`, `air.compute_pipeline_state`, `air.depth_stencil_state`, `air.instance_acceleration_structure`, `air.intersection_function_table`).
  **Kernel Core Image**: `air.ci` con `air.ci_texture`, `air.ci_sampler`, `air.ci_pointer`, `air.ci_matrix`, `air.ci_builtin` (`abi/core_image.rs`): CoreImage compila i propri filtri come funzioni AIR speciali -> il traduttore **deve** supportarle per avere un desktop usabile (Anteprima, Foto, effetti di sistema).
- **Intrinseci** (`intrinsics/mod.rs:1-31`): famiglie `air.*` decodificate in modo tipizzato: math, conversioni/packing, atomici e accessi coerenti, derivate, texture e sampler (`air.sample_texture_*`, `air.read_texture_*`, `air.write_texture_*`, `air.get_width_*`...), barriere e fence (`air.wg.barrier`, `air.mem_barrier`), **simdgroup e quad** (`simd_sum/product/min/max/and/or/xor`, `simd_prefix_{in,ex}clusive_{sum,product}`, `simd_shuffle{,_up,_down,_xor,_rotate_*,_and_fill_*}`, `simd_broadcast{,_first}`, `simd_ballot`, `simd_all/any`, `simd_active_threads_mask`, `simd_is_first`, `quad_*`; `intrinsics/simd.rs`), **simdgroup matrix** (8x8), function constants, operazioni fragment (discard, framebuffer fetch), imageblock, async copy, function table, query di acceleration structure, `air.intersect` (ray tracing), descrittori tensor, comandi indiretti GPU-side (`render_command`/`compute_command`), più un set chiuso di `llvm.*` e la famiglia "AGX". I nomi sconosciuti restano `UnknownIntrinsic` e sono rifiutati solo se sopravvivono alla specializzazione.

### 2.4 Function constants, linking, argument buffer

- **Function constants** (`[[function_constant(n)]]`): global "esterni" elencati in `air.function_constants` + tag `CNST` del container. Apple specializza in `newFunctionWithName:constantValues:` (il compiler service rilegge l'AIR con i valori). metal2vulkan li **"cuoce"** come inizializzatori, poi SCCP + potatura (`canon/mod.rs:15-19`); i fatti di binding variabili per draw (presenza di slot, parole sampler) diventano **specialization constant SPIR-V** (`docs/API.md:367-373`). NullMoth espone `nvmtl_translate_fc` (`06 §6`).
- **Linked/visible functions e dynamic library**: risolte staticamente (import + inlining); le **visible function table** sono devirtualizzate in uno `switch` sulle funzioni possibili quando il set è noto alla creazione pipeline (`canon/mod.rs:10-30`). Ricorsione e chiamate davvero dinamiche (function pointer arbitrari) sono rifiutate (`DynamicCall`: "no Vulkan mechanism").
- **Argument buffer**:
  - *Tier 1* (Metal 2): struct codificata tramite `MTLArgumentEncoder` con layout opaco del driver: il driver decide il layout -> può essere tradotto in descriptor set.
  - *Tier 2 / Metal 3 "bindless"*: l'argument buffer è memoria qualsiasi scritta dalla CPU; un `device T*` è il `gpuAddress` (64 bit) di un `MTLBuffer`, una texture/sampler è un `MTLResourceID` (64 bit, `gpuResourceID`). Mapping metal2vulkan: puntatori -> **buffer device address** (`PhysicalStorageBuffer64`); texture/sampler -> indice in **array "heap" nel descriptor set 1** (`docs/API.md:362-366`); `MTLResourceID` = indice nell'heap assegnato dal runtime. Membri che sono pipeline state, ICB, function table o acceleration structure: rifiutati (`ArgumentBufferObjects`, "not implemented").
  - Conseguenza per il driver: `MTLBuffer.gpuAddress` deve essere il VA GPU reale (`vkGetBufferDeviceAddress` su RADV = VA nel VM del processo) e `gpuResourceID` deve indicizzare un descriptor heap globale per device. È esattamente ciò che Cobalt64 **non** implementa (per questo nega `MTLGPUFamilyMetal3` alle app, `Navi48Device.m:6270-6284`) e che NullMoth implementa (`NVMTLObjects.m:821` `gpuAddress` = BDA NVK; `:981` `gpuResourceID` = handle per texture).

### 2.5 Test eseguito: LLVM upstream legge l'AIR di Apple (macOS 26) [VERIFICATO]

Input: le 5 fixture AIR compilate col compilatore Apple presenti in `M2V/crates/metal2vulkan-validation/fixtures/public/engine/ob3_*.air` (dati di terzi, solo letti). Strumento: `llvm-dis` 23.1.1 di sistema, output in `scratchpad/metal-xlate/air/`.
- Tutti e 5 i file (wrapper `DE C0 17 0B`, header wrapper offset 0x14) sono disassemblati **senza errori** da LLVM upstream 23.1.1.
- `target triple = "air64_v28-apple-macosx26.0.0"` (AIR 2.8, il triple ora porta la versione), datalayout come in §2.3, **puntatori opachi** (`ptr addrspace(1)`), intrinseci tipo `declare { <4 x i32>, i8 } @air.read_texture_2d.u.v4i32(ptr addrspace(1) ..., ptr addrspace(2), <2 x i32>, <2 x i32>, i32, i32)` e `@air.get_read_sampler()`.
- Metadata: `!llvm.ident = "Apple metal version 32023.921 (metalfe-32023.921.6)"` (32023 = 0x7d17, il `llvmVersion` dichiarato da Cobalt64), `!air.version = {2, 8, 0}`, `!air.language_version = {"Metal", 4, 0, 0}`, `!air.compile_options = {denorms_disable, fast_math_enable, framebuffer_fetch_enable}`.
- Conseguenza: per il percorso "testo LLVM" (metal2vulkan 0.1) basta un LLVM upstream recente (non serve il `libLLVM` Apple); metal2vulkan 0.2 non ne ha nemmeno bisogno. Rischio residuo: versioni future del bitcode Apple potrebbero precedere il supporto upstream (record nuovi): il lettore proprio di metal2vulkan 0.2 va tenuto allineato alle release di macOS.

## 3. metal2vulkan: architettura, copertura, gap, test

### 3.1 Due generazioni molto diverse [VERIFICATO]

| | 0.1.x (vendorizzato) | 0.2.0 (upstream attuale, `M2V/`) |
|---|---|---|
| Dove | `NVM/translator/translator` (crate `metal2vulkan 0.1.0`, Rust 1.87, ~302 K righe con test) + wrapper NullMoth `nvmtl_translate`; Cobalt64 fissa il commit `43c46ac8` + patch di 1 328 righe + cdylib `n48xlate` di 594 righe (`COB/third-party/metal2vulkan-n48/README.txt`, `n48xlate/src/lib.rs`) | `steelbrain/metal2vulkan` commit `13b279df` dell'11-10-2026; workspace di 5 crate, ~1,25 M righe Rust (translator 559 K, air 81 K, runtime 211 K, validation 400 K, devtools 4 K, conteggio `wc -l`) |
| Licenza | LGPL-3.0-or-later | **GPL-2.0-or-later OR LGPL-3.0-or-later** (`CHANGELOG.md`) |
| Input | **testo LLVM IR** (`.ll`), prodotto dal chiamante con LLVM (NullMoth: `libLLVM.dylib` nel bundle; Cobalt64: bitcode reader di sistema o `n48-llvm-dis`) | metallib / bitcode AIR direttamente (lettore bitcode proprio), `.ll` solo da CLI (`llvm-as`) |
| Unità | singolo stadio -> SPIR-V 1.x + JSON di reflection | **pipeline intera** (compute, render, tessellation, tile, mesh): SPIR-V per stadio, un pipeline layout, stato fixed-function, *binding plan* per draw/dispatch |
| Runtime Metal | no (lo scrive il consumer: `NVMTLObjects.m`, `Navi48Device.m`) | **sì**: `metal2vulkan-runtime`, API Metal su Vulkan (via `ash`) |
| Stato | usato in produzione da NullMoth e Cobalt64 | "Alpha", API instabile, 0.2.0 non pubblicata su crates.io (`README.md`) |

Osservazione importante: la documentazione 0.2 parla di un "consumer" che è **una GPU paravirtualizzata che avvolge Metal dietro i propri trait** (`docs/RUNTIME-PORTING.md:1-10`, `:594-612`: `HostVm`, `GpuDevice::new_texture_on_surface`, "guest"), e i casi "reach=system" citano *"macOS 26.6.2's login ... the consumer's boots"* (`docs/REFUSALS.md`, righe `FramebufferFetch`, `SamplerBicubicFilter`). Cioè: metal2vulkan 0.2 è sviluppato per eseguire il **traffico Metal di un guest macOS** (protocollo ParavirtualizedGraphics, lato host) su Vulkan, e viene validato proprio sul traffico reale di WindowServer/CoreAnimation/CoreImage di Tahoe 26.6.2. Per noi è un vantaggio: il suo "reach=system" è esattamente l'elenco di ciò che serve al desktop.

### 3.2 Pipeline del traduttore 0.2 (`docs/ARCHITECTURE.md`) [VERIFICATO]

```
metallib | AIR bitcode
 -> parse (container) -> decode (bitstream/bitcode -> IR tipizzato + AirAbi + intrinseci tipizzati)
 -> specialize (canon: entry, linking visible functions, function constants, static init, pointer erasure,
               inlining, devirtualizzazione function table, SCCP, potatura)
 -> analyze (memory: provenance dei puntatori, MemoryPlan, finestre di slot)
 -> select  (una strategia per istruzione/interfaccia, placement push constant, requisiti, stima dimensione)
 -> structurize (CFG AIR -> albero strutturato; irriducibile -> dispatch multi-entry; rifiuto se contiene istruzioni convergenti)
 -> emit (builder SPIR-V tipizzato) -> tidy (promozione, DCE, "roll" di regioni ripetute)
 -> verify (verificatore completo SEMPRE attivo, anche in release) -> serialize (SPIR-V 1.5, rilocazioni tipizzate)
 = CompiledFunction (cache-abile per FunctionCompileKey)
 -> link (set/binding, Location, SpecId, pipeline layout) -> relocate
 = ComputePipeline | RenderPipeline | tile/mesh pipeline
BindState -> shape -> BindingPlan (per pipeline x shape) -> instantiate -> descriptor write + push constant per comando
```

Principi rilevanti per un driver di sistema:
- **Rifiuti tipizzati** (`Error::Unsupported{Feature, Needs}`, `NeedsInput`, `LimitExceeded`), mai un modulo che calcola altro (`README.md`). Per WindowServer serve però una politica di *fallback* (pipeline no-op/magenta come Cobalt64, `05 §6.3`) per non far abortire il processo.
- **Profilo device** da JSON Khronos Profiles o da `ash` (`DeviceDescription::query`): ogni scelta (tier subgroup, larghezze storage, robustness, spazio push constant, "driver deviation" misurate) dipende dal profilo, e la sua impronta entra in ogni chiave di cache. Il nostro profilo RADV gfx1200 esiste già: `scratchpad/metal-xlate/vkprofile_gpu0.json` (generato da `vulkaninfo --json` nel run precedente, "AMD Radeon RX 9060 XT (RADV GFX1200)", Mesa 26.3.0-devel git-8ea6e9dd41). Nella cartella profili di validazione c'è `amd-rdna3-radv.json` ma **nessun profilo RDNA4** (`M2V/crates/metal2vulkan-validation/profiles/`).
- **Lavoro limitato**: ogni compile ha deadline, token di cancellazione, cap deterministici (`Budget`); per isolamento da crash si consiglia la compilazione in un processo figlio (`docs/HOWTO.md` §5). Cobalt64 fa la stessa cosa con il daemon `com.navi48.translate` per WindowServer (`05 §6.3`).

### 3.3 Modello di binding generato [VERIFICATO, `docs/API.md:355-420`]

- Set 0: tutti gli slot Metal staticamente usati (buffer/texture/sampler per stadio), numerati densamente in ordine `ResourceSlot`.
- Set 1: **array heap** per le risorse raggiunte via argument buffer e `MTLResourceID`.
- Push constant: valori che il binder scrive per comando (es. classe di formato delle texture, offset).
- *Variant*: un piano può chiedere un'altra variante di pipeline (formato di una storage texture, range buffer oltre il limite del descrittore, vertex buffer non fetchabile dal fixed-function). Il consumer compila la variante e memoizza su `(PipelineKey, BindShape)`.
- Questo è più generale dello schema fisso di NullMoth (`NVMTL_NBUF=32`, `NVMTL_NTEX=128`, `NVMTL_NSAMP=32`, binding 480/640, `nvmtl_vk.c:1774-1787`) e delle firme di descriptor set di Cobalt64 (render = set 1, compute = set 0, `05 §6.3`).

### 3.4 Copertura API (`docs/METAL-COVERAGE.md`, generata da `scripts/metal-coverage/coverage.tsv` contro l'SDK macOS 27.0) [VERIFICATO]

| Stato | Voci | di cui deprecate |
|---|---|---|
| implementate | 957 (634 runtime, 323 valori del traduttore) | 36 |
| mancanti | 829 (S 145, M 148, L 160, XL 376) | 27 |
| fuori scope | 349 (ray tracing API, multi-GPU, servizi solo macOS, **IOSurface, drawable, compilazione da sorgente**) | 5 |

Mancanti in ordine di costruzione (`METAL-COVERAGE.md:20-65`), le più rilevanti per noi: label/debug group (S), `MTLCommandBufferDescriptor` / `retainedReferences` / `enqueue` (S/M), `MTLCommandQueueDescriptor` (S), `newLibraryWithFile:`/`URL:` (S), `textureBarrier` (S/M), reflection dopo la creazione pipeline (S), **parallel render encoding** (M, 9 voci), `lodBias` sampler (M), depth bounds (M), **counter sample buffer** (M, 54), **residency set** (M, 25), shader logging (M), GPU capture (S), function stitching (L, 24), `MTLIOCommandQueue` (L, 44), tensor (L, 68), **modello di comando Metal 4** (L/XL, 369 voci), ML encoder (XL).
Già implementate e importanti: `gpuAddress` (`:1086`), `useResource:`/`useHeap:` (`:1243-1246`, `:2114-2120`), `argumentBuffersSupport`, `newArgumentEncoder*`, `newIndirectCommandBuffer...` (`:1451`), `newSharedEvent` / `newSharedEventWithHandle:` (**solo in-process**, `:1454`), sparse tile size (`:1463-1468`), `newBufferWithBytesNoCopy:` (`:1408`). Fuori scope: `newTextureWithDescriptor:iosurface:plane:` (`:1411`, "IOSurface is the consumer's; the runtime offers the plane over a no-copy buffer") e `supportsRaytracing` = NO (`:1482`).

### 3.5 Copertura per famiglia di feature (traduttore) [VERIFICATO su `docs/REFUSALS.md` + moduli `lower/*`]

| Feature Metal | Stato in metal2vulkan 0.2 | Meccanismo Vulkan / requisito | Su RADV gfx1200 (profilo misurato) |
|---|---|---|---|
| Tessellation (`[[patch]]`, post-tessellation vertex) | implementata (`lower/tessellation/mod.rs`: la funzione post-tess diventa una TES, lo stadio di controllo è sintetizzato dallo stato pipeline); rifiuti residui `Tessellation` | `tessellationShader`, `maxTessellationGenerationLevel`, push constant | tessellationShader = true |
| Mesh/object shader | implementata (`lower/mesh/mod.rs`: object = `TaskEXT`, mesh = `MeshEXT`, griglia via `OpEmitMeshTasksEXT`) | `VK_EXT_mesh_shader`, limiti `maxMeshOutputLayers`, `maxTaskPayloadSize` | meshShader/taskShader = true, maxTaskPayloadSize 16384, maxMeshOutputVertices/Primitives 256, maxMeshOutputLayers 8 |
| Ray tracing (intersector `air.intersect`) | **traduzione** implementata via `VK_KHR_ray_query` (`lower/raytracing/mod.rs`); intersection function table rifiutate (`IntersectionFunctionTable`); **runtime senza build di acceleration structure** (fuori scope) | ray query + acceleration structure | rayQuery, accelerationStructure, rayTracingPipeline = true; BVH8 gfx12 in RADV (`03 §4.6`) |
| Argument buffer tier 2 | puntatori: implementati via BDA (`ArgumentBufferPointers` solo senza BDA); texture/sampler: heap array (`ArgumentBufferTextures` ai limiti); **pipeline state / ICB / function table / AS dentro argument buffer: rifiutati** (`ArgumentBufferObjects`) | `bufferDeviceAddress`, descriptor indexing, update-after-bind | BDA + captureReplay true; maxPerStageDescriptorUpdateAfterBindSampledImages 8 388 606; `VK_EXT_mutable_descriptor_type`, `VK_EXT_descriptor_buffer`, `VK_EXT_descriptor_heap` presenti |
| Indirect command buffer | runtime implementato (`metal2vulkan-runtime/src/indirect_command_buffer.rs`, replay `bind/replay.rs`); comandi codificati dalla GPU parzialmente rifiutati (`GpuEncodedIndirectCommands`), render state settati da shader rifiutati (`IndirectRenderState`) | BDA, int64; opz. `VK_EXT_device_generated_commands` | DGC presente (non usato dal traduttore) |
| Sparse texture/heap | implementate con residency (`SparseTexture`, `SparseTextures`, `SparseMapping` rifiutati solo in alcune forme) | sparseBinding/sparseResidency* | sparseResidencyBuffer/Image2D/Image3D/Aliased = true, residencyNonResidentStrict = true |
| Atomici | 32 bit ok; 64 bit con feature (`Int64Atomics`); atomici immagine oltre 32 bit interi parziali (`ImageAtomics`) | `shaderBufferInt64Atomics`, `shaderImageInt64Atomics`, atomic float | int64 buffer/shared/image = true; float32 add/minmax = true; **float64 add e float16 atomics = false** |
| simdgroup (32 lane) | tier `Direct`, `Cluster32` (subgroup 64 diviso in cluster da 32), `PartialFragment`, `Emulated` (via LDS) (`device/subgroup.rs:73-88`); **simdgroup_matrix: NON implementata** (`SimdgroupMatrix`, "every device") | `subgroupSizeControl`, `requiredSubgroupSizeStages`, op clustered/quad | minSubgroupSize 32, max 64; pinnable solo **FS, CS, task, mesh** (non VS/TES/GS); CLUSTERED e QUAD supportati in tutti gli stadi |
| half / bfloat | `half` completo con politiche fast/exact (`docs/FAST-PATHS.md:37-41`); bfloat non citato nei rifiuti [INFERITO: segue il supporto `bfloat` di MSL 3.1 come tipo di storage] | `shaderFloat16`, `storageBuffer16BitAccess`; `VK_KHR_shader_bfloat16` | float16/int16/int8 = true; shaderBFloat16Type = true |
| Framebuffer fetch / raster order group | implementati via **fragment shader pixel interlock** quando manca rasterization-order attachment access (`lower/fragment/fetch.rs:1-22`, cita RADV esplicitamente) | `fragmentShaderPixelInterlock` | true; `VK_EXT_rasterization_order_attachment_access` **assente** |
| Tile shading / imageblock | parziale (`TileShading`, `Imageblocks` rifiuti residui) | storage buffer/immagini + interlock | - |
| Rasterization rate map | parziale (rifiuti `RasterizationRateMap`) | - | - |
| Funzioni dinamiche (function pointer) | **rifiutate** (`DynamicCall`); visible function table devirtualizzate se il set è noto | nessun meccanismo Vulkan | - |
| Vertex amplification, layered rendering | con multiview / `shaderOutputLayer` | multiview, ShaderOutputLayer/ViewportIndex | tutte true |
| Formati XR10 Apple (`BGRA10_XR`, `RGB10A8_2P_XR10`) e blend extended-range | emulati (`bind/two_plane_texels.rs`, `extended_shadow`), **blend parzialmente rifiutato** (`ExtendedRangeBlend`, reach=system) | storage image + interlock | - |
| Filtro bicubico (`MTLSamplerMinMagFilterCubic`) | implementato in shader; la forma con mip filter rifiutata (`SamplerBicubicFilter`, reach=system: Tahoe lo crea al boot) | `VK_EXT_filter_cubic` non usato | filter_cubic assente su RADV (non serve) |
| YCbCr / formati CoreVideo 4:2:x, 10 bit | conversioni in shader (`bind/ycbcr_convert.rs`, `ycbcr_write.rs`, `plane_copy`) con rifiuti `Format` dove il device manca | sampler ycbcr opzionale | `G8_B8R8_2PLANE_420`, `G10X6..._2PLANE_420` supportati; **`B8G8R8G8_422`/`G8B8G8R8_422` assenti** (MTL `BGRG422`/`GBGR422` vanno emulati) |

Verifica eseguita (script `scratchpad/metal-xlate/scripts/feat_check.py`, Python isolato): ho estratto da `docs/REFUSALS.md` tutte le feature/estensioni Vulkan nominate come requisito (`VkFeature::*`, `VkExtension::*`) e le ho confrontate con il profilo del RX 9060 XT. **Tutte le 29 feature e le 2 estensioni nominate sono presenti su RADV gfx1200**, tranne 4 nomi che non sono feature RADV: `constantAlphaColorBlendFactors`, `imageView2DOn3DImage`, `multisampleArrayImage` (feature di `VK_KHR_portability_subset`: assenti significa "supportato pienamente" su un driver non-portability) e `rasterizationOrderColorAttachmentAccess` (assente su RADV; aggirata con interlock). **[VERIFICATO]**

### 3.6 Rifiuti con "reach = system" (ciò che WindowServer/CoreAnimation/CoreImage colpiscono davvero) [VERIFICATO, `docs/REFUSALS.md`]

| Variante | Cosa blocca | Perché conta |
|---|---|---|
| `FramebufferFetch` | fetch non ordinato o in pipeline MSAA | *"macOS 26.6.2's login reaches it (two WindowServer and RenderBox pipelines fetch RGB10A8_2P_XR10 attachments)"* |
| `ExtendedRangeBlend` | parti del blend su attachment XR10 non modellate | *"the consumer's guests blend RGB10A8_2P_XR10 attachments"* (desktop EDR/HDR) |
| `SamplerBicubicFilter` | bicubico con mip filter | Tahoe crea un sampler `MTLSamplerMinMagFilterCubic` al boot |
| `Format` | formati che il device non ha per un uso (CoreVideo 4:2:x, 10 bit) | video, anteprime, QuickLook |
| `HostMemory` | `newBufferWithBytesNoCopy:` dove il device non importa la memoria | CoreImage/CoreVideo/IOSurface CPU-backed |
| `Render` (runtime) | 20 siti di render pass/resolve/attachment non costruiti | forme di pass del compositor |
| `FillUnmeasured` (runtime) | fill di texture SPI Apple | software di sistema |

Totali (`REFUSALS.md` "Totals"): traduttore 125 varianti (6 system, 33 app, 68 rare, 18 none), runtime 65 gap (1 system, 6 app, 40 rare, 18 none), Apple-only 9.

### 3.7 Test suite [VERIFICATO, `docs/VALIDATION.md`, `docs/ARCHITECTURE.md` "Checks"]

- **Gate senza GPU**: `cargo fmt`, `clippy -D warnings`, `cargo nextest` su tutti i crate, doctest. Fixture sintetiche proprie (nessuno shader di terzi nel repo).
- **Verificatore interno sempre attivo** + `spirv-val` nei test/CLI; **interprete SPIR-V su CPU** (`spirv::interp`) per verificare lowering compute, OOB e terminazione.
- **Hash golden** dell'output (`src/tests/golden_hashes.rs`) per la stabilità dell'emitter; inventario fixture (`tests/public_fixture_expectations_engine.tsv`) per profilo.
- **Casi "authored" eseguiti su Metal e su Vulkan e confrontati** (crate `metal2vulkan-validation`, `--cfg m2v_gpu` con GPU reale, `--cfg m2v_cpu_icd` con lavapipe/SwiftShader); "driver deviation" misurate per GPU (`device/driver_facts.rs`, es. lane dei simdgroup fragment su MoltenVK M3/M4).
- **Audit su corpus privato** di AIR reale (`corpus-triage`, `corpus/authored-compile.tsv`): misura tempo, memoria e copertura.
- Profili device pronti: RDNA2/RDNA3/780M RADV, ANV, NVIDIA, MoltenVK M3/M4, lavapipe, SwiftShader, Vulkan 1.2 bare (`profiles/`). **Manca RDNA4**: va aggiunto il nostro.
- Mancano invece (da costruire noi): CTS Vulkan su RADV-Darwin, un harness Metal di sistema (lista di app/framework Apple con screenshot/CRC, come i test "zero incorrect pixels" di NullMoth `NVM/docs/CARD-SUPPORT.md:56-66`).

## 4. Superficie API Metal: desktop (WindowServer/CoreAnimation/CoreImage) vs app (WebKit, Chromium, giochi)

### 4.1 Il contratto per "esistere" come device Metal

| Elemento | Dettaglio | Evidenza |
|---|---|---|
| Servizio IOAccelerator nel registry | sottoclasse di `IOGraphicsAccelerator2`, `IOMatchCategory=IOAccelerator`, proprietà `MetalPluginName` (path relativo a `/System/Library/Extensions`, NullMoth usa `../../../Library/GPUBundles/NVMTLDriver`) e `MetalPluginClassName` | [VERIFICATO] `06 §2.3`, `05 §6.1`; messaggi di Metal.framework *"MTLIOAccelDevice bad MetalPluginClassName property (null)"* e *"+[MTLIOAccelDevice registerDevices]: Zero Metal services found"* [WEB: bugzilla.mozilla.org/show_bug.cgi?id=1701080] |
| Classe plugin | sottoclasse di `MTLIOAccelDevice`, `-initWithAcceleratorPort:(mach_port_t)`; la base apre i user client standard della famiglia (shared memory, stamp, resource pool) -> il kext deve implementarli anche se il rendering passa da RADV | [VERIFICATO] `NVM/plugin/NVMTLDevice.m:136-140,364-392`; `COB/.../Navi48Device.m` (classe `Navi48Device : MTLIOAccelDevice`) |
| Tabella limiti | `-featureProfile` (privato) seleziona la tabella dei limiti servita da `-initLimits`; se manca "every table-served limit stays 0 (CoreImage will refuse renders)". Valori usati: NullMoth 10002 (`NVMTLDevice_contract.m:12`), Cobalt64 10000 (copiato da `AppleParavirtDevice`, `Navi48Device.m:6264-6265`); `supportsFeatureSet:` 10000..10005 (`NVMTLDevice.m:1627`) | [VERIFICATO] `NVMTLDevice.m:381-388` |
| Gating | il plugin viene caricato in **ogni** processo che enumera device Metal: serve allow-list per processo (NullMoth `nvmtl-allow.txt`; Cobalt64 kill file + `Navi48,Ready` + ammissione da kernel per le app, `Navi48Device.m:118-133,231-290`) e pubblicare `MetalPluginName` solo quando il display pipe è pronto (altrimenti CoreDisplay "Failed to create MetalDevice" -> crash loop) | [VERIFICATO] `06 §2.3, §5.1`; `05 §6` |
| Sandbox | i processi GPU di Safari/Chromium e le app sandboxate possono aprire user client **solo** su servizi IOAccelerator: il canale RADV->kext deve passare dall'acceleratore (NullMoth `newUserClient` con tipo 'NV', Cobalt64 "G6") e la traduzione shader deve funzionare in-process senza scrivere file arbitrari né lanciare processi | [VERIFICATO] `06 §2.4`; `Navi48Device.m:513`; `COB/third-party/metal2vulkan-n48/n48xlate/src/lib.rs:7-10` |
| SPI non implementate | un selettore privato mancante = `doesNotRecognizeSelector` = crash di WindowServer: NullMoth inoltra con firme prese dalle classi Apple (`NVMTLForward.m`), Cobalt64 fa un *census* dei metodi di protocollo mancanti a `+load` (`n48_census.h`). Entrambi indispensabili in sviluppo | [VERIFICATO] |

### 4.2 Cosa usano WindowServer / SkyLight / CoreDisplay / QuartzCore (desktop minimo) [VERIFICATO dalle note di Cobalt64 e NullMoth salvo dove indicato]

| Area | API / comportamento | Fonte |
|---|---|---|
| Superfici | `newTextureWithDescriptor:iosurface:plane:` (drawable, backing store dei layer, superfici display) anche **multi-plane** e con descrittore più piccolo della superficie (CoreImage chiede 308x514 su 320x576) | `n48_plane.h:1-10`; `NVMTLDevice.m:724-747` |
| Superfici display | CoreDisplay "GPUPass" rende in **3 IOSurface** display per WindowServer (`DisplaySurface::GetMTLTexture`), poi presenta via display pipe; `RunFullDisplayPipe` usa una texture **R32Float 16384x1** come LUT gamma | `Navi48Device.m:1026-1030,1251-1291,2228-2230` |
| Mai nil | SkyLight abortisce su texture nil (`AbortWithTexture...`), CoreDisplay non sopravvive a un nil da `GetMTLTexture`: anche per IOSurface protette/senza mapping CPU bisogna restituire una texture (immagine device-local) | `Navi48Device.m:2630-2636` |
| Heap | il MetalCompositor di SkyLight crea **MPSDevice** -> `newHeapWithDescriptor:` (size, storage, cpuCacheMode, resourceOptions, protectionOptions), poi `setPurgeableState:3`, `size` | `Navi48Device.m:3055-3058` |
| Stato | `newDepthStencilStateWithDescriptor:` (SkyLight e QuartzCore uno ciascuno), render pass solo colore | `Navi48Device.m:3234-3240` |
| Risorse (SPI) | `-virtualAddress`, `-contents`, `-didModifyRange:`, `rootResource`, `isShareable`, `newSharedTextureHandle`, `remoteStorageTexture`, `swizzle`, `isCompressed`, `setPurgeableState:`, `allocatedSize`, `protectionOptions`, `setResponsibleProcess:` | `Navi48Device.m:2194-2200,2984-2992`; `NVMTLObjects.m:975-976` |
| Buffer | `newBufferWithBytesNoCopy:` su memoria client (backing store "client memory" di QuartzCore -> texture lineari su buffer) | `Navi48Device.m:2791`; `NVMTLDevice_contract.m:16-30` |
| Formati | BGRA8/RGBA8 (+sRGB), RGB10A2/BGR10A2, RGBA16F, R16F/RG16F, R32F/RG32F, R16/RG16/RGBA16 Unorm (tabella m11h3), **formati XR10 / `RGB10A8_2P_XR10`** con blend extended-range e **framebuffer fetch** (login di Tahoe 26.6.2) | `Navi48Device.m:2228-2240`; `M2V/docs/REFUSALS.md` (`FramebufferFetch`, `ExtendedRangeBlend`) |
| Sampler | sampler bicubico (`MTLSamplerMinMagFilterCubic`) creato al boot di Tahoe | `REFUSALS.md` `SamplerBicubicFilter` |
| Sincronizzazione | `commitAndWaitUntilSubmitted` seguito subito dallo swap del display pipe: in WindowServer bisogna attendere il **completamento** GPU (o ordinare il flip dopo la fence nel kernel), altrimenti flicker | `NVM/docs/CARD-SUPPORT.md:36-47`; `NVMTLObjects.m:4567` |
| Eventi | `MTLSharedEvent`/`MTLEvent` (Cobalt64 usa la `_MTLSharedEvent` CPU-side generica di Metal, granularità command buffer) | `Navi48Device.m:4805-4815` |
| Pipeline | poche decine di pipeline note (Cobalt64 le ha precompilate in `spvcache` + traduzione asincrona con pipeline di fallback e hot-swap) | `05 §6.3` |
| Famiglie | Cobalt64 dichiara `Metal3` **solo** a WindowServer (che altrimenti cambia percorso), Mac2 + Common1..3 a tutti | `Navi48Device.m:6270-6284` |

### 4.3 CoreImage, MPS, CoreVideo/VideoToolbox (servono subito dopo: Anteprima, Foto, QuickLook, sfondi, Control Center)

- **CoreImage**: compila i filtri in kernel AIR `air.ci` (`M2V/crates/metal2vulkan-air/src/abi/core_image.rs`), linka librerie con `newLibraryWithCIFilters:imageFilterFunctionInfo:error:` / `newLibraryWithImageFilterFunctionsSPI:` (`NVMTLDevice.m:1028-1031`), riflette i kernel CIKL stringa via `-[_MTLDevice compiler]`: se nil, `CIKernelReflection::consolidate` va in fault (Anteprima "Regola colore"); Cobalt64 forza `CI_USE_MTL_DAG_FOR_CIKL_SRC=0` (`n48_cienv.h:11-12`, `Navi48Device.m:1928-1934`). Usa function constants, texture su IOSurface multi-plane e `newBufferWithBytesNoCopy:`.
- **MPS** (MetalPerformanceShaders): usato dallo stesso compositor (heap) e da sfocature/blur; NullMoth lo valida con "Five MPS Gaussian blur runs" (`CARD-SUPPORT.md:62`). MPS usa kernel precompilati nel framework (metallib di sistema) -> passano dal traduttore come qualsiasi metallib.
- **CoreVideo/VideoToolbox**: superfici YCbCr 4:2:0 8/10 bit biplanari, 4:2:2 (`BGRG422`/`GBGR422`, non supportati nativamente da gfx12: emulare in shader), formati 10 bit; senza decoder HW (VCN 5.0) VideoToolbox decodifica su CPU e consegna IOSurface al compositor. Un video 1080p in Safari crea IOSurface di continuo: la politica di use-count sbagliata faceva importare a WindowServer ogni superficie (`n48_ledger.h` (B)).

### 4.4 Cosa serve alle app

| Client | Uso di Metal | Requisiti chiave per noi |
|---|---|---|
| **Safari / WebKit** (processo GPU) | compositing via CoreAnimation/IOSurface; WebGL tramite ANGLE con backend Metal (MSL generato a runtime -> `newLibraryWithSource:`); WebGPU in `WebGPU.framework`: WGSL -> MSL a runtime, inizialmente **solo argument buffer tier 2**, tier 1 aggiunto a gennaio 2023 [WEB: bugs.webkit.org/show_bug.cgi?id=250123]; media via VideoToolbox | compilazione MSL->AIR a runtime (MTLCompilerService tramite `[super newLibraryWithSource:]` come NullMoth, `06 §5.3`); traduzione **in-process** nel sandbox; `MTLSharedEvent` (sincronizzazione GPU process <-> WebContent [INFERITO]); IOSurface condivise tra processi |
| **Chromium / Chrome / Edge / Electron** | GL via ANGLE-Metal (compositor Skia Ganesh) o Skia Graphite Metal (che verifica `supportsFamily:` fino a `MTLGPUFamilyMac2` e `isDepth24Stencil8PixelFormatSupported`) [WEB: skia.googlesource.com .../graphite/mtl/MtlCaps.mm]; WebGPU via Dawn (WGSL->MSL, `newLibraryWithSource:`); presentazione con CALayer/IOSurface | `MTLGPUFamilyMac2` = YES obbligatorio; risposte coerenti su D24S8 (su gfx12 **non** supportato: `VK_FORMAT_D24_UNORM_S8_UINT` ha 0 feature nel profilo -> rispondere NO, NullMoth risponde YES su NVIDIA); MSL runtime; nota di contesto: con AMFI rilassato (necessario per caricare un bundle firmato ad-hoc) Firefox e altre app crashavano all'avvio finché NullMoth non ha aggiunto il boot-arg `ipc_control_port_options=0` (`NVM/docs/RELEASE-1.11.0.md:7`, `NVM/docs/HOW-IT-WORKS.md:78`) |
| **Firefox** | WebRender su OpenGL (-> GL-su-Metal di Apple) o software; WebGPU (wgpu-hal Metal) | `IOGLBundleName=AppleMetalOpenGLRenderer` (`06 §5.4`) |
| **App OpenGL legacy** | Apple GL-on-Metal (`AppleMetalOpenGLRenderer`) | il plugin deve servire la reflection extra che il renderer GL richiede (`NVM/plugin/NVMTLGL.m`) |
| **OpenCL** (Geekbench, app vecchie) | su questi sistemi Apple implementa OpenCL sopra Metal (NullMoth: Geekbench OpenCL funziona, `06 §5.4`) [INFERITO per AMD x86] | kernel compute + `MTLBinding access` |
| **Giochi Metal 3** (porting, Game Porting Toolkit/CrossOver lato D3D->Metal) | argument buffer tier 2 / bindless, `gpuAddress`, `gpuResourceID`, `useResource/useHeap`, ICB, heap placement, function constants, mesh shader, ray tracing opzionale, MetalFX [INFERITO] | Metal 3 completo: è il gap principale di Cobalt64 (Tier1 alle app) |
| **Blender, DaVinci, Final Cut, Pixelmator** | compute pesante, argument buffer, function constants, heap, ray tracing (Cycles), MPS; NullMoth: "Blender 4.2 starts", "Geekbench" | qualità del traduttore + prestazioni compilazione (cache su disco) |

### 4.5 Sintesi: matrice minima per tappe

| Tappa | Deve funzionare | Può mancare |
|---|---|---|
| T0 "device esiste" | registry + plugin + `initWithAcceleratorPort:` + `featureProfile/initLimits` + census/forwarding SPI | tutto il resto (rifiuta i processi non ammessi) |
| T1 WindowServer | IOSurface->texture (anche multi-plane), render pass solo colore con blend, **framebuffer fetch + formati XR10** (login Tahoe), heap MPS, depth/stencil state, sampler (anche bicubico), blit/copy/fill, compute semplice, `commit`/`waitUntilCompleted`/completion handler, presentazione su display pipe con ordinamento rispetto alla fence | argument buffer, ICB, tessellation, mesh, RT, MSAA complesso |
| T2 CoreImage/QuickLook/Foto | kernel `air.ci`, function constants, YCbCr, `newBufferWithBytesNoCopy:`, `newLibraryWithSource:` (via MTLCompilerService) | Metal 3 |
| T3 Browser | traduzione in-process nel sandbox, MSL runtime, `MTLSharedEvent`, argument buffer tier 1 (WebKit WebGPU), tier 2 consigliato, IOSurface cross-process | RT, mesh |
| T4 Metal 3 per app | argument buffer tier 2, `gpuAddress`/`gpuResourceID`, `useResource/useHeap`, residency set, ICB, placement heap, sparse, MSAA, query/counter, `MTLGPUFamilyMetal3` | ray tracing, Metal 4 |
| T5 Avanzato | ray tracing (`VK_KHR_ray_query` + build AS), mesh shader, simdgroup_matrix (cooperative matrix), Metal 4 | - |

## 5. Implementazioni di riferimento di MTLDevice su Vulkan: NullMoth, Cobalt64, metal2vulkan-runtime

Tre implementazioni dello stesso strato "API Metal -> Vulkan", con maturità e licenze diverse. I dettagli dei primi due sono in `05 §6` e `06 §5`; qui il confronto per aspetto.

### 5.1 Quadro generale [VERIFICATO]

| | NullMoth `NVMTLDriver.bundle` | Cobalt64 `Navi48Metal.bundle` | `metal2vulkan-runtime` 0.2 |
|---|---|---|---|
| Dimensione | ~24,5 K righe (`plugin/*.m,*.c,*.h`) + wrapper Rust 2,1 K | ~10,1 K righe (`Navi48Device.m` 6 293 + header puri; test esclusi) | ~211 K righe Rust (con test) |
| Licenza | **PolyForm Noncommercial** (non riusabile in un progetto open, solo come riferimento) | MIT (bundle), LGPL per `n48xlate` | GPL-2.0+ OR LGPL-3.0+ |
| Classe device | `NVMTLDevice : MTLIOAccelDevice` | `Navi48Device : MTLIOAccelDevice` | `Device` Rust (nessuna integrazione ObjC: va avvolto) |
| Oggetti | `NSObject` conformi ai protocolli `MTL*` + forwarding SPI (`NVMTLForward.m`) | sottoclassi delle classi private `_MTLResource`, `_MTLCommandBuffer`, `_MTLCommandEncoder`, `_MTLHeap` + census | tipi Rust con nomi Metal (`Buffer`, `CommandQueue`...) |
| Librerie/funzioni | parsing proprio del metallib ("MTLB"), MSL via `[super newLibraryWithSource:]` + `libraryDataContents` | librerie e funzioni **di Apple** (`MTLIOAccelDevice`), bitcode letto con la SPI `-[MTLFunction bitcodeData]` alla creazione pipeline (`Navi48Device.m:1994-2004,3402-3410`) | `new_library_with_data` (metallib), nessun compilatore MSL |
| Traduttore | metal2vulkan 0.1 + pass NullMoth, in-process, cache SPIR-V LRU | metal2vulkan 0.1 patchato: daemon per WindowServer, `libn48xlate` in-process per le app, cache `spvcache` per hash | metal2vulkan 0.2 integrato, cache su disco per utente |
| Coda Vulkan | 1 coda GRAPHICS\|COMPUTE, coda seriale `nvmtl.execution`, fence per CB | 1 coda (`N48R.q`), fence per CB, thread di completamento (`Navi48Device.m:4354,4505-4550`) | scheduler per device, batch separati dagli eventi, thread di completamento, più famiglie di code se presenti (`command_buffer/mod.rs`, `sharing.rs`) |
| Render pass | `vkCmdBeginRenderPass` legacy (`nvmtl_vk.c:4367`) | `vkCmdBeginRenderPass` + cache render pass | piano per pass, stand-in per attachment, resolve propri |
| Hazard tracking | barriere **globali grossolane** (`ALL_COMMANDS`, `nvmtl_vk.c:2352-2356,4931-4944`) | barriere globali (`Navi48Device.m:2428`) | **tracking automatico di Metal** come funzioni pure (`tracker.rs`): barriere per encoder/dispatch seriale/concorrente |
| Eventi | `MTLEvent`/`MTLSharedEvent` user space (`NSCondition`), non cross-process | `_MTLSharedEvent` generico di Metal, attesa a livello di submission | **timeline semaphore** per evento, mapping valori Metal (`event.rs`, `event_timeline.rs`); shared event handle solo in-process |
| Residency/heaps | heap con alias e heap placement (`NVMTLDevice.m:1631-1645`); **residency in user space**: purge e LRU page-off/on delle texture sotto pressione VRAM (`NVMTLObjects.m:217-400`) | heap = oggetto budget con allocatore first-fit, nessuna memoria propria (`n48_heapalloc.h`, `Navi48Device.m:3055-3060`) | `use_resource/use_heap` -> resident set del bind state (`residency.rs`); residency set mancanti (M) |
| Storage mode | Shared -> VRAM CPU-visibile (BAR1) se c'è budget, altrimenti sysmem (`nvmtl_vk.c:940-950`); Private -> DEVICE_LOCAL; Managed -> shadow + `didModifyRange` (`NVMTLObjects.m:592-669,842`) | opzioni salvate (`_opts`), MSAA solo Private (`Navi48Device.m:2446-2472`) | contratto Managed/unified memory (`managed.rs`), NoCopy via external_memory_host (`host_memory.rs`) |
| IOSurface | **zero-copy in VRAM** tramite hook NVK `nvmtl_nvk_stage_import` + condivisione handle RM da `deviceCacheForIOSurface` (`06 §2.5, §5.4`); fallback immagine privata + copie sincronizzate col seed | **import della memoria di sistema** dell'IOSurface (`IOSurfaceGetBaseAddress` + `VK_EXT_external_memory_host` -> userptr nel kext, patch Mesa `0004-darwin-host-pointer-import-userptr...`), "path (a)" lineare o "path (b)" immagine ottimale + copie, cache import/alias (`n48_impcache.h`, `n48_ioalias.h`) | fuori scope: il consumer offre il piano su un buffer no-copy (`Buffer::new_texture_with_iosurface_plane`) |
| Presentazione desktop | display pipe transaction -> flip NVKMS zero-copy sulla VRAM della surface, o copia CPU; WindowServer attende il completamento GPU | "D-copy": a fine CB che scrive una delle 3 superfici CoreDisplay, copia GPU nell'una di 3 slot in VRAM visibile + flip HUBP latched a VUPDATE via `radv_darwin_scanout_*` (`Navi48Device.m:1026-1060`, `n48_dispflip.h`) | n/a |
| Feature dichiarate | `supportsFamily`: Mac1, Mac2, Common1-3, **Metal3** (`NVMTLDevice.m:1618-1625`); `argumentBuffersSupport` **Tier2** (`:1617`); `readWriteTextureSupport` Tier2 (`:1734`); `supportsRaytracing` = disponibilità RT in NVK (`:1540`); function pointer e dynamic library YES (`:1412-1415`); raster order group NO (`:1736`); BC YES; D24S8 YES (`NVMTLDevice_contract.m:15`); `featureProfile` 10002 | Mac2 + Common1-3 a tutti, **Metal3 solo a WindowServer**, `argumentBuffersSupport` Tier1 alle app (base class per WS) (`Navi48Device.m:6270-6284`); `maxBufferLength` 4 GiB, `recommendedMaxWorkingSetSize` 12 GiB (`:5948-5949`); `hasUnifiedMemory` NO; `featureProfile` 10000; `llvmVersion` 0x7d17 | `supports_family` con audit per famiglia (`families/`), `argument_buffers_support` dal profilo; ray tracing NO |
| Non implementato | (quasi completo; RT via NVK) | ICB, argument encoder, RT, mesh, rate map, counter sample buffer, binary archive, tile shader (`05 §6.2`) | vedi §3.4 (829 voci mancanti, RT API, IOSurface) |

### 5.2 Mappatura risorse raccomandata per RADV gfx1200 [INFERITO, basato sulle tre implementazioni + hardware]

- **Memoria**: con Resizable BAR attivo (BAR0 = 16 GB, tutta la VRAM CPU-visibile) RADV espone un tipo `DEVICE_LOCAL|HOST_VISIBLE|HOST_COHERENT` grande quanto la VRAM. Quindi: `Private` -> `DEVICE_LOCAL`; `Shared` -> VRAM visibile (write-combined) per buffer piccoli/streaming e **GTT cached** (`HOST_VISIBLE|HOST_CACHED`) per buffer letti dalla CPU (readback); `Managed` -> VRAM + shadow in sysmem come NullMoth, oppure direttamente VRAM visibile con `didModifyRange` no-op (Metal permette entrambe) ; `Memoryless` -> immagine transiente (`VK_MEMORY_PROPERTY_LAZILY_ALLOCATED` non esiste su dGPU: allocare normalmente).
  Attenzione: il kext deve gestire il **budget** (Cobalt64 riporta il budget VRAM per sessione, patch Mesa `0006-radv-darwin-report-the-kext-s-per-session-VRAM-budge.patch`) e in mancanza di eviction (TTM) una residency in user space come NullMoth, oppure implementare eviction nel kext. Con 16 GB su Navi 44 si può partire senza eviction (Cobalt64 dichiara 12 GiB di working set).
- **gpuAddress** = `vkGetBufferDeviceAddress` (VA reale nel VM del processo; RADV usa VA a 48 bit con il VM a 4 livelli di GMC 12). **gpuResourceID** = indice in un descriptor heap per device (`VK_EXT_descriptor_heap`/`descriptor_buffer`/`mutable_descriptor_type` tutti presenti su RADV gfx1200, §7).
- **Texture**: `MTLTextureType` -> `VkImageType`/`VkImageViewType` (Cobalt64 `n48_texdesc.h`); swizzle Metal -> `VkComponentMapping`; texture su buffer (linear) -> `VkImage` con memoria alias del buffer quando il pitch lo permette (gfx12 linear: pitch di default 128 B, forzato a 256 B per superfici 2D a un livello non MSAA, `MESA/src/amd/common/ac_surface.c:3969-3975` e `LINEAR_PITCH_ALIGNMENT 256` a `:1238` [VERIFICATO]; `minimumLinearTextureAlignmentForPixelFormat` e la validazione delle IOSurface (bytesPerRow) devono riflettere il vincolo, NullMoth richiede pitch multiplo di 32 su NVIDIA).
- **Formati**: D24S8 non supportato da gfx12 -> `isDepth24Stencil8PixelFormatSupported = NO` e mappare `Depth24Unorm_Stencil8` solo se l'app lo usa malgrado il NO (Metal su Apple silicon fa lo stesso); ASTC/ETC2 assenti (coerente con la famiglia Mac2: solo BC); 4:2:2 Apple da emulare.
- **Sincronizzazione**: un `MTLCommandQueue` -> una sequenza ordinata su un `VkQueue` (gfx) con timeline semaphore per CB; `MTLEvent`/`MTLSharedEvent` -> timeline semaphore (metal2vulkan-runtime) e, per lo **shared event cross-process** (WebKit, AVFoundation), un oggetto kernel: un syncobj timeline del kext esportabile come porta Mach (estensione rispetto alle due implementazioni esistenti, che sono solo in-process).
- **Hazard tracking**: adottare il tracker preciso (metal2vulkan) invece delle barriere globali: su RDNA4 una barriera `ALL_COMMANDS` svuota tutta la pipeline (wait-idle CP + flush/invalidate cache GL2/K$) a ogni encoder, costo misurabile su WindowServer che fa molti pass piccoli.

## 6. IOSurface e percorso di presentazione

### 6.1 Dall'app allo schermo [VERIFICATO dove citato, resto INFERITO]

```
App: CAMetalLayer.nextDrawable
  -> CoreAnimation alloca un pool (tipicamente 3) di IOSurface e le avvolge con
     -[MTLDevice newTextureWithDescriptor:iosurface:plane:]            [VERIFICATO: NVMTLDevice.m:724-747]
  -> l'app codifica e chiama [commandBuffer presentDrawable:]
     (NullMoth: blocco [drawable present] eseguito DOPO il completamento, NVMTLObjects.m:4535-4557)
  -> [drawable present]: CA consegna l'IOSurface (per ID / Mach port) al render server
WindowServer (render server CoreAnimation + SkyLight + CoreDisplay, stesso processo)
  -> importa ogni IOSurface dei layer come MTLTexture (stesso selettore), compone con Metal
     (MetalCompositor di SkyLight, MPS, pipeline di RenderBox) in una delle 3 "display surface" di CoreDisplay
     [VERIFICATO: Navi48Device.m:1026-1030, 1251-1291, 3055-3058]
  -> CoreDisplay "RunFullDisplayPipe": pass finale (LUT gamma R32Float 16384x1, eventuale EDR/XR10)
  -> commitAndWaitUntilSubmitted, poi transazione sul display pipe: IOAccelDisplayPipe::performTransaction
     con getPlaneIOSurface(0,0)/getPlaneResource(0,0)                    [VERIFICATO: 06 §2.6, nvrm-accel.cpp:830-919]
Kext: flip dello scanout sulla superficie (o copia in un buffer di scanout), completamento con signalTransactionInterrupt
  -> DCN 4.0.1: HUBP surface address update latched a VUPDATE         [VERIFICATO: Cobalt64 n48_dispflip.h; 02/05 §7.4]
```

Prerequisito nel registry: `IOAccelDisplayPipeCapabilities = {DisplayPipeSupported: true, TransactionsSupported: true}` sull'acceleratore (NullMoth lo pubblica via sysctl `debug.nvaccel_iop=1`, `06 §2.3`) e un `IOFramebuffer` per ogni head (Cobalt64 `Navi48Framebuffer`, NullMoth `NVRMFB`).

### 6.2 Dove vive la memoria di un'IOSurface: tre modelli

| Modello | Chi lo usa | Come | Pro | Contro |
|---|---|---|---|---|
| (A) **Memoria di sistema importata** | Cobalt64 | IOSurface allocata da IOSurface.kext in RAM; il bundle prende `IOSurfaceGetBaseAddress` e la importa con `VK_EXT_external_memory_host` -> RADV `ac_drm_create_bo_from_user_mem` -> selettore kext `BoImportHost` (userptr, pin delle pagine + mapping nel VM GPU) (`COB/mesa-patches/0004-darwin-host-pointer-import-userptr-via-N48N-BoImport.patch`; `Navi48Device.m:334-342,610-616`) | semplice, nessun hook nella famiglia IOAccelerator, `IOSurfaceLock`/accesso CPU coerente gratis, condivisione cross-process gratis | GPU legge/scrive su PCIe; per lo scanout serve una **copia** in VRAM a ogni frame ("D-copy", 3 slot in VRAM visibile, `Navi48Device.m:1026-1060,1492-1560`); un import per IOSurface (budget di import del kext, cache `n48_impcache.h`); superfici protette senza mapping CPU -> immagine privata (`Navi48Device.m:2635`) |
| (B) **VRAM tramite la famiglia IOAccelerator** | NullMoth | `IOSurfaceRoot::lookupSurface` -> `IOGraphicsAccelerator2::deviceCacheForIOSurface(surface, plane)` -> risorsa del vendor (`NVResource`/`NVVidMemory` in VRAM) -> handle condiviso col client del processo, import in NVK via hook `nvmtl_nvk_stage_import{surfaceID, plane, size}` (`06 §2.5, §5.4`) | zero-copy end-to-end, **flip diretto** della superficie composta (nessuna copia per frame) | dipende da simboli C++ e layout privati di IOAcceleratorFamily2 (fragile tra versioni macOS), accesso CPU via BAR (lento in lettura), servono IOSurface con pitch compatibile (NullMoth: single-plane, pitch multiplo di 32) |
| (C) Immagine privata + copie sincronizzate | fallback di entrambi | `VkImage` ottimale propria, upload/writeback sincronizzati al seed dell'IOSurface (`NVMTLObjects.m:1020-1075`; "path (b)" Cobalt64 con modello di alias per CB, `n48_ioalias.h`) | funziona per qualsiasi formato/pitch | costo di copia, problemi di coerenza (CoreImage avvolge la stessa IOSurface in molti oggetti texture: "Preview: the image disappears", `n48_ioalias.h:3-14`) |

Specificità RX 9060 XT / Navi 44: Resizable BAR attivo (BAR0 = 16 GB) rende **tutta** la VRAM mappabile dalla CPU, quindi il modello (B) non ha il limite di aperture tipico dei 256 MB; resta il costo di lettura CPU da memoria write-combined. Il DCN 4.0.1 su dGPU va trattato come "scanout solo da VRAM" (su Linux `amdgpu_display_supported_domains()` aggiunge GTT solo se `mode_info.gpu_vm_support`, che `amdgpu_dm.c:528-548` abilita ("S/G display") solo con `AMD_IS_APU`: per una dGPU come Navi 44 lo scanout è sempre in VRAM, `amdgpu_display.c:557-578` [VERIFICATO]), quindi con (A) la copia per frame è inevitabile.

### 6.3 Sincronizzazione delle superfici tra processi

- macOS non ha la implicit sync stile `dma_resv` di Linux. Nel modello Apple l'IOAccelerator del kernel traccia l'uso GPU per risorsa (stamp) e ordina le submission tra code/processi [INFERITO]; i driver di terze parti finora **non** lo replicano: NullMoth presenta dopo il completamento e in WindowServer attende il completamento prima dello swap (`CARD-SUPPORT.md:36-47`), Cobalt64 presenta lo slot nel completion block e incrementa lo use-count dell'IOSurface solo mentre un CB che la tocca è in volo (`n48_ledger.h` (B), misurato: Metal di Apple non tocca lo use-count).
- Raccomandazione [INFERITO]: (1) tappa iniziale come NullMoth (present dopo completion, WindowServer sincrono); (2) poi **fence per BO nel kext** (equivalente di `dma_resv`: ogni CS registra la fence sui BO scritti; l'import di un BO da un altro processo e il flip del display pipe attendono quelle fence lato kernel). È anche ciò che serve per ordinare il flip dopo la fence senza bloccare WindowServer.
- `MTLSharedEvent` cross-process (WebKit GPU/WebContent, AVFoundation): serve un oggetto kernel condivisibile (syncobj timeline esportato come porta Mach); nessuna delle tre implementazioni lo ha (NullMoth `NSCondition`, Cobalt64 `_MTLSharedEvent` CPU, metal2vulkan "in process only").

### 6.4 Formati di scanout e compressione

- Cobalt64 supporta solo scanout lineare `ARGB8888` senza DCC (`n48_scanabi.h:5,10`). WindowServer usa anche superfici 10 bit e XR10/EDR; per i primi passi forzare un profilo colore SDR 8 bit.
- DCC su gfx12 è decisa dalla page table ("compressione trasparente", `03 §4.3`): una superficie compressa scritta da RADV può essere letta da HUBP solo se DCN è configurato per decomprimere; nella prima fase allocare display surface e IOSurface importate **non compresse**.
- Hardware Navi 44 vs Navi 48: stessi blocchi DCN (basi segmento DMU identiche, `05 §7.4`), ma topologia connettori diversa (DP->UNIPHY_A, HDMI->UNIPHY_B, HDMI->UNIPHY_C sulla nostra Sapphire): il mapping head->OTG/HUBP del display pipe va derivato dal VBIOS.

## 7. Gap analysis RADV gfx12 (GC 12.0.0, Navi 44) per Metal 3

Dati: profilo Vulkan misurato su questa macchina (`scratchpad/metal-xlate/vkprofile_gpu0.json`, "AMD Radeon RX 9060 XT (RADV GFX1200)", Mesa 26.3.0-devel git-8ea6e9dd41, 247 estensioni, Vulkan 1.4.363) e sorgenti Mesa main (`MESA/src/amd/vulkan/radv_physical_device.c`). Tutti i valori della colonna "RADV gfx1200" sono **[VERIFICATO]** sul profilo. **Navi 44 vs Navi 48**: RADV non ha codice specifico per i due chip (stesso `gfx_level` GFX12, `03 §4.1`); differiscono solo i numeri (32 CU vs 64, 8 vs 16 RB, 128-bit vs 256-bit, 16 GB), quindi questa analisi vale per entrambi.

### 7.1 Tabella feature Metal 3 -> Vulkan -> RADV gfx1200

| Feature Metal | Meccanismo Vulkan | RADV gfx1200 | Gap / azione |
|---|---|---|---|
| Argument buffer tier 2 / bindless (`gpuAddress`, `gpuResourceID`) | BDA + descriptor indexing (+ mutable / descriptor buffer / descriptor heap) | `bufferDeviceAddress`, `bufferDeviceAddressCaptureReplay`, `runtimeDescriptorArray`, `descriptorBindingPartiallyBound`, `descriptorBindingVariableDescriptorCount`, non-uniform indexing = true; update-after-bind sampled image/sampler/storage buffer per stage = 8 388 606; `VK_EXT_mutable_descriptor_type`, `VK_EXT_descriptor_buffer`, **`VK_EXT_descriptor_heap`** (heap risorse/sampler senza limite, descrittore immagine 32 B, buffer 16 B, sampler 16 B, allineamento 4) | nessun gap hardware/driver. Lavoro: allocatore di heap descrittori per device + mapping `MTLResourceID` -> indice; residency (`useResource`) nel bind state |
| 64-bit atomics (`atomic_ulong` min/max, Metal 3.1) | `VK_KHR_shader_atomic_int64`, `VK_EXT_shader_image_atomic_int64` | buffer/shared/image/sparse image int64 atomics = true | nessuno |
| Atomici float (`atomic_float` add) | `VK_EXT_shader_atomic_float(2)` | buffer/shared/image float32 add = true, float32 min/max = true; float64 add = false, float16 atomics = false | Metal non ha `double` né atomici half: nessun gap |
| simdgroup a 32 lane | `VK_EXT_subgroup_size_control` (`requiredSubgroupSize = 32`), `computeFullSubgroups` | minSubgroupSize 32, maxSubgroupSize 64, `subgroupSize` API 64; `requiredSubgroupSizeStages` = **FRAGMENT, COMPUTE, TASK, MESH** (non VS/TES/GS: `radv_physical_device.c:2026-2028`); RADV onora il valore con `RADV_REQUIRED_WAVE32` (`radv_pipeline.c:131-141`); default **wave64 per CS, PS e geometria**, wave32 solo per RT (`radv_physical_device.c:2836-2860`) | il traduttore deve pinnare 32 in FS/CS/task/mesh (tier `Direct`) e usare il tier `Cluster32` (operazioni clustered a 32 su wave64) in VS/TES; alternativa nel nostro build Darwin di RADV: default `ge_wave_size = 32` (equivalente a `RADV_PERFTEST=gewave32`). `threadExecutionWidth` = 32 sempre |
| Operazioni simd/quad, ballot, shuffle, prefix | subgroup basic/vote/arithmetic/ballot/shuffle/relative/clustered/quad/rotate | tutte supportate in tutti gli stadi, `subgroupQuadOperationsInAllStages` = true, `VK_KHR_shader_quad_control`, `VK_KHR_shader_subgroup_rotate`, **`shaderMaximalReconvergence` = true** | nessuno; la reconvergenza massimale evita le note `ImplementationDefined` di metal2vulkan |
| simdgroup_matrix 8x8 (float/half/bfloat) | `VK_KHR_cooperative_matrix` (WMMA RDNA4) | `cooperativeMatrix` = true, `VK_EXT_cooperative_matrix_maintenance1`, `shaderBFloat16CooperativeMatrix` = true (forme 16x16 su RDNA [INFERITO, l'elenco delle forme non è nel dump di vulkaninfo]) | **gap nel traduttore** (`SimdgroupMatrix` non implementata su nessun device): emulare 8x8 con shuffle (32 lane x 2 elementi) o raggruppare in tile 16x16; serve per MPS/CoreML/MPSGraph e ML |
| half, bfloat | `shaderFloat16`, 16-bit storage, `VK_KHR_shader_bfloat16` | float16/int16/int8 = true, `storageBuffer16BitAccess`/`storageInputOutput16` = true, `shaderBFloat16Type`/`DotProduct` = true | nessuno |
| Mesh/object shader | `VK_EXT_mesh_shader` | task/mesh = true; maxMeshWorkGroupInvocations **256**, maxTaskWorkGroupInvocations 1024, maxMeshOutputVertices/Primitives **256/256**, maxTaskPayloadSize 16384, maxMeshOutputLayers 8; `meshShaderQueries` = false. Su RADV richiede coda compute + gang submit (`radv_taskmesh_enabled`, `radv_physical_device.c:67-76`) | possibile gap di limiti: Metal ammette threadgroup mesh più grandi e più primitive [INFERITO: da confrontare con le Metal feature set tables]; il traduttore rifiuta oltre i limiti (`MeshShading`). **Dipendenza kernel**: il nostro kext deve esporre almeno una coda compute (MES compute HQD) e la gang submission |
| Ray tracing (intersector, instance/primitive AS) | `VK_KHR_ray_query` + `VK_KHR_acceleration_structure` | rayQuery, accelerationStructure, rayTracingPipeline = true; `VK_KHR_ray_tracing_position_fetch`; maxGeometryCount 16 777 215, maxPrimitiveCount 536 870 911; BVH8 gfx12 (`03 §4.6`) | traduzione intersezione ok (metal2vulkan via ray query); **mancano**: build AS (`MTLAccelerationStructureCommandEncoder` -> `vkCmdBuildAccelerationStructuresKHR`, NullMoth ne ha uno, `nvmtl_vk_cmd_build_accel`), intersection function table (ray query + loop candidati + switch devirtualizzato), motion blur (nessuna estensione su RADV -> `supportsPrimitiveMotionBlur` = NO) |
| Sparse texture/heap | sparse binding/residency | sparseBinding/ResidencyBuffer/Image2D/Image3D/Aliased = true, `residencyStandard2DBlockShape`, `residencyNonResidentStrict`, `shaderResourceResidency` = true, `sparseAddressSpaceSize` 128 TiB | **dipendenza kernel**: map/unmap PRT nel VM (equivalente `AMDGPU_VA_OP_*` con flag PRT) e coda per i bind sparse |
| Indirect command buffer (CPU e GPU-encoded) | replay CPU; `VK_EXT_device_generated_commands` | DGC = true | ICB codificati dalla GPU: oggi rifiutati in parte dal traduttore; DGC di RADV è la via naturale (lavoro nuovo) |
| Raster order group, framebuffer fetch, imageblock | `VK_EXT_fragment_shader_interlock` (POPS) | `fragmentShaderPixelInterlock`/`SampleInterlock` = true; `VK_EXT_rasterization_order_attachment_access` assente; `VK_KHR_dynamic_rendering_local_read` presente | nessun gap per il fetch ordinato (metal2vulkan usa l'interlock); costo prestazionale da misurare su WindowServer (ogni fetch serializza i fragment per pixel) |
| Tessellation | tessellation shader | true, maxTessellationGenerationLevel 64 (= fattore max Metal su Mac2), patch size 32 | nessuno |
| Vertex amplification, layered rendering | multiview, `shaderOutputLayer`/`ViewportIndex` | true, maxMultiviewViewCount 8, maxViewports 16 | nessuno |
| Barycentric, primitive_id, stencil export | `VK_KHR_fragment_shader_barycentric`, geometryShader, `VK_EXT_shader_stencil_export` | tutti presenti | nessuno |
| Sample positions programmabili, depth bounds, depth clip | `VK_EXT_sample_locations`, `depthBounds`, `VK_EXT_depth_clip_enable/control`, `VK_EXT_depth_range_unrestricted` | tutti presenti | nessuno (`depth_range_unrestricted` evita la nota `RestrictedDepthRange` di FAST-PATHS) |
| Formati | - | BC = true; **ASTC/ETC2 = false** (coerente con Mac2); **D24S8 = nessuna feature**; R32F filtrabile (linear + minmax); 2-plane 4:2:0 8/10 bit ok; 4:2:2 packed assenti; `VK_EXT_4444_formats` ok | rispondere `isDepth24Stencil8PixelFormatSupported = NO`; emulare 4:2:2 e XR10 nel traduttore |
| Filtro bicubico | (in shader) | `VK_EXT_filter_cubic` assente | in shader (metal2vulkan) |
| Memoria host senza copia | `VK_EXT_external_memory_host` | presente, `minImportedHostPointerAlignment` 4096 | **dipendenza kernel**: userptr (pin pagine utente + mapping GPU) |
| Eventi / shared event | timeline semaphore | `timelineSemaphore` = true | **dipendenza kernel**: syncobj timeline; cross-process = porta Mach del syncobj |
| Function pointer / dynamic library | (nessuno) | - | solo devirtualizzazione; dichiarare `supportsFunctionPointers` solo se i casi tipici passano |
| Metal 4 (macOS 26): argument table, command allocator, residency set obbligatori, `MTL4Compiler`, ML encoder/tensor | descriptor heap, BDA, cooperative matrix | primitive presenti | lavoro di API (369 voci mancanti in metal2vulkan); da pianificare dopo Metal 3 |

### 7.2 Limiti numerici utili per le risposte di `MTLDevice` [VERIFICATO sul profilo; i valori Metal tra parentesi sono INFERITI dalle Metal feature set tables, da ricontrollare]

maxComputeWorkGroupInvocations 1024 e maxComputeWorkGroupSize 1024^3 (Metal: 1024 thread per threadgroup); maxComputeSharedMemorySize 65 536 (Metal `maxThreadgroupMemoryLength` su Mac tipicamente 32 KiB [INFERITO]: si può dichiarare 64 KiB solo se le app lo tollerano, prudente 32 KiB); maxPushConstantsSize 256 (il traduttore sintetizza buffer per `setBytes:` oltre la finestra push); maxStorageBufferRange 4 GiB-1 (Cobalt64 dichiara `maxBufferLength` 4 GiB); maxImageDimension2D 32 768 ma maxFramebufferWidth 16 384 (Metal Mac2: 16 384 per texture 2D: dichiarare 16 384); maxImageArrayLayers 8 192 (Metal 2 048); maxColorAttachments 8 (Metal 8); framebufferColorSampleCounts 1/2/4/8 (Metal 1/2/4/8); maxSamplerAnisotropy 16; maxSamplerLodBias 16; maxVertexInputAttributes/Bindings 32 (Metal 31 attributi/31 buffer); timestampPeriod 10 ns (100 MHz; `MTLDevice` timestamp e counter sample buffer devono convertire).

### 7.3 Dipendenze dal kernel (kext) che il lato Metal impone a RADV-Darwin

Dal punto di vista Metal, quasi tutto è user space (ACO/RADV). Le eccezioni, da riportare nei requisiti del kext (cfr. `03 §7.2`):
1. **VA stabili per processo** (BDA = `gpuAddress`): VM per processo con VA a 48 bit, nessuno spostamento dei BO mappati.
2. **userptr** per `newBufferWithBytesNoCopy:` e per il modello IOSurface (A).
3. **import per IOSurface ID** (modello B) o almeno lookup IOSurface -> pagine.
4. **syncobj timeline** (eventi, shared event, ordinamento present) e, a regime, **fence per BO** (implicit sync tra processi).
5. **coda compute + gang submit** per task/mesh shader; coda SDMA opzionale (transfer queue di RADV è sperimentale, `radv_transfer_queue_enabled`).
6. **PRT** (map/unmap sparse) per sparse texture/heap.
7. **budget VRAM** riportato (patch Cobalt64 0006) e in seguito eviction o residency user space.

## 8. Architettura di traduzione raccomandata

### 8.1 Opzioni valutate

| Opzione | Descrizione | Pro | Contro | Verdetto |
|---|---|---|---|---|
| A. Plugin ObjC + encoder propri su RADV + **solo il traduttore** metal2vulkan | modello Cobalt64/NullMoth (`05 §6`, `06 §5`) | provato in produzione da due progetti; controllo totale su WindowServer | hazard tracking, eventi, ICB, argument buffer, formati Apple da riscrivere (NullMoth ~24 K righe, Cobalt64 ~10 K e ancora incompleto) | fallback |
| B. Plugin ObjC "shim" + **metal2vulkan-runtime** come motore (via FFI C) che adotta il `VkDevice` RADV creato dal plugin | il runtime implementa API Metal, hazard tracking, eventi come timeline semaphore, ICB, argument buffer, formati XR10/YCbCr; il plugin aggiunge IOSurface, presentazione, gating, SPI | semantica Metal misurata su hardware Apple, validata sul traffico reale di WindowServer/CA/CI di Tahoe 26.6.2 (§3.1); licenza LGPL compatibile con un bundle che linka una dylib; adozione di un device esterno prevista (`README` runtime: "takes the consumer's `vkGetInstanceProcAddr` when it adopts one"; `interop.rs`) | alpha, API instabile, Rust 1.98, ~211 K righe in più nel processo WindowServer; IOSurface/drawable fuori scope (da scrivere noi); dipendenza da un singolo autore | **raccomandata** (con A come rete di sicurezza) |
| C. Diretto a gfx12 senza Vulkan (AIR -> NIR -> ACO, PM4 proprio) | scrivere un `air_to_nir` e un "Metal driver" nativo sul modello di RADV | nessun overhead SPIR-V/Vulkan, mapping 1:1 di alcune feature (simdgroup = wave32, POPS, DGC) | riscrivere gestione stato PM4/NGG/descrittori/addrlib = rifare RADV (`03`); nessun progetto di riferimento | no (solo ottimizzazioni mirate, v. 8.4) |
| D. macOS guest paravirtualizzato su host Linux (protocollo ParavirtualizedGraphics) | il "consumer" di metal2vulkan è di questo tipo (§3.1) | nessun kext GPU, nessun DCN | non è un Hackintosh bare-metal, implementazione host non pubblica [INFERITO] | fuori obiettivo; utile solo come idea di banco di prova |

### 8.2 Architettura proposta (opzione B)

```
 Processo Metal (app, WindowServer, WebKit GPU process ...)
 +--------------------------------------------------------------------------------------------+
 | Metal.framework                                                                            |
 |   MTLLibrary/MTLFunction di Apple (front-end MSL->AIR via MTLCompilerService, reflection,  |
 |   function constants, linking, CoreImage CIFilter libraries)                              |
 +------------------------------|-------------------------------------------------------------+
 | Navi44Metal.bundle (/Library/GPUBundles)                                                   |
 |  ObjC shim: N44Device : MTLIOAccelDevice, N44Buffer/N44Texture : _MTLResource, ...         |
 |   - gating (allow-list, kill file, Ready dal kext), census + forwarding SPI                |
 |   - limiti/feature (featureProfile, supportsFamily, argumentBuffersSupport, limits gfx1200)|
 |   - AIR della funzione: -[MTLFunction bitcodeData] (SPI, come Cobalt64);                   |
 |     fallback: libraryDataContents + parser metallib di metal2vulkan-air                    |
 |   - IOSurface: modello A (userptr) -> poi B (VRAM via kext), cache import/alias/ledger     |
 |   - presentazione: superfici CoreDisplay -> flip DCN via export RADV-Darwin                |
 |  libm2v_shim.dylib (Rust, C ABI) = metal2vulkan-runtime + metal2vulkan (LGPL)              |
 |   - Device adottato sul VkDevice RADV; cache shader su disco (cartella cache utente)       |
 |   - WindowServer: cache precompilata + compilazione in processo helper con pipeline di     |
 |     fallback e hot-swap (modello Cobalt64); app: compilazione in-process (sandbox-safe)    |
 +------------------------------|-------------------------------------------------------------+
 | libvulkan_radeon.dylib (RADV, Mesa main + winsys Darwin; ACO gfx1200)                      |
 |   export privati: scanout (acquire/register/present/status), import IOSurface, budget      |
 +------------------------------|-------------------------------------------------------------+
                                v  IOUserClient sull'IOAccelerator (sandbox-friendly)
 Kext Navi44 (IOGraphicsAccelerator2 + IOFramebuffer + IOAccelDisplayPipe + core amdgpu-like)
```

Scelte puntuali:
1. **Librerie e funzioni restano di Apple** (come Cobalt64): massima compatibilità con reflection, `newLibraryWithSource:` (WebKit/ANGLE/Dawn), CoreImage (`newLibraryWithCIFilters:`), binary archive e dynamic library; il nostro codice interviene alla creazione della pipeline. Rischio: `bitcodeData` è SPI -> tenere il percorso alternativo via `libraryDataContents` (usato da NullMoth, `06 §5.3`).
2. **Traduzione per pipeline, non per funzione**: usare `compile_render_pipeline`/`compile_compute_pipeline` + `BindingPlan` di metal2vulkan 0.2 (varianti per formato storage texture, vertex descriptor, function constants) invece del modello "per funzione + layout fisso" di 0.1.
3. **SIMD a 32**: profilo device dal `VkDevice` reale (`DeviceDescription::query`), che riporta `requiredSubgroupSizeStages` = FS/CS/task/mesh; valutare nel nostro RADV-Darwin il default `ge_wave_size = 32`.
4. **Profilo e cache**: chiave di cache = impronta del profilo + `SEMANTICS_VERSION` di metal2vulkan + build id di RADV; VkPipelineCache/`VK_KHR_pipeline_binary` per evitare la ricompilazione ACO a ogni avvio di WindowServer.
5. **Sicurezza di WindowServer**: nessun panic Rust deve attraversare il confine (il traduttore usa `catch_unwind`, `docs/ARCHITECTURE.md`); su rifiuto (`Unsupported`) pipeline di fallback + log + traduzione asincrona; deadline di compilazione (`Budget`).
6. **Feature dichiarate per tappa**: `MTLGPUFamilyMac2` + Common1..3 da subito; `argumentBuffersSupport` Tier1 finché il bindless non è validato, poi Tier2; `MTLGPUFamilyMetal3` solo quando argument buffer tier 2 + mesh + `gpuAddress` passano i casi di validazione (Cobalt64 insegna che dichiararlo prima rompe le app, `Navi48Device.m:6270-6272`); `supportsRaytracing` NO fino al build delle AS; `isDepth24Stencil8PixelFormatSupported` NO; `hasUnifiedMemory` NO; `recommendedMaxWorkingSetSize` ~75% della VRAM letta dal kext (12 GiB su 16 GB); nome "AMD Radeon RX 9060 XT".

### 8.3 Cosa riusare da dove

| Componente | Fonte | Licenza | Uso |
|---|---|---|---|
| Traduttore AIR->SPIR-V + binder | metal2vulkan 0.2 (`M2V/crates/metal2vulkan`, `-air`) | GPL-2.0+ OR LGPL-3.0+ | dylib, come dipendenza |
| Runtime Metal su Vulkan | `M2V/crates/metal2vulkan-runtime` | idem | motore dell'opzione B |
| Modello di classi ObjC, gating, census, IOSurface (impcache/ioalias/ledger/plane/texdesc), D-copy present, heap allocator | Cobalt64 `tools/native/navi48metal` | MIT | fork/adattamento (cambiare `productName`, id device 0x7590, ABI kext) |
| Idee: forwarding SPI, VRAM IOSurface zero-copy, residency user space, `commitAndWaitUntilSubmitted` sincrono in WindowServer, `featureProfile`/`initLimits` | NullMoth `plugin/` | **PolyForm Noncommercial** | solo come riferimento di design, niente codice |

### 8.4 Ottimizzazioni "dirette a gfx12" da tenere per dopo (opzione C mirata)

- **Ingresso NIR privato in RADV**: Mesa ha moduli shader interni con NIR già pronto (meta shader); un export RADV-Darwin che accetti NIR da un futuro `air_to_nir` eliminerebbe SPIR-V (latenza di compilazione in WindowServer) [INFERITO].
- **Fetch ordinato su POPS**: già la via di metal2vulkan su RADV; misurare il costo su WindowServer (pass di login con fetch XR10).
- **ICB codificati dalla GPU -> `VK_EXT_device_generated_commands`** (RADV lo implementa con PM4 generato dalla GPU).
- **simdgroup_matrix -> WMMA gfx12** tramite cooperative matrix.

## 9. Piano di copertura incrementale

Ogni tappa ha un criterio di accettazione verificabile. Le tappe 0-1 si possono fare **interamente su Linux con RADV sulla stessa RX 9060 XT** (il runtime metal2vulkan gira su qualunque Vulkan 1.2 con timeline semaphore), prima ancora di avere macOS o il kext: questo separa i bug di traduzione da quelli del kernel.

| Tappa | Contenuto | Accettazione |
|---|---|---|
| **L0 (Linux)** | build di metal2vulkan (dopo revisione del codice: è codice di terzi), aggiunta del profilo `RDNA4 RADV` (il nostro `vkprofile_gpu0.json`) alla validazione; esecuzione del gate senza GPU e delle lane `--cfg m2v_gpu` sulla 9060 XT | gate verde; nessuna regressione rispetto al profilo `amd-rdna3-radv`; elenco delle "driver deviation" RDNA4 misurate (lane simdgroup, NaN, denorm) |
| **L1 (Linux)** | corpus AIR reale: catturare con un bundle di dump (modo `n48_dump`, `Navi48Device.m:1994-2004`) gli AIR di WindowServer/CoreImage/MPS/WebKit su un Mac reale o sulla prima installazione macOS; tradurli tutti su Linux (`corpus-triage`) e compilarli con RADV gfx1200 | 100% delle pipeline di WindowServer tradotte e compilate; elenco dei rifiuti "system" risolto o con fallback |
| **M0 device** | kext con IOAccelerator minimo + bundle con `initWithAcceleratorPort:`, `featureProfile`, census; RADV-Darwin aperto; allow-list solo per un probe (`mtlprobe` stile Cobalt64) | probe: enumerazione device, dispatch compute, blit, triangolo offscreen con readback corretto |
| **M1 WindowServer** | IOSurface modello A (userptr), render pass colore + blend, framebuffer fetch/XR10, heap MPS, depth/stencil state, sampler bicubico, D-copy present su DCN 4.0.1 (DP->UNIPHY_A), `commitAndWaitUntilSubmitted` sincrono | login window e desktop disegnati; WindowServer stabile 60 s senza crash né "flip-latch timeout"; CRC dei frame coerente; nessun selettore mancante nel census |
| **M2 sistema** | CoreImage (`air.ci`, `CI_USE_MTL_DAG_FOR_CIKL_SRC` solo se serve), QuickLook/Anteprima/Foto, YCbCr/4:2:2, `newBufferWithBytesNoCopy:`, video in Safari via VideoToolbox software | test tipo NullMoth: texture row-pitch/offset, render target IOSurface vs privati, blur MPS, grafo CoreImage con zero componenti errati (`CARD-SUPPORT.md:56-66`) |
| **M3 browser** | traduzione in-process nel sandbox, MSL runtime (`newLibraryWithSource:` via MTLCompilerService), IOSurface cross-process, `MTLSharedEvent` cross-process (syncobj come porta Mach), argument buffer Tier1 | Safari: pagine, video, WebGL (ANGLE-Metal), WebGPU samples; Chrome: compositing GPU, WebGL, WebGPU |
| **M4 Metal 3 app** | argument buffer Tier2 (BDA + descriptor heap), `gpuAddress`/`gpuResourceID`, `useResource/useHeap`, residency set, ICB CPU, heap placement, sparse (PRT nel kext), counter sample buffer, MSAA; dichiarazione `MTLGPUFamilyMetal3` | casi authored metal2vulkan su RADV-Darwin = Linux; Blender (Cycles Metal), Geekbench Metal/OpenCL, giochi Metal nativi |
| **M5 prestazioni** | IOSurface in VRAM (modello B) + flip diretto senza D-copy, fence per BO nel kext (present a "scheduled"), hazard tracking preciso, `VK_KHR_pipeline_binary`, wave32 dove conviene, DCC per superfici non display | frame time WindowServer a 4K60 senza drop; nessuna copia per frame |
| **M6 avanzato** | build AS + intersection function table (ray tracing), mesh oltre i limiti RADV, simdgroup_matrix (cooperative matrix), ICB GPU-encoded (DGC), Metal 4 | `supportsRaytracing` YES con i sample Apple di ray tracing; MPSGraph/CoreML su GPU |

## 10. Rischi, domande aperte e test eseguiti

### 10.1 Rischi

1. **Dipendenza da metal2vulkan 0.2**: alpha, API instabile, un solo autore, ~1,25 M righe Rust (Rust 1.98, target `x86_64-apple-darwin` da compilare con SDK macOS). Mitigazione: fissare un commit, vendorizzare, mantenere l'opzione A (solo traduttore) come ripiego, contribuire il profilo RDNA4 a monte.
2. **SPI Apple**: `MTLIOAccelDevice`, classi `_MTL*`, `-bitcodeData`, `-libraryDataContents`, `-featureProfile`, `-initLimits`, layout di `IOAcceleratorFamily2`: cambiano tra Sequoia 15 e Tahoe 26. Cobalt64 fissa Tahoe 26.6.2 e verifica i layout a runtime ("layout gate", `05 §7.1`); NullMoth è su Sequoia 15.x. [INFERITO] Tahoe 26 è annunciata come ultima release macOS per Mac Intel: le SPI x86 dovrebbero congelarsi, il che favorisce Tahoe come target.
3. **Latenza di traduzione al boot**: la prima accensione di WindowServer senza cache produce pipeline di fallback (magenta/no-op in Cobalt64): serve una cache SPIR-V/pipeline precompilata distribuita col bundle e generata per il nostro profilo.
4. **Framebuffer fetch via POPS**: necessario per il login di Tahoe (XR10); serializza i fragment per pixel: costo da misurare.
5. **Sincronizzazione tra processi** assente nei progetti esistenti (present dopo completion, WindowServer sincrono): rischio di flicker e di latenza; la soluzione corretta (fence per BO nel kext) è lavoro nuovo.
6. **IOSurface in memoria di sistema** (modello A): banda PCIe e copia per frame in VRAM; con più monitor 4K può non bastare -> modello B necessario per M5.
7. **Divergenze numeriche** rispetto ad Apple (politiche "fast" di metal2vulkan, `docs/FAST-PATHS.md`): accettabili per giochi, da valutare per CoreImage/gestione colore (attivare le varianti exact per i kernel `air.ci` se servono).
8. **Sandbox**: traduttore e cache dentro processi sandboxati (WebKit GPU process): niente processi figli, cache nella cartella cache utente consentita (`n48xlate` docs).
9. **Licenze**: NullMoth PolyForm Noncommercial (solo idee); metal2vulkan LGPL (dylib separata, ricompilabile dall'utente); Mesa MIT; firmware AMD (linux-firmware).
10. **wave64 di default e semantica simdgroup in VS/TES**: gestita dal tier `Cluster32`, ma un bug lì rompe silenziosamente shader che usano `simd_*` nel vertex: inserire test dedicati su gfx1200.
11. **D24S8 assente su gfx12**: app vecchie che lo assumono sui Mac AMD (dove Apple lo supportava [INFERITO]) possono fallire; NullMoth risponde YES su NVIDIA, noi dobbiamo rispondere NO o emulare con D32S8.

### 10.2 Domande aperte (richiedono macOS installato, un Mac reale o dati privilegiati)

- Versione macOS target (Tahoe 26.x vs Sequoia 15.x) e relativo ABI privato di `MTLIOAccelDevice`/`IOAccelerator` (vtable, `IOAccelConfig`).
- Elenco completo degli AIR/pipeline di WindowServer, CoreDisplay, RenderBox e CoreImage sulla versione target (cattura con bundle di dump) e quanti colpiscono i rifiuti "system" di metal2vulkan.
- Se WindowServer su Tahoe x86 richiede `MTLGPUFamilyMetal3` (Cobalt64 lo mantiene YES solo per WindowServer: perché?).
- Forme supportate da `VK_KHR_cooperative_matrix` su gfx1200 (`vkGetPhysicalDeviceCooperativeMatrixPropertiesKHR`): non esposte da `vulkaninfo`; serve un piccolo programma Vulkan, ma gli header Vulkan non sono installati su questa macchina (niente installazioni permesse in questa fase).
- Limiti Metal per mesh shader su Mac2 (thread per threadgroup mesh/object, primitive massime) da confrontare con quelli RADV (256/256/16 KiB).
- Valori esatti che il driver AMD di Apple (AMDRadeonX6000MTLDriver) restituisce per `featureProfile`, `supportsFamily`, D24S8, `maxThreadgroupMemoryLength` su un Mac con Navi 2x (da un Mac reale o da un'installazione con RX 6000).
- Chi è il "consumer" paravirtualizzato di metal2vulkan e se la sua implementazione host è pubblica (potrebbe fornire un banco di prova senza kext).
- Se il percorso display di WindowServer su Tahoe x86 con un `IOFramebuffer` di terze parti usa sempre le transazioni `IOAccelDisplayPipe` (verificato per NullMoth su Sequoia e Cobalt64 su Tahoe, non per entrambe le versioni).

### 10.3 Test e verifiche eseguiti in questa analisi

1. **Confronto requisiti metal2vulkan vs RX 9060 XT**: script `scratchpad/metal-xlate/scripts/feat_check.py` (Python `-I`) su `docs/REFUSALS.md` e sul profilo Vulkan misurato: 29/29 feature e 2/2 estensioni nominate presenti; 4 nomi non-RADV spiegati (§3.5).
2. **Estrazione di 80+ estensioni, feature e limiti Metal-rilevanti** dal profilo (`vkprofile_gpu0.json`) e da `gpu0.txt` (cooperative matrix, conservative raster, depthBounds, image 2D view of 3D) (§7).
3. **LLVM upstream 23.1.1 su AIR Apple 2.8**: `llvm-dis` su 5 fixture compilate da Apple: 5/5 OK, triple `air64_v28-apple-macosx26.0.0`, `metalfe-32023.921.6`, AIR 2.8, Metal 4.0, puntatori opachi (§2.5).
4. **Verifiche nei sorgenti**: wave size di default e `requiredSubgroupSizeStages` di RADV (`radv_physical_device.c:2022-2028,2836-2860`), gestione `requiredSubgroupSize` (`radv_pipeline.c:131-141`), condizioni task/mesh e sparse (`radv_physical_device.c:67-76,99-107,147-157`), pitch lineare gfx12 (`ac_surface.c:1238,3969-3975`), domini di scanout Linux (`amdgpu_display.c:557-578`, `amdgpu_dm.c:528-548`).


### 10.4 Fonti web consultate

- Messaggi `MTLIOAccelDevice bad MetalPluginClassName property (null)` / `+[MTLIOAccelDevice registerDevices]: Zero Metal services found`: https://bugzilla.mozilla.org/show_bug.cgi?id=1701080
- WebKit WebGPU, supporto argument buffer tier 1 aggiunto (prima solo tier 2), commit 258651@main, gennaio 2023: https://bugs.webkit.org/show_bug.cgi?id=250123
- Skia Graphite, rilevamento famiglia GPU Metal (Apple9..Apple2, Mac2) e query D24S8: https://skia.googlesource.com/skia/+/chrome/m153/src/gpu/graphite/mtl/MtlCaps.mm
- Famiglie Metal 3 (AMD Vega/5000/6000, Intel UHD 630/Iris Plus, Apple A14+/M1+), mesh shader, argument buffer, MetalFX: https://developer.apple.com/metal/feature-sets , https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf
