//
//  dpm_boot.cpp - kext 0.0.678: GFXCLK under PMFW DPM after a fail-safe idle gate (decision and constants in dpm_gate_pure.h). Runs once, at
//  the very end of Navi48Bringup::runStages (after clock gating, the fan step and the native S1b self-test), before any client.
//
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

#include "amdgpu_regs.h"
#include "amdgpu_smu.h"
#include "amdgpu_ip.h"
#include "amdgpu_log.h"
#include "dpm_gate_pure.h"
#include "cp_census_pure.h"
#include "n4x_safety.h"

#define DPM_LOG(fmt, ...) AMDGPU_LOG("dpm", fmt, ##__VA_ARGS__)

namespace amdgpu {

static_assert(n48dpm::kStateAuto == SMUPowerState::Auto, "SMUPowerState::Auto");
static_assert(n48dpm::kStateLow == SMUPowerState::Low, "SMUPowerState::Low");
static_assert(n48dpm::kStateBootCap == SMUPowerState::BootCap, "SMUPowerState::BootCap");
static_assert(n48dpm::kMsgSetWorkloadMask != PPSMC::SetSoftMaxByFreq && n48dpm::kMsgSetWorkloadMask != PPSMC::SetSoftMinByFreq, "message ids");

namespace {

struct DpmState {
    uint32_t verdict { n48dpm::kNotRun };
    bool wanted { true };
    uint32_t samples { 0 }, busy { 0 }, gui { 0 }, cpf2 { 0 }, cpfStatus { 0 };
    uint32_t firstGrbm { 0 }, firstGrbm2 { 0 }, firstCpf { 0 };
    uint32_t capMhz { 0 };
    uint32_t pmfwMin { 0 }, pmfwMax { 0 };
    kern_return_t rangeKr { kIOReturnNotReady };
    uint32_t sentState { 0xFFFFFFFFu };
    kern_return_t clockKr { kIOReturnNotReady };
    bool workloadSent { false };
    kern_return_t workloadKr { kIOReturnNotReady };
    uint32_t restore { n48dpm::kStateLow };
    bool watchdogActive { false };
};
DpmState gDpm;

uint32_t rd(const DeviceContext &dev, const n48cpc::Reg &r) { return RREG32(dev, SOC15_REG_OFFSET_BIDX(dev, IPBlock::GC, r.idx, r.off)); }

const char *state_name(uint32_t s) {
    switch (s) {
    case SMUPowerState::Auto:    return "Auto (SetSoftMax 0xffff, SetSoftMin 0: PMFW DPM)";
    case SMUPowerState::Low:     return "Low (soft max = PMFW minimum)";
    case SMUPowerState::BootCap: return "BootCap (soft max = navi48-gfxmax)";
    default:                     return "none";
    }
}

// The gate: kGateSamples samples, kGateGapUs apart, of GRBM_STATUS / GRBM_STATUS2 / CP_CPF_STATUS (unbanked; no select, no write).
void sample_gate(const DeviceContext &dev) {
    using namespace n48cpc;
    gDpm.samples = gDpm.busy = gDpm.gui = gDpm.cpf2 = gDpm.cpfStatus = 0;
    for (uint32_t s = 0; s < n48dpm::kGateSamples; s++) {
        const uint32_t g = rd(dev, kMark[kGrbmStatus]), g2 = rd(dev, kMark[kGrbmStatus2]), c = rd(dev, kMark[kCpfStatus]);
        if (s == 0) { gDpm.firstGrbm = g; gDpm.firstGrbm2 = g2; gDpm.firstCpf = c; }
        if ((g >> n48dpm::kGuiActiveBit) & 1u) gDpm.gui++;
        if ((g2 >> n48dpm::kGrbm2CpfBusyBit) & 1u) gDpm.cpf2++;
        if ((c >> n48dpm::kCpfStatusCpfBusyBit) & 1u) gDpm.cpfStatus++;
        if (n48dpm::sample_busy(g, g2, c)) gDpm.busy++;
        gDpm.samples++;
        IODelay(n48dpm::kGateGapUs);
    }
}

}  // namespace

uint32_t dpm_boot_gate(const DeviceContext &dev, bool idleClamp, bool fullPath, uint32_t capMhz)
{
    uint32_t v = 1;
    const bool present = PE_parse_boot_argn("navi48-dpm", &v, sizeof(v));
    gDpm.wanted = n48dpm::dpm_wanted(present, v);
    gDpm.capMhz = capMhz;
    gDpm.watchdogActive = n4xs::active();
    const bool sample = idleClamp && gDpm.wanted && fullPath && dev.ip.isResolved(IPBlock::GC);
    if (sample) sample_gate(dev);
    const bool gatePassed = sample && n48dpm::gate_pass(gDpm.busy, gDpm.samples);
    if (sample)
        DPM_LOG("gate: %u of %u samples busy (GUI_ACTIVE %u, GRBM_STATUS2.CPF_BUSY %u, CP_CPF_STATUS.CPF_BUSY %u; first GRBM_STATUS %#010x "
                "GRBM_STATUS2 %#010x CP_CPF_STATUS %#010x), limit %u %% -> %s", gDpm.busy, gDpm.samples, gDpm.gui, gDpm.cpf2, gDpm.cpfStatus,
                gDpm.firstGrbm, gDpm.firstGrbm2, gDpm.firstCpf, n48dpm::kGateMaxBusyPct, gatePassed ? "PASS" : "FAIL");

    if (!dev.smuOnline) { gDpm.verdict = n48dpm::kNotFullPath; gDpm.restore = n48dpm::restore_state(gDpm.verdict, capMhz); n4xs::set_restore_state(gDpm.restore); return gDpm.verdict; }

    // Everything below under the shared SMU mailbox lock: no metrics read, thermal clamp/restore or UCLK pin interleaves.
    SmuSeq seq;
    if (!seq.held) {   // as the fan step: nothing is sent without the mailbox lock; the clamp stays
        gDpm.verdict = n48dpm::kApplyFailed; gDpm.restore = n48dpm::restore_state(gDpm.verdict, capMhz); n4xs::set_restore_state(gDpm.restore);
        DPM_LOG("the SMU mailbox lock is unavailable; nothing sent, the boot clamp stays");
        return gDpm.verdict;
    }
    // The PMFW GFXCLK range, for the record (GetMin/MaxDpmFreq, as the boot clamp reads it).
    {
        uint32_t lo = 0, hi = 0;
        gDpm.rangeKr = smu_send_msg_with_param(dev, PPSMC::GetMinDpmFreq, PPCLK::GFXCLK << 16, &lo);
        if (gDpm.rangeKr == kIOReturnSuccess) gDpm.rangeKr = smu_send_msg_with_param(dev, PPSMC::GetMaxDpmFreq, PPCLK::GFXCLK << 16, &hi);
        if (gDpm.rangeKr == kIOReturnSuccess) { gDpm.pmfwMin = lo; gDpm.pmfwMax = hi; }
    }
    gDpm.verdict = n48dpm::decide(gDpm.wanted, idleClamp, fullPath, gatePassed, n4xs::clamped());
    // The restore target first: a thermal release from here on returns to the new policy.
    gDpm.restore = n48dpm::restore_state(gDpm.verdict, capMhz);
    n4xs::set_restore_state(gDpm.restore);

    if (gDpm.verdict == n48dpm::kApplied) {
        const uint32_t st = n48dpm::dpm_state(capMhz);
        gDpm.sentState = st;
        gDpm.clockKr = smu_set_power_state(dev, st);
        if (gDpm.clockKr != kIOReturnSuccess) {
            // Fail safe: back to the boot clamp, and the watchdog restores the clamp too.
            gDpm.verdict = n48dpm::kApplyFailed;
            gDpm.restore = n48dpm::restore_state(gDpm.verdict, capMhz);
            n4xs::set_restore_state(gDpm.restore);
            const kern_return_t back = smu_set_power_state(dev, n48dpm::clamp_state(capMhz));
            DPM_LOG("clock messages failed %#x; boot clamp re-sent %#x", gDpm.clockKr, back);
        }
    }
    if (gDpm.verdict == n48dpm::kApplied || gDpm.verdict == n48dpm::kHeldThermal) {
        // Linux smu_bump_power_profile_mode: SetWorkloadMask(1 << WORKLOAD_PPLIB_DEFAULT_BIT) once DPM runs. A refusal is logged, not fatal.
        gDpm.workloadSent = true;
        gDpm.workloadKr = smu_send_msg_with_param(dev, n48dpm::kMsgSetWorkloadMask, n48dpm::workload_mask_bootup_default(), nullptr);
    }
    DPM_LOG("%s; PMFW GFXCLK %u..%u MHz (kr %#x); sent %s kr %#x; SetWorkloadMask(%#x) %s kr %#x; thermal restore -> %s; cap navi48-gfxmax=%u; "
            "watchdog %s", n48dpm::verdict_name(gDpm.verdict), gDpm.pmfwMin, gDpm.pmfwMax, gDpm.rangeKr, state_name(gDpm.sentState), gDpm.clockKr,
            n48dpm::workload_mask_bootup_default(), gDpm.workloadSent ? "sent" : "not sent", gDpm.workloadKr, state_name(gDpm.restore), capMhz,
            gDpm.watchdogActive ? "on" : "OFF");
    return gDpm.verdict;
}

void dpm_describe(char *t, size_t n)
{
    snprintf(t, n, "%s; gate %u/%u samples busy (GUI_ACTIVE %u, CPF_BUSY %u/%u; limit %u %%; first CP_CPF_STATUS %#x); PMFW GFXCLK %u..%u MHz; "
             "sent %s (soft min %u, soft max %s) kr %#x; SetWorkloadMask(%#x, bootup default) %s kr %#x; GameClockAc not sent (Linux AUTO sends 0xffff); "
             "thermal restore %s; navi48-gfxmax %u; navi48-dpm %s; watchdog %s",
             n48dpm::verdict_name(gDpm.verdict), gDpm.busy, gDpm.samples, gDpm.gui, gDpm.cpf2, gDpm.cpfStatus, n48dpm::kGateMaxBusyPct, gDpm.firstCpf,
             gDpm.pmfwMin, gDpm.pmfwMax, state_name(gDpm.sentState), n48dpm::kAutoSoftMin,
             gDpm.sentState == SMUPowerState::Auto ? "0xffff" : gDpm.sentState == SMUPowerState::BootCap ? "cap" : "-", gDpm.clockKr,
             n48dpm::workload_mask_bootup_default(), gDpm.workloadSent ? "sent" : "not sent", gDpm.workloadKr, state_name(gDpm.restore), gDpm.capMhz,
             gDpm.wanted ? "on" : "0", gDpm.watchdogActive ? "on" : "off");
}

}  // namespace amdgpu
