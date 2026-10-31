// n48_memtype.h: bundle 33 memory-type choice for GPU-only allocations, as plain C (no Vulkan, no Foundation; host test: tests/test-b33-memtype.c).
// Navi48Device.m copies RADV's VkMemoryType::propertyFlags into a flat table once, at device creation; these functions return indices into it.
//
// The table on this device (RADV on the native kext, RX 9060 XT; the log line "scanout: RADV memory type N" prints it at each start):
//   0, 1  DEVICE_LOCAL                            heap 0, 15399 MiB   (1 = the 32-bit type)
//   2     HOST_VISIBLE|HOST_COHERENT              heap 1, 512 MiB GTT (write-combined)
//   3     DEVICE_LOCAL|HOST_VISIBLE|COHERENT      heap 2, 217 MiB     (the CPU-visible VRAM heap; 4 = the 32-bit type)
//   5, 6  HOST_VISIBLE|HOST_COHERENT|CACHED       heap 1, GTT         (6 = the 32-bit type)
// RADV drops the 32-bit types from buffer and image requirements (radv_buffer.c:188, radv_device.c:1784): a buffer or an image allows {0,2,3,5}.
//
// Rules (bundle 33):
//  * GPU-only data (Private buffers, textures, the IOSurface device-local copy): the first DEVICE_LOCAL type WITHOUT HOST_VISIBLE that the resource
//    allows; then the other such types; then the HOST_VISIBLE|HOST_COHERENT types that are not DEVICE_LOCAL (system memory) when the size is at most
//    gtt_max. The CPU-visible device-local heap is never part of the plan. VK_ERROR_OUT_OF_DEVICE_MEMORY from one entry moves to the next.
//  * CPU-visible data (Shared buffers, host-pointer imports) and the scanout slots keep their own rules and do not use this plan.
#ifndef N48_MEMTYPE_H
#define N48_MEMTYPE_H

#include <stdint.h>

#define N48MT_MAX_TYPES 32u
// A GPU-only allocation above this size never falls back to system memory. The GTT cap is 512 MiB per session and the CPU-visible buffers need it too.
#define N48MT_GTT_FALLBACK_MAX (8ull << 20)

#define N48MT_DEVICE_LOCAL  0x1u
#define N48MT_HOST_VISIBLE  0x2u
#define N48MT_HOST_COHERENT 0x4u

// The first index allowed by bits whose flags contain every bit of want (the rule of Navi48Device.m's n48_find_mem, kept for the CPU-visible and
// scanout choices). -1 = none.
static inline int n48mt_find(uint32_t bits, const uint32_t *flags, uint32_t n, uint32_t want) {
    for (uint32_t i = 0; i < n && i < N48MT_MAX_TYPES; i++)
        if ((bits & (1u << i)) && (flags[i] & want) == want) return (int)i;
    return -1;
}

// The first DEVICE_LOCAL type without HOST_VISIBLE that bits allows. -1 = none: the caller fails as before and never uses a visible type instead.
static inline int n48mt_gpu_first(uint32_t bits, const uint32_t *flags, uint32_t n) {
    for (uint32_t i = 0; i < n && i < N48MT_MAX_TYPES; i++)
        if ((bits & (1u << i)) && (flags[i] & (N48MT_DEVICE_LOCAL | N48MT_HOST_VISIBLE)) == N48MT_DEVICE_LOCAL) return (int)i;
    return -1;
}

// The whole plan for a GPU-only allocation of `size` bytes, in order. out must hold N48MT_MAX_TYPES entries. Returns the count.
static inline uint32_t n48mt_gpu_plan(uint32_t bits, const uint32_t *flags, uint32_t n, uint64_t size, uint64_t gtt_max, uint32_t *out) {
    uint32_t k = 0;
    for (uint32_t i = 0; i < n && i < N48MT_MAX_TYPES; i++)
        if ((bits & (1u << i)) && (flags[i] & (N48MT_DEVICE_LOCAL | N48MT_HOST_VISIBLE)) == N48MT_DEVICE_LOCAL) out[k++] = i;
    if (size <= gtt_max)
        for (uint32_t i = 0; i < n && i < N48MT_MAX_TYPES; i++)
            if ((bits & (1u << i)) && (flags[i] & (N48MT_DEVICE_LOCAL | N48MT_HOST_VISIBLE | N48MT_HOST_COHERENT)) == (N48MT_HOST_VISIBLE | N48MT_HOST_COHERENT))
                out[k++] = i;
    return k;
}

// The plan without `first` (the type the caller already tried), in plan order: what VK_ERROR_OUT_OF_DEVICE_MEMORY from `first` falls back to.
// out must hold N48MT_MAX_TYPES entries. Returns the count.
static inline uint32_t n48mt_gpu_fallbacks(uint32_t bits, const uint32_t *flags, uint32_t n, uint64_t size, uint64_t gtt_max, uint32_t first, uint32_t *out) {
    uint32_t plan[N48MT_MAX_TYPES], np = n48mt_gpu_plan(bits, flags, n, size, gtt_max, plan), k = 0;
    for (uint32_t j = 0; j < np; j++)
        if (plan[j] != first) out[k++] = plan[j];
    return k;
}

#endif
