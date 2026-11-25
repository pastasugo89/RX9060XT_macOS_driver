// 0.0.682 host test: the opt-in soft recovery (amd/softrec_pure.h): the decision table, "once per stall", "never latch for a non-WindowServer
// owner", the SQ_CMD kill value against GC 12 (Linux v7.3 gc_12_0_0 headers, and the Linux 6.14 gfx_v12_0_ring_soft_recovery encoding), the kill
// sequence against a register recorder, and source pins on native_s1c.cpp.
// Build: clang++ -std=c++17 -I src tests/softrec682_test.cpp -o /tmp/sr682 ; run: /tmp/sr682 <kernel source dir> <linux-v7.3 drivers/gpu/drm/amd> [<6.14 gfx_v12_0.c>]
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <regex>
#include "amd/softrec_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const std::string &what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what.c_str()); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static long define_of(const std::string &t, const std::string &name) {
    std::smatch m; std::regex r("#define " + name + "\\s+(0x[0-9A-Fa-f]+|[0-9]+)L?\\b");
    return std::regex_search(t, m, r) ? std::stol(m[1].str(), nullptr, 0) : -1;
}
using namespace n48softrec;

static Input base() { return Input{ true, true, true, true, false, 100ull, 9u, true, 8u, 0ull }; }

static void test_decide() {
    Input in = base();
    expect(decide(in) == kKill && !may_latch(kKill), "an app's stall: kill, never latch");
    in.on = false; expect(decide(in) == kOff && may_latch(kOff), "switch off: today's path");
    in = base(); in.multi = false; expect(decide(in) == kOff, "multisession off: today's path");
    in = base(); in.guiltyKnown = false; expect(decide(in) == kNotUser && may_latch(kNotUser), "unknown owner: today's path (latch)");
    in = base(); in.userSession = false; expect(decide(in) == kNotUser, "kernel probe / closed session: today's path");
    in = base(); in.guiltyIsWs = true; expect(decide(in) == kWsGuilty && may_latch(kWsGuilty), "WindowServer guilty: today's path");
    in = base(); in.actedSeq = 100ull; expect(decide(in) == kActed && !may_latch(kActed), "the same stall again: nothing more, no latch (once per stall)");
    in = base(); in.actedSeq = 99ull; expect(decide(in) == kKill, "a NEW stall (another guilty seqno) gets its own attempt");
    in = base(); in.guiltyVmid = 7u; expect(decide(in) == kBadVmid && !may_latch(kBadVmid), "VMID 7 (the MES range) is never killed, and still no latch");
    in = base(); in.guiltyVmid = UINT32_MAX; expect(decide(in) == kBadVmid, "no binding found: no kill");
    in = base(); in.guiltyVmid = 8u; in.wsVmid = 8u; expect(decide(in) == kBadVmid, "never the VMID WindowServer holds");
    in = base(); in.guiltyVmid = 8u; in.wsBound = false; expect(decide(in) == kKill, "VMID 8 is killable when WindowServer does not hold it");
    expect(g2_after(kKill, false) && !g2_after(kKill, true) && g2_after(kBadVmid, false) && !g2_after(kActed, false), "the G2 queue reset follows only a kill that did not move the ring or an unkillable VMID");
    // exhaustive: a stall owned by a non-WindowServer user session NEVER latches with the switch on
    bool never = true;
    for (int k = 0; k < 2; k++) for (int u = 0; u < 2; u++) for (uint32_t v = 0; v < 17; v++) for (int wb = 0; wb < 2; wb++) for (uint32_t wv = 0; wv < 17; wv++) for (int a = 0; a < 2; a++) {
        Input x{ true, true, k != 0, u != 0, false, 50ull, v, wb != 0, wv, a ? 50ull : 0ull };
        const uint32_t d = decide(x);
        if (k && u && may_latch(d)) never = false;
        if (d == kKill && (!user_vmid(v) || (wb && wv == v))) never = false;
    }
    expect(never, "exhaustive: no latch for a known non-WindowServer user owner; a kill only for 8..15 and never WindowServer's VMID");
}

static void test_encoding(const std::string &linuxAmd, const std::string &g614) {
    expect(kill_value(9) == 0x90000093u && kill_value(15) == 0xF0000093u && kill_value(8) == 0x80000093u, "kill values for VMIDs 8, 9, 15");
    expect(kill_value(0) == 0u && kill_value(7) == 0u && kill_value(16) == 0u, "no kill value outside 8..15 (never a broadcast without CHECK_VMID)");
    const Fault f = decode_fault(0x00940211u);
    expect(f.vmid == 9u && f.mapping == false && f.perm == 1u && f.cid == 1u && f.more && fault_latched(f), "fault status decode");
    if (linuxAmd.empty()) return;
    const std::string off = slurp(linuxAmd + "/include/asic_reg/gc/gc_12_0_0_offset.h"), sh = slurp(linuxAmd + "/include/asic_reg/gc/gc_12_0_0_sh_mask.h");
    expect(define_of(off, "regSQ_CMD") == (long)kSqCmd && define_of(off, "regSQ_CMD_BASE_IDX") == (long)kSqCmdBaseIdx, "SQ_CMD offset / base idx = GC 12");
    expect(define_of(off, "regRLC_SAFE_MODE") == (long)kRlcSafeMode && define_of(off, "regRLC_SAFE_MODE_BASE_IDX") == (long)kRlcSafeModeBaseIdx, "RLC_SAFE_MODE = GC 12");
    expect(define_of(off, "regRLC_CNTL") == (long)kRlcCntl && define_of(off, "regRLC_CNTL_BASE_IDX") == (long)kRlcCntlBaseIdx, "RLC_CNTL = GC 12");
    expect(define_of(off, "regGCVM_L2_PROTECTION_FAULT_STATUS_LO32") == (long)kFaultStatusLo32, "fault status offset = GC 12");
    expect(define_of(sh, "SQ_CMD__CMD__SHIFT") == 0 && define_of(sh, "SQ_CMD__MODE__SHIFT") == 4 && define_of(sh, "SQ_CMD__CHECK_VMID__SHIFT") == 7 &&
           define_of(sh, "SQ_CMD__VM_ID__SHIFT") == (long)kSqCmdVmidShift && define_of(sh, "SQ_CMD__VM_ID_MASK") == 0xF0000000L, "SQ_CMD fields = GC 12");
    expect(define_of(sh, "GCVM_L2_PROTECTION_FAULT_STATUS_LO32__VMID__SHIFT") == 20 && define_of(sh, "GCVM_L2_PROTECTION_FAULT_STATUS_LO32__CID__SHIFT") == 9 &&
           define_of(sh, "GCVM_L2_PROTECTION_FAULT_STATUS_LO32__MAPPING_ERROR__SHIFT") == 8, "fault status fields = GC 12");
    expect(define_of(sh, "RLC_SAFE_MODE__CMD_MASK") == 1 && define_of(sh, "RLC_SAFE_MODE__MESSAGE__SHIFT") == 1, "RLC_SAFE_MODE CMD / MESSAGE = GC 12");
    const std::string v73 = slurp(linuxAmd + "/amdgpu/gfx_v12_0.c");
    expect(v73.find(".soft_recovery") == std::string::npos && v73.find("amdgpu_gfx_mes_reset_queue(ring, vmid, timedout_fence, use_mmio)") != std::string::npos,
           "Linux v7.3 gfx_v12_0 has no soft_recovery and resets the queue through MES (documented risk: the kill is the 6.14 behaviour)");
    if (!g614.empty()) {
        const std::string o = slurp(g614);
        expect(o.find("value = REG_SET_FIELD(value, SQ_CMD, CMD, 0x03);") != std::string::npos && o.find("value = REG_SET_FIELD(value, SQ_CMD, MODE, 0x01);") != std::string::npos &&
               o.find("value = REG_SET_FIELD(value, SQ_CMD, CHECK_VMID, 1);") != std::string::npos && o.find("amdgpu_gfx_rlc_enter_safe_mode(adev, 0);\n\tWREG32_SOC15(GC, 0, regSQ_CMD, value);") != std::string::npos,
               "Linux 6.14 gfx_v12_0_ring_soft_recovery: CMD 3, MODE 1, CHECK_VMID, inside the RLC safe-mode bracket");
    }
}

struct Rec {
    std::vector<std::string> log;
    uint32_t rlcCntl = 1u, safeAckAfter = 2u, safePolls = 0u, movesAfterWrites = 3u, writes = 0u;
    uint32_t rd(uint32_t bi, uint32_t reg) {
        char b[64]; snprintf(b, sizeof b, "rd %u:%#x", bi, reg); log.push_back(b);
        if (reg == kRlcCntl) return rlcCntl;
        if (reg == kRlcSafeMode) return ++safePolls >= safeAckAfter ? 0u : 1u;
        return 0;
    }
    void wr(uint32_t bi, uint32_t reg, uint32_t v) {
        char b[64]; snprintf(b, sizeof b, "wr %u:%#x=%#x", bi, reg, v); log.push_back(b);
        if (reg == kSqCmd) writes++;
        if (reg == kRlcSafeMode && v == 3u) safePolls = 0u;
    }
    void delayUs(uint32_t) {}
    bool moved() { return writes >= movesAfterWrites; }
};

static void test_kill() {
    Rec r; KillStats st{};
    expect(kill(r, 9u, st) == kKillMoved && st.writes == 3u, "the kill repeats until the ring moves (3 writes)");
    bool onlyAllowed = true, bracketed = true;
    for (size_t i = 0; i < r.log.size(); i++) {
        const std::string &l = r.log[i];
        if (l.rfind("wr", 0) == 0 && l.find(":0x111b=") == std::string::npos && l.find(":0x980=") == std::string::npos) onlyAllowed = false;
        if (l == "wr 0:0x111b=0x90000093") {
            if (i == 0 || r.log[i - 1].find("rd 1:0x980") == std::string::npos || i + 1 >= r.log.size() || r.log[i + 1] != "wr 1:0x980=0x1") bracketed = false;
        } else if (l.find(":0x111b=") != std::string::npos) onlyAllowed = false;
    }
    expect(onlyAllowed, "writes: SQ_CMD with VMID 9's kill value and RLC_SAFE_MODE only");
    expect(bracketed, "every SQ_CMD write is after the safe-mode ack and followed by the exit");
    Rec s; s.movesAfterWrites = 100u;
    expect(kill(s, 9u, st) == kKillStuck && st.writes == kKillTries, "a kill that does not move stops after 10 writes (10 ms)");
    Rec t; t.rlcCntl = 0u;
    expect(kill(t, 9u, st) == kKillRlcOff && t.writes == 0u, "RLC not running: no write at all");
    Rec u; u.safeAckAfter = 0xFFFFFFFFu;
    expect(kill(u, 9u, st) == kKillSafeModeTimeout && u.writes == 0u && u.log.back() == "wr 1:0x980=0x1", "safe mode not acknowledged: no SQ_CMD write, the bracket is closed");
    Rec v;
    expect(kill(v, 3u, st) == kKillBadVmid && v.log.empty(), "VMID 3: nothing read or written");
}

static void test_pins(const std::string &src) {
    const std::string s = slurp(src + "/src/amd/native_s1c.cpp");
    expect(s.find("if (!n48softrec::may_latch(v)) { softrec_run(v, g, gs, gVmid, em, re, tried); return false; }") != std::string::npos,
           "stall_handle: a soft verdict returns without latching");
    expect(s.find("const bool soft = softrec_on();") != std::string::npos && s.find("n48softrec::latch_on(present, v)") != std::string::npos, "the switch is the boot-arg navi48-softrec=1");
    expect(s.find("__atomic_store_n(&gs->poisoned, 1u, __ATOMIC_SEQ_CST);   // before the kill") != std::string::npos, "the guilty session is poisoned before the kill");
    expect(s.find("const Fault f = decode_fault(hub_rd(kFaultStatusLo32));   // read only, never cleared") != std::string::npos, "the fault status is read, never cleared");
    const size_t run = s.find("static void softrec_run("), end = s.find("// A stall was detected and THIS call owns it");
    const std::string body = run != std::string::npos && end != std::string::npos ? s.substr(run, end - run) : std::string();
    expect(!body.empty() && body.find("hang_latch_wait") == std::string::npos && body.find("hang_announce") == std::string::npos && body.find("gHang.hung") == std::string::npos,
           "softrec_run never touches the HUNG latch");
    expect(body.find("__atomic_store_n(&gRecovering, 0u, __ATOMIC_SEQ_CST);") != std::string::npos, "softrec_run always releases the stall (gRecovering)");
}

int main(int argc, char **argv) {
    test_decide();
    test_encoding(argc > 2 ? argv[2] : "", argc > 3 ? argv[3] : "");
    test_kill();
    if (argc > 1) test_pins(argv[1]);
    printf("%s: %d checks, %d failures\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
