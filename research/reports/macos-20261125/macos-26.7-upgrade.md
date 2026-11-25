# macOS 26.6.2 to 26.7.x upgrade evaluation

Date: 2026-11-25. Read-only evaluation. Nothing was installed, downloaded, built, edited or committed.
Machine: Ryzen 7 7700, RX 9060 XT (Navi 44), OpenCore, macOS Tahoe 26.6.2 (build 25G83).

Sources checked: the repo (`docs/STATUS.md`, `README.md`, `cobalt64/tools/native/navi48metal/`, `cobalt64/src/navi48-bringup/`,
`cobalt64/tools/native/navi48accel/`, `cobalt64/third-party/rdna4fb-n44/`, `tools/baremetal/navi44-desktop/`, the newest
generated OpenCore config under `research/builds/macos-20261123/`), `research/reports/macos-20261125/vermilion-audit.md`,
`research/ext/vermilion`, `research/refs/nvidia-macos-driver`, and public Apple security pages and hackintosh reports.

Note on the working tree: `git status` shows uncommitted modifications in `cobalt64/tools/native/navi48metal/` (including
`Navi48Device.m`, which changed while it was being read). Line numbers below are from the working tree as it was on
2026-11-25 and may shift. Also, `docs/STATUS.md` says kernel 0.0.675 is installed, while the newest generated config loads
0.0.681. Confirm which Navi48Bringup is on the machine before any update.

## 1. Verdict

**Do not upgrade now. Stay on 26.6.2 (25G83) for the moment, and treat 26.7.x as a port project, not a point update.**

- **Confidence the stack breaks on 26.7.x: high.** At least three checks fail closed (the activation daemon, the Navi48Accel
  layout gate and the AGDC address path), so the accelerated desktop would be off or refused. Several others fail silently
  (scanout classification by symbol name, spvcache hashes, unguarded IOSurface offsets), which can produce a black or
  frozen screen with no error.
- **Security cost of staying: real.** 26.6.2 lacks the 26.7.1, 26.7.2 and 26.7.3 fixes. The most serious one for this
  stack is in IOAcceleratorFamily, IOGPUFamily, GPU Drivers and IOSurface (26.7.2). 26.7.1 also fixes a CoreGraphics
  out-of-bounds write that press reports as exploited in the wild. The machine is local and not exposed, which lowers the
  practical risk, but the gap should be known and accepted on purpose.
- The Vermilion user's black screen on 26.7.3 has no recorded cause in any source we have. Treat it as an unknown until
  someone reads the issue and its comments.

## 2. Dependency inventory (what a point update can break)

### 2a. Metal bundle (`cobalt64/tools/native/navi48metal/`)

Verified by reading the code. Line numbers are approximate, because `Navi48Device.m` is being edited.

| Where | Dependency | If 26.7.x changes it | Confidence it breaks |
|---|---|---|---|
| `Navi48Device.m:83-114` | Subclasses private Metal classes `MTLIOAccelDevice`, `_MTLResource`, `_MTLHeap`, `_MTLCommandQueue`, `_MTLCommandBuffer`, `_MTLCommandEncoder`, `_MTLRenderPipelineState`. Linked as `_OBJC_CLASS_$_` through `-framework Metal`. | A class no longer exported stops the bundle loading at dyld (no acceleration). Ivar changes are absorbed by the non-fragile ABI. | Medium (only if Apple removes or renames a class) |
| `Navi48Device.m:85-108, 4867, 5192, 5622, 6157, 6317, 4933-4972, 5129` | Private initialisers and callbacks: `initWithAcceleratorPort:`, `lazyInitialize`, `initWithDevice:descriptor:`, `commandBufferDidComplete:startTime:completionTime:error:`, `initWithQueue:retainedReferences:`, `didScheduleWithStartTime:endTime:error:`, `setCurrentCommandEncoder:`, `initWithCommandBuffer:`. | A renamed selector or changed signature gives unrecognised-selector (WindowServer crash loop) or a completion that never arrives (hang). | Medium |
| `Navi48Device.m:6489-6531, 6711-6724, 6803, ~6830` | Overrides of private methods, with comments that record 25G83 behaviour: `lazyInitialize` (comment at ~6523 says "Tahoe 25G83's caller consumes a BOOL result"), `_purgeDevice` (stops a SEGV in `-[_MTLCommandQueue dealloc]`), `supportLazyInitialization`, `featureProfile` (returns 10000), `llvmVersion` (returns 0x7d17). `newFence` and `currentAllocatedSize` SEGV if the override goes dead (~6711-6714). | If Apple renames a method, the override goes dead and the base method runs (known SEGVs in WindowServer). | Medium |
| `Navi48Device.m:6489-6495` | `+load` uses `objc_getProtocol("MTLDeviceSPI")` and `class_addProtocol`. | Renamed protocol fails the `conformsToProtocol:` assertion in `MTLAddDevice` (crash at device add). | Medium |
| `Navi48Device.m:2192, ~3740-4180` | Private `-[MTLFunction bitcodeData]` via `objc_msgSend`, guarded by `respondsToSelector`. | Removed: no AIR, every pipeline misses (magenta fallback in WindowServer). | Medium |
| `Navi48Device.m:1432-1457` (`n48s_bt_signal`), `1467-1494` (`n48s_classify`) | Scanout classification walks `[NSThread callStackReturnAddresses]` with `dladdr`. A surface is a display surface only if some frame's symbol contains **both** "DisplaySurface" and "GetMTLTexture" (CoreDisplay `DisplaySurface::GetMTLTexture`). Used at ~2968 and ~3071. Bypassed only by the root test flag `N48M_TEST_DISPFLIP` (~1369). | If the symbol is renamed, inlined or stripped, no surface is classified as display, D-copy scanout never fires, and the result is a frozen or black screen with no error. | High (for a rename or strip) |
| `n48_dispflip.h:196, 220` (`n48df_fn_is_final`) | Fragment function name containing "GPUPass" marks CoreDisplay's final pass. | If renamed, no frame is presented unless `/private/tmp/n48m-presentall` exists: stale or black screen. | High (for a rename) |
| `Navi48Device.m:385` | `backtrace_symbols` for logging only. | None. | n/a |
| `n48_gate.h:190` | WindowServer compile wait applies only on the dispatch queue labelled `com.apple.coreanimation.pipelines`. | If the label changes, the wait is skipped and the magenta or hot-swap fallback is used. | Medium |
| `n48_census.h:36-44` | Logs Metal protocols and classes at load. | Logging only. It is the right tool to diff 26.7 (see section 6). | n/a |
| `Navi48Device.m:2114, 2200` plus `build.sh:37-38` | Pipelines are looked up by sha256 of Apple's AIR bitcode. The cache is `research/ext/spvcache-25G83`, generated on 25G83. | Any changed CoreDisplay, QuartzCore or SkyLight shader changes its hash and misses. WindowServer shows magenta, or no-op compute, until the translation daemon hot-swaps (INSTALL.md section 8). | High (likelihood of at least some misses) |
| `n48_xlate.h:51, 614-621` | `dlopen`s `/System/Library/PrivateFrameworks/GPUCompiler.framework/Versions/*/Libraries/libLLVM.dylib` and needs 10 `LLVM*` C symbols plus an optional mangled one. | Apps fail to translate and get fallback or error. WindowServer not affected. | Low to medium |
| `n48_gate.h:206-219` | Claimed GPU families (Mac2, Common1-3, Metal3 for WindowServer). `featureProfile` 10000 and `llvmVersion` 32023 are copied from 26.6.2's paravirtual GPU driver. | Unlikely to change in a point release. | Low |
| `Navi48Device.m:3684`, `n48_xlate.h:126` | `kern.osversion` in the translation cache key. | Caches rebuild after the update, which is correct. | n/a |
| `Info.plist:25-26` | `LSMinimumSystemVersion` 26.6. | A 26.7 system satisfies it. | n/a |
| `build.sh:49` | `-mmacosx-version-min=12.0`. | None. | n/a |
| Whole bundle | No `sw_vers`, `ProductBuildVersion`, `operatingSystemVersion` or `kern.osproductversion` check anywhere. | A 26.7 build is accepted silently: nothing refuses it, nothing warns. | n/a |
| `n48_gate.h:65-87`, `Navi48Device.m:218-261` | IOKit user client to our own kext (service `Navi48Accelerator`, type `N48N`), nub properties. | Our kext, so only changes if our kext changes. | Low |
| `Navi48Device.m:2894-2918, 1614-1618` | Public IOSurface getters only (`IOSurfaceGet*`, `IOSurfaceLock`, `IOSurfaceLookup`). No IOSurfaceCreate property dictionaries. | Low. | Low |

### 2b. Kexts

Verified by reading the code and the Info.plists, unless marked as inference.

**Navi48Accel (AuxKC, `cobalt64/tools/native/navi48accel/`)**

- `Info.plist:75-86` requires IOAcceleratorFamily2 2.0.0, IOGraphicsFamily 1.0, and kpi.* at 20.0.0.
- `src/Navi48Accel.cpp:107-109` imports private family symbols by mangled name:
  `__ZN11IOAccelTask4initEP22IOGraphicsAccelerator2jPP16IORangeAllocator` and
  `__ZN22IOGraphicsAccelerator225initializeConfigStructureEv`. It also links 14 `__ZTV` family vtables (`build/accel.o`).
  If Apple changes either symbol, the AuxKC link fails or the kext will not load. Confidence high.
- **Layout gate, fails closed.** `n48_layout_gate()` at `Navi48Accel.cpp:302-333`; `size_ok` needs an exact match
  (`n48accel_pure.h:75`). The values come from `cobalt64/tools/ioaccel-layout/generated/IOAccelFamily2_decl.h`. Examples
  (size / slots): `IOGraphicsAccelerator2` 0xdd8 / 350, `IOAccelDisplayPipe` 0x318 / 306, `IOAccelCommandQueue` 0x6a8 / 337,
  `IOFramebuffer` 0x1d0 / 350, `IOAccelSharedUserClient2` 0x168 / 308. The gate also runs on the framebuffer path (`:626`).
  Any change refuses the accelerator and both Navi48Framebuffer personalities: no Metal acceleration and no second-monitor
  framebuffer. The README for ioaccel-layout says it was tested only on 25G83 (`cobalt64/tools/ioaccel-layout/README.md:62`).
- **Hard-coded slots, used after the gate passes** (not guarded independently): `this+0xc88` IOAccelConfig, length 0x90
  (`:365-366`); EventMachine vtable slot 38 `setStampBaseAddress` (`:547`); `newUserClient` overrides at slots 238 and 239
  (`:145-146`); IOAccelDisplayPipe slot 277 via `n48_ztvfam_IOAccelDisplayPipe[2+277]` (`:295`); factory slots 327, 333,
  334, 322, 348, 329. Failure is silent misbehaviour or a panic. Confidence medium.

**Navi48Bringup (kernel, `cobalt64/src/navi48-bringup/`)**

- `Info.plist:41-52` requires IOPCIFamily 1.0 and kpi.* 20.0.0. Imports only KPI symbols and IOService/IOUserClient
  vtables. Risk very low.
- **Native display route** (active in production, `navi48-metal-disp=1`). Offsets in `src/amd/native_disp_pure.h:121-150`:
  pipe +0x88/0x90/0x98/0xe0 and +0x298 isActive; accel +0x368/0x378/0x380, config at 0xc88, pipe gate byte 0xccf;
  display machine pipes +0x88 and count +0x108; transaction +0x38/0x48/0x58; resource 0xe/0x70/0x80/0xb0/0xb2/0xc0/0xe0;
  SysMemory 0xc/0x40/0xd0.
- **IOSurface offsets, not gated**: 0x58/0x60/0x68/0x70/0x72/0x78/0x80/0x98 and flags 0x3da (`native_disp_pure.h:143-145`,
  labelled "IOSurface, for this build only"). No runtime gate covers them. A shifted field gives wrong presents or copies
  (black or garbled screen) or a panic. Confidence medium-high.
- **Native AGDC route** (`accel pipeagdc 1`, run by the activation daemon). Unslid 26.6.2 SystemKC addresses:
  `kAgdcMeta 0x13d418e8`, `kPipeMeta 0x146036d8` (`src/amd/native_agdc_pure.h:30-55`, `:44-46`), AGDC vtable `0x13d40478`
  with 276 slots, start/newUserClient/vendor/new/delete/constructor addresses, prologue byte signatures and class size 0x110
  (`src/apple/DisplayPipeGuard.cpp:1654-1669`), slot checks 7/184/238/267 (`:1933-1946`), and an `AppleGPUWrangler` service
  requirement (`:1950`). Any kernel-collection rebuild moves these. The path fails closed (status 4-7): AGDC is not
  published and desktop integration may degrade. Confidence high that it refuses; low on the exact user-visible effect.
- `src/apple/iodp_vtable_static.h:2`: IOAccelDisplayPipe vtable, 306 slots, from 26.6.2.
- `src/dcn/navi48_fbname.cpp`: rewrites the RDNA4FB OSMetaClass `className` after a scan that depends on the OSMetaClass
  struct shape. Refuses on mismatch. Medium-low risk.
- In the tree but not in the production build (`APPLE_ROUTE=0`, `Makefile:37`): X6000, HWServices, getTtl slot 266 hooks
  (`DisplayPipeGuard.cpp:108-119`), and `fbwc` kernel anchors (`DisplayPipeGuard.cpp:2423-2426`, which need `navi48-fbwc=1`,
  not set). Low risk for this build.
- `cobalt64/src/g2capture/g2capture.m:9,37` and `cobalt64/src/navi48-bringup/src/apple/AppleHardwareHook.cpp:261`,
  `gfx_neuter.h:26`: hard-coded 26.6.2 / 25G83 addresses or layouts (reported by a sub-investigator; not independently checked).

**RDNA4FB patches (`cobalt64/third-party/rdna4fb-n44/0001-0009`)**

- Use only public IOFramebuffer virtuals (open override in patch 0004, timing, gamma), plus a `static_assert` that
  `IODisplayTimingRangeV2` is 0x138 bytes. Deployed Info.plist (`research/builds/macos-20261123/rdna4fb-0.0.10/src-tree/Info.plist:52-63`)
  requires IOPCIFamily, IOGraphicsFamily and kpi 20.0.0. Risk low to medium.

**Inference (not verified):** Navi48Accel and RDNA4FB live in the AuxKC. Per the boot config, their OpenCore entries are
disabled. An OS update invalidates the AuxKC, and it must be rebuilt against the new Boot and System KCs. Until then, the
framebuffer is missing, which would give a black screen. The repo builds the AuxKC with `--allow-missing-kdk`, and
`cobalt64/tools/stage-to-pc.sh:250` says there is no KDK on the PC, so no KDK is needed for the current build path.

### 2c. Tools and build checks

- `tools/baremetal/navi44-desktop/accelerated-reboot-trial.sh:87`: requires exactly `26.6.2` and `25G83`. Otherwise it
  prints "STOP unexpected macOS build" and latches software mode (no accelerated desktop). The same check appears in the
  metal-trial-b29, b30 and b31 templates at line 87. **Certain to fire on 26.7.x.** It is an intentional guard, but it is
  the first thing that will stop an update.
- Deploy and payload tools refuse any other build with a ValueError: `production-kernel-payload.py:1151`,
  `check-unified-payload.py:138,173`, `check-eight-combined.py:76`, `prepare-performance-fix.py:69`.
- The trial daemon also requires exact SHA-256 hashes of the Metal bundle (`:107-109`).
- The kexts contain no OS build check (grep verified).
- Required boot-args are checked by the same script (`:89-91`), including `navi48-agdc=1`, `navi48-metal-disp=1`,
  `navi48-metal-ws=1`, `amfi_get_out_of_my_way=1`.
- Kill switches: `$APP/disabled` (line 86, "persistent activation disabled") and `/private/tmp/n48m-noflip1|2` (line 92).

### 2d. OpenCore and boot configuration

Verified from the newest generated config, `research/builds/macos-20261123/kernel-681/kernel-payload-v17/EFI/OC/config.plist`
(not confirmed as the one booting the machine now).

- **Kernel > Add with `MaxKernel 25.6.99`** (lines 497-588): BlueToolFixup, IntelBTPatcher, BluetoothWCN7850, QwzWifi,
  QwzAirport, Navi44CPPC. 26.6.2 is Darwin 25.6, so these six are injected only up to 25.6.99. For 26.7.x (Darwin 25.7 by
  inference) they are **not injected**: no Wi-Fi, no Bluetooth, no CPPC. Separately, QwzAirport's personality allows only
  build 25G83 (`QwzAirportBuilds = ['25G83']`, its Info.plist:39 and 54).
- **Navi48Bringup** is injected with MinKernel 25.0.0 and no MaxKernel (line ~434), so it still loads.
- **Kernel > Patch** (AMD Vanilla byte patterns, MaxKernel 25.99.99): OpenCore still applies them, but they may not match
  after a point update. Critical ones: #7 "Bypass GenuineIntel check panic" (find `00000000000031d2b301`, line ~874; a miss is
  a boot panic); #0 cpuid_cores_per_package; #13 and #14 non-monotonic time panic (#14 was added for 26.4, which shows point
  updates do break these); the IOPCIFamily patches `probeBusGated` (find `e0117340`, line ~1020) and
  `IOPCIIsHotplugPort` (find `8400754b`). `tools/baremetal/audit-kernel-patches.py` can replay these patterns against a new
  BootKC before a reboot.
- **Security settings:** `SecureBootModel Disabled` (line ~1388), `ApECID 0`, `BlacklistAppleUpdate true`,
  `csr-active-config 03000000`. Keep SecureBootModel Disabled through the update (see section 5).
- **boot-args** (line ~1457) include `amfi_get_out_of_my_way=1`, `keepsyms=1`, `navi48-metal-disp=1`, `navi48-agdc=1`,
  `navi48-metal-ws=1`, `navi48-aux=1`. No `-lilubetaall` needed (same Darwin major).
- **KDK:** Apple had not released a KDK for 26.7.3 RC1 (25G416) at the time of the InsanelyMac thread. A KDK for 26.7.2
  (25G332) exists and was used by OCLP-CustoMac (second-hand, see section 3).

## 3. Comparison with Vermilion and NullMoth

Source: the investigator's read of `research/reports/macos-20261125/vermilion-audit.md`, `research/ext/vermilion` and
`research/refs/nvidia-macos-driver` (release 1.13.0, one commit `0960b2e`).

- **Vermilion (26.7.1 only).** It was tied to 26.7.1 on purpose: it reverse-engineered CoreDisplay addresses
  (`src/vermilion-accel/accel/phxrotate.h:147,156,159,163`), `IOFBDisplayModeDescription == 0xcc` ("CoreDisplay 26.7.1",
  `phxrotate_k.cpp:25`), IOAccel display-pipe offsets labelled "RE'd 26.7.1" (`nvrm-accel.cpp:481-491`), an AGDC header of
  0x110 "padded for a larger Tahoe base" (`phxagdc.cpp:45`), private VideoToolbox decoder ABI (`src/video-decoder/phx_vtdec.h:2-3`),
  and AMDRadeonVADriver2 entry points (`src/video-accel/PhxVA.c:4-6`). Its docs say other builds are untested
  (`docs/INSTALL.md:664-685`). It lists sleep/wake, GPU audio, a third or fourth monitor, FileVault and kmutil removal as
  unverified or unsupported. Its link gate uses symbol sets from the 26.7.1 KCs and says to re-run it after every macOS update
  (`scripts/build/linkgate_exports.sh:3-9`). Vermilion has **no** 26.7.2 or 26.7.3 notes, no point-release changelog, and
  its git log (14 commits) has no point-release commit.
- **Vermilion tracks Apple's vtable churn by symbol.** It forwards IOAcceleratorFamily2 methods through exported base
  vtables (`tahoe_fwd.h`, `nvrm-accel.cpp:47`, from NullMoth's `gen_tahoe_fwd.py:3-8`), which claims 27 methods made private
  in Tahoe and 7 retyped. Our repo instead hard-codes a 26.6.2 vtable (row 5 below). **This is the main structural difference:
  Vermilion's approach survives more point updates than ours.**
- **Issue #1 black screen on 26.7.3.** The only record is `vermilion-audit.md:34,175,177`. The reporter installed 26.7.3 and
  asked about the NullMoth 2.4.1 skeleton and `spirv-val`. The comments were never read (`:194`). **No cause is recorded.**
  The sources support neither "a Vermilion 26.7.1 dependency changed" nor "the skeleton bundle problem"; both are
  inferences.
- **NullMoth (`research/refs/nvidia-macos-driver`).** Documents macOS 15 Sequoia only (tested on 15.7.x and 15.8.1,
  `README.md:3,13,23`). "macOS 26 support" is listed as not done (`docs/RELEASE-1.0.13.md:29`, `RELEASE-1.1.0.md:27`). Its
  only 26.7 reference is the 26.7.1 KDK check. Its installer checks only the major version (`15|26`) and refuses an unknown
  build string (`package/install.sh:83-86,169`). Its update flow parks the driver with `-nvoff`, the small BAR and the
  firmware framebuffer before the update, and restores the kexts on the first boot after (`app/Resources/nullmoth-setup.sh:572-600`).
  That pre-update parking is worth copying. `25G241` appears only as a fake `sw_vers` string in tests.
- **Our repo vs Vermilion, row by row:**

| Dependency | Vermilion | Our repo |
|---|---|---|
| Private IOAccelerator layout | 26.7.1, forwarded through exported base vtables | 26.6.2 hard-coded (`iodp_vtable_static.h:2`, `Navi48Accel.cpp:302-333`) |
| Metaclass addresses | 26.7.1 CoreDisplay and AGDC addresses | 26.6.2 (`native_agdc_pure.h:44-46`) |
| Build gate | Installer major-version check, link gate by symbol | Exact-build checks in the activation daemon and deploy tools |
| Metal private subclassing | Not the same (uses a forwarder) | `MTLIOAccelDevice` and `_MTL*` subclasses (`Navi48Device.m:83-114`) |
| Scanout detection | Not the same | Backtrace symbol names (`Navi48Device.m:1447`) |

## 4. What changed in 26.7.x (web research)

| Release | Date (source) | Build | Security content relevant to this stack |
|---|---|---|---|
| 26.6.2 (ours) | 2026-08-17 (Apple page 148281) | 25G83 | Kernel and IOGPUFamily entries only. No IOAccelerator, IOSurface, WindowServer, CoreDisplay or Metal entries. |
| 26.7 | 2026-09-14 (Apple page 149042) | not confirmed | Graphics (CVE-2026-84492, race, app crash); **IOAcceleratorFamily** (CVE-2026-86944, OOB write); WindowServer secure input state (CVE-2026-65379); IOKit use-after-free (CVE-2026-28969); Kernel fixes (several, including CVE-2026-86917, a root-privilege restriction); Accelerate (CVE-2026-86882). The page lists no known issues. |
| 26.7.1 | 2026-09-28 (Apple page 149228; osxdaily says 9/29) | **25G241** (9to5mac; also seen as a NullMoth test string) | Security-only. CoreGraphics OOB write (CVE-2026-86950), which press reports as used in the wild. |
| 26.7.2 | 2026-10-26 (Apple page 149522, published 11-20) | **25G332** (per the KDK used by OCLP, second-hand) | **GPU Drivers** (CVE-2026-86981, OOB write, app can crash the system); **IOGPUFamily** (CVE-2026-43743, race; and sensitive data access); **IOSurface** use-after-free; **Kernel** (memory corruption, sandbox, root); Metal (sandbox file read); WindowServer and Screen Sharing (screen access). No display-specific entries and no known-issues section. |
| 26.7.3 | 2026-11-09 (Apple page 149719) | final build not confirmed; RC1 was **25G416** | Bluetooth UAF, AirPlay and rapportd pairing rate-limit, Messages group, brotli OOB write. **No** kernel, IOKit, GPU, WindowServer, IOSurface or display entries. |
| 26.7.4 | Unverified | Unknown | A search snippet mentions RCs. Not checked. |

Hackintosh and forum reports (thin, not systematic):

- InsanelyMac thread (Nov 3-5): OTA from 26.7.2 to 26.7.3 RC1 (25G416) on an X299 Hackintosh succeeded. The one boot-loop
  reported was fixed by setting **SecureBootModel to Disabled** during the update (the moderator says this has been known
  since early OpenCore). One black-screen report, on Screen Mirroring to Apple devices, was fixed by FeatureUnlock-Tahoe 1.3.1.
  OCLP-CustoMac used the 26.7.2 KDK (25G332). No OpenCore version was named for 26.7.3.
- No hackintosh report of a kernel-patch break on 26.7.x was found. The search was thin: r/hackintosh results were older
  builds or were not dated.
- The Parallels and UTM 26.7 "blank screen" reports are VM-guest issues (new VM firmware), not bare-metal. They do not apply
  directly here.
- Apple community threads about AppleDCP kernel panics and rendering artifacts concern 26.2 and 26.3 on real Macs. They are
  not 26.7.

## 5. Breakage forecast for 26.7.x

| # | Item | Where | Symptom if broken | Confidence it breaks on 26.7.x |
|---|---|---|---|---|
| 1 | Activation daemon exact build check | `accelerated-reboot-trial.sh:87` | No accelerated desktop (software mode latched) | Certain (intentional guard) |
| 2 | Navi48Accel layout gate, exact sizes and slot counts | `Navi48Accel.cpp:302-333`, `n48accel_pure.h:75` | No Metal accelerator, no second-monitor framebuffer | High if any class changed in IOAcceleratorFamily2 or IOFramebuffer. 26.7 adds IOAccel fixes, so likely. |
| 3 | AGDC static SystemKC addresses | `native_agdc_pure.h:44-46`, `DisplayPipeGuard.cpp:1654-1669` | AGDC not published, desktop integration degraded | High (any kernel-collection rebuild moves them) |
| 4 | Scanout classification by symbol name | `Navi48Device.m:1447` plus `n48_dispflip.h:196` | Frozen or black screen, silent | Medium-high (depends on CoreDisplay rename) |
| 5 | spvcache keyed by AIR hashes from 25G83 | `Navi48Device.m:2114, 2200`, `build.sh:37-38` | Magenta or no-op compute in WindowServer until hot-swap | High (any changed shader misses) |
| 6 | IOSurface offsets, not gated | `native_disp_pure.h:143-145` | Wrong presents or copies, black or garbled screen, or panic | Medium |
| 7 | Metal private subclass and override set | `Navi48Device.m:83-114, 6489-6831` | Dyld failure, unrecognised selector, or SEGV in WindowServer | Medium |
| 8 | Kernel>Add `MaxKernel 25.6.99` (BT, Wi-Fi, CPPC) | config lines 497-588 | No Wi-Fi, Bluetooth or CPPC (not a black screen) | Certain (by Darwin number, inference) |
| 9 | QwzAirport 25G83 allowlist | QwzAirport Info.plist:39, 54 | Wi-Fi personality refused | Certain |
| 10 | AMD Vanilla kernel patches (GenuineIntel, IOPCIFamily) | config lines ~874, ~1020 | Boot panic or PCI and GPU enumeration problem | Medium |
| 11 | AuxKC rebuild after update (Navi48Accel, RDNA4FB) | cobalt64 tools, `accelerated-reboot-trial.sh:157` | No framebuffer until rebuilt, black screen | Medium (inference) |
| 12 | Libs: `libLLVM` path and symbols | `n48_xlate.h:51, 614-621` | App translation fails | Low to medium |

Riskiest, in order: 2 and 1 (fail closed, certain to stop the accelerated path), then 4 and 5 (fail silently, black or
magenta screen), then 3.

Note: the security fixes most likely to touch our kexts are the 26.7 IOAcceleratorFamily fix and the 26.7.2 IOSurface,
GPU Drivers and IOGPUFamily fixes. Those are the same areas where our hard-coded layouts live, so they are likely to change
the layouts we depend on. That is an inference, and the only way to check it is to diff the KCs.

## 6. Effort to adapt

Estimate, not a measurement (low confidence in the number): roughly **two to six weeks of focused reverse engineering and
port work**, plus soak testing. Work items:

1. Get the 26.7.x KC and the matching KDK (needs the user's approval to download; see section 7). Regenerate the
   `ioaccel-layout` class sizes and slot counts, and diff them against 25G83. Fix the Navi48Accel gate values.
2. Re-derive the AGDC and SystemKC addresses (`native_agdc_pure.h`), the IOAccelDisplayPipe vtable (306 slots), and the
   IOSurface and pipe offsets (`native_disp_pure.h`). Prefer symbol lookup over fixed addresses where possible, which is what
   Vermilion does. Consider porting its forwarder approach.
3. Verify the CoreDisplay symbol `DisplaySurface::GetMTLTexture` and the shader fragment `GPUPass` still exist in the 26.7.x
   shared cache. Run `N48M_CENSUS=1` on 26.7.x to diff the Metal protocols and classes.
4. Regenerate the spvcache from 26.7.x shaders (`research/ext/spvcache-25G83` is from 25G83; the build needs
   `N48_SPVCACHE_DIR`).
5. Update the build checks: the activation daemon (line 87, and the b29-b31 templates), the deploy tools, the
   `QwzAirportBuilds` allowlist and the Kernel>Add `MaxKernel` values (or move them to a new upper bound).
6. Re-check the Kernel>Patch byte patterns with `audit-kernel-patches.py` against the new BootKC before the first reboot.
7. Soak test, following `docs/STATUS.md` (thermal watchdog and clock gating are new and still need soak testing).

Vermilion's stack needed the same kinds of work for 26.7.1, and it did not survive 26.7.3 without a reported black screen.

## 7. Safe upgrade procedure (for when it is decided)

Do none of these until the user approves each step. Several need sudo or a download, which need the user's approval.

0. **Decide to hold, or to port first.** Turn off automatic macOS update installs yourself in System Settings (this is an
   account or system setting, so it is the user's own action).
1. **Full backups before anything.**
   - Copy the EFI partition to an external disk, including `EFI/OC/config.plist` (the current generated config is in
     `research/builds/macos-20261123/`). Keep the current config as the reference for 26.6.2.
   - Clone the system volume to an external disk with a clone tool, and verify the clone boots through a separate OpenCore
     entry. A Time Machine backup is a second copy, not a substitute.
   - Create a local APFS snapshot as a further rollback point (`tmutil localsnapshot`).
2. **Keep 26.6.2 bootable.** Keep a second OpenCore entry that loads without the Navi48 kexts or boot-args, as the README
   requires. Keep the 26.6.2 config and kext set. Do not remove the 25G83 spvcache or the 25G83 layout headers.
3. **Park the driver before updating.** Use the activation kill switch (`$APP/disabled`) and remove the Navi48 boot-args, so
   the update runs without the custom kexts. Copy NullMoth's approach of parking the driver before the update and restoring
   it on the first boot after.
4. **Keep SecureBootModel Disabled** (already Disabled in the config). The OTA boot loop reported on 26.7.3 RC1 was fixed this way.
5. **Test on a clone first, never the live volume.** Update the cloned system volume, boot it through the test OpenCore entry,
   and check: boots, WindowServer runs, `N48M_CENSUS=1` census output, and no GPU clock or power changes by hand (the repo
   rule is that a manual power change froze the machine).
6. **Test order.** 26.7.2 first if a KDK exists for it (25G332 has one). Then 26.7.3 final, once a KDK exists for that build
   and after the RC-to-final check. Do not test 26.7.3 on the live machine until the Vermilion issue #1 cause is known.
7. **Only after the clone works,** port the code (section 6) and do the live update with the rollback ready.
8. **Rollback.** Boot the 26.6.2 OpenCore entry. If the system volume is damaged, restore from the clone or the snapshot
   (Recovery). Keep the EFI copy on an external disk.

## 8. Open questions and what would change the verdict

- **Diff the KCs.** Get the 26.7.x KDK and KC (needs user approval to download) and diff the IOAcceleratorFamily2 and
  IOFramebuffer class sizes and vtables against the generated headers. This is the single most useful next step, and it
  turns the medium-confidence items into facts.
- **Vermilion issue #1.** Read the issue and its comments (`vermilion-audit.md:194`). The cause of the 26.7.3 black screen
  would change the verdict.
- **Which kext is installed.** STATUS says 0.0.675, the newest config says 0.0.681. Settle this before any update.
- **Security trade-off.** The 26.7.1 and 26.7.2 fixes matter for this stack. If the machine is used with untrusted content,
  the cost of staying on 26.6.2 rises, and the port becomes more urgent.
- **Uncommitted changes.** The `navi48metal` tree has uncommitted edits. Any port should start from a committed state.
- Not verified: whether the 26.7.4 RC exists and what it contains; the final build number for 26.7.3; whether any 26.7.x
  point release changed `libLLVM` or GPUCompiler paths.
