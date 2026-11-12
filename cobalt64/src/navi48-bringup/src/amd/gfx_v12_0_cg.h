//
//  gfx_v12_0_cg.h - kext 0.0.675: GFX clock gating on GC 12.0.0 (Linux gfx_v12_0_update_gfx_clock_gating, ported in gfx_v12_0_cg_pure.h).
//
//  Boot-args:
//    navi48-cg=0       do not program clock gating (default 1 = gate, once, after the full bring-up ladder; Navi48Bringup::runStages)
//    navi48-cg-ints=0  leave the CP GUI-idle / context busy-empty interrupt enables untouched (default 1 = Linux's sequence; see
//                      gfx_v12_0_cg.cpp for why they are safe with navi48-interrupts=0)
//  Every register is logged before and after; the outcome is the registry property Navi48,ClockGating.
//
#pragma once
#include <stddef.h>
#include "amdgpu_regs.h"
#include "gfx_v12_0_cg_pure.h"

namespace amdgpu {

// Reads the boot-args. *ints receives navi48-cg-ints. Returns navi48-cg (default true).
bool gfx_cg_config(bool *ints);

// Records why clock gating was not attempted (n48cg::kWhyOff / kWhyNotFullPath) for the registry text.
void gfx_cg_skip(uint32_t why);

// Runs n48cg::update_gfx_clock_gating(enable = true) once on the live registers (GC base idx0/idx1 from discovery). sdma1: the second SDMA
// instance exists (Linux adev->sdma.num_instances > 1). Returns kIOReturnSuccess when the sequence completed (code ok).
kern_return_t gfx_v12_0_enable_clock_gating(const DeviceContext &dev, bool sdma1, bool ints);

// The registry text (n48cg::describe).
void gfx_cg_describe(char *buf, size_t cap);

}  // namespace amdgpu
