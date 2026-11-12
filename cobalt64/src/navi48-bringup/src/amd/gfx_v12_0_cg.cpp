//
//  gfx_v12_0_cg.cpp - kext 0.0.675: GFX clock gating, the kernel half (register access, logging, registry text). The sequence and every value
//  are in gfx_v12_0_cg_pure.h (a port of Linux v7.3 gfx_v12_0.c, MIT; attribution there).
//
//  WHEN. Linux gates once from amdgpu_device_ip_late_init (amdgpu_device.c:3302), after every IP block's hw_init (RLC, CP, MES, SDMA). Here:
//  Navi48Bringup::runStages, after amdgpu::bringup_to reached its target on the full path (MES running, the kernel GFX queue mapped by PM4Test)
//  and before the native self-test and the desktop. Nothing else touches GC registers at that point. GFXOFF is disallowed since init
//  (DisallowGfxOff in ensure_gfxhub_gart), so the GC registers are powered.
//
//  INTERRUPTS (navi48-cg-ints, default 1 = exactly Linux). The coarse-grain step sets CP_INT_CNTL CNTX_BUSY / CNTX_EMPTY / CMP_BUSY / GFX_IDLE
//  and the last step sets the same four in CP_INT_CNTL_RING0. They are kept ON by default because:
//   * they are the RLC's busy/idle inputs for the gating FSM, not driver interrupts: radeon keeps CNTX_BUSY/CNTX_EMPTY enabled even in its
//     "disable every interrupt the driver uses" path and with the IH ring off (cik.c cik_disable_interrupt_state :6856-6860 and cik_irq_set
//     :7030-7038 `if (!rdev->ih.enabled)`, si.c :5934 / :6052, r600.c :3622, evergreen.c :4463-4470), and si/cik turn them off before
//     ungating and then wait for RLC_STAT clock/power status (si.c si_enable_gui_idle_interrupt :5125-5149). Linux GC 12 has no handler
//     for them (gfx_v12_0.c registers EOP, priv reg/inst, bad op, RLC poison only); an unhandled source is only a debug message in
//     amdgpu_irq_dispatch. Enabling CGCG WITHOUT them is a configuration Linux never runs.
//   * with navi48-interrupts=0 (the production boot-args) the IH ring runs with RB_ENABLE=1, ENABLE_INTR=0 and no MSI handler
//     (ih_v7_0.cpp, amdgpu_init.cpp IHInit), so no CPU interrupt can be raised; an entry the CP may post lands in a ring nobody drains, and
//     WPTR_OVERFLOW_ENABLE=1 makes a full ring drop entries instead of stalling the writer. With navi48-interrupts=1 the handler drains them
//     and counts them as irqOther (Navi48Bringup::handleInterrupt).
//  navi48-cg-ints=0 leaves both registers untouched (diagnostic only).
//
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>
#include "gfx_v12_0_cg.h"
#include "amdgpu_log.h"

#define CG_LOG(fmt, ...) AMDGPU_LOG("cg", fmt, ##__VA_ARGS__)

namespace amdgpu {
namespace {

n48cg::Report gCgReport;

struct KextIo {
    const DeviceContext &dev;
    uint32_t base0, base1;
    uint32_t addr(const n48cg::Reg &r) const { return (r.idx ? base1 : base0) + r.off; }
    uint32_t rd(const n48cg::Reg &r) { return RREG32(dev, addr(r)); }
    void wr(const n48cg::Reg &r, uint32_t v) { WREG32(dev, addr(r), v); }
    void udelay1() { IODelay(1); }
};

void snapshot(KextIo &io, uint32_t *out, const char *when) {
    for (size_t i = 0; i < n48cg::kSnapshotCount; i++) {
        const n48cg::Reg &r = *n48cg::kSnapshot[i];
        out[i] = io.rd(r);
        CG_LOG("%s %-22s @%#07x (idx%u+%#06x) = %#010x", when, r.name, io.addr(r), r.idx, r.off, out[i]);
    }
}

}  // namespace

bool gfx_cg_config(bool *ints) {
    uint32_t on = 1, i = 1;
    PE_parse_boot_argn("navi48-cg", &on, sizeof(on));
    PE_parse_boot_argn("navi48-cg-ints", &i, sizeof(i));
    if (ints) *ints = (i != 0);
    return on != 0;
}

void gfx_cg_skip(uint32_t why) {
    gCgReport = n48cg::Report{};
    gCgReport.why = why;
    CG_LOG("GFX clock gating NOT programmed: %s", why == n48cg::kWhyOff ? "navi48-cg=0" : "not the full bring-up path");
}

kern_return_t gfx_v12_0_enable_clock_gating(const DeviceContext &dev, bool sdma1, bool ints) {
    gCgReport = n48cg::Report{};
    gCgReport.attempted = true;
    gCgReport.ints = ints;
    if (!dev.ip.isResolved(IPBlock::GC, 0) || !dev.ip.isResolved(IPBlock::GC, 1)) {
        gCgReport.res.code = n48cg::kNotRun;
        CG_LOG("GC base unresolved: clock gating not programmed");
        return kIOReturnNotReady;
    }
    KextIo io { dev, dev.ip.getBase(IPBlock::GC, 0), dev.ip.getBase(IPBlock::GC, 1) };
    CG_LOG("GFX clock gating (Linux gfx_v12_0_update_gfx_clock_gating, GC 12.0.0 cg_flags %#llx): GC base idx0 %#x idx1 %#x, sdma1 %d, ints %d",
           (unsigned long long)n48cg::kGc1200CgFlags, io.base0, io.base1, sdma1 ? 1 : 0, ints ? 1 : 0);
    snapshot(io, gCgReport.before, "before");
    n48cg::Options o = n48cg::default_options(sdma1);
    o.ints = ints;
    gCgReport.res = n48cg::update_gfx_clock_gating(io, true, o);
    const n48cg::Result &r = gCgReport.res;
    for (uint32_t i = 0; i < r.nWrites && i < n48cg::kMaxTrace; i++)
        CG_LOG("write %2u %-22s @%#07x: %#010x -> %#010x", i, r.trace[i].reg->name, io.addr(*r.trace[i].reg), r.trace[i].before, r.trace[i].value);
    snapshot(io, gCgReport.after, "after ");
    CG_LOG("GFX clock gating %s: %u writes, safe mode %s after %u polls; RLC_CNTL %#010x; MGCG_OVERRIDE %#010x -> %#010x, CGCG_CGLS_CTRL %#010x -> %#010x",
           n48cg::code_name(r.code), r.nWrites, r.safeMode ? "used" : "not used", r.safeModePolls, r.rlcCntl,
           gCgReport.before[n48cg::kSnapOvr], gCgReport.after[n48cg::kSnapOvr], gCgReport.before[n48cg::kSnapCgcg], gCgReport.after[n48cg::kSnapCgcg]);
    return r.code == n48cg::kOk ? kIOReturnSuccess : kIOReturnTimeout;
}

void gfx_cg_describe(char *buf, size_t cap) { n48cg::describe(buf, cap, gCgReport); }

}  // namespace amdgpu
