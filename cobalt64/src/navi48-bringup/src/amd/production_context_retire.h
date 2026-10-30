#pragma once
#include <stdint.h>

namespace n48production {
enum class RetireVerdict : uint8_t { WorkPending, RootUncertain, FenceUncertain, Retired };
struct RetireResult { RetireVerdict verdict; bool rootParked; };

// Both address spaces can reach a client's memory: its private root and VMID 0's
// shared fence window. Keep BOs and page tables until both invalidations ACK.
// The caller holds the session/registry locks and has already waited outside the
// registry lock. Failure retains the ownership records for quarantine.
template <class Env>
inline RetireResult retire_context_bindings(Env &env, bool ownWorkRetired) {
    if (!ownWorkRetired) return {RetireVerdict::WorkPending, false};
    if (!env.park_root()) return {RetireVerdict::RootUncertain, false};
    const bool hadFences = env.clear_fence_ptes();
    if (hadFences && !env.flush_fence_tlb()) return {RetireVerdict::FenceUncertain, true};
    env.forget_fences();
    return {RetireVerdict::Retired, true};
}
} // namespace n48production
