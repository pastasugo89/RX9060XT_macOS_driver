# Vermilion audit (read-only), 25 November 2026

Scope: find the project "Vermilion" (macOS GPU acceleration for AMD RX 7900 XT, Navi 31 / RDNA 3), verify it, check licence and provenance, compare it with our RX 9060 XT (Navi 44, RDNA 4) driver, and rank what we can reuse.

Method: GitHub search and API reads, a local `git clone` into `research/ext/vermilion` (gitignored; HEAD `9a91901`, 23 Nov 2026), and targeted reads and greps of the clone. Nothing was built, installed or run. No tracked file was edited and nothing was committed or posted. Paths below are relative to the repo root unless stated otherwise. Vermilion paths are relative to `research/ext/vermilion/`.

## 1. Summary

- **What it is.** An experimental macOS Tahoe 26.7.1 driver for one board: AMD RX 7900 XT, PCI `1002:744c` rev `0xcc`. It has a boot kext (`VermilionBoot.kext`, GPU bring-up, IH, PSP/SMU, DMUB display), an accelerator kext (`VermilionAccel.kext`, AuxKC, derived from NullMoth's NVIDIA driver), a Metal plugin (`NVMTLDriver`, Metal on RADV, also NullMoth-derived), a shader translator (NullMoth's metal2vulkan, LGPL), RADV Darwin patches, an optional HEVC/AV1 decode path, and a boot daemon.
- **Maturity.** Very young and single-maintainer: repo created 5 Nov 2026, first commit 4 Nov 2026, 14 commits, 16 stars, 2 forks, 1 open issue. The maintainer's other public repos are small 2020 to 2023 app projects. Only one candidate project exists (see section 2).
- **Claimed working** (on one reference machine): Metal acceleration of WindowServer, 144 Hz and 165 Hz, two monitors at once (DisplayPort and HDMI), hot-plug, display rotation. **Not yet:** sleep and wake, GPU audio, a third or fourth monitor.
- **Licence verdict.** Mixed. Most code is MIT. Parts derived from NullMoth are PolyForm Noncommercial 1.0.0, which is the same licence as our project, so they can be reused in our noncommercial project if the notices are kept. The translator is LGPL-3.0-or-later. Some nullarc-derived files are offered as MIT or GPL-2.0-only; we must take the MIT option, never GPL-2.0. No NootRX or NootedRed lineage found (section 3).
- **Overall.** Vermilion is ahead of us on the things it actually implements: an interrupt path (opt-in), a VCN 4 ring bring-up (debug-level), an opt-in GPU soft-recovery design, two-display DP+HDMI (claimed), and a wider Metal API surface (partly claimed). We are ahead on RDNA 4 specifics: GFX clock gating on by default since 0.0.675, the thermal clamp, and SMU 14. Most of its code is Navi 31 register plans, which do not transfer. Direct reuse is limited to design patterns and a few small items (section 6).

## 2. Identification

Search results (GitHub repository search, 25 Nov 2026):

| Query | Hits |
|---|---|
| `vermilion RX 7900 XT macOS Metal` | 1: `leolivm/vermilion` |
| `vermilion in:name macos gpu` | 0 |
| `Navi 31 macOS Metal acceleration RDNA3` | 1: `leolivm/vermilion` |
| Web search, "Vermilion macOS RX 7900 XT ..." | No Vermilion coverage; only general RX 7900 XT and macOS forum material |

Only one candidate: **https://github.com/leolivm/vermilion** (owner `leolivm`).

Facts from the GitHub API and the clone:

- Created 2026-11-05T01:30:06Z (API). First commit `713a785` dated 2026-11-04 (local git log). Last push 2026-11-23 (commit `9a91901`, "submit_test: fd3 rec, the automatic recovery probe (kext b127)").
- Language Rust (repo tooling). GitHub licence field: `other` (NOASSERTION), because the repo is a licence map, not one licence.
- 16 stars, 16 watchers, 2 forks, 1 open issue, no `.github` CI directory found.
- The commit history contains `Co-Authored-By: Claude Opus 5.5` and `Claude-Session` trailers (for example `93a9571`, `5189257`, `ffd2bf4`, `036bb61`, `75120fa`). The README does not say that the code is AI-assisted. This does not change the licence analysis, but it means the provenance claims ("ported from", "derived from") should be checked against the sources before anyone relies on them.
- Open issue #1, opened 21 Nov 2026 by another user (https://github.com/leolivm/vermilion/issues/1): a user built the kexts, plugin, translator and RADV at the documented commit, installed them on Tahoe 26.7.3 (the docs say 26.7.1), and got a black screen with a movable pointer. The user asks whether the NullMoth 2.4.1 bundle skeleton is an authorised source and whether `spirv-val` is needed. I did not read the comments and cannot see a maintainer reply in the listing.

## 3. Licence and provenance

Sources read: `LICENSE` (licence map), `CREDITS.md`, `THIRD_PARTY_NOTICES.md`, `README.md`, and the SPDX census (155 lines `MIT`, 101 lines `PolyForm-Noncommercial-1.0.0`, 1 line `(MIT OR GPL-2.0-only) AND BSD-3-Clause`, outside the translator; one line per file header).

### Provenance check (NootRX / NootedRed)

- A case-insensitive grep for `nootrx`, `nootedred` and `noot` across the whole clone (excluding `.git`) returned **zero hits**. There was therefore no part to skip.
- Declared lineage (CREDITS.md): NullMoth (accelerator, Metal plugin, translator wrapper), metal2vulkan (translator core), nullarc (boot kext skeleton, `phxctl`, `mesboot`), Cobalt64 (RADV Darwin backend, user-client ABI, PSP ring method), RX4Darwin (AUX, DMUB, HPD methods, BSD-3), RedNavi (AUX, pipe and VBIOS method, BSD-3, "no code copied"), Linux amdgpu (MIT), Mesa (MIT), FFmpeg (LGPL-2.1), Acidanthera (MacKernelSDK build-time, OpenCore).

### Licence table and reuse verdict for our noncommercial project

| Part (Vermilion path) | Licence | Reuse for us |
|---|---|---|
| Vermilion-written code: `src/vermilion-boot` (except the nullarc and AMD files), `src/video-decoder`, `src/video-accel`, `tools/metaltest`, `tools/firmware`, `scripts/`, `tests/`, `docs/` | MIT (Copyright 2026 Vermilion contributors) | Yes, keep the notice. Compatible with PolyForm NC. |
| Linux amdgpu-derived register tables and algorithms (`phx_regs_dcn32.h`, `PhxGamma.h`, `PhxVbios.h`, `PhxDdc.h`, `PhxHpd.h`, `PhxPipe0.h`, `PhxPipe2.h`, `phx_*_plan_*.inc`, `phx_psp_smu.cpp`, `phx_vm.cpp`, `tools/phxctl/mes_v11_api_def.h`, `csb_gfx11.h`) | MIT, Copyright Advanced Micro Devices, Inc. | Yes, keep the AMD notice. These are Navi 31 (DCN 3.2, SMU 13, MES 11) values, so mostly not portable (section 7). |
| nullarc-derived files (`PhxBringup.cpp`, `PhxNativeABI.h`, `build.sh`, `kmod_info.c`, `Info.plist`, `tools/phxctl/phxctl.c`, `mesboot.c`, `relocate_gpubundle.sh`) | MIT **or** GPL-2.0-only, at the user's option | **Take the MIT option only.** GPL-2.0 terms conflict with PolyForm NC's noncommercial restriction. |
| `PhxNativeABI.h` user-client layouts, `phx_psp_smu.cpp` PSP ring method (after Cobalt64) | additionally BSD-3-Clause (Navi48 project) | Yes, keep the notice. Our own code. |
| `src/vermilion-accel` and `src/metal-plugin` (derived from NullMoth's driver) | **PolyForm Noncommercial 1.0.0**, Required Notice "Copyright (c) 2026 NullMoth Systems (https://nullmothsystems.com)" | Usable only in a noncommercial project, with the Required Notice and the licence text. Our project is also PolyForm NC 1.0.0, so compatible. Not usable if the project ever goes commercial. |
| `src/metal-plugin/nvmtl_copy_compat.h`, `nvmtl_format_twin.h` (added by `ffd2bf4`) | **No SPDX line and no copyright line.** By the LICENSE table they sit in `src/metal-plugin` (PolyForm NC). | Treat as PolyForm NC. Do not copy them until the author confirms their licence. Re-implementing the rule from the Vulkan format rules is the cleaner route (section 6). |
| `src/translator` (NullMoth's metal2vulkan copy v2.6.5, and the Vermilion wrapper changes) | LGPL-3.0-or-later | Yes, keep LGPL obligations. We already use NullMoth's translator (LGPL), so the licence position is the same. |
| `patches/mesa` (Mesa MIT; patches 0001 to 0009 Cobalt64 MIT; 0010 to 0015 nullarc; 0016 to 0017 Vermilion) | MIT | Yes, keep notices. |
| `patches/ffmpeg` | LGPL-2.1-or-later | Only as shared libraries with notices and source offer. |
| Not in the repo: linux-firmware `amdgpu/` blobs (AMD licence, binary redistribution only), MacKernelSDK (APSL 2.0), NullMoth 2.4.1 `NVMTLDriver.bundle` skeleton, Apple `air-opt`, Vulkan-Headers | Various | Not redistributable by us from this repo. Get them ourselves, as the project already does for firmware. |

**Licence verdict in one line:** reusable in our noncommercial project with notices kept (MIT, BSD-3, LGPL, PolyForm NC for the NullMoth-derived parts); never take the GPL-2.0 option; the two header-less Metal files are PolyForm NC by directory until the author says otherwise.

## 4. Architecture and features (what it does, with evidence)

Install stack (docs/INSTALL.md):

1. OpenCore injects `VermilionBoot.kext` (`docs/INSTALL.md` section 3). It matches `0x744c1002` only.
2. `VermilionAccel.kext` goes into the Auxiliary Kernel Collection (section 4).
3. The Metal plugin, translator and RADV go into `/Library/GPUBundles` (section 5). The plugin needs an existing `NVMTLDriver.bundle` skeleton from NullMoth 2.4.1, which is not shipped (section 5.2, marked "unverified" that a minimal `Info.plist` works).
4. A LaunchDaemon `phxboot-navi31.sh` runs at each boot and powers the GPU up before WindowServer, with optional steps behind flag files (section 7).

Prerequisites that matter for us (section 1 and "What amfi=0x80 costs"):

- macOS 26.7.1 only. The plugin uses private Metal interfaces of that build.
- `csr-active-config` set to `0x0A03` (INSTALL line 37). Section 5.5 confirms that the `0x800` bit is authenticated-root, and that the sysvol install needs it disabled.
- `amfi=0x80` (library validation off for every process). Side effects they list: FairPlay and DRM playback fails, and third-party privacy prompts are denied.
- WhateverGreen must be disabled.
- Optional sysvol write (`tools/phxctl/sysvol_install.sh`) to install a video decode bundle; a macOS update removes it.

Feature facts by area (with the file that shows them):

- **Interrupts.** `src/vermilion-boot/phx_ih_irq.cpp`: IH ring in system memory or VRAM, write-back wptr, MSI filter, EOP (client 0x14, src 0xB5) wakeups, overflow skip, and a storm guard (more than 50,000 interrupts in a 1 s window disables `ENABLE_INTR`). **Enabling is opt-in:** `ihEnable` and `irqEnable` are called only from the sysctl handlers `debug.phxih` and `debug.phxirq` (`src/vermilion-boot/phx_sysctl.cpp`). No script under `tools/` or `tests/` sets those sysctls, and no boot path calls them. The interrupt path exists but is off in the shipped flow as far as the tree shows.
- **Fault recovery.** `PhxRecover.h`, `phx_recover.cpp`, `PhxFaultDef.h`, host test `tests/mock/recover_test.cpp`. When a fence wait stalls for `debug.phxrecover_ms` (default 2000), and a GCVM protection fault names a user VMID, it writes `SQ_CMD = KILL | BROADCAST | CHECK_VMID` for that VMID only, up to 10 ms, then clears the status. The context is marked lost and gets `kIOReturnAborted`. Default off (`debug.phxrecover=0`). Nothing is reset.
- **VCN.** `phx_vcn_mmhub.cpp`, `tools/phxctl/vcn_up.sh` (VCN 4, instance 0, "VCN 4 alive" milestone, Linux 6.8 `vcn_v4_0_start_dpg_mode` sequence), `vcn_m1_gen.py`. MMHUB VM translation with contexts 8 to 15 mirroring the GC page tables, and a 200 ms VCN watchdog. The CHANGELOG records these as debug-level steps.
- **Video decode.** Optional `libphxdec_hevc.dylib` and FFmpeg Vulkan video (`src/video-decoder`, `patches/ffmpeg`). `PhxVA.bundle` is a placeholder that declines every request, so VideoToolbox falls back to software. I found no recorded validation result for the decode path in the CHANGELOG or docs.
- **Power.** SMU 13 mailbox (`phx_psp_smu.cpp`, `PHX_SMU_MSG_REG 0x16282`); DAL `SetHardMinByFreq` and DPM limit messages for UCLK and FCLK only; UCLK is pinned when a display cannot take a memory-clock switch (CHANGELOG 71, Linux's behaviour); `tools/phxctl/gfx_cg.sh` writes GFX clock-gating register values captured from Linux amdgpu on Navi 31 (its header says an idle card otherwise runs about 250 W at 110 °C hotspot; this is their measurement, not verified by me). GFXOFF exists only as a debug selector (`PHX_PPSMC_AllowGfxOff` in `phx_debug.cpp`). No thermal clamp or fan logic found.
- **Watermarks.** `tools/phxctl/wm144.sh` refuses to reprogram watermarks while stutter is allowed (following a Linux commit they cite, `c82b8f96eb9`; I did not check that commit), and the 60 Hz return forces stutter off first (`tests/mock/wm144_guard_test.sh`).
- **Display.** DCN 3.2 register set (`phx_regs_dcn32.h`), DMUB firmware `dcn_3_2_0_dmcub.bin`, pipe 0 and pipe 2 plans measured on the reference machine (1080p 60, 144 and 165 Hz; plan files `phx_s2_plan_*.inc`, `phx_p0_plan_*`). HDMI SCDC and TMDS handling, DP AUX/DDC defer handling, HPD debounce, EDID fallbacks, rotation (`phxrotate`), hot-plug.
- **Metal (plugin).** `NVMTLDevice.m`: `argumentBuffersSupport` returns Tier2 (line 2246); `supportsFamily` returns YES for `MTLGPUFamilyMac2`, Common1 to 3, and private families 2001 and 5001 (Metal 3 class) for every client (lines 2247 to 2255). `NVMTLEmbedded.m` logs "tier2: reads argument-buffer texture(s) through the bindless heap; N field(s) still bound per draw", so the bindless path is partial. `newIndirectCommandBufferWithDescriptor:maxCommandCount:options:` creates a real object (line 2286). `gpuAddress` is implemented (`nvmtl_vk_buffer_address`). `NVMTLDevice_contract.m` is included by `NVMTLDevice.m` and has stubs that return nil "(not built yet)", including `newBufferWithDescriptor` and `newBufferWithIOSurface`. Its ICB stub uses the selector `maxCount:`, not the Metal selector `maxCommandCount:`, so it does not override the real method.
- **Metal (copies).** `nvmtl_copy_compat.h` and `nvmtl_format_twin.h`: texture copies between size-compatible formats (sRGB and linear twins) are performed, not dropped. Test `tests/plugin/test_copy_compat.c`.
- **Translator (NullMoth v2.9 ports, from its commit messages):** `5189257` folds Core Animation's `fixed_frag` configuration struct (their measurement: WindowServer translates each variant in about 0.6 s instead of 1.6 s; SPIR-V shrinks from about 690 KB to 20 to 30 KB), adds AIR 2.9 atomic operand handling and `air.simdgroup.barrier` device scope. `93a9571` fixes a texture-environment element-zero case that blanked xterm.js (VS Code terminal) WebGL output.
- **Firmware.** `tools/firmware/fw.lock` pins 20 linux-firmware files by md5 at commit `add225168d0d...` (release 20250917), and says later releases replace most GC, PSP, SMU, VCN, SDMA and DCN files. Files: GC 11.0.0, PSP 13.0.0, SMU 13.0.0, SDMA 6.0.0, VCN 4.0.0, DMCUB DCN 3.2.0.
- **Tests and CI.** Host mock tests (`tests/mock/run.sh`, `b15test.sh`, `recover_test`, `faultdef_test`, `fd3_shader_test`). No CI configuration found.

## 5. Feature comparison with our project

Our evidence comes from `docs/STATUS.md`, `README.md`, and greps of `cobalt64/` (paths relative to the repo root).

| Area | Vermilion (RX 7900 XT, Navi 31) | Ours (RX 9060 XT, Navi 44) | Ahead |
|---|---|---|---|
| Target and macOS | `1002:744c` rev `0xcc`; macOS 26.7.1 (a reporter runs 26.7.3) | `1002:7590`; macOS 26.6.2 (25G83) | n/a |
| Firmware (what the bring-up loads) | GC 11.0.0, PSP 13.0.0, SMU 13.0.0, SDMA 6.0.0, VCN 4.0.0, DMCUB 3.2.0; md5 pinned, fetch refuses other revs | GC 12.0.0 (incl. `uni_mes`), PSP 14.0.2, SMU 14.0.2, SDMA 7.0.0 (`cobalt64/src/navi48-bringup/Makefile` lines 18 to 30); sha256 pinned | RDNA 4 for us. Pinning: parity |
| Interrupts | IH ring, MSI filter, EOP wakeup, storm guard, overflow skip; **enabled only by sysctl** | IH v7 (`src/amd/ih_v7_0.cpp`), MSI path in `Navi48Bringup.cpp` around 7263 to 7500; **gated by `navi48-interrupts=1`, default polled** | Vermilion (code more complete; both off by default) |
| Fault recovery | Opt-in soft recovery, one kill per stall, VMID-scoped | None. `DEVICE_LOST` on every submission after a fault | Vermilion |
| GFX clock gating | Script-driven register values from Linux Navi 31 trace (`gfx_cg.sh`), off unless run | gfx_v12_0 clock gating on since 0.0.675 (`src/amd/gfx_v12_0_cg.cpp`) | Ours |
| GFXCLK and thermal | No thermal clamp or fan logic found | GFXCLK clamped at 500 MHz; 90 °C warning; 100 °C clamp; release after 10 s below 85 °C | Ours |
| UCLK / display underflow | UCLK pin when display cannot switch; stutter off before watermark changes (wm144 guard) | Two-stage fallback: stutter off, then UCLK pin (`src/amd/smu_uclkpin_pure.h`). Watermark-stutter guard not yet checked | Roughly even; check the guard |
| GFXOFF | Not used (debug selector only) | Not used (`AppleHardwareHook.cpp` notes our kext never sends AllowGfxOff) | Tie |
| SDMA copies | Not used | Not used in the shipped path (STATUS) | Tie |
| VCN | VCN 4 ring "alive" (debug), MMHUB VM mapping, watchdog | VCN firmware loader and tests (`src/amd/fw_loader.cpp`, `native_vcn_*`); no VCN firmware in the navi44 `FW_REQUIRED` list | Vermilion |
| Video decode | HEVC/AV1 via FFmpeg Vulkan, VideoToolbox bundle; unvalidated, placeholder declines | None | Vermilion (unvalidated) |
| Display | DCN 3.2; DP and HDMI at once (claimed 144 and 165 Hz); hot-plug; rotation; SCDC and TMDS | DCN 4.x; one 1440p 120 Hz display validated; multi-monitor behind experimental flags, not validated | Vermilion (claimed) |
| Black band / 60 Hz | Not discussed | Black band fixed in 0.0.673; 60 Hz opt-in, one bad boot | n/a |
| Sleep and wake | Not done (`pmset` workaround) | Not verified | Tie |
| HDR | Not claimed | Not working | Tie |
| Metal feature level | Claims Tier2 argument buffers, Metal 3 family YES for all apps, `gpuAddress`, ICB object, residency sets. Bindless partial | Tier1 for apps; Metal 3 only for WindowServer (`tools/native/navi48metal/n48_gate.h` lines 204 to 216); `gpuAddress` 0; ICB NO (`Navi48Device.m` 4537, 4737); residency sets retain only | Vermilion (claimed, partly verified). Our Metal 3 gate is the safer position |
| Texture copies between sRGB and linear twins | Implemented | Not verified (we checked buffer copies only, `Navi48Device.m` 6306 to 6328) | Vermilion (to check) |
| Translator base | NullMoth v2.6.5 plus v2.9 ports | NullMoth v2.7.2 base, v3.0 patch set (`cobalt64/third-party/metal2vulkan-n48/patches/0003`, `0004`) | Ours (base likely newer; port status to check) |
| Licence | Mixed (section 3) | PolyForm NC 1.0.0 with upstream notices | n/a |
| Testing | Host mocks; no CI | Host test suites; our own CI status not checked here | Not compared |

Notes on the table:

- Our interrupt default is polled, matching `docs/STATUS.md` ("no GPU interrupts (polled fences)"). Vermilion's default is also off. We must not claim it has interrupts running by default.
- On Metal, the claim "Vermilion is ahead" applies to the API surface it declares, not to verified behaviour. Its own log line says fields are still bound per draw.

## 6. What we can take, ranked

Effort and risk are my rough estimates. Items 1 to 2 are low risk and can be done in mock tests first. Items 3 and 4 touch live hardware, and the memory rule "no live GPU state tests" applies: no live clock, power or interrupt changes on the desktop without the user's explicit go-ahead.

1. **Translator ports from NullMoth v2.9 (fixed_frag folding, AIR 2.9 atomics, texture-env element-zero fix).**
   - Why: fixed_frag folding cuts WindowServer translation time and SPIR-V size (their figures). The texture-env fix addresses blank WebGL output in xterm.js, a class of problem related to our Brave WebGL gap.
   - Plan: (a) check whether our v3.0 base already has equivalents (search the `n48xlate` translator and the NullMoth v3.0 tree for the same passes and `.ll` fixtures from commits `5189257` and `93a9571`); (b) for any missing one, port the change and its `.ll` fixtures, run our translator tests; (c) keep LGPL notices; (d) expect a one-time re-translation because the SPIR-V cache key changes.
   - Effort: hours if already upstream, 2 to 5 days if not. Risk: low.

2. **Watermark stutter guard before a watermark change (`wm144.sh`, mock test `wm144_guard_test.sh`).**
   - Why: it targets the same display-underflow-on-memory-clock-switch gap we list. It is a precondition check, not a new clock change.
   - Plan: (a) grep our DCN watermark and mode-switch path for a stutter-state check; (b) if absent, add the refusal behind a flag; (c) mock test covering every write mode; (d) a live test only with the user's approval.
   - Effort: 1 to 3 days. Risk: low to medium (display path).

3. **IH design: storm guard and overflow handling (`phx_ih_irq.cpp`).**
   - Why: it is the design we need to enable our gated MSI path safely. Our own comment warns that an unacked interrupt is a live-lock. Vermilion's answer is a windowed storm guard (50,000 IVs in one second disables `ENABLE_INTR`), overflow skip to the oldest valid IV with a flag toggle, a bounded drain loop, and EOP wakeups.
   - Plan: (a) port the storm and overflow state machine into our `handleInterrupt`, using IH v7 offsets from our headers, not Vermilion's IH v6 register values; (b) keep `navi48-interrupts` default 0; (c) host tests for storm and overflow; (d) live enable only with user approval and a recovery path.
   - Effort: 1 to 2 weeks. Risk: medium to high on hardware.

4. **Soft recovery decision logic (`PhxRecover.h`, `recover_test.cpp`).**
   - Why: it addresses our "DEVICE_LOST freezes the desktop until restart" gap. Its key property is that it kills only the VMID named by the protection fault, tries once per stall, and never resets.
   - Plan: (a) port the decision as pure logic with a host test; (b) check the `SQ_CMD` encoding against our GFX 12 headers and the Linux gfx_v12 soft-recovery routine (verify, do not assume the RDNA 3 encoding carries over); (c) default off; (d) hardware test only with the user's approval, because a kill that does not unstick can hang the GPU.
   - Effort: 2 to 3 weeks. Risk: high on hardware, low for the pure logic.

5. **Texture copies between compatible formats (sRGB and linear twins).**
   - Why: it may close a Metal copy gap, which we have not verified. Vermilion's test (`tests/plugin/test_copy_compat.c`) shows the refusal cases.
   - Plan: (a) first verify whether our bundle refuses such copies (read the texture-to-texture copy path, not only the buffer paths I checked); (b) if it does, reimplement the rule from the Vulkan format-compatibility rules and write our own test. Do not copy `nvmtl_copy_compat.h` or `nvmtl_format_twin.h`: they have no licence header.
   - Effort: 1 to 2 days. Risk: low.

**Study only, do not port now:**

- Vermilion's bindless heap and Tier2 argument-buffer claim. Its own log says fields are still bound per draw. Our current gate (Metal 3 only for WindowServer) is the safer position. Changing it touches the compositor path, which the n48 gate notes flag as risky.
- Its `gfx_cg.sh` values. Useful only as a cross-check of our gfx_v12 clock-gating register values, not as code.
- RX4Darwin (BSD-3) is an RDNA 4 kext. Vermilion took its AUX defer handling, DMUB inbox protocol and HPD debounce timing. Those are RDNA 4 lineage, so compare them with our display code before anything else.

## 7. RDNA 3 to RDNA 4 porting map

| Block | Vermilion (Navi 31) | Ours (Navi 44) | Portability |
|---|---|---|---|
| GC | GC 11, MES 11 (`mes_v11_api_def.h`, `gc_11_0_0_mes*.bin`) | GC 12.0.0, `gc_12_0_0_uni_mes` | Register offsets differ. Only the sequencing and design transfer. |
| IH | IH ring at `0x1120` family, CP EOP enable at `0x306A` and `0x3085` (`phx_ih_irq.cpp`) | IH v7 (`ih_v7_0.cpp`) | Design transfers (storm guard, overflow). Offsets do not. |
| SMU | SMU 13 mailbox `0x16282`, PSP 13 | SMU 14.0.2, PSP 14.0.2 | Message numbers and mailbox differ. Our SMU 14 code is the reference. |
| Display | DCN 3.2 (`phx_regs_dcn32.h`), DMUB 3.2.0, measured plans | DCN 4.x (our README says DCN 4.1) | Plans and register sets do not transfer. Sequence ideas do (DISPCLK-first switch, DET split, AUX defer). |
| VCN | VCN 4.0.0 | Not in navi44 `FW_REQUIRED` | RDNA 4 video block is a different generation; check our headers before assuming anything. |
| SDMA | SDMA 6.0.0 (not used) | SDMA 7.0.0 | Nothing to take. |
| Metal | Plugin code is API-generic (Vulkan), Navi 31 only in the device table and the `canned navi31` RADV patches (`patches/mesa` 0016, 0017) | Our `navi44` profile | The Metal logic transfers in principle. The device tables do not. |

## 8. Red flags

1. **Installs depend on NullMoth's proprietary-licence package.** The `NVMTLDriver.bundle` skeleton comes from NullMoth 2.4.1 (PolyForm NC), not shipped by Vermilion, and the minimal-plist route is untested (INSTALL 5.2). Open issue #1 says that release was superseded after black-screen reports (reported by the user; I did not verify it).
2. **System-level weakening.** `csr-active-config 0x0A03` (INSTALL line 37; the `0x800` bit is authenticated-root). `amfi=0x80` (system-wide library validation off; FairPlay and privacy prompts break). Optional writes to the sealed system volume. Our own SIP note (`research/reports/navi44_sip_and_stage17_installer_20261027.md`) proposes `0x03` only and says it is untested. We must not follow their set-up, and should check whether our docs (several mention `amfi`) rely on it.
3. **Exact-build dependency.** Plugin relies on private interfaces of macOS 26.7.1. Installing on 26.7.3, as the issue reporter did, is unsupported. Our test host is 26.6.2, so Vermilion would not run on our machine as is.
4. **Overclaimed Metal surface.** `supportsFamily` returns YES for Metal 3 class families (2001, 5001) to every client. `argumentBuffersSupport` returns Tier2 unconditionally, while its own log says bindless fields are still bound per draw. Apps that trust these answers can take code paths that do not work.
5. **Stale firmware pin.** linux-firmware 20250917. Their own note says later releases replace most of the blobs the bring-up uses.
6. **Board-specific values.** Watermarks, DET, timings and fallback EDIDs were measured on one card and two named monitors (INSTALL 1 and 10). The display plans should not be generalised.
7. **Unverified claims.** Video decode is not shown to work. VCN is "alive" at one debug step. Two-monitor operation and 144 and 165 Hz are reported on one machine. The 1.5-minute shader translation at first login is documented as a known limit.
8. **Provenance and AI assistance.** Commit trailers show Claude co-authorship, and the README does not say so. The "derived from" and "ported from" statements in CREDITS and THIRD_PARTY_NOTICES should be checked against the upstream sources before we rely on them. The two Metal files with no licence header (section 3) are an example.
9. **Single maintainer, three weeks old, no CI, one open unanswered issue** (from the listing I saw). Expect changes that break the install path.
10. **Opt-in recovery that writes GPU registers.** Soft recovery and the interrupt sysctls write to live hardware. They are off by default, but they are the kind of change our own memory notes warn about.

## 9. Not done, and what is unverified

- No build, install or run of anything from the clone (per instructions). Everything above is from reading.
- Reads and greps only: I did not read the translator internals, the full RADV patch series, most of `PhxPipe2.h`, or the full `NVMTLDevice.m`. Claims about the Metal feature level are from the declarations and a few implementations.
- The IH and VCN bring-up sequences were not verified against hardware or against Linux.
- The Linux commits cited for the watermark guard (`c82b8f96eb9`) and for the GFX clock-gating values were not checked.
- Our translator's equivalence to the NullMoth v2.9 changes was not verified (the grep found no matching strings in our tree, but our base is v3.0, which may carry them under other names).
- Our texture-copy path and our watermark-stutter guard were not read in full.
- Issue #1 comments were not read.

## 10. Sources

- Repository: https://github.com/leolivm/vermilion (clone at `research/ext/vermilion`, HEAD `9a91901`, 23 Nov 2026)
- Issue #1: https://github.com/leolivm/vermilion/issues/1 (21 Nov 2026)
- Lineage: https://github.com/nullmoth/nvidia-macos-driver ; https://github.com/steelbrain/metal2vulkan ; https://github.com/luuumi-dev/nullarc ; https://github.com/Almosst-DEV/Cobalt64 ; https://github.com/RX4Darwin/AMDRadeonRDNA4.kext ; https://github.com/Helemen7/RedNavi ; https://gitlab.freedesktop.org/mesa/mesa ; https://ffmpeg.org ; https://gitlab.com/kernel-firmware/linux-firmware
