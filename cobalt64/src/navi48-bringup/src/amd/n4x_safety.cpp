//
//  n4x_safety.cpp - the thermal safety watchdog thread (see n4x_safety.h; the decisions are in n4x_safety_pure.h).
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
        if (gSensorOk) {
            raw = RREG32(*gDev, gSensorDword);   // a read: no register is written here
            d = decode_thm_cur_temp(raw);
            monitor_step(m, gTh, d);
        }
        __atomic_store_n(&gRaw, raw, __ATOMIC_RELEASE);
        __atomic_store_n(&gHot, (uint32_t)d.tempC, __ATOMIC_RELEASE);
        __atomic_store_n(&gHotValid, d.valid ? 1u : 0u, __ATOMIC_RELEASE);
        __atomic_store_n(&gReason, m.reason, __ATOMIC_RELEASE);
        __atomic_store_n(&gLevel, m.level, __ATOMIC_RELEASE);   // TRIP latches inside monitor_step
        if (m.level == kLevelTrip && !tripLogged) {
            tripLogged = true;
            IOLog("N4X-SAFETY event=TRIP reason=%s hotspot=%d thm=%#x\n", reason_name(m.reason), (int)d.tempC, raw);
        }
        const uint64_t now = uptime_ms();
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
    if (!thresholds_valid(c) || w > 100u || t > 100u) {
        IOLog("N4X-SAFETY event=CONFIG-REFUSED warn=%u trip=%u (accepted 50..100, warn < trip): defaults %d/%d\n",
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
    IOLog("N4X-SAFETY event=START sensor=%s dword=%#x warn=%d trip=%d\n",
          gSensorOk ? "THM_TCON_CUR_TMP" : "unresolved (fail closed)", sensorDword, gTh.warnC, gTh.tripC);
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
    return level() == kLevelTrip;
}

bool clock_raise_allowed() {
    uint32_t v = 0;
    return PE_parse_boot_argn("navi48-clock-raise", &v, sizeof(v)) && v == 1u;
}

}  // namespace n4xs
