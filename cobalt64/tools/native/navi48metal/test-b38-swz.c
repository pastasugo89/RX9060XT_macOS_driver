// test-b38-swz.c - host test of n48_swz.h and of its use on every texture creation path of Navi48Device.m (bundle 38).
// Build/run: clang -Wall -Wextra -Werror -o /tmp/t test-b38-swz.c && /tmp/t [path/to/Navi48Device.m]
#include "n48_swz.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int fails;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL: %s\n", m); fails++; } else printf("ok: %s\n", m); } while (0)
int main(int argc, char **argv) {
    CHECK(!n48sw_wants_view(2, 3, 4, 5, 0, 0, 1), "identity swizzle -> no extra view");
    CHECK(n48sw_wants_view(2, 2, 2, 3, 0, 0, 1), "IconServices RG8 gray+alpha (R,R,R,G) -> swizzled view");
    CHECK(n48sw_wants_view(5, 4, 3, 2, 0, 0, 1), "full reversal -> swizzled view");
    CHECK(n48sw_wants_view(0, 0, 0, 1, 0, 0, 1), "constants (0,0,0,1) -> swizzled view");
    CHECK(!n48sw_wants_view(2, 2, 2, 3, 1, 0, 1), "depth/stencil keeps identity");
    CHECK(!n48sw_wants_view(2, 2, 2, 3, 0, 1, 1), "texture buffer keeps identity");
    CHECK(!n48sw_wants_view(2, 2, 2, 3, 0, 0, 4), "multisample keeps identity");
    CHECK(!n48sw_wants_view(6, 3, 4, 5, 0, 0, 1), "out-of-range channel ignored");
    const char *src = argc > 1 ? argv[1] : "Navi48Device.m";
    FILE *f = fopen(src, "r"); if (!f) { printf("FAIL: cannot open %s\n", src); return 1; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET); char *s = malloc(n + 1); fread(s, 1, n, f); s[n] = 0; fclose(f);
    const char *paths[] = { "\"texture\")", "\"iosurface\")", "\"iosurface, no CPU mapping\")", "\"buffer\")" };
    for (int i = 0; i < 4; i++) {
        char want[128]; snprintf(want, sizeof want, "_smpView = n48_desc_swizzle_view(d, _fmt, &");
        const char *p = s; int found = 0;
        while ((p = strstr(p, want))) { const char *e = strchr(p, ';'); if (e && strstr(p, paths[i]) && strstr(p, paths[i]) < e) { found = 1; break; } p++; }
        char m[160]; snprintf(m, sizeof m, "descriptor swizzle applied on the %s path", paths[i]); CHECK(found, m);
    }
    CHECK(strstr(s, "- (VkImageView)n48SampleView { return _smpView ? _smpView : _view; }") != NULL, "sampled bindings use n48SampleView");
    free(s);
    printf("%s (%d failure(s))\n", fails ? "FAILED" : "PASSED", fails);
    return fails ? 1 : 0;
}
