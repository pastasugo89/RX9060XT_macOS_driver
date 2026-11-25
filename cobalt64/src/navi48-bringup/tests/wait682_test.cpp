// 0.0.682 host test: the wait steps and the bound-expiry log gate (amd/wait_pure.h; F1 / F3 of research/reports/macos-20261125/stability-performance.md),
// plus source pins: no submit path waits for ring space under gRingLock, every 2 s bound logs, no wait loop keeps the 5 ms spin.
// Build: clang++ -std=c++17 -I src tests/wait682_test.cpp -o /tmp/w682 ; run: /tmp/w682 <kernel source dir>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include "amd/wait_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static int count(const std::string &h, const std::string &n) { int c = 0; for (size_t p = h.find(n); p != std::string::npos; p = h.find(n, p + n.size())) c++; return c; }
using namespace n48wait;

// Simulate one wait of `boundNs` that never completes: total spin time, number of sleeps, total planned sleep, longest step.
struct Sim { uint64_t spinNs, sleepNs; uint32_t sleeps, maxUs; };
static Sim simulate(uint32_t mode, uint64_t boundNs, uint32_t capUs) {
    Sim r{0, 0, 0, 0}; Backoff b{}; uint64_t el = 0;
    while (el < boundNs) {
        const Step st = next_step(mode, b, el, capUs);
        const uint64_t ns = (uint64_t)st.us * 1000ull;
        if (st.kind == kSpin1us) r.spinNs += ns; else { r.sleepNs += ns; r.sleeps++; }
        if (st.us > r.maxUs) r.maxUs = st.us;
        el += ns;
    }
    return r;
}

static void test_steps() {
    expect(mode_of(false, 0, false) == kSleep && mode_of(true, 1, false) == kSleep && mode_of(true, 0, false) == kLegacy, "navi48-waitsleep: absent/1 -> sleep, 0 -> legacy");
    expect(mode_of(false, 0, true) == kEop && mode_of(true, 0, true) == kLegacy, "the EOP wake upgrades sleep only; legacy stays legacy");
    const Sim legacy = simulate(kLegacy, 2000000000ull, kFenceCapUs);
    expect(legacy.spinNs == 5000000ull && legacy.maxUs == 1000u, "legacy = the 0.0.681 step: 5 ms of 1 us spins, then 1 ms sleeps");
    const Sim sl = simulate(kSleep, 2000000000ull, kFenceCapUs);
    expect(sl.spinNs == kSpinNs, "sleep mode spins 50 us at most per wait");
    expect(sl.maxUs == 200u, "fence waits never sleep longer than 200 us per step");
    expect(sl.spinNs * 100 <= legacy.spinNs, "at least 100x less spinning than 0.0.681");
    Backoff b{};
    const uint32_t want[] = {50, 100, 200, 200, 200};
    bool okSeq = true;
    for (uint32_t i = 0; i < 5; i++) { const Step st = next_step(kSleep, b, kSpinNs + i, kFenceCapUs); okSeq = okSeq && st.kind == kSleepUs && st.us == want[i]; }
    expect(okSeq, "fence backoff 50, 100, 200, 200, ...");
    Backoff r{};
    const uint32_t wantR[] = {50, 100, 200, 400, 800, 1000, 1000};
    bool okR = true;
    for (uint32_t i = 0; i < 7; i++) { const Step st = next_step(kSleep, r, kSpinNs, kRetryCapUs); okR = okR && st.us == wantR[i]; }
    expect(okR, "production retry backoff 50 .. 1000 us (the global locks retaken at most once per step)");
    Backoff e{};
    expect(next_step(kEop, e, kSpinNs, kFenceCapUs).kind == kEventUs && next_step(kEop, e, 0, kFenceCapUs).kind == kSpin1us, "EOP mode: same spin, then event sleeps");
    const Sim sr = simulate(kSleep, 2000000000ull, kRetryCapUs);
    expect(sr.sleeps < 2100u, "a 2 s production retry takes ~2000 lock rounds instead of ~5000 + 1995");
    Backoff big{}; big.sleeps = 31;
    for (int i = 0; i < 10; i++) (void)next_step(kSleep, big, kSpinNs, kFenceCapUs);
    expect(big.sleeps == 32u && backoff_us(1000, 200) == 200u && backoff_us(0, 30) == 30u, "the exponent saturates; the cap always wins");
    // the bound: the elapsed check is the caller's; a step never exceeds 1 ms, so a 2 s bound is overrun by at most one step
    expect(simulate(kSleep, 2000000000ull, kRetryCapUs).maxUs <= 1000u && simulate(kLegacy, 2000000000ull, kRetryCapUs).maxUs == 1000u, "no step longer than 1 ms in any mode");
}

static void test_gate() {
    LogGate g{}; uint32_t sup = 99;
    expect(log_gate(g, 1000, &sup) && sup == 0, "the first line prints");
    expect(!log_gate(g, 1000 + kLogGapNs - 1, &sup), "a second line inside 100 ms is suppressed");
    expect(!log_gate(g, 1000 + 1, &sup) && g.suppressed == 2u, "and counted");
    expect(log_gate(g, 1000 + kLogGapNs, &sup) && sup == 2u && g.suppressed == 0u, "the next line after 100 ms prints with the dropped count");
    LogGate m{};
    uint32_t printed = 0;
    for (uint32_t i = 0; i < 1000; i++) if (log_gate(m, (uint64_t)i * kLogGapNs, &sup)) printed++;
    expect(printed == kLogMax && m.suppressed == 1000u - kLogMax, "at most 256 lines per boot");
    expect(std::string(kind_name(kRingSpace)) == "ring-space" && std::string(kind_name(kAdmission)) == "vmid/admission", "kind names");
}

static void test_pins(const std::string &src) {
    const std::string s = slurp(src + "/src/amd/native_s1c.cpp");
    expect(!s.empty(), "native_s1c.cpp readable");
    expect(count(s, "ring_put_locked(gSubmitBuf, n, seq, (uint8_t)s->slot, s->id, s, false)") == 3, "all three submit paths call ring_put_locked without the space wait");
    expect(count(s, "ring_put_locked(dw, 8u, probe, kOwnerKernel, 0u, nullptr)") == 1, "only the recovery probe keeps the in-lock wait");
    expect(s.find("if (rc == kRingNoSpace) rc = n48native::g2::kBusy;") != std::string::npos, "production: no space = retry with both global locks dropped");
    expect(s.find("if (!waitSpace) return kRingNoSpace;") != std::string::npos, "ring_put_locked returns at once without the wait");
    expect(count(s, "if (el < 5000000ull) IODelay(1); else IOSleep(1);") == 2 && count(s, "if (elapsed < 5000000ull) IODelay(1); else IOSleep(1);") == 0,
           "the 5 ms spin is left only in the recovery probe's in-lock space wait and the G1 test env (plus the G2 verify); no submit or fence wait keeps it");
    expect(count(s, "wait_relax(bo,") == 5, "own_wait, ring_submit, G5, production and n1c_wait step through wait_relax");
    expect(s.find("wait_relax(bo, elapsed, gen, n48wait::kRetryCapUs);") != std::string::npos, "production uses the 1 ms retry cap");
    for (const char *c : { "bound_log(\"own_wait\"", "bound_log(\"ring_submit\"", "bound_log(\"ring_submit_production\"", "bound_log(\"n1c_wait\"", "bound_log(\"ring_submit_app_g5\"", "bound_log(\"hang_from_wait" })
        expect(s.find(c) != std::string::npos, std::string("bound expiry logged: ") + c);
    expect(s.find("if (mode == n48wait::kLegacy) { IOSleep(1); return; }") != std::string::npos, "legacy mode sleeps exactly IOSleep(1)");
    expect(s.find("(void)IOLockSleepDeadline(l, (void *)&gEopGen, dl, THREAD_UNINT);") != std::string::npos, "the sleep is a timed IOLockSleepDeadline");
    expect(s.find("__atomic_add_fetch(&gEopGen, 1u, __ATOMIC_RELEASE);\n    IOLockWakeup(l, (void *)&gEopGen, false);") != std::string::npos,
           "the signal bumps the generation and wakes under the same lock (no lost wakeup)");
}

int main(int argc, char **argv) {
    test_steps(); test_gate();
    if (argc > 1) test_pins(argv[1]);
    printf("%s: %d checks, %d failures\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
