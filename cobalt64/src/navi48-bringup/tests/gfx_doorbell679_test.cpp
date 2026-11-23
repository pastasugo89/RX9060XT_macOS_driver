// 0.0.679 host test: the kernel GFX queue's doorbell moves to Linux's index by default (amd/cp_doorbell_pure.h), and the ComputeDispatch doorbell
// probe separates the doorbell from the IB in the boot marks. Why (0.0.678 boot marks, 2026-11-23): idle after PM4Test, busy for good from the
// first step of ComputeDispatch (its IB test). PM4Test rings the GFX doorbell only BEFORE it maps the kernel compute queue; the IB test's kick
// is the first GFX doorbell after a compute HQD is active, and the old doorbell (byte 0x22C) lies in the MEC doorbell window.
// Build: clang++ -std=c++17 -I src tests/gfx_doorbell679_test.cpp ; run: ./a.out <kernel source dir>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include "amd/cp_doorbell_pure.h"
#include "amd/cp_census_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }

using namespace n48db;

static void test_pure() {
    const uint32_t gfxLo = window_reg(0x8B), gfxHi = window_reg(0xFF), mecLo = window_reg(0x00), mecHi = window_reg(0x8A);
    expect(mode_of(false, 0) == kModeLinux, "default: Linux's index");
    expect(mode_of(true, 0) == kModeLegacy, "navi48-gfxdb=0: the kill switch");
    expect(mode_of(true, 1) == kModeLinux && mode_of(true, 2) == kModeLinux, "any other value: Linux's index");
    const uint32_t def = kgq_index(0x8B, mode_of(false, 0));
    expect(def == 0x116 && byte_offset(def) == 0x458 && where(def, gfxLo, gfxHi, mecLo, mecHi) == kInGfx && qword_aligned(def),
           "the default doorbell is byte 0x458: in the GFX window, outside the MEC window, qword-aligned");
    const uint32_t old = kgq_index(0x8B, mode_of(true, 0));
    expect(byte_offset(old) == 0x22C && where(old, gfxLo, gfxHi, mecLo, mecHi) == kInMec, "the kill switch's doorbell is byte 0x22C, in the MEC window");
    // The KCQ (mec_ring[0] = 3, byte 0xC) and the MES ring (0x0B, byte 0x2C) are in the MEC window and owned; the new GFX doorbell is not among them.
    expect(where(3, gfxLo, gfxHi, mecLo, mecHi) == kInMec && where(0x0B, gfxLo, gfxHi, mecLo, mecHi) == kInMec, "KCQ and MES doorbells in the MEC window");
    expect(std::string(mode_name(kModeLinux)).find("Linux qword index (gfx_ring0 << 1)") == 0, "the registry text keeps the 0.0.677 wording");
    expect(n48cpc::kMarkSamples == 16, "16 samples per mark");
}

static size_t count(const std::string &t, const std::string &n) { size_t c = 0; for (size_t p = t.find(n); p != std::string::npos; p = t.find(n, p + 1)) c++; return c; }

static void test_sources(const char *dir) {
    if (!dir) { printf("(source pins skipped)\n"); return; }
    const std::string root = dir;
    const std::string init = slurp(root + "/src/amd/amdgpu_init.cpp"), cp = slurp(root + "/src/amd/cp_v12_0.cpp"), cc = slurp(root + "/src/amd/cp_census.cpp");
    const std::string ct = slurp(root + "/src/amd/compute_test.cpp");
    expect(!init.empty() && !cp.empty() && !cc.empty() && !ct.empty(), "sources read");
    // PM4Test: every GFX doorbell (fetch probe, scratch, EOP, WRITE_DATA) comes before the KCQ is mapped - the reason PM4Test ends idle
    const size_t pm4 = init.find("case BringupStage::PM4Test: {"), kcq = init.find("r = cp_compute_queue_map_mes(dev, ctx.kcq, ctx.mes);", pm4);
    const size_t lastKick = init.rfind("cp_kick_doorbell(dev, ctx.cp)", kcq);
    expect(pm4 != std::string::npos && kcq != std::string::npos && lastKick > pm4 && lastKick < kcq, "PM4Test's GFX doorbells all precede the KCQ mapping");
    expect(count(init.substr(kcq, init.find("case BringupStage::ComputeDispatch: {") - kcq), "cp_kick_doorbell(dev, ctx.cp)") == 0, "no GFX doorbell after the KCQ in PM4Test");
    // ComputeDispatch: start mark, doorbell probe, probe mark, then the dispatch test (whose IB test kicks the doorbell again)
    const size_t cd = init.find("case BringupStage::ComputeDispatch: {");
    const size_t m0 = init.find("cp_busy_mark(dev, \"ComputeDispatch/start\");", cd), pr = init.find("cp_ring_fetch_probe(dev, ctx.cp, 16, 500000);", cd);
    const size_t m1 = init.find("cp_busy_mark(dev, \"ComputeDispatch/doorbell probe\");", cd), t = init.find("compute_dispatch_test(dev, ctx.gmc, ctx.cp,", cd);
    expect(cd < m0 && m0 < pr && pr < m1 && m1 < t, "ComputeDispatch: start mark -> doorbell probe -> mark -> IB test");
    expect(init.find("if (cp_busy_marks_on() && !ctx.cpLegacyRb) {", cd) < m0, "the probe runs only with the marks (navi48-cpmark) and the MES-mapped queue");
    expect(cc.find("bool cp_busy_marks_on() { return mark_enabled(); }") != std::string::npos, "cp_busy_marks_on");
    expect(ct.find("cp_busy_mark(dev, \"ComputeDispatch/IB test\");") != std::string::npos, "the 0.0.678 IB-test mark stays");
    expect(cp.find("gGfxDbMode = n48db::mode_of(present, v);") != std::string::npos, "the boot-arg goes through mode_of");
}

int main(int argc, char **argv) {
    test_pure();
    test_sources(argc > 1 ? argv[1] : nullptr);
    printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
