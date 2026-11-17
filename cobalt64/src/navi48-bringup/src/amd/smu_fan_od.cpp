//
//  smu_fan_od.cpp - kext 0.0.676: the PMFW zero-RPM fan mode, the kernel half (SMU table transfers through the driver-table VRAM slot, logging,
//  registry text). Every decision is in smu_od_pure.h (the Linux port and its attribution are there; host-tested by tests/fan_od676_test.cpp).
//
//  WHEN. Once per boot, from Navi48Bringup::runStages right after GFX clock gating: the full bring-up ladder completed, so smc_hw_setup ran
//  EnableAllSmuFeatures and the protection gate saw THROTTLERS, FW_CTF and FAN_CONTROL running. Never from a user client, never live.
//  WHAT. Boot-arg navi48-fan-zerorpm absent: nothing is read or written (the PMFW default, exactly 0.0.675). =0: FanZeroRpmEnable = 0 (the fans
//  always spin). =1: FanZeroRpmEnable = 1. Any other value: nothing.
//  HOW. Under the shared SMU mailbox lock (SmuSeq, held for the whole sequence, so no metrics read, clamp or UCLK pin interleaves):
//    1. TransferTableSmu2Dram(TABLE_COMBO_PPTABLE) into the driver-table slot (canary-filled first), the PPTable layout and the OD limits checked;
//    2. TransferTableSmu2Dram(TABLE_OVERDRIVE) twice, both reads identical, the fan block plausible against the limits; logged in full;
//    3. the upload image (the read table, FanZeroRpmEnable = value, FeatureCtrlMask = BIT(ZERO_FAN)) staged in the slot and read back;
//    4. TransferTableDram2Smu(TABLE_OVERDRIVE) (the PMFW's arg checked for TABLE_TRANSFER_FAILED);
//    5. TransferTableSmu2Dram(TABLE_OVERDRIVE) and a byte-for-byte compare.
//  Steps 1-3 failing write nothing to the PMFW; after step 4 nothing more is ever written, whatever 4-5 report.
//  The slot is the one smu_read_metrics uses; VRAM goes through the MM_INDEX window like smu_read_metrics (boot time, before any client or
//  residency copier exists).
//
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

#include "amdgpu_smu.h"
#include "amdgpu_log.h"
#include "smu_od_pure.h"

namespace amdgpu {
namespace {

n48od::Result gFan = { n48od::kWantDefault, n48od::kNotRun, 0u, 0u, 0xFFu, 0xFFu, 0u, 0u, 0u, {}, 0u, 0u, 0u };
constexpr uint32_t kCanary = 0xA5A5A5A5u;
constexpr uint32_t kComboReadBytes = n48od::kComboSmcPPTable + n48od::kPPTableBytes;   // the header + PPTable_t
uint8_t gCombo[(kComboReadBytes + 3u) & ~3u];   // boot-only scratch (one call per boot; too large for the kernel stack)

uint64_t slot(const DeviceContext &dev) { return dev.vramBase + kSMUDriverTableVRAMOffset; }

// Canary-fill [0, bytes) of the slot, transfer table `id` PMFW -> slot, copy it out. False when the message failed or the PMFW wrote nothing.
bool table_read(const DeviceContext &dev, uint32_t id, uint8_t *dst, uint32_t bytes, kern_return_t *krOut) {
    const uint32_t dwords = (bytes + 3u) / 4u;
    for (uint32_t i = 0; i < dwords; i++) WVRAM32_via_mm(dev, slot(dev) + i * 4u, kCanary);
    const kern_return_t kr = smu_send_msg_with_param(dev, PPSMCTable::TransferTableSmu2Dram, id, nullptr);
    if (krOut) *krOut = kr;
    if (kr != kIOReturnSuccess) { SMU_LOG("fan-od: TransferTableSmu2Dram(%u) failed kr=0x%x", id, (unsigned)kr); return false; }
    uint32_t canaries = 0;
    for (uint32_t i = 0; i < dwords; i++) {
        const uint32_t v = RVRAM32_via_mm(dev, slot(dev) + i * 4u);
        if (v == kCanary) canaries++;
        for (uint32_t b = 0; b < 4u && i * 4u + b < bytes; b++) dst[i * 4u + b] = (uint8_t)(v >> (8u * b));
    }
    if (canaries == dwords) { SMU_LOG("fan-od: table %u: the PMFW wrote nothing into the slot", id); return false; }
    return true;
}

void dump(const char *what, const uint8_t *b, uint32_t bytes) {
    for (uint32_t o = 0; o < bytes; o += 32u) {
        uint32_t w[8] = {};
        for (uint32_t i = 0; i < 8u && o + i * 4u < bytes; i++) w[i] = n48od::rd32(b, o + i * 4u);
        SMU_LOG("fan-od: %s +0x%03x: %08x %08x %08x %08x %08x %08x %08x %08x", what, o, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7]);
    }
}

uint32_t finish(uint32_t verdict) { gFan.verdict = verdict; SMU_LOG("fan-od: %s: %s", n48od::want_name(gFan.want), n48od::verdict_name(verdict)); return verdict; }

uint32_t run(const DeviceContext &dev, uint32_t value) {
    using namespace n48od;
    kern_return_t kr = kIOReturnSuccess;
    // 1. the PPTable: layout, version, OD limits, ZERO_FAN support, the value's range.
    if (!table_read(dev, kTableComboPPTable, gCombo, kComboReadBytes, &kr)) { gFan.kr = (uint32_t)kr; return finish(kPPTableReadFailed); }
    const uint32_t pv = check_pptable(gCombo, kComboReadBytes, gFan.lim);
    const Limits &l = gFan.lim;
    SMU_LOG("fan-od: combo PPTable: PPTable_t at 0x%x size 0x%x, SkuTable at 0x%x size 0x%x (IF 0x2E: 0x%x/0x%x, 0x%x/0x%x), SkuTable.Version 0x%x (want 0x%x)",
            l.pptStart, l.pptSize, l.skuStart, l.skuSize, kComboSmcPPTable, kPPTableBytes, kComboSmcPPTable + kSkuInPPTable, kSkuBytes, l.skuVersion, kPPTableVersion);
    dump("combo header", gCombo, kHdrBytes);
    if (l.skuStart == kComboSmcPPTable + kSkuInPPTable && l.skuSize == kSkuBytes) {
        dump("OD limits BasicMin", gCombo + l.skuStart + kSkuOdBasicMin, kLimBytes);
        dump("OD limits BasicMax", gCombo + l.skuStart + kSkuOdBasicMax, kLimBytes);
    }
    SMU_LOG("fan-od: OD limits: FeatureCtrlMask min 0x%x max 0x%x (ZERO_FAN bit 11 %s), FanZeroRpmEnable %u..%u, FanStopTemp %u..%u C, GfxclkFoffset %d..%d MHz, "
            "Uclk %u..%u MHz, FanTargetTemperature %u..%u C, MaxOpTemp %u..%u C (Linux on this card: SCLK_OFFSET -500..1000, MCLK 97..1500)",
            l.maskMin, l.maskMax, (l.maskMax & kOdFeatureZeroFan) ? "advertised" : "NOT advertised", l.zeroMin, l.zeroMax, l.stopMin, l.stopMax,
            (int)l.gfxOffMin, (int)l.gfxOffMax, l.uclkMin, l.uclkMax, l.targetMin, l.targetMax, l.opMin, l.opMax);
    if (pv != kNotRun) return finish(pv);
    if (!value_in_range(value, l)) return finish(kOutOfRange);
    // 2. the OD table, twice.
    uint8_t od[kOdBytes] = {}, od2[kOdBytes] = {};
    if (!table_read(dev, kTableOverdrive, od, kOdBytes, &kr)) { gFan.kr = (uint32_t)kr; return finish(kOdReadFailed); }
    if (!table_read(dev, kTableOverdrive, od2, kOdBytes, &kr)) { gFan.kr = (uint32_t)kr; return finish(kOdReadFailed); }
    dump("OD table", od, kOdBytes);
    gFan.before = rd8(od, kOdFanZeroRpmEnable); gFan.stopTemp = rd8(od, kOdFanZeroRpmStopTemp); gFan.fanMode = rd8(od, kOdFanMode);
    gFan.targetTemp = rd16(od, kOdFanTargetTemperature);
    SMU_LOG("fan-od: OD table: FanZeroRpmEnable %u, FanZeroRpmStopTemp %u C, FanMode %u, FanTargetTemperature %u C, MaxOpTemp %u C, Uclk %u..%u MHz, GfxclkFoffset %d",
            gFan.before, gFan.stopTemp, gFan.fanMode, gFan.targetTemp, rd8(od, kOdMaxOpTemp), rd16(od, kOdUclkFmin), rd16(od, kOdUclkFmax), (int)rds16(od, kOdGfxclkFoffset));
    for (uint32_t i = 0; i < kOdBytes; i++) if (od[i] != od2[i]) return finish(kOdUnstable);
    if (!od_plausible(od, l)) return finish(kOdImplausible);
    if (gFan.before == value) { gFan.after = gFan.before; return finish(kAlready); }
    // 3. the upload image, staged and read back.
    uint8_t up[kOdBytes] = {};
    build_upload(od, value, up);
    for (uint32_t i = 0; i < kOdBytes / 4u; i++) WVRAM32_via_mm(dev, slot(dev) + i * 4u, rd32(up, i * 4u));
    for (uint32_t i = 0; i < kOdBytes / 4u; i++)
        if (RVRAM32_via_mm(dev, slot(dev) + i * 4u) != rd32(up, i * 4u)) return finish(kStageFailed);
    // 4. the upload. From here on nothing more is written, whatever happens.
    uint32_t arg = 0;
    kr = smu_send_msg_with_param(dev, PPSMCTable::TransferTableDram2Smu, kTableOverdrive, &arg);
    gFan.kr = (uint32_t)kr; gFan.arg = arg;
    SMU_LOG("fan-od: TransferTableDram2Smu(OVERDRIVE, FeatureCtrlMask 0x%x, FanZeroRpmEnable %u) kr=0x%x arg=0x%x%s", kOdFeatureZeroFan, value, (unsigned)kr, arg,
            upload_rejected(arg) ? " (TABLE_TRANSFER_FAILED: invalid content)" : "");
    if (upload_rejected(arg)) { SMU_LOG("fan-od: the PMFW's OD error code %u", od_error_code(arg)); return finish(kUploadRejected); }
    if (kr != kIOReturnSuccess) return finish(kUploadFailed);
    // 5. the read-back.
    uint8_t back[kOdBytes] = {};
    if (!table_read(dev, kTableOverdrive, back, kOdBytes, &kr)) return finish(kReadbackFailed);
    gFan.after = rd8(back, kOdFanZeroRpmEnable);
    if (!verify_readback(up, back, value)) { dump("OD read-back", back, kOdBytes); return finish(kVerifyMismatch); }
    return finish(kApplied);
}

}  // namespace

uint32_t smu_fan_zerorpm_boot(const DeviceContext &dev, bool fullPath)
{
    using namespace n48od;
    uint32_t v = 0;
    const bool present = PE_parse_boot_argn("navi48-fan-zerorpm", &v, sizeof(v));
    init(gFan, want_of(present, v));
    if (gFan.want == kWantDefault) return finish(kDefault);
    if (gFan.want == kWantInvalid) return finish(kBadArg);
    if (!dev.smuOnline || smu_driver_table_mc(dev) == 0) return finish(kNoSmu);
    if (!fullPath || !smu_protections_verified()) return finish(kNotFullPath);
    uint32_t verdict;
    {
        SmuSeq seq;
        if (!seq.held) return finish(kNoLock);   // a multi-message table sequence never runs unlocked
        verdict = run(dev, gFan.want == kWantOff ? 0u : 1u);
    }
    // One metrics read for the registry (the fans take seconds to react; `navi48test metrics` shows them live).
    SmuMetricsResult m{};
    if (smu_read_metrics(dev, &m) == kIOReturnSuccess) { gFan.rpm = m.metrics.AvgFanRpm; gFan.pwm = m.metrics.AvgFanPwm; gFan.metricsOk = 1u; }
    return verdict;
}

const n48od::Result &smu_fan_result() { return gFan; }

void smu_fan_describe(char *t, size_t n)
{
    using namespace n48od;
    const Result &r = gFan;
    if (r.verdict == kDefault || r.verdict == kNotRun) {
        snprintf(t, n, "zero-rpm: %s; %s (navi48-fan-zerorpm=0 keeps the fans spinning)", want_name(r.want), verdict_name(r.verdict));
        return;
    }
    snprintf(t, n, "zero-rpm: %s; %s; FanZeroRpmEnable %u -> %u (0xff = not read), stop temp %u C, FanMode %u, target %u C; upload kr 0x%x arg 0x%x; "
             "PPTable SkuTable 0x%x/0x%x version 0x%x, OD mask max 0x%x, zero-fan limits %u..%u, stop-temp limits %u..%u C; fan %u rpm %u%% pwm (%s)",
             want_name(r.want), verdict_name(r.verdict), r.before, r.after, r.stopTemp, r.fanMode, r.targetTemp, r.kr, r.arg,
             r.lim.skuStart, r.lim.skuSize, r.lim.skuVersion, r.lim.maskMax, r.lim.zeroMin, r.lim.zeroMax, r.lim.stopMin, r.lim.stopMax,
             r.rpm, r.pwm, r.metricsOk ? "metrics at boot" : "metrics not read");
}

}  // namespace amdgpu
