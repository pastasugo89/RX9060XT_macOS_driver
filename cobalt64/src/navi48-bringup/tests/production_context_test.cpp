#include <cassert>
#include <cstdio>
#include <memory>
#include "production_context_pure.h"
using namespace n48production;

static Ticket bind(Slot *hardware, Request request, uint64_t retired) {
    const auto choice = plan(hardware, request, retired);
    if (choice.decision == Decision::Bound)
        return {choice.slot, choice.generation, request.context};
    assert(choice.decision == Decision::Bind);
    Ticket ticket{};
    assert(claim(hardware, choice, request, retired, &ticket));
    assert(finish(hardware, ticket, true));
    return ticket;
}

static void park(Slot *hardware, Ticket ticket, uint64_t retired) {
    Ticket parking{};
    assert(begin_release(hardware, ticket, retired, &parking));
    assert(finish(hardware, parking, true));
}

int main() {
    constexpr uint32_t count = 1001;
    auto table = std::make_unique<ContextRecord[]>(count);
    auto refs = std::make_unique<ContextRef[]>(count);
    Slot hardware[kHardwareSlots]{};
    uint64_t nextIdentity = 1;
    Request request{};
    uint64_t root = UINT64_MAX;
    // Keep 1000 application records live at the same time, not just sequential
    // identities. Their allocated address spaces need no hardware slot at open.
    for (uint32_t i = 0; i < count; ++i) {
        assert(context_open(table.get(), count, nextIdentity, i + 1, i == 0, &refs[i]));
        assert(context_publish(table.get(), count, refs[i], i + 1, (i + 1ull) * 4096));
    }
    assert(nextIdentity == count + 1);
    ContextRef extra{};
    assert(!context_open(table.get(), count, nextIdentity, 9999, false, &extra));
    assert(nextIdentity == count + 1); // failed open does not consume an identity
    for (const auto &slot : hardware) assert(slot.state == SlotState::Empty);
    assert(!context_request(table.get(), count, refs[0], 1, &request));
    assert(context_pin(table.get(), count, refs[0], 1));
    assert(context_request(table.get(), count, refs[0], 1, &request));
    auto compositor = bind(hardware, request, 0);
    assert(context_submitted(table.get(), count, refs[0], 1, hardware, compositor, 1));
    assert(context_unpin(table.get(), count, refs[0], 1));
    uint64_t retired = 1;
    Ticket last{};
    for (uint32_t i = 1; i < count; ++i) {
        assert(!context_pin(table.get(), count, refs[i], 9999));
        assert(context_pin(table.get(), count, refs[i], i + 1));
        assert(context_request(table.get(), count, refs[i], i + 1, &request));
        last = bind(hardware, request, retired);
        assert(last.slot > 0);
        assert(context_pin(table.get(), count, refs[0], 1));
        assert(!context_submitted(table.get(), count, refs[0], 1, hardware, last, retired + 1));
        assert(context_unpin(table.get(), count, refs[0], 1));
        assert(context_submitted(table.get(), count, refs[i], i + 1, hardware, last, retired + 1));
        assert(!context_submitted(table.get(), count, refs[i], i + 1, hardware, last, retired + 1));
        ++retired;
        assert(context_unpin(table.get(), count, refs[i], i + 1));
        assert(hardware[0].context == compositor.context);
        assert(table[i].state == ContextState::Live);
    }
    assert(context_close(table.get(), count, refs[count - 1], count));
    assert(!context_pin(table.get(), count, refs[count - 1], count));
    assert(!context_begin_destroy(table.get(), count, refs[count - 1], count, hardware, retired - 1, &root));
    assert(!context_begin_destroy(table.get(), count, refs[count - 1], count, hardware, retired, &root));
    park(hardware, last, retired);
    assert(context_begin_destroy(table.get(), count, refs[count - 1], count, hardware, retired, &root));
    assert(root == count * 4096ull);
    assert(!context_open(table.get(), count, nextIdentity, 9999, false, &extra));
    assert(context_destroyed(table.get(), count, refs[count - 1], count));
    assert(!context_destroyed(table.get(), count, refs[count - 1], count));
    assert(context_open(table.get(), count, nextIdentity, count, false, &extra));
    assert(extra.index == refs[count - 1].index && extra.identity != refs[count - 1].identity);
    assert(!context_publish(table.get(), count, refs[count - 1], count, root));
    assert(!context_publish(table.get(), count, extra, count, 4096)); // another context's root
    assert(context_publish(table.get(), count, extra, count, root));
    assert(context_lookup(table.get(), count, refs[count - 1], count) == nullptr);

    // A close races a pinned CPU operation; destruction waits for its unpin.
    ContextRecord raced[2]{};
    ContextRef a{}, b{};
    uint64_t identity = 1;
    Slot bindings[kHardwareSlots]{};
    assert(context_open(raced, 2, identity, 10, false, &a));
    assert(context_publish(raced, 2, a, 10, 0x1000));
    assert(context_pin(raced, 2, a, 10));
    assert(context_request(raced, 2, a, 10, &request));
    auto pa = plan(bindings, request, 0);
    Ticket binding{};
    assert(claim(bindings, pa, request, 0, &binding));
    assert(context_close(raced, 2, a, 10));
    assert(!context_begin_destroy(raced, 2, a, 10, bindings, 0, &root));
    assert(finish(bindings, binding, true));
    assert(!context_submitted(raced, 2, a, 10, bindings, binding, 1));
    assert(context_unpin(raced, 2, a, 10));
    assert(!context_unpin(raced, 2, a, 10));
    assert(!context_begin_destroy(raced, 2, a, 10, bindings, 0, &root));
    park(bindings, binding, 0);
    assert(context_begin_destroy(raced, 2, a, 10, bindings, 0, &root));
    assert(context_destroyed(raced, 2, a, 10));

    // A failed rebind retains BOTH roots even if every sequence has retired.
    assert(context_open(raced, 2, identity, 10, false, &a));
    assert(context_publish(raced, 2, a, 10, 0x1000));
    assert(context_open(raced, 2, identity, 20, false, &b));
    assert(context_publish(raced, 2, b, 20, 0x2000));
    auto old = bind(bindings, {a.identity, 0x1000, false}, 0);
    for (uint32_t i = 2; i < kHardwareSlots; ++i) bindings[i].state = SlotState::Quarantined;
    request = {b.identity, 0x2000, false};
    auto pb = plan(bindings, request, 0);
    assert(claim(bindings, pb, request, 0, &binding));
    assert(finish(bindings, binding, false));
    assert(bindings[old.slot].root == 0x1000 && bindings[old.slot].pendingRoot == 0x2000);
    assert(context_close(raced, 2, a, 10) && context_close(raced, 2, b, 20));
    assert(!context_begin_destroy(raced, 2, a, 10, bindings, UINT64_MAX, &root));
    assert(!context_begin_destroy(raced, 2, b, 20, bindings, UINT64_MAX, &root));

    // Failed initialization is reclaimable, while explicit quarantine is not.
    ContextRecord cold[2]{};
    identity = UINT64_MAX;
    Slot empty[kHardwareSlots]{};
    assert(context_open(cold, 2, identity, 1, true, &a));
    assert(a.identity == UINT64_MAX && identity == 0);
    assert(!context_open(cold, 2, identity, 2, false, &b));
    assert(context_close(cold, 2, a, 1));
    assert(context_begin_destroy(cold, 2, a, 1, empty, 0, &root) && root == 0);
    assert(context_destroyed(cold, 2, a, 1));
    assert(!context_open(cold, 2, identity, 2, false, &b)); // no identity wrap/ABA
    identity = 1;
    assert(context_open(cold, 2, identity, 1, true, &a));
    assert(!context_open(cold, 2, identity, 2, true, &b));
    assert(context_publish(cold, 2, a, 1, 0x1000));
    cold[a.index].references = UINT32_MAX;
    assert(!context_pin(cold, 2, a, 1));
    cold[a.index].references = 0;
    assert(context_quarantine(cold, 2, a, 1));
    assert(!context_close(cold, 2, a, 1));
    assert(!context_begin_destroy(cold, 2, a, 1, empty, UINT64_MAX, &root));
    puts("PASS: 1000 simultaneously live application records, seven reused app VMIDs, owner isolation, stale handles, close/pin race, park ACK, two-root quarantine and identity exhaustion. Host policies only; kernel integration untested.");
}
