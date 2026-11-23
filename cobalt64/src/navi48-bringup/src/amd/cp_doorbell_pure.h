//
//  cp_doorbell_pure.h - 0.0.677: the kernel GFX queue's doorbell in Linux's units (pure, host-tested by tests/gfx_doorbell677_test.cpp).
//
//  THE BUG (0.0.18 .. 0.0.676). Linux (MIT, gfx_v12_0.c:927) gives the kernel GFX ring
//      ring->doorbell_index = adev->doorbell_index.gfx_ring0 << 1        (0x8B << 1 = 0x116: a DWORD index of a QWORD-aligned 64-bit doorbell)
//  and uses that one number for the MQD's CP_RB_DOORBELL_CONTROL.DOORBELL_OFFSET, the MES ADD_QUEUE / RESET / REMOVE doorbell_offset and
//  WDOORBELL64(ring->doorbell_index) (byte offset index * 4 = 0x458). The doorbell windows are programmed in the same QWORD units
//  (gfx_v12_0_cp_set_doorbell_range): GFX = [(gfx_ring0 * 2) << 2, (gfx_userqueue_end * 2) << 2] = bytes [0x458, 0x7F8],
//  MEC = [(kiq * 2) << 2, (userqueue_end * 2) << 2] = bytes [0x000, 0x450].
//  Our kext programmed the windows exactly like Linux but used the UNSHIFTED gfx_ring0 (0x8B) as the queue's doorbell: the MQD said
//  DOORBELL_OFFSET 0x8B and every submission wrote its 64-bit doorbell at byte 0x22C - INSIDE THE COMPUTE WINDOW, below the GFX window, at an
//  odd dword. The GFX CP never sees that doorbell; the write lands in the MEC range on an offset no compute queue owns (an "unmapped" doorbell,
//  which the MES is told to handle), and the GFX queue only learns its new wptr through the wptr-poll path. On 2026-11-17, with the display
//  asleep and WindowServer at ~80 command buffers/s, CPF_BUSY was set in 99.5 % of 200 GRBM_STATUS2 samples while ME/PFP and the MEC were idle,
//  and the PMFW counted GFX 100 % busy.
//  CORRECTION (2026-11-17, live read-only data): CP_RB_DOORBELL_CONTROL reads 0xc000022c (offset 0x8B, EN, HIT=1): the GFX CP DOES receive the
//  doorbell at the old offset, so the window filter does not drop it and the doorbell is NOT the busy source. The Linux index stays available as
//  an OPT-IN (navi48-gfxdb=1) for a Linux-parity A/B; the default is the pre-0.0.677 index, i.e. exactly 0.0.676. The MES ring and the kernel
//  compute queue keep their dword indices.
//
#pragma once
#include <stdint.h>

namespace n48db {

enum Mode : uint32_t { kModeLinux = 1, kModeLegacy = 0 };
// navi48-gfxdb: 1 = Linux (opt-in); absent, 0 or anything else = the pre-0.0.677 index (the default, as 0.0.676).
inline uint32_t mode_of(bool present, uint32_t v) { return present && v == 1u ? kModeLinux : kModeLegacy; }
inline const char *mode_name(uint32_t m) { return m == kModeLegacy ? "dword index gfx_ring0, as 0.0.676 (default)" : "Linux qword index (gfx_ring0 << 1) (navi48-gfxdb=1)"; }

// The kernel GFX queue's doorbell index (DWORD units of BAR2, the number the MQD, the MES frames and the doorbell write all use).
inline uint32_t kgq_index(uint32_t gfx_ring0, uint32_t mode) { return mode == kModeLegacy ? gfx_ring0 : gfx_ring0 << 1; }
inline uint64_t byte_offset(uint32_t index) { return (uint64_t)index * 4u; }

// The window registers, Linux's encoding (gfx_v12_0_cp_set_doorbell_range): a BYTE offset, (idx * 2) << 2.
inline uint32_t window_reg(uint32_t navi10_index) { return (navi10_index * 2u) << 2; }

// Where a 64-bit doorbell at `index` lands: in the GFX window [gfxLo, gfxHi] (bytes), in the MEC window, or neither; and whether it is
// QWORD-aligned.
enum Where : uint32_t { kInGfx = 0, kInMec = 1, kOutside = 2 };
inline uint32_t where(uint32_t index, uint32_t gfxLo, uint32_t gfxHi, uint32_t mecLo, uint32_t mecHi) {
    const uint64_t b = byte_offset(index);
    if (b >= gfxLo && b <= gfxHi) return kInGfx;
    if (b >= mecLo && b <= mecHi) return kInMec;
    return kOutside;
}
inline bool qword_aligned(uint32_t index) { return (byte_offset(index) & 7u) == 0u; }
inline const char *where_name(uint32_t w) { return w == kInGfx ? "inside the GFX window" : w == kInMec ? "INSIDE THE COMPUTE (MEC) WINDOW" : "OUTSIDE both windows"; }

} // namespace n48db
