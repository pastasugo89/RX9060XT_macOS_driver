//
//  n4x_safety_pure.h - the PURE half of the thermal safety watchdog (kext, default ON for the Navi 44 profile).
//
//  No kernel header is included: tools/hosttests/test_n4x_safety_pure.cpp compiles this on Linux and drives the same
//  functions the kext calls (n4x_safety.cpp). Design, thresholds and their justification: research/reports/gpu_safety.md.
//
//  Everything here is arithmetic and decisions. Nothing touches a register, a clock, a voltage or a table.
//
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace n4xs {

// ---- the sensor: THM_TCON_CUR_TMP -------------------------------------------------------------------------------------
// Linux amdgpu, asic_reg/thm/thm_14_0_2_offset.h: regTHM_TCON_CUR_TMP = 0x0000 in the THM block, BASE_IDX 0. On this card the
// discovery table reports THM (hwId 3, v14.0.2) segment 0 = dword 0x16600 (byte 0x59800, the same base as the header's
// "base address: 0x59800"). The CUR_TEMP field is bits [31:21] (thm_14_0_2_sh_mask.h: CUR_TEMP_MASK 0xFFE00000), the range
// select is bit 19. Decoding follows Linux smu10_hwmgr.c / smu8_hwmgr.c (degrees = field / 8, minus 49 when the range bit is
// set). THE DECODE IS NOT VALIDATED ON HARDWARE: the boot must show it agrees with the hwmgr junction value (idle ~30 C).
constexpr uint32_t kThmHwId          = 3;       // THM_HWID (soc15_hw_ip.h)
constexpr uint32_t kThmSeg           = 0;       // BASE_IDX 0
constexpr uint32_t kThmCurTmpDword   = 0x0000;  // regTHM_TCON_CUR_TMP
constexpr uint32_t kCurTempShift     = 21;
constexpr uint32_t kCurTempField     = 0x7FFu;  // 11 bits
constexpr uint32_t kRangeSelShift    = 19;

// ---- thresholds and timing ----------------------------------------------------------------------------------------------
// Defaults (hotspot = junction, the only independent sensor on this path). Edge and memory temperatures are NOT used for a
// decision: they come from the SMU metrics table, whose layout is unverified for IF 0x33 (research/reports/smu_metrics_if33_audit.md).
constexpr int32_t kDefaultWarnC      = 75;
constexpr int32_t kDefaultTripC      = 80;
constexpr int32_t kConfigMinC        = 50;      // boot-arg range; anything outside falls back to the default
constexpr int32_t kConfigMaxC        = 100;
constexpr int32_t kPlausibleMinC     = 0;       // a decoded value outside this range is a sensor fault, not a temperature
constexpr int32_t kPlausibleMaxC     = 125;
constexpr uint32_t kSamplePeriodMs   = 250;
constexpr uint32_t kHeartbeatMs      = 1000;
constexpr uint32_t kInvalidTripSamples = 12;    // 12 x 250 ms = 3 s without a readable sensor while armed -> TRIP

struct Thresholds {
    int32_t warnC;
    int32_t tripC;
};

inline bool thresholds_valid(const Thresholds &t) {
    return t.warnC >= kConfigMinC && t.tripC <= kConfigMaxC && t.warnC < t.tripC;
}

// ---- decode -------------------------------------------------------------------------------------------------------------
struct ThmDecode {
    bool     valid;
    int32_t  tempC;
    uint32_t raw;        // the 11-bit CUR_TEMP field
    uint32_t rangeSel;   // 0 or 1
};

inline ThmDecode decode_thm_cur_temp(uint32_t reg) {
    ThmDecode d{false, 0, 0, 0};
    if (reg == 0xFFFFFFFFu) return d;                  // what the kext's RREG32 answers for a dword outside BAR5
    d.raw = (reg >> kCurTempShift) & kCurTempField;
    d.rangeSel = (reg >> kRangeSelShift) & 1u;
    int32_t t = (int32_t)(d.raw / 8u);
    if (d.rangeSel) t -= 49;
    d.tempC = t;
    d.valid = (t >= kPlausibleMinC && t <= kPlausibleMaxC);
    return d;
}

// ---- decision -----------------------------------------------------------------------------------------------------------
enum Level : uint32_t { kLevelOk = 0, kLevelWarn = 1, kLevelTrip = 2 };
enum Reason : uint32_t {
    kReasonNone = 0, kReasonWarnTemp = 1, kReasonTripTemp = 2, kReasonSensorInvalid = 3, kReasonNoSensor = 4,
};

inline const char *level_name(uint32_t level) {
    return level == kLevelTrip ? "TRIP" : level == kLevelWarn ? "WARN" : "OK";
}
inline const char *reason_name(uint32_t reason) {
    switch (reason) {
    case kReasonWarnTemp:      return "warn-temp";
    case kReasonTripTemp:      return "trip-temp";
    case kReasonSensorInvalid: return "sensor-invalid";
    case kReasonNoSensor:      return "no-sensor";
    default:                   return "none";
    }
}

// The monitor. TRIP latches: once set it stays set until the kext is reloaded, so a single spike cannot be "forgotten".
// WARN and OK follow the sample. An unreadable sample is WARN at first and TRIP after kInvalidTripSamples in a row.
struct Monitor {
    uint32_t invalidRun;
    uint32_t level;
    uint32_t reason;
};

inline void monitor_init(Monitor &m) {
    m.invalidRun = 0;
    m.level = kLevelOk;
    m.reason = kReasonNone;
}

inline uint32_t monitor_step(Monitor &m, const Thresholds &th, const ThmDecode &d) {
    if (m.level == kLevelTrip) return kLevelTrip;      // latched
    if (!d.valid) {
        m.invalidRun++;
        if (m.invalidRun >= kInvalidTripSamples) {
            m.level = kLevelTrip;
        } else {
            m.level = kLevelWarn;
        }
        m.reason = kReasonSensorInvalid;
        return m.level;
    }
    m.invalidRun = 0;
    if (d.tempC >= th.tripC) {
        m.level = kLevelTrip;
        m.reason = kReasonTripTemp;
    } else if (d.tempC >= th.warnC) {
        m.level = kLevelWarn;
        m.reason = kReasonWarnTemp;
    } else {
        m.level = kLevelOk;
        m.reason = kReasonNone;
    }
    return m.level;
}

// Called when the sensor cannot be resolved at all while the watchdog is enabled: fail closed.
inline uint32_t monitor_no_sensor(Monitor &m) {
    m.level = kLevelTrip;
    m.reason = kReasonNoSensor;
    return m.level;
}

// ---- protections (SMU feature mask) -------------------------------------------------------------------------------------
// Bits from Linux smu14_driver_if_v14_0.h: FEATURE_THROTTLERS_BIT 23 (PPT, TDC and the temperature throttlers ride on it:
// smu_v14_0_2_ppt.c maps SMU_FEATURE_PPT_BIT to FEATURE_THROTTLERS_BIT), FEATURE_VR0HOT_BIT 27 (informational here),
// FEATURE_FW_CTF_BIT 28 (firmware critical temperature shutdown), FEATURE_FAN_CONTROL_BIT 29. The real mask read on this card
// is 0x0498f59e38fffcfb (research/hw_dump/pm_info.txt), which has all four set.
constexpr uint32_t kFeatThrottlers   = 23;
constexpr uint32_t kFeatVr0Hot       = 27;
constexpr uint32_t kFeatFwCtf        = 28;
constexpr uint32_t kFeatFanControl   = 29;
constexpr uint64_t kRequiredFeatures = (1ull << kFeatThrottlers) | (1ull << kFeatFwCtf) | (1ull << kFeatFanControl);

struct ProtectionReport {
    bool     ok;
    uint64_t running;    // (hi << 32) | lo, as GetRunningSmuFeaturesHigh/Low return them
    uint64_t missing;    // required bits that are not running
    bool     vr0hot;     // informational
};

inline ProtectionReport check_protections(uint32_t lo, uint32_t hi) {
    ProtectionReport r{};
    r.running = ((uint64_t)hi << 32) | (uint64_t)lo;
    r.missing = kRequiredFeatures & ~r.running;
    r.ok = (r.missing == 0);
    r.vr0hot = ((r.running >> kFeatVr0Hot) & 1u) != 0;
    return r;
}

// ---- heartbeat line -----------------------------------------------------------------------------------------------------
// "N4X-SAFETY t=<ms> hotspot=<C|na> edge=na mem=na ppt=na state=OK|WARN|TRIP|STOP reason=<r> proto=<0|1> thm=<hex>"
// edge, mem and ppt stay na: they are not validated on this firmware. The host parser (gpu-safety-watchdog.py) reads these keys.
struct HeartbeatFields {
    uint64_t t_ms;
    bool     hotValid;
    int32_t  hotC;
    uint32_t level;      // kLevelOk / kLevelWarn / kLevelTrip
    uint32_t reason;
    bool     stopping;   // the kext is stopping: state=STOP, the host treats it as a clean end
    bool     proto;
    uint32_t thmRaw;
};

namespace detail {
inline size_t put_str(char *buf, size_t cap, size_t at, const char *s) {
    while (*s && at + 1 < cap) buf[at++] = *s++;
    buf[at] = '\0';
    return at;
}
inline size_t put_u64(char *buf, size_t cap, size_t at, uint64_t v) {
    char tmp[24];
    size_t n = 0;
    do { tmp[n++] = (char)('0' + (v % 10u)); v /= 10u; } while (v != 0 && n < sizeof tmp);
    while (n > 0 && at + 1 < cap) buf[at++] = tmp[--n];
    buf[at] = '\0';
    return at;
}
inline size_t put_i32(char *buf, size_t cap, size_t at, int32_t v) {
    if (v < 0) { if (at + 1 < cap) buf[at++] = '-'; return put_u64(buf, cap, at, (uint64_t)(-(int64_t)v)); }
    return put_u64(buf, cap, at, (uint64_t)v);
}
inline size_t put_hex32(char *buf, size_t cap, size_t at, uint32_t v) {
    static const char digits[] = "0123456789abcdef";
    at = put_str(buf, cap, at, "0x");
    for (int sh = 28; sh >= 0; sh -= 4) if (at + 1 < cap) buf[at++] = digits[(v >> sh) & 0xFu];
    buf[at] = '\0';
    return at;
}
}  // namespace detail

inline size_t format_heartbeat(char *buf, size_t cap, const HeartbeatFields &f) {
    size_t at = 0;
    buf[0] = '\0';
    at = detail::put_str(buf, cap, at, "N4X-SAFETY t=");
    at = detail::put_u64(buf, cap, at, f.t_ms);
    at = detail::put_str(buf, cap, at, " hotspot=");
    if (f.hotValid) at = detail::put_i32(buf, cap, at, f.hotC); else at = detail::put_str(buf, cap, at, "na");
    at = detail::put_str(buf, cap, at, " edge=na mem=na ppt=na state=");
    at = detail::put_str(buf, cap, at, f.stopping ? "STOP" : level_name(f.level));
    at = detail::put_str(buf, cap, at, " reason=");
    at = detail::put_str(buf, cap, at, reason_name(f.reason));
    at = detail::put_str(buf, cap, at, " proto=");
    at = detail::put_str(buf, cap, at, f.proto ? "1" : "0");
    at = detail::put_str(buf, cap, at, " thm=");
    at = detail::put_hex32(buf, cap, at, f.thmRaw);
    return at;
}

}  // namespace n4xs
