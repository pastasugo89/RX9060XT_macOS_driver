// bundle 35: R8Uint (13) and R32Uint (53) in the colour format table, and the integer clear at each format's own channel width.
// Part 1: source wiring, checked as text in Navi48Device.m and Info.plist (the .m needs Vulkan and Metal to link):
//         both entries are in n48_fmts with N48F_UINT, n48_uint_bits exists, the attachment clear uses the format's width (not 16),
//         and CFBundleVersion is 35.
// Part 2: the pure converter n48if_clear_u at 8 and 32 bits (saturation at 2^bits - 1, truncation, NaN and negatives to 0).
// Build/run:  cc -O1 -Wall -Wextra -Werror -I. -o bin/test-b35-uintfmt test-b35-uintfmt.c && bin/test-b35-uintfmt <dir holding Navi48Device.m and Info.plist>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "n48_intfmt.h"

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }

// The line of the format table that starts with `prefix` (e.g. "{ MTLPixelFormatR8Uint,") must also name `flag` and `vk`.
static int table_line_has(const char *src, const char *prefix, const char *vk, const char *flag) {
    const char *p = strstr(src, prefix);
    if (!p) return 0;
    const char *e = strchr(p, '\n'); size_t n = e ? (size_t)(e - p) : strlen(p);
    char line[512]; if (n >= sizeof line) return 0;
    memcpy(line, p, n); line[n] = 0;
    return strstr(line, vk) != NULL && strstr(line, flag) != NULL;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char pm[1024], pp[1024];
    snprintf(pm, sizeof pm, "%s/Navi48Device.m", dir);
    snprintf(pp, sizeof pp, "%s/Info.plist", dir);
    char *src = slurp(pm), *plist = slurp(pp);
    check(src != NULL, "Navi48Device.m readable");
    check(plist != NULL, "Info.plist readable");
    if (src && plist) {
        check(table_line_has(src, "{ MTLPixelFormatR8Uint,", "VK_FORMAT_R8_UINT", "N48F_UINT"), "n48_fmts: R8Uint -> VK_FORMAT_R8_UINT, N48F_UINT");
        check(table_line_has(src, "{ MTLPixelFormatR32Uint,", "VK_FORMAT_R32_UINT", "N48F_UINT"), "n48_fmts: R32Uint -> VK_FORMAT_R32_UINT, N48F_UINT");
        check(table_line_has(src, "{ MTLPixelFormatRG16Uint,", "VK_FORMAT_R16G16_UINT", "N48F_UINT"), "n48_fmts: RG16Uint unchanged");
        check(strstr(src, "static unsigned n48_uint_bits(MTLPixelFormat f)") != NULL, "n48_uint_bits(MTLPixelFormat) defined");
        check(strstr(src, "f == MTLPixelFormatR8Uint ? 8u : f == MTLPixelFormatR32Uint ? 32u : 16u") != NULL, "n48_uint_bits: 8 for R8Uint, 32 for R32Uint, 16 otherwise");
        check(strstr(src, "const unsigned ub = n48_uint_bits([t pixelFormat]);") != NULL, "integer attachment clear reads the texture's own format width");
        check(strstr(src, "n48if_clear_u(c.red, ub), n48if_clear_u(c.green, ub), n48if_clear_u(c.blue, ub), n48if_clear_u(c.alpha, ub)") != NULL, "integer clear uses ub for all four channels");
        check(strstr(src, "n48if_clear_u(c.red, 16)") == NULL, "the hard-coded 16-bit integer clear is gone");
        check(strstr(plist, "<key>CFBundleVersion</key>\n\t<string>35</string>") != NULL, "Info.plist CFBundleVersion is 35");
    }
    // Part 2: the converter at the widths the new formats use. Metal's rules (n48_intfmt.h): NaN and <= 0 give 0, the fraction is truncated,
    // values >= 2^bits - 1 saturate.
    check(n48if_clear_u(300.0, 8) == 255, "8 bits: 300 saturates to 255");
    check(n48if_clear_u(1000.0, 8) == 255, "8 bits: 1000 saturates to 255 (not 1000, which the 16-bit clear gave)");
    check(n48if_clear_u(254.9, 8) == 254, "8 bits: 254.9 truncates to 254");
    check(n48if_clear_u(-5.0, 8) == 0, "8 bits: -5 gives 0");
    check(n48if_clear_u(__builtin_nan(""), 8) == 0, "8 bits: NaN gives 0");
    check(n48if_clear_u(1e10, 32) == 0xFFFFFFFFu, "32 bits: 1e10 saturates to 4294967295");
    check(n48if_clear_u(4294967296.0, 32) == 0xFFFFFFFFu, "32 bits: 2^32 saturates to 4294967295");
    check(n48if_clear_u(2.5, 32) == 2u, "32 bits: 2.5 truncates to 2");
    check(n48if_clear_u(-1.0, 32) == 0u, "32 bits: -1 gives 0");
    check(n48if_clear_u(65535.9, 16) == 65535u, "16 bits (RG16Uint): 65535.9 saturates to 65535 (unchanged)");
    printf("\n%d checks, %d failed\n", checks, fails);
    free(src); free(plist);
    return fails ? 1 : 0;
}
