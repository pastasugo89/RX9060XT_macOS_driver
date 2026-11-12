//
//  n4x_safety.cpp - the thermal safety watchdog thread (see n4x_safety.h; the decisions are in n4x_safety_pure.h).
//  0.0.675: a TRIP no longer latches or refuses submissions; it clamps GFXCLK low through the SMU (smu_set_power_state Low) and restores the
//  boot clock policy after the hysteresis of n4x_safety_pure.h (monitor_step, clamp_action). The SMU messages are sent from this thread under
//  the shared SMU mailbox lock (SmuSeq), only on a change of the wanted state (and at most once a second while a send fails).
//
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>

#include "n4x_safety.h"
#include "amdgpu_smu.h"

namespace n4xs {
namespace {

// Written by start() before the thread exists; read by the thread. Level, reason and the last sample are published atomically.
amdgpu::DeviceContext *gDev         = nullptr;
uint32_t               gSensorDword = 0;
bool                   gSensorOk    = false;
Thresholds             gTh          = { kDefaultWarnC, kDefaultTripC };

uint32_t gStarted  = 0;     // set once by start()
uint32_t gRunning  = 0;     // the thread is alive
uint32_t gStop     = 0;     // stop() asks the thread to end
uint32_t gLevel    = kLevelOk;
uint32_t gReason   = kReasonNone;
uint32_t gHot      = 0;     // last decoded hotspot (int32 bits)
uint32_t gHotValid = 0;
uint32_t gRaw      = 0;     // last THM dword
uint32_t gTeardown = 0;     // 0.0.675: stop() was called (the only state that refuses submissions)
uint32_t gRestoreState = amdgpu::SMUPowerState::Low;   // 0.0.675: the boot clock policy (navi48-idle-clamp: Low by default, Auto when off)
uint32_t gClampApplied = 0; // 0.0.675: the thermal clamp is in force
bool     gClampTried = false;
uint64_t gClampLastTryMs = 0;
bool     gClampSmuWaitLogged = false;
uint64_t gClampCount = 0;

uint64_t uptime_ms() {
    uint64_t t = 0, ns = 0;
    clock_get_uptime(&t);
    absolutetime_to_nanoseconds(t, &ns);
    return ns / 1000000ull;
}

void emit(bool stopping, uint64_t now) {
    HeartbeatFields f {};
    f.t_ms     = now;
    f.hotValid = __atomic_load_n(&gHotValid, __ATOMIC_ACQUIRE) != 0;
    f.hotC     = (int32_t)__atomic_load_n(&gHot, __ATOMIC_ACQUIRE);
    f.level    = __atomic_load_n(&gLevel, __ATOMIC_ACQUIRE);
    f.reason   = __atomic_load_n(&gReason, __ATOMIC_ACQUIRE);
    f.stopping = stopping;
    f.proto    = amdgpu::smu_protections_verified();
    f.thmRaw   = __atomic_load_n(&gRaw, __ATOMIC_ACQUIRE);
    char buf[200];
    format_heartbeat(buf, sizeof buf, f);
    IOLog("%s\n", buf);
}

// 0.0.675: send the clamp (kActClamp: GFXCLK soft max = PMFW minimum) or the restore (the boot clock policy). Runs on the watchdog thread.
void apply_clamp(uint32_t act, uint64_t now, int32_t hotC, uint32_t reason) {
    gClampTried = true;
    gClampLastTryMs = now;
    if (!gDev || !gDev->smuOnline) {
        if (!gClampSmuWaitLogged) {
            gClampSmuWaitLogged = true;
            IOLog("N4X-SAFETY event=%s-WAIT reason=%s: the SMU is not online yet, retried every %llu ms\n",
                  act == kActClamp ? "CLAMP" : "RESTORE", reason_name(reason), (unsigned long long)kClampRetryMs);
        }
        return;
    }
    const uint32_t state = act == kActClamp ? (uint32_t)amdgpu::SMUPowerState::Low : __atomic_load_n(&gRestoreState, __ATOMIC_ACQUIRE);
    kern_return_t kr;
    {
        amdgpu::SmuSeq seq;   // both clock messages under the shared mailbox lock, as Navi48UserClient::doPowerState
        kr = amdgpu::smu_set_power_state(*gDev, state);
    }
    if (kr == kIOReturnSuccess) {
        __atomic_store_n(&gClampApplied, act == kActClamp ? 1u : 0u, __ATOMIC_RELEASE);
        gClampTried = false;
        gClampSmuWaitLogged = false;
        if (act == kActClamp) gClampCount++;
    }
    IOLog("N4X-SAFETY event=%s reason=%s hotspot=%d power_state=%u kr=%#x (thermal clamps this boot: %llu)\n",
          act == kActClamp ? "CLAMP" : "RESTORE", reason_name(reason), (int)hotC, state, (unsigned)kr, (unsigned long long)gClampCount);
}

void watchdog_loop(void *, wait_result_t) {
    Monitor m;
    monitor_init(m);
    if (!gSensorOk) monitor_no_sensor(m);
    uint64_t lastHb = 0;
    bool first = true;
    bool tripLogged = false;
    while (__atomic_load_n(&gStop, __ATOMIC_ACQUIRE) == 0) {
        ThmDecode d { false, 0, 0, 0 };
        uint32_t raw = 0;
        const uint64_t sampleMs = uptime_ms();
        if (gSensorOk) {
            raw = RREG32(*gDev, gSensorDword);   // a read: no register is written here
            d = decode_thm_cur_temp(raw);
            monitor_step(m, gTh, d, sampleMs);
        }
        __atomic_store_n(&gRaw, raw, __ATOMIC_RELEASE);
        __atomic_store_n(&gHot, (uint32_t)d.tempC, __ATOMIC_RELEASE);
        __atomic_store_n(&gHotValid, d.valid ? 1u : 0u, __ATOMIC_RELEASE);
        __atomic_store_n(&gReason, m.reason, __ATOMIC_RELEASE);
        __atomic_store_n(&gLevel, m.level, __ATOMIC_RELEASE);   // 0.0.675: TRIP no longer latches (monitor_step's hysteresis)
        if (m.level == kLevelTrip && !tripLogged) {
            tripLogged = true;   // 0.0.675: re-armed when the level leaves TRIP, so every TRIP episode is logged once
            IOLog("N4X-SAFETY event=TRIP reason=%s hotspot=%d thm=%#x (GFXCLK clamped low until below %d C for %llu ms; submissions continue)\n",
                  reason_name(m.reason), (int)d.tempC, raw, release_c(gTh), (unsigned long long)kReleaseHoldMs);
        } else if (m.level != kLevelTrip && tripLogged) {
            tripLogged = false;
            IOLog("N4X-SAFETY event=TRIP-END hotspot=%d level=%s\n", (int)d.tempC, level_name(m.level));
        }
        const uint64_t now = uptime_ms();
        {
            const uint32_t act = clamp_action(m.clamp, __atomic_load_n(&gClampApplied, __ATOMIC_ACQUIRE) != 0, gClampTried, gClampLastTryMs, now);
            if (act != kActNone) apply_clamp(act, now, d.tempC, m.reason);
        }
        if (first || now - lastHb >= kHeartbeatMs) {
            emit(false, now);
            lastHb = now;
            first = false;
        }
        IOSleep(kSamplePeriodMs);
    }
    emit(true, uptime_ms());
    __atomic_store_n(&gRunning, 0u, __ATOMIC_RELEASE);
}

}  // namespace

bool config(bool defaultOn, Thresholds *th) {
    uint32_t on = defaultOn ? 1u : 0u;
    PE_parse_boot_argn("navi48-safety", &on, sizeof(on));
    uint32_t w = (uint32_t)kDefaultWarnC, t = (uint32_t)kDefaultTripC;
    PE_parse_boot_argn("navi48-safety-warn", &w, sizeof(w));
    PE_parse_boot_argn("navi48-safety-trip", &t, sizeof(t));
    Thresholds c { (int32_t)w, (int32_t)t };
    if (!thresholds_valid(c) || w > (uint32_t)kConfigMaxC || t > (uint32_t)kConfigMaxC) {
        IOLog("N4X-SAFETY event=CONFIG-REFUSED warn=%u trip=%u (accepted 50..105, warn < trip): defaults %d/%d\n",
              w, t, kDefaultWarnC, kDefaultTripC);
        c = Thresholds { kDefaultWarnC, kDefaultTripC };
    }
    if (th) *th = c;
    return on != 0;
}

void start(amdgpu::DeviceContext &dev, uint32_t sensorDword, const Thresholds &th) {
    if (__atomic_exchange_n(&gStarted, 1u, __ATOMIC_ACQ_REL) != 0) return;
    gDev = &dev;
    gSensorDword = sensorDword;
    gSensorOk = (sensorDword != 0) && (dev.rmmio != nullptr);
    gTh = thresholds_valid(th) ? th : Thresholds { kDefaultWarnC, kDefaultTripC };
    IOLog("N4X-SAFETY event=START sensor=%s dword=%#x warn=%d trip=%d release=%d/%llums (TRIP clamps GFXCLK, never refuses submissions)\n",
          gSensorOk ? "THM_TCON_CUR_TMP" : "unresolved (fail closed: clamp)", sensorDword, gTh.warnC, gTh.tripC, release_c(gTh),
          (unsigned long long)kReleaseHoldMs);
    __atomic_store_n(&gRunning, 1u, __ATOMIC_RELEASE);
    thread_t th_ = nullptr;
    const kern_return_t kr = kernel_thread_start(&watchdog_loop, nullptr, &th_);
    if (kr != KERN_SUCCESS) {
        __atomic_store_n(&gRunning, 0u, __ATOMIC_RELEASE);
        __atomic_store_n(&gReason, (uint32_t)kReasonNoSensor, __ATOMIC_RELEASE);
        __atomic_store_n(&gLevel, (uint32_t)kLevelTrip, __ATOMIC_RELEASE);   // fail closed: no thread, no protection
        IOLog("N4X-SAFETY event=START-FAILED kr=%#x state=TRIP\n", kr);
        return;
    }
    thread_deallocate(th_);
}

void stop() {
    __atomic_store_n(&gTeardown, 1u, __ATOMIC_RELEASE);
    if (__atomic_load_n(&gRunning, __ATOMIC_ACQUIRE) == 0) return;
    __atomic_store_n(&gStop, 1u, __ATOMIC_RELEASE);
    for (int i = 0; i < 3000 && __atomic_load_n(&gRunning, __ATOMIC_ACQUIRE) != 0; i++) IOSleep(1);
    if (__atomic_load_n(&gRunning, __ATOMIC_ACQUIRE) != 0) IOLog("N4X-SAFETY event=STOP-TIMEOUT\n");
}

bool active() {
    return __atomic_load_n(&gRunning, __ATOMIC_ACQUIRE) != 0;
}

uint32_t level() {
    return __atomic_load_n(&gLevel, __ATOMIC_ACQUIRE);
}

bool refused() {
    return refuses_writers(__atomic_load_n(&gStop, __ATOMIC_ACQUIRE) != 0, level());
}

bool submit_refused() {
    return refuses_submissions(__atomic_load_n(&gTeardown, __ATOMIC_ACQUIRE) != 0, level());
}

bool clamped() {
    return __atomic_load_n(&gClampApplied, __ATOMIC_ACQUIRE) != 0;
}

void set_restore_state(uint32_t smuPowerState) {
    __atomic_store_n(&gRestoreState, smuPowerState, __ATOMIC_RELEASE);
}

bool clock_raise_allowed() {
    uint32_t v = 0;
    return PE_parse_boot_argn("navi48-clock-raise", &v, sizeof(v)) && v == 1u;
}

}  // namespace n4xs
