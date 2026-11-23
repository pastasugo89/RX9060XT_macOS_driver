//
//  dpm_gate_pure.h - 0.0.678: GFXCLK under PMFW DPM (as Linux leaves it) behind a fail-safe gate (pure decision, host-tested by
//  tests/dpm_gate678_test.cpp against Linux smu_v14_0_2_ppsmc.h / smu14_driver_if_v14_0.h / smu_v14_0_2_ppt.c).
//
//  WHAT LINUX DOES after DPM is enabled (amdgpu_smu.c smu_late_init -> smu_handle_task(COMPLETE_INIT) -> smu_adjust_power_state_dynamic):
//   * level AUTO: smu_v14_0_set_performance_level(AMD_DPM_FORCED_LEVEL_AUTO) -> smu_v14_0_set_soft_freq_limited_range(GFXCLK, min, max,
//     automatic = true), which sends SetSoftMaxByFreq((GFXCLK << 16) | 0xffff) then SetSoftMinByFreq((GFXCLK << 16) | 0): "PMFW picks"
//     on both sides. (It sends the same for UCLK/SOCCLK/FCLK; we touch GFXCLK only, because the display owns UCLK through the fallback pin.)
//   * DriverReportedClocks.GameClockAc only caps the TOP LEVEL REPORTED in the dpm table (smu_v14_0_2_set_default_dpm_table: "the reported
//     maximum shader clock ... aligned with Window setting") and the PROFILE_PEAK pstate. It is never sent to the PMFW in AUTO, so we do not
//     send it either: the PMFW boosts within its own power, current and thermal limits, as on Linux and Windows.
//   * smu_bump_power_profile_mode: SetWorkloadMask (PPSMC_MSG_SetWorkloadMask 0x24) with the backend mask of
//     PP_SMC_POWER_PROFILE_BOOTUP_DEFAULT -> WORKLOAD_PPLIB_DEFAULT_BIT 0 (smu_v14_0_2_workload_map), i.e. param 0x1.
//  THE GATE. Unclamping a GPU whose command fetcher never idles sends GFXCLK to the 170 W board limit (2026-11-12). So, after the whole boot
//  ladder (native S1b included), 64 samples 1 ms apart of UNBANKED status registers (GRBM_STATUS, GRBM_STATUS2, CP_CPF_STATUS; no select, no
//  write). A sample is busy when GUI_ACTIVE, GRBM_STATUS2.CPF_BUSY or CP_CPF_STATUS.CPF_BUSY is set. DPM is applied only when at most 25 % of the
//  samples are busy (idle in at least 75 %); otherwise the 500 MHz clamp (or the navi48-gfxmax cap) stays and Navi48,Dpm says why.
//  Boot-args: navi48-dpm=0 keeps the clamp; navi48-gfxmax=<MHz> still caps (DPM then runs below the cap); navi48-idle-clamp=0 as before
//  (no clamp at all, no gate).
//
#pragma once
#include <stdint.h>

namespace n48dpm {

constexpr uint32_t kMsgSetWorkloadMask = 0x24u;          // PPSMC_MSG_SetWorkloadMask (smu_v14_0_2_ppsmc.h)
constexpr uint32_t kWorkloadPplibDefaultBit = 0u;        // WORKLOAD_PPLIB_DEFAULT_BIT (smu14_driver_if_v14_0.h)
constexpr uint32_t workload_mask_bootup_default() { return 1u << kWorkloadPplibDefaultBit; }
constexpr uint32_t kAutoSoftMax = 0xFFFFu, kAutoSoftMin = 0u;   // smu_v14_0_set_soft_freq_limited_range(automatic = true)

// amdgpu::SMUPowerState values (amdgpu_smu.h; static_assert'ed in dpm_boot.cpp).
constexpr uint32_t kStateAuto = 0u, kStateLow = 1u, kStateBootCap = 5u;

// navi48-dpm: absent or non-zero = the gate decides (default); 0 = keep the boot clamp (0.0.677 behaviour).
inline bool dpm_wanted(bool present, uint32_t v) { return !present || v != 0u; }

// The gate sampler.
constexpr uint32_t kGateSamples = 64u, kGateGapUs = 1000u, kGateMaxBusyPct = 25u;
constexpr uint32_t kGuiActiveBit = 31u, kGrbm2CpfBusyBit = 28u, kCpfStatusCpfBusyBit = 31u;
inline bool sample_busy(uint32_t grbmStatus, uint32_t grbmStatus2, uint32_t cpfStatus) {
    return ((grbmStatus >> kGuiActiveBit) & 1u) || ((grbmStatus2 >> kGrbm2CpfBusyBit) & 1u) || ((cpfStatus >> kCpfStatusCpfBusyBit) & 1u);
}
// Idle in most samples: at least kGateSamples taken, at most kGateMaxBusyPct % of them busy.
inline bool gate_pass(uint32_t busy, uint32_t samples) {
    return samples >= kGateSamples && busy <= samples && (uint64_t)busy * 100u <= (uint64_t)samples * kGateMaxBusyPct;
}

enum Verdict : uint32_t {
    kNotRun = 0,          // runStages has not reached the gate
    kOffBootArg,          // navi48-dpm=0: the clamp stays
    kNoClamp,             // navi48-idle-clamp=0: there is no clamp to lift (the PMFW has picked since boot)
    kNotFullPath,         // the ladder did not complete (or MES failed / the SMU is offline): the clamp stays
    kGateBusy,            // the fetcher was busy in more than 25 % of the samples: the clamp stays
    kApplied,             // DPM applied (soft min 0 / soft max 0xffff, or the navi48-gfxmax cap)
    kHeldThermal,         // the thermal clamp is in force: DPM becomes the restore target, applied when the watchdog releases
    kApplyFailed,         // the SMU refused the clock messages: the clamp is re-sent
};
inline const char *verdict_name(uint32_t v) {
    switch (v) {
    case kNotRun:      return "not run";
    case kOffBootArg:  return "off (navi48-dpm=0): the boot clamp stays";
    case kNoClamp:     return "no clamp (navi48-idle-clamp=0): the PMFW picks since boot, no gate";
    case kNotFullPath: return "not applied: the bring-up ladder did not complete; the boot clamp stays";
    case kGateBusy:    return "not applied: the command fetcher was busy at the gate; the boot clamp stays";
    case kApplied:     return "applied: GFXCLK under PMFW DPM";
    case kHeldThermal: return "deferred: a thermal clamp is in force; DPM is the restore target";
    case kApplyFailed: return "failed: the SMU refused the clock messages; the boot clamp was re-sent";
    default:           return "?";
    }
}

// The decision before any message is sent.
inline uint32_t decide(bool wanted, bool idleClamp, bool fullPath, bool gatePassed, bool thermalClamped) {
    if (!idleClamp) return kNoClamp;
    if (!wanted) return kOffBootArg;
    if (!fullPath) return kNotFullPath;
    if (!gatePassed) return kGateBusy;
    if (thermalClamped) return kHeldThermal;
    return kApplied;
}

// The SMU power state that runs GFXCLK under DPM: Auto (soft max 0xffff, soft min 0) without a cap, BootCap (soft max = the cap) with one.
inline uint32_t dpm_state(uint32_t capMhz) { return capMhz != 0u ? kStateBootCap : kStateAuto; }
// The boot clamp (0.0.676/0.0.677): BootCap with a cap, Low (soft max = PMFW minimum) without one.
inline uint32_t clamp_state(uint32_t capMhz) { return capMhz != 0u ? kStateBootCap : kStateLow; }

// What the thermal watchdog restores after a TRIP clamp is released (n4xs::set_restore_state): the DPM policy once DPM is applied or
// deferred, Auto when there is no clamp at all, else the boot clamp.
inline uint32_t restore_state(uint32_t verdict, uint32_t capMhz) {
    if (verdict == kNoClamp) return kStateAuto;
    if (verdict == kApplied || verdict == kHeldThermal) return dpm_state(capMhz);
    return clamp_state(capMhz);
}

}  // namespace n48dpm
