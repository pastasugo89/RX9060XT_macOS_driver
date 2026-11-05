// refresh60_test.cpp - build 0.0.670 (the 60 Hz scanout switch on Navi 44). Compiles the REAL decisions and sequences of
// src/dcn/navi48_refresh_pure.h on the host and drives them against a model of the display registers:
//   * the OTG master lock: the request bit sets UPDATE_LOCK_STATUS; the V_TOTAL writes made under the lock are applied only at the unlock;
//   * the double-buffer pending flag: set by a write under the lock, cleared when the unlock applies it;
//   * the scanout: a line counter that runs at 5 us per line over the APPLIED total, so the witness reads the real frame length;
//   * refusals (a write that does nothing, once or always), a stuck lock, a stuck unlock, a stuck pending flag, unreadable registers.
// Every sequence runs twice: with DRR off (V_TOTAL_MIN = V_TOTAL_MAX = 0: the live Navi 44 GOP read on 0.0.669) and with DRR on
// (both = 1524, the pair 0.0.669 required). Section "live" uses the exact register values read on 0.0.669.
// Every register the verb writes is also checked against the REAL dcn41 write allowlist (dcn41_allow.c, the table the kext's dcn_wreg uses).
// Planted defects: a writer that skips the lock must be caught by the same checker; a writer that enables DRR (MIN/MAX from zero) must be
// caught by the DRR-off check; a classifier input with a wrong V_TOTAL, or a mixed MIN/MAX pair, must be refused.
//   clang -c ../../dcn41/dcn41_allow.c -o /tmp/dcn41_allow.o   (C11, no kernel headers)
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all refresh60_test.cpp dcn41_allow.o
#include "../src/dcn/navi48_refresh_pure.h"
#include "../../dcn41/dcn41_allow.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <string>
#include <vector>

using namespace n48rf;

static int failures = 0;
static int checks = 0;
static const char *g_variant = "";
#define CHECK(cond, what) do { checks++; if (!(cond)) { failures++; std::printf("FAIL [%s]: %s  (line %d)\n", g_variant, what, __LINE__); } } while (0)

namespace {

struct Wr { uint32_t abs, val; bool lockHeld; };

struct Fake {
    std::map<uint32_t, uint32_t> reg;          // the register file as the hardware holds it
    std::map<uint32_t, int> refuseCount;       // writes to this dword are dropped this many times (-1 = always)
    std::map<uint32_t, uint32_t> forced;       // reads return this value
    bool lockStuckOn = false;                  // UPDATE_LOCK_STATUS never sets
    bool lockStuckOff = false;                 // UPDATE_LOCK_STATUS never clears after an unlock
    bool pendingStuck = false;                 // the double-buffer pending flag never clears
    bool applyOnUnlock = true;                 // false: the unlock never applies the new totals (witness must catch it)
    bool pendingStuckAfterUnlock = false;      // the pending flag sticks from the first unlock on
    bool lockReq = false, lockStatus = false, pendingBit = false;
    uint32_t applied = 1525;                   // lines of the frame the scanout runs now
    uint64_t t = 1000000;                      // microseconds
    std::vector<Wr> writes;
    std::vector<std::string> logs;

    static bool isV(uint32_t a) { return a == kRegVTotal || a == kRegVTotalMin || a == kRegVTotalMax; }

    // The 120 Hz GOP register file. drrOn: V_TOTAL_MIN = V_TOTAL_MAX = 0x5F4 (the pair 0.0.669 required); otherwise both 0 (the live GOP).
    void reset_gop(bool drrOn) {
        reg.clear();
        reg[kRegHTotal] = 0x0A9Fu;
        reg[kRegVTotal] = 0x05F4u;
        reg[kRegVTotalMin] = drrOn ? 0x05F4u : 0u;
        reg[kRegVTotalMax] = drrOn ? 0x05F4u : 0u;
        reg[kRegMsa1Navi44] = 0x0AA005F5u;
        reg[kRegDtoPhase] = 0x1DAB0FF0u; reg[kRegDtoModulo] = 0x2AEA5400u; reg[kRegRateDiv] = 0x00008421u;
        reg[kRegDbCtrl] = 0u; reg[kRegMasterLock] = 0u; reg[kRegPipeUpd] = 0u;
        lockReq = lockStatus = pendingBit = false;
        applied = 1525;
        writes.clear(); logs.clear();
    }

    uint32_t counter() const { return (uint32_t)((t / 5u) % applied); }

    uint32_t rd(uint32_t a) {
        auto f = forced.find(a);
        if (f != forced.end()) return f->second;
        switch (a) {
        case kRegMasterLock: return (lockReq ? 1u : 0u) | (lockStatus ? kLockStatus : 0u);
        case kRegDbCtrl: return reg[kRegDbCtrl] | (pendingBit ? 0x1u : 0u) | (pendingStuck ? 0x1u : 0u);
        case kRegStatusPos: return counter();
        case kRegPipeUpd: return 0u;
        default: { auto it = reg.find(a); return it == reg.end() ? 0u : it->second; }
        }
    }

    void wr(uint32_t a, uint32_t v) {
        writes.push_back(Wr{ a, v, lockReq });
        auto rc = refuseCount.find(a);
        if (rc != refuseCount.end() && rc->second != 0) { if (rc->second > 0) rc->second--; return; }
        if (a == kRegMasterLock) {
            const bool prev = lockReq;
            lockReq = (v & 1u) != 0u;
            reg[a] = v & 1u;
            if (lockReq) lockStatus = !lockStuckOn;
            else if (!lockStuckOff) lockStatus = false;
            if (prev && !lockReq) {                       // the unlock: the held totals take effect at this frame edge
                if (applyOnUnlock && !lockStuckOff) applied = reg[kRegVTotal] + 1u;
                if (pendingStuckAfterUnlock) pendingStuck = true;
                if (!pendingStuck) pendingBit = false;
            }
            return;
        }
        if (a == kRegDbCtrl) { reg[a] = v & ~0x231u; return; }    // pending bits are read-only
        reg[a] = v;
        if (lockReq && isV(a)) pendingBit = true;
    }
};

// The adapter: the plain C callbacks of n48rf::Hw over the fake.
uint32_t f_rd(void *c, uint32_t a) { return static_cast<Fake *>(c)->rd(a); }
void f_wr(void *c, uint32_t a, uint32_t v) { static_cast<Fake *>(c)->wr(a, v); }
void f_delay(void *c, uint32_t us) { static_cast<Fake *>(c)->t += us; }
uint64_t f_now(void *c) { return static_cast<Fake *>(c)->t; }
void f_log(void *c, const char *what, uint32_t a, uint32_t x, uint32_t y) {
    char buf[160];
    std::snprintf(buf, sizeof buf, "%s %#x %#x %#x", what, a, x, y);
    static_cast<Fake *>(c)->logs.push_back(buf);
}
Hw hw_of(Fake &f) { return Hw{ &f, f_rd, f_wr, f_delay, f_now, f_log }; }

uint32_t regv(const Fake &f, uint32_t a) {
    auto it = f.reg.find(a);
    return it == f.reg.end() ? 0xFFFFFFFFu : it->second;
}

// The registers as a finished set 60 leaves them: V 3049, MIN and MAX 0 (DRR off) or 3049 (DRR on), MSA 3050, DRR 0, lock off, applied 3050.
bool target_regs(const Fake &f, bool drrOn) {
    const uint32_t mm = drrOn ? 3049u : 0u;
    return regv(f, kRegVTotal) == 3049u && regv(f, kRegVTotalMin) == mm && regv(f, kRegVTotalMax) == mm && regv(f, kRegMsa1Navi44) == 0x0AA00BEAu &&
           regv(f, kRegDbCtrl) == 0u && regv(f, kRegMasterLock) == 0u && f.applied == 3050u;
}
// The registers as the GOP has them: V 1524, MIN and MAX 0 (DRR off) or 1524 (DRR on), MSA 1525, DRR 0, lock off, applied 1525.
bool gop_regs(const Fake &f, bool drrOn) {
    const uint32_t mm = drrOn ? 0x5F4u : 0u;
    return regv(f, kRegVTotal) == 0x5F4u && regv(f, kRegVTotalMin) == mm && regv(f, kRegVTotalMax) == mm &&
           regv(f, kRegMsa1Navi44) == 0x0AA005F5u && regv(f, kRegDbCtrl) == 0u && regv(f, kRegMasterLock) == 0u && f.applied == 1525u;
}
// True when a MIN or MAX write carries a non-zero value: the sequence enabled DRR.
bool enables_drr(const Fake &f) {
    for (const Wr &w : f.writes) if ((w.abs == kRegVTotalMin || w.abs == kRegVTotalMax) && w.val != 0u) return true;
    return false;
}

// Every V_TOTAL-family write must be made with the lock held; the MSA write must come after the unlock; DRR goes 2 before the lock and 0 after the unlock.
// Returns the first violation or "" when the order is right.
std::string order_violation(const Fake &f) {
    for (const Wr &w : f.writes) {
        if (Fake::isV(w.abs) && !w.lockHeld) return "V_TOTAL-family write without the master lock";
        if (w.abs == kRegMsa1Navi44 && w.lockHeld) return "MSA write while the lock is held";
    }
    // the first DB write (DRR 2) comes before the first lock request and the first V write
    size_t iDb = f.writes.size(), iLock = f.writes.size(), iV = f.writes.size();
    for (size_t i = 0; i < f.writes.size(); i++) {
        if (f.writes[i].abs == kRegDbCtrl && iDb == f.writes.size()) iDb = i;
        if (f.writes[i].abs == kRegMasterLock && iLock == f.writes.size() && (f.writes[i].val & 1u)) iLock = i;
        if (Fake::isV(f.writes[i].abs) && iV == f.writes.size()) iV = i;
    }
    if (iV < f.writes.size() && !(iDb < iLock && iLock < iV)) return "DRR 2, lock request and V_TOTAL writes are out of order";
    return "";
}

// The scanout's frame length is only trusted once the apply has unlocked, so a sequence that ends with the lock held is a violation.
bool ends_unlocked(const Fake &f) { return !f.lockReq && f.reg.at(kRegMasterLock) == 0u; }

// The exact register values read on 0.0.669 (navi48test reg, read only) with the 120 Hz GOP on screen, DRR off.
void live_fixture(Fake &f) {
    f.reset_gop(false);
    f.reg[kRegHTotal] = 0x00000A9Fu;      // OTG0_OTG_H_TOTAL 0x4FEA
    f.reg[kRegVTotal] = 0x000005F4u;      // OTG0_OTG_V_TOTAL 0x4FEF
    f.reg[kRegVTotalMin] = 0x00000000u;   // OTG0_OTG_V_TOTAL_MIN 0x4FF0
    f.reg[kRegVTotalMax] = 0x00000000u;   // OTG0_OTG_V_TOTAL_MAX 0x4FF1
    f.reg[kRegMsa1Navi44] = 0x0AA005F5u;  // DP MSA_TIMING_PARAM1 0x5622
    f.reg[kRegDtoPhase] = 0x1DAB0FF0u;    // DP_DTO0_PHASE 0x141
    f.reg[kRegDtoModulo] = 0x2AEA5400u;   // DP_DTO0_MODULO 0x142
    f.reg[kRegRateDiv] = 0x00008421u;     // OTG_PIXEL_RATE_DIV 0x12F
    f.reg[kRegDbCtrl] = 0x00000000u;      // OTG_DOUBLE_BUFFER_CONTROL 0x501C
    f.reg[kRegMasterLock] = 0x00000000u;  // OTG_MASTER_UPDATE_LOCK 0x5049 (coordinator note: no lock, quiet)
    f.reg[kRegPipeUpd] = 0x00000000u;     // OTG_PIPE_UPDATE_STATUS 0x505E
    f.applied = 1525u;
}

// The sequences that must hold for each GOP pair: set 60, restore 120, and the refusals and failures of the locked sequence.
void sequences(bool drrOn) {
    g_variant = drrOn ? "DRR on" : "DRR off";

    // ---- 4. set 60 on the GOP timing: the locked sequence, its order, the final registers ----------------------------------------------------
    {
        Fake f; f.reset_gop(drrOn);
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kOk, "set 60 succeeds on the GOP timing");
        CHECK(o.vLines == 3050u && o.msaLines == 3050u, "the outcome reports 3050 lines");
        CHECK(o.witnessMax > 1525u && o.witnessMax <= 3049u && o.witnessN > 0u, "the witness saw the 3050-line frame");
        CHECK(target_regs(f, drrOn), "the registers hold the 60 Hz target: V_TOTAL 3049, MIN/MAX as the GOP had them (0 stays 0), MSA 3050, DRR 0, lock off, applied 3050");
        CHECK(order_violation(f).empty(), order_violation(f).c_str());
        CHECK(ends_unlocked(f), "the sequence ends unlocked");
        // the exact write list: with DRR off no MIN or MAX write is made at all
        std::vector<uint32_t> seq;
        for (const Wr &w : f.writes) if (w.abs == kRegVTotal || w.abs == kRegVTotalMin || w.abs == kRegVTotalMax || w.abs == kRegMsa1Navi44 || w.abs == kRegDbCtrl || w.abs == kRegMasterLock) seq.push_back(w.abs);
        const std::vector<uint32_t> want = drrOn
            ? std::vector<uint32_t>{ kRegDbCtrl, kRegMasterLock, kRegVTotal, kRegVTotalMin, kRegVTotalMax, kRegMasterLock, kRegMsa1Navi44, kRegDbCtrl }
            : std::vector<uint32_t>{ kRegDbCtrl, kRegMasterLock, kRegVTotal, kRegMasterLock, kRegMsa1Navi44, kRegDbCtrl };
        CHECK(seq == want, "the writes are DRR 2, lock, V_TOTAL (and MIN, MAX when DRR is on), unlock, MSA, DRR 0 (in that order)");
        CHECK(f.writes.size() == want.size(), "no other register is written");
        CHECK(!f.logs.empty(), "every step is logged");
        CHECK(drrOn || !enables_drr(f), "DRR off: the sequence writes no non-zero MIN or MAX (DRR is not enabled)");
        // the second call is a no-op success
        const size_t before = f.writes.size();
        Outcome again = set60(h, read_snap(h));
        CHECK(again.code == kOk && f.writes.size() == before, "set 60 on the 60 Hz target writes nothing");
    }

    // ---- 5. restore 120 from the target: the GOP values back, reverse order ------------------------------------------------------------------
    {
        Fake f; f.reset_gop(drrOn);
        Hw h = hw_of(f);
        CHECK(set60(h, read_snap(h)).code == kOk, "precondition: 60 Hz");
        f.writes.clear();
        Outcome o = restore120(h, read_snap(h));
        CHECK(o.code == kOk && gop_regs(f, drrOn), "restore 120 returns the GOP registers exactly (V 1524, MIN/MAX as the GOP had them, MSA 0x0AA005F5, applied 1525)");
        CHECK(order_violation(f).empty(), order_violation(f).c_str());
        CHECK(o.witnessMax <= 1524u && o.witnessMax > 100u, "the witness saw the 1525-line frame again");
        CHECK(drrOn || !enables_drr(f), "DRR off: restore 120 writes no non-zero MIN or MAX");
        const size_t before = f.writes.size();
        CHECK(restore120(h, read_snap(h)).code == kOk && f.writes.size() == before, "restore 120 on the GOP timing writes nothing");
    }

    // ---- 6. refusals with no write: a timing that is not the GOP, not the target, or unreadable ----------------------------------------------
    {
        Fake f; f.reset_gop(drrOn); f.reg[kRegVTotal] = 0x05F3u;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kTimingDiffers && f.writes.empty(), "set 60 refuses a timing that differs from the GOP, with no write");
        Fake g; g.reset_gop(drrOn);
        Hw hg = hw_of(g);
        CHECK(restore120(hg, read_snap(hg)).code == kOk && g.writes.empty(), "restore 120 on a GOP timing is a no-op success, no write");
        Fake u; u.reset_gop(drrOn); u.forced[kRegHTotal] = 0xFFFFFFFFu;
        Hw hu = hw_of(u);
        CHECK(set60(hu, read_snap(hu)).code == kTimingDiffers && u.writes.empty(), "an unreadable H total refuses set 60 with no write");
    }

    // ---- 7. failures in the sequence: each one leaves the GOP timing behind -------------------------------------------------------------------
    {
        // 7a. the lock never comes on: nothing is written under it; the lock is released; the DRR mode is restored
        Fake f; f.reset_gop(drrOn); f.lockStuckOn = true;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kLockTimeout, "a lock that never comes on is kLockTimeout");
        CHECK(gop_regs(f, drrOn), "a lock timeout leaves the GOP registers (no V write was made)");
        CHECK(order_violation(f).empty(), order_violation(f).c_str());
    }
    {
        // 7b. one refused write inside the locked group: readback mismatch, every recorded write put back in reverse, the GOP timing restored.
        // DRR on: the refused write is the V_TOTAL_MAX write. DRR off: there is no MIN/MAX write, so the refused write is V_TOTAL itself.
        Fake f; f.reset_gop(drrOn);
        f.refuseCount[drrOn ? kRegVTotalMax : kRegVTotal] = 1;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kReadbackMismatch, "a refused V-family write is a readback mismatch");
        CHECK(gop_regs(f, drrOn), "after the refusal the rollback leaves the GOP registers exactly");
        CHECK(order_violation(f).empty(), order_violation(f).c_str());
        std::vector<uint32_t> tailV;
        for (const Wr &w : f.writes) if (Fake::isV(w.abs)) tailV.push_back(w.abs);
        const std::vector<uint32_t> wantV = drrOn
            ? std::vector<uint32_t>{ kRegVTotal, kRegVTotalMin, kRegVTotalMax, kRegVTotalMax, kRegVTotalMin, kRegVTotal }
            : std::vector<uint32_t>{ kRegVTotal, kRegVTotal };
        CHECK(tailV == wantV, "the recorded V-family writes are put back newest first");
    }
    {
        // 7c. the MSA write is refused always: the MSA is rolled back to 0x0AA005F5 and the V-family too
        Fake f; f.reset_gop(drrOn); f.refuseCount[kRegMsa1Navi44] = -1;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kReadbackMismatch, "a permanently refused MSA write is a readback mismatch");
        CHECK(f.reg[kRegVTotal] == 0x5F4u && f.reg[kRegVTotalMin] == (drrOn ? 0x5F4u : 0u) && f.reg[kRegVTotalMax] == (drrOn ? 0x5F4u : 0u),
              "the V-family is back to the GOP values (1524, MIN/MAX as before)");
        CHECK(gop_regs(f, drrOn), "after the MSA refusal the GOP registers are exact");
    }
    {
        // 7d. the frame does not change (the unlock never applies it): the witness refuses and the rollback restores GOP
        Fake f; f.reset_gop(drrOn); f.applyOnUnlock = false;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kReadbackMismatch, "a witness that never sees the 3050-line frame is a readback mismatch");
        CHECK(gop_regs(f, drrOn), "the rollback after a failed witness leaves the GOP timing");
    }
    {
        // 7e. the unlock never clears its status: the sequence stops, states the unlock failed (no more writes), and reports kLockTimeout
        Fake f; f.reset_gop(drrOn); f.lockStuckOff = true;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kLockTimeout, "an unlock that never clears is kLockTimeout");
        CHECK(!f.writes.empty() && f.writes.back().abs == kRegMasterLock && f.writes.back().val == 0u, "nothing is written after the failed unlock");
    }
    {
        // 7f. the pending flag never clears: the restore cannot verify, so the outcome is kRestoreFailed (the kext keeps the 60 Hz property)
        Fake f; f.reset_gop(drrOn); f.pendingStuckAfterUnlock = true;
        Hw h = hw_of(f);
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kRestoreFailed, "a pending flag that sticks after the unlock cannot be verified: kRestoreFailed");
        CHECK(o.code != kOk, "a stuck pending flag is not a success");
    }
    g_variant = "";
}

// A mutation of the live fixture: every one of these must be refused by set 60 AND by restore 120, with no write.
struct Mut { const char *what; std::function<void(Fake &)> apply; };

}  // namespace

int main() {
    // ---- 1. the request decoder and its native-boot exemption ----------------------------------------------------------------------------------
    g_variant = "decoder";
    {
        Request r = parse(kActRefresh, 60u | (15u << 16));
        CHECK(r.kind == kReqSet60 && r.timeoutS == 15u, "109 60 15 -> set 60 with a 15 s timeout");
        CHECK(parse(kActRefresh, 60u).kind == kReqBad, "109 60 without a timeout is refused (set 60 always reverts)");
        CHECK(parse(kActRefresh, 60u | (4u << 16)).kind == kReqBad, "a 4 s timeout is refused");
        CHECK(parse(kActRefresh, 60u | (5u << 16)).kind == kReqSet60, "a 5 s timeout is the minimum");
        CHECK(parse(kActRefresh, 60u | (600u << 16)).kind == kReqSet60, "a 600 s timeout is the maximum");
        CHECK(parse(kActRefresh, 60u | (601u << 16)).kind == kReqBad, "a 601 s timeout is refused");
        CHECK(parse(kActRefresh, 120u).kind == kReqSet120, "109 120 -> restore");
        CHECK(parse(kActRefresh, 120u | (15u << 16)).kind == kReqBad, "a timeout with 120 is refused");
        CHECK(parse(kActRefresh, 121u).kind == kReqBad && parse(kActRefresh, 0u).kind == kReqBad, "other rates are refused");
        CHECK(parse(kActRefresh, 60u | (15u << 16) | (1ull << 32)).kind == kReqBad, "bits above 32 are refused");
        CHECK(parse(kActRefreshConfirm, 0u).kind == kReqConfirm && parse(kActRefreshConfirm, 1u).kind == kReqStatus, "110 0 confirm, 110 1 status");
        CHECK(parse(kActRefreshConfirm, 2u).kind == kReqBad, "110 2 is refused");
        CHECK(native_exempt(kActRefresh, 60u | (15u << 16)) && native_exempt(kActRefresh, 120u) && native_exempt(kActRefreshConfirm, 0u) &&
              native_exempt(kActRefreshConfirm, 1u), "the well-formed requests are exempt from the native refusal");
        CHECK(!native_exempt(kActRefresh, 60u) && !native_exempt(kActRefreshConfirm, 2u) && !native_exempt(77u, 0u) && !native_exempt(108u, 0u),
              "malformed requests and other verbs are not exempt");
        CHECK(is_refresh_action(109u) && is_refresh_action(110u) && !is_refresh_action(108u) && !is_refresh_action(111u), "the action numbers 109 and 110");
    }

    // ---- 2. the allowlist: every register the verb writes is inside the kext's real dcn41 write allowlist ------------------------------------
    {
        const uint32_t seg[5] = { 0x12u, 0xC0u, 0x34C0u, 0x9000u, 0x2403C00u };
        dcn41_allow_state st;
        std::memset(&st, 0, sizeof st);
        CHECK(dcn41_allow_init(&st, seg, 0x10000u) == 0, "allowlist arms with the generated segment bases");
        const uint32_t regs[] = { kRegVTotal, kRegVTotalMin, kRegVTotalMax, kRegDbCtrl, kRegMasterLock, kRegMsa1Navi44 };
        for (uint32_t a : regs) {
            char what[96];
            std::snprintf(what, sizeof what, "allowlist permits the write %#x", a);
            const bool ok = dcn41_allow_write(&st, a, 0u, "refresh60-probe");
            CHECK(ok, what);
        }
        CHECK(!dcn41_allow_write(&st, kRegMsa1Navi44 + 0x100000u, 0u, "refresh60-probe"), "an address outside the table is still refused");
    }

    // ---- 3. classification: the two GOP pairs, the two target pairs, and every near miss is "other" ---------------------------------------
    g_variant = "classify";
    {
        Fake f; f.reset_gop(false);
        Hw h = hw_of(f);
        CHECK(classify(read_snap(h)) == kLiveGop, "the live DRR-off GOP (MIN = MAX = 0) classifies as GOP");
        f.reset_gop(true);
        CHECK(classify(read_snap(h)) == kLiveGop, "the DRR-on GOP (MIN = MAX = 1524) classifies as GOP");
        f.reset_gop(false); f.reg[kRegVTotal] = 0x0BE9u; f.reg[kRegMsa1Navi44] = 0x0AA00BEAu; f.applied = 3050;
        CHECK(classify(read_snap(h)) == kLiveTarget, "the 60 Hz target with DRR off (MIN = MAX = 0) classifies as target");
        f.reset_gop(true); f.reg[kRegVTotal] = 0x0BE9u; f.reg[kRegVTotalMin] = 0x0BE9u; f.reg[kRegVTotalMax] = 0x0BE9u;
        f.reg[kRegMsa1Navi44] = 0x0AA00BEAu; f.applied = 3050;
        CHECK(classify(read_snap(h)) == kLiveTarget, "the 60 Hz target with DRR on (MIN = MAX = 3049) classifies as target");
        f.reset_gop(false); f.reg[kRegVTotal] = 0x05F3u;
        CHECK(classify(read_snap(h)) == kLiveOther, "V_TOTAL off by one is other");
        f.reset_gop(false); f.reg[kRegMsa1Navi44] = 0x0AA005C9u;
        CHECK(classify(read_snap(h)) == kLiveOther, "the 60 Hz golden MSA with the 120 Hz V_TOTAL is other");
        f.reset_gop(false); f.reg[kRegVTotalMax] = 0x05F4u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a mixed pair (MIN 0, MAX 1524) is other");
        f.reset_gop(false); f.reg[kRegVTotalMin] = 0x05F4u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a mixed pair (MIN 1524, MAX 0) is other");
        f.reset_gop(false); f.reg[kRegVTotalMin] = 0x0BE9u; f.reg[kRegVTotalMax] = 0x0BE9u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a DRR pair that is not V_TOTAL (3049 at V 1524) is other");
        f.reset_gop(true); f.reg[kRegVTotal] = 0x0BE9u; f.reg[kRegVTotalMin] = 0x0BE9u; f.reg[kRegVTotalMax] = 0x0BE9u;
        f.reg[kRegMsa1Navi44] = 0x0AA00BEAu; f.applied = 3050;
        CHECK(classify(read_snap(h)) == kLiveTarget, "the target with MIN = MAX = 3049 classifies as target");
        f.reset_gop(true); f.reg[kRegVTotal] = 0x0BE9u; f.reg[kRegVTotalMax] = 0x0BE9u; f.reg[kRegMsa1Navi44] = 0x0AA00BEAu; f.applied = 3050;
        CHECK(classify(read_snap(h)) == kLiveOther, "a target with a mixed pair (MIN 1524, MAX 3049) is other");
        f.reset_gop(false); f.reg[kRegDbCtrl] = 0x01000000u;
        CHECK(classify(read_snap(h)) == kLiveOther, "DRR mode 1 is other");
        f.reset_gop(false); f.reg[kRegDbCtrl] = 0x02000000u;
        CHECK(classify(read_snap(h)) == kLiveGop, "DRR mode 2 (DP start of frame) on the GOP timing is still the GOP timing");
        f.reset_gop(false); f.forced[kRegMasterLock] = 0x100u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a lock left held (status) is other");
        f.reset_gop(false); f.forced[kRegMasterLock] = 0x1u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a lock requested is other");
        f.reset_gop(false); f.forced[kRegPipeUpd] = 0x10u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a PIPE_UPDATE pending flag is other");
        f.reset_gop(false); f.reg[kRegDbCtrl] = 0x00000100u;
        CHECK(classify(read_snap(h)) == kLiveOther, "UPDATE_INSTANTLY set is other");
        f.reset_gop(false); f.reg[kRegRateDiv] = 0x00008423u;
        CHECK(classify(read_snap(h)) == kLiveOther, "an OTG_PIXEL_RATE_DIV field bit set (DPDTO0_INT != 0) is other");
        f.reset_gop(false); f.reg[kRegHTotal] = 0x0A9Eu;
        CHECK(classify(read_snap(h)) == kLiveOther, "a different H total is other");
        f.reset_gop(false); f.reg[kRegDtoPhase] = 0x1DAB0FF1u;
        CHECK(classify(read_snap(h)) == kLiveOther, "a different DTO is other");
        f.reset_gop(false); f.forced[kRegVTotal] = 0xFFFFFFFFu;
        CHECK(classify(read_snap(h)) == kLiveOther, "an unreadable register is other");
        f.reset_gop(false); f.forced[kRegVTotalMin] = 0xFFFFFFFFu;
        CHECK(classify(read_snap(h)) == kLiveOther, "an unreadable MIN is other");
    }
    {
        // a locked apply never writes a mixed pair: apply() refuses it before any write
        Fake f; f.reset_gop(false);
        Hw h = hw_of(f);
        Snap s = read_snap(h);
        s.vMax = 0x5F4u;
        Outcome o = apply(h, s, 3050u, true);
        CHECK(o.code == kTimingDiffers && f.writes.empty(), "apply refuses a mixed MIN/MAX pair with no write");
    }
    g_variant = "";

    // ---- 4-7. the sequences, once with DRR off (the live GOP) and once with DRR on (the pair 0.0.669 required) -------------------------------
    sequences(false);
    sequences(true);

    // ---- 8. the planted defect: a writer that skips the lock is caught by the same order check ------------------------------------------------
    g_variant = "planted";
    {
        Fake f; f.reset_gop(false);
        Hw h = hw_of(f);
        // a naive writer: V_TOTAL written with no lock request, the way dcnmode 101 did
        h.wr(h.ctx, kRegVTotal, 3049u);
        CHECK(!order_violation(f).empty(), "CONTROL: a V_TOTAL write without the lock is reported by the order check");
    }
    {
        // a writer that enables DRR on the live GOP (MIN and MAX from 0 to V_TOTAL, the 0.0.669 apply's writes) is caught twice:
        // by the DRR-off write check, and by the target check, which needs MIN = MAX = 0 with DRR off.
        Fake f; f.reset_gop(false);
        Hw h = hw_of(f);
        h.wr(h.ctx, kRegVTotalMin, 0x05F4u);
        h.wr(h.ctx, kRegVTotalMax, 0x05F4u);
        CHECK(enables_drr(f), "CONTROL: a non-zero MIN/MAX write is reported by the DRR-off check");
        CHECK(!target_regs(f, false), "CONTROL: a DRR-enabling write does not satisfy the DRR-off target check");
    }

    // ---- 9. the session: revert deadlines, confirm and status ----------------------------------------------------------------------------------
    g_variant = "session";
    {
        Session s{ kPhaseGop120, 0u, 0u, 0u, 0u };
        session_begin(s, 15u, 0u);
        CHECK(s.phase == kPhasePending60 && remaining_s(s, 0u) == 15u, "after set 60 15 the revert is 15 s away");
        CHECK(remaining_s(s, 10000000ull) == 5u, "10 s later, 5 s remain");
        CHECK(remaining_s(s, 14500000ull) == 1u, "half a second before the deadline counts as 1 s (rounded up)");
        CHECK(remaining_s(s, 15000000ull) == 0u, "at the deadline nothing remains");
        session_gop(s);
        CHECK(s.phase == kPhaseGop120 && remaining_s(s, 0u) == 0u, "the GOP phase has no revert pending");
    }

    // ---- 10. the exact live register values of 0.0.669: the full round trip, and every single-field mutation of them is refused ------------
    g_variant = "live";
    {
        Fake f; live_fixture(f);
        Hw h = hw_of(f);
        CHECK((0x00000A9Fu & 0xFFFFu) == 0x0A9Fu && 0x0AA005F5u == ((2720u << 16) | 1525u), "the live H total and MSA golden agree with 2720 x 1525");
        CHECK((0x00008421u & kRateDivMask) == 0u, "the live OTG_PIXEL_RATE_DIV 0x8421 has no DPDTO0_INT bits set");
        CHECK((0x00A90306u & kVertMask) == 774u, "the live OTG0_STATUS_POSITION 0x00a90306 reads VERT_COUNT 774 (the witness mask)");
        CHECK(classify(read_snap(h)) == kLiveGop, "the live 120 Hz GOP (DRR off) classifies as GOP");
        const std::map<uint32_t, uint32_t> live = f.reg;
        Outcome o = set60(h, read_snap(h));
        CHECK(o.code == kOk && target_regs(f, false), "set 60 from the live GOP: V 3049, MIN and MAX stay 0, MSA 0x0AA00BEA, DRR 0, lock off");
        CHECK(!enables_drr(f), "set 60 from the live GOP never writes a non-zero MIN or MAX");
        CHECK(order_violation(f).empty(), order_violation(f).c_str());
        CHECK(classify(read_snap(h)) == kLiveTarget, "the 60 Hz target (DRR off) classifies as target");
        Outcome r = restore120(h, read_snap(h));
        CHECK(r.code == kOk, "restore 120 succeeds from the 60 Hz target");
        CHECK(f.reg == live, "restore 120 returns every register to the live GOP values (the full register file)");
        CHECK(f.applied == 1525u, "the frame is 1525 lines again");
        CHECK(!enables_drr(f), "the live round trip writes no non-zero MIN or MAX");
    }
    {
        const std::vector<Mut> muts = {
            { "H total 0x0A9E", [](Fake &f) { f.reg[kRegHTotal] = 0x0A9Eu; } },
            { "V_TOTAL 0x05F3", [](Fake &f) { f.reg[kRegVTotal] = 0x05F3u; } },
            { "MIN 0, MAX 0x05F4 (mixed)", [](Fake &f) { f.reg[kRegVTotalMax] = 0x05F4u; } },
            { "MIN 0x05F4, MAX 0 (mixed)", [](Fake &f) { f.reg[kRegVTotalMin] = 0x05F4u; } },
            { "MIN = MAX = 3049 at V 1524", [](Fake &f) { f.reg[kRegVTotalMin] = 0x0BE9u; f.reg[kRegVTotalMax] = 0x0BE9u; } },
            { "MSA 0x0AA005C9 (the 60 Hz golden)", [](Fake &f) { f.reg[kRegMsa1Navi44] = 0x0AA005C9u; } },
            { "DTO phase + 1", [](Fake &f) { f.reg[kRegDtoPhase] = 0x1DAB0FF1u; } },
            { "DTO modulo + 1", [](Fake &f) { f.reg[kRegDtoModulo] = 0x2AEA5401u; } },
            { "PIXEL_RATE_DIV 0x8423 (DPDTO0_INT bit set)", [](Fake &f) { f.reg[kRegRateDiv] = 0x00008423u; } },
            { "DRR mode 1", [](Fake &f) { f.reg[kRegDbCtrl] = 0x01000000u; } },
            { "DB UPDATE_PENDING", [](Fake &f) { f.reg[kRegDbCtrl] = 0x00000001u; } },
            { "DB TIMING pending b5", [](Fake &f) { f.reg[kRegDbCtrl] = 0x00000020u; } },
            { "DB UPDATE_INSTANTLY", [](Fake &f) { f.reg[kRegDbCtrl] = 0x00000100u; } },
            { "MASTER_UPDATE_LOCK requested", [](Fake &f) { f.forced[kRegMasterLock] = 0x1u; } },
            { "UPDATE_LOCK_STATUS held", [](Fake &f) { f.forced[kRegMasterLock] = 0x100u; } },
            { "PIPE_UPDATE pending", [](Fake &f) { f.forced[kRegPipeUpd] = 0x10u; } },
            { "MIN unreadable", [](Fake &f) { f.forced[kRegVTotalMin] = 0xFFFFFFFFu; } },
            { "target V with the GOP MSA", [](Fake &f) { f.reg[kRegVTotal] = 0x0BE9u; f.reg[kRegMsa1Navi44] = 0x0AA005F5u; f.applied = 3050; } },
            { "target V with a mixed pair", [](Fake &f) { f.reg[kRegVTotal] = 0x0BE9u; f.reg[kRegMsa1Navi44] = 0x0AA00BEAu; f.reg[kRegVTotalMin] = 0x05F4u; f.applied = 3050; } },
        };
        for (const Mut &m : muts) {
            Fake f; live_fixture(f);
            m.apply(f);
            Hw h = hw_of(f);
            const std::string set = std::string("live mutation refused by set 60: ") + m.what;
            const std::string rest = std::string("live mutation refused by restore 120: ") + m.what;
            CHECK(set60(h, read_snap(h)).code == kTimingDiffers && f.writes.empty(), set.c_str());
            CHECK(restore120(h, read_snap(h)).code == kTimingDiffers && f.writes.empty(), rest.c_str());
        }
    }

    g_variant = "";
    std::printf("refresh60_test: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? 0 : 1;
}
