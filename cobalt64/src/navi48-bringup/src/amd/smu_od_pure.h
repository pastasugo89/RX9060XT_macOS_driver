//
//  smu_od_pure.h - 0.0.676: the PMFW zero-RPM fan mode through the OverDrive table (pure decisions, host-tested by tests/fan_od676_test.cpp).
//
//  Linux (MIT, drivers/gpu/drm/amd/pm/swsmu/smu14/smu_v14_0_2_ppt.c, torvalds/linux master as of 2026-11-14):
//    smu_v14_0_2_od_edit_dpm_table  case PP_OD_EDIT_FAN_ZERO_RPM_ENABLE: refuse unless smu_v14_0_2_is_od_feature_supported(ZERO_FAN_BIT), i.e.
//        PPTable SkuTable.OverDriveLimitsBasicMax.FeatureCtrlMask has bit 11; range-check the value against
//        [OverDriveLimitsBasicMin.FanZeroRpmEnable, OverDriveLimitsBasicMax.FanZeroRpmEnable] (smu_v14_0_2_get_od_setting_limits);
//        od_table->FanZeroRpmEnable = value; FeatureCtrlMask |= BIT(PP_OD_FEATURE_ZERO_FAN_BIT).
//    case PP_OD_COMMIT_DPM_TABLE: the upload image is the edited table with FeatureCtrlMask = the normalized pending mask, which for a zero-RPM
//        edit alone is exactly BIT(PP_OD_FEATURE_ZERO_FAN_BIT) (smu_v14_0_2_normalize_feature_mask clears every other bit whose fields equal the
//        boot table); smu_v14_0_2_upload_overdrive_table = TransferTableDram2Smu(TABLE_OVERDRIVE) with the PMFW's read_arg: (arg & 0xff) ==
//        TABLE_TRANSFER_FAILED means "invalid content", the OD_FAIL_e code in arg >> 16.
//    The boot table comes from TransferTableSmu2Dram(TABLE_OVERDRIVE) (smu_v14_0_2_get_overdrive_table); the PPTable from TransferTableSmu2Dram(
//        TABLE_COMBO_PPTABLE) (smu_cmn_get_combo_pptable), whose PPTable_t starts at smu_14_0_2_powerplay_table.smc_pptable.
//
//  The layouts are the IF 0x2E ones (smu14_driver_if_v14_0.h, PPTABLE_VERSION 0x1B). The PMFW here speaks driver IF 0x33, so nothing below is
//  trusted without evidence from the tables themselves:
//    (1) the combo PPTable describes itself: its header gives the PPTable_t and SkuTable_t start offsets and sizes; they must be the 0x2E ones,
//        and SkuTable_t.Version must be PPTABLE_VERSION 0x1B ("increment this version if SkuTable_t or BoardTable_t change");
//    (2) the OD limits read from that SkuTable must advertise ZERO_FAN and allow FanZeroRpmEnable = 0;
//    (3) the OD table read twice must be identical, and its fields around the fan block must be plausible against those limits (UclkFmin/Fmax,
//        FanTargetTemperature, FanZeroRpmEnable, FanZeroRpmStopTemp, FanMode, MaxOpTemp);
//    (4) the upload carries FeatureCtrlMask = BIT(11) only, so the PMFW applies the zero-fan fields only (and validates them itself);
//    (5) the read-back must equal the upload byte for byte outside FeatureCtrlMask.
//  Any failure: nothing is written (before the upload) or nothing more is written (after it).
//
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace n48od {

// ---- table ids and sizes (smu14_driver_if_v14_0.h:1862-1870, smu_v14_0_2_ppt.c MP0_MP1_DATA_REGION_SIZE_COMBOPPTABLE) ----
constexpr uint32_t kTablePPTable = 0, kTableComboPPTable = 1, kTableOverdrive = 8;
constexpr uint32_t kComboRegionBytes = 0x4000;
constexpr uint32_t kTableTransferFailed = 0xFF;   // TABLE_TRANSFER_FAILED, in (read_arg & 0xff)

// ---- OverDriveTable_t (IF 0x2E): 156 bytes ----
constexpr uint32_t kOdBytes = 0x9C;
constexpr uint32_t kOdFeatureCtrlMask = 0x00;          // u32
constexpr uint32_t kOdGfxclkFoffset = 0x18;            // s16
constexpr uint32_t kOdUclkFmin = 0x1C, kOdUclkFmax = 0x1E;   // u16
constexpr uint32_t kOdFanLinearPwmPoints = 0x28, kOdFanLinearTempPoints = 0x2E;   // u8[6]
constexpr uint32_t kOdFanMinimumPwm = 0x34, kOdAcousticTarget = 0x36, kOdAcousticLimit = 0x38, kOdFanTargetTemperature = 0x3A;   // u16
constexpr uint32_t kOdFanZeroRpmEnable = 0x3C, kOdFanZeroRpmStopTemp = 0x3D, kOdFanMode = 0x3E, kOdMaxOpTemp = 0x3F;   // u8
constexpr uint32_t kOdFanPoints = 6;   // NUM_OD_FAN_MAX_POINTS

// ---- OverDriveLimits_t (IF 0x2E): 96 bytes ----
constexpr uint32_t kLimBytes = 0x60;
constexpr uint32_t kLimFeatureCtrlMask = 0x00, kLimGfxclkFoffset = 0x14, kLimUclkFmin = 0x18, kLimUclkFmax = 0x1A;
constexpr uint32_t kLimFanTargetTemperature = 0x36, kLimFanZeroRpmEnable = 0x38, kLimMaxOpTemp = 0x39;

// ---- PPTable_t / SkuTable_t / smu_14_0_2_powerplay_table (IF 0x2E, PPTABLE_VERSION 0x1B) ----
constexpr uint32_t kPPTableVersion = 0x1B;
constexpr uint32_t kPPTableBytes = 0x1174, kSkuBytes = 0xDE0, kSkuInPPTable = 0x1C;
constexpr uint32_t kComboSmcPPTable = 0x540;           // offsetof(smu_14_0_2_powerplay_table, smc_pptable)
constexpr uint32_t kSkuVersion = 0x000;                // u32
constexpr uint32_t kSkuFanStopTempMin = 0xA68, kSkuFanStopTempMax = 0xA6A;   // MsgLimits_t.FanStopTempMin/Max, u16
constexpr uint32_t kSkuOdBasicMin = 0xAA0, kSkuOdBasicMax = 0xB00;            // OverDriveLimits_t
// combo header (smu_v14_0_2_pptable.h): u16 at 6 / 8 / 10 / 12
constexpr uint32_t kHdrPPTableStart = 0x06, kHdrPPTableSize = 0x08, kHdrSkuStart = 0x0A, kHdrSkuSize = 0x0C;
constexpr uint32_t kHdrBytes = 0x20;

constexpr uint32_t kOdFeatureZeroFanBit = 11;          // PP_OD_FEATURE_ZERO_FAN_BIT
constexpr uint32_t kOdFeatureZeroFan = 1u << kOdFeatureZeroFanBit;

inline uint32_t rd8(const uint8_t *b, uint32_t o) { return b[o]; }
inline uint32_t rd16(const uint8_t *b, uint32_t o) { return (uint32_t)b[o] | ((uint32_t)b[o + 1] << 8); }
inline int32_t rds16(const uint8_t *b, uint32_t o) { return (int32_t)(int16_t)(uint16_t)rd16(b, o); }
inline uint32_t rd32(const uint8_t *b, uint32_t o) { return rd16(b, o) | (rd16(b, o + 2) << 16); }
inline void wr32(uint8_t *b, uint32_t o, uint32_t v) { b[o] = (uint8_t)v; b[o + 1] = (uint8_t)(v >> 8); b[o + 2] = (uint8_t)(v >> 16); b[o + 3] = (uint8_t)(v >> 24); }

// ---- the boot-arg (navi48-fan-zerorpm): absent = leave the PMFW default (nothing read, nothing written); 0 = disable zero RPM; 1 = enable ----
enum Want : uint32_t { kWantDefault = 0, kWantOff = 1, kWantOn = 2, kWantInvalid = 3 };
inline uint32_t want_of(bool present, uint32_t v) { return !present ? kWantDefault : v == 0u ? kWantOff : v == 1u ? kWantOn : kWantInvalid; }
inline const char *want_name(uint32_t w) {
    return w == kWantDefault ? "PMFW default (boot-arg absent)" : w == kWantOff ? "zero RPM disable requested (navi48-fan-zerorpm=0)" :
           w == kWantOn ? "zero RPM enable requested (navi48-fan-zerorpm=1)" : "invalid navi48-fan-zerorpm value (ignored)";
}

// ---- verdicts ----
enum Verdict : uint32_t {
    kNotRun = 0, kDefault = 1, kApplied = 2, kAlready = 3,
    kPPTableReadFailed = 10, kPPTableLayout = 11, kNotSupported = 12, kOutOfRange = 13,
    kOdReadFailed = 20, kOdUnstable = 21, kOdImplausible = 22,
    kStageFailed = 30, kUploadFailed = 31, kUploadRejected = 32, kReadbackFailed = 33, kVerifyMismatch = 34,
    kNoSmu = 40, kNotFullPath = 41, kBadArg = 42, kNoLock = 43,
};
inline const char *verdict_name(uint32_t v) {
    switch (v) {
    case kNotRun: return "not run";
    case kDefault: return "unchanged (PMFW default; nothing read or written)";
    case kApplied: return "setting uploaded and read back (fan operation not verified)";
    case kAlready: return "already in the wanted state (nothing written)";
    case kPPTableReadFailed: return "PPTable read failed (nothing written)";
    case kPPTableLayout: return "PPTable layout is not the IF 0x2E / PPTABLE_VERSION 0x1B one (nothing written)";
    case kNotSupported: return "the OD limits do not advertise ZERO_FAN (nothing written)";
    case kOutOfRange: return "the wanted value is outside the OD limits (nothing written)";
    case kOdReadFailed: return "OD table read failed (nothing written)";
    case kOdUnstable: return "OD table differs between two reads (nothing written)";
    case kOdImplausible: return "OD table values implausible against the limits (nothing written)";
    case kStageFailed: return "the staged upload did not read back (nothing sent)";
    case kUploadFailed: return "TransferTableDram2Smu failed (no further write)";
    case kUploadRejected: return "the PMFW rejected the OD table (no further write)";
    case kReadbackFailed: return "the read-back after the upload failed (no further write)";
    case kVerifyMismatch: return "the read-back differs from the upload (no further write)";
    case kNoSmu: return "SMU not online (nothing done)";
    case kNotFullPath: return "the bring-up ladder did not complete (nothing done)";
    case kBadArg: return "invalid boot-arg value (nothing done)";
    case kNoLock: return "SMU mailbox lock unavailable (nothing done)";
    default: return "?";
    }
}

// What the PPTable says about OD (filled by check_pptable).
struct Limits {
    uint32_t pptStart, pptSize, skuStart, skuSize, skuVersion;
    uint32_t maskMin, maskMax;
    uint32_t zeroMin, zeroMax;            // OverDriveLimitsBasicMin/Max.FanZeroRpmEnable
    uint32_t stopMin, stopMax;            // MsgLimits FanStopTempMin/Max
    int32_t  gfxOffMin, gfxOffMax;
    uint32_t uclkMin, uclkMax;            // BasicMin.UclkFmin, BasicMax.UclkFmax
    uint32_t targetMin, targetMax;        // FanTargetTemperature
    uint32_t opMin, opMax;                // MaxOpTemp
};

// (1) + (2): the combo PPTable (first kComboRegionBytes bytes). Returns kNotRun on success (limits filled), else the verdict.
inline uint32_t check_pptable(const uint8_t *combo, uint32_t len, Limits &l) {
    l = Limits{};
    if (combo == nullptr || len < kComboSmcPPTable + kPPTableBytes) return kPPTableReadFailed;
    l.pptStart = rd16(combo, kHdrPPTableStart); l.pptSize = rd16(combo, kHdrPPTableSize);
    l.skuStart = rd16(combo, kHdrSkuStart); l.skuSize = rd16(combo, kHdrSkuSize);
    if (l.pptStart != kComboSmcPPTable || l.pptSize != kPPTableBytes || l.skuStart != kComboSmcPPTable + kSkuInPPTable || l.skuSize != kSkuBytes)
        return kPPTableLayout;
    const uint8_t *sku = combo + l.skuStart;
    l.skuVersion = rd32(sku, kSkuVersion);
    if (l.skuVersion != kPPTableVersion) return kPPTableLayout;
    const uint8_t *mn = sku + kSkuOdBasicMin, *mx = sku + kSkuOdBasicMax;
    l.maskMin = rd32(mn, kLimFeatureCtrlMask); l.maskMax = rd32(mx, kLimFeatureCtrlMask);
    l.zeroMin = rd8(mn, kLimFanZeroRpmEnable); l.zeroMax = rd8(mx, kLimFanZeroRpmEnable);
    l.stopMin = rd16(sku, kSkuFanStopTempMin); l.stopMax = rd16(sku, kSkuFanStopTempMax);
    l.gfxOffMin = rds16(mn, kLimGfxclkFoffset); l.gfxOffMax = rds16(mx, kLimGfxclkFoffset);
    l.uclkMin = rd16(mn, kLimUclkFmin); l.uclkMax = rd16(mx, kLimUclkFmax);
    l.targetMin = rd16(mn, kLimFanTargetTemperature); l.targetMax = rd16(mx, kLimFanTargetTemperature);
    l.opMin = rd8(mn, kLimMaxOpTemp); l.opMax = rd8(mx, kLimMaxOpTemp);
    // Plausibility of the limits themselves (a shifted SkuTable would give garbage here even with the right Version word).
    if (l.zeroMin > 1u || l.zeroMax > 1u || l.zeroMin > l.zeroMax) return kPPTableLayout;
    if (l.stopMin > l.stopMax || l.stopMax > 120u) return kPPTableLayout;
    if (l.gfxOffMin > l.gfxOffMax || l.uclkMin > l.uclkMax || l.uclkMax > 10000u) return kPPTableLayout;
    if (l.targetMin > l.targetMax || l.targetMax > 150u || l.opMin > l.opMax || l.opMax > 150u) return kPPTableLayout;
    // Linux smu_v14_0_2_is_od_feature_supported(ZERO_FAN_BIT): BasicMax.FeatureCtrlMask bit 11. smu_v14_0_2_check_powerplay_table: OD is off
    // altogether when either mask is 0.
    if (l.maskMin == 0u || l.maskMax == 0u || (l.maskMax & kOdFeatureZeroFan) == 0u) return kNotSupported;
    return kNotRun;
}

// Linux's range check (smu_v14_0_2_get_od_setting_limits PP_OD_FEATURE_FAN_ZERO_RPM_ENABLE).
inline bool value_in_range(uint32_t value, const Limits &l) { return value >= l.zeroMin && value <= l.zeroMax; }

// (3): the OD table as read (kOdBytes). True when the fan block and its neighbours are plausible against the limits.
inline bool od_plausible(const uint8_t *od, const Limits &l) {
    const uint32_t zero = rd8(od, kOdFanZeroRpmEnable), stop = rd8(od, kOdFanZeroRpmStopTemp), mode = rd8(od, kOdFanMode), op = rd8(od, kOdMaxOpTemp);
    const uint32_t target = rd16(od, kOdFanTargetTemperature), umin = rd16(od, kOdUclkFmin), umax = rd16(od, kOdUclkFmax);
    const int32_t goff = rds16(od, kOdGfxclkFoffset);
    if (zero > 1u || mode > 1u) return false;                                    // booleans / FanMode_e
    if (stop < l.stopMin || stop > l.stopMax || stop == 0u) return false;         // the zero-RPM stop temperature sits inside MsgLimits
    if (l.targetMax != 0u && (target < l.targetMin || target > l.targetMax)) return false;
    if (l.opMax != 0u && (op < l.opMin || op > l.opMax)) return false;
    if (umin > umax || umin < l.uclkMin || umax > l.uclkMax) return false;        // Linux on this card: OD_MCLK 97 / 1259 inside 97..1500
    if (goff < l.gfxOffMin || goff > l.gfxOffMax) return false;
    return true;
}

// (4): the upload image: the table as read, FanZeroRpmEnable = value, FeatureCtrlMask = BIT(ZERO_FAN) only (Linux's normalized commit mask).
inline void build_upload(const uint8_t *od, uint32_t value, uint8_t *out) {
    for (uint32_t i = 0; i < kOdBytes; i++) out[i] = od[i];
    out[kOdFanZeroRpmEnable] = (uint8_t)value;
    wr32(out, kOdFeatureCtrlMask, kOdFeatureZeroFan);
}

// (5): the read-back equals the upload outside FeatureCtrlMask (the PMFW does not report the commit mask back), and holds the value.
inline bool verify_readback(const uint8_t *upload, const uint8_t *back, uint32_t value) {
    for (uint32_t i = 4; i < kOdBytes; i++) if (upload[i] != back[i]) return false;
    return back[kOdFanZeroRpmEnable] == value;
}

// The PMFW's answer to the upload (Linux smu_v14_0_2_upload_overdrive_table): rejected when (arg & 0xff) == TABLE_TRANSFER_FAILED.
inline bool upload_rejected(uint32_t arg) { return (arg & 0xFFu) == kTableTransferFailed; }
inline uint32_t od_error_code(uint32_t arg) { return arg >> 16; }

// The result published as Navi48,Fan.
struct Result {
    uint32_t want, verdict, kr, arg;
    uint32_t before, after;              // FanZeroRpmEnable as read / as read back (0xFF = unknown)
    uint32_t stopTemp, fanMode, targetTemp;
    Limits lim;
    uint32_t rpm, pwm, metricsOk;        // Raw decoded fan fields after one successful transfer; not physical validation.
    uint32_t metricsIf, metricsLayoutVerified, metricsPlausible;
};
inline void init(Result &r, uint32_t want) { r = Result{}; r.want = want; r.before = 0xFFu; r.after = 0xFFu; }

} // namespace n48od
