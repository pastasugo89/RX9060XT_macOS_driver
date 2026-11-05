// native_gtt_test.cpp - build 0.0.671: a GTT BO is wired, zero-filled and NOT physically contiguous (src/amd/native_gtt_pure.h; the kernel side is
// src/amd/amdgpu_sysmem.cpp and src/amd/native_s1c.cpp). Host test, no IOKit:
//   clang++ -std=c++17 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -I src/navi48-bringup/src -I src/navi48-bringup/src/amd src/navi48-bringup/tests/native_gtt_test.cpp -o /tmp/native_gtt && /tmp/native_gtt src/navi48-bringup
//   (from the cobalt64 directory, as tools/hosttests/run-cobalt64-tests.py runs it. The argument is the navi48-bringup directory the source pins are
//   read from: the repo's, or a candidate tree's; it must contain src/amd/native_s1c.cpp and src/amd/amdgpu_sysmem.cpp.)
// Covers:
//   T1  gtt_size_ok / gtt_admit: malformed sizes (BadArg); the 64 MiB per-BO maximum and the 512 MiB client cap (NoMemory); no wrap; the admission
//       of a request after a free;
//   T2  gtt_collect over a fake descriptor: a fully scattered 64 MiB BO (16384 one-page runs), scattered runs of mixed lengths, every refusal;
//   T3  gtt_map into a real 4-level tree (a fake memory): a scattered 64 MiB BO mapped in pieces at BO offsets: every page resolves to ITS physical
//       page with exactly SYSTEM|SNOOPED|R|W; out-of-range or malformed ranges are refused without touching the tree; a failed map leaves no leaf;
//   T4  gtt_fence_pte_pa: each page's own address; out of range = 0; a fence PTE built from it is the page's address, not base + page * 4 KiB;
//   T5  the lifecycle over the pure functions: admit -> collect -> map -> fence -> unmap -> free, with the failed-flush rule (memory_may_free_after_flush);
//   T6  source pins of the REAL kernel code: BoCreate allocates before any lock and frees after the unlock, its GTT branch calls no contiguous
//       allocator, sysmem_alloc_scattered uses no contiguity flag, no GTT path reads b.sm.bus, the fence and the GEM map use the page list, and
//       the GTT CPU map hands out the wired descriptor.
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <map>
#include <array>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include "amd/native_gtt_pure.h"

using namespace n48native;
using namespace n48native::s1c;

static int gFail = 0, gRun = 0;
static void expect(bool ok, const char *what) { gRun++; if (!ok) { gFail++; std::printf("FAIL: %s\n", what); } }
static void expect_u(const char *what, uint64_t got, uint64_t want) {
    gRun++;
    if (got != want) { gFail++; std::printf("FAIL: %s: got %#llx want %#llx\n", what, (unsigned long long)got, (unsigned long long)want); }
}
static std::string slurp(const std::string &path) { std::ifstream f(path, std::ios::binary); std::stringstream ss; ss << f.rdbuf(); return ss.str(); }
static bool has(const std::string &s, const char *needle) { return s.find(needle) != std::string::npos; }
static size_t count_of(const std::string &s, const std::string &needle) { size_t n = 0, p = 0; while ((p = s.find(needle, p)) != std::string::npos) { n++; p += needle.size(); } return n; }
static bool in_order(const std::string &s, std::initializer_list<const char *> parts) {
    size_t at = 0;
    for (const char *p : parts) { const size_t f = s.find(p, at); if (f == std::string::npos) return false; at = f + 1; }
    return true;
}
// The source without its // comments (the pins match code, not prose).
static std::string code_only(const std::string &raw) {
    std::string code;
    std::istringstream lines(raw);
    for (std::string line; std::getline(lines, line);) {
        const size_t c = line.find("//");
        code += (c == std::string::npos ? line : line.substr(0, c)) + "\n";
    }
    return code;
}
// The code of one function: from its signature to the closing brace at column 0.
static std::string fn_body(const std::string &src, const std::string &sig) {
    const size_t a = src.find(sig);
    if (a == std::string::npos) return "";
    const size_t e = src.find("\n}\n", a);
    return code_only(e == std::string::npos ? src.substr(a) : src.substr(a, e - a + 3));
}

constexpr uint64_t MiB = 1ull << 20;

// ---- T1 ----------------------------------------------------------------------------------------------------------------------------------------
static void t1_admission() {
    expect(gtt_size_ok(kPage) && gtt_size_ok(kGttMaxBo) && !gtt_size_ok(0) && !gtt_size_ok(kGttMaxBo + kPage) && !gtt_size_ok(0x1800),
           "T1: a GTT size is a page multiple, non-zero, at most 64 MiB");
    expect_u("T1: size 0 is BadArg", gtt_admit(0, 0), kBadArg);
    expect_u("T1: an unaligned size is BadArg", gtt_admit(0x1800, 0), kBadArg);
    expect_u("T1: 64 MiB on an empty client: admitted", gtt_admit(kGttMaxBo, 0), kOk);
    expect_u("T1: 64 MiB + 4 KiB: NoMemory (per-BO maximum)", gtt_admit(kGttMaxBo + kPage, 0), kNoMemory);
    expect_u("T1: the cap: 448 MiB held + 64 MiB = 512 MiB: admitted", gtt_admit(kGttMaxBo, 448 * MiB), kOk);
    expect_u("T1: the cap: 449 MiB held + 64 MiB: NoMemory", gtt_admit(kGttMaxBo, 449 * MiB), kNoMemory);
    expect_u("T1: the running total near 2^64 does not wrap the cap open", gtt_admit(kPage, ~0ull - 100), kNoMemory);
    expect_u("T1: a free restores the room (512 MiB held after one 64 MiB free: admitted)", gtt_admit(kGttMaxBo, 448 * MiB), kOk);
    expect_u("T1: a request the cap refuses is refused whatever its size is", gtt_admit(kPage, kGttCap), kNoMemory);
}

// ---- T2 ----------------------------------------------------------------------------------------------------------------------------------------
struct FakeSeg {   // (physical base, length) runs laid end to end
    std::vector<std::pair<uint64_t, uint64_t>> runs;
    uint64_t phys(uint64_t off, uint64_t *len) {
        uint64_t base = 0;
        for (auto &r : runs) {
            if (off < base + r.second) { *len = r.second - (off - base); return r.first + (off - base); }
            base += r.second;
        }
        *len = 0; return 0;
    }
};
static void t2_collect() {
    static uint64_t out[kGttMaxPages];
    {   // the whole 64 MiB, every page in its own run and in a scattered order
        FakeSeg s; for (uint64_t i = 0; i < kGttMaxPages; i++) s.runs.push_back({ 0x100000000ull + ((i * 7919ull) % 20011ull) * 0x3000ull, kPage });
        std::memset(out, 0, sizeof out);
        expect_u("T2: a fully scattered 64 MiB BO collects", gtt_collect(s, kGttMaxBo, out, kGttMaxPages), kOk);
        bool same = true;
        for (uint64_t i = 0; i < kGttMaxPages; i++) same = same && out[i] == 0x100000000ull + ((i * 7919ull) % 20011ull) * 0x3000ull;
        expect(same, "T2: every scattered page is its own physical page, in BO order");
    }
    {   // runs of mixed length: 3, 1, 5 pages
        FakeSeg s; s.runs = { { 0x10000000, 3 * kPage }, { 0x30000000, kPage }, { 0x20000000, 5 * kPage } };
        expect_u("T2: mixed runs collect", gtt_collect(s, 9 * kPage, out, kGttMaxPages), kOk);
        expect(out[0] == 0x10000000 && out[2] == 0x10002000 && out[3] == 0x30000000 && out[4] == 0x20000000 && out[8] == 0x20004000,
               "T2: mixed runs give the right pages");
    }
    { FakeSeg s; s.runs = { { 0x10000000, 2 * kPage } };       expect_u("T2: the descriptor ends early", gtt_collect(s, 3 * kPage, out, kGttMaxPages), kNoMemory); }
    { FakeSeg s; s.runs = { { 0x10000800, 4 * kPage } };       expect_u("T2: an unaligned page address", gtt_collect(s, 2 * kPage, out, kGttMaxPages), kNoMemory); }
    { FakeSeg s; s.runs = { { 0, 4 * kPage } };                expect_u("T2: physical address 0", gtt_collect(s, 2 * kPage, out, kGttMaxPages), kNoMemory); }
    { FakeSeg s; s.runs = { { 0x0001000000000000ull, 4 * kPage } }; expect_u("T2: an address above the PTE field", gtt_collect(s, 2 * kPage, out, kGttMaxPages), kBadArg); }
    { FakeSeg s; s.runs = { { 0x10000000, 4 * kPage } };       expect_u("T2: a size that is not a page multiple", gtt_collect(s, 0x1800, out, kGttMaxPages), kBadArg); }
    { FakeSeg s; s.runs = { { 0x10000000, 4 * kPage } };       expect_u("T2: size 0", gtt_collect(s, 0, out, kGttMaxPages), kBadArg); }
    { FakeSeg s; s.runs = { { 0x10000000, 4 * kPage } };       expect_u("T2: 64 MiB + 4 KiB refused", gtt_collect(s, kGttMaxBo + kPage, out, kGttMaxPages), kBadArg); }
    { FakeSeg s; s.runs = { { 0x10000000, 4 * kPage } };       expect_u("T2: a page list too small for the size", gtt_collect(s, 4 * kPage, out, 3), kBadArg); }
}

// ---- T3 ----------------------------------------------------------------------------------------------------------------------------------------
struct FakeMem {   // page-table memory addressed by pa; pagesLeft limits the table pages (a failed map)
    std::map<uint64_t, std::array<uint64_t, 512>> t;
    uint64_t next = 0x100000000ull, pagesLeft = 1000000; uint64_t writes = 0;
    uint64_t rd(uint64_t pa, uint32_t idx) { auto it = t.find(pa); return it == t.end() ? 0 : it->second[idx]; }
    void wr(uint64_t pa, uint32_t idx, uint64_t v) { auto &tb = t[pa]; tb[idx] = v; writes++; }
    uint64_t alloc_page() { if (pagesLeft == 0) return 0; pagesLeft--; const uint64_t pa = next; next += 0x1000; t[pa] = {}; return pa; }
};
static uint64_t scattered_pa(uint64_t i) { return 0x200000000ull + ((i * 7919ull) % 20011ull) * 0x1000ull; }   // distinct for i < 20011
static void t3_map() {
    const uint64_t leafGtt = leaf_flags(N48N_VM_PAGE_READABLE | N48N_VM_PAGE_WRITEABLE, false, true);
    expect_u("T3: the GTT leaf is exactly SYSTEM|SNOOPED|R|W|VALID", leafGtt, kPteValid | kPteSystem | kPteSnooped | kPteRead | kPteWrite);
    static uint64_t pages[kGttMaxPages];
    for (uint64_t i = 0; i < kGttMaxPages; i++) pages[i] = scattered_pa(i);
    {   // the whole BO at once at a base in the low half, then pieces at odd BO offsets
        FakeMem m; const uint64_t root = m.alloc_page();
        expect_u("T3: a 64 MiB scattered BO maps", gtt_map(root, 0x200000ull, kGttMaxBo, 0, kGttMaxBo, pages, kGttMaxPages, leafGtt, m), kOk);
        bool ok = true, flags = true;
        for (uint64_t i = 0; i < kGttMaxPages; i++) {
            uint64_t leaf = 0; const uint64_t got = pt_walk(root, 0x200000ull + i * kPage, m, &leaf);
            if (got != pages[i]) ok = false;
            if ((leaf & ~kPtePaMask & ~kPteIsPte) != leafGtt) flags = false;
        }
        expect(ok, "T3: every page of the 64 MiB mapping resolves to its OWN physical page");
        expect(flags, "T3: every leaf carries exactly SYSTEM|SNOOPED|R|W|VALID");
        pt_unmap(root, 0x200000ull, kGttMaxPages, m);
        bool gone = true; for (uint64_t i = 0; i < kGttMaxPages; i++) if (pt_walk(root, 0x200000ull + i * kPage, m, nullptr) != 0) gone = false;
        expect(gone, "T3: unmapping the BO clears every leaf");
    }
    {   // a piece at BO offset 3 pages, 5 pages long, in the high half: page k maps pages[3 + k]
        FakeMem m; const uint64_t root = m.alloc_page();
        const uint64_t va = 0xFFFF800000400000ull, off = 3 * kPage, bytes = 5 * kPage;
        expect_u("T3: a piece at a BO offset maps (high half)", gtt_map(root, va, bytes, off, kGttMaxBo, pages, kGttMaxPages, leafGtt, m), kOk);
        bool ok = true;
        for (uint64_t k = 0; k < 5; k++) if (pt_walk(root, va + k * kPage, m, nullptr) != pages[3 + k]) ok = false;
        expect(ok, "T3: page k of the piece maps BO page 3 + k");
        uint64_t leaf = 0; expect_u("T3: the page after the piece is not mapped", pt_walk(root, va + bytes, m, &leaf), 0);
    }
    {   // refusals: nothing is written
        FakeMem m; const uint64_t root = m.alloc_page(); const uint64_t w0 = m.writes;
        expect_u("T3: a range past the end of the BO is refused", gtt_map(root, 0x200000ull, 2 * kPage, kGttMaxBo - kPage, kGttMaxBo, pages, kGttMaxPages, leafGtt, m), kBadArg);
        expect_u("T3: zero bytes are refused", gtt_map(root, 0x200000ull, 0, 0, kGttMaxBo, pages, kGttMaxPages, leafGtt, m), kBadArg);
        expect_u("T3: an unaligned offset is refused", gtt_map(root, 0x200000ull, kPage, 0x800, kGttMaxBo, pages, kGttMaxPages, leafGtt, m), kBadArg);
        expect_u("T3: a page list that is not the BO's (count mismatch) is refused", gtt_map(root, 0x200000ull, kPage, 0, kGttMaxBo, pages, 7, leafGtt, m), kBadArg);
        expect_u("T3: a null page list is refused", gtt_map(root, 0x200000ull, kPage, 0, kGttMaxBo, nullptr, kGttMaxPages, leafGtt, m), kBadArg);
        expect_u("T3: an oversized BO is refused", gtt_map(root, 0x200000ull, kPage, 0, kGttMaxBo + kPage, pages, kGttMaxPages + 1, leafGtt, m), kBadArg);
        expect(m.writes == w0, "T3: no refused map wrote to the tree");
    }
    {   // a failed map (no room for the tables) leaves no partial mapping
        FakeMem m; const uint64_t root = m.alloc_page(); m.pagesLeft = 2;   // the tree for 64 pages needs more tables than this
        const uint64_t va = 0x400000ull;
        expect_u("T3: a map with no table room fails", gtt_map(root, va, 64 * kPage, 0, kGttMaxBo, pages, kGttMaxPages, leafGtt, m), kNoMemory);
        bool none = true; for (uint64_t k = 0; k < 64; k++) if (pt_walk(root, va + k * kPage, m, nullptr) != 0) none = false;
        expect(none, "T3: a failed map leaves no leaf behind");
    }
}

// ---- T4 ----------------------------------------------------------------------------------------------------------------------------------------
static void t4_fence() {
    static uint64_t pages[kGttMaxPages];
    for (uint64_t i = 0; i < kGttMaxPages; i++) pages[i] = scattered_pa(i);
    expect_u("T4: page 0 is its own address", gtt_fence_pte_pa(pages, kGttMaxPages, 0), scattered_pa(0));
    expect_u("T4: page 9000 is its own address (not base + 9000 * 4 KiB)", gtt_fence_pte_pa(pages, kGttMaxPages, 9000), scattered_pa(9000));
    expect(gtt_fence_pte_pa(pages, kGttMaxPages, 9000) != pages[0] + 9000 * kPage, "T4: scattered pages differ from a contiguous run");
    expect_u("T4: the last page", gtt_fence_pte_pa(pages, kGttMaxPages, kGttMaxPages - 1), scattered_pa(kGttMaxPages - 1));
    expect_u("T4: a page past the BO is 0", gtt_fence_pte_pa(pages, kGttMaxPages, kGttMaxPages), 0ull);
    expect_u("T4: no page list is 0", gtt_fence_pte_pa(nullptr, 0, 0), 0ull);
}

// ---- T5 ----------------------------------------------------------------------------------------------------------------------------------------
// The lifecycle of one GTT BO over the pure functions, in the order the kext runs it: admit (twice), collect the pages (outside the locks), map at
// an offset, point a fence slot at a page, then the normal release: unmap, the flush of the unmap must be acknowledged, the fence slot cleared, the
// flush of the clear must be acknowledged, and only then the memory goes (memory_may_free_after_flush, as host_release does for host imports).
struct Bo { uint64_t size; uint64_t pages[kGttMaxPages]; uint64_t npages; bool mapped; bool fenced; bool freed; uint32_t cpuRetains; };
static void t5_lifecycle() {
    FakeSeg s; for (uint64_t i = 0; i < 64; i++) s.runs.push_back({ scattered_pa(i), kPage });
    static Bo b {}; b.size = 64 * kPage; b.npages = b.size / kPage;
    expect_u("T5: the pre-lock admission of 256 KiB", gtt_admit(b.size, 0), kOk);
    expect_u("T5: the admission under the lock with the running total", gtt_admit(b.size, 100 * MiB), kOk);
    expect_u("T5: the pages are collected (outside the locks)", gtt_collect(s, b.size, b.pages, kGttMaxPages), kOk);
    FakeMem m; const uint64_t root = m.alloc_page(); const uint64_t va = 0x800000ull;
    expect_u("T5: the BO maps at a GPU address", gtt_map(root, va, 16 * kPage, 8 * kPage, b.size, b.pages, b.npages, leaf_flags(N48N_VM_PAGE_READABLE, false, true), m), kOk);
    b.mapped = true;
    b.cpuRetains++;   // the user client takes the descriptor for IOConnectMapMemory64 (retain), released by XNU after the mapping
    expect(pt_walk(root, va, m, nullptr) == scattered_pa(8), "T5: the first mapped page is BO page 8, at its own address");
    expect_u("T5: a fence slot for page 3 names page 3's own address", gtt_fence_pte_pa(b.pages, b.npages, 3), scattered_pa(3));
    b.fenced = true;
    // release, normal mode: the unmap, its flush (acknowledged), the fence clear, its flush (acknowledged), then the free
    pt_unmap(root, va, 16, m); b.mapped = false;
    const uint32_t flushUnmap = 0u;
    expect(memory_may_free_after_flush(flushUnmap), "T5: an acknowledged flush after the unmap may free the memory");
    b.fenced = false;
    const uint32_t flushFence = 0u;
    if (memory_may_free_after_flush(flushFence)) b.freed = true;
    expect(b.freed && !b.mapped && !b.fenced, "T5: the memory is freed only after the unmap and the fence are gone and acknowledged");
    // the same release with an unacknowledged flush keeps the memory (it may still be translated)
    static Bo c {}; c.size = 64 * kPage; c.npages = 16; c.mapped = true;
    expect(!memory_may_free_after_flush(kTimeout), "T5: an unacknowledged flush keeps the GTT pages (no free)");
    expect(c.mapped && !c.freed, "T5: the kept BO stays mapped and allocated");
}

// ---- T6 ----------------------------------------------------------------------------------------------------------------------------------------
static void t6_source(const std::string &root) {
    const std::string s1c = code_only(slurp(root + "/src/amd/native_s1c.cpp"));
    const std::string sys = code_only(slurp(root + "/src/amd/amdgpu_sysmem.cpp"));
    expect(!s1c.empty() && !sys.empty(), "T6: the kernel sources are readable (pass the navi48-bringup directory)");
    if (s1c.empty() || sys.empty()) return;
    const std::string create = fn_body(s1c, "IOReturn n1c_bo_create(const N1cRef &ref, const n48n_gem_create_in *in, uint64_t out[4]) {");
    expect(!create.empty(), "T6: n1c_bo_create is found");
    expect(!has(create, "sysmem_alloc(") && !has(create, "kIOMemoryPhysicallyContiguous") && !has(create, "sysmem_alloc ("),
           "T6: BoCreate's GTT path calls no contiguous allocator");
    {   // the allocation is the first thing that can block: before the session lock and before EVERY IOLockLock of the function (a lock on the allocation's own line counts)
        const size_t alloc = create.find("sysmem_alloc_scattered(gm"), sess = create.find("sess_lock(ref, true)"), lock = create.find("IOLockLock(");
        expect(alloc != std::string::npos && sess != std::string::npos && lock != std::string::npos && alloc < sess && alloc < lock,
               "T6: BoCreate allocates the pages before the session lock and before any IOLockLock");
    }
    expect(in_order(create, { "sysmem_alloc_scattered(gm", "sess_lock(ref, true)", "IOLockLock(gCliLock)", "IOLockUnlock(gCliLock)", "sysmem_free_scattered(gm)" }),
           "T6: BoCreate's order is allocate, session lock, gCliLock, unlock, free of what the record did not take");
    expect(in_order(create, { "IOLockLock(gCliLock)", "gtt_admit(p.size, s->gttUsed)", "b.kind = kBoGtt; b.gtt = gm;", "IOLockUnlock(gCliLock)" }),
           "T6: the GTT admission is decided again under gCliLock, and the record takes the pages there");
    const std::string scat = fn_body(sys, "kern_return_t sysmem_alloc_scattered(");
    expect(!scat.empty() && has(scat, "inTaskWithOptions(") && !has(scat, "PhysicallyContiguous") && !has(scat, "inTaskWithPhysicalMask"),
           "T6: sysmem_alloc_scattered uses no contiguity flag and no physical mask");
    expect(has(scat, "collect_pages(") && has(scat, "IOMalloc("), "T6: the page list is collected per page (collect_pages), never assumed");
    const std::string contig = fn_body(sys, "kern_return_t sysmem_alloc(");
    expect(has(contig, "kIOMemoryPhysicallyContiguous"), "T6: sysmem_alloc (kernel structures) keeps its contiguous allocation");
    expect_u("T6: native_s1c.cpp has no contiguous GTT allocation left (sysmem_alloc( calls)", count_of(s1c, "sysmem_alloc("), 0);
    expect_u("T6: no GTT path reads the old single bus address (b.sm)", count_of(s1c, "b.sm") + count_of(s1c, "sm.bus"), 0);
    const std::string gemva = fn_body(s1c, "IOReturn n1c_gem_va(const N1cRef &ref, const n48n_gem_va *in) {");
    expect(has(gemva, "gtt_map(s->rootPa, q.stripped, in->map_size, in->offset_in_bo, b.size, b.gtt.pages, b.gtt.npages"),
           "T6: the GEM VA map of a GTT BO maps its own page list (gtt_map)");
    expect(!has(gemva, "basePa") && !has(gemva, "b.sm"), "T6: the single-base mapping of a GTT BO is gone");
    const std::string fence = fn_body(s1c, "static uint32_t resolve_fence(Session *s, uint32_t handle, uint32_t off, uint64_t *addr) {");
    expect(has(fence, "gtt_fence_pte_pa(b.gtt.pages, b.gtt.npages, page)"), "T6: a fence slot's PTE names the page's own address");
    const std::string mem = fn_body(s1c, "IOReturn n1c_memory_for_handle(const N1cRef &ref, uint32_t handle, IOOptionBits *options, IOMemoryDescriptor **memory) {");
    expect(has(mem, "b.gtt.md->retain();") && has(mem, "*memory = b.gtt.md;"), "T6: the GTT CPU map hands out the wired descriptor (retained)");
    expect_u("T6: both GTT frees go through sysmem_free_scattered", count_of(s1c, "sysmem_free_scattered(b.gtt)"), 2);
}

int main(int argc, char **argv) {
    t1_admission();
    t2_collect();
    t3_map();
    t4_fence();
    t5_lifecycle();
    if (argc > 1) t6_source(argv[1]);
    else { std::printf("FAIL: pass the navi48-bringup directory as the argument (the source pins need it)\n"); gFail++; gRun++; }
    if (gFail != 0) { std::printf("native_gtt_test: %d of %d checks FAILED\n", gFail, gRun); return 1; }
    std::printf("native_gtt_test: %d checks, 0 failures (T1 admission, T2 page list, T3 per-page GPU map, T4 fence PTEs, T5 lifecycle, T6 source pins)\n", gRun);
    return 0;
}
