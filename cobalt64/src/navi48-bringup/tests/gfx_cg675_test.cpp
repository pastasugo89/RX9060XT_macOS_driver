// Host test (kext 0.0.675): the GFX clock-gating sequence of amd/gfx_v12_0_cg_pure.h, a port of Linux v7.3 gfx_v12_0_update_gfx_clock_gating.
// 1. Every register offset, BASE_IDX and field constant of the port equals Linux's gc_12_0_0_offset.h / gc_12_0_0_sh_mask.h (the Linux headers
//    are included directly; amd_shared.h's AMD_CG_SUPPORT_* bits are checked as literal values from include/amd_shared.h:126-159).
// 2. Over a register model seeded with the LIVE values of research/reports/macos-20261112/gfx-power-gating-study.md (MGCG_OVERRIDE 0x7ff,
//    CGCG_CGLS_CTRL 0x0001003c, CGCG_CGLS_CTRL_3D 0x3c, CP_RB_WPTR_POLL_CNTL 0x00400000, CP_INT_CNTL 0, RLC_SAFE_MODE 0), the exact write
//    order and the final values equal a literal transcription of Linux's functions (linux_oracle below, written against the Linux macros).
// 3. The deviations D1 (RLC not enabled: nothing written), D2 (safe-mode timeout: stop, exit write only), D3 (navi48-cg-ints=0), the second
//    SDMA instance, idempotence, the disable path and the registry text.
// Build (from cobalt64/src/navi48-bringup):
//   clang++ -std=c++17 -Wall -Wextra -Werror -I src -I <repo>/research/ext/amdgpu-port-study/drm-kmod/drivers/gpu/drm/amd/include/asic_reg/gc \
//     tests/gfx_cg675_test.cpp -o /tmp/cg && /tmp/cg
#include "amd/gfx_v12_0_cg_pure.h"
#include "gc_12_0_0_offset.h"
#include "gc_12_0_0_sh_mask.h"
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

static int checks = 0, fails = 0;
#define CHECK(c, msg) do { checks++; if (!(c)) { fails++; std::printf("FAIL: %s (line %d)\n", msg, __LINE__); } } while (0)

using namespace n48cg;

constexpr uint32_t kBase0 = 0x1260, kBase1 = 0xA000;   // this card's GC bases (dwords), idx0 / idx1
static uint32_t abs_of(const Reg &r) { return (r.idx ? kBase1 : kBase0) + r.off; }

// ---- the register model -----------------------------------------------------------------------------------------------------------------
struct Model {
    std::map<uint32_t, uint32_t> regs;
    std::vector<std::pair<uint32_t, uint32_t>> writes;   // (absolute dword, value) in order
    uint32_t ackAfter = 3;          // RLC_SAFE_MODE.CMD clears after this many reads following an enter (UINT32_MAX = never)
    uint32_t readsSinceCmd = 0;
    uint64_t delays = 0;
    uint32_t rd(const Reg &r) {
        const uint32_t a = abs_of(r);
        uint32_t v = regs.count(a) ? regs[a] : 0u;
        if (a == abs_of(kRlcSafeMode) && (v & 1u)) {
            if (ackAfter != UINT32_MAX && ++readsSinceCmd >= ackAfter) { v &= ~1u; regs[a] = v; }
        }
        return v;
    }
    void wr(const Reg &r, uint32_t v) {
        const uint32_t a = abs_of(r);
        regs[a] = v; writes.emplace_back(a, v);
        if (a == abs_of(kRlcSafeMode)) readsSinceCmd = 0;
    }
    void udelay1() { delays++; }
};

static Model live_model() {
    Model m;
    m.regs[abs_of(kRlcCgttMgcgOvr)]    = 0x000007ffu;
    m.regs[abs_of(kRlcCgcgCglsCtrl)]   = 0x0001003cu;
    m.regs[abs_of(kRlcCgcgCglsCtrl3d)] = 0x0000003cu;
    m.regs[abs_of(kCpRbWptrPollCntl)]  = 0x00400000u;
    m.regs[abs_of(kCpIntCntl)]         = 0x00000000u;
    m.regs[abs_of(kRlcSafeMode)]       = 0x00000000u;
    m.regs[abs_of(kRlcCntl)]           = 0x00000001u;   // RLC_ENABLE_F32 (the RLC runs: the CP/MES ladder needs it)
    m.regs[abs_of(kCpIntCntlRing0)]    = 0x00000000u;   // not in the study; the EOP enable would be bit 26 (navi48-interrupts=1 only)
    m.regs[abs_of(kSdma0RlcCgcgCtrl)]  = 0x00000000u;   // not in the study
    m.regs[abs_of(kSdma1RlcCgcgCtrl)]  = 0x00000000u;
    return m;
}

// ---- Linux, transcribed (gfx_v12_0.c:3771-3815, 3892-4109, 1757-1783; amdgpu_rlc.c:38-78) with the Linux macros ---------------------------
// AMD_CG_SUPPORT_* values from include/amd_shared.h:126-159.
#define AMD_CG_SUPPORT_GFX_MGCG      (1ULL << 0)
#define AMD_CG_SUPPORT_GFX_MGLS      (1ULL << 1)
#define AMD_CG_SUPPORT_GFX_CGCG      (1ULL << 2)
#define AMD_CG_SUPPORT_GFX_CGLS      (1ULL << 3)
#define AMD_CG_SUPPORT_GFX_3D_CGCG   (1ULL << 20)
#define AMD_CG_SUPPORT_GFX_3D_CGLS   (1ULL << 21)
#define AMD_CG_SUPPORT_GFX_FGCG      (1ULL << 31)
#define AMD_CG_SUPPORT_REPEATER_FGCG (1ULL << 32)
#define AMD_CG_SUPPORT_GFX_PERF_CLK  (1ULL << 33)
#define REG_SET_FIELD(orig, reg, field, val) (((orig) & ~reg##__##field##_MASK) | (reg##__##field##_MASK & ((val) << reg##__##field##__SHIFT)))
struct LinuxDev {
    uint64_t cg_flags;
    int sdma_num_instances;
    std::map<uint32_t, uint32_t> regs;
    std::vector<std::pair<uint32_t, uint32_t>> writes;
    uint32_t base(int idx) const { return idx ? kBase1 : kBase0; }
};
#define RREG32_SOC15(ip, inst, reg) (adev->regs[adev->base(reg##_BASE_IDX) + reg])
#define WREG32_SOC15(ip, inst, reg, v) do { const uint32_t _a = adev->base(reg##_BASE_IDX) + reg, _v = (uint32_t)(v); \
    adev->regs[_a] = _v; adev->writes.emplace_back(_a, _v); } while (0)

static void lx_set_safe_mode(LinuxDev *adev) {
    uint32_t data = RLC_SAFE_MODE__CMD_MASK;
    data |= (1 << RLC_SAFE_MODE__MESSAGE__SHIFT);
    WREG32_SOC15(GC, 0, regRLC_SAFE_MODE, data);
    adev->regs[adev->base(regRLC_SAFE_MODE_BASE_IDX) + regRLC_SAFE_MODE] &= ~RLC_SAFE_MODE__CMD_MASK;   // the RLC acknowledges (the poll exits)
}
static void lx_unset_safe_mode(LinuxDev *adev) { WREG32_SOC15(GC, 0, regRLC_SAFE_MODE, RLC_SAFE_MODE__CMD_MASK); }
static void lx_coarse(LinuxDev *adev, bool enable) {
    uint32_t def, data;
    if (!(adev->cg_flags & (AMD_CG_SUPPORT_GFX_CGCG | AMD_CG_SUPPORT_GFX_CGLS | AMD_CG_SUPPORT_GFX_3D_CGCG | AMD_CG_SUPPORT_GFX_3D_CGLS))) return;
    if (enable) {
        def = data = RREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE);
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_CGCG) data &= ~RLC_CGTT_MGCG_OVERRIDE__GFXIP_CGCG_OVERRIDE_MASK;
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_CGLS) data &= ~RLC_CGTT_MGCG_OVERRIDE__GFXIP_CGLS_OVERRIDE_MASK;
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_3D_CGCG || adev->cg_flags & AMD_CG_SUPPORT_GFX_3D_CGLS)
            data &= ~RLC_CGTT_MGCG_OVERRIDE__GFXIP_GFX3D_CG_OVERRIDE_MASK;
        if (def != data) WREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE, data);
        def = data = RREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL);
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_CGCG) {
            data &= ~RLC_CGCG_CGLS_CTRL__CGCG_GFX_IDLE_THRESHOLD_MASK;
            data |= (0x36 << RLC_CGCG_CGLS_CTRL__CGCG_GFX_IDLE_THRESHOLD__SHIFT) | RLC_CGCG_CGLS_CTRL__CGCG_EN_MASK;
        }
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_CGLS) {
            data &= ~RLC_CGCG_CGLS_CTRL__CGLS_REP_COMPANSAT_DELAY_MASK;
            data |= (0x000F << RLC_CGCG_CGLS_CTRL__CGLS_REP_COMPANSAT_DELAY__SHIFT) | RLC_CGCG_CGLS_CTRL__CGLS_EN_MASK;
        }
        if (def != data) WREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL, data);
        def = data = RREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL_3D);
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_3D_CGCG) {
            data &= ~RLC_CGCG_CGLS_CTRL_3D__CGCG_GFX_IDLE_THRESHOLD_MASK;
            data |= (0x36 << RLC_CGCG_CGLS_CTRL_3D__CGCG_GFX_IDLE_THRESHOLD__SHIFT) | RLC_CGCG_CGLS_CTRL_3D__CGCG_EN_MASK;
        }
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_3D_CGLS) {
            data &= ~RLC_CGCG_CGLS_CTRL_3D__CGLS_REP_COMPANSAT_DELAY_MASK;
            data |= (0xf << RLC_CGCG_CGLS_CTRL_3D__CGLS_REP_COMPANSAT_DELAY__SHIFT) | RLC_CGCG_CGLS_CTRL_3D__CGLS_EN_MASK;
        }
        if (def != data) WREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL_3D, data);
        def = data = RREG32_SOC15(GC, 0, regCP_RB_WPTR_POLL_CNTL);
        data &= ~(CP_RB_WPTR_POLL_CNTL__POLL_FREQUENCY_MASK | CP_RB_WPTR_POLL_CNTL__IDLE_POLL_COUNT_MASK);
        data |= (0x0100 << CP_RB_WPTR_POLL_CNTL__POLL_FREQUENCY__SHIFT) | (0x0090 << CP_RB_WPTR_POLL_CNTL__IDLE_POLL_COUNT__SHIFT);
        if (def != data) WREG32_SOC15(GC, 0, regCP_RB_WPTR_POLL_CNTL, data);
        data = RREG32_SOC15(GC, 0, regCP_INT_CNTL);
        data = REG_SET_FIELD(data, CP_INT_CNTL, CNTX_BUSY_INT_ENABLE, 1);
        data = REG_SET_FIELD(data, CP_INT_CNTL, CNTX_EMPTY_INT_ENABLE, 1);
        data = REG_SET_FIELD(data, CP_INT_CNTL, CMP_BUSY_INT_ENABLE, 1);
        data = REG_SET_FIELD(data, CP_INT_CNTL, GFX_IDLE_INT_ENABLE, 1);
        WREG32_SOC15(GC, 0, regCP_INT_CNTL, data);
        data = RREG32_SOC15(GC, 0, regSDMA0_RLC_CGCG_CTRL);
        data = REG_SET_FIELD(data, SDMA0_RLC_CGCG_CTRL, CGCG_INT_ENABLE, 1);
        WREG32_SOC15(GC, 0, regSDMA0_RLC_CGCG_CTRL, data);
        if (adev->sdma_num_instances > 1) {
            data = RREG32_SOC15(GC, 0, regSDMA1_RLC_CGCG_CTRL);
            data = REG_SET_FIELD(data, SDMA1_RLC_CGCG_CTRL, CGCG_INT_ENABLE, 1);
            WREG32_SOC15(GC, 0, regSDMA1_RLC_CGCG_CTRL, data);
        }
    } else {
        def = data = RREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL);
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_CGCG) data &= ~RLC_CGCG_CGLS_CTRL__CGCG_EN_MASK;
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_CGLS) data &= ~RLC_CGCG_CGLS_CTRL__CGLS_EN_MASK;
        if (def != data) WREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL, data);
        def = data = RREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL_3D);
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_3D_CGCG) data &= ~RLC_CGCG_CGLS_CTRL_3D__CGCG_EN_MASK;
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_3D_CGLS) data &= ~RLC_CGCG_CGLS_CTRL_3D__CGLS_EN_MASK;
        if (def != data) WREG32_SOC15(GC, 0, regRLC_CGCG_CGLS_CTRL_3D, data);
    }
}
static void lx_medium(LinuxDev *adev, bool enable) {
    uint32_t data, def;
    if (!(adev->cg_flags & (AMD_CG_SUPPORT_GFX_MGCG | AMD_CG_SUPPORT_GFX_MGLS))) return;
    if (enable) {
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_MGCG) {
            def = data = RREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE);
            data &= ~(RLC_CGTT_MGCG_OVERRIDE__GRBM_CGTT_SCLK_OVERRIDE_MASK | RLC_CGTT_MGCG_OVERRIDE__RLC_CGTT_SCLK_OVERRIDE_MASK |
                      RLC_CGTT_MGCG_OVERRIDE__GFXIP_MGCG_OVERRIDE_MASK);
            if (def != data) WREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE, data);
        }
    } else {
        if (adev->cg_flags & AMD_CG_SUPPORT_GFX_MGCG) {
            def = data = RREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE);
            data |= (RLC_CGTT_MGCG_OVERRIDE__RLC_CGTT_SCLK_OVERRIDE_MASK | RLC_CGTT_MGCG_OVERRIDE__GRBM_CGTT_SCLK_OVERRIDE_MASK |
                     RLC_CGTT_MGCG_OVERRIDE__GFXIP_MGCG_OVERRIDE_MASK);
            if (def != data) WREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE, data);
        }
    }
}
static void lx_ovr(LinuxDev *adev, uint64_t flag, uint32_t mask, bool enable) {   // repeater_fgcg / sram_fgcg / perf_clk share this shape
    uint32_t def, data;
    if (!(adev->cg_flags & flag)) return;
    def = data = RREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE);
    if (enable) data &= ~mask; else data |= mask;
    if (def != data) WREG32_SOC15(GC, 0, regRLC_CGTT_MGCG_OVERRIDE, data);
}
static void lx_gui_idle(LinuxDev *adev, bool enable) {   // num_me = 1, num_pipe_per_me = 1 -> CP_INT_CNTL_RING0
    uint32_t tmp = RREG32_SOC15(GC, 0, regCP_INT_CNTL_RING0);
    tmp = REG_SET_FIELD(tmp, CP_INT_CNTL_RING0, CNTX_BUSY_INT_ENABLE, enable ? 1 : 0);
    tmp = REG_SET_FIELD(tmp, CP_INT_CNTL_RING0, CNTX_EMPTY_INT_ENABLE, enable ? 1 : 0);
    tmp = REG_SET_FIELD(tmp, CP_INT_CNTL_RING0, CMP_BUSY_INT_ENABLE, enable ? 1 : 0);
    tmp = REG_SET_FIELD(tmp, CP_INT_CNTL_RING0, GFX_IDLE_INT_ENABLE, enable ? 1 : 0);
    WREG32_SOC15(GC, 0, regCP_INT_CNTL_RING0, tmp);
}
static void linux_oracle(LinuxDev *adev, bool enable) {   // gfx_v12_0_update_gfx_clock_gating, RLC enabled
    const bool sm = adev->cg_flags & (AMD_CG_SUPPORT_GFX_CGCG | AMD_CG_SUPPORT_GFX_MGCG | AMD_CG_SUPPORT_GFX_3D_CGCG);
    if (sm) lx_set_safe_mode(adev);
    lx_coarse(adev, enable);
    lx_medium(adev, enable);
    lx_ovr(adev, AMD_CG_SUPPORT_REPEATER_FGCG, RLC_CGTT_MGCG_OVERRIDE__GFXIP_REPEATER_FGCG_OVERRIDE_MASK | RLC_CGTT_MGCG_OVERRIDE__RLC_REPEATER_FGCG_OVERRIDE_MASK, enable);
    lx_ovr(adev, AMD_CG_SUPPORT_GFX_FGCG, RLC_CGTT_MGCG_OVERRIDE__GFXIP_FGCG_OVERRIDE_MASK, enable);
    lx_ovr(adev, AMD_CG_SUPPORT_GFX_PERF_CLK, RLC_CGTT_MGCG_OVERRIDE__PERFMON_CLOCK_STATE_MASK, enable);
    if (adev->cg_flags & (AMD_CG_SUPPORT_GFX_MGCG | AMD_CG_SUPPORT_GFX_CGLS | AMD_CG_SUPPORT_GFX_CGCG | AMD_CG_SUPPORT_GFX_3D_CGCG | AMD_CG_SUPPORT_GFX_3D_CGLS))
        lx_gui_idle(adev, enable);
    if (sm) lx_unset_safe_mode(adev);
}

// ---- 1. constants -----------------------------------------------------------------------------------------------------------------------
static void test_constants() {
    struct { const Reg &r; uint32_t off, idx; } regs[] = {
        { kRlcSafeMode, regRLC_SAFE_MODE, regRLC_SAFE_MODE_BASE_IDX }, { kRlcCntl, regRLC_CNTL, regRLC_CNTL_BASE_IDX },
        { kRlcCgttMgcgOvr, regRLC_CGTT_MGCG_OVERRIDE, regRLC_CGTT_MGCG_OVERRIDE_BASE_IDX },
        { kRlcCgcgCglsCtrl, regRLC_CGCG_CGLS_CTRL, regRLC_CGCG_CGLS_CTRL_BASE_IDX },
        { kRlcCgcgCglsCtrl3d, regRLC_CGCG_CGLS_CTRL_3D, regRLC_CGCG_CGLS_CTRL_3D_BASE_IDX },
        { kCpRbWptrPollCntl, regCP_RB_WPTR_POLL_CNTL, regCP_RB_WPTR_POLL_CNTL_BASE_IDX }, { kCpIntCntl, regCP_INT_CNTL, regCP_INT_CNTL_BASE_IDX },
        { kCpIntCntlRing0, regCP_INT_CNTL_RING0, regCP_INT_CNTL_RING0_BASE_IDX },
        { kSdma0RlcCgcgCtrl, regSDMA0_RLC_CGCG_CTRL, regSDMA0_RLC_CGCG_CTRL_BASE_IDX },
        { kSdma1RlcCgcgCtrl, regSDMA1_RLC_CGCG_CTRL, regSDMA1_RLC_CGCG_CTRL_BASE_IDX },
        { kRlcGpmStat, regRLC_GPM_STAT, regRLC_GPM_STAT_BASE_IDX }, { kGrbmStatus, regGRBM_STATUS, regGRBM_STATUS_BASE_IDX },
        { kCpStat, regCP_STAT, regCP_STAT_BASE_IDX }, { kRlcPgCntl, regRLC_PG_CNTL, regRLC_PG_CNTL_BASE_IDX },
    };
    for (auto &e : regs) {
        char m[96]; std::snprintf(m, sizeof m, "offset/BASE_IDX of %s equal Linux gc_12_0_0_offset.h", e.r.name);
        CHECK(e.r.off == e.off && e.r.idx == e.idx, m);
    }
    // the study's live addresses: GC idx1 0xA000 + 0x4C48 etc. and idx0 0x1260 + 0x0F62 (the study prints them relative to the base)
    CHECK(abs_of(kRlcCgttMgcgOvr) == 0xA000u + 0x4C48u && abs_of(kCpRbWptrPollCntl) == 0x1260u + 0x0F62u, "absolute addresses from the two GC bases");
    CHECK(kRlcCntlEnableF32 == RLC_CNTL__RLC_ENABLE_F32_MASK, "RLC_ENABLE_F32");
    CHECK(kSafeModeCmd == RLC_SAFE_MODE__CMD_MASK && kSafeModeMessageShift == RLC_SAFE_MODE__MESSAGE__SHIFT, "RLC_SAFE_MODE fields");
    CHECK(kOvrRlcRepeaterFgcg == RLC_CGTT_MGCG_OVERRIDE__RLC_REPEATER_FGCG_OVERRIDE_MASK && kOvrRlcCgttSclk == RLC_CGTT_MGCG_OVERRIDE__RLC_CGTT_SCLK_OVERRIDE_MASK &&
          kOvrGfxipMgcg == RLC_CGTT_MGCG_OVERRIDE__GFXIP_MGCG_OVERRIDE_MASK && kOvrGfxipCgcg == RLC_CGTT_MGCG_OVERRIDE__GFXIP_CGCG_OVERRIDE_MASK &&
          kOvrGfxipCgls == RLC_CGTT_MGCG_OVERRIDE__GFXIP_CGLS_OVERRIDE_MASK && kOvrGrbmCgttSclk == RLC_CGTT_MGCG_OVERRIDE__GRBM_CGTT_SCLK_OVERRIDE_MASK &&
          kOvrGfxipMgls == RLC_CGTT_MGCG_OVERRIDE__GFXIP_MGLS_OVERRIDE_MASK && kOvrGfxipGfx3dCg == RLC_CGTT_MGCG_OVERRIDE__GFXIP_GFX3D_CG_OVERRIDE_MASK &&
          kOvrGfxipFgcg == RLC_CGTT_MGCG_OVERRIDE__GFXIP_FGCG_OVERRIDE_MASK && kOvrGfxipRepeaterFgcg == RLC_CGTT_MGCG_OVERRIDE__GFXIP_REPEATER_FGCG_OVERRIDE_MASK &&
          kOvrPerfmonClockState == RLC_CGTT_MGCG_OVERRIDE__PERFMON_CLOCK_STATE_MASK, "RLC_CGTT_MGCG_OVERRIDE fields");
    CHECK(kCgcgEn == RLC_CGCG_CGLS_CTRL__CGCG_EN_MASK && kCglsEn == RLC_CGCG_CGLS_CTRL__CGLS_EN_MASK &&
          kCglsRepCompansatDelayMask == RLC_CGCG_CGLS_CTRL__CGLS_REP_COMPANSAT_DELAY_MASK && kCglsRepCompansatDelayShift == RLC_CGCG_CGLS_CTRL__CGLS_REP_COMPANSAT_DELAY__SHIFT &&
          kCgcgGfxIdleThresholdMask == RLC_CGCG_CGLS_CTRL__CGCG_GFX_IDLE_THRESHOLD_MASK && kCgcgGfxIdleThresholdShift == RLC_CGCG_CGLS_CTRL__CGCG_GFX_IDLE_THRESHOLD__SHIFT,
          "RLC_CGCG_CGLS_CTRL fields");
    CHECK(kCgcgEn == RLC_CGCG_CGLS_CTRL_3D__CGCG_EN_MASK && kCglsEn == RLC_CGCG_CGLS_CTRL_3D__CGLS_EN_MASK &&
          kCglsRepCompansatDelayMask == RLC_CGCG_CGLS_CTRL_3D__CGLS_REP_COMPANSAT_DELAY_MASK &&
          kCgcgGfxIdleThresholdMask == RLC_CGCG_CGLS_CTRL_3D__CGCG_GFX_IDLE_THRESHOLD_MASK, "RLC_CGCG_CGLS_CTRL_3D has the same layout");
    CHECK(kPollFrequencyMask == CP_RB_WPTR_POLL_CNTL__POLL_FREQUENCY_MASK && kIdlePollCountMask == CP_RB_WPTR_POLL_CNTL__IDLE_POLL_COUNT_MASK &&
          kPollFrequencyShift == CP_RB_WPTR_POLL_CNTL__POLL_FREQUENCY__SHIFT && kIdlePollCountShift == CP_RB_WPTR_POLL_CNTL__IDLE_POLL_COUNT__SHIFT,
          "CP_RB_WPTR_POLL_CNTL fields");
    CHECK(kCmpBusyIntEnable == CP_INT_CNTL__CMP_BUSY_INT_ENABLE_MASK && kCntxBusyIntEnable == CP_INT_CNTL__CNTX_BUSY_INT_ENABLE_MASK &&
          kCntxEmptyIntEnable == CP_INT_CNTL__CNTX_EMPTY_INT_ENABLE_MASK && kGfxIdleIntEnable == CP_INT_CNTL__GFX_IDLE_INT_ENABLE_MASK, "CP_INT_CNTL fields");
    CHECK(kCmpBusyIntEnable == CP_INT_CNTL_RING0__CMP_BUSY_INT_ENABLE_MASK && kCntxBusyIntEnable == CP_INT_CNTL_RING0__CNTX_BUSY_INT_ENABLE_MASK &&
          kCntxEmptyIntEnable == CP_INT_CNTL_RING0__CNTX_EMPTY_INT_ENABLE_MASK && kGfxIdleIntEnable == CP_INT_CNTL_RING0__GFX_IDLE_INT_ENABLE_MASK,
          "CP_INT_CNTL_RING0 fields");
    CHECK(kSdmaCgcgIntEnable == SDMA0_RLC_CGCG_CTRL__CGCG_INT_ENABLE_MASK && kSdmaCgcgIntEnable == SDMA1_RLC_CGCG_CTRL__CGCG_INT_ENABLE_MASK, "SDMA RLC_CGCG_CTRL");
    CHECK(kGc1200CgFlags == (AMD_CG_SUPPORT_GFX_CGCG | AMD_CG_SUPPORT_GFX_CGLS | AMD_CG_SUPPORT_GFX_MGCG | AMD_CG_SUPPORT_GFX_3D_CGCG |
                             AMD_CG_SUPPORT_GFX_3D_CGLS | AMD_CG_SUPPORT_REPEATER_FGCG | AMD_CG_SUPPORT_GFX_FGCG | AMD_CG_SUPPORT_GFX_PERF_CLK),
          "cg_flags = soc24.c:390-397 GFX bits");
    CHECK(kSafeModePollUs == 100000, "safe-mode bound = AMDGPU_MAX_USEC_TIMEOUT");
}

static std::string name_of(uint32_t a) {
    for (size_t i = 0; i < kSnapshotCount; i++) if (abs_of(*kSnapshot[i]) == a) return kSnapshot[i]->name;
    return "?";
}

// ---- 2. the live state against Linux ------------------------------------------------------------------------------------------------------
static void test_live_sequence() {
    Model m = live_model();
    const Result r = update_gfx_clock_gating(m, true, default_options(true));
    LinuxDev lx{ kGc1200CgFlags, 2, live_model().regs, {} };
    linux_oracle(&lx, true);
    CHECK(r.code == kOk && r.safeMode, "live: ok, inside safe mode");
    CHECK(m.writes == lx.writes, "live: the write sequence equals Linux's, register for register and value for value");
    // the exact expected sequence, written out (what the boot log's "cg: write" lines must show)
    const std::vector<std::pair<uint32_t, uint32_t>> want = {
        { abs_of(kRlcSafeMode),       0x00000003u },   // enter: CMD | MESSAGE 1
        { abs_of(kRlcCgttMgcgOvr),    0x00000767u },   // coarse: CGCG, CGLS, GFX3D_CG overrides off
        { abs_of(kRlcCgcgCglsCtrl),   0x0000363fu },   // CGCG_EN, CGLS_EN, idle threshold 0x36, CGLS delay 0xF
        { abs_of(kRlcCgcgCglsCtrl3d), 0x0000363fu },
        { abs_of(kCpRbWptrPollCntl),  0x00900100u },
        { abs_of(kCpIntCntl),         0x003c0000u },   // CMP_BUSY, CNTX_BUSY, CNTX_EMPTY, GFX_IDLE
        { abs_of(kSdma0RlcCgcgCtrl),  0x00000002u },
        { abs_of(kSdma1RlcCgcgCtrl),  0x00000002u },
        { abs_of(kRlcCgttMgcgOvr),    0x00000741u },   // medium: GRBM_CGTT_SCLK, RLC_CGTT_SCLK, MGCG overrides off
        { abs_of(kRlcCgttMgcgOvr),    0x00000540u },   // repeater FGCG (GFXIP + RLC)
        { abs_of(kRlcCgttMgcgOvr),    0x00000440u },   // SRAM FGCG
        { abs_of(kRlcCgttMgcgOvr),    0x00000040u },   // perfmon clock
        { abs_of(kCpIntCntlRing0),    0x003c0000u },   // GUI idle interrupt (me 0 pipe 0)
        { abs_of(kRlcSafeMode),       0x00000001u },   // exit: CMD only
    };
    CHECK(m.writes == want, "live: the 14 writes, in order, with these values");
    if (m.writes != want) for (auto &w : m.writes) std::printf("  wrote %-22s %#07x = %#010x\n", name_of(w.first).c_str(), w.first, w.second);
    CHECK(r.nWrites == 14 && r.trace[1].before == 0x7ffu && r.trace[2].before == 0x0001003cu && r.trace[4].before == 0x00400000u, "live: trace with the old values");
    CHECK(m.regs[abs_of(kRlcCgttMgcgOvr)] == 0x40u, "final MGCG_OVERRIDE = 0x40 (only MGLS, not in GC 12.0.0's cg_flags, stays overridden)");
    CHECK(m.regs[abs_of(kRlcCgcgCglsCtrl)] == 0x363fu && m.regs[abs_of(kRlcCgcgCglsCtrl3d)] == 0x363fu, "final CGCG_CGLS_CTRL(_3D) = 0x363F (Linux's comment)");
    CHECK(m.regs[abs_of(kCpRbWptrPollCntl)] == 0x00900100u, "final CP_RB_WPTR_POLL_CNTL = 0x00900100");
    CHECK(m.regs[abs_of(kCpIntCntl)] == 0x003c0000u && m.regs[abs_of(kCpIntCntlRing0)] == 0x003c0000u, "final CP_INT_CNTL / RING0");
    CHECK(m.regs[abs_of(kRlcSafeMode)] == 0x1u, "RLC_SAFE_MODE left at the exit command");
    CHECK(r.safeModePolls == 2 && m.delays == 2, "safe mode: polled until CMD cleared (3rd read), 1 us apart");
    for (auto &kv : lx.regs) {
        char msg[96]; std::snprintf(msg, sizeof msg, "final %s equals Linux", name_of(kv.first).c_str());
        if (kv.first != abs_of(kRlcSafeMode)) CHECK(m.regs[kv.first] == kv.second, msg);
    }
    // preserved bits: an EOP enable (TIME_STAMP_INT_ENABLE, bit 26) in RING0 and SDMA hysteresis bits survive
    Model p = live_model();
    p.regs[abs_of(kCpIntCntlRing0)] = 0x04000000u;
    p.regs[abs_of(kSdma0RlcCgcgCtrl)] = 0x00100000u;
    update_gfx_clock_gating(p, true, default_options(true));
    CHECK(p.regs[abs_of(kCpIntCntlRing0)] == 0x043c0000u && p.regs[abs_of(kSdma0RlcCgcgCtrl)] == 0x00100002u, "read-modify-write keeps the other bits");
}

// ---- 3. deviations and variants ------------------------------------------------------------------------------------------------------------
static void test_variants() {
    { // D1: RLC not enabled -> nothing written
        Model m = live_model(); m.regs[abs_of(kRlcCntl)] = 0;
        const Result r = update_gfx_clock_gating(m, true, default_options(true));
        CHECK(r.code == kRlcNotEnabled && m.writes.empty(), "D1: RLC_ENABLE_F32 clear: no write at all");
        Model f = live_model(); f.regs[abs_of(kRlcCntl)] = 0xFFFFFFFFu;
        CHECK(update_gfx_clock_gating(f, true, default_options(true)).code == kRlcNotEnabled && f.writes.empty(), "D1: all-ones RLC_CNTL (device gone): no write");
    }
    { // D2: safe mode never acknowledged -> enter + exit only, bounded
        Model m = live_model(); m.ackAfter = UINT32_MAX;
        const Result r = update_gfx_clock_gating(m, true, default_options(true));
        const std::vector<std::pair<uint32_t, uint32_t>> want = { { abs_of(kRlcSafeMode), 3u }, { abs_of(kRlcSafeMode), 1u } };
        CHECK(r.code == kSafeModeTimeout && m.writes == want, "D2: timeout: only the enter and exit writes, no gating register touched");
        CHECK(r.safeModePolls == kSafeModePollUs && m.delays == kSafeModePollUs, "D2: the poll is bounded at 100000 x 1 us");
        CHECK(m.regs[abs_of(kRlcCgttMgcgOvr)] == 0x7ffu && m.regs[abs_of(kRlcCgcgCglsCtrl)] == 0x0001003cu, "D2: gating left as found");
    }
    { // D3: navi48-cg-ints=0 -> neither CP_INT_CNTL nor CP_INT_CNTL_RING0 written, everything else as Linux
        Model m = live_model();
        Options o = default_options(true); o.ints = false;
        const Result r = update_gfx_clock_gating(m, true, o);
        bool cpInt = false;
        for (auto &w : m.writes) cpInt |= (w.first == abs_of(kCpIntCntl) || w.first == abs_of(kCpIntCntlRing0));
        CHECK(r.code == kOk && !cpInt && r.nWrites == 12, "D3: no CP interrupt enable written (12 writes)");
        CHECK(m.regs[abs_of(kRlcCgttMgcgOvr)] == 0x40u && m.regs[abs_of(kRlcCgcgCglsCtrl)] == 0x363fu && m.regs[abs_of(kSdma0RlcCgcgCtrl)] == 2u,
              "D3: the gating itself is unchanged");
    }
    { // one SDMA instance (Linux: num_instances == 1)
        Model m = live_model();
        update_gfx_clock_gating(m, true, default_options(false));
        bool sdma1 = false;
        for (auto &w : m.writes) sdma1 |= (w.first == abs_of(kSdma1RlcCgcgCtrl));
        LinuxDev lx{ kGc1200CgFlags, 1, live_model().regs, {} };
        linux_oracle(&lx, true);
        CHECK(!sdma1 && m.writes == lx.writes, "one SDMA: SDMA1 untouched, the rest equals Linux");
    }
    { // idempotence: a second run writes only what Linux writes unconditionally
        Model m = live_model();
        update_gfx_clock_gating(m, true, default_options(true));
        m.writes.clear();
        const Result r = update_gfx_clock_gating(m, true, default_options(true));
        const std::vector<std::pair<uint32_t, uint32_t>> want = {
            { abs_of(kRlcSafeMode), 3u }, { abs_of(kCpIntCntl), 0x3c0000u }, { abs_of(kSdma0RlcCgcgCtrl), 2u }, { abs_of(kSdma1RlcCgcgCtrl), 2u },
            { abs_of(kCpIntCntlRing0), 0x3c0000u }, { abs_of(kRlcSafeMode), 1u } };
        CHECK(r.code == kOk && m.writes == want, "second run: only the unconditional writes (Linux does the same)");
    }
    { // the disable path equals Linux's too (not used by the kext; ported for completeness)
        Model m = live_model();
        update_gfx_clock_gating(m, true, default_options(true));
        LinuxDev lx{ kGc1200CgFlags, 2, m.regs, {} };
        m.writes.clear();
        update_gfx_clock_gating(m, false, default_options(true));
        lx.regs[abs_of(kRlcSafeMode)] = 1u;
        linux_oracle(&lx, false);
        CHECK(m.writes == lx.writes, "disable: the write sequence equals Linux's");
        CHECK(m.regs[abs_of(kRlcCgttMgcgOvr)] == 0x767u && (m.regs[abs_of(kRlcCgcgCglsCtrl)] & 3u) == 0 && m.regs[abs_of(kCpIntCntlRing0)] == 0,
              "disable: MGCG/FGCG/perf overrides back on, CGCG/CGLS off, GUI idle ints off");
    }
    { // registry text
        Report rep; rep.attempted = true; rep.ints = true;
        Model m = live_model();
        for (size_t i = 0; i < kSnapshotCount; i++) rep.before[i] = m.rd(*kSnapshot[i]);
        rep.res = update_gfx_clock_gating(m, true, default_options(true));
        for (size_t i = 0; i < kSnapshotCount; i++) rep.after[i] = m.rd(*kSnapshot[i]);
        char buf[400];
        describe(buf, sizeof buf, rep);
        CHECK(std::strcmp(buf, "result=ok override 0x000007ff->0x00000040 cgcg 0x0001003c->0x0000363f cgcg3d 0x0000003c->0x0000363f "
                               "poll 0x00400000->0x00900100 cpint 0x00000000->0x003c0000 ring0 0x00000000->0x003c0000 ints=1 writes=14 polls=2") == 0,
              "describe: the Navi48,ClockGating text");
        if (fails) std::printf("  %s\n", buf);
        Report off; off.why = kWhyOff;
        describe(buf, sizeof buf, off);
        CHECK(std::strcmp(buf, "result=off (navi48-cg=0)") == 0, "describe: off");
        char small[16];
        const size_t n = describe(small, sizeof small, rep);
        CHECK(n < sizeof small && std::strlen(small) < sizeof small, "describe: a short buffer is truncated, never overrun");
    }
}

int main() {
    test_constants();
    test_live_sequence();
    test_variants();
    std::printf("gfx_cg675_test: %d checks, %d failed\n", checks, fails);
    std::puts(fails ? "FAIL" : "PASS");
    return fails ? 1 : 0;
}
