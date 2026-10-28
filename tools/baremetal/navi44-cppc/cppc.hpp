// Pure CPPC transaction logic; no kernel, I/O or privileged instructions.
// Register definitions cross-checked against Linux msr-index.h and FreeBSD
// hwpstate_amd.c. CAP1 field order differs from REQUEST field order.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace n44cppc {
constexpr unsigned kCpus = 16;
constexpr uint32_t kCap = 0xc00102b0, kEnable = 0xc00102b1, kRequest = 0xc00102b3;
constexpr uint8_t kBalancedEpp = 128;
enum class Phase { Snapshot, Enable, Plan, Request, Verify, Restore, Observe };
enum class Error : uint32_t { None, Profile, Read, Write, Caps, Readback, NoSnapshot, Ownership };

inline bool profile(bool amd, unsigned family, unsigned model, unsigned stepping,
                    uint32_t ebx8, bool hypervisor, const char *brand) {
    const char prefix[] = "AMD Ryzen 7 7700 ";
    return amd && family == 0x19 && model == 0x61 && stepping == 2 &&
           (ebx8 & (1u << 27)) && !hypervisor && brand &&
           !strncmp(brand, prefix, sizeof(prefix) - 1);
}
struct Caps {
    uint8_t lowest, efficient, nominal, highest;
};
inline Caps decode(uint64_t value) {
    return { static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8),
             static_cast<uint8_t>(value >> 16), static_cast<uint8_t>(value >> 24) };
}
inline bool valid(Caps c) {
    return c.lowest > 0 && c.lowest <= c.efficient && c.efficient <= c.nominal &&
           c.nominal <= c.highest && c.lowest < c.highest;
}
inline bool request(uint64_t original, uint64_t cap, unsigned epp, uint64_t &out) {
    const Caps c = decode(cap);
    if (!valid(c) || epp > 255) return false;
    // DesiredPerformance=0 selects autonomous operation. Preserve reserved upper bits.
    out = (original & 0xffffffff00000000ull) | (static_cast<uint64_t>(epp) << 24) |
          (static_cast<uint64_t>(c.lowest) << 8) | c.highest;
    return true;
}
struct Core {
    bool seen = false, saved = false, enableTouched = false, requestTouched = false;
    Error error = Error::None;
    uint64_t originalEnable = 0, originalRequest = 0;
    uint64_t cap = 0, enable = 0, req = 0, target = 0;
};
// IO::read/write operate on the CPU executing this function. Kernel callers
// run one phase on every CPU, then inspect all results before the next phase.
template <typename IO> inline void step(Core &c, Phase phase, IO &io, unsigned epp = kBalancedEpp) {
    c.seen = true; c.error = Error::None;
    if (!io.profile()) { c.error = Error::Profile; return; }
    if (phase == Phase::Snapshot) {
        if (c.saved) { c.error = Error::Ownership; return; }
        if (!io.read(kEnable, c.originalEnable) || !io.read(kRequest, c.originalRequest) || !io.read(kCap, c.cap)) {
            c.error = Error::Read; return;
        }
        c.enable = c.originalEnable; c.req = c.originalRequest; c.saved = true;
        return;
    }
    if (phase == Phase::Observe) {
        if (!io.read(kEnable, c.enable) || !io.read(kRequest, c.req) || !io.read(kCap, c.cap)) c.error = Error::Read;
        return;
    }
    if (!c.saved) { if (phase != Phase::Restore) c.error = Error::NoSnapshot; return; }
    if (phase == Phase::Enable) {
        if (!(c.originalEnable & 1)) {
            c.enableTouched = true; // A fault may follow a partial operation: still attempt rollback.
            if (!io.write(kEnable, c.originalEnable | 1)) { c.error = Error::Write; return; }
        }
        return;
    }
    if (phase == Phase::Plan) {
        // Read CAP1 after enabling: some firmware returns its reset value while disabled.
        if (!io.read(kCap, c.cap)) { c.error = Error::Read; return; }
        if (!request(c.originalRequest, c.cap, epp, c.target)) c.error = Error::Caps;
        return;
    }
    if (phase == Phase::Request) {
        c.requestTouched = true;
        if (!io.write(kRequest, c.target)) c.error = Error::Write;
        return;
    }
    if (phase == Phase::Verify) {
        if (!io.read(kEnable, c.enable) || !io.read(kRequest, c.req)) { c.error = Error::Read; return; }
        if (c.enable != (c.originalEnable | 1) || c.req != c.target) c.error = Error::Readback;
        return;
    }
    if (phase == Phase::Restore) {
        bool ok = true;
        if (c.requestTouched) ok = io.write(kRequest, c.originalRequest) && ok;
        if (c.enableTouched) ok = io.write(kEnable, c.originalEnable) && ok;
        uint64_t en = 0, req = 0;
        const bool read = io.read(kEnable, en) && io.read(kRequest, req);
        if (!ok) c.error = Error::Write;
        else if (!read) c.error = Error::Read;
        else if ((c.enableTouched && en != c.originalEnable) || (c.requestTouched && req != c.originalRequest)) c.error = Error::Readback;
        if (c.error == Error::None) { c.enableTouched = c.requestTouched = false; c.saved = false; }
        c.enable = en; c.req = req;
    }
}
inline bool complete(const Core *cores, bool badIndex = false) {
    if (badIndex) return false;
    for (unsigned i = 0; i < kCpus; i++) if (!cores[i].seen || cores[i].error != Error::None) return false;
    return true;
}
struct Outcome { bool active, restored; Phase failed; };
template <typename Batch> inline Outcome activate(Batch &batch) {
    if (!batch.run(Phase::Snapshot)) return { false, true, Phase::Snapshot }; // no writes yet
    const Phase phases[] = { Phase::Enable, Phase::Plan, Phase::Request, Phase::Verify };
    for (Phase phase : phases) if (!batch.run(phase)) return { false, batch.run(Phase::Restore), phase };
    return { true, false, Phase::Verify };
}
}
