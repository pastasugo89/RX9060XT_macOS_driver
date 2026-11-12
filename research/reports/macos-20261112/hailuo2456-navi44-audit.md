# Audit: hailuo2456/AMDRadeonRDNA4-navi44 (read-only), focus on GPU power management

Date: 2026-11-12. Scope: read-only. Clone at `research/ext/hailuo2456-navi44` (git clone only; nothing built, run or executed). No tracked file edited, no commit, no live GPU state change. Per the memory note, no clock or power change was made on the live machine. The `power 0` freeze recorded there is a reason to keep every recommendation below off the live desktop until it is tested in a planned boot.

Rules observed: no NootRX or NootedRed source was opened. The only file read that mentions MetalCyan (a NootedRed fork) is `docs/metal-spike.md`, and only the provenance sentence at line 302 (see section 6).

Upstream references were fetched from `torvalds/linux` master (raw GitHub) into the scratchpad. The repo claims Linux 7.2.2 as its reference, so line numbers may differ from that tag.

---

## 0. Bottom line

- **Is it ahead of us anywhere?** Yes, in one place that matters for the goal: **GFX clock gating (CGCG/CGLS/MGCG/FGCG, GUI-idle CP interrupt)**. Our kernel never programs any of it (section 2.1). Their port in `src/compute.cpp:1600-1720` closely follows upstream `gfx_v12_0.c`, and it is on by default in their tree. Their own measured evidence, from an RX 9070 XT and not a Navi 44, puts idle at 131-300 W before clock gating and about 20 W after.
- **Elsewhere they are behind us**: SMU/PMFW plumbing (our SMU path has verdict logging, the UCLK pin and a soft-limit release path that theirs lacks), PSP (ours about 6x larger), IH (ours is on by default and theirs is off), SDMA and MES bring-up, display DET/watermarks, and the Metal path. Neither repo has VCN.
- **Gaps common to both projects**, and the real blockers for fan control, PPT limits and boost: neither parses or uploads the VBIOS powerplay table (`PPTABLE`). Both only send `UseDefaultPPTable`. Neither calls `SetPptLimit`. Neither drives a fan curve.
- **The Navi 44 claim is weak.** Their own `docs/PORT-NAVI44.md` says the port is untested on hardware. The Navi 44 work is a device-ID retarget of an RX 9070 XT display driver. The compute kernels are still gfx1201 binaries accepted on gfx1200. All hardware logs in the repo come from an RX 9070 XT.
- **Licence:** the root LICENSE is BSD-3 (Sunneva N. Mariu), the same lineage as our `research/refs/AMDRadeonRDNA4.kext` at commit 5ff69aa. `vulkan/` is MIT (Navi48-MacOS contributors). The AMD firmware blobs and a Sapphire VBIOS ROM are committed in the repo. Treat all of them as not ours to copy.

**Recommended path for the GFX-clock-without-idle goal, in order:**
1. Port GFX clock gating from upstream `gfx_v12_0.c` (cite their `compute.cpp:1600-1720` only as a cross-check). Low-to-medium risk. Biggest expected idle win.
2. Send `SetWorkloadMask(WORKLOAD_PPLIB_DEFAULT_BIT)` once after bring-up, as amdgpu does. Trivial.
3. Build the VBIOS powerplay-table reader and `TransferTableDram2Smu` upload. This is the gate for fan curve, PPT limit and a trustworthy max-boost picture. Medium-high effort.
4. GFXOFF last. Their own data says it is worth about 3 W on top of clock gating (16 W vs 19 W), and it needs proper refcounting (section 2.3).

---

## 1. Provenance and licence

| Item | Finding | Evidence |
|---|---|---|
| Commit | Single commit `387ed0b54990c644af0bd886d73abe1980171f73`, 2026-11-07 14:20:27 +0800, message `PORT-NAVI44: RX 9060 XT (Navi 44 / gfx1200) port of AMDRadeonRDNA4 0.1.0`. No history, no tags. | `git log` in clone |
| Root licence | BSD-3, `Copyright (c) 2026 Sunneva N. Mariu`. Identical to `research/refs/AMDRadeonRDNA4.kext/LICENSE` (commit 5ff69aa, 2026-08-21, RX4Darwin/AMDRadeonRDNA4.kext). | `LICENSE`; `diff` of `research/refs/` |
| Upstream lineage | `src/` display core (`atombios`, `edid`, `dmub.hpp`, `ipdiscovery`, `otgtiming`, `kmod_info.c`) is near-identical to our local copy of upstream 5ff69aa. Those files differ by 2-357 lines. 94 `src/` files are new, mostly compute/GFX bring-up. | `diff -rq` against `research/refs/AMDRadeonRDNA4.kext/src` |
| RDNA4FB | Same lineage: `research/ext/RDNA4FB-n44` is `somestupidgirl/RDNA4FB` at the same commit 5ff69aa. The README says the project was called RDNA4FB until October 2026. | `README.md:4-7`; clone of RDNA4FB-n44 |
| `vulkan/LICENSE-Navi48-MacOS` | MIT, Navi48-MacOS contributors. Same as `cobalt64/LICENSE` and `research/refs/7000-macos/LICENSE` (twhippp/7000-macos). | byte-identical files |
| `vulkan/LICENSE-Navi48-bringup` | BSD-3, the Navi48 project. Same as `cobalt64/src/navi48-bringup/LICENSE`. | byte-identical |
| `vulkan/mesa-patches/*`, `vulkan/navi48_native_abi.h` | Byte-identical to files in our `research/refs/7000-macos/` copy. These are not new Navi 44 work. | sha256 match |
| `tools/pipegen/shim/*`, `tools/dcn41` shims | Byte-identical to our `cobalt64/tools/dcn41/linuxshim`. Derived from the same lineage. | sha256 match |
| `src/amdgpu/clearstate_gfx12.h`, `clearstate_defs.h` | "Copyright 2023/2012 Advanced Micro Devices", MIT permission text. Upstream amdgpu headers, OK to reuse with attribution. | file header |
| New `src/*.cpp` (e.g. `compute.cpp`, `psp.cpp`, `sdma.cpp`, `pmidle.cpp`) | No SPDX or licence header. Implicit BSD-3 of the repo. Several are clearly ports of upstream amdgpu (`gfx_v12_0`, `RLC`, `SDMA`, `IH`), and amdgpu is MIT/GPL-2.0 dual. | file headers |
| `emu/qemu/rdna4.c` | `GPL-2.0-or-later`. Mixing a GPL file into a BSD-3 repo: flag only. Not used by us. | file header |
| `emu/efi/RdnaGop*` | `BSD-2-Clause-Patent` | file header |
| AMD firmware `firmware/amdgpu/*.bin` (gc_12_0_0 pfp/me/mec/rlc/imu/uni_mes, psp_14_0_2_sos/ta, sdma_7_0_0, smu_14_0_2) | Committed into the repo. Licence `firmware/amdgpu/LICENSE.amdgpu`: redistribution "in binary form only", no reverse engineering. Our `.gitignore` deliberately excludes firmware. **Do not copy the blobs into our tree**, and do not depend on theirs. | `LICENSE.amdgpu` text |
| `firmware/Sapphire.RX9070XT.16384.241213.rom` | A vendor VBIOS ROM committed to a BSD-3 repo. Redistribution rights unclear. Our `research/refs/RDNA4FB` holds the same file. | `firmware/` listing |
| NootRX / NootedRed | No source file contains NootRX or NootedRed code by name (grep by filename). The `README.md:36` mention is an analogy about injection. | grep, filenames only |
| MetalCyan (NootedRed fork, non-commercial licence) | `docs/metal-spike.md:302` says the authors "read" MetalCyan source (`file:line` citations from commit 4382dfa, [MEASURED] tags) and say NootRX is "read and cited only". This is **contamination risk for their docs**, and it applies to any finding in `docs/metal-spike.md`, `docs/metal-readiness.md`, `docs/m0-pvgpu.md`, `docs/emu-linux.md` that cites that source. Do not reuse anything from those docs. | `docs/metal-spike.md:302` (read only this line) |

**Licence verdict for reuse:** the register table in `src/gfxregs.hpp` and the message-id constants are facts that cross-check against upstream headers (section 2.4), so they are low-risk. Re-typing the CG sequence from upstream `gfx_v12_0.c`, rather than copying their file, is the cleanest route. Do not copy their firmware or the VBIOS ROM.

---

## 2. Inventory: what each part actually implements

Legend: **R** = real code and plausible; **P** = partial or probe-only; **S** = stub or absent. "Default" means whether it runs without a boot-arg.

| Component | Their repo (lines) | Default | Our kernel (lines) | Verdict |
|---|---|---|---|---|
| **GFX clock gating (CG)** | `src/compute.cpp:1581-1720` (CGCG/CGLS coarse, MGCG medium, repeater/SRAM FGCG, perf clock, GUI-idle). Safe mode `rlcSafeMode` at :1600-1616. Applied at `compute.cpp:858-861`. | **on** (mask 15, `requestedGfxCg` :1692) | **none**. `rlc_v12_0.cpp:520-525` says it "is programmed later in set_clockgating_state", which does not exist. No write to `RLC_CGTT_MGCG_OVERRIDE` (0x4c48) or `RLC_SAFE_MODE` (0x980) anywhere in `src/amd` or `src/Navi48Bringup.cpp`. | **their R, ours S. Largest gap.** |
| **GFX power gating / GFXOFF** | `compute.cpp:1046-1600`: `AllowGfxOff` (0x28), `DisallowGfxOff` (0x29), NVRAM persistent flag, `gfxOffAfterWake`, GC access guard `gcBusy`. Probe-only: `requestedGfxOff()` at :1576 needs `rdna4-gfxoff=1`. `gfxOffAllow` :1458 (one shot). | **off** | Only hold/release: `DisallowGfxOff` before GART setup (`amdgpu_init.cpp:282-287`), `AllowGfxOff` at teardown (:871-874). `gfxOffHeld` at `amdgpu_init.h:119`. No idle-driven allow. | **P** (theirs has the guard machinery but no refcount and no delayed work; ours has no allow path). |
| **GFXOFF refcount / idle delay** (amdgpu `amdgpu_gfx_off_ctrl`) | Not implemented. `pmidle.cpp` does idle accounting only and "sends no SMU message" (its header comment). | n/a | none | **S** in both. Upstream `amdgpu_gfx.c:930-990`. |
| **SMU mailbox and message ids** | `gfxregs.hpp:458-488`. All ids checked against upstream `smu_v14_0_2_ppsmc.h` (see 2.4). | n/a | `amd/amdgpu_ip.h:340-400`, `amd/smu_v14_0.cpp` (SMU_LOG names up to :150). | **R in both.** Ours is larger and has log/verdict infrastructure. |
| **SMU feature enable** | `compute.cpp:2100-2160` (display-safe mask minus UCLK/FCLK/DCN DPM, DS_*, GFXOFF, DF_CSTATE, ATHUB_MMHUB_PG, then fallbacks). `smuEnableFeatures` :2214-2254. | runs | `smu_v14_0.cpp:575-600` (SetAllowedFeaturesMask attempt, then EnableAllSmuFeatures) | **R both.** Their own W19 audit (`docs/gfx-pm-audit.md` §3) reports the card refuses the allowed mask (0xFD, CmdRejectedPrereq, SCPM) and runs its own pptable feature set. Their held-back list is therefore largely ignored. Ours logs 0xFE (UnknownCmd) for the same message, so the two cards/PMFW builds differ here. |
| **Workload profile** (`SetWorkloadMask` 0x24) | `compute.cpp:1877-1884`, **opt-in** (`rdna4-gfxpm=1`). Sends only `WORKLOAD_PPLIB_DEFAULT_BIT` (bit 0). | off | **none** | **P** theirs; **S** ours. amdgpu sends it once after init (`smu_v14_0_2_ppt.c:1975`). |
| **Soft clock limits** (`SetSoftMin/MaxByFreq` 0x19/0x1A) | `compute.cpp:1835-1839`, probe modes only. | opt-in | `smu_v14_0.cpp:850-905` (set_soft_freq_range, Low clamp, auto release). `power 0` path at :881-893 sets SoftMax 0xFFFF. | **R both**. Ours is the one in use (500 MHz clamp). |
| **UCLK pinning** | none (UCLK DPM is held back and not controlled). | — | `smu_uclkpin_pure.h:14-35` and `smu_v14_0.cpp:755-780`: GetMax/MinDpmFreq(UCLK) then SoftMinByFreq(UCLK). This is the 1258 MHz pin (0.0.673). | **R, ours only.** |
| **Metrics table (`TABLE_SMU_METRICS`, table 5)** | `compute.cpp:955-1010` (`readSensors`, `readSensorsEx`). Offsets in `src/smu_metrics.h`. | runs when asked | `smu_v14_0.cpp:960-1040` (`smu_read_metrics`), struct `amdgpu_smu.h:330-400` (260 bytes, static_assert). | **R both, same layout (0x2E).** See 2.5. |
| **Fan control** | Metrics read only (`AvgFanRpm` @170). No curve, no `SetMGpuFanBoostLimitRpm`. | — | Notes only: fan goes to max after `EnableAllSmuFeatures` without a pptable (`smu_v14_0.cpp:513-531, 820-840`; `amdgpu_smu.h:270-275`). | **S both.** Their W19 note says the fan "ramps and regulates" on the 9070 XT, which suggests the PMFW default curve works there. Ours is unresolved. |
| **PPT / power limit** (`SetPptLimit` 0x32, `GetPptLimit` 0x33) | none | — | none | **S both.** Needed for 3.2-3.5 GHz without runaway power. |
| **VBIOS powerplay table / `PPTABLE` upload** | none. Their tree never sends `UseDefaultPPTable` (0x14); grep finds no call. | — | `UseDefaultPPTable` best effort only (`smu_v14_0.cpp:513-533`). `smu_transfer_table_dram_to_smu` helper exists (`smu_v14_0.cpp:358-362`) but no caller uploads PPTABLE. | **S both. Blocker for fan curve, PPT, boost.** |
| **IH (interrupt handler) ring** | `src/ih.cpp` (975 lines). Register names match upstream IH v7 (`IhRbBase`, `IhRbCntl`, `IhRbWptr`, `IhDoorbellRptr`, `IhWptrAddrHi/Lo`). Sources: `IhSrcCpEop`, `IhSrcSdmaTrap`, `IhSrcVblankBase`, `IhSrcPflipBase`, `IhSrcGfxVmFault`. | **off** (`ih.cpp:162-163`: needs `rdna4-ih>=1`) | `amd/ih_v7_0.cpp` (749 lines, upstream IH v7 names). Enabled by **code default** (`Navi48Bringup.cpp:7417-7420`, `wantIrq = 1`, validated on hardware at 0.0.35). **The boot arg `navi48-interrupts=0` in the user's current boot-args disables it.** | **R both. Ours is default-on and more mature.** Their "3823 interrupt wakeups" claim is from RX 9070 XT logs (`docs/power-gfx.md` §1 table, `docs/final-test-plan.md`). |
| **SDMA** | `sdma.hpp/.cpp` (95 lines) are packet builders and a ring writer only. Engine bring-up is in `compute.cpp:2373-2640` (`sdmaStartMcus`, `sdmaQueueInit`, doorbell). Used for flip copy (`flip.cpp:365`) and IH test (`ih.cpp:314-325`). Hardware claim: `docs/hw-logs/2026-09-28-recovery-dma-pass.txt` (RX 9070 XT). | copies are used only in the flip path (opt-in) | `amd/sdma_v7_0.cpp` (2541 lines), used in the runtime copy path | **R both; ours broader.** |
| **PSP** | `psp.cpp` (272 lines): SOS load, LOAD_TOC, LOAD_IP_FW, AUTOLOAD_RLC. Real and short. | runs | `amd/psp_v14_0.cpp` (1777 lines), with runtime DB and PPTABLE_ERR entry parsing (:281-362) | **R both; ours far more complete.** |
| **MEC / compute queues (HQD)** | `compute.cpp` (3528 lines), `cp_v12`-style. Docs show dequeue timeouts and `device not responding` on the RX 9070 XT in round 6 (`docs/power-gfx.md` §1 F3). | stage 3-7, opt-in pieces | `amd/cp_v12_0.cpp` (2940), `amd/mes_v12_1.cpp` (1660). Our Metal path runs through RADV/our bundle. | **R-ish both; theirs had recorded failures.** |
| **MES** | Firmware loaded (`fwblobs.S:43`, `amdfw.cpp:204-207`), but no MES queue code. | — | `mes_v12_1.cpp` | **S theirs; R ours.** |
| **Gfx ring (PFP/ME)** | `gfxring.cpp` (1927). Ring and draw tests. Their own docs: "G3 0 px" draw failures in round 5 (`docs/power-gfx.md`). | opt-in | `amd/gfx_v12_0.cpp` (1046), `gfxring` paths | **P theirs.** |
| **Display (DCN)** | `pipe2_linux*.inc` are register traces recorded on RX 9070 XT, per connector (`docs/PORT-NAVI44.md:33`). DET programming appears only as trace rows (`pipe2_linux_hpd4.inc:253`). No DET0 20-segment fix (our 0.0.673) and no watermark code of our kind. | runs | `dcn/navi48_dcn.cpp` (3545), `navi48_disp2.h`, our DET/watermark fix in 0.0.673 | **Ours ahead.** |
| **VCN / video decode** | none (grep for vcn/uvd/vce/jpeg finds only false positives) | — | none | **S both.** |
| **Vulkan/RADV backend** | `vulkan/*` patches and ABI header. Byte-identical to our `research/refs/7000-macos`. | — | our bundle and `cobalt64/mesa-patches` | not new. |
| **Metal** | None. README says no 3D/Metal (`README.md:4`, "Scope"). | — | our Metal bundle and `libn48xlate` path | ours ahead. |

### 2.1 GFX clock gating: the largest gap

Our tree has no clock gating at all. Their port is the thing to compare against.

- Upstream `soc24.c:349-367`: GC 12.0.0 (Navi 44) gets `CGCG | CGLS | MGCG | 3D_CGCG | 3D_CGLS | REPEATER_FGCG | FGCG | PERF_CLK`, which is the same set as the 12.0.1 entry at :368-380. Their default mask 15 is therefore right for Navi 44.
- Upstream `gfx_v12_0_update_gfx_clock_gating` (`gfx_v12_0.c:4374-4393`) wraps every step in `amdgpu_gfx_rlc_enter_safe_mode/exit`. Their `rlcSafeMode` (`compute.cpp:1600-1616`) does the same with the same sequence (CMD | MESSAGE 1 in, wait for CMD to clear).
- Coarse grain (`gfx_v12_0.c:4155-4270`): unset CGCG/CGLS/3D override in `RLC_CGTT_MGCG_OVERRIDE`, write `RLC_CGCG_CGLS_CTRL` with threshold 0x36 and REP delay 0xF, the same for `_3D`, `CP_RB_WPTR_POLL_CNTL` = 0x0090 idle count and 0x0100 frequency, set the CP_INT_CNTL busy/empty/idle bits, and set `SDMAn_RLC_CGCG_CTRL.CGCG_INT_ENABLE`. Their `gfxCgCoarse` (`compute.cpp:1626-1654`) matches this line for line.
- Medium grain and fine grain: their `gfxCgMedium` and `gfxCgFine` (`compute.cpp:1656-1674`) match `gfx_v12_0.c:4272-4330`. Upstream `update_gfx_clock_gating` also calls `gfx_v12_0_update_perf_clk`, which they cover with the perf-clock override bit.
- Their evidence (gfx-pm-audit and power-gfx.md, **RX 9070 XT, not Navi 44, not independently verified**): "round-4 boot 14 went from 2541 MHz / 100 % / 131 W to 803 MHz / 3 % / 20 W with clock gating", reproduced in five non-VM boots (`docs/power-gfx.md` F6, `docs/hw-logs/2026-09-30-power-evidence/idle-power-by-boot.txt`). Log extracts only; the raw logs are not in the repo.

**Port plan (ours):**
- Effort: 1-2 days. About 250 lines in `cobalt64/src/navi48-bringup/src/amd/gfx_v12_0.cpp` or a new `gfx_v12_0_cg.cpp`, plus register constants (`RLC_CGTT_MGCG_OVERRIDE` 0x4c48, `RLC_CGCG_CGLS_CTRL` 0x4c49, `RLC_CGCG_CGLS_CTRL_3D` 0x4cc5, `RLC_SAFE_MODE` 0x980, `CP_RB_WPTR_POLL_CNTL` 0xf62, `CP_INT_CNTL` 0x1de9, `CP_INT_CNTL_RING0` 0x1e0a, `SDMA0/1_RLC_CGCG_CTRL` 0x055 / 0x655). These match upstream (`gc_12_0_0_offset.h`, section 2.4).
- Re-derive from upstream rather than copying their file. The upstream file is GPL-2.0 OR MIT for amdgpu; using it is fine with attribution.
- Risk: medium. RLC safe-mode timeouts and CP interrupt enables could hang the ring. Mitigate with a bounded wait (theirs does this) and a boot-arg off switch. Test in a planned boot, never on the live desktop.
- Known caveat: CG alone may not fix idle if a queue or wave keeps `GRBM_STATUS` GUI_ACTIVE high. Their own round-5 VM boots stayed at 100 % / 75-81 W even with the gating applied (`docs/power-gfx.md` F2, F4). Check `GRBM_STATUS` and `CP_STAT` before and after CG to tell the two apart.

### 2.2 Workload profile

- Upstream `smu_bump_power_profile_mode` sends `SetWorkloadMask(1 << WORKLOAD_PPLIB_DEFAULT_BIT)` once at init (`smu_v14_0_2_ppt.c:251,1975`; bit values in `smu14_driver_if_v14_0.h:1828`, DEFAULT=0).
- Theirs: opt-in via `rdna4-gfxpm=1`, same message (`compute.cpp:1877-1884`). Ours: none.
- Effort: hours. Risk: low. Add it after the DPM enable, log the response.

### 2.3 GFXOFF

- Upstream: `amdgpu_gfx_off_ctrl` (`amdgpu_gfx.c:930-990`) keeps `gfx_off_req_count`, starts it at 1 (`amdgpu_device.c:3887`), and releases the last hold through `gfx_v12_0_set_powergating_state` (`gfx_v12_0.c:4134-4148`, GC 12.0.0 and 12.0.1 both). Allow is delayed by 100 ms of idle (`gfx_off_delay_work`) and is gated on `PP_GFXOFF_MASK`.
- Theirs: `AllowGfxOff` is a one-shot probe at end of bring-up (`compute.cpp:1528-1550`), guarded by an NVRAM flag and a GC-access guard. Their own W19 audit (`docs/gfx-pm-audit.md` §4) says GFXOFF "is not offered in the experiment" because it would need every MMIO and doorbell access fenced. Their boot-5 probe showed GFXOFF reaching 16 W (vs 19 W clock-gated) and then waking into 100 % / 71-89 W, "unexplained" (`docs/power-gfx.md` F7).
- Ours: `DisallowGfxOff` and `AllowGfxOff` only around GART setup and teardown (`amdgpu_init.cpp:282-287, 871-874`).
- Their data says GFXOFF is worth about 3 W on top of CG. **So for the 170 W problem, GFXOFF is the second-order item.** Do CG first and measure.
- Effort: 1-2 weeks. Risk: high. A proper port needs the refcount, the 100 ms delayed work, the wake path, and GC access guards. Only then enable `AllowGfxOff` on idle.

### 2.4 Verification against upstream: what agrees

I checked constants against upstream master headers. Everything below agrees.

- **SMU message ids** (`smu_v14_0_2_ppsmc.h`): TestMessage 0x1, GetSmuVersion 0x2, GetDriverIfVersion 0x3, SetAllowedMask 0x4/0x5, EnableAllSmuFeatures 0x6, GetRunningFeatures 0xC/0xD, DriverDram 0xE/0xF, TransferTable 0x12, SoftMinByFreq 0x19, SoftMaxByFreq 0x1A, HardMinByFreq 0x1B, SetWorkloadMask 0x24, AllowGfxOff 0x28, DisallowGfxOff 0x29, RunDcBtc 0x36. Both repos agree on all of them. Upstream also defines SetPptLimit 0x32 and GetPptLimit 0x33, which neither repo uses.
- **Feature bits** (`smu14_driver_if_v14_0.h:46-103`): DPM_GFXCLK 1, DPM_UCLK 3, DPM_FCLK 4, DPM_DCN 7, GFXOFF 18, FW_CTF 28, FAN_CONTROL 29, GFX_IMU 36, DF_CSTATE 40, ATHUB_MMHUB_PG 47. Their `gfxregs.hpp:484-488` matches.
- **MP1 mailbox**: `regMP1_SMN_C2PMSG_66` = 0x0082, base index 1 (`mp_14_0_2_offset.h`). Their `SmuMsg/SmuArg/SmuResp` (0x82/0x92/0x9a) match.
- **GC register table**: 204 of 224 entries in their `src/gfxregs.hpp` exist in upstream `gc_12_0_0_offset.h` at the same offset and base index, with the same names (checked by script, see 2.5). The 20 misses are MMHUB (`MM*`, 0x4c7-0x5d0) and NBIF entries I did not check against the NBIF/MMHUB headers. Spot-checked names: `CP_RB0_BASE`, `RLC_SRM_CNTL`, `GFX_IMU_CORE_CTRL`, `RLC_SAFE_MODE`, `RLC_CGTT_MGCG_OVERRIDE`, `CP_MEC_RS64_CNTL`, `GCVM_L2_PROTECTION_FAULT_CNTL`, `SPI_COMPUTE_QUEUE_RESET`, `SQ_CMD`, `CP_VMID_RESET`. Our `amd/amdgpu_rlc.h:70-77` uses the same 0x4c49 for `RLC_CGCG_CGLS_CTRL`.

### 2.5 Metrics table and IF 0x33

- Upstream master `smu14_driver_if_v14_0.h:1649-1727` (`SmuMetrics_t`) defines the layout. Their offsets (`src/smu_metrics.h`) agree with it exactly for: CurrClock @0, AvgGfxclkPreDs @46, AvgGfxclkPostDs @48, AvgMemclkPostDs @56, MovingAverageGfxActivity @90, MetricsCounter @104, AvgVoltage @108, AvgCurrent @116, AverageGfxActivity @124, AverageUclkActivity @126, AverageSocketPower @136, AvgTemperature @140, AvgFanRpm @170, ThrottlingPercentage @172. Our `amdgpu_smu.h` mirrors the same struct and carries `static_assert(sizeof == 260)`.
- Upstream pins `SMU14_DRIVER_IF_VERSION_SMU_V14_0_2 = 0x2E` (`smu_v14_0_2_ppt.c:74`). Upstream also has 0x7 for 14.0.0 and 0x6 for 14.0.1, but there is **no published layout for 0x33** in upstream master (`pmfw_if/` contains only `smu14_driver_if_v14_0.h` and `_v14_0_0.h`).
- Both repos see IF 0x33 on the card. Their `compute.cpp:1823` says "AvgCurrent not trusted on IF 0x33". Our `amdgpu_smu.h:387-400` and `smu_v14_0.cpp:979-1026` set `layout_verified = false` on 0x33 and say "fields near the start are very likely still correct; anything deep may have shifted."
- Practical policy: trust fields up to `AvgFanRpm`, `CurrClock[]`, `MetricsCounter` and the activity counters. Do not present `ThrottlingPercentage`, `AvgCurrent`, `EnergyAccumulator` or the D3hot counters as fact on 0x33 until they are checked against a known event (for example, a deliberate power-limit throttle).
- Cross-checks to add: `CurrClock[GFXCLK]` against `GetDpmFreqByIndex`, and `EnergyAccumulator` deltas against `AverageSocketPower`.

### 2.6 Interrupts (IH)

- Both repos use the same IH v7 register names. Theirs is more complete in source enumeration (EOP, SDMA trap, VBLANK, PFLIP, GFX VM fault). Theirs is **off by default** (`ih.cpp:162`).
- Ours is **on by default** (`Navi48Bringup.cpp:7417-7420`, validated at 0.0.35 on hardware) and the user's current boot-arg `navi48-interrupts=0` disables it. The perf plan's item #2 (fence wait spinning, 7.25 s of kernel time per 10 s) is solved by re-enabling it and blocking on EOP, not by porting theirs.
- Recommendation: keep ours. Do not port theirs. Re-test `navi48-interrupts=1` with the fence-wait change in one planned boot.

---

## 3. Highest-value items for the power-management goal, ranked

| # | Item | Source to cite | Effort | Risk | What it fixes |
|---|---|---|---|---|---|
| 1 | GFX clock gating (CGCG/CGLS/MGCG/FGCG/GUI-idle) | upstream `soc24.c:349-367`, `gfx_v12_0.c:4155-4393`; their `compute.cpp:1600-1720` as cross-check | 1-2 days | medium | idle power from clock-high state (their evidence: 131-300 W to 20 W, on RX 9070 XT) |
| 2 | `SetWorkloadMask(DEFAULT)` after DPM enable | upstream `smu_v14_0_2_ppt.c:1975`; theirs `compute.cpp:1877` | hours | low | PMFW gets the boot profile it expects |
| 3 | VBIOS powerplay table read and `TransferTableDram2Smu(PPTABLE)` upload | upstream `smu_v14_0.c:232-283` (`smu_v14_0_get_pptable_from_vbios`, `powerplayinfo`), `smu_v14_0_setup_pptable` | 1-2 weeks | medium-high | unlocks fan curve, PPT limit (`SetPptLimit` 0x32), correct DPM table max |
| 4 | PPT limit via `SetPptLimit` (after 3) | upstream `smu_v14_0.c:689-712` | days | low | caps socket power so 3.2-3.5 GHz does not run away |
| 5 | Memory at factory max: read `GetMaxDpmFreq(UCLK)` and pin SoftMin to it | ours `smu_uclkpin_pure.h`, `smu_v14_0.cpp:755-780` (already done for 1258 MHz) | hours | low | UCLK at max rather than hard-coded; do not hard-code 1258 |
| 6 | GFXOFF with proper refcount and idle delay | upstream `amdgpu_gfx.c:930-990`, `gfx_v12_0.c:4134-4148`; theirs `compute.cpp:1046-1600` as design reference only | 1-2 weeks | high | about 3 W (their data); needed later for real idle |
| 7 | Metrics validation for 0x33 | ours `amdgpu_smu.h:387-400` | days | low | trustworthy telemetry for the above |
| 8 | Interrupts: keep ours, re-test `navi48-interrupts=1` with EOP blocking | ours `Navi48Bringup.cpp:7417-7420` | hours (test) | medium | removes fence spinning (perf plan #2) |

**Gate for 3.2-3.5 GHz without the 170 W idle:** items 1 and 2 first, then measure idle with the GFX clock released, then 3 and 4. Do not release the clamp (`power 0` path, `smu_v14_0.cpp:881-893`) before 1 is in and tested.

**Fan:** neither repo has a fan curve. Their tree never sends `UseDefaultPPTable`, so their fan behaviour comes from the PMFW boot pptable alone. On their card the PMFW default regulates the fan; on ours the fan pins to max after `EnableAllSmuFeatures` (notes at `smu_v14_0.cpp:513-531`). The difference is unexplained. Check whether our card's PMFW pptable has a fan table, and whether `AvgFanPwm` moves under load before writing curve code.

---

## 4. Red flags and claims to discount

1. **Platform mismatch.** `README.md:1-8` describes an RX 9070 XT (0x7550) display-only Lilu plugin with "No 3D/Metal acceleration". The compute code and `docs/PORT-NAVI44.md` target 0x7590. The README was not updated.
2. **Hardware evidence is for the wrong card.** Every hardware log and measurement (idle 131-300 W, clock gating 20 W, GFXOFF 16 W, SDMA recovery pass, IH "3823 wakeups", the 3422 MHz / 75 W sample) comes from an RX 9070 XT (Navi 48, GC 12.0.1). The repo's `firmware/` even includes a Sapphire RX 9070 XT VBIOS. Transfer to Navi 44 (GC 12.0.0) is by analogy only.
3. **Their own port doc says it is unverified.** `docs/PORT-NAVI44.md`, section "已知边界与未验证项": "本移植未经硬件验证" (this port is not verified on hardware). The compute kernels are still gfx1201 binaries; the code-object check was relaxed to accept `0x4e` as well as `0x4d`. Second display is untested. PMFW 14.0.2 behaviour is unverified.
4. **Inconsistent SMU identity.** `gfxregs.hpp` and `docs/PORT-NAVI44.md` say the Navi 44 SMU is 14.0.2. `compute.cpp:2139` says "this card's MP1 is 14.0.3". Ours uses 14.0.3 (`amd/amdgpu_ip.h:37-52`).
5. **Different refusal codes for the same message.** Theirs logs 0xFD (CmdRejectedPrereq) for `SetAllowedFeaturesMask` (`docs/gfx-pm-audit.md` §2 row 1). Ours logs 0xFE (UnknownCmd, `smu_v14_0.cpp:566-577`). Check which PMFW build each card runs before comparing.
6. **Docs cite history that the repo does not contain.** One squashed commit, but the docs reference branches (`premetal/power`, `premetal/pm`, `premetal/int`), an external `~/work/tools/linux-amdgpu` and a `docs/rdna4-navi44-porting-analysis.md` that lives in "the main project". Hardware log files are "extracts" with the originals on an OpenCore stick. None of that can be checked here.
7. **"[M] measured" labels** in `docs/power-gfx.md` are attached to log extracts. The extracts look internally consistent (sensor lines match between files), but the raw logs are not in the repo. Treat them as plausible, not verified.
8. **Recorded failures.** Their own round-5 and round-6 logs show dequeue timeouts, VM self-test failure and `device not responding` (`docs/power-gfx.md` F2, F3; `docs/hw-logs/2026-09-30-round6-client-paths-fail.txt`). Their compute path was not working on the card as last recorded.
9. **AI-assisted writing is plausible** (uniform W-numbered workstreams, long hedged tables, mixed-language docs). I cannot establish provenance from the repo. Do not rely on any single claim without a reproduction.
10. **Their GFXOFF probe is unsafe to enable.** `AllowGfxOff` without refcounting and with GC access unguarded can strand the card at 100 % (their boot-5 result).
11. **Licence hygiene.** Committed AMD firmware and a vendor VBIOS ROM sit inside a BSD-3 repo, and an RX 9070 XT ROM is a redistribution question. GPL-2.0 `emu/qemu/rdna4.c` is mixed in without a note.
12. **Their GFX-clock-stays-at-max hypothesis list** (`docs/gfx-pm-audit.md` §6) ranks "the sample was the tail of the benchmark" as most likely. Treat their "300 W at 3200 MHz" as an unmeasured observation until it is repeated at idle.

---

## 5. What we did not verify

- Nothing was built, run or loaded. The 9070 XT numbers and the Navi 44 analysis are from source and logs only.
- The NootRX and NootedRed sources were not opened. MetalCyan (a NootedRed fork) is named in one of their docs. That doc was read only at its provenance line.
- Upstream headers were taken from the Linux master branch, not from the 7.2.2 tag the repo cites. Offsets could differ slightly for older kernels.
- The 0x33 metrics layout is not published anywhere I could reach. Section 2.5's policy is an inference.
- The 0x33 PMFW's SetAllowedFeaturesMask refusal (0xFD on theirs, 0xFE on ours) was not confirmed on a single card.

---

## 6. Provenance sentence, verbatim (for the licence file)

`docs/metal-spike.md:302` (quoted only as a provenance pointer): "[github.com/amethyst8118/MetalCyan] ... a Lilu plugin forked from ChefKiss' NootedRed ... Licence: **Thou Shalt Not Profit License 1.5**, incompatible with this repo's BSD-3-Clause, so, like NootRX, it is **read and cited only**." Their claim, not verified. Any finding in their docs that cites `file:line` in MetalCyan should be treated as contaminated for our purposes.

---

## Appendix A. Paths

Clone (read-only): `~/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/ext/hailuo2456-navi44`

Their key files (relative to the clone):
- `src/compute.cpp`: CG 1581-1720; GFXOFF 1046-1600, 1576; workload 1877; feature enable 2100-2160, 2214-2254; metrics 955-1010; IF 0x33 caveat 1823.
- `src/gfxregs.hpp`: SMU messages 458-488; register table 27-410.
- `src/smu_metrics.h`: metrics offsets.
- `src/ih.cpp`: IH ring and sources, default off at 162.
- `src/sdma.cpp`, `src/sdma.hpp`: packet builders only.
- `src/psp.cpp`: PSP load, 272 lines.
- `docs/gfx-pm-audit.md`: W19 ranked causes, §2-§7.
- `docs/power-gfx.md`: measured claims F1-F7 (RX 9070 XT).
- `docs/PORT-NAVI44.md`: porting status and known limits.
- `firmware/amdgpu/LICENSE.amdgpu`: firmware licence.

Ours (absolute, under the project root `~/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver`):
- `cobalt64/src/navi48-bringup/src/amd/rlc_v12_0.cpp:520-525`: CG comment, no CG writes.
- `cobalt64/src/navi48-bringup/src/amd/amdgpu_init.cpp:282-287, 871-874`: GFXOFF hold and release.
- `cobalt64/src/navi48-bringup/src/amd/amdgpu_smu.h:306-400`: metrics layout, IF 0x2E pin, 0x33 caveat, `static_assert` 260.
- `cobalt64/src/navi48-bringup/src/amd/smu_v14_0.cpp:513-533`: UseDefaultPPTable; `:575-600` feature mask attempt; `:755-780` UCLK pin; `:850-905` soft limits and `power 0` path; `:960-1040` metrics read.
- `cobalt64/src/navi48-bringup/src/amd/smu_uclkpin_pure.h:14-35`.
- `cobalt64/src/navi48-bringup/src/amd/amdgpu_ip.h:37-52`: IP versions (SMU 14.0.3).
- `cobalt64/src/navi48-bringup/src/Navi48Bringup.cpp:7417-7420`: IH default on.
- `cobalt64/src/navi48-bringup/LICENSE` (BSD-3 "the Navi48 project") and `cobalt64/LICENSE` (MIT "Navi48-MacOS contributors").
- `research/reports/macos-20261112/performance-plan.md` §1.3 and §2 items 1-2 (the clamp and the fence wait).
- `research/reports/macos-20261112/memclk-display-power.md` (not re-read in this pass).

Upstream (fetched to the scratchpad, not in the project): `gfx_v12_0.c`, `soc24.c`, `amdgpu_gfx.c`, `smu_v14_0.c`, `smu_v14_0_2_ppt.c`, `smu_v14_0_0_ppt.c`, `smu_v14_0_2_ppsmc.h`, `smu14_driver_if_v14_0.h`, `mp_14_0_2_offset.h`, `gc_12_0_0_offset.h`, `amdgpu_discovery.c`.
