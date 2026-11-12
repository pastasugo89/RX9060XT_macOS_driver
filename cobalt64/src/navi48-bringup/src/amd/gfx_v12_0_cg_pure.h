//
//  gfx_v12_0_cg_pure.h - kext 0.0.675: GFX clock gating on GC 12.0.0, the PURE half (sequence and decisions only, no kernel header).
//  tests/gfx_cg675_test.cpp compiles this on the host and drives the exact sequence the kext runs (amd/gfx_v12_0_cg.cpp) over a register model.
//
//  PORTED FROM Linux v7.3 drivers/gpu/drm/amd/amdgpu/gfx_v12_0.c (research/ext/amdgpu-port-study/drm-kmod/drivers/gpu/drm/amd), MIT license:
//    Copyright 2023 Advanced Micro Devices, Inc.
//    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the
//    "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish,
//    distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
//    following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
//    Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
//  Functions ported (same order, same read-modify-write, same "write only if changed" rule where Linux has it):
//    gfx_v12_0_update_gfx_clock_gating        gfx_v12_0.c:4083-4109  (safe mode, coarse, medium, repeater FGCG, SRAM FGCG, perf clk, GUI idle int)
//    gfx_v12_0_update_coarse_grain_clock_gating :3892-4007
//    gfx_v12_0_update_medium_grain_clock_gating :4009-4041
//    gfx_v12_0_update_repeater_fgcg            :4043-4062
//    gfx_v12_0_update_sram_fgcg                :4064-4081
//    gfx_v12_0_update_perf_clk                 :3797-3815
//    gfx_v12_0_enable_gui_idle_interrupt       :1757-1783 (with gfx_v12_0_get_cpg_int_cntl :1719-1734: me 0 pipe 0 -> CP_INT_CNTL_RING0 only;
//                                                         gfx_v12_0_sw_init :1349-1350 / :1357-1358: num_me = 1, num_pipe_per_me = 1)
//    gfx_v12_0_set_safe_mode / unset_safe_mode :3771-3795, with amdgpu_gfx_rlc_enter/exit_safe_mode (amdgpu_rlc.c:38-78: only when the RLC
//                                                         is enabled, RLC_CNTL.RLC_ENABLE_F32, and cg_flags has CGCG, MGCG or 3D_CGCG)
//    cg_flags of GC 12.0.0: soc24.c:390-404 (the GFX bits; ATHUB / MC / HDP gating are other IP blocks and are NOT done here)
//    Called by Linux from amdgpu_device_ip_late_init -> amdgpu_device_set_cg_state(GATE) (amdgpu_device.c:3302, 3154-3188) ->
//    gfx_v12_0_set_clockgating_state (gfx_v12_0.c:4111-4128, GC 12.0.0 and 12.0.1 only).
//
//  Register offsets and fields: Linux include/asic_reg/gc/gc_12_0_0_offset.h and gc_12_0_0_sh_mask.h (line numbers next to each constant).
//  The dword address of a register is GC base[BASE_IDX] + offset (SOC15_REG_OFFSET); this card's GC bases are idx0 0x1260, idx1 0xA000.
//
//  Deviations from Linux (each one conservative, none changes a value Linux writes):
//    D1. The RLC must be enabled (RLC_CNTL.RLC_ENABLE_F32). Linux would skip only the safe-mode bracket and still program the gating; we
//        program NOTHING and report kRlcNotEnabled.
//    D2. Safe-mode entry is polled at most kSafeModePollUs x 1 us (Linux: adev->usec_timeout = AMDGPU_MAX_USEC_TIMEOUT = 100000 us, amdgpu.h:285,
//        and Linux CONTINUES after a timeout). We stop before the first gating write, issue Linux's exit write (CMD only) and report
//        kSafeModeTimeout.
//    D3. Options::ints = false (boot-arg navi48-cg-ints=0) leaves the CP interrupt enables (CP_INT_CNTL busy/empty/cmp-busy/idle and the
//        GUI-idle enables of CP_INT_CNTL_RING0) untouched. Linux always writes them; the default (ints = true) is Linux's sequence exactly.
//        The SDMA RLC_CGCG_CTRL.CGCG_INT_ENABLE (an SDMA -> RLC signal) is written either way.
//
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace n48cg {

// ---- cg_flags (Linux include/amd_shared.h:126-159) -----------------------------------------------------------------------------------------
constexpr uint64_t kCgGfxMgcg        = 1ull << 0;
constexpr uint64_t kCgGfxMgls        = 1ull << 1;
constexpr uint64_t kCgGfxCgcg        = 1ull << 2;
constexpr uint64_t kCgGfxCgls        = 1ull << 3;
constexpr uint64_t kCgGfx3dCgcg      = 1ull << 20;
constexpr uint64_t kCgGfx3dCgls      = 1ull << 21;
constexpr uint64_t kCgGfxFgcg        = 1ull << 31;
constexpr uint64_t kCgRepeaterFgcg   = 1ull << 32;
constexpr uint64_t kCgGfxPerfClk     = 1ull << 33;
// soc24.c:390-399, IP_VERSION(12, 0, 0): the GFX part of adev->cg_flags (the ATHUB_MGCG/LS, MC_MGCG/LS and HDP_SD bits are not GFX's).
constexpr uint64_t kGc1200CgFlags = kCgGfxCgcg | kCgGfxCgls | kCgGfxMgcg | kCgGfx3dCgcg | kCgGfx3dCgls | kCgRepeaterFgcg | kCgGfxFgcg | kCgGfxPerfClk;

// ---- registers (gc_12_0_0_offset.h) ---------------------------------------------------------------------------------------------------------
struct Reg { uint32_t off; uint32_t idx; const char *name; };
constexpr Reg kRlcSafeMode       { 0x0980, 1, "RLC_SAFE_MODE" };            // offset.h:7015-7016
constexpr Reg kRlcCntl           { 0x4c00, 1, "RLC_CNTL" };                 // offset.h:6298-6299
constexpr Reg kRlcCgttMgcgOvr    { 0x4c48, 1, "RLC_CGTT_MGCG_OVERRIDE" };   // offset.h:6398-6399
constexpr Reg kRlcCgcgCglsCtrl   { 0x4c49, 1, "RLC_CGCG_CGLS_CTRL" };       // offset.h:6400-6401
constexpr Reg kRlcCgcgCglsCtrl3d { 0x4cc5, 1, "RLC_CGCG_CGLS_CTRL_3D" };    // offset.h:6530-6531
constexpr Reg kCpRbWptrPollCntl  { 0x0f62, 0, "CP_RB_WPTR_POLL_CNTL" };     // offset.h:2154-2155
constexpr Reg kCpIntCntl         { 0x1de9, 0, "CP_INT_CNTL" };              // offset.h:3482-3483
constexpr Reg kCpIntCntlRing0    { 0x1e0a, 0, "CP_INT_CNTL_RING0" };        // offset.h:3528-3529
constexpr Reg kSdma0RlcCgcgCtrl  { 0x0055, 0, "SDMA0_RLC_CGCG_CTRL" };      // offset.h:140-141
constexpr Reg kSdma1RlcCgcgCtrl  { 0x0655, 0, "SDMA1_RLC_CGCG_CTRL" };      // offset.h:1122-1123
// read-only context for the log (not written): offset.h:6828-6829, 2002-2003, 2130-2131, 6390-6391
constexpr Reg kRlcGpmStat        { 0x4e6c, 1, "RLC_GPM_STAT" };
constexpr Reg kGrbmStatus        { 0x0da4, 0, "GRBM_STATUS" };
constexpr Reg kCpStat            { 0x0f40, 0, "CP_STAT" };
constexpr Reg kRlcPgCntl         { 0x4c43, 1, "RLC_PG_CNTL" };

// ---- fields (gc_12_0_0_sh_mask.h) -----------------------------------------------------------------------------------------------------------
constexpr uint32_t kRlcCntlEnableF32          = 0x00000001u;   // RLC_CNTL__RLC_ENABLE_F32_MASK (shift 0, sh_mask.h:19743)
constexpr uint32_t kSafeModeCmd               = 0x00000001u;   // RLC_SAFE_MODE__CMD_MASK (sh_mask.h:22405)
constexpr uint32_t kSafeModeMessageShift      = 1;             // RLC_SAFE_MODE__MESSAGE__SHIFT (sh_mask.h:22401)
// RLC_CGTT_MGCG_OVERRIDE (sh_mask.h:20153-20163)
constexpr uint32_t kOvrRlcRepeaterFgcg        = 0x00000001u;
constexpr uint32_t kOvrRlcCgttSclk            = 0x00000002u;
constexpr uint32_t kOvrGfxipMgcg              = 0x00000004u;
constexpr uint32_t kOvrGfxipCgcg              = 0x00000008u;
constexpr uint32_t kOvrGfxipCgls              = 0x00000010u;
constexpr uint32_t kOvrGrbmCgttSclk           = 0x00000020u;
constexpr uint32_t kOvrGfxipMgls              = 0x00000040u;
constexpr uint32_t kOvrGfxipGfx3dCg           = 0x00000080u;
constexpr uint32_t kOvrGfxipFgcg              = 0x00000100u;
constexpr uint32_t kOvrGfxipRepeaterFgcg      = 0x00000200u;
constexpr uint32_t kOvrPerfmonClockState      = 0x00000400u;
// RLC_CGCG_CGLS_CTRL and RLC_CGCG_CGLS_CTRL_3D have the same layout (sh_mask.h:20174-20177 and 20519-20522)
constexpr uint32_t kCgcgEn                    = 0x00000001u;
constexpr uint32_t kCglsEn                    = 0x00000002u;
constexpr uint32_t kCglsRepCompansatDelayMask = 0x000000FCu;  constexpr uint32_t kCglsRepCompansatDelayShift = 2;
constexpr uint32_t kCgcgGfxIdleThresholdMask  = 0x07FFFF00u;  constexpr uint32_t kCgcgGfxIdleThresholdShift  = 8;
constexpr uint32_t kCgcgIdleThreshold         = 0x36;   // gfx_v12_0.c:3925 and :3943
constexpr uint32_t kCglsDelay                 = 0xF;    // gfx_v12_0.c:3931 (0x000F) and :3949 (0xf)
// CP_RB_WPTR_POLL_CNTL (sh_mask.h:7010-7013)
constexpr uint32_t kPollFrequencyMask         = 0x0000FFFFu;  constexpr uint32_t kPollFrequencyShift = 0;
constexpr uint32_t kIdlePollCountMask         = 0xFFFF0000u;  constexpr uint32_t kIdlePollCountShift = 16;
constexpr uint32_t kPollFrequency             = 0x0100;   // gfx_v12_0.c:3963 ("set IDLE_POLL_COUNT(0x00900100)")
constexpr uint32_t kIdlePollCount             = 0x0090;   // gfx_v12_0.c:3964
// CP_INT_CNTL and CP_INT_CNTL_RING0 (sh_mask.h:11680-11683 and 11851-11854: same bits)
constexpr uint32_t kCmpBusyIntEnable          = 0x00040000u;
constexpr uint32_t kCntxBusyIntEnable         = 0x00080000u;
constexpr uint32_t kCntxEmptyIntEnable        = 0x00100000u;
constexpr uint32_t kGfxIdleIntEnable          = 0x00200000u;
constexpr uint32_t kGuiIdleInts               = kCmpBusyIntEnable | kCntxBusyIntEnable | kCntxEmptyIntEnable | kGfxIdleIntEnable;
// SDMA0/1_RLC_CGCG_CTRL (sh_mask.h:681 and 3590)
constexpr uint32_t kSdmaCgcgIntEnable         = 0x00000002u;

constexpr uint32_t kSafeModePollUs            = 100000;   // AMDGPU_MAX_USEC_TIMEOUT (amdgpu.h:285)

// ---- options and result -------------------------------------------------------------------------------------------------------------------
struct Options {
    uint64_t cgFlags;   // kGc1200CgFlags on this card
    bool     ints;      // D3: the CP interrupt enables (default true = Linux)
    bool     sdma1;     // Linux: adev->sdma.num_instances > 1 (gfx_v12_0.c:3982)
};
inline Options default_options(bool sdma1) { return Options{ kGc1200CgFlags, true, sdma1 }; }

enum Code : uint32_t { kOk = 0, kRlcNotEnabled = 1, kSafeModeTimeout = 2, kNotRun = 3 };
inline const char *code_name(uint32_t c) {
    return c == kOk ? "ok" : c == kRlcNotEnabled ? "rlc-not-enabled" : c == kSafeModeTimeout ? "safe-mode-timeout" : c == kNotRun ? "not-run" : "?";
}

constexpr uint32_t kMaxTrace = 24;
struct Write { const Reg *reg; uint32_t before; uint32_t value; };

struct Result {
    uint32_t code { kNotRun };
    bool     enable { false };
    bool     safeMode { false };        // the safe-mode bracket was used (amdgpu_gfx_rlc_enter_safe_mode conditions)
    uint32_t safeModePolls { 0 };       // 1 us polls until RLC_SAFE_MODE.CMD cleared
    uint32_t rlcCntl { 0 };
    uint32_t nWrites { 0 };
    Write    trace[kMaxTrace] {};       // every register write, in order (the kext logs these)
};

// ---- the sequence ---------------------------------------------------------------------------------------------------------------------------
// Io must provide: uint32_t rd(const Reg &); void wr(const Reg &, uint32_t); void udelay1();
namespace detail {
template <class Io> inline void wr(Io &io, Result &r, const Reg &reg, uint32_t before, uint32_t value) {
    io.wr(reg, value);
    if (r.nWrites < kMaxTrace) r.trace[r.nWrites] = Write{ &reg, before, value };
    r.nWrites++;
}

template <class Io> inline void coarse(Io &io, Result &r, const Options &o, bool enable) {   // gfx_v12_0.c:3892-4007
    const uint64_t f = o.cgFlags;
    if (!(f & (kCgGfxCgcg | kCgGfxCgls | kCgGfx3dCgcg | kCgGfx3dCgls))) return;
    uint32_t def, data;
    if (enable) {
        def = data = io.rd(kRlcCgttMgcgOvr);
        if (f & kCgGfxCgcg) data &= ~kOvrGfxipCgcg;                                   // unset CGCG override
        if (f & kCgGfxCgls) data &= ~kOvrGfxipCgls;
        if ((f & kCgGfx3dCgcg) || (f & kCgGfx3dCgls)) data &= ~kOvrGfxipGfx3dCg;
        if (def != data) wr(io, r, kRlcCgttMgcgOvr, def, data);

        def = data = io.rd(kRlcCgcgCglsCtrl);                                          // enable cgcg FSM (0x0000363F)
        if (f & kCgGfxCgcg) {
            data &= ~kCgcgGfxIdleThresholdMask;
            data |= (kCgcgIdleThreshold << kCgcgGfxIdleThresholdShift) | kCgcgEn;
        }
        if (f & kCgGfxCgls) {
            data &= ~kCglsRepCompansatDelayMask;
            data |= (kCglsDelay << kCglsRepCompansatDelayShift) | kCglsEn;
        }
        if (def != data) wr(io, r, kRlcCgcgCglsCtrl, def, data);

        def = data = io.rd(kRlcCgcgCglsCtrl3d);                                        // Program RLC_CGCG_CGLS_CTRL_3D
        if (f & kCgGfx3dCgcg) {
            data &= ~kCgcgGfxIdleThresholdMask;
            data |= (kCgcgIdleThreshold << kCgcgGfxIdleThresholdShift) | kCgcgEn;
        }
        if (f & kCgGfx3dCgls) {
            data &= ~kCglsRepCompansatDelayMask;
            data |= (kCglsDelay << kCglsRepCompansatDelayShift) | kCglsEn;
        }
        if (def != data) wr(io, r, kRlcCgcgCglsCtrl3d, def, data);

        def = data = io.rd(kCpRbWptrPollCntl);                                         // set IDLE_POLL_COUNT (0x00900100)
        data &= ~(kPollFrequencyMask | kIdlePollCountMask);
        data |= (kPollFrequency << kPollFrequencyShift) | (kIdlePollCount << kIdlePollCountShift);
        if (def != data) wr(io, r, kCpRbWptrPollCntl, def, data);

        if (o.ints) {                                                                   // D3; Linux writes these unconditionally
            def = data = io.rd(kCpIntCntl);
            data |= kCntxBusyIntEnable; data |= kCntxEmptyIntEnable; data |= kCmpBusyIntEnable; data |= kGfxIdleIntEnable;
            wr(io, r, kCpIntCntl, def, data);
        }
        def = data = io.rd(kSdma0RlcCgcgCtrl);
        data |= kSdmaCgcgIntEnable;
        wr(io, r, kSdma0RlcCgcgCtrl, def, data);
        if (o.sdma1) {                                                                  // only when there is a second SDMA instance
            def = data = io.rd(kSdma1RlcCgcgCtrl);
            data |= kSdmaCgcgIntEnable;
            wr(io, r, kSdma1RlcCgcgCtrl, def, data);
        }
    } else {
        def = data = io.rd(kRlcCgcgCglsCtrl);
        if (f & kCgGfxCgcg) data &= ~kCgcgEn;
        if (f & kCgGfxCgls) data &= ~kCglsEn;
        if (def != data) wr(io, r, kRlcCgcgCglsCtrl, def, data);
        def = data = io.rd(kRlcCgcgCglsCtrl3d);
        if (f & kCgGfx3dCgcg) data &= ~kCgcgEn;
        if (f & kCgGfx3dCgls) data &= ~kCglsEn;
        if (def != data) wr(io, r, kRlcCgcgCglsCtrl3d, def, data);
    }
}

template <class Io> inline void medium(Io &io, Result &r, const Options &o, bool enable) {   // gfx_v12_0.c:4009-4041
    if (!(o.cgFlags & (kCgGfxMgcg | kCgGfxMgls))) return;
    if (!(o.cgFlags & kCgGfxMgcg)) return;   // both branches act only with MGCG ("It is disabled by HW by default")
    uint32_t def, data;
    def = data = io.rd(kRlcCgttMgcgOvr);
    if (enable) data &= ~(kOvrGrbmCgttSclk | kOvrRlcCgttSclk | kOvrGfxipMgcg);
    else        data |=  (kOvrRlcCgttSclk | kOvrGrbmCgttSclk | kOvrGfxipMgcg);
    if (def != data) wr(io, r, kRlcCgttMgcgOvr, def, data);
}

template <class Io> inline void override_bits(Io &io, Result &r, uint32_t bits, bool enable) {   // repeater FGCG, SRAM FGCG, perf clk
    uint32_t def, data;
    def = data = io.rd(kRlcCgttMgcgOvr);
    if (enable) data &= ~bits; else data |= bits;
    if (def != data) wr(io, r, kRlcCgttMgcgOvr, def, data);
}

template <class Io> inline void gui_idle_interrupt(Io &io, Result &r, bool enable) {   // gfx_v12_0.c:1757-1783, num_me 1 x num_pipe 1 -> RING0
    uint32_t def, data;
    def = data = io.rd(kCpIntCntlRing0);
    if (enable) data |= kGuiIdleInts; else data &= ~kGuiIdleInts;   // CNTX_BUSY, CNTX_EMPTY, CMP_BUSY, GFX_IDLE (REG_SET_FIELD x 4)
    wr(io, r, kCpIntCntlRing0, def, data);
}
}  // namespace detail

// gfx_v12_0_update_gfx_clock_gating(adev, enable), gfx_v12_0.c:4083-4109, with the deviations D1-D3 above.
template <class Io> inline Result update_gfx_clock_gating(Io &io, bool enable, const Options &o) {
    Result r;
    r.enable = enable;
    // amdgpu_gfx_rlc_enter_safe_mode (amdgpu_rlc.c:38-53)
    r.rlcCntl = io.rd(kRlcCntl);
    if (!(r.rlcCntl & kRlcCntlEnableF32) || r.rlcCntl == 0xFFFFFFFFu) { r.code = kRlcNotEnabled; return r; }   // D1
    r.safeMode = (o.cgFlags & (kCgGfxCgcg | kCgGfxMgcg | kCgGfx3dCgcg)) != 0;
    if (r.safeMode) {
        // gfx_v12_0_set_safe_mode: CMD | (1 << MESSAGE shift), then wait for CMD to clear
        detail::wr(io, r, kRlcSafeMode, 0u, kSafeModeCmd | (1u << kSafeModeMessageShift));
        bool acked = false;
        for (uint32_t i = 0; i < kSafeModePollUs; i++) {
            const uint32_t v = io.rd(kRlcSafeMode);
            if (v != 0xFFFFFFFFu && !(v & kSafeModeCmd)) { acked = true; break; }
            r.safeModePolls++;
            io.udelay1();
        }
        if (!acked) {                                                                    // D2
            detail::wr(io, r, kRlcSafeMode, 0u, kSafeModeCmd);                           // gfx_v12_0_unset_safe_mode
            r.code = kSafeModeTimeout;
            return r;
        }
    }
    detail::coarse(io, r, o, enable);
    detail::medium(io, r, o, enable);
    if (o.cgFlags & kCgRepeaterFgcg) detail::override_bits(io, r, kOvrGfxipRepeaterFgcg | kOvrRlcRepeaterFgcg, enable);   // :4043-4062
    if (o.cgFlags & kCgGfxFgcg)      detail::override_bits(io, r, kOvrGfxipFgcg, enable);                                 // :4064-4081
    if (o.cgFlags & kCgGfxPerfClk)   detail::override_bits(io, r, kOvrPerfmonClockState, enable);                          // :3797-3815
    if ((o.cgFlags & (kCgGfxMgcg | kCgGfxCgls | kCgGfxCgcg | kCgGfx3dCgcg | kCgGfx3dCgls)) && o.ints)                      // :4098-4104 (D3)
        detail::gui_idle_interrupt(io, r, enable);
    if (r.safeMode) detail::wr(io, r, kRlcSafeMode, 0u, kSafeModeCmd);                   // amdgpu_gfx_rlc_exit_safe_mode -> unset_safe_mode
    r.code = kOk;
    return r;
}

// The registers the kext snapshots before and after (and publishes / logs), in this order.
constexpr const Reg *kSnapshot[] = { &kRlcCgttMgcgOvr, &kRlcCgcgCglsCtrl, &kRlcCgcgCglsCtrl3d, &kCpRbWptrPollCntl, &kCpIntCntl,
                                     &kCpIntCntlRing0, &kSdma0RlcCgcgCtrl, &kSdma1RlcCgcgCtrl, &kRlcSafeMode, &kRlcCntl,
                                     &kRlcGpmStat, &kRlcPgCntl, &kGrbmStatus, &kCpStat };
constexpr size_t kSnapshotCount = sizeof(kSnapshot) / sizeof(kSnapshot[0]);
enum SnapIx : uint32_t { kSnapOvr = 0, kSnapCgcg = 1, kSnapCgcg3d = 2, kSnapPoll = 3, kSnapCpInt = 4, kSnapRing0 = 5 };

// What the boot did, for the registry property Navi48,ClockGating (ioreg -l | grep ClockGating).
struct Report {
    bool     attempted { false };   // false: navi48-cg=0, or not on the full bring-up path
    uint32_t why       { 0 };       // when not attempted: kWhyOff / kWhyNotFullPath
    bool     ints      { true };
    Result   res {};
    uint32_t before[kSnapshotCount] {};
    uint32_t after[kSnapshotCount] {};
};
enum Why : uint32_t { kWhyNone = 0, kWhyOff = 1, kWhyNotFullPath = 2 };

namespace detail {
inline size_t put(char *b, size_t cap, size_t at, const char *s) { while (*s && at + 1 < cap) b[at++] = *s++; if (cap) b[at < cap ? at : cap - 1] = '\0'; return at; }
inline size_t hex(char *b, size_t cap, size_t at, uint32_t v) {
    static const char d[] = "0123456789abcdef";
    at = put(b, cap, at, "0x");
    for (int s = 28; s >= 0; s -= 4) if (at + 1 < cap) b[at++] = d[(v >> s) & 0xFu];
    if (cap) b[at < cap ? at : cap - 1] = '\0';
    return at;
}
inline size_t dec(char *b, size_t cap, size_t at, uint32_t v) {
    char t[12]; size_t n = 0;
    do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v && n < sizeof t);
    while (n && at + 1 < cap) b[at++] = t[--n];
    if (cap) b[at < cap ? at : cap - 1] = '\0';
    return at;
}
}  // namespace detail

// "result=<code> override 0x..->0x.. cgcg 0x..->0x.. cgcg3d 0x..->0x.. poll 0x..->0x.. cpint 0x..->0x.. ring0 0x..->0x.. ints=1 writes=N polls=N"
inline size_t describe(char *b, size_t cap, const Report &rep) {
    using namespace detail;
    if (!cap) return 0;
    b[0] = '\0';
    size_t at = 0;
    if (!rep.attempted) return put(b, cap, at, rep.why == kWhyOff ? "result=off (navi48-cg=0)" : "result=not-run (not the full bring-up path)");
    at = put(b, cap, at, "result="); at = put(b, cap, at, code_name(rep.res.code));
    static const char *const names[] = { " override ", " cgcg ", " cgcg3d ", " poll ", " cpint ", " ring0 " };
    for (uint32_t i = 0; i < 6; i++) {
        at = put(b, cap, at, names[i]); at = hex(b, cap, at, rep.before[i]); at = put(b, cap, at, "->"); at = hex(b, cap, at, rep.after[i]);
    }
    at = put(b, cap, at, rep.ints ? " ints=1" : " ints=0");
    at = put(b, cap, at, " writes="); at = dec(b, cap, at, rep.res.nWrites);
    at = put(b, cap, at, " polls="); at = dec(b, cap, at, rep.res.safeModePolls);
    return at;
}

}  // namespace n48cg
