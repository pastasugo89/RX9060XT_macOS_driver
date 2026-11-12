# GFX power: why the unclamped GPU burned 170 W and froze the desktop, and the plan to full clocks

Date 2026-11-12. Kernel 0.0.674 live (deployed tree research/builds/macos-20261112/kernel-674/kernel-contexts-v10). Linux reference:
research/ext/amdgpu-port-study/drm-kmod (v7.3, MIT). All live data below are read-only register/metrics reads.

## 1. The 2026-11-12 freeze: our own thermal TRIP latch, not a GPU hang (confidence: high)

Timeline (WindowServer unified log, local time):
- ~16:33:20 `navi48test power 0` (SetSoftMax GFXCLK back to PMFW max). Board power climbs to 169-170 W, hotspot 85-87 °C within seconds.
- 16:33:24.9-25.7 WindowServer log activity collapses (frames stop completing).
- 16:33:26.766 first `command buffer ... ended with -13`, then `one-shot submit/wait = -4 (DEVICE_LOST)` on every submission, forever.
- `power 1` brought power back to 33 W but nothing recovered; the whole desktop stayed frozen until a forced reboot.

Cause: the n4x thermal watchdog (`amd/n4x_safety_pure.h`: warn 75 °C, **TRIP 80 °C** hotspot, 250 ms sampling) latches TRIP for the rest of the boot,
and a latched TRIP makes `N48N_SEL_SUBMIT` return kIOReturnNotPermitted (`Navi48NativeClient.cpp:199-200`). WindowServer therefore loses every
submission permanently: the screen cannot update and input appears dead. The metrics run during the test logged hotspot 85-87 °C, above the trip.
The kernel log ring of that boot is gone (forced reboot), so the TRIP line itself was not captured; every other observation fits.

Not the cause:
- The gcvm fault `STATUS_LO32 0x00840d5c vmid 8 ADDR 0x200000` is sticky ("never cleared") and appears 85 times on the current, normal boot too.
- PMFW protections (FW_CTF, THROTTLERS, FAN_CONTROL) were running; 87 °C is far below the PMFW's own limits.

Consequence for the design: 80 °C hotspot is a normal value for any real 3D load on this card. With TRIP = "refuse all submissions", any game or
benchmark at full clock would freeze the desktop the same way. The TRIP action must change before clocks are lifted (section 4, P2).

## 2. Why idle at full clock = 170 W (confidence: high for gating, medium for activity)

Live registers (GC base idx 1 = 0xA000, idx 0 = 0x1260), 3 samples on the idle desktop:

| Register | Value | Meaning |
|---|---|---|
| RLC_CGTT_MGCG_OVERRIDE 0x4C48 | 0x000007ff | **every clock-gating override set**: MGCG, CGCG, CGLS, 3D CG, FGCG, repeater FGCG, perfmon clock all forced ON |
| RLC_CGCG_CGLS_CTRL 0x4C49 | 0x0001003c | CGCG_EN = 0, CGLS_EN = 0 |
| RLC_CGCG_CGLS_CTRL_3D 0x4CC5 | 0x0000003c | 3D CGCG/CGLS off |
| RLC_PG_CNTL 0x4C43 | 0 | no power gating; SMU handshake bit clear |
| RLC_GPM_STAT 0x4E6C | 0x00b40016/17 | GFX powered, clocks running, MGCG/FGCG override status set |
| CP_RB_WPTR_POLL_CNTL 0x0F62 (idx 0) | 0x00400000 | not Linux's 0x00900100 idle-poll setting |
| CP_INT_CNTL 0x1DE9 | 0 | GUI idle / context busy-empty interrupts off |
| GRBM_STATUS 0x0DA4 | 0xad40382c / 0xa800382c / 0xedf1582c | GUI_ACTIVE + CP_BUSY in every sample |
| CP_STAT 0x0F40 | 0x80068600 / 0 | CP busy (PFP, ME, query, ring/IB1) except brief gaps |

SMU metrics, decoded with Linux's SmuMetrics_t (IF 0x2E layout; the early fields are plausible on our PMFW 0x33):
CurrClock GFX 1000 / SOC 1371 / UCLK 1258 / FCLK 2016; AverageGfxclkFrequencyTarget 498, PreDs 470 (the 500 MHz clamp works);
MovingAverageGfxActivity **100 %**; UCLK activity 22 %; dGPU_W_MAX **170 W** (the board power limit); socket power 43 W.

Reading: with all clock-gating overrides forced on, the whole GFX block toggles at the full clock even when it has nothing to do, so power
scales with frequency, not with work. The PMFW sees 100 % GFX activity (the desktop at 500 MHz plus a CP that never reports idle; with CGCG
and the GUI-idle interrupts off the RLC never signals idle) and, once unclamped, drives GFXCLK to the top until the 170 W board limit.
The project's older note (gpu_safety.md R2: 304 W at board limit with no work, before the clamp) is the same effect.

Linux on GC 12.0.0 (soc24.c:390-404) enables CGCG, CGLS, MGCG, 3D CGCG/CGLS, repeater FGCG, FGCG, perf clock, ATHUB MGCG/LS, MC MGCG/LS,
HDP SD, and gates them in gfx_v12_0_update_gfx_clock_gating (gfx_v12_0.c:4083-4109): RLC safe mode, clear the overrides, CGCG FSM with
idle threshold 0x36 and CGLS delay 0xF (also 3D), CP_RB_WPTR_POLL_CNTL = 0x00900100, CP_INT_CNTL busy/empty/idle interrupts, SDMA CGCG
interrupt, GUI idle interrupt, exit safe mode. pg_flags has no GFX PG: GFX power gating on GC 12 is GFXOFF only (gfx_v12_0.c:3871-3889 ->
amdgpu_gfx_off_ctrl), done by the PMFW/IMU after AllowGfxOff, with a refcounted disallow around register access (amdgpu_gfx.c:803).
Our kext programs none of the clock gating (rlc_v12_0.cpp:520-525 only documents it) and sends DisallowGfxOff once at init.

## 3. What must be true before GFXCLK can be lifted
1. Clock gating on (P1), so idle power no longer scales with the clock. Acceptance: at the same 500 MHz clamp, MGCG_OVERRIDE != 0x7ff,
   CGCG_EN = 1, idle board power drops, MovingAverageGfxActivity falls well below 100 % on a static desktop.
2. A thermal policy that never freezes the desktop (P2).
3. The clamp replaced by a boot-arg ladder, never changed on the live desktop (P3).

## 4. Staged plan (each a kernel build applied at boot, with a kill switch)
- **P1, GFX clock gating (0.0.675)**: port gfx_v12_0_update_gfx_clock_gating and its helpers exactly, after RLC/CP are up and before the
  desktop; RLC safe mode around it (RLC_SAFE_MODE 0x0980 idx 1, CMD + MESSAGE=1, poll CMD clear). Boot-arg navi48-cg=0 off. Clamp kept at
  500 MHz. Effort 1-2 days, risk medium (CGCG FSM with our polled fences/doorbells: check GRBM_STATUS/CP_STAT and frame timing after boot).
  Optional in the same build: SetWorkloadMask(default) once after EnableAllSmuFeatures (Linux smu_v14_0_2_ppt.c); ATHUB/MC/HDP gating later.
- **P2, thermal policy (0.0.675 or 0.0.676)**: TRIP no longer refuses submissions. New ladder: WARN 90 °C (log), at TRIP (default 100 °C,
  below the PMFW's own throttle/CTF) re-apply the low GFXCLK soft max through the SMU and release it with hysteresis; refuse submissions only
  if the sensor is unreadable. PMFW throttlers and FW_CTF stay the real protection, as on Linux/Windows.
- **P3, clock ladder (0.0.676)**: boot-arg navi48-gfxmax=<MHz> sets the boot soft max instead of the PMFW minimum (1500 -> 2500 -> PMFW max),
  one reboot per step, idle and load power/temperature measured read-only at each step. Linux also caps the reported top at
  DriverReportedClocks.GameClockAc (smu_v14_0_2_ppt.c:542-547), which is the "stable boost" (~3.2 GHz expected) the user mentioned.
- **P4, GFXOFF (later)**: AllowGfxOff with a refcount and a 100 ms idle delay as amdgpu_gfx_off_ctrl; every MMIO path to GC (polling in
  cp_v12_0.cpp, fence waits, census, diagnostics, navi48test) must disallow around access or move to memory fences. 1-2 weeks, high risk,
  a few watts at idle once P1 is done.
- **Fans**: FEATURE_FAN_CONTROL (bit 29) is in the running mask; the PMFW runs the fan automatically (0 rpm at idle is its zero-RPM mode).
  A custom curve needs the PPTable/OD table path (TransferTableDram2Smu), not before P3.
- **Sensors**: the decode above shows the 0x2E layout's early fields are usable; publishing them (ioreg, then PerformanceStatistics for
  Activity Monitor and similar tools) is independent of P1-P4.
