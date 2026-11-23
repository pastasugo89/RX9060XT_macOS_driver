// 0.0.678 host test: the ComputeDispatch fix (amd/compute_cdfix_pure.h). The GFX12 compute preamble's registers against Linux
// gc_12_0_0_offset.h / gc_12_0_0_sh_mask.h, its values against Mesa (ac_cmdbuf.c gfx12_init_compute_preamble_state, radv_queue.c), the exact
// packet stream, the refusals, the boot-arg, and source pins on the kernel glue (preamble in both IB builders, readback only on failure,
// the sub-marks, the S1b buffer, the registry property).
// Build: clang++ -std=c++17 -I src tests/compute_cdfix678_test.cpp ; run: ./a.out <kernel source dir> <linux drivers/gpu/drm/amd> <mesa src/amd>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include <regex>
#include <vector>
#include "amd/compute_cdfix_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static long define_of(const std::string &t, const std::string &name) {
    std::smatch m; std::regex r("#define " + name + "\\s+(0x[0-9A-Fa-f]+|[0-9]+)L?\\b");
    return std::regex_search(t, m, r) ? std::stol(m[1].str(), nullptr, 0) : -1;
}
static size_t count_of(const std::string &t, const std::string &needle) {
    size_t n = 0; for (size_t p = t.find(needle); p != std::string::npos; p = t.find(needle, p + 1)) n++; return n;
}

using namespace n48cdfix;

static void test_pure() {
    expect(fix_on(false, 0) && fix_on(true, 1) && fix_on(true, 2) && !fix_on(true, 0), "navi48-cdfix: on unless 0");
    expect(se_mask(0, 2) == 0xFFFFFFFFu && se_mask(1, 2) == 0xFFFFFFFFu && se_mask(2, 2) == 0 && se_mask(3, 2) == 0 && se_mask(3, 4) == 0xFFFFFFFFu,
           "CU masks only for the SEs that exist (Mesa i < max_se)");
    expect(num_se_of(true, 2, 4) == 2 && num_se_of(false, 2, 2) == 2 && num_se_of(true, 0, 2) == 2 && num_se_of(true, 9, 2) == 2 && num_se_of(false, 0, 0) == 1,
           "SE count: discovery when valid, else the profile, never 0");
    uint32_t dw = 0;
    for (uint32_t r = 0; r < kRowCount; r++) dw += 2 + kRows[r].n;
    expect(dw == kPreambleDwords && kPreambleDwords == 33, "33 preamble dwords");
    // The exact stream for GC[0] = 0x1260, two SEs.
    std::vector<uint32_t> p(64, 0xEEEEEEEEu);
    const uint32_t end = emit_preamble(p.data(), 3, 64, 0x1260, 2);
    expect(end == 36, "the preamble is appended at `at`");
    const uint32_t want[] = {
        0xC0037602u, 0x1260u + 0x1ba4u - 0x2C00u, 0, 0, 0,                      // START_X/Y/Z
        0xC0017602u, 0x1260u + 0x1babu - 0x2C00u, 0,                            // PERFCOUNT_ENABLE
        0xC0027602u, 0x1260u + 0x1baeu - 0x2C00u, 0, 0,                         // DISPATCH_PKT_ADDR_LO/HI
        0xC0017602u, 0x1260u + 0x1bc3u - 0x2C00u, 0,                            // SE8
        0xC0047602u, 0x1260u + 0x1bc4u - 0x2C00u, 0, 0, 0, 0,                   // USER_ACCUM_0..3
        0xC0047602u, 0x1260u + 0x1bcbu - 0x2C00u, 0, 0, 0, 0,                   // SE4..7 (two-SE part)
        0xC0017602u, 0x1260u + 0x1c1du - 0x2C00u, 0,                            // DISPATCH_TUNNEL
        0xC0019B02u, (0x1260u + 0x1bcfu - 0x2C00u) | (2u << 28), 64,            // DISPATCH_INTERLEAVE, SET_SH_REG_INDEX index 2
    };
    bool same = true;
    for (uint32_t i = 0; i < 33; i++) same = same && p[3 + i] == want[i];
    expect(same, "the preamble dwords are exactly the expected packets");
    expect(p[2] == 0xEEEEEEEEu && p[36] == 0xEEEEEEEEu, "nothing written outside [at, end)");
    expect(want[1] == 0x20cu - 0x8u && (0x1260u + 0x1bacu - 0x2C00u) == 0x20cu, "SET_SH_REG index matches the 0.0.677 log (COMPUTE_PGM_LO sh_idx 0x20c)");
    std::vector<uint32_t> q(64, 0);
    expect(emit_preamble(q.data(), 0, 32, 0x1260, 2) == 0 && emit_preamble(q.data(), 32, 64, 0x1260, 2) == 0, "refused when it does not fit");
    expect(emit_preamble(q.data(), 0, 64, 0x0, 2) == 0, "refused when a register index would underflow SET_SH_REG_START");
    expect(emit_preamble(nullptr, 0, 64, 0x1260, 2) == 0, "refused without a buffer");
    std::vector<uint32_t> f(64, 0);
    emit_preamble(f.data(), 0, 64, 0x1260, 8);
    expect(f[23] == 0xFFFFFFFFu && f[26] == 0xFFFFFFFFu && f[14] == 0u, "eight SEs: SE4..7 all CUs, SE8 still 0");
    expect(value_of(COMPUTE_DISPATCH_INTERLEAVE, 2) == 64 && value_of(COMPUTE_DISPATCH_TUNNEL, 2) == 0 && value_of(COMPUTE_PERFCOUNT_ENABLE, 2) == 0,
           "INTERLEAVE 64 (a valid value), TUNNEL 0, PERFCOUNT off");
    expect(type3_cs(0x76, 2) == 0xC0027602u, "compute-typed SET_SH_REG header (as the 0.0.677 log: c0027602)");
}

static void test_linux(const char *amd) {
    if (!amd) { printf("(Linux cross-check skipped)\n"); return; }
    const std::string off = slurp(std::string(amd) + "/include/asic_reg/gc/gc_12_0_0_offset.h");
    const std::string sh = slurp(std::string(amd) + "/include/asic_reg/gc/gc_12_0_0_sh_mask.h");
    expect(!off.empty() && !sh.empty(), "Linux gc 12.0.0 headers read");
    struct N { const char *name; uint32_t off; } regs[] = {
        { "COMPUTE_START_X", COMPUTE_START_X }, { "COMPUTE_START_Y", COMPUTE_START_Y }, { "COMPUTE_START_Z", COMPUTE_START_Z },
        { "COMPUTE_PERFCOUNT_ENABLE", COMPUTE_PERFCOUNT_ENABLE }, { "COMPUTE_DISPATCH_PKT_ADDR_LO", COMPUTE_DISPATCH_PKT_ADDR_LO },
        { "COMPUTE_DISPATCH_PKT_ADDR_HI", COMPUTE_DISPATCH_PKT_ADDR_HI }, { "COMPUTE_STATIC_THREAD_MGMT_SE0", COMPUTE_STATIC_THREAD_MGMT_SE0 },
        { "COMPUTE_STATIC_THREAD_MGMT_SE1", COMPUTE_STATIC_THREAD_MGMT_SE1 }, { "COMPUTE_STATIC_THREAD_MGMT_SE2", COMPUTE_STATIC_THREAD_MGMT_SE2 },
        { "COMPUTE_STATIC_THREAD_MGMT_SE3", COMPUTE_STATIC_THREAD_MGMT_SE3 }, { "COMPUTE_STATIC_THREAD_MGMT_SE8", COMPUTE_STATIC_THREAD_MGMT_SE8 },
        { "COMPUTE_USER_ACCUM_0", COMPUTE_USER_ACCUM_0 }, { "COMPUTE_USER_ACCUM_1", COMPUTE_USER_ACCUM_0 + 1 }, { "COMPUTE_USER_ACCUM_2", COMPUTE_USER_ACCUM_0 + 2 },
        { "COMPUTE_USER_ACCUM_3", COMPUTE_USER_ACCUM_0 + 3 }, { "COMPUTE_STATIC_THREAD_MGMT_SE4", COMPUTE_STATIC_THREAD_MGMT_SE4 },
        { "COMPUTE_STATIC_THREAD_MGMT_SE5", COMPUTE_STATIC_THREAD_MGMT_SE4 + 1 }, { "COMPUTE_STATIC_THREAD_MGMT_SE6", COMPUTE_STATIC_THREAD_MGMT_SE4 + 2 },
        { "COMPUTE_STATIC_THREAD_MGMT_SE7", COMPUTE_STATIC_THREAD_MGMT_SE4 + 3 }, { "COMPUTE_DISPATCH_INTERLEAVE", COMPUTE_DISPATCH_INTERLEAVE },
        { "COMPUTE_DISPATCH_TUNNEL", COMPUTE_DISPATCH_TUNNEL },
    };
    for (const N &r : regs) {
        expect(define_of(off, std::string("reg") + r.name) == (long)r.off, std::string("offset of ") + r.name);
        expect(define_of(off, std::string("reg") + r.name + "_BASE_IDX") == 0, std::string("BASE_IDX 0 of ") + r.name);
    }
    // every multi-register row is a real run of consecutive registers
    expect(define_of(off, "regCOMPUTE_PGM_LO") == 0x1bac, "COMPUTE_PGM_LO 0x1bac (the sh_idx check above)");
    expect(define_of(sh, "COMPUTE_DISPATCH_INTERLEAVE__INTERLEAVE_1D__SHIFT") == 0 && define_of(sh, "COMPUTE_DISPATCH_INTERLEAVE__INTERLEAVE_1D_MASK") == 0x3FF,
           "INTERLEAVE_1D is [9:0]");
    expect(define_of(sh, "COMPUTE_DISPATCH_TUNNEL__OFF_DELAY_MASK") == 0x1FFF, "DISPATCH_TUNNEL OFF_DELAY [12:0]");
    expect(define_of(sh, "COMPUTE_PERFCOUNT_ENABLE__PERFCOUNT_ENABLE_MASK") == 1, "PERFCOUNT_ENABLE bit 0");
}

static void test_mesa(const char *mesa) {
    if (!mesa) { printf("(Mesa cross-check skipped)\n"); return; }
    const std::string cmd = slurp(std::string(mesa) + "/common/ac_cmdbuf.c"), q = slurp(std::string(mesa) + "/vulkan/radv_queue.c");
    expect(!cmd.empty() && !q.empty(), "Mesa sources read");
    const size_t a = cmd.find("gfx12_init_compute_preamble_state(const struct ac_preamble_state *state,"), b = cmd.find("cdna_init_compute_preamble_state(const");
    expect(a != std::string::npos && b != std::string::npos && b > a, "Mesa gfx12_init_compute_preamble_state found");
    const std::string g12 = cmd.substr(a, b - a);
    for (const char *r : { "R_00B82C_COMPUTE_PERFCOUNT_ENABLE, 0", "R_00B838_COMPUTE_DISPATCH_PKT_ADDR_LO, 0", "R_00B83C_COMPUTE_DISPATCH_PKT_ADDR_HI, 0",
                           "R_00B890_COMPUTE_USER_ACCUM_0, 0", "R_00B89C_COMPUTE_USER_ACCUM_3, 0", "R_00B9F4_COMPUTE_DISPATCH_TUNNEL, 0",
                           "R_00B88C_COMPUTE_STATIC_THREAD_MGMT_SE8, num_se > 8 ? compute_cu_en : 0",
                           "R_00B8AC_COMPUTE_STATIC_THREAD_MGMT_SE4, num_se > 4 ? compute_cu_en : 0",
                           "R_00B868_COMPUTE_STATIC_THREAD_MGMT_SE3, num_se > 3 ? compute_cu_en : 0" })
        expect(g12.find(r) != std::string::npos, std::string("Mesa GFX12 preamble writes ") + r);
    expect(q.find(".compute_dispatch_interleave = 64") != std::string::npos, "RADV interleave 64");
    expect(q.find("ac_pm4_set_reg_custom(pm4, R_00B8BC_COMPUTE_DISPATCH_INTERLEAVE - SI_SH_REG_OFFSET,") != std::string::npos &&
           q.find("PKT3_SET_SH_REG_INDEX, 2);") != std::string::npos, "RADV: DISPATCH_INTERLEAVE on the gfx queue via SET_SH_REG_INDEX index 2");
    expect(q.find("ac_pm4_set_reg(pm4, R_00B810_COMPUTE_START_X, 0);") != std::string::npos, "RADV: COMPUTE_START_X = 0");
    // Mesa's SH offsets map onto ours: (R_00Bxxx - 0xB000) / 4 + 0x2C00 = absolute dword = GC[0] (0x1260) + off.
    expect((0xB82Cu - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_PERFCOUNT_ENABLE && (0xB9F4u - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_DISPATCH_TUNNEL &&
           (0xB8BCu - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_DISPATCH_INTERLEAVE && (0xB88Cu - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_STATIC_THREAD_MGMT_SE8 &&
           (0xB8ACu - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_STATIC_THREAD_MGMT_SE4 && (0xB810u - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_START_X &&
           (0xB838u - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_DISPATCH_PKT_ADDR_LO && (0xB890u - 0xB000u) / 4u + 0x2C00u == 0x1260u + COMPUTE_USER_ACCUM_0,
           "Mesa R_00Bxxx offsets equal ours at GC[0] = 0x1260");
}

static void test_sources(const char *dir) {
    if (!dir) { printf("(source pins skipped)\n"); return; }
    const std::string root = dir;
    const std::string ct = slurp(root + "/src/amd/compute_test.cpp"), s1b = slurp(root + "/src/amd/native_s1b.cpp"), init = slurp(root + "/src/amd/amdgpu_init.cpp");
    const std::string br = slurp(root + "/src/Navi48Bringup.cpp"), cc = slurp(root + "/src/amd/cp_census.cpp");
    expect(!ct.empty() && !s1b.empty() && !init.empty() && !br.empty() && !cc.empty(), "sources read");
    expect(ct.find("const bool present = PE_parse_boot_argn(\"navi48-cdfix\", &v, sizeof(v));") != std::string::npos &&
           ct.find("gCdfixOn = n48cdfix::fix_on(present, v) ? 1 : 0;") != std::string::npos, "navi48-cdfix read through fix_on");
    const size_t test = ct.find("compute_dispatch_test(DeviceContext &dev, GMCContext &gmc, CPContext &cp,"), builder = ct.find("uint32_t compute_build_va_dispatch_ib(");
    expect(test != std::string::npos && builder != std::string::npos && builder > test, "both IB builders found");
    const std::string tbody = ct.substr(test, builder - test), bbody = ct.substr(builder);
    expect(tbody.find("n = emit_cdfix_preamble(dev, pkt, n, 128, true);") < tbody.find("Reg::COMPUTE_PGM_LO, v, 2, names)"), "dispatch test: the preamble first");
    expect(bbody.find("n = emit_cdfix_preamble(dev, pkt, n, max_dw, false);") < bbody.find("Reg::COMPUTE_PGM_LO, v, 2, names)"), "S1b builder: the preamble first");
    expect(tbody.find("uint32_t pkt[128];") != std::string::npos, "the dispatch IB buffer has room (74 dwords used)");
    expect(count_of(ct, "{ cu_mask(dev, 0), cu_mask(dev, 1) }") == 2 && count_of(ct, "{ cu_mask(dev, 2), cu_mask(dev, 3) }") == 2 &&
           count_of(ct, "{ kAllCUsEnabled, kAllCUsEnabled }") == 0, "per-SE CU masks in both builders");
    expect(count_of(tbody, "dump_sh_readback(dev, \"before submit\");") == 1 && tbody.find("if (!compute_cdfix_on()) {   // 0.0.677 stream") < tbody.find("dump_sh_readback(dev, \"before submit\");"),
           "the readback before the dispatch only on the 0.0.677 stream");
    expect(tbody.find("if (!compute_cdfix_on() || !passed) dump_sh_readback(dev, \"after submit\");") != std::string::npos &&
           count_of(tbody, "dump_sh_readback(dev, \"after submit\");") == 1, "the readback after the dispatch only on the 0.0.677 stream or a failure");
    expect(tbody.find("cp_busy_mark(dev, \"ComputeDispatch/IB test\");") < tbody.find("cp_busy_mark(dev, \"ComputeDispatch/dispatch\");"), "sub-marks: IB test, then dispatch");
    expect(tbody.find("cp_busy_mark(dev, \"ComputeDispatch/SH readback\");") != std::string::npos, "sub-mark after the 0.0.677 readback");
    expect(bbody.find("const uint32_t need = compute_cdfix_on() ? 64u + n48cdfix::kPreambleDwords : 64u;") != std::string::npos, "the builder needs 97 dwords with the fix");
    expect(s1b.find("static uint32_t       sPkt[128];") != std::string::npos &&
           s1b.find("compute_build_va_dispatch_ib(dev, sPkt, (uint32_t)(sizeof(sPkt) / sizeof(sPkt[0])), codeVa, resVa)") != std::string::npos,
           "native S1b passes a 128-dword buffer");
    expect(init.find("INIT_LOG(\"ComputeDispatch: navi48-cdfix %s\"") < init.find("compute_dispatch_test(dev, ctx.gmc, ctx.cp, &ctx.computeResult, ctx.hsaAbi);"), "the stage logs the mode");
    expect(br.find("setProperty(\"Navi48,ComputeDispatchFix\", t);") != std::string::npos, "ioreg Navi48,ComputeDispatchFix");
    expect(cc.find("constexpr uint32_t kKeep = 16;") != std::string::npos, "room for the sub-marks in the registry");
}

int main(int argc, char **argv) {
    test_pure();
    test_sources(argc > 1 ? argv[1] : nullptr);
    test_linux(argc > 2 ? argv[2] : nullptr);
    test_mesa(argc > 3 ? argv[3] : nullptr);
    printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
