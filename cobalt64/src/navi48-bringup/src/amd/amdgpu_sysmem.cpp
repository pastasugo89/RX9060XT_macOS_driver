#include "amdgpu_sysmem.h"
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOLib.h>
#include "native_hostimport_pure.h"   // 0.0.671: collect_pages (the scattered page list of a GTT BO), kGttMaxBo, kOk (host-tested)

namespace amdgpu {

kern_return_t sysmem_alloc(SysMem &m, uint64_t size, uint64_t align) {
    sysmem_free(m);
    if (size == 0) return kIOReturnBadArgument;
    if (align < 4096) align = 4096;
    if (align & (align - 1)) return kIOReturnBadArgument;
    // physical mask: 48-bit addresses, low bits force alignment
    const mach_vm_address_t mask = 0x0000FFFFFFFFFFFFULL & ~(align - 1);
    IOBufferMemoryDescriptor *md = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(
        kernel_task, kIODirectionInOut | kIOMemoryPhysicallyContiguous | kIOMemoryMapperNone,
        size, mask);
    if (!md) return kIOReturnNoMemory;
    if (md->prepare() != kIOReturnSuccess) { md->release(); return kIOReturnNoMemory; }
    IOByteCount seg = 0;
    addr64_t phys = md->getPhysicalSegment(0, &seg, kIOMemoryMapperNone);
    void *cpu = md->getBytesNoCopy();
    if (!phys || !cpu || seg < size) { md->complete(); md->release(); return kIOReturnNoMemory; }
    bzero(cpu, (size_t)size);
    m.md = md; m.cpu = cpu; m.bus = phys; m.size = md->getLength();
    return kIOReturnSuccess;
}

void sysmem_free(SysMem &m) {
    if (m.md) { m.md->complete(); m.md->release(); }
    m.md = nullptr; m.cpu = nullptr; m.bus = 0; m.size = 0;
}

// The segment source of collect_pages over a prepare()d descriptor: the physical address of byte `off` and the length of the physically
// contiguous run there (0 for no such byte). CPU physical == bus: there is no IOMMU on this platform.
namespace {
struct PageRuns {
    IOMemoryDescriptor *md;
    uint64_t phys(uint64_t off, uint64_t *len) {
        IOByteCount seg = 0;
        const addr64_t pa = md->getPhysicalSegment((IOByteCount)off, &seg, kIOMemoryMapperNone);
        *len = pa != 0 ? (uint64_t)seg : 0ull;
        return (uint64_t)pa;
    }
};
}

kern_return_t sysmem_alloc_scattered(ScatteredMem &m, uint64_t size) {
    sysmem_free_scattered(m);
    if (size == 0 || (size & 4095ull) != 0 || size > n48native::s1c::kGttMaxBo) return kIOReturnBadArgument;
    const uint32_t npages = (uint32_t)(size / 4096ull);
    // Wired kernel memory from ordinary free pages: no kIOMemoryPhysicallyContiguous, so there is no run to search for, and the pages may be
    // anywhere in RAM. Page alignment is the only alignment the GPU needs (it maps each page on its own).
    IOBufferMemoryDescriptor *md = IOBufferMemoryDescriptor::inTaskWithOptions(
        kernel_task, kIODirectionInOut | kIOMemoryMapperNone, (vm_size_t)size, (vm_offset_t)4096);
    if (!md) return kIOReturnNoMemory;
    if (md->prepare() != kIOReturnSuccess) { md->release(); return kIOReturnNoMemory; }
    if (md->getLength() != size) { md->complete(); md->release(); return kIOReturnNoMemory; }
    uint64_t *pages = static_cast<uint64_t *>(IOMalloc((vm_size_t)(npages * sizeof(uint64_t))));
    if (pages == nullptr) { md->complete(); md->release(); return kIOReturnNoMemory; }
    PageRuns runs { md };
    if (n48native::s1c::collect_pages(runs, size, pages, npages) != n48native::s1c::kOk) {
        IOFree(pages, (vm_size_t)(npages * sizeof(uint64_t)));
        md->complete(); md->release();
        return kIOReturnNoMemory;
    }
    void *cpu = md->getBytesNoCopy();
    if (cpu == nullptr) {
        IOFree(pages, (vm_size_t)(npages * sizeof(uint64_t)));
        md->complete(); md->release();
        return kIOReturnNoMemory;
    }
    bzero(cpu, (size_t)size);
    m.md = md; m.cpu = cpu; m.pages = pages; m.size = size; m.npages = npages;
    return kIOReturnSuccess;
}

void sysmem_free_scattered(ScatteredMem &m) {
    if (m.md) { m.md->complete(); m.md->release(); }
    if (m.pages) IOFree(m.pages, (vm_size_t)((uint64_t)m.npages * sizeof(uint64_t)));
    m = ScatteredMem();
}

} // namespace amdgpu
