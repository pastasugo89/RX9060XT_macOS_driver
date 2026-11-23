// 0.0.677 host test: the boot-time CP busy marks / queue census tables (amd/cp_census_pure.h) against Linux gc_12_0_0_offset.h / gc_12_0_0_sh_mask.h,
// the counting, the switches, and source pins (the marks read only unbanked registers; the census is opt-in, restores select 0, never reads a
// *_HEADER_DUMP register; the KIQ A/B keeps Linux's write by default).
// Build: clang++ -std=c++17 -I src tests/cp_census677_test.cpp ; run: ./a.out <kernel source dir> <linux .../asic_reg/gc dir>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include <regex>
#include "amd/cp_census_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }

using namespace n48cpc;

static long define_of(const std::string &t, const std::string &name) {
    std::smatch m; std::regex r("#define " + name + "\\s+(0x[0-9A-Fa-f]+|[0-9]+)\\b");
    return std::regex_search(t, m, r) ? std::stol(m[1].str(), nullptr, 0) : -1;
}
static void check_reg(const std::string &off, const Reg &r) {
    expect(define_of(off, std::string("reg") + r.name) == (long)r.off, std::string("offset of ") + r.name);
    expect(define_of(off, std::string("reg") + r.name + "_BASE_IDX") == (long)r.idx, std::string("base idx of ") + r.name);
}

static void test_linux(const char *gcdir) {
    if (!gcdir) { printf("(Linux cross-check skipped)\n"); return; }
    const std::string off = slurp(std::string(gcdir) + "/gc_12_0_0_offset.h"), sh = slurp(std::string(gcdir) + "/gc_12_0_0_sh_mask.h");
    expect(!off.empty() && !sh.empty(), "Linux headers read");
    for (const Reg &r : kMark) check_reg(off, r);
    for (const Reg &r : kGfxHqd) check_reg(off, r);
    for (const Reg &r : kCmpHqd) check_reg(off, r);
    for (const Reg &r : kMesPipe) check_reg(off, r);
    expect(define_of(off, "regGRBM_GFX_CNTL") == 0x0900 && define_of(off, "regGRBM_GFX_CNTL_BASE_IDX") == 1, "GRBM_GFX_CNTL idx1 0x0900");
    for (const Bit &b : kBits) {
        const std::string reg = kMark[b.reg].name;
        expect(define_of(sh, reg + "__" + b.name + "__SHIFT") == (long)b.bit, reg + "." + b.name + " bit");
    }
    expect(define_of(sh, "GRBM_GFX_CNTL__PIPEID__SHIFT") == 0 && define_of(sh, "GRBM_GFX_CNTL__MEID__SHIFT") == 2 &&
           define_of(sh, "GRBM_GFX_CNTL__QUEUEID__SHIFT") == 8, "GRBM_GFX_CNTL fields");
}

static void test_pure() {
    expect(grbm_select(3, 1, 0) == 0xd && grbm_select(1, 0, 1) == 0x104 && grbm_select(0, 0, 0) == 0, "grbm_select encoding");
    Counts c{};
    uint32_t v[kMarkRegs] = {};
    v[kCpfStatus] = 0x88000001u; v[kGrbmStatus2] = 0x14100000u; v[kGrbmStatus] = 0xa800382cu;
    for (int i = 0; i < 4; i++) count_sample(c, v);
    v[kCpfStatus] = 0;
    count_sample(c, v);
    auto setOf = [&](const char *n) { for (uint32_t b = 0; b < kBitCount; b++) if (std::string(kBits[b].name) == n) return c.set[b]; return 999u; };
    expect(c.n == 5 && c.first[kCpfStatus] == 0x88000001u && c.last[kCpfStatus] == 0u, "first / last");
    expect(setOf("CPF_CMP_BUSY") == 4 && setOf("POST_WPTR_GFX_BUSY") == 4 && setOf("CPF_BUSY") == 5 && setOf("RLC_BUSY") == 5 && setOf("GUI_ACTIVE") == 5 &&
           setOf("CPC_BUSY") == 0 && setOf("MES_HQD_BUSY") == 0, "the live sample of 2026-11-17 decodes as reported (CPF_CMP_BUSY + POST_WPTR_GFX_BUSY)");
    expect(mark_on(false, 0) && mark_on(true, 1) && !mark_on(true, 0), "navi48-cpmark: on unless 0");
    expect(!census_on(false, 0) && census_on(true, 1) && !census_on(true, 0) && !census_on(true, 2), "navi48-cpcensus: opt-in");
    for (const Reg &r : kMark) expect(std::string(r.name).find("HEADER_DUMP") == std::string::npos, "no HEADER_DUMP in the marks");
    for (const Reg &r : kCmpHqd) expect(std::string(r.name).find("HEADER_DUMP") == std::string::npos, "no HEADER_DUMP in the census");
    for (const Reg &r : kMesPipe) expect(std::string(r.name).find("HEADER_DUMP") == std::string::npos, "no HEADER_DUMP in the census");
}

static void test_sources(const char *dir) {
    if (!dir) { printf("(source pins skipped)\n"); return; }
    const std::string root = dir;
    const std::string cc = slurp(root + "/src/amd/cp_census.cpp"), init = slurp(root + "/src/amd/amdgpu_init.cpp"), br = slurp(root + "/src/Navi48Bringup.cpp");
    const std::string mes = slurp(root + "/src/amd/mes_v12_1.cpp");
    expect(!cc.empty() && !init.empty() && !br.empty() && !mes.empty(), "sources read");
    // the marks: reads only (the only WREG32 in the file are the census's select writes and its restore)
    const size_t census = cc.find("void cp_queue_census(");
    expect(census != std::string::npos && cc.find("WREG32(") > census, "no register write before cp_queue_census (the marks only read)");
    expect(cc.find("if (!census_on(p, v) || !dev.ip.isResolved(IPBlock::GC)) return;") < cc.find("WREG32(", census), "the census writes nothing unless navi48-cpcensus=1");
    expect(cc.find("WREG32(dev, sel, 0u);") != std::string::npos, "the census restores select 0");
    expect(init.find("if (s >= (uint32_t)BringupStage::CPInit) cp_busy_mark(*ctx.dev, stage_name((BringupStage)s));") != std::string::npos, "a mark after every stage from CPInit");
    expect(br.find("amdgpu::cp_busy_mark(dev, \"end of runStages\");") != std::string::npos && br.find("setProperty(\"Navi48,CpBusyMarks\", m);") != std::string::npos,
           "the end mark and the registry property");
    expect(br.find("amdgpu::cp_busy_mark(dev, \"end of runStages\");") < br.find("nativeGate == n48native::kGateOn"), "before the native path and any client");
    expect(mes.find("if (PE_parse_boot_argn(\"navi48-kiqsched\", &ks, sizeof(ks)) && ks == 0) {") != std::string::npos &&
           mes.find("mes_kiq_setting(dev, /*me=*/3, /*pipe=*/1, /*queue=*/0);\n        }") != std::string::npos, "the KIQ scheduler write stays the default; navi48-kiqsched=0 skips it");
}

int main(int argc, char **argv) {
    test_pure();
    test_sources(argc > 1 ? argv[1] : nullptr);
    test_linux(argc > 2 ? argv[2] : nullptr);
    printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
