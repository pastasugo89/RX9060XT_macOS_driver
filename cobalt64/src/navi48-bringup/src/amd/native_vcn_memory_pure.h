// VCN 5.0 PSP-mode allocation layout, based on Linux amdgpu_vcn_sw_init and
// vcn_v5_0_0_mc_resume. Arithmetic only: no allocation, MMIO, PSP or mappings.
// AMD copyright and permission notice: VCN-AMD-LICENSE.txt in this directory.
#pragma once
#include <stdint.h>
#include <limits.h>
namespace n48vcn {
constexpr uint64_t kStackBytes = 128ull * 1024, kContextBytes = 512ull * 1024, kPageBytes = 4096;
struct MemoryPlan { bool valid; uint64_t stack, context, shared, totalBytes; };
// sharedBytes must be the page-aligned *actual* ABI struct size, established
// separately. This planner deliberately does not infer VCN firmware ABI size.
constexpr MemoryPlan psp_memory(uint64_t gpuBase, uint64_t sharedBytes) {
    if ((gpuBase & (kPageBytes-1)) || !sharedBytes || (sharedBytes & (kPageBytes-1)) ||
        sharedBytes > UINT64_MAX - kStackBytes - kContextBytes)
        return MemoryPlan{false,0,0,0,0};
    const uint64_t total = kStackBytes + kContextBytes + sharedBytes;
    if (gpuBase > UINT64_MAX-total) return MemoryPlan{false,0,0,0,0};
    return MemoryPlan{true,gpuBase,gpuBase+kStackBytes,gpuBase+kStackBytes+kContextBytes,total};
}
}
