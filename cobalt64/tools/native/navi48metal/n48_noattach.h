// Render passes without attachments (bundle 44, empty targets in bundle 45). A Metal render pass may name no colour and no depth/stencil attachment: its size,
// layer count and sample count then come from the descriptor (renderTargetWidth / renderTargetHeight, renderTargetArrayLength, defaultRasterSampleCount).
// The SDK (MTLRenderPass.h) documents renderTargetWidth/Height as constraints that default to 0, and defaultRasterSampleCount as the raster sample count when
// no attachments are given. A zero width or height is an empty target: no fragment is produced, so its draws do nothing (bundle 45: was a refusal).
// The decision is pure C so the host test (test-noattach.c) can check it. Navi48Device.m calls n48na_decide with the device's limits.
#ifndef N48_NOATTACH_H
#define N48_NOATTACH_H
#include <stddef.h>
#include <stdint.h>

// ok = 1, noop = 0: a w x h framebuffer with `layers` layers; the pass and every pipeline drawn in it use `samples` (rasterizationSamples must equal it).
// ok = 1, noop = 1: an empty target (a zero width or height). The encoder exists, records nothing, and its draws do nothing.
// ok = 0: why names the refusal (a sample count the device cannot use, or a size past the device limits). The encoder is then not created.
typedef struct { int ok; int noop; uint32_t w, h, layers; unsigned samples; const char *why; } n48na_t;

// The Metal fields arrive as uint64_t, so a value that does not fit the device limit is refused instead of being truncated.
// samplesMask: the VkSampleCountFlagBits a pass without attachments may use. Bit n is VK_SAMPLE_COUNT_n_BIT for n = 1, 2, 4, 8.
// renderTargetArrayLength 0 means one layer, defaultRasterSampleCount 0 means one sample (Metal's defaults).
static inline n48na_t n48na_decide(uint64_t rtw, uint64_t rth, uint64_t rtl, uint64_t dsc, unsigned samplesMask,
                                   uint32_t maxW, uint32_t maxH, uint32_t maxLayers) {
    n48na_t r = { 0, 0, 0, 0, 0, 0, NULL };
    uint64_t n = dsc ? dsc : 1;
    if (n != 1 && n != 2 && n != 4 && n != 8) { r.why = "defaultRasterSampleCount must be 1, 2, 4 or 8"; return r; }
    if (!((uint64_t)samplesMask & n)) { r.why = "the device does not support this defaultRasterSampleCount without attachments"; return r; }
    r.samples = (unsigned)n;
    if (rtw == 0 || rth == 0) { r.ok = 1; r.noop = 1; r.layers = 1; return r; }
    if (rtw > maxW || rth > maxH) { r.why = "the render target exceeds maxFramebufferWidth or maxFramebufferHeight"; return r; }
    uint64_t layers = rtl ? rtl : 1;
    if (layers > maxLayers) { r.why = "renderTargetArrayLength exceeds maxFramebufferLayers"; return r; }
    r.ok = 1; r.w = (uint32_t)rtw; r.h = (uint32_t)rth; r.layers = (uint32_t)layers;
    return r;
}
#endif
