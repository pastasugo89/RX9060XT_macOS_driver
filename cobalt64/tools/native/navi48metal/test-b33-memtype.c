// bundle 33: memory-type choice for GPU-only allocations (src/n48_memtype.h), checked on a fake VkPhysicalDeviceMemoryProperties modelled on this device.
// Part 1: source wiring, checked as text in Navi48Device.m and Info.plist (the Objective-C file needs Vulkan and Metal to link).
// Part 2: the pure functions on the fake table (types and heaps as the RADV log lines "scanout: RADV memory type N" print them): the GPU-only
//         choice never lands on the CPU-visible heap (type 3/4), the fallback after VK_ERROR_OUT_OF_DEVICE_MEMORY is another device-local type
//         without host-visible, then host-coherent system memory up to the size cap; the CPU-visible and scanout choices are the old ones.
// Build/run:  cc -O1 -Wall -Wextra -Werror -I<mesa include> -I. -o bin/test-b33-memtype test-b33-memtype.c && bin/test-b33-memtype <dir holding Navi48Device.m and Info.plist>
//             (<mesa include> = research/ext/mesa-darwin/include, the Vulkan headers)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <vulkan/vulkan.h>
#include "n48_memtype.h"

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
static int has(const char *s, const char *needle) { return s && strstr(s, needle) != NULL; }

// ----------------------------------------------------------------------------------------------------------------- the fake device
// The table of this device (RX 9060 XT on the native kext, 217 MiB CPU-visible VRAM heap, no resizable BAR): see n48_memtype.h.
#define DL VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT
#define HV VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
#define HC VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
#define HK VK_MEMORY_PROPERTY_HOST_CACHED_BIT
static VkPhysicalDeviceMemoryProperties device_table(void) {
    VkPhysicalDeviceMemoryProperties mp; memset(&mp, 0, sizeof mp);
    mp.memoryHeapCount = 3;
    mp.memoryHeaps[0] = (VkMemoryHeap){ 15399ull << 20, VK_MEMORY_HEAP_DEVICE_LOCAL_BIT };   // the 15 GB heap
    mp.memoryHeaps[1] = (VkMemoryHeap){ 512ull << 20, 0 };                                    // GTT (system memory, 512 MiB cap)
    mp.memoryHeaps[2] = (VkMemoryHeap){ 217ull << 20, VK_MEMORY_HEAP_DEVICE_LOCAL_BIT };    // the CPU-visible VRAM heap
    static const struct { VkMemoryPropertyFlags f; uint32_t heap; } t[7] = {
        { DL, 0 }, { DL, 0 },                 /* 0 device-local, 1 the 32-bit device-local type */
        { HV | HC, 1 },                       /* 2 GTT write-combined */
        { DL | HV | HC, 2 }, { DL | HV | HC, 2 },   /* 3 CPU-visible VRAM, 4 its 32-bit type */
        { HV | HC | HK, 1 }, { HV | HC | HK, 1 }    /* 5 GTT cached, 6 its 32-bit type */
    };
    mp.memoryTypeCount = 7;
    for (uint32_t i = 0; i < 7; i++) { mp.memoryTypes[i].propertyFlags = t[i].f; mp.memoryTypes[i].heapIndex = t[i].heap; }
    return mp;
}
// Images and buffers allow {0,2,3,5}: RADV drops the 32-bit types (radv_buffer.c:188, radv_device.c:1784). 32-bit buffers allow {1,4,6}.
#define IMG_BITS 0x2du
#define BUF32_BITS 0x52u

// The flat copy Navi48Device.m makes (N48MT.n / N48MT.flags) right after vkGetPhysicalDeviceMemoryProperties.
static uint32_t flat[N48MT_MAX_TYPES]; static uint32_t nflat;
static void copy_flat(const VkPhysicalDeviceMemoryProperties *mp) {
    nflat = mp->memoryTypeCount < N48MT_MAX_TYPES ? mp->memoryTypeCount : N48MT_MAX_TYPES;
    for (uint32_t i = 0; i < nflat; i++) flat[i] = mp->memoryTypes[i].propertyFlags;
}
static int same_list(const uint32_t *got, uint32_t n, const uint32_t *want, uint32_t m) {
    if (n != m) return 0;
    for (uint32_t i = 0; i < n; i++) if (got[i] != want[i]) return 0;
    return 1;
}
static uint32_t plan_of(uint32_t bits, uint64_t size, uint32_t *out) { return n48mt_gpu_plan(bits, flat, nflat, size, N48MT_GTT_FALLBACK_MAX, out); }
static uint32_t plan_of_custom(uint32_t bits, const uint32_t *f, uint32_t nf, uint64_t size) {   /* the plan count for another table */
    uint32_t o[N48MT_MAX_TYPES]; return n48mt_gpu_plan(bits, f, nf, size, N48MT_GTT_FALLBACK_MAX, o);
}
static uint32_t fallbacks_of(uint32_t bits, uint64_t size, uint32_t first, uint32_t *out) {
    return n48mt_gpu_fallbacks(bits, flat, nflat, size, N48MT_GTT_FALLBACK_MAX, first, out);
}

int main(int argc, char **argv) {
    // ------------------------------------------------------------------------------------------- part 1: source wiring
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[1024];
    snprintf(path, sizeof path, "%s/Navi48Device.m", dir); char *m = slurp(path);
    snprintf(path, sizeof path, "%s/Info.plist", dir); char *pl = slurp(path);
    snprintf(path, sizeof path, "%s/n48_memtype.h", dir); char *h = slurp(path);
    if (!m || !pl || !h) { printf("FAIL: cannot read Navi48Device.m, Info.plist or n48_memtype.h in %s\n", dir); return 1; }

    check(has(m, "#include \"n48_memtype.h\""), "wiring: Navi48Device.m includes n48_memtype.h");
    check(!has(h, "#include <vulkan") && !has(h, "#include <Foundation") && !has(h, "#import") && !has(h, "#include <Metal"),
          "wiring: n48_memtype.h includes no Vulkan, Foundation or Metal header (plain C)");
    check(count(m, "n48_find_mem(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)") == 0 &&
          count(m, "n48_find_mem(nmr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)") == 0 &&
          count(m, "n48_find_mem(bits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)") == 0,
          "wiring: no GPU-only site still asks for the first DEVICE_LOCAL type (n48_find_mem DEVICE_LOCAL = 0 uses)");
    check(count(m, "n48_find_gpu_mem(") == 6, "wiring: n48_find_gpu_mem = its definition + the 5 GPU-only sites");
    check(count(m, "n48_gpu_vkalloc(") == 6, "wiring: n48_gpu_vkalloc = its definition + the 5 non-pooled GPU-only sites");
    check(has(m, "static VkResult n48_mem_alloc(uint32_t mt, VkMemoryRequirements mr, BOOL map, BOOL zero, VkBuffer b, VkImage i, N48Mem *m) {") &&
          has(m, "if (r != VK_ERROR_OUT_OF_DEVICE_MEMORY || map) return r;") &&
          has(m, "r = n48_mem_alloc_one(fb[k], mr, map, zero, b, i, m);"),
          "wiring: pooled allocator falls back only for GPU-only memory (map == NO) on VK_ERROR_OUT_OF_DEVICE_MEMORY");
    check(has(m, "static VkResult n48_gpu_vkalloc(VkMemoryRequirements mr, VkMemoryAllocateInfo *ma, VkDeviceMemory *mem) {") &&
          has(m, "r = vkAllocateMemory(N48R.dev, ma, NULL, mem);\n    for (uint32_t k = 0; r == VK_ERROR_OUT_OF_DEVICE_MEMORY && k < nfb; k++) {"),
          "wiring: non-pooled GPU-only allocation retries down the plan on VK_ERROR_OUT_OF_DEVICE_MEMORY");
    check(has(m, "n48mt_gpu_fallbacks(mr.memoryTypeBits, N48MT.flags, N48MT.n, mr.size, N48MT_GTT_FALLBACK_MAX, first, fb)") ||
          has(m, "n48mt_gpu_fallbacks(mr.memoryTypeBits, N48MT.flags, N48MT.n, mr.size, N48MT_GTT_FALLBACK_MAX, mt, fb)"),
          "wiring: both fallbacks are built from the same plan (n48_memtype.h)");
    check(has(m, "static int n48_find_gpu_mem(uint32_t bits) { return n48mt_gpu_first(bits, N48MT.flags, N48MT.n); }"),
          "wiring: n48_find_gpu_mem is the DEVICE_LOCAL-without-HOST_VISIBLE choice");
    check(has(m, "static void n48_mt_moved(uint32_t from, uint32_t to, uint64_t size) {") &&
          has(m, "atomic_fetch_add(&n48_mt_fallbacks, 1);") && has(m, "T1 memtype: a GPU-only allocation"),
          "wiring: a fallback is counted and its first occurrence logged");
    check(has(m, "N48MT.flags[i] = N48R.mp.memoryTypes[i].propertyFlags;") &&
          has(m, "vkGetPhysicalDeviceMemoryProperties(N48R.pd, &N48R.mp);\n        N48MT.n = "),
          "wiring: the flat type table is copied right after vkGetPhysicalDeviceMemoryProperties");
    // CPU-visible and scanout choices: unchanged from bundle 32.
    check(has(m, ": n48_find_mem(mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);"),
          "wiring: Shared buffers keep the first HOST_VISIBLE|HOST_COHERENT type");
    check(has(m, "N48S.vtype = n48_find_mem(0xFFFFFFFFu, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);"),
          "wiring: the scanout slot type stays DEVICE_LOCAL|HOST_VISIBLE|HOST_COHERENT");
    check(count(m, "n48_find_mem(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)") == 2,
          "wiring: the two scanout slot sites keep their visible-VRAM type");
    check(has(m, "sm == 2 ? n48_gpu_vkalloc(mr, &ma, &_vkmem) : vkAllocateMemory(N48R.dev, &ma, NULL, &_vkmem);"),
          "wiring: the non-pooled buffer fallback is for Private storage only (Shared keeps vkAllocateMemory)");
    // VK_EXT_memory_budget: the function, the enable, and the T1 line.
    check(has(m, "X(vkGetPhysicalDeviceMemoryProperties2) X(vkGetPhysicalDeviceQueueFamilyProperties)"), "wiring: vkGetPhysicalDeviceMemoryProperties2 is in the loaded function list");
    check(has(m, "if (!strcmp(ex[i].extensionName, VK_EXT_MEMORY_BUDGET_EXTENSION_NAME)) N48R.budgetExt = YES;") &&
          has(m, "if (N48R.budgetExt) devExts[nDevExts++] = VK_EXT_MEMORY_BUDGET_EXTENSION_NAME;") &&
          has(m, ".enabledExtensionCount = nDevExts, .ppEnabledExtensionNames = devExts"),
          "wiring: VK_EXT_memory_budget is enabled at device creation when RADV advertises it");
    check(has(m, "VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_BUDGET_PROPERTIES_EXT") && has(m, "vkGetPhysicalDeviceMemoryProperties2(N48R.pd, &m2);") &&
          has(m, "N48LOG(\"T1 vidmem/10s [%s pid %d]: %s; GPU-only memory-type fallbacks %llu\""),
          "wiring: the budget is read per heap and logged as the T1 vidmem line");
    check(count(m, "n48_vidmem_report();") == 1 && has(m, "static void n48_vidmem_report(void) {"), "wiring: the vidmem line is printed from the 10 s T1 tick");
    check(has(pl, "<key>CFBundleVersion</key>\n\t<string>33</string>"), "wiring: Info.plist CFBundleVersion is 33");

    // ------------------------------------------------------------------------------------------- part 2: the pure choice
    VkPhysicalDeviceMemoryProperties mp = device_table();
    copy_flat(&mp);
    check(nflat == 7 && N48MT_MAX_TYPES == 32 && N48MT_GTT_FALLBACK_MAX == (8ull << 20), "table: 7 types, 32 slots, GTT fallback cap 8 MiB");

    // the GPU-only first choice
    check(n48mt_gpu_first(IMG_BITS, flat, nflat) == 0, "gpu first: texture (bits 0x2d) -> type 0, the 15 GB heap");
    check(n48mt_gpu_first(BUF32_BITS, flat, nflat) == 1, "gpu first: 32-bit buffer (bits 0x52) -> type 1, still the 15 GB heap");
    check(n48mt_gpu_first(0x2cu, flat, nflat) == -1, "gpu first: types {2,3,5} only -> none (never the visible type 3)");
    check(n48mt_gpu_first(0x28u, flat, nflat) == -1, "gpu first: types {3,5} only -> none");
    check(n48mt_gpu_first(0x08u, flat, nflat) == -1, "gpu first: type {3} only -> none");
    check(n48mt_gpu_first(0u, flat, nflat) == -1, "gpu first: no bits -> none");

    // the CPU-visible and scanout choices: the old 'contains' rule, unchanged
    check(n48mt_find(IMG_BITS, flat, nflat, HV | HC) == 2, "cpu-visible (Shared): first HOST_VISIBLE|COHERENT -> type 2 (GTT), as bundle 32");
    check(n48mt_find(0x08u, flat, nflat, HV | HC) == 3, "cpu-visible: a visible-VRAM-only set still matches by 'contains' (old rule kept)");
    check(n48mt_find(0xFFFFFFFFu, flat, nflat, DL | HV | HC) == 3, "scanout: DEVICE_LOCAL|HOST_VISIBLE|COHERENT -> type 3 (the visible heap), as bundle 32");
    check(n48mt_find(0x2cu, flat, nflat, DL | HV | HC) == 3, "scanout: visible-VRAM type is the only one in {2,3,5} with DEVICE_LOCAL");

    // the whole plan and the fallbacks
    uint32_t out[N48MT_MAX_TYPES];
    uint32_t n = plan_of(IMG_BITS, 40u << 10, out); uint32_t w1[] = { 0, 2, 5 };
    check(same_list(out, n, w1, 3), "plan: texture of 40 KiB -> [0 (15 GB), 2 (GTT WC), 5 (GTT cached)]");
    n = plan_of(IMG_BITS, 14745600u, out); uint32_t w2[] = { 0 };
    check(same_list(out, n, w2, 1), "plan: 14.1 MiB texture -> [0] only (no system-memory fallback above the cap)");
    n = plan_of(IMG_BITS, N48MT_GTT_FALLBACK_MAX, out);
    check(same_list(out, n, w1, 3), "plan: size exactly at the cap still gets the system-memory entries");
    n = plan_of(IMG_BITS, N48MT_GTT_FALLBACK_MAX + 1, out);
    check(same_list(out, n, w2, 1), "plan: one byte above the cap -> no system-memory entries");
    n = plan_of(BUF32_BITS, 1u << 20, out); uint32_t w3[] = { 1, 6 };
    check(same_list(out, n, w3, 2), "plan: 32-bit buffer of 1 MiB -> [1 (15 GB 32-bit), 6 (GTT cached 32-bit)]");
    n = fallbacks_of(IMG_BITS, 40u << 10, 0, out); uint32_t w4[] = { 2, 5 };
    check(same_list(out, n, w4, 2), "fallback after type 0 refused (40 KiB): type 2, then type 5 (never the visible type 3)");
    n = fallbacks_of(IMG_BITS, 14745600u, 0, out);
    check(n == 0, "fallback after type 0 refused (14 MiB): none (the allocation fails as before)");
    n = fallbacks_of(BUF32_BITS, 1u << 20, 1, out); uint32_t w5[] = { 6 };
    check(same_list(out, n, w5, 1), "fallback after type 1 refused: type 6 (system memory)");
    n = fallbacks_of(IMG_BITS, 40u << 10, 2, out); uint32_t w6[] = { 0, 5 };
    check(same_list(out, n, w6, 2), "fallback after a system-memory type refused: the other entries of the plan, in order");

    // simulate the -2 chain: each refused type is skipped; the first accepted entry is the placement
    {
        uint32_t refused[N48MT_MAX_TYPES]; (void)refused;
        uint32_t order[N48MT_MAX_TYPES]; uint32_t no = 0; order[no++] = 0;
        uint32_t fb[N48MT_MAX_TYPES]; uint32_t nf = fallbacks_of(IMG_BITS, 40u << 10, 0, fb);
        for (uint32_t k = 0; k < nf; k++) order[no++] = fb[k];
        int placed = -1;   /* type 0 and 2 refuse (VRAM and the first system heap full), 5 accepts */
        for (uint32_t k = 0; k < no && placed < 0; k++) if (order[k] != 0 && order[k] != 2) placed = (int)order[k];
        check(placed == 5, "simulated -2 chain: refusals of types 0 and 2 land the 40 KiB texture in type 5");
        check(no == 3 && order[0] == 0 && order[1] == 2 && order[2] == 5, "simulated -2 chain: the order is 0, 2, 5");
    }

    // exhaustive properties over every bit set of the 7 types and five sizes
    {
        const uint64_t sizes[5] = { 4096u, 1u << 20, N48MT_GTT_FALLBACK_MAX, N48MT_GTT_FALLBACK_MAX + 1, 1ull << 30 };
        int visible_free = 1, gtt_after_gpu = 1, gtt_host = 1, no_dupes = 1, bounded = 1;
        for (uint32_t bits = 0; bits < 128u; bits++) for (int s = 0; s < 5; s++) {
            uint32_t p[N48MT_MAX_TYPES]; uint32_t np = plan_of(bits, sizes[s], p);
            int seen_gtt = 0;
            if (np > 7) bounded = 0;
            for (uint32_t k = 0; k < np; k++) {
                const uint32_t t = p[k];
                if (t >= 7 || !(bits & (1u << t))) { bounded = 0; continue; }
                if ((flat[t] & (DL | HV)) == (DL | HV)) visible_free = 0;             /* never the CPU-visible device-local heap */
                const int gtt = (flat[t] & (DL | HV | HC)) == (HV | HC);
                if (gtt) seen_gtt = 1; else if (seen_gtt) gtt_after_gpu = 0;          /* device-local entries come first */
                if (!gtt && (flat[t] & (DL | HV)) != DL) gtt_host = 0;                 /* the rest is device-local without host-visible */
                for (uint32_t j = 0; j < k; j++) if (p[j] == t) no_dupes = 0;
            }
            if (np > 0 && sizes[s] > N48MT_GTT_FALLBACK_MAX) { for (uint32_t k = 0; k < np; k++) if (!((flat[p[k]] & DL) && !(flat[p[k]] & HV))) gtt_host = 0; }
        }
        check(visible_free, "exhaustive: no plan (any bits, any size) ever contains the CPU-visible device-local types 3 or 4");
        check(gtt_after_gpu, "exhaustive: device-local entries always come before the system-memory entries");
        check(gtt_host, "exhaustive: system-memory entries are host-visible+coherent and not device-local; above the cap only device-local entries appear");
        check(no_dupes && bounded, "exhaustive: no duplicate entries, no entry outside the bits, at most 7 entries");
    }

    // synthetic devices: edge cases the caller must not turn into a visible-heap allocation
    {
        const uint32_t onlyVisible[1] = { DL | HV | HC };
        check(n48mt_gpu_first(0x1u, onlyVisible, 1) == -1 && plan_of_custom(0x1u, onlyVisible, 1, 4096u) == 0,
              "synthetic: a device whose only device-local type is host-visible has no GPU-only choice");
        const uint32_t dlHvOnly[2] = { DL, HV };   /* host-visible but not coherent: not a fallback */
        uint32_t sp[N48MT_MAX_TYPES]; const uint32_t sn = n48mt_gpu_plan(0x3u, dlHvOnly, 2, 4096u, N48MT_GTT_FALLBACK_MAX, sp);
        check(n48mt_gpu_first(0x3u, dlHvOnly, 2) == 0 && sn == 1 && sp[0] == 0,
              "synthetic: a host-visible type without HOST_COHERENT is not used as a system-memory fallback");
    }

    printf("test-b33-memtype: %d checks, %d failed\n", checks, fails);
    free(m); free(pl); free(h);
    return fails ? 1 : 0;
}
