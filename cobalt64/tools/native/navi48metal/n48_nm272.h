// n48_nm272.h (bundle 35 -> nm272 candidate): the pure decisions behind the NullMoth 2.7-2.7.2 items this bundle takes on top of bundle 35: items 1, 2, 3 and 8
// (see RESULTS.md in the bundle directory). Pure C, with no Metal or Vulkan types, so tests/test-nm272-items.c checks it on the host.
// The Objective-C glue that calls these is in src/Navi48Device.m (search "bundle nm272 candidate").
#ifndef N48_NM272_H
#define N48_NM272_H
#include <stdint.h>

// Item 2. The depth bounds test is bit 31 of the depth/stencil variant key. n48ds_key (n48_depth.h) uses bits 0-30 only, and a pipeline variant carries
// this bit only when the pipeline has a depth attachment (the render encoder sets it, the variant's VkPipelineDepthStencilState reads it).
#define N48NM_DS_DEPTH_BOUNDS (1u << 31)

// Item 1. The product of a compute function's required threads per threadgroup (MTLComputePipelineDescriptor.requiredThreadsPerThreadgroup). A zero count
// means "not required" and gives 0. The product saturates at UINT64_MAX instead of wrapping.
static inline uint64_t n48nm_mul_sat(uint64_t a, uint64_t b) {
    if (a && b > UINT64_MAX / a) return UINT64_MAX;
    return a * b;
}
static inline uint64_t n48nm_required_product(uint64_t w, uint64_t h, uint64_t d) {
    if (!w || !h || !d) return 0;
    return n48nm_mul_sat(n48nm_mul_sat(w, h), d);
}
// maxTotalThreadsPerThreadgroup of a compute pipeline: the device bound, unless a required size is smaller than it (then the required size bounds the total).
static inline uint64_t n48nm_max_total_tg(uint64_t device_max, uint64_t required_product) {
    return (required_product && required_product < device_max) ? required_product : device_max;
}

// Item 2 (range). Metal's depth bounds are two floats; Vulkan's dynamic depth bounds must lie in [0, 1] (VK_EXT_depth_range_unrestricted is not assumed).
// A stored depth is already in [0, 1], so clamping keeps the test's answer. NaN gives the widest range: 0 for the minimum, 1 for the maximum.
static inline float n48nm_db_lo(float v) { return !(v > 0.0f) ? 0.0f : (v > 1.0f ? 1.0f : v); }
static inline float n48nm_db_hi(float v) { return !(v < 1.0f) ? 1.0f : (v < 0.0f ? 0.0f : v); }

// Item 3. An MTLTextureViewDescriptor as the view code reads it (by key, so the bundle needs no macOS 26 SDK type). A zero pixel format keeps the
// texture's own; an empty level or slice range covers every level or slice of the texture; an all-zero swizzle is the identity (MTLTextureSwizzle:
// Zero 0, One 1, Red 2, Green 3, Blue 4, Alpha 5). NullMoth 2.7 (bc467c8) resolves the view the same way.
typedef struct { uint64_t pf, tt, lvLoc, lvLen, slLoc, slLen; uint8_t sw[4]; } n48nm_tvd_t;
static inline void n48nm_tvd_resolve(const n48nm_tvd_t *in, uint64_t rootPf, uint64_t rootLevels, uint64_t rootSlices, n48nm_tvd_t *out) {
    *out = *in;
    if (!out->pf) out->pf = rootPf;
    if (!out->lvLen) { out->lvLoc = 0; out->lvLen = rootLevels; }
    if (!out->slLen) { out->slLoc = 0; out->slLen = rootSlices; }
    if (!out->sw[0] && !out->sw[1] && !out->sw[2] && !out->sw[3]) { out->sw[0] = 2; out->sw[1] = 3; out->sw[2] = 4; out->sw[3] = 5; }
}

// Item 8. An indirect dispatch reads MTLDispatchThreadgroupsIndirectArguments (three uint32 group counts, the layout of VkDispatchIndirectCommand) at
// offset `off` of a buffer of `len` bytes. The offset must be 4-byte aligned and the 12 bytes must lie inside the buffer.
static inline int n48nm_indirect_ok(uint64_t off, uint64_t len) {
    return (off % 4) == 0 && off <= len && len - off >= 12;
}

#endif
