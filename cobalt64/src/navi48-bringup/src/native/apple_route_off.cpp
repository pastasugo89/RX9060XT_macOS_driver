//
//  apple_route_off.cpp - the kext WITHOUT Cobalt64's "Apple route" (make APPLE_ROUTE=0, the default of this port).
//
//  The Apple route drives Apple's own AMD kexts (AMDRadeonX6000 & co.) from this kext: apple/AppleHardwareHook.cpp,
//  apple/AppleTtlHook.cpp, apple/Navi48AccelPeer.cpp, apple/Navi48Ttl.cpp, xlat12 and shadercache. This port uses only the
//  native route, so those translation units are left out of the build and this file provides, for every symbol the native
//  code still references, the behaviour the real function has when the Apple route is not running:
//    * Apple's AMD kexts are not loaded (their personalities are gone from Info.plist), so no hook is ever installed,
//      install_ttl_hook never succeeds and `accel fire` never happens: every fire-gated verb returns kIOReturnNotReady in
//      Navi48Bringup::accelExperiment before reaching its function here;
//    * every Apple-route switch is OFF at boot.
//  Each body below reproduces that default state (status codes, the non-zero defaults of out[] included). The
//  classification, with the file:line evidence of each default path, is in research/reports/apple_route_split.md.
//
//  Three functions are NOT Apple-route code and are copied here verbatim (they run in the default configuration):
//    hw_hook_ramtop_init / hw_hook_ramtop_derived_or_zero - the RAM top from the EFI memory map, read by BoImportHost's
//      device-page refusal (amd/native_s1c.cpp);
//    hw_hook_uptime_us - the boot chain's timestamps.
//  gfxneuter keeps routing the three switches whose state lives in the native code: 37 (MM-window priority), 74 (flip mode)
//  and 83 (the GMC TLB-flush wait). The "continuous arm" guard those switches consult is Apple-route state that never
//  exists here, so it is passed as "not standing".
//
//  apple/DisplayPipeGuard.cpp stays compiled: it also holds native display code (the native AGDC route behind
//  navi48-metal-disp=1, the scanout descriptor of the user client, the RDNA4FB helpers). The Apple-route symbols it
//  references (the present hooks, the X6000 accelerator anchors) are stubbed here too.
//
#if !N4X_APPLE_ROUTE

#include "../amd/n48log.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include "../apple/AppleHardwareHook.hpp"
#include "../apple/AppleTtlHook.hpp"
#include "../apple/Navi48Ttl.hpp"
#include "../apple/fastcopy.h"
#include "../apple/pairing_policy.h"
#include "../apple/gfx_ramtop.h"

#define AROLOG(fmt, ...) ::amdgpu::n48_logf("AppleRouteOff: " fmt "\n", ##__VA_ARGS__)

static inline void aro_zero(uint64_t *out, unsigned count, unsigned max) {
    if (out) for (unsigned i = 0; i < count && i < max; i++) out[i] = 0;
}

// ===================================================================================================================
// Copied from apple/AppleHardwareHook.cpp (0.0.386 and 0.0.237): native work, needed with or without the Apple route.
// ===================================================================================================================
namespace n48 {

static uint64_t         gRamTopDerived = N48_RT_LEGACY_TOP;
static uint32_t         gRamTopDone    = 0u;
static uint64_t         gRamTopPhysMem = 0u;
static n48_rt_res       gRamTopRes {};

static void ramtop_line(const char *how) {
    AROLOG("gfxc-ramtop: host-page RAM bound %#llx (%s). Derived %#llx, legacy floor %#llx, map reason %s. EFI map: %u "
           "descriptor(s), %u RAM, %u device window(s), %u empty, %u out of order; RAM total %llu MiB vs installed %llu MiB.",
           (unsigned long long)gRamTopDerived, how, (unsigned long long)gRamTopDerived,
           (unsigned long long)N48_RT_LEGACY_TOP, n48_rt_reason_name(gRamTopRes.reason), gRamTopRes.descs,
           gRamTopRes.ram_descs, gRamTopRes.dev_descs, gRamTopRes.empty_descs, gRamTopRes.unsorted,
           (unsigned long long)(gRamTopRes.ram_bytes >> 20), (unsigned long long)(gRamTopPhysMem >> 20));
}

// Once, from Navi48Bringup::start, single-threaded. Every failure path leaves the bound at the legacy constant.
void hw_hook_ramtop_init() {
    if (gRamTopDone) return;
    gRamTopDone = 1u;

    const boot_args *ba = reinterpret_cast<const boot_args *>(PE_state.bootArgs);
    if (!ba) { gRamTopRes.reason = N48_RT_NO_MAP; gRamTopRes.value = N48_RT_LEGACY_TOP; ramtop_line("PE_state.bootArgs is null"); return; }

    const uint64_t phys  = ba->MemoryMap;
    const uint64_t bytes = ba->MemoryMapSize;
    const uint32_t dsz   = ba->MemoryMapDescriptorSize;
    gRamTopPhysMem       = ba->PhysicalMemorySize;

    if (!phys || (phys & 0xfffull) || !bytes || bytes > (uint64_t)N48_RT_DESC_MAX * N48_RT_DESC_COUNT_MAX ||
        phys + bytes > N48_RT_HOLE_LO) {
        gRamTopRes.reason = N48_RT_BAD_HEADER; gRamTopRes.value = N48_RT_LEGACY_TOP;
        ramtop_line("boot_args names a map we refuse to map");
        return;
    }

    const char *how = "read";
    if (IOMemoryDescriptor *md = IOMemoryDescriptor::withPhysicalAddress((IOPhysicalAddress)phys, (IOByteCount)bytes,
                                                                         kIODirectionIn)) {
        if (md->prepare(kIODirectionIn) == kIOReturnSuccess) {
            if (IOMemoryMap *map = md->map()) {
                n48_rt_map in {};
                in.desc      = reinterpret_cast<const uint8_t *>(map->getVirtualAddress());
                in.bytes     = bytes;
                in.desc_size = dsz;
                in.phys_mem  = gRamTopPhysMem;
                in.floor     = N48_RT_LEGACY_TOP;
                (void)n48_rt_eval(&in, &gRamTopRes);
                map->release();
            } else { how = "IOMemoryMap::map failed"; gRamTopRes.reason = N48_RT_NO_MAP; }
            md->complete(kIODirectionIn);
        } else { how = "IOMemoryDescriptor::prepare failed"; gRamTopRes.reason = N48_RT_NO_MAP; }
        md->release();
    } else { how = "IOMemoryDescriptor::withPhysicalAddress failed"; gRamTopRes.reason = N48_RT_NO_MAP; }

    if (gRamTopRes.value < N48_RT_LEGACY_TOP) gRamTopRes.value = N48_RT_LEGACY_TOP;
    gRamTopDerived = gRamTopRes.value;
    ramtop_line(how);
}

uint64_t hw_hook_ramtop_derived_or_zero() { return (gRamTopDone != 0u && gRamTopRes.reason == N48_RT_OK) ? gRamTopDerived : 0ull; }

uint64_t hw_hook_uptime_us() {
    uint64_t t = 0, ns = 0;
    clock_get_uptime(&t);
    absolutetime_to_nanoseconds(t, &ns);
    return ns / 1000ull;
}

// ===================================================================================================================
// Hot paths: the default state of each (no holder, no arm, no bridge armed).
// ===================================================================================================================
uint32_t hw_mkh_gate(uintptr_t) { return 0; }
uint32_t hw_mkh_holder(uintptr_t) { return 0; }
void hw_mkh_spin(uint32_t, uint64_t) {}
void hw_mkh_lockwait(uint64_t) {}
uint32_t hw_hook_eop_bridge_fire(uint32_t) { return 0; }
uint32_t hw_hook_sdma_trap_bridge_fire(uint32_t) { return 0; }
uint32_t hw_cm_armed() { return 0; }
uint32_t hw_sk82_flight_live() { return 0; }
int64_t hw_d84_ws_pid() { return -1; }
void hw_hook_boot_chain_configure(uint32_t mode) {
    if (mode) AROLOG("boot-chain: navi48-boot-chain=%#x ignored (the boot chain drives Apple's accelerator: not built)", mode);
}
uint32_t hw_hook_eop_bridge_control(uint32_t, uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }

// Present hooks read by apple/DisplayPipeGuard.cpp: switches 73 and 95 OFF (every present copies).
uint32_t hw_p73_on() { return 0; }
uint32_t hw_p95_on() { return 0; }
uint32_t hw_p73_present(uint64_t, uint64_t) { return 1; }
uint32_t hw_p95_present(uint64_t *, uint64_t *, uint32_t *, uint32_t *, uint32_t *, uint32_t *, uint32_t *, uint32_t *, uint64_t) { return 1; }
void hw_p73_delivered() {}
void hw_p95_after_copy(uint64_t, uint32_t) {}
uint32_t hw_hook_dpg_writedata(uint32_t mode, uint64_t *out, unsigned count) {
    aro_zero(out, count, 12);
    return mode == 1 ? 1u : 0u;   // arming refused: the GFX writeTail hook is never installed
}

// ===================================================================================================================
// Verbs reachable without `accel fire`: the default answer of each.
// ===================================================================================================================
uint32_t hw_hook_gfx_neuter(uint64_t arg, uint64_t *out, unsigned count) {
    uint32_t st = 0;
    const uint32_t sw = (uint32_t)(arg & 0xffu), m = (uint32_t)(arg >> 8);
    if (sw == 37u) {
        if (m == 0u) (void)navi48_mm_prio_switch(0u);
        else if (m == 0xFFu || m == 1u) (void)navi48_mm_prio_switch(m);
        else st = 6;
    } else if (sw == 74u) {
        st = navi48_fm_control(m, 0u);
    } else if (sw == 83u) {
        (void)navi48_tlb83_switch(m, 0u, &st);
    } else if (arg == 1u) {
        st = 1;   // the GFX protection cannot arm: no Apple ring
    } else if (arg != 0u && arg != 2u) {
        st = 11;  // an Apple-route switch: refused, nothing changed
    }
    if (out && count > 7) { out[7] = 0; }
    if (out && count > 8) { out[8] = 0; }
    if (st == 11) AROLOG("gfxneuter %#llx refused: Apple-route switch (not built)", (unsigned long long)arg);
    return st;
}
uint32_t hw_hook_gfx_census(uint64_t, uint64_t *out, unsigned count) { aro_zero(out, count, 7); return 0; }
uint32_t hw_hook_gfx_probe(uint64_t arg, uint64_t *, unsigned) { return arg == 1 ? 1u : 0u; }
uint32_t hw_hook_gfx_capture(uint64_t arg, uint64_t *, unsigned) { return arg == 1 ? 1u : 0u; }
uint32_t hw_hook_drain_state(uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t hw_hook_boot_chain_state(uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t hw_hook_kiq_stamp(KiqStampInfo *out) { if (out) { *out = KiqStampInfo{}; out->lastPropMs = 0xFFFFFFFFu; } return 0; }
uint32_t hw_hook_kiq_chan_state(KiqStampInfo *out) { if (out) { *out = KiqStampInfo{}; out->lastPropMs = 0xFFFFFFFFu; } return 0; }
uint32_t hw_hook_gfx_map(GfxMapInfo *out) { if (out) *out = GfxMapInfo{}; return 0; }
uint32_t hw_hook_gfx_state(GfxMapInfo *out) { if (out) *out = GfxMapInfo{}; return 0; }
uint32_t hw_hook_sdma_map(SdmaMapInfo *out) { if (out) *out = SdmaMapInfo{}; return 0; }
uint32_t hw_hook_sdma_state(SdmaMapInfo *out) { if (out) *out = SdmaMapInfo{}; return 0; }
uint32_t hw_hook_vm_fault_clear() { return 0; }
uint32_t hw_hook_vm_arena_state() { return 0; }
uint32_t hw_hook_vm_ib_dump(uint64_t, uint64_t *outPhys, uint32_t *outFirstDword, uint32_t *outCpStat) {
    if (outPhys) *outPhys = 0;
    if (outFirstDword) *outFirstDword = 0;
    if (outCpStat) *outCpStat = 0;
    return 0;
}
uint32_t hw_hook_vm_page_scan(uint64_t, uint64_t *out, unsigned count) {
    aro_zero(out, count, 13);
    if (out && count > 7) out[7] = 0xffffffffu;
    return 0;
}
uint32_t hw_hook_vm_root_dump(uint64_t, uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t hw_hook_ring_map(uint64_t, uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t hw_hook_vm_context_observe(uint64_t, uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t hw_hook_rearm_after_drain(uint64_t, uint64_t *out, unsigned count) {
    aro_zero(out, count, 13);
    if (out && count > 1) out[1] = 1;   // no VM-context record
    return 0;
}
uint32_t hw_hook_root_write(uint64_t, uint64_t *out, unsigned count) {
    aro_zero(out, count, 13);
    if (out && count > 1) out[1] = 0xFF;
    return 0;
}
uint32_t hw_hook_render_xlat(uint64_t arg, uint64_t *out, uint32_t nOut) {
    aro_zero(out, nOut, 13);
    if (out && nOut > 1) out[1] = arg & 0xFFu;
    return 0;
}
// gHardware is null (it is set only when Apple's accelerator calls Navi48Ttl::initialize): each of these returns 0.
uint32_t hw_hook_set_virtual_space() { return 0; }
uint32_t hw_hook_kiq_enable() { return 0; }
uint32_t hw_hook_pm4_power_up() { return 0; }
uint32_t hw_hook_resume_scheduler() { return 0; }
uint32_t hw_hook_run_advance() { return 0; }
uint32_t hw_hook_run_checktimestamps() { return 0; }
uint32_t hw_hook_signal_stamp() { return 0; }
uint32_t hw_hook_sched_state() { return 0; }
uint32_t hw_hook_bind_channel() { return 0; }
uint32_t hw_hook_signal_completion() { return 0; }
uint32_t hw_hook_stamp_gap() { return 0; }
uint32_t hw_hook_stamp_state() { return 0; }

// ===================================================================================================================
// Fire-gated verbs: unreachable (accelExperimentFired is never set without the TTL hook).
// ===================================================================================================================
uint32_t hw_hook_sync_apple_gart() { return 0; }
bool hw_hook_enable_vram_allocations() { return false; }
bool hw_hook_set_virtual_space_ready(bool) { return false; }
bool hw_hook_enable_memory_allocations(bool) { return false; }
uint32_t hw_hook_enable_sdma_rings() { return 0; }
uint32_t hw_hook_start_hw_engines() { return 0; }
uint32_t hw_hook_report_ring_state() { return 0; }
uint32_t hw_hook_dump_rings() { return 0; }
uint32_t hw_hook_program_apple_queue(bool) { return 0; }
uint32_t hw_hook_install_ring_hooks() { return 0; }
uint32_t hw_hook_dump_indirect_buffers() { return 0; }
uint32_t hw_hook_rebase_ib_fills() { return 0; }
uint32_t hw_hook_kick_apple_queue() { return 0; }
uint32_t hw_hook_dump_ring_refs() { return 0; }
uint32_t hw_hook_open_cond_exec_gate() { return 0; }
uint32_t hw_hook_neuter_register_polls() { return 0; }
uint32_t hw_hook_dump_channel_completion() { return 0; }
uint32_t hw_hook_poke_completion() { return 0; }
uint32_t hw_hook_translate_gcvm_regs() { return 0; }
uint32_t hw_hook_ring_ib_dump(uint64_t) { return 0; }
uint32_t hw_hook_blit_flush_drop(uint64_t *, uint32_t) { return 0; }

// The TTL redirect needs Apple's HWServices, which never appears: the same answer as the real search running out.
TtlHookResult install_ttl_hook(IOService *, Navi48Ttl *) {
    TtlHookResult r;
    r.why = "HWServices never appeared under the PCI nub";
    return r;
}

} // namespace n48

// ===================================================================================================================
// apple/Navi48AccelPeer.cpp symbols: no accelerator object, no residency copy, nothing armed.
// ===================================================================================================================
void navi48_cg_close_scope(int32_t slot, uint64_t lo, uint64_t hi, bool wrote, bool failed, bool mismatch) {
    // must still close the copy-guard slot (navi48_cg_close is native), exactly as the real scope close does with
    // switches 82 and 84 OFF and no residency copy to account
    const uint32_t sampled = navi48_fc_scope_closed(lo, hi);
    navi48_cg_close(slot, lo, hi, n48_fc_cg_close_wrote(wrote ? 1u : 0u, failed ? 1u : 0u, mismatch ? 1u : 0u, sampled) != 0u,
                    failed, mismatch);
}
uint32_t navi48_ic_bumped_mine(void) { return 0; }
void navi48_ic_chunk_dead(uint64_t, uint64_t, uint64_t) {}
uint64_t navi48_peer_copy_seq(void) { return 0; }
uint32_t navi48_d84_programs_in(void *, const uint8_t *, uint64_t, uint64_t, uint64_t) { return 0; }
void *navi48_accel_object(void) { return nullptr; }
void **navi48_accel_vtable_copy(void) { return nullptr; }
uintptr_t navi48_x6000_slide(uint32_t *reason) { if (reason) *reason = 1; return 0; }
uint32_t navi48_ctx2d_calls(uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t navi48_ctx2d_control(uint64_t, uint64_t *out, unsigned count) { aro_zero(out, count, 7); return 0; }
uint32_t navi48_pairing_control(uint64_t arg, uint64_t *out, unsigned count) {
    const uint32_t verdict = n48_pairing_verb_verdict(arg, 0, 0, 0);
    uint32_t bootArg = 0;
    const bool present = PE_parse_boot_argn("navi48-display-pairing", &bootArg, sizeof(bootArg));
    const uint64_t v[10] = { verdict, 0, present ? 1u : 0u, present ? bootArg : 0u, 0, 0, 0, 0, 0, 0 };
    if (out) for (unsigned i = 0; i < count && i < 10; i++) out[i] = v[i];
    return verdict;
}
uint32_t navi48_ucprobe_control(uint64_t arg, uint64_t *out, unsigned count) {
    const uint32_t st = arg > 2 ? 5u : (arg == 1 ? 1u : 0u);
    aro_zero(out, count, 13);
    if (out && count > 0) out[0] = st;
    if (out && count > 10) out[10] = 0xFFull << 40;   // gRnLastKind's default 0xffffffff, as the real report packs it
    return st;
}
uint32_t navi48_flushhook_control(uint64_t arg, uint64_t *out, unsigned count) {
    const uint32_t st = arg > 4 ? 5u : ((arg == 1 || arg == 3) ? 1u : 0u);
    aro_zero(out, count, 13);
    if (out && count > 0) out[0] = st;
    return st;
}
uint32_t navi48_kernelsub_control(uint32_t, uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t navi48_pagecopy_control2(uint32_t, uint64_t *out, unsigned count) { aro_zero(out, count, 13); return 0; }
uint32_t navi48_shadercache_control(uint32_t mode, uint64_t *out, unsigned count) {
    aro_zero(out, count, 13);
    if (mode == 1) AROLOG("shadercache: not built (Apple route); navi48-shader-cache ignored");
    return 0;
}

#endif /* !N4X_APPLE_ROUTE */
