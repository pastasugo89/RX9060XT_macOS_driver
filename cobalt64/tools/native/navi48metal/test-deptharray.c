// test-deptharray.c: bundle 46 host test. Depth/stencil textures of type 2D array and cube (six faces) are accepted (n48_depth.h n48dp_check). Cube arrays,
// 1D and 3D are refused. Every other rule (Private storage, no ShaderWrite, the attachment and sampling features) applies to every accepted type.
// Source pins tie the REAL Navi48Device.m and n48_texdesc.h to the rule: the MTLTextureType static asserts, the texture init's n48dp_check call, the zero-init
// of every layer, per-layer depth attachment views, the whole-image layout transitions of a layered texture, and the sampling view with the depth aspect.
// Build/run (from this directory):  cc -std=c11 -O1 -Wall -Wextra -Werror -o <out>/test-deptharray test-deptharray.c && <out>/test-deptharray .
//   argv[1] = the directory holding Navi48Device.m, n48_depth.h, n48_texdesc.h and n48_zinit.h (default ".").
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n48_depth.h"

static int fails, checks;
#define CHECK(c, ...) do { int ok_ = (c) ? 1 : 0; checks++; printf("%s: ", ok_ ? "ok  " : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!ok_) fails++; } while (0)

static char *slurp(const char *dir, const char *name) {
    char p[1024]; snprintf(p, sizeof p, "%s/%s", dir, name);
    FILE *f = fopen(p, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    if (n < 0) { fclose(f); return NULL; }
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f);
    return b;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    const unsigned long ALL = N48DP_FEAT_SAMPLED | N48DP_FEAT_DS_ATT;
    const char *why = NULL;

    // ---- the type rule: 2D, 2D array, 2D multisample and cube are accepted; the rest refused ----
    CHECK(n48dp_check(N48DP_T_2D, N48DP_USE_RT | N48DP_USE_READ, N48DP_ST_PRIVATE, ALL, &why) && !why, "2D depth, RenderTarget|ShaderRead, Private -> accepted");
    CHECK(n48dp_check(N48DP_T_2DARRAY, N48DP_USE_RT | N48DP_USE_READ, N48DP_ST_PRIVATE, ALL, &why) && !why, "2D array depth (shadow cascades), RenderTarget|ShaderRead, Private -> accepted (bundle 46)");
    CHECK(n48dp_check(N48DP_T_CUBE, N48DP_USE_RT | N48DP_USE_READ, N48DP_ST_PRIVATE, ALL, &why) && !why, "cube depth, RenderTarget|ShaderRead, Private -> accepted (bundle 46)");
    CHECK(n48dp_check(N48DP_T_2DMS, N48DP_USE_RT | N48DP_USE_READ, N48DP_ST_PRIVATE, ALL, &why) && !why, "2D multisample depth -> still accepted");
    CHECK(!n48dp_check(6, N48DP_USE_RT, N48DP_ST_PRIVATE, ALL, &why) && why && strstr(why, "cube array"), "cube array depth (type 6) -> refused (\"%s\")", why ? why : "");
    CHECK(!n48dp_check(0, N48DP_USE_RT, N48DP_ST_PRIVATE, ALL, &why) && why && strstr(why, "1D"), "1D depth (type 0) -> refused");
    CHECK(!n48dp_check(1, N48DP_USE_RT, N48DP_ST_PRIVATE, ALL, &why) && why, "1D array depth (type 1) -> refused");
    CHECK(!n48dp_check(7, N48DP_USE_RT, N48DP_ST_PRIVATE, ALL, &why) && why && strstr(why, "3D"), "3D depth (type 7) -> refused");
    CHECK(!n48dp_check(8, N48DP_USE_RT, N48DP_ST_PRIVATE, ALL, &why) && why, "2D multisample array depth (type 8) -> refused");
    CHECK(!n48dp_check(9, N48DP_USE_RT, N48DP_ST_PRIVATE, ALL, &why) && why, "texture buffer depth (type 9) -> refused");

    // ---- the same rules as before apply to the new types ----
    CHECK(!n48dp_check(N48DP_T_2DARRAY, N48DP_USE_RT, N48DP_ST_SHARED, ALL, &why) && why && strstr(why, "Private"), "2D array depth in Shared storage -> refused");
    CHECK(!n48dp_check(N48DP_T_CUBE, N48DP_USE_RT, N48DP_ST_MANAGED, ALL, &why) && why && strstr(why, "Private"), "cube depth in Managed storage -> refused");
    CHECK(!n48dp_check(N48DP_T_2DARRAY, N48DP_USE_RT | N48DP_USE_WRITE, N48DP_ST_PRIVATE, ALL, &why) && why && strstr(why, "ShaderWrite"), "2D array depth with ShaderWrite -> refused");
    CHECK(!n48dp_check(N48DP_T_CUBE, N48DP_USE_READ | N48DP_USE_WRITE, N48DP_ST_PRIVATE, ALL, &why) && why && strstr(why, "ShaderWrite"), "cube depth with ShaderWrite -> refused");
    CHECK(!n48dp_check(N48DP_T_2DARRAY, N48DP_USE_RT, N48DP_ST_PRIVATE, N48DP_FEAT_SAMPLED, &why) && why && strstr(why, "attachment"), "2D array depth without the attachment feature -> refused for RenderTarget");
    CHECK(!n48dp_check(N48DP_T_CUBE, N48DP_USE_READ, N48DP_ST_PRIVATE, N48DP_FEAT_DS_ATT, &why) && why && strstr(why, "sample"), "cube depth without the sampled feature -> refused for ShaderRead");
    CHECK(n48dp_check(N48DP_T_2DARRAY, N48DP_USE_RT, N48DP_ST_PRIVATE, N48DP_FEAT_DS_ATT, &why), "2D array depth as a RenderTarget needs only the attachment feature");

    // ---- source pins on the REAL Navi48Device.m, n48_depth.h and n48_texdesc.h ----
    char *m = slurp(dir, "Navi48Device.m");
    char *dh = slurp(dir, "n48_depth.h");
    char *td = slurp(dir, "n48_texdesc.h");
    if (!m || !dh || !td) { printf("FAIL: cannot read the sources under %s\n", dir); fails++; }
    else {
        CHECK(strstr(dh, "enum { N48DP_T_2D = 2, N48DP_T_2DARRAY = 3, N48DP_T_2DMS = 4, N48DP_T_CUBE = 5 };") != NULL, "n48_depth.h names the 2D array (3) and cube (5) texture types");
        CHECK(strstr(m, "(int)MTLTextureType2DArray == N48DP_T_2DARRAY") != NULL && strstr(m, "(int)MTLTextureTypeCube == N48DP_T_CUBE") != NULL,
              "Navi48Device.m checks the 2D array and cube type values against the SDK enum");
        CHECK(strstr(m, "if (!n48dp_check((unsigned long)tt, (unsigned long)d.usage, (unsigned long)d.storageMode, (unsigned)ff, &why))") != NULL,
              "a depth texture descriptor (any accepted type) goes through n48dp_check in the texture init");
        CHECK(strstr(m, "n48zi_clear_depth_stencil(_img, n48zi_ds_aspects(_aspects), (uint32_t)_levels, (uint32_t)ti.layers)") != NULL,
              "a new depth texture is zeroed over all of its layers (ti.layers: the array length, or six cube faces)");
        CHECK(strstr(m, "VkImageSubresourceRange rg = { aspects, 0, levels, 0, layers };") != NULL, "the depth zero-init clear range names every layer");
        CHECK(strstr(m, ".subresourceRange = { isDS ? n48dp_view_aspect(_aspects) : VK_IMAGE_ASPECT_COLOR_BIT, 0, (uint32_t)_levels, 0, ti.layers } };") != NULL,
              "the sampling view of a depth texture has its depth aspect over every layer");
        CHECK(strstr(m, "views[na] = [dt n48AttViewLevel:(uint32_t)lvl layer:(uint32_t)slc]; _views[na] = views[na]; _tex[na] = dt;") != NULL,
              "a depth attachment is the view of its slice (per-layer depth attachment)");
        CHECK(strstr(m, "if (!_root && lv == 0 && ly == 0 && _levels <= 1 && !_viewSwz && !n48td_is_layered2d(_tdk) && sameAsp) return _view;") != NULL,
              "a layered depth texture never uses its sampling view as an attachment (one 2D view per layer)");
        CHECK(strstr(m, "BOOL wholeImg = [dt n48Levels] > 1 || [dt n48Layers] > 1;") != NULL, "a layered depth texture moves every layer to the attachment layout before a pass");
        CHECK(strstr(m, ".subresourceRange = { n48dp_barrier_aspect([t n48Aspects]), 0, [t n48Levels], 0, [t n48Layers] } };") != NULL,
              "the layout barrier of a depth texture names its depth aspect and every layer");
        CHECK(strstr(m, "ii[nii++] = (VkDescriptorImageInfo){ VK_NULL_HANDLE, tv, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };") != NULL,
              "a sampled depth texture is bound with its sampling view in the read-only layout");
        CHECK(strstr(m, "- (VkImageView)n48SampleView { return _smpView ? _smpView : _view; }") != NULL, "sampling reads the texture's sampling view (2D array or cube)");
        CHECK(strstr(td, "static inline int n48td_is_layered2d(unsigned kind) { return kind == N48TD_K_CUBE || kind == N48TD_K_2DARRAY; }") != NULL,
              "cube and 2D array textures are layered 2D images (per-layer attachment views)");
        CHECK(strstr(td, "if (tt == N48TD_MTL_CUBEARRAY) { o->why = \"cube-array textures") != NULL, "cube arrays stay refused in the texture descriptor mapping");
    }
    free(m); free(dh); free(td);

    printf("test-deptharray: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
