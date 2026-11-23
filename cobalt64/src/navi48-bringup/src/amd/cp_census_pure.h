//
//  cp_census_pure.h - 0.0.677: boot-time, kernel-side observation of the command processor's busy state (pure tables and counting,
//  host-tested by tests/cp_census677_test.cpp against Linux gc_12_0_0_offset.h / gc_12_0_0_sh_mask.h).
//
//  WHY. With the display asleep the PMFW counts GFX 100 % busy; GRBM_STATUS2.CPF_BUSY is set in ~99.5 % of samples and CP_CPF_STATUS reads
//  0x88000001 (CPF_BUSY + CPF_CMP_BUSY + POST_WPTR_GFX_BUSY) in 100 % of samples while ME/PFP and the MEC are idle. Live register reads from user
//  space are no longer allowed, so the kext observes it itself, at boot, before the desktop:
//   * MARKS (default ON, navi48-cpmark=0 off): after every bring-up stage from CPInit on, and after clock gating / the fan step, 16 samples
//     50 us apart of UNBANKED status registers only (no select, no write): which stage first leaves the fetcher busy for good.
//   * CENSUS (default OFF, navi48-cpcensus=1): once, after the ladder, the per-queue HQD registers of the kernel GFX queue (me0/p0/q0), the
//     kernel compute queue slots (me1/p0/q0..1), the MES scheduler (me3/p0/q0) and the MES KIQ slot (me3/p1/q0). This needs GRBM_GFX_CNTL
//     select WRITES (as cp_dump_gfx_hqd / mes_queue_init already do at boot); it restores select 0. No *_HEADER_DUMP register is read (FIFO-like).
//
#pragma once
#include <stdint.h>

namespace n48cpc {

struct Reg { const char *name; uint32_t off; uint8_t idx; };   // absolute dword = GC base[idx] + off (gc_12_0_0_offset.h)

// Unbanked status registers read by the marks.
enum : uint32_t { kGrbmStatus = 0, kGrbmStatus2, kCpStat, kCpfStatus, kCpfBusy, kCpfBusy2, kCpfStalled1, kCpcStatus, kMesCntl, kRlcCpSched, kMarkRegs };
constexpr Reg kMark[kMarkRegs] = {
    { "GRBM_STATUS", 0x0da4, 0 }, { "GRBM_STATUS2", 0x0da2, 0 }, { "CP_STAT", 0x0f40, 0 }, { "CP_CPF_STATUS", 0x0e27, 0 },
    { "CP_CPF_BUSY_STAT", 0x0e28, 0 }, { "CP_CPF_BUSY_STAT2", 0x0e33, 0 }, { "CP_CPF_STALLED_STAT1", 0x0e29, 0 }, { "CP_CPC_STATUS", 0x0e24, 0 },
    { "CP_MES_CNTL", 0x2807, 1 }, { "RLC_CP_SCHEDULERS", 0x098a, 1 },
};

// The bits counted per mark (register, bit, name).
struct Bit { uint8_t reg; uint8_t bit; const char *name; };
constexpr Bit kBits[] = {
    { kGrbmStatus, 31, "GUI_ACTIVE" }, { kGrbmStatus, 29, "CP_BUSY" },
    { kGrbmStatus2, 28, "CPF_BUSY" }, { kGrbmStatus2, 29, "CPC_BUSY" }, { kGrbmStatus2, 30, "CPG_BUSY" }, { kGrbmStatus2, 26, "RLC_BUSY" },
    { kCpfStatus, 0, "POST_WPTR_GFX_BUSY" }, { kCpfStatus, 15, "HQD_BUSY" }, { kCpfStatus, 24, "MES_HQD_BUSY" }, { kCpfStatus, 26, "CPF_GFX_BUSY" },
    { kCpfStatus, 27, "CPF_CMP_BUSY" }, { kCpfStatus, 30, "CPC_CPF_BUSY" },
    { kCpcStatus, 0, "MEC1_BUSY" }, { kCpcStatus, 16, "MES_BUSY" },
};
constexpr uint32_t kBitCount = sizeof(kBits) / sizeof(kBits[0]);
constexpr uint32_t kMarkSamples = 16, kMarkGapUs = 50;

// Per-queue HQD registers read by the census (banked by GRBM_GFX_CNTL).
constexpr Reg kGfxHqd[] = {
    { "CP_GFX_HQD_ACTIVE", 0x1e80, 0 }, { "CP_GFX_HQD_RPTR", 0x1e88, 0 }, { "CP_GFX_HQD_CSMD_RPTR", 0x1e90, 0 }, { "CP_GFX_HQD_WPTR", 0x1e91, 0 },
    { "CP_GFX_HQD_WPTR_HI", 0x1e92, 0 }, { "CP_GFX_HQD_OFFSET", 0x1e8e, 0 }, { "CP_GFX_HQD_HQ_STATUS0", 0x1e98, 0 }, { "CP_GFX_HQD_MAPPED", 0x1e94, 0 },
    { "CP_RB0_RPTR", 0x0f60, 0 },
};
constexpr Reg kCmpHqd[] = {
    { "CP_HQD_ACTIVE", 0x1fab, 0 }, { "CP_HQD_VMID", 0x1fac, 0 }, { "CP_MQD_BASE_ADDR", 0x1fa9, 0 }, { "CP_HQD_PQ_RPTR", 0x1fb3, 0 },
    { "CP_HQD_PQ_WPTR_LO", 0x1fdf, 0 }, { "CP_HQD_PQ_WPTR_HI", 0x1fe0, 0 }, { "CP_HQD_PQ_CONTROL", 0x1fba, 0 },
    { "CP_HQD_PQ_DOORBELL_CONTROL", 0x1fb8, 0 }, { "CP_HQD_IQ_TIMER", 0x1fbf, 0 }, { "CP_HQD_DEQUEUE_REQUEST", 0x1fc1, 0 },
    { "CP_HQD_HQ_STATUS0", 0x1fc9, 0 }, { "CP_HQD_ERROR", 0x1fdc, 0 }, { "CP_HQD_EOP_RPTR", 0x1fd1, 0 }, { "CP_HQD_EOP_WPTR", 0x1fd2, 0 },
};
constexpr Reg kMesPipe[] = { { "CP_MES_INSTR_PNTR", 0x2813, 1 }, { "CP_MES_MSTATUS_LO", 0x2816, 1 } };
struct Slot { uint8_t me, pipe, queue; const char *what; };
constexpr Slot kSlots[] = { { 0, 0, 0, "kernel GFX queue" }, { 1, 0, 0, "KCQ slot q0" }, { 1, 0, 1, "KCQ slot q1" },
                            { 3, 0, 0, "MES scheduler" }, { 3, 1, 0, "MES KIQ slot (pipe 1)" } };

// GRBM_GFX_CNTL (PIPEID [1:0], MEID [3:2], VMID [7:4], QUEUEID [10:8]).
inline uint32_t grbm_select(uint32_t me, uint32_t pipe, uint32_t queue) { return (pipe & 3u) | ((me & 3u) << 2) | ((queue & 7u) << 8); }

struct Counts { uint32_t n; uint32_t set[kBitCount]; uint32_t first[kMarkRegs]; uint32_t last[kMarkRegs]; };
inline void count_sample(Counts &c, const uint32_t v[kMarkRegs]) {
    if (c.n == 0) for (uint32_t r = 0; r < kMarkRegs; r++) c.first[r] = v[r];
    for (uint32_t r = 0; r < kMarkRegs; r++) c.last[r] = v[r];
    for (uint32_t b = 0; b < kBitCount; b++) if ((v[kBits[b].reg] >> kBits[b].bit) & 1u) c.set[b]++;
    c.n++;
}

// navi48-cpmark: absent or non-zero = on; navi48-cpcensus: 1 = on.
inline bool mark_on(bool present, uint32_t v) { return !present || v != 0u; }
inline bool census_on(bool present, uint32_t v) { return present && v == 1u; }

}  // namespace n48cpc
