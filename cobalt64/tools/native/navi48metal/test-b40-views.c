// test-b40-views.c: host test of the bundle 40 texture views (n48_texdesc.h: n48td_view_map, n48td_view_default, n48td_mip_dim, n48td_image_level, n48td_image_layer),
// plus source pins that tie the REAL Navi48Device.m and Info.plist to them.
// Build/run (from this directory):  cc -O1 -Wall -Wextra -Werror -o /tmp/test-b40-views test-b40-views.c && /tmp/test-b40-views .
//   argv[1] = the directory holding Navi48Device.m, n48_texdesc.h and Info.plist (default ".").
// The rule this file enforces: a view is accepted exactly when Metal's view rules accept it (ref_accept below is written from those rules, not from the header), an accepted view
// names a subresource range that lies inside its root, and the bundle-9 request (a 2D view of level 0, slice 0 of a 2D texture) maps as it did before.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n48_texdesc.h"
static int fails, checks;
#define CHECK(c, ...) do { int ok_ = (c) ? 1 : 0; checks++; printf("%s: ", ok_ ? "ok  " : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!ok_) fails++; } while (0)
#define QUIET(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

// Metal's rules, spelled with the numeric values (Metal type: 2D 2, 2DArray 3, Cube 5, CubeArray 6, 1D 0, 1DArray 1, 3D 7, 2DMS 4, 2DMSArray 8, Buffer 9;
// root kind: 2D 0, 1D 1, 1DArray 2, 3D 3, Cube 4, 2DArray 5, 2DMS 6). A view of a 2D, cube or 2D-array root: a valid level range and slice range of the root; a 2D view
// covers one slice; a 2D-array view covers a cube or a 2D-array root (not a 2D root); a cube view covers all six slices of a cube root (its image is cube-compatible only then).
static int ref_accept(unsigned rk, unsigned layers, unsigned levels, unsigned long tt, unsigned long lo, unsigned long ln, unsigned long so, unsigned long sn) {
    unsigned long L = layers ? layers : 1, N = levels ? levels : 1;
    if (!(rk == 0 || rk == 4 || rk == 5)) return 0;
    if (ln == 0 || lo >= N || ln > N - lo) return 0;
    if (sn == 0 || so >= L || sn > L - so) return 0;
    if (tt == 5) return rk == 4 && so == 0 && sn == 6;
    if (tt == 2) return sn == 1;
    if (tt == 3) return rk != 0;
    return 0;
}
// The fields an accepted view must carry, from the same rules: the Vulkan view type and the layer count follow the Metal type; the ranges are the request's.
static int ref_fields(const n48td_view_t *v, unsigned long tt, unsigned long lo, unsigned long ln, unsigned long so, unsigned long sn) {
    if (!v->ok || v->why != NULL) return 0;
    if (v->baseLevel != lo || v->levels != ln) return 0;
    if (tt == 5) return v->kind == N48TD_K_CUBE && v->viewType == N48TD_VK_VIEW_CUBE && v->baseLayer == 0 && v->layers == 6;
    if (tt == 2) return v->kind == N48TD_K_2D && v->viewType == N48TD_VK_VIEW_2D && v->baseLayer == so && v->layers == 1;
    if (tt == 3) return v->kind == N48TD_K_2DARRAY && v->viewType == N48TD_VK_VIEW_2D_ARRAY && v->baseLayer == so && v->layers == sn;
    return 0;
}

static char *slurp(const char *dir, const char *name) {
    char p[1024]; snprintf(p, sizeof p, "%s/%s", dir, name); FILE *f = fopen(p, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET); char *b = calloc(1, (size_t)n + 1); if (fread(b, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(b); return NULL; } fclose(f); return b; }

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    n48td_view_t v;
    // ---- cube roots: six faces, a CUBE_COMPATIBLE image ----
    CHECK(n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 0, 7, 0, 6, &v) && v.ok && v.kind == N48TD_K_CUBE && v.viewType == N48TD_VK_VIEW_CUBE && v.layers == 6 && v.baseLayer == 0 && v.baseLevel == 0 && v.levels == 7,
          "cube root (7 levels): a cube view of every level and face -> VIEW_CUBE, 6 layers, levels 0+7");
    CHECK(n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 2, 3, 0, 6, &v) && v.baseLevel == 2 && v.levels == 3 && v.layers == 6, "cube view of mip levels 2+3 keeps the level range");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 5, 3, 0, 6, &v) && v.why && strstr(v.why, "mip levels"), "cube view past the last level (5+3 of 7) -> refused (\"%s\")", v.why ? v.why : "");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 7, 1, 0, 6, &v), "cube view starting at level 7 of 7 -> refused");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 0, 0, 0, 6, &v), "cube view with no levels -> refused");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 0, 7, 0, 5, &v) && v.why && strstr(v.why, "six faces"), "cube view of five faces -> refused (\"%s\")", v.why ? v.why : "");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 0, 7, 1, 6, &v) && !n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_CUBE, 0, 7, 0, 7, &v), "cube view not starting at face 0, or of seven faces -> refused");
    CHECK(n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_2D, 0, 1, 5, 1, &v) && v.kind == N48TD_K_2D && v.viewType == N48TD_VK_VIEW_2D && v.baseLayer == 5 && v.layers == 1 && v.levels == 1,
          "cube face view: a 2D view of face 5 (baseArrayLayer 5, one layer, level 0)");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_2D, 0, 1, 6, 1, &v), "2D view of face 6 (past the six faces) -> refused");
    CHECK(n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_2D, 3, 2, 4, 1, &v) && v.baseLevel == 3 && v.levels == 2 && v.baseLayer == 4, "2D view of face 4 at mip levels 3+2 -> accepted with the level range");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_2D, 0, 1, 0, 2, &v) && v.why && strstr(v.why, "one slice"), "2D view of two slices -> refused (\"%s\")", v.why ? v.why : "");
    CHECK(n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_2DARRAY, 0, 7, 1, 4, &v) && v.kind == N48TD_K_2DARRAY && v.viewType == N48TD_VK_VIEW_2D_ARRAY && v.baseLayer == 1 && v.layers == 4,
          "cube as a 2D-array view: slices 1+4 -> VIEW_2D_ARRAY, base layer 1, 4 layers");
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 7, N48TD_MTL_2DARRAY, 0, 1, 0, 7, &v), "2D-array view of seven slices of a cube -> refused");
    CHECK(!n48td_view_map(N48TD_K_2DARRAY, 6, 1, N48TD_MTL_CUBE, 0, 1, 0, 6, &v) && v.why && strstr(v.why, "cube-compatible"), "cube view of a 2D-array texture -> refused (\"%s\")", v.why ? v.why : "");
    // ---- 2D-array roots ----
    CHECK(n48td_view_map(N48TD_K_2DARRAY, 5, 3, N48TD_MTL_2D, 0, 3, 4, 1, &v) && v.kind == N48TD_K_2D && v.baseLayer == 4 && v.layers == 1 && v.levels == 3,
          "2D-array root (5 slices, 3 levels): a 2D view of slice 4 with every level");
    CHECK(!n48td_view_map(N48TD_K_2DARRAY, 5, 3, N48TD_MTL_2D, 0, 1, 5, 1, &v), "2D view of slice 5 of five -> refused");
    CHECK(n48td_view_map(N48TD_K_2DARRAY, 5, 3, N48TD_MTL_2DARRAY, 0, 3, 0, 5, &v) && v.viewType == N48TD_VK_VIEW_2D_ARRAY && v.layers == 5 && v.baseLayer == 0, "2D-array root: a 2D-array view of all five slices");
    CHECK(n48td_view_map(N48TD_K_2DARRAY, 5, 3, N48TD_MTL_2DARRAY, 2, 1, 2, 3, &v) && v.baseLayer == 2 && v.layers == 3 && v.baseLevel == 2 && v.levels == 1,
          "2D-array root: a 2D-array view of slices 2+3 at mip level 2");
    CHECK(!n48td_view_map(N48TD_K_2DARRAY, 5, 3, N48TD_MTL_CUBE, 0, 3, 0, 6, &v), "cube view of a 2D-array root -> refused (not cube-compatible)");
    CHECK(n48td_view_map(N48TD_K_2DARRAY, 1, 1, N48TD_MTL_2DARRAY, 0, 1, 0, 1, &v) && v.viewType == N48TD_VK_VIEW_2D_ARRAY && v.layers == 1, "a 2D-array of one slice: a 2D-array view of that slice (the type is kept)");
    // ---- 2D roots: the bundle-9 view and its level ranges ----
    CHECK(n48td_view_map(N48TD_K_2D, 1, 1, N48TD_MTL_2D, 0, 1, 0, 1, &v) && v.kind == N48TD_K_2D && v.viewType == N48TD_VK_VIEW_2D && v.baseLevel == 0 && v.levels == 1 && v.baseLayer == 0 && v.layers == 1,
          "2D root: the bundle-9 view (2D, level 0, slice 0) maps as before");
    CHECK(n48td_view_map(N48TD_K_2D, 0, 0, N48TD_MTL_2D, 0, 1, 0, 1, &v) && v.viewType == N48TD_VK_VIEW_2D, "a 2D root with zero slice and level counts counts as one of each");
    CHECK(n48td_view_map(N48TD_K_2D, 1, 7, N48TD_MTL_2D, 3, 4, 0, 1, &v) && v.baseLevel == 3 && v.levels == 4, "2D root (7 levels): a 2D view of mip levels 3+4");
    CHECK(!n48td_view_map(N48TD_K_2D, 1, 7, N48TD_MTL_2D, 0, 8, 0, 1, &v), "2D view of eight levels of seven -> refused");
    CHECK(!n48td_view_map(N48TD_K_2D, 1, 1, N48TD_MTL_2D, 0, 1, 0, 2, &v) && !n48td_view_map(N48TD_K_2D, 1, 1, N48TD_MTL_2D, 1, 1, 0, 1, &v), "2D root: two slices, or level 1 of one level -> refused");
    CHECK(!n48td_view_map(N48TD_K_2D, 1, 1, N48TD_MTL_2DARRAY, 0, 1, 0, 1, &v), "2D-array view of a 2D texture -> refused (not implemented)");
    CHECK(!n48td_view_map(N48TD_K_2D, 1, 1, N48TD_MTL_CUBE, 0, 1, 0, 6, &v), "cube view of a 2D texture -> refused");
    // ---- what stays refused ----
    CHECK(!n48td_view_map(N48TD_K_CUBE, 6, 1, N48TD_MTL_CUBEARRAY, 0, 1, 0, 6, &v) && v.why && strstr(v.why, "cube-array"), "cube-array view -> refused (\"%s\")", v.why ? v.why : "");
    CHECK(!n48td_view_map(N48TD_K_1D, 1, 1, N48TD_MTL_2D, 0, 1, 0, 1, &v) && v.why, "a 1D root is refused (\"%s\")", v.why ? v.why : "");
    CHECK(!n48td_view_map(N48TD_K_1DARRAY, 3, 1, N48TD_MTL_2DARRAY, 0, 1, 0, 3, &v) && !n48td_view_map(N48TD_K_3D, 1, 1, N48TD_MTL_2D, 0, 1, 0, 1, &v) &&
          !n48td_view_map(N48TD_K_2DMS, 1, 1, N48TD_MTL_2D, 0, 1, 0, 1, &v) && v.why, "1DArray, 3D and multisample roots -> refused with a reason");
    {   static const unsigned long refusedTypes[] = { 0, 1, 4, 6, 7, 8, 9, 99 };
        int allRefused = 1;
        for (size_t i = 0; i < sizeof refusedTypes / sizeof *refusedTypes; i++) {
            if (n48td_view_map(N48TD_K_CUBE, 6, 1, refusedTypes[i], 0, 1, 0, 6, &v) || n48td_view_map(N48TD_K_2D, 1, 1, refusedTypes[i], 0, 1, 0, 1, &v) || n48td_view_map(N48TD_K_2DARRAY, 4, 1, refusedTypes[i], 0, 1, 0, 4, &v)) allRefused = 0;
        }
        CHECK(allRefused, "1D, 1DArray, 2DMultisample, 3D, 2DMultisampleArray, buffer and unknown view types -> refused on every root");
    }
    // ---- the one-argument request (newTextureViewWithPixelFormat:) ----
    unsigned long tt = 0, lo = 0, ln = 0, so = 0, sn = 0;
    n48td_view_default(N48TD_K_CUBE, 6, 7, &tt, &lo, &ln, &so, &sn);
    CHECK(tt == N48TD_MTL_CUBE && lo == 0 && ln == 7 && so == 0 && sn == 6 && n48td_view_map(N48TD_K_CUBE, 6, 7, tt, lo, ln, so, sn, &v) && v.viewType == N48TD_VK_VIEW_CUBE,
          "one-argument view of a cube with 7 levels: a cube view of levels 0+7 and slices 0+6 (Metal's rule), and it is accepted");
    n48td_view_default(N48TD_K_2DARRAY, 4, 3, &tt, &lo, &ln, &so, &sn);
    CHECK(tt == N48TD_MTL_2DARRAY && lo == 0 && ln == 3 && so == 0 && sn == 4 && n48td_view_map(N48TD_K_2DARRAY, 4, 3, tt, lo, ln, so, sn, &v) && v.viewType == N48TD_VK_VIEW_2D_ARRAY,
          "one-argument view of a 2D array (4 slices, 3 levels): a 2D-array view of levels 0+3 and slices 0+4");
    n48td_view_default(N48TD_K_2D, 1, 9, &tt, &lo, &ln, &so, &sn);
    CHECK(tt == N48TD_MTL_2D && lo == 0 && ln == 9 && so == 0 && sn == 1 && n48td_view_map(N48TD_K_2D, 1, 9, tt, lo, ln, so, sn, &v) && v.viewType == N48TD_VK_VIEW_2D && v.levels == 9,
          "one-argument view of a 2D texture with 9 levels: a 2D view of every level and slice 0 (Metal's rule), and it is accepted");
    n48td_view_default(N48TD_K_2D, 0, 0, &tt, &lo, &ln, &so, &sn);
    CHECK(tt == N48TD_MTL_2D && ln == 1 && sn == 1, "one-argument view of a 2D texture with zero counts: the same bundle-9 view");
    // ---- helpers: mip sizes, image subresources ----
    CHECK(n48td_mip_dim(64, 0) == 64 && n48td_mip_dim(64, 3) == 8 && n48td_mip_dim(7, 1) == 3 && n48td_mip_dim(1, 5) == 1 && n48td_mip_dim(5, 2) == 1 && n48td_mip_dim(100, 70) == 1,
          "mip size: max(1, dim >> level), and a shift of 64 or more gives 1");
    CHECK(n48td_image_level(2, 3) == 5 && n48td_image_level(0, 0) == 0 && n48td_image_level(1, 0) == 1, "image level = the view's base level + the level");
    CHECK(n48td_image_layer(0, 5, 2) == 7 && n48td_image_layer(0, 0, 0) == 0 && n48td_image_layer(1, 3, 0) == 0, "image layer = the view's base layer + the slice; a 3D texture is layer 0");
    // ---- exhaustive sweep: the header against the reference, over every root kind and small ranges ----
    {   static const unsigned roots[][3] = { { 0, 1, 1 }, { 0, 1, 4 }, { 4, 6, 1 }, { 4, 6, 5 }, { 5, 1, 1 }, { 5, 2, 3 }, { 5, 6, 2 }, { 1, 1, 1 }, { 2, 3, 1 }, { 3, 1, 1 }, { 6, 1, 1 } };
        static const unsigned long types[] = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 99 };
        long total = 0, accepted = 0, mismatch = 0, badFields = 0, badRange = 0, badWhy = 0;
        for (size_t r = 0; r < sizeof roots / sizeof *roots; r++)
        for (size_t t = 0; t < sizeof types / sizeof *types; t++)
        for (unsigned long lo2 = 0; lo2 <= 6; lo2++) for (unsigned long ln2 = 0; ln2 <= 6; ln2++)
        for (unsigned long so2 = 0; so2 <= 6; so2++) for (unsigned long sn2 = 0; sn2 <= 6; sn2++) {
            unsigned rk = roots[r][0], L = roots[r][1], N = roots[r][2];
            n48td_view_t w; int got = n48td_view_map(rk, L, N, types[t], lo2, ln2, so2, sn2, &w); int exp = ref_accept(rk, L, N, types[t], lo2, ln2, so2, sn2);
            total++;
            if (got != exp) { mismatch++; QUIET(0, "root kind %u (%u slices, %u levels), type %lu, levels %lu+%lu, slices %lu+%lu: header %d, reference %d", rk, L, N, types[t], lo2, ln2, so2, sn2, got, exp); continue; }
            if (got) {
                accepted++;
                if (!ref_fields(&w, types[t], lo2, ln2, so2, sn2)) badFields++;
                if (w.baseLevel + w.levels > (N ? N : 1) || w.baseLayer + w.layers > (L ? L : 1)) badRange++;   // an accepted view lies inside its root
            } else if (!w.why || !w.why[0]) badWhy++;   // a refusal always says why
        }
        CHECK(mismatch == 0, "the header agrees with the reference on all %ld requests (%ld accepted)", total, accepted);
        CHECK(accepted == 572, "the sweep accepts exactly 572 requests (a hand count from the rules over the sweep's roots and ranges)");
        CHECK(badFields == 0 && badRange == 0 && badWhy == 0, "every accepted view has the reference's fields, lies inside its root, and every refusal names its reason (fields %ld, ranges %ld, reasons %ld)", badFields, badRange, badWhy);
    }
    // ---- source pins on the REAL Navi48Device.m and Info.plist ----
    char *m = slurp(dir, "Navi48Device.m");
    CHECK(m != NULL, "Navi48Device.m is readable");
    if (m) {
        CHECK(strstr(m, "- (instancetype)initViewOf:(N48Texture *)root textureType:(MTLTextureType)tt levels:(NSRange)lv slices:(NSRange)sl pixelFormat:(MTLPixelFormat)pf swizzle:(MTLTextureSwizzleChannels)swz error:(NSError **)err {") != NULL,
              "initViewOf takes the texture type, the level range and the slice range");
        CHECK(strstr(m, "if (!n48td_view_map(root->_tdk, n48td_nlayers((unsigned)root->_layers), (unsigned)(root->_levels ? root->_levels : 1), (unsigned long)tt,") != NULL,
              "the request is checked by n48td_view_map against the root's kind, slices and levels");
        CHECK(strstr(m, "root->_aspects ? n48dp_view_aspect(root->_aspects) : VK_IMAGE_ASPECT_COLOR_BIT, vd.baseLevel, vd.levels, vd.baseLayer, vd.layers } };") != NULL,
              "the view's subresource range is the mapped one (its levels and slices in the root)");
        CHECK(strstr(m, "_w = (NSUInteger)n48td_mip_dim(root->_w, vd.baseLevel)") != NULL && strstr(m, "_tdk = vd.kind; _layers = vd.layers; _levels = vd.levels; _depth = 1; _baseLevel = vd.baseLevel; _baseLayer = vd.baseLayer;") != NULL,
              "a view's size is its first level's, and its kind, layers, levels and base are the mapped ones");
        CHECK(strstr(m, "_stDropped = root->_stDropped;") != NULL, "a view inherits its root's dropped storage (a storage bind of it fails as on the root)");
        CHECK(strstr(m, "- (uint32_t)n48ViewLayers { return n48td_nlayers((unsigned)_layers); }") != NULL && strstr(m, "- (uint32_t)n48BaseLevel { return _baseLevel; }") != NULL &&
              strstr(m, "- (uint32_t)n48BaseLayer { return _baseLayer; }") != NULL, "n48ViewLayers, n48BaseLevel and n48BaseLayer report the view's own range");
        CHECK(strstr(m, "- (NSUInteger)mipmapLevelCount { return _levels ? _levels : 1; }") != NULL, "mipmapLevelCount is the view's own level count");
        CHECK(strstr(m, "- (NSUInteger)parentRelativeLevel { return _baseLevel; }") != NULL && strstr(m, "- (NSUInteger)parentRelativeSlice { return _baseLayer; }") != NULL,
              "parentRelativeLevel and parentRelativeSlice report the view's base");
        CHECK(strstr(m, "n48td_view_default(_tdk, n48td_nlayers((unsigned)_layers), (unsigned)(_levels ? _levels : 1), &tt, &lvLoc, &lvLen, &slLoc, &slLen);") != NULL,
              "the one-argument newTextureViewWithPixelFormat: takes its request from n48td_view_default");
        CHECK(strstr(m, "if (!v) N48LOG(\"newTextureView: refused: %s\", e ? e.localizedDescription.UTF8String : \"no reason given\");") != NULL, "a refused view logs its reason");
        CHECK(strstr(m, "- (VkImageView)n48AttViewLevel:(uint32_t)lv layer:(uint32_t)ly {\n    if (_root) {\n        if (lv == 0 && ly == 0 && _levels <= 1 && !n48td_is_layered2d(_tdk)) return _view;") != NULL,
              "a view's own sampling view is its attachment only for one level and one layer");
        CHECK(strstr(m, ".image = [self vkImage],\n            .viewType = (VkImageViewType)av.viewType") != NULL && strstr(m, "_baseLevel + lv, 1, _baseLayer + av.baseLayer, av.layerCount } };") != NULL,
              "the other attachment views are made on the root's image at the absolute level and slice");
        CHECK(strstr(m, "ca.slice >= [t n48ViewLayers]") != NULL && strstr(m, "slc >= [dt n48ViewLayers]") != NULL, "render pass slices are checked against the view's own slices");
        CHECK(strstr(m, "uint32_t nl = (uint32_t)[t mipmapLevelCount];") != NULL && strstr(m, "const uint32_t lvBase = [t n48BaseLevel], layBase = [t n48BaseLayer], layN = [t n48ViewLayers];") != NULL &&
              strstr(m, "lvBase + L - 1, layBase, layN") != NULL && strstr(m, "lvBase + L, layBase, layN") != NULL, "generateMipmapsForTexture runs over the view's own levels and slices");
        CHECK(strstr(m, "n48td_image_level(level, [t n48BaseLevel]), n48td_image_layer(is3, slice, [t n48BaseLayer])") != NULL, "buffer copies (n48_bic) address the view's level and slice");
        CHECK(strstr(m, "views of cube / 2D-array textures are not implemented") == NULL && strstr(m, "only a 2D view of level 0 slice 0 exists") == NULL,
              "the bundle-9 refusals of cube / 2D-array views and of level / slice ranges are gone");
        free(m);
    }
    printf("test-b40-views: %d checks, %d failed\n", checks, fails); return fails ? 1 : 0;
}
