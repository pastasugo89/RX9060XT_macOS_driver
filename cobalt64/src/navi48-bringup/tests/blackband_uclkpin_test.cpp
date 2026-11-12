// blackband_uclkpin_test.cpp - build 0.0.674 (black band): the display UCLK pin. Compiles the REAL amd/smu_v14_0.cpp on the host (the tests/dalshim
// KPI shims, as native_s2_dal_test.cpp does) against a simulated PMFW on the PPSMC mailbox, and drives smu_pin_uclk_for_display / smu_hw_init.
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -pthread '-D__asm__=0;' '-D__volatile__(...)=' \
//       -I src/navi48-bringup/tests/dalshim -I src/navi48-bringup/src -I src/navi48-bringup/src/amd \
//       src/navi48-bringup/tests/blackband_uclkpin_test.cpp src/navi48-bringup/src/amd/smu_v14_0.cpp -o /tmp/blackband_uclkpin && /tmp/blackband_uclkpin
// Covers: P the pure rules (boot-arg, params, plausibility, names); B the exact PPSMC message list per scenario (pinned, off, query failure,
// implausible reply, set refused, PMFW without reply); I smu_hw_init calls the pin only on the full setup and before the protection gate.
// 0.0.673: the default is AUTO (no message at SMU init), navi48-uclkpin=1 FORCE is the 0.0.672 pin; D the run-time pin / release
// (smu_uclk_display_pin) of the display monitor's fallback; F the fallback state machine (n48uclk::fb).
// 0.0.674: F has two stages before any pin (stage 1 = the stutter forced off again, no pin; stage 2 = the pin on the next trigger) and the one
// time-limited release of an AUTO pin (10 min with the display on and no counted underflow; re-armed at stage 2, never latched by it).
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdarg>
#include <vector>
#include <string>
#include <utility>
#include <pthread.h>
#include <kern/thread.h>
#include <libkern/OSAtomic.h>
#include "smu_uclkpin_pure.h"
#include "amdgpu_smu.h"
#include "native_s1b.h"

static int gFail = 0, gRun = 0;
static void expect(bool ok, const char *what) { gRun++; if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }

// ---- the simulated PMFW: PPSMC mailbox msg 0x16282, arg 0x16292, resp 0x1629A (MP1 base 0x16200) ----
int gDalShimLockCount = 0, gDalShimLockAllocFail = 0;   // tests/dalshim/IOKit/IOLocks.h
static uint32_t gReg[0x17000];
struct World {
    std::vector<std::pair<uint32_t, uint32_t>> seen;
    uint32_t uclkMin = 96, uclkMax = 2518, softMinUclk = 0;
    uint32_t failMsg = 0, failResp = 0xFF; bool hangMsgAll = false;
    uint32_t featuresLo = 0x38fffcfbu, featuresHi = 0x0498f59eu;
} W;
static void pmfw_service() {
    const uint32_t msg = gReg[0x16282];
    if (msg == 0u || W.hangMsgAll) return;
    const uint32_t arg = gReg[0x16292];
    W.seen.push_back({ msg, arg });
    gReg[0x16282] = 0u;
    if (W.failMsg && msg == W.failMsg) { gReg[0x1629A] = W.failResp; return; }
    uint32_t ret = 0;
    switch (msg) {
    case 0x01: ret = arg + 1u; break;                                   // TestMessage
    case 0x1D: ret = (arg >> 16) == 2u ? W.uclkMin : 0u; break;         // GetMinDpmFreq
    case 0x1E: ret = (arg >> 16) == 2u ? W.uclkMax : 0u; break;         // GetMaxDpmFreq
    case 0x19: if ((arg >> 16) == 2u) W.softMinUclk = arg & 0xFFFFu; break;   // SetSoftMinByFreq
    case 0x0C: ret = W.featuresLo; break;                               // GetRunningSmuFeaturesLow
    case 0x0D: ret = W.featuresHi; break;                               // GetRunningSmuFeaturesHigh
    default: break;
    }
    gReg[0x16292] = ret; gReg[0x1629A] = 1u;
}
static uint64_t gNow = 1000000000ull;
extern "C" void dalshim_sleep(unsigned ms) { gNow += (uint64_t)ms * 1000000ull; pmfw_service(); }
extern "C" void clock_get_uptime(uint64_t *t) { gNow += 1000ull; pmfw_service(); *t = gNow; }
extern "C" void absolutetime_to_nanoseconds(uint64_t t, uint64_t *ns) { *ns = t; }
extern "C" thread_t current_thread(void) { return (thread_t)(uintptr_t)pthread_self(); }
extern "C" bool OSCompareAndSwap(UInt32 o, UInt32 n, volatile UInt32 *p) { return __sync_bool_compare_and_swap(p, o, n); }
extern "C" bool OSCompareAndSwapPtr(void *o, void *n, void *volatile *p) { return __sync_bool_compare_and_swap(p, o, n); }
static struct { bool present; uint32_t val; } gArg;
extern "C" bool PE_parse_boot_argn(const char *name, void *out, int sz) {
    if (std::strcmp(name, "navi48-uclkpin") != 0 || !gArg.present || sz != 4) return false;
    std::memcpy(out, &gArg.val, 4); return true;
}
static std::vector<std::string> gLog;
namespace amdgpu {
void n48_logf(const char *fmt, ...) { char b[1024]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap); gLog.push_back(b); }
static NativeS1bState gS1b;
const NativeS1bState &native_s1b_state() { return gS1b; }
}
static amdgpu::DeviceContext gDev;
static void world_reset() {
    std::memset(gReg, 0, sizeof gReg); W = World(); gArg.present = false; gArg.val = 0; gLog.clear();
    gReg[0x1629A] = 1u;   // a previous message answered OK (the sender's pre-check)
    gDev.rmmio = gReg; gDev.rmmioSize = sizeof gReg; gDev.ip.setBase(amdgpu::IPBlock::MP1, 1, 0x16200u); gDev.smuOnline = true;
}
static bool seen_exact(const std::vector<std::pair<uint32_t, uint32_t>> &want) { return W.seen == want; }

int main() {
    using namespace n48uclk;
    // ---- P: pure rules ----
    expect(mode_of(false, 0) == kModeAuto && mode_of(true, 0) == kModeOff && mode_of(true, 1) == kModeForce && mode_of(true, 7) == kModeAuto,
           "0.0.673: absent = auto (fallback only), 0 = off, 1 = force (the 0.0.672 pin), anything else = auto");
    expect(query_param() == 0x00020000u && set_param(2518) == 0x000209D6u && set_param(0x12345) == 0x00022345u, "params: PPCLK_UCLK (2) << 16 | MHz");
    expect(max_ok(2518, true, 96) && max_ok(100, false, 0) && max_ok(5000, true, 5000), "plausible maxima accepted");
    expect(!max_ok(99, false, 0) && !max_ok(5001, false, 0) && !max_ok(0, false, 0) && !max_ok(500, true, 600) && !max_ok(0xFFFFFFFFu, false, 0), "implausible maxima refused");
    expect(min_ok(96, 2518) && !min_ok(0, 2518) && !min_ok(3000, 2518) && !min_ok(0xFFFFFFFFu, 0xFFFFFFFFu), "release target: a plausible minimum not above the maximum");
    expect(kPpclkUclk == amdgpu::SMUClk::UCLK, "PPCLK_UCLK matches the metrics index (amdgpu_smu.h)");
    expect(kMsgSetSoftMinByFreq == amdgpu::PPSMC::SetSoftMinByFreq && kMsgGetMinDpmFreq == amdgpu::PPSMC::GetMinDpmFreq && kMsgGetMaxDpmFreq == amdgpu::PPSMC::GetMaxDpmFreq, "message ids match amdgpu_ip.h");
    expect(std::strcmp(verdict_name(kPinned), "pinned") == 0 && std::strstr(verdict_name(kOff), "navi48-uclkpin=0") != nullptr && std::strstr(verdict_name(kAuto), "auto") != nullptr &&
           std::strstr(verdict_name(kReleased), "released") != nullptr, "verdict names");

    // ---- D0: before smu_hw_init enabled the features, the run-time path sends nothing ----
    world_reset();
    kern_return_t r = amdgpu::smu_uclk_display_pin(gDev, true, kWhyUnderflow);
    expect(r == kIOReturnNotPermitted && W.seen.empty(), "run-time pin before SMU init: refused, no message");
    // ---- B1: default (no boot-arg) = AUTO: nothing sent at SMU init ----
    world_reset();
    r = amdgpu::smu_pin_uclk_for_display(gDev);
    expect(r == kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kAuto && amdgpu::smu_uclk_pin_result().mode == kModeAuto && W.seen.empty(),
           "default: auto, NO message (the memory clock stays under PMFW DPM)");
    // ---- D1: the fallback pin at run time, then the release ----
    W.seen.clear();
    r = amdgpu::smu_uclk_display_pin(gDev, true, kWhyUnderflow);
    expect(r == kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kPinned && amdgpu::smu_uclk_pin_result().why == kWhyUnderflow && W.softMinUclk == 2518,
           "fallback pin: pinned to the maximum");
    expect(seen_exact({ { 0x1D, 0x20000 }, { 0x1E, 0x20000 }, { 0x19, 0x209D6 } }), "fallback pin: exactly GetMin, GetMax, SetSoftMin(UCLK, 2518)");
    W.seen.clear();
    r = amdgpu::smu_uclk_display_pin(gDev, false, kWhyDisplayOff);
    expect(r == kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kReleased && W.softMinUclk == 96 && amdgpu::smu_uclk_pin_result().setMhz == 96,
           "release: the soft minimum back to the DPM minimum");
    expect(seen_exact({ { 0x1D, 0x20000 }, { 0x1E, 0x20000 }, { 0x19, 0x20060 } }), "release: exactly GetMin, GetMax, SetSoftMin(UCLK, 96)");
    expect(amdgpu::smu_uclk_pin_result().pins == 1u && amdgpu::smu_uclk_pin_result().releases == 1u, "counted");
    W.seen.clear(); W.failMsg = 0x1D; W.softMinUclk = 1234;
    r = amdgpu::smu_uclk_display_pin(gDev, false, kWhyDisplayOff);
    expect(r != kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kQueryFailed && W.softMinUclk == 1234 && W.seen.size() == 2, "release without a minimum: nothing set");
    W.seen.clear(); W.failMsg = 0; W.uclkMin = 0;
    (void)amdgpu::smu_uclk_display_pin(gDev, false, kWhyDisplayOff);
    expect(amdgpu::smu_uclk_pin_result().verdict == kImplausible && W.softMinUclk == 1234, "release to a 0 MHz minimum: implausible, nothing set");
    // ---- B2: FORCE (navi48-uclkpin=1) = the 0.0.672 pin at SMU init ----
    world_reset(); gArg.present = true; gArg.val = 1;
    r = amdgpu::smu_pin_uclk_for_display(gDev);
    expect(r == kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kPinned && amdgpu::smu_uclk_pin_result().mode == kModeForce, "navi48-uclkpin=1: pinned");
    expect(seen_exact({ { 0x1D, 0x20000 }, { 0x1E, 0x20000 }, { 0x19, 0x209D6 } }), "force: exactly GetMin, GetMax, SetSoftMin(UCLK, 2518)");
    expect(W.softMinUclk == 2518 && amdgpu::smu_uclk_pin_result().setMhz == 2518 && amdgpu::smu_uclk_pin_result().minMhz == 96, "the soft minimum is the DPM maximum");
    // ---- B3: OFF ----
    world_reset(); gArg.present = true; gArg.val = 0;
    r = amdgpu::smu_pin_uclk_for_display(gDev);
    expect(r == kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kOff && W.seen.empty(), "navi48-uclkpin=0: OFF and NO message at all");
    r = amdgpu::smu_uclk_display_pin(gDev, true, kWhyUnderflow);
    expect(r == kIOReturnNotPermitted && W.seen.empty(), "navi48-uclkpin=0: the fallback never pins");
    // ---- B4..B8: the force pin's failure paths (as 0.0.672) ----
    world_reset(); gArg.present = true; gArg.val = 1; W.failMsg = 0x1E;
    r = amdgpu::smu_pin_uclk_for_display(gDev);
    expect(r != kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kQueryFailed, "max query refused: query-failed");
    expect(W.softMinUclk == 0 && W.seen.size() == 2 && W.seen.back().first == 0x1E, "max query refused: SetSoftMin never sent");
    world_reset(); gArg.present = true; gArg.val = 1; W.uclkMax = 7000;
    (void)amdgpu::smu_pin_uclk_for_display(gDev);
    expect(amdgpu::smu_uclk_pin_result().verdict == kImplausible && W.softMinUclk == 0 && W.seen.size() == 2, "7000 MHz: implausible, nothing sent");
    world_reset(); gArg.present = true; gArg.val = 1; W.uclkMax = 50; W.uclkMin = 96;
    (void)amdgpu::smu_pin_uclk_for_display(gDev);
    expect(amdgpu::smu_uclk_pin_result().verdict == kImplausible && W.softMinUclk == 0, "max below min: implausible");
    world_reset(); gArg.present = true; gArg.val = 1; W.failMsg = 0x1D;
    (void)amdgpu::smu_pin_uclk_for_display(gDev);
    expect(amdgpu::smu_uclk_pin_result().verdict == kPinned && W.softMinUclk == 2518 && amdgpu::smu_uclk_pin_result().minMhz == 0, "min query refused: still pinned on a plausible max");
    world_reset(); gArg.present = true; gArg.val = 1; W.failMsg = 0x19;
    r = amdgpu::smu_pin_uclk_for_display(gDev);
    expect(r != kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kSetFailed && W.softMinUclk == 0, "SetSoftMin refused: set-failed, PMFW default");
    world_reset(); gArg.present = true; gArg.val = 1; W.hangMsgAll = true;
    r = amdgpu::smu_pin_uclk_for_display(gDev);
    expect(r != kIOReturnSuccess && amdgpu::smu_uclk_pin_result().verdict == kQueryFailed && W.softMinUclk == 0, "PMFW silent: returns (bounded), query-failed");

    // ---- F: the fallback state machine ----
    {
        using namespace n48uclk::fb;
        const uint64_t Q = kQuietReleaseMs;
        auto is = [](const char *a, const char *b) { return std::strcmp(a, b) == 0; };
        expect(kTriggerEvents == 3u && kWindowMs == 10000u && kOffReleaseMs == 2000u && kRetryMs == 10000u && Q == 600000u,
               "the constants: 3 events within 10 s, 2 s display off, 10 s retry, 10 min quiet");
        expect(kStageNone == 0u && kStageStutterOff == 1u && kStagePinned == 2u && kStutterOff == 3u && kWhyQuiet == 4u, "stages, actions and the quiet why");
        // ---- the start: AUTO (stage 0, the one time-limited release allowed), FORCE (stage 2, pinned, never quiet-released), OFF ----
        State a; init(a, kModeAuto, false);
        expect(a.stage == kStageNone && !a.pinned && !a.latched && a.quietAllowed && !a.everPinned && is(status_text(a), "stage 0 (not triggered)"), "auto at boot: stage 0");
        // ---- stage 1: the first trigger forces the stutter off again, NO pin ----
        State f; init(f, kModeAuto, false);
        expect(step(f, kModeAuto, 1000, 5, true) == kNone, "not armed (the arbitration has not run): underflows do not act");
        f.armed = true;
        expect(step(f, kModeAuto, 2000, 1, true) == kNone && step(f, kModeAuto, 3000, 1, true) == kNone, "2 events: not yet");
        expect(step(f, kModeAuto, 4000, 1, true) == kStutterOff && f.why == kWhyUnderflow, "3 events within 10 s: STAGE 1 (the stutter off, no pin)");
        done(f, kStutterOff, true, 4000);
        expect(f.stage == kStageStutterOff && f.stage1s == 1u && f.stage1AtMs == 4000u && f.triggers == 1u && !f.pinned && !f.latched,
               "stage 1 done: not pinned, not latched, counted");
        expect(is(status_text(f), "fallback stage 1 (stutter off, no pin)"), "the registry's words for stage 1");
        expect(step(f, kModeAuto, 4500, 0, false) == kNone && step(f, kModeAuto, 5000, 0, true) == kNone, "stage 1 is not latched: the display off and on pins nothing");
        // ---- stage 2: the next trigger, counted from the stage 1 action, pins ----
        expect(step(f, kModeAuto, 5100, 2, true) == kNone && step(f, kModeAuto, 6000, 0, true) == kNone, "after stage 1: 2 events do not pin");
        expect(step(f, kModeAuto, 6100, 1, true) == kPin && f.why == kWhyUnderflow, "stage 2: 3 events within 10 s after stage 1 PIN");
        done(f, kPin, true, 6100);
        expect(f.pinned && f.latched && f.stage == kStagePinned && f.triggers == 2u && f.repins == 0u && f.pinAtMs == 6100u,
               "pinned at stage 2: the first pin is a trigger, not a repin");
        expect(is(status_text(f), "fallback stage 2 (pinned)"), "the registry's words for stage 2");
        expect(step(f, kModeAuto, 6150, 9, true) == kNone, "pinned: an underflow changes nothing but the quiet clock");
        expect(step(f, kModeAuto, 7000, 0, false) == kNone && step(f, kModeAuto, 8900, 0, false) == kNone, "display off < 2 s: kept");
        expect(step(f, kModeAuto, 9000, 0, false) == kRelease && f.why == kWhyDisplayOff, "display off 2 s: RELEASE (as 0.0.673)");
        done(f, kRelease, true, 9000);
        expect(!f.pinned && f.releases == 1u && f.quietReleases == 0u && step(f, kModeAuto, 9500, 0, false) == kNone, "released, stays released while off");
        expect(step(f, kModeAuto, 10000, 0, true) == kPin && f.why == kWhyWake, "display back after an underflow pin: PIN again at once");
        done(f, kPin, true, 10000);
        expect(f.pinned && f.repins == 1u && f.triggers == 2u, "the wake pin is a repin");
        // ---- a failed stage 1 is retried after 10 s, not before, and is not a stage ----
        State r; init(r, kModeAuto, false); r.armed = true;
        expect(step(r, kModeAuto, 1000, 3, true) == kStutterOff, "a failing stage 1 is asked for");
        done(r, kStutterOff, false, 1000);
        expect(r.failures == 1u && r.stage == kStageNone && !r.pinned && r.stage1s == 0u, "a failed stage 1: nothing done, counted");
        expect(step(r, kModeAuto, 5000, 3, true) == kNone && step(r, kModeAuto, 10999, 3, true) == kNone, "not retried sooner than 10 s");
        expect(step(r, kModeAuto, 11000, 3, true) == kStutterOff, "retried at 10 s");
        done(r, kStutterOff, true, 11000);
        expect(r.stage == kStageStutterOff && r.stage1s == 1u && r.failures == 1u, "the retry succeeded");
        // ---- a failed stage 2 pin keeps stage 1 ----
        State p; init(p, kModeAuto, false); p.armed = true;
        expect(step(p, kModeAuto, 1000, 3, true) == kStutterOff, "a trigger at stage 0 asks for stage 1"); done(p, kStutterOff, true, 1000);
        expect(step(p, kModeAuto, 2000, 3, true) == kPin, "a trigger at stage 1 asks for the pin"); done(p, kPin, false, 2000);
        expect(p.stage == kStageStutterOff && !p.pinned && p.failures == 1u && p.triggers == 1u, "a failed stage 2 pin: still stage 1, counted");
        // ---- the window: 3 events spread over more than 10 s do not trigger ----
        State g; init(g, kModeAuto, false); g.armed = true;
        expect(step(g, kModeAuto, 1000, 1, true) == kNone && step(g, kModeAuto, 2000, 1, true) == kNone && step(g, kModeAuto, 13000, 1, true) == kNone,
               "3 events spread over more than 10 s: no trigger (the window restarts)");
        expect(g.winEvents == 1u, "the window restarted at 13 s");
        expect(step(g, kModeAuto, 14000, 0, false) == kNone && step(g, kModeAuto, 15000, 1, true) == kNone && g.winEvents == 1u, "a display-off period clears the window");
        // ---- 0.0.674: the one time-limited release of an AUTO pin: 10 min with the display on and no counted underflow ----
        State q; init(q, kModeAuto, false); q.armed = true;
        expect(step(q, kModeAuto, 1000, 3, true) == kStutterOff, "quiet case: stage 1"); done(q, kStutterOff, true, 1000);
        expect(step(q, kModeAuto, 2000, 3, true) == kPin, "quiet case: stage 2 pin"); done(q, kPin, true, 2000);
        expect(step(q, kModeAuto, 2000 + Q - 1, 0, true) == kNone, "pinned: not released 1 ms before 10 min without an underflow");
        expect(step(q, kModeAuto, 2000 + Q, 0, true) == kRelease && q.why == kWhyQuiet, "10 min with the display on and no counted underflow: RELEASE (time-limited)");
        done(q, kRelease, true, 2000 + Q);
        expect(!q.pinned && q.quietReleases == 1u && q.releases == 1u && !q.quietAllowed && !q.latched && q.stage == kStagePinned,
               "released once: re-armed at stage 2, NOT latched (the display back does not pin it)");
        expect(is(status_text(q), "fallback stage 2 (released after 10 min without underflow, re-armed)"), "the registry's words for the quiet release");
        const uint64_t t1 = 2000 + Q;
        expect(step(q, kModeAuto, t1 + 100, 0, false) == kNone && step(q, kModeAuto, t1 + 3000, 0, true) == kNone,
               "released: the display off and on does not re-pin (no underflow proved the need)");
        expect(step(q, kModeAuto, t1 + 4000, 1, true) == kNone && step(q, kModeAuto, t1 + 4500, 2, true) == kPin && q.why == kWhyUnderflow,
               "re-armed at stage 2: 3 underflows PIN again");
        done(q, kPin, true, t1 + 4500);
        expect(q.pinned && q.latched && q.triggers == 3u && q.repins == 1u && q.quietReleases == 1u, "the re-arm pin: a trigger and a repin");
        expect(step(q, kModeAuto, t1 + 4500 + 10 * Q, 0, true) == kNone, "pinned for the rest of the boot: no second time-limited release");
        const uint64_t t2 = t1 + 4500 + 10 * Q;
        expect(step(q, kModeAuto, t2 + 1000, 0, false) == kNone && step(q, kModeAuto, t2 + 3000, 0, false) == kRelease && q.why == kWhyDisplayOff,
               "the display-off release still applies after the quiet re-pin (0.0.673)");
        // an underflow while pinned restarts the quiet clock
        State e; init(e, kModeAuto, false); e.armed = true;
        expect(step(e, kModeAuto, 1000, 3, true) == kStutterOff, "restart case: stage 1"); done(e, kStutterOff, true, 1000);
        expect(step(e, kModeAuto, 2000, 3, true) == kPin, "restart case: stage 2 pin"); done(e, kPin, true, 2000);
        expect(step(e, kModeAuto, 300000, 1, true) == kNone, "an underflow while pinned restarts the quiet clock");
        expect(step(e, kModeAuto, 2000 + Q, 0, true) == kNone, "the clock from the pin would have released here: not now");
        expect(step(e, kModeAuto, 300000 + Q, 0, true) == kRelease && e.why == kWhyQuiet, "10 min after that underflow: RELEASE");
        // ---- FORCE (navi48-uclkpin=1): pinned at boot, the display-off release and the wake pin as 0.0.672, never quiet-released ----
        State h; init(h, kModeForce, true); h.armed = true;
        expect(h.latched && h.pinned && h.stage == kStagePinned && !h.quietAllowed && h.everPinned, "force: pinned at boot (stage 2), no time-limited release");
        expect(step(h, kModeForce, 1000 + 20 * Q, 0, true) == kNone, "force: never released by the quiet rule");
        expect(step(h, kModeForce, 1000, 0, false) == kNone && step(h, kModeForce, 3000, 0, false) == kRelease && h.why == kWhyDisplayOff,
               "force: released while the display is off");
        done(h, kRelease, true, 3000);
        expect(step(h, kModeForce, 4000, 0, true) == kPin && h.why == kWhyWake, "force: pinned again when the display is back");
        done(h, kPin, true, 4000);
        expect(h.repins == 1u && h.quietReleases == 0u, "force: the wake pin is a repin");
        State o; init(o, kModeOff, false); o.armed = true;
        expect(step(o, kModeOff, 1000, 50, true) == kNone && step(o, kModeOff, 1100, 50, true) == kNone, "off: never");
        expect(std::strcmp(why_name(kWhyQuiet), "10 min without underflow (time-limited release, once per boot)") == 0, "the quiet release's name");
    }

    // ---- I: smu_hw_init wiring ----
    world_reset();
    (void)amdgpu::smu_hw_init(gDev, false);
    bool any = false; for (auto &p : W.seen) any |= (p.first == 0x19 || p.first == 0x1E);
    expect(!any, "smu_hw_init(full=false): no UCLK message (the pin needs the features we enabled)");
    world_reset(); gArg.present = true; gArg.val = 1; gDev.vramMcBase = 0; gDev.vramBase = 0; gDev.vramLimit = 0;
    (void)amdgpu::smu_hw_init(gDev, true);
    any = false; for (auto &p : W.seen) any |= (p.first == 0x19 || p.first == 0x1E);
    expect(!any && W.softMinUclk == 0, "smc_hw_setup failed before EnableAllSmuFeatures (no driver table): no UCLK message");
    world_reset(); gDev.vramMcBase = 0x8000000000ull; gDev.vramBase = 0x01000000ull; gDev.vramLimit = 0x400000000ull;
    (void)amdgpu::smu_hw_init(gDev, true);
    any = false; for (auto &p : W.seen) any |= (p.first == 0x19 || p.first == 0x1E || p.first == 0x1D);
    expect(!any && W.softMinUclk == 0 && amdgpu::smu_uclk_pin_result().verdict == kAuto, "smu_hw_init(full=true), default: no UCLK message, verdict auto");
    world_reset(); gArg.present = true; gArg.val = 1; gDev.vramMcBase = 0x8000000000ull; gDev.vramBase = 0x01000000ull; gDev.vramLimit = 0x400000000ull;
    (void)amdgpu::smu_hw_init(gDev, true);
    size_t iSet = 99, iFeat = 99; for (size_t i = 0; i < W.seen.size(); i++) { if (W.seen[i].first == 0x19 && W.seen[i].second == 0x209D6u && iSet == 99) iSet = i; if (W.seen[i].first == 0x0C) iFeat = i; }
    expect(iSet != 99 && W.softMinUclk == 2518, "smu_hw_init(full=true), force: UCLK pinned");
    size_t iEnable = 99; for (size_t i = 0; i < W.seen.size(); i++) if (W.seen[i].first == amdgpu::PPSMC::EnableAllSmuFeatures) iEnable = i;
    expect(iEnable != 99 && iEnable < iSet, "the pin comes after EnableAllSmuFeatures");
    // the protection gate reads features after the pin (last GetRunningSmuFeaturesLow is after the pin)
    expect(iFeat != 99 && iFeat > iSet, "the protection gate's feature read comes after the pin");
    std::printf("%s: %d checks, %d failed\n", gFail ? "FAIL" : "PASS", gRun, gFail);
    return gFail ? 1 : 0;
}
