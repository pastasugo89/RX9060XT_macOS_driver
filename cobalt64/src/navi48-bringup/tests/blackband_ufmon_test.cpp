// blackband_ufmon_test.cpp - build 0.0.672 (black band): the scanout underflow monitor's decisions (dcn/navi48_ufmon_pure.h) and its wiring in
// dcn/navi48_dcn.cpp (source pins: no lock held at the call, try-lock only, writes only through mt_wr, the registers and the kill switch).
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -I src/navi48-bringup/src/dcn \
//       src/navi48-bringup/tests/blackband_ufmon_test.cpp -o /tmp/blackband_ufmon && /tmp/blackband_ufmon src/navi48-bringup
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <fstream>
#include <sstream>
#include "navi48_ufmon_pure.h"

static int gFail = 0, gRun = 0;
static void expect(bool ok, const char *what) { gRun++; if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream ss; ss << f.rdbuf(); return ss.str(); }
using namespace n48ufmon;
namespace uf = n48mt::uf;

int main(int argc, char **argv) {
    const uint32_t H0 = 0x000e0000u, O0 = 0x00000000u;              // clean values seen on this machine (HUBP 0xe0000, OPTC bit 10 clear)
    const uint32_t Hbad = H0 | 0x10000000u, Obad = 0x00000400u;     // HUBP UNDERFLOW_STATUS 1, OPTC UNDERFLOW_OCCURRED_STATUS (sticky)
    // ---- register / bit layout pinned against Linux dcn_4_1_0 (offsets + seg2 0x34C0) ----
    expect(n48mt::kRegHubpCntl == 0x34C0u + 0x05F4u && n48mt::kRegOptcInGlobal == 0x34C0u + 0x1ACAu, "HUBP0_DCHUBP_CNTL 0x3AB4, ODM0_OPTC_INPUT_GLOBAL_CONTROL 0x4F8A");
    expect(uf::kHubpStatus == 0x70000000u && uf::kHubpClear == 0x80000000u && uf::kOptcOccurred == 0x400u && uf::kOptcClear == 0x1000u, "status / clear bits");
    // ---- switch ----
    expect(enabled(false, 0) && enabled(true, 1) && !enabled(true, 0), "only navi48-ufmon=0 turns it off");
    // ---- baseline ----
    Mon m; init(m);
    Step s = step(m, 1, H0, 0x400u, 1000, 10, false);
    expect(s.stale && s.act == kClear && !s.counted && m.events == 0 && m.baselineStale == 1, "a sticky status at the first sample is stale: cleared, not counted (the GOP / boot flag seen on 10/28)");
    after_clear(m, true, false);
    s = step(m, 1, H0, O0, 2000, 11, false);
    expect(!s.counted && s.act == kNone && m.events == 0, "clean sample: nothing");
    // ---- an event ----
    s = step(m, 1, H0, Obad, 3000, 12, false);
    expect(s.counted && s.log && s.act == kClear && m.events == 1 && m.optcEvents == 1 && m.hubpEvents == 0 && m.lastFrame == 12 && m.firstNs == 3000, "OPTC event counted, logged, cleared");
    after_clear(m, true, false);
    s = step(m, 1, Hbad, Obad, 4000, 13, false);
    expect(s.counted && m.events == 2 && m.hubpEvents == 1 && m.optcEvents == 2, "HUBP + OPTC event");
    after_clear(m, true, false);
    // ---- busy: counted once, never cleared while busy ----
    s = step(m, 1, H0, Obad, 5000, 14, true);
    expect(s.counted && s.act == kNone && m.events == 3 && m.busySkips == 1, "busy (mode trial / 60 Hz hold): counted, NOT cleared");
    s = step(m, 1, H0, Obad, 5050, 15, true);
    expect(!s.counted && s.act == kNone && m.events == 3, "still set while busy: the same event, not counted again");
    s = step(m, 1, H0, Obad, 5100, 16, false);
    expect(!s.counted && s.act == kClear && m.events == 3, "lock free again: the held event is cleared, still not recounted");
    after_clear(m, true, false);
    s = step(m, 1, H0, Obad, 5150, 17, false);
    expect(s.counted && m.events == 4, "a new event after a clean clear is counted");
    after_clear(m, true, false);
    // ---- clear that does not take ----
    s = step(m, 1, H0, Obad, 6000, 18, false); after_clear(m, true, true);
    expect(s.counted && m.events == 5, "event counted");
    s = step(m, 1, H0, Obad, 6050, 19, false);
    expect(!s.counted && s.act == kClear && m.events == 5, "a status that survived the strobe is not counted every 50 ms");
    after_clear(m, true, false);
    s = step(m, 1, H0, O0, 6100, 20, false);
    expect(!s.counted, "clean");
    // ---- soft reset: never written ----
    const uint32_t Oreset = Obad | uf::kOptcSoftReset;
    s = step(m, 1, H0, Oreset, 7000, 21, false);
    expect(s.counted && s.act == kClear && !optc_needs_clear(Oreset) && m.clearRefused == 1, "OPTC in soft reset: counted, its strobe refused (never written)");
    s = step(m, 1, H0, Oreset, 7050, 22, false);
    expect(!s.counted && m.events == 6, "and not recounted while it stays set");
    after_clear(m, false, true);
    // ---- unreadable ----
    const uint64_t ev = m.events;
    s = step(m, 1, 0xFFFFFFFFu, O0, 8000, 23, false);
    expect(!s.counted && s.act == kNone && m.unreadable == 1 && m.events == ev, "an unreadable register: no verdict, no write");
    expect(!hubp_needs_clear(0xFFFFFFFFu) && !optc_needs_clear(0xFFFFFFFFu), "never write back a dead read");
    // ---- strobe values: status bits written 0, control bits kept, strobe set ----
    expect(uf::optc_clear_value(0x00000400u | 0x00000100u) == (0x00000100u | 0x1000u), "OPTC clear keeps control bits, drops status, sets CLEAR");
    expect(uf::hubp_clear_value(0x100e0008u) == (0x000e0008u | 0x80000000u | 0x04000000u), "HUBP clear keeps control bits, drops status, sets both strobes");
    // ---- a new acquisition restarts the baseline, not the totals ----
    s = step(m, 2, H0, Obad, 9000, 1, false);
    expect(s.stale && !s.counted && m.events == ev, "new scanout generation: baseline again");
    // ---- log rate ----
    expect(should_log(1) && should_log(20) && !should_log(21) && should_log(64) && !should_log(65) && should_log(128), "log: first 20, then every 64th");
    // ---- source pins on the kext wiring ----
    const std::string root = argc > 1 ? argv[1] : ".";
    const std::string d = slurp(root + "/src/dcn/navi48_dcn.cpp");
    expect(!d.empty(), "navi48_dcn.cpp readable (pass the navi48-bringup directory)");
    const size_t pPoll = d.find("static void ufmon_poll(uint32_t gen) {"), pEnd = d.find("static void mt_sleep(void *, uint32_t ms) {");
    expect(pPoll != std::string::npos && pEnd != std::string::npos && pPoll < pEnd, "ufmon_poll defined before mt_sleep");
    const std::string body = d.substr(pPoll, pEnd - pPoll);
    expect(body.find("IOLockTryLock(gMtLock)") != std::string::npos && body.find("IOLockLock(") == std::string::npos, "gMtLock only by try-lock (never waits)");
    expect(body.find("WREG32") == std::string::npos && body.find("dcn_wreg") == std::string::npos, "writes only through mt_wr (the DCN allowlist)");
    expect(body.find("\"navi48-ufmon\"") != std::string::npos, "kill switch navi48-ufmon");
    expect(body.find("__atomic_load_n(&gMt.busy, __ATOMIC_SEQ_CST) == 0u && mt_ensure_lock() && IOLockTryLock(gMtLock)") != std::string::npos, "never clears while a mode trial / hold runs");
    const size_t pw = d.find("static void scan_watchdog_loop(uint32_t myGen) {");
    const size_t pc = d.find("ufmon_poll(myGen);", pw);
    const size_t pu = d.rfind("IOLockUnlock(l);", pc);
    expect(pw != std::string::npos && pc != std::string::npos && pu != std::string::npos && pu > pw, "the watchdog calls ufmon_poll after dropping the scan lock");
    const size_t pnext = d.find("IOLockLock(l);", pu);
    expect(pnext == std::string::npos || pnext > pc, "no scan lock is re-taken between the unlock and the call");
    std::printf("%s: %d checks, %d failed\n", gFail ? "FAIL" : "PASS", gRun, gFail);
    return gFail ? 1 : 0;
}
