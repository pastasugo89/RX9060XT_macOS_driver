# Memory clock vs. display scanout: how others do it, and what we should do

Date: 2026-11-12. Scope: read-only research. No sudo, no register writes, no edits to tracked files.
Card: RX 9060 XT 16 GB (Navi 44, GC 12.0.0, DCN 4.01, PMFW 102.71.0 = `0x00664700`, DMCUB `0x0a004b00`).
Kernel loaded at the time of writing: `com.navi48.bringup` **0.0.671**. 0.0.672 (UCLK pin plus ufmon) is not installed.
`/Library/Application Support/Navi44/accelerated-trial/refresh-60` is absent right now, so the next boot is at 120 Hz unless the flag is recreated.

Linux sources used: `research/ext/amdgpu-port-study/linux-v7.3/drivers/gpu/drm/amd/...`, shortened below to `amd/...`.

---

## 0. Executive summary

1. **Linux does not pin memory for our setup. It almost certainly uses the plain hardware "vactive" method.**
   - With one 2560x1440@120 plane, DML21 tries the methods in this order: **vactive** → SubVP → alternate → vblank → FW-DRR (`dml2_pmo_dcn4_fams2.c:13-51`).
   - Linux gives a single pipe up to about 1280 KB of DET (MRQ formula, `dml2_core_dcn4_calcs.c:410`). That is about 128 lines of 2560×4 B, or about 700 µs of buffering.
   - The UCLK p-state watermark needs about 409 µs (400 µs blackout plus urgent latency).
   - So the memory switch is hidden **during active scanout**. It needs neither vblank, FAMS2 nor MALL.
   - UCLK stays free to drop to the lowest DPM level, **96 MHz** (`pp_dpm_mclk`: 96/456/772/875/1124/1258).
   - On a static desktop, Linux can also put the frame in the 32 MB MALL (CAB, `dcn401_apply_idle_power_optimizations`).
2. **Our kext does none of the DCN side.**
   - It never touches DCHUBBUB arbitration (watermarks, DRAM_STATE_CNTL force bits) and never resizes DET. The GOP left a **192 KB DET** (DET0 = 0x303, 3 × 64 KB), which is only about 19 lines, about 105 µs.
   - It never tells the PMFW anything about the display: no DALSMC NumOfDisplays, SetUclkPstateAllow or hard minimum.
   - With GOP buffering, an UCLK switch can only be hidden inside vblank. At 120 Hz the vblank is 85 lines = 464.5 µs, which leaves an allow window of about 100 µs per frame. It is correct only if the GOP's watermarks are right for a 400 µs blackout, and that is unverified.
3. **The 0.0.672 pin removes the symptom but costs idle power.**
   - My estimate is **+8 to +15 W board power at idle** on this 16 GB card (128-bit GDDR6 at 20 Gbps versus 96 MHz), and a few °C. This is an estimate, not a measurement; see §4a.
   - That is worse than Linux or Windows on a single 1440p display.
4. **Recommendation:**
   - **Now:** run the read-only register dump in §3.3. It is cheap and decides between the hypotheses.
   - **Interim:** ship 0.0.672 with the pin **on**, but only as a short A/B instrument, with an explicit plan to replace it.
   - **Next (0.0.673):** a "Linux-equivalent" display-aware UCLK.
     - Clear any force-allow left by the GOP.
     - Program the UCLK, FCLK and SR watermarks and a large DET0 using golden values captured from Linux on this exact monitor and mode.
     - Send the DALSMC NumOfDisplays / SetUclkPstateAllow / hard minimum.
     - Keep ufmon as a watchdog that falls back to the pin if underflows ever reappear.
   - That gives memory power management equal to Linux and Windows. MALL/CAB static-screen would be better still, but is a later, optional stage.

Confidence: high on what the Linux code does; medium on "Linux would choose vactive here" (hand-evaluated DML, not run); low-to-medium on the power estimates.

---

## 1. Linux amdgpu: DCN 4.01 + SMU 14.0.2

### 1.1 Hardware handshake (DCHUBBUB ↔ PMFW)

**Watermarks** (`amd/display/dc/hubbub/dcn401/dcn401_hubbub.c`):

- **Urgent:** `hubbub401_program_urgent_watermarks` (:67). DATA_URGENCY, FRAC_URG_BW_*, REFCYC_PER_TRIP_TO_MEMORY, META_TRIP.
- **Stutter / self-refresh:** `hubbub401_program_stutter_watermarks` (:186). ALLOW_SR_ENTER/EXIT for sets A and B.
- **P-state:** `hubbub401_program_pstate_watermarks` (:286-411).
  - `DCHUBBUB_ARB_UCLK_PSTATE_CHANGE_WATERMARK_A/B`: DRAM clock change.
  - `..._UCLK_PSTATE_CHANGE_WATERMARK1_A/B`: temp-read / PPT dummy p-state.
  - `DCHUBBUB_ARB_FCLK_PSTATE_CHANGE_WATERMARK(1)_A/B`.
- **USR retraining:** `hubbub401_program_usr_watermarks` (:414).
- **Wrapper:** `hubbub401_program_watermarks` (:454). It ends with `hubbub1_allow_self_refresh_control` (DRAM_STATE_CNTL SR force bits) and `hubbub32_force_usr_retraining_allow`.
- **Init:** `hubbub401_init_watermarks` (:501) copies set A to set B. Linux calls it only when the VBIOS was not in accelerated mode (`dcn401_hwseq.c:374`).
- **Units:** values are DCHUB refclk cycles; the SoC bounding box has `dchub_refclk_mhz = 50`. The DTN log we captured on Linux (`research/hw_dump/dm_dtn_log.txt`) shows WM set A/B as urgent 8.8, sr_enter 57.92, sr_exit 44.92, dram_clk_change **408.8 µs**.

**The allow signal.** DCHUBBUB raises "allow UCLK p-state change" toward the PMFW when every active HUBP has buffered enough data (DET, plus the line buffer, or the remaining vblank) to cover the p-state watermark. Software can override it with `DCHUBBUB_ARB_DRAM_STATE_CNTL` bits:

| Bit | Field |
|---|---|
| 0 | `ALLOW_SELF_REFRESH_FORCE_VALUE` |
| 1 | `ALLOW_SELF_REFRESH_FORCE_ENABLE` |
| 4 | `ALLOW_PSTATE_CHANGE_FORCE_VALUE` |
| 5 | `ALLOW_PSTATE_CHANGE_FORCE_ENABLE` |

Bit layout is from `dcn_4_1_0_sh_mask.h:5913-5930`; the override is applied by `hubbub3_force_pstate_change_control` (`hubbub/dcn30/dcn30_hubbub.c:391`).

Per-pipe overrides also exist:
- `HUBPREQx_UCLK_PSTATE_FORCE` (DATA/CURSOR_UCLK_PSTATE_FORCE_EN/VALUE).
- `OTGx_OTG_PSTATE_REGISTER` (KEEPOUT_START, EXTEND, ALLOW_WIDTH_MIN), which FAMS2 and SubVP use.

**What Linux does with the force bits** (`hwss/dcn401/dcn401_hwseq.c`):
- **init_hw** (:380): `force_pstate_change_control(false,false)`. Force is cleared, so the hardware watermark decides.
- **First plane enabled after none** (:1888): force allow for 500 µs while the pipes come up. **After programming** (:2575, :2775): force is removed.
- **`dcn401_hardware_release`** (:1875-1893): on driver unload, if p-state is unsupported or FAMS2 is active, Linux **forces allow = 1**. The comment says "force it supported by dcn". The reason is that the PMFW keeps working after the OS driver leaves, and must not be blocked by a display that no longer has a driver.

  This implies the PMFW **waits for the DCN allow before it switches UCLK**. `hubbub1_verify_allow_pstate_change_high` (`dcn10_hubbub.c`) says that if allow stays low "we are probably stuck and going to hang". The PMFW is closed and is not disassembled here, so this is an inference from the driver code (medium confidence).

  Consequence: a pre-OS GOP plausibly leaves either the force-allow bits set, or watermarks never validated against a 400 µs blackout, because UCLK DPM is off before the OS driver enables it. **This is exactly what the §3.3 dump checks.**

**DCN → PMFW messages.** These go through the separate DALSMC mailbox (`clk_mgr/dcn401/dalsmc.h`), not the MP1 driver mailbox our SMU code uses. They are sent by `dcn401_execute_block_sequence` and built in `dcn401_build_update_bandwidth_clocks_sequence` (`dcn401_clk_mgr.c:769-1072`):

| Message (id) | When Linux sends it |
|---|---|
| `NumOfDisplays` (0xE) | Every update. With 0 displays the PMFW knows there is no isochronous client. |
| `SetHardMinByFreq` (0x9) PPCLK_DCFCLK | DCFCLK needed by DML. |
| `SetMinDeepSleepDcfclk` (0xD) | DCFCLK deep-sleep floor. |
| `SetUclkPstateAllow` (0x1A) = 1 | When DML says p-state is supported (:908-922). |
| `SetUclkPstateAllow` = 0 | When unsupported (:1024-1031). |
| `SetHardMinByFreq` UCLK = `max_memclk_mhz` | **Only if p-state is unsupported**: "when P-State switching disabled, set UCLK min = max" (:924-937). Otherwise the hard minimum is DML's required `dramclk_khz`. |
| `ActiveUclkFclk` / `IdleUclkFclk` (0x18/0x19) | Only if "idle DPM" is enabled. For GC 12.0.0 that needs PMFW ≥ `0x681800` (`dcn401_is_ppclk_idle_dpm_enabled`, :121-143). **Our PMFW `0x664700` is below that, so Linux would use the plain UCLK hard minimum.** |
| `IndicateDrrStatus` (0x17), `SetAlwaysWaitDmcubResp` (0x16) | When FAMS2 / FW-based MCLK switching is turned on or off. |
| `SetCabForUclkPstate` (0x12) | SubVP / MALL ways. |
| WM range table (`TransferTableDram2Smu`) | `notify_wm_ranges` at init (`dcn401_hwseq.c:377`). Uses `dcn401_build_wm_range_table`, which has set A for all clocks. |

**SMU side** (`amd/pm/swsmu/smu14/smu_v14_0_2_ppt.c`):
- It has **no display hooks for SMU 14.0.2**: no display_config_change, no set_watermarks_table use, no NumOfDisplays via MP1. All display coordination for DCN4 goes through the DALSMC channel above.
- The MP1 side only does generic DPM: feature enable, workload mask `SetWorkloadMask` (:1848-1897), and soft/hard limits.
- Feature bits (`smu14_driver_if_v14_0.h:46-109`): our running mask `0x0498f59e_38fffcfb` is identical to Linux. It includes DPM_UCLK (3), DPM_FCLK (4), DPM_DCN (7), DS_FCLK (12), DS_DCFCLK (14), DS_UCLK (15) and MEM_TEMP_READ (46).

### 1.2 DML21 per-mode decision, applied to our mode

**Inputs.** DCN 4.01 IP and SoC (`dml2_0/dml21/inc/bounding_boxes/dcn4_soc_bb.h`):
- `dram_clk_change_blackout_us = 400`.
- `fclk_change_blackout_us = 0`.
- Stutter: 54 µs enter+exit, 41 µs exit.
- `config_return_buffer_size_in_kbytes = 1344` in 64 KB segments; ROB 192 KB.
- `max_vactive_det_fill_delay_us = 400`.
- FAMS2 timing caps (:356-370).
- `mall_allocated_for_dcn_mbytes = 64`. At runtime this is replaced by channels × 4 MB, clamped to 16 channels on GC 12.0.0 (`dcn401_resource.c:1449-1468, 2080-2089`). Navi 44 has 32 MB Infinity Cache, so 32 MB MALL.
- `dcn401_resource.c:795-806`: FAMS v2.1 enabled, SubVP allowed.

**Strategy order for one display** (`dml2_pmo_dcn4_fams2.c:13-51`):
1. vactive
2. fw_svp (SubVP)
3. alternate
4. vblank
5. fw_drr (FAMS2 V_TOTAL stretch)

DRR variants are added only when the timing is DRR-enabled; the DRR rate limit is ≥ 119 Hz (:685-686). FAMS2 (`fams2_required`) is set only for SubVP/DRR methods (:2196-2233). **vactive and vblank are pure-hardware methods, with no DMUB involvement.**

**Rules:**
- **vactive** is supported if `ActiveDRAMClockChangeLatencyMargin > 0` (`dml2_core_dcn4_calcs.c:6880-6990`):

  `margin = LB_hiding + floor(DET lines to swath) * line_time - DST_after_scaler - DRAMClockChangeWatermark`

- **vblank** reserves `reserved_vblank_time = 400 µs` (`setup_planes_for_vblank_by_mask`, :2113). The prefetch must then fit into `VStartup - TWait`, where `TWait = 400 + max(urgent, trip)` (`CalculateTWait`, :4861).
- **unsupported:** the clock manager sets `SetUclkPstateAllow(0)` and pins the UCLK hard minimum to max.

**DET:**
- MRQ is present on DCN4 (`dml2_core_dcn4.c:151`), so `MaxTotalDET = ceil((1344+192)*4/5, 64) = 1280 KB` (:410).
- With one stream, all of the budget goes to that plane (:1100-1155). With ODM 2:1 it is split 640 KB + 640 KB over half the width each, which gives the same time coverage.

**Our timing.** Pixel clock 497.75 MHz, H_TOTAL 2720, V_TOTAL 1525, ARGB8888, 2560 wide.

| Quantity | Value |
|---|---|
| Line time | 2720 / 497.75 = **5.4646 µs** |
| Vblank | 85 lines = **464.5 µs** |
| Line bytes | 2560 × 4 = 10 240 B |
| Linux DET | 1280 KB → 128 lines → about **700 µs** (+ line buffer, − about 5 lines DST_after_scaler) |
| Watermark | about 400 + 8.8 → **about 409 µs** |
| Margin | about **+260 to +290 µs > 0 → vactive supported** |

The same holds at our 60 Hz mode (same line time). DET needed for vactive: about (409 + 27) / 5.4646 ≈ 80 lines ≈ **800 KB → 13 segments**.

**vblank at 120 Hz** would be marginal or fail: 464.5 − 400 − about 9 leaves about 55 µs for prefetch. It does not matter, because vactive comes first.

**What Linux would end up with** for this monitor at 2560x1440@120 on Navi 44:
- `p_state_change_support = true`, so `SetUclkPstateAllow(1)`.
- UCLK hard minimum = DML's bandwidth minimum. 1.77 GB/s scanout is far below what even 96 MHz UCLK delivers: 128-bit × about 1.5 Gb/s ≈ 24 GB/s.
- The PMFW is free to idle UCLK at **96 MHz**.
- On a static screen it can also enter MALL CAB (`dcn401_apply_idle_power_optimizations`, `dcn401_hwseq.c:1260+`). The 14.7 MB frame fits in 32 MB.

**Idle power.** We have Linux numbers only with the monitor **off**: MCLK 96, SoC average 8 to 12 W, 29 to 33 °C (`research/hw_dump/pm_info.txt`, `linux-oracle-20261020T181307Z/*pm_info.txt`, README: "monitors off"). With one 1440p120 display I expect Linux idle in the same order, about 10 to 15 W board. **This is not measured on this monitor; §3.4 M1 measures it.**

### 1.3 Real-world behaviour (anecdotal, cited)

- **RDNA4 under Linux (RX 9070 XT, dual monitor 144 + 100 Hz):** forcing the "high" performance level stopped DP flicker, but idle rose to **45 to 55 W, versus 15 to 30 W** in auto, because VRAM stopped down-clocking ([CachyOS forum](https://discuss.cachyos.org/t/rx-9070-xt-dual-monitor-displayport-signal-drops-at-high-refresh-rates-wayland/29949)).
  - Other reports: VRAM held at max on 5120x1440@240 in auto mode, which is DML's "unsupported → pin" path; VRAM stuck after resume ([CachyOS](https://discuss.cachyos.org/t/gpu-vram-clock-wont-turn-down-after-sleep/33493)); and an RDNA4 idle-power fix after compute workloads in Linux 7.0 ([linux.org/Phoronix](https://www.linux.org/threads/phoronix-linux-7-0-amdgpu-fixing-idle-power-issue-for-rdna4-gpus-after-compute-workloads.63745/latest)).
  - Pattern: **Linux pins VRAM only when DML says no method works** (high pixel rate, multiple displays, short vblank and DET not enough). A single 1440p120 display is well inside the vactive envelope.
- **Windows (Adrenalin):** the display core (DC/DML) is the same code base AMD shares with Linux, so Windows makes the same per-mode decisions, including FAMS2 and MALL/CAB.
  - From memory, not verified for this report: the RDNA3 "high idle at high refresh / multi-monitor" saga was fixed only partly by driver releases in 2023. It stems from exactly this pin-when-unsupported rule.
  - For the 9060 XT at idle on Windows (FHD@60), Igor's Lab measured **17.9 W (XFX) and 18.3 W (Sapphire)** board power ([igorslab](https://www.igorslab.de/xfx-swift-radeon-rx-9060-xt-und-sapphire-nitro-rx-9060-xt-im-test-amds-antwort-auf-die-geforce-rtx-5060-ti/12/)).
  - I could not retrieve TechPowerUp's or PCGH's multi-monitor tables (HTTP 403).

---

## 2. NullMoth NVIDIA driver (RTX 5060), behaviour only

This section is from `research/refs/nvidia-macos-driver` at `0960b2ef` (1.13.0). It is PolyForm Noncommercial, so I read it for behaviour only and copied no code.

- The driver links NVIDIA's own r610 open RM/HAL + GSP stack and the stock nvkms modeset library. Only the flip-completion notifier object is replaced (`docs/CARD-SUPPORT.md:3`, `README.md:40`, `docs/HOW-IT-WORKS.md:23-50`, `kexts/NVRM/patches/README.md`).
- **It does not manage clocks or P-states at all.**
  - The driver's own code has no `NV2080_CTRL_CMD_PERF_*`, CLK, PMGR or perf-limit calls. Its only own 0x2080 control is FB_GET_INFO_V2 (`kexts/NVRM/nvrm_fbinfo.cpp:28`).
  - `os_registry_init` is empty (`kexts/NVRM/os-xnu.cpp:290`).
  - `nv_dynamic_power_available` returns false (`kexts/NVRM/nv_xnu_stubs.cpp:254-258`).
  - `nvkms_disable_vrr_memclk_switch()` returns false (`kexts/NVRM/os-nvkms-xnu.cpp:153`). NVIDIA's VRR-aware MCLK switch is left **enabled**.
- **MCLK safety therefore comes entirely from NVIDIA's code.** The nvkms IMP (isohub) validation tells RM/GSP which MCLK switches the display can tolerate, and GSP performs them in vblank or refuses. It is the same division of labour as AMD's DML → DALSMC/PMFW, done by vendor code that NullMoth reuses unchanged.
- **No power, clock or temperature telemetry is exposed.** It only publishes a boot-raster refresh measurement (`kexts/NVRM/NVRM.cpp:407-444`).
- High-refresh flicker on some DP monitors is listed as a known issue with no root cause (`docs/RELEASE-1.10.0.md:23-28`, `RELEASE-1.11.0.md:22`, `RELEASE-1.13.0.md:24`).

**Lesson for us:** NullMoth reaches "equal to the vendor" because they run the vendor's own display-bandwidth model. We have no vendor blob, so the equivalent is to reproduce DML's **outputs** for our few fixed modes (golden values from Linux) and to send the same DALSMC messages.

---

## 3. Our stack today

### 3.1 What the kext programs

- **DCHUBBUB arbitration: nothing.** No code touches ARB watermarks, DRAM_STATE_CNTL, WATERMARK_CHANGE_CNTL or SAT_LEVEL. The write allowlist would allow them (`src/dcn41/dcn41_allow_ranges.h:64`).
- **DET and COMPBUF are read-only.**
  - Census: `dcn/navi48_dispread.h:1041-1052`.
  - Checks: `navi48_disp2.h:1033,1166-1167`. DET0 = 0x303, so 3 segments = 192 KB.
- **HUBP DLG/TTU is written only in two places:**
  - The Navi48-only mode trial row 120, which is refused on Navi 44.
  - The disp2 HUBP0→HUBP2 mirror.
- **The 60 Hz switch writes only V_TOTAL (+MSA)** (`dcn/navi48_refresh_pure.h:7-20`). Everything else is the GOP's 120 Hz state.
- **SMU, MP1 mailbox** (`amd/smu_v14_0.cpp:445-645`):
  - Sends SetAllowedFeaturesMask all-ones, which the PMFW rejects with 0xFD, then EnableAllSmuFeatures (OK). The running mask is the same as Linux.
  - The idle clamp sets SoftMax GFXCLK only (`amdgpu_init.cpp:923-930`).
  - **Never sent:** NumOfDisplays, any DALSMC p-state message, any UCLK/FCLK/DCFCLK minimum, workload mask.
  - The DALSMC mailbox code exists only as a DISPCLK/DPPCLK experiment behind `navi48-dalsmc` (`amd/smu_dal_pure.h`, `amd/smu_dal.cpp`).
- **0.0.672:**
  - `smu_pin_uclk_for_display` (`smu_v14_0.cpp:737-783`, `amd/smu_uclkpin_pure.h`) does GetMaxDpmFreq(UCLK), then MP1 `SetSoftMinByFreq(UCLK, max)`.
  - Default is ON (`navi48-uclkpin=0` turns it off). The result is published in ioreg as `Navi48,UclkPin`.
  - **There is no release path**: no display sleep, no 60 Hz, no teardown.
  - The soft minimum is set even when EnableAllSmuFeatures failed (non-fatal path).
- **ufmon** (`dcn/navi48_ufmon_pure.h`, glue `navi48_dcn.cpp:2104-2150`):
  - Watches HUBP0 `DCHUBP_CNTL` UNDERFLOW_STATUS (abs 0x3AB4) and ODM0 `OPTC_INPUT_GLOBAL_CONTROL` underflow bits (abs 0x4F8A).
  - Publishes `Navi48,DisplayUnderflow`.
  - **It runs only inside `scan_watchdog_loop` during a native scanout acquisition.** Confirm that the desktop path keeps it alive, or the A/B will read zero.

### 3.2 Live, without root

- `ioreg`: `Navi48,VRAMBytes = 17095983104` (16 GB, so 128-bit GDDR6 in clamshell).
- `Navi48,UclkPin` and `Navi48,DisplayUnderflow` are absent because 0.0.671 is loaded.
- `navi48test` needs root (`IOServiceOpen 0xe00002e2`).
- No UCLK-switching log exists in the repo. The "1124 ↔ 1258 MHz" observation is only in the orchestrator's notes; `1124` appears only in Linux `pp_dpm_mclk`.
- Metrics are decoded with the IF 0x2E layout while the PMFW speaks IF 0x33 (`research/reports/smu_metrics_if33_audit.md`). **Socket and board power values are unverified.** Cross-check them against a Linux reading of the same state before trusting a ΔW.

### 3.3 Root-only read-only dump for the orchestrator

This is the decisive measurement. Run it at 120 Hz on the desktop, before and after a few minutes of load. The absolute dword equals DMU segment 2 base `0x34C0` plus the `dcn_4_1_0_offset.h` offset; this is the same convention as ufmon (HUBP0_DCHUBP_CNTL = 0x34C0 + 0x5F4 = 0x3AB4). `regs` is read-only (selector RegRead only, `navi48test.c:114-162`).

```sh
T="/Library/Application Support/Navi44/accelerated-trial/navi48test"
sudo "$T" regs <<'EOF' | tee ~/dchubbub-wm-$(date +%Y%m%d-%H%M%S).txt
0x39BC DCHUBBUB_ARB_DRAM_STATE_CNTL   # bit5/4 = PSTATE force EN/VAL, bit1/0 = SR force EN/VAL
0x39E4 DCHUBBUB_ARB_WATERMARK_CHANGE_CNTL
0x39E7 DCHUBBUB_GLOBAL_TIMER_CNTL     # DCHUB refclk divider -> WM units
0x39BE DCHUBBUB_ARB_DATA_URGENCY_WATERMARK_A
0x39BF DCHUBBUB_ARB_USR_RETRAINING_WATERMARK_A
0x39C0 DCHUBBUB_ARB_REFCYC_PER_TRIP_TO_MEMORY_A
0x39C2 DCHUBBUB_ARB_ALLOW_SR_ENTER_WATERMARK_A
0x39C3 DCHUBBUB_ARB_ALLOW_SR_EXIT_WATERMARK_A
0x39CA DCHUBBUB_ARB_UCLK_PSTATE_CHANGE_WATERMARK_A
0x39CB DCHUBBUB_ARB_UCLK_PSTATE_CHANGE_WATERMARK1_A
0x39CC DCHUBBUB_ARB_FCLK_PSTATE_CHANGE_WATERMARK_A
0x39CD DCHUBBUB_ARB_FCLK_PSTATE_CHANGE_WATERMARK1_A
0x39D1 DCHUBBUB_ARB_DATA_URGENCY_WATERMARK_B
0x39D5 DCHUBBUB_ARB_ALLOW_SR_ENTER_WATERMARK_B
0x39D6 DCHUBBUB_ARB_ALLOW_SR_EXIT_WATERMARK_B
0x39DD DCHUBBUB_ARB_UCLK_PSTATE_CHANGE_WATERMARK_B
0x39DE DCHUBBUB_ARB_UCLK_PSTATE_CHANGE_WATERMARK1_B
0x39DF DCHUBBUB_ARB_FCLK_PSTATE_CHANGE_WATERMARK_B
0x39E0 DCHUBBUB_ARB_FCLK_PSTATE_CHANGE_WATERMARK1_B
0x39B9 DCHUBBUB_ARB_DF_REQ_OUTSTAND
0x39BA DCHUBBUB_ARB_SAT_LEVEL
0x397A DCHUBBUB_COMPBUF_CTRL
0x397B DCHUBBUB_DET0_CTRL
0x397C DCHUBBUB_DET1_CTRL
0x397D DCHUBBUB_DET2_CTRL
0x397E DCHUBBUB_DET3_CTRL
0x3AB4 HUBP0_DCHUBP_CNTL              # underflow status b30:28
0x3AE1 HUBPREQ0_DCN_TTU_QOS_WM
0x3B20 HUBPREQ0_UCLK_PSTATE_FORCE     # b0/b1 data force EN/VAL, b2/b3 cursor
0x505F OTG0_OTG_PSTATE_REGISTER       # keepout start / extend / allow width min
0x4F8A ODM0_OPTC_INPUT_GLOBAL_CONTROL
EOF
sudo "$T" metrics 60 > ~/metrics-120hz-idle-$(date +%Y%m%d-%H%M%S).txt   # UCLK level histogram + power
```

Check the derived addresses against the kext's own name tables before running. `tests/native_scanx_test.cpp` derives these by name, and the census already uses 0x397A, 0x397B and 0x39E7. If any of these fall outside the RegRead allowlist, the tool prints ERR and nothing is written.

**How to read the result:**

| Observation | Meaning |
|---|---|
| `DRAM_STATE_CNTL` bit5 = 1 and bit4 = 1 | The GOP forces "allow". The PMFW can switch at any time, with no hiding. **Root cause found.** Fix: clear the force bits and program real watermarks. |
| UCLK_PSTATE WM_A/B ≪ 400 µs × refclk (for example 0, or a value for a µs-scale blackout) | Allow is asserted too late in or too far into vblank. That matches a band at the top. |
| WM ≈ 409 µs and force = 0 | The hardware should hide switches inside the roughly 100 µs window per 120 Hz frame. The band would then more likely be **H2 below**. |
| `HUBPREQ0_UCLK_PSTATE_FORCE` b0 = 1 | The per-pipe force is set; same meaning as the global force. |

**Alternative hypothesis H2 (not a switch blackout).** The band "lasts up to about 1 s" (STATO, 31/10). That is about 120 frames at 120 Hz, but a UCLK switch blackout hits at most one frame. A persistent top band fits **prefetch starvation at a lower UCLK/FCLK level**: the GOP's DLG/TTU/VSTARTUP were computed for boot clocks, and the 85-line vblank is too short to prefetch at lower bandwidth or higher latency. At 60 Hz the 8.8 ms vblank always suffices, so the band is rare.
- The pin fixes H2 too, which makes the 0.0.672 A/B **not discriminating** by itself.
- To discriminate, correlate ufmon events with the metrics UCLK/FCLK level at 1 s resolution. Many consecutive underflowing frames at a stable low level mean H2. Isolated single events at level changes mean switch blackout.

### 3.4 Further measurements

- **M1, Linux golden capture.** Same monitor, 2560x1440@120, on the CachyOS install, with the desktop idle.
  - Sample `pp_dpm_mclk` and `pp_dpm_fclk` every second for 60 s, plus `amdgpu_pm_info` (power).
  - Capture `amdgpu_dm_dtn_log` (watermarks, DET, per-HUBP TTU) with the plane **on**. The existing dump has HUBP rows all zero.
  - Take a umr or `amdgpu_regs2` read of the §3.3 list.
  - This gives Linux's real idle UCLK and power for this exact setup, and the golden register values for §4b.
  - Repeat at 60 Hz with Linux's EDID 60 Hz mode.
- **M2, A/B on 0.0.672.** `navi48-uclkpin=0` versus the default. At 120 Hz and 60 Hz, 30 to 60 min each, on the idle desktop plus a fixed light load (for example scrolling a browser page).
  - Record ufmon count per hour, metrics UCLK/FCLK histogram, socket and board W, and edge/hotspot/mem °C.
  - The power delta must be read on the same IF 0x33 decode in both arms, so the comparison holds even if absolute values are off.

---

## 4. Options, ranked

The scale is my estimate: idle power relative to Linux; safety meaning the band is gone; effort; risk.

| # | Option | Idle power | Band safety | Effort | Risk |
|---|---|---|---|---|---|
| **b** | DCN↔PMFW handshake done like Linux: golden WM + DET + force-clear + DALSMC msgs | **≈ Linux (UCLK 96 MHz idle)** | high, if golden values are used; ufmon fallback | medium (about 1 to 2 builds) | medium: DET/WM rewrite while scanning out |
| e1 | Dynamic pin: pin while 120 Hz or display active, release at 60 Hz and display sleep, plus ufmon-triggered pin | between a and Linux | high | low | low |
| f | 60 Hz long vblank as default (current) | Linux-like if switches are vblank-gated, but the residual band says gating is not right yet | medium (band rare, not zero) | none | low, but 60 Hz is a UX cost |
| c | Custom 120 Hz timing with longer vblank | Linux-like if gating works | medium-high | low-medium | medium: monitor acceptance |
| a | Pin UCLK max always (0.0.672) | **+8 to +15 W** (est.) | high | done | low |
| e2 | Limit UCLK to 2 levels / disable DS_UCLK or FCLK DPM | small saving vs a | unknown | low | medium: guesswork |
| d | FAMS-like V_TOTAL stretch | Linux-like | high | **high** (DMUB FAMS2 cmds + PMFW `IndicateDrrStatus` + DRR) | high |

### 4a. Pin always (0.0.672)

The UCLK range is 96 to 1258 MHz. GDDR6 at 20 Gbps needs high VDDIO/VMEMP plus PHY/UMC power. This card has 16 GB on 128 bits, which is 8 devices in clamshell, so more DRAM devices at full clock.

- **Public reference:**
  - RX 9070 XT forced to the high level idles at 45 to 55 W, versus 15 to 30 W in auto (256-bit, see §1.3). Scaling to 128-bit gives roughly half of that delta.
  - 9060 XT idles at about 18 W on Windows FHD60 (Igor's Lab).
- **Estimate:** **about +8 to +15 W board** at desktop idle, and **about +3 to +8 °C** on GPU and memory temperatures. Fans probably stay in zero-RPM.
- So idle goes from about 15 to 18 W (Linux and Windows class) to about 25 to 30 W. That is clearly worse than other OSes and fails the user's requirement as a permanent solution. M2 replaces this estimate with a measurement.
- Note that Linux pins with a **hard** minimum on the DALSMC channel and also sets `SetUclkPstateAllow(0)`. Our pin is an MP1 **soft** minimum. Both work, because the PMFW stays at max either way.

### 4b. Proper handshake (recommended target)

Steps, all at modeset or refresh change time, where we already write V_TOTAL:

1. **Force bits:** clear `DRAM_STATE_CNTL` PSTATE force (bits 4 and 5) if the GOP set them. Keep SR force cleared, as Linux does.
2. **Watermarks:** program sets A and B with Linux golden values (M1): urgent, SR enter/exit, UCLK_PSTATE (about 409 µs), UCLK_PSTATE1 (temp read), FCLK_PSTATE, USR. Follow Linux's order and rules:
   - When raising: write immediately.
   - When lowering: only after the new state is active (the `safe_to_lower` logic in `hubbub401_program_*`).
   - Select via `WATERMARK_CHANGE_CNTL`.
3. **DET:** move DET0 from 3 segments to at least 13 (Linux would use up to 20 for one pipe), and shrink COMPBUF accordingly.
   - Use Linux's sequence (`dcn401_program_det_segments`, `dcn401_program_compbuf_segments` with safe_to_increase, `dcn401_wait_for_det_update`, `dcn401_hubbub.c:1119-1195`).
   - Do it with HUBP1..3 DET released first (they are unused on our single-display path), and only while the stream is in a known state.
   - **This step is what makes 120 Hz switch safely during active**, independent of vblank.
4. **DALSMC messages:**
   - `NumOfDisplays(1)`.
   - `SetUclkPstateAllow(1)`.
   - `SetHardMinByFreq(DCFCLK, DML value)` and `SetMinDeepSleepDcfclk`.
   - `SetHardMinByFreq(UCLK, bandwidth min)`, which is the lowest level for us.
   - On display off: `NumOfDisplays(0)`, which lets the PMFW go fully idle.
   - On kext teardown: force-allow = 1, mirroring `dcn401_hardware_release`.
5. **Safety net:** keep ufmon running permanently. If it counts N underflows in T seconds, apply the 0.0.672 pin (UCLK soft or hard min = max) and log it. Release the pin at the next modeset. Worst case is then exactly option a, never a visible band for long.

Stage 3 (optional, beyond parity): MALL/CAB static-screen via DMUB `DMUB_CMD__CAB_FOR_SS` (`dcn401_apply_idle_power_optimizations`). This is the Linux and Windows idle path, and it needs DMUB command plumbing we only partly have (`dcn/navi48_dmubcmd.h`).

### 4c. Longer vblank at 120 Hz

Limits:
- Monitor EDID (`cobalt64/tools/dcn41/boards/navi44/edid-AUX0.bin`): V 48–180 Hz, H 30–265 kHz, max pixel clock 720 MHz.
- DP HBR2×4 at 24 bpp: 4 × 5.4 Gb/s × 0.8 / 24 = **720 MHz**. HBR3×4: 1080 MHz, but the monitor caps at 720.
- The live link is HBR2×4.
- The monitor's own modes all have short vblanks: 144 Hz is 103 lines = 464 µs; 180 Hz is 30 lines; 100 Hz is 70 lines.

| Variant | H_TOTAL | V_TOTAL | Pclk | Line time | Vblank lines / µs | H freq |
|---|---|---|---|---|---|---|
| current | 2720 | 1525 | 497.75 | 5.465 | 85 / 464 | 183 kHz |
| A: RB2 H-blank 80, **same pclk** | 2640 | 1571 | 497.75 | 5.304 | 131 / **695** | 188.5 kHz |
| B: same H, faster pclk | 2720 | 1600 | 522.24 | 5.208 | 160 / **833** | 192 kHz |
| C: both | 2640 | 1650 | 522.72 | 5.051 | 210 / **1061** | 198 kHz |

- All variants fit HBR2 and the EDID.
- **A** keeps the DTO unchanged but changes H timing and the MSA, and our 60 Hz path does not write those.
- **B** changes only the DTO and V_TOTAL.
- With GOP DET (about 105 µs), the vblank allow window grows from about 100 µs to about 330 / 470 / 700 µs. Alone this helps only if the watermarks and force bits are correct, so it is a complement to 4b, not a substitute. With a large DET, as in 4b, it is unnecessary.
- Risk: LG scaler acceptance of a non-EDID timing. The 60 Hz V_TOTAL trick was accepted, which is encouraging.

### 4d. FAMS-like V_TOTAL stretch

This is what Linux uses only when vactive, SubVP and vblank all fail (fw_drr). It needs a PMFW↔DMUB protocol: DMUB FAMS2 config commands, `IndicateDrrStatus`, `SetAlwaysWaitDmcubResp`, and DMUB-programmed OTG keepout/HUBP force. That protocol is undocumented outside the Linux source. A driver-side imitation cannot know when the PMFW wants to switch. **Not worth it for one 1440p display.**

### 4e. Variants

- **e1 (dynamic pin)** is the best interim, but it needs a small code addition: a release path. It is also needed anyway for display sleep. Release means `SetSoftMinByFreq(UCLK, min)` from `GetMinDpmFreq`, or the PMFW default.
- **e2:** DS_UCLK is deep sleep inside a level and FCLK blackout is 0 in the SoC bounding box. Disabling them blindly is guesswork; keep them, as Linux does.

### 4f. 60 Hz default

60 Hz is a working mode, but not a solution. The **residual band at 60 Hz with an 8.8 ms vblank** is itself evidence that switch gating is not right (force bits, watermarks) or that the cause is H2. A correct handshake would make 60 Hz band-free with full DPM.

---

## 5. Recommendation

1. **Today:** run §3.3 (root, read-only) at 120 Hz on 0.0.671, plus `metrics 60`. If PSTATE force = 1 or the UCLK watermark is far below 409 µs, the root cause is confirmed.
2. **0.0.672: ship it as an interim with the pin ON by default.** The band is a visible correctness bug and the pin is reversible with `navi48-uclkpin=0`.
   - Run M2 (A/B, 120 and 60 Hz) with ufmon **and** 1 s metrics. Confirm that ufmon actually runs on the desktop path.
   - Tell the user explicitly that this is temporary and costs an estimated 8 to 15 W at idle.
   - If the user prefers power over correctness in the meantime: pin OFF plus `refresh-60` plus ufmon ON is the alternative. It is acceptable because the band is rare at 60 Hz.
3. **0.0.673:** implement 4b (force-clear, golden WM, DET0 ≥ 13 segments, DALSMC messages), add the e1 release path, and add the ufmon-triggered pin fallback.
   - Golden values come from M1 on Linux with the same monitor.
   - Acceptance: zero ufmon events per hour at 120 Hz with UCLK reaching 96 to 456 MHz at idle, and idle board power within about 2 W of the Linux reading.
4. **Later:** MALL/CAB static screen (better than parity), and optionally timing A or B from 4c as extra margin.

**Decision rule after M2:**
- If the measured pin delta is ≤ 3 W, the user may accept the pin as permanent and 4b becomes low priority.
- If it is ≥ 5 W (expected), do 4b.

Sources (web):
- [CachyOS: RX 9070 XT dual monitor high refresh](https://discuss.cachyos.org/t/rx-9070-xt-dual-monitor-displayport-signal-drops-at-high-refresh-rates-wayland/29949)
- [CachyOS: VRAM clock won't turn down after sleep](https://discuss.cachyos.org/t/gpu-vram-clock-wont-turn-down-after-sleep/33493)
- [linux.org / Phoronix: Linux 7.0 RDNA4 idle power fix](https://www.linux.org/threads/phoronix-linux-7-0-amdgpu-fixing-idle-power-issue-for-rdna4-gpus-after-compute-workloads.63745/latest)
- [Igor's Lab: RX 9060 XT power](https://www.igorslab.de/xfx-swift-radeon-rx-9060-xt-und-sapphire-nitro-rx-9060-xt-im-test-amds-antwort-auf-die-geforce-rtx-5060-ti/12/)
