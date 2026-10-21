// Wire layout for MESAPI_SET_HW_RESOURCES_1 (MES v12.1).
// Keep this freestanding so the exact dword ABI can be tested on the host.
#pragma once

#include <stddef.h>
#include <stdint.h>

struct MES_API_Status_1_Wire {
    uint64_t fence_addr;
    uint64_t fence_value;
};

struct MES_SetHwResources1_Wire {
    uint32_t header;                         // dw 0
    uint32_t pad_header_to_status;           // dw 1
    MES_API_Status_1_Wire api_status;         // dw 2..5
    uint64_t timestamp;                      // dw 6..7
    uint32_t flags;                          // dw 8
    uint32_t pad_flags_to_debug_addr;        // dw 9
    uint64_t mes_debug_ctx_mc_addr;          // dw 10..11
    uint32_t mes_debug_ctx_size;             // dw 12
    uint32_t mes_kiq_unmap_timeout;          // dw 13, units of 100 ms
    uint64_t coop_sch_shared_mc_addr;        // dw 14..15
    uint64_t cleaner_shader_fence_mc_addr;   // dw 16..17
    uint32_t reserved[46];                   // dw 18..63
};

static_assert(sizeof(MES_API_Status_1_Wire) == 16,
              "MES API status wire size changed");
static_assert(offsetof(MES_SetHwResources1_Wire, api_status) == 8,
              "SET_HW_RESOURCES_1 api_status must start at dw 2");
static_assert(offsetof(MES_SetHwResources1_Wire, timestamp) == 24,
              "SET_HW_RESOURCES_1 timestamp must start at dw 6");
static_assert(offsetof(MES_SetHwResources1_Wire, flags) == 32,
              "SET_HW_RESOURCES_1 flags must start at dw 8");
static_assert(offsetof(MES_SetHwResources1_Wire, mes_debug_ctx_mc_addr) == 40,
              "SET_HW_RESOURCES_1 debug address must start at dw 10");
static_assert(offsetof(MES_SetHwResources1_Wire, mes_debug_ctx_size) == 48,
              "SET_HW_RESOURCES_1 debug size must start at dw 12");
static_assert(offsetof(MES_SetHwResources1_Wire, mes_kiq_unmap_timeout) == 52,
              "SET_HW_RESOURCES_1 timeout must start at dw 13");
static_assert(offsetof(MES_SetHwResources1_Wire, coop_sch_shared_mc_addr) == 56,
              "SET_HW_RESOURCES_1 coop address must start at dw 14");
static_assert(offsetof(MES_SetHwResources1_Wire, cleaner_shader_fence_mc_addr) == 64,
              "SET_HW_RESOURCES_1 cleaner fence must start at dw 16");
static_assert(sizeof(MES_SetHwResources1_Wire) == 64 * sizeof(uint32_t),
              "SET_HW_RESOURCES_1 must be exactly 64 dwords");
