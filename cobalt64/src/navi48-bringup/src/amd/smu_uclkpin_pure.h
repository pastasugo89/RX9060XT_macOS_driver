//
//  smu_uclkpin_pure.h - build 0.0.672 (black band): the PURE half of the display UCLK pin. No kernel header, so
//  tests/blackband_uclkpin_test.cpp compiles it on the host and drives the exact decisions smu_v14_0.cpp makes.
//
//  Why: smc_hw_setup's EnableAllSmuFeatures turns on DPM_UCLK (feature bit 3; the boot logs read running low word 0x38fffcfb), so the PMFW
//  changes the memory clock whenever the GPU load changes. Each UCLK switch is a DRAM blackout (DCN 4.01 bounding box:
//  dram_clk_change_blackout_us = 400, Linux dml2 dcn4_soc_bb.h). The GOP's 2560x1440@120 timing on this LG has a vertical blank of
//  1525 - 1440 = 85 lines x 5.465 us = 0.46 ms: too short to hide that blackout plus the next frame's prefetch, so the first lines of the
//  frame after a switch starve (DCN underflow: black at the top of the screen). Linux never lets that happen: when the mode cannot hide a
//  p-state switch (clk_mgr p_state_change_support false) dcn401_update_clocks sets the UCLK hard minimum to the maximum
//  ("when P-State switching disabled, set UCLK min = max", dcn401_clk_mgr.c). Nothing on this stack does the equivalent.
//  The 60 Hz mode (V_TOTAL 3050: a 8.8 ms blank) hides the blackout, which is why the band became rare there.
//
//  What: after the features are enabled, ask the PMFW for the UCLK DPM maximum (PPSMC GetMaxDpmFreq, PPCLK_UCLK) and set the UCLK SOFT
//  minimum to it (PPSMC SetSoftMinByFreq, the same message Linux's pp_dpm_mclk / smu_v14_0_set_soft_freq_limited_range uses). The soft
//  maximum is not touched; throttlers (PPT/TDC/thermal) still win over a soft minimum.
//  Kill switch: boot-arg navi48-uclkpin=0 (absent or any other value = ON).
#pragma once
#include <stdint.h>

namespace n48uclk {

constexpr uint32_t kPpclkUclk = 2u;                 // PPCLK_UCLK (smu14_driver_if_v14_0.h PPCLK_e: GFXCLK 0, SOCCLK 1, UCLK 2, FCLK 3)
constexpr uint32_t kMsgSetSoftMinByFreq = 0x19u;    // PPSMC_MSG_SetSoftMinByFreq (smu_v14_0_2_ppsmc.h)
constexpr uint32_t kMsgGetMinDpmFreq = 0x1Du;       // PPSMC_MSG_GetMinDpmFreq
constexpr uint32_t kMsgGetMaxDpmFreq = 0x1Eu;       // PPSMC_MSG_GetMaxDpmFreq
constexpr uint32_t kMinPlausibleMhz = 100u;         // a GDDR6 UCLK maximum below this is not a reply we trust
constexpr uint32_t kMaxPlausibleMhz = 5000u;

enum Verdict : uint32_t {
    kNotRun = 0,       // smc_hw_setup did not run (navi48-smu-full off / basic): DPM was never enabled by us, nothing to pin
    kOff = 1,          // boot-arg navi48-uclkpin=0
    kPinned = 2,       // SetSoftMinByFreq(UCLK, max) answered OK
    kQueryFailed = 3,  // GetMaxDpmFreq failed: nothing sent
    kImplausible = 4,  // the reply is outside [100, 5000] MHz or below the reported minimum: nothing sent
    kSetFailed = 5,    // SetSoftMinByFreq was answered with an error: the clock state is the PMFW's default (as before 0.0.672)
};
constexpr const char *verdict_name(uint32_t v) {
    return v == kNotRun ? "not-run (SMU features not enabled by this boot)" : v == kOff ? "off (boot-arg navi48-uclkpin=0)" : v == kPinned ? "pinned" :
           v == kQueryFailed ? "query-failed (GetMaxDpmFreq; nothing sent)" : v == kImplausible ? "implausible-max (nothing sent)" :
           v == kSetFailed ? "set-failed (SetSoftMinByFreq refused; PMFW default kept)" : "?";
}

struct Result { uint32_t verdict, minMhz, maxMhz, setMhz, kr; };

// The boot-arg: `present` = PE_parse_boot_argn found it. Only an explicit 0 turns the pin off.
constexpr bool enabled(bool present, uint32_t value) { return !(present && value == 0u); }
// The GetMin/MaxDpmFreq parameter and the SetSoftMinByFreq parameter (clk_id << 16 | MHz, smu_v14_0_set_soft_freq_limited_range).
constexpr uint32_t query_param() { return kPpclkUclk << 16; }
constexpr uint32_t set_param(uint32_t mhz) { return (kPpclkUclk << 16) | (mhz & 0xFFFFu); }
// The PMFW's GetMaxDpmFreq reply is MHz in the low 16 bits (Linux masks nothing here, but a value above 16 bits is not a clock).
constexpr bool max_ok(uint32_t maxMhz, bool haveMin, uint32_t minMhz) {
    return maxMhz >= kMinPlausibleMhz && maxMhz <= kMaxPlausibleMhz && (!haveMin || minMhz <= maxMhz);
}

} // namespace n48uclk
