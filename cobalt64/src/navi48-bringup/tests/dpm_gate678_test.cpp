// 0.0.678 host test: GFXCLK under PMFW DPM behind the idle gate (amd/dpm_gate_pure.h). The decision table, the gate threshold, the thermal
// restore target, the message ids and the workload bit against Linux (smu_v14_0_2_ppsmc.h, smu14_driver_if_v14_0.h, smu_v14_0_2_ppt.c,
// smu_v14_0.c), and source pins on the kernel glue (dpm_boot.cpp, Navi48Bringup.cpp, smu_v14_0.cpp, n4x_safety.cpp).
// Build: clang++ -std=c++17 -I src tests/dpm_gate678_test.cpp ; run: ./a.out <kernel source dir> <linux drivers/gpu/drm/amd>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include <regex>
#include "amd/dpm_gate_pure.h"
#include "amd/cp_census_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static long define_of(const std::string &t, const std::string &name) {
    std::smatch m; std::regex r("#define " + name + "\\s+(0x[0-9A-Fa-f]+|[0-9]+)L?\\b");
    return std::regex_search(t, m, r) ? std::stol(m[1].str(), nullptr, 0) : -1;
}

using namespace n48dpm;

static void test_pure() {
    // the gate threshold: idle in at least 75 % of 64 samples
    expect(gate_pass(0, 64) && gate_pass(16, 64) && !gate_pass(17, 64) && !gate_pass(64, 64), "64 samples: pass up to 16 busy (25 %)");
    expect(!gate_pass(0, 0) && !gate_pass(0, 63) && !gate_pass(65, 64), "too few samples, or more busy than samples: fail");
    // the samples of 0.0.677 (2026-11-23 boot marks): every sample busy -> the gate keeps the clamp
    expect(sample_busy(0xa800382cu, 0x14100000u, 0x88000001u), "the stuck fetcher (CP_CPF_STATUS 0x88000001) is busy");
    expect(sample_busy(0u, 0u, 0x80000000u) && sample_busy(0u, 0x10000000u, 0u) && sample_busy(0x80000000u, 0u, 0u), "each busy bit alone counts");
    expect(!sample_busy(0x0000382cu, 0x00000000u, 0u), "idle GRBM_STATUS (0x382c, as after CPInit) and CPF_STATUS 0 are idle");
    expect(!sample_busy(0u, 0x04000000u, 0x00000001u) , "RLC_BUSY alone or POST_WPTR alone (without CPF_BUSY) is not counted");
    uint32_t busy = 0;
    for (int i = 0; i < 64; i++) busy += sample_busy(0xa800382cu, 0x14100000u, 0x88000001u) ? 1u : 0u;
    expect(!gate_pass(busy, 64), "0.0.677's stuck state fails the gate");
    // the decision
    expect(decide(true, true, true, true, false) == kApplied, "default + full path + idle + no thermal clamp -> applied");
    expect(decide(false, true, true, true, false) == kOffBootArg, "navi48-dpm=0 -> clamp stays");
    expect(decide(true, false, true, true, false) == kNoClamp && decide(false, false, false, false, true) == kNoClamp, "navi48-idle-clamp=0 -> no clamp, no gate");
    expect(decide(true, true, false, true, false) == kNotFullPath, "ladder incomplete -> clamp stays");
    expect(decide(true, true, true, false, false) == kGateBusy, "busy fetcher -> clamp stays");
    expect(decide(true, true, true, true, true) == kHeldThermal, "thermal clamp in force -> deferred");
    expect(dpm_wanted(false, 0) && dpm_wanted(true, 1) && !dpm_wanted(true, 0), "navi48-dpm: on unless 0");
    // the states
    expect(dpm_state(0) == kStateAuto && dpm_state(2500) == kStateBootCap, "DPM: Auto, or the navi48-gfxmax cap");
    expect(clamp_state(0) == kStateLow && clamp_state(1500) == kStateBootCap, "the boot clamp: Low, or the cap");
    // the thermal restore target (task 4): DPM after a release once DPM is applied or deferred, never the 500 MHz clamp then
    expect(restore_state(kApplied, 0) == kStateAuto && restore_state(kHeldThermal, 0) == kStateAuto, "restore to Auto (DPM) after a TRIP release");
    expect(restore_state(kApplied, 2000) == kStateBootCap, "restore to the cap with navi48-gfxmax");
    expect(restore_state(kGateBusy, 0) == kStateLow && restore_state(kOffBootArg, 0) == kStateLow && restore_state(kNotFullPath, 0) == kStateLow &&
           restore_state(kApplyFailed, 0) == kStateLow, "clamp kept -> restore to the clamp");
    expect(restore_state(kNoClamp, 0) == kStateAuto, "no clamp -> Auto (as 0.0.675)");
    expect(workload_mask_bootup_default() == 0x1u && kMsgSetWorkloadMask == 0x24u, "SetWorkloadMask(0x24, 0x1)");
    expect(kAutoSoftMax == 0xFFFFu && kAutoSoftMin == 0u, "AUTO: soft max 0xffff, soft min 0");
    for (uint32_t v = kNotRun; v <= kApplyFailed; v++) expect(std::string(verdict_name(v)) != "?", "every verdict has a name");
    // the gate reads the same unbanked registers as the marks
    expect(std::string(n48cpc::kMark[n48cpc::kGrbmStatus].name) == "GRBM_STATUS" && std::string(n48cpc::kMark[n48cpc::kGrbmStatus2].name) == "GRBM_STATUS2" &&
           std::string(n48cpc::kMark[n48cpc::kCpfStatus].name) == "CP_CPF_STATUS", "the gate's registers are the marks' unbanked ones");
    expect(kGateSamples * kGateGapUs == 64000u, "the gate takes 64 ms");
}

static void test_linux(const char *amd) {
    if (!amd) { printf("(Linux cross-check skipped)\n"); return; }
    const std::string a = amd;
    const std::string ppsmc = slurp(a + "/pm/swsmu/inc/pmfw_if/smu_v14_0_2_ppsmc.h"), drv = slurp(a + "/pm/swsmu/inc/pmfw_if/smu14_driver_if_v14_0.h");
    const std::string ppt = slurp(a + "/pm/swsmu/smu14/smu_v14_0_2_ppt.c"), v14 = slurp(a + "/pm/swsmu/smu14/smu_v14_0.c"), sm = slurp(a + "/pm/swsmu/amdgpu_smu.c");
    const std::string sh = slurp(a + "/include/asic_reg/gc/gc_12_0_0_sh_mask.h");
    expect(!ppsmc.empty() && !drv.empty() && !ppt.empty() && !v14.empty() && !sm.empty() && !sh.empty(), "Linux sources read");
    expect(define_of(ppsmc, "PPSMC_MSG_SetWorkloadMask") == (long)kMsgSetWorkloadMask, "PPSMC_MSG_SetWorkloadMask = 0x24");
    expect(define_of(ppsmc, "PPSMC_MSG_SetSoftMinByFreq") == 0x19 && define_of(ppsmc, "PPSMC_MSG_SetSoftMaxByFreq") == 0x1A &&
           define_of(ppsmc, "PPSMC_MSG_GetMinDpmFreq") == 0x1D && define_of(ppsmc, "PPSMC_MSG_GetMaxDpmFreq") == 0x1E, "the clock message ids");
    expect(define_of(drv, "WORKLOAD_PPLIB_DEFAULT_BIT") == (long)kWorkloadPplibDefaultBit, "WORKLOAD_PPLIB_DEFAULT_BIT = 0");
    expect(ppt.find("WORKLOAD_MAP(PP_SMC_POWER_PROFILE_BOOTUP_DEFAULT,\tWORKLOAD_PPLIB_DEFAULT_BIT)") != std::string::npos,
           "smu_v14_0_2 maps BOOTUP_DEFAULT to WORKLOAD_PPLIB_DEFAULT_BIT");
    expect(ppt.find("ret = smu_cmn_send_smc_msg_with_param(smu, SMU_MSG_SetWorkloadMask,\n\t\t\t\t\t      backend_workload_mask, NULL);") != std::string::npos,
           "smu_v14_0_2_set_power_profile_mode sends SetWorkloadMask(backend mask)");
    expect(sm.find("PP_SMC_POWER_PROFILE_BOOTUP_DEFAULT") != std::string::npos, "the default profile is BOOTUP_DEFAULT");
    // AUTO = automatic: 0xffff / 0
    expect(v14.find("param = (uint32_t)((clk_id << 16) | 0xffff);") != std::string::npos && v14.find("param = (uint32_t)((clk_id << 16) | 0);") != std::string::npos,
           "smu_v14_0_set_soft_freq_limited_range(automatic): max 0xffff, min 0");
    expect(v14.find("case AMD_DPM_FORCED_LEVEL_AUTO:") != std::string::npos && v14.find("auto_level = true;") != std::string::npos, "AUTO uses automatic");
    // GameClockAc only labels the reported table
    const size_t g = ppt.find("skutable->DriverReportedClocks.GameClockAc;");
    expect(g != std::string::npos && ppt.rfind("dpm_table->dpm_levels[dpm_table->count - 1].value =", g) != std::string::npos,
           "GameClockAc overwrites the reported top dpm level only");
    expect(define_of(sh, "GRBM_STATUS__GUI_ACTIVE__SHIFT") == kGuiActiveBit && define_of(sh, "GRBM_STATUS2__CPF_BUSY__SHIFT") == kGrbm2CpfBusyBit &&
           define_of(sh, "CP_CPF_STATUS__CPF_BUSY__SHIFT") == kCpfStatusCpfBusyBit, "the gate's bit positions");
}

static void test_sources(const char *dir) {
    if (!dir) { printf("(source pins skipped)\n"); return; }
    const std::string root = dir;
    const std::string dpm = slurp(root + "/src/amd/dpm_boot.cpp"), br = slurp(root + "/src/Navi48Bringup.cpp"), smu = slurp(root + "/src/amd/smu_v14_0.cpp");
    const std::string saf = slurp(root + "/src/amd/n4x_safety.cpp"), init = slurp(root + "/src/amd/amdgpu_init.cpp");
    expect(!dpm.empty() && !br.empty() && !smu.empty() && !saf.empty() && !init.empty(), "sources read");
    // order in dpm_boot_gate: lock, decide, restore target, then the clock message, then the workload mask
    const size_t lock = dpm.find("SmuSeq seq;"), dec = dpm.find("gDpm.verdict = n48dpm::decide("), rs = dpm.find("n4xs::set_restore_state(gDpm.restore);", dec);
    const size_t clk = dpm.find("gDpm.clockKr = smu_set_power_state(dev, st);"), wl = dpm.find("smu_send_msg_with_param(dev, n48dpm::kMsgSetWorkloadMask");
    expect(lock < dec && dec < rs && rs < clk && clk < wl, "lock -> decide -> restore target -> clocks -> SetWorkloadMask");
    expect(dpm.find("if (!seq.held) {") != std::string::npos, "nothing sent without the mailbox lock");
    expect(dpm.find("n4xs::clamped()") != std::string::npos, "a thermal clamp in force defers DPM");
    expect(dpm.find("smu_set_power_state(dev, n48dpm::clamp_state(capMhz))") != std::string::npos, "a refused clock message re-sends the clamp");
    expect(dpm.find("PPCLK::UCLK") == std::string::npos && dpm.find("SetHardMin") == std::string::npos && dpm.find("PPCLK::GFXCLK << 16") != std::string::npos, "GFXCLK only: the UCLK pin is not touched");
    expect(dpm.find("WREG32") == std::string::npos, "the gate writes no register");
    expect(dpm.find("PE_parse_boot_argn(\"navi48-dpm\", &v, sizeof(v));") != std::string::npos, "navi48-dpm");
    // runStages: the gate is the last step, after native S1b, and publishes Navi48,Dpm
    const size_t s1b = br.find("(void)amdgpu::native_s1b_run(ctx);"), gate = br.find("(void)amdgpu::dpm_boot_gate(dev, ctx.idleClamp, dpmPath, amdgpu::smu_gfx_boot_cap());");
    expect(s1b != std::string::npos && gate != std::string::npos && s1b < gate, "the DPM gate runs after native S1b");
    expect(br.find("setProperty(\"Navi48,Dpm\", t);", gate) != std::string::npos, "ioreg Navi48,Dpm");
    expect(br.find("amdgpu::cp_busy_mark(dev, \"after native S1b\");") < gate, "a mark after native S1b, before the gate");
    expect(br.find("n4xs::set_restore_state(ctx.idleClamp ? amdgpu::smu_gfx_boot_state() : amdgpu::SMUPowerState::Auto);") < s1b,
           "until the gate, the restore target is the boot clamp (as 0.0.677)");
    // the idle clamp is still applied at the end of the ladder (DPM replaces it only through the gate)
    expect(init.find("kern_return_t pr = smu_set_power_state(*ctx.dev, smu_gfx_boot_state());") != std::string::npos, "the boot clamp stays the ladder's default");
    // SMUPowerState::Auto sends what Linux AUTO sends
    const size_t a = smu.find("case SMUPowerState::Auto:");
    expect(a != std::string::npos && smu.find("min_mhz = 0;", a) < smu.find("break;", a) && smu.find("max_mhz = 0xFFFFu;", a) < smu.find("break;", a),
           "Auto = SetSoftMax 0xffff + SetSoftMin 0");
    expect(smu.find("(state == SMUPowerState::Auto) ||") != std::string::npos, "Auto sends the soft min");
    // the watchdog's RESTORE sends the restore target (the DPM policy once set), its CLAMP the PMFW minimum
    expect(saf.find("const uint32_t state = act == kActClamp ? (uint32_t)amdgpu::SMUPowerState::Low : __atomic_load_n(&gRestoreState, __ATOMIC_ACQUIRE);") != std::string::npos,
           "the thermal RESTORE sends set_restore_state's target");
}

int main(int argc, char **argv) {
    test_pure();
    test_sources(argc > 1 ? argv[1] : nullptr);
    test_linux(argc > 2 ? argv[2] : nullptr);
    printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
