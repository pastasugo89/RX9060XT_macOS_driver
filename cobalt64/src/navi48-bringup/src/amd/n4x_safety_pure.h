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
// 0.0.675 (research/reports/macos-20261112/gfx-power-gating-study.md section 1): 80 C hotspot is a normal value under any real 3D load, and the
// old TRIP (80 C, latched, refusing every submission) froze the desktop on 2026-11-12 at 85-87 C. New ladder: WARN 90 C (log only), TRIP 100 C
// (below the PMFW's own throttlers and FW_CTF, which stay the real protection): the kext clamps GFXCLK to the PMFW minimum through the SMU and
// keeps it until the hotspot stays below the release temperature (85 C) for kReleaseHoldMs; then the boot clock policy comes back. A TRIP
// never latches and never refuses a submission (see refuses_submissions below).
constexpr int32_t kDefaultWarnC      = 90;
constexpr int32_t kDefaultTripC      = 100;
constexpr int32_t kDefaultReleaseC   = 85;
constexpr uint64_t kReleaseHoldMs    = 10000;   // the hotspot must stay below the release temperature this long (10 s)
constexpr uint64_t kClampRetryMs     = 1000;    // a failed SMU clamp / restore is retried at most once a second
constexpr int32_t kConfigMinC        = 50;      // boot-arg range; anything outside falls back to the default
constexpr int32_t kConfigMaxC        = 105;
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

// The temperature the hotspot must stay below (for kReleaseHoldMs) before a thermal clamp is released: 85 C, or 5 C under a lower TRIP set
// by boot-arg (navi48-safety-trip=80 releases below 75 C), so the release is always under the TRIP.
inline int32_t release_c(const Thresholds &t) {
    return t.tripC - 5 < kDefaultReleaseC ? t.tripC - 5 : kDefaultReleaseC;
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

// A precondition for entering PSP, not a guarantee during the chain.
inline uint64_t psp_gate_sample(uint64_t sampleMs, bool valid, uint32_t level) {
    return (sampleMs << 1) | ((valid && level == kLevelOk) ? 1u : 0u);
}
inline bool psp_entry_permitted(bool running, uint64_t sample, uint64_t nowMs) {
    const uint64_t sampleMs = sample >> 1;
    return running && (sample & 1u) != 0 && nowMs >= sampleMs && nowMs - sampleMs <= 1000;
}
enum Reason : uint32_t {
    kReasonNone = 0, kReasonWarnTemp = 1, kReasonTripTemp = 2, kReasonSensorInvalid = 3, kReasonNoSensor = 4,
    kReasonWatchdogFailure = 5,
    kReasonCooling = 6,   // 0.0.675: below TRIP, the clamp held until the hotspot stays below release_c for kReleaseHoldMs
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
    case kReasonWatchdogFailure: return "watchdog-failure";
    case kReasonCooling:       return "cooling";
    default:                   return "none";
    }
}

// The monitor (0.0.675). Nothing latches. A temperature at or above TRIP sets level TRIP and asks for the thermal clamp (clamp = true: the kext
// sends smu_set_power_state(Low), GFXCLK soft max = PMFW minimum). While the clamp is held the level stays TRIP (reason trip-temp at or above
// TRIP, cooling below it); the clamp is released only after kReleaseHoldMs of consecutive valid samples below release_c, and then WARN / OK
// follow the sample again. An unreadable sample is WARN at first; kInvalidTripSamples in a row while armed is TRIP (sensor-invalid) with the
// clamp asked for too, released by the same rule once the sensor reads again. Up to 0.0.674 a TRIP latched and refused submissions; that
// froze the desktop (2026-11-12), so no level refuses a submission now (refuses_submissions).
struct Monitor {
    uint32_t invalidRun;
    uint32_t level;
    uint32_t reason;
    bool     clamp;          // the thermal clamp is wanted (the kext applies / releases it on a change)
    bool     cooling;        // a below-release run is being timed
    uint64_t coolSinceMs;    // when that run started
    bool     permanent;      // no sensor at all: the clamp is never released
};

inline void monitor_init(Monitor &m) {
    m.invalidRun = 0;
    m.level = kLevelOk;
    m.reason = kReasonNone;
    m.clamp = false;
    m.cooling = false;
    m.coolSinceMs = 0;
    m.permanent = false;
}

inline uint32_t monitor_step(Monitor &m, const Thresholds &th, const ThmDecode &d, uint64_t nowMs) {
    if (m.permanent) return m.level;                   // no sensor: TRIP + clamp for the whole boot
    if (!d.valid) {
        m.invalidRun++;
        m.cooling = false;                             // an unreadable sample never counts towards a release
        if (m.invalidRun >= kInvalidTripSamples) {
            m.level = kLevelTrip;
            m.clamp = true;
        } else if (!m.clamp) {
            m.level = kLevelWarn;
        }
        m.reason = kReasonSensorInvalid;
        return m.level;
    }
    m.invalidRun = 0;
    if (d.tempC >= th.tripC) {
        m.level = kLevelTrip;
        m.reason = kReasonTripTemp;
        m.clamp = true;
        m.cooling = false;
        return m.level;
    }
    if (m.clamp) {                                     // hysteresis: hold until below release_c for kReleaseHoldMs
        if (d.tempC < release_c(th)) {
            if (!m.cooling) { m.cooling = true; m.coolSinceMs = nowMs; }
            if (nowMs >= m.coolSinceMs && nowMs - m.coolSinceMs >= kReleaseHoldMs) {
                m.clamp = false;
                m.cooling = false;
            }
        } else {
            m.cooling = false;
        }
        if (m.clamp) {
            m.level = kLevelTrip;
            m.reason = kReasonCooling;
            return m.level;
        }
    }
    if (d.tempC >= th.warnC) {
        m.level = kLevelWarn;
        m.reason = kReasonWarnTemp;
    } else {
        m.level = kLevelOk;
        m.reason = kReasonNone;
    }
    return m.level;
}

// Called when the sensor cannot be resolved at all while the watchdog is enabled: fail closed = TRIP and the thermal clamp for the whole boot
// (0.0.675: clocks low, submissions still accepted).
inline uint32_t monitor_no_sensor(Monitor &m) {
    m.level = kLevelTrip;
    m.reason = kReasonNoSensor;
    m.clamp = true;
    m.permanent = true;
    return m.level;
}

// ---- the clamp action (0.0.675) -----------------------------------------------------------------------------------------------------------
// The kext keeps `applied` (what the SMU last accepted) and `lastTryMs`. clamp_action says what to send now: kActClamp (smu_set_power_state
// Low), kActRestore (the boot clock policy: Low when navi48-idle-clamp is on, the default; Auto when it is off) or nothing. A failed send is
// retried at most every kClampRetryMs.
enum Action : uint32_t { kActNone = 0, kActClamp = 1, kActRestore = 2 };
inline uint32_t clamp_action(bool wanted, bool applied, bool tried, uint64_t lastTryMs, uint64_t nowMs) {
    if (wanted == applied) return kActNone;
    if (tried && nowMs >= lastTryMs && nowMs - lastTryMs < kClampRetryMs) return kActNone;
    return wanted ? kActClamp : kActRestore;
}

// ---- what a level refuses (0.0.675) ---------------------------------------------------------------------------------------------------------
// Submissions (N48N submit, the legacy SubmitIB) are NEVER refused for a temperature or a sensor fault: only while the watchdog is being torn
// down (stopping). The writers that can raise a clock or change the display (DAL step / hold, mode trial, power states other than Low, the
// accel experiment, refresh-60, the bring-up ladder beyond SMUInit) are refused while TRIP (a temperature TRIP, the cooling hold, an
// unreadable or unresolved sensor, a watchdog failure) and while stopping.
inline bool refuses_submissions(bool stopping, uint32_t /*level*/) { return stopping; }
inline bool refuses_writers(bool stopping, uint32_t level) { return stopping || level == kLevelTrip; }

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
