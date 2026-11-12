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
//
//  0.0.673: the pin is no longer the default. 0.0.673 gives the display the Linux DET and watermarks (dcn/navi48_disparb_pure.h), which hide a
//  UCLK switch during active scanout, so the memory clock stays under PMFW DPM control (idle 96 MHz). The pin becomes a FALLBACK: the display
//  monitor thread (dcn/navi48_dcn.cpp) pins when the scanout underflow monitor counts kTriggerEvents underflows within kWindowMs AFTER the
//  arbitration ran, and releases the pin (soft minimum back to the DPM minimum) when the display has been off for kOffReleaseMs; it pins
//  again when the display comes back, because an underflow proved this boot needs it (fb::step below).
//  Boot-arg navi48-uclkpin: absent (or any value other than 0 and 1) = AUTO (the fallback), 1 = FORCE (pinned at SMU init, the 0.0.672
//  behaviour, still released while the display is off), 0 = OFF (never pinned, no fallback).
//  0.0.674: the fallback has two stages before any pin: stage 1 forces the stutter off again (no pin), and only the next trigger pins (the fb
//  namespace below). An AUTO pin is released once after 10 minutes without a counted underflow (kQuietReleaseMs); FORCE keeps its pin.
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
    kAuto = 6,         // 0.0.673 default: not pinned; the display monitor pins on underflow (the fallback)
    kReleased = 7,     // 0.0.673: the soft minimum was put back to the UCLK DPM minimum (the display is off)
};
constexpr const char *verdict_name(uint32_t v) {
    return v == kNotRun ? "not-run (SMU features not enabled by this boot)" : v == kOff ? "off (boot-arg navi48-uclkpin=0)" : v == kPinned ? "pinned" :
           v == kQueryFailed ? "query-failed (GetMaxDpmFreq; nothing sent)" : v == kImplausible ? "implausible-max (nothing sent)" :
           v == kSetFailed ? "set-failed (SetSoftMinByFreq refused; PMFW default kept)" :
           v == kAuto ? "auto (not pinned: memory clock under PMFW DPM; pins on display underflow)" :
           v == kReleased ? "released (soft minimum = UCLK DPM minimum)" : "?";
}

// Why the last pin / release happened (Result.why). 0.0.674: kWhyQuiet = the time-limited release (10 min without a counted underflow).
enum Why : uint32_t { kWhyBoot = 0, kWhyUnderflow = 1, kWhyWake = 2, kWhyDisplayOff = 3, kWhyQuiet = 4 };
constexpr const char *why_name(uint32_t w) {
    return w == kWhyBoot ? "boot" : w == kWhyUnderflow ? "display underflow" : w == kWhyWake ? "display on again after an underflow pin" :
           w == kWhyDisplayOff ? "display off" : w == kWhyQuiet ? "10 min without underflow (time-limited release, once per boot)" : "?";
}

// verdict/minMhz/maxMhz/setMhz/kr: the last operation. mode: the boot-arg mode. why/pins/releases: 0.0.673.
struct Result { uint32_t verdict, minMhz, maxMhz, setMhz, kr; uint32_t mode, why, pins, releases; };

// The boot-arg: `present` = PE_parse_boot_argn found it.
enum Mode : uint32_t { kModeOff = 0, kModeAuto = 1, kModeForce = 2 };
constexpr uint32_t mode_of(bool present, uint32_t value) { return !present ? kModeAuto : value == 0u ? kModeOff : value == 1u ? kModeForce : kModeAuto; }
constexpr const char *mode_name(uint32_t m) { return m == kModeOff ? "off" : m == kModeAuto ? "auto" : m == kModeForce ? "force" : "?"; }
// The release target must be a plausible DPM minimum not above the maximum.
constexpr bool min_ok(uint32_t minMhz, uint32_t maxMhz) { return minMhz >= 10u && minMhz <= kMaxPlausibleMhz && minMhz <= maxMhz; }
// The GetMin/MaxDpmFreq parameter and the SetSoftMinByFreq parameter (clk_id << 16 | MHz, smu_v14_0_set_soft_freq_limited_range).
constexpr uint32_t query_param() { return kPpclkUclk << 16; }
constexpr uint32_t set_param(uint32_t mhz) { return (kPpclkUclk << 16) | (mhz & 0xFFFFu); }
// The PMFW's GetMaxDpmFreq reply is MHz in the low 16 bits (Linux masks nothing here, but a value above 16 bits is not a clock).
constexpr bool max_ok(uint32_t maxMhz, bool haveMin, uint32_t minMhz) {
    return maxMhz >= kMinPlausibleMhz && maxMhz <= kMaxPlausibleMhz && (!haveMin || minMhz <= maxMhz);
}

// ---- 0.0.673 / 0.0.674: the fallback state machine the display monitor thread runs every 50 ms (navi48_dcn.cpp arb_monitor_loop) ----------------
// 0.0.674 (two stages, then one time-limited release):
//   stage 1 (kStutterOff): the first trigger (kTriggerEvents counted underflow events within kWindowMs) forces the stutter off again, as the GOP had it
//           (DRAM_STATE SELF_REFRESH_FORCE). NO pin.
//   stage 2 (kPin): the next trigger, counted from the stage 1 action, pins UCLK (the soft minimum is the maximum), as 0.0.673's trigger did.
//   quiet release (kRelease, kWhyQuiet): AUTO only, once per boot: a stage-2 pin is released when the display has been on for kQuietReleaseMs with no
//           counted underflow since the last one (or since the pin). The fallback stays at stage 2 (re-armed, not latched): the next trigger pins again,
//           and that pin is kept for the rest of the boot (no second quiet release). navi48-uclkpin=1 (FORCE) is never released by this rule.
// The display-off release (kOffReleaseMs) and the pin on the display's return (latched) are unchanged from 0.0.673.
namespace fb {
constexpr uint32_t kTriggerEvents = 3u;      // counted underflow events (ufmon) ...
constexpr uint64_t kWindowMs = 10000u;       // ... within this window (one band lasting about 1 s is many 50 ms polls; an isolated event is not enough)
constexpr uint64_t kOffReleaseMs = 2000u;    // the display off (OTG0 not lit or HUBP0 blanked) this long releases a pin
constexpr uint64_t kRetryMs = 10000u;        // a failed action (stutter, pin, release) is not retried sooner
constexpr uint64_t kQuietReleaseMs = 600000u;   // 0.0.674: 10 minutes with the display on and no counted underflow: the one time-limited release
enum Act : uint32_t { kNone = 0, kPin = 1, kRelease = 2, kStutterOff = 3 };
enum Stage : uint32_t { kStageNone = 0, kStageStutterOff = 1, kStagePinned = 2 };   // the highest stage reached (FORCE starts at kStagePinned)
struct State {
    bool armed;           // the arbitration ran (any verdict): from then on underflows count toward the fallback
    bool pinned;          // the soft minimum is the maximum right now
    bool latched;         // stage 2 was reached and this boot needs the pin (FORCE, or an underflow pin): pin again whenever the display is on
    bool everPinned;      // a pin was made this boot (the first is a trigger, a later one a repin)
    bool quietAllowed;    // the time-limited release may still happen: AUTO, and not used yet this boot
    bool off;             // the display is off since offSinceMs
    uint32_t stage, winEvents, why;
    uint64_t offSinceMs, winStartMs, retryAtMs, lastEventMs, stage1AtMs, pinAtMs;
    uint64_t triggers, repins, releases, quietReleases, stage1s, failures;
};
inline void init(State &s, uint32_t mode, bool pinnedAtBoot) {
    s = State{};
    s.latched = mode == kModeForce;
    s.pinned = pinnedAtBoot;
    s.everPinned = pinnedAtBoot;
    s.stage = pinnedAtBoot ? kStagePinned : kStageNone;
    s.quietAllowed = mode == kModeAuto;
}
// The registry's words for the fallback (Navi48,UclkPin, Navi48,DisplayArb): the highest stage reached, and whether the pin is on now.
inline const char *status_text(const State &s) {
    return s.stage == kStageNone ? "stage 0 (not triggered)" : s.stage == kStageStutterOff ? "fallback stage 1 (stutter off, no pin)" :
           s.pinned ? "fallback stage 2 (pinned)" : s.quietReleases ? "fallback stage 2 (released after 10 min without underflow, re-armed)" :
           "fallback stage 2 (released while the display is off)";
}
// One poll. newEvents = underflow events ufmon counted since the previous poll. Returns what to do; the caller does it (no lock held) and reports
// the outcome with done().
inline uint32_t step(State &s, uint32_t mode, uint64_t nowMs, uint64_t newEvents, bool displayOn) {
    if (mode == kModeOff) return kNone;
    if (newEvents > 0u) s.lastEventMs = nowMs;   // 0.0.674: the quiet clock restarts at every counted underflow
    if (nowMs < s.retryAtMs) return kNone;
    if (!displayOn) {
        if (!s.off) { s.off = true; s.offSinceMs = nowMs; }
        s.winEvents = 0;   // what happens while the display is off says nothing about the scanout
        if (s.pinned && nowMs - s.offSinceMs >= kOffReleaseMs) { s.why = kWhyDisplayOff; return kRelease; }
        return kNone;
    }
    s.off = false;
    if (!s.pinned && s.latched) { s.why = kWhyWake; return kPin; }
    if (s.pinned) {
        // 0.0.674: the one time-limited release (AUTO only): the display on and no counted underflow for kQuietReleaseMs.
        if (s.quietAllowed && nowMs - s.lastEventMs >= kQuietReleaseMs) { s.why = kWhyQuiet; return kRelease; }
        return kNone;
    }
    if (!s.armed || newEvents == 0u) return kNone;
    if (s.winEvents == 0u || nowMs - s.winStartMs > kWindowMs) { s.winStartMs = nowMs; s.winEvents = 0u; }
    s.winEvents += (uint32_t)(newEvents > 1000u ? 1000u : newEvents);
    if (s.winEvents < kTriggerEvents) return kNone;
    s.why = kWhyUnderflow;
    return s.stage == kStageNone ? kStutterOff : kPin;   // 0.0.674: stage 1 first (no pin), stage 2 on the next trigger
}
inline void done(State &s, uint32_t act, bool ok, uint64_t nowMs) {
    if (!ok) { s.failures++; s.retryAtMs = nowMs + kRetryMs; return; }
    if (act == kStutterOff) {
        s.stage = kStageStutterOff; s.stage1s++; s.stage1AtMs = nowMs; s.winEvents = 0u; s.triggers++;   // the window of stage 2 starts now
    } else if (act == kPin) {
        if (s.why == kWhyUnderflow) s.triggers++;
        if (s.everPinned) s.repins++;   // a pin after an earlier one: the display back, or the re-arm after the quiet release
        s.everPinned = true;
        s.pinned = true; s.latched = true; s.stage = kStagePinned; s.pinAtMs = nowMs; s.lastEventMs = nowMs; s.winEvents = 0u;
    } else if (act == kRelease) {
        s.pinned = false; s.releases++;
        if (s.why == kWhyQuiet) { s.quietReleases++; s.quietAllowed = false; s.latched = false; }   // re-armed at stage 2: only an underflow pins again
    }
}
}  // namespace fb

} // namespace n48uclk
