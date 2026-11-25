// 0.0.682 host test: the guarded interrupt mode (amd/ih_storm_pure.h): the boot-arg mapping, the storm guard window, the IH v7 overflow resync,
// the trip mask, the EOP-wake condition; register fields against Linux v7.3 (osssys_7_0_0_sh_mask.h), and source pins on the kernel glue.
// Build: clang++ -std=c++17 -I src tests/ih_storm682_test.cpp -o /tmp/ih682 ; run: /tmp/ih682 <kernel source dir> <linux drivers/gpu/drm/amd>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include <regex>
#include "amd/ih_storm_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static long define_of(const std::string &t, const std::string &name) {
    std::smatch m; std::regex r("#define " + name + "\\s+(0x[0-9A-Fa-f]+|[0-9]+)L?\\b");
    return std::regex_search(t, m, r) ? std::stol(m[1].str(), nullptr, 0) : -1;
}
using namespace n48ih;

static void test_mode() {
    expect(mode_of(false, 0) == kMsi, "absent -> 1 (the 0.0.35 default, unchanged)");
    expect(mode_of(true, 0) == kPolled, "0 -> polled (the production boot-args)");
    expect(mode_of(true, 1) == kMsi && mode_of(true, 3) == kMsi && mode_of(true, 0xFFFFFFFFu) == kMsi, "1 and any other non-zero but 2 -> the plain MSI path, as before");
    expect(mode_of(true, 2) == kMsiGuarded && guarded(kMsiGuarded) && !guarded(kMsi) && !guarded(kPolled), "2 -> guarded; only 2 is guarded");
    expect(wants_msi(kMsi) && wants_msi(kMsiGuarded) && !wants_msi(kPolled), "MSI armed for 1 and 2 only");
}

static void test_storm() {
    Storm s{};
    const uint64_t t0 = 5000000000ull;
    bool kept = true;
    for (uint32_t i = 0; i < kStormMaxIrqs; i++) kept = kept && storm_note(s, t0 + i * 10ull, 1, 0) == kKeep;   // 50000 runs in 0.5 ms: kept
    expect(kept, "every one of the first 50000 runs is kept");
    expect(s.trip == kTripNone && s.irqs == kStormMaxIrqs, "exactly 50000 interrupts in the window do not trip");
    expect(storm_note(s, t0 + 600000000ull, 1, 0) == kTripNow && s.trip == kTripIrqs, "the 50001st inside the window trips (Vermilion: ++cnt > 50000)");
    expect(storm_note(s, t0 + 700000000ull, 1, 0) == kAlreadyTripped && storm_note(s, t0 + 9000000000ull, 0, 0) == kAlreadyTripped, "the trip is sticky (once per boot)");

    Storm w{};
    for (uint32_t i = 0; i < 49000; i++) (void)storm_note(w, t0 + i, 1, 0);
    expect(storm_note(w, t0 + kStormWindowNs, 1, 0) == kKeep && w.irqs == 1u, "a new window starts after 1 s: the count restarts");
    for (int sec = 0; sec < 30; sec++) for (uint32_t i = 0; i < 40000; i++) (void)storm_note(w, t0 + (uint64_t)(sec + 2) * kStormWindowNs + i * 20000ull, 1, 0);
    expect(w.trip == kTripNone, "40000 interrupts per second for 30 s never trips");

    Storm e{};
    expect(storm_note(e, t0, 150000, 0) == kKeep && storm_note(e, t0 + 1, 50000, 0) == kKeep, "200000 entries in a window do not trip");
    expect(storm_note(e, t0 + 2, 1, 0) == kTripNow && e.trip == kTripEntries, "200001 entries trip (one MSI can cover a whole ring)");

    Storm o{};
    expect(storm_note(o, t0, 10, 3) == kKeep && storm_note(o, t0 + 900000000ull, 10, 1) == kTripNow && o.trip == kTripOverflows, "4 overflows inside one window trip");
    Storm o2{};
    expect(storm_note(o2, t0, 10, 3) == kKeep && storm_note(o2, t0 + kStormWindowNs, 10, 3) == kKeep && o2.trip == kTripNone, "3 overflows per window never trip");

    Storm z{};
    (void)storm_note(z, t0, 0, 0); (void)storm_note(z, t0 + 1, 0, 0);
    expect(z.emptyRuns == 2u && z.trip == kTripNone, "empty runs are counted, not a storm by themselves below the limit");
    Storm b{};
    expect(storm_note(b, 0, 1, 0) == kKeep && b.winStartNs != 0, "a clock of 0 still opens a window");
    Storm back{};
    (void)storm_note(back, t0, 1, 0);
    expect(storm_note(back, t0 - 5, 1, 0) == kKeep && back.irqs == 1u, "a clock that goes back restarts the window instead of underflowing");
    Storm sat{};
    expect(storm_note(sat, t0, 0xFFFFFFF0u, 0) == kTripNow && sat.entries == 0xFFFFFFF0u, "the entry count saturates");
    expect(std::string(trip_name(kTripIrqs)).find("50000") != std::string::npos && std::string(trip_name(kTripNone)) == "none", "trip names");

    Census c{};
    for (int i = 0; i < 5; i++) census_note(c, 0x14, 0xB5);
    census_note(c, 0x0A, 0x31);
    expect(c.key[0] == 0x14B5 && c.cnt[0] == 5 && c.key[1] == 0x0A31 && c.cnt[1] == 1, "the census keys client:src");
    for (int k = 0; k < 20; k++) census_note(c, 0x01, (uint8_t)k);
    expect(c.other == 6u, "past 16 keys the rest is counted as other");
}

static void test_overflow() {
    const uint32_t mask = 256u * 1024u - 1u;
    expect(rptr_after_overflow(0x00001001u, mask) == 0x1020u, "Linux: (wptr + 32) & mask with RB_OVERFLOW cleared");
    expect(rptr_after_overflow(0x0003FFE1u, mask) == 0u, "the resync wraps at the end of the ring");
    expect(rptr_after_overflow(0x00001011u, mask) == 0x1020u, "a damaged (misaligned) wptr is aligned down to its vector first");
    expect(wptr_overflowed(1u) && !wptr_overflowed(0x1000u), "RB_OVERFLOW is bit 0");
    expect(wptr_usable(0x00041020u, mask) == 0x1020u && wptr_usable(0x1031u, mask) == 0x1020u, "usable wptr: masked and aligned");
    for (uint32_t w = 0; w <= mask; w += 4) { if ((rptr_after_overflow(w | 1u, mask) & 31u) != 0u) { expect(false, "rptr after overflow always on a vector"); break; } }
    expect(cntl_after_trip(0xA0310121u | kCntlEnableIntr) == (0xA0310121u & ~kCntlRptrRearm & ~kCntlEnableIntr) &&
           (cntl_after_trip(0xFFFFFFFFu) & 0x00010101u) == 0x00010101u, "the trip clears ENABLE_INTR and RPTR_REARM only (RB_ENABLE, WPTR_WRITEBACK, WPTR_OVERFLOW_ENABLE kept)");
    expect(eop_wake_on(kMsiGuarded, true, true, false), "EOP wake: mode 2, armed, delivering, not tripped");
    expect(!eop_wake_on(kMsi, true, true, false) && !eop_wake_on(kMsiGuarded, false, true, false) && !eop_wake_on(kMsiGuarded, true, false, false) &&
           !eop_wake_on(kMsiGuarded, true, true, true), "EOP wake off for mode 1, unarmed, polled ring or after a trip");
    expect(seq_int_sel(true) == 2u && seq_int_sel(false) == 0u, "INT_SEL 2 only with the EOP wake");
}

static void test_linux(const std::string &linuxAmd) {
    const std::string m = slurp(linuxAmd + "/include/asic_reg/oss/osssys_7_0_0_sh_mask.h");
    expect(!m.empty(), "osssys_7_0_0_sh_mask.h readable");
    expect(define_of(m, "IH_RB_WPTR__RB_OVERFLOW_MASK") == (long)kWptrOverflow, "RB_OVERFLOW mask = Linux");
    expect(define_of(m, "IH_RB_CNTL__ENABLE_INTR_MASK") == (long)kCntlEnableIntr, "ENABLE_INTR mask = Linux");
    expect(define_of(m, "IH_RB_CNTL__RPTR_REARM_MASK") == (long)kCntlRptrRearm, "RPTR_REARM mask = Linux");
    const std::string ih = slurp(linuxAmd + "/amdgpu/ih_v7_0.c");
    expect(ih.find("tmp = (wptr + 32) & ih->ptr_mask;") != std::string::npos, "Linux ih_v7_0_get_wptr resync is (wptr + 32) & ptr_mask");
    const std::string pm4 = slurp(linuxAmd + "/amdgpu/gfx_v12_0.c");
    expect(pm4.find("PACKET3_RELEASE_MEM_INT_SEL(int_sel ? 2 : 0)") != std::string::npos, "Linux gfx_v12_0_ring_emit_fence uses INT_SEL 2 for an interrupt");
}

static void test_pins(const std::string &src) {
    const std::string b = slurp(src + "/src/Navi48Bringup.cpp"), ih = slurp(src + "/src/amd/ih_v7_0.cpp"), s1c = slurp(src + "/src/amd/native_s1c.cpp"),
                      pure = slurp(src + "/src/amd/native_s1c_pure.h");
    expect(b.find("irqMode = n48ih::mode_of(irqArg, wantIrq);") != std::string::npos, "the kext maps the boot-arg through mode_of");
    expect(b.find("if (wantIrq != 0) gBringup.wantInterrupts = armInterrupts();") != std::string::npos, "arming is unchanged (mode 0 never arms)");
    expect(b.find("if (n48ih::guarded(irqMode)) {\n\t\tif (sawEop) amdgpu::n1c_eop_signal();") != std::string::npos, "the EOP signal and the guard run in mode 2 only");
    expect(b.find("n48ih::storm_note(irqStorm, nowNs, total, dOv) == n48ih::kTripNow) stormTrip();") != std::string::npos, "the handler feeds the guard");
    expect(b.find("amdgpu::ih_cpu_intr_off(dev, gBringup.ih);") != std::string::npos && b.find("if (intSource) intSource->disable();") != std::string::npos,
           "the trip clears ENABLE_INTR and disables the source");
    expect(ih.find("WREG32(dev, reg, n48ih::cntl_after_trip(before));") != std::string::npos, "ih_cpu_intr_off writes cntl_after_trip");
    expect(ih.find("n48ih::rptr_after_overflow(wptr, ih.ptr_mask)") != std::string::npos && ih.find("(wptr + 32) & ih.ptr_mask") == std::string::npos,
           "ih_get_wptr resyncs through the tested function");
    expect(ih.find("cntl |= (1u << kIH_RB_CNTL__WPTR_OVERFLOW_CLEAR__SHIFT);\n    WREG32(dev, cntl_reg, cntl);") != std::string::npos &&
           ih.find("cntl &= ~(1u << kIH_RB_CNTL__WPTR_OVERFLOW_CLEAR__SHIFT);\n    WREG32(dev, cntl_reg, cntl);") != std::string::npos, "the WPTR_OVERFLOW_CLEAR pulse is kept");
    expect(s1c.find("static inline uint32_t seq_int_sel() { return eop_wake_now() ? kPM4RMIntSelSendInt : kPM4RMIntSelNone; }") != std::string::npos,
           "the seqno asks for an interrupt only with the EOP wake on");
    expect(pure.find("k += emit_release_mem(o + k, seqAddr, seq, seqIntSel);") != std::string::npos && pure.find("if (hasFence) k += emit_release_mem(o + k, fenceAddr, seq);") != std::string::npos,
           "only the kernel seqno RELEASE_MEM may carry INT_SEL; the user fence never does");
}

int main(int argc, char **argv) {
    test_mode(); test_storm(); test_overflow();
    if (argc > 2) test_linux(argv[2]);
    if (argc > 1) test_pins(argv[1]);
    printf("%s: %d checks, %d failures\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
