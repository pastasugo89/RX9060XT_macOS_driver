// Render passes without attachments (bundle 44). A Metal render pass may name no colour and no depth/stencil attachment: its size, layer count and
// sample count then come from the descriptor (renderTargetWidth / renderTargetHeight, renderTargetArrayLength, defaultRasterSampleCount). The decision is
// pure C so the host test (test-noattach.c) can check it. Navi48Device.m calls n48na_decide with the device's limits.
#ifndef N48_NOATTACH_H
#define N48_NOATTACH_H
#include <stddef.h>
#include <stdint.h>

// ok = 1: a w x h framebuffer with `layers` layers; the pass and every pipeline drawn in it use `samples` (rasterizationSamples must equal it).
// ok = 0: why names the refusal. The encoder is then not created.
typedef struct { int ok; uint32_t w, h, layers; unsigned samples; const char *why; } n48na_t;

// The Metal fields arrive as uint64_t, so a value that does not fit the device limit is refused instead of being truncated.
// samplesMask: the VkSampleCountFlagBits a pass without attachments may use. Bit n is VK_SAMPLE_COUNT_n_BIT for n = 1, 2, 4, 8.
// renderTargetArrayLength 0 means one layer, defaultRasterSampleCount 0 means one sample (Metal's defaults).
static inline n48na_t n48na_decide(uint64_t rtw, uint64_t rth, uint64_t rtl, uint64_t dsc, unsigned samplesMask,
                                   uint32_t maxW, uint32_t maxH, uint32_t maxLayers) {
    n48na_t r = { 0, 0, 0, 0, 0, NULL };
    if (rtw == 0 || rth == 0) { r.why = "renderTargetWidth and renderTargetHeight must both be set"; return r; }
    if (rtw > maxW || rth > maxH) { r.why = "the render target exceeds maxFramebufferWidth or maxFramebufferHeight"; return r; }
    uint64_t layers = rtl ? rtl : 1;
    if (layers > maxLayers) { r.why = "renderTargetArrayLength exceeds maxFramebufferLayers"; return r; }
    uint64_t n = dsc ? dsc : 1;
    if (n != 1 && n != 2 && n != 4 && n != 8) { r.why = "defaultRasterSampleCount must be 1, 2, 4 or 8"; return r; }
    if (!((uint64_t)samplesMask & n)) { r.why = "the device does not support this defaultRasterSampleCount without attachments"; return r; }
    r.ok = 1; r.w = (uint32_t)rtw; r.h = (uint32_t)rth; r.layers = (uint32_t)layers; r.samples = (unsigned)n;
    return r;
}
#endif
