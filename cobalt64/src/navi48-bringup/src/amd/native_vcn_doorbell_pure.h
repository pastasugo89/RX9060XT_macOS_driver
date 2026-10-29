// Experimental VCN 5.0 doorbell planner for NBIF 6.3.1. No MMIO operations.
// Field definitions and behaviour: AMD's Linux nbif_v6_3_1_vcn_doorbell_range.
// AMD copyright and permission notice: VCN-AMD-LICENSE.txt in this directory.
// This only prepares an entry-4 value; VCN firmware, MMHUB, queues, lifecycle,
// collision checks against the full doorbell map, and macOS integration are absent.
#pragma once
#include <stdint.h>

namespace n48vcn {
constexpr uint32_t kEntryBaseIndex = 2u, kEntryOffset = 0x01cfu;
constexpr uint32_t kEnable = 0x00000001u, kAwid = 0x0000003eu;
constexpr uint32_t kOffset = 0x0001ff80u, kSize = 0x01fe0000u, kAddr = 0xf0000000u;
constexpr uint32_t kTouched = kEnable | kAwid | kOffset | kSize | kAddr;
constexpr uint32_t kRange = 8u, kMaxOffset = 1023u;
struct Plan { bool valid; uint32_t value; };
// The range must fit in the field. Instance 1 shares entry 5 with VPE on this
// NBIF family and is deliberately left for a future resource ownership audit.
constexpr Plan doorbell0(uint32_t before, bool enable, uint32_t offset) {
    if (!enable) return Plan{true, before & ~kSize};
    if (offset > kMaxOffset - (kRange - 1u)) return Plan{false, before};
    return Plan{true, (before & ~kTouched) | kEnable | (4u << 1) |
                         (offset << 7) | (kRange << 17) | (4u << 28)};
}
}
