// Fixed gfx1200 vadd_ir HSA argument/dispatch-pointer ABI.
#pragma once

#include <stdint.h>

namespace amdgpu {

struct __attribute__((packed)) VaddKernarg {
    uint64_t a;
    uint64_t b;
    uint64_t c;
    uint32_t n;
};

struct VaddDispatchPacket {
    uint16_t header;
    uint16_t setup;
    uint16_t workgroup_size_x;
    uint16_t workgroup_size_y;
    uint16_t workgroup_size_z;
    uint16_t reserved0;
    uint32_t grid_size_x;
    uint32_t grid_size_y;
    uint32_t grid_size_z;
    uint32_t private_segment_size;
    uint32_t group_segment_size;
    uint64_t kernel_object;
    uint64_t kernarg_address;
    uint64_t reserved1;
    uint64_t completion_signal;
};

static_assert(sizeof(VaddKernarg) == 28, "vadd_ir kernarg size");
static_assert(__builtin_offsetof(VaddKernarg, a) == 0, "vadd arg a offset");
static_assert(__builtin_offsetof(VaddKernarg, b) == 8, "vadd arg b offset");
static_assert(__builtin_offsetof(VaddKernarg, c) == 16, "vadd arg c offset");
static_assert(__builtin_offsetof(VaddKernarg, n) == 24, "vadd arg n offset");
static_assert(sizeof(VaddDispatchPacket) == 64, "AQL dispatch packet size");
static_assert(__builtin_offsetof(VaddDispatchPacket, workgroup_size_x) == 4,
              "dispatch_ptr workgroup_size_x offset consumed by vadd_ir");
static_assert(__builtin_offsetof(VaddDispatchPacket, grid_size_x) == 12,
              "AQL grid_size_x offset");
static_assert(__builtin_offsetof(VaddDispatchPacket, kernarg_address) == 40,
              "AQL kernarg pointer offset");

constexpr uint16_t kVaddHsaKernelDispatchPacket = 2;
constexpr uint16_t kVaddHsaSetupOneDimension = 1;
constexpr uint16_t kVaddWorkgroupSizeX = 32;

inline VaddDispatchPacket make_vadd_dispatch_packet(uint64_t code_va, uint64_t kernarg_va)
{
    VaddDispatchPacket p {};
    p.header = kVaddHsaKernelDispatchPacket;
    p.setup = kVaddHsaSetupOneDimension;
    p.workgroup_size_x = kVaddWorkgroupSizeX;
    p.workgroup_size_y = 1;
    p.workgroup_size_z = 1;
    p.grid_size_x = kVaddWorkgroupSizeX;
    p.grid_size_y = 1;
    p.grid_size_z = 1;
    p.kernel_object = code_va;
    p.kernarg_address = kernarg_va;
    return p;
}

} // namespace amdgpu
