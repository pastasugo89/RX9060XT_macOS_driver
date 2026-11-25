// test-noattach.c: host test of the render pass without attachments (n48_noattach.h: n48na_decide; bundle 44 sized passes, bundle 45 empty targets), plus
// source pins that tie the REAL Navi48Device.m and Info.plist to it: the encoder takes its size, layers and samples from the descriptor, an empty target
// records nothing, every refusal after the base encoder exists ends that encoder first (N48_INIT_REFUSE), the bundle 45 diagnostics are wired, RGBA8Uint
// (73) is in the format table, and Info.plist names bundle 45. The runtime probe is test-noattach-runtime.m (not run by this file).
// Build/run (from this directory):  cc -std=c11 -O1 -Wall -Wextra -Werror -o <out>/test-noattach test-noattach.c && <out>/test-noattach .
//   argv[1] = the directory holding Navi48Device.m, n48_noattach.h and Info.plist (default ".").
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n48_noattach.h"

static int fails, checks;
#define CHECK(c, ...) do { int ok_ = (c) ? 1 : 0; checks++; printf("%s: ", ok_ ? "ok  " : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!ok_) fails++; } while (0)

// The limits of the RX 9060 XT's RADV build (radv_physical_device.c: framebuffer sample counts 0xF, maxFramebufferWidth/Height 16384, layers 2048).
#define MAXW 16384u
#define MAXH 16384u
#define MAXL 2048u
#define MASK 0xFu

static int is_sized(n48na_t r, uint32_t w, uint32_t h, uint32_t l, unsigned s) {
    return r.ok && !r.noop && r.w == w && r.h == h && r.layers == l && r.samples == s;
}
static int is_empty(n48na_t r, unsigned s) {
    return r.ok && r.noop && r.w == 0 && r.h == 0 && r.samples == s;
}
static int is_refused(n48na_t r, const char *part) {
    return !r.ok && !r.noop && r.why && strstr(r.why, part);
}
static char *slurp(const char *dir, const char *name) {
    char p[1024]; snprintf(p, sizeof p, "%s/%s", dir, name);
    FILE *f = fopen(p, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    if (n < 0) { fclose(f); return NULL; }
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f);
    return b;
}
// 1 when the first line of `m` that contains `key` also contains both `a` and `b`.
static int line_has(const char *m, const char *key, const char *a, const char *b) {
    const char *p = strstr(m, key); if (!p) return 0;
    const char *s = p; while (s > m && s[-1] != '\n') s--;
    const char *e = strchr(p, '\n'); size_t n = e ? (size_t)(e - s) : strlen(s);
    char buf[1024]; if (n >= sizeof buf) n = sizeof buf - 1;
    memcpy(buf, s, n); buf[n] = 0;
    return strstr(buf, a) != NULL && strstr(buf, b) != NULL;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    n48na_t r;

    // ---- sized passes (bundle 44) ----
    r = n48na_decide(1920, 1080, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_sized(r, 1920, 1080, 1, 1), "1920x1080 with no layer or sample count -> one layer, one sample, sized");
    r = n48na_decide(8, 2, 3, 4, MASK, MAXW, MAXH, MAXL);
    CHECK(is_sized(r, 8, 2, 3, 4), "8x2 with 3 layers and 4 samples -> the same, sized");
    r = n48na_decide(8, 2, 0, 2, 0x2, MAXW, MAXH, MAXL);
    CHECK(is_sized(r, 8, 2, 1, 2), "two samples on a device that offers exactly two -> accepted");
    r = n48na_decide(8, 2, 0, 0, 0x0, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "without attachments"), "one sample on a mask without bit 1 -> refused (\"%s\")", r.why ? r.why : "");
    r = n48na_decide(8, 2, 0, 4, 0x3, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "without attachments"), "four samples the device lacks -> refused");
    r = n48na_decide(8, 2, 0, 3, MASK, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "1, 2, 4 or 8"), "three samples -> refused (\"%s\")", r.why ? r.why : "");
    r = n48na_decide(8, 2, 0, 16, MASK, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "1, 2, 4 or 8"), "sixteen samples -> refused");
    r = n48na_decide(MAXW, MAXH, MAXL, 8, MASK, MAXW, MAXH, MAXL);
    CHECK(is_sized(r, MAXW, MAXH, MAXL, 8), "the largest framebuffer, layer count and sample count -> accepted");
    r = n48na_decide(MAXW + 1u, 2, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "maxFramebuffer"), "a width above the limit -> refused");
    r = n48na_decide(8, MAXH + 1u, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "maxFramebuffer"), "a height above the limit -> refused");
    r = n48na_decide(8, 2, MAXL + 1u, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "maxFramebufferLayers"), "a layer count above the limit -> refused");
    r = n48na_decide((1ull << 32) + 8u, 2, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(!r.ok, "a width of 2^32 + 8 is refused, not truncated to 8");
    r = n48na_decide(8, 2, (1ull << 32) + 1u, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(!r.ok, "a layer count of 2^32 + 1 is refused, not truncated to 1");
    r = n48na_decide(8, 2, 0, (1ull << 32) + 4u, MASK, MAXW, MAXH, MAXL);
    CHECK(!r.ok, "a sample count of 2^32 + 4 is refused, not truncated to 4");

    // ---- empty targets (bundle 45): a zero width or height draws nothing; the sample count is still validated ----
    r = n48na_decide(0, 2, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_empty(r, 1), "zero width -> an empty target (no-op pass), one sample");
    r = n48na_decide(8, 0, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_empty(r, 1), "zero height -> an empty target (no-op pass)");
    r = n48na_decide(0, 0, 0, 0, MASK, MAXW, MAXH, MAXL);
    CHECK(is_empty(r, 1), "zero width and height -> an empty target (Basemark's depth passes after a refused texture)");
    r = n48na_decide(0, 0, 4, 4, MASK, MAXW, MAXH, MAXL);
    CHECK(is_empty(r, 4), "an empty target keeps a valid defaultRasterSampleCount of 4");
    r = n48na_decide(0, 0, 0, 3, MASK, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "1, 2, 4 or 8"), "an empty target with three samples is still refused");
    r = n48na_decide(0, 0, 0, 4, 0x3, MAXW, MAXH, MAXL);
    CHECK(is_refused(r, "without attachments"), "an empty target with four samples the device lacks is still refused");
    r = n48na_decide(0, 0, 0, (1ull << 32) + 4u, MASK, MAXW, MAXH, MAXL);
    CHECK(!r.ok, "an empty target with a sample count of 2^32 + 4 is refused, not truncated");

    // ---- source pins on the REAL Navi48Device.m and Info.plist ----
    char *m = slurp(dir, "Navi48Device.m");
    if (!m) { printf("FAIL: cannot read %s/Navi48Device.m\n", dir); fails++; }
    else {
        CHECK(strstr(m, "#include \"n48_noattach.h\"") != NULL, "Navi48Device.m includes n48_noattach.h");
        CHECK(strstr(m, "n48na_decide((uint64_t)d.renderTargetWidth, (uint64_t)d.renderTargetHeight, (uint64_t)d.renderTargetArrayLength, (uint64_t)d.defaultRasterSampleCount,") != NULL,
              "a pass without attachments takes its size, layers and samples from the descriptor through n48na_decide");
        CHECK(strstr(m, "N48R.lim.framebufferNoAttachmentsSampleCounts & n48_ms_mask(), N48R.lim.maxFramebufferWidth, N48R.lim.maxFramebufferHeight, N48R.lim.maxFramebufferLayers);") != NULL,
              "the device limits are the no-attachment sample counts (within the colour/depth/stencil mask) and the framebuffer size and layer limits");
        CHECK(strstr(m, "_w = nr.w; _h = nr.h; layers = nr.layers;") != NULL, "a sized pass takes the decided size and layer count");
        CHECK(strstr(m, ".width = _w, .height = _h, .layers = layers };") != NULL, "the framebuffer uses the decided layer count");
        CHECK(strstr(m, "render pass: no colour or depth/stencil attachments") == NULL, "the attachment-less refusal of bundle 43 is gone");
        CHECK(strstr(m, "#define N48_INIT_REFUSE() do { [super endEncoding]; return nil; } while (0)") != NULL,
              "a refused init ends the base encoder (super endEncoding) before it returns nil");
        // The init body runs from the @implementation line to N48_DNR. Its only literal `return nil;` is the super-init check.
        const char *s0 = strstr(m, "@implementation N48RenderEncoder\n- (instancetype)initWithCommandBuffer:(id)cb descriptor:(MTLRenderPassDescriptor *)d {");
        const char *s1 = s0 ? strstr(s0, "N48_DNR(N48RenderEncoder)") : NULL;
        int nret = 0, nref = 0;
        if (s0 && s1) {
            for (const char *p = s0; p < s1; p++) {
                if (strncmp(p, "return nil;", 11) == 0) nret++;
                if (strncmp(p, "N48_INIT_REFUSE();", 18) == 0) nref++;
            }
        }
        CHECK(s0 && s1 && nret == 1, "the init returns nil in one place only: the super-init check (found %d)", nret);
        CHECK(nref >= 21, "every refusal after the base init is N48_INIT_REFUSE() (%d sites)", nref);
        // bundle 45: empty targets
        CHECK(strstr(m, "    BOOL _noop;") != NULL || strstr(m, "uint32_t _clrm; NSUInteger _dvc; BOOL _noop;") != NULL, "N48RenderEncoder has the _noop flag");
        CHECK(strstr(m, "_noop = YES; _w = 0; _h = 0;") != NULL, "a zero-size pass without attachments is an empty target (bundle 45)");
        CHECK(strstr(m, "if (_noop) {   // bundle 45: an empty target has no Vulkan render pass, framebuffer or query pool; it produces no fragment") != NULL,
              "an empty target creates no Vulkan render pass, framebuffer or query pool");
        CHECK(strstr(m, "if (vb && [vb isKindOfClass:[N48Buffer class]] && [(N48Buffer *)vb contents]) {") != NULL && strstr(m, "if (!acc) memset([(N48Buffer *)vb contents], 0, [vb length]);") != NULL,
              "an empty target resets a visibility result buffer (Reset) like a real pass");
        CHECK(strstr(m, "if (_noop) return NO;") != NULL, "n48PrepareDraw draws nothing for an empty target");
        CHECK(strstr(m, "if (_noop) return;   // bundle 45: an empty target draws nothing") != NULL, "drawIndexedPrimitives draws nothing for an empty target");
        CHECK(strstr(m, "if (_noop) { _ended = YES; [super endEncoding]; return; }") != NULL, "endEncoding of an empty target records nothing and ends the base encoder");
        CHECK(strstr(m, "if (_noop) return;   // bundle 45: nothing to order in an empty target") != NULL, "barriers of an empty target record nothing");
        // bundle 45: diagnostics
        CHECK(strstr(m, "static void n48_rp_dump(MTLRenderPassDescriptor *d) {") != NULL, "the render pass dump is defined");
        const char *q = m; int dumps = 0;
        while ((q = strstr(q, "n48_rp_dump(d);")) != NULL) { dumps++; q++; }
        CHECK(dumps >= 2, "the dump runs for refused passes and for empty targets (%d call sites)", dumps);
        // bundle 45: RGBA8Uint (73) in the format table and its integer clear width
        CHECK(line_has(m, "{ MTLPixelFormatRGBA8Uint,", "VK_FORMAT_R8G8B8A8_UINT,", "4, N48F_UINT }"),
              "the format table maps RGBA8Uint (73) to VK_FORMAT_R8G8B8A8_UINT with the integer flag");
        CHECK(strstr(m, "static unsigned n48_uint_bits(MTLPixelFormat f) { return (f == MTLPixelFormatR8Uint || f == MTLPixelFormatRGBA8Uint) ? 8u : f == MTLPixelFormatR32Uint ? 32u : 16u; }") != NULL,
              "RGBA8Uint clears with 8-bit channels");
        // bundle 45: the unbound-resource warnings (about 9000 per Basemark run) and the pipeline-state warning are rate limited
        CHECK(strstr(m, "N48LOGR(\"WARN %s texture(%u) is used by the shader but was never bound: 1x1 dummy\"") != NULL
              && strstr(m, "N48LOGR(\"WARN %s buffer(%u)") != NULL && strstr(m, "N48LOGR(\"WARN %s sampler(%u)") != NULL
              && strstr(m, "N48LOGR(\"setRenderPipelineState: not an N48RenderPipelineState\")") != NULL,
              "the unbound-resource and pipeline-state warnings are rate limited (N48LOGR)");
        free(m);
    }
    char *pl = slurp(dir, "Info.plist");
    CHECK(pl && strstr(pl, "<key>CFBundleVersion</key>\n\t<string>46</string>") != NULL, "Info.plist names bundle 46 (CFBundleVersion)");
    free(pl);

    printf("test-noattach: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
