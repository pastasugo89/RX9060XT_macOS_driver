// n48_zinit.h: bundle 34 zero-initialisation of new device-local resources, as plain C (no Vulkan, no Foundation; host test:
// tests/test-b34-zinit.c). Navi48Device.m does the Vulkan calls (one-shot, waited: n48_oneshot).
//
// Why (bundle 33, controlled test in research/builds/macos-20261031/icon-mix-b33): a NEW private texture or buffer returned the
// contents of the resource that had been released into the same memory just before. Measured with the pool ON and OFF:
// 65536 of 65536 pixels (texture) and 1048576 of 1048576 bytes (buffer). Metal gives a new resource zeroed contents; the icon
// renderers rely on it, and an icon composed on top of a recycled texture shows the previous icon through it. Device-local
// memory is also not zeroed by the kernel or RADV on this stack (fresh allocations hold stale data), so the bundle clears it.
//
// Scope: textures created by -initWithDevice:descriptor: (colour, single-sampled) and every private buffer. Depth/stencil and
// multisample textures are not cleared (vkCmdClearColorImage does not apply to them). WindowServer is not changed by this step.
#ifndef N48_ZINIT_H
#define N48_ZINIT_H
#include <stdint.h>

typedef enum {
    N48ZI_CLEAR = 0,            // clear it (before its first GPU use)
    N48ZI_SKIP_KILL,            // /private/tmp/n48m-nozinit exists (kill file, latched once per process): bundle 33 behaviour
    N48ZI_SKIP_WINDOWSERVER,    // this process is WindowServer: unchanged until tested there
    N48ZI_SKIP_EMPTY,           // nothing to clear
    N48ZI_SKIP_HOSTVISIBLE,     // host-visible memory is never cleared here (the pool zeroes CPU-mapped memory itself)
    N48ZI_SKIP_DEPTH,           // depth/stencil: needs vkCmdClearDepthStencilImage (not implemented)
    N48ZI_SKIP_MULTISAMPLE      // multisample: vkCmdClearColorImage does not apply
} n48zi_verdict;

// killed: the kill file exists. ws: this process is WindowServer. isDepthStencil / samples describe the texture.
static inline n48zi_verdict n48zi_decide_texture(int killed, int ws, int isDepthStencil, uint32_t samples, uint64_t allocSize) {
    if (killed) return N48ZI_SKIP_KILL;
    if (ws) return N48ZI_SKIP_WINDOWSERVER;
    if (allocSize == 0) return N48ZI_SKIP_EMPTY;
    if (isDepthStencil) return N48ZI_SKIP_DEPTH;
    if (samples > 1) return N48ZI_SKIP_MULTISAMPLE;
    return N48ZI_CLEAR;
}

// Buffers: every device-local (private) buffer. hostVisible = 1 is refused (only the pool's CPU-mapped memory is zeroed by the pool).
static inline n48zi_verdict n48zi_decide_buffer(int killed, int ws, int hostVisible, uint64_t size) {
    if (killed) return N48ZI_SKIP_KILL;
    if (ws) return N48ZI_SKIP_WINDOWSERVER;
    if (size == 0) return N48ZI_SKIP_EMPTY;
    if (hostVisible) return N48ZI_SKIP_HOSTVISIBLE;
    return N48ZI_CLEAR;
}

// vkCmdFillBuffer writes whole 32-bit words: the fill covers the size rounded down to a multiple of 4 (0 = nothing to do).
static inline uint64_t n48zi_fill_bytes(uint64_t size) { return size & ~(uint64_t)3; }

static inline const char *n48zi_name(n48zi_verdict v) {
    switch (v) {
    case N48ZI_CLEAR: return "clear";
    case N48ZI_SKIP_KILL: return "skip (kill file)";
    case N48ZI_SKIP_WINDOWSERVER: return "skip (WindowServer)";
    case N48ZI_SKIP_EMPTY: return "skip (empty)";
    case N48ZI_SKIP_HOSTVISIBLE: return "skip (host-visible)";
    case N48ZI_SKIP_DEPTH: return "skip (depth/stencil)";
    case N48ZI_SKIP_MULTISAMPLE: return "skip (multisample)";
    }
    return "?";
}
#endif
