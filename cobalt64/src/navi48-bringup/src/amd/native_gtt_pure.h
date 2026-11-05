//
//  native_gtt_pure.h - the pure half of the GTT BO (kext 0.0.671): a session's system-memory buffer is wired and zero-filled but NOT
//  physically contiguous. No kernel header: tests/native_gtt_test.cpp compiles this file and drives it. native_s1c.cpp (n1c_bo_create,
//  bo_release, n1c_gem_va, resolve_fence, n1c_memory_for_handle) and amdgpu_sysmem.cpp (sysmem_alloc_scattered) are the callers.
//
//  Why (0.0.670 evidence): every GTT BO was ONE physically contiguous run (sysmem_alloc, up to 64 MiB), requested while gCliLock was held. After
//  some uptime the wired RAM is fragmented: each such request scanned all of RAM (vm_page_find_contiguous, ~150 ms), found nothing and failed,
//  and every GPU client waited behind the lock (418 failures in two minutes; command latency 1 ms -> 100-700 ms). Now the pages come from
//  ordinary free memory, are allocated before any lock, and are mapped one by one, exactly as an imported host range already is
//  (native_hostimport_pure.h: collect_pages, pt_map_pages).
//
#pragma once
#include <stdint.h>

#include "native_hostimport_pure.h"   // collect_pages (the physical page list), pt_map_pages (the scattered mapper), kImportMaxPages

namespace n48native {
namespace s1c {

constexpr uint64_t kGttMaxPages = kGttMaxBo / kPage;   // 16384 pages: the page list of the largest GTT BO (128 KiB)
static_assert(kGttMaxPages == 16384u, "64 MiB / 4 KiB");

// The size rule of a GTT BO: non-zero, a whole number of pages, at most kGttMaxBo (the page list is sized for that).
constexpr bool gtt_size_ok(uint64_t size) { return size != 0ull && (size & (kPage - 1ull)) == 0ull && size <= kGttMaxBo; }

// The admission of a GTT BO of `size` bytes for a session whose GTT total is `gttUsed`: a malformed size is BadArg; the per-BO maximum and
// the per-client cap (kGttCap) are NoMemory. BoCreate asks twice: with gttUsed 0 BEFORE any page is allocated (so an oversized request costs
// nothing), and under the locks with the session's running total (the authoritative answer).
constexpr uint32_t gtt_admit(uint64_t size, uint64_t gttUsed) {
    if (size == 0ull || (size & (kPage - 1ull)) != 0ull) return kBadArg;
    if (size > kGttMaxBo || would_exceed(gttUsed, size, kGttCap)) return kNoMemory;
    return kOk;
}

// The physical page list of a GTT BO: one 4 KiB physical address per page of `size`, from the prepared descriptor through the segment
// source `s` (collect_pages: scattered runs are fine, a short run, an unaligned or zero address, or an address above the PTE field is refused).
template <class Seg>
inline uint32_t gtt_collect(Seg &s, uint64_t size, uint64_t *out, uint64_t cap) {
    if (!gtt_size_ok(size) || cap < size / kPage) return kBadArg;
    return collect_pages(s, size, out, cap);
}

// Map `bytes` of a GTT BO, starting at BO offset `off`, at GPU address `va`: page k of the range maps pages[off / 4096 + k], with the GTT leaf
// flags the caller passes (SYSTEM | SNOOPED). `boSize` is the BO's size and `npages` its page count (must be boSize / 4096). Same contract as
// pt_map_pages: every leaf is checked before any is written, so a failed call leaves no partial mapping. kOk / kNoMemory / kBadArg.
template <class M>
inline uint32_t gtt_map(uint64_t rootPa, uint64_t va, uint64_t bytes, uint64_t off, uint64_t boSize, const uint64_t *pages, uint64_t npages,
                        uint64_t leafFlagsIn, M &m) {
    if (!gtt_size_ok(boSize) || pages == nullptr || npages != boSize / kPage) return kBadArg;
    if (bytes == 0ull || ((bytes | off) & (kPage - 1ull)) != 0ull || !range_in_bo(off, bytes, boSize)) return kBadArg;
    return pt_map_pages(rootPa, va, bytes / kPage, pages + off / kPage, leafFlagsIn, m);
}

// The physical address a GTT fence slot's PTE names for page `page` of a GTT BO: that page's own address, never base + page * 4096 (the pages
// are not one run). 0 when the page is outside the BO.
inline uint64_t gtt_fence_pte_pa(const uint64_t *pages, uint64_t npages, uint64_t page) {
    return (pages != nullptr && page < npages) ? pages[page] : 0ull;
}

} // namespace s1c
} // namespace n48native
