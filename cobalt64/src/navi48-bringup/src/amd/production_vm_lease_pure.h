// Production VMID leasing policy. No MMIO, allocation or OS dependencies.
// This module is not yet wired into native_s1c.cpp. A logical context owns its
// page tables independently of these eight hardware bindings. Slot 0 is reserved
// for the compositor; idle application slots may change owners after retirement.
//
// Kernel integration must hold one lease-table lock for each operation and order
// submission/lastSequence publication with the ring lock. claim() reserves a slot
// before any MMIO. finish() may succeed only after root programming AND TLB ACK.
// An uncertain binding quarantines both old/new roots: caller must retain them.
#pragma once
#include <stdint.h>

namespace n48production {
constexpr uint32_t kHardwareSlots = 8;
constexpr uint32_t kFirstVmid = 8;
constexpr uint32_t kNoHardwareSlot = UINT32_MAX;
enum class SlotState : uint8_t { Empty, Ready, Binding, Quarantined };
enum class Decision : uint8_t { Bound, Bind, WaitForRetirement, BusyBinding, Unavailable, Invalid };

struct Slot {
    SlotState state;
    uint64_t context, root, lastSequence, generation;
    uint64_t pendingContext, pendingRoot;
};
struct Request { uint64_t context, root; bool compositor; };
struct Plan {
    Decision decision;
    uint32_t slot;
    uint64_t generation, oldContext, oldRoot, oldSequence, waitSequence;
};
struct Ticket { uint32_t slot; uint64_t generation, context; };
constexpr bool valid_root(uint64_t root) { return root != 0 && (root & 4095u) == 0; }
constexpr uint32_t vmid(uint32_t slot) { return slot < kHardwareSlots ? kFirstVmid + slot : UINT32_MAX; }

inline Plan plan(const Slot *slots, Request request, uint64_t retired) {
    Plan out{Decision::Invalid, kNoHardwareSlot, 0, 0, 0, 0, 0};
    if (!slots || !request.context || !valid_root(request.root)) return out;
    const uint32_t first = request.compositor ? 0 : 1;
    const uint32_t end = request.compositor ? 1 : kHardwareSlots;
    // Context IDs include the logical context's generation, not its table index.
    for (uint32_t i = 0; i < kHardwareSlots; ++i) {
        const Slot &s = slots[i];
        if (s.pendingContext == request.context) {
            if (i < first || i >= end || s.pendingRoot != request.root) return out;
            return {s.state == SlotState::Binding ? Decision::BusyBinding : Decision::Unavailable,
                    i, s.generation, s.context, s.root, s.lastSequence, 0};
        }
        if (s.state == SlotState::Empty || s.context != request.context) continue;
        if (i < first || i >= end || s.root != request.root) return out;
        if (s.state == SlotState::Ready)
            return {Decision::Bound, i, s.generation, s.context, s.root, s.lastSequence, 0};
        return {s.state == SlotState::Binding ? Decision::BusyBinding : Decision::Unavailable,
                i, s.generation, s.context, s.root, s.lastSequence, 0};
    }
    uint32_t pick = kNoHardwareSlot;
    uint64_t oldest = UINT64_MAX, wait = UINT64_MAX;
    bool binding = false;
    for (uint32_t i = first; i < end; ++i) {
        const Slot &s = slots[i];
        if (s.state == SlotState::Binding) {
            if (s.pendingContext == request.context) return {Decision::BusyBinding, i, s.generation, s.context, s.root, s.lastSequence, 0};
            binding = true; continue;
        }
        if (s.state == SlotState::Quarantined) continue;
        // The compositor's binding is pinned to its logical context until close.
        if (request.compositor && s.state == SlotState::Ready) continue;
        if (s.state == SlotState::Empty) { pick = i; break; }
        if (s.lastSequence > retired) {
            if (s.lastSequence < wait) wait = s.lastSequence;
            continue;
        }
        if (pick == kNoHardwareSlot || s.lastSequence < oldest) {
            oldest = s.lastSequence; pick = i;
        }
    }
    if (pick == kNoHardwareSlot) {
        out.decision = wait != UINT64_MAX ? Decision::WaitForRetirement : binding ? Decision::BusyBinding : Decision::Unavailable;
        out.waitSequence = wait == UINT64_MAX ? 0 : wait;
        return out;
    }
    const Slot &s = slots[pick];
    return {Decision::Bind, pick, s.generation, s.context, s.root, s.lastSequence, 0};
}

inline bool claim(Slot *slots, const Plan &choice, Request request, uint64_t retired, Ticket *ticket) {
    if (!slots || !ticket || choice.decision != Decision::Bind || choice.slot >= kHardwareSlots ||
        !request.context || !valid_root(request.root) || ((choice.slot == 0) != request.compositor)) return false;
    const Plan current = plan(slots, request, retired);
    if (current.decision != Decision::Bind || current.slot != choice.slot) return false;
    Slot &s = slots[choice.slot];
    if ((s.state != SlotState::Empty && s.state != SlotState::Ready) || s.generation == UINT64_MAX ||
        s.generation != choice.generation || s.context != choice.oldContext || s.root != choice.oldRoot ||
        s.lastSequence != choice.oldSequence || s.lastSequence > retired) return false;
    s.state = SlotState::Binding;
    ++s.generation;
    s.pendingContext = request.context; s.pendingRoot = request.root;
    *ticket = {choice.slot, s.generation, request.context};
    return true;
}

inline bool finish(Slot *slots, Ticket ticket, bool rootAndTlbAcknowledged) {
    if (!slots || ticket.slot >= kHardwareSlots) return false;
    Slot &s = slots[ticket.slot];
    if (s.state != SlotState::Binding || s.generation != ticket.generation || s.pendingContext != ticket.context) return false;
    if (!rootAndTlbAcknowledged) {
        s.state = SlotState::Quarantined; // retain old AND pending roots
        return true;
    }
    s.context = s.pendingContext; s.root = s.pendingRoot;
    s.pendingContext = 0; s.pendingRoot = 0; s.lastSequence = 0;
    s.state = s.context ? SlotState::Ready : SlotState::Empty;
    return true;
}

inline bool submitted(Slot *slots, Ticket ticket, uint64_t sequence) {
    if (!slots || ticket.slot >= kHardwareSlots || !ticket.context || !sequence) return false;
    Slot &s = slots[ticket.slot];
    if (s.state != SlotState::Ready || s.generation != ticket.generation ||
        s.context != ticket.context || sequence <= s.lastSequence) return false;
    s.lastSequence = sequence;
    return true;
}

// Begin a close: the kernel must park the hardware root and receive TLB ACK
// before finish(..., true). Retired work alone does not make page tables freeable.
inline bool begin_release(Slot *slots, Ticket owner, uint64_t retired, Ticket *park) {
    if (!slots || !park || owner.slot >= kHardwareSlots || !owner.context) return false;
    Slot &s = slots[owner.slot];
    if (s.state != SlotState::Ready || s.context != owner.context || s.generation != owner.generation ||
        s.generation == UINT64_MAX || s.lastSequence > retired) return false;
    s.state = SlotState::Binding; ++s.generation;
    s.pendingContext = 0; s.pendingRoot = 0;
    *park = {owner.slot, s.generation, 0};
    return true;
}
} // namespace n48production
