// n48_nocopy.h: bundle 35, refused no-copy imports (newBufferWithBytesNoCopy / newTextureWithBytesNoCopy). Pure C (no Vulkan, no Foundation).
// Host test: tests/test-b35-nocopy.c.
//
// Cause (2026-11-05, icons-ws/src/noc_probe.m, run with the installed bundle 34): the kernel wires a host range for READ AND WRITE
// (IOMemoryDescriptor::withAddressRange(..., kIODirectionInOut, task) then prepare(): src/navi48-bringup/src/amd/native_s1c.cpp:1604-1606).
// A range the caller maps read-only fails at prepare(). The path: RADV (research/ext/mesa-darwin/src/amd/vulkan/winsys/amdgpu/radv_amdgpu_bo.c:829,
// ac_drm_create_bo_from_user_mem) -> the darwin shim (src/amd/common/darwin/ac_darwin_kext.c:328-335, ACD_SEL_BO_IMPORT_HOST) -> n1c_bo_import_host.
// Any failure there is VK_ERROR_INVALID_EXTERNAL_HANDLE (radv_amdgpu_bo.c:831), and the bundle returned nil (bundle 34: Navi48Device.m, code 118).
// Measured: anonymous, file-backed private/shared and copy-on-write mappings with write access import; every read-only mapping is refused.
// CoreUI maps app Assets.car read-only (Finder: "r--/rw- SM=COW" in vmmap), so its renditions are the refused kind.
//
// Fix (bundle 35): a refused import in the classes below is served by a copy. The copy is refreshed from the caller's pages before every
// command buffer that uses it is submitted (NullMoth's plugin does the same: NVMTLDevice_contract.m, "COPIED ... resynced at every submission").
#ifndef N48_NOCOPY_H
#define N48_NOCOPY_H
#include <stdint.h>

// The refusals a copy can stand in for: 112 no VK_EXT_external_memory_host, 114 length above the per-BO import limit, 116 host pointer properties
// refused, 117 no common memory type, 118 vkAllocateMemory(import) refused (the kernel's read-only refusal). Argument errors stay nil as in Metal:
// 110 NULL, 111 storage mode, 113 pointer or length not page aligned, 115 vkCreateBuffer, 119 vkBindBufferMemory.
static inline int n48nc_falls_back(int code) { return code == 112 || code == 114 || code == 116 || code == 117 || code == 118; }

// The copy is made up to this size. The kernel's import limit is 64 MiB per BO; a larger range is copied up to 256 MiB.
#define N48NC_MAX_COPY_BYTES (256ull << 20)
static inline int n48nc_size_ok(uint64_t len) { return len > 0 && len <= N48NC_MAX_COPY_BYTES; }

// Log rate for refusals and fallbacks (k is the 1-based count in the process): the first 32, then every 256th.
static inline int n48nc_log_due(uint32_t k) { return k <= 32u || (k % 256u) == 0u; }

#endif
