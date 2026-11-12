//
//  navi48_ufmon_pure.h - build 0.0.672 (black band): the PURE half of the scanout underflow monitor. tests/blackband_ufmon_test.cpp drives it.
//
//  The scanout watchdog thread (navi48_dcn.cpp scan_watchdog_loop, every 50 ms while a native client holds the plane) reads HUBP0_DCHUBP_CNTL
//  and ODM0_OPTC_INPUT_GLOBAL_CONTROL. Both underflow statuses are STICKY, so one read only says "at least one underflow since the last clear".
//  To count and timestamp each event the monitor clears them with the same write-1 strobes the mode trial uses (n48mt::uf, Linux
//  hubp1_clear_underflow / optc1_clear_optc_underflow), through the DCN allowlist, never while OPTC INPUT_SOFT_RESET is set, and only when gMtLock
//  (the mode trial / 60 Hz hold) is free. The first sample after an acquisition is a BASELINE: what it finds predates the monitor (the GOP, an
//  earlier session, the 60 Hz transition) and is cleared but not counted.
//  Output: kernel log lines "ufmon: UNDERFLOW #n ..." (navi48test log) and the registry property Navi48,DisplayUnderflow (ioreg, no root).
//  Kill switch: boot-arg navi48-ufmon=0 (nothing is read or written).
#pragma once
#include <stdint.h>
#include "navi48_modetrial_pure.h"   // n48mt::uf (the bit layout and the strobe values, pinned by tests/native_s2d_test.cpp)

namespace n48ufmon {

constexpr uint32_t kLogFirst = 20u, kLogEvery = 64u;

struct Mon {
    uint32_t gen;              // the scanout acquisition the counters belong to (a new one restarts the baseline, not the totals)
    bool baselined, uncleared;   // uncleared: an event was counted while busy and is still set (not counted again)
    uint64_t polls, events, hubpEvents, optcEvents, baselineStale, clears, clearRefused, unreadable, busySkips;
    uint64_t firstNs, lastNs, lastFrame;
    uint32_t lastHubp, lastOptc;
};
inline void init(Mon &m) { m = Mon{}; }

enum Act : uint32_t { kNone = 0, kClear = 1 };
struct Step { uint32_t act; bool counted, log, stale; };

constexpr bool enabled(bool present, uint32_t value) { return !(present && value == 0u); }
constexpr bool should_log(uint64_t n) { return n <= kLogFirst || (n % kLogEvery) == 0u; }

// One sample. busy = gMtLock could not be taken (the trial / the 60 Hz hold is writing the pipe): read-only this time, never clear.
inline Step step(Mon &m, uint32_t gen, uint32_t hubp, uint32_t optc, uint64_t nowNs, uint64_t frame, bool busy) {
    Step s{ kNone, false, false, false };
    if (gen != m.gen) { m.gen = gen; m.baselined = false; m.uncleared = false; }
    m.polls++;
    if (n48mt::uf::unreadable(hubp) || n48mt::uf::unreadable(optc)) { m.unreadable++; return s; }   // a dead read is never a verdict and never written back
    const bool hb = n48mt::uf::hubp_bad(hubp), ob = n48mt::uf::optc_bad(optc);
    if (!m.baselined) {
        if (busy) { m.busySkips++; return s; }
        m.baselined = true;
        if (hb || ob) { m.baselineStale++; s.stale = true; s.act = kClear; }
        return s;
    }
    if (!hb && !ob) { m.uncleared = false; return s; }
    // A status counted while busy (not cleared) is still the same event on the next sample: count it once.
    if (!m.uncleared) {
        m.events++; if (hb) m.hubpEvents++; if (ob) m.optcEvents++;
        if (!m.firstNs) m.firstNs = nowNs;
        m.lastNs = nowNs; m.lastFrame = frame; m.lastHubp = hubp; m.lastOptc = optc;
        s.counted = true; s.log = should_log(m.events);
    }
    if (busy) { m.busySkips++; m.uncleared = true; return s; }
    m.uncleared = false;
    if (ob && n48mt::uf::clear_refused(optc)) { m.clearRefused++; m.uncleared = true; }
    s.act = kClear;
    return s;
}
// After the caller's clear: `stillBad` = the read-back after the strobes still shows a status. That status is the SAME event (a clear that did not
// take, or an OPTC soft reset that refused it): it is not counted again until a sample reads clean.
inline void after_clear(Mon &m, bool wrote, bool stillBad) { if (wrote) m.clears++; if (stillBad) m.uncleared = true; }
// The strobe values (the caller writes HUBP first when it is bad, then OPTC when it is bad and not in soft reset), then the unstrobe if one reads back set.
constexpr bool hubp_needs_clear(uint32_t hubp) { return !n48mt::uf::unreadable(hubp) && n48mt::uf::hubp_bad(hubp); }
constexpr bool optc_needs_clear(uint32_t optc) { return !n48mt::uf::unreadable(optc) && n48mt::uf::optc_bad(optc) && !n48mt::uf::clear_refused(optc); }

} // namespace n48ufmon
