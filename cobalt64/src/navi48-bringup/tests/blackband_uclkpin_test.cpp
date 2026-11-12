// blackband_uclkpin_test.cpp - build 0.0.672 (black band): the display UCLK pin. Compiles the REAL amd/smu_v14_0.cpp on the host (the tests/dalshim
// KPI shims, as native_s2_dal_test.cpp does) against a simulated PMFW on the PPSMC mailbox, and drives smu_pin_uclk_for_display / smu_hw_init.
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -pthread '-D__asm__=0;' '-D__volatile__(...)=' \
//       -I src/navi48-bringup/tests/dalshim -I src/navi48-bringup/src -I src/navi48-bringup/src/amd \
//       src/navi48-bringup/tests/blackband_uclkpin_test.cpp src/navi48-bringup/src/amd/smu_v14_0.cpp -o /tmp/blackband_uclkpin && /tmp/blackband_uclkpin
// Covers: P the pure rules (boot-arg, params, plausibility, names); B the exact PPSMC message list per scenario (pinned, off, query failure,
// implausible reply, set refused, PMFW without reply); I smu_hw_init calls the pin only on the full setup and before the protection gate.
// 0.0.673: the default is AUTO (no message at SMU init), navi48-uclkpin=1 FORCE is the 0.0.672 pin; D the run-time pin / release
// (smu_uclk_display_pin) of the display monitor's fallback; F the fallback state machine (n48uclk::fb).
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
        State f; init(f, kModeAuto, false);
        expect(step(f, kModeAuto, 1000, 5, true) == kNone, "not armed (the arbitration has not run): underflows do not pin");
        f.armed = true;
        expect(step(f, kModeAuto, 2000, 1, true) == kNone && step(f, kModeAuto, 3000, 1, true) == kNone, "2 events: not yet");
        expect(step(f, kModeAuto, 4000, 1, true) == kPin && f.why == kWhyUnderflow, "3 events within 10 s: PIN");
        done(f, kPin, true, 4000);
        expect(f.pinned && f.latched && f.triggers == 1u && step(f, kModeAuto, 4050, 9, true) == kNone, "pinned: nothing more");
        expect(step(f, kModeAuto, 5000, 0, false) == kNone && step(f, kModeAuto, 6900, 0, false) == kNone, "display off < 2 s: kept");
        expect(step(f, kModeAuto, 7000, 0, false) == kRelease && f.why == kWhyDisplayOff, "display off 2 s: RELEASE");
        done(f, kRelease, true, 7000);
        expect(!f.pinned && f.releases == 1u && step(f, kModeAuto, 8000, 0, false) == kNone, "released, stays released while off");
        expect(step(f, kModeAuto, 9000, 0, true) == kPin && f.why == kWhyWake, "display back after an underflow pin: PIN again at once");
        done(f, kPin, false, 9000);
        expect(f.failures == 1u && step(f, kModeAuto, 9050, 0, true) == kNone && step(f, kModeAuto, 19000, 0, true) == kPin, "a failed pin is retried after 10 s, not before");
        State g; init(g, kModeAuto, false); g.armed = true;
        expect(step(g, kModeAuto, 1000, 1, true) == kNone && step(g, kModeAuto, 2000, 1, true) == kNone && step(g, kModeAuto, 13000, 1, true) == kNone,
               "3 events spread over more than 10 s: no pin (the window restarts)");
        expect(step(g, kModeAuto, 14000, 0, false) == kNone && step(g, kModeAuto, 15000, 1, true) == kNone && g.winEvents == 1u, "a display-off period clears the window");
        State h; init(h, kModeForce, true); h.armed = true;
        expect(h.latched && h.pinned && step(h, kModeForce, 1000, 0, false) == kNone && step(h, kModeForce, 3000, 0, false) == kRelease, "force: released while the display is off");
        done(h, kRelease, true, 3000);
        expect(step(h, kModeForce, 4000, 0, true) == kPin && h.why == kWhyWake, "force: pinned again when the display is back");
        State o; init(o, kModeOff, false); o.armed = true;
        expect(step(o, kModeOff, 1000, 50, true) == kNone && step(o, kModeOff, 1100, 50, true) == kNone, "off: never");
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
