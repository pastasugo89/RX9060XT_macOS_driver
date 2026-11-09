// bundle 29 fixes: source-level checks of Navi48Device.m (the fixes live in the Objective-C file, which needs Vulkan / Metal to link).
// Build/run:  cc -O1 -Wall -Wextra -Werror -o /tmp/test-b29-fixes test-b29-fixes.c && /tmp/test-b29-fixes <dir holding Navi48Device.m>
// It checks that each fix's marker text is present and in the right function. It does NOT execute the fixes (see RESULTS.md, risks).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }
static const char *at(const char *s, const char *needle) { return s ? strstr(s, needle) : NULL; }

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[4096]; snprintf(path, sizeof path, "%s/Navi48Device.m", dir);
    char *s = slurp(path);
    if (!s) { printf("FAIL: cannot read %s\n", path); return 1; }

    // fix 4: format 84 table entry, ARGB read mapping, refusal as a colour attachment inside the render pipeline initializer
    { const char *row = at(s, "{ (MTLPixelFormat)84,");   // table row: format 84 -> R8G8B8A8_UNORM, N48F_ARGB (column spacing is free)
      check(row && at(row, "VK_FORMAT_R8G8B8A8_UNORM") && at(row, "N48F_ARGB }") && at(row, "N48F_ARGB }") - row < 160, "fix4: format 84 maps to R8G8B8A8_UNORM with N48F_ARGB"); }
    check(at(s, "VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_G, VK_COMPONENT_SWIZZLE_B, VK_COMPONENT_SWIZZLE_A, VK_COMPONENT_SWIZZLE_R };") != NULL,
          "fix4: ARGB read mapping (R<-G, G<-B, B<-A, A<-R on the RGBA8 bytes A,R,G,B)");
    const char *refuse = at(s, "if (f->flags & N48F_ARGB) { N48_ONCE(");
    { const char *fn = NULL;   // the method that encloses the refusal must be the render pipeline initializer
      for (const char *q = s; (q = strstr(q, "\n- (")) != NULL && q < refuse; q++) fn = q + 1;
      check(fn && strncmp(fn, "- (instancetype)initWithDevice:(id)dev descriptor:(MTLRenderPipelineDescriptor *)d noFallback", 93) == 0 && at(refuse, "return nil;") && at(refuse, "return nil;") - refuse < 400,
            "fix4: format 84 colour attachment refused inside render pipeline creation (nil + NSError)"); }

    // fix 3: memoised in-process translation failures, bounded, failures only
    check(at(s, "static NSCache<NSString *, NSNumber *> *n48x_failcache;") != NULL, "fix3: NSCache for failed translations");
    check(at(s, "countLimit = 256") != NULL, "fix3: bounded at 256 entries");
    check(at(s, "NSString *fkey = n48x_fail_key(sha, role, fn);") != NULL && at(s, "[n48x_failcache objectForKey:fkey]") != NULL, "fix3: lookup before the translation engine runs");
    check(at(s, "if (fkey && (rc == N48X_E_CAP || rc == N48X_E_SKIP_CRASH || rc == N48X_E_SKIP_FAIL || rc == N48X_E_READER || rc == N48X_E_REFUSED)) { [n48x_failcache setObject:@(rc) forKey:fkey];") != NULL, "fix3: only deterministic failures are stored (not SKIP_LIVE, IO, UNAVAILABLE, TIMEOUT)");

    // fix 5: unbound-slot sampler
    check(at(s, "sd.lodMaxClamp = 0;") != NULL && at(s, "sd.minFilter = MTLSamplerMinMagFilterNearest;") != NULL, "fix5: default sampler is nearest, level 0 only");
    check(at(s, "sd.sAddressMode = MTLSamplerAddressModeClampToEdge;") != NULL, "fix5: default sampler is clamp-to-edge");

    // fix 2: sampled view with the descriptor swizzle; storage and attachments keep identity; destroyed with the texture
    // bundle 38: the decision moved to n48_swz.h (n48sw_wants_view, host-tested by test-b38-swz.c); the ordinary path passes the texture-buffer type and the sample count
    check(at(s, "if (![d respondsToSelector:@selector(swizzle)]) return VK_NULL_HANDLE;") != NULL && at(s, "tt == MTLTextureTypeTextureBuffer, ti.samples, \"texture\")") != NULL, "fix2: created only for a non-identity swizzle, not for buffers / multisample");
    check(at(s, "- (VkImageView)n48SampleView { return _smpView ? _smpView : _view; }") != NULL, "fix2: sampled-view accessor falls back to the identity view");
    check(at(s, "if (_smpView) vkDestroyImageView(N48R.dev, _smpView, NULL);") != NULL, "fix2: destroyed with the texture");
    check(at(s, "n48AttViewLevel:0], VK_IMAGE_LAYOUT_GENERAL }") != NULL, "fix2: storage images still use the identity attachment view");

    // fix 1: null view / sampler guard in the descriptor fill
    check(at(s, "VkImageView tv = [t n48SampleView];") != NULL && at(s, "bound to the 1x1 dummy instead") != NULL, "fix1: null image view replaced by the dummy texture");
    check(at(s, "the default nearest/clamp sampler is bound instead") != NULL, "fix1: null VkSampler replaced by the default sampler");

    printf("test-b29-fixes: %d checks, %d failed\n", checks, fails);
    free(s);
    return fails ? 1 : 0;
}
