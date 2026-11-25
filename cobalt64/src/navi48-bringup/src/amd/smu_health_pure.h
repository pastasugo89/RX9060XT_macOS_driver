//
//  smu_health_pure.h - build 0.0.685: the PURE half of the SMU mailbox health latch. No kernel header, so tests/smuhealth685_test.cpp compiles
//  it on the host and drives the exact decisions smu_v14_0.cpp (the PPSMC wrapper), smu_dal.cpp (the DAL sender) and clkfloor.cpp make.
//
//  Why (0.0.684, live boot 2026-11-25 19:37): the display clock floors sent NumOfDisplays(1) (OK), then SetHardMinByFreq(DCFCLK, 147 MHz) (OK),
//  then the first ReturnHardMinStatus was never answered (2 s) and from then on the PMFW answered neither mailbox: every PPSMC message
//  (GetDriverIfVersion of each metrics read) timed out after 2 s. The 0.0.684 clock trace kept sending one every 500 ms (188 timeouts), each one
//  holding the shared mailbox lock and the display monitor thread for 2 s, and each one rewriting the mailbox while the PMFW had not answered the
//  previous message. Linux (swsmu smu_cmn.c, smu_msg_v1_send_msg) does neither: it pre-polls the response of the previous message and sends
//  nothing while it is 0, and after a fatal reply it latches SMU_FW_HANG and refuses every later message.
//
//  The latch, as a state machine:
//    kUnarmed   the boot SMU bring-up (smu_hw_init, DPM, fan) runs exactly as before 0.0.685; timeouts are only counted. smu_health_arm() (the
//               display monitor thread's start) moves to kHealthy.
//    kHealthy   everything may be sent. A PPSMC timeout -> kDegraded. A DAL timeout -> kSuspect (and the DAL mailbox is off for the boot).
//    kSuspect   only the health probe (GetSmuVersion on the PPSMC mailbox) may be sent: OK -> kHealthy (DAL stays off), no answer -> kDegraded.
//    kDegraded  NOTHING is sent (every PPSMC / DAL message is refused at once, no register touched), so no caller waits 2 s on a dead PMFW. The
//               PMFW keeps the clocks it last set (DPM as last set). The only way back: the display monitor reads (never writes) the PPSMC
//               response register every kRecoverPollMs; once the PMFW has answered the pending message (RESP != 0) it sends ONE GetSmuVersion,
//               at most kMaxProbes times per boot. OK -> kHealthy (optional traffic resumes; the DAL mailbox and the clock trace stay off).
//  "Optional" traffic (the clock trace, the UCLK fallback pin, user-client metrics/power states, telemetry) asks optional_ok() first and stops.
//
#pragma once
#include <stdint.h>

namespace n48smuh {

enum State : uint32_t { kUnarmed = 0, kHealthy = 1, kSuspect = 2, kDegraded = 3 };
enum Reason : uint32_t { kRNone = 0, kRMainTimeout = 1, kRDalTimeout = 2, kRProbeFailed = 3, kRPending = 4, kRDalProbeOk = 5, kRRecovered = 6 };
enum Event : uint32_t {
    kEvArm = 0,            // the display monitor started: from now on a timeout latches
    kEvMainOk = 1,         // a PPSMC message was answered (any reply: the PMFW is alive)
    kEvMainTimeout = 2,    // a PPSMC message was not answered within 2 s
    kEvDalTimeout = 3,     // a DAL message was not answered within 2 s
    kEvProbeOk = 4,        // the health probe (PPSMC GetSmuVersion) was answered OK
    kEvProbeFail = 5,      // the health probe was not sent (RESP still 0) or not answered
    kEvPendingSeen = 6,    // a PPSMC send found the previous message still unanswered (RESP 0): nothing was written
};
constexpr uint32_t kMaxProbes = 3u;
constexpr uint64_t kRecoverPollMs = 10000u;

struct Health {
    uint32_t state;        // State
    uint32_t reason;       // Reason of the last transition
    bool mainPending;      // our last PPSMC message was never answered (its RESP may still be 0)
    bool dalPending;       // our last DAL message was never answered
    bool dalOff;           // the DAL mailbox is off for the rest of the boot (after any DAL timeout)
    uint32_t mainTimeouts, dalTimeouts, refused, pendingSeen, probes, probesOk, recoveries, transitions;
    uint64_t sinceMs;      // uptime of the last state change
};

constexpr Health initial() { return Health{ kUnarmed, kRNone, false, false, false, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u }; }

constexpr Health go(Health h, uint32_t st, uint32_t why, uint64_t nowMs) {
    if (h.state != st) { h.state = st; h.sinceMs = nowMs; h.transitions++; }
    h.reason = why;
    return h;
}

constexpr Health on_event(Health h, uint32_t ev, uint64_t nowMs) {
    switch (ev) {
    case kEvArm:
        return h.state == kUnarmed ? go(h, kHealthy, kRNone, nowMs) : h;
    case kEvMainOk:
        h.mainPending = false;
        return h;
    case kEvMainTimeout:
        h.mainTimeouts++;
        h.mainPending = true;
        return h.state == kUnarmed ? h : go(h, kDegraded, kRMainTimeout, nowMs);
    case kEvDalTimeout:
        h.dalTimeouts++;
        h.dalPending = true;
        h.dalOff = true;
        return h.state == kHealthy ? go(h, kSuspect, kRDalTimeout, nowMs) : h;
    case kEvProbeOk:
        h.probesOk++;
        h.mainPending = false;
        if (h.state == kSuspect) return go(h, kHealthy, kRDalProbeOk, nowMs);
        if (h.state == kDegraded) { h.recoveries++; return go(h, kHealthy, kRRecovered, nowMs); }
        return h;
    case kEvProbeFail:
        return h.state == kUnarmed ? h : go(h, kDegraded, kRProbeFailed, nowMs);
    case kEvPendingSeen:
        h.pendingSeen++;
        return h.state == kUnarmed ? h : go(h, kDegraded, kRPending, nowMs);
    default:
        return h;
    }
}

// The PPSMC wrapper's gate, before it touches a register. respNow = the PPSMC response register as read now (read only when it matters:
// the caller passes ~0u when it did not read it). Unarmed: always kGo (the pre-0.0.685 path).
enum Gate : uint32_t { kGo = 0, kRefuseLatched = 1, kRefusePending = 2, kNeedResp = 3 };
constexpr uint32_t main_gate(const Health &h, bool probe, uint32_t respNow) {
    if (h.state == kUnarmed) return kGo;
    if (h.state == kDegraded || h.state == kSuspect) {
        if (!probe) return kRefuseLatched;
    }
    if (h.mainPending) {
        if (respNow == ~0u) return kNeedResp;      // read RESP first
        if (respNow == 0u) return kRefusePending;  // the PMFW has not answered the previous message: never write over it (Linux's pre-poll)
    }
    return kGo;
}
// The DAL sender's gate (before its allowlist): off after any DAL timeout, and while the PPSMC side is not healthy. Unarmed: as before.
constexpr bool dal_ok(const Health &h) {
    if (h.dalOff || h.dalPending) return false;
    return h.state == kUnarmed || h.state == kHealthy;
}
// Optional SMU traffic (the clock trace, the UCLK fallback, user-client metrics and power states, telemetry): only while healthy (or unarmed).
constexpr bool optional_ok(const Health &h) { return h.state == kUnarmed || h.state == kHealthy; }
// The display monitor's recovery: in kDegraded, every kRecoverPollMs, read RESP; probe only when the pending message has been answered.
constexpr bool recover_probe(const Health &h, uint32_t respNow) {
    return h.state == kDegraded && h.probes < kMaxProbes && respNow != 0u && respNow != ~0u;
}

constexpr const char *state_name(uint32_t s) {
    return s == kUnarmed ? "unarmed (boot bring-up)" : s == kHealthy ? "healthy" : s == kSuspect ? "suspect (DAL timeout, probing the PPSMC mailbox)" :
           s == kDegraded ? "DEGRADED (PMFW not answering: no SMU message is sent)" : "?";
}
constexpr const char *reason_name(uint32_t r) {
    return r == kRNone ? "none" : r == kRMainTimeout ? "a PPSMC message timed out" : r == kRDalTimeout ? "a DAL message timed out" :
           r == kRProbeFailed ? "the PPSMC health probe was not answered" : r == kRPending ? "the previous PPSMC message is still unanswered" :
           r == kRDalProbeOk ? "DAL timeout, but the PPSMC mailbox answers (DAL off for the boot)" : r == kRRecovered ? "the PMFW answered again" : "?";
}

// ---- the clock trace's self-limit (clkfloor.cpp take_sample) --------------------------------------------------------------------------------
// After kTraceBackoffAfter consecutive failed samples the period grows (5 s, 10 s, 20 s, 40 s, 60 s); after kTraceStopAfter consecutive
// failures the trace stops for the boot. A good sample resets the run. A refused sample (SMU degraded) stops it at once.
constexpr uint32_t kTraceBackoffAfter = 2u, kTraceStopAfter = 5u;
constexpr uint64_t kTraceBaseMs = 500u, kTraceBackoffMs = 5000u, kTraceMaxBackoffMs = 60000u;
constexpr uint64_t trace_period_ms(uint32_t consecutiveFailures) {
    if (consecutiveFailures < kTraceBackoffAfter) return kTraceBaseMs;
    uint64_t p = kTraceBackoffMs;
    for (uint32_t i = kTraceBackoffAfter; i < consecutiveFailures && p < kTraceMaxBackoffMs; i++) p *= 2u;
    return p > kTraceMaxBackoffMs ? kTraceMaxBackoffMs : p;
}
constexpr bool trace_should_stop(uint32_t consecutiveFailures) { return consecutiveFailures >= kTraceStopAfter; }

}  // namespace n48smuh
