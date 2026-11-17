//
//  smu_gfxmax_pure.h - 0.0.676: the boot GFXCLK cap (boot-arg navi48-gfxmax=<MHz>), the first rung of the clock ladder (pure, host-tested by
//  tests/fan_od676_test.cpp).
//
//  Without the boot-arg nothing changes: the idle clamp sends SetSoftMaxByFreq(GFXCLK, PMFW minimum) exactly as 0.0.675 (smu_set_power_state Low).
//  With it, the idle clamp (and the thermal watchdog's RESTORE after a TRIP clamp) sends SetSoftMaxByFreq(GFXCLK, cap) instead, where cap is the
//  requested MHz bounded to the PMFW's [GetMinDpmFreq, GetMaxDpmFreq] range. The thermal TRIP clamp itself stays at the PMFW minimum. No SetSoftMin
//  is sent (as Low). navi48-idle-clamp=0 (Auto) ignores the cap. Live changes are not offered: navi48test power still takes 0..4 only.
//
#pragma once
#include <stdint.h>

namespace n48gfx {

constexpr uint32_t kMaxPlausibleMhz = 10000u;   // the same bound smu_set_power_state Low applies to the PMFW range

// The requested cap from the boot-arg: 0 = absent or 0 (no cap: Low, the 0.0.675 behaviour).
inline uint32_t requested_of(bool present, uint32_t v) { return present && v != 0u && v <= kMaxPlausibleMhz ? v : 0u; }

// The MHz to send for a valid PMFW range [lo, hi]: the request bounded to it. 0 = the range is not plausible (the caller refuses, as Low does).
inline uint32_t cap_mhz(uint32_t requested, uint32_t lo, uint32_t hi) {
    if (lo == 0u || lo > hi || hi > kMaxPlausibleMhz) return 0u;
    if (requested == 0u || requested < lo) return lo;
    return requested > hi ? hi : requested;
}

} // namespace n48gfx
