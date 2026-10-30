// Logical contexts have their own storage and lifetime, independent of VMIDs.
// The caller supplies the table, allocates/releases its resources and authenticates
// owner tokens from the IOUserClient, never from caller-supplied ioctl fields.
// Hold the same registry/lease lock across operations on either table. A CPU
// operation must pin its record before dropping that lock. Submission accounting
// and ring publication additionally share the ring lock, before the doorbell.
// This policy is not yet connected to the live kernel's Session records.
#pragma once
#include "production_vm_lease_pure.h"

namespace n48production {
enum class ContextState : uint8_t { Free, Opening, Live, Closing, Destroying, Quarantined };
struct ContextRef { uint32_t index; uint64_t identity; };
struct ContextRecord {
    ContextState state;
    uint64_t identity, owner, root, lastSequence;
    uint32_t references;
    bool compositor;
};

inline ContextRecord *context_lookup(ContextRecord *records, uint32_t count,
                                     ContextRef ref, uint64_t owner) {
    if (!records || ref.index >= count || !ref.identity || !owner) return nullptr;
    ContextRecord &c = records[ref.index];
    if (c.state == ContextState::Free || c.identity != ref.identity || c.owner != owner) return nullptr;
    return &c;
}

inline bool context_open(ContextRecord *records, uint32_t count, uint64_t &nextIdentity,
                         uint64_t owner, bool compositor, ContextRef *out) {
    if (!records || !nextIdentity || !owner || !out) return false;
    // At most one logical compositor context, including one still closing.
    if (compositor) for (uint32_t i = 0; i < count; ++i)
        if (records[i].state != ContextState::Free && records[i].compositor) return false;
    for (uint32_t i = 0; i < count; ++i) {
        if (records[i].state != ContextState::Free) continue;
        const uint64_t identity = nextIdentity;
        nextIdentity = identity == UINT64_MAX ? 0 : identity + 1;
        records[i] = {ContextState::Opening, identity, owner, 0, 0, 0, compositor};
        *out = {i, identity};
        return true;
    }
    return false;
}

inline bool context_publish(ContextRecord *records, uint32_t count, ContextRef ref,
                            uint64_t owner, uint64_t root) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || c->state != ContextState::Opening || !valid_root(root)) return false;
    // Each logical address space owns its root until physical teardown finishes.
    for (uint32_t i = 0; i < count; ++i)
        if (records[i].state != ContextState::Free && records[i].root == root) return false;
    c->root = root;
    c->state = ContextState::Live;
    return true;
}

inline bool context_pin(ContextRecord *records, uint32_t count, ContextRef ref, uint64_t owner) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || c->state != ContextState::Live || c->references == UINT32_MAX) return false;
    ++c->references;
    return true;
}

inline bool context_unpin(ContextRecord *records, uint32_t count, ContextRef ref, uint64_t owner) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || !c->references) return false;
    --c->references;
    return true;
}

inline bool context_request(ContextRecord *records, uint32_t count, ContextRef ref,
                            uint64_t owner, Request *out) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || c->state != ContextState::Live || !c->references || !out) return false;
    *out = {c->identity, c->root, c->compositor};
    return true;
}

inline bool context_submitted(ContextRecord *records, uint32_t count, ContextRef ref,
                              uint64_t owner, Slot *hardware, Ticket ticket, uint64_t sequence) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || c->state != ContextState::Live || !c->references || !hardware ||
        ticket.context != c->identity || ticket.slot >= kHardwareSlots ||
        hardware[ticket.slot].root != c->root || sequence <= c->lastSequence) return false;
    if (!submitted(hardware, ticket, sequence)) return false;
    c->lastSequence = sequence;
    return true;
}

inline bool context_close(ContextRecord *records, uint32_t count, ContextRef ref, uint64_t owner) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || (c->state != ContextState::Opening && c->state != ContextState::Live)) return false;
    c->state = ContextState::Closing;
    return true;
}

inline bool context_quarantine(ContextRecord *records, uint32_t count, ContextRef ref, uint64_t owner) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || c->state == ContextState::Destroying) return false;
    c->state = ContextState::Quarantined;
    return true;
}

// Retirement alone cannot free a root: hardware must no longer reference either
// the old or pending owner, including a failed programming operation's quarantine.
inline bool context_begin_destroy(ContextRecord *records, uint32_t count, ContextRef ref,
                                  uint64_t owner, const Slot *hardware, uint64_t retired,
                                  uint64_t *root) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || !hardware || !root || c->state != ContextState::Closing ||
        c->references || c->lastSequence > retired) return false;
    for (uint32_t i = 0; i < kHardwareSlots; ++i) {
        const Slot &s = hardware[i];
        if (s.context == c->identity || s.pendingContext == c->identity ||
            (c->root && (s.root == c->root || s.pendingRoot == c->root))) return false;
    }
    c->state = ContextState::Destroying;
    *root = c->root;
    return true;
}

// Call only after the OS has finished destroying page tables and BO resources.
inline bool context_destroyed(ContextRecord *records, uint32_t count, ContextRef ref, uint64_t owner) {
    ContextRecord *c = context_lookup(records, count, ref, owner);
    if (!c || c->state != ContextState::Destroying || c->references) return false;
    *c = {};
    return true;
}
} // namespace n48production
