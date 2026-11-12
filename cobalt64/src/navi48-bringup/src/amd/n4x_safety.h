//
//  n4x_safety.h - the thermal safety watchdog of the kext. Default ON on the Navi 44 profile, OFF on Navi 48.
//
//  Boot-args:
//    navi48-safety=0|1         enable or disable (default: 1 on Navi 44, 0 on Navi 48)
//    navi48-safety-warn=<C>    WARN threshold, degrees C (default 90, 0.0.675), accepted range 50..105
//    navi48-safety-trip=<C>    TRIP threshold, degrees C (default 100, 0.0.675), accepted range 50..105, must be above warn
//  An invalid pair falls back to the defaults and says so in the log.
//
//  What it does, and nothing else:
//    * reads THM_TCON_CUR_TMP (hardware sensor, independent of the SMU metrics table) every 250 ms;
//    * emits "N4X-SAFETY t=... hotspot=... state=OK|WARN|TRIP|STOP ..." on the serial log once a second;
//    * 0.0.675: on TRIP (hotspot >= trip, or the sensor unreadable for 3 s, or unresolved) it clamps GFXCLK to the PMFW minimum through the
//      SMU (smu_set_power_state Low) and keeps the clamp until the hotspot stays below 85 C (release_c) for 10 s, then restores the boot
//      clock policy (set_restore_state: Low with navi48-idle-clamp on, Auto with it off). Nothing latches.
//    * a TRIP NEVER refuses a submission (submit_refused: only while the watchdog is torn down). Up to 0.0.674 a latched TRIP refused every
//      submission and froze the desktop at 85-87 C (research/reports/macos-20261112/gfx-power-gating-study.md section 1).
//    * while TRIP (including the cooling hold) the writers that can raise a clock or change the display still refuse (refused(): DAL step and
//      hold, mode trial, power states other than Low, accel experiment, refresh-60, the bring-up ladder beyond SMUInit).
//  The only GPU state it changes is the GFXCLK soft limits above (the same SMU messages navi48test power uses); never a voltage, a fan setting,
//  a table or a register. PMFW throttlers and FW_CTF remain the real protection. Design: research/reports/gpu_safety.md.
//
#pragma once
#include <stdint.h>
#include "amdgpu_regs.h"
#include "n4x_safety_pure.h"

namespace n4xs {

// Reads the boot-args. defaultOn is the profile default. Writes the effective thresholds to *th. Returns whether the watchdog is enabled.
bool config(bool defaultOn, Thresholds *th);

// Starts the watchdog thread (idempotent). sensorDword is the dword index of THM_TCON_CUR_TMP in BAR5 (0 = not resolved: fail closed).
// The thread reads dev.rmmio while it runs: the caller must call stop() before the registers are unmapped.
void start(amdgpu::DeviceContext &dev, uint32_t sensorDword, const Thresholds &th);

// Writes the STOP heartbeat and waits (at most ~3 s) for the thread to finish. Safe when never started.
void stop();

// True while the watchdog thread is running.
bool active();

// The current level (Level): kLevelOk, kLevelWarn or kLevelTrip. A watchdog that is not enabled reports kLevelOk and never refuses.
uint32_t level();

// True while TRIP (temperature, cooling hold, sensor fault, watchdog failure) or stopping. The WRITERS check this (DAL, mode trial, clock
// raise, accel experiment, refresh-60, the ladder) and return kIOReturnNotPermitted. Submissions do NOT use it (0.0.675): submit_refused().
bool refused();

// 0.0.675: true only while the watchdog is being torn down (stop()). N48N submit and the legacy SubmitIB check this; temperature never refuses.
bool submit_refused();

// 0.0.675: the thermal clamp is in force (the SMU accepted the Low power state for a TRIP).
bool clamped();

// 0.0.675: the power state the watchdog restores when a thermal clamp is released (amdgpu::SMUPowerState: Low = the boot idle clamp, the
// default; Auto when navi48-idle-clamp=0). Navi48Bringup::runStages sets it from ctx.idleClamp.
void set_restore_state(uint32_t smuPowerState);

// Boot-arg navi48-clock-raise=1 (default OFF). Without it doPowerState refuses the power states that RAISE a clock (High, Peak).
bool clock_raise_allowed();

}  // namespace n4xs
