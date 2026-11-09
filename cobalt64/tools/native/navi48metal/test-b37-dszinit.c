// bundle 37: depth/stencil zero-initialisation (src/n48_zinit.h, src/Navi48Device.m).
// Part 1: source wiring and ordering, checked as text in Navi48Device.m and Info.plist (the .m needs Vulkan and Metal to link):
//         the depth/stencil decision and clear are called in the isDS branch, the clear is guarded by TRANSFER_DST usage, it runs after
//         BOTH memory binds and before the view, the aspects map N48DP_ASP_* to VK_IMAGE_ASPECT_*, the entry point is in the table.
// Part 2: the pure decisions (n48zi_decide_depth_stencil, and the unchanged colour / bundle 34 depth decision).
// Build/run:  cc -O1 -Wall -Wextra -Werror -I<mesa include> -I. -o bin/test-b37-dszinit test-b37-dszinit.c && bin/test-b37-dszinit <dir holding Navi48Device.m and Info.plist>
//             (<mesa include> = research/ext/mesa-darwin/include, the Vulkan headers)
// Negative control: the same binary on the bundle 36 source must fail the part 1 checks (no depth/stencil clear there).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "n48_zinit.h"

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }
static int count(const char *s, const char *needle) {
    int n = 0; size_t l = strlen(needle); if (!s) return 0;
    for (const char *p = s; (p = strstr(p, needle)) != NULL; p += l) n++;
    return n;
}
static long at(const char *s, const char *needle) { const char *p = s ? strstr(s, needle) : NULL; return p ? (long)(p - s) : -1; }

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <dir with Navi48Device.m and Info.plist>\n", argv[0]); return 2; }
    char pm[1024], pp[1024];
    snprintf(pm, sizeof pm, "%s/Navi48Device.m", argv[1]);
    snprintf(pp, sizeof pp, "%s/Info.plist", argv[1]);
    char *m = slurp(pm), *plist = slurp(pp);
    printf("== part 1: source wiring (%s)\n", pm);
    check(m != NULL, "Navi48Device.m readable");
    check(plist != NULL, "Info.plist readable");
    check(count(m, "X(vkCmdClearDepthStencilImage)") == 1, "vkCmdClearDepthStencilImage in the Vulkan entry-point table");
    check(count(m, "n48zi_decide_depth_stencil(n48zi_killed(), n48zi_ws(), (uint32_t)ti.samples, (uint64_t)mr.size)") == 1, "depth/stencil decision called once, with the kill file and WindowServer inputs");
    check(count(m, "n48zi_decide_texture(n48zi_killed(), n48zi_ws(), isDS, (uint32_t)ti.samples, (uint64_t)mr.size)") == 1, "colour decision still called once (bundle 34)");
    check(count(m, "static VkImageAspectFlags n48zi_ds_aspects(unsigned asp) {") == 1, "aspect mapping defined once");
    check(count(m, "((asp & N48DP_ASP_DEPTH) ? VK_IMAGE_ASPECT_DEPTH_BIT : 0)") == 1 && count(m, "((asp & N48DP_ASP_STENCIL) ? VK_IMAGE_ASPECT_STENCIL_BIT : 0)") == 1,
          "depth and stencil aspects mapped from the texture's own aspects");
    check(count(m, "static BOOL n48zi_clear_depth_stencil(VkImage img, VkImageAspectFlags aspects, uint32_t levels, uint32_t layers) {") == 1, "depth/stencil clear helper defined once");
    check(count(m, "VkClearDepthStencilValue z = { 0.0f, 0 };") == 1, "zero depth (0.0) and stencil (0) as the clear value");
    check(count(m, "vkCmdClearDepthStencilImage(cmd, img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &z, 1, &rg);") == 1, "vkCmdClearDepthStencilImage recorded in the one-shot, in TRANSFER_DST_OPTIMAL");
    check(count(m, "n48zi_clear_depth_stencil(_img, n48zi_ds_aspects(_aspects), (uint32_t)_levels, (uint32_t)ti.layers)") == 1, "depth/stencil clear called once with the texture's own aspects, levels and layers");
    check(count(m, "n48zi_clear_image(_img, (uint32_t)_levels, (uint32_t)ti.layers)") == 1, "colour clear still called once");
    check(count(m, "[self setLayout:VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL]") == 2, "layout tracked after each clear (colour and depth/stencil)");
    check(count(m, "n48_oneshot(&e, ^(VkCommandBuffer cmd) {") >= 3, "the clears use the waited one-shot helper");
    check(count(m, "if (!(iu & VK_IMAGE_USAGE_TRANSFER_DST_BIT)) N48_ONCE(") == 1, "the depth/stencil clear is guarded by TRANSFER_DST usage (logged once if absent)");
    long dsBranch = at(m, "if (isDS) {   // bundle 37");
    long dsGuard = at(m, "if (!(iu & VK_IMAGE_USAGE_TRANSFER_DST_BIT))");
    long dsClear = at(m, "n48zi_clear_depth_stencil(_img, n48zi_ds_aspects(_aspects)");
    long bPool = at(m, "vkBindImageMemory(N48R.dev, _img, _pm.mem, _pm.off)");
    long bNon = at(m, "vkBindImageMemory(N48R.dev, _img, _mem, 0)");
    long vcm = at(m, "VkComponentMapping cm = n48_view_map(_fmt, _swz);");
    check(dsBranch > 0 && dsGuard > 0 && dsClear > 0 && bPool > 0 && bNon > 0 && vcm > 0, "depth/stencil branch, guard, clear, binds and view found");
    check(bPool < dsBranch && bNon < dsBranch, "depth/stencil branch runs after BOTH memory binds (pooled and direct)");
    check(dsBranch < dsGuard && dsGuard < dsClear && dsClear < vcm, "depth/stencil: branch, guard, clear, then the view");
    check(at(m, "N48DP_ASP_DEPTH") > 0 && count(m, "_aspects = df.aspects;") == 1, "texture aspects come from the depth/stencil descriptor (bundle 10 table)");
    check(count(m, "static void n48rp_ds(") == 0 && count(m, "n48rp_ds(asp, dtI != nil,") == 1, "the render-pass load mapping is still n48rp_ds (unchanged)");
    check(plist && count(plist, "<key>CFBundleVersion</key>\n\t<string>37</string>") == 1, "Info.plist CFBundleVersion is 37");

    printf("== part 2: pure decisions (src/n48_zinit.h)\n");
    check(n48zi_decide_depth_stencil(0, 0, 1, 262144) == N48ZI_CLEAR, "depth/stencil: single-sampled, app -> clear");
    check(n48zi_decide_depth_stencil(1, 0, 1, 262144) == N48ZI_SKIP_KILL, "depth/stencil: kill file wins -> bundle 36 behaviour");
    check(n48zi_decide_depth_stencil(1, 1, 1, 0) == N48ZI_SKIP_KILL, "depth/stencil: kill file wins over every other reason");
    check(n48zi_decide_depth_stencil(0, 1, 1, 262144) == N48ZI_SKIP_WINDOWSERVER, "depth/stencil: WindowServer unchanged");
    check(n48zi_decide_depth_stencil(0, 0, 1, 0) == N48ZI_SKIP_EMPTY, "depth/stencil: zero-size allocation skipped");
    check(n48zi_decide_depth_stencil(0, 0, 4, 262144) == N48ZI_SKIP_MULTISAMPLE, "depth/stencil: 4x multisample still skipped (no render-pass clear)");
    check(n48zi_decide_depth_stencil(0, 0, 2, 262144) == N48ZI_SKIP_MULTISAMPLE, "depth/stencil: 2x multisample still skipped");
    check(n48zi_decide_texture(0, 0, 0, 1, 262144) == N48ZI_CLEAR, "colour: single-sampled, app -> clear (bundle 34 unchanged)");
    check(n48zi_decide_texture(0, 0, 1, 1, 262144) == N48ZI_SKIP_DEPTH, "bundle 34 decision for a depth/stencil flag is unchanged (the caller no longer uses it for DS)");
    check(strcmp(n48zi_name(N48ZI_CLEAR), "clear") == 0, "verdict names unchanged");

    printf("\n%d checks, %d failed\n", checks, fails);
    free(m); free(plist);
    return fails ? 1 : 0;
}
