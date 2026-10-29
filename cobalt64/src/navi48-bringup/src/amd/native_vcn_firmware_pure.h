// VCN common firmware header validation and size calculations, no PSP/MMIO.
// Based on Linux amdgpu common_firmware_header and VCN 5.0 cache setup.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace n48vcn {
struct FirmwarePlan { bool valid; uint32_t payloadOffset, payloadSize, version; uint64_t pspBytes, cacheBytes; };
inline uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
inline FirmwarePlan firmware_plan(const uint8_t *data, size_t bytes) {
    const FirmwarePlan bad{false,0,0,0,0,0};
    if (!data || bytes < 32u) return bad;
    const uint32_t total=le32(data), header=le32(data+4), major=(uint32_t)data[8] | ((uint32_t)data[9] << 8);
    const uint32_t minor=(uint32_t)data[10] | ((uint32_t)data[11] << 8);
    const uint32_t version=le32(data+16), size=le32(data+20), offset=le32(data+24);
    if (major != 1 || minor != 0 || total > bytes || total < 32u || header < 32u || header > total ||
        offset < header || offset > total || !size || (uint64_t)offset + size > total) return bad;
    const uint64_t alignedPsp = ((uint64_t)size + 4095u) & ~4095ull;
    const uint64_t alignedCache = ((uint64_t)size + 8u + 4095u) & ~4095ull;
    // VCN hardware cache-size registers are 32-bit.
    if (alignedPsp > UINT32_MAX || alignedCache > UINT32_MAX) return bad;
    return FirmwarePlan{true,offset,size,version,alignedPsp,alignedCache};
}
}
