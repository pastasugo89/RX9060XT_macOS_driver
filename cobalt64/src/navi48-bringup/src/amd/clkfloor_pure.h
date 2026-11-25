//
//  clkfloor_pure.h - build 0.0.684: the PURE half of the display clock floors and of the boot clock trace. No kernel header, so
//  tests/dalfloor684_test.cpp compiles it on the host and drives the exact decisions clkfloor.cpp makes.
//
//  Why (research/reports/macos-20261114/gfx-activity-investigation.md, Part C, H1..H4): since 0.0.673 the DET (20 segments) and the Linux
//  watermarks are programmed and HUBP never underflows, but every boot still sees OPTC-only underflows about a minute after login until the AUTO
//  fallback pins UCLK at its maximum. Linux sends the PMFW, through the DAL mailbox (DALSMC, amd/display/dc/clk_mgr/dcn401/dalsmc.h), the display's
//  clock requirements on every bandwidth update; we never did: no NumOfDisplays, no DCFCLK hard minimum, no DCFCLK deep-sleep floor, no
//  DISPCLK/DPPCLK hard minimum. Without them the PMFW believes no display is lit and nothing bounds DCFCLK deep sleep around a UCLK switch (H1).
//
//  What Linux sends for this machine's only mode (one 2560x1440@120 ARGB8888 plane, pixel clock 497.75 MHz, H_TOTAL 2720, V_TOTAL 1525,
//  ODM 2:1 because dcn401_resource.c sets enable_single_display_2to1_odm_policy and minimize_dispclk_using_odm), worked out by hand from
//  linux-v7.3 (research/ext/amdgpu-port-study, MIT):
//    dcn401_build_update_bandwidth_clocks_sequence (dcn401_clk_mgr.c:769-1072), the prepare (raise) pass of dcn401_update_clocks (:1282):
//      1. NumOfDisplays(1)                                         (:810-822; every non-lowering update with a display)
//      2. SetHardMinByFreq(DCFCLK, ceil(dcfclk_khz))               (:854-865)  dcfclk_khz = DML active DCFCLK rounded up to the PMFW's DCFCLK
//         levels (dml2_dpmm_dcn4.c calculate_system_active_minimums + map_soc_min_clocks_to_dpm_fine_grained): this mode needs about 39 MHz of
//         return bandwidth (dcfclk_need_khz below), so it is the lowest DCFCLK level (147 MHz in the Linux oracle's pp_dpm_dcefclk);
//      3. SetMinDeepSleepDcfclk(ceil(dcfclk_deep_sleep_khz))       (:868-875)  dml2_core_dcn4_calcs.c CalculateDCFCLKDeepSleepTdlut:
//         max(8, 1.15 * ReadBW / 64, max(1.15 * SwathWidth * Bpp / 64 / LineDeliveryTime, PixelClock / 16)) = 33.671 MHz -> 34 MHz;
//      4. SetHardMinByFreq(UCLK, ceil(dramclk_khz))                (:1012-1019, PMFW 0x664700 is below dcn401_is_ppclk_idle_dpm_enabled's
//         0x681800, so the plain UCLK hard minimum is used): the lowest UCLK level for this mode (96 MHz). OPT-IN here (kPartUclk).
//         SetUclkPstateAllow(1) (:908-922) is sent by Linux only on a transition from "unsupported"; dcn401_init_clocks starts at "supported",
//         so Linux does not send it on this mode at boot. OPT-IN here (kPartPstateAllow).
//    dcn401_build_update_display_clocks_sequence (:1085-1249): DISPCLK then DPPCLK hard minimums (dcn401_set_hard_min_by_freq_optimized, MHz
//      floor first). DML: DISPCLK = 497.75 / 2 * 1.0038 (dcn_downspread_percent 0.38) * 1.01 (dispclk_ramp_margin_percent 1) = 252.32 MHz,
//      rounded on the 4500 MHz DFS VCO to 253.521 MHz; DPPCLK = 497.75 / 2 * 1.0038 = 249.82 MHz -> 250.000 MHz (dml2_dpmm_dcn4.c
//      map_mode_to_soc_dpm + add_margin_and_round_to_dfs_grainularity). Linux would LOWER both from the GOP's 272.727 MHz in the optimize (lower)
//      pass, which also reprograms the DPP DTOs. We never lower a display clock under a lit pipe whose DTOs we did not program: the floor is
//      max(the DML value, the clock read back now), so the request equals the running clock (a floor that keeps it, as Linux's floor would).
//  Each hard minimum is followed by ReturnHardMinStatus polled until bit (1 << ppclk) (dcn401_smu_wait_hard_min_status, <= 1 s).
//
//  The clock trace (boot-time logging, read-only): PMFW metrics CurrClock[] (UCLK, FCLK, DCFCLK, DISPCLK, DPPCLK, SOCCLK) and the DISPCLK/DPPCLK
//  DFS readback, sampled every kSamplePeriodMs, kept in a ring; each burst of ufmon underflow events is classified by which clocks moved
//  within [-kPreMs, +kPostMs] of the first event (H1: DCFCLK / DISPCLK / DPPCLK; H2: FCLK; H3: UCLK; none: no clock moved).
//
//  Everything here is arithmetic and decisions; nothing touches a register. Integer arithmetic only (kernel code: no floating point).
//
#pragma once
#include <stdint.h>

namespace n48dalfloor {

// ---- DALSMC messages (dalsmc.h) and PPCLK_e (dcn401_smu14_driver_if.h) -------------------------------------------------------------------
constexpr uint32_t kMsgGetSmuVersion = 0x2u, kMsgGetDriverIfVersion = 0x3u, kMsgGetMsgHeaderVersion = 0x4u;
constexpr uint32_t kMsgSetHardMinByFreq = 0x9u, kMsgGetDpmFreqByIndex = 0xBu, kMsgSetMinDeepSleepDcfclk = 0xDu, kMsgNumOfDisplays = 0xEu;
constexpr uint32_t kMsgReturnHardMinStatus = 0x15u, kMsgSetUclkPstateAllow = 0x1Au;
constexpr uint32_t kDalsmcVersion = 0x1u;                       // DALSMC_VERSION
constexpr uint32_t kClkUclk = 2u, kClkFclk = 3u, kClkDispclk = 6u, kClkDppclk = 7u, kClkDcfclk = 9u;
constexpr uint32_t kIndexAll = 0xFFu;
constexpr uint32_t kMaxLevels = 16u;
constexpr uint32_t kIdleDpmSmuVer = 0x681800u;                  // dcn401_is_ppclk_idle_dpm_enabled, GC 12.0.0: at or above it Linux uses ActiveUclkFclk instead

// ---- the parts (boot-arg navi48-dalfloor) ------------------------------------------------------------------------------------------------
enum Part : uint32_t {
    kPartDisplays = 0x01u,      // NumOfDisplays(1)
    kPartDcfclk = 0x02u,        // SetHardMinByFreq(DCFCLK, the DML level)
    kPartDeepSleep = 0x04u,     // SetMinDeepSleepDcfclk(the DML value)
    kPartDispDpp = 0x08u,       // SetHardMinByFreq(DISPCLK / DPPCLK, max(DML, the running clock))
    kPartUclk = 0x10u,          // SetHardMinByFreq(UCLK, the lowest level) - opt-in
    kPartPstateAllow = 0x20u,   // SetUclkPstateAllow(1) - opt-in (Linux does not send it at boot on this mode)
};
constexpr uint32_t kPartsAll = 0x3Fu;
constexpr uint32_t kDefaultParts = kPartDisplays | kPartDcfclk | kPartDeepSleep | kPartDispDpp;
// navi48-dalfloor: absent = the default (0x0F); 0 = OFF (nothing is sent); 1 = the default; 2 = the default + the UCLK hard minimum (0x1F);
// 3 = everything (0x3F); 0x100 | mask = exactly `mask` (bits above, 0x100 alone = nothing). Any other value: the default.
constexpr uint32_t parts_of(bool present, uint32_t v) {
    return !present ? kDefaultParts : v == 0u ? 0u : v == 1u ? kDefaultParts : v == 2u ? (kDefaultParts | kPartUclk) : v == 3u ? kPartsAll
         : (v & ~0xFFu) == 0x100u ? (v & kPartsAll) : kDefaultParts;
}

// ---- the mode and the DML values (integer forms of the double expressions; the host test checks them against the doubles) ----------------
struct Mode { uint32_t pclkKhz, hActive, hTotal, vActive, vTotal, bpp, odm; };
constexpr Mode kMode1440p120 { 497750u, 2560u, 2720u, 1440u, 1525u, 4u, 2u };   // the GOP's (and Linux's) timing on this LG, ODM 2:1
// The lit timing must be this mode (read from OTG0 at the call): the values above are computed for it. V_TOTAL 3050 is the 60 Hz switch
// (navi48_refresh_pure.h: V_TOTAL only, same pixel clock and line time, so the same DCN clock needs).
constexpr bool mode_matches(const Mode &m, uint32_t hActive, uint32_t vActive, uint32_t hTotal, uint32_t vTotal) {
    return hActive == m.hActive && vActive == m.vActive && hTotal == m.hTotal && (vTotal == m.vTotal || vTotal == 2u * m.vTotal);
}
constexpr uint32_t kDfsVcoKhz = 4500000u;   // dcn4_soc_bb.h dispclk_dppclk_vco_speed_mhz (the PLL_REQ readback agrees: 272.727 = 4 * 4500 / 66)

constexpr uint32_t ceil_div(uint64_t a, uint64_t b) { return (uint32_t)((a + b - 1u) / b); }
constexpr uint32_t max2(uint32_t a, uint32_t b) { return a > b ? a : b; }
// DCFClkDeepSleep in kHz, truncated as dml2_core_dcn4.c does ((unsigned int)(MHz * 1000)).
//   global  = 1.15 * ReadBandwidth / ReturnBusWidth(64), ReadBandwidth = hActive * Bpp / (hTotal / pclk)
//   surface = max(1.15 * SwathWidth * Bpp / 64 / LineDeliveryTime, pclk / 16); SwathWidth = hActive / odm, LineDeliveryTime = SwathWidth * odm / pclk
constexpr uint32_t deep_sleep_global_khz(const Mode &m) { return (uint32_t)((115ull * m.hActive * m.bpp * m.pclkKhz) / (6400ull * m.hTotal)); }
constexpr uint32_t deep_sleep_surface_khz(const Mode &m) { return max2((uint32_t)((115ull * m.bpp * m.pclkKhz) / (6400ull * (m.odm ? m.odm : 1u))), m.pclkKhz / 16u); }
constexpr uint32_t deep_sleep_khz(const Mode &m) { return max2(8000u, max2(deep_sleep_global_khz(m), deep_sleep_surface_khz(m))); }
constexpr uint32_t deep_sleep_mhz(const Mode &m) { return ceil_div(deep_sleep_khz(m), 1000u); }   // khz_to_mhz_ceil
// The DCFCLK the mode's return bandwidth needs (kHz): the larger of DML's urgent (derate 100 %) and average (derate 75 %) terms, without the
// urgent burst factor; the lowest DCFCLK level (147 MHz) is about 3.8 times this, so the factor cannot change the level picked.
constexpr uint32_t dcfclk_need_khz(const Mode &m) { return ceil_div((uint64_t)m.hActive * m.bpp * m.pclkKhz * 4u, 3ull * 64u * m.hTotal); }
// add_margin_and_round_to_dfs_grainularity: divider = floor(4 * vco / clk); rounded = vco * 4 / divider. clk is a rational num / den here.
constexpr uint32_t dfs_round_khz(uint64_t num, uint64_t den, uint32_t vcoKhz) {
    // divider = floor(4 * vco / (num / den)) = floor(4 * vco * den / num)
    return (num == 0u) ? 0u : (uint32_t)((4ull * vcoKhz) / ((4ull * vcoKhz * den) / num ? (4ull * vcoKhz * den) / num : 1u));
}
// DML DISPCLK: pclk / odm * (1 + 0.38 %) * (1 + 1 %), DFS-rounded. num / den = pclk * 10038 * 101 / (odm * 10^6).
constexpr uint32_t dml_dispclk_khz(const Mode &m, uint32_t vcoKhz) { return dfs_round_khz((uint64_t)m.pclkKhz * 10038u * 101u, (uint64_t)(m.odm ? m.odm : 1u) * 1000000u, vcoKhz); }
// DML DPP reference clock: (unsigned long)(pclk / odm * 1.0038), DFS-rounded; the plane's DPPCLK is dppref / 255 * ceil(need * 255 / dppref).
constexpr uint32_t dml_dppref_khz(const Mode &m, uint32_t vcoKhz) {
    return dfs_round_khz((uint64_t)((uint64_t)m.pclkKhz * 10038u / (10000ull * (m.odm ? m.odm : 1u))), 1u, vcoKhz);
}
constexpr uint32_t dml_dppclk_khz(const Mode &m, uint32_t vcoKhz) {
    return dml_dppref_khz(m, vcoKhz) == 0u ? 0u :
        (uint32_t)(((uint64_t)dml_dppref_khz(m, vcoKhz) * ceil_div((uint64_t)m.pclkKhz * 10038u * 255u, 10000ull * (m.odm ? m.odm : 1u) * dml_dppref_khz(m, vcoKhz))) / 255u);
}

// ---- the floor of DISPCLK / DPPCLK: never below the running clock, never below the DML value ------------------------------------------------
constexpr uint32_t kDispMinMhz = 200u, kDispMaxMhz = 600u;   // the allowlist's bounds for a DISPCLK / DPPCLK hard minimum
// curKhz: the DFS readback (0 = unreadable). The PMFW sets a DFS divider whose clock is the smallest at or above the request (the 0.0.606
// restore: 272 MHz read back as 272.727, DID 0x41), so floor(running MHz) keeps the running clock; a DML value above the running clock
// is a raise, as Linux would make it (ceil, dcn401_set_hard_min_by_freq_optimized's second try). 0 = no floor can be derived.
constexpr uint32_t disp_floor_mhz(uint32_t dmlKhz, uint32_t curKhz) {
    return curKhz == 0u ? 0u : curKhz >= dmlKhz ? curKhz / 1000u : ceil_div(dmlKhz, 1000u);
}

// ---- the level tables (GetDpmFreqByIndex, read exactly as dcn401_init_single_clock) --------------------------------------------------------
constexpr uint32_t level_count(uint32_t r) { return (r & 0x80000000u) != 0u ? 2u : (r & 0xFFu); }
constexpr uint32_t level_mhz(uint32_t r) { return r & 0xFFFFu; }
struct Levels { uint32_t n; uint32_t mhz[kMaxLevels]; };
// round_up_to_next_dpm (dml2_dpmm_dcn4.c): more than 2 values = the first level at or above the need; 2 values (fine-grained) = the need itself
// if the top level reaches it. 0 = no level fits (or no table).
constexpr uint32_t level_for(const Levels &l, uint32_t needKhz) {
    if (l.n == 0u || l.n > kMaxLevels) return 0u;
    if (l.n > 2u) {
        for (uint32_t i = 0; i < l.n; i++) if ((uint64_t)l.mhz[i] * 1000u >= needKhz) return l.mhz[i];
        return 0u;
    }
    return (uint64_t)l.mhz[l.n - 1u] * 1000u >= needKhz ? max2(ceil_div(needKhz, 1000u), l.mhz[0]) : 0u;
}
constexpr uint32_t levels_min(const Levels &l) {
    uint32_t m = 0u;
    for (uint32_t i = 0; i < l.n && i < kMaxLevels; i++) if (l.mhz[i] != 0u && (m == 0u || l.mhz[i] < m)) m = l.mhz[i];
    return m;
}
constexpr uint32_t levels_max(const Levels &l) {
    uint32_t m = 0u;
    for (uint32_t i = 0; i < l.n && i < kMaxLevels; i++) if (l.mhz[i] > m) m = l.mhz[i];
    return m;
}

// ---- the allowlist of this path: nothing else may be sent through it ---------------------------------------------------------------------
enum Refuse : uint32_t { kAllow = 0, kRefOff = 1, kRefMsg = 2, kRefParam = 3, kRefClk = 4, kRefRange = 5, kRefNoTable = 6, kRefPart = 7 };
constexpr const char *refuse_name(uint32_t r) {
    return r == kAllow ? "allowed" : r == kRefOff ? "off" : r == kRefMsg ? "message not on the floor allowlist" : r == kRefParam ? "parameter" :
           r == kRefClk ? "clock" : r == kRefRange ? "out of range" : r == kRefNoTable ? "no level table" : r == kRefPart ? "part not enabled" : "?";
}
struct Limits { uint32_t dcfMinMhz, dcfMaxMhz, uclkMinMhz; };
constexpr uint32_t kDeepSleepMinMhz = 8u, kDeepSleepMaxMhz = 100u, kDcfclkCapMhz = 600u;
constexpr uint32_t allow(uint32_t parts, uint32_t msg, uint32_t param, const Limits &l) {
    if ((parts & kPartsAll) == 0u) return kRefOff;
    switch (msg) {
    case kMsgGetSmuVersion: case kMsgGetDriverIfVersion: case kMsgGetMsgHeaderVersion: case kMsgReturnHardMinStatus:
        return param == 0u ? kAllow : kRefParam;
    case kMsgGetDpmFreqByIndex: {
        const uint32_t clk = (param >> 16) & 0xFFu, idx = param & 0xFFFFu;
        if ((param >> 24) != 0u) return kRefParam;
        if (clk != kClkDcfclk && clk != kClkUclk) return kRefClk;
        return (idx < kMaxLevels || idx == kIndexAll) ? kAllow : kRefParam;
    }
    case kMsgNumOfDisplays:
        if ((parts & kPartDisplays) == 0u) return kRefPart;
        return param == 1u ? kAllow : kRefParam;
    case kMsgSetMinDeepSleepDcfclk:
        if ((parts & kPartDeepSleep) == 0u) return kRefPart;
        return (param >= kDeepSleepMinMhz && param <= kDeepSleepMaxMhz) ? kAllow : kRefRange;
    case kMsgSetUclkPstateAllow:
        if ((parts & kPartPstateAllow) == 0u) return kRefPart;
        return param == 1u ? kAllow : kRefParam;      // never 0: this path never forbids a switch
    case kMsgSetHardMinByFreq: {
        const uint32_t clk = param >> 16, mhz = param & 0xFFFFu;
        if (clk == kClkDcfclk) {
            if ((parts & kPartDcfclk) == 0u) return kRefPart;
            if (l.dcfMinMhz == 0u || l.dcfMaxMhz == 0u) return kRefNoTable;
            return (mhz >= l.dcfMinMhz && mhz <= l.dcfMaxMhz && mhz <= kDcfclkCapMhz) ? kAllow : kRefRange;
        }
        if (clk == kClkUclk) {
            if ((parts & kPartUclk) == 0u) return kRefPart;
            if (l.uclkMinMhz == 0u) return kRefNoTable;
            return mhz == l.uclkMinMhz ? kAllow : kRefRange;   // the lowest level only: never a pin from this path
        }
        if (clk == kClkDispclk || clk == kClkDppclk) {
            if ((parts & kPartDispDpp) == 0u) return kRefPart;
            return (mhz >= kDispMinMhz && mhz <= kDispMaxMhz) ? kAllow : kRefRange;
        }
        return kRefClk;
    }
    default: return kRefMsg;   // SetHardMax, transfer tables, DRAM addresses, FCLK, CAB, DRR, idle/active UCLK-FCLK, PstateAllow(0), ...
    }
}
constexpr uint32_t param_hardmin(uint32_t clk, uint32_t mhz) { return (clk << 16) | (mhz & 0xFFFFu); }

// ---- the plan: what will be sent, in Linux's order ---------------------------------------------------------------------------------------
struct Step { uint32_t msg, param, clk; bool hardMin; };
constexpr uint32_t kMaxSteps = 8u;
struct Plan {
    uint32_t n;
    Step s[kMaxSteps];
    uint32_t dcfMhz, deepSleepMhz, uclkMhz, dispMhz, dppMhz;           // 0 = not planned
    uint32_t dmlDispKhz, dmlDppKhz, dcfNeedKhz, deepSleepKhz;          // what DML says (for the log)
    uint32_t skipped;                                                  // parts asked for that could not be planned
};
struct PlanIn {
    uint32_t parts;
    Levels dcf, uclk;
    uint32_t curDispKhz, curDppKhz;       // the DFS readback (0 = unreadable)
    uint32_t smuVer;                       // DALSMC GetSmuVersion
    Mode mode;
    uint32_t vcoKhz;
};
constexpr void plan_push(Plan &p, uint32_t msg, uint32_t param, uint32_t clk, bool hm) {
    if (p.n < kMaxSteps) { p.s[p.n] = Step{ msg, param, clk, hm }; p.n++; }
}
constexpr Plan make_plan(const PlanIn &in) {
    Plan p{};
    p.dmlDispKhz = dml_dispclk_khz(in.mode, in.vcoKhz);
    p.dmlDppKhz = dml_dppclk_khz(in.mode, in.vcoKhz);
    p.dcfNeedKhz = dcfclk_need_khz(in.mode);
    p.deepSleepKhz = deep_sleep_khz(in.mode);
    const uint32_t parts = in.parts & kPartsAll;
    if (parts & kPartDisplays) plan_push(p, kMsgNumOfDisplays, 1u, 0u, false);
    if (parts & kPartDcfclk) {
        const uint32_t dcf = level_for(in.dcf, p.dcfNeedKhz);
        if (dcf != 0u) { p.dcfMhz = dcf; plan_push(p, kMsgSetHardMinByFreq, param_hardmin(kClkDcfclk, dcf), kClkDcfclk, true); }
        else p.skipped |= kPartDcfclk;
    }
    if (parts & kPartDeepSleep) {
        const uint32_t ds = deep_sleep_mhz(in.mode);
        if (ds >= kDeepSleepMinMhz && ds <= kDeepSleepMaxMhz) { p.deepSleepMhz = ds; plan_push(p, kMsgSetMinDeepSleepDcfclk, ds, 0u, false); }
        else p.skipped |= kPartDeepSleep;
    }
    if (parts & kPartPstateAllow) plan_push(p, kMsgSetUclkPstateAllow, 1u, 0u, false);
    if (parts & kPartUclk) {
        const uint32_t u = levels_min(in.uclk);
        if (u != 0u && in.smuVer < kIdleDpmSmuVer) { p.uclkMhz = u; plan_push(p, kMsgSetHardMinByFreq, param_hardmin(kClkUclk, u), kClkUclk, true); }
        else p.skipped |= kPartUclk;
    }
    if (parts & kPartDispDpp) {
        const uint32_t d = disp_floor_mhz(p.dmlDispKhz, in.curDispKhz), q = disp_floor_mhz(p.dmlDppKhz, in.curDppKhz);
        if (d >= kDispMinMhz && d <= kDispMaxMhz && q >= kDispMinMhz && q <= kDispMaxMhz) {
            p.dispMhz = d; p.dppMhz = q;
            plan_push(p, kMsgSetHardMinByFreq, param_hardmin(kClkDispclk, d), kClkDispclk, true);   // dcn401_build_update_display_clocks_sequence: DISPCLK first
            plan_push(p, kMsgSetHardMinByFreq, param_hardmin(kClkDppclk, q), kClkDppclk, true);
        } else p.skipped |= kPartDispDpp;
    }
    return p;
}
// Every planned step passes the allowlist (the kernel checks again before each send).
constexpr bool plan_allowed(const Plan &p, uint32_t parts, const Limits &l) {
    for (uint32_t i = 0; i < p.n; i++) if (allow(parts, p.s[i].msg, p.s[i].param, l) != kAllow) return false;
    return true;
}

// ---- the verdict of the run ------------------------------------------------------------------------------------------------------------
enum Verdict : uint32_t {
    kVNotRun = 0, kVOff = 1, kVSent = 2, kVPartial = 3, kVMailbox = 4, kVHeader = 5, kVNoSmu = 6, kVClocks = 7, kVBusy = 8, kVRefused = 9, kVDropped = 10,
    kVMode = 11
};
constexpr const char *verdict_name(uint32_t v) {
    return v == kVNotRun ? "not run" : v == kVOff ? "off (navi48-dalfloor=0)" : v == kVSent ? "sent, every message OK" :
           v == kVPartial ? "sent, some messages not OK (see the steps)" : v == kVMailbox ? "DAL mailbox not ready or timed out: stopped" :
           v == kVHeader ? "DALSMC header version is not 1: nothing sent" : v == kVNoSmu ? "SMU features not enabled by this boot: nothing sent" :
           v == kVClocks ? "DISPCLK/DPPCLK readback unusable: display clock floors skipped" : v == kVBusy ? "the DAL mailbox is owned by a DAL step or a clock hold: nothing sent" :
           v == kVRefused ? "a planned message failed the allowlist: nothing sent" : v == kVDropped ? "a display clock read below its start after the floors: raised back" :
           v == kVMode ? "the lit timing is not 2560x1440 H_TOTAL 2720 V_TOTAL 1525/3050: nothing sent" : "?";
}
// After the DISPCLK / DPPCLK floors: kept (both at or above the start), or one fell (the corrective raise asks ceil(start MHz)).
constexpr bool clocks_kept(uint32_t startDisp, uint32_t startDpp, uint32_t nowDisp, uint32_t nowDpp) {
    return nowDisp != 0u && nowDpp != 0u && nowDisp >= startDisp && nowDpp >= startDpp;
}

// =========================================================================================================================================
// The clock trace (boot-time, read-only): samples, the ring, the burst classification around ufmon events.
// =========================================================================================================================================
enum TClk : uint32_t { kTUclk = 0, kTFclk = 1, kTDcf = 2, kTDisp = 3, kTDpp = 4, kTSoc = 5, kTClks = 6 };
constexpr const char *tclk_name(uint32_t i) {
    return i == kTUclk ? "UCLK" : i == kTFclk ? "FCLK" : i == kTDcf ? "DCFCLK" : i == kTDisp ? "DISPCLK" : i == kTDpp ? "DPPCLK" : i == kTSoc ? "SOCCLK" : "?";
}
struct Sample { uint64_t ms; uint32_t mhz[kTClks]; uint32_t dfsDispKhz, dfsDppKhz; bool ok; bool pinned; };
constexpr uint32_t kRing = 32u;
constexpr uint64_t kSamplePeriodMs = 500u, kPreMs = 1500u, kPostMs = 1000u;
constexpr uint32_t kDefaultTraceS = 600u, kMaxTraceS = 3600u;
// navi48-clklog: absent = kDefaultTraceS seconds after the floors; 0 = off; N = N seconds (capped at kMaxTraceS).
constexpr uint32_t trace_seconds(bool present, uint32_t v) { return !present ? kDefaultTraceS : v > kMaxTraceS ? kMaxTraceS : v; }
// Burst flags (which clock moved in the window, by the metrics; the DFS readback counts for DISPCLK / DPPCLK too).
enum BFlag : uint32_t {
    kBUclk = 1u << kTUclk, kBFclk = 1u << kTFclk, kBDcf = 1u << kTDcf, kBDisp = 1u << kTDisp, kBDpp = 1u << kTDpp, kBSoc = 1u << kTSoc,
    kBDcfBelowFloor = 0x40u, kBFewSamples = 0x80u, kBPinned = 0x100u
};
struct Burst { uint64_t atMs; uint32_t events; uint32_t flags; uint32_t nSamples; uint32_t lo[kTClks], hi[kTClks]; };
struct Trace {
    Sample ring[kRing];
    uint32_t head, count;                   // head = the next slot
    uint64_t samples, failures;
    uint32_t lo[kTClks], hi[kTClks];        // over the whole trace (0 = none yet)
    uint64_t moves[kTClks];                 // sample-to-sample changes
    uint64_t fclkMovesPinned, uclkMovesPinned, dcfBelowFloor;
    uint32_t dcfFloorMhz;                   // what the floors asked (0 = none)
    bool pending; Burst cur;                // the burst being collected
    Burst last;                             // the last classified burst
    uint64_t bursts, events, bUclk, bFclk, bFclkOnly, bDcf, bDispDpp, bNone, bPinned, bFew;
};
inline void trace_init(Trace &t, uint32_t dcfFloorMhz) { t = Trace{}; t.dcfFloorMhz = dcfFloorMhz; }
inline const Sample *trace_at(const Trace &t, uint32_t back) {   // back 0 = newest
    if (back >= t.count) return nullptr;
    return &t.ring[(t.head + kRing - 1u - back) % kRing];
}
// Add one sample: the extremes, the moves (against the previous good sample).
inline void trace_add(Trace &t, const Sample &s) {
    if (!s.ok) { t.failures++; return; }
    const Sample *prev = trace_at(t, 0);
    t.ring[t.head] = s; t.head = (t.head + 1u) % kRing; if (t.count < kRing) t.count++;
    t.samples++;
    for (uint32_t i = 0; i < kTClks; i++) {
        if (s.mhz[i] != 0u && (t.lo[i] == 0u || s.mhz[i] < t.lo[i])) t.lo[i] = s.mhz[i];
        if (s.mhz[i] > t.hi[i]) t.hi[i] = s.mhz[i];
        if (prev != nullptr && prev->mhz[i] != s.mhz[i]) {
            t.moves[i]++;
            if (s.pinned && i == kTFclk) t.fclkMovesPinned++;
            if (s.pinned && i == kTUclk) t.uclkMovesPinned++;
        }
    }
    if (t.dcfFloorMhz != 0u && s.mhz[kTDcf] != 0u && s.mhz[kTDcf] < t.dcfFloorMhz) t.dcfBelowFloor++;
}
// n underflow events counted at nowMs: open a burst, or extend the open one.
inline void trace_event(Trace &t, uint64_t nowMs, uint64_t n, bool pinned) {
    if (n == 0u) return;
    t.events += n;
    if (!t.pending) { t.pending = true; t.cur = Burst{}; t.cur.atMs = nowMs; }
    t.cur.events += (uint32_t)(n > 1000u ? 1000u : n);
    if (pinned) t.cur.flags |= kBPinned;
}
// The classification of the open burst over the ring samples in [atMs - kPreMs, atMs + kPostMs].
inline Burst trace_classify(const Trace &t, const Burst &b) {
    Burst r = b;
    for (uint32_t i = 0; i < kTClks; i++) { r.lo[i] = 0u; r.hi[i] = 0u; }
    uint32_t dLo = 0u, dHi = 0u, pLo = 0u, pHi = 0u;
    r.nSamples = 0u;
    for (uint32_t k = 0; k < t.count; k++) {
        const Sample *s = trace_at(t, k);
        if (s == nullptr || s->ms + kPreMs < b.atMs || s->ms > b.atMs + kPostMs) continue;
        r.nSamples++;
        for (uint32_t i = 0; i < kTClks; i++) {
            if (r.lo[i] == 0u || s->mhz[i] < r.lo[i]) r.lo[i] = s->mhz[i];
            if (s->mhz[i] > r.hi[i]) r.hi[i] = s->mhz[i];
        }
        if (dLo == 0u || s->dfsDispKhz < dLo) dLo = s->dfsDispKhz;
        if (s->dfsDispKhz > dHi) dHi = s->dfsDispKhz;
        if (pLo == 0u || s->dfsDppKhz < pLo) pLo = s->dfsDppKhz;
        if (s->dfsDppKhz > pHi) pHi = s->dfsDppKhz;
        if (t.dcfFloorMhz != 0u && s->mhz[kTDcf] != 0u && s->mhz[kTDcf] < t.dcfFloorMhz) r.flags |= kBDcfBelowFloor;
    }
    for (uint32_t i = 0; i < kTClks; i++) if (r.lo[i] != r.hi[i]) r.flags |= 1u << i;
    if (dLo != dHi) r.flags |= kBDisp;
    if (pLo != pHi) r.flags |= kBDpp;
    if (r.nSamples < 3u) r.flags |= kBFewSamples;
    return r;
}
// Called after each sample: when the open burst's post window has a sample, classify it and count it. Returns true (and *out) when it did.
inline bool trace_settle(Trace &t, uint64_t nowMs, Burst *out) {
    if (!t.pending || nowMs < t.cur.atMs + kPostMs) return false;
    const Burst r = trace_classify(t, t.cur);
    t.pending = false;
    t.last = r;
    t.bursts++;
    const bool h1 = (r.flags & (kBDcf | kBDcfBelowFloor)) != 0u, h1d = (r.flags & (kBDisp | kBDpp)) != 0u;
    const bool h2 = (r.flags & kBFclk) != 0u, h3 = (r.flags & kBUclk) != 0u;
    if (h3) t.bUclk++;
    if (h2) t.bFclk++;
    if (h2 && !h3) t.bFclkOnly++;
    if (h1) t.bDcf++;
    if (h1d) t.bDispDpp++;
    if (!h1 && !h1d && !h2 && !h3) t.bNone++;
    if (r.flags & kBPinned) t.bPinned++;
    if (r.flags & kBFewSamples) t.bFew++;
    if (out != nullptr) *out = r;
    return true;
}
// The words for the registry: what the bursts so far point at.
inline const char *trace_lean(const Trace &t) {
    if (t.bursts == 0u) return "no underflow burst traced";
    if (t.bDcf + t.bDispDpp > 0u && t.bDcf + t.bDispDpp >= t.bUclk && t.bDcf + t.bDispDpp >= t.bFclk) return "H1 (a display clock moved or DCFCLK under its floor)";
    if (t.bFclkOnly > 0u && t.bFclkOnly >= t.bUclk) return "H2 (FCLK moved without UCLK)";
    if (t.bUclk > 0u) return "H3 (UCLK switched in the window)";
    return "none of the sampled clocks moved (H4, or a switch shorter than the sampling)";
}

}  // namespace n48dalfloor
