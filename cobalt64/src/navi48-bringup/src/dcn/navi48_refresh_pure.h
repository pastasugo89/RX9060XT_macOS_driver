//
//  navi48_refresh_pure.h - kext 0.0.669: the 60 Hz scanout switch on Navi 44 (approach A). Decisions and sequences only; no kernel
//  header, so tests/refresh60_test.cpp compiles this on the host Mac and drives the exact code the kext runs. The kext supplies the
//  register callbacks (dcn/navi48_dcn.cpp refresh_hw(): every write goes through the DCN allowlist) and the lock, timer and registry
//  property (Navi48Bringup.cpp: refreshVerb, refreshTimerFired, refreshShutdown).
//
//  WHAT CHANGES. The GOP scans 2560x1440 as a 2720 x 1525 raster at a 497.75 MHz pixel clock (120.00 Hz). The 60 Hz target keeps the pixel
//  clock, the H timing and the DP link, and makes the frame 3050 lines: 497.75e6 / (2720 x 3050) = 59.9988 Hz. Exactly these registers change:
//    OTG0_OTG_V_TOTAL, OTG0_OTG_V_TOTAL_MIN, OTG0_OTG_V_TOTAL_MAX   (total - 1: 1524 -> 3049; MIN and MAX equal V_TOTAL in the GOP golden)
//    DP MSA_TIMING_PARAM1 VTOTAL field (low 16 bits, the TOTAL line count: 1525 -> 3050; the high half is the H total, kept)
//  The MSA field is not optional: the GOP golden (navi48_modetrial_tables.h kGold120 [19]) carries the total there (0x0AA005F5 = 2720 x 1525),
//  and the 60 Hz golden carries 1481 (0x0AA005C9). DTO, H timing, VTG, the DLG/TTU set and the stream enable are not written.
//
//  SEQUENCE (apply(), used by set 60 and by restore 120; the values differ, the order is the same):
//    preflight (reads only): classify() must say the GOP timing (set) or the 60 Hz target (restore); anything else refuses with no write.
//    1. OTG_DOUBLE_BUFFER_CONTROL DRR_TIMING_DBUF_UPDATE_MODE = 2 (start of frame), as the row-120 apply of navi48_modetrial_pure.h does
//    2. OTG_MASTER_UPDATE_LOCK = 1 and wait for UPDATE_LOCK_STATUS (<= 10 ms)
//    3. V_TOTAL, V_TOTAL_MIN, V_TOTAL_MAX under the lock: each one recorded BEFORE its write, read back after it
//    4. OTG_MASTER_UPDATE_LOCK = 0 and wait for the status to clear (a stuck unlock stops the sequence: state uncertain, no rollback)
//    5. wait for the double-buffer pending bits and PIPE_UPDATE pending to clear (<= 100 ms)
//    6. witness: VERT_COUNT sampled for 40 ms (about two 60 Hz frames). Set 60 needs a count above 1525 (the 3050-line frame is live);
//       restore needs a count at or below 1524 and above 100 (the 1525-line frame is live again)
//    7. MSA_TIMING_PARAM1 with the new VTOTAL field, read back
//    8. DRR mode back to 0 (the GOP value), read back
//    9. final classify(): must be the target state; otherwise the rollback runs
//  ROLLBACK (every failure after the first write, and every failed final check): under the lock, every recorded write is put back to
//  its old value in REVERSE order, then unlock, pending wait, DRR mode 0, and a final classify() that must equal the state before the apply.
//  If the rollback cannot verify, the result is kRestoreFailed and the session keeps its phase (the kext logs it and leaves the property at 60).
//
//  THE SESSION (kernel state, Navi48Bringup.cpp): set 60 with a timeout arms a timer; `refresh confirm` cancels it (kConfirmed60); if the
//  timer fires first, the restore runs (kGop120). Set 60 always has a timeout (5..600 s): there is no 60 Hz state without a revert timer.
//
//  WRITES NOTHING itself: every register access goes through Hw.rd / Hw.wr. Hw.wr in the kext is dcn_wreg, i.e. the dcn41 write allowlist.
//
#pragma once
#include <stdint.h>

namespace n48rf {

// ---- register dwords: ABSOLUTE BAR5 dwords (navi48_modetrial_tables.h kCap; the OTG registers are the same on Navi 44 and Navi 48) -----------
constexpr uint32_t kRegDtoPhase   = 0x00000141u;   // DP_DTO0_PHASE (read only here)
constexpr uint32_t kRegDtoModulo  = 0x00000142u;   // DP_DTO0_MODULO (read only here)
constexpr uint32_t kRegRateDiv    = 0x0000012Fu;   // OTG_PIXEL_RATE_DIV (read only here; DPDTO0_INT is bits 4:1)
constexpr uint32_t kRegHTotal     = 0x00004FEAu;   // OTG0_OTG_H_TOTAL (total - 1), read only here
constexpr uint32_t kRegVTotal     = 0x00004FEFu;   // OTG0_OTG_V_TOTAL (total - 1)
constexpr uint32_t kRegVTotalMin  = 0x00004FF0u;   // OTG0_OTG_V_TOTAL_MIN (total - 1)
constexpr uint32_t kRegVTotalMax  = 0x00004FF1u;   // OTG0_OTG_V_TOTAL_MAX (total - 1)
constexpr uint32_t kRegStatusPos  = 0x0000500Au;   // OTG0_OTG_STATUS_POSITION: VERT_COUNT b14:0
constexpr uint32_t kRegDbCtrl     = 0x0000501Cu;   // OTG0_OTG_DOUBLE_BUFFER_CONTROL: UPDATE_PENDING b0, DRR pending b4, TIMING pending b5, UPDATE_INSTANTLY b8, VSTARTUP pending b9, DRR mode b25:24
constexpr uint32_t kRegMasterLock = 0x00005049u;   // OTG0_OTG_MASTER_UPDATE_LOCK: MASTER_UPDATE_LOCK b0 (request), UPDATE_LOCK_STATUS b8
constexpr uint32_t kRegPipeUpd    = 0x0000505Eu;   // OTG0_OTG_PIPE_UPDATE_STATUS: DC_REG_UPDATE_PENDING b4
// The live DP stream on Navi 44 is DP0 (navi48_disp_profile.h kLitDp = 0; the static_assert in navi48_modetrial_pure.h pins DP0_VID at 0x55E2).
// DP_MSA_TIMING_PARAM1 sits +0x40 from DP_VID_STREAM_CNTL (DP1: 0x5746 = 0x5706 + 0x40, navi48_modetrial_tables.h). Navi 44 therefore uses
// 0x5622. The sequence reads it first and refuses unless it holds the GOP value, so a wrong address stops the verb before any write.
constexpr uint32_t kRegMsa1Navi44 = 0x00005622u;

// ---- the GOP golden (navi48_modetrial_tables.h kGold120, the 120 Hz row) and the 60 Hz target -----------------------------------------
constexpr uint32_t kHTotalReg     = 0x00000A9Fu;   // 2720 - 1
constexpr uint32_t kHTotalPix     = 2720u;
constexpr uint32_t kLinesGop      = 1525u;         // total lines of the GOP frame (120.00 Hz)
constexpr uint32_t kLinesTarget   = 3050u;         // total lines of the 60 Hz frame (59.9988 Hz at 497.75 MHz)
constexpr uint32_t kDtoPhaseGop   = 0x1DAB0FF0u;   // DP_DTO0_PHASE of the 497.75 MHz pixel clock
constexpr uint32_t kDtoModuloGop  = 0x2AEA5400u;   // DP_DTO0_MODULO
constexpr uint32_t kRateDivMask   = 0x0000001Eu;   // OTG_PIXEL_RATE_DIV field the GOP golden fixes at 0
constexpr uint32_t kMsaGop        = (kHTotalPix << 16) | kLinesGop;     // 0x0AA005F5
constexpr uint32_t kMsaTarget     = (kHTotalPix << 16) | kLinesTarget;  // 0x0AA00BEA

// ---- field masks and bounds ---------------------------------------------------------------------------------------------------------------
constexpr uint32_t kDbDrrMask     = 0x03000000u, kDbDrrShift = 24u;
constexpr uint32_t kDbPendingMask = 0x00000231u;   // bits 0, 4, 5, 9: pending flags (read-only)
constexpr uint32_t kDbInstantly   = 0x00000100u;   // UPDATE_INSTANTLY (must be clear: the write has to wait for the frame)
constexpr uint32_t kLockReq       = 0x00000001u, kLockStatus = 0x00000100u;
constexpr uint32_t kPipePending   = 0x00000010u;
constexpr uint32_t kVertMask      = 0x00007FFFu;
constexpr uint32_t kUnreadable    = 0xFFFFFFFFu;
constexpr uint32_t kLockPolls     = 100u,  kLockPollUs = 100u;      // <= 10 ms
constexpr uint32_t kPendPolls     = 1000u, kPendPollUs = 100u;      // <= 100 ms
constexpr uint32_t kWitnessUs     = 40000u, kWitnessPollUs = 20u;   // two 60 Hz frames
constexpr uint32_t kTimeoutMin    = 5u,    kTimeoutMax = 600u;      // seconds
constexpr uint32_t kWitnessFloor  = 100u;                           // a live counter above this proves the frame is scanning
constexpr uint32_t kMaxJournal    = 8u;

// ---- the ASCII kernel ABI (action numbers of the accel verb, Navi48Bringup.cpp accelExperiment; the user client admits them) -------------
constexpr uint32_t kActRefresh        = 109u;   // `refresh 60 <timeout>` / `refresh 120`: arg = hz | (timeout << 16)
constexpr uint32_t kActRefreshConfirm = 110u;   // arg 0 = `refresh confirm`, arg 1 = `refresh status` (read only)

// ---- result codes (navi48test.c prints the names; the same numbers come back in scalar output 3) -------------------------------------
enum Code : uint32_t {
    kOk = 0, kNotNavi44 = 1, kNotAdopted = 2, kPipeFailed = 3, kTimingDiffers = 4, kBadArg = 5, kLockTimeout = 6,
    kWriteRefused = 7, kReadbackMismatch = 8, kNotArmed = 9, kRestoreFailed = 10, kNoPending = 11, kStateChanged = 12,
};
inline const char *code_name(uint32_t c) {
    switch (c) {
    case kOk: return "ok";
    case kNotNavi44: return "not Navi 44";
    case kNotAdopted: return "native display pipe not adopted";
    case kPipeFailed: return "display pipe in a failed state (HUNG or thermal trip)";
    case kTimingDiffers: return "live timing differs from the expected GOP or 60 Hz timing";
    case kBadArg: return "bad argument";
    case kLockTimeout: return "OTG lock or pending wait timed out";
    case kWriteRefused: return "register write refused by the allowlist";
    case kReadbackMismatch: return "readback or witness mismatch";
    case kNotArmed: return "DCN not bound or revert timer unavailable";
    case kRestoreFailed: return "restore could not be verified";
    case kNoPending: return "no 60 Hz state awaiting confirmation";
    case kStateChanged: return "state changed during the request";
    default: return "unknown";
    }
}

// ---- the request: decoded from (action, arg) ----------------------------------------------------------------------------------------------
enum Kind : uint32_t { kReqBad = 0, kReqSet60 = 1, kReqSet120 = 2, kReqConfirm = 3, kReqStatus = 4 };
struct Request { uint32_t kind; uint32_t timeoutS; };
inline Request parse(uint32_t action, uint64_t arg) {
    if (action == kActRefresh) {
        const uint64_t hz = arg & 0xFFFFu, to = (arg >> 16) & 0xFFFFu;
        if ((arg >> 32) != 0u) return Request{ kReqBad, 0u };
        if (hz == 60u) return (to >= kTimeoutMin && to <= kTimeoutMax) ? Request{ kReqSet60, (uint32_t)to } : Request{ kReqBad, 0u };
        if (hz == 120u) return to == 0u ? Request{ kReqSet120, 0u } : Request{ kReqBad, 0u };
        return Request{ kReqBad, 0u };
    }
    if (action == kActRefreshConfirm) {
        if (arg == 0u) return Request{ kReqConfirm, 0u };
        if (arg == 1u) return Request{ kReqStatus, 0u };
    }
    return Request{ kReqBad, 0u };
}
constexpr bool is_refresh_action(uint32_t action) { return action == kActRefresh || action == kActRefreshConfirm; }
// The native-boot refusal exemption: exactly the well-formed requests (anything else stays refused or BadArgument as before).
constexpr bool native_exempt(uint32_t action, uint64_t arg) { return is_refresh_action(action) && parse(action, arg).kind != kReqBad; }

// ---- the hardware interface ---------------------------------------------------------------------------------------------------------------
struct Hw {
    void *ctx;
    uint32_t (*rd)(void *ctx, uint32_t abs);
    void (*wr)(void *ctx, uint32_t abs, uint32_t value);
    void (*delay_us)(void *ctx, uint32_t us);
    uint64_t (*now_us)(void *ctx);
    void (*log)(void *ctx, const char *what, uint32_t abs, uint32_t a, uint32_t b);   // one line per step; the kext prints it
};

// ---- the snapshot: every register the decisions read ------------------------------------------------------------------------------------
struct Snap { uint32_t hTot, vTot, vMin, vMax, msa1, dtoPhase, dtoMod, rateDiv, db, drr, lock, pipe; };
inline Snap read_snap(const Hw &hw) {
    Snap s;
    s.hTot = hw.rd(hw.ctx, kRegHTotal);
    s.vTot = hw.rd(hw.ctx, kRegVTotal);
    s.vMin = hw.rd(hw.ctx, kRegVTotalMin);
    s.vMax = hw.rd(hw.ctx, kRegVTotalMax);
    s.msa1 = hw.rd(hw.ctx, kRegMsa1Navi44);
    s.dtoPhase = hw.rd(hw.ctx, kRegDtoPhase);
    s.dtoMod = hw.rd(hw.ctx, kRegDtoModulo);
    s.rateDiv = hw.rd(hw.ctx, kRegRateDiv);
    s.db = hw.rd(hw.ctx, kRegDbCtrl);
    s.drr = (s.db == kUnreadable) ? kUnreadable : (s.db & kDbDrrMask) >> kDbDrrShift;
    s.lock = hw.rd(hw.ctx, kRegMasterLock);
    s.pipe = hw.rd(hw.ctx, kRegPipeUpd);
    return s;
}
constexpr bool readable(const Snap &s) {
    return s.hTot != kUnreadable && s.vTot != kUnreadable && s.vMin != kUnreadable && s.vMax != kUnreadable && s.msa1 != kUnreadable &&
           s.dtoPhase != kUnreadable && s.dtoMod != kUnreadable && s.rateDiv != kUnreadable && s.db != kUnreadable && s.drr != kUnreadable &&
           s.lock != kUnreadable && s.pipe != kUnreadable;
}
enum Live : uint32_t { kLiveGop = 0, kLiveTarget = 1, kLiveOther = 2 };
// Exact classification. Every field of the golden must match; no lock, no pending flag, no DRR mode 2 may be left behind.
inline uint32_t classify(const Snap &s) {
    if (!readable(s)) return kLiveOther;
    // DRR mode 0 (the GOP) or 2 (start of frame): the apply records the mode it found and restores exactly that one.
    const bool quiet = (s.lock & (kLockReq | kLockStatus)) == 0u && (s.pipe & kPipePending) == 0u && (s.db & kDbPendingMask) == 0u &&
                       (s.db & kDbInstantly) == 0u && (s.drr == 0u || s.drr == 2u);
    const bool clocks = s.hTot == kHTotalReg && s.dtoPhase == kDtoPhaseGop && s.dtoMod == kDtoModuloGop && (s.rateDiv & kRateDivMask) == 0u;
    if (!quiet || !clocks) return kLiveOther;
    if (s.vTot == kLinesGop - 1u && s.vMin == kLinesGop - 1u && s.vMax == kLinesGop - 1u && s.msa1 == kMsaGop) return kLiveGop;
    if (s.vTot == kLinesTarget - 1u && s.vMin == kLinesTarget - 1u && s.vMax == kLinesTarget - 1u && s.msa1 == kMsaTarget) return kLiveTarget;
    return kLiveOther;
}

// ---- the locked sequence --------------------------------------------------------------------------------------------------------------
struct Entry { uint32_t abs, oldv, newv; };
struct Journal { Entry e[kMaxJournal]; uint32_t n; };
struct Outcome { uint32_t code; uint32_t vLines; uint32_t msaLines; uint32_t witnessMax; uint32_t witnessN; };

// DRR_TIMING_DBUF_UPDATE_MODE: 2 = start of frame (the lock holds the write until then), 0 = the GOP value. Pending flags are written 0.
inline uint32_t drr_set(const Hw &hw, uint32_t mode) {
    const uint32_t cur = hw.rd(hw.ctx, kRegDbCtrl);
    if (cur == kUnreadable) return kReadbackMismatch;
    const uint32_t nv = (cur & ~(kDbDrrMask | kDbPendingMask)) | (mode << kDbDrrShift);
    hw.wr(hw.ctx, kRegDbCtrl, nv);
    hw.log(hw.ctx, "drr mode", kRegDbCtrl, cur, nv);
    hw.delay_us(hw.ctx, 20u);
    const uint32_t v = hw.rd(hw.ctx, kRegDbCtrl);
    if (v == kUnreadable) return kReadbackMismatch;
    return ((v & kDbDrrMask) >> kDbDrrShift) == mode ? kOk : kReadbackMismatch;
}

// OTG_MASTER_UPDATE_LOCK: writes bit 0 only, then waits until UPDATE_LOCK_STATUS equals the request.
inline uint32_t lock_set(const Hw &hw, bool on) {
    const uint32_t cur = hw.rd(hw.ctx, kRegMasterLock);
    if (cur == kUnreadable) return kLockTimeout;
    const uint32_t nv = (cur & ~(kLockReq | kLockStatus)) | (on ? kLockReq : 0u);   // the status bit is read-only: it is written 0
    hw.wr(hw.ctx, kRegMasterLock, nv);
    hw.log(hw.ctx, on ? "lock on" : "lock off", kRegMasterLock, cur, nv);
    for (uint32_t i = 0u; i < kLockPolls; i++) {
        const uint32_t s = hw.rd(hw.ctx, kRegMasterLock);
        if (s != kUnreadable && ((s & kLockStatus) != 0u) == on) return kOk;
        hw.delay_us(hw.ctx, kLockPollUs);
    }
    return kLockTimeout;
}

// Waits until the double-buffer pending flags and the PIPE_UPDATE pending flag are clear.
inline uint32_t wait_pending(const Hw &hw) {
    for (uint32_t i = 0u; i < kPendPolls; i++) {
        const uint32_t db = hw.rd(hw.ctx, kRegDbCtrl);
        const uint32_t pu = hw.rd(hw.ctx, kRegPipeUpd);
        if (db == kUnreadable || pu == kUnreadable) return kLockTimeout;
        if ((db & kDbPendingMask) == 0u && (pu & kPipePending) == 0u) return kOk;
        hw.delay_us(hw.ctx, kPendPollUs);
    }
    return kLockTimeout;
}

// The witness: the largest VERT_COUNT seen over kWitnessUs, and how many samples were readable.
inline void witness(const Hw &hw, uint32_t *vmax, uint32_t *n) {
    const uint64_t t0 = hw.now_us(hw.ctx);
    uint32_t mx = 0u, cnt = 0u;
    while (hw.now_us(hw.ctx) - t0 < kWitnessUs) {
        const uint32_t v = hw.rd(hw.ctx, kRegStatusPos);
        if (v != kUnreadable) { const uint32_t c = v & kVertMask; cnt++; if (c > mx) mx = c; }
        hw.delay_us(hw.ctx, kWitnessPollUs);
    }
    *vmax = mx;
    *n = cnt;
}

// One write, recorded first. Returns kOk when the register reads back as written.
inline uint32_t write_verify(const Hw &hw, Journal &j, uint32_t abs, uint32_t oldv, uint32_t newv) {
    if (j.n >= kMaxJournal) return kWriteRefused;
    j.e[j.n++] = Entry{ abs, oldv, newv };
    hw.wr(hw.ctx, abs, newv);
    hw.log(hw.ctx, "write", abs, oldv, newv);
    const uint32_t back = hw.rd(hw.ctx, abs);
    if (back == kUnreadable) return kReadbackMismatch;
    return back == newv ? kOk : kReadbackMismatch;
}

// The ROLLBACK: every recorded write back to its old value, newest first, under the lock; then unlock, pending wait, and the DRR mode
// the snapshot recorded. It always unlocks, even when nothing was written. It returns kOk only when every register reads back as it did
// before the apply: every entry is put back even after an earlier mismatch.
inline uint32_t rollback(const Hw &hw, const Snap &before, const Journal &j) {
    bool bad = false;
    if (j.n != 0u) {
        if (drr_set(hw, 2u) != kOk) bad = true;
        if (lock_set(hw, true) != kOk) bad = true;
        for (uint32_t k = j.n; k-- > 0u;) {
            const Entry &e = j.e[k];
            hw.wr(hw.ctx, e.abs, e.oldv);
            hw.log(hw.ctx, "restore write", e.abs, e.newv, e.oldv);
            if (hw.rd(hw.ctx, e.abs) != e.oldv) bad = true;
        }
    }
    if (lock_set(hw, false) != kOk) bad = true;
    if (wait_pending(hw) != kOk) bad = true;
    if (drr_set(hw, before.drr) != kOk) bad = true;
    const Snap after = read_snap(hw);
    if (!readable(after) || after.vTot != before.vTot || after.vMin != before.vMin || after.vMax != before.vMax || after.msa1 != before.msa1 ||
        after.drr != before.drr || (after.lock & kLockReq) != 0u)
        bad = true;
    return bad ? kRestoreFailed : kOk;
}

// apply(): the sequence above. `cur` is the snapshot the decision was taken from; `lines` is the new frame total; `growth` is true for set 60.
inline Outcome apply(const Hw &hw, const Snap &cur, uint32_t lines, bool growth) {
    Outcome o{ kOk, 0u, 0u, 0u, 0u };
    Journal j{};
    j.n = 0u;
    const uint32_t newV = lines - 1u;
    const uint32_t newMsa = (cur.msa1 & 0xFFFF0000u) | lines;
    uint32_t rc = drr_set(hw, 2u);                                  // step 1
    bool locked = false;
    if (rc == kOk) {
        rc = lock_set(hw, true);                                    // step 2 (the request is out even when the wait timed out: it is cleared below)
        locked = true;
    }
    if (rc == kOk) rc = write_verify(hw, j, kRegVTotal, cur.vTot, newV);                // step 3
    if (rc == kOk) rc = write_verify(hw, j, kRegVTotalMin, cur.vMin, newV);
    if (rc == kOk) rc = write_verify(hw, j, kRegVTotalMax, cur.vMax, newV);
    if (locked) {                                                   // step 4: the unlock happens on every exit of the writes
        const uint32_t u = lock_set(hw, false);
        if (u != kOk) { o.code = kLockTimeout; return o; }          // state uncertain: no further write, the kext reports it
    }
    if (rc == kOk) rc = wait_pending(hw);                           // step 5
    if (rc == kOk) {                                                // step 6
        uint32_t vmax = 0u, n = 0u;
        witness(hw, &vmax, &n);
        o.witnessMax = vmax;
        o.witnessN = n;
        const bool ok = growth ? (n != 0u && vmax > kLinesGop - 1u && vmax <= kLinesTarget - 1u)
                               : (n != 0u && vmax <= kLinesGop - 1u && vmax > kWitnessFloor);
        if (!ok) rc = kReadbackMismatch;
    }
    if (rc == kOk) rc = write_verify(hw, j, kRegMsa1Navi44, cur.msa1, newMsa);      // step 7
    if (rc == kOk) rc = drr_set(hw, cur.drr);                                       // step 8: the DRR mode the snapshot recorded
    if (rc == kOk) {                                                                // step 9
        const Snap after = read_snap(hw);
        const uint32_t want = growth ? kLiveTarget : kLiveGop;
        if (classify(after) != want || after.drr != cur.drr) rc = kReadbackMismatch;
    }
    if (rc != kOk) {
        const uint32_t rb = rollback(hw, cur, j);
        o.code = (rb == kOk) ? rc : kRestoreFailed;
        return o;
    }
    o.code = kOk;
    o.vLines = lines;
    o.msaLines = lines;
    return o;
}

// set 60: from the GOP timing only. The 60 Hz target again is a no-op success; anything else refuses without a write.
inline Outcome set60(const Hw &hw, const Snap &cur) {
    const uint32_t live = classify(cur);
    if (live == kLiveTarget) return Outcome{ kOk, kLinesTarget, kLinesTarget, 0u, 0u };
    if (live != kLiveGop) return Outcome{ kTimingDiffers, 0u, 0u, 0u, 0u };
    return apply(hw, cur, kLinesTarget, true);
}
// restore 120: from the 60 Hz target only. The GOP timing again is a no-op success; anything else refuses without a write.
inline Outcome restore120(const Hw &hw, const Snap &cur) {
    const uint32_t live = classify(cur);
    if (live == kLiveGop) return Outcome{ kOk, kLinesGop, kLinesGop, 0u, 0u };
    if (live != kLiveTarget) return Outcome{ kTimingDiffers, 0u, 0u, 0u, 0u };
    return apply(hw, cur, kLinesGop, false);
}

// ---- the session: the phase of the 60 Hz state and its revert deadline (kernel state; host-tested here) ------------------------------------
enum Phase : uint32_t { kPhaseGop120 = 0, kPhasePending60 = 1, kPhaseConfirmed60 = 2 };
struct Session { uint32_t phase; uint64_t deadlineUs; uint32_t timeoutS; uint32_t reverts; uint32_t confirms; };
inline void session_begin(Session &s, uint32_t timeoutS, uint64_t nowUs) {
    s.phase = kPhasePending60;
    s.timeoutS = timeoutS;
    s.deadlineUs = nowUs + (uint64_t)timeoutS * 1000000ull;
}
inline void session_gop(Session &s) { s.phase = kPhaseGop120; s.timeoutS = 0u; s.deadlineUs = 0u; }
// What the verb returns in scalar outputs 3..9 (the kext copies them; navi48test.c reads them by these names).
struct Report { uint32_t code, hz, remaining, vLines, msaLines, phase, witnessMax; };
// Seconds until the automatic revert, rounded up; 0 when no revert is pending.
inline uint32_t remaining_s(const Session &s, uint64_t nowUs) {
    if (s.phase != kPhasePending60 || nowUs >= s.deadlineUs) return 0u;
    return (uint32_t)((s.deadlineUs - nowUs + 999999ull) / 1000000ull);
}

}  // namespace n48rf
