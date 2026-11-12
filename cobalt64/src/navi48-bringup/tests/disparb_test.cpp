// disparb_test.cpp - build 0.0.673 (black band without a fixed memory clock): the display arbitration (dcn/navi48_disparb_pure.h) driven over a
// DCHUBBUB register model seeded with the 2026-11-12 live read, plus source pins on its kext wiring (dcn/navi48_dcn.cpp, Navi48Bringup.cpp).
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -I src/navi48-bringup/src/dcn \
//       src/navi48-bringup/tests/disparb_test.cpp -o /tmp/disparb && /tmp/disparb src/navi48-bringup [repo root, for the Linux offset check]
// Covers: C the DML arithmetic and the register addresses (and, when the Linux tree is present, every watermark offset against dcn_4_1_0_offset.h);
// S the Linux order on the live state (raise -> DET release -> DET grow -> wait -> lower -> stutter allow), the exact write set and values;
// R every refusal writes no DET register; T the timeout rollback and the allowlist refusal; K the kill switches; W the kext wiring.
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <set>
#include <fstream>
#include <sstream>
#include "navi48_disparb_pure.h"

static int gFail = 0, gRun = 0;
static void expect(bool ok, const char *what) { gRun++; if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream ss; ss << f.rdbuf(); return ss.str(); }
using namespace n48arb;

// ---- the register model ----------------------------------------------------------------------------------------------------------------------------
// DETn_SIZE_CURRENT follows DETn_SIZE at the next VUPDATE (8333 us at 120 Hz) for an ACTIVE pipe (pipe 0 here); an inactive pipe keeps CURRENT 0.
// A requested layout above the 21-segment CRB sets COMPBUF CONFIG_ERROR (what dcn401_program_det_segments warns about).
struct Model {
    std::map<uint32_t, uint32_t> r;
    std::vector<std::pair<uint32_t, uint32_t>> writes;
    std::set<uint32_t> refuse, deadRead;
    bool frozen = false;          // the DET never follows (a hung DCHUBBUB)
    bool frozenUntilRollback = false;
    uint32_t stickAt = 0;         // nonzero: DET0_SIZE_CURRENT goes to this value at the next VUPDATE and stays there (a broken resize)
    uint64_t now = 0, pendingAt = 0; bool pending = false;
    std::vector<std::string> log;
    void seed_live() {
        r.clear();
        r[0x39BC] = 0x20001002u; r[0x39E4] = 0x00000010u; r[0x39E7] = 0x00001002u;
        r[0x39BE] = 0x1FEu; r[0x39BF] = 0u; r[0x39C0] = 0u; r[0x39C1] = 0u; r[0x39C2] = 0x4BAu; r[0x39C3] = 0x424u;
        for (uint32_t a = 0x39C4; a <= 0x39C9; a++) r[a] = (a & 1u) ? 0x424u : 0x4BAu;   // SR enter/exit 1..3 as set A's
        r[0x39CA] = 0x4EE8u; r[0x39CB] = 0u; r[0x39CC] = 0u; r[0x39CD] = 0u;
        for (uint32_t a = 0x39BE; a <= 0x39CD; a++) r[a + 0x13u] = r[a];                  // set B = set A (the live read: urgent B 0x1fe, SR B 0x4ba/0x424, UCLK B 0x4ee8)
        r[0x397A] = 0x00040101u; r[0x397B] = 0x303u; r[0x397C] = 3u; r[0x397D] = 3u; r[0x397E] = 3u;
        r[0x3AB4] = 0x000f0002u;
    }
    uint32_t sumSizes() const { return size_of(r.at(0x397B)) + size_of(r.at(0x397C)) + size_of(r.at(0x397D)) + size_of(r.at(0x397E)) + size_of(r.at(0x397A)); }
    void tick(uint32_t us) {
        now += us;
        if (pending && now >= pendingAt && stickAt != 0u) { pending = false; r[0x397B] = (r[0x397B] & ~0x1F00u) | (stickAt << 8); frozen = true; return; }
        if (pending && now >= pendingAt && !frozen) {
            pending = false;
            const uint32_t d0 = r[0x397B];
            r[0x397B] = (d0 & ~0x1F00u) | (size_of(d0) << 8);   // pipe 0 active
            for (uint32_t i = 1; i < 4; i++) r[0x397B + i] &= ~0x1F00u;   // inactive pipes: CURRENT 0
        }
    }
};
static Model M;
static uint32_t m_rd(void *, uint32_t a) { if (M.deadRead.count(a)) return 0xFFFFFFFFu; auto it = M.r.find(a); return it == M.r.end() ? 0xDEADBEEFu : it->second; }
static bool m_wr(void *, uint32_t a, uint32_t v) {
    if (M.refuse.count(a)) return false;
    M.writes.push_back({ a, v });
    if (a >= 0x397B && a <= 0x397E) {
        M.r[a] = (M.r[a] & 0x1F00u) | (v & ~0x1F00u);   // CURRENT is read-only
        if (M.sumSizes() > kCrbSegs) M.r[0x397A] |= kCompbufConfigError;
        if (M.frozenUntilRollback && a == 0x397B && size_of(v) != kDetTargetSegs) M.frozen = false;
        M.pending = true; M.pendingAt = M.now + 8333u;
    } else M.r[a] = v;
    return true;
}
static void m_delay(void *, uint32_t us) { M.tick(us); }
static void m_log(void *, const char *what, uint32_t a, uint32_t b, uint32_t c) { char t[160]; std::snprintf(t, sizeof t, "%s %#x %#x->%#x", what, a, b, c); M.log.push_back(t); }
static const Hw kHw{ nullptr, m_rd, m_wr, m_delay, m_log };
static void reset() { M = Model(); M.seed_live(); }
static size_t idx_of(uint32_t a, uint32_t v) { for (size_t i = 0; i < M.writes.size(); i++) if (M.writes[i].first == a && (v == 0xFFFFFFFFu || M.writes[i].second == v)) return i; return SIZE_MAX; }
static bool any_det_write() { for (auto &w : M.writes) if (w.first >= 0x397A && w.first <= 0x397E) return true; return false; }
static bool any_wm_write() { for (auto &w : M.writes) if (w.first >= 0x39BE && w.first <= 0x39E0) return true; return false; }

int main(int argc, char **argv) {
    // ---- C: the arithmetic and the addresses ----
    expect(max_total_det_kb() == 1280u && kDetTargetSegs == 20u && kCompbufSegs == 1u && kCrbSegs == 21u, "DML MaxTotalDET 1280 KB = 20 segments, compbuf 1, CRB 21");
    expect(lines_of(3) == 19u && lines_of(20) == 128u, "192 KB = 19 lines, 1280 KB = 128 lines of 2560 x 4 B");
    expect(kWmPerSet == 15u && wm_abs(0) == 0x39BEu && wm_abs(kWmPerSet) == 0x39D1u && wm_abs(11) == 0x39CAu && wm_abs(kWmPerSet + 11) == 0x39DDu, "WM addresses A/B");
    expect(wm_target(0) == 440u && wm_target(3) == 2896u && wm_target(4) == 2246u && wm_target(11) == 20440u && wm_target(12) == 440u && wm_target(13) == 440u && wm_target(14) == 440u,
           "targets: urgent 440, SR 2896/2246, UCLK 20440, UCLK1/FCLK/FCLK1 440 (8.8 / 57.92 / 44.92 / 408.8 us x 50 MHz)");
    for (uint32_t i = 0; i < kWmRegs; i++) expect(wm_target(i) == wm_target(i % kWmPerSet) && (wm_target(i) & ~kWm[i % kWmPerSet].mask) == 0u, "set B = set A, every target fits its field");
    expect(enabled(false, 0) && enabled(true, 1) && enabled(true, 5) && !enabled(true, 0), "only an explicit 0 turns a step off");
    expect(refclk_ok(0x1002u) && !refclk_ok(0x1001u) && !refclk_ok(0x0002u) && !refclk_ok(0xFFFFFFFFu), "refclk: REFDIV 2 + ENABLE (50 MHz from 100 MHz)");
    // C2: the watermark offsets against Linux's dcn_4_1_0_offset.h (when the study tree is present)
    {
        const std::string repo = argc > 2 ? argv[2] : "../..";
        const std::string off = slurp(repo + "/research/ext/amdgpu-port-study/linux-v7.3/drivers/gpu/drm/amd/include/asic_reg/dcn/dcn_4_1_0_offset.h");
        if (off.empty()) std::printf("note: Linux dcn_4_1_0_offset.h not found under %s: offset cross-check skipped\n", repo.c_str());
        else {
            auto offset_of = [&](const std::string &name) -> long {
                const std::string key = "#define reg" + name + " ";
                const size_t p = off.find(key);
                if (p == std::string::npos) return -1;
                return std::strtol(off.c_str() + p + key.size(), nullptr, 16);
            };
            for (uint32_t i = 0; i < kWmPerSet; i++) {
                const std::string n = std::string("DCHUBBUB_ARB_") + kWm[i].name;
                expect(offset_of(n + "_A") == (long)kWm[i].offA && offset_of(n + "_B") == (long)(kWm[i].offA + kSetBDelta), kWm[i].name);
            }
            expect(offset_of("DCHUBBUB_COMPBUF_CTRL") == 0x4BA && offset_of("DCHUBBUB_DET0_CTRL") == 0x4BB && offset_of("DCHUBBUB_DET3_CTRL") == 0x4BE &&
                   offset_of("DCHUBBUB_ARB_DRAM_STATE_CNTL") == 0x4FC && offset_of("DCHUBBUB_ARB_WATERMARK_CHANGE_CNTL") == 0x524 && offset_of("DCHUBBUB_GLOBAL_TIMER_CNTL") == 0x527,
                   "DET / COMPBUF / DRAM_STATE / WM_CHANGE / GLOBAL_TIMER offsets");
        }
    }

    // ---- S: the live state, everything ON ----
    reset();
    Result r = apply(kHw, Cfg{ true, true, true });
    expect(r.det == kDetDone && r.wm == kWmDone && r.refusedWrites == 0u, "live 120 Hz state: resized and programmed");
    expect(M.r[0x397B] == 0x1414u && size_of(M.r[0x397C]) == 0u && size_of(M.r[0x397D]) == 0u && size_of(M.r[0x397E]) == 0u, "DET0 20/20, DET1-3 size 0");
    expect(M.r[0x397A] == 0x00040101u && (M.r[0x397A] & kCompbufConfigError) == 0u, "COMPBUF untouched (1 segment), no CONFIG_ERROR at any step");
    expect(M.r[0x39BC] == 0x20001000u && r.srAllowed, "DRAM_STATE: SR force enable/value cleared (stutter allowed), the rest kept");
    expect(M.r[0x39E4] == 0x10u && idx_of(0x39E4, 0xFFFFFFFFu) == SIZE_MAX, "WATERMARK_CHANGE_CNTL never written (Linux dcn401 does not use it)");
    for (uint32_t i = 0; i < kWmRegs; i++) expect(M.r[wm_abs(i)] == wm_target(i), kWm[i % kWmPerSet].name);
    expect(r.detWaitUs >= 8300u && r.detWaitUs <= 8500u, "DET0_SIZE_CURRENT waited for (one VUPDATE)");
    {
        const size_t rel1 = idx_of(0x397C, 0u), rel3 = idx_of(0x397E, 0u), grow = idx_of(0x397B, 0x314u), uclk = idx_of(0x39CA, 20440u), urgent = idx_of(0x39BE, 440u),
                     sr = idx_of(0x39C2, 2896u), dram = idx_of(0x39BC, 0xFFFFFFFFu);
        expect(rel1 != SIZE_MAX && rel3 != SIZE_MAX && grow != SIZE_MAX && rel1 < grow && rel3 < grow, "the free pipes give their DET back BEFORE DET0 grows (DET0 write = 0x314: SIZE 20, CURRENT bits kept as read)");
        expect(uclk < rel1 && sr < rel1, "prepare: the raised watermarks (UCLK, SR) are written before the DET");
        expect(urgent != SIZE_MAX && urgent > grow && dram > urgent, "optimize: the LOWERED urgent watermark only after the DET settled, then the stutter allow");
        size_t lastDet = 0; for (size_t i = 0; i < M.writes.size(); i++) if (M.writes[i].first >= 0x397B && M.writes[i].first <= 0x397E) lastDet = i;
        expect(lastDet == grow, "no DET write after the grow");
    }
    {
        std::set<uint32_t> allowed { 0x397B, 0x397C, 0x397D, 0x397E, 0x39BC };
        for (uint32_t i = 0; i < kWmRegs; i++) allowed.insert(wm_abs(i));
        bool only = true; for (auto &w : M.writes) only = only && allowed.count(w.first) != 0u;
        expect(only, "writes only to DET0-3, DRAM_STATE and the 30 watermark registers (no USR, no FRAC_URG_BW, no COMPBUF, no HUBP)");
        expect(M.r[0x39BF] == 0u && M.r[0x39BF + 0x13] == 0u, "USR retraining watermark untouched");
    }
    expect(r.raised + r.lowered == 30u && r.writes == 35u, "every write is accounted: 30 watermark changes + 3 DET releases + 1 grow + DRAM_STATE");
    // Idempotent: a second apply on the result writes nothing to the DET and says already
    {
        M.writes.clear();
        Result r2 = apply(kHw, Cfg{ true, true, true });
        expect(r2.det == kDetAlready && r2.wm == kWmDone && M.writes.empty(), "second run: already-linux-size, nothing written");
    }

    // ---- R: refusals write no DET register (the watermarks still go) ----
    struct Case { const char *what; uint32_t reg, val; uint32_t want; };
    const Case cases[] = {
        { "another pipe holds DET (DET1 CURRENT 3)", 0x397C, 0x303u, kDetOtherPipe },
        { "DET0 resize pending (SIZE 4, CURRENT 3)", 0x397B, 0x304u, kDetPending },
        { "COMPBUF resize pending", 0x397A, 0x00040201u, kDetPending },
        { "COMPBUF 2 segments", 0x397A, 0x00040202u, kDetCompbuf },
        { "COMPBUF CONFIG_ERROR", 0x397A, 0x80040101u, kDetConfigError },
        { "HUBP0 unbounded request", 0x3AB4, 0x000f0402u, kDetUnbounded },
        { "HUBP0 blanked", 0x3AB4, 0x000f0003u, kDetPlaneBlank },
        { "HUBP0 holds no DET", 0x397B, 0x0u, kDetNoPipe0 },
        { "DET2 unreadable", 0x397D, 0xFFFFFFFFu, kDetUnreadable },
    };
    for (const Case &c : cases) {
        reset(); M.r[c.reg] = c.val;
        Result rr = apply(kHw, Cfg{ true, true, true });
        expect(rr.det == c.want && !any_det_write() && rr.wm == kWmDone, c.what);
    }

    // ---- T: the DET does not follow -> rolled back; the allowlist refuses -> rolled back ----
    reset(); M.frozen = true; M.frozenUntilRollback = true;
    r = apply(kHw, Cfg{ true, true, true });
    expect(r.det == kDetTimeoutRolledBack && r.detWaitUs == 100000u, "DET0_SIZE_CURRENT stuck 100 ms: timeout, rolled back");
    expect(M.r[0x397B] == 0x303u && M.r[0x397C] == 3u && M.r[0x397D] == 3u && M.r[0x397E] == 3u, "rollback: DET0 3 (current 3), DET1-3 SIZE 3 again");
    expect((M.r[0x397A] & kCompbufConfigError) == 0u, "rollback order: DET0 shrinks before DET1-3 take theirs back (never above the CRB)");
    reset(); M.frozen = true;   // never follows: CURRENT stays 3, so the rollback finds DET0 where it was
    r = apply(kHw, Cfg{ true, true, true });
    expect(r.det == kDetTimeoutRolledBack && M.r[0x397B] == 0x303u && M.r[0x397C] == 3u, "a DET that never follows: rolled back to the GOP layout");
    reset(); M.stickAt = 7u;   // CURRENT moves to a value that is neither the target nor the old size, and stays
    r = apply(kHw, Cfg{ true, true, true });
    expect(r.det == kDetRollbackFailed, "a DET stuck half-way: rollback failed (reported, state uncertain)");
    reset(); M.refuse.insert(0x397B);
    r = apply(kHw, Cfg{ true, true, true });
    expect(r.det == kDetRefused && M.r[0x397B] == 0x303u && M.r[0x397C] == 3u && M.r[0x397E] == 3u && r.refusedWrites >= 1u, "allowlist refuses DET0: DET1-3 given back their 3 segments");
    reset(); M.refuse.insert(0x39CA);
    r = apply(kHw, Cfg{ true, true, true });
    expect(r.wm == kWmRefused && (M.r[0x39BC] & kDramSrForceEnable) != 0u, "allowlist refuses a watermark: WM refused, stutter NOT allowed");

    // ---- K: the switches ----
    reset(); r = apply(kHw, Cfg{ false, true, true });
    expect(r.det == kDetOff && !any_det_write() && r.wm == kWmDone, "navi48-det=0: no DET write, watermarks programmed");
    reset(); r = apply(kHw, Cfg{ true, false, true });
    expect(r.wm == kWmOff && !any_wm_write() && M.r[0x39BC] == 0x20001002u && r.det == kDetDone, "navi48-wm=0: no watermark / DRAM_STATE write, DET resized");
    reset(); r = apply(kHw, Cfg{ true, true, false });
    expect(r.wm == kWmDone && M.r[0x39BC] == 0x20001002u && !r.srAllowed, "navi48-sr=0: the GOP's stutter force-off is kept");
    reset(); r = apply(kHw, Cfg{ false, false, false });
    expect(M.writes.empty() && r.det == kDetOff && r.wm == kWmOff, "all off: nothing written at all");
    reset(); M.r[0x39E7] = 0x1001u; r = apply(kHw, Cfg{ false, true, true });
    expect(r.wm == kWmRefclk && M.writes.empty(), "refclk not 50 MHz: no watermark written");
    reset(); M.deadRead.insert(0x39DD); r = apply(kHw, Cfg{ false, true, true });
    expect(r.wm == kWmUnreadable && M.writes.empty(), "an unreadable watermark register: nothing written");
    reset(); M.r[0x39BC] = 0x20001032u; r = apply(kHw, Cfg{ false, true, true });
    expect(M.r[0x39BC] == 0x20001000u && r.wm == kWmDone, "a GOP p-state force (b5/b4) is cleared as dcn401_init_hw does");

    // ---- W: the kext wiring (source pins) ----
    const std::string root = argc > 1 ? argv[1] : ".";
    const std::string d = slurp(root + "/src/dcn/navi48_dcn.cpp"), b = slurp(root + "/src/Navi48Bringup.cpp");
    expect(!d.empty() && !b.empty(), "navi48_dcn.cpp / Navi48Bringup.cpp readable (pass the navi48-bringup directory)");
    auto body = [&](const std::string &src, const char *start) -> std::string {
        const size_t p = src.find(start); if (p == std::string::npos) return std::string();
        const size_t e = src.find("\n}\n", p); return src.substr(p, e == std::string::npos ? std::string::npos : e - p);
    };
    const std::string wr = body(d, "static bool arb_wr(void *, uint32_t abs, uint32_t v) {");
    expect(wr.find("dcn41_allow_write(&gDcn.allow") != std::string::npos && wr.find("WREG32") > wr.find("dcn41_allow_write"), "arb_wr: the allowlist decides before the write");
    const std::string ap = body(d, "static bool arb_apply_once() {");
    const size_t lk = ap.find("IOLockLock(gMtLock);"), ar = ap.find("n48arb::apply(disparb_hw(), c);"), ul = ap.find("IOLockUnlock(gMtLock);");
    expect(lk != std::string::npos && ar > lk && ul > ar, "apply runs under gMtLock (the mode trial / hold exclusion)");
    expect(ap.find("modeTrialBusy() || modeHoldActive()") != std::string::npos, "never while a mode trial or hold runs");
    expect(ap.find("\"navi48-det\"") != std::string::npos && ap.find("\"navi48-wm\"") != std::string::npos && ap.find("\"navi48-sr\"") != std::string::npos, "kill switches navi48-det / navi48-wm / navi48-sr");
    expect(ap.find("if (gArbMultiLatch) c.det = false;") != std::string::npos, "no DET resize while a multi-display latch is on");
    const std::string lp = body(d, "static void arb_monitor_loop() {");
    expect(lp.find("ufmon_poll(monGen);") != std::string::npos && lp.find("IOLockLock(") == std::string::npos, "the monitor runs ufmon and takes no lock itself");
    expect(lp.find("smu_uclk_display_pin(*gDcn.dev, pin, gFb.why)") != std::string::npos, "the fallback pin / release goes through smu_uclk_display_pin");
    expect(lp.find("ms - t0 >= 2000u") != std::string::npos, "the arbitration waits 2 s after the start");
    expect(lp.find("if (pin && gFb.why == n48uclk::kWhyUnderflow) arb_sr_revert();") != std::string::npos, "an underflow trigger also takes the stutter allow back");
    expect(lp.find("up.verdict == n48uclk::kNotRun ? (uint32_t)n48uclk::kModeOff : up.mode") != std::string::npos, "no fallback when this boot did not enable the SMU features");
    const std::string sr = body(d, "static void arb_sr_revert() {");
    expect(sr.find("IOLockLock(gMtLock);") != std::string::npos && sr.find("arb_wr(nullptr, kRegDramState,") > sr.find("IOLockLock(gMtLock);") && sr.find("IOLockUnlock(gMtLock);") > sr.find("arb_wr(nullptr, kRegDramState,"),
           "the stutter revert: under gMtLock, through the allowlisted write");
    expect(sr.find("(d & ~(kDramSrForceEnable | kDramSrForceValue)) | gop") != std::string::npos, "it restores exactly the GOP's two SELF_REFRESH_FORCE bits");
    const std::string wd = body(d, "static void scan_watchdog_loop(uint32_t myGen) {");
    expect(!wd.empty() && wd.find("ufmon_poll(") == std::string::npos, "ufmon no longer depends on a scanout acquisition's watchdog");
    const std::string st = body(d, "static void arb_monitor_start() {");
    expect(st.find("\"navi48-dispmon\"") != std::string::npos && st.find("kernel_thread_start(&arb_monitor") != std::string::npos, "the thread, with its kill switch navi48-dispmon");
    const size_t bnd = d.find("\tmt_golden_at_bind();\n\tarb_monitor_start();");
    expect(bnd != std::string::npos, "started at the end of bind (the display layer armed)");
    const std::string sd = body(d, "void scanShutdown() {");
    expect(sd.find("arb_monitor_stop();") != std::string::npos && sd.find("arb_monitor_stop();") < sd.find("mt_shutdown();"), "kext stop: the monitor ends first");
    expect(b.find("n48dcn::dispArbModeChanged();") != std::string::npos && b.find("req.kind == n48rf::kReqSet60 || req.kind == n48rf::kReqSet120) n48dcn::dispArbModeChanged();") != std::string::npos,
           "the 60 Hz switch tells the monitor (new ufmon baseline)");
    expect(b.find("n48dcn::uclkPinDescribe(t, sizeof(t));") != std::string::npos, "Navi48,UclkPin text from the display layer");
    expect(d.find("setProperty(\"Navi48,DisplayArb\"") != std::string::npos && d.find("setProperty(\"Navi48,UclkPin\"") != std::string::npos &&
           d.find("setProperty(\"Navi48,DisplayUnderflow\"") != std::string::npos, "the three registry properties");
    std::printf("%s: %d checks, %d failed\n", gFail ? "FAIL" : "PASS", gRun, gFail);
    return gFail ? 1 : 0;
}
