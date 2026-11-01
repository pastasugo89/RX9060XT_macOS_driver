// bundle 34: zero-initialisation of new device-local resources (src/n48_zinit.h, src/Navi48Device.m).
// Part 1: source wiring and ordering, checked as text in Navi48Device.m and Info.plist (the .m needs Vulkan and Metal to link):
//         the clears come after the memory bind in BOTH the pooled and the non-pooled branch, the kill file is named, and the
//         image-clear entry point is loaded.
// Part 2: the pure decisions (n48zi_decide_texture / n48zi_decide_buffer / n48zi_fill_bytes) over every input that matters.
// Build/run:  cc -O1 -Wall -Wextra -Werror -I<mesa include> -I. -o bin/test-b34-zinit test-b34-zinit.c && bin/test-b34-zinit <dir holding Navi48Device.m and Info.plist>
//             (<mesa include> = research/ext/mesa-darwin/include, the Vulkan headers)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <vulkan/vulkan.h>
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
    check(count(m, "#include \"n48_zinit.h\"") == 1, "n48_zinit.h included once");
    check(count(m, "X(vkCmdClearColorImage)") == 1, "vkCmdClearColorImage loaded through the X-macro table");
    check(count(m, "#define N48_NOZINIT_FILE \"/private/tmp/n48m-nozinit\"") == 1, "kill file named /private/tmp/n48m-nozinit");
    check(count(m, "n48zi_decide_texture(n48zi_killed()") == 1, "texture decision called once");
    check(count(m, "n48zi_decide_buffer(n48zi_killed()") == 1, "buffer decision called once");
    check(count(m, "n48zi_clear_image(_img,") == 1, "image clear called once");
    check(count(m, "n48zi_fill_buffer(_vkbuf,") == 1, "buffer fill called once");
    check(count(m, "vkCmdClearColorImage(cmd, img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &z, 1, &rg);") == 1, "vkCmdClearColorImage recorded in the one-shot");
    check(count(m, "vkCmdFillBuffer(cmd, buf, 0, (VkDeviceSize)n, 0);") == 1, "vkCmdFillBuffer recorded in the one-shot");
    check(count(m, "[self setLayout:VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL]") == 1, "texture layout tracked after the clear");
    check(count(m, "n48_oneshot(&e, ^(VkCommandBuffer cmd) {") >= 2, "clears use the waited one-shot helper");
    long bPool = at(m, "vkBindImageMemory(N48R.dev, _img, _pm.mem, _pm.off)");
    long bNon = at(m, "vkBindImageMemory(N48R.dev, _img, _mem, 0)");
    long clr = at(m, "n48zi_clear_image(_img,");
    long vcm = at(m, "VkComponentMapping cm = n48_view_map(_fmt, _swz);");
    check(bPool > 0 && bNon > 0 && clr > 0 && vcm > 0, "texture: bind (pooled and direct), clear and view found");
    check(bPool < clr && bNon < clr && clr < vcm, "texture: the clear runs after BOTH memory binds and before the view");
    long fBPool = at(m, "vkBindBufferMemory(N48R.dev, _vkbuf, _pm.mem, _pm.off)");
    long fBNon = at(m, "vkBindBufferMemory(N48R.dev, _vkbuf, _vkmem, 0)");
    long fill = at(m, "n48zi_fill_buffer(_vkbuf,");
    long fLog = at(m, "N48LOGR(\"N48Buffer %p: %lu bytes");
    check(fBPool > 0 && fBNon > 0 && fill > 0 && fLog > 0, "buffer: bind (pooled and direct), fill and log found");
    check(fBPool < fill && fBNon < fill && fill < fLog, "buffer: the fill runs after BOTH memory binds and before the log line");
    check(count(m, "static BOOL n48zi_clear_image(") == 1 && count(m, "static BOOL n48zi_fill_buffer(") == 1, "helpers defined once");
    check(plist && count(plist, "<key>CFBundleVersion</key>\n\t<string>34</string>") == 1, "Info.plist CFBundleVersion is 34");

    printf("== part 2: pure decisions (src/n48_zinit.h)\n");
    check(n48zi_decide_texture(0, 0, 0, 1, 262144) == N48ZI_CLEAR, "texture: colour, single-sampled, app -> clear");
    check(n48zi_decide_texture(1, 0, 0, 1, 262144) == N48ZI_SKIP_KILL, "texture: kill file wins -> bundle 33 behaviour");
    check(n48zi_decide_texture(1, 1, 1, 4, 0) == N48ZI_SKIP_KILL, "texture: kill file wins over every other reason");
    check(n48zi_decide_texture(0, 1, 0, 1, 262144) == N48ZI_SKIP_WINDOWSERVER, "texture: WindowServer unchanged");
    check(n48zi_decide_texture(0, 0, 0, 1, 0) == N48ZI_SKIP_EMPTY, "texture: zero-size allocation skipped");
    check(n48zi_decide_texture(0, 0, 1, 1, 262144) == N48ZI_SKIP_DEPTH, "texture: depth/stencil skipped (no depth clear)");
    check(n48zi_decide_texture(0, 0, 0, 4, 262144) == N48ZI_SKIP_MULTISAMPLE, "texture: multisample skipped");
    check(n48zi_decide_texture(0, 0, 0, 2, 262144) == N48ZI_SKIP_MULTISAMPLE, "texture: 2x multisample skipped");
    check(n48zi_decide_buffer(0, 0, 0, 4096) == N48ZI_CLEAR, "buffer: private, app -> clear");
    check(n48zi_decide_buffer(0, 0, 1, 4096) == N48ZI_SKIP_HOSTVISIBLE, "buffer: host-visible never cleared here");
    check(n48zi_decide_buffer(1, 0, 0, 4096) == N48ZI_SKIP_KILL, "buffer: kill file -> bundle 33 behaviour");
    check(n48zi_decide_buffer(0, 1, 0, 4096) == N48ZI_SKIP_WINDOWSERVER, "buffer: WindowServer unchanged");
    check(n48zi_decide_buffer(0, 0, 0, 0) == N48ZI_SKIP_EMPTY, "buffer: zero-length skipped");
    check(n48zi_fill_bytes(0) == 0, "fill: 0 bytes -> nothing");
    check(n48zi_fill_bytes(1) == 0 && n48zi_fill_bytes(3) == 0, "fill: 1..3 bytes -> nothing (no partial word)");
    check(n48zi_fill_bytes(4) == 4, "fill: 4 bytes -> 4");
    check(n48zi_fill_bytes(1001) == 1000, "fill: 1001 bytes -> 1000 (whole words only)");
    check(n48zi_fill_bytes(1048576) == 1048576, "fill: 1 MiB -> 1 MiB");
    check(strcmp(n48zi_name(N48ZI_CLEAR), "clear") == 0 && strcmp(n48zi_name(N48ZI_SKIP_KILL), "skip (kill file)") == 0, "verdict names");

    printf("\n%d checks, %d failed\n", checks, fails);
    free(m); free(plist);
    return fails ? 1 : 0;
}
