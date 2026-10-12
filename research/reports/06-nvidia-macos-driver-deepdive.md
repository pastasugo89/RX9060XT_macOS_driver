# 06 — Deep-dive: nullmoth `nvidia-macos-driver` (NVIDIA Turing+ → Metal su macOS 15 Sequoia)

> Report di analisi (fase "solo ricerca", nessun codice driver scritto). Sorgente analizzata:
> `research/refs/nvidia-macos-driver/` (codice di terze parti NON fidato: solo letto, mai compilato/eseguito).
> Legenda: **[VERIFICATO]** = letto nel codice/doc con riferimento file:riga; **[INFERITO]** = deduzione dell'analista.
> Obiettivo: estrarre COME una GPU di terze parti diventa un device Metal "first-class" su macOS moderno,
> e mappare ogni componente su un equivalente AMD (RX 9060 XT, Navi 44, GC 12.0.0 / DCN 4.0.1, stack RADV).

## 0. Sommario esecutivo

**Come una GPU di terze parti diventa un device Metal "first-class" su macOS 15 (verificato nel codice NullMoth):**

1. **Kernel, 4 kext in Auxiliary Kernel Collection** (`/Library/Extensions`, `kmutil create -n aux ... --allow-missing-kdk`), non iniettati
   da OpenCore perché linkano IOAcceleratorFamily2/IOGraphicsFamily:
   - `NVRM` = driver HW (qui: l'RM open di NVIDIA r610 portato su XNU, GSP firmware da `/Users/Shared/nvfw`), user client che emula
     `/dev/nvidia*` (selettori 0-6), boot hold con `adjustBusy` finché la GPU non è pronta;
   - `NVAccel : IOGraphicsAccelerator2` = ciò che Metal/WindowServer cercano: 17 metodi puri (stamp, event machine, task/VA, memory map,
     resource, vid/sys memory, display machine, contesti stub) su header **ricostruiti dal binario Apple** con nomi presi dai driver AMD di
     Apple; proprietà `MetalPluginName=../../../Library/GPUBundles/NVMTLDriver` e `MetalPluginClassName=NVMTLDevice`, **trattenute** finché
     il display non è armato; `IOGLBundleName=AppleMetalOpenGLRenderer`; `IOAccelDisplayPipeCapabilities` per le display-pipe transactions;
   - `NVRMFB : IOFramebuffer` per head (modi/EDID/VBL/cursore) + `NVRMFBClaim` (score 30000) che ritira `IONDRVFramebuffer`;
   - `NVRMAGDC : AppleGraphicsDeviceControl` che risponde alla display policy (cmd `1` vendor info, `0x980` mappa framebuffer).
2. **User space**: `NVMTLDriver.bundle` in `/Library/GPUBundles`, classe `NVMTLDevice : MTLIOAccelDevice` (privata) inizializzata con
   `initWithAcceleratorPort:`; tutti gli altri oggetti sono `NSObject` conformi ai protocolli pubblici Metal + una rete di forwarding per
   le SPI private. Il plugin implementa Metal **sopra Vulkan** chiamando direttamente NVK (`dlopen libvulkan_nouveau.dylib`).
3. **Shader**: MTLCompilerService usato solo come front-end MSL->AIR (`super newLibraryWithSource:` + `libraryDataContents`); i metallib
   sono letti direttamente; AIR bitcode -> `libLLVM.dylib` incluso -> testo IR -> **metal2vulkan (LGPL, Rust)** -> SPIR-V -> NVK/NAK.
4. **NVK patch (MIT)**: nuovo backend `nvkmd/nvrm` (4.3k righe) al posto di DRM; trasporto `nvrm_xnu.c` = ioctl RM su
   `IOConnectCallMethod`, mmap su `IOConnectMapMemory64`, fd segnaposto `/dev/null`; submission GPFIFO + doorbell **in user space**;
   import zero-copy delle IOSurface con escape privata `0xE2/0xE3` + dup handle RM.
5. **Install**: SIP `0x0A43`, `amfi_get_out_of_my_way=0x1 amfi=0x80 ipc_control_port_options=0`, **Lilu+AMFIPass** (WindowServer è
   platform binary e rifiuta un bundle ad-hoc), `SecureBootModel=Disabled`, `ResizeGpuBars=13`/`ResizeAppleGpuBars=-1`, blocco
   `IONDRVSupport`, SMBIOS `iMacPro1,1`; installer macOS con impostazioni opposte; entry EFI di recovery (`-nvoff`).

**Per AMD (RX 9060 XT, Navi 44, GC 12.0.0)**: architettura, contratto IOKit/Metal, trasporto, procedure di install e gating sono
**vendor-neutral** e si mappano 1:1 (blueprint §10). RADV su gfx1200 espone **tutte** le estensioni Vulkan che il plugin NullMoth richiede
(verificato con vulkaninfo, §10.1). La differenza enorme è sotto: NullMoth ha portato un RM già OS-agnostico che delega l'init al GSP;
per AMD il "core" (PSP/SMU/GMC/IH/GFX12/MES/SDMA + DCN 4.0.1/DMUB) va portato o scritto, e il display DC è il componente più grande.
Licenze: plugin/kext/installer **PolyForm Noncommercial** (solo ispirazione o fork NC), traduttore **LGPL-3.0+** (riusabile come dylib),
patch NVK **MIT** (riusabile liberamente).


## 1. Mappa del repository e dimensioni

**[VERIFICATO]** Layout di `refs/nvidia-macos-driver/` (righe di codice contate con `wc -l` su .c/.cpp/.h/.m/.inc/.rs/.sh/.py/.swift/.patch/.metal/.js):

| Componente | Path sorgente | Righe | Installato in | Licenza |
|---|---|---:|---|---|
| Kernel core RM (open-gpu-kernel-modules r610 portato su XNU) | `kexts/NVRM/` (escluso accel) | ~10.7k (incluse copie vecchie `fb/`,`agdc/` e `nvkms_shaders.cpp` 1 381 righe di shader embedded; + i sorgenti NVIDIA esterni, non nel repo) | `/Library/Extensions/NVRM.kext` | PolyForm NC 1.0.0 (codice NullMoth) + MIT/GPL-2.0 (RM NVIDIA) |
| Acceleratore IOAccelerator | `kexts/NVRM/accel/` (`nvrm-accel.cpp`, `nvaccel_stubs.h`, `tahoe_fwd.h`, `iofam/*.h`, `re/*.h`) | 3 861 | `/Library/Extensions/NVAccel.kext` | PolyForm NC |
| Framebuffer IOFramebuffer | `kexts/NVRMFB/fb/nvrm-fb.cpp` (+ copia più vecchia in `kexts/NVRM/fb/`) | 3 298 | `/Library/Extensions/NVRMFB.kext` | PolyForm NC |
| Shim policy AGDC | `kexts/NVRMAGDC/nvrm-agdc.cpp` (+ copia più vecchia in `kexts/NVRM/agdc/`) | 483 | `/Library/Extensions/NVRMAGDC.kext` | PolyForm NC |
| Extra (non nel percorso base) | `kexts/NMHDA` (audio HDMI), `kexts/NMIntelFB` (pannello iGPU Intel come head 4) | 226 / 598 | opzionali | PolyForm NC |
| Plugin Metal | `plugin/` (`NVMTLDevice.m` 1 803, `NVMTLObjects.m` 5 226, `nvmtl_vk.c` 6 999, `NVMTLLibraryLoad.m` 2 520, ...) | 24 600 | `/Library/GPUBundles/NVMTLDriver.bundle` | PolyForm NC |
| Traduttore AIR→SPIR-V | `translator/translator/` (crate Rust, fork di metal2vulkan) + `translator/wrapper/` (passi extra) | ~302k di `.rs` (di cui ~54k test/fixture) | `libnvmtl_translate.dylib` dentro il plugin | **LGPL-3.0-or-later** |
| Patch NVK | `nvk/nvk-macos.patch` (454 KB, 12 183 righe, 81 file) su Mesa `17ca6174` (`nvk/MESA_BASE`) | 12 183 | `/Library/GPUBundles/nvmtl/` | **MIT** (Mesa) |
| Build | `build/` (`build_xlate.sh`, `build_plugin.sh`, `build263.sh`, `accel_build.sh`, `build_agdc.sh`) | 119 | — | PolyForm NC |
| Pacchetto | `package/install.sh`, `uninstall.sh` | 310 | — | PolyForm NC |
| App installer "1401" | `app/` (Swift+WebKit, `nullmoth-setup.sh`, `efi-safe/` Rust UEFI) | 4 903 | `1401.app` | PolyForm NC |
| Test/host tools | `tools/` (test python su macOS, oracoli, `vtdump.py`) | 3 143 | — | PolyForm NC |

Firmware GSP NVIDIA: `/Users/Shared/nvfw/nvidia/610.57.04` (non modificato, licenza firmware NVIDIA).

**Pipeline di un frame** (`docs/HOW-IT-WORKS.md:12-26`, `README.md:30-32`):

```
Metal app / WindowServer / CoreImage / MPS / OpenGL(GL-on-Metal di Apple)
   -> NVMTLDriver.bundle (MTLDevice privato)  [plugin/]
        shader: AIR (bitcode LLVM Apple) -> SPIR-V   [translator/, libnvmtl_translate.dylib]
   -> NVK (Mesa Vulkan + NAK) in-process, linkato nel bundle  [nvk-macos.patch]
        SPIR-V -> SASS, command buffer (pushbuf) GPFIFO
   -> NVRM.kext (RM NVIDIA r610 su XNU) via IOUserClient
   -> GSP firmware -> GPU
Display: WindowServer -> IOFramebuffer = NVRMFB (heads NVKMS, modi, vblank)
                      -> IOAccelerator = NVAccel (surface/IOSurface che WindowServer compone, display pipe)
                      -> AppleGraphicsDeviceControl policy = NVRMAGDC
```

Osservazione chiave **[VERIFICATO]**: non esiste un "Metal-on-Vulkan" separato tipo MoltenVK al contrario: il plugin è un
`MTLDevice` privato completo scritto in Objective-C che chiama Vulkan **direttamente** (API C) su NVK linkato nello stesso
processo. Vulkan è solo l'ABI interna tra "front-end Metal" e "back-end GPU".

**Differenza importante col nostro target [INFERITO]**: lato kernel NullMoth NON ha scritto un driver: ha *portato* l'RM
open di NVIDIA (che delega quasi tutto l'init hardware al GSP, un RISC-V on-die). Per AMD non esiste un equivalente
"firmware fa tutto": PSP/SMU/MES/RLC vanno caricati e pilotati dal driver host (vedi report su bring-up). Il porting
dell'RM è stato fattibile perché l'RM è già pensato per essere OS-agnostico (`os-interface`, `nv-xnu.h` qui sostituisce
`nv-linux.h`); `amdgpu` invece è profondamente legato a DRM/TTM/Linux.


## 2. (a) Integrazione con la famiglia IOAccelerator (NVAccel + iofam)

### 2.1 Il punto centrale: macOS trova una GPU cercando un `IOGraphicsAccelerator2` attaccato a un `IOPCIDevice`

**[VERIFICATO]** `kexts/NVRM/accel/re/IOGraphicsAccelerator2.h:4-11`: *"THIS IS THE CLASS OUR DRIVER MUST BE ... macOS finds a graphics
accelerator by finding an IOGraphicsAccelerator2 attached to a PCI GPU. IT IS AN ABSTRACT CLASS. 17 of its vtable slots are
`___cxa_pure_virtual`, and those 17 methods are the ENTIRE required vendor interface"*.

- Catena di classi (dal registry OSMetaClass del kernel + costruttore metaclasse): `IOGraphicsAccelerator2 -> IOAccelerator -> IOService`;
  `sizeof(IOGraphicsAccelerator2) = 0xdd8` (3544 B) (`re/IOGraphicsAccelerator2.h:16-20,74`). Vtable `__ZTV22IOGraphicsAccelerator2`,
  84 nuovi slot virtuali (268..351).
- Apple **non pubblica header** per IOAcceleratorFamily2: NullMoth li ha **ricostruiti dal binario** x86_64 di Sequoia
  (`re/gen_virtuals.py`, non incluso nel repo) prendendo i *nomi* dei metodi dai simboli dei driver Apple AMD
  (`AMDRadeonX4000_AMDGraphicsAccelerator`, `AMDRadeonX4000_AMDEllesmereGraphicsAccelerator`), `re/IOGraphicsAccelerator2.h:23-27`.
  Il tipo `_AMDSurfaceSwapSyncOptions` compare perfino nella firma di `IOAccelLegacySurface::setSyncCommand` (`iofam/iofam_types.h`,
  `nvaccel_stubs.h:88`). **Lezione AMD**: per noi i driver Apple `AMDRadeonX5000/X6000.kext` (Vega/RDNA1/RDNA2) sono la *referenza
  canonica* di come un vendor implementa questa famiglia: stesse classi, stessi slot.
- Rischi documentati nei commenti (`re/IOAccelDevice2.h:14-25`, `re/IOGraphicsAccelerator2.h:28-45`): (1) ordine vtable: un solo slot
  sbagliato sposta tutti i successivi -> panic a runtime, silenzio a compile time; (2) dimensione classe: i membri della sottoclasse
  partono all'offset della base (es. `IOAccelDevice2` = 0x188); se l'header sottostima la size i campi si sovrappongono. Guardia: `static_assert`.
  Gli override ereditati da IOService (start/stop/newUserClient...) **non** vengono ridichiarati apposta per non creare slot nuovi.

I 17 metodi puri da implementare (`re/IOGraphicsAccelerator2.h:101-176`) e cosa fa NVAccel (`nvrm-accel.cpp:159-235`):

| Slot | Metodo puro | Implementazione NVAccel |
|---:|---|---|
| 273 | `getStampMemory(unsigned*)` | `IOBufferMemoryDescriptor` 16 KB fisicamente contiguo, 4096 stamp (`nvrm-accel.cpp:166-169`) |
| 275 | `newEventMachine()` | `NVEventMachine : IOAccelEventMachineFast2` (stamp scritti da CPU, `checkGPUProgress` sempre true) |
| 309/316 | `createUserGPUTask()` / `createKernelGPUTask()` | `NVTask : IOAccelTask` con 32 `IORangeAllocator` da 1 TB (VA GPU per task) |
| 312 | `populateAccelConfig(IOAccelConfig*)` | scrive a mano 0x70 byte: nome `"NVIDIAAccelerator"`, flags `0x30844300`, AccelCaps=15, max tex 16384x16384, maxFB=5 (`:180-206`) — **offset copiati dal comportamento AMD**, non documentati |
| 314/315 | `configureDevice/teardownDevice(IOPCIDevice*)` | no-op: "RM owns the card (NVRM.kext)" |
| 322 | `newDisplayMachine()` | `NVDisplayMachine : IOAccelLegacyDisplayMachine` |
| 326-330 | `newGLContext/newCLContext/newSurface/new2DContext/newVideoContext` | sottoclassi stub generate (`NVGLContext`, `NVCLContext`, `NVSurface`, `NV2DContext`, `NVVideoContext`) |
| 334-336 | `newSysMemory/newVidMemory/newResource` | `NVSysMemory`, `NVVidMemory` (VRAM reale via RM), `NVResource : IOAccelResource2` |
| 339 | `newMemoryMap()` | `NVMemoryMap : IOAccelMemoryMap` (commit in page table GPU via RM `MAP_MEMORY_DMA`) |

In più (non puro) `newDisplayPipe()` -> `NVDisplayPipe : IOAccelLegacyDisplayPipe`.

### 2.2 Classi Apple sottoclassate (elenco completo verificato)

`OSDefineMetaClassAndStructors` in `nvrm-accel.cpp:87-604` e `nvaccel_stubs.h:56-173`:

| Classe NullMoth | Base Apple (IOAcceleratorFamily2) | Ruolo |
|---|---|---|
| `NVAccel` | `IOGraphicsAccelerator2` | il device acceleratore, IOClass della personality |
| `NVEventMachine` | `IOAccelEventMachineFast2` | stamp/fence della famiglia (scritti da CPU: `writeStamp` -> `nvAccelWriteStamp`) |
| `NVDisplayMachine` | `IOAccelLegacyDisplayMachine` | collega gli IOFramebuffer (heads) alla famiglia: `found_framebuffer()`, `display_mode_will/did_change` |
| `NVDisplayPipe` | `IOAccelLegacyDisplayPipe` | **presentazione WindowServer**: `validateTransaction/performTransaction/isTransactionComplete`, `initFramebufferResource` |
| `NVTask` | `IOAccelTask` | spazio VA GPU per processo: `allocate()/deallocate()` -> RM gpuva |
| `NVMemoryMap` | `IOAccelMemoryMap` | `commitIntoGPUPageTable/releaseFromGPUPageTable` |
| `NVResource` | `IOAccelResource2` | risorsa (backing di IOSurface): aperture, `getLevelOffset`, `pageoff` |
| `NVVidMemory` / `NVSysMemory` | `IOAccelVidMemory` / `IOAccelSysMemory` | `allocPhysical()` chiede VRAM a NVRMFB (`callPlatformFunction(NVRM_VRAM_FN_ALLOC)`) |
| `NVSurface` | `IOAccelLegacySurface` | surface legacy (swap: `submitSwapCopy` -> flip o copia su scanout) |
| `NVGLContext`, `NV2DContext`, `NVCLContext`, `NVVideoContext` | `IOAccelGLContext2`, `IOAccel2DContext2`, `IOAccelCLContext2`, `IOAccelVideoContext2` (tutti su `IOAccelContext2`/`IOAccelSubmitter2`) | **stub che loggano**: i canali GPU della famiglia NON sono usati |
| `IOAccelNVRMCarrier` (x32) | `IOService` | nodi figli a cui attaccare gli user client RM (vedi 2.4) |

**Ciò che NON è sottoclassato [VERIFICATO]**: `IOAccelDevice2`, `IOAccelSharedUserClient2`, `IOAccelContext2` (come user client),
`IOAccelCommandQueue`: gli header `re/IOAccelDevice2.h` e `re/IOAccelSharedUserClient2.h` esistono ma `nvrm-accel.cpp` non li include
(`grep` vuoto). La famiglia fornisce già i propri user client (`newUserClient` per tipi non-'NV' delega a
`IOGraphicsAccelerator2::newUserClient`, `nvrm-accel.cpp:456-464`): così `MTLIOAccelDevice` (lato Metal.framework) apre i suoi client
standard (device, shared, surface, display pipe) **implementati da Apple**, e il vendor fornisce solo gli oggetti di backend.

`iofam/` (22 header, `kexts/NVRM/accel/iofam/*.h`) = ricostruzioni minime delle classi base sopra elencate, sufficienti a sottoclassarle
(vtable + size). `gen_stubs.py` genera `nvaccel_stubs.h`: per ogni base percorre la catena e trasforma ogni virtuale ancora puro in uno
stub che logga (`gen_stubs.py:1-4`: la v1 aveva sbagliato regex e "stubbava" metodi che la famiglia implementa: *"A stub over a real
implementation is a silent lie"*).

**Tahoe (macOS 26)**: `tahoe_fwd.h`/`gen_tahoe_fwd.py` — su Tahoe Apple ha reso privati metodi ereditati di IOAcceleratorFamily2: NullMoth
li inoltra via vtable (`NM_TAHOE_FWD_*`). Per questo `NVAccel.kext` è l'**unico kext compilato per-OS** (`package/install.sh:88-90`:
*"Tahoe made the IOAcceleratorFamily2 methods it inherits private"*; build con `-DNM_TAHOE`, `build/accel_build.sh`).
Nota: il README dichiara Sequoia, ma `install.sh:86` accetta `15|26`.

### 2.3 Proprietà di registry che fanno scegliere il device a Metal/WindowServer

**[VERIFICATO]** `kexts/NVRM/accel/Info.plist:26-39` (personality `NVAccel`):

```xml
<key>IOClass</key><string>NVAccel</string>
<key>IOProviderClass</key><string>IOPCIDevice</string>
<key>IOPCIPrimaryMatch</key><string>0x000010de&amp;0x0000ffff</string>   <!-- vendor NVIDIA, qualsiasi device -->
<key>IOPCIClassMatch</key><string>0x03000000&amp;0xff000000</string>     <!-- base class display -->
<key>IOMatchCategory</key><string>IOAccelerator</string>                 <!-- categoria separata: coesiste con NVRM e NVRMFBClaim sullo stesso IOPCIDevice -->
<key>IOProbeScore</key><integer>100</integer>
<key>MetalPluginName</key><string>../../../Library/GPUBundles/NVMTLDriver</string>
<key>MetalPluginClassName</key><string>NVMTLDevice</string>
```

- `MetalPluginName` è un path **relativo** che Metal.framework risolve rispetto a `/System/Library/Extensions/` [INFERITO dall'aritmetica del
  path: tre `..` da `/System/Library/Extensions` portano a `/`] (dove stanno i bundle
  Apple tipo `AMDRadeonX6000MTLDriver.bundle`): il `../../../` esce dal volume di sistema sigillato (SSV) e punta a
  `/Library/GPUBundles/NVMTLDriver.bundle`. **[INFERITO]** questo è il trucco che evita di dover modificare `/System` (impossibile con SSV
  senza root patch): il bundle vive su volume Data scrivibile.
- `MetalPluginClassName` = nome della classe ObjC che Metal istanzia con `-initWithAcceleratorPort:` (vedi §5).
- `IOGLBundleName = "AppleMetalOpenGLRenderer"` impostato **a runtime** dopo l'arm (`nvrm-accel.cpp:404-407`): OpenGL passa dal renderer
  GL-su-Metal di Apple, quindi nessun driver GL vendor.
- `IOAccelDisplayPipeCapabilities = { DisplayPipeSupported: true, TransactionsSupported: true }` pubblicato via sysctl
  `debug.nvaccel_iop=1` (`nvrm-accel.cpp:921-946`): dice a WindowServer di usare le **display-pipe transactions** (presentazione moderna).
- **Non usati** nel codice NullMoth (grep vuoto): `MetalStatisticsName`, `PerformanceStatistics`, `GPUConfigurationVariable`,
  `IOVARendererID`, `AAPL,*`. Quindi NON sono necessari per avere un device Metal funzionante su Sequoia [VERIFICATO per assenza].
  (`PerformanceStatistics` serve ad Activity Monitor/`ioreg` per l'uso GPU — cosmetico.)
- Proprietà aggiunte da altri kext: `model` sul `IOPCIDevice` (nome marketing, `NVRM.cpp:311`), `IOFBDependentID=0x4E56524D00000001`
  e `IOFBDependentIndex` sugli IOFramebuffer (`NVRMFB/fb/nvrm-fb.cpp:1386-1387`) per raggrupparli come heads della stessa GPU.

**Gating del plugin (lezione critica)** `nvrm-accel.cpp:576-585`: in `start()` NVAccel **rimuove** `MetalPluginName` dal registry e lo
rimette solo quando un framebuffer NVRMFB è stato registrato nella display machine (`onCountGrewLocked`, `:396-408`). Motivo: se
WindowServer trova un device Metal prima che esista un display pipe funzionante, CoreDisplay crasha/loop. Varianti:
- *headless* (`headlessCheck`, `:281-313`): se dopo 60 s nessun head NVIDIA è pubblicato (laptop con display sull'iGPU), rimette
  `MetalPluginName` **senza armare**, setta `NVAccelHeadless=true` e sysctl `debug.nvaccel_headless=1`; il plugin rifiuta allora
  WindowServer ma serve le app (modello "dGPU secondaria" dei MacBook Pro dual-GPU).
- boot-arg `nvaccel=1` obbligatorio (`:550-551`, "boot-loop guard"), `-nvoff` spegne tutto (`nvrm_driver_off()`).
- NVAccel aspetta fino a 30 s che `NVRM` metta `nvrm-claimed=true` sull'`IOPCIDevice` (`:552-560`).

### 2.4 User client: come il plugin raggiunge il kernel RM passando dall'acceleratore

**[VERIFICATO]** `NVAccel::newUserClient` (`nvrm-accel.cpp:456-497`): se `type & 0xFFFF0000 == 0x4E560000` ('NV'), invece della famiglia
chiama `NVRM->callPlatformFunction("nvNewAccelClient", task, type&0xFFFF, &uc)`; NVRM crea un `IOAccelNVRMBridge : NVRMUserClient`
(`NVRM.cpp:983-1027`) che viene attaccato a uno dei 32 `IOAccelNVRMCarrier` (figli dell'acceleratore) perché *"the accelerator ... sleeps
at ~1019 children"* (`:487-491`). Lato NVK (`nvrm_xnu.c`, §7) si apre `IOServiceOpen(NVAccel, 0x4E560000|type)` con fallback su `NVRM`.
**[INFERITO]** Il motivo di instradare via IOAccelerator e chiamare la classe `IOAccel...Bridge` sono i profili sandbox: processi GPU di
Safari/Chromium/WebKit e molte app sandboxate possono aprire user client della famiglia IOAccelerator ma non di un servizio arbitrario
(`nvrm_xnu.c` cita esplicitamente i sandbox GPU dei browser per `/dev/null`).

Dispatch di `NVRMUserClient::externalMethod` (`NVRM.cpp:1130-1144`): selettore 0 `sGo`, 1 `sEsc` (= ioctl RM Linux `NV_ESC_*`, struct
variabile in/out), 2 `sGetFd`, 3 `sBindFd`, 4 `sKms` (ioctl NVKMS), 5 `sKmsEvents`, 6 `sWaitEvent`; `clientMemoryForType` per i mmap
(`IOConnectMapMemory64`). È una **traduzione 1:1 del device node Linux `/dev/nvidia*` in IOUserClient**.

### 2.5 Memoria: IOSurface <-> VRAM <-> GPU VA

- `NVVidMemory::allocPhysical()` (`nvrm-accel.cpp:703-738`): legge la lunghezza a `this+0x40`, chiede VRAM a NVRMFB con
  `callPlatformFunction(NVRM_VRAM_FN_ALLOC)` (ABI in `nvrm_vram_abi.h`), riempie `fRmHandle/fKva/fPhys/fBytes` e scrive l'indirizzo fisico a
  `this+0xc8`. Ritorna `false` se già backed *"as AMD's does"* — il comportamento è calcato sull'implementazione AMD di Apple.
- `NVResource::getApertureMemoryDescriptor()` (`:670-694`): `IODeviceMemory::withRange(fPhys, fBytes)` sopra BAR1 -> la CPU vede la VRAM.
  Su AMD l'equivalente è la BAR0 da 16 GB (ReBAR attivo, vedi hw facts): **tutta la VRAM è CPU-visibile**, semplificazione notevole.
- `NVTask::allocate()` + `NVMemoryMap::commitIntoGPUPageTable()` (`:105-150`, `:1608-1641`): VA GPU allocata dall'RM (`NVRM_GPUVA_FN_ALLOC`)
  e mappata con `MAP_MEMORY_DMA` — la famiglia Apple decide *quando*, il vendor decide *come* (page table).
- Surface share (`nvAccelSurfVram`, `:1184-1240`): dato un `surfaceID` e il task chiamante, `IOSurfaceRoot::lookupSurface` ->
  `IOGraphicsAccelerator2::deviceCacheForIOSurface(surface, plane)` (simboli C++ mangled chiamati direttamente) -> `NVResource` ->
  `NVVidMemory` -> l'RM duplica l'handle di memoria nel client RM del processo (`NVRM_SS_RM_SHARE_KAPI`). Così NVK nel processo può
  importare la VRAM **di un IOSurface allocato dalla famiglia** (zero-copy tra processi, base del compositing).

### 2.6 Presentazione: display pipe transactions (il pezzo più delicato)

`NVDisplayPipe::performTransaction` (`nvrm-accel.cpp:830-919`): WindowServer, dopo aver composto con Metal, invia una transazione con
`getPlaneIOSurface(0,0)`/`getPlaneResource(0,0)`. Strategia:
1. **zero-copy flip** (`nvAccelIopFlip`, `:1464-1530`, sysctl `debug.nvaccel_iop_flip=1`): se l'IOSurface è BGRA (`0x42475241`) e ha VRAM RM
   aggiornata (`valid[6]&1`), chiede a NVRMFB `callPlatformFunction("nvFlipToSurfacePure")` -> flip NVKMS dello scanout sulla VRAM
   della surface; asincrono su thread call con `signalTransactionInterrupt` ("Apple's shape", `debug.nvaccel_iop_async=1`).
2. fallback **copia CPU** riga per riga dalla surface (mappata) al buffer di scanout descritto da NVRMFB (`NVRM_VRAM_FN_SCANOUT`).
- Ordinamento: il kernel non sa ordinare lo swap dopo il fence NVK; quindi nel plugin `commitAndWaitUntilSubmitted` **in WindowServer**
  aspetta il completamento (`plugin/NVMTLObjects.m:4563-4573`, `docs/CARD-SUPPORT.md:36-47`: altrimenti flicker sotto il cursore).
  **Lezione AMD**: servirà un meccanismo vero di attesa fence lato kernel (o la stessa scorciatoia) — su AMD l'EOP fence/`RELEASE_MEM`
  può scrivere in memoria visibile al kernel, quindi un'attesa kernel-side sul seqno è fattibile.

### 2.7 Strumentazione e "gates" runtime

Tutto è dietro sysctl `debug.nvaccel*` (`nvrm-accel.cpp:1012-1044` e seguenti): `debug.nvaccelfb` (1=found_framebuffer, 2=sweep famiglia,
3=scanout gate, 4=aperture gate), `nvaccel_iop`, `nvaccel_iop_flip`, `nvaccel_iop_async`, `nvaccel_igpu`, contatori (`nvaccel_vm_alloc`,
`nvaccel_map_commit`, `nvaccel_iop_ok_h0..4`, CRC display `nvaccel_crc`). Metodologia: abilitare ogni funzione per gradi ("rung 5", "K3",
"K6") con fallback alla base class. **Da imitare** per non bloccare il boot durante lo sviluppo AMD.


## 3. (b) Framebuffer NVRMFB e shim AGDC (NVRMAGDC)

### 3.1 NVRMFB: `NVRMNVDAFramebuffer : IOFramebuffer`

**[VERIFICATO]** `kexts/NVRMFB/fb/Info.plist` (identico a `kexts/NVRM/fb/Info.plist`; la copia in `kexts/NVRM/fb/nvrm-fb.cpp` è una
versione più vecchia da 1 654 righe, quella in uso è `kexts/NVRMFB/fb/nvrm-fb.cpp` da 2 427 righe):

| Personality | IOClass | Provider | Score | Scopo |
|---|---|---|---:|---|
| `NVRMFB` | `NVRMNVDAFramebuffer` | `NVRMDisplay` (nub IOService pubblicato da NVRM, uno per head; `NVRM.cpp:55`) | 1000 | il vero framebuffer, uno per head |
| `NVRMFBClaim` | `NVRMFBClaim` | `IOPCIDevice` con `IONameMatch=display`, `IOMatchCategory=IOFramebuffer` | **30000** | batte `IONDRVFramebuffer` (`.Display_boot`, probe 20000) e lo "ritira": un solo framebuffer deve pubblicare BAR1+0 (commento `Info.plist:30-32`: con due framebuffer il desktop esteso vuoto sovrascriveva quello reale nella stessa memoria) |

`NVRMFBClaim::start` (`nvrm-fb.cpp:270-285`) cede se il driver è spento (`nvrm_driver_off()`), così in recovery il firmware screen resta.
In aggiunta OpenCore blocca `com.apple.iokit.IONDRVSupport` (`Kernel > Block`, Strategy `Exclude`) perché altrimenti il framebuffer firmware
prende l'indice display 0 (README §Wiring).

Override di `IOFramebuffer` implementati (`nvrm-fb.cpp:179-236`): `start/stop/free`, `enableController`, `getPixelFormats`,
`getDisplayModeCount/getDisplayModes` (modi da NVKMS + "refresh modes" aggiunti), `validateDetailedTiming/setDetailedTimings`,
`getInformationForDisplayMode`, `getTimingInfoForDisplayMode`, `getPixelInformation`, `getCurrentDisplayMode`, `setDisplayMode` (modeset
NVKMS), `getApertureRange` / `getVRAMRange` (scanout in BAR1), `getAttribute*/setAttribute*` (power, connection), `setPowerState`,
`setCursorImage/setCursorState` (cursore HW), `isConsoleDevice`, gamma/CLUT = no-op, `getConnectionCount()=1`, `hasDDCConnect/getDDCBlock`
(EDID da NVKMS), `registerForInterruptType` (accetta solo `kIOFBVBLInterruptType` e `kIOFBConnectInterruptType`, `:2412-2426`).
Proprietà: `IOFBDependentID = 0x4E56524D00000001` ("NVRM"), `IOFBDependentIndex = head` (`:1386-1387`), più diagnostica
(`NVRMTiming`, `NVRMDetailedTimings`, `NVRMModeSwitches`).

Backend: **NVKMS KAPI** di NVIDIA (`NvKmsKapiFunctionsTable`, la stessa API usata da `nvidia-drm` su Linux) — l'NVRM espone il puntatore
alla tabella come proprietà `nvkms-kapi` sul nub (`NVRM.cpp:73`, letto in `nvrm-accel.cpp` per i CRC). Modeset atomico che spegne
anche gli head non posseduti (`nvrmUnownedHeadsOff`, `:287-300`), flip cache con epoca per evitare riuso di indirizzi liberati.

`callPlatformFunction` del framebuffer (`nvrm-fb.cpp:2094-2150`) = **API privata kernel-kernel verso NVAccel**:
`NVRM_VRAM_FN_ALLOC/FREE` (VRAM per `NVVidMemory`), `NVRM_VRAM_FN_SCANOUT` (descrive lo scanout corrente: phys/kva/pitch),
`NVRM_GPUVA_FN_HANDLES` (handle KAPI device), `nvFlipToSurfacePure` e `NVRM_FLIP_FN` (flip dello scanout su un `NvKmsKapiMemory`).
Le ABI sono header condivisi versionati (`nvrm_vram_abi.h`, `nvrm_gpuva_abi.h`, `nvrm_surfshare_abi.h`) con controllo
`version` ("ABI mismatch — REBUILD BOTH KEXTS"). **Design da copiare**: kext separati che parlano via `callPlatformFunction` + struct versionate.

**Perché è necessario [VERIFICATO+INFERITO]**: WindowServer/CoreDisplay su macOS 15 richiede (1) un `IOFramebuffer` per ogni display con
modi/EDID/vblank reali, (2) che quel framebuffer sia registrato nella `IOAccelDisplayMachine` dell'acceleratore (`found_framebuffer`), (3)
un display pipe che presenti l'IOSurface composta. Senza (1) non ci sono display; senza (2)-(3) WindowServer non ha dove comporre con Metal.
Il framebuffer firmware (`IONDRVFramebuffer`/GOP) non ha vblank né modeset e non può essere associato all'acceleratore.

### 3.2 NVRMAGDC: `NVDADeviceControl : AppleGraphicsDeviceControl`

**[VERIFICATO]** `kexts/NVRMAGDC/Info.plist`: personality `NVDAGDCLoader` su `IOResources` (`IOResourceMatch=IOKit`), dipendenza da
`com.apple.AppleGraphicsDeviceControl`. Il loader sta fermo finché `sysctl debug.nvrmfb_agdc=1` (scritto da NVRM durante l'arm, §4);
allora `nvdaAgdcWorkBody` (`nvrm-agdc.cpp:196-217`) alloca `NVDADeviceControl`, lo **attacca all'IOPCIDevice della GPU** e chiama
`AppleGraphicsDeviceControl::start`.

`AppleGraphicsDeviceControl` (header ricostruito `AppleGraphicsDeviceControl_re.h`, size 0x110 su 15.7.9) ha un solo metodo puro:
`vendor_doDeviceAttribute(cmd, in, inSize, out, outSize, args)`. Comandi risposti (`nvrm-agdc.cpp:94-129`):

| cmd | Significato | Risposta |
|---|---|---|
| `1` | vendor info (`AGDCVendorInfo_t`, 0x2c B) | `version=0x30000`, `"NVIDIA"`, `vendorID=0x10de`, `vendorClass=2` |
| `0x980` | GPU capability (`AGDCGPUCapability_t`, 0xdc B) | `portMask`, conteggi, `maxFramebuffers=n`, puntatori `pciDevice` e `framebuffer[i]` (fino a 20) |
| `0x921` (`kAGDCLinkConfig`) / `0x711` (FB cap ex, plane scaler) | "K5", dietro `debug.nvrmfb_agdc_k5` | timing per head da proprietà `NVRMTiming` (`nvrm-agdc-k5.h`) |
| altri | — | `kIOReturnUnsupported` (contati) |

**Perché serve [INFERITO, coerente con i commenti]**: su macOS moderno la *display policy* (IOPresentment / CoreDisplay: mappa
framebuffer<->porte, link config, plane scaler, hot-plug policy) interroga l'oggetto AGDC del vendor della GPU. Sui Mac reali
`AppleGraphicsControl.kext` fornisce `AppleGraphicsDevicePolicy`/`AGDC` per AMD/Intel; con un vendor sconosciuto la policy non trova la
mappa framebuffer (`nvrm-agdc.cpp:53` cita *"IOPresentment's map holds 8"*). NVRMAGDC è quindi un **adattatore minimale** che risponde alle
domande essenziali. È anche il motivo per cui il README chiede di togliere `agdpmod=pikera` (patch WhateverGreen sulla board-id policy).

**Rilevanza AMD [INFERITO]**: per una Navi 44 servirà lo stesso shim (vendorID 0x1002). Su Hackintosh AMD esistono già i kext Apple
`AppleGraphicsDevicePolicy` che conoscono i framebuffer AMD *Apple* (`AMDRadeonX6000Framebuffer`), ma il nostro framebuffer sarà nuovo,
quindi va imitato il pattern NullMoth (risposte esplicite a `1` e `0x980`, il resto Unsupported, tutto dietro gate sysctl).

## 4. Kernel core NVRM (open-gpu-kernel-modules r610 sotto XNU)

**[VERIFICATO]** `kexts/NVRM/Info.plist`: personality `NVRM` su `IOPCIDevice`, stessa maschera vendor/classe di NVAccel, `IOProbeScore 1000`,
`IOUserClientClass NVRMUserClient`; dipende da `IOPCIFamily`, `IOACPIFamily`, `kpi.unsupported`. Il commento (`:52-60`) spiega il match
largo voluto: *"NVRM::probe() calls NVIDIA's own rm_is_supported_pci_device() and go() calls rm_is_supported_device(), and THOSE decide"*.

Sequenza di start (`NVRM.cpp:255-345`, `docs/HOW-IT-WORKS.md:38-46`):
1. `probe`: classe 0x03 sub 0x00/0x02, gate RM.
2. `start`: legge config PCI, `snapshotBootScreen()` (copia la schermata GOP), `placeLargeBar1()` (`:695-...`) — cerca la capability
   **Resizable BAR** (ext cap 0x15), se possibile ridimensiona BAR1 tra 4 e 8 GB e la riloca a `0x10000000000` (fuori dalla finestra della
   console firmware), `readBARs()`, pubblica `model` (nome dal chip table RM) e `nvrm-claimed=true` sull'IOPCIDevice.
3. **Boot hold**: `adjustBusy(1)` (`:330`) tiene il registry "busy" così WindowServer non parte sul framebuffer firmware; timer di cap
   = settle + 40 s (`bootHoldCap`).
4. Thread `autoGo` (`:510-590`): attende il settle (500 ms se BAR1 riposizionata, 100 s nel fallback small-BAR), `go(2)` ->
   MSI + `rm_init_adapter()` (`:927-929`, *"GSP boot from inside macOS"*), firmware caricato con `vnode_open`/`vn_rdwr` da
   `/Users/Shared/nvfw/nvidia/610.57.04/*.bin` (`os-xnu2.cpp:23,1127-1137`).
5. Poi aspetta che gli head NVRMFB pubblichino (`debug.nvaccel_heads_published` >= `nvfbheads`), fa CAS sul boot hold e **arma lo stack
   display scrivendo sysctl dal kernel** (`nvrmSysW`): `debug.nvaccelfb=1` poi `4`, `debug.nvrmfb_agdc_k5=1`, `debug.nvrmfb_agdc=1`,
   `debug.nvaccel_iop=1`; rilascia il boot hold (WindowServer parte); 60 s dopo `debug.nvaccel_iop_flip=1` (zero-copy flip).
   Proprietà riassuntiva `nvrm-display = "heads 0x.. accel 4 agdc 1 k5 1 iop 1"`.

Strato OS: `os-xnu.cpp`(301), `os-xnu2.cpp`(1 396), `nv_xnu_stubs.cpp`(1 815), `os-nvkms-xnu.cpp`(371) implementano l'interfaccia
`os_*`/`nv_*` che su Linux sta in `nvidia/os-interface.c` e `nv.c` (alloc, mapping, IRQ con `IOFilterInterruptEventSource`, timer,
thread, firmware, PCI config). L'ioctl Linux diventa `IOUserClient::externalMethod` (§2.4). Il pattern è **"porta un driver
OS-agnostico sostituendo solo lo strato OS"** — possibile perché l'RM NVIDIA è stato progettato per Linux/FreeBSD/Solaris/Windows.

**Confronto AMD [INFERITO, importante per il piano]**: l'equivalente di "RM+GSP" lato AMD è l'intero `amdgpu` (init IP: PSP 14.0.2
bootloader+TOC, SMU 14.0.2, GMC 12, IH 7, GFX 12 + RLC/IMU, MES 12, SDMA 7, DCN 4.0.1 + DMUB): codice Linux-specifico (DRM, TTM,
dma_fence, kthread, workqueue, firmware API). Non c'è un firmware "che fa tutto"; MES aiuta per lo scheduling delle code ma l'host deve
comunque caricare il microcode via PSP e programmare GMC/IH. Strategie possibili: (a) port selettivo di `amdgpu` con uno shim
`linux-on-xnu` (approccio Cobalt64/mac-amdgpu, vedi report dedicati), (b) driver minimale scritto da zero solo per GC 12.0.0. In entrambi i
casi la struttura dei kext (core + accel + fb + agdc) e i meccanismi di gating sono riusabili 1:1.


## 5. (c) Il plugin Metal in /Library/GPUBundles (NVMTLDriver.bundle)

### 5.1 Come Metal.framework carica il plugin

**[VERIFICATO]** Catena di caricamento:
1. Metal.framework (`MTLCreateSystemDefaultDevice`/`MTLCopyAllDevices`) enumera i servizi `IOAccelerator` nel registry e legge
   `MetalPluginName` + `MetalPluginClassName` (§2.3).
2. Carica `/System/Library/Extensions/<MetalPluginName>.bundle` -> qui `../../../Library/GPUBundles/NVMTLDriver.bundle`.
3. Istanzia `MetalPluginClassName` (`NVMTLDevice`) con **`-initWithAcceleratorPort:(mach_port_t)`** (porta del servizio IOAccelerator).

`plugin/NVMTLDevice.m:136-140`:

```objc
@interface MTLIOAccelDevice : NSObject
- (instancetype)initWithAcceleratorPort:(mach_port_t)port;
@end
@protocol MTLDeviceSPI <NSObject> @end
@interface NVMTLDevice : MTLIOAccelDevice <MTLDevice, MTLDeviceSPI>
```

`NVMTLDevice` **eredita dalla classe privata Apple `MTLIOAccelDevice`** (in Metal.framework; [INFERITO] è la base comune dei driver Metal
vendor x86 di Apple, es. `AMDMTLBronzeDriver` — `NVMTLForward.m` indicizza infatti anche le classi `AMD*`/`AGX*` per le firme). `[super initWithAcceleratorPort:]` apre gli user client standard della famiglia
IOAccelerator (shared memory, stamp, resource pools) — è per questo che NVAccel deve implementare correttamente gli oggetti di backend
anche se il rendering vero passa da NVK. `initWithAcceleratorPort:` (`NVMTLDevice.m:364-392`):
- `nvmtl_process_is_allowed()` (`:295-327`): **allow-list per processo** letta da `/Library/GPUBundles/nvmtl-allow.txt` (regole `*`, `nome`,
  `-nome` = negato, `!nome` = solo se armato `debug.nvaccelfb=1`); WindowServer escluso se `debug.nvaccel_headless=1`. Se la lista non è
  leggibile da `_windowserver` -> nessun device -> CoreDisplay abort "Failed to create MetalDevice" -> crash loop
  (`package/install.sh:198-202`). Lezione: **rollout per-processo** è il paracadute principale.
- `nvmtl_vk_init()`: carica NVK nel processo; se fallisce ritorna `nil` (Metal fa fallback / nessun device).
- registra encoder/decoder video (NVENC/NVDEC via `VTRegisterVideoEncoderWithInfo`, `:282-292`), chiama `-initLimits` (privato di
  `MTLIOAccelDevice`: popola i limiti serviti da tabella; *"every table-served limit stays 0 (CoreImage will refuse renders)"*).
- `vendorName` = `@"NVIDIA"`, `name` = `"<marketing> (NVMTL over <nome NVK>)"`.

### 5.2 Le interfacce implementate

**[VERIFICATO]** `plugin/NVMTLObjects.h`: ogni oggetto è un `NSObject` conforme al **protocollo pubblico** Metal (non sottoclassi delle
classi private `MTLIOAccel*`, tranne il device):
`NVMTLBuffer <MTLBuffer>`, `NVMTLTexture <MTLTexture>`, `NVMTLHeap <MTLHeap>`, `NVMTLLibrary <MTLLibrary>`, `NVMTLFunction <MTLFunction>`,
`NVMTLRenderPipelineState`, `NVMTLComputePipelineState`, `NVMTLCommandQueue <MTLCommandQueue>`, `NVMTLCommandBuffer <MTLCommandBuffer>`,
`NVMTLRenderCommandEncoder`, `NVMTLComputeCommandEncoder`, `NVMTLBlitCommandEncoder`, `NVMTLParallelRenderCommandEncoder`,
`NVMTLAccelerationStructure(+CommandEncoder)`, `NVMTLIndirectCommandBuffer`, `NVMTLArgumentEncoder`, `NVMTLFence`, `NVMTLEvent`,
`NVMTLSharedEvent`, `NVMTLResidencySet`, `NVMTLDepthStencilState`, `NVMTLSamplerState`, `NVMTLCounter*`, oggetti di reflection
(`NVMTLArgument`, `NVMTLStructType`, `NVMTLPointerType`, ...).

Rete di sicurezza per le SPI private: `NVMTLForward.m` sostituisce `methodSignatureForSelector:`/`forwardInvocation:` su ~40 classi
(`kNVCounterpart`, `:30-52`): se un framework Apple chiama un selettore privato non implementato, la firma viene presa dalla classe Apple
equivalente (`NVMTLCommandBuffer` -> `MTLIOAccelCommandBuffer`, ecc. o dai protocolli `MTL*`) e la chiamata viene assorbita restituendo
zero/nil invece di `doesNotRecognizeSelector` -> crash di WindowServer (`:254-272`, *"was: log-then-abort on 20"*). Indice costruito
scandendo tutte le classi `MTL*`, `AGX*`, `AMD*`, `IOAccel*`, `CA*`, `Apple*`.

SPI "vendor compiler" di `MTLIOAccelDevice` implementate come stub (`NVMTLVendorCompiler.m:452-495`):
`newTranslatedDriverCompilerOptions:compilerOptionsSize:`, `freeTranslatedDriverCompilerOptions:compilerOptionsSize:`,
`getComputeFunctionId:compilerOptions:compilerOptionsSize:`, `getComputeFunctionId:function:compilerOptions:compilerOptionsSize:`,
`computeVariantWithCompilerOutput:pipelineStatisticsOutput:` — sono gli agganci con cui il flusso Apple normale (MTLCompilerService +
backend compiler del vendor) consegna l'output al driver. Qui non sono usati (salvo la corsia opzionale NVVM).

### 5.3 MTLCompilerService: usato solo come front-end MSL->AIR

**[VERIFICATO]** `NVMTLDevice.m:994-1046`:
- `newLibraryWithData:` / `newLibraryWithURL:` / `newLibraryWithFile:` / `newDefaultLibrary`: il plugin legge **direttamente il container
  metallib** (`"MTLB"`, function list, `NVMTLLibraryLoad.m:652-...`) e traduce ogni funzione AIR (§6). Nessun MTLCompilerService.
- `newLibraryWithSource:options:error:` chiama `[super newLibraryWithSource:]` (cioè `MTLIOAccelDevice` -> MTLCompilerService XPC che fa
  il front-end MSL->AIR, indipendente dalla GPU), poi estrae il container con la SPI `libraryDataContents` e lo ritraduce
  (`nvmtlBridgeAppleLibrary`, `:1018-1027`). Stesso trucco per i link Core Image (`newLibraryWithCIFilters:imageFilterFunctionInfo:error:`,
  `newLibraryWithImageFilterFunctionsSPI:...`, `:1028-1031`).
- "Apple twin" (`:763-829`): per le API che pretendono un vero oggetto libreria Apple, il plugin costruisce in parallelo la libreria Apple
  via `super` (memoizzata per hash/inode).
- Il **backend** Apple (AIR -> ISA vendor, che per AMD vive nei bundle `AMDMTLBronzeDriver`/compilatore AMD di Apple) è completamente
  bypassato. Corsia opzionale (`NVMTL_VENDOR_COMPILER`): `NVIDIAShared.bundle` (compilatore NVVM NVIDIA d'epoca web-driver) + `air2nvvm.py`
  -> cubin SASS iniettato in NVK (`nvmtl_nvk_dispatch_sass_v1`); scelta del target SM dal nome chip, rifiuta chip sconosciuti
  (`docs/CARD-SUPPORT.md:49-54`).

### 5.4 Dal command buffer Metal a NVK

**[VERIFICATO]** `plugin/nvmtl_vk.h`/`nvmtl_vk.c` (6 999 righe) è uno strato C sottile sopra Vulkan con API proprie
(`nvmtl_vk_queue_create`, `nvmtl_vk_cmd_begin`, `nvmtl_vk_cmd_begin_render_ex`, `nvmtl_vk_cmd_draw_indexed`, `nvmtl_vk_cmd_dispatch_threads`,
`nvmtl_vk_bind_buffer/texture/sampler`, `nvmtl_vk_cmd_build_accel`, query di occlusione/timestamp, ...).
- **Init** (`nvmtl_vk.c:565-660`): `dlopen("/Library/GPUBundles/nvmtl/libvulkan_nouveau.dylib")` e `vk_icdGetInstanceProcAddr` **senza
  loader** (fallback su `libvulkan.dylib` + `VK_ICD_FILENAMES=nvk_icd.json`); Vulkan 1.3; prima famiglia GRAPHICS|COMPUTE; estensioni
  cercate: `VK_EXT_extended_dynamic_state3`, `VK_EXT_depth_clip_enable`, `VK_EXT_memory_budget`, `VK_KHR_acceleration_structure`,
  `VK_KHR_ray_query`, `VK_KHR_deferred_host_operations`, `VK_EXT_external_memory_host`, `VK_EXT_image_drm_format_modifier`,
  `VK_KHR_external_memory_fd`, `VK_EXT_mutable_descriptor_type`, `VK_KHR_cooperative_matrix`, `VK_EXT_calibrated_timestamps`,
  `VK_EXT_sample_locations`, `VK_KHR_pipeline_executable_properties`. Shader cache Mesa in `~/Library/Caches` o `_CS_DARWIN_USER_CACHE_DIR`.
- **Hook privati NVK** risolti con `dlsym` (`:581-585`): `nvmtl_nvk_stage_import`, `nvmtl_nvk_surface_dirty`,
  `nvmtl_nvk_sample_depth_contract_v1`, `nvmtl_nvk_sample_depth_image_v1`, `nvmtl_nvk_sparse_bind_v1` (+ `nvmtl_nvk_dispatch_sass_v1`).
  L'accoppiamento NVIDIA-specifico in `nvmtl_vk.c` è minimo (~33 righe: path della lib, `VkPhysicalDeviceShaderSMBuiltinsPropertiesNV`,
  questi hook). **Il resto è Vulkan portabile.**
- **Commit** (`NVMTLEventSync.m:389-401`, `nvmtl_vk.c:5012-5090`): `commit` -> `nvmtlSubmitWithEvents` -> coda serial
  `nvmtl.execution` (prenotazioni per ordinare i CB di una queue, eventi/shared event come attese/segnali) -> `vkEndCommandBuffer` +
  `vkCreateFence` + `vkQueueSubmit` con eventuale CB "prologo" (upload/fill raggruppati) -> attesa fence -> completion handler.
  `MTLSharedEvent` implementato in user space (`NSCondition`), non cross-process via kernel.
- **Presentazione app**: `presentDrawable:` registra un blocco `[drawable present]` eseguito dopo l'esecuzione (`NVMTLObjects.m:4535-4557`);
  il `CAMetalDrawable` è una texture su IOSurface creata da CoreAnimation tramite `newTextureWithDescriptor:iosurface:plane:`
  (`NVMTLDevice.m:724-747`): **zero-copy** se l'IOSurface (single-plane, pitch multiplo di 32) ha VRAM della famiglia importabile
  (`nvmtl_vk_surface_vram`, `nvmtl_vk.c:1729-1770`: `VkImportMemoryFdInfoKHR` con un fd fittizio `/dev/null` + record "staged" passato
  all'hook `nvmtl_nvk_stage_import` = `{surfaceID, plane, size}`), altrimenti immagine privata + copie CPU sincronizzate via seed
  dell'IOSurface (`IOSurfaceLock`, `NVMTLObjects.m:1020-1075`). WindowServer stesso usa il plugin per comporre, poi il display pipe (§2.6).
- **OpenGL**: nessun driver GL; `IOGLBundleName=AppleMetalOpenGLRenderer` + `NVMTLGL.m` (reflection extra che il renderer GL-su-Metal
  di Apple richiede). **OpenCL**: Apple implementa OpenCL sopra Metal su questi sistemi; il plugin serve i kernel (fix `-[MTLBinding access]`
  nei commenti di `NVMTLDevice.m:36-40`).

Build (`build/build_plugin.sh`): un solo TU (`NVMTLDevice.m` include gli altri), `clang -bundle -fobjc-arc`, link solo `Foundation`,
`Metal`, `IOSurface`; **firma ad-hoc** (`codesign -f -s -`); verifica di "marker" di feature nella binary. NVK e traduttore sono `dlopen`ati.
Conseguenza: un bundle ad-hoc caricato in WindowServer e in ogni app -> servono gli argomenti AMFI (§8).

## 6. Traduttore AIR -> SPIR-V (libnvmtl_translate)

**[VERIFICATO]** `translator/translator/` = crate Rust `metal2vulkan` 0.1.0 (Anees Iqbal, LGPL-3.0-or-later, `Cargo.toml`), *"translates
Metal AIR—LLVM bitcode or sanitized LLVM IR—into Vulkan 1.2 SPIR-V with a native Rust emitter"* (`README.md`); stadi vertex,
post-tessellation vertex, fragment, kernel; reflection (descrittori, function constants, argument buffer). `translator/wrapper/` = cdylib
`nvmtl_translate` con passi extra NullMoth (`buffer_addresses.rs`, `table_ubo.rs`, `wide_loads.rs`, `linearize.rs`, `align_guard.rs`,
`g2_inline.rs`) ed export C (`wrapper/src/lib.rs`): `nvmtl_translate(ll, stage, &out, &len, err, errlen)`, `nvmtl_translate_fc`
(function constants), `nvmtl_reflect(_fc)`, `nvmtl_link_externs/visible/runtime` (linking di funzioni visibili/dinamiche),
`nvmtl_lower_mesh(2)` (mesh shader), `nvmtl_lower_buffer_addresses(_ex/_g2)`, `nvmtl_translate_samplers`, `nvmtl_translate_set_caps`.

Pipeline completa di uno shader (verificata nei sorgenti):

```
metallib ("MTLB" container, NVMTLLibraryLoad.m:652)          [o MSL -> super newLibraryWithSource -> libraryDataContents]
  -> per funzione: AIR bitcode
  -> libLLVM.dylib incluso nel bundle (Contents/MacOS/air-runtime/libLLVM.dylib, NVMTLLibraryLoad.m:420-445)
       LLVMParseBitcodeInContext2 + LLVMPrintModuleToString (+ opz. LLVMRunPasses per unroll / retype GEP)
  -> testo LLVM IR (.ll)
  -> nvmtl_translate() [Rust, metal2vulkan + wrapper]  -> SPIR-V 1.x (Vulkan 1.2)
  -> post-pass C sul SPIR-V nel plugin (nvmtl_readonly_metadata.h: NonWritable; nvmtl_physical_bounds.h: PhysicalStorageBuffer
     OpInBoundsAccessChain -> OpAccessChain; ...)
  -> cache su disco (spvcache, LRU con tetto NVMTL_SPVCACHE_MAX_MB, NVMTLLibraryLoad.m:155-245)
  -> vkCreateShaderModule / pipeline NVK -> NAK -> SASS
```

**Vendor-neutralità [VERIFICATO+INFERITO]**: AIR->SPIR-V non dipende da NVIDIA. I punti NVIDIA-specifici sono a valle (NAK) e in qualche
scelta di layout (binding band fissi `NVMTL_NBUF=32`, `NVMTL_NTEX=128`, `NVMTL_NSAMP=32`, binding 480/640 per storage texture e "address
binding", `nvmtl_vk.c:1774-1787`). Con RADV/ACO il SPIR-V entrerebbe uguale. Rischi per AMD: (1) argument buffer tier 2 / bindless che
mappano su `VK_EXT_mutable_descriptor_type` e buffer device address (RADV li supporta, gfx12 incluso); (2) `simdgroup` = 32 lane su
NVIDIA; su RDNA4 wave32 è nativo ma **RADV di default compila CS, PS e geometria in wave64** (`mesa/src/amd/vulkan/radv_physical_device.c:2836-2851`:
`cs_wave_size = 64` salvo `RADV_PERFTEST=cswave32`, PS wave64 "raccomandato"; solo RT è wave32 di default) [VERIFICATO]. Il layer Metal deve
quindi chiedere `VkPipelineShaderStageRequiredSubgroupSizeCreateInfo{32}` (`VK_EXT_subgroup_size_control`, supportato da RADV) per ogni stadio che
usa `simd_*`/`quad_*` e riportare `threadExecutionWidth`=32; (3) mesh shader: RADV su gfx12 supporta `VK_EXT_mesh_shader`.


## 7. (d) La patch NVK per macOS: winsys e interfaccia kernel

**[VERIFICATO]** `nvk/nvk-macos.patch` (12 183 righe, 81 file, base Mesa `17ca6174`, 26.3-devel); spezzata per file in
`scratchpad/nvidia-deepdive/nvkparts/`. Righe aggiunte per area:

| Area | Righe `+` | File principali |
|---|---:|---|
| **Winsys nvkmd/nvrm (nuovo backend kernel)** | 4 255 | `src/nouveau/vulkan/nvkmd/nvrm/{nvkmd_nvrm_pdev,dev,ctx,mem,va,sync}.c`, `nvRmApi.c`, `nvRmSemSurf.c`, `nvrm_xnu.c`, `nvrm_surfshare_abi.h`, `class/cla26f.h` |
| Core NVK (fix di contratto Metal, memoria, cmd) | 2 373 | `nvk_cmd_buffer.c`, `nvk_cmd_dispatch.c`, `nvk_cmd_draw.c`, `nvk_device_memory.c`, `nvk_image.c`, `nvk_physical_device.c`, `nvk_shader.c`, ... |
| Ray tracing (port RT su NVK) | 1 743 | `nvk_acceleration_structure.c`, `nvk_nir_lower_ray_queries.c`, `nvk_nir_ray_tracing.c`, `bvh/encode.comp` |
| Compilatore NAK | 1 411 | `nak/from_nir.rs`, `legalize.rs`, `sm70_encode.rs`, `qmd.rs`, `nak_nir.c`, ... |
| cubin/ELF minimale per macOS | 333 | `src/nouveau/cubin/macos/nv_libelf_mini.c` (niente libelf su macOS) |
| Hook `nvmtl_*` esportati per il plugin | 161 | `nvmtl_nvk_sass.c`, `nvmtl_cfg.h`, `nvmtl_sample_depth_contract.h` |
| Build | 134 | `meson.build` (BVH builder anche per nouveau, niente SPIRV-Tools Homebrew), `src/nouveau/meson.build` (via `drm/` e `winsys/`) |

### 7.1 Sostituzione del winsys

- Upstream NVK parla con il kernel tramite `nvkmd` ("NVK kernel mode driver" abstraction) con backend `nouveau` (DRM). La patch sostituisce
  `nvkmd_try_create_pdev_for_drm(drmDevice*)` con `nvkmd_enum_pdev(visitor)` -> `nvkmd_nvrm_enum_pdev` (`nvkmd.c` diff) e commenta
  `subdir('drm')`/`subdir('winsys')` (*"macOS has no DRM / libdrm_nouveau; NVK talks to NVRM"*). Il backend `nvrm` deriva dal port Haiku
  (presenza di `nv-haiku.h` e `#ifdef __HAIKU__` in `nvRmApi.c`): **riusa l'idea che un driver Mesa possa parlare con l'RM proprietario
  via le stesse ioctl `NV_ESC_RM_ALLOC/CONTROL/MAP_MEMORY/...` del driver NVIDIA closed**.
- `nvrm_xnu.c` (193 righe, letto per intero) è lo **strato di trasporto** che emula i device node Linux:
  - `nvrm_xnu_open("/dev/nvidiactl"|"/dev/nvidia0")` -> `IOServiceOpen(NVAccel, 0x4E560000|type)` (fallback `NVRM`), poi apre un fd
    segnaposto `open("/dev/null", O_RDONLY)` e lo lega alla connessione con il selettore 3 `SEL_BINDFD` (l'RM usa i numeri di fd come
    identità: `NV_ESC_REGISTER_FD`, mapping con fd). *O_RDONLY perché i sandbox GPU di Safari/Chromium negano `/dev/null` in scrittura*.
  - pool di 128 connessioni riutilizzabili, tabella fd->`io_connect_t` (max 32 768), tabella mapping (16 384).
  - `nvrm_xnu_ioctl(fd, cmd, data, size)` -> `IOConnectCallMethod(conn, SEL_ESC=1, &cmd, 1, data, size, ..., data, &out)` (struct in/out).
  - `nvrm_xnu_mmap(_wc)` -> `IOConnectMapMemory64(conn, 0, ..., kIOMapAnywhere | kIOMapWriteCombineCache)` (il kernel prepara il
    descrittore nel contesto di mapping in `clientMemoryForType`), `nvrm_xnu_munmap` -> `IOConnectUnmapMemory64`.
  - `nvrm_xnu_wait_event(fd, seen, timeout_us)` -> selettore 6 (`sWaitEvent`): attesa bloccante sugli eventi RM al posto di `poll()`
    su fd Linux.
- `nvkmd_nvrm_pdev.c`: interroga l'RM con `NV2080_CTRL_CMD_MC_GET_ARCH_INFO`, `GPU_GET_NAME_STRING`, `NV0080_CTRL_CMD_GPU_GET_CLASSLIST_V2`,
  `GR_GET_INFO_V2`, `GR_GET_GPC_MASK/TPC_MASK`, `FB_GET_INFO_V2`, `FB_GET_SEMAPHORE_SURFACE_LAYOUT`; alloca `HOPPER/TURING/VOLTA_USERMODE_A`
  e mappa la pagina usermode (doorbell). Config da `/Library/GPUBundles/nvmtl/nvrm610.conf` (non da env: le app non hanno env custom).
- `nvkmd_nvrm_ctx.c` (1 155 righe): canale GPFIFO per contesto, **submission interamente in user space**: scrive l'entry GPFIFO
  (`write_gp_fifo_entry`) e suona il doorbell scrivendo il token in `usermodeMap + NVC361_NOTIFY_CHANNEL_PENDING` (`ctx.c` diff righe
  922-923, 1094-1095). Sincronizzazione con semaphore release/acquire in memoria (`write_semaphore_release/acquire`), attesa CPU con
  backoff e `nvrm_xnu_wait_event`. Bind ctx separato per sparse binding.
- `nvkmd_nvrm_sync.c`: `vk_sync_type` propria con `VK_SYNC_FEATURE_TIMELINE|BINARY|GPU_WAIT|CPU_WAIT|CPU_SIGNAL|CPU_RESET|WAIT_PENDING`
  basata su "semaphore surface" RM (`nvRmSemSurf.c`).
- `nvkmd_nvrm_mem.c`: VRAM `NV01_MEMORY_LOCAL_USER` / sysmem `NV01_MEMORY_SYSTEM` con `NVOS32_TYPE_IMAGE`; import host
  (`NV01_MEMORY_SYSTEM_OS_DESCRIPTOR`, pinning di pagine utente nel kext) per `VK_EXT_external_memory_host`/`newBufferWithBytesNoCopy`;
  **import IOSurface** (`nvkmd_nvrm_import_dma_buf`, diff righe 278-310): il plugin prima chiama `nvmtl_nvk_stage_import({surfaceID,plane,size})`,
  poi `vkAllocateMemory` con `VkImportMemoryFdInfoKHR` su un fd fittizio; NVK chiede all'RM l'escape privata `NVRM_ESC_SURF_VRAM (0xE2)`
  (`nvrm_surfshare_abi.h`), che nel kernel diventa `NVAccel::callPlatformFunction("nvSurfVram")` -> `nvAccelSurfVram` -> `NV04_SHARE` del
  memory handle KAPI verso il client RM del processo (`kexts/NVRM/nvrm_surfshare.cpp:22-40`); infine `nvRmApiDupObject`. `NVRM_ESC_SURF_DIRTY (0xE3)`
  segnala quale copia (VRAM vs sysmem) è la più recente. **Zero-copy IOSurface cross-process con un'escape di 2 opcode + dup handle.**

### 7.2 Cosa ci dice per RADV

**[INFERITO, con riferimenti verificati in Mesa]** Lo schema è trasferibile quasi alla lettera:
- RADV ha già un'astrazione winsys: `src/amd/vulkan/winsys/amdgpu/` (libdrm_amdgpu) e `winsys/null/`; NullMoth ha dovuto *creare*
  `nvkmd/nvrm`, noi dovremmo creare `winsys/darwin` (o un `ac_drm` emulato) che implementi `radeon_winsys` (BO create/map/va, CS submit,
  syncobj/timeline, query info). L'equivalente di `nvrm_xnu.c` sarebbe uno shim che mappa le ioctl `DRM_IOCTL_AMDGPU_*` (GEM_CREATE 0x00,
  GEM_MMAP 0x01, CTX 0x02, BO_LIST 0x03, CS 0x04, INFO 0x05, GEM_VA 0x08, WAIT_CS 0x09, ... `include/uapi/drm/amdgpu_drm.h`) su
  `IOConnectCallMethod` di un IOUserClient, con fd segnaposto `/dev/null` per le API che ragionano in fd (syncobj, dma-buf).
- **Submission user-mode**: Linux 7.x ha `DRM_AMDGPU_USERQ (0x16)`, `USERQ_SIGNAL (0x17)`, `USERQ_WAIT (0x18)`
  (`linux/include/uapi/drm/amdgpu_drm.h:57-59,79-81`, `drivers/gpu/drm/amd/amdgpu/amdgpu_userq.c`, `mes_userqueue.c`) per GFX11/12 via MES:
  coda in memoria utente + doorbell (BAR2 da 256 MB su questa scheda) = esatto analogo di GPFIFO+usermode doorbell NVIDIA. Mesa ha helper
  userq in `src/amd/common/ac_linux_drm.c` (grep), ma RADV in questo tree non li usa ancora (grep vuoto in `src/amd/vulkan`). Strategia
  iniziale più semplice: submission via ioctl tipo `AMDGPU_CS` verso il kext (che scrive nel ring kernel o in una coda MES), poi user
  queues come ottimizzazione.
- **IOSurface import** su AMD: stesso trucco "staged import" + `VK_EXT_external_memory_dma_buf`/`opaque_fd` di RADV con un
  `radeon_winsys::buffer_from_fd` che invece di un dma-buf risolve `{surfaceID, plane}` via escape del kext acceleratore. Attenzione al
  **tiling**: le IOSurface di WindowServer/CoreAnimation sono lineari; RADV su gfx12 deve usare `ADDR3_LINEAR`/`DRM_FORMAT_MOD_LINEAR`; per le surface 2D lineari
  addrlib gfx12 usa pitch 128 B di default e Mesa lo forza a 256 B (`LINEAR_PITCH_ALIGNMENT`) per interop multi-GPU
  (`mesa/src/amd/common/ac_surface.c:3969-3977`) [VERIFICATO]: il kext deve quindi allocare le IOSurface con `bytesPerRow` multiplo di 256
  (CoreAnimation di norma allinea a 64 B: da verificare su macOS) [INFERITO]. NullMoth richiede pitch multiplo di 32 per NVIDIA (`NVMTLDevice.m:703`).


## 8. (e) Installazione: AuxKC, kmutil, SIP, AMFI, SecureBootModel, SMBIOS, ResizeGpuBars

### 8.1 Dove finiscono i file (`package/install.sh`, letto)

| Cosa | Path | Note |
|---|---|---|
| 4 kext | `/Library/Extensions/{NVRM,NVAccel,NVRMFB,NVRMAGDC}.kext` (`install.sh:8-9`) | `root:wheel`, 755; NVAccel scelto per OS da `/Library/NullMoth/kexts/{15,26}/` (`:88-90`, `:183-191`) |
| Plugin Metal | `/Library/GPUBundles/NVMTLDriver.bundle` | contiene `libnvmtl_translate.dylib` e `air-runtime/libLLVM.dylib` |
| NVK | `/Library/GPUBundles/nvmtl/` (`libvulkan_nouveau.dylib`, `nvk_icd.json`, `libvulkan.dylib`, `nvrm610.conf`) | |
| Compilatore vendor opzionale | `/Library/GPUBundles/NVIDIAShared.bundle` | |
| Allow-list | `/Library/GPUBundles/nvmtl-allow.txt` (644, verificata leggibile da `_windowserver`: `sudo -u _windowserver /bin/test -r`, `:202`) | |
| Firmware GSP | `/Users/Shared/nvfw/nvidia/610.57.04/` | letto dal kext via `vnode_open` |

**Auxiliary Kernel Collection** (`install.sh:10-16,158-210`): i kext NON sono iniettati da OpenCore perché *"the display kexts link against
Apple frameworks (IOGraphicsFamily, IOAcceleratorFamily2) that only exist in macOS's own kernel collections"* (`docs/HOW-IT-WORKS.md:54-56`).
Procedura:
1. preflight in una repo temporanea con `chown -R root:wheel` (*"macOS 26 kmutil silently skips kexts not owned by root"*, `:158`);
2. `kmutil create -n aux --volume-root / --allow-missing-kdk [--kernel /System/Library/Kernels/kernel] -B BootKernelExtensions.kc
   -S SystemKernelExtensions.kc --repository <repo> -A <out.kc> -z` (`:160`; `--allow-missing-kdk` perché da macOS 13 kmutil vuole il KDK);
3. `kmutil inspect -a x86_64 -A <kc>` e verifica che ci siano i 4 bundle id `com.nullmoth.*` (`:162-163`);
4. build reale da `/Library/Extensions` e `mv` atomico su `/Library/KernelCollections/AuxiliaryKernelExtensions.kc` (`:204-209`);
5. reboot obbligatorio; al primo avvio approvazione in *Impostazioni > Privacy e sicurezza*, poi altro reboot.
Durante un aggiornamento macOS l'NVAccel specifico per OS viene "parcheggiato" con una voce `Kernel > Block` e un LaunchDaemon
`com.nullmoth.osupdate` lo ricostruisce dopo (`app/Resources/nullmoth-setup.sh:374,597-602`).

### 8.2 OpenCore e firmware (README §Wiring, `docs/HOW-IT-WORKS.md:74-89`, `nullmoth-setup.sh`)

| Impostazione | Valore | Perché |
|---|---|---|
| `csr-active-config` | `<430A0000>` = `0x0A43` (`nullmoth-setup.sh:24 SIP_BITS=$((0x0A43))`) | [bit da `xnu/bsd/sys/csr.h`, non verificati localmente] `0x1 ALLOW_UNTRUSTED_KEXTS` + `0x2 ALLOW_UNRESTRICTED_FS` + `0x40 ALLOW_UNRESTRICTED_NVRAM` + `0x200 ALLOW_UNAPPROVED_KEXTS` + `0x800 ALLOW_UNAUTHENTICATED_ROOT` |
| `boot-args` | `nvfb=1 nvaccel=1 nvfbheads=4 -nvkmsnosmooth amfi_get_out_of_my_way=0x1 amfi=0x80 ipc_control_port_options=0` | `nvfb/nvaccel` = gate anti boot-loop dei kext; argomenti AMFI = WindowServer può caricare il bundle ad-hoc; `ipc_control_port_options=0` evita crash di Firefox e app hardened con AMFI rilassato (`nullmoth-setup.sh:4-6`, stessa scelta di OCLP) |
| **Lilu + AMFIPass.kext** (in `EFI/OC/Kexts`, AMFIPass dopo Lilu) | obbligatori | non nel README ma imposti dal setup (`nullmoth-setup.sh:704-723`, `tools/test_amfipass_required.py`): senza AMFIPass WindowServer rifiuta il plugin con *"mapping process is a platform binary, but mapped file is not"* -> schermo nero con cursore |
| `Misc > Security > SecureBootModel` | `Disabled` | Apple Secure Boot rifiuta kext non firmati Apple |
| `UEFI > Quirks > ResizeGpuBars` | `13` (8 GB) | banda piena; NVRM poi riloca BAR1 lontano dal boot screen |
| `Booter > Quirks > ResizeAppleGpuBars` | `-1` | macOS vede la BAR intera |
| `Kernel > Block` | `com.apple.iokit.IONDRVSupport`, `Exclude` | altrimenti il framebuffer firmware prende display index 0 |
| BIOS | Above 4G Decoding ON, CSM OFF | BAR sopra 4 GB |
| SMBIOS | Mac con dGPU supportato da macOS 15 (testato `iMacPro1,1`) | — |
| `NVRAM > Delete` | tutte le chiavi sopra | riscritte a ogni boot |
| Rimuovere | `nv_disable=1`, patch WEG NVIDIA, `agdpmod=pikera` | — |
| Installer macOS | valori **opposti**: `ResizeAppleGpuBars=0`, `ResizeGpuBars=-1`, IONDRVSupport non bloccato | l'installer non ha driver e vive sul framebuffer firmware, che sopravvive al setup PCI solo con BAR piccola |

Recovery: entry OpenCore `NullMothSafe.efi` (Rust UEFI, `app/efi-safe/`) aggiunge `-nvoff` e `nullmoth-remove=1`; al boot il LaunchDaemon
`com.nullmoth.recover` disinstalla (`docs/HOW-IT-WORKS.md:118-121`). Tutti i kext controllano `nvrm_driver_off()` (`kexts/*/nvrm_off.h`).

**Adattamenti per la RX 9060 XT [INFERITO]**:
- AuxKC + `/Library/Extensions` è obbligatorio anche per noi se i kext linkano IOAcceleratorFamily2/IOGraphicsFamily (stesso motivo).
- ReBAR: la scheda ha già BAR0 = 16 GB (tutta la VRAM) e BAR2 = 256 MB doorbell (hw facts); con `ResizeAppleGpuBars=-1` macOS deve
  accettare una BAR0 da 16 GB: va verificato che IOPCIFamily la allochi sopra 4 GB senza conflitti. Nota: la nostra scheda sta dietro lo
  switch PCIe interno della GPU (upstream/downstream port), quindi anche le finestre dei bridge devono essere dimensionate dal firmware.
- Il problema "boot screen dentro la BAR" esiste anche su AMD: il GOP disegna in VRAM tramite BAR0; il nostro kext dovrà prendere in
  carico lo scanout DCN dal firmware (o lasciarlo) prima che WindowServer parta (stesso boot-hold con `adjustBusy`).
- SMBIOS: `iMacPro1,1` è supportato da Sequoia ma **non** da Tahoe [conoscenza generale, non verificato qui]; per un percorso Tahoe servirà
  `MacPro7,1` (Mac con GPU AMD discrete supportato da Tahoe), che è anche la scelta tipica degli Hackintosh AMD.

## 9. (f) Pezzi vendor-neutral riusabili per AMD/RADV e implicazioni di licenza

### 9.1 Classificazione componente per componente

| Componente NullMoth | Vendor-neutral? | Riuso per AMD | Licenza | Implicazione |
|---|---|---|---|---|
| `kexts/NVRM/accel/re/*.h`, `iofam/*.h` (layout ricostruiti di IOAcceleratorFamily2) | **Sì** (sono header Apple ricostruiti) | Molto alto: stesse classi; per AMD conviene ricostruire/validare contro `AMDRadeonX6000.kext` | PolyForm NC | fatti di interoperabilità (offset, ordine vtable) non sono di per sé protetti, ma copiare i file sì: **ri-derivare** in autonomia con lo stesso metodo (gen_virtuals da IOAcceleratorFamily2 + simboli AMDRadeonX*) |
| `nvrm-accel.cpp` logica di NVAccel (gating MetalPluginName, display machine, display pipe, carriers) | Per lo più sì (le chiamate RM sono isolate in `callPlatformFunction`) | Alto come *design*; il codice usa RM/NVKMS per VRAM e flip | PolyForm NC | reimplementare (clean-room dal comportamento documentato in questo report) |
| `NVRMFB` IOFramebuffer | Metà: la parte IOFramebuffer sì, il backend NVKMS no | Struttura sì, backend da scrivere su DCN 4.0.1/DMUB | PolyForm NC | reimplementare |
| `NVRMAGDC` | Quasi tutto (cambia vendorID/nome) | Alto | PolyForm NC | reimplementare (è piccolo, 483 righe) |
| `NVRM` core + OS layer XNU | No (RM NVIDIA) | Solo pattern: user client = device node, boot hold, firmware da file, BAR move | PolyForm NC + MIT/GPL (RM) | — |
| Plugin `NVMTLDriver.bundle` (Metal su Vulkan) | **Quasi del tutto** (~33 righe NV in `nvmtl_vk.c` + 5 hook NVK) | Altissimo tecnicamente: girerebbe su RADV con un altro `dlopen` e hook equivalenti | **PolyForm NC** | utilizzabile/modificabile solo per scopi non commerciali, obbligo di includere i termini e la riga `Required Notice: Copyright (c) 2026 NullMoth Systems` (`LICENSE:75`); un fork AMD non commerciale è lecito, ma resterebbe NC per sempre per quelle parti. Per un progetto potenzialmente redistribuibile liberamente conviene **non** derivarne codice e usare invece l'architettura |
| Traduttore `metal2vulkan` + wrapper | **Sì** | Altissimo | **LGPL-3.0-or-later** | riusabile anche in progetti non-NC: va distribuito come libreria dinamica sostituibile (è già `libnvmtl_translate.dylib`), sorgenti delle modifiche alla libreria disponibili; il plugin che la `dlopen`a non è contaminato. Upstream: `github.com/steelbrain/metal2vulkan` (preferire l'upstream alle modifiche NullMoth se servono licenze pulite; le modifiche NullMoth al translator sono anch'esse LGPL per `NOTICE`) |
| Post-pass SPIR-V nel plugin (`nvmtl_readonly_metadata.h`, `nvmtl_physical_bounds.h`, ...) | Sì | Sì | PolyForm NC | reimplementare (piccoli) |
| Patch NVK | No per backend/NAK; **sì come schema** (nvkmd backend su IOKit) | Schema per `radv/winsys/darwin` | **MIT** | liberamente riusabile anche il codice (es. `nvrm_xnu.c`: pool di connessioni, fd segnaposto, mapping table) |
| `libLLVM.dylib` nel bundle | Sì | Sì | Apache-2.0 w/ LLVM exception | ok |
| App 1401 / install.sh / NullMothSafe.efi | Sì (OpenCore, AuxKC, recovery) | Alto come procedura | PolyForm NC | reimplementare; la *procedura* (AuxKC, SIP, AMFIPass, recovery entry) non è proteggibile |

### 9.2 Lezioni vendor-neutral (il "contratto" macOS per una GPU di terze parti)

1. **Un `IOGraphicsAccelerator2` sull'`IOPCIDevice`** con `IOMatchCategory=IOAccelerator`, `MetalPluginName` (path relativo a
   `/System/Library/Extensions`) e `MetalPluginClassName`. 17 metodi puri da implementare; tutto il resto lo dà la famiglia.
2. **Un plugin che eredita `MTLIOAccelDevice`** e risponde a `initWithAcceleratorPort:`; gli altri oggetti possono essere `NSObject`
   conformi ai protocolli pubblici + rete di forwarding per le SPI private.
3. **Front-end MSL dal sistema** (`super newLibraryWithSource:` -> MTLCompilerService), **back-end proprio** (AIR -> SPIR-V -> ISA).
4. **IOSurface come valuta comune**: la VRAM degli IOSurface deve essere allocata dalla famiglia (via `IOAccelVidMemory::allocPhysical`
   del vendor) ed esportabile al driver user-space di ogni processo (escape kernel + dup handle).
5. **Presentazione WindowServer = display pipe transactions** su un `IOAccelLegacyDisplayPipe` legato a un `IOFramebuffer` vero
   (`found_framebuffer`), con flip zero-copy o copia; `IOAccelDisplayPipeCapabilities` pubblicato solo quando pronto.
6. **Gating**: niente `MetalPluginName` finché il display non è armato; allow-list per processo; boot-arg di abilitazione; boot hold
   (`adjustBusy`) fino a GPU pronta; sysctl per abilitare ogni stadio; entry di recovery nel boot picker.
7. **AGDC shim** per la display policy (vendor info + mappa framebuffer).
8. **Firma**: bundle ad-hoc in WindowServer (platform binary) => SIP rilassato + `amfi_get_out_of_my_way=0x1 amfi=0x80` + **AMFIPass**.


## 10. Blueprint architetturale per l'equivalente AMD (diagramma ASCII + mappa componenti)

### 10.1 Verifica preliminare eseguita: RADV su questa macchina copre il contratto Vulkan del plugin NullMoth

**[VERIFICATO, test non privilegiato]** Dump `vulkaninfo` già presente in `scratchpad/mesa-radv/vulkaninfo_full.txt` (sezione GPU0
estratta in `scratchpad/nvidia-deepdive/gpu0_vkinfo.txt`): `AMD Radeon RX 9060 XT (RADV GFX1200)`, Mesa 26.3.0-devel (git-8ea6e9dd41),
Vulkan 1.4.363. **Tutte** le 14 estensioni che `nvmtl_vk.c:637-643` cerca sono esposte da RADV su GFX1200
(`VK_EXT_extended_dynamic_state3`, `VK_EXT_depth_clip_enable`, `VK_EXT_memory_budget`, `VK_KHR_acceleration_structure`, `VK_KHR_ray_query`,
`VK_KHR_deferred_host_operations`, `VK_EXT_external_memory_host`, `VK_EXT_image_drm_format_modifier`, `VK_KHR_external_memory_fd`,
`VK_EXT_mutable_descriptor_type`, `VK_KHR_cooperative_matrix`, `VK_EXT_calibrated_timestamps`, `VK_EXT_sample_locations`,
`VK_KHR_pipeline_executable_properties`), più `VK_EXT_subgroup_size_control`, `VK_EXT_mesh_shader`, `VK_EXT_external_memory_dma_buf`.
Sottogruppi: `subgroupSize = 64` (default), `minSubgroupSize = 32`, `maxSubgroupSize = 64`, `requiredSubgroupSizeStages` 4 stadi;
`sparseBinding/sparseResidencyImage2D = true`. Conclusione: **il front-end "Metal su Vulkan" non ha bisogno di funzionalità che RADV su
gfx1200 non abbia già su Linux**; il lavoro AMD-specifico è tutto sotto Vulkan (winsys macOS) e nel kernel.

### 10.2 Diagramma componenti

```
                         ┌──────────────────────────── user space (ogni processo Metal, WindowServer incluso) ─────────────────────────┐
 Metal app / CoreAnimation / CoreImage / MPS / GL-on-Metal (Apple) / OpenCL-on-Metal (Apple)
        │  MTLCreateSystemDefaultDevice -> registry: IOAccelerator{MetalPluginName, MetalPluginClassName}
        ▼
 ┌──────────────────────────────────────────────┐     ┌───────────────────────────────────────┐
 │ AMDMTLDriver.bundle  (/Library/GPUBundles)   │     │ libamdmtl_translate.dylib             │
 │  AMDMTLDevice : MTLIOAccelDevice             │────▶│  metallib/AIR -> (libLLVM) .ll ->     │
 │   initWithAcceleratorPort:, allow-list,      │     │  metal2vulkan (LGPL) -> SPIR-V        │
 │   forward-net SPI, IOSurface textures,       │     │  + post-pass (wave32, bindless, ...)  │
 │   encoders -> Vulkan calls (RADV API)        │     └───────────────────────────────────────┘
 │  newLibraryWithSource -> super (MTLCompiler- │
 │   Service: MSL->AIR) -> libraryDataContents  │
 └───────────────┬──────────────────────────────┘
                 │ dlopen + vk_icdGetInstanceProcAddr (+ hook privati amdmtl_radv_*: stage_import, surface_dirty)
                 ▼
 ┌──────────────────────────────────────────────┐
 │ libvulkan_radeon.dylib (RADV + ACO, Mesa)    │  SPIR-V -> NIR -> ACO -> ISA gfx1200 (wave32 forzato per stadi simd)
 │  winsys/darwin (NUOVO, ~ nvkmd/nvrm)         │  BO alloc/map/VA, CS submit, timeline sync, info query
 │   amdgpu_xnu.c (~ nvrm_xnu.c): ioctl DRM_AMDGPU_* -> IOConnectCallMethod, fd segnaposto, mmap -> IOConnectMapMemory64
 └───────────────┬──────────────────────────────┘
                 │ IOServiceOpen(AMDAccel, 'AM'<<16|type)   (passa dall'IOAccelerator per i sandbox)
═════════════════╪══════════════════════════════════════════════ kernel (Auxiliary KC, /Library/Extensions) ═══════════════════════════
                 ▼
 ┌──────────────────────────────┐  callPlatformFunction(ABI versionate)  ┌──────────────────────────────────────────┐
 │ AMDAccel.kext                │◀──────────────────────────────────────▶│ AMDGPUCore.kext (~ NVRM)                 │
 │  AMDAccel : IOGraphics-      │  "amdNewAccelClient", VRAM alloc,      │  IOPCIDevice 1002:7590, BAR0 16G/BAR2/5  │
 │   Accelerator2 (17 puri)     │  GPU VA map, surface share, flip       │  boot hold (adjustBusy), firmware da file│
 │  AMDEventMachine, AMDTask,   │                                        │  PSP 14.0.2 (sos/ta, TOC) -> SMU 14.0.2  │
 │  AMDMemoryMap, AMDResource,  │                                        │  GMC 12 (VM 4 livelli), IH 7, GFX 12     │
 │  AMDVidMemory (VRAM BAR0),   │                                        │  (RLC/IMU/ME/PFP/MEC), MES 12, SDMA 7,   │
 │  AMDDisplayMachine/Pipe      │                                        │  user client = "/dev/dri/renderD128"     │
 │  (display pipe transactions) │                                        │  (ioctl AMDGPU_* via externalMethod)     │
 │  carriers per user client    │                                        └──────────────┬───────────────────────────┘
 └───────────┬──────────────────┘                                                       │
             │ found_framebuffer / scanout / flip                                       │ DCN 4.0.1 + DMUB fw 0x0A004B00
             ▼                                                                          ▼
 ┌──────────────────────────────┐   ┌──────────────────────────────┐   ┌──────────────────────────────────────────┐
 │ AMDFB.kext                   │   │ AMDAGDC.kext                 │   │ (opz.) AMDHDA: audio HDMI/DP 03:00.1     │
 │  AMDFramebuffer : IOFrame-   │   │  AMDDeviceControl : Apple-   │   │  1002:ab40                               │
 │   buffer x3 (DP-1, HDMI-A-1, │   │   GraphicsDeviceControl      │   └──────────────────────────────────────────┘
 │   HDMI-A-2), EDID, modi, VBL │   │  cmd 1 (vendor 0x1002),      │
 │  AMDFBClaim (score 30000)    │   │  0x980 (mappa FB), 0x921/0x711│
 └──────────────────────────────┘   └──────────────────────────────┘
                                         │
                                         ▼  Radeon RX 9060 XT (Navi 44, GC 12.0.0 gfx1200, 32 CU, 16 GB GDDR6)
```

### 10.3 Mappa componente AMD <-> controparte NVIDIA

| # | Componente AMD proposto | Controparte NullMoth | Riuso | Specificità Navi 44 / GC 12.0.0 / DCN 4.0.1 |
|---|---|---|---|---|
| 1 | `AMDGPUCore.kext` (init HW, firmware, VM, code, IRQ, user client) | `NVRM.kext` (RM r610 + os-xnu) | solo pattern (boot hold, firmware da file, user client = device node, BAR) | IP discovery: GC 12.0.0, PSP/SMU 14.0.2, SDMA 7.0.0, IH 7.0.0, MMHUB/ATHUB 4.1.0, HDP 7.0.0, NBIF 6.3.1; firmware `gc_12_0_0_{imu,me,mec,mes,mes1,pfp,rlc,toc,uni_mes}`, `psp_14_0_2_{sos,ta}`, `smu_14_0_2`, `sdma_7_0_0`, `dcn_4_0_1_dmcub`, `vcn_5_0_0`. **Navi 48 usa `gc_12_0_1_*` (+ `_kicker`)**: non intercambiabili |
| 2 | `AMDAccel.kext` (`IOGraphicsAccelerator2`) | `NVAccel.kext` | design 1:1 (17 puri, gating, display pipe, carriers, surface share) | VRAM CPU-visibile tutta via BAR0 16 GB (ReBAR): `getApertureMemoryDescriptor` banale; GPU VA da GMC v12 (4 livelli, blocco 9 bit) |
| 3 | `AMDFB.kext` (`IOFramebuffer` per connettore) | `NVRMFB.kext` (NVKMS KAPI) | struttura 1:1, backend nuovo | DCN 4.0.1 (DMU 4.1.0 in discovery) + DMUB `0x0A004B00`; connettori DP-1, HDMI-A-1, HDMI-A-2; VBL da IH (DCN vline/vupdate) |
| 4 | `AMDAGDC.kext` | `NVRMAGDC.kext` | quasi 1:1 | `vendorID=0x1002`, `maxFramebuffers=3` |
| 5 | `AMDMTLDriver.bundle` | `NVMTLDriver.bundle` | architettura 1:1; codice NullMoth utilizzabile solo NC | `threadExecutionWidth=32` + `requiredSubgroupSize=32`; limiti da RADV verificati su GPU0: `maxComputeWorkGroupInvocations=1024`, `maxComputeSharedMemorySize=65536` (Metal: `maxThreadsPerThreadgroup`=1024, `maxThreadgroupMemoryLength`=32 KB nella Metal Feature Set Table [non verificato qui]: 64 KB è un superset) |
| 6 | `libamdmtl_translate.dylib` | `libnvmtl_translate.dylib` | **riuso diretto possibile (LGPL)** | nessuna (SPIR-V portabile); tuning ACO a valle |
| 7 | RADV + `winsys/darwin` | NVK + `nvkmd/nvrm` + `nvrm_xnu.c` | schema 1:1, codice NVK MIT riusabile per il trasporto | ioctl `DRM_AMDGPU_*` (0x00-0x1A), `GEM_CREATE` domini VRAM/GTT, `CS` su ring GFX/compute/SDMA o `USERQ` (0x16-0x18) via MES (gfx `hqd_mask 0xfe`, compute `0x0c`, sdma `0xfc` dai dmesg) |
| 8 | Installer + recovery EFI | `install.sh`, 1401, `NullMothSafe.efi` | procedura 1:1 | stesse impostazioni OpenCore; SMBIOS `MacPro7,1`/`iMacPro1,1` secondo la versione macOS |

### 10.3b Cosa cambia tra Navi 44 (nostro target) e Navi 48 (Cobalt64 / R9700) in questo blueprint

| Aspetto | Navi 44 — RX 9060 XT (questa macchina) | Navi 48 — RX 9070/9070 XT/R9700 | Impatto sui componenti |
|---|---|---|---|
| PCI ID | `1002:7590` rev `c0` (hw facts) | `1002:7550`/`7551`... [conoscenza generale] | match `IOPCIPrimaryMatch` dei kext |
| GC / ISA | GC 12.0.0, `gfx1200` | GC 12.0.1, `gfx1201` | ACO/RADV distinguono già i due; il traduttore SPIR-V è identico |
| Firmware GC/MES/IMU | `gc_12_0_0_{imu,me,mec,mes,mes1,pfp,rlc,toc,uni_mes}` | `gc_12_0_1_*` + varianti `_kicker` (`imu_v12_0.c:35-37`, `gfx_v12_0.c:73-82`, `mes_v12_0.c:36-41`) [VERIFICATO] | core kext: tabelle firmware per-ASIC; la lista "kicker" (`amdgpu_ucode.c:33-36`: `{0x744B,0x00}`, `{0x7551,0xC8}`) **non** include `7590`, quindi niente kicker per noi [VERIFICATO] |
| PSP / SMU | MP0/MP1 14.0.2, `psp_14_0_2_{sos,ta}`, `smu_14_0_2` | 14.0.3 (`psp_14_0_3_*` + `_kicker`, `psp_v14_0.c:36-39`) [VERIFICATO per i nomi file] | core kext: bootstrap PSP diverso solo nei blob |
| Shader engine | 2 SE x 2 SH x 8 CU = 32 CU, 8 RB, `gb_addr_config 0x08200545` | 64 CU, 256-bit [conoscenza generale] | nessun impatto sul contratto Metal; limiti/occupancy diversi |
| VRAM / BAR | 16 GB GDDR6 128-bit, BAR0 = 16 GB (ReBAR), BAR2 256 MB doorbell, BAR5 512 KB MMIO | 16/32 GB 256-bit [conoscenza generale] | AMDAccel: aperture e VA identiche nel principio |
| Display | DCN 4.0.1 (DMU 4.1.0 in discovery), DMUB `dcn_4_0_1_dmcub` 0x0A004B00, DP-1 + 2x HDMI | DCN 4.0.1 [conoscenza generale] | AMDFB condivisibile tra le due schede |

### 10.4 Ordine di costruzione suggerito (derivato dalla sequenza NullMoth "rung"/"K")

1. Core kext che fa probe/claim, BAR, boot hold con timeout e `-amdoff` (nessuna scrittura HW): verifica di boot sicuro.
2. Init HW minimo fino a GMC+IH+PSP+SMU (+ MES/GFX), con log via `kprintf`/sysctl; user client con `AMDGPU_INFO` per far partire RADV
   `vkEnumeratePhysicalDevices` in un tool CLI (come `nvmtltest`/`mtlprobe` nell'allow-list NullMoth).
3. RADV `winsys/darwin`: BO, VA, submit, fence -> compute headless (vkCompute) da CLI.
4. AMDFB su DCN: un modo fisso, poi EDID/modi/VBL; NVRMFBClaim-equivalente per battere `IONDRVFramebuffer`.
5. AMDAccel con `MetalPluginName` trattenuto; display machine + display pipe con copia CPU; poi flip zero-copy.
6. Plugin Metal ristretto da allow-list (prima `mtlprobe`, poi app, per ultimo WindowServer), AGDC, quindi WindowServer.


## 11. Rischi, blocchi e domande aperte

### 11.1 Rischi tecnici evidenziati dall'esperienza NullMoth

1. **ABI privata Apple fragile**: IOAcceleratorFamily2, `MTLIOAccelDevice`, `AppleGraphicsDeviceControl` non hanno header; layout e slot
   vtable vanno ricostruiti per **ogni** major macOS (NullMoth già spedisce due NVAccel, 15 e 26, `install.sh:86-90`; su Tahoe metodi
   ereditati sono diventati privati, `tahoe_fwd.h`). Un errore di slot = panic silenzioso. Mitigazione: generatori automatici + `static_assert`
   sulle size, come `gen_stubs.py`/`gen_tahoe_fwd.py`.
2. **Offset magici**: `populateAccelConfig` scrive 0x70 byte a offset non documentati (`nvrm-accel.cpp:180-206`); NVAccel legge campi interni
   della famiglia per offset (`accel+0xc78`, `dm+0x108`, `pipe+0x98`, `res+0x88`, `vidmem+0x40/+0xc8`, `surface+0x11B0/0x11C0`): vanno
   ri-misurati per ogni build di macOS. Per AMD il riferimento naturale è il comportamento di `AMDRadeonX6000` (stesso pattern "as AMD's does").
3. **Ordinamento presentazione**: il kernel non sa attendere il fence user-space -> WindowServer deve fare `waitUntilCompleted`
   (`NVMTLObjects.m:4563-4573`): costo di latenza. Su AMD conviene progettare subito un fence kernel-visibile (seqno EOP in memoria GART)
   che il display pipe possa attendere.
4. **Sicurezza ridotta**: SIP `0x0A43`, AMFI disattivato, AMFIPass, SecureBootModel Disabled: ogni utente del driver gira con macOS
   fortemente indebolito. Inevitabile finché il bundle non è firmato da Apple.
5. **Boot screen / BAR**: il passaggio dal framebuffer firmware al driver è il punto più fragile (boot hold, 100 s di attesa in small-BAR,
   `IONDRVSupport` bloccato, installer con impostazioni opposte).
6. **Sandbox**: user client aperti passando dall'IOAccelerator, fd `/dev/null` O_RDONLY, config da file e non da env: dettagli emersi
   solo con Safari/Chromium/Firefox reali.
7. **Licenza**: il plugin (la parte più preziosa e vendor-neutral) è PolyForm Noncommercial; un port AMD derivato erediterebbe il vincolo NC.
   Il traduttore (LGPL) e le patch NVK (MIT) sono riusabili liberamente.
8. **Scala dello sforzo lato kernel**: NullMoth ha riusato l'intero RM NVIDIA (sorgenti esterni al repo, `OGKM=$HOME/ogkm610` in
   `build/accel_build.sh`) con ~3.9k righe di strato OS XNU; per AMD l'equivalente è `amdgpu`, Linux-specifico e accoppiato IP per IP
   (`research/notes/amdgpu_sloc.txt` [VERIFICATO]: core comune 26 113 righe .c, IP gfx12 totali 11 546 — `gfx_v12_0.c` 4 443, `mes_v12_0.c` 1 661,
   `sdma_v7_0.c` 1 260, `gmc_v12_0.c` 761, `psp_v14_0.c` 513, `ih_v7_0.c` 563 —, swsmu core+smu14_0_2 8 239, **DC 414 947** di cui dcn401 14 615 e
   DMUB srv 4 898). Il display (DC) è da solo più grande di tutto il resto: è il blocco principale per un desktop WindowServer.
9. **Wave size**: RADV compila CS/PS in wave64 di default (verificato), Metal assume simdgroup=32 -> va forzato wave32 per stadio.
10. **Validazione limitata anche in NullMoth**: fisicamente solo RTX 5060 su 15.7.x/15.8.1 (`docs/CARD-SUPPORT.md:11-16`), Tahoe non
    qualificato: le soluzioni sono empiriche e possono non generalizzare.

### 11.2 Domande aperte (richiedono macOS installato o dati privilegiati)

- Layout esatto di `IOGraphicsAccelerator2`/`IOAccelDisplayPipe`/`IOAccelResource2` sulla versione macOS target (15.x vs 26.x): richiede
  il binario `IOAcceleratorFamily2.kext` della versione scelta (e `AMDRadeonX6000.kext` come riferimento AMD).
- Quale versione macOS è il target (Sequoia 15.x come NullMoth, o Tahoe 26)? Determina SMBIOS (`iMacPro1,1` vs `MacPro7,1`) e set di
  header ricostruiti.
- `MetalPluginName` relativo (`../../../Library/GPUBundles/...`): comportamento verificato da NullMoth su 15.x; da riconfermare su 26.x.
- Il bundle AMD di Apple per RDNA2 (`AMDRadeonX6000MTLDriver.bundle`, compilatore AIR->gfx10.3) potrebbe essere usato come "corsia vendor"
  analoga a `NVIDIAShared.bundle`? Probabilmente no per gfx12 (ISA diversa), ma i suoi selettori SPI sono la documentazione migliore.
- Con ReBAR a 16 GB, IOPCIFamily/OpenCore (`ResizeAppleGpuBars=-1`) assegnano davvero la BAR0 intera e le finestre del PCIe switch interno
  della Navi 44? Da verificare su hardware con macOS (log `ioreg -l` di IOPCIDevice e bridge).
- Il GOP firmware della Sapphire 1DA2:A493 lascia lo scanout DCN in uno stato riutilizzabile (modo/pitch/indirizzo in VRAM leggibili da
  registri DCN) per un "takeover" senza modeset, analogo a `snapshotBootScreen()`/`measureBootRaster()` di NVRM?
- Dati privilegiati utili da Linux (non raccolti, richiedono root/debugfs): `amdgpu_regs` DCN HUBP surface address/pitch del boot
  framebuffer, `amdgpu_firmware_info` già presente, dump `amdgpu_vm_info` per un processo, eventuale dump IH ring per i vector VBL.

