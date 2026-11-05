// bundle 35: refused no-copy imports are logged (region information, rate limited) and served by a copy (src/n48_nocopy.h, src/Navi48Device.m).
// Part 1: the pure rules: which refusal codes a copy stands in for, the copy size limit, the log rate.
// Part 2: source wiring, checked as text in Navi48Device.m (the .m needs Vulkan and Metal to link): the refusal note is on every NCFAIL, the device method
//         falls back only for the import-level codes and only with the kill switch absent, the copy is Shared and filled from the caller's pages, the dealloc
//         hands the caller's pointer back, command buffers record the copy-served buffers they use and refresh them before vkQueueSubmit, and the kill-file name.
// Build/run:  cc -O1 -Wall -Wextra -Werror -I. -o bin/test-b35-nocopy test-b35-nocopy.c && bin/test-b35-nocopy <dir holding Navi48Device.m and n48_nocopy.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "n48_nocopy.h"

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }
static int at(const char *hay, const char *needle) { const char *p = hay ? strstr(hay, needle) : NULL; return p ? (int)(p - hay) : -1; }

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char pm[1024]; snprintf(pm, sizeof pm, "%s/Navi48Device.m", dir);
    char *src = slurp(pm);
    check(src != NULL, "Navi48Device.m readable");

    // Part 1: the pure rules
    check(n48nc_falls_back(112) && n48nc_falls_back(114) && n48nc_falls_back(116) && n48nc_falls_back(117) && n48nc_falls_back(118),
          "copy fallback for the import-level refusals 112, 114, 116, 117, 118");
    check(!n48nc_falls_back(110) && !n48nc_falls_back(111) && !n48nc_falls_back(113) && !n48nc_falls_back(115) && !n48nc_falls_back(119) && !n48nc_falls_back(120) && !n48nc_falls_back(0),
          "no copy for the argument errors 110, 111, 113 (alignment: nil, as Metal), 115, 119, and 120");
    check(!n48nc_size_ok(0) && n48nc_size_ok(1) && n48nc_size_ok(64ull << 20) && n48nc_size_ok(256ull << 20) && !n48nc_size_ok((256ull << 20) + 1),
          "copy size: 1 byte to 256 MiB");
    int due_ok = 1; for (uint32_t k = 1; k <= 32; k++) due_ok &= n48nc_log_due(k) == 1;
    check(due_ok && !n48nc_log_due(33) && !n48nc_log_due(255) && n48nc_log_due(256) && !n48nc_log_due(257) && n48nc_log_due(512),
          "log rate: the first 32, then every 256th");

    // Part 2: source wiring
    if (src) {
        check(strstr(src, "#include \"n48_nocopy.h\"") != NULL, "n48_nocopy.h is included");
        check(strstr(src, "static void n48nc_refusal_note(const void *p, NSUInteger len, int code, const char *what) {") != NULL, "refusal note defined");
        check(strstr(src, "mach_vm_region_recurse(mach_task_self(), &a, &rsz, &depth,") != NULL, "refusal note reads the mapping (mach_vm_region_recurse, read-only)");
        check(strstr(src, "if (!n48nc_log_due(k)) return;") != NULL, "refusal note is rate limited");
        check(strstr(src, "N48LOG(\"newBufferWithBytesNoCopy: refused: %s\", m_.UTF8String); n48nc_refusal_note(p, len, code, m_.UTF8String);") != NULL,
              "every NCFAIL refusal calls the refusal note (region information in the log)");
        check(strstr(src, "if (!b && n48nc_falls_back((int)e.code) && n48nc_size_ok(len) && n48nc_fallback_on()) {") != NULL,
              "the device method falls back only for the import-level codes, within the size limit, with the kill switch absent");
        check(strstr(src, "static int n48nc_fallback_on(void) {") != NULL && strstr(src, "/private/tmp/n48m-nocopy-nofallback") != NULL,
              "kill switch /private/tmp/n48m-nocopy-nofallback, latched once per process");
        check(strstr(src, "+ (instancetype)n48NoCopyFallbackOn:(id)dev ptr:(void *)p length:(NSUInteger)len") != NULL, "copy constructor declared and defined");
        check(strstr(src, "(MTLResourceStorageModeShared | N48_OPT_NOZERO)") != NULL, "the copy is Shared host-visible memory, not zeroed (it is filled at once)");
        check(strstr(src, "memcpy(c->_ptr, p, len);") != NULL, "the copy is filled from the caller's pages");
        check(strstr(src, "c->_ncOrig = p; c->_ncFallback = YES; c->_deallocator = d ? [d copy] : nil;") != NULL,
              "the copy keeps the caller's pointer and takes over the deallocator");
        check(strstr(src, "d(_ncFallback ? _ncOrig : _ptr, _len);") != NULL, "dealloc hands the caller's pointer back to the deallocator");
        check(strstr(src, "- (void)n48NCSync { if (_ncFallback && _ncOrig && _ptr && _len) memcpy(_ptr, _ncOrig, _len); }") != NULL,
              "the copy is refreshed from the caller's pages (n48NCSync)");
        check(strstr(src, "fb = [(N48Texture *)o n48NCHostBuffer];") != NULL, "a texture made over a copy-served buffer is tracked by its command buffer");
        check(strstr(src, "- (void)n48NCNote:(N48Buffer *)b {") != NULL && strstr(src, "NSMutableArray *_ncbufs;") != NULL,
              "command buffers record the copy-served buffers they use");
        int sync_at = at(src, "[cb n48NCSync];"), submit_at = at(src, "VkResult r = vkQueueSubmit(N48R.q, 1, &si, fence);");
        check(sync_at >= 0 && submit_at > sync_at, "command buffers refresh the copies before vkQueueSubmit");
        check(strstr(src, "n48nc_size_ok(len)") != NULL && strstr(src, "n48_err(120,") != NULL, "a failed copy is reported (code 120), not silently nil");
    }
    printf("\n%d checks, %d failed\n", checks, fails);
    free(src);
    return fails ? 1 : 0;
}
