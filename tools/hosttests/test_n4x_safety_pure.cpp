// Host test: the pure thermal-safety logic of the kext (cobalt64/src/navi48-bringup/src/amd/n4x_safety_pure.h).
// 0.0.675: WARN 90 / TRIP 100, the TRIP clamp with its 85 C / 10 s hysteresis, the clamp action and what each level refuses (never a submission).
// Build: tools/hosttests/run.sh   Usage: test_n4x_safety_pure
#include "amd/n4x_safety_pure.h"
#include <cstdio>
#include <cstring>
#include <initializer_list>

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
    CHECK(kDefaultWarnC == 90 && kDefaultTripC == 100 && kDefaultReleaseC == 85, "thresholds: 0.0.675 defaults WARN 90, TRIP 100, release 85");
    CHECK(thresholds_valid({kDefaultWarnC, kDefaultTripC}), "thresholds: defaults are valid");
    CHECK(!thresholds_valid({80, 75}), "thresholds: warn above trip is refused");
    CHECK(!thresholds_valid({75, 75}), "thresholds: warn equal to trip is refused");
    CHECK(!thresholds_valid({40, 80}), "thresholds: warn below the config floor is refused");
    CHECK(thresholds_valid({95, 105}), "thresholds: trip 105 (the new ceiling) is accepted");
    CHECK(!thresholds_valid({75, 106}), "thresholds: trip above the config ceiling (105) is refused");
    CHECK(thresholds_valid({75, 80}), "thresholds: the old 75/80 pair is still accepted by boot-arg");
    CHECK(release_c({kDefaultWarnC, kDefaultTripC}) == 85, "release: 85 C with the defaults");
    CHECK(release_c({75, 80}) == 75, "release: 5 C under a lower TRIP (80 -> 75)");
    CHECK(release_c({95, 105}) == 85, "release: never above 85 C");
}

static const Thresholds kTh {kDefaultWarnC, kDefaultTripC};

static uint32_t step_at(Monitor &m, int32_t c, uint64_t t) {
    return monitor_step(m, kTh, decode_thm_cur_temp(thm_reg((uint32_t)(c * 8), 0)), t);
}

static void test_monitor() {
    uint64_t t = 1000;
    Monitor m; monitor_init(m);
    CHECK(step_at(m, 30, t) == kLevelOk && m.reason == kReasonNone && !m.clamp, "monitor: 30 C is OK, no clamp");
    CHECK(step_at(m, 87, t += 250) == kLevelOk && !m.clamp, "monitor: 87 C (the 2026-11-12 hotspot) is OK now, no clamp");
    CHECK(step_at(m, 90, t += 250) == kLevelWarn && m.reason == kReasonWarnTemp && !m.clamp, "monitor: 90 C is WARN, log only");
    CHECK(step_at(m, 89, t += 250) == kLevelOk, "monitor: WARN follows the sample back to OK");
    CHECK(step_at(m, 99, t += 250) == kLevelWarn && !m.clamp, "monitor: 99 C is WARN, no clamp");
    CHECK(step_at(m, 100, t += 250) == kLevelTrip && m.reason == kReasonTripTemp && m.clamp, "monitor: 100 C is TRIP and asks for the clamp");
    CHECK(step_at(m, 95, t += 250) == kLevelTrip && m.reason == kReasonCooling && m.clamp, "monitor: below TRIP but above release: cooling hold");
    CHECK(step_at(m, 85, t += 250) == kLevelTrip && m.clamp && !m.cooling, "monitor: 85 C is not below release (strict)");
    // below release: the 10 s run starts at the first sample below 85 C
    const uint64_t start = (t += 250);
    CHECK(step_at(m, 84, start) == kLevelTrip && m.clamp && m.cooling, "monitor: 84 C starts the release timer");
    for (uint64_t k = 250; k < kReleaseHoldMs; k += 250) step_at(m, 70, start + k);
    CHECK(m.clamp && m.level == kLevelTrip, "monitor: still clamped 9.75 s into the run");
    CHECK(step_at(m, 70, start + kReleaseHoldMs) == kLevelOk && !m.clamp, "monitor: released after 10 s below 85 C, level follows the sample");
    // a spike inside the run restarts it
    Monitor h; monitor_init(h);
    t = 0;
    step_at(h, 101, t);
    step_at(h, 80, t += 250);
    for (int i = 0; i < 20; i++) step_at(h, 80, t += 250);                  // 5 s below release
    CHECK(step_at(h, 86, t += 250) == kLevelTrip && h.clamp && !h.cooling, "monitor: a sample at or above release resets the run");
    const uint64_t again = (t += 250);
    step_at(h, 80, again);
    step_at(h, 80, again + kReleaseHoldMs - 1);
    CHECK(h.clamp, "monitor: the run restarted (9.999 s after the reset: still clamped)");
    CHECK(step_at(h, 80, again + kReleaseHoldMs) == kLevelOk && !h.clamp, "monitor: released 10 s after the restart");
    CHECK(step_at(h, 100, again + kReleaseHoldMs + 250) == kLevelTrip && h.clamp, "monitor: TRIP again after a release (nothing latched, nothing disarmed)");
    Monitor w2; monitor_init(w2);
    step_at(w2, 100, 0);
    for (uint64_t k = 250; k <= kReleaseHoldMs + 250; k += 250) step_at(w2, 60, k);
    CHECK(w2.level == kLevelOk && w2.reason == kReasonNone && !w2.clamp, "monitor: after release the reason is none");

    // unreadable sensor
    Monitor w; monitor_init(w);
    for (int i = 0; i < 11; i++) monitor_step(w, kTh, ThmDecode{false, 0, 0, 0}, (uint64_t)i * 250);
    CHECK(w.level == kLevelWarn && w.reason == kReasonSensorInvalid && !w.clamp, "monitor: 11 unreadable samples are WARN, no clamp");
    monitor_step(w, kTh, ThmDecode{false, 0, 0, 0}, 11 * 250);
    CHECK(w.level == kLevelTrip && w.clamp && w.reason == kReasonSensorInvalid, "monitor: 12 unreadable samples (3 s) are TRIP + clamp");
    CHECK(step_at(w, 40, 3250) == kLevelTrip && w.clamp && w.reason == kReasonCooling, "monitor: the sensor back at 40 C: still clamped (hysteresis)");
    CHECK(step_at(w, 40, 3250 + kReleaseHoldMs) == kLevelOk && !w.clamp, "monitor: released 10 s after the sensor came back cool");
    // unreadable samples never count towards a release
    Monitor u; monitor_init(u);
    step_at(u, 100, 0);
    step_at(u, 60, 250);
    monitor_step(u, kTh, ThmDecode{false, 0, 0, 0}, 5000);
    CHECK(u.clamp && u.level == kLevelTrip && !u.cooling, "monitor: an unreadable sample during the hold resets the run, keeps TRIP");
    step_at(u, 60, 5250);
    CHECK(step_at(u, 60, 5250 + kReleaseHoldMs - 250) == kLevelTrip && u.clamp, "monitor: the run restarted at the next readable sample");

    Monitor r; monitor_init(r);
    for (int i = 0; i < 5; i++) monitor_step(r, kTh, ThmDecode{false, 0, 0, 0}, (uint64_t)i);
    CHECK(step_at(r, 30, 10) == kLevelOk && r.invalidRun == 0, "monitor: a readable sample clears the invalid run");

    Monitor n; monitor_init(n);
    monitor_no_sensor(n);
    CHECK(n.level == kLevelTrip && n.reason == kReasonNoSensor && n.clamp, "monitor: no sensor fails closed = TRIP + clamp");
    CHECK(step_at(n, 30, 1000000) == kLevelTrip && n.clamp, "monitor: no sensor: the clamp is never released");
}

static void test_clamp_action() {
    CHECK(clamp_action(false, false, false, 0, 1000) == kActNone, "action: nothing wanted, nothing applied");
    CHECK(clamp_action(true, false, false, 0, 1000) == kActClamp, "action: TRIP -> clamp");
    CHECK(clamp_action(true, true, false, 0, 1000) == kActNone, "action: clamp already applied");
    CHECK(clamp_action(false, true, false, 0, 1000) == kActRestore, "action: release -> restore the boot policy");
    CHECK(clamp_action(true, false, true, 1000, 1500) == kActNone, "action: a failed clamp is not resent within 1 s");
    CHECK(clamp_action(true, false, true, 1000, 2000) == kActClamp, "action: a failed clamp is retried after 1 s");
    CHECK(clamp_action(false, true, true, 1000, 1999) == kActNone && clamp_action(false, true, true, 1000, 2000) == kActRestore,
          "action: a failed restore is retried after 1 s");
}

static void test_refusal() {
    // the 2026-11-12 freeze: submissions are never refused for a temperature or a sensor fault
    CHECK(!refuses_submissions(false, kLevelTrip), "refusal: TRIP does not refuse submissions");
    CHECK(!refuses_submissions(false, kLevelWarn) && !refuses_submissions(false, kLevelOk), "refusal: WARN / OK do not refuse submissions");
    CHECK(refuses_submissions(true, kLevelOk), "refusal: only teardown refuses submissions");
    CHECK(refuses_writers(false, kLevelTrip), "refusal: TRIP (and its cooling hold) refuses the writers (DAL, mode trial, clock raise)");
    CHECK(!refuses_writers(false, kLevelWarn) && !refuses_writers(false, kLevelOk), "refusal: WARN / OK do not refuse the writers");
    CHECK(refuses_writers(true, kLevelOk), "refusal: teardown / watchdog failure refuses the writers");
    // end to end over the monitor: the levels a full TRIP episode goes through never refuse a submission
    Monitor m; monitor_init(m);
    bool anySubmitRefused = false, writersRefusedDuringHold = true;
    uint64_t t = 0;
    for (int c : {60, 87, 95, 101, 104, 96, 90, 84}) { step_at(m, c, t += 250); anySubmitRefused |= refuses_submissions(false, m.level); }
    for (uint64_t k = 0; k < kReleaseHoldMs; k += 250) {
        step_at(m, 70, t += 250);
        anySubmitRefused |= refuses_submissions(false, m.level);
        if (m.clamp) writersRefusedDuringHold &= refuses_writers(false, m.level);
    }
    CHECK(!anySubmitRefused, "refusal: no submission refused through a whole TRIP episode");
    CHECK(writersRefusedDuringHold, "refusal: the writers stay refused while the clamp is held");
    CHECK(!m.clamp && !refuses_writers(false, m.level), "refusal: the writers are allowed again after the release");
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
    test_clamp_action();
    test_refusal();
    test_protections();
    test_heartbeat();
    std::printf("n4x_safety_pure: %d checks, %d failed\n", checks, fails);
    std::puts(fails == 0 ? "PASS" : "FAIL");
    return fails == 0 ? 0 : 1;
}
