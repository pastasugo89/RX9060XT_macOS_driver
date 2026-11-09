// n48_swz.h - bundle 38: which textures get a descriptor-swizzled SAMPLED view (MTLTextureDescriptor.swizzle). No Foundation: host-testable (test-b38-swz.c).
// Bundle 29 applied the descriptor swizzle only to textures from newTextureWithDescriptor:. IOSurface-backed textures (newTextureWithDescriptor:iosurface:plane:) and textures over a
// buffer dropped it. IconServices / IconRendering hands gray+alpha icon layers over as RG8Unorm IOSurfaces sampled with swizzle (R,R,R,G): without it a layer read as (gray, alpha, 0, 1),
// so white glass turned yellow (blue 0) and the transparent part of each layer rectangle became opaque black (alpha forced to 1). Proven in-process: icons-opus/out (before/after).
#ifndef N48_SWZ_H
#define N48_SWZ_H
// Metal's MTLTextureSwizzle values: Zero 0, One 1, Red 2, Green 3, Blue 4, Alpha 5.
static inline int n48sw_is_default(unsigned r, unsigned g, unsigned b, unsigned a) { return r == 2 && g == 3 && b == 4 && a == 5; }
// 1 = make a separate sampled view with the descriptor swizzle. Depth/stencil, texture buffers and multisample textures keep the identity mapping (as bundle 29);
// an out-of-range channel (> 5) is ignored rather than turned into a view.
static inline int n48sw_wants_view(unsigned r, unsigned g, unsigned b, unsigned a, int isDepthStencil, int isTextureBuffer, unsigned samples) {
    if (r > 5 || g > 5 || b > 5 || a > 5) return 0;
    if (n48sw_is_default(r, g, b, a)) return 0;
    return !isDepthStencil && !isTextureBuffer && samples <= 1;
}
#endif /* N48_SWZ_H */
