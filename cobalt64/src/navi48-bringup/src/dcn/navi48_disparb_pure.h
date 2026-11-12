//
//  navi48_disparb_pure.h - kext 0.0.673 (black band without a fixed memory clock): the display arbitration Linux programs for ONE plane on
//  DCN 4.01, decisions and sequence only. No kernel header: tests/disparb_test.cpp compiles this on the host and drives the exact sequence the
//  kext runs, over a register model. The kext supplies the callbacks (dcn/navi48_dcn.cpp disparb_hw(): reads through dcn_rreg, writes ONLY
//  through the DCN allowlist) and runs apply() once, from the display monitor thread, with gMtLock held (the mode trial / hold exclusion).
//
//  WHY. The GOP leaves a 192 KB DET for HUBP0 (DCHUBBUB_DET0_CTRL 0x303: 3 x 64 KB = about 19 lines of 2560 x 4 B = about 105 us at 5.465 us a
//  line), so the display can raise "allow UCLK p-state" only inside the 85-line vblank (464.5 us at 120 Hz) against a 404-409 us watermark:
//  almost no margin, and a switch that collides with the next frame's prefetch starves the top lines (the black band). Linux gives the single
//  plane the whole DET budget, so the switch is hidden during ACTIVE scanout ("vactive", dml2_pmo_dcn4_fams2.c strategy order) and UCLK can idle.
//
//  WHAT LINUX PROGRAMS (Linux v7.3, MIT, research/ext/amdgpu-port-study/linux-v7.3/drivers/gpu/drm/amd/display/dc; values derived below):
//   DET / COMPBUF (dml2_core_dcn4_calcs.c CalculateMaxDETAndMinCompressedBufferSize :395-430 and CalculateDETBufferSize :1009-1240):
//     MRQ present on DCN4 -> MaxTotalDET = ceil((CRB 1344 + ROB 192) x 4/5, 64) = 1280 KB = 20 segments, MinCompressedBuffer = 1344 - 1280 = 64 KB
//     = 1 segment (dcn4_soc_bb.h :341-345, dcn401_hubbub.h DCN4_01_CRB_SIZE_KB 1344 / segment 64). One non-phantom surface without unbounded
//     requesting gets the whole pool: DET0 = 20 segments, compbuf = 1 (the CRB is 21 segments: 20 + 1 = 21). Unbounded requesting (single DPP,
//     tiled, no chroma; :991-1007) would give DET = 2 swaths + compbuf = the rest; it is a HUBP mode (DCHUBP_CNTL.HUBP_UNBOUNDED_REQ_MODE b10),
//     the GOP leaves it OFF (0x000f0002), and this header never turns it on, so the bounded split 20 + 1 is the Linux answer for this HUBP state.
//   ORDER (hwss/dcn401/dcn401_hwseq.c dcn401_prepare_bandwidth :1360-1418, the pipe programming of hwss/dcn20/dcn20_hwseq.c :1965-1973 and
//     :2125-2145, dcn401_wait_for_det_buffer_update_under_otg_master :1907-1938, dcn401_optimize_bandwidth :1462-1505):
//     1. prepare: program_watermarks(safe_to_lower = false) - only RAISES; program_compbuf_segments(new, safe_to_increase = false) - only SHRINKS
//     2. the disabled pipes give their DET back (program_det_segments(inst, 0)), then the active pipe's det_size (program_det_segments(0, n))
//     3. wait_for_det_update: DET0_SIZE_CURRENT == the programmed size, REG_WAIT(.., 1, 100000) = 100 ms ("1 vupdate at 10hz")
//     4. optimize: program_watermarks(safe_to_lower = true) - now the lowered values too; program_compbuf_segments(new, true) - a GROW waits for
//        every DETn_SIZE_CURRENT == DETn_SIZE first (REG_WAIT 1 us x 100 each, hubbub/dcn401/dcn401_hubbub.c :1156-1173)
//     For this transition the compbuf target (1) equals the GOP's (1): steps 1 and 4 write no compbuf (the preflight refuses any other compbuf).
//   WATERMARKS (hubbub/dcn401/dcn401_hubbub.c hubbub401_program_urgent/stutter/pstate_watermarks :67-411; dml2_dpmm_dcn4.c
//     dpmm_dcn4_map_watermarks :800-840: sets A and B identical, num_watermark_sets = 2, so there are no C/D sets on DCN 4.01). DCHUB refclk 50 MHz
//     (dcn4_soc_bb.h dchub_refclk_mhz; DCHUBBUB_GLOBAL_TIMER_CNTL REFDIV 2 from the 100 MHz reference, hubbub2_get_dchub_ref_freq). The values are
//     DML's (dml2_core_dcn4_calcs.c CalculateWatermarksMALLUseAndDRAMSpeedChangeSupport :6778-6802) as Linux printed them on this card
//     (research/hw_dump/dm_dtn_log.txt: urgent 8.800, sr_enter 57.920, sr_exit 44.920, dram_clk_change 408.800 us):
//       urgent = UrgentLatency + ExtraLatency                          8.8 us   ->   440   (also REFCYC_PER_TRIP_TO_MEMORY and _PER_META_TRIP, :818-819)
//       uclk_pstate = dram_clk_change_blackout 400 + urgent           408.8 us  -> 20440
//       fclk_pstate = fclk_change_blackout 0 + urgent                  8.8 us   ->   440   (dcn4_soc_bb.h :289: 0 us, so the FCLK watermark is the urgent one)
//       temp_read_or_ppt = g6_temp_read_blackout (commented out = 0) + urgent -> 440  (UCLK_PSTATE_CHANGE_WATERMARK1 and FCLK_PSTATE_CHANGE_WATERMARK1)
//       sr_enter (StutterEnterPlusExit) 57.92 us -> 2896, sr_exit 44.92 us -> 2246 (also written to SR ENTER/EXIT WATERMARK1..3: "On dGPU Z states
//       are N/A", :206-213)
//     NOT written (left as the GOP has them): FRAC_URG_BW_NOM/FLIP/MALL (they are fractions of the mode's bandwidth that only the full DML has),
//     USR_RETRAINING (GDDR7/HBM retraining; the GOP has 0), DCHUBBUB_TIMEOUT_DETECTION_CTRL2 / CTRL_STATUS (dcn401_program_arbiter: FAMS2 stall
//     detection), per-HUBP DLG/TTU (DML's qos_level_high_wm = 4 lines and min_ttu_vblank do not depend on the DET size).
//     WATERMARK_CHANGE_CNTL: DCN 4.01 has separate A and B registers and Linux never writes the change-select/request protocol there (it is
//     `#if 0` since dcn10_hubbub.c :611-615 and absent from hubbub401_program_watermarks), so neither do we; the register is only reported.
//   DRAM_STATE_CNTL (hubbub1_allow_self_refresh_control, dcn10_hubbub.c :91-102, called at the end of hubbub401_program_watermarks; Linux's
//     default disable_stutter is false, amdgpu_dm.c :643): SELF_REFRESH_FORCE_ENABLE b1 = 0 and FORCE_VALUE b0 = 0 (stutter allowed; the GOP leaves
//     b1 = 1: stutter forbidden). P-state FORCE_ENABLE b5 / VALUE b4 = 0 as dcn401_init_hw (:380) leaves them (they are 0 already on this card).
//
//  WHY OUR "RAISE FIRST, LOWER AFTER" COMPARES WITH THE LIVE REGISTER. Linux compares each target with its own software copy, which is zero at driver
//  load, so its first prepare writes every target at once. We compare with the value the hardware holds: a value that goes DOWN (urgent 510 -> 440)
//  waits until the DET is in place. That is the stricter reading of the same rule.
//
//  SAFETY. apply() refuses with NO write when anything is not the single-pipe GOP layout it was written for (preflight()). A DET that does not
//  settle within 100 ms is rolled back (DET0 to its old size, waited for, then DET1..3 back). Every write goes through Hw.wr, which is the DCN
//  allowlist in the kext (DCHUBBUB 0x392f..0x3de1 is an allowlisted range); a refused write stops the sequence and rolls back what it can.
//  Kill switches (read by the kext): navi48-det=0 (no DET/COMPBUF write), navi48-wm=0 (no watermark write), navi48-sr=0 (keep the GOP's stutter
//  force-off). Defaults: all ON.
//
#pragma once
#include <stdint.h>

namespace n48arb {

// ---- registers: ABSOLUTE BAR5 dwords = DMU segment 2 base 0x34C0 + dcn_4_1_0_offset.h (the census and ufmon use the same convention) ----------
constexpr uint32_t kSeg2 = 0x34C0u;
constexpr uint32_t kRegCompbuf     = kSeg2 + 0x04BAu;   // 0x397A DCHUBBUB_COMPBUF_CTRL: COMPBUF_SIZE b4:0, COMPBUF_SIZE_CURRENT b12:8, CONFIG_ERROR b31
constexpr uint32_t kRegDet0        = kSeg2 + 0x04BBu;   // 0x397B DCHUBBUB_DET0_CTRL: DET0_SIZE b4:0, DET0_SIZE_CURRENT b12:8 (DET1..3 follow)
constexpr uint32_t kRegDramState   = kSeg2 + 0x04FCu;   // 0x39BC DCHUBBUB_ARB_DRAM_STATE_CNTL
constexpr uint32_t kRegWmChange    = kSeg2 + 0x0524u;   // 0x39E4 DCHUBBUB_ARB_WATERMARK_CHANGE_CNTL (read only here)
constexpr uint32_t kRegGlobalTimer = kSeg2 + 0x0527u;   // 0x39E7 DCHUBBUB_GLOBAL_TIMER_CNTL: REFDIV b3:0, ENABLE b12
constexpr uint32_t kRegHubp0Cntl   = 0x3AB4u;           // HUBP0_DCHUBP_CNTL: HUBP_BLANK_EN b0, HUBP_UNBOUNDED_REQ_MODE b10
constexpr uint32_t reg_det(uint32_t i) { return kRegDet0 + i; }
static_assert(kRegCompbuf == 0x397Au && kRegDet0 == 0x397Bu && kRegDramState == 0x39BCu && kRegWmChange == 0x39E4u && kRegGlobalTimer == 0x39E7u,
              "the addresses of the 2026-11-12 live read (research/builds/macos-20261112/regdump/dchubbub-wm-120hz.txt)");

// ---- field layout (dcn_4_1_0_sh_mask.h :5913-5938, :6544-6565, :6094-6098, :7192-7209) ---------------------------------------------------------
constexpr uint32_t kSizeMask = 0x1Fu, kCurShift = 8u;
constexpr uint32_t size_of(uint32_t v) { return v & kSizeMask; }
constexpr uint32_t cur_of(uint32_t v) { return (v >> kCurShift) & kSizeMask; }
constexpr uint32_t with_size(uint32_t v, uint32_t seg) { return (v & ~kSizeMask) | (seg & kSizeMask); }   // REG_UPDATE(.., SIZE, seg)
constexpr uint32_t kCompbufConfigError = 0x80000000u;
constexpr uint32_t kDramSrForceValue = 0x1u, kDramSrForceEnable = 0x2u, kDramPstateForceValue = 0x10u, kDramPstateForceEnable = 0x20u;
constexpr uint32_t kHubpUnbounded = 0x400u, kHubpBlank = 0x1u;
constexpr bool unreadable(uint32_t v) { return v == 0xFFFFFFFFu; }

// ---- the CRB arithmetic (DML, see the header) ------------------------------------------------------------------------------------------------------
constexpr uint32_t kCrbKb = 1344u, kRobKb = 192u, kSegKb = 64u, kMaxPipes = 4u;
constexpr uint32_t max_total_det_kb() { return (((kCrbKb + kRobKb) * 4u + 5u * kSegKb - 1u) / (5u * kSegKb)) * kSegKb; }   // ceil((1344+192)*4/5, 64)
constexpr uint32_t kCrbSegs = kCrbKb / kSegKb;                                  // 21
constexpr uint32_t kDetTargetSegs = max_total_det_kb() / kSegKb;                // 20
constexpr uint32_t kCompbufSegs = (kCrbKb - max_total_det_kb()) / kSegKb;       // 1 (MinCompressedBufferSizeInKByte)
static_assert(max_total_det_kb() == 1280u && kCrbSegs == 21u && kDetTargetSegs == 20u && kCompbufSegs == 1u, "DML: 1280 KB DET + 64 KB compbuf = 1344 KB CRB");
static_assert(kDetTargetSegs + kCompbufSegs <= kCrbSegs, "the target layout fits the CRB (dcn401_program_det_segments' check)");
static_assert(kDetTargetSegs <= kSizeMask, "DET0_SIZE is 5 bits");
// What a size buys at 2560 x 4 B a line, 5.4646 us a line (reported, not used by the sequence)
constexpr uint32_t lines_of(uint32_t segs) { return segs * kSegKb * 1024u / (2560u * 4u); }

// ---- the watermarks: Linux's values for this card in DCHUB refclk cycles (50 MHz), sets A and B identical ----------------------------------------
constexpr uint32_t kRefclkMhz = 50u;
constexpr uint32_t cycles_ns(uint32_t ns) { return ns * kRefclkMhz / 1000u; }
constexpr uint32_t kUrgentNs = 8800u, kSrEnterNs = 57920u, kSrExitNs = 44920u, kUclkNs = 408800u, kFclkNs = 0u + kUrgentNs, kTempReadNs = 0u + kUrgentNs;
static_assert(cycles_ns(kUrgentNs) == 440u && cycles_ns(kSrEnterNs) == 2896u && cycles_ns(kSrExitNs) == 2246u && cycles_ns(kUclkNs) == 20440u,
              "the DTN log's microseconds x 50 MHz");
constexpr uint32_t kSetBDelta = 0x13u;   // every set-B register is the set-A one + 0x13 (dcn_4_1_0_offset.h :1592-1667)
enum WmGroup : uint32_t { kGUrgent = 0, kGStutter = 1, kGPstate = 2 };
struct WmReg { uint32_t offA; uint32_t mask; uint32_t ns; uint32_t group; const char *name; };
constexpr WmReg kWm[] = {
    { 0x04FEu, 0x3FFFu, kUrgentNs,   kGUrgent,  "DATA_URGENCY_WATERMARK" },
    { 0x0500u, 0x3FFFu, kUrgentNs,   kGUrgent,  "REFCYC_PER_TRIP_TO_MEMORY" },
    { 0x0501u, 0x3FFFu, kUrgentNs,   kGUrgent,  "REFCYC_PER_META_TRIP" },
    { 0x0502u, 0xFFFFu, kSrEnterNs,  kGStutter, "ALLOW_SR_ENTER_WATERMARK" },
    { 0x0503u, 0xFFFFu, kSrExitNs,   kGStutter, "ALLOW_SR_EXIT_WATERMARK" },
    { 0x0504u, 0xFFFFu, kSrEnterNs,  kGStutter, "ALLOW_SR_ENTER_WATERMARK1" },
    { 0x0505u, 0xFFFFu, kSrExitNs,   kGStutter, "ALLOW_SR_EXIT_WATERMARK1" },
    { 0x0506u, 0xFFFFu, kSrEnterNs,  kGStutter, "ALLOW_SR_ENTER_WATERMARK2" },
    { 0x0507u, 0xFFFFu, kSrExitNs,   kGStutter, "ALLOW_SR_EXIT_WATERMARK2" },
    { 0x0508u, 0xFFFFu, kSrEnterNs,  kGStutter, "ALLOW_SR_ENTER_WATERMARK3" },
    { 0x0509u, 0xFFFFu, kSrExitNs,   kGStutter, "ALLOW_SR_EXIT_WATERMARK3" },
    { 0x050Au, 0xFFFFu, kUclkNs,     kGPstate,  "UCLK_PSTATE_CHANGE_WATERMARK" },
    { 0x050Bu, 0xFFFFu, kTempReadNs, kGPstate,  "UCLK_PSTATE_CHANGE_WATERMARK1" },
    { 0x050Cu, 0xFFFFu, kFclkNs,     kGPstate,  "FCLK_PSTATE_CHANGE_WATERMARK" },
    { 0x050Du, 0xFFFFu, kTempReadNs, kGPstate,  "FCLK_PSTATE_CHANGE_WATERMARK1" },
};
constexpr uint32_t kWmPerSet = sizeof(kWm) / sizeof(kWm[0]);   // 15
constexpr uint32_t kWmRegs = 2u * kWmPerSet;                    // sets A and B
constexpr uint32_t wm_abs(uint32_t i) { return kSeg2 + kWm[i % kWmPerSet].offA + (i >= kWmPerSet ? kSetBDelta : 0u); }
constexpr uint32_t wm_target(uint32_t i) { return cycles_ns(kWm[i % kWmPerSet].ns) & kWm[i % kWmPerSet].mask; }
static_assert(kSeg2 + 0x050Au == 0x39CAu && kSeg2 + 0x050Au + kSetBDelta == 0x39DDu && kSeg2 + 0x0502u + kSetBDelta == 0x39D5u && kSeg2 + 0x04FEu + kSetBDelta == 0x39D1u,
              "UCLK WM A/B 0x39CA/0x39DD, SR enter B 0x39D5, urgent B 0x39D1 (the live read)");

// ---- the callbacks (the kext: dcn_rreg / the allowlisted write / IODelay / N48LOG) ----------------------------------------------------------------
struct Hw {
    void *ctx;
    uint32_t (*rd)(void *ctx, uint32_t abs);
    bool (*wr)(void *ctx, uint32_t abs, uint32_t v);          // false = the allowlist refused it (nothing reached the hardware)
    void (*delay_us)(void *ctx, uint32_t us);
    void (*log)(void *ctx, const char *what, uint32_t abs, uint32_t before, uint32_t after);
};

struct Cfg { bool det, wm, sr; };
// The switches: only an explicit 0 turns a step off (absent or any other value = ON).
constexpr bool enabled(bool present, uint32_t value) { return !(present && value == 0u); }

enum DetVerdict : uint32_t {
    kDetNotRun = 0, kDetOff, kDetDone, kDetAlready,
    kDetUnreadable, kDetPending, kDetOtherPipe, kDetCompbuf, kDetConfigError, kDetUnbounded, kDetNoPipe0, kDetPlaneBlank,
    kDetRefused, kDetTimeoutRolledBack, kDetRollbackFailed,
};
constexpr const char *det_name(uint32_t v) {
    return v == kDetNotRun ? "not-run" : v == kDetOff ? "off (navi48-det=0)" : v == kDetDone ? "resized" : v == kDetAlready ? "already-linux-size" :
           v == kDetUnreadable ? "refused: unreadable register" : v == kDetPending ? "refused: a DET/COMPBUF resize is pending" :
           v == kDetOtherPipe ? "refused: another pipe holds DET (DETn_SIZE_CURRENT != 0)" : v == kDetCompbuf ? "refused: COMPBUF is not 1 segment" :
           v == kDetConfigError ? "refused: COMPBUF CONFIG_ERROR set" : v == kDetUnbounded ? "refused: HUBP0 in unbounded-request mode" :
           v == kDetNoPipe0 ? "refused: HUBP0 holds no DET" : v == kDetPlaneBlank ? "refused: HUBP0 is blanked" :
           v == kDetRefused ? "write refused by the allowlist (rolled back)" : v == kDetTimeoutRolledBack ? "DET0_SIZE_CURRENT did not follow in 100 ms: rolled back" :
           v == kDetRollbackFailed ? "ROLLBACK FAILED (DET state uncertain)" : "?";
}
enum WmVerdict : uint32_t { kWmNotRun = 0, kWmOff, kWmDone, kWmUnreadable, kWmRefclk, kWmRefused, kWmMismatch };
constexpr const char *wm_name(uint32_t v) {
    return v == kWmNotRun ? "not-run" : v == kWmOff ? "off (navi48-wm=0)" : v == kWmDone ? "programmed" : v == kWmUnreadable ? "refused: unreadable register" :
           v == kWmRefclk ? "refused: DCHUB refclk is not 50 MHz (GLOBAL_TIMER REFDIV/ENABLE)" : v == kWmRefused ? "write refused by the allowlist" :
           v == kWmMismatch ? "read-back differs" : "?";
}

struct Snap {
    uint32_t compbuf, det[kMaxPipes], dram, wmChange, timer, hubp0;
    uint32_t wm[kWmRegs];
};
inline Snap read_snap(const Hw &hw) {
    Snap s{};
    s.compbuf = hw.rd(hw.ctx, kRegCompbuf);
    for (uint32_t i = 0; i < kMaxPipes; i++) s.det[i] = hw.rd(hw.ctx, reg_det(i));
    s.dram = hw.rd(hw.ctx, kRegDramState); s.wmChange = hw.rd(hw.ctx, kRegWmChange); s.timer = hw.rd(hw.ctx, kRegGlobalTimer); s.hubp0 = hw.rd(hw.ctx, kRegHubp0Cntl);
    for (uint32_t i = 0; i < kWmRegs; i++) s.wm[i] = hw.rd(hw.ctx, wm_abs(i));
    return s;
}

// The single-pipe GOP layout this sequence was written for. Reads only.
inline uint32_t det_preflight(const Snap &s) {
    if (unreadable(s.compbuf) || unreadable(s.hubp0)) return kDetUnreadable;
    for (uint32_t i = 0; i < kMaxPipes; i++) if (unreadable(s.det[i])) return kDetUnreadable;
    if ((s.compbuf & kCompbufConfigError) != 0u) return kDetConfigError;
    if (size_of(s.compbuf) != cur_of(s.compbuf) || size_of(s.det[0]) != cur_of(s.det[0])) return kDetPending;
    for (uint32_t i = 1; i < kMaxPipes; i++) if (cur_of(s.det[i]) != 0u) return kDetOtherPipe;
    if (size_of(s.compbuf) != kCompbufSegs) return kDetCompbuf;
    if (cur_of(s.det[0]) == 0u) return kDetNoPipe0;
    if ((s.hubp0 & kHubpUnbounded) != 0u) return kDetUnbounded;
    if ((s.hubp0 & kHubpBlank) != 0u) return kDetPlaneBlank;
    if (size_of(s.det[0]) == kDetTargetSegs) {
        bool othersFree = true;
        for (uint32_t i = 1; i < kMaxPipes; i++) othersFree = othersFree && size_of(s.det[i]) == 0u;
        if (othersFree) return kDetAlready;
    }
    return kDetDone;   // = go
}
inline bool refclk_ok(uint32_t timer) { return !unreadable(timer) && (timer & 0xFu) == 2u && (timer & 0x1000u) != 0u; }

struct Result {
    uint32_t det, wm;
    Snap before, after;
    uint32_t detWaitUs, writes, refusedWrites, raised, lowered;
    bool srAllowed;
};

namespace detail {
inline bool w(const Hw &hw, Result &r, const char *what, uint32_t abs, uint32_t before, uint32_t v) {
    const bool ok = hw.wr(hw.ctx, abs, v);
    hw.log(hw.ctx, what, abs, before, v);
    if (ok) r.writes++; else r.refusedWrites++;
    return ok;
}
// REG_WAIT(DETn_CTRL, DETn_SIZE_CURRENT, want, 1, 100000): 100 ms; polled every 100 us (the frame is 8.3 ms at 120 Hz).
inline bool wait_cur(const Hw &hw, uint32_t abs, uint32_t want, uint32_t *waitedUs) {
    for (uint32_t t = 0; t <= 100000u; t += 100u) {
        const uint32_t v = hw.rd(hw.ctx, abs);
        if (!unreadable(v) && cur_of(v) == want) { if (waitedUs) *waitedUs = t; return true; }
        hw.delay_us(hw.ctx, 100u);
    }
    if (waitedUs) *waitedUs = 100000u;
    return false;
}
// Watermarks: lower = false is Linux's prepare (only raise), true its optimize (every target). Returns false on a refused write.
inline bool program_wm(const Hw &hw, Result &r, const Snap &s, bool lower) {
    for (uint32_t i = 0; i < kWmRegs; i++) {
        const uint32_t cur = hw.rd(hw.ctx, wm_abs(i)) & kWm[i % kWmPerSet].mask, tgt = wm_target(i);
        if (tgt == cur || (!lower && tgt < cur)) continue;
        if (!w(hw, r, lower ? "wm-optimize" : "wm-prepare", wm_abs(i), s.wm[i], tgt)) return false;
        if (tgt > cur) r.raised++; else r.lowered++;
    }
    return true;
}
// The rollback of the DET: DET0 back first (it is the one that grew), waited for, then DET1..3 back.
inline bool det_rollback(const Hw &hw, Result &r, const Snap &s) {
    const uint32_t d0 = hw.rd(hw.ctx, reg_det(0));
    bool ok = !unreadable(d0);
    if (ok && size_of(d0) != size_of(s.det[0])) ok = w(hw, r, "det-rollback", reg_det(0), d0, with_size(d0, size_of(s.det[0])));   // (a refused grow never landed)
    ok = ok && wait_cur(hw, reg_det(0), size_of(s.det[0]), nullptr);
    for (uint32_t i = 1; i < kMaxPipes; i++) {
        const uint32_t v = hw.rd(hw.ctx, reg_det(i));
        if (unreadable(v)) { ok = false; continue; }
        if (size_of(v) != size_of(s.det[i])) ok = w(hw, r, "det-rollback", reg_det(i), v, with_size(v, size_of(s.det[i]))) && ok;
    }
    return ok;
}
}  // namespace detail

// The whole sequence. Called once per boot by the kext (the monitor thread, gMtLock held, no other lock).
inline Result apply(const Hw &hw, const Cfg &c) {
    using namespace detail;
    Result r{};
    r.before = read_snap(hw);
    const Snap &s = r.before;
    r.det = c.det ? det_preflight(s) : (uint32_t)kDetOff;
    const bool doDet = r.det == kDetDone;   // det_preflight's "go" is kDetDone; kDetAlready and every refusal write nothing
    r.wm = !c.wm ? (uint32_t)kWmOff : !refclk_ok(s.timer) ? (unreadable(s.timer) ? (uint32_t)kWmUnreadable : (uint32_t)kWmRefclk) : (uint32_t)kWmDone;
    for (uint32_t i = 0; i < kWmRegs && r.wm == kWmDone; i++) if (unreadable(s.wm[i])) r.wm = kWmUnreadable;
    if (r.wm == kWmDone && unreadable(s.dram)) r.wm = kWmUnreadable;
    const bool doWm = r.wm == kWmDone;
    // 1. prepare: raise only (dcn401_prepare_bandwidth -> hubbub401_program_watermarks(.., false)). compbuf shrink: none (target 1 = current 1).
    if (doWm && !program_wm(hw, r, s, false)) r.wm = kWmRefused;
    // 2. the DET: the free pipes give theirs back, then HUBP0 takes the Linux size (dcn20_program_pipe / dcn20_program_front_end_for_ctx order)
    if (doDet) {
        bool ok = true;
        for (uint32_t i = 1; i < kMaxPipes && ok; i++)
            if (size_of(s.det[i]) != 0u) ok = w(hw, r, "det-release", reg_det(i), s.det[i], with_size(s.det[i], 0u));
        if (ok) ok = w(hw, r, "det-grow", reg_det(0), s.det[0], with_size(s.det[0], kDetTargetSegs));
        // 3. dcn401_wait_for_det_update(hubp 0)
        if (ok && wait_cur(hw, reg_det(0), kDetTargetSegs, &r.detWaitUs)) {
            r.det = kDetDone;
        } else {
            const bool rb = det_rollback(hw, r, s);
            r.det = !rb ? (uint32_t)kDetRollbackFailed : !ok ? (uint32_t)kDetRefused : (uint32_t)kDetTimeoutRolledBack;
        }
        // 4a. compbuf grow (safe_to_increase): target 1 = current 1, nothing to write (the preflight pinned it).
    }
    // 4b. optimize: every target (the lowered ones too), then the self-refresh control of hubbub401_program_watermarks.
    if (r.wm == kWmDone) {
        if (!program_wm(hw, r, s, true)) r.wm = kWmRefused;
    }
    if (r.wm == kWmDone) {
        const uint32_t d = hw.rd(hw.ctx, kRegDramState);
        uint32_t nd = d & ~(kDramPstateForceEnable | kDramPstateForceValue);            // dcn401_init_hw: force_pstate_change_control(false, false)
        if (c.sr) nd &= ~(kDramSrForceEnable | kDramSrForceValue);                       // hubbub1_allow_self_refresh_control(allow = true)
        if (!unreadable(d) && nd != d && !w(hw, r, "dram-state", kRegDramState, d, nd)) r.wm = kWmRefused;
    }
    r.after = read_snap(hw);
    if (r.wm == kWmDone) {
        for (uint32_t i = 0; i < kWmRegs; i++) if ((r.after.wm[i] & kWm[i % kWmPerSet].mask) != wm_target(i)) r.wm = kWmMismatch;
        const uint32_t force = kDramPstateForceEnable | kDramPstateForceValue | (c.sr ? (kDramSrForceEnable | kDramSrForceValue) : 0u);
        if ((r.after.dram & force) != 0u) r.wm = kWmMismatch;
    }
    r.srAllowed = !unreadable(r.after.dram) && (r.after.dram & kDramSrForceEnable) == 0u;
    return r;
}

}  // namespace n48arb
