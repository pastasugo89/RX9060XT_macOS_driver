// Eight-session build profile: pure admission and backwards-compatible stat pages.
#define N48_MAX_NATIVE_SESSIONS 8
#include "native_g2_pure.h"
#include "native_g5_pure.h"
#include <cassert>
#include <cstdio>
using namespace n48native::g2;
int main() {
    static_assert(kMaxSessions == 8 && kStatGlobal == 4);
    assert(!stall_progressed(7, 7));
    assert(stall_progressed(7, 8));
    assert(!stall_progressed(7, 6));
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
    // Explore mixed live/dead/free states, including WindowServer replacement.
    uint32_t seed = 0x21c5u;
    for (unsigned run = 0; run < 30000; ++run) {
        seed = seed * 1664525u + 1013904223u;
        uint32_t open = 0, free = 0, first = kNoSlot;
        for (unsigned i = 0; i < kMaxSessions; ++i) {
            seed = seed * 1664525u + 1013904223u;
            state[i] = (seed >> 16) % 3u;
            if (state[i] == kSlotOpen) ++open;
            if (state[i] == kSlotFree) { ++free; if (first == kNoSlot) first = i; }
        }
        for (unsigned ws = 0; ws < 2; ++ws) for (unsigned wsOpen = 0; wsOpen < 2; ++wsOpen) {
            auto p = open_pick(true, state, open, ws, false, true, wsOpen);
            const bool allowed = free && (ws ? !wsOpen : (wsOpen || free > 1));
            assert((p.rc == kOk) == allowed);
            if (allowed) assert(p.slot == first && state[p.slot] == kSlotFree);
        }
    }
    // Seven app waiters share one ring: lower-priority waiters cannot pass
    // an older live waiter, while clearing a completed waiter makes progress.
    uint64_t since[kMaxSessions] = {};
    constexpr uint64_t now = 1000, stale = 1000;
    for (unsigned i = 1; i < kMaxSessions; ++i)
        n48native::g5::since_mark(since, i, 100 + i);
    for (unsigned i = 1; i < kMaxSessions; ++i) {
        assert(!n48native::g5::older_waiter(since, i, now, stale));
        for (unsigned j = i + 1; j < kMaxSessions; ++j)
            assert(n48native::g5::older_waiter(since, j, now, stale));
        n48native::g5::since_clear(since, i);
    }
    OwnerLog log {};
    owner_note(log, 1, 0, 100, 0); // WindowServer
    for (unsigned i = 1; i < kMaxSessions; ++i)
        owner_note(log, i + 1, i, 100 + i, 0);
    assert(n48native::g5::app_in_flight(log, 0, 8, 100, 8) == 7);
    assert(n48native::g5::ws_outstanding(log, 0, 8, 100) == 1);
    assert(guilty_of(log, 4, 8).known && guilty_of(log, 4, 8).slot == 4);
    puts("eight-session admission and stat ABI: PASS (30000 state samples)");
}
