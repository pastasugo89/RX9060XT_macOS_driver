//
//  cp_census.cpp - kext 0.0.677: the boot-time command-processor busy marks and the optional queue census (tables, counting and switches in
//  cp_census_pure.h). Runs only in the bring-up thread, before any client exists.
//
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

#include "amdgpu_regs.h"
#include "amdgpu_log.h"
#include "amdgpu_cp.h"
#include "cp_census_pure.h"

#define CPC_LOG(fmt, ...) AMDGPU_LOG("cpmark", fmt, ##__VA_ARGS__)

namespace amdgpu {
namespace {

constexpr uint32_t kKeep = 16;   // the marks kept for the registry (0.0.678: 12 -> 16 for the ComputeDispatch sub-marks)
struct Kept { const char *where; uint32_t n; uint32_t cpf, cmp, postWptr, mesHqd, guiActive, cpfFirst, mesCntl; };
Kept gKept[kKeep];
uint32_t gKeptN = 0;
int gMarkOn = -1;

uint32_t rd(const DeviceContext &dev, const n48cpc::Reg &r) { return RREG32(dev, SOC15_REG_OFFSET_BIDX(dev, IPBlock::GC, r.idx, r.off)); }

bool mark_enabled() {
    if (gMarkOn < 0) { uint32_t v = 1; const bool p = PE_parse_boot_argn("navi48-cpmark", &v, sizeof(v)); gMarkOn = n48cpc::mark_on(p, v) ? 1 : 0; }
    return gMarkOn == 1;
}

uint32_t idx_of(const char *name) {
    for (uint32_t b = 0; b < n48cpc::kBitCount; b++) {
        const char *a = n48cpc::kBits[b].name, *c = name;
        while (*a && *a == *c) { a++; c++; }
        if (*a == 0 && *c == 0) return b;
    }
    return 0;
}

}  // namespace

void cp_busy_mark(const DeviceContext &dev, const char *where)
{
    using namespace n48cpc;
    if (!mark_enabled() || !dev.ip.isResolved(IPBlock::GC)) return;
    Counts c{};
    for (uint32_t s = 0; s < kMarkSamples; s++) {
        uint32_t v[kMarkRegs];
        for (uint32_t r = 0; r < kMarkRegs; r++) v[r] = rd(dev, kMark[r]);
        count_sample(c, v);
        IODelay(kMarkGapUs);
    }
    CPC_LOG("%s: GRBM_STATUS %#010x GRBM_STATUS2 %#010x CP_STAT %#010x CP_CPF_STATUS %#010x BUSY %#010x BUSY2 %#010x STALLED1 %#010x CP_CPC_STATUS %#010x "
            "CP_MES_CNTL %#010x RLC_CP_SCHEDULERS %#010x (first of %u samples)", where, c.first[kGrbmStatus], c.first[kGrbmStatus2], c.first[kCpStat],
            c.first[kCpfStatus], c.first[kCpfBusy], c.first[kCpfBusy2], c.first[kCpfStalled1], c.first[kCpcStatus], c.first[kMesCntl], c.first[kRlcCpSched], c.n);
    char line[400]; size_t at = 0;
    for (uint32_t b = 0; b < kBitCount && at < sizeof(line); b++)
        at += (size_t)snprintf(line + at, sizeof(line) - at, "%s%s %u", b ? ", " : "", kBits[b].name, c.set[b]);
    CPC_LOG("%s: bits set in %u samples: %s", where, c.n, line);
    if (gKeptN < kKeep) {
        Kept &k = gKept[gKeptN++];
        k = Kept{ where, c.n, c.set[idx_of("CPF_BUSY")], c.set[idx_of("CPF_CMP_BUSY")], c.set[idx_of("POST_WPTR_GFX_BUSY")],
                  c.set[idx_of("MES_HQD_BUSY")], c.set[idx_of("GUI_ACTIVE")], c.first[kCpfStatus], c.first[kMesCntl] };
    }
}

void cp_busy_marks_describe(char *t, size_t n)
{
    if (!mark_enabled()) { snprintf(t, n, "off (navi48-cpmark=0)"); return; }
    size_t at = 0;
    t[0] = 0;
    for (uint32_t i = 0; i < gKeptN && at + 1 < n; i++) {
        const Kept &k = gKept[i];
        at += (size_t)snprintf(t + at, n - at, "%s%s: CPF_STATUS %#x cpf %u cmp %u postwptr %u meshqd %u gui %u /%u", i ? "; " : "", k.where, k.cpfFirst,
                               k.cpf, k.cmp, k.postWptr, k.mesHqd, k.guiActive, k.n);
    }
}

void cp_queue_census(const DeviceContext &dev, const char *where)
{
    using namespace n48cpc;
    uint32_t v = 0;
    const bool p = PE_parse_boot_argn("navi48-cpcensus", &v, sizeof(v));
    if (!census_on(p, v) || !dev.ip.isResolved(IPBlock::GC)) return;
    const uint32_t sel = SOC15_REG_OFFSET_BIDX(dev, IPBlock::GC, 1, 0x0900);   // GRBM_GFX_CNTL (abs 0xA900)
    const uint32_t before = RREG32(dev, sel);
    CPC_LOG("census (%s): GRBM_GFX_CNTL before %#x (navi48-cpcensus=1: select writes, restored to 0)", where, before);
    for (const Slot &s : kSlots) {
        WREG32(dev, sel, grbm_select(s.me, s.pipe, s.queue));
        char line[600]; size_t at = 0;
        line[0] = 0;
        if (s.me == 0) {
            for (const Reg &r : kGfxHqd) at += (size_t)snprintf(line + at, sizeof(line) - at, "%s %#x ", r.name, rd(dev, r));
        } else {
            for (const Reg &r : kCmpHqd) at += (size_t)snprintf(line + at, sizeof(line) - at, "%s %#x ", r.name, rd(dev, r));
            if (s.me == 3) for (const Reg &r : kMesPipe) at += (size_t)snprintf(line + at, sizeof(line) - at, "%s %#x ", r.name, rd(dev, r));
        }
        CPC_LOG("census (%s): me%u/pipe%u/queue%u %s: %s", where, s.me, s.pipe, s.queue, s.what, line);
    }
    WREG32(dev, sel, 0u);
    CPC_LOG("census (%s): GRBM_GFX_CNTL restored to %#x", where, RREG32(dev, sel));
}

}  // namespace amdgpu
