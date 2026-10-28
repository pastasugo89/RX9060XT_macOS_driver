#include "cppc.hpp"
#include <Headers/kern_api.hpp>
#include <Headers/kern_patcher.hpp>
#include <Headers/plugin_start.hpp>
#include <IOKit/IOLib.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOCommandGate.h>
#include <IOKit/pwr_mgt/IOPM.h>
#include <IOKit/pwr_mgt/IOPMpowerState.h>
#include <i386/proc_reg.h>
#include <libkern/c++/OSArray.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <pexpert/pexpert.h>

extern "C" int cpu_number(void);
extern "C" void mp_rendezvous(void (*)(void *), void (*)(void *), void (*)(void *), void *);
using Writer = int (*)(uint32_t, uint32_t, uint32_t);
static Writer writer = nullptr;

static void cpuid(uint32_t leaf, uint32_t &a, uint32_t &b, uint32_t &c, uint32_t &d) {
    __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(c), "=d"(d) : "a"(leaf), "c"(0));
}
static bool supportedCpu() {
    if (getKernelVersion() != KernelVersion::Tahoe || getKernelMinorVersion() != 6) return false;
    uint32_t a, b, c, d;
    cpuid(0, a, b, c, d);
    if (b != 0x68747541 || d != 0x69746e65 || c != 0x444d4163) return false;
    cpuid(0x80000000, a, b, c, d);
    if (a < 0x80000008) return false;
    char brand[49] = {};
    for (unsigned i = 0; i < 3; i++) {
        cpuid(0x80000002 + i, a, b, c, d);
        const uint32_t words[] = { a, b, c, d };
        memcpy(brand + 16 * i, words, 16);
    }
    cpuid(1, a, b, c, d);
    const unsigned family = ((a >> 8) & 15) + ((a >> 20) & 255);
    const unsigned model = ((a >> 4) & 15) | (((a >> 16) & 15) << 4), stepping = a & 15;
    const bool hypervisor = (c & (1u << 31)) != 0;
    cpuid(0x80000008, a, b, c, d);
    return n44cppc::profile(true, family, model, stepping, b, hypervisor, brand);
}
struct NativeIO {
    bool profile() { return supportedCpu(); }
    bool read(uint32_t msr, uint64_t &value) {
        uint32_t lo = 0, hi = 0;
        if (rdmsr_carefully(msr, &lo, &hi)) return false;
        value = lo | (static_cast<uint64_t>(hi) << 32);
        return true;
    }
    bool write(uint32_t msr, uint64_t value) {
        // No inline WRMSR fallback, no arbitrary MSR interface.
        if (msr != n44cppc::kEnable && msr != n44cppc::kRequest) return false;
        Writer fn = __atomic_load_n(&writer, __ATOMIC_ACQUIRE);
        return fn && fn(msr, static_cast<uint32_t>(value), static_cast<uint32_t>(value >> 32)) == 0;
    }
};

class EXPORT Navi44CPPC : public IOService {
    OSDeclareDefaultStructors(Navi44CPPC)
    IOWorkLoop *loop = nullptr;
    IOTimerEventSource *timer = nullptr;
    IOCommandGate *gate = nullptr;
    n44cppc::Core cores[n44cppc::kCpus];
    struct Performance { uint64_t aperf = 0, mperf = 0, sample = 0; bool valid = false; } perf[n44cppc::kCpus];
    n44cppc::Phase phase = n44cppc::Phase::Observe;
    uint32_t badIndex = 0, awake = 1, resume = 0;
    bool active = false, failed = false, stopped = false, attempted = false;
    unsigned mode = 0, readyAttempts = 0;
    const char *state = "starting";
    static void rendezvous(void *arg) {
        auto self = static_cast<Navi44CPPC *>(arg);
        const int cpu = cpu_number();
        if (cpu < 0 || static_cast<unsigned>(cpu) >= n44cppc::kCpus) {
            __atomic_store_n(&self->badIndex, 1u, __ATOMIC_RELAXED); return;
        }
        NativeIO io;
        n44cppc::step(self->cores[cpu], self->phase, io);
        if (self->phase == n44cppc::Phase::Observe) {
            auto &p = self->perf[cpu];
            p.valid = self->cores[cpu].error == n44cppc::Error::None &&
                      io.read(0xe8, p.aperf) && io.read(0xe7, p.mperf);
            if (p.valid) p.sample++;
        }
    }
    void publish() {
        bool verified = active && n44cppc::complete(cores, badIndex != 0);
        for (const auto &core : cores) verified &= core.enable == (core.originalEnable | 1) && core.req == core.target;
        setProperty("CPPC,State", state);
        setProperty("CPPC,ActiveVerified", static_cast<uint64_t>(verified), 32);
        setProperty("CPPC,OwnsSnapshot", static_cast<uint64_t>(active), 32);
        setProperty("CPPC,RequestedMode", static_cast<uint64_t>(mode), 32);
        setProperty("CPPC,EPP", static_cast<uint64_t>(n44cppc::kBalancedEpp), 32);
        setProperty("CPPC,SafeWriterAvailable", static_cast<uint64_t>(__atomic_load_n(&writer, __ATOMIC_ACQUIRE) != nullptr), 32);
        OSArray *data = OSArray::withCapacity(n44cppc::kCpus);
        if (!data) return;
        for (unsigned i = 0; i < n44cppc::kCpus; i++) {
            const auto &c = cores[i];
            OSDictionary *row = OSDictionary::withCapacity(13);
            if (!row) continue;
            const char *keys[] = { "CPU", "Seen", "Error", "Enable", "Request", "Capability1", "TargetRequest", "OriginalRequest", "OriginalEnable", "APERF", "MPERF", "PerfSample", "PerfValid" };
            const uint64_t values[] = { i, c.seen, static_cast<uint32_t>(c.error), c.enable, c.req, c.cap, c.target, c.originalRequest, c.originalEnable, perf[i].aperf, perf[i].mperf, perf[i].sample, perf[i].valid };
            for (unsigned k = 0; k < sizeof(keys) / sizeof(keys[0]); k++) {
                OSNumber *number = OSNumber::withNumber(values[k], 64);
                if (number) { row->setObject(keys[k], number); number->release(); }
            }
            data->setObject(row); row->release();
        }
        setProperty("CPPC,Cores", data); data->release();
    }
    bool anotherManager() {
        OSDictionary *match = IOService::serviceMatching("AMDRyzenCPUPowerManagement");
        if (!match) return true;
        IOService *other = IOService::copyMatchingService(match);
        match->release();
        if (other) { other->release(); return true; }
        return false;
    }
    void tick() {
        if (stopped || !__atomic_load_n(&awake, __ATOMIC_ACQUIRE)) return;
        if (mode != 1 || failed) {
            run(n44cppc::Phase::Observe);
            if (!failed) state = "read-only";
            publish(); return;
        }
        if (__atomic_exchange_n(&resume, 0u, __ATOMIC_ACQ_REL) && active) {
            // Workloop context after wake, never a rendezvous on the PM callback thread.
            if (!run(n44cppc::Phase::Observe)) {
                __atomic_store_n(&resume, 1u, __ATOMIC_RELEASE);
                state = "resume-awaiting-all-cpus"; publish(); return;
            }
            if (!run(n44cppc::Phase::Restore)) {
                active = false; failed = true; state = "resume-rollback-failed"; publish(); return;
            }
            active = attempted = false;
        }
        if (!attempted && !__atomic_load_n(&writer, __ATOMIC_ACQUIRE)) {
            run(n44cppc::Phase::Observe);
            state = "awaiting-safe-writer";
            if (++readyAttempts >= 10) { failed = true; state = "read-only-no-safe-writer"; }
            publish(); return;
        }
        if (!attempted) {
            attempted = true;
            if (anotherManager()) { failed = true; state = "refused-other-cpu-manager"; publish(); return; }
            auto result = n44cppc::activate(*this);
            active = result.active; failed = !result.active;
            setProperty("CPPC,FailedPhase", result.active ? 0xffffffffull : static_cast<uint64_t>(result.failed), 32);
            state = active ? "autonomous-balanced-verified" : result.failed == n44cppc::Phase::Snapshot ?
                "activation-refused-before-writes" : result.restored ? "activation-refused-restored" : "rollback-failed";
            IOLog("Navi44CPPC: %s\n", state);
        } else if (active) {
            if (!run(n44cppc::Phase::Observe)) state = "active-observation-failed";
            else {
                bool matches = true;
                for (const auto &core : cores) matches &= core.enable == (core.originalEnable | 1) && core.req == core.target;
                state = matches ? "autonomous-balanced-verified" : "policy-changed-externally";
            }
        }
        publish();
    }
    static void onTimer(OSObject *owner, IOTimerEventSource *source) {
        auto self = OSDynamicCast(Navi44CPPC, owner);
        if (!self) return;
        self->tick();
        if (!self->stopped) source->setTimeoutMS(1000);
    }
    static IOReturn stopAction(OSObject *owner, void *, void *, void *, void *) {
        auto self = OSDynamicCast(Navi44CPPC, owner);
        if (!self) return kIOReturnBadArgument;
        self->stopped = true;
        if (self->timer) self->timer->cancelTimeout();
        bool saved = false; for (const auto &core : self->cores) saved |= core.saved;
        if (saved && !self->run(n44cppc::Phase::Restore)) IOLog("Navi44CPPC: stop rollback failed\n");
        return kIOReturnSuccess;
    }
public:
    bool run(n44cppc::Phase next) {
        phase = next; badIndex = 0;
        for (unsigned i = 0; i < n44cppc::kCpus; i++) {
            cores[i].seen = false;
            if (next == n44cppc::Phase::Observe) perf[i].valid = false;
        }
        mp_rendezvous(nullptr, &rendezvous, nullptr, this);
        return n44cppc::complete(cores, badIndex != 0);
    }
    bool start(IOService *provider) override {
        if (!IOService::start(provider)) return false;
        if (!ADDPR(startSuccess) || !supportedCpu()) { state = "unsupported-profile"; publish(); return false; }
        PE_parse_boot_argn("n44-cppc", &mode, sizeof(mode));
        loop = IOWorkLoop::workLoop();
        timer = IOTimerEventSource::timerEventSource(this, &onTimer);
        gate = IOCommandGate::commandGate(this);
        const IOReturn gateResult = loop && gate ? loop->addEventSource(gate) : kIOReturnNoMemory;
        const IOReturn timerResult = loop && timer && gateResult == kIOReturnSuccess ? loop->addEventSource(timer) : kIOReturnNoMemory;
        if (timerResult != kIOReturnSuccess) {
            if (gateResult == kIOReturnSuccess) loop->removeEventSource(gate);
            if (gate) { gate->release(); gate = nullptr; }
            if (timer) { timer->release(); timer = nullptr; }
            if (loop) { loop->release(); loop = nullptr; }
            return false;
        }
        PMinit();
        IOPMPowerState states[2] = {};
        states[0].version = states[1].version = 1;
        states[1].capabilityFlags = kIOPMPowerOn | kIOPMDeviceUsable;
        states[1].inputPowerRequirement = states[1].outputPowerCharacter = kIOPMPowerOn;
        provider->joinPMtree(this);
        if (registerPowerDriver(this, states, 2) != kIOReturnSuccess) {
            PMstop();
            loop->removeEventSource(timer); loop->removeEventSource(gate);
            timer->release(); timer = nullptr; gate->release(); gate = nullptr;
            loop->release(); loop = nullptr;
            return false;
        }
        timer->setTimeoutMS(1000); registerService();
        return true;
    }
    IOReturn setPowerState(unsigned long ordinal, IOService *) override {
        const uint32_t on = ordinal ? 1u : 0u;
        const uint32_t was = __atomic_exchange_n(&awake, on, __ATOMIC_ACQ_REL);
        if (on && !was) __atomic_store_n(&resume, 1u, __ATOMIC_RELEASE);
        return IOPMAckImplied;
    }
    void stop(IOService *provider) override {
        PMstop();
        if (gate) gate->runAction(&stopAction);
        else stopped = true;
        if (loop && timer) loop->removeEventSource(timer);
        if (loop && gate) loop->removeEventSource(gate);
        if (timer) { timer->release(); timer = nullptr; }
        if (gate) { gate->release(); gate = nullptr; }
        if (loop) { loop->release(); loop = nullptr; }
        IOService::stop(provider);
    }
};
OSDefineMetaClassAndStructors(Navi44CPPC, IOService)

static void onPatcher(void *, KernelPatcher &patcher) {
    if (getKernelVersion() != KernelVersion::Tahoe || getKernelMinorVersion() != 6) return;
    auto address = patcher.solveSymbol(KernelPatcher::KernelID, "_wrmsr_carefully");
    patcher.clearError();
    if (address) __atomic_store_n(&writer, reinterpret_cast<Writer>(address), __ATOMIC_RELEASE);
}
static void pluginStart() {
    const auto error = lilu.onPatcherLoad(&onPatcher);
    if (error != LiluAPI::Error::NoError) IOLog("Navi44CPPC: no patcher callback; read-only\n");
}
static const char *disableArgs[] = { "-n44cppcoff" };
PluginConfiguration ADDPR(config) = {
    "Navi44CPPC", parseModuleVersion("0.0.1"), LiluAPI::AllowNormal,
    disableArgs, 1, nullptr, 0, nullptr, 0,
    KernelVersion::Tahoe, KernelVersion::Tahoe, &pluginStart
};
