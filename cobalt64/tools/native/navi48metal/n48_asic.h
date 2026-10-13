// n48_asic.h - the board this Metal bundle is built for (build.sh: ASIC=navi44, the default, or ASIC=navi48).
// It must match the kext (`make ASIC=...`, src/navi48-bringup/src/amd/asic_profile.h) and the RADV it ships
// (mesa-patches/0010: gfx1200 / 0x7590 by default, -DRADV_DARWIN_NAVI48 for gfx1201 / 0x7550).
//
// Only what the bundle states as a constant lives here. The PCI vendor / device id are NOT: the bundle reads them
// from RADV (VkPhysicalDeviceProperties, n48_t1.h), so they follow the RADV build.
//
// Limits (Navi48Device.m N48_MAX_BUFFER_LENGTH / N48_RECOMMENDED_WORKING_SET, maxThreadsPerThreadgroup) are the same
// for both boards; checked against the RX 9060 XT's own vulkaninfo under Linux RADV
// (research/artifacts/mesa-radv/vulkaninfo_full.txt): maxStorageBufferRange 4294967295, maxComputeWorkGroupSize
// 1024 x 1024 x 1024, device-local heap 17095983104 B (15.92 GiB) > the 12 GiB recommended working set.
#ifndef N48_ASIC_H
#define N48_ASIC_H

#if defined(N4X_ASIC_NAVI48)
#define N48M_PRODUCT_NAME  "RX 9070 XT"     /* Navi 48, gfx1201, 1002:7550 */
#define N48M_GFX_NAME      "gfx1201"
#define N48M_PCI_DEVICE    0x7550u
#define N48M_COMPUTE_UNITS 64u
#else
#define N4X_ASIC_NAVI44 1
#define N48M_PRODUCT_NAME  "RX 9060 XT"     /* Navi 44, gfx1200, 1002:7590 */
#define N48M_GFX_NAME      "gfx1200"
#define N48M_PCI_DEVICE    0x7590u
#define N48M_COMPUTE_UNITS 32u
#endif

// The PCI device id the RADV inside the bundle must report: a mismatch means the bundle and its RADV were built
// for different boards (checked once at device creation, logged, not fatal).
static inline int n48m_radv_matches(unsigned vendor, unsigned device) {
    return vendor == 0x1002u && device == N48M_PCI_DEVICE;
}

#endif
