// 0.0.676 host test: the zero-RPM OverDrive decisions (amd/smu_od_pure.h) against Linux's own structs, the navi48-gfxmax cap (amd/smu_gfxmax_pure.h),
// the UCLK fallback's release default (amd/smu_uclkpin_pure.h), and source pins on the kernel glue (amd/smu_fan_od.cpp).
// Build: clang++ -std=c++17 -I src -I <linux>/pm/swsmu/inc tests/fan_od676_test.cpp ; run: ./a.out <kernel source dir (the one holding src/)>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <fstream>
#include <sstream>

struct atom_common_table_header { uint16_t structuresize; uint8_t format_revision; uint8_t content_revision; };
#include "pmfw_if/smu14_driver_if_v14_0.h"
#include "smu_v14_0_2_pptable.h"

#include "amd/smu_od_pure.h"
#include "amd/smu_gfxmax_pure.h"
#include "amd/smu_uclkpin_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } }

using namespace n48od;

// ---- the offsets in smu_od_pure.h are Linux's (IF 0x2E, PPTABLE_VERSION 0x1B) ----
static void test_layout() {
    expect(sizeof(OverDriveTable_t) == kOdBytes, "sizeof OverDriveTable_t");
    expect(sizeof(OverDriveLimits_t) == kLimBytes, "sizeof OverDriveLimits_t");
    expect(offsetof(OverDriveTable_t, FeatureCtrlMask) == kOdFeatureCtrlMask, "od FeatureCtrlMask");
    expect(offsetof(OverDriveTable_t, GfxclkFoffset) == kOdGfxclkFoffset, "od GfxclkFoffset");
    expect(offsetof(OverDriveTable_t, UclkFmin) == kOdUclkFmin && offsetof(OverDriveTable_t, UclkFmax) == kOdUclkFmax, "od Uclk");
    expect(offsetof(OverDriveTable_t, FanLinearPwmPoints) == kOdFanLinearPwmPoints && offsetof(OverDriveTable_t, FanLinearTempPoints) == kOdFanLinearTempPoints, "od fan curve");
    expect(NUM_OD_FAN_MAX_POINTS == kOdFanPoints, "fan points");
    expect(offsetof(OverDriveTable_t, FanMinimumPwm) == kOdFanMinimumPwm && offsetof(OverDriveTable_t, AcousticTargetRpmThreshold) == kOdAcousticTarget &&
           offsetof(OverDriveTable_t, AcousticLimitRpmThreshold) == kOdAcousticLimit, "od legacy fan");
    expect(offsetof(OverDriveTable_t, FanTargetTemperature) == kOdFanTargetTemperature, "od FanTargetTemperature");
    expect(offsetof(OverDriveTable_t, FanZeroRpmEnable) == kOdFanZeroRpmEnable, "od FanZeroRpmEnable");
    expect(offsetof(OverDriveTable_t, FanZeroRpmStopTemp) == kOdFanZeroRpmStopTemp, "od FanZeroRpmStopTemp");
    expect(offsetof(OverDriveTable_t, FanMode) == kOdFanMode && offsetof(OverDriveTable_t, MaxOpTemp) == kOdMaxOpTemp, "od FanMode/MaxOpTemp");
    expect(offsetof(OverDriveLimits_t, FeatureCtrlMask) == kLimFeatureCtrlMask && offsetof(OverDriveLimits_t, GfxclkFoffset) == kLimGfxclkFoffset, "lim mask/gfx");
    expect(offsetof(OverDriveLimits_t, UclkFmin) == kLimUclkFmin && offsetof(OverDriveLimits_t, UclkFmax) == kLimUclkFmax, "lim uclk");
    expect(offsetof(OverDriveLimits_t, FanTargetTemperature) == kLimFanTargetTemperature, "lim target");
    expect(offsetof(OverDriveLimits_t, FanZeroRpmEnable) == kLimFanZeroRpmEnable && offsetof(OverDriveLimits_t, MaxOpTemp) == kLimMaxOpTemp, "lim zero/op");
    expect(PPTABLE_VERSION == kPPTableVersion, "PPTABLE_VERSION");
    expect(sizeof(PPTable_t) == kPPTableBytes && sizeof(SkuTable_t) == kSkuBytes && offsetof(PPTable_t, SkuTable) == kSkuInPPTable, "PPTable sizes");
    expect(offsetof(SkuTable_t, Version) == kSkuVersion, "sku Version");
    expect(offsetof(SkuTable_t, MsgLimits) + offsetof(MsgLimits_t, FanStopTempMin) == kSkuFanStopTempMin, "sku FanStopTempMin");
    expect(offsetof(SkuTable_t, MsgLimits) + offsetof(MsgLimits_t, FanStopTempMax) == kSkuFanStopTempMax, "sku FanStopTempMax");
    expect(offsetof(SkuTable_t, OverDriveLimitsBasicMin) == kSkuOdBasicMin && offsetof(SkuTable_t, OverDriveLimitsBasicMax) == kSkuOdBasicMax, "sku OD limits");
    expect(offsetof(struct smu_14_0_2_powerplay_table, smc_pptable) == kComboSmcPPTable, "combo smc_pptable");
    expect(offsetof(struct smu_14_0_2_powerplay_table, pmfw_pptable_start_offset) == kHdrPPTableStart &&
           offsetof(struct smu_14_0_2_powerplay_table, pmfw_pptable_size) == kHdrPPTableSize &&
           offsetof(struct smu_14_0_2_powerplay_table, pmfw_sku_table_start_offset) == kHdrSkuStart &&
           offsetof(struct smu_14_0_2_powerplay_table, pmfw_sku_table_size) == kHdrSkuSize, "combo header offsets");
    expect(sizeof(struct smu_14_0_2_powerplay_table) <= kComboRegionBytes, "combo fits the region");
    expect(PP_OD_FEATURE_ZERO_FAN_BIT == kOdFeatureZeroFanBit && TABLE_OVERDRIVE == kTableOverdrive && TABLE_COMBO_PPTABLE == kTableComboPPTable &&
           TABLE_TRANSFER_FAILED == kTableTransferFailed, "ids");
}

// A combo PPTable like this card's (Linux 7.2 on it: SCLK_OFFSET -500..1000, MCLK 97..1500, OD_MCLK 97/1259).
static struct smu_14_0_2_powerplay_table *make_combo(uint8_t *buf) {
    memset(buf, 0, kComboRegionBytes);
    auto *c = reinterpret_cast<struct smu_14_0_2_powerplay_table *>(buf);
    c->pmfw_pptable_start_offset = offsetof(struct smu_14_0_2_powerplay_table, smc_pptable);
    c->pmfw_pptable_size = sizeof(PPTable_t);
    c->pmfw_sku_table_start_offset = offsetof(struct smu_14_0_2_powerplay_table, smc_pptable) + offsetof(PPTable_t, SkuTable);
    c->pmfw_sku_table_size = sizeof(SkuTable_t);
    SkuTable_t &s = c->smc_pptable.SkuTable;
    s.Version = PPTABLE_VERSION;
    s.MsgLimits.FanStopTempMin = 30; s.MsgLimits.FanStopTempMax = 70;
    OverDriveLimits_t &mn = s.OverDriveLimitsBasicMin, &mx = s.OverDriveLimitsBasicMax;
    mn.FeatureCtrlMask = 0x3FFF; mx.FeatureCtrlMask = 0x3FFF;
    mn.GfxclkFoffset = -500; mx.GfxclkFoffset = 1000;
    mn.UclkFmin = 97; mx.UclkFmax = 1500;
    mn.FanTargetTemperature = 25; mx.FanTargetTemperature = 110;
    mn.FanZeroRpmEnable = 0; mx.FanZeroRpmEnable = 1;
    mn.MaxOpTemp = 50; mx.MaxOpTemp = 110;
    return c;
}
static void make_od(OverDriveTable_t &o) {
    memset(&o, 0, sizeof(o));
    o.UclkFmin = 97; o.UclkFmax = 1259; o.FanTargetTemperature = 95; o.FanZeroRpmEnable = 1; o.FanZeroRpmStopTemp = 50; o.FanMode = FAN_MODE_AUTO;
    o.MaxOpTemp = 110;
    for (int i = 0; i < NUM_OD_FAN_MAX_POINTS; i++) { o.FanLinearTempPoints[i] = (uint8_t)(25 + 15 * i); o.FanLinearPwmPoints[i] = (uint8_t)(15 + 15 * i); }
}

static void test_pptable() {
    static uint8_t buf[kComboRegionBytes];
    const uint32_t len = kComboSmcPPTable + kPPTableBytes;
    Limits l{};
    auto *c = make_combo(buf);
    expect(check_pptable(buf, len, l) == kNotRun, "the card-like combo passes");
    expect(l.zeroMin == 0 && l.zeroMax == 1 && l.stopMin == 30 && l.stopMax == 70 && l.gfxOffMin == -500 && l.gfxOffMax == 1000 && l.uclkMin == 97 &&
           l.uclkMax == 1500 && l.skuVersion == 0x1B, "limits decoded from Linux's struct");
    expect(value_in_range(0, l) && value_in_range(1, l) && !value_in_range(2, l), "Linux's range check");
    expect(check_pptable(buf, len - 1, l) == kPPTableReadFailed, "short read");
    expect(check_pptable(nullptr, len, l) == kPPTableReadFailed, "null");
    c->smc_pptable.SkuTable.Version = 0x1C; expect(check_pptable(buf, len, l) == kPPTableLayout, "another PPTABLE_VERSION"); make_combo(buf);
    c->pmfw_pptable_size = sizeof(PPTable_t) + 4; expect(check_pptable(buf, len, l) == kPPTableLayout, "another PPTable_t size"); make_combo(buf);
    c->pmfw_sku_table_size = sizeof(SkuTable_t) + 8; expect(check_pptable(buf, len, l) == kPPTableLayout, "another SkuTable_t size"); make_combo(buf);
    c->pmfw_sku_table_start_offset += 4; expect(check_pptable(buf, len, l) == kPPTableLayout, "a shifted SkuTable"); make_combo(buf);
    c->pmfw_pptable_start_offset += 32; expect(check_pptable(buf, len, l) == kPPTableLayout, "a shifted PPTable_t"); make_combo(buf);
    c->smc_pptable.SkuTable.OverDriveLimitsBasicMax.FeatureCtrlMask &= ~(1u << PP_OD_FEATURE_ZERO_FAN_BIT);
    expect(check_pptable(buf, len, l) == kNotSupported, "ZERO_FAN not advertised"); make_combo(buf);
    c->smc_pptable.SkuTable.OverDriveLimitsBasicMin.FeatureCtrlMask = 0; expect(check_pptable(buf, len, l) == kNotSupported, "OD off (min mask 0)"); make_combo(buf);
    c->smc_pptable.SkuTable.OverDriveLimitsBasicMax.FanZeroRpmEnable = 7; expect(check_pptable(buf, len, l) == kPPTableLayout, "zero-fan limit not a boolean"); make_combo(buf);
    c->smc_pptable.SkuTable.OverDriveLimitsBasicMin.FanZeroRpmEnable = 1; c->smc_pptable.SkuTable.OverDriveLimitsBasicMax.FanZeroRpmEnable = 1;
    expect(check_pptable(buf, len, l) == kNotRun && !value_in_range(0, l), "a board that forbids turning zero RPM off: 0 out of range"); make_combo(buf);
    c->smc_pptable.SkuTable.MsgLimits.FanStopTempMin = 80; expect(check_pptable(buf, len, l) == kPPTableLayout, "stop-temp limits inverted"); make_combo(buf);
    c->smc_pptable.SkuTable.OverDriveLimitsBasicMax.UclkFmax = 60000; expect(check_pptable(buf, len, l) == kPPTableLayout, "uclk limit absurd"); make_combo(buf);
}

static void test_od() {
    static uint8_t buf[kComboRegionBytes];
    Limits l{};
    make_combo(buf);
    expect(check_pptable(buf, kComboSmcPPTable + kPPTableBytes, l) == kNotRun, "limits");
    OverDriveTable_t o; make_od(o);
    const uint8_t *b = reinterpret_cast<const uint8_t *>(&o);
    expect(od_plausible(b, l), "the boot OD table is plausible");
    OverDriveTable_t t;
    t = o; t.FanZeroRpmEnable = 2; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "zero-rpm not boolean");
    t = o; t.FanMode = 3; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "FanMode not a FanMode_e");
    t = o; t.FanZeroRpmStopTemp = 0; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "stop temp 0");
    t = o; t.FanZeroRpmStopTemp = 90; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "stop temp above MsgLimits");
    t = o; t.FanTargetTemperature = 200; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "target temp out of limits");
    t = o; t.MaxOpTemp = 20; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "MaxOpTemp out of limits");
    t = o; t.UclkFmin = 1300; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "uclk min > max");
    t = o; t.UclkFmax = 2000; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "uclk max over limit");
    t = o; t.GfxclkFoffset = 2000; expect(!od_plausible(reinterpret_cast<uint8_t *>(&t), l), "gfx offset over limit");
    // A table shifted by one byte or two bytes (an inserted field before the fan block) is refused.
    for (uint32_t shift = 1; shift <= 4; shift++) {
        uint8_t sh[kOdBytes + 8] = {};
        memcpy(sh + shift, b, kOdBytes);
        expect(!od_plausible(sh, l), "a shifted OD table is refused");
    }
    uint8_t up[kOdBytes];
    build_upload(b, 0, up);
    const OverDriveTable_t *u = reinterpret_cast<const OverDriveTable_t *>(up);
    expect(u->FeatureCtrlMask == (1u << PP_OD_FEATURE_ZERO_FAN_BIT), "Linux's commit mask: ZERO_FAN only");
    expect(u->FanZeroRpmEnable == 0 && u->FanZeroRpmStopTemp == o.FanZeroRpmStopTemp && u->FanMode == o.FanMode, "only FanZeroRpmEnable changes");
    expect(memcmp(up + 4, b + 4, kOdFanZeroRpmEnable - 4) == 0 && memcmp(up + kOdFanZeroRpmEnable + 1, b + kOdFanZeroRpmEnable + 1, kOdBytes - kOdFanZeroRpmEnable - 1) == 0,
           "every other byte as read");
    uint8_t back[kOdBytes]; memcpy(back, up, kOdBytes); memset(back, 0, 4);
    expect(verify_readback(up, back, 0), "read-back equal outside FeatureCtrlMask");
    back[kOdFanZeroRpmEnable] = 1; expect(!verify_readback(up, back, 0), "read-back with the old value");
    memcpy(back, up, kOdBytes); back[0x50] ^= 1; expect(!verify_readback(up, back, 0), "read-back with another byte changed");
    expect(upload_rejected(0xFF) && upload_rejected(0x000C00FF) && od_error_code(0x000C00FF) == OD_FAN_ZERO_RPM_STOP_TEMP_ERROR && !upload_rejected(0x8) && !upload_rejected(0),
           "TABLE_TRANSFER_FAILED and the OD error code");
    expect(want_of(false, 0) == kWantDefault && want_of(false, 1) == kWantDefault && want_of(true, 0) == kWantOff && want_of(true, 1) == kWantOn &&
           want_of(true, 2) == kWantInvalid, "the boot-arg");
    Result r; init(r, kWantOff);
    expect(r.verdict == kNotRun && r.before == 0xFF && r.after == 0xFF, "result init");
    for (uint32_t v = 0; v <= 43; v++) expect(verdict_name(v) != nullptr, "verdict names");
}

static void test_gfxmax() {
    using namespace n48gfx;
    expect(requested_of(false, 2500) == 0 && requested_of(true, 0) == 0 && requested_of(true, 2500) == 2500 && requested_of(true, 20000) == 0, "gfxmax boot-arg");
    expect(cap_mhz(0, 500, 3500) == 500, "no request: the PMFW minimum (Low)");
    expect(cap_mhz(1500, 500, 3500) == 1500, "in range");
    expect(cap_mhz(100, 500, 3500) == 500, "below the minimum: the minimum");
    expect(cap_mhz(9000, 500, 3500) == 3500, "above the maximum: the maximum");
    expect(cap_mhz(1500, 0, 3500) == 0 && cap_mhz(1500, 4000, 3500) == 0 && cap_mhz(1500, 500, 20000) == 0, "an implausible PMFW range is refused");
}

static void test_uclk_release() {
    using namespace n48uclk;
    using namespace n48uclk::fb;
    expect(!quiet_release_enabled(false, 0) && !quiet_release_enabled(true, 0) && quiet_release_enabled(true, 1) && !quiet_release_enabled(true, 2), "release boot-arg");
    State s; init(s, kModeAuto, false, false);
    expect(!s.quietAllowed, "0.0.676 default: no time-limited release");
    s.armed = true;
    uint64_t t = 1000;
    // stage 1, then stage 2 (pin)
    expect(step(s, kModeAuto, t, 3, true) == kStutterOff, "stage 1"); done(s, kStutterOff, true, t);
    t += 100; expect(step(s, kModeAuto, t, 3, true) == kPin, "stage 2"); done(s, kPin, true, t);
    t += kQuietReleaseMs * 3; expect(step(s, kModeAuto, t, 0, true) == kNone && s.pinned, "the pin holds past 10 min without underflow");
    State q; init(q, kModeAuto, false, true);
    expect(q.quietAllowed, "navi48-uclkpin-release=1: the 0.0.675 release");
    State d; init(d, kModeAuto, false);
    expect(d.quietAllowed, "the three-argument form keeps its 0.0.674 meaning");
    State f; init(f, kModeForce, true, true);
    expect(!f.quietAllowed, "FORCE is never released");
    t += 10; expect(step(s, kModeAuto, t, 0, false) == kNone, "display off"); t += kOffReleaseMs;
    expect(step(s, kModeAuto, t, 0, false) == kRelease, "the display-off release is unchanged");
}

static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static size_t count(const std::string &s, const std::string &n) { size_t c = 0, at = 0; while ((at = s.find(n, at)) != std::string::npos) { c++; at += n.size(); } return c; }

static void test_sources(const char *dir) {
    if (!dir) { printf("(source pins skipped: no directory given)\n"); return; }
    const std::string root = dir;
    const std::string od = slurp(root + "/src/amd/smu_fan_od.cpp"), bring = slurp(root + "/src/Navi48Bringup.cpp"), smu = slurp(root + "/src/amd/smu_v14_0.cpp");
    const std::string dcn = slurp(root + "/src/dcn/navi48_dcn.cpp"), init = slurp(root + "/src/amd/amdgpu_init.cpp"), uc = slurp(root + "/src/Navi48UserClient.cpp");
    expect(!od.empty() && !bring.empty() && !smu.empty() && !dcn.empty() && !init.empty() && !uc.empty(), "sources read");
    // The one PMFW write of the fan code, after every check.
    expect(count(od, "TransferTableDram2Smu,") == 1, "smu_fan_od.cpp sends TransferTableDram2Smu exactly once");
    const size_t up = od.find("PPSMCTable::TransferTableDram2Smu,");
    expect(up != std::string::npos && od.find("od_plausible(od, l)") < up && od.find("check_pptable(") < up && od.find("value_in_range(") < up &&
           od.find("kOdUnstable") < up && od.find("kStageFailed") < up, "every check comes before the upload");
    expect(od.find("\"navi48-fan-zerorpm\"") != std::string::npos && od.find("if (gFan.want == kWantDefault) return finish(kDefault);") != std::string::npos,
           "boot-arg absent: nothing read or written");
    expect(od.find("if (!seq.held) return finish(kNoLock);") != std::string::npos, "never unlocked");
    expect(od.find("smu_protections_verified()") != std::string::npos, "only after the protection gate (EnableAllSmuFeatures ran)");
    // Called once, from runStages after clock gating, nowhere else.
    expect(count(bring, "smu_fan_zerorpm_boot(") == 1 && bring.find("smu_fan_zerorpm_boot(") > bring.find("gfx_v12_0_enable_clock_gating(dev"), "the fan step runs once, after clock gating");
    expect(bring.find("setProperty(\"Navi48,Fan\"") != std::string::npos, "Navi48,Fan published");
    expect(uc.find("smu_fan") == std::string::npos, "no user-client path to the fan code");
    // gfxmax: Low unchanged, the thermal clamp still Low, the user client still 0..4.
    expect(init.find("smu_set_power_state(*ctx.dev, smu_gfx_boot_state())") != std::string::npos, "the idle clamp uses the boot state");
    expect(init.find("const kern_return_t pr = smu_set_power_state(*ctx.dev, SMUPowerState::Low);") != std::string::npos, "the failure clamp stays Low");
    expect(uc.find("if (state > 4) return kIOReturnBadArgument;") != std::string::npos, "the user client cannot ask for BootCap");
    expect(smu.find("case SMUPowerState::BootCap:") != std::string::npos && smu.find("max_mhz = lo;") != std::string::npos, "Low still caps at the PMFW minimum");
    expect(bring.find("n4xs::set_restore_state(ctx.idleClamp ? amdgpu::smu_gfx_boot_state() : amdgpu::SMUPowerState::Auto);") != std::string::npos, "the RESTORE follows the cap");
    // UCLK: the release boot-arg is read where the fallback is initialised.
    expect(dcn.find("\"navi48-uclkpin-release\"") != std::string::npos && dcn.find("n48uclk::fb::init(gFb, up.mode, up.verdict == n48uclk::kPinned, quietRelease);") != std::string::npos,
           "the fallback init takes the release boot-arg");
}

int main(int argc, char **argv) {
    test_layout();
    test_pptable();
    test_od();
    test_gfxmax();
    test_uclk_release();
    test_sources(argc > 1 ? argv[1] : nullptr);
    printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
