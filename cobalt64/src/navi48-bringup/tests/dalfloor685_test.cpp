// dalfloor685_test.cpp - build 0.0.685 (from dalfloor684_test.cpp): the display clock floors (DALSMC, as Linux dcn401 clk_mgr) and the boot clock trace
// (src/amd/clkfloor_pure.h; the kernel side is src/amd/clkfloor.cpp and the display monitor in src/dcn/navi48_dcn.cpp). Host test, no IOKit:
//   clang++ -std=c++17 -Wall -Wextra -Werror -I <tree>/src tests/dalfloor685_test.cpp -o /tmp/dalfloor685 && /tmp/dalfloor685 <tree> [<linux>/drivers/gpu/drm/amd]
// 0.0.685: the floors are OFF unless navi48-dalfloor opts in, need the live DISPCLK/DPPCLK they were computed for (272.7 MHz), a healthy SMU and a
// PPSMC readiness probe, run under the shared lock and probe the PPSMC mailbox afterwards (T3, T9); the trace never waits for the lock (T7).
//   (<tree> is the navi48-bringup directory or a candidate tree; the optional second argument is the Linux amd directory the constants are checked against.)
// Covers:
//   T1  the integer DML forms against the double expressions of dml2_core_dcn4_calcs.c / dml2_dpmm_dcn4.c (this mode exactly, and a sweep);
//   T2  this mode's values: deep sleep 33671 kHz -> 34 MHz, DISPCLK 253521 kHz, DPPCLK 250000 kHz, the DCFCLK need;
//   T3  the boot-arg navi48-dalfloor and navi48-clklog;
//   T4  the floor allowlist (everything else refused);
//   T5  the plan in Linux's order, the opt-in parts, the skips; disp_floor_mhz never lowers a running clock;
//   T6  the clock trace: moves, bursts and their classification (H1 / H2 / H3 / none), the ring;
//   T7  source pins of the kernel code; T8 (with the Linux tree) the Linux constants this file mirrors.
#include <cstdio>
#include <cstdint>
#include <cmath>
#include <cstdlib>
#include <string>
#include <fstream>
#include <sstream>
#include "amd/clkfloor_pure.h"

using namespace n48dalfloor;

static int gFail = 0, gRun = 0;
static void expect(bool ok, const char *what) { gRun++; if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }
static void expect_u(const char *what, uint64_t got, uint64_t want) {
    gRun++;
    if (got != want) { gFail++; std::printf("FAIL: %s: got %llu want %llu\n", what, (unsigned long long)got, (unsigned long long)want); }
}
static std::string slurp(const std::string &path) { std::ifstream f(path, std::ios::binary); std::stringstream ss; ss << f.rdbuf(); return ss.str(); }
static bool has(const std::string &s, const char *needle) { return s.find(needle) != std::string::npos; }
static std::string body(const std::string &src, const char *start) {
    const size_t p = src.find(start); if (p == std::string::npos) return std::string();
    const size_t e = src.find("\n}\n", p); return src.substr(p, e == std::string::npos ? std::string::npos : e - p);
}

bool in_order_ok(const std::string &s, std::initializer_list<const char *> parts);
static bool lp_has_timing(const std::string &d) { return d.find("if (dcn41_otg_read_timing(&gDcn.d, 0u, &ftm) == DCN41_OK) dcn41_otg_timing_decode(&ftm, &ftd);") != std::string::npos; }
// "#define NAME <value>" (any spacing) with the value parsed as C does (0x.. hex).
static bool def_is(const std::string &src, const char *name, uint32_t want) {
    std::istringstream in(src); std::string line;
    while (std::getline(in, line)) {
        std::istringstream w(line); std::string d, n, v;
        if (!(w >> d >> n >> v) || d != "#define" || n != name) continue;
        return std::strtoul(v.c_str(), nullptr, 0) == want;
    }
    return false;
}

// ---- the double references (the Linux expressions) ----------------------------------------------------------------------------------
static uint32_t ref_deep_sleep_khz(const Mode &m) {
    const double pix = m.pclkKhz / 1000.0;
    const double swath = (double)(m.hActive / m.odm);
    const double delivery = swath * m.odm / 1.0 / pix;
    double per = 1.15 * swath * m.bpp / 64.0 / delivery;
    per = std::fmax(per, pix / 16);
    const double readbw = m.hActive * std::ceil((double)m.bpp) / (m.hTotal / pix) * 1.0;
    double ds = std::fmax(8.0, 1.15 * readbw / 64.0);
    ds = std::fmax(ds, per);
    return (uint32_t)(ds * 1000);
}
static uint32_t ref_dfs(double clk, uint32_t vco) { const unsigned divider = (unsigned)((int)4 * (vco / clk)); return (uint32_t)((unsigned long)vco * 4 / divider); }
static uint32_t ref_dispclk(const Mode &m, uint32_t vco) {
    const double req = (double)(m.pclkKhz / m.odm);   // RequiredDISPCLK * 1000 as an unsigned int (exact for these modes)
    return ref_dfs(req * (1 + 0.38 / 100.0) * (1.0 + 1 / 100.0), vco);
}
static uint32_t ref_dppclk(const Mode &m, uint32_t vco) {
    const uint32_t per = (uint32_t)(m.pclkKhz / 1000.0 / m.odm * 1000);
    const unsigned long dppref0 = (unsigned long)(per * (1 + 0.38 / 100.0));
    const uint32_t dppref = ref_dfs((double)dppref0, vco);
    return (uint32_t)(dppref / 255.0 * std::ceil(per * (1.0 + 0.38 / 100.0) * 255.0 / dppref));
}

static void t1_dml() {
    const Mode m = kMode1440p120;
    expect_u("T1 deep sleep = the double expression", deep_sleep_khz(m), ref_deep_sleep_khz(m));
    expect_u("T1 DISPCLK = the double expression", dml_dispclk_khz(m, kDfsVcoKhz), ref_dispclk(m, kDfsVcoKhz));
    expect_u("T1 DPPCLK = the double expression", dml_dppclk_khz(m, kDfsVcoKhz), ref_dppclk(m, kDfsVcoKhz));
    uint32_t bad = 0, n = 0;
    const uint32_t widths[] = { 1920u, 2560u, 3440u, 3840u };
    for (uint32_t w : widths) for (uint32_t odm = 1u; odm <= 2u; odm++) for (uint32_t pclk = 148500u; pclk <= 700000u; pclk += 7250u) {
        if (pclk % (2u * 1000u / 1000u) != 0u && odm == 2u) continue;
        const Mode x { pclk - (pclk % 2u), w, w + 160u, 1440u, 1525u, 4u, odm };
        n++;
        const uint32_t a = deep_sleep_khz(x), b = ref_deep_sleep_khz(x);
        if (a + 1u < b || a > b + 1u) bad++;
        if (dml_dispclk_khz(x, kDfsVcoKhz) != ref_dispclk(x, kDfsVcoKhz)) bad++;
        if (dml_dppclk_khz(x, kDfsVcoKhz) + 1000u < ref_dppclk(x, kDfsVcoKhz) || dml_dppclk_khz(x, kDfsVcoKhz) > ref_dppclk(x, kDfsVcoKhz) + 1000u) bad++;
    }
    expect(n > 100u, "T1 the sweep ran");
    expect_u("T1 sweep: the integer forms agree with the doubles (deep sleep +-1 kHz, DISPCLK exact, DPPCLK within one DFS rounding)", bad, 0u);
}

static void t2_values() {
    const Mode m = kMode1440p120;
    expect_u("T2 deep sleep global term 33671 kHz", deep_sleep_global_khz(m), 33671u);
    expect_u("T2 deep sleep surface term = pclk / 16 (31109 kHz)", deep_sleep_surface_khz(m), 31109u);
    expect_u("T2 deep sleep 33671 kHz", deep_sleep_khz(m), 33671u);
    expect_u("T2 deep sleep 34 MHz (khz_to_mhz_ceil)", deep_sleep_mhz(m), 34u);
    const Mode bypass { m.pclkKhz, m.hActive, m.hTotal, m.vActive, m.vTotal, m.bpp, 1u };
    expect_u("T2 ODM bypass would be 35778 kHz -> 36 MHz", deep_sleep_mhz(bypass), 36u);
    expect_u("T2 DML DISPCLK 253521 kHz (DFS divider 71 on 4500 MHz)", dml_dispclk_khz(m, kDfsVcoKhz), 253521u);
    expect_u("T2 DML DPP ref 250000 kHz", dml_dppref_khz(m, kDfsVcoKhz), 250000u);
    expect_u("T2 DML DPPCLK 250000 kHz", dml_dppclk_khz(m, kDfsVcoKhz), 250000u);
    expect_u("T2 DCFCLK need 39040 kHz (ceil of 39039.2)", dcfclk_need_khz(m), 39040u);
    expect(dcfclk_need_khz(m) * 3u < 147000u, "T2 the lowest DCFCLK level (147 MHz) is above 3x the need: the burst factor cannot change the level");
    expect_u("T2 the running GOP clock 272727 kHz keeps 272 MHz", disp_floor_mhz(253521u, 272727u), 272u);
    expect_u("T2 DPPCLK 272727 kHz keeps 272 MHz", disp_floor_mhz(250000u, 272727u), 272u);
    expect_u("T2 a running clock below DML is raised to ceil(DML)", disp_floor_mhz(253521u, 250000u), 254u);
    expect_u("T2 unreadable: no floor", disp_floor_mhz(253521u, 0u), 0u);
    // the floor never asks less than the running clock's MHz floor, and never more than ceil(max(DML, running))
    for (uint32_t cur = 150000u; cur <= 600000u; cur += 137u) {
        const uint32_t f = disp_floor_mhz(253521u, cur);
        if (!((uint64_t)f * 1000u <= (cur > 253521u ? cur : 254000u) && (uint64_t)f * 1000u + 1000u > (cur > 253521u ? cur : 253521u))) { expect(false, "T2 floor bounds"); break; }
    }
}

static void t3_bootargs() {
    expect(mode_matches(kMode1440p120, 2560u, 1440u, 2720u, 1525u), "T3 the 120 Hz timing matches");
    expect(mode_matches(kMode1440p120, 2560u, 1440u, 2720u, 3050u), "T3 the 60 Hz V_TOTAL switch matches (same line time)");
    expect(!mode_matches(kMode1440p120, 2560u, 1440u, 2720u, 1543u) && !mode_matches(kMode1440p120, 1920u, 1080u, 2200u, 1125u) &&
           !mode_matches(kMode1440p120, 2560u, 1440u, 2640u, 1525u) && !mode_matches(kMode1440p120, 0u, 0u, 0u, 0u), "T3 any other timing (or unreadable) does not");
    expect_u("T3 0.0.685: absent = OFF", parts_of(false, 0u), 0u);
    expect_u("T3 default = displays + DCFCLK + deep sleep + DISPCLK/DPPCLK", kDefaultParts, 0x0Fu);
    expect_u("T3 0 = off", parts_of(true, 0u), 0u);
    expect_u("T3 1 = default", parts_of(true, 1u), 0x0Fu);
    expect_u("T3 2 = default + UCLK", parts_of(true, 2u), 0x1Fu);
    expect_u("T3 3 = all", parts_of(true, 3u), 0x3Fu);
    expect_u("T3 0x104 = deep sleep only", parts_of(true, 0x104u), kPartDeepSleep);
    expect_u("T3 0x100 = nothing", parts_of(true, 0x100u), 0u);
    expect_u("T3 0x1FF = the six parts only", parts_of(true, 0x1FFu), 0x3Fu);
    expect_u("T3 0.0.685: other values = OFF", parts_of(true, 7u), 0u);
    expect_u("T3 0.0.685: 0x200 = OFF", parts_of(true, 0x200u), 0u);
    expect_u("T3 clklog absent = 600 s", trace_seconds(false, 0u), 600u);
    expect_u("T3 clklog 0 = off", trace_seconds(true, 0u), 0u);
    expect_u("T3 clklog 120", trace_seconds(true, 120u), 120u);
    expect_u("T3 clklog capped at 1 h", trace_seconds(true, 99999u), 3600u);
}

static void t4_allow() {
    const Limits l { 147u, 1800u, 96u };
    const uint32_t all = kPartsAll, def = kDefaultParts;
    expect_u("T4 off refuses everything", allow(0u, kMsgGetSmuVersion, 0u, l), kRefOff);
    expect_u("T4 GetSmuVersion", allow(def, kMsgGetSmuVersion, 0u, l), kAllow);
    expect_u("T4 GetSmuVersion with a parameter", allow(def, kMsgGetSmuVersion, 1u, l), kRefParam);
    expect_u("T4 header version", allow(def, kMsgGetMsgHeaderVersion, 0u, l), kAllow);
    expect_u("T4 ReturnHardMinStatus", allow(def, kMsgReturnHardMinStatus, 0u, l), kAllow);
    expect_u("T4 DCFCLK level count", allow(def, kMsgGetDpmFreqByIndex, (kClkDcfclk << 16) | 0xFFu, l), kAllow);
    expect_u("T4 UCLK level 5", allow(def, kMsgGetDpmFreqByIndex, (kClkUclk << 16) | 5u, l), kAllow);
    expect_u("T4 DISPCLK levels are not queried here", allow(def, kMsgGetDpmFreqByIndex, (kClkDispclk << 16) | 0xFFu, l), kRefClk);
    expect_u("T4 index 16", allow(def, kMsgGetDpmFreqByIndex, (kClkDcfclk << 16) | 16u, l), kRefParam);
    expect_u("T4 high byte", allow(def, kMsgGetDpmFreqByIndex, 0x01000000u | (kClkDcfclk << 16), l), kRefParam);
    expect_u("T4 NumOfDisplays(1)", allow(def, kMsgNumOfDisplays, 1u, l), kAllow);
    expect_u("T4 NumOfDisplays(0)", allow(def, kMsgNumOfDisplays, 0u, l), kRefParam);
    expect_u("T4 NumOfDisplays(2)", allow(def, kMsgNumOfDisplays, 2u, l), kRefParam);
    expect_u("T4 NumOfDisplays without its part", allow(kPartDcfclk, kMsgNumOfDisplays, 1u, l), kRefPart);
    expect_u("T4 deep sleep 34", allow(def, kMsgSetMinDeepSleepDcfclk, 34u, l), kAllow);
    expect_u("T4 deep sleep 7", allow(def, kMsgSetMinDeepSleepDcfclk, 7u, l), kRefRange);
    expect_u("T4 deep sleep 101", allow(def, kMsgSetMinDeepSleepDcfclk, 101u, l), kRefRange);
    expect_u("T4 PstateAllow(1) is opt-in", allow(def, kMsgSetUclkPstateAllow, 1u, l), kRefPart);
    expect_u("T4 PstateAllow(1) with its part", allow(all, kMsgSetUclkPstateAllow, 1u, l), kAllow);
    expect_u("T4 PstateAllow(0) never", allow(all, kMsgSetUclkPstateAllow, 0u, l), kRefParam);
    expect_u("T4 DCFCLK 147", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDcfclk, 147u), l), kAllow);
    expect_u("T4 DCFCLK 146", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDcfclk, 146u), l), kRefRange);
    expect_u("T4 DCFCLK above the cap", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDcfclk, 601u), l), kRefRange);
    expect_u("T4 DCFCLK without a table", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDcfclk, 147u), Limits{ 0u, 0u, 96u }), kRefNoTable);
    expect_u("T4 UCLK is opt-in", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkUclk, 96u), l), kRefPart);
    expect_u("T4 UCLK the lowest level", allow(all, kMsgSetHardMinByFreq, param_hardmin(kClkUclk, 96u), l), kAllow);
    expect_u("T4 UCLK never a pin", allow(all, kMsgSetHardMinByFreq, param_hardmin(kClkUclk, 1258u), l), kRefRange);
    expect_u("T4 DISPCLK 272", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDispclk, 272u), l), kAllow);
    expect_u("T4 DPPCLK 272", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDppclk, 272u), l), kAllow);
    expect_u("T4 DISPCLK 199", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDispclk, 199u), l), kRefRange);
    expect_u("T4 DPPCLK 601", allow(def, kMsgSetHardMinByFreq, param_hardmin(kClkDppclk, 601u), l), kRefRange);
    expect_u("T4 DISPCLK without its part", allow(kPartDisplays, kMsgSetHardMinByFreq, param_hardmin(kClkDispclk, 272u), l), kRefPart);
    expect_u("T4 FCLK hard minimum never", allow(all, kMsgSetHardMinByFreq, param_hardmin(kClkFclk, 1000u), l), kRefClk);
    expect_u("T4 GFXCLK hard minimum never", allow(all, kMsgSetHardMinByFreq, param_hardmin(0u, 500u), l), kRefClk);
    const uint32_t never[] = { 0x1u, 0x5u, 0x6u, 0x7u, 0x8u, 0xAu, 0xCu, 0xFu, 0x10u, 0x11u, 0x12u, 0x13u, 0x14u, 0x16u, 0x17u, 0x18u, 0x19u, 0x1Bu, 0x1Cu, 0x1Du, 0xFFu };
    uint32_t leaked = 0;
    for (uint32_t msg : never) for (uint32_t p : { 0u, 1u, 0x90093u }) if (allow(all, msg, p, l) != kRefMsg) leaked++;
    expect_u("T4 every other DALSMC message is refused (SetHardMax, tables, DRAM addresses, FCLK/CAB/DRR, idle/active UCLK-FCLK, ...)", leaked, 0u);
}

static Levels lv(std::initializer_list<uint32_t> v) { Levels l{}; for (uint32_t x : v) l.mhz[l.n++] = x; return l; }

static void t5_plan() {
    PlanIn in{};
    in.parts = kDefaultParts; in.dcf = lv({ 147u, 236u, 1800u }); in.uclk = lv({ 96u, 456u, 772u, 875u, 1124u, 1258u });
    in.curDispKhz = 272727u; in.curDppKhz = 272727u; in.smuVer = 0x00664700u; in.mode = kMode1440p120; in.vcoKhz = kDfsVcoKhz;
    const Limits l { 147u, 1800u, 96u };
    Plan p = make_plan(in);
    expect_u("T5 default: 5 messages", p.n, 5u);
    expect(p.n == 5u && p.s[0].msg == kMsgNumOfDisplays && p.s[0].param == 1u, "T5 1: NumOfDisplays(1)");
    expect(p.n == 5u && p.s[1].msg == kMsgSetHardMinByFreq && p.s[1].param == param_hardmin(kClkDcfclk, 147u) && p.s[1].hardMin && p.s[1].clk == kClkDcfclk, "T5 2: DCFCLK 147 (hard minimum)");
    expect(p.n == 5u && p.s[2].msg == kMsgSetMinDeepSleepDcfclk && p.s[2].param == 34u && !p.s[2].hardMin, "T5 3: deep sleep 34");
    expect(p.n == 5u && p.s[3].param == param_hardmin(kClkDispclk, 272u) && p.s[4].param == param_hardmin(kClkDppclk, 272u), "T5 4/5: DISPCLK then DPPCLK at the running 272 MHz");
    expect(plan_allowed(p, in.parts, l), "T5 the default plan passes the allowlist");
    expect_u("T5 nothing skipped", p.skipped, 0u);
    in.parts = kPartsAll;
    p = make_plan(in);
    expect_u("T5 all parts: 7 messages", p.n, 7u);
    expect(p.n == 7u && p.s[3].msg == kMsgSetUclkPstateAllow && p.s[4].param == param_hardmin(kClkUclk, 96u) && p.s[5].param == param_hardmin(kClkDispclk, 272u),
           "T5 PstateAllow and UCLK (lowest level) between the deep sleep and the display clocks (Linux's order)");
    expect(plan_allowed(p, in.parts, l), "T5 the full plan passes the allowlist");
    in.smuVer = kIdleDpmSmuVer;
    p = make_plan(in);
    expect((p.skipped & kPartUclk) != 0u && p.uclkMhz == 0u, "T5 a PMFW with idle DPM (>= 0x681800): the plain UCLK hard minimum is not Linux's path: skipped");
    in.smuVer = 0x00664700u; in.parts = kDefaultParts;
    in.curDispKhz = 0u;
    p = make_plan(in);
    expect((p.skipped & kPartDispDpp) != 0u && p.dispMhz == 0u && p.n == 3u, "T5 unreadable display clocks: no DISPCLK/DPPCLK floor");
    in.curDispKhz = 272727u; in.dcf = Levels{};
    p = make_plan(in);
    expect((p.skipped & kPartDcfclk) != 0u && p.dcfMhz == 0u && p.n == 4u, "T5 no DCFCLK table: no DCFCLK hard minimum");
    in.dcf = lv({ 20u, 1800u });   // fine-grained: the need itself, at least the minimum
    p = make_plan(in);
    expect_u("T5 fine-grained DCFCLK: ceil(need) = 40 MHz", p.dcfMhz, 40u);
    in.dcf = lv({ 147u, 236u, 1800u }); in.parts = kPartDisplays;
    p = make_plan(in);
    expect(p.n == 1u && p.s[0].msg == kMsgNumOfDisplays, "T5 one part: one message");
    expect_u("T5 level_for discrete", level_for(lv({ 147u, 236u, 1800u }), 150000u), 236u);
    expect_u("T5 level_for above every level", level_for(lv({ 147u, 236u, 1800u }), 1900000u), 0u);
    expect_u("T5 levels_min / max", levels_min(lv({ 236u, 147u, 1800u })) * 10000u + levels_max(lv({ 236u, 147u, 1800u })), 147u * 10000u + 1800u);
    expect(clocks_kept(272727u, 272727u, 272727u, 272727u) && clocks_kept(272727u, 272727u, 281250u, 272727u), "T5 kept: equal or above");
    expect(!clocks_kept(272727u, 272727u, 257142u, 272727u) && !clocks_kept(272727u, 272727u, 0u, 272727u), "T5 fallen or unreadable: not kept");
}

static Sample smp(uint64_t ms, uint32_t u, uint32_t f, uint32_t d, bool pinned = false, uint32_t disp = 272u) {
    Sample s{}; s.ms = ms; s.ok = true; s.pinned = pinned;
    s.mhz[kTUclk] = u; s.mhz[kTFclk] = f; s.mhz[kTDcf] = d; s.mhz[kTDisp] = disp; s.mhz[kTDpp] = 272u; s.mhz[kTSoc] = 1371u;
    s.dfsDispKhz = disp * 1000u; s.dfsDppKhz = 272727u;
    return s;
}

static void t6_trace() {
    Trace t; trace_init(t, 147u);
    uint64_t ms = 0;
    for (; ms < 5000u; ms += 500u) trace_add(t, smp(ms, 96u, 1096u, 147u));
    expect_u("T6 10 samples", t.samples, 10u);
    expect_u("T6 no moves yet", t.moves[kTUclk] + t.moves[kTFclk] + t.moves[kTDcf], 0u);
    // H3: UCLK switches at the event
    trace_add(t, smp(ms, 1258u, 1096u, 147u)); ms += 500u;
    trace_event(t, ms - 400u, 2u, false);
    Burst b{};
    expect(!trace_settle(t, ms, &b), "T6 not settled before the post window");
    for (int k = 0; k < 3; k++) { trace_add(t, smp(ms, 1258u, 1096u, 147u)); ms += 500u; }
    expect(trace_settle(t, ms, &b), "T6 settled after the post window");
    expect((b.flags & kBUclk) != 0u && (b.flags & kBFclk) == 0u && (b.flags & kBDcf) == 0u, "T6 burst 1: UCLK moved only");
    expect_u("T6 burst 1 events", b.events, 2u);
    expect_u("T6 burst counts: UCLK", t.bUclk, 1u);
    expect(std::string(trace_lean(t)).find("H3") == 0, "T6 lean H3");
    // H2: FCLK moves, UCLK steady (pinned)
    for (int k = 0; k < 6; k++) { trace_add(t, smp(ms, 1258u, 1096u, 147u, true)); ms += 500u; }
    trace_add(t, smp(ms, 1258u, 2016u, 147u, true));
    trace_event(t, ms, 1u, true); ms += 500u;
    for (int k = 0; k < 3; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u, true)); ms += 500u; }
    expect(trace_settle(t, ms, &b) && (b.flags & kBFclk) != 0u && (b.flags & kBUclk) == 0u && (b.flags & kBPinned) != 0u, "T6 burst 2: FCLK alone, while pinned");
    expect_u("T6 FCLK moves with UCLK pinned", t.fclkMovesPinned, 1u);
    expect_u("T6 FCLK alone", t.bFclkOnly, 1u);
    expect_u("T6 bursts while pinned", t.bPinned, 1u);
    // H1: DCFCLK under its floor in the window
    for (int k = 0; k < 6; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u)); ms += 500u; }
    trace_add(t, smp(ms, 1258u, 2016u, 40u));
    trace_event(t, ms, 1u, false); ms += 500u;
    for (int k = 0; k < 3; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u)); ms += 500u; }
    expect(trace_settle(t, ms, &b) && (b.flags & kBDcfBelowFloor) != 0u && (b.flags & kBDcf) != 0u, "T6 burst 3: DCFCLK under its floor");
    expect_u("T6 samples under the DCFCLK floor", t.dcfBelowFloor, 1u);
    // DISPCLK change seen by the DFS readback
    for (int k = 0; k < 6; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u)); ms += 500u; }
    trace_add(t, smp(ms, 1258u, 2016u, 147u, false, 257u));
    trace_event(t, ms, 1u, false); ms += 500u;
    for (int k = 0; k < 3; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u)); ms += 500u; }
    expect(trace_settle(t, ms, &b) && (b.flags & kBDisp) != 0u, "T6 burst 4: DISPCLK moved");
    expect_u("T6 DISPCLK/DPPCLK bursts", t.bDispDpp, 1u);
    // nothing moved
    for (int k = 0; k < 6; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u)); ms += 500u; }
    trace_event(t, ms, 3u, false); ms += 500u;
    for (int k = 0; k < 3; k++) { trace_add(t, smp(ms, 1258u, 2016u, 147u)); ms += 500u; }
    expect(trace_settle(t, ms, &b) && (b.flags & 0x3Fu) == 0u && (b.flags & kBDcfBelowFloor) == 0u, "T6 burst 5: nothing moved");
    expect_u("T6 nothing-moved bursts", t.bNone, 1u);
    expect_u("T6 bursts", t.bursts, 5u);
    expect_u("T6 events", t.events, 8u);
    expect(std::string(trace_lean(t)).find("H1") == 0, "T6 lean: H1 (DCFCLK + DISPCLK bursts outnumber the others)");
    // few samples: an event with no ring around it
    Trace e; trace_init(e, 0u);
    trace_event(e, 10000u, 1u, false);
    trace_add(e, smp(11000u, 96u, 1096u, 147u));
    expect(trace_settle(e, 11000u, &b) && (b.flags & kBFewSamples) != 0u && e.bFew == 1u, "T6 a burst with under 3 samples is marked");
    // the ring wraps and the extremes hold
    Trace r; trace_init(r, 0u);
    for (uint32_t k = 0; k < 3u * kRing; k++) trace_add(r, smp(k * 500u, k == 5u ? 456u : 96u, 1096u, 147u));
    expect_u("T6 ring count capped", r.count, kRing);
    expect(r.lo[kTUclk] == 96u && r.hi[kTUclk] == 456u && r.moves[kTUclk] == 2u, "T6 extremes and moves survive the wrap");
    expect(trace_at(r, 0) != nullptr && trace_at(r, 0)->ms == (3u * kRing - 1u) * 500u && trace_at(r, kRing) == nullptr, "T6 trace_at newest first");
    Sample bad = smp(0u, 1u, 1u, 1u); bad.ok = false;
    trace_add(r, bad);
    expect_u("T6 a failed sample is counted, not stored", r.failures, 1u);
    expect(r.bursts == 0u && std::string(trace_lean(r)).find("no underflow") == 0, "T6 lean with no burst");
}

static void t7_pins(const std::string &root) {
    const std::string f = slurp(root + "/src/amd/clkfloor.cpp"), d = slurp(root + "/src/dcn/navi48_dcn.cpp"), dal = slurp(root + "/src/amd/smu_dal.cpp");
    const std::string dalh = slurp(root + "/src/amd/smu_dal.h"), dalp = slurp(root + "/src/amd/smu_dal_pure.h");
    expect(!f.empty() && !d.empty() && !dal.empty(), "T7 sources readable (pass the navi48-bringup directory)");
    // the floors: one sender, the allowlist first, no register write of their own
    const std::string fa = body(f, "uint32_t floor_allow(uint32_t msg, uint32_t param) {"), fs = body(f, "kern_return_t fsend(const DeviceContext &dev, uint32_t msg, uint32_t param, DalMsg *m) {");
    expect(fa.find("allow(gF.parts, msg, param, limits())") != std::string::npos && fa.find("return why == kAllow ? 0u : 0x100u | why;") != std::string::npos, "T7 floor_allow: the floor allowlist, non-zero = refused");
    expect(fs.find("return smu_dal_send(dev, msg, param, m, floor_allow);") != std::string::npos, "T7 fsend: the shared sender with the floor allowlist");
    size_t calls = 0, p = 0; while ((p = f.find("smu_dal_send(", p)) != std::string::npos) { calls++; p++; }
    expect_u("T7 smu_dal_send is called once in the floors (fsend), always with floor_allow", calls, 1u);
    expect(f.find("WREG32") == std::string::npos, "T7 no register write of the floors' own");
    expect(has(f, "\"navi48-dalfloor\"") && has(f, "\"navi48-clklog\""), "T7 the two boot-args");
    expect(has(f, "dal_owner_claim_floor()") && has(f, "dal_owner_release_floor();"), "T7 the floors own the DAL mailbox while they run");
    const std::string run = body(f, "uint32_t dal_floor_run(const DeviceContext &dev, uint32_t hActive, uint32_t vActive, uint32_t hTotal, uint32_t vTotal, uint32_t *dcfFloorMhz) {");
    expect(run.find("mode_matches(kMode1440p120, hActive, vActive, hTotal, vTotal)") < run.find("dal_owner_claim_floor()"), "T7 nothing sent unless OTG0 is lit with the mode the values are for");
    expect(lp_has_timing(d), "T7 the monitor reads OTG0's timing (read-only) for the floors");
    expect(run.find("if (gF.ran)") < run.find("dal_owner_claim_floor()"), "T7 once per boot");
    expect(run.find("n48uclk::kNotRun") < run.find("dal_owner_claim_floor()") && run.find("gF.parts == 0u") < run.find("dal_owner_claim_floor()"),
           "T7 nothing sent when off or when this boot did not enable the SMU features");
    expect(run.find("gF.hdrVer != kDalsmcVersion") < run.find("make_plan(in)"), "T7 the DALSMC header version is checked before any floor");
    expect(run.find("plan_allowed(gF.plan, gF.parts, limits())") < run.find("run_step(dev, gF.plan.s[i]"), "T7 the whole plan is allowed before the first floor");
    expect(run.find("out:\n    dal_owner_release_floor();") != std::string::npos, "T7 the owner word is released on every path");
    expect(has(f, "SmuTrySeq seq;   // the whole table transfer under the shared mailbox lock (as Navi48UserClient::doMetrics), or nothing") && has(f, "if (!seq.held) return kSBusy;"),
           "T7 0.0.685: the metrics read takes the shared mailbox lock only if it is free (never queues behind a 2 s timeout)");
    // the shared sender keeps the experiment's allowlist in front
    const std::string ds = body(dal, "kern_return_t smu_dal_send(const DeviceContext &dev, uint32_t msg, uint32_t param, DalMsg *m, DalAllowFn floorAllow) {");
    const size_t pw = ds.find("floorAllow != nullptr ? floorAllow(msg, param) : allow_check(dal_gated_level(), msg, param, gDal.max[0], gDal.max[1]);");
    expect(pw != std::string::npos && pw < ds.find("SmuSeq seq;") && pw < ds.find("WREG32(dev, kRegResp, 0u);"), "T7 smu_dal_send: one allowlist (the floors' or the experiment's) before the lock and the first write");
    expect(has(dalh, "DalAllowFn floorAllow = nullptr);") && has(dalp, "kOwnerFloor = 3"), "T7 every other caller keeps the experiment's allowlist (default nullptr); owner 3 is declared");
    expect(has(dal, "bool dal_owner_claim_floor() { return owner_cas(kOwnerIdle, kOwnerFloor); }"), "T7 the claim is a compare-and-swap from idle");
    // the display monitor: after the arbitration, before the fallback arms; the trace with no lock
    const std::string lp = body(d, "static void arb_monitor_loop() {");
    const size_t ap = lp.find("arb_apply_once()) {"), fr = lp.find("amdgpu::dal_floor_run(*gDcn.dev, ftd.h_active, ftd.v_active, ftd.h_total, ftd.v_total, &dcfFloor);"), ar = lp.find("gFb.armed = true;");
    expect(ap != std::string::npos && fr > ap && ar > fr, "T7 the floors run after the arbitration and before the fallback arms");
    expect(lp.find("amdgpu::clktrace_start(t0);") < lp.find("while (__atomic_load_n(&gArbStop"), "T7 the trace starts with the monitor");
    expect(lp.find("amdgpu::clktrace_poll(*gDcn.dev, now_ms(), fresh, gFb.pinned)") > lp.find("fresh = ev - lastEvents;"), "T7 the trace sees each poll's new underflow events");
    expect(lp.find("IOLockLock(") == std::string::npos && lp.find("if (on) ufmon_poll(monGen);") != std::string::npos, "T7 the monitor still takes no lock itself");
    expect(has(d, "setProperty(\"Navi48,DalFloor\"") && has(d, "setProperty(\"Navi48,DisplayClocks\""), "T7 the two registry properties");
}

// 0.0.685: the preconditions and the post-check (pure + source pins).
static void t9_685(const std::string &root) {
    expect_u("T9 the assumed DISPCLK is 4 x 4500 / 66 MHz", kAssumedDispKhz, 272727u);
    expect(clocks_match_assumption(272727u, 272727u) && clocks_match_assumption(270000u, 275000u), "T9 272.7 MHz (within 1 %) matches");
    expect(!clocks_match_assumption(562500u, 562500u), "T9 the live 0.0.684 readback (562.5 / 562.5 MHz) does NOT match: nothing would be sent");
    expect(!clocks_match_assumption(272727u, 562500u) && !clocks_match_assumption(0u, 272727u) && !clocks_match_assumption(269000u, 272727u) && !clocks_match_assumption(276000u, 272727u),
           "T9 either clock off by more than 1 % (or unreadable) does not match");
    expect(std::string(verdict_name(kVOff)).find("default") != std::string::npos && std::string(verdict_name(kVAssume)).find("nothing sent") != std::string::npos &&
           std::string(verdict_name(kVUnhealthy)).find("nothing sent") != std::string::npos && std::string(verdict_name(kVPostFail)).find("DEGRADED") != std::string::npos, "T9 the new verdict names");
    if (root.empty()) return;
    const std::string f = slurp(root + "/src/amd/clkfloor.cpp");
    const std::string run = body(f, "uint32_t dal_floor_run(const DeviceContext &dev, uint32_t hActive, uint32_t vActive, uint32_t hTotal, uint32_t vTotal, uint32_t *dcfFloorMhz) {");
    const size_t claim = run.find("dal_owner_claim_floor()"), asum = run.find("clocks_match_assumption(gF.before.dispKhz, gF.before.dppKhz)"),
                 health = run.find("!smu_optional_ok() || !smu_dal_allowed()"), lock = run.find("SmuSeq seq;"), probe = run.find("if (smu_health_probe(dev) != kIOReturnSuccess) {"),
                 first = run.find("fsend(dev, kMsgGetSmuVersion, 0u, &m)"), post = run.find("gF.verdict = kVPostFail;"), outp = run.find("out:\n");
    expect(asum != std::string::npos && asum < claim, "T9 the clock assumption is checked before the mailbox is claimed (nothing sent on a mismatch)");
    expect(health != std::string::npos && health < claim, "T9 the SMU health latch is checked before the mailbox is claimed");
    expect(lock != std::string::npos && probe != std::string::npos && claim < lock && lock < probe && probe < first, "T9 the whole sequence under the shared lock, the PPSMC readiness probe before the first DAL message");
    expect(post != std::string::npos && post > run.find("run_step(dev, gF.plan.s[i]") && post < outp, "T9 the post-check probe after the floors, before the owner is released");
    size_t probes = 0, p = 0; while ((p = run.find("smu_health_probe(dev)", p)) != std::string::npos) { probes++; p++; }
    expect_u("T9 two probes in the run (readiness, post-check); a DAL timeout's probe is smu_dal_send's", probes, 2u);
    const std::string poll = body(f, "bool clktrace_poll(const DeviceContext &dev, uint64_t nowMs, uint64_t newEvents, bool pinned) {");
    expect(poll.find("if (!gTOn || gTStop != 0u) return false;") != std::string::npos && poll.find("if (!smu_optional_ok()) {") != std::string::npos, "T9 the trace stops for good when stopped or when the SMU is degraded");
    expect(poll.find("n48smuh::trace_period_ms(gTConsec)") != std::string::npos && poll.find("n48smuh::trace_should_stop(gTConsec)") != std::string::npos && poll.find("gTSkippedBusy++;") != std::string::npos,
           "T9 the trace backs off, stops after consecutive failures, and skips (no failure) when the lock is busy");
    expect(has(f, "if (!gTEnded && nowMs - gTPubMs >= 5000u)"), "T9 the registry is not rewritten every 5 s after the trace ended");
}

static void t8_linux(const std::string &amd) {
    const std::string dalsmc = slurp(amd + "/display/dc/clk_mgr/dcn401/dalsmc.h"), drvif = slurp(amd + "/display/dc/clk_mgr/dcn401/dcn401_smu14_driver_if.h");
    const std::string clk = slurp(amd + "/display/dc/clk_mgr/dcn401/dcn401_clk_mgr.c"), bb = slurp(amd + "/display/dc/dml2_0/dml21/inc/bounding_boxes/dcn4_soc_bb.h");
    const std::string core = slurp(amd + "/display/dc/dml2_0/dml21/src/dml2_core/dml2_core_dcn4.c"), shared = slurp(amd + "/display/dc/dml2_0/dml21/src/dml2_core/dml2_core_shared_types.h");
    const std::string res = slurp(amd + "/display/dc/resource/dcn401/dcn401_resource.c"), calcs = slurp(amd + "/display/dc/dml2_0/dml21/src/dml2_core/dml2_core_dcn4_calcs.c");
    expect(!dalsmc.empty() && !clk.empty() && !bb.empty() && !calcs.empty(), "T8 Linux sources readable");
    expect(def_is(dalsmc, "DALSMC_VERSION", kDalsmcVersion) && def_is(dalsmc, "DALSMC_MSG_GetSmuVersion", kMsgGetSmuVersion) &&
           def_is(dalsmc, "DALSMC_MSG_GetDriverIfVersion", kMsgGetDriverIfVersion) && def_is(dalsmc, "DALSMC_MSG_GetMsgHeaderVersion", kMsgGetMsgHeaderVersion) &&
           def_is(dalsmc, "DALSMC_MSG_SetHardMinByFreq", kMsgSetHardMinByFreq) && def_is(dalsmc, "DALSMC_MSG_GetDpmFreqByIndex", kMsgGetDpmFreqByIndex) &&
           def_is(dalsmc, "DALSMC_MSG_SetMinDeepSleepDcfclk", kMsgSetMinDeepSleepDcfclk) && def_is(dalsmc, "DALSMC_MSG_NumOfDisplays", kMsgNumOfDisplays) &&
           def_is(dalsmc, "DALSMC_MSG_ReturnHardMinStatus", kMsgReturnHardMinStatus) && def_is(dalsmc, "DALSMC_MSG_SetUclkPstateAllow", kMsgSetUclkPstateAllow),
           "T8 dalsmc.h message ids");
    const size_t e = drvif.find("PPCLK_GFXCLK = 0,");
    const std::string en = e == std::string::npos ? std::string() : drvif.substr(e, 200);
    expect(in_order_ok(en, { "PPCLK_GFXCLK", "PPCLK_SOCCLK", "PPCLK_UCLK", "PPCLK_FCLK", "PPCLK_DCLK_0", "PPCLK_VCLK_0", "PPCLK_DISPCLK", "PPCLK_DPPCLK", "PPCLK_DPREFCLK", "PPCLK_DCFCLK" }),
           "T8 PPCLK_e order: UCLK 2, FCLK 3, DISPCLK 6, DPPCLK 7, DCFCLK 9");
    expect(has(clk, "clk_mgr->smu_ver >= 0x681800"), "T8 the idle-DPM PMFW threshold for GC 12.0.0");
    expect(has(clk, "CLK_MGR401_UPDATE_NUM_DISPLAYS") && has(clk, "CLK_MGR401_UPDATE_DEEP_SLEEP_DCFCLK") && has(clk, "PPCLK_DCFCLK"), "T8 the bandwidth sequence sends NumOfDisplays, the DCFCLK hard minimum and the deep-sleep floor");
    expect(has(bb, ".dcn_downspread_percent = 0.38,") && has(bb, ".dispclk_dppclk_vco_speed_mhz = 4500,") && has(bb, ".return_bus_width_bytes = 64,"), "T8 dcn4_soc_bb.h: downspread 0.38 %, VCO 4500 MHz, return bus 64 B");
    expect(has(core, ".dispclk_ramp_margin_percent = 1,"), "T8 dispclk_ramp_margin_percent 1");
    expect(has(shared, "#define __DML2_CALCS_DCFCLK_FACTOR__ 1.15"), "T8 the DCFCLK factor 1.15");
    expect(has(calcs, "*DCFClkDeepSleep = math_max2(8.0, __DML2_CALCS_DCFCLK_FACTOR__ * ReadBandwidth / (double)ReturnBusWidth);") &&
           has(calcs, "DCFClkDeepSleepPerSurface[k] = math_max2(DCFClkDeepSleepPerSurface[k], pixel_rate_mhz / 16);"), "T8 CalculateDCFCLKDeepSleep's terms");
    expect(has(res, ".enable_single_display_2to1_odm_policy = true,") && has(res, "dc->dml2_options.minimize_dispclk_using_odm = true;"), "T8 dcn401: single-display ODM 2:1");
}
// (kept separate so T8 reads like the others)
bool in_order_ok(const std::string &s, std::initializer_list<const char *> parts) {
    size_t at = 0;
    for (const char *p : parts) { const size_t q = s.find(p, at); if (q == std::string::npos) return false; at = q + 1; }
    return true;
}

int main(int argc, char **argv) {
    t1_dml(); t2_values(); t3_bootargs(); t4_allow(); t5_plan(); t6_trace();
    if (argc > 1) t7_pins(argv[1]);
    t9_685(argc > 1 ? argv[1] : "");
    if (argc > 2) t8_linux(argv[2]);
    std::printf("%s: %d checks, %d failed\n", gFail ? "FAIL" : "PASS", gRun, gFail);
    return gFail ? 1 : 0;
}
