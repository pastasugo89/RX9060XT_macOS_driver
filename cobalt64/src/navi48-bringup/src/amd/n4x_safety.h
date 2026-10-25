//
//  n4x_safety.h - the thermal safety watchdog of the kext. Default ON on the Navi 44 profile, OFF on Navi 48.
//
//  Boot-args:
//    navi48-safety=0|1         enable or disable (default: 1 on Navi 44, 0 on Navi 48)
//    navi48-safety-warn=<C>    WARN threshold, degrees C (default 75), accepted range 50..100
//    navi48-safety-trip=<C>    TRIP threshold, degrees C (default 80), accepted range 50..100, must be above warn
//  An invalid pair falls back to the defaults and says so in the log.
//
//  What it does, and nothing else:
//    * reads THM_TCON_CUR_TMP (hardware sensor, independent of the SMU metrics table) every 250 ms;
//    * emits "N4X-SAFETY t=... hotspot=... state=OK|WARN|TRIP|STOP ..." on the serial log once a second;
//    * on TRIP the state latches until the kext is reloaded, and the writing entry points refuse
//      (N48N submit, DAL step and hold, mode trial, power state, accel experiment, bring-up ladder);
//    * when the sensor cannot be resolved while enabled, it fails closed: state=TRIP reason=no-sensor.
//  It never writes a voltage, a clock, a fan setting, a table or a register. The host watchdog (tools/vm/gpu-safety-watchdog.py)
//  is the part that stops the VM; the kext only reports and refuses. Design: research/reports/gpu_safety.md.
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

// The latched level (Level): kLevelOk, kLevelWarn or kLevelTrip. A watchdog that is not enabled reports kLevelOk and never refuses.
uint32_t level();

// True once the watchdog has latched TRIP. Writing entry points check this and return kIOReturnNotPermitted.
bool refused();

// Boot-arg navi48-clock-raise=1 (default OFF). Without it doPowerState refuses the power states that RAISE a clock (High, Peak).
bool clock_raise_allowed();

}  // namespace n4xs
