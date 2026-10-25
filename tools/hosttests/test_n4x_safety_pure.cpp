// Host test: the pure thermal-safety logic of the kext (cobalt64/src/navi48-bringup/src/amd/n4x_safety_pure.h).
// Build: tools/hosttests/run.sh   Usage: test_n4x_safety_pure
#include "amd/n4x_safety_pure.h"
#include <cstdio>
#include <cstring>

using namespace n4xs;

static int fails = 0, checks = 0;
#define CHECK(cond, msg) do { checks++; if (!(cond)) { fails++; std::printf("FAIL: %s (line %d)\n", msg, __LINE__); } } while (0)

static uint32_t thm_reg(uint32_t field, uint32_t rangeSel) {
    return (field << kCurTempShift) | (rangeSel << kRangeSelShift);
}

static void test_decode() {
    // 240 counts = 30 C (the idle junction the Linux oracle reports: junction30C).
    ThmDecode d = decode_thm_cur_temp(thm_reg(240, 0));
    CHECK(d.valid && d.tempC == 30, "decode: field 240 -> 30 C");
    CHECK(d.raw == 240 && d.rangeSel == 0, "decode: raw field and range bit");
    d = decode_thm_cur_temp(thm_reg(0, 0));
    CHECK(d.valid && d.tempC == 0, "decode: zero is a plausible reading");
    d = decode_thm_cur_temp(thm_reg(kCurTempField, 0));            // 2047 / 8 = 255 C
    CHECK(!d.valid, "decode: 255 C is implausible");
    d = decode_thm_cur_temp(thm_reg((49 + 100) * 8, 1));            // range bit set: 149 - 49 = 100 C
    CHECK(d.valid && d.tempC == 100 && d.rangeSel == 1, "decode: range-select offset of 49");
    d = decode_thm_cur_temp(0xFFFFFFFFu);
    CHECK(!d.valid, "decode: all-ones (unmapped dword) is invalid");
    // Bits outside the field must not leak into the decode.
    d = decode_thm_cur_temp(thm_reg(240, 0) | 0x7FFFFu);
    CHECK(d.valid && d.tempC == 30, "decode: low bits ignored");
}

static void test_thresholds() {
    CHECK(thresholds_valid({kDefaultWarnC, kDefaultTripC}), "thresholds: defaults are valid");
    CHECK(!thresholds_valid({80, 75}), "thresholds: warn above trip is refused");
    CHECK(!thresholds_valid({75, 75}), "thresholds: warn equal to trip is refused");
    CHECK(!thresholds_valid({40, 80}), "thresholds: warn below the config floor is refused");
    CHECK(!thresholds_valid({75, 101}), "thresholds: trip above the config ceiling is refused");
}

static uint32_t step(Monitor &m, int32_t c) {
    return monitor_step(m, {kDefaultWarnC, kDefaultTripC}, decode_thm_cur_temp(thm_reg((uint32_t)(c * 8), 0)));
}

static void test_monitor() {
    Monitor m; monitor_init(m);
    CHECK(step(m, 30) == kLevelOk && m.reason == kReasonNone, "monitor: 30 C is OK");
    CHECK(step(m, 75) == kLevelWarn && m.reason == kReasonWarnTemp, "monitor: 75 C is WARN");
    CHECK(step(m, 74) == kLevelOk, "monitor: WARN follows the sample back to OK");
    CHECK(step(m, 80) == kLevelTrip && m.reason == kReasonTripTemp, "monitor: 80 C is TRIP");
    CHECK(step(m, 40) == kLevelTrip, "monitor: TRIP latches after the temperature falls");

    Monitor w; monitor_init(w);
    for (int i = 0; i < 11; i++) monitor_step(w, {kDefaultWarnC, kDefaultTripC}, ThmDecode{false, 0, 0, 0});
    CHECK(w.level == kLevelWarn && w.reason == kReasonSensorInvalid, "monitor: 11 unreadable samples are WARN");
    monitor_step(w, {kDefaultWarnC, kDefaultTripC}, ThmDecode{false, 0, 0, 0});
    CHECK(w.level == kLevelTrip, "monitor: 12 unreadable samples (3 s) are TRIP");

    Monitor r; monitor_init(r);
    for (int i = 0; i < 5; i++) monitor_step(r, {kDefaultWarnC, kDefaultTripC}, ThmDecode{false, 0, 0, 0});
    CHECK(step(r, 30) == kLevelOk && r.invalidRun == 0, "monitor: a readable sample clears the invalid run");

    Monitor n; monitor_init(n);
    monitor_no_sensor(n);
    CHECK(n.level == kLevelTrip && n.reason == kReasonNoSensor, "monitor: no sensor fails closed");
}

static void test_protections() {
    // The mask read on this card: 0x0498f59e38fffcfb (hi 0x0498f59e, lo 0x38fffcfb).
    ProtectionReport ok = check_protections(0x38fffcfbu, 0x0498f59eu);
    CHECK(ok.ok && ok.missing == 0, "protections: the real mask passes");
    CHECK(ok.running == 0x0498f59e38fffcfbull, "protections: running mask assembled hi:lo");
    CHECK(ok.vr0hot, "protections: VR0HOT reported (informational)");
    ProtectionReport noCtf = check_protections(0x38fffcfbu & ~(1u << kFeatFwCtf), 0x0498f59eu);
    CHECK(!noCtf.ok && noCtf.missing == (1ull << kFeatFwCtf), "protections: FW_CTF missing fails, names the bit");
    ProtectionReport noThr = check_protections(0x38fffcfbu & ~(1u << kFeatThrottlers), 0x0498f59eu);
    CHECK(!noThr.ok && noThr.missing == (1ull << kFeatThrottlers), "protections: THROTTLERS (PPT/TDC) missing fails");
    ProtectionReport noFan = check_protections(0x38fffcfbu & ~(1u << kFeatFanControl), 0x0498f59eu);
    CHECK(!noFan.ok && noFan.missing == (1ull << kFeatFanControl), "protections: FAN_CONTROL missing fails");
    ProtectionReport none = check_protections(0, 0);
    CHECK(!none.ok && none.missing == kRequiredFeatures, "protections: nothing running fails");
}

static void test_heartbeat() {
    char buf[200];
    HeartbeatFields f{};
    f.t_ms = 12345; f.hotValid = true; f.hotC = 30; f.level = kLevelOk; f.reason = kReasonNone; f.proto = true; f.thmRaw = 0x1E000000u;
    format_heartbeat(buf, sizeof buf, f);
    CHECK(std::strcmp(buf, "N4X-SAFETY t=12345 hotspot=30 edge=na mem=na ppt=na state=OK reason=none proto=1 thm=0x1e000000") == 0,
          "heartbeat: OK line exact");

    HeartbeatFields t{};
    t.t_ms = 5; t.hotValid = false; t.level = kLevelTrip; t.reason = kReasonSensorInvalid; t.thmRaw = 0xFFFFFFFFu;
    format_heartbeat(buf, sizeof buf, t);
    CHECK(std::strcmp(buf, "N4X-SAFETY t=5 hotspot=na edge=na mem=na ppt=na state=TRIP reason=sensor-invalid proto=0 thm=0xffffffff") == 0,
          "heartbeat: unreadable TRIP line exact");

    HeartbeatFields neg{};
    neg.t_ms = 0; neg.hotValid = true; neg.hotC = -5; neg.level = kLevelWarn; neg.reason = kReasonWarnTemp; neg.thmRaw = 0;
    format_heartbeat(buf, sizeof buf, neg);
    CHECK(std::strstr(buf, "hotspot=-5 ") != nullptr && std::strstr(buf, "state=WARN reason=warn-temp") != nullptr, "heartbeat: negative temperature and WARN");

    HeartbeatFields s{};
    s.t_ms = 99; s.stopping = true; s.level = kLevelTrip; s.reason = kReasonTripTemp; s.hotValid = true; s.hotC = 91;
    format_heartbeat(buf, sizeof buf, s);
    CHECK(std::strstr(buf, "state=STOP ") != nullptr, "heartbeat: stopping kext reports STOP, not TRIP");

    char small[12];
    size_t n = format_heartbeat(small, sizeof small, f);
    CHECK(n < sizeof small && std::strlen(small) < sizeof small, "heartbeat: a short buffer is truncated, never overrun");
}

int main() {
    test_decode();
    test_thresholds();
    test_monitor();
    test_protections();
    test_heartbeat();
    std::printf("n4x_safety_pure: %d checks, %d failed\n", checks, fails);
    std::puts(fails == 0 ? "PASS" : "FAIL");
    return fails == 0 ? 0 : 1;
}
