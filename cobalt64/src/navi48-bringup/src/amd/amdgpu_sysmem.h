//
//  amdgpu_sysmem.h — DMA-able system memory for the GPU (kernel IOKit).
//  Replaces the reference's IOBufferMemoryDescriptor::Create + IODMACommand
//  pairs: one physically contiguous, zeroed buffer with a CPU pointer and the
//  bus address the GPU uses (no IOMMU on this platform: bus == physical).
//
#pragma once
#include <stdint.h>
#include <IOKit/IOReturn.h>

class IOBufferMemoryDescriptor;

namespace amdgpu {

struct SysMem {
    IOBufferMemoryDescriptor *md { nullptr };
    void     *cpu  { nullptr };   // kernel virtual address
    uint64_t  bus  { 0 };         // GPU-visible address (48-bit)
    uint64_t  size { 0 };         // bytes (page-rounded)
    bool valid() const { return md != nullptr && cpu != nullptr && bus != 0; }
};

// Allocate `size` bytes, physically contiguous, aligned to `align` (>= 4096,
// power of two), zero-filled. Returns kIOReturnSuccess or an error.
// Kernel structures only (rings, IH, write-back and MES/CP blocks, allocated once at init): a contiguous request scans all of RAM and fails
// once memory is fragmented. Session memory (GTT BOs) uses sysmem_alloc_scattered below.
kern_return_t sysmem_alloc(SysMem &m, uint64_t size, uint64_t align = 4096);
void          sysmem_free (SysMem &m);

// 0.0.671: the memory of a GTT BO. Wired and zero-filled like SysMem, but NOT physically contiguous: the pages come from ordinary free memory and
// may be scattered, so the call never searches for a run. `md` is the kernel descriptor (the CPU mapping and the user mapping of the BO);
// `pages` holds the physical address of every 4 KiB page (IOMalloc'd, `npages` entries). The GPU reaches the memory only through its own page
// table, one PTE per page (native_gtt_pure.h). A descriptor and its page list are freed together by sysmem_free_scattered.
struct ScatteredMem {
    IOBufferMemoryDescriptor *md { nullptr };
    void     *cpu    { nullptr };   // kernel virtual address of byte 0 (one kernel mapping, whatever the physical layout)
    uint64_t *pages  { nullptr };   // physical address of each 4 KiB page
    uint64_t  size   { 0 };         // bytes, a whole number of pages
    uint32_t  npages { 0 };         // size / 4096
    bool valid() const { return md != nullptr && cpu != nullptr && pages != nullptr && npages != 0u && size == (uint64_t)npages * 4096ull; }
};
// `size`: a whole number of pages, 1..64 MiB. Returns kIOReturnSuccess (m.valid()) or an error; on error nothing is held. MAY BLOCK: never call it
// while a lock is held (IOBufferMemoryDescriptor's documented rule).
kern_return_t sysmem_alloc_scattered(ScatteredMem &m, uint64_t size);
void          sysmem_free_scattered(ScatteredMem &m);   // complete() + release() of the descriptor, then the page list; a no-op on an empty record

// Make CPU writes visible to the device / device writes visible to the CPU.
// Memory is mapped uncached-coherent on x86; these are compiler+store fences.
static inline void sysmem_wmb() { __asm__ __volatile__("sfence" ::: "memory"); }
static inline void sysmem_rmb() { __asm__ __volatile__("lfence" ::: "memory"); }

} // namespace amdgpu
