# GPU power and clock management for Navi 44: Linux reference, gap analysis, staged plan

Date: 2026-11-12. Read-only study. No sudo, no register writes, no GPU state changes, no tracked files edited.

Card: RX 9060 XT 16 GB (Navi 44, GC 12.0.0, MP1 14.0.2, PMFW 102.71.0 = `0x00664700`, PMFW driver-IF 0x33). Kext `com.navi48.bringup` 0.0.674.

Path shorthands:
- `L/` = `research/ext/amdgpu-port-study/linux-v7.3/drivers/gpu/drm/amd/`
- `K/` = `cobalt64/src/navi48-bringup/src/`

Linux code may be ported with attribution (MIT header on the swsmu files).

**Scope.** On 2026-11-12 the orchestrator moved three topics to a separate *power-gating study*:
- the root cause of the 170 W idle and the DEVICE_LOST freeze;
- why GFX activity reads 100 % at idle;
- GFXOFF, RLC power gating and GFX clock gating.

This report only records the evidence it had already found on those topics (§3). It concentrates on:
- the SMU 14.0.2 sequence and feature mask;
- the metrics decode and how sensors reach macOS (S1);
- DPM, workload profiles and a safe clock ladder (S4);
- fans (S5);
- interrupts (S6);
- the read-only commands (§5).

---

## 0. Summary

1. **Our metrics struct is not mis-decoded.**
   - `K/amd/amdgpu_smu.h:338-385` matches `SmuMetrics_t` in `L/pm/swsmu/inc/pmfw_if/smu14_driver_if_v14_0.h:1649-1727` field for field (both are 260 bytes).
   - Linux v7.3 still pins IF 0x2E for SMU 14.0.2 (`L/pm/swsmu/smu14/smu_v14_0_2_ppt.c:74`) and decodes the same struct under the same PMFW 102.71.
   - The Linux oracle dumps decode to sane idle values: `research/hw_dump/gpu_metrics.bin` and `linux-oracle-*/gpu_metrics.bin` give gfx 0 MHz, 6–12 W socket, 29–38 °C, activity 0 %.
   - **The real bug is which field we show as the GFX clock.** We print `CurrClock[GFXCLK]` (`K/Navi48UserClient.cpp:485`). Linux never uses that field for GFX. It reports `AverageGfxclkFrequencyPostDs`, or `PreDs` when activity is above 5 % (`smu_v14_0_2_ppt.c:647-651`, `2201-2213`).
   - That explains the constant "gfx 1000 MHz". It does not explain the "busy 100 %": `AverageGfxActivity` is the same field Linux uses, so that value is probably real. The power-gating study owns that question.
2. **Our SMU init differs from Linux in three small ways (S1 fixes):**
   - **`NotifyPowerSource` sends param 1, which is DC.** In the PMFW enum AC is 0 (`smu14_driver_if_v14_0.h:579`). Linux never sends this message on 14.0.2: there is no `.set_power_source` in the ppt_funcs. The PMFW currently answers 0xFF, so it is harmless today, but it must go.
   - **`UseDefaultPPTable` is sent.** Linux skips it under SCPM.
   - **`SetAllowedFeaturesMask` is sent Low before High.** Linux sends High first, and skips both under SCPM, which is why the PMFW answers 0xFD.
   - The resulting running mask `0x0498f59e_38fffcfb` is **identical to Linux's** (`research/hw_dump/pp_features.txt`).
3. **Workload profile.** Linux sets `SetWorkloadMask` to 0x1 (BOOTUP_DEFAULT) at init. While a GFX ring is in use it raises it to BOOTUP_DEFAULT plus FULLSCREEN3D (0x3), and drops back after 1 s with no fences. We never send `SetWorkloadMask` (msg 0x24).
4. **DPM limits.** Linux "auto" is exactly what our `navi48test power 0` sent for GFXCLK: SoftMax `0xFFFF`, SoftMin 0 (`L/pm/swsmu/smu14/smu_v14_0.c:1146-1192`, `1019-1062`). **So the DPM message itself was not the fault in the freeze.** The difference from Linux lies in GFXOFF, clock gating and the activity source (§3, owned by the power-gating study).
5. **Fan.** On 14.0.2 Linux has no fan-set function: fan control is PMFW-automatic from the pptable (FAN_CONTROL bit 29 runs). Zero-RPM at idle matches Linux (fan 0 in both oracle dumps). Customisation is possible only through the OverDrive table (TABLE_OVERDRIVE = 8).
6. **Sensors on macOS.**
   - Today nothing device-specific is published. `Navi48Accelerator` carries only the IOAccelerator family's generic `PerformanceStatistics`.
   - The Stats app reads `"Device Utilization %"` / `"GPU Activity(%)"`, `"Renderer Utilization %"` and `"Tiler Utilization %"` from that dictionary. Temperatures come from SMC keys.

---

## 1. How Linux runs SMU 14.0.2 (Navi 44)

### 1.1 Init sequence (hw_init → smc_hw_setup → late_init)

| # | Step | PPSMC msg (id) | Linux file:line | Notes for us |
|---|---|---|---|---|
| 1 | `smu_check_fw_version` | GetSmuVersion (0x2), GetDriverIfVersion (0x3) | `L/pm/swsmu/amdgpu_smu.c:1955-1960` → `smu_cmn.c` | Logs the IF mismatch (0x33 vs 0x2E); never fatal |
| 2 | `smu_init_display_count(0)` | – (no-op on 14.0.2) | `amdgpu_smu.c:1724` | – |
| 3 | `smu_set_driver_table_location` | SetDriverDramAddrHigh/Low (0xE/0xF) | `amdgpu_smu.c:1730`; `smu_v14_0.c:560` | We do this |
| 4 | `smu_set_tool_table_location` | SetToolsDramAddrHigh/Low (0x10/0x11) | `amdgpu_smu.c:1739`; `smu_v14_0.c:580` | PMSTATUSLOG buffer; we skip it (only tools need it) |
| 5 | `smu_notify_memory_pool_location` | DramLogSetDramAddr* (0x21-0x23) | `amdgpu_smu.c:1748`; `smu_v14_0.c:529` | Optional |
| 6 | `smu_setup_pptable` | TransferTableSmu2Dram(**TABLE_COMBO_PPTABLE = 1**) | `smu_v14_0_2_ppt.c:337-378` | **Reads** the PMFW pptable: SkuTable limits, fan params, DriverReportedClocks. We never read it. |
| 7 | `smu_write_pptable` | skipped because `adev->scpm_enabled` | `amdgpu_smu.c:1767-1781` | **We send UseDefaultPPTable (0x14)**, `K/amd/smu_v14_0.cpp:525-535`. Linux does not. |
| 8 | `smu_run_btc` | RunDcBtc (0x36) | `amdgpu_smu.c:1784`; `smu_v14_0.c:1478` | We do this |
| 9 | `smu_feature_set_allowed_mask` | skipped under SCPM; otherwise SetAllowedFeaturesMask**High** then **Low** | `amdgpu_smu.c:1800-1806`; `smu_v14_0.c:600-621` | We send Low, then High, all-ones (`smu_v14_0.cpp:578-593`); PMFW answers 0xFD to both |
| 10 | `smu_update_pcie_parameters` | OverridePcieParameters (0x20) per link level | `amdgpu_smu.c:1808-1846`; `smu_v14_0_2_ppt.c:1411-1491` | We skip it. Link already Gen4 x16 (metrics PcieRate/Width). Low value. |
| 11 | `smu_system_features_control(true)` | EnableAllSmuFeatures (0x6) | `amdgpu_smu.c:1848`; `smu_v14_0.c:649` | We do this |
| 12 | `smu_feature_get_enabled_mask` | GetRunningSmuFeaturesLow/High (0xC/0xD) | `amdgpu_smu.c:1856` | We do this: `0x0498f59e_38fffcfb` = Linux (`research/hw_dump/pp_features.txt`) |
| 13 | `smu_set_default_dpm_table` | GetDpmFreqByIndex (0x1F): count with index 0xFF, then each level | `smu_v14_0_2_ppt.c:465-597`; `smu_v14_0.c:1292-1375` | **The GFX top level is capped to `SkuTable.DriverReportedClocks.GameClockAc` *for reporting only*** (`:500-513`). The Linux oracle shows `pp_dpm_sclk` 500 / 2700 MHz while GetMaxDpmFreq says 3500. |
| 14 | `smu_get_thermal_temperature_range` | – (from pptable `CustomSkuTable.TemperatureLimit[]`) | `smu_v14_0_2_ppt.c:1493-1530` | For sensor limits and alerts |
| 15 | `smu_enable_thermal_alert` | AllowIHHostInterrupt (0x4D) after `amdgpu_irq_get` | `smu_v14_0.c:1808-1827` | Needs the IH ring (S6) |
| 16 | late_init: `smu_set_ac_dc` | NotifyPowerSource **only if ppt_funcs has set_power_source**; 14.0.2 does not | `amdgpu_smu.c:957-963, 2777-2799`; ppt_funcs `smu_v14_0_2_ppt.c:2915-2983` | **We send NotifyPowerSource(1 = DC)** (`smu_v14_0.cpp:555-563`, comment says AC). PMFW answers 0xFF. Remove. |
| 17 | late_init: `smu_set_default_od_settings` | TransferTableSmu2Dram(TABLE_OVERDRIVE = 8) | `smu_v14_0_2_ppt.c:2357-2427` | Needed only for S5 custom fan curve / OC |
| 18 | late_init: `smu_populate_umd_state_clk` | – | `smu_v14_0_2_ppt.c:1532-1584` | Peak = GameClockAc, standard = BaseClockAc |
| 19 | late_init: `smu_handle_task(COMPLETE_INIT)` → `smu_adjust_power_state_dynamic` → `smu_bump_power_profile_mode` | **SetWorkloadMask (0x24) = 0x1** (BOOTUP_DEFAULT); the `set_power_profile_mode` path also calls `deep_sleep_control(true)` | `amdgpu_smu.c:2394-2480`; `smu_v14_0_2_ppt.c:1847-1904`; `smu_init_power_profile` `amdgpu_smu.c:1357-1363` | **We never send it** |
| 20 | Runtime: GFX ring begin_use / end_use | SetWorkloadMask 0x3 (adds FULLSCREEN3D, bit 1) while submissions are in flight; back to 0x1 after 1 s with no emitted fences | `L/amdgpu/amdgpu_gfx.c:2758-2830`; `gfx_v12_0.c:5325-5330`; timeout `amdgpu_gfx.h:63` | Gap |
| 21 | Runtime: GFXOFF | AllowGfxOff / DisallowGfxOff (0x28/0x29) via `amdgpu_gfx_off_ctrl` (100 ms delay) | `smu_v14_0.c:623-647`; `amdgpu_gfx.c:929-1013`; `gfx_v12_0.c:4132-4151` | **Owned by the power-gating study** |
| 22 | Runtime: performance level AUTO | For GFX, MCLK, SOCCLK, VCLK, DCLK, FCLK: SetSoftMax(clk<<16 \| 0xFFFF) then SetSoftMin(clk<<16 \| 0) | `smu_v14_0.c:1146-1192, 1019-1062` | Our `power 0` = the GFX half of this |

Workload bits: `smu14_driver_if_v14_0.h:1828-1838`. Linux map (`smu_v14_0_2_ppt.c:246-255`):
- BOOTUP_DEFAULT → bit 0;
- FULLSCREEN3D → bit 1;
- POWER_SAVING → 2;
- VIDEO → 3;
- VR → 4;
- COMPUTE → 5;
- CUSTOM → 6;
- WINDOW3D → 7.

**Activity-monitor coefficients** (TABLE_ACTIVITY_MONITOR_COEFF = 7) are PMFW defaults; Linux only rewrites the CUSTOM slot (`smu_v14_0_2_ppt.c:1791-1845`). The Linux oracle (`research/hw_dump/sysfs_power.txt`) shows, for GFXCLK:

| Profile | BoosterFreqType | BoosterFreq | PD_Data_limit_c | error coefficient |
|---|---|---|---|---|
| BOOTUP_DEFAULT | 4 | 800 | 4587520 | -65536 |
| 3D_FULL_SCREEN | 1 | – | 5570560 | -655 |

So FULLSCREEN3D reacts much faster to load. **There is nothing to port for the coefficients**: only the mask message.

**Soft-limit encoding:** `param = (PPCLK_id << 16) | MHz`.
- An explicit max goes in as `max + 1` (`SMU_V14_SOFT_FREQ_ROUND`, `L/pm/swsmu/inc/smu_v14_0.h:54`).
- 0xFFFF and 0 mean "PMFW decides".
- PPCLK ids (`smu14_driver_if_v14_0.h:455-468`): GFX 0, SOC 1, UCLK 2, FCLK 3, DCLK0 4, VCLK0 5, DISPCLK 6, DPPCLK 7, DPREFCLK 8, DCFCLK 9, DTBCLK 10.

**PPT (power limit):**
- GetPptLimit 0x33 and SetPptLimit 0x32 (`smu_v14_0.c:670-720`; `smu_v14_0_2_ppt.c:1639-1704, 2862`).
- The defaults come from `CustomSkuTable.SocketPowerLimitAc[PPT0]`, plus an OD percentage.
- Linux never changes the limit unless the user asks. The PMFW enforces it, and THROTTLERS (bit 23) runs for us too.

### 1.2 Feature mask (running, ours = Linux)

`0x0498f59e_38fffcfb`. Bit names are in `smu14_driver_if_v14_0.h:46-110`; per-bit state is in `research/hw_dump/pp_features.txt`.

- **Enabled:** FW_DATA_READ, DPM_GFXCLK/UCLK/FCLK/SOCCLK/LINK/DCN, DS_GFXCLK/SOCCLK/FCLK/LCLK/DCFCLK/UCLK, GFX_ULV, FW_DSTATE, **GFXOFF (18)**, BACO, MM_DPM, SOC_MPCLK_DS, BACO_MPCLK_DS, THROTTLERS, VR0HOT, FW_CTF, FAN_CONTROL, GFXCLK_SPREAD_SPECTRUM, OOB_MONITOR, OPTIMIZED_VMIN, GFX_IMU, SOC_CG, DF_CSTATE, BOOT_POWER_OPT, DS_VCN, BACO_CG, MEM_TEMP_READ, ATHUB_MMHUB_PG, GFX_PSM_DIDT, APT_ALL_ENABLE, GFX_EDC_XVMIN, CLOCK_STRETCH_COMPENSATOR.
- **Disabled, on both OSes:** GFX_POWER_OPTIMIZER, VMEMP/VDDIO scaling, SMARTSHIFT, GTHR, ACDC, GFX_DCS, GFX_PCC_DFLL, GFX_EDC, SOC_PCC, EDC_PWRBRK, …

GFXOFF *running* in the PMFW mask does not mean GFX is off: the driver must also *allow* it (see §3).

### 1.3 Sensors: the metrics table (IF 0x2E layout, used unchanged by Linux under this PMFW)

`SmuMetrics_t` is at `smu14_driver_if_v14_0.h:1649-1727`. It is wrapped in `SmuMetricsExternal_t` (+30 spare dwords + 8 MmHub dwords, `:1729-1735`) and read with TransferTableSmu2Dram(TABLE_SMU_METRICS = 5).

Byte offsets (our `static_assert` confirms 260 bytes):

| Offset | Field | Linux use (`smu_v14_0_2_ppt.c`) |
|---|---|---|
| 0x00 | `CurrClock[11]` u32 | SOC/UCLK/FCLK/VCLK/DCLK/DCF "current" (`:633-652`). **Not used for GFX.** |
| 0x2C | `AverageGfxclkFrequencyTarget` u16 | – |
| 0x2E | `AverageGfxclkFrequencyPreDs` | GFX clock when activity > 5 % (`:647-651`) |
| 0x30 | `AverageGfxclkFrequencyPostDs` | GFX clock when activity ≤ 5 %. **This is what `pp_dpm_sclk`, sensors and gpu_metrics show.** |
| 0x32/0x34 | `AverageFclkFrequencyPre/PostDs` | FCLK average (same 5 % rule, on UclkActivity) |
| 0x36/0x38 | `AverageMemclkFrequencyPre/PostDs` | UCLK average |
| 0x3A-0x40 | Vclk0/Dclk0/Vclk1/Dclk1 averages | VCN |
| 0x42 | `AveragePCIeBusy` | – |
| 0x44 | `dGPU_W_MAX` | – |
| 0x48-0x66 | `MovingAverage*` (16 × u16) | – |
| 0x68 | `MetricsCounter` u32 | Freshness |
| 0x6C | `AvgVoltage[4]` (GFX, SOC, VDDCI_MEM, VDDIO_MEM), mV | `voltage_gfx/soc/mem` (`:2240-2242`) |
| 0x74 | `AvgCurrent[4]` | – |
| 0x7C | `AverageGfxActivity` u16, % | GPU load |
| 0x7E | `AverageUclkActivity` | MEM load (`smu_safe_u16_nn`) |
| 0x80/0x82 | VCN0 / VCN1 activity | – |
| 0x84 | `EnergyAccumulator` u32 | **Only on MP1 14.0.3 with fw ≥ 0x685000** (`:2197-2198`). Ours is 14.0.2, so invalid. |
| 0x88 | `AverageSocketPower` u16, W | `power1_average` (`:715-717`) |
| 0x8A | `AverageTotalBoardPower` u16, W | **Not used by Linux on 14.0.2.** Our "board W" is unvalidated. |
| 0x8C | `AvgTemperature[12]` u16, °C: EDGE, HOTSPOT, HOTSPOT_GFX, HOTSPOT_SOC, MEM, VR_GFX, VR_SOC, VR_MEM0, VR_MEM1, LIQUID0, LIQUID1, PLX | edge / junction / mem / vrgfx / vrsoc / vrmem = max(VR_MEM0, VR_MEM1) |
| 0xA4 | `AvgTemperatureFanIntake` | – |
| 0xA6/0xA7 | `PcieRate`, `PcieWidth` u8 | Link |
| 0xA8 | `AvgFanPwm` u8, % | ×255/100 for hwmon pwm (`:1606-1626`) |
| 0xAA | `AvgFanRpm` u16 | fan1_input |
| 0xAC | `ThrottlingPercentage[21]` u8 | throttle_status bit i = (value ≠ 0) (`:611-622`). Bits per `:195-216`: EDGE, HOTSPOT, …, TDC_GFX 12, PPT0 14, FIT 18, … |
| 0xC1 | `VmaxThrottlingPercentage` | – |

**Oracle cross-check (Linux, same card and PMFW, monitors off):**

| Field | Value |
|---|---|
| gfx_act | 0 |
| socket | 6–9 W |
| gfx clock | 0 (GFXOFF) |
| UCLK | 96 MHz |
| SOCCLK | 417 MHz |
| edge / hotspot | 29–38 °C |
| fan | 0 rpm |
| pcie | x16 |

The throttle field is 2 in one dump: bit 1, TEMP_HOTSPOT. Because the fields are consistent with each other, the layout holds for IF 0x33. This supersedes the "unverified" caveat in `research/reports/smu_metrics_if33_audit.md` for the fields Linux itself reads.

---

## 2. Our kext versus Linux, gap by gap

| Area | Linux | Ours | Gap / action |
|---|---|---|---|
| Driver table | 64 KB `driver_table` BO plus a per-table BO | Fixed VRAM slot `vramBase + 0xE00000`, 64 KB, zeroed (`K/amd/amdgpu_smu.h:173-174`, `smu_v14_0.cpp:409-418, 468-490`) | OK. Large enough for the combo pptable (16 KB), OD, activity coefficients and metrics. Serialise every transfer under `SmuSeq` (already done). |
| Tools table | SetToolsDramAddr | not sent | None needed |
| pptable read | TransferTableSmu2Dram(COMBO_PPTABLE) | **never read** | S1: read it once to get GameClockAc/BoostClockAc/BaseClockAc, TemperatureLimit[], fan settings, SocketPowerLimitAc, FanMaximumRpm |
| UseDefaultPPTable | not sent under SCPM | sent, OK (`smu_v14_0.cpp:525-535`) | S1: drop it, or gate it behind a boot-arg. Low risk either way. |
| Allowed mask | skipped under SCPM | sent Low/High, PMFW answers 0xFD (`:578-593`) | Drop (cosmetic) |
| NotifyPowerSource | not sent on 14.0.2 | **sent with param 1 = DC**, PMFW answers 0xFF (`:555-563`) | **Remove.** If a future PMFW accepted it, the card would run with DC limits. |
| EnableAllSmuFeatures / running mask | yes | yes, identical mask | – |
| Protection gate | – | THROTTLERS + FW_CTF + FAN_CONTROL required (`:659-681`) | Keep |
| Default DPM tables | GetDpmFreqByIndex per clock | only GetMin/MaxDpmFreq(GFX, UCLK) | S4: read the level tables, publish them |
| Thermal alert / IH | AllowIHHostInterrupt + IH THM/MP1 sources | none (`navi48-interrupts=0` on this boot) | S6 |
| Workload mask | 0x1 at init; 0x3 while the GFX ring is busy, 1 s hysteresis | **never sent** | S4 |
| Perf level / soft limits | AUTO = 0xFFFF / 0 on every DPM clock | GFX SoftMax = PMFW **min** (500 MHz) at the end of `bringup_to` (`K/amd/amdgpu_init.cpp:917-930`; `smu_v14_0.cpp:895-913`). `ctx.idleClamp` defaults to 1 (`K/Navi48Bringup.cpp:6950-6952`). | S4 (only after the power-gating study's fixes) |
| UCLK | PMFW DPM plus DALSMC display hard-min | AUTO with a fallback pin on underflow. **Pinned at 1258 MHz this boot** (ioreg `Navi48,UclkPin`: "pinned … last display underflow") | Covered by `memclk-display-power.md`. Note: Linux AUTO would send SetSoftMin(UCLK, 0). **S4 must not touch UCLK** while the pin is active. |
| GFXOFF / CG / PG | §3 | §3 | Owned by the power-gating study |
| Metrics GFX clock | AverageGfxclkFrequencyPostDs/PreDs | `CurrClock[GFXCLK]` (`K/Navi48UserClient.cpp:485`; `smu_v14_0.cpp:1005, 1029-1032`) | **S1 fix.** This is the "always 1000 MHz". |
| Metrics fields shown | ~25 | 15. No voltages, VR temps, PreDs/PostDs averages, throttle bits or VCN. | S1 |
| Raw dump | – | Only the first 128 bytes are logged (`smu_v14_0.cpp:1041-1046`) | S1: log all 260 bytes |
| Layout flag | – | Prints "UNVERIFIED" whenever the IF ≠ 0x2E (`smu_v14_0.cpp:979, 1020-1028`) | S1: mark as verified-by-Linux-parity. Keep the range check. |
| Sensors exposure | hwmon + gpu_metrics | none outside `navi48test metrics` (root) | S1 |
| Fan | PMFW auto; OD fan curve optional | PMFW auto; FAN_CONTROL verified | S5 |

---

## 3. 170 W idle + DEVICE_LOST freeze (owned by the power-gating study; evidence found before the scope change)

Only short notes here. They are facts from code; the conclusions belong to the other study.

- **GFXOFF is disallowed for the whole session.**
  - `ensure_gfxhub_gart` sends `DisallowGfxOff` before the manual GART setup and sets `ctx.gfxOffHeld` (`K/amd/amdgpu_init.cpp:278-288`).
  - The only `AllowGfxOff` is in teardown (`:870-874`).
  - Linux, by contrast, starts with `gfx_off_req_count = 1` (`L/amdgpu/amdgpu_device.c:3887`). Late init drops it to 0 through `gfx_v12_0_set_powergating_state` → `amdgpu_gfx_off_ctrl(true)` (`gfx_v12_0.c:4132-4151`; `amdgpu_device.c:2772-2773`). It brackets MMIO and ring work with `amdgpu_gfx_off_ctrl(false/true)`.
  - The Linux oracle `pp_dpm_sclk` shows "S: 0Mhz *", that is, GFX off at idle.
- **No GFX clock gating is programmed.**
  - No code writes `RLC_CGTT_MGCG_OVERRIDE`, `RLC_CGCG_CGLS_CTRL(_3D)`, `CP_RB_WPTR_POLL_CNTL` or `CP_INT_CNTL`. The register is only read, in `K/amd/rlc_v12_0.cpp:280-316`.
  - Linux GC 12.0.0 cg_flags: CGCG, CGLS, MGCG, 3D_CGCG/CGLS, REPEATER_FGCG, FGCG, PERF_CLK, ATHUB/MC/HDP (`L/amdgpu/soc24.c:349-367`). Sequence: `gfx_v12_0.c:4153-4370`.
  - Linux sets `CP_RB_WPTR_POLL_CNTL.IDLE_POLL_COUNT = 0x90` and enables the CP GUI-idle interrupts as part of CGCG.
- **The DPM side of `power 0` was identical to Linux AUTO for GFXCLK** (§1.1 row 22). The PMFW was therefore given the same limits as Linux, but with GFX ungated and reporting 100 % activity, so it drove the clock to the top bin.
- **WindowServer genuinely keeps the GPU 75–80 % busy at 120 Hz** at 500 MHz (`performance-plan.md` §1.2). Part of "busy 100 %" is therefore likely real work, not a decode error: `AverageGfxActivity` is the same field Linux reads.

**What must be true before the clamp is lifted** (input to S4, to be confirmed by the power-gating study):
1. Idle `AverageGfxActivity` stays at or below about 5 % with WindowServer idle, and the GFX clock (PostDs) drops toward deep sleep.
2. GFXOFF allowed, with the driver's MMIO/doorbell paths bracketed, *or* CG/MGCG enabled, so that an idle core does not draw full board power.
3. A fault/hang path that survives a clock change: the gcvm fault at vmid 8 must be understood.

---

## 4. Staged plan

Every stage is a kernel build applied **at boot** with a boot-arg kill switch. Nothing changes live on the desktop (per the "no live GPU state tests" rule). Acceptance tests are read-only: `metrics`, `regs`, `ioreg`, `log show`.

### S1: correct sensors, the SMU init cleanup, and macOS exposure (start now; independent of the freeze)

**Kernel build A, effort 2–3 days.**

1. **Metrics decode.**
   - GFX clock = `AverageGfxActivity <= 5 ? PostDs : PreDs`, as in `smu_v14_0_2_ppt.c:647-651`. Same rule for FCLK/UCLK averages.
   - Keep `CurrClock[]` for SOC/UCLK/FCLK/DCF and also show `CurrClock[GFX]` as "gfx target".
   - Add: VDDGFX/SOC/MEM voltage, all 12 temperatures plus fan intake, throttle bits (Linux bit order, `:195-216`) with the per-throttler %, VCN activity, PCIe busy, MetricsCounter age.
   - Mark `AverageTotalBoardPower` "unvalidated, not used by Linux". **Show socket power as the primary watt figure.**
   - Mark EnergyAccumulator invalid on 14.0.2.
   - Change the "UNVERIFIED" banner to "layout = Linux v7.3 (IF 0x2E struct used by Linux on this PMFW)". Keep the range check.
   - Log all 65 dwords of the raw dump.
2. **pptable read (read-only messaging).**
   - TransferTableSmu2Dram(1, COMBO_PPTABLE) once at init into the driver-table slot.
   - Copy the 16 KB and publish the key fields: `DriverReportedClocks` Base/Game/BoostClockAc, `TemperatureLimit[]`, `SocketPowerLimitAc[PPT0]`, `FanMaximumRpm`, fan stop/start temperatures, `FanTargetTemperature`, `OverDriveLimitsBasicMin/Max`.
   - Port `smu_14_0_2_powerplay_table` / `PPTable_t` from `smu14_driver_if_v14_0.h` (MIT) with a static_assert on the size.
   - Also GetPptLimit (0x33) and GetDpmFreqByIndex for GFX, UCLK, FCLK and SOCCLK (count = index 0xFF, then each level).
3. **Init parity.**
   - Remove `NotifyPowerSource(1)`.
   - Gate `UseDefaultPPTable` and the allowed-mask messages behind `navi48-smu-legacyinit=1` (default off). This matches Linux under SCPM.
   - Acceptance: the running mask is still `0x0498f59e_38fffcfb`, the protection gate is still PRESENT, and the fan behaves the same.
4. **Publish sensors (no root needed to read).**
   - A kext timer every 2 s (configurable; `navi48-sensors=0` turns it off) takes `SmuSeq`, reads metrics, and sets an `OSDictionary` `Navi48,Sensors` on the bring-up service.
   - Keys: `GPU Core Clock(MHz)`, `GPU Memory Clock(MHz)`, `SOC Clock(MHz)`, `FCLK(MHz)`, `Edge/Hotspot/Mem/VR GFX/VR SOC/VR MEM Temperature(C)`, `Fan Speed(RPM)`, `Fan Speed(%)`, `Socket Power(W)`, `VDDGFX(mV)`, `GPU Activity(%)`, `Memory Activity(%)`, `Throttle Status`, `PCIe Gen`, `PCIe Width`, plus a `Limits` sub-dict from the pptable.
   - **Cost:** two mailbox messages every 2 s. Linux caches metrics for 1 ms, and `gpu_metrics` users poll at about 1 Hz.
   - **Risk:** mailbox contention with the UCLK/DAL paths. Already serialised by `SmuSeq`.
5. **macOS apps.** Three options; recommended order a → b → c.
   - **(a)** `Navi48,Sensors` plus a tiny user-space menu-bar or CLI reader. No approvals needed.
   - **(b) PerformanceStatistics** on `Navi48Accelerator`, which is an `IOGraphicsAccelerator2` subclass in `com.navi48.accelprobe` (`cobalt64/tools/native/navi48accel/src/Navi48Accel.cpp:112`).
     - The Stats app (exelban/stats `Modules/GPU/reader.swift`) reads exactly `"Device Utilization %"` (falling back to `"GPU Activity(%)"`), `"Renderer Utilization %"`, `"Tiler Utilization %"` and `"In use system memory"`.
     - It classifies the GPU by `IOClass` containing "amd". `Navi48Accelerator` gives type "Unknown"; utilisation is still shown.
     - Real AMD kexts additionally publish `"Temperature(C)"`, `"Fan Speed(RPM)"`, `"Fan Speed(%)"`, `"Core Clock(MHz)"`, `"Memory Clock(MHz)"`, `"Total Power(W)"`. This list is from memory; verify on any real AMD Mac `ioreg -l` before relying on it.
     - Activity Monitor's GPU History uses the accelerator's utilisation. Inference: it reads `"Device Utilization %"`.
     - This is an accelprobe rebuild and needs the user's Allow click. The family overwrites the dictionary on its own timer, so the right hook is the family's statistics-update virtual: **find it in the IOGraphicsAccelerator2 vtable before designing**.
     - Effort 1–2 days plus approval.
   - **(c) VirtualSMC plugin** (VirtualSMC is already loaded, per `cobalt64/tools/pc/esp-kext.sh:19`) publishing GPU temperature and fan SMC keys, so iStat, Stats sensors and HWMonitorSMC2 see them.
     - The key names must follow what those apps map to "GPU". Check the apps' own key tables, not NootRX/NootedRed.
     - Effort 3–5 days. Lowest priority.

**Acceptance S1:**
- `metrics` shows a GFX clock that varies, matching `CurrClock[GFX]` and the 500 MHz cap (PostDs ≤ 500).
- `Navi48,Sensors` updates in `ioreg -l` without root.
- pptable values match `pp_od_clk_voltage` / `pp_dpm_*` from the Linux oracle: GFX levels 500 / 2700 (GameClock), UCLK 96…1258, FCLK 307/666/2400, SOCCLK 417/1476.
- The running mask is unchanged.

**Risk:** low; read-only SMU messages. The kill switches are `navi48-sensors=0` and `navi48-smu-legacyinit=1`.

### S2 and S3: activity at idle, GFXOFF and clock/power gating

**Owned by the power-gating study.** S4 must not start until its acceptance holds:
- idle `AverageGfxActivity` ≤ 5 %;
- GFX PostDs clock near the deep-sleep floor, or GFXOFF entries visible;
- socket power at idle within about 3 W of Linux (6–12 W socket, monitors off; about 15–18 W board on Windows).

### S4: proper DPM and boost (after S2/S3)

**Kernel build(s) B, effort 2–3 days of code plus 4–6 boots for the ladder.**

1. **`SetWorkloadMask` (0x24).**
   - 0x1 (BOOTUP_DEFAULT) after EnableAllSmuFeatures. Port `smu_v14_0_2_set_power_profile_mode`, `smu_v14_0_2_ppt.c:1847-1904`, minus CUSTOM.
   - Then begin_use/end_use in the native submit path (`native_s1c` submit and fence retire): the first submission sets 0x3 (FULLSCREEN3D | DEFAULT). A 1 s delayed callout with zero outstanding fences returns to 0x1. Port `amdgpu_gfx.c:2758-2830`.
   - Rate limit: at most one message per 100 ms.
   - Kill switch `navi48-workload=0`.
2. **Replace the fixed clamp with a boot-arg ladder `navi48-gfxmax=<MHz>`.**
   - Default stays 500 (the current behaviour) until the ladder passes.
   - Values: 1000 → 1500 → 2000 → 2700 (GameClockAc) → `max`, which sends SoftMax 0xFFFF. PMFW GFX max is 3500; the stable boost is expected around 3.1–3.3 GHz under PPT and thermal limits.
   - Message: `SetSoftMaxByFreq(GFX<<16 | (N+1))`, as in Linux `SMU_V14_SOFT_FREQ_ROUND`; SoftMin 0.
   - Applied once at boot, at the end of `bringup_to` where the clamp is today. **Never** from the user client on a live desktop. Keep `Low` for the failure path.
   - **Do not touch UCLK, FCLK or SOCCLK soft limits.** UCLK belongs to the display pin.
3. **In-kernel guard.**
   - A watchdog on the S1 sensor timer. If the GPU is idle (no fences for 5 s) and socket power is above 40 W, or hotspot is above 90 °C, or any throttle bit is set while idle for more than 10 s, it re-applies the 500 MHz SoftMax once and latches a `Navi48,GfxGuard` reason. This is the same two-stage pattern as the UCLK fallback.
   - It is a safety net, not the plan. The freeze took seconds, so S2/S3 must make it unnecessary.
4. **Ladder acceptance** for each step, booted with `navi48-gfxmax=N`:
   - idle desktop 10 min: socket W, hotspot, fan and activity within ±2 W / ±3 °C of the 500 MHz baseline;
   - a fixed load (the same browser scroll / Metal sample) for 10 min: no DEVICE_LOST in `log show`, no gcvm faults in the kext log, and `T1 cb_gpu` average down versus the baseline;
   - the PreDs clock reaches N under load.
   - Stop at the first failing step.

**Risk:** high until S2/S3 land. Medium afterwards. Kill switch: `navi48-gfxmax=500`.

### S5: fans

- **Verify only, 0.5 day.** PMFW auto control is active (FAN_CONTROL bit 29 is in the protection gate). Zero-RPM at idle matches Linux. Acceptance, read-only over a ladder run under load:
  - RPM and PWM rise with hotspot, and stop again below the pptable `FanStopTemp`;
  - no FAN_ABNORMAL;
  - hotspot stays under `TemperatureLimit[HOTSPOT]`.
- **Optional custom curve, 2–3 days.**
  - Read TABLE_OVERDRIVE (8). Check that `OverDriveLimitsBasicMax.FeatureCtrlMask` has `PP_OD_FEATURE_FAN_CURVE_BIT` (4) and `ZERO_FAN_BIT` (11) (`smu14_driver_if_v14_0.h:693-706`).
  - Set `FeatureCtrlMask`, `FanLinearTempPoints[]`/`FanLinearPwmPoints[]`, `FanMode = FAN_MODE_MANUAL_LINEAR`, zero-RPM enable and stop temperature.
  - TransferTableDram2Smu(8). Port `smu_v14_0_2_od_edit_dpm_table` / `upload_overdrive_table` (`smu_v14_0_2_ppt.c:2294-2318, 2514-…`) with Linux's range checks against the OD limits.
  - Boot-arg selected (`navi48-fancurve=<profile>`); default PMFW auto.
  - **Risk:** medium. A bad curve means heat, and the FW_CTF/THROTTLERS protections still apply.

### S6: interrupts

The IH ring and MSI already work in code. They are on by default and disabled by the boot-arg on this machine (`K/Navi48Bringup.cpp:7411-7421`). Two separate pieces:

- **(a) PM-relevant: SMU thermal / CTF / AC-DC interrupts.**
  - `AllowIHHostInterrupt` (0x4D) plus the IH sources for THM and MP1 (`smu_v14_0.c:891-933, 1808-1827`).
  - Only for logging and an early guard. The PMFW already protects on its own (FW_CTF, THROTTLERS).
  - Effort 1–2 days once `navi48-interrupts=1` is back.
- **(b) EOP-driven fence wake** to remove the busy-spins (`performance-plan.md` item 2). **Not a GPU power-management dependency**, except that it frees about 0.75 CPU core. Keep it as a separate project. Effort: 1 day for the sleep-granularity fix, 1–2 weeks for EOP wake.

### Effort table

| Stage | Build | Effort | Linux code to port | Depends on |
|---|---|---|---|---|
| S1 | kernel A (+ accelprobe for b) | 2–3 d (+1–2 d b, +3–5 d c) | `smu14_driver_if_v14_0.h` structs (PPTable_t, OverDriveTable_t, SmuMetrics_t), `get_smu_metrics_data` / `get_gpu_metrics` logic, `set_single_dpm_table` | – |
| S2/S3 | power-gating study | – | – | – |
| S4 | kernel B | 2–3 d + 4–6 boots | `set_power_profile_mode`, `amdgpu_gfx_profile_ring_begin/end_use`, `set_soft_freq_limited_range` | S1, S2/S3 |
| S5 | none / kernel C | 0.5 d / 2–3 d | `od_edit_dpm_table` (fan part), `upload_overdrive_table` | S1 |
| S6a | kernel | 1–2 d | `smu_v14_0_register_irq_handler`, `enable_thermal_alert` | IH on |
| S6b | kernel | 1 d … 2 wk | amdgpu fence / IH EOP | separate |

---

## 5. Root-only READ-ONLY commands to run now

```sh
T="/Library/Application Support/Navi44/accelerated-trial/navi48test"

# 1. SMU init as it ran this boot (log ring is in-kernel; read-only)
sudo "$T" log | grep -E 'smc_hw_setup|running features|UseDefaultPPTable|NotifyPowerSource|AllowedFeaturesMask|protections|set_power_state|idle clamp|uclk-pin|DisallowGfxOff|GFXOFF' | tail -60

# 2. One metrics read, then the raw dump it logs (words 11-12 = GfxclkTarget|PreDs, PostDs|FclkPreDs; word 31 = GfxActivity|UclkActivity)
#    (`metrics` sends GetDriverIfVersion + TransferTableSmu2Dram only; no clock/power state changes.)
sudo "$T" metrics 1
sudo "$T" log | grep -E 'metrics( raw|:)' | tail -12

# 3. 60 s of metrics on the idle desktop (activity / clock / power distribution)
sudo "$T" metrics 60 > ~/metrics-idle-$(date +%H%M%S).txt

# 4. GC status registers (absolute dwords: GC seg0 0x1260, seg1 0xA000 from ip_discovery_table.bin;
#    offsets from gc_12_0_0_offset.h). Safe now because GFXOFF is held disallowed. Sample 5x, 1 s apart.
for i in 1 2 3 4 5; do sudo "$T" regs <<'EOF'
0x2004 GRBM_STATUS
0x2002 GRBM_STATUS2
0x2007 GRBM_STATUS3
0x21A0 CP_STAT
0x219F CP_BUSY_STAT
0x2084 CP_CPC_STATUS
0x2085 CP_CPC_BUSY_STAT
0x2087 CP_CPF_STATUS
0x21C2 CP_RB_WPTR_POLL_CNTL
0x3049 CP_INT_CNTL
0x30E0 CP_GFX_HQD_ACTIVE
0xEE6C RLC_GPM_STAT
0xEC43 RLC_PG_CNTL
0xEC48 RLC_CGTT_MGCG_OVERRIDE
0xEC49 RLC_CGCG_CGLS_CTRL
0xECC5 RLC_CGCG_CGLS_CTRL_3D
0xEC04 RLC_STAT
0xC807 CP_MES_CNTL
EOF
sleep 1; done > ~/gc-status-$(date +%H%M%S).txt
```

Without root:

```sh
ioreg -l -w0 | grep -E '"Navi48,(UclkPin|DisplayUnderflow|StageReached)"'
ioreg -r -c Navi48Accelerator -l -w0 | grep -E '"IOClass"|"PerformanceStatistics"' | cut -c1-300
/usr/bin/log show --last 10m --style compact --predicate 'process == "WindowServer" AND eventMessage CONTAINS "T1 cb_gpu"' | tail -20
```

How to read the results:
- **Raw words 11/12.** If PostDs ≤ 500 while `CurrClock[GFX]` = 1000, the S1 decode fix is confirmed.
- **Activity and GC registers** (the GRBM_STATUS GUI_ACTIVE bit and CP_BUSY_STAT): hand them to the power-gating study. They show whether "busy" is CP/MES polling or real draws.
- **Item 1** confirms which init messages were refused, which matters for the S1 init-parity change.

Nothing in this list writes a register, changes a clock or power state, or reloads anything.
