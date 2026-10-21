// Pure pieces of gfxhub_v12_0_set_fault_enable_default from upstream Linux.
#pragma once
#include <stdint.h>

namespace amdgpu {

constexpr uint32_t kCpDebugUtcl1ErrorHaltDisable = 1u << 15;

// Linux RMW: REG_SET_FIELD(CP_DEBUG, CPG_UTCL1_ERROR_HALT_DISABLE, 1).
// Keep this arithmetic pure so host tests can verify preservation/idempotence.
static inline uint32_t cp_debug_allow_utcl1_fault_recovery(uint32_t value) {
    return value | kCpDebugUtcl1ErrorHaltDisable;
}

} // namespace amdgpu
