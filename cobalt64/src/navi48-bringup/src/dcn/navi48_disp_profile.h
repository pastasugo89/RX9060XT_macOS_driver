//
//  navi48_disp_profile.h - the display profile seam (ASIC=navi44 default, navi48 = Cobalt64's values).
//
//  PURE. Derives the primary display path's absolute BAR5 dwords from N4X_DISP_* (amd/asic_profile.h) and states which
//  multi-display features the profile supports. Navi 48 values are unchanged: the static asserts in navi48_modetrial_pure.h pin them.
//  Host test: tools/hosttests/test_disp_profile.cpp (every formula against dcn_4_1_0_offset.h).
//
//  Register groups of the DCN 4.1.0 DMU (segment 2, BASE_IDX 2) repeat every 0x124 dwords per pipe / link / DIG:
//  DP0..3 at 0x2122/0x2246/0x236a/0x248e (VID_STREAM_CNTL), DP_STEER_FIFO at +1, DIG0..3 FIFO_CTRL0 at 0x209b/0x21bf/...
//  (verified against dcn_4_1_0_offset.h).
//
#ifndef N48_DISP_PROFILE_H
#define N48_DISP_PROFILE_H

#include <stdint.h>
#include "../amd/asic_profile.h"

namespace n4xdisp {

constexpr uint32_t kSeg2 = 0x34c0u;        // DMU segment 2 base (dump: 0x34c0 on this card; the same DMU 4.1.0 on Navi 44 and 48)
constexpr uint32_t kIdxStride = 0x124u;    // per-link / per-DIG group stride

// The live (primary) path: DP link, DIG and PHY of the stream the GOP lights and Cobalt64 adopts (OTG0 / HUBP0 / DPP0 / MPCC0).
constexpr uint32_t kLitDp = N4X_DISP_DP_LINE;    // Navi 48: 1 (DP1 / DP_AUX1 / HPD2); Navi 44: 0 (DP0 / AUX0 / HPD1)
constexpr uint32_t kLitDig = N4X_DISP_DP_DIG;    // Navi 48: 1 (DIG1 / PHY B); Navi 44: 0 (DIG0 / PHY A), dump-confirmed
constexpr uint32_t kLitSymclk = N4X_DISP_DP_PHY; // SYMCLK<x> feeds the same PHY (Navi 48: SYMCLKB, Navi 44: SYMCLKA)

constexpr uint32_t dpVidAbs(uint32_t n) { return kSeg2 + 0x2122u + n * kIdxStride; }        // DPn_DP_VID_STREAM_CNTL
constexpr uint32_t dpSteerAbs(uint32_t n) { return kSeg2 + 0x2123u + n * kIdxStride; }      // DPn_DP_STEER_FIFO
constexpr uint32_t digFifoCtrl0Abs(uint32_t n) { return kSeg2 + 0x209bu + n * kIdxStride; } // DIGn_DIG_FIFO_CTRL0

// Multi-display features. Navi 44 refuses each one with a clean "not available on this profile" (no state is touched).
enum Feature { kFeatM6, kFeatM6Flip, kFeatM6Flip1, kFeatDisp2, kFeatDmubCmd, kFeatModeTrial };
constexpr bool supported(Feature f) {
#if defined(N4X_ASIC_NAVI44)
    (void)f; return false;
#else
    return f == kFeatModeTrial ? N4X_DISP_MODETRIAL_SUPPORTED != 0 : N4X_DISP_M6_SUPPORTED != 0;
#endif
}

}  // namespace n4xdisp

#endif /* N48_DISP_PROFILE_H */
