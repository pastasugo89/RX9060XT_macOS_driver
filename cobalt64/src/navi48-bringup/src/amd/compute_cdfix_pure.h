//
//  compute_cdfix_pure.h - 0.0.678: the ComputeDispatch stage's compute state on the kernel GFX queue (pure tables and the packet builder,
//  host-tested by tests/compute_cdfix678_test.cpp against Linux gc_12_0_0_offset.h / sh_mask.h and Mesa's GFX12 preamble).
//
//  WHY. 0.0.677's boot marks (Navi48,CpBusyMarks) show CP_CPF_STATUS = 0 after CPInit, MESInit, GFXInit, SDMAInit and PM4Test, and
//  0x88000001 (CPF_BUSY + CPF_CMP_BUSY + POST_WPTR_GFX_BUSY) in 16 of 16 samples after ComputeDispatch and for the rest of the boot. What the
//  ComputeDispatch stage does that PM4Test does not:
//    1. it dispatches a compute shader on the GFX ring with the COMPUTE_* persistent state left at its power-on values: nothing on this
//       driver ever writes COMPUTE_DISPATCH_INTERLEAVE, COMPUTE_DISPATCH_TUNNEL, COMPUTE_PERFCOUNT_ENABLE, COMPUTE_DISPATCH_PKT_ADDR_LO/HI,
//       COMPUTE_USER_ACCUM_0..3, COMPUTE_START_X/Y/Z or COMPUTE_STATIC_THREAD_MGMT_SE4..SE8 (the boot logs read the COMPUTE_* registers back
//       as random values before the first dispatch), and SE2/SE3 get all-CUs masks on a two-SE part. Linux has no kernel dispatch on the GFX
//       ring; every user-mode driver that dispatches there first emits the GFX12 compute preamble (Mesa ac_cmdbuf.c
//       gfx12_init_compute_preamble_state, plus RADV radv_queue.c: COMPUTE_START_* = 0 and COMPUTE_DISPATCH_INTERLEAVE through
//       SET_SH_REG_INDEX index 2 on the gfx queue). COMPUTE_DISPATCH_INTERLEAVE's only valid values are 0, 64, 128, 256, 512 (Mesa).
//    2. it reads sixteen COMPUTE_* SH registers of the live GFX pipe back through MMIO (dump_sh_readback, before and after the dispatch);
//       Linux never reads them while a queue runs.
//    3. it runs an INDIRECT_BUFFER on the GFX ring (CONTEXT_CONTROL + IB + fence): identical to gfx_v12_0_ring_test_ib and to every native
//       submission, so it stays.
//  The fix (navi48-cdfix absent or non-zero): the GFX12 compute preamble at the head of the dispatch IB (also in the native S1b compute
//  leg's IB), CU masks only for the SEs that exist, and no SH readback unless the dispatch failed. navi48-cdfix=0 = the 0.0.677 stream.
//  Sub-marks after the IB test, after the readback (0.0.677 stream only) and after the dispatch say on the next boot which step it was.
//
#pragma once
#include <stdint.h>

namespace n48cdfix {

// navi48-cdfix: absent or non-zero = the fix; 0 = the 0.0.677 stream (preamble absent, SH readback before and after the dispatch).
inline bool fix_on(bool present, uint32_t v) { return !present || v != 0u; }

// PM4 (soc15d.h / nvd.h): TYPE[31:30] = 3, COUNT[29:16] = payload dwords - 1, IT_OPCODE[15:8], SHADER_TYPE[1] (1 = compute).
constexpr uint32_t kOpSetShReg = 0x76u, kOpSetShRegIndex = 0x9Bu;
constexpr uint32_t kPacket3SetShRegStart = 0x2C00u;   // nvd.h PACKET3_SET_SH_REG_START
inline uint32_t type3_cs(uint32_t op, uint32_t countMinus1) { return (3u << 30) | ((countMinus1 & 0x3FFFu) << 16) | ((op & 0xFFu) << 8) | (1u << 1); }

// GC registers, BASE_IDX 0 (gc_12_0_0_offset.h).
constexpr uint32_t COMPUTE_START_X = 0x1ba4, COMPUTE_START_Y = 0x1ba5, COMPUTE_START_Z = 0x1ba6;
constexpr uint32_t COMPUTE_PERFCOUNT_ENABLE = 0x1bab;
constexpr uint32_t COMPUTE_DISPATCH_PKT_ADDR_LO = 0x1bae, COMPUTE_DISPATCH_PKT_ADDR_HI = 0x1baf;
constexpr uint32_t COMPUTE_STATIC_THREAD_MGMT_SE0 = 0x1bb6, COMPUTE_STATIC_THREAD_MGMT_SE1 = 0x1bb7;
constexpr uint32_t COMPUTE_STATIC_THREAD_MGMT_SE2 = 0x1bb9, COMPUTE_STATIC_THREAD_MGMT_SE3 = 0x1bba;
constexpr uint32_t COMPUTE_STATIC_THREAD_MGMT_SE8 = 0x1bc3;
constexpr uint32_t COMPUTE_USER_ACCUM_0 = 0x1bc4;   // .. _3 = 0x1bc7
constexpr uint32_t COMPUTE_STATIC_THREAD_MGMT_SE4 = 0x1bcb;   // .. SE7 = 0x1bce
constexpr uint32_t COMPUTE_DISPATCH_INTERLEAVE = 0x1bcf;
constexpr uint32_t COMPUTE_DISPATCH_TUNNEL = 0x1c1d;

// COMPUTE_DISPATCH_INTERLEAVE.INTERLEAVE_1D [9:0] = 64: RADV's value (preamble_state.gfx11.compute_dispatch_interleave), written on the gfx
// queue with SET_SH_REG_INDEX index 2 (radv_queue.c, ac_pm4_set_reg_custom(..., PKT3_SET_SH_REG_INDEX, 2)).
constexpr uint32_t kInterleave1D = 64u, kInterleaveIndex = 2u;
constexpr uint32_t kAllCUs = 0xFFFFFFFFu;   // SH0_CU_EN | SH1_CU_EN with spi_cu_en = 0xffff (Mesa compute_cu_en)

// Mesa: mask = i < info->max_se ? compute_cu_en : 0.
inline uint32_t se_mask(uint32_t se, uint32_t numSe) { return se < numSe ? kAllCUs : 0u; }

// The shader-engine count used for the masks: the discovery gc_info value when it is valid (1..8), else the ASIC profile's.
inline uint32_t num_se_of(bool topoValid, uint32_t topoNumSe, uint32_t profileNumSe) {
    if (topoValid && topoNumSe >= 1u && topoNumSe <= 8u) return topoNumSe;
    return (profileNumSe >= 1u && profileNumSe <= 8u) ? profileNumSe : 1u;
}

// One preamble row: a run of `n` consecutive registers from `off`, written with SET_SH_REG (index 0) or SET_SH_REG_INDEX (index != 0).
struct Row { const char *name; uint32_t off; uint32_t n; uint32_t index; };
constexpr Row kRows[] = {
    { "COMPUTE_START_X/Y/Z",               COMPUTE_START_X,                3, 0 },
    { "COMPUTE_PERFCOUNT_ENABLE",          COMPUTE_PERFCOUNT_ENABLE,       1, 0 },
    { "COMPUTE_DISPATCH_PKT_ADDR_LO/HI",   COMPUTE_DISPATCH_PKT_ADDR_LO,   2, 0 },
    { "COMPUTE_STATIC_THREAD_MGMT_SE8",    COMPUTE_STATIC_THREAD_MGMT_SE8, 1, 0 },
    { "COMPUTE_USER_ACCUM_0..3",           COMPUTE_USER_ACCUM_0,           4, 0 },
    { "COMPUTE_STATIC_THREAD_MGMT_SE4..7", COMPUTE_STATIC_THREAD_MGMT_SE4, 4, 0 },
    { "COMPUTE_DISPATCH_TUNNEL",           COMPUTE_DISPATCH_TUNNEL,        1, 0 },
    { "COMPUTE_DISPATCH_INTERLEAVE",       COMPUTE_DISPATCH_INTERLEAVE,    1, kInterleaveIndex },
};
constexpr uint32_t kRowCount = sizeof(kRows) / sizeof(kRows[0]);

// The value of register `off` in the preamble.
inline uint32_t value_of(uint32_t off, uint32_t numSe) {
    if (off >= COMPUTE_STATIC_THREAD_MGMT_SE4 && off <= COMPUTE_STATIC_THREAD_MGMT_SE4 + 3u) return se_mask(4u + (off - COMPUTE_STATIC_THREAD_MGMT_SE4), numSe);
    if (off == COMPUTE_STATIC_THREAD_MGMT_SE8) return se_mask(8u, numSe);
    if (off == COMPUTE_DISPATCH_INTERLEAVE) return kInterleave1D;
    return 0u;   // START_*, PERFCOUNT_ENABLE, DISPATCH_PKT_ADDR, USER_ACCUM_*, DISPATCH_TUNNEL
}

constexpr uint32_t kPreambleDwords = 5 + 3 + 4 + 3 + 6 + 6 + 3 + 3;   // 33

// Emit the preamble at pkt[at..]. gc0Base = the absolute dword base of GC segment 0 (0x1260 on this card). Returns the new length, or 0 when
// it would not fit in `cap` dwords or a register index would underflow PACKET3_SET_SH_REG_START.
inline uint32_t emit_preamble(uint32_t *pkt, uint32_t at, uint32_t cap, uint32_t gc0Base, uint32_t numSe) {
    if (pkt == nullptr || at + kPreambleDwords > cap) return 0;
    for (uint32_t r = 0; r < kRowCount; r++) {
        const Row &row = kRows[r];
        if (gc0Base + row.off < kPacket3SetShRegStart) return 0;
        const uint32_t idx = gc0Base + row.off - kPacket3SetShRegStart;
        pkt[at++] = type3_cs(row.index ? kOpSetShRegIndex : kOpSetShReg, row.n);
        pkt[at++] = idx | (row.index << 28);
        for (uint32_t i = 0; i < row.n; i++) pkt[at++] = value_of(row.off + i, numSe);
    }
    return at;
}

}  // namespace n48cdfix
