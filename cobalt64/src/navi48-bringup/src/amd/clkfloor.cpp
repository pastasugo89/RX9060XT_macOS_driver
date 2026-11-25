//
//  clkfloor.cpp - build 0.0.684: the display clock floors (DALSMC, as Linux's dcn401 clk_mgr) and the boot clock trace. See clkfloor.h;
//  every decision is in clkfloor_pure.h (host-tested by tests/dalfloor685_test.cpp, which also pins this file's shape).
//  0.0.685 (after 0.0.684 wedged the PMFW on the live boot): the floors are OFF by default; opted in, they need a healthy SMU, the live DISPCLK/DPPCLK
//  the floors were computed for and a PPSMC readiness probe, run under the shared mailbox lock, stop at the first unanswered message and probe the PPSMC
//  mailbox afterwards. The trace never waits for the lock, backs off after failures and stops for the boot (smu_health_pure.h).
//
//  What this file WRITES: the three DAL mailbox dwords, through smu_dal_send with the floor allowlist only (n48dalfloor::allow decides every message)
//  (fsend below is the single entry). Everything else is read-only: the DFS / PLL readback of DISPCLK / DPPCLK (CLK0 registers), and the PMFW
//  metrics table (smu_read_metrics, under the shared mailbox lock, as the user client's `metrics` does).
//
#include <string.h>
#include <IOKit/IOLib.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>

#include "clkfloor.h"
#include "clkfloor_pure.h"
#include "smu_dal.h"
#include "smu_dal_pure.h"
#include "amdgpu_smu.h"
#include "amdgpu_log.h"
#include "smu_health_pure.h"   // 0.0.685: the clock trace's self-limit

#define FLOOR_LOG(fmt, ...) AMDGPU_LOG("dalfloor", fmt, ##__VA_ARGS__)
#define TRACE_LOG(fmt, ...) AMDGPU_LOG("clktrace", fmt, ##__VA_ARGS__)

namespace amdgpu {

using namespace n48dalfloor;

namespace {
struct StepRes { uint32_t msg, param, rc, resp, arg, us, refuse, statusUs, status; bool statusDone; };
struct FloorState {
    bool ran;
    uint32_t verdict, parts, bootArg;
    bool bootArgPresent;
    uint32_t smuVer, ifVer, hdrVer;
    Levels dcf, uclk;
    bool dcfOk, uclkOk;
    n48dal::Decoded before, after, fixed;
    Plan plan;
    StepRes steps[kMaxSteps];
    uint32_t nSteps, nOk;
    uint32_t corrective;          // 0 none; 1 a display clock fell and was raised back; 2 the raise did not verify
    uint64_t atMs, tookMs;
    uint32_t dcfFloorMhz;
    uint32_t hActive, vActive, hTotal, vTotal;
};
FloorState gF;

uint64_t now_ms() {
    uint64_t t = 0, ns = 0;
    clock_get_uptime(&t);
    absolutetime_to_nanoseconds(t, &ns);
    return ns / 1000000ull;
}
uint64_t now_us() {
    uint64_t t = 0, ns = 0;
    clock_get_uptime(&t);
    absolutetime_to_nanoseconds(t, &ns);
    return ns / 1000ull;
}
uint32_t us32(uint64_t v) { return v > 0xFFFFFFFFull ? 0xFFFFFFFFu : (uint32_t)v; }

// The DISPCLK / DPPCLK readback (read-only): CLK0 PLL_REQ, the two DFS DIDs, DENTIST. Unreadable (outside the mapping) = all-ones = not ok.
n48dal::Decoded read_clocks(const DeviceContext &dev) {
    return n48dal::decode_clocks(RREG32(dev, n48dal::kRegPllReq), RREG32(dev, n48dal::kRegDfs0), RREG32(dev, n48dal::kRegDfs1), RREG32(dev, n48dal::kRegDentist));
}
bool clocks_usable(const n48dal::Decoded &d) { return d.ok && d.dentAgree && d.chgDone; }

Limits limits() { return Limits{ gF.dcfOk ? levels_min(gF.dcf) : 0u, gF.dcfOk ? levels_max(gF.dcf) : 0u, gF.uclkOk ? levels_min(gF.uclk) : 0u }; }

// The floor allowlist as the shared sender's floorAllow hook (it runs first in smu_dal_send, before the lock and any register access).
uint32_t floor_allow(uint32_t msg, uint32_t param) {
    const uint32_t why = allow(gF.parts, msg, param, limits());
    if (why != kAllow) FLOOR_LOG("REFUSED msg=0x%02x param=0x%08x: %s (nothing sent)", msg, param, refuse_name(why));
    return why == kAllow ? 0u : 0x100u | why;
}
// THE ONLY SENDER OF THIS FILE: the shared DAL sender (BAR5 bounds, the shared lock, RESP != 0 before, <= 2 s wait) with the floor allowlist.
kern_return_t fsend(const DeviceContext &dev, uint32_t msg, uint32_t param, DalMsg *m) {
    return smu_dal_send(dev, msg, param, m, floor_allow);
}
// A reply that says the mailbox itself is unhealthy (no answer, RESP 0 before the send, no device, no lock): stop everything after it.
bool mailbox_lost(const DalMsg &m) {
    return m.rc == (uint32_t)kIOReturnTimeout || m.rc == (uint32_t)kIOReturnNotReady || m.rc == (uint32_t)kIOReturnNoDevice || m.rc == (uint32_t)kIOReturnNoResources;
}

// ReturnHardMinStatus until bit (1 << clk), every 1 ms, <= 1 s (dcn401_smu_wait_hard_min_status). Returns true when done; *lost on a mailbox failure.
bool wait_hard_min(const DeviceContext &dev, uint32_t clk, StepRes &r, bool *lost) {
    const uint64_t t0 = now_us();
    for (;;) {
        DalMsg m;
        const kern_return_t kr = fsend(dev, kMsgReturnHardMinStatus, 0u, &m);
        if (kr == kIOReturnSuccess) { r.status = m.arg; if ((m.arg & (1u << clk)) != 0u) { r.statusUs = us32(now_us() - t0); return true; } }
        else if (mailbox_lost(m) || m.refuse != 0u) { *lost = mailbox_lost(m); r.statusUs = us32(now_us() - t0); return false; }
        if (now_us() - t0 >= 1000000ull) { r.statusUs = us32(now_us() - t0); return false; }
        IOSleep(1);
    }
}

// GetDpmFreqByIndex(clk, 0xFF), then each level (dcn401_init_single_clock).
bool query_levels(const DeviceContext &dev, uint32_t clk, Levels &l, bool *lost) {
    l = Levels{};
    DalMsg m;
    if (fsend(dev, kMsgGetDpmFreqByIndex, (clk << 16) | kIndexAll, &m) != kIOReturnSuccess) { *lost = mailbox_lost(m); return false; }
    const uint32_t n = level_count(m.arg);
    if (n == 0u || n > kMaxLevels) { FLOOR_LOG("clk %u: level-count reply 0x%08x (%u levels) is unusable", clk, m.arg, n); return false; }
    for (uint32_t i = 0; i < n; i++) {
        if (fsend(dev, kMsgGetDpmFreqByIndex, (clk << 16) | i, &m) != kIOReturnSuccess) { *lost = mailbox_lost(m); return false; }
        l.mhz[i] = level_mhz(m.arg);
    }
    l.n = n;
    FLOOR_LOG("clk %u: %u levels (%s): %u %u %u %u %u %u %u %u MHz", clk, n, (m.arg & 0x80000000u) ? "fine-grained" : "discrete",
              l.mhz[0], l.mhz[1], l.mhz[2], l.mhz[3], l.mhz[4], l.mhz[5], l.mhz[6], l.mhz[7]);
    return true;
}

// One planned step: send, record, and for a hard minimum wait for its status bit. Returns false when the mailbox is lost.
bool run_step(const DeviceContext &dev, const Step &s, StepRes &r) {
    DalMsg m;
    const kern_return_t kr = fsend(dev, s.msg, s.param, &m);
    r = StepRes{ s.msg, s.param, m.rc, m.resp, m.arg, m.us, m.refuse, 0u, 0u, false };
    if (kr != kIOReturnSuccess) return !mailbox_lost(m);
    if (s.hardMin) {
        bool lost = false;
        r.statusDone = wait_hard_min(dev, s.clk, r, &lost);
        if (lost) return false;
        if (!r.statusDone) FLOOR_LOG("hard minimum clk %u = %u MHz: ReturnHardMinStatus did not report it done in %u us (status 0x%x)", s.clk, s.param & 0xFFFFu, r.statusUs, r.status);
    }
    return true;
}
bool step_ok(const StepRes &r) { return r.rc == (uint32_t)kIOReturnSuccess && r.refuse == 0u && (r.msg != kMsgSetHardMinByFreq || r.statusDone); }
const char *msg_name(uint32_t msg) {
    return msg == kMsgNumOfDisplays ? "NumOfDisplays" : msg == kMsgSetHardMinByFreq ? "SetHardMinByFreq" : msg == kMsgSetMinDeepSleepDcfclk ? "SetMinDeepSleepDcfclk" :
           msg == kMsgSetUclkPstateAllow ? "SetUclkPstateAllow" : "?";
}
}  // namespace

uint32_t dal_floor_run(const DeviceContext &dev, uint32_t hActive, uint32_t vActive, uint32_t hTotal, uint32_t vTotal, uint32_t *dcfFloorMhz) {
    if (dcfFloorMhz != nullptr) *dcfFloorMhz = 0u;
    if (gF.ran) { if (dcfFloorMhz != nullptr) *dcfFloorMhz = gF.dcfFloorMhz; return gF.verdict; }
    gF = FloorState{};
    gF.ran = true;
    gF.atMs = now_ms();
    uint32_t v = 0;
    gF.bootArgPresent = PE_parse_boot_argn("navi48-dalfloor", &v, sizeof(v));
    gF.bootArg = v;
    gF.parts = parts_of(gF.bootArgPresent, v);
    if (gF.parts == 0u) {
        gF.verdict = kVOff;
        FLOOR_LOG("display clock floors OFF (0.0.685 default; navi48-dalfloor=1 opts in): nothing sent");
        return gF.verdict;
    }
    gF.hActive = hActive; gF.vActive = vActive; gF.hTotal = hTotal; gF.vTotal = vTotal;
    if (!mode_matches(kMode1440p120, hActive, vActive, hTotal, vTotal)) {
        gF.verdict = kVMode;
        FLOOR_LOG("display clock floors: OTG0 timing %ux%u H_TOTAL %u V_TOTAL %u is not the mode the floors are computed for: nothing sent", hActive, vActive, hTotal, vTotal);
        return gF.verdict;
    }
    if (smu_uclk_pin_result().verdict == n48uclk::kNotRun) {
        gF.verdict = kVNoSmu;
        FLOOR_LOG("display clock floors: the SMU features were not enabled by this boot: nothing sent");
        return gF.verdict;
    }
    // 0.0.685: the clock state the floors were computed for (DISPCLK / DPPCLK 272.727 MHz). 0.0.684's live boot read 562.5 / 562.5: nothing is sent then.
    gF.before = read_clocks(dev);
    if (!clocks_usable(gF.before) || !clocks_match_assumption(gF.before.dispKhz, gF.before.dppKhz)) {
        gF.verdict = kVAssume;
        FLOOR_LOG("display clock floors: DISPCLK/DPPCLK read %u / %u kHz (%s), not the %u kHz the floors were computed for: nothing sent",
                  gF.before.dispKhz, gF.before.dppKhz, clocks_usable(gF.before) ? "usable" : "UNUSABLE readback", kAssumedDispKhz);
        return gF.verdict;
    }
    // 0.0.685: the SMU must be healthy and the DAL mailbox allowed (no earlier timeout this boot).
    if (!smu_optional_ok() || !smu_dal_allowed()) {
        gF.verdict = kVUnhealthy;
        FLOOR_LOG("display clock floors: the SMU health latch does not allow it (optional traffic %s, DAL %s): nothing sent",
                  smu_optional_ok() ? "ok" : "stopped", smu_dal_allowed() ? "allowed" : "off");
        return gF.verdict;
    }
    if (!dal_owner_claim_floor()) {
        gF.verdict = kVBusy;
        FLOOR_LOG("display clock floors: the DAL mailbox is owned by a DAL step or a clock hold: nothing sent");
        return gF.verdict;
    }
    FLOOR_LOG("display clock floors: parts 0x%02x (navi48-dalfloor=%u), as Linux dcn401_update_clocks for one 2560x1440@120 plane", gF.parts, v);
    bool lost = false;
    DalMsg m;
    {
    // 0.0.685: the WHOLE sequence under the shared mailbox lock (recursive: each message takes it again), so no PPSMC message (metrics, the UCLK
    // fallback, a user client) runs between two DAL messages; the sequence stops at its first unanswered message (smu_dal_send then turns the DAL
    // mailbox off and probes the PPSMC mailbox once), so the lock is never held past one 2 s timeout plus that probe.
    SmuSeq seq;
    if (!seq.held) { gF.verdict = kVBusy; goto out; }
    // 0.0.685: the readiness probe: the PPSMC mailbox must answer GetSmuVersion before the first DAL message.
    if (smu_health_probe(dev) != kIOReturnSuccess) {
        gF.verdict = kVUnhealthy;
        FLOOR_LOG("display clock floors: the PPSMC readiness probe failed: nothing sent on the DAL mailbox");
        goto out;
    }
    // dcn401_init_clocks: the SMU is present when GetSmuVersion answers; the two version checks are logged (Linux goes on either way) but the
    // header version must be DALSMC_VERSION here, or the message ids below may not mean what dalsmc.h says.
    if (fsend(dev, kMsgGetSmuVersion, 0u, &m) != kIOReturnSuccess) { gF.verdict = kVMailbox; goto out; }
    gF.smuVer = m.arg;
    if (fsend(dev, kMsgGetDriverIfVersion, 0u, &m) != kIOReturnSuccess && mailbox_lost(m)) { gF.verdict = kVMailbox; goto out; }
    gF.ifVer = m.arg;
    if (fsend(dev, kMsgGetMsgHeaderVersion, 0u, &m) != kIOReturnSuccess) { gF.verdict = mailbox_lost(m) ? kVMailbox : kVHeader; goto out; }
    gF.hdrVer = m.arg;
    if (gF.hdrVer != kDalsmcVersion) { gF.verdict = kVHeader; goto out; }
    if (gF.parts & kPartDcfclk) { gF.dcfOk = query_levels(dev, kClkDcfclk, gF.dcf, &lost); if (lost) { gF.verdict = kVMailbox; goto out; } }
    if (gF.parts & kPartUclk) { gF.uclkOk = query_levels(dev, kClkUclk, gF.uclk, &lost); if (lost) { gF.verdict = kVMailbox; goto out; } }
    {
        PlanIn in{};
        in.parts = gF.parts;
        in.dcf = gF.dcfOk ? gF.dcf : Levels{};
        in.uclk = gF.uclkOk ? gF.uclk : Levels{};
        in.curDispKhz = clocks_usable(gF.before) ? gF.before.dispKhz : 0u;
        in.curDppKhz = clocks_usable(gF.before) ? gF.before.dppKhz : 0u;
        in.smuVer = gF.smuVer;
        in.mode = kMode1440p120;
        // The DFS VCO: the PLL readback when it is the bounding box's 4500 MHz within 1 %, else the bounding box value.
        in.vcoKhz = (gF.before.ok && gF.before.vcoKhz >= 4455000u && gF.before.vcoKhz <= 4545000u) ? gF.before.vcoKhz : kDfsVcoKhz;
        gF.plan = make_plan(in);
        if (!plan_allowed(gF.plan, gF.parts, limits())) { gF.verdict = kVRefused; goto out; }
        FLOOR_LOG("plan: %u messages; DML for 497.75 MHz ODM 2:1: DISPCLK %u kHz, DPPCLK %u kHz, DCFCLK need %u kHz, deep sleep %u kHz; requests: DCFCLK %u, deep sleep %u, "
                  "UCLK %u, DISPCLK %u, DPPCLK %u MHz (running %u / %u kHz); parts not planned 0x%02x",
                  gF.plan.n, gF.plan.dmlDispKhz, gF.plan.dmlDppKhz, gF.plan.dcfNeedKhz, gF.plan.deepSleepKhz, gF.plan.dcfMhz, gF.plan.deepSleepMhz,
                  gF.plan.uclkMhz, gF.plan.dispMhz, gF.plan.dppMhz, in.curDispKhz, in.curDppKhz, gF.plan.skipped);
        for (uint32_t i = 0; i < gF.plan.n; i++) {
            const bool alive = run_step(dev, gF.plan.s[i], gF.steps[i]);
            gF.nSteps = i + 1u;
            if (step_ok(gF.steps[i])) gF.nOk++;
            if (gF.plan.s[i].clk == kClkDcfclk && step_ok(gF.steps[i])) gF.dcfFloorMhz = gF.plan.dcfMhz;
            if (!alive) { gF.verdict = kVMailbox; goto out; }
        }
        gF.verdict = (gF.nOk == gF.plan.n && gF.plan.skipped == 0u) ? kVSent : kVPartial;
        // The display clocks must still read at least their start (a floor equal to the running clock keeps it). If one fell, raise it back:
        // ceil(start MHz) is the smallest request whose DFS clock is at or above the start.
        if ((gF.parts & kPartDispDpp) && gF.plan.dispMhz != 0u) {
            IOSleep(20);
            gF.after = read_clocks(dev);
            if (!clocks_kept(gF.before.dispKhz, gF.before.dppKhz, gF.after.ok ? gF.after.dispKhz : 0u, gF.after.ok ? gF.after.dppKhz : 0u)) {
                FLOOR_LOG("DISPCLK/DPPCLK read %u / %u kHz after the floors, below the start %u / %u kHz: raising back", gF.after.dispKhz, gF.after.dppKhz,
                          gF.before.dispKhz, gF.before.dppKhz);
                const Step fix[2] = { { kMsgSetHardMinByFreq, param_hardmin(kClkDispclk, ceil_div(gF.before.dispKhz, 1000u)), kClkDispclk, true },
                                      { kMsgSetHardMinByFreq, param_hardmin(kClkDppclk, ceil_div(gF.before.dppKhz, 1000u)), kClkDppclk, true } };
                StepRes fr{};
                for (uint32_t k = 0; k < 2u; k++) (void)run_step(dev, fix[k], fr);
                IOSleep(20);
                gF.fixed = read_clocks(dev);
                gF.corrective = clocks_kept(gF.before.dispKhz, gF.before.dppKhz, gF.fixed.ok ? gF.fixed.dispKhz : 0u, gF.fixed.ok ? gF.fixed.dppKhz : 0u) ? 1u : 2u;
                gF.verdict = kVDropped;
            }
        }
    }
    // 0.0.685: the post-check: the PMFW must still answer the PPSMC mailbox after the floors (0.0.684's live boot: it did not).
    if (smu_health_probe(dev) != kIOReturnSuccess) {
        gF.verdict = kVPostFail;
        FLOOR_LOG("*** display clock floors: the PMFW stopped answering after the floors: SMU DEGRADED, all SMU traffic stopped ***");
    }
    }
out:
    dal_owner_release_floor();
    gF.tookMs = now_ms() - gF.atMs;
    if (dcfFloorMhz != nullptr) *dcfFloorMhz = gF.dcfFloorMhz;
    FLOOR_LOG("display clock floors: %s; DALSMC smu 0x%08x if 0x%x header %u; %u of %u messages OK; DISPCLK/DPPCLK %u / %u kHz before, %u / %u after%s; %llu ms; SMU %s",
              verdict_name(gF.verdict), gF.smuVer, gF.ifVer, gF.hdrVer, gF.nOk, gF.plan.n, gF.before.dispKhz, gF.before.dppKhz, gF.after.dispKhz, gF.after.dppKhz,
              gF.corrective == 1u ? " (fell, raised back)" : gF.corrective == 2u ? " (fell, the raise did NOT verify)" : "", (unsigned long long)gF.tookMs,
              smu_optional_ok() ? "healthy" : "DEGRADED (no SMU message is sent any more)");
    return gF.verdict;
}

void dal_floor_describe(char *t, size_t n) {
    if (t == nullptr || n == 0u) return;
    if (!gF.ran) { snprintf(t, n, "not run yet (sent once, after the display arbitration)"); return; }
    size_t o = (size_t)snprintf(t, n, "%s; parts 0x%02x (navi48-dalfloor %s); DALSMC smu 0x%08x if 0x%x header %u; DCFCLK levels %u (%u..%u MHz); "
                               "OTG0 %ux%u total %ux%u; DML: DISPCLK %u kHz, DPPCLK %u kHz, DCFCLK need %u kHz, deep sleep %u kHz; steps:",
                               verdict_name(gF.verdict), gF.parts, gF.bootArgPresent ? "set" : "absent", gF.smuVer, gF.ifVer, gF.hdrVer, gF.dcf.n,
                               levels_min(gF.dcf), levels_max(gF.dcf), gF.hActive, gF.vActive, gF.hTotal, gF.vTotal, gF.plan.dmlDispKhz, gF.plan.dmlDppKhz, gF.plan.dcfNeedKhz, gF.plan.deepSleepKhz);
    for (uint32_t i = 0; i < gF.nSteps && o < n; i++) {
        const StepRes &r = gF.steps[i];
        o += (size_t)snprintf(t + o, n - o, " %s(%#x)=%s%s", msg_name(r.msg), r.param, r.refuse ? "refused" : n48dal::resp_name(r.resp),
                              r.msg == kMsgSetHardMinByFreq ? (r.statusDone ? "+done" : "+not-done") : "");
    }
    if (o < n) snprintf(t + o, n - o, "; DISPCLK/DPPCLK kHz before %u/%u after %u/%u%s; at uptime %llu ms, %llu ms",
                        gF.before.dispKhz, gF.before.dppKhz, gF.after.dispKhz, gF.after.dppKhz,
                        gF.corrective == 1u ? " (fell, raised back)" : gF.corrective == 2u ? " (fell, raise NOT verified)" : "",
                        (unsigned long long)gF.atMs, (unsigned long long)gF.tookMs);
}

// =========================================================================================================================================
// The clock trace.
// =========================================================================================================================================
namespace {
Trace gT;
bool gTOn, gTFloored, gTEnded;
uint32_t gTSeconds;
uint64_t gTStartMs, gTEndMs, gTNextMs, gTPubMs;
uint32_t gTLines, gTBurstLogs;
constexpr uint32_t kMaxLines = 400u, kMaxBurstLogs = 24u;
// 0.0.685: the self-limit (smu_health_pure.h): consecutive failures, the busy skips, the stop and its reason.
uint32_t gTConsec, gTMaxConsec;
uint64_t gTSkippedBusy;
uint32_t gTStop;   // 0 running; 1 consecutive failures; 2 the SMU health latch stopped optional traffic
uint64_t gTStopMs;
uint32_t gTLastKr;
enum SampleRes : uint32_t { kSOk = 0, kSFailed = 1, kSBusy = 2, kSRefused = 3 };

uint32_t take_sample(const DeviceContext &dev, uint64_t ms, bool pinned, Sample &s) {
    s = Sample{};
    s.ms = ms; s.pinned = pinned;
    SmuMetricsResult r{};
    kern_return_t kr;
    {
        // 0.0.685: never queue behind another SMU user (a message in flight there may wait its full 2 s): skip this sample instead.
        SmuTrySeq seq;   // the whole table transfer under the shared mailbox lock (as Navi48UserClient::doMetrics), or nothing
        if (!seq.held) return kSBusy;
        if (!smu_optional_ok()) return kSRefused;
        kr = smu_read_metrics(dev, &r);
    }
    gTLastKr = (uint32_t)kr;
    if (kr != kIOReturnSuccess) return smu_optional_ok() ? kSFailed : kSRefused;
    const SmuMetrics &m = r.metrics;
    s.mhz[kTUclk] = m.CurrClock[SMUClk::UCLK];
    s.mhz[kTFclk] = m.CurrClock[SMUClk::FCLK];
    s.mhz[kTDcf] = m.CurrClock[SMUClk::DCFCLK];
    s.mhz[kTDisp] = m.CurrClock[SMUClk::DISPCLK];
    s.mhz[kTDpp] = m.CurrClock[SMUClk::DPPCLK];
    s.mhz[kTSoc] = m.CurrClock[SMUClk::SOCCLK];
    for (uint32_t i = 0; i < kTClks; i++) if (s.mhz[i] > 10000u) return kSFailed;   // a layout shift, not a clock
    const n48dal::Decoded d = read_clocks(dev);
    s.dfsDispKhz = d.ok ? d.dispKhz : 0u;
    s.dfsDppKhz = d.ok ? d.dppKhz : 0u;
    s.ok = true;
    return kSOk;
}
void log_sample(const char *why, const Sample &s, uint64_t evMs) {
    TRACE_LOG("%s t=%llu ms (%lld ms from the burst): UCLK %u FCLK %u DCFCLK %u DISPCLK %u DPPCLK %u SOCCLK %u MHz; DFS DISPCLK %u DPPCLK %u kHz%s", why,
              (unsigned long long)s.ms, evMs ? (long long)s.ms - (long long)evMs : 0ll, s.mhz[kTUclk], s.mhz[kTFclk], s.mhz[kTDcf], s.mhz[kTDisp],
              s.mhz[kTDpp], s.mhz[kTSoc], s.dfsDispKhz, s.dfsDppKhz, s.pinned ? " (UCLK pinned)" : "");
}
}  // namespace

void clktrace_start(uint64_t nowMs) {
    uint32_t v = 0;
    const bool p = PE_parse_boot_argn("navi48-clklog", &v, sizeof(v));
    gTSeconds = trace_seconds(p, v);
    trace_init(gT, 0u);
    gTOn = gTSeconds != 0u;
    gTFloored = false; gTEnded = false;
    gTStartMs = nowMs; gTEndMs = ~0ull; gTNextMs = nowMs; gTPubMs = 0u; gTLines = 0u; gTBurstLogs = 0u;
    gTConsec = 0u; gTMaxConsec = 0u; gTSkippedBusy = 0u; gTStop = 0u; gTStopMs = 0u; gTLastKr = 0u;
    TRACE_LOG("boot clock trace %s", gTOn ? "ON: PMFW CurrClock UCLK/FCLK/DCFCLK/DISPCLK/DPPCLK/SOCCLK + DFS readback every 500 ms, around ufmon events (navi48-clklog=0 turns it off)"
                                          : "OFF (navi48-clklog=0)");
}
void clktrace_floor(uint32_t dcfFloorMhz, uint64_t nowMs) {
    gT.dcfFloorMhz = dcfFloorMhz;
    gTFloored = true;
    gTEndMs = nowMs + (uint64_t)gTSeconds * 1000ull;
    if (gTOn) TRACE_LOG("the floors ran at %llu ms: tracing %u s more (DCFCLK floor %u MHz)", (unsigned long long)nowMs, gTSeconds, dcfFloorMhz);
}
bool clktrace_poll(const DeviceContext &dev, uint64_t nowMs, uint64_t newEvents, bool pinned) {
    if (!gTOn || gTStop != 0u) return false;
    bool changed = false;
    // 0.0.685: the SMU health latch stopped optional traffic: the trace stops for the boot (no message is sent from here on).
    if (!smu_optional_ok()) {
        gTStop = 2u; gTStopMs = nowMs;
        TRACE_LOG("trace STOPPED at %llu ms: the SMU is DEGRADED (no SMU message is sent); %llu samples, %llu failed", (unsigned long long)nowMs,
                  (unsigned long long)gT.samples, (unsigned long long)gT.failures);
        return true;
    }
    if (newEvents > 0u && (!gTEnded || gT.pending)) trace_event(gT, nowMs, newEvents, pinned);
    const bool live = nowMs < gTEndMs || gT.pending;
    if (live && nowMs >= gTNextMs) {
        gTNextMs = nowMs + kSamplePeriodMs;
        Sample s;
        const Sample *prev = trace_at(gT, 0);
        const Sample p = prev != nullptr ? *prev : Sample{};
        const bool had = prev != nullptr;
        const uint32_t sr = take_sample(dev, nowMs, pinned, s);
        if (sr == kSBusy) {
            gTSkippedBusy++;   // another SMU user holds the lock: no sample, no failure, try again next period
        } else if (sr == kSRefused) {
            gTStop = 2u; gTStopMs = nowMs;
            TRACE_LOG("trace STOPPED at %llu ms: the SMU is DEGRADED (no SMU message is sent)", (unsigned long long)nowMs);
            return true;
        } else if (sr == kSOk) {
            gTConsec = 0u;
            trace_add(gT, s);
            bool moved = false;
            for (uint32_t i = 0; i < kTClks - 1u; i++) if (had && p.mhz[i] != s.mhz[i]) moved = true;   // SOCCLK moves are not logged one by one
            if (had && (p.dfsDispKhz != s.dfsDispKhz || p.dfsDppKhz != s.dfsDppKhz)) moved = true;
            if (gTLines < kMaxLines && (!had || moved || (gT.samples % 20u) == 0u)) { log_sample(!had ? "first" : moved ? "change" : "every 10 s", s, 0u); gTLines++; }
        } else {
            trace_add(gT, s);   // counts the failure
            gTConsec++;
            if (gTConsec > gTMaxConsec) gTMaxConsec = gTConsec;
            gTNextMs = nowMs + n48smuh::trace_period_ms(gTConsec);   // back off: 0.5 s, then 5, 10, 20, 40, 60 s
            if (n48smuh::trace_should_stop(gTConsec)) {
                gTStop = 1u; gTStopMs = nowMs;
                TRACE_LOG("trace STOPPED at %llu ms: %u consecutive metrics failures (last kr 0x%x); %llu samples, %llu failed", (unsigned long long)nowMs,
                          gTConsec, gTLastKr, (unsigned long long)gT.samples, (unsigned long long)gT.failures);
                return true;
            }
        }
        Burst b{};
        if (trace_settle(gT, nowMs, &b)) {
            changed = true;
            if (gTBurstLogs < kMaxBurstLogs) {
                gTBurstLogs++;
                TRACE_LOG("underflow burst #%llu at %llu ms (%u events%s): moved:%s%s%s%s%s%s%s; %u samples in [-%llu, +%llu] ms; UCLK %u..%u FCLK %u..%u DCFCLK %u..%u (floor %u) "
                          "DISPCLK %u..%u DPPCLK %u..%u MHz -> %s",
                          (unsigned long long)gT.bursts, (unsigned long long)b.atMs, b.events, (b.flags & kBPinned) ? ", UCLK pinned" : "",
                          (b.flags & kBUclk) ? " UCLK" : "", (b.flags & kBFclk) ? " FCLK" : "", (b.flags & kBDcf) ? " DCFCLK" : "",
                          (b.flags & kBDisp) ? " DISPCLK" : "", (b.flags & kBDpp) ? " DPPCLK" : "", (b.flags & kBDcfBelowFloor) ? " DCFCLK-under-floor" : "",
                          (b.flags & (kBUclk | kBFclk | kBDcf | kBDisp | kBDpp | kBDcfBelowFloor)) ? "" : " nothing",
                          b.nSamples, (unsigned long long)kPreMs, (unsigned long long)kPostMs, b.lo[kTUclk], b.hi[kTUclk], b.lo[kTFclk], b.hi[kTFclk],
                          b.lo[kTDcf], b.hi[kTDcf], gT.dcfFloorMhz, b.lo[kTDisp], b.hi[kTDisp], b.lo[kTDpp], b.hi[kTDpp], trace_lean(gT));
                for (uint32_t k = b.nSamples < 8u ? b.nSamples : 8u; k > 0u; k--) {
                    // the window's samples, oldest first
                    uint32_t seen = 0u;
                    for (uint32_t j = 0; j < gT.count; j++) {
                        const Sample *q = trace_at(gT, j);
                        if (q == nullptr || q->ms + kPreMs < b.atMs || q->ms > b.atMs + kPostMs) continue;
                        if (++seen == k) { log_sample("  burst", *q, b.atMs); break; }
                    }
                }
            }
        }
    }
    if (!gTEnded && gTFloored && nowMs >= gTEndMs && !gT.pending) {
        gTEnded = true;
        changed = true;
        TRACE_LOG("trace ended: %llu samples (%llu failed), %llu bursts (%llu events): UCLK %llu FCLK %llu (FCLK alone %llu) DCFCLK %llu DISPCLK/DPPCLK %llu nothing %llu; %s",
                  (unsigned long long)gT.samples, (unsigned long long)gT.failures, (unsigned long long)gT.bursts, (unsigned long long)gT.events,
                  (unsigned long long)gT.bUclk, (unsigned long long)gT.bFclk, (unsigned long long)gT.bFclkOnly, (unsigned long long)gT.bDcf,
                  (unsigned long long)gT.bDispDpp, (unsigned long long)gT.bNone, trace_lean(gT));
    }
    if (!gTEnded && nowMs - gTPubMs >= 5000u) { gTPubMs = nowMs; changed = true; }   // the registry every 5 s while tracing; nothing after the end
    return changed;
}

void clktrace_describe(char *t, size_t n) {
    if (t == nullptr || n == 0u) return;
    const int w = snprintf(t, n, "%s (every %llu ms, %u s after the floors; %llu samples, %llu failed); bursts %llu (events %llu): UCLK moved %llu, FCLK moved %llu "
             "(without UCLK %llu), DCFCLK moved or under floor %llu, DISPCLK/DPPCLK moved %llu, nothing moved %llu, UCLK pinned %llu, under 3 samples %llu; "
             "lean: %s; MHz ranges UCLK %u..%u FCLK %u..%u DCFCLK %u..%u (floor %u, samples under it %llu) DISPCLK %u..%u DPPCLK %u..%u SOCCLK %u..%u; "
             "moves UCLK %llu FCLK %llu DCFCLK %llu DISPCLK %llu DPPCLK %llu; with UCLK pinned: FCLK moves %llu, UCLK moves %llu; last burst at %llu ms flags %#x",
             !gTOn ? "off (navi48-clklog=0)" : gTStop == 1u ? "STOPPED (consecutive metrics failures)" : gTStop == 2u ? "STOPPED (SMU degraded)" :
             gTEnded ? "ended" : gTFloored ? "tracing" : "tracing (floors not run yet)",
             (unsigned long long)kSamplePeriodMs, gTSeconds, (unsigned long long)gT.samples, (unsigned long long)gT.failures,
             (unsigned long long)gT.bursts, (unsigned long long)gT.events, (unsigned long long)gT.bUclk, (unsigned long long)gT.bFclk,
             (unsigned long long)gT.bFclkOnly, (unsigned long long)gT.bDcf, (unsigned long long)gT.bDispDpp, (unsigned long long)gT.bNone,
             (unsigned long long)gT.bPinned, (unsigned long long)gT.bFew, trace_lean(gT),
             gT.lo[kTUclk], gT.hi[kTUclk], gT.lo[kTFclk], gT.hi[kTFclk], gT.lo[kTDcf], gT.hi[kTDcf], gT.dcfFloorMhz, (unsigned long long)gT.dcfBelowFloor,
             gT.lo[kTDisp], gT.hi[kTDisp], gT.lo[kTDpp], gT.hi[kTDpp], gT.lo[kTSoc], gT.hi[kTSoc],
             (unsigned long long)gT.moves[kTUclk], (unsigned long long)gT.moves[kTFclk], (unsigned long long)gT.moves[kTDcf],
             (unsigned long long)gT.moves[kTDisp], (unsigned long long)gT.moves[kTDpp],
             (unsigned long long)gT.fclkMovesPinned, (unsigned long long)gT.uclkMovesPinned, (unsigned long long)gT.last.atMs, gT.last.flags);
    // 0.0.685: the self-limit's counters.
    if (w > 0 && (size_t)w < n)
        snprintf(t + w, n - (size_t)w, "; failures: consecutive %u (max %u; backoff after %u, stop after %u), busy skips %llu, last kr %#x%s",
                 gTConsec, gTMaxConsec, n48smuh::kTraceBackoffAfter, n48smuh::kTraceStopAfter, (unsigned long long)gTSkippedBusy, gTLastKr,
                 gTStop != 0u ? (gTStop == 1u ? "; stopped by consecutive failures" : "; stopped: SMU degraded") : "");
}

}  // namespace amdgpu
