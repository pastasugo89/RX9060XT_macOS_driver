// smuhealth685_test.cpp - build 0.0.685: the SMU mailbox health latch, the guarded display clock floors and the self-limiting clock trace.
// It compiles the REAL kernel sources amd/smu_v14_0.cpp, amd/smu_dal.cpp and amd/clkfloor.cpp on the host (the tests/dalshim KPI shims, IOSleep
// advancing a fake clock, as native_s2_dal_test.cpp does) against a simulated PMFW with BOTH mailboxes (PPSMC 0x16282/0x16292/0x1629A and DAL
// 0x1628A/0x16273/0x16274) that can WEDGE: after the message that wedges it, it answers nothing on either mailbox, exactly what the live 0.0.684 boot
// of 2026-11-25 showed (NumOfDisplays OK, SetHardMinByFreq(DCFCLK 147) OK, then ReturnHardMinStatus and every PPSMC message unanswered).
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -pthread '-D__asm__=0;' '-D__volatile__(...)=' \
//       -I tests/dalshim -I <tree>/src -I <tree>/src/amd tests/smuhealth685_test.cpp <tree>/src/amd/smu_v14_0.cpp <tree>/src/amd/smu_dal.cpp \
//       <tree>/src/amd/clkfloor.cpp -o /tmp/smuhealth685 && /tmp/smuhealth685
// Each scenario runs in a forked child (the latch, the floors' once-per-boot state and the trace are per-boot statics of the real code).
// Covers:
//   P   the pure latch (smu_health_pure.h): every transition, the gates, the recovery rule, the trace back-off;
//   R   the 0.0.684 failure reproduced (floors opted in, clocks as assumed): DAL timeout -> one PPSMC probe -> DEGRADED; after it NO register write on
//       either mailbox from the trace, the UCLK fallback, metrics, power states or the DAL sender, each refused in < 1 ms of fake time (no 2 s waits);
//       the pending PPSMC message is never written over; passive recovery only after the PMFW answers, bounded probes;
//   D   the floors' defaults and preconditions: absent = nothing sent; DISPCLK/DPPCLK 562.5 MHz = nothing sent; a healthy run sends the plan between a
//       readiness probe and a post-check, all under one hold of the shared lock;
//   T   the trace: one timeout stops it (DEGRADED); error replies back off (0.5, 5, 10, 20 s) and stop after 5; a busy lock skips without a failure;
//       the metrics table is copied through the registered (locked) VRAM reader;
//   U   unarmed (the boot bring-up): a timeout does not latch and the next message is still sent (the pre-0.0.685 path).
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cstdarg>
#include <string>
#include <vector>
#include <utility>
#include <pthread.h>
#include <unistd.h>
#include <sys/wait.h>

#include <kern/thread.h>
#include <libkern/OSAtomic.h>
#include "smu_health_pure.h"
#include "smu_dal_pure.h"
#include "smu_dal.h"
#include "clkfloor.h"
#include "clkfloor_pure.h"
#include "amdgpu_smu.h"
#include "native_s1b.h"
#include "Navi48NativeABI.h"
#include "../src/dcn/navi48_dcn.hpp"

static int gFail = 0, gRun = 0;
static void expect(bool ok, const char *what) { gRun++; if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }
static void expect_u(const char *what, uint64_t got, uint64_t want) {
    gRun++;
    if (got != want) { gFail++; std::printf("FAIL: %s: got %llu want %llu\n", what, (unsigned long long)got, (unsigned long long)want); }
}

// =====================================================================================================================================
// The simulated machine
// =====================================================================================================================================
int gDalShimLockCount = 0, gDalShimLockAllocFail = 0;
static uint64_t gNowNs = 1000000000ull;
static pthread_mutex_t gTimeMu = PTHREAD_MUTEX_INITIALIZER;
constexpr uint32_t kPMsg = 0x16282u, kPArg = 0x16292u, kPResp = 0x1629Au;
constexpr uint32_t kDMsg = n48dal::kRegMsg, kDArg = n48dal::kRegArg, kDResp = n48dal::kRegResp;

struct World {
    uint32_t reg[0x17000];
    bool wedged;                     // the PMFW answers nothing on either mailbox
    uint32_t wedgeOnDal;             // a DAL message id that is ANSWERED OK and then wedges the PMFW (0 = none)
    uint32_t wedgeOnDalParamClk;     // ... only for this clock (param >> 16) when non-zero
    uint32_t ppsmcFailMsg, ppsmcFailResp;   // a PPSMC message answered with an error reply
    uint32_t ppsmcLatencyMs;         // a PPSMC answer arrives after this long (0 = at the next service)
    uint64_t ppsmcDue; bool ppsmcPending; uint32_t pMsg, pArg;
    std::vector<std::pair<uint32_t, uint32_t>> ppsmcSeen, dalSeen;   // every message the PMFW RECEIVED (taken off the mailbox)
    uint32_t ppsmcWrites, dalWrites;  // every MSG register write the driver made (seen at the next service: a rewrite while pending counts too)
    uint32_t lastPMsgSeenWrite, lastDMsgSeenWrite;
    uint32_t did0, did1, pll;
    uint32_t vramReads;
};
static World W;
static amdgpu::DeviceContext gDev;
static amdgpu::NativeS1bState gS1b;
static std::vector<std::string> gLog;
struct Arg { const char *name; bool present; uint32_t val; };
static Arg gArgs[3] = { { "navi48-dalfloor", false, 0 }, { "navi48-clklog", false, 0 }, { "navi48-uclkpin", false, 0 } };

static void sync_clocks() {
    W.reg[n48dal::kRegPllReq] = W.pll; W.reg[n48dal::kRegDfs0] = W.did0; W.reg[n48dal::kRegDfs1] = W.did1;
    W.reg[n48dal::kRegDentist] = (W.did1 << 24) | 0x007F0000u | (W.did0 << 8) | W.did0;
}
static void dal_handle(uint32_t msg, uint32_t arg) {
    using namespace n48dalfloor;
    W.dalSeen.push_back({ msg, arg });
    uint32_t ret = 0;
    switch (msg) {
    case kMsgGetSmuVersion: ret = 0x00664700u; break;
    case kMsgGetDriverIfVersion: ret = 0x33u; break;
    case kMsgGetMsgHeaderVersion: ret = 1u; break;
    case kMsgGetDpmFreqByIndex: {
        const uint32_t clk = (arg >> 16) & 0xFF, idx = arg & 0xFFFF;
        if (clk == kClkDcfclk) ret = idx == 0xFF ? 0x80000000u : idx == 0 ? 147u : idx == 1 ? 1800u : 0u;
        else if (clk == kClkUclk) ret = idx == 0xFF ? 4u : idx == 0 ? 96u : idx == 1 ? 456u : idx == 2 ? 772u : 2518u;
        break;
    }
    case kMsgNumOfDisplays: case kMsgSetMinDeepSleepDcfclk: case kMsgSetUclkPstateAllow: break;
    case kMsgSetHardMinByFreq: ret = arg & 0xFFFF; break;
    case kMsgReturnHardMinStatus: ret = 0x3FFu; break;
    default: W.reg[kDResp] = n48dal::kRespUnknownCmd; return;
    }
    W.reg[kDArg] = ret; W.reg[kDResp] = n48dal::kRespOk;
    if (W.wedgeOnDal != 0u && msg == W.wedgeOnDal && (W.wedgeOnDalParamClk == 0u || (arg >> 16) == W.wedgeOnDalParamClk)) W.wedged = true;
}
static void ppsmc_handle(uint32_t msg, uint32_t arg) {
    W.ppsmcSeen.push_back({ msg, arg });
    if (W.ppsmcFailMsg != 0u && msg == W.ppsmcFailMsg) { W.reg[kPResp] = W.ppsmcFailResp; return; }
    uint32_t ret = 0;
    switch (msg) {
    case 0x02: ret = 0x00664700u; break;       // GetSmuVersion
    case 0x03: ret = 0x33u; break;             // GetDriverIfVersion
    case 0x01: ret = arg + 1u; break;          // TestMessage
    case 0x1D: ret = 96u; break;               // GetMinDpmFreq
    case 0x1E: ret = 2518u; break;             // GetMaxDpmFreq
    default: break;
    }
    W.reg[kPArg] = ret; W.reg[kPResp] = 1u;
}
static void service() {
    sync_clocks();
    // a MSG write the driver made since the last service (the driver writes RESP = 0, ARG, MSG; the PMFW clears MSG when it takes the message)
    if (W.reg[kPMsg] != 0u && W.reg[kPMsg] != W.lastPMsgSeenWrite) { W.ppsmcWrites++; W.lastPMsgSeenWrite = W.reg[kPMsg]; }
    if (W.reg[kDMsg] != 0u && W.reg[kDMsg] != W.lastDMsgSeenWrite) { W.dalWrites++; W.lastDMsgSeenWrite = W.reg[kDMsg]; }
    if (W.wedged) return;
    if (W.reg[kDMsg] != 0u) { const uint32_t m = W.reg[kDMsg]; W.reg[kDMsg] = 0u; W.lastDMsgSeenWrite = 0u; dal_handle(m, W.reg[kDArg]); }
    if (W.wedged) return;
    if (!W.ppsmcPending && W.reg[kPMsg] != 0u) {
        W.ppsmcPending = true; W.pMsg = W.reg[kPMsg]; W.pArg = W.reg[kPArg]; W.reg[kPMsg] = 0u; W.lastPMsgSeenWrite = 0u;
        W.ppsmcDue = gNowNs + (uint64_t)W.ppsmcLatencyMs * 1000000ull;
    }
    if (W.ppsmcPending && gNowNs >= W.ppsmcDue) { W.ppsmcPending = false; ppsmc_handle(W.pMsg, W.pArg); }
}
extern "C" void dalshim_sleep(unsigned ms) { pthread_mutex_lock(&gTimeMu); gNowNs += (uint64_t)ms * 1000000ull; service(); pthread_mutex_unlock(&gTimeMu); }
extern "C" void clock_get_uptime(uint64_t *t) { pthread_mutex_lock(&gTimeMu); gNowNs += 1000ull; service(); *t = gNowNs; pthread_mutex_unlock(&gTimeMu); }
extern "C" void absolutetime_to_nanoseconds(uint64_t t, uint64_t *ns) { *ns = t; }
extern "C" thread_t current_thread(void) { return (thread_t)(uintptr_t)pthread_self(); }
extern "C" bool OSCompareAndSwap(UInt32 o, UInt32 n, volatile UInt32 *p) { return __sync_bool_compare_and_swap(p, o, n); }
extern "C" bool OSCompareAndSwapPtr(void *o, void *n, void *volatile *p) { return __sync_bool_compare_and_swap(p, o, n); }
extern "C" bool PE_parse_boot_argn(const char *name, void *out, int sz) {
    for (Arg &a : gArgs) if (std::strcmp(name, a.name) == 0) { if (!a.present || sz != 4) return false; std::memcpy(out, &a.val, 4); return true; }
    return false;
}
namespace amdgpu {
void n48_logf(const char *fmt, ...) { char b[2048]; va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap); gLog.push_back(b); }
const NativeS1bState &native_s1b_state() { return gS1b; }
}
namespace n48dcn {
uint32_t scanStatus(struct n48n_scan_status *o) { std::memset(o, 0, sizeof(*o)); return 0; }
bool modeTrialBusy() { return false; }
uint32_t scanQuery(struct n48n_scan_query *o) { std::memset(o, 0, sizeof(*o)); return 0; }
}
// the locked VRAM reader Navi48Bringup registers (navi48_vram_read_mm): fills the metrics table with the live boot's first sample
static bool fake_vram_reader(uint64_t, uint32_t *dst, uint32_t dwords) {
    W.vramReads++;
    if (dwords == 0u || dwords > 64u) return false;
    for (uint32_t i = 0; i < dwords; i++) dst[i] = 0u;
    return true;
}
static uint64_t now_ms() { return gNowNs / 1000000ull; }
static uint32_t did_for_khz(uint32_t khz) {   // the DID whose DFS clock on this PLL is exactly khz
    for (uint32_t d = 0x08; d < 0x80; d++) if (n48dal::did_khz(n48dal::vco_khz(W.pll), d) == khz) return d;
    return 0u;
}
static void world_reset(bool clocks562 = false) {
    W.~World(); new (&W) World();
    W.reg[kPResp] = 1u; W.reg[kDResp] = n48dal::kRespOk;   // both mailboxes: the previous message answered
    W.pll = 0x2d; W.did0 = W.did1 = 0x41;                  // 272.727 MHz (the GOP's, 0.0.606)
    if (clocks562) { const uint32_t d = did_for_khz(562500u); W.did0 = W.did1 = d; }
    sync_clocks();
    gDev.rmmio = W.reg; gDev.rmmioSize = sizeof(W.reg);
    gDev.ip.setBase(amdgpu::IPBlock::MP1, 1, 0x16200u);
    gDev.smuOnline = true;
    gDev.vramMcBase = 0x8000000000ull; gDev.vramBase = 8ull << 20; gDev.vramLimit = 256ull << 20;
    gS1b.gate = n48native::kGateOn; gS1b.positivePass = true;
    for (Arg &a : gArgs) { a.present = false; a.val = 0; }
    gLog.clear();
    amdgpu::smu_set_vram_reader(fake_vram_reader);
}
static bool scen(const char *name, void (*fn)()) {
    std::fflush(stdout);
    const pid_t p = fork();
    if (p == 0) { alarm(60); gFail = 0; gRun = 0; fn();   // a hang (e.g. the trace waiting behind a held lock) fails the scenario
                  std::printf("  %s: %d checks, %d failed\n", name, gRun, gFail); std::fflush(stdout); _exit(gFail ? 1 : 0); }
    int st = 0; waitpid(p, &st, 0);
    gRun++; if (!(WIFEXITED(st) && WEXITSTATUS(st) == 0)) { gFail++; std::printf("FAIL: scenario %s\n", name); return false; }
    return true;
}
static bool log_has(const char *needle) { for (auto &l : gLog) if (l.find(needle) != std::string::npos) return true; return false; }
static size_t count_dal(uint32_t msg) { size_t n = 0; for (auto &m : W.dalSeen) if (m.first == msg) n++; return n; }

// the AUTO UCLK pin mode (what smu_hw_init leaves on the live machine): smu_uclk_pin_result().verdict != kNotRun, the fallback allowed
static void uclk_auto() { const auto saved = W.ppsmcSeen.size(); (void)amdgpu::smu_pin_uclk_for_display(gDev); expect(W.ppsmcSeen.size() == saved, "(setup) AUTO sends nothing"); }

// =====================================================================================================================================
// P: the pure latch
// =====================================================================================================================================
static void p_pure() {
    using namespace n48smuh;
    Health h = initial();
    expect(h.state == kUnarmed && optional_ok(h) && dal_ok(h) && main_gate(h, false, ~0u) == kGo, "P unarmed: everything goes (the pre-0.0.685 path)");
    Health u = on_event(h, kEvMainTimeout, 5);
    expect(u.state == kUnarmed && u.mainTimeouts == 1u && main_gate(u, false, 0u) == kGo, "P unarmed: a timeout is counted, nothing latches, the next message still goes");
    h = on_event(h, kEvArm, 10);
    expect(h.state == kHealthy && h.sinceMs == 10u && optional_ok(h) && dal_ok(h), "P armed: healthy");
    expect(on_event(h, kEvArm, 20).sinceMs == 10u, "P a second arm changes nothing");
    Health d = on_event(h, kEvMainTimeout, 30);
    expect(d.state == kDegraded && d.reason == kRMainTimeout && d.mainPending && !optional_ok(d) && !dal_ok(d), "P healthy + PPSMC timeout -> DEGRADED");
    expect(main_gate(d, false, ~0u) == kRefuseLatched && main_gate(d, false, 1u) == kRefuseLatched, "P DEGRADED: every ordinary message refused");
    expect(main_gate(d, true, ~0u) == kNeedResp && main_gate(d, true, 0u) == kRefusePending && main_gate(d, true, 1u) == kGo, "P DEGRADED: the probe only after RESP != 0");
    expect(!recover_probe(d, 0u) && !recover_probe(d, ~0u) && recover_probe(d, 1u) && recover_probe(d, 0xFFu), "P recovery probes only once the pending message was answered");
    Health dp = d; dp.probes = kMaxProbes;
    expect(!recover_probe(dp, 1u), "P recovery probes are bounded per boot");
    Health r = on_event(d, kEvProbeOk, 40);
    expect(r.state == kHealthy && r.recoveries == 1u && !r.mainPending && r.reason == kRRecovered, "P DEGRADED + probe OK -> healthy (recovered)");
    Health s = on_event(h, kEvDalTimeout, 50);
    expect(s.state == kSuspect && s.dalOff && s.dalPending && !optional_ok(s) && !dal_ok(s) && main_gate(s, false, ~0u) == kRefuseLatched && main_gate(s, true, ~0u) == kGo,
           "P DAL timeout -> SUSPECT: only the probe may go, DAL off");
    Health s1 = on_event(s, kEvProbeOk, 60);
    expect(s1.state == kHealthy && s1.dalOff && !dal_ok(s1) && optional_ok(s1) && s1.reason == kRDalProbeOk, "P SUSPECT + probe OK -> healthy, DAL stays off for the boot");
    Health s2 = on_event(s, kEvProbeFail, 60);
    expect(s2.state == kDegraded && s2.reason == kRProbeFailed, "P SUSPECT + probe failed -> DEGRADED");
    Health pend = h; pend.mainPending = true;
    expect(main_gate(pend, false, ~0u) == kNeedResp && main_gate(pend, false, 0u) == kRefusePending && main_gate(pend, false, 1u) == kGo,
           "P healthy with our message pending: never written over while RESP is 0 (Linux's pre-poll)");
    expect(on_event(pend, kEvPendingSeen, 70).state == kDegraded, "P seeing it still pending latches DEGRADED");
    expect(on_event(pend, kEvMainOk, 70).mainPending == false, "P an answer clears the pending flag");
    // the trace's self-limit
    expect_u("P trace period 0 failures", trace_period_ms(0), 500u);
    expect_u("P trace period 1 failure", trace_period_ms(1), 500u);
    expect_u("P trace period 2", trace_period_ms(2), 5000u);
    expect_u("P trace period 3", trace_period_ms(3), 10000u);
    expect_u("P trace period 4", trace_period_ms(4), 20000u);
    expect_u("P trace period capped", trace_period_ms(40), 60000u);
    expect(!trace_should_stop(4) && trace_should_stop(5), "P the trace stops after 5 consecutive failures");
    expect(std::string(state_name(kDegraded)).find("DEGRADED") != std::string::npos, "P names");
}

// =====================================================================================================================================
// R: the 0.0.684 failure, reproduced on the 0.0.685 code
// =====================================================================================================================================
static void r_repro() {
    world_reset();
    gArgs[0].present = true; gArgs[0].val = 1;   // navi48-dalfloor=1: the 0.0.684 set, opted in
    W.wedgeOnDal = n48dalfloor::kMsgSetHardMinByFreq; W.wedgeOnDalParamClk = n48dalfloor::kClkDcfclk;
    uclk_auto();
    amdgpu::smu_health_arm();
    amdgpu::clktrace_start(now_ms());
    expect(amdgpu::clktrace_poll(gDev, now_ms(), 0, false) || true, "(trace first sample)");
    expect(W.vramReads == 2u, "T the metrics table is copied through the registered locked reader (64 + 1 dwords)");
    const size_t pBefore = W.ppsmcSeen.size();
    const uint64_t t0 = gNowNs;
    uint32_t dcf = 0;
    const uint32_t v = amdgpu::dal_floor_run(gDev, 2560, 1440, 2720, 1525, &dcf);
    const uint64_t took = (gNowNs - t0) / 1000000ull;
    expect_u("R verdict: DAL mailbox lost, stopped", v, n48dalfloor::kVMailbox);
    expect(W.wedged, "R the simulated PMFW wedged on SetHardMinByFreq(DCFCLK) as on the live boot");
    expect(W.ppsmcSeen.size() == pBefore + 1u && W.ppsmcSeen[pBefore].first == 0x02, "R the PPSMC readiness probe (GetSmuVersion) went out before the first DAL message");
    expect(count_dal(n48dalfloor::kMsgNumOfDisplays) == 1u && count_dal(n48dalfloor::kMsgSetHardMinByFreq) == 1u, "R NumOfDisplays and the DCFCLK hard minimum went out (the 0.0.684 order)");
    expect(count_dal(n48dalfloor::kMsgSetMinDeepSleepDcfclk) == 0u, "R nothing after the unanswered message: no deep-sleep floor, no DISPCLK/DPPCLK");
    expect(W.dalWrites >= 1u && W.reg[kDMsg] == n48dalfloor::kMsgReturnHardMinStatus, "R the unanswered DAL message is ReturnHardMinStatus (still in the mailbox)");
    expect(W.reg[kPMsg] == 0x02u && W.reg[kPResp] == 0u, "R after the DAL timeout ONE PPSMC probe (GetSmuVersion) was written and is unanswered");
    expect(!amdgpu::smu_optional_ok() && !amdgpu::smu_dal_allowed(), "R the latch is DEGRADED: optional traffic and DAL stopped");
    expect(took >= 4000u && took < 4300u, "R the whole run took one DAL timeout + one PPSMC probe timeout (about 4 s), not more");
    expect(log_has("SMU-HEALTH: *** DEGRADED") && log_has("*** DAL TIMEOUT"), "R logged loudly");
    char desc[600]; amdgpu::smu_health_describe(desc, sizeof desc);
    expect(std::string(desc).find("DEGRADED") != std::string::npos && std::string(desc).find("PPSMC timeouts 1, DAL timeouts 1") != std::string::npos, "R Navi48,SmuHealth says DEGRADED with the counts");
    // From here on: nothing written on either mailbox, and nothing waits.
    const uint32_t pw = W.ppsmcWrites, dw = W.dalWrites;
    uint64_t a = gNowNs;
    for (int i = 0; i < 400; i++) { (void)amdgpu::clktrace_poll(gDev, now_ms(), (uint64_t)(i % 7 == 0), false); dalshim_sleep(50); }
    const uint64_t traceMs = (gNowNs - a) / 1000000ull;
    expect(traceMs < 400u * 50u + 100u, "R 20 s of monitor polls cost no SMU wait at all");
    char t[1600]; amdgpu::clktrace_describe(t, sizeof t);
    expect(std::string(t).find("STOPPED (SMU degraded)") == 0, "R the trace is stopped (Navi48,DisplayClocks says why)");
    a = gNowNs;
    expect(amdgpu::smu_uclk_display_pin(gDev, true, n48uclk::kWhyUnderflow) == kIOReturnNotReady, "R the UCLK fallback pin is refused");
    uint32_t out = 7;
    expect(amdgpu::smu_send_msg_with_param(gDev, 0x03, 0, &out) == kIOReturnNotReady && out == 0u, "R a PPSMC message (user client) is refused at once");
    amdgpu::SmuMetricsResult mr{};
    expect(amdgpu::smu_read_metrics(gDev, &mr) == kIOReturnNotReady, "R metrics (doMetrics / telemetry) refused at once");
    expect(amdgpu::smu_set_power_state(gDev, amdgpu::SMUPowerState::Low) != kIOReturnSuccess, "R a power state (thermal clamp / doPowerState) is refused");
    amdgpu::DalMsg dm{};
    expect(amdgpu::smu_dal_send(gDev, n48dalfloor::kMsgGetSmuVersion, 0, &dm, [](uint32_t, uint32_t) -> uint32_t { return 0u; }) == kIOReturnNotReady && dm.refuse != 0u,
           "R the DAL sender refuses (nothing sent)");
    expect((gNowNs - a) / 1000000ull < 2u, "R every refusal returns in under 1 ms (no 2 s timeout anywhere)");
    expect(W.ppsmcWrites == pw && W.dalWrites == dw && W.reg[kPMsg] == 0x02u, "R NO register write on either mailbox after DEGRADED; the pending probe is never written over");
    expect(amdgpu::dal_floor_run(gDev, 2560, 1440, 2720, 1525, &dcf) == n48dalfloor::kVMailbox && W.dalWrites == dw, "R the floors never run twice");
    // passive recovery: while the PMFW stays wedged, only reads
    for (int i = 0; i < 6; i++) { amdgpu::smu_health_poll(gDev, now_ms()); dalshim_sleep(10000); }
    expect(W.ppsmcWrites == pw && !amdgpu::smu_optional_ok(), "R recovery polls while wedged: read RESP only, nothing sent");
    // the PMFW comes back: it answers the pending probe; the next poll sends ONE probe and the latch is healthy (DAL stays off, the trace stays stopped)
    W.wedged = false; dalshim_sleep(1);
    expect(W.reg[kPResp] == 1u, "(the pending probe answered)");
    dalshim_sleep(10000);
    amdgpu::smu_health_poll(gDev, now_ms());
    expect(amdgpu::smu_optional_ok() && !amdgpu::smu_dal_allowed(), "R recovered after the PMFW answered: optional traffic allowed, DAL off for the boot");
    expect(W.ppsmcWrites == pw + 1u, "R exactly one recovery probe");
    expect(amdgpu::smu_send_msg_with_param(gDev, 0x03, 0, &out) == kIOReturnSuccess && out == 0x33u, "R PPSMC messages work again");
    expect(amdgpu::clktrace_poll(gDev, now_ms(), 0, false) == false, "R the trace stays stopped for the boot");
}

// The live 0.0.684 run as it was (default 0x0F parts) but with the PMFW dead from the DAL timeout: an unarmed boot would have kept going; check the
// clock trace alone also stops after ONE timeout when the PMFW is dead before the floors.
static void t_dead_trace() {
    world_reset();
    uclk_auto();
    amdgpu::smu_health_arm();
    W.wedged = true;   // the PMFW answers nothing
    amdgpu::clktrace_start(now_ms());
    const uint64_t a = gNowNs;
    for (int i = 0; i < 1200; i++) { (void)amdgpu::clktrace_poll(gDev, now_ms(), 0, false); dalshim_sleep(50); }
    expect_u("T dead PMFW: exactly one PPSMC write (the first sample's GetDriverIfVersion)", W.ppsmcWrites, 1u);
    expect(!amdgpu::smu_optional_ok(), "T dead PMFW: one timeout latches DEGRADED");
    expect((gNowNs - a) / 1000000ull < 1200u * 50u + 2100u, "T dead PMFW: one 2 s wait in 60 s of polls (0.0.684: one per sample)");
    char t[1600]; amdgpu::clktrace_describe(t, sizeof t);
    expect(std::string(t).find("STOPPED (SMU degraded)") == 0, "T the trace says it stopped");
}

// Error replies (a live PMFW refusing the table transfer): back off and stop after 5; the SMU stays healthy.
static void t_backoff() {
    world_reset();
    uclk_auto();
    amdgpu::smu_health_arm();
    W.ppsmcFailMsg = 0x12; W.ppsmcFailResp = 0xFF;   // TransferTableSmu2Dram -> Failed
    amdgpu::clktrace_start(now_ms());
    std::vector<uint64_t> at;
    size_t seen = 0;
    for (int i = 0; i < 2400; i++) {   // 120 s
        (void)amdgpu::clktrace_poll(gDev, now_ms(), 0, false);
        size_t n = 0; for (auto &m : W.ppsmcSeen) if (m.first == 0x12) n++;
        if (n != seen) { seen = n; at.push_back(now_ms()); }
        dalshim_sleep(50);
    }
    expect_u("T error replies: 5 attempts, then stopped", at.size(), 5u);
    if (at.size() == 5u) {
        const uint64_t d1 = at[1] - at[0], d2 = at[2] - at[1], d3 = at[3] - at[2], d4 = at[4] - at[3];
        expect(d1 >= 500 && d1 < 600 && d2 >= 5000 && d2 < 5100 && d3 >= 10000 && d3 < 10100 && d4 >= 20000 && d4 < 20100, "T back-off 0.5 s, 5 s, 10 s, 20 s");
    }
    expect(amdgpu::smu_optional_ok(), "T error replies do not latch DEGRADED (the PMFW answers)");
    char t[1600]; amdgpu::clktrace_describe(t, sizeof t);
    expect(std::string(t).find("STOPPED (consecutive metrics failures)") == 0 && std::string(t).find("consecutive 5 (max 5") != std::string::npos, "T the counters are published");
}

// A busy lock (another thread in the middle of a message): the trace skips, never waits, counts no failure.
static volatile int gHold = 0, gHeld = 0;
static void *holder(void *) { amdgpu::SmuSeq s; gHeld = 1; while (gHold) usleep(100); gHeld = 0; return nullptr; }
static void t_busy() {
    world_reset();
    uclk_auto();
    amdgpu::smu_health_arm();
    amdgpu::clktrace_start(now_ms());
    gHold = 1; pthread_t th; pthread_create(&th, nullptr, holder, nullptr);
    while (!gHeld) usleep(100);
    const size_t before = W.ppsmcSeen.size();
    for (int i = 0; i < 40; i++) { (void)amdgpu::clktrace_poll(gDev, now_ms(), 0, false); dalshim_sleep(50); }
    expect(W.ppsmcSeen.size() == before, "T busy lock: no message, no wait");
    char t[1600]; amdgpu::clktrace_describe(t, sizeof t);
    expect(std::string(t).find("busy skips") != std::string::npos && std::string(t).find("0 failed") != std::string::npos && std::string(t).find("busy skips 0") == std::string::npos,
           "T busy lock: skips counted, no failure");
    gHold = 0; pthread_join(th, nullptr);
    for (int i = 0; i < 20; i++) { (void)amdgpu::clktrace_poll(gDev, now_ms(), 0, false); dalshim_sleep(50); }
    expect(W.ppsmcSeen.size() > before, "T lock free again: sampling resumes");
}

// =====================================================================================================================================
// D: the floors' defaults and preconditions
// =====================================================================================================================================
static void d_default_off() {
    world_reset();
    uclk_auto();
    amdgpu::smu_health_arm();
    uint32_t dcf = 0;
    expect_u("D absent navi48-dalfloor: OFF", amdgpu::dal_floor_run(gDev, 2560, 1440, 2720, 1525, &dcf), n48dalfloor::kVOff);
    expect(W.dalSeen.empty() && W.ppsmcSeen.empty() && W.dalWrites == 0u, "D default: nothing sent on either mailbox");
}
static void d_clocks562() {
    world_reset(true);
    gArgs[0].present = true; gArgs[0].val = 1;
    uclk_auto();
    amdgpu::smu_health_arm();
    uint32_t dcf = 0;
    expect_u("D DISPCLK/DPPCLK 562.5 MHz (the live readback): nothing sent", amdgpu::dal_floor_run(gDev, 2560, 1440, 2720, 1525, &dcf), n48dalfloor::kVAssume);
    expect(W.dalSeen.empty() && W.ppsmcSeen.empty(), "D 562.5 MHz: nothing sent on either mailbox");
    expect(log_has("562500 / 562500 kHz"), "D the log names the live clocks");
}
static void d_unhealthy() {
    world_reset();
    gArgs[0].present = true; gArgs[0].val = 1;
    uclk_auto();
    amdgpu::smu_health_arm();
    amdgpu::smu_health_dal_timeout();   // an earlier DAL timeout this boot (then the probe would follow; here only the latch)
    uint32_t dcf = 0;
    expect_u("D after a DAL timeout this boot: nothing sent", amdgpu::dal_floor_run(gDev, 2560, 1440, 2720, 1525, &dcf), n48dalfloor::kVUnhealthy);
    expect(W.dalSeen.empty(), "D unhealthy: no DAL message");
}
static void d_healthy() {
    world_reset();
    gArgs[0].present = true; gArgs[0].val = 1;
    uclk_auto();
    amdgpu::smu_health_arm();
    const int locks0 = gDalShimLockCount;
    uint32_t dcf = 0;
    const uint32_t v = amdgpu::dal_floor_run(gDev, 2560, 1440, 2720, 1525, &dcf);
    expect_u("D healthy PMFW, clocks as assumed, opted in: sent", v, n48dalfloor::kVSent);
    expect_u("D the DCFCLK floor", dcf, 147u);
    expect(W.ppsmcSeen.size() == 2u && W.ppsmcSeen[0].first == 0x02 && W.ppsmcSeen[1].first == 0x02, "D exactly two PPSMC messages: the readiness probe and the post-check");
    expect(count_dal(n48dalfloor::kMsgNumOfDisplays) == 1u && count_dal(n48dalfloor::kMsgSetHardMinByFreq) == 3u && count_dal(n48dalfloor::kMsgSetMinDeepSleepDcfclk) == 1u,
           "D the plan: NumOfDisplays, DCFCLK, deep sleep, DISPCLK, DPPCLK");
    expect_u("D the whole sequence took the shared lock ONCE (the per-message takes are recursive)", (uint64_t)(gDalShimLockCount - locks0), 1u);
    expect(amdgpu::smu_optional_ok() && amdgpu::smu_dal_allowed(), "D still healthy afterwards");
}

// =====================================================================================================================================
// U: unarmed = the pre-0.0.685 path
// =====================================================================================================================================
static void u_unarmed() {
    world_reset();
    W.wedged = true;
    uint32_t out = 0;
    expect(amdgpu::smu_send_msg_with_param(gDev, 0x02, 0, &out) == kIOReturnTimeout, "U unarmed: a timeout");
    W.wedged = false;
    expect(amdgpu::smu_send_msg_with_param(gDev, 0x03, 0, &out) == kIOReturnSuccess && out == 0x33u, "U unarmed: the next message is still sent (no latch before the monitor arms)");
    expect(amdgpu::smu_optional_ok(), "U unarmed: optional traffic not stopped");
    // armed, a slow PMFW (answers after 3 s): the latch trips, then a send is refused without a write while RESP is 0, and recovery works
    amdgpu::smu_health_arm();
    W.ppsmcLatencyMs = 3000;
    expect(amdgpu::smu_send_msg_with_param(gDev, 0x02, 0, &out) == kIOReturnTimeout && !amdgpu::smu_optional_ok(), "U armed: a 3 s answer is a timeout -> DEGRADED");
    const uint32_t pw = W.ppsmcWrites;
    expect(amdgpu::smu_send_msg_with_param(gDev, 0x03, 0, &out) == kIOReturnNotReady && W.ppsmcWrites == pw, "U DEGRADED: refused, nothing written");
    dalshim_sleep(1500);   // the slow answer lands
    W.ppsmcLatencyMs = 0;
    amdgpu::smu_health_poll(gDev, now_ms());
    expect(amdgpu::smu_optional_ok(), "U the slow PMFW answered: the recovery probe restores healthy");
}

int main() {
    p_pure();
    scen("R the 0.0.684 failure reproduced", r_repro);
    scen("T dead PMFW, trace only", t_dead_trace);
    scen("T error replies back off", t_backoff);
    scen("T busy lock", t_busy);
    scen("D default off", d_default_off);
    scen("D clocks 562.5 MHz", d_clocks562);
    scen("D unhealthy", d_unhealthy);
    scen("D healthy run", d_healthy);
    scen("U unarmed / slow PMFW", u_unarmed);
    std::printf("%s: smuhealth685_test: %d checks, %d failed\n", gFail ? "FAIL" : "PASS", gRun, gFail);
    return gFail ? 1 : 0;
}
