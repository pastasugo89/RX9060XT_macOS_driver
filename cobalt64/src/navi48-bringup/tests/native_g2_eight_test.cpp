// Eight-session build profile: pure admission and backwards-compatible stat pages.
#define N48_MAX_NATIVE_SESSIONS 8
#include "native_g2_pure.h"
#include "native_g5_pure.h"
#include <cassert>
#include <cstdio>
using namespace n48native::g2;
int main() {
    static_assert(kMaxSessions == 8 && kStatGlobal == 4);
    uint8_t state[kMaxSessions] = {};
    for (unsigned i = 0; i < kMaxSessions; ++i) {
        assert(n48native::vmid_ok(vmid_of_slot(i)));
        assert(vmid_of_slot(i) == i + 8);
        auto p = open_pick(true, state, i, i == 0, false, true, i != 0);
        assert(p.rc == kOk && p.slot == i);
        state[i] = kSlotOpen;
    }
    assert(open_pick(true, state, 8, false, false, true, true).rc == kExclusive);
    state[4] = kSlotDead; state[6] = kSlotFree;
    assert(open_pick(true, state, 7, false, false, true, true).slot == 6);
    state[6] = kSlotOpen; state[7] = kSlotFree;
    assert(open_pick(true, state, 7, false, false, true, false).rc == kExclusive);
    assert(open_pick(true, state, 7, true, false, true, false).slot == 7);
    for (unsigned i = 0; i < 4; ++i) assert(stat_page_slot(i) == i);
    for (unsigned i = 6; i <= 9; ++i) {
        assert(args_ok(kActSessStat, i));
        assert(stat_page_slot(i) == i - 2);
        assert(!n48native::g5::args_ok(true, kActSessStat, i));
    }
    assert(args_ok(kActSessStat, 4));
    assert(!args_ok(kActSessStat, 5));
    assert(n48native::g5::args_ok(true, kActSessStat, 5));
    assert(!args_ok(kActSessStat, 10));
    puts("eight-session admission and stat ABI: PASS");
}
