//
//  clkfloor.h - build 0.0.684: the display clock floors Linux's dcn401 clk_mgr sends through the DAL mailbox (NumOfDisplays, the DCFCLK hard
//  minimum and deep-sleep floor, the DISPCLK/DPPCLK hard minimums), sent ONCE at boot by the display monitor thread after the display arbitration
//  and before the UCLK fallback arms; and the boot clock trace (PMFW metrics CurrClock[] and the DFS readback around ufmon underflow events).
//  Every decision is in clkfloor_pure.h (host-tested by tests/dalfloor684_test.cpp).
//  Boot-args: navi48-dalfloor (absent = NumOfDisplays + DCFCLK + deep sleep + DISPCLK/DPPCLK; 0 = nothing sent; see parts_of), navi48-clklog
//  (absent = 600 s of trace after the floors; 0 = off; N = N seconds).
//  Callers: navi48_dcn.cpp arb_monitor_loop only (a kernel thread, no lock held). Never the interrupt handler, never under a display lock.
//
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "amdgpu_regs.h"

namespace amdgpu {

// The floors: once per boot. Sleeps on the PMFW (each message <= 2 s, each hard-minimum status poll <= 1 s). Returns the verdict
// (n48dalfloor::Verdict) and the DCFCLK floor it set (MHz, 0 = none) for the trace.
// hActive / vActive / hTotal / vTotal: OTG0's lit timing (0 = unreadable); nothing is sent unless it is the mode the values are for.
uint32_t dal_floor_run(const DeviceContext &dev, uint32_t hActive, uint32_t vActive, uint32_t hTotal, uint32_t vTotal, uint32_t *dcfFloorMhz);
// Navi48,DalFloor: what the floors found, planned and got.
void dal_floor_describe(char *t, size_t n);

// The clock trace. clktrace_poll runs every monitor poll (50 ms) while the display is on; it samples every 500 ms until the trace window
// ends, opens a burst on newEvents > 0 and logs a classified burst once its post window is sampled. Returns true when the registry text changed.
// clktrace_start: at the monitor's start (samples from then on, before the floors too). clktrace_floor: after the floors (the DCFCLK floor the
// samples are checked against; the trace window of navi48-clklog seconds starts then).
void clktrace_start(uint64_t nowMs);
void clktrace_floor(uint32_t dcfFloorMhz, uint64_t nowMs);
bool clktrace_poll(const DeviceContext &dev, uint64_t nowMs, uint64_t newEvents, bool pinned);
// Navi48,DisplayClocks.
void clktrace_describe(char *t, size_t n);

}  // namespace amdgpu
