//
//  navi48_gopsnap.h - the GOP observation table (research/display/gop_vm_readout_plan.md; boot-arg navi48-gopsnap=1).
//
//  PURE DATA. The kext reads these registers ONCE, in attach() at start(), before any stage writes anything (dcn/navi48_dcn.cpp gopSnapshot),
//  and logs each one as `gopsnap: <name> abs <dword> = <value>`. Nothing here is written: the table is never handed to a write path.
//  Every row (name, BASE_IDX, offset) is checked against research/src .../dcn/dcn_4_1_0_offset.h by tools/hosttests/test_gopsnap.cpp.
//  BASE_IDX as in the header: 1 = DCCG segment, 2 = DMU segment 2 (0x34c0 on this card), 3 = DMU segment 3 (0x9000). The kext resolves
//  them with dcn41_abs_rd, the read-only twin used by the census (navi48_dispread.h).
//
//  Groups, in log order: OTG0..3 (control, status, timing, update lock) | ODM0..3 (OPTC data source = which OTG feeds which pipe)
//  | HUBPREQ0..3 (surface address, pitch: what the GOP scans, and where) | HUBP0..3 (enable, format) | DPP_TOP0..3 | MPCC0..3 | OPP_PIPE0..3
//  | DIG0..3 (front end / back end: which OTG and which link each DIG is connected to) | DP0..3 (DP side of the link encoder)
//  | UNIPHYA..D (link encoders) | SYMCLKA..D (symbol clocks) | HPD1..3 (hot-plug status) | RDPCSTX0..3 (PHY) | DMCUB (control, scratch,
//  INBOX1 / OUTBOX1 rings, REGION4 window). DMCUB rows are READS of the registers only: the ring contents are not read here.
//
//  Navi 44 (this card): DP = DIG0 / PHY A / AUX0 / HPD1 (VBIOS 113-P816G493-S05); HDMI-A-1 = DIG1 / PHY B / HPD2; HDMI-A-2 = DIG2 / PHY C / HPD3; no PHY D.
//  Which of these the GOP actually lights is what this table is for.
//
#ifndef N48_GOPSNAP_H
#define N48_GOPSNAP_H

#include <stdint.h>

struct n48gop_reg { const char *name; uint8_t base_idx; uint16_t off; };

#define N48GOP_COUNT 164u
static const struct n48gop_reg n48gop_regs[N48GOP_COUNT] = {
    { "OTG0_OTG_CONTROL", 2, 0x1b43 }, { "OTG0_OTG_STATUS", 2, 0x1b49 }, { "OTG0_OTG_STATUS_POSITION", 2, 0x1b4a }, { "OTG0_OTG_H_TOTAL", 2, 0x1b2a },
    { "OTG0_OTG_H_BLANK_START_END", 2, 0x1b2b }, { "OTG0_OTG_V_TOTAL", 2, 0x1b2f }, { "OTG0_OTG_V_BLANK_START_END", 2, 0x1b38 }, { "OTG0_OTG_MASTER_UPDATE_LOCK", 2, 0x1b89 },
    { "OTG1_OTG_CONTROL", 2, 0x1bc3 }, { "OTG1_OTG_STATUS", 2, 0x1bc9 }, { "OTG1_OTG_STATUS_POSITION", 2, 0x1bca }, { "OTG1_OTG_H_TOTAL", 2, 0x1baa },
    { "OTG1_OTG_H_BLANK_START_END", 2, 0x1bab }, { "OTG1_OTG_V_TOTAL", 2, 0x1baf }, { "OTG1_OTG_V_BLANK_START_END", 2, 0x1bb8 }, { "OTG1_OTG_MASTER_UPDATE_LOCK", 2, 0x1c09 },
    { "OTG2_OTG_CONTROL", 2, 0x1c43 }, { "OTG2_OTG_STATUS", 2, 0x1c49 }, { "OTG2_OTG_STATUS_POSITION", 2, 0x1c4a }, { "OTG2_OTG_H_TOTAL", 2, 0x1c2a },
    { "OTG2_OTG_H_BLANK_START_END", 2, 0x1c2b }, { "OTG2_OTG_V_TOTAL", 2, 0x1c2f }, { "OTG2_OTG_V_BLANK_START_END", 2, 0x1c38 }, { "OTG2_OTG_MASTER_UPDATE_LOCK", 2, 0x1c89 },
    { "OTG3_OTG_CONTROL", 2, 0x1cc3 }, { "OTG3_OTG_STATUS", 2, 0x1cc9 }, { "OTG3_OTG_STATUS_POSITION", 2, 0x1cca }, { "OTG3_OTG_H_TOTAL", 2, 0x1caa },
    { "OTG3_OTG_H_BLANK_START_END", 2, 0x1cab }, { "OTG3_OTG_V_TOTAL", 2, 0x1caf }, { "OTG3_OTG_V_BLANK_START_END", 2, 0x1cb8 }, { "OTG3_OTG_MASTER_UPDATE_LOCK", 2, 0x1d09 },
    { "ODM0_OPTC_DATA_SOURCE_SELECT", 2, 0x1acb }, { "ODM1_OPTC_DATA_SOURCE_SELECT", 2, 0x1adb }, { "ODM2_OPTC_DATA_SOURCE_SELECT", 2, 0x1aeb }, { "ODM3_OPTC_DATA_SOURCE_SELECT", 2, 0x1afb },
    { "HUBPREQ0_DCSURF_PRIMARY_SURFACE_ADDRESS", 2, 0x060a }, { "HUBPREQ0_DCSURF_PRIMARY_SURFACE_ADDRESS_HIGH", 2, 0x060b }, { "HUBPREQ0_DCSURF_SURFACE_PITCH", 2, 0x0607 }, { "HUBP0_DCHUBP_CNTL", 2, 0x05f4 },
    { "HUBP0_DCSURF_SURFACE_CONFIG", 2, 0x05e5 }, { "HUBPREQ1_DCSURF_PRIMARY_SURFACE_ADDRESS", 2, 0x06e6 }, { "HUBPREQ1_DCSURF_PRIMARY_SURFACE_ADDRESS_HIGH", 2, 0x06e7 }, { "HUBPREQ1_DCSURF_SURFACE_PITCH", 2, 0x06e3 },
    { "HUBP1_DCHUBP_CNTL", 2, 0x06d0 }, { "HUBP1_DCSURF_SURFACE_CONFIG", 2, 0x06c1 }, { "HUBPREQ2_DCSURF_PRIMARY_SURFACE_ADDRESS", 2, 0x07c2 }, { "HUBPREQ2_DCSURF_PRIMARY_SURFACE_ADDRESS_HIGH", 2, 0x07c3 },
    { "HUBPREQ2_DCSURF_SURFACE_PITCH", 2, 0x07bf }, { "HUBP2_DCHUBP_CNTL", 2, 0x07ac }, { "HUBP2_DCSURF_SURFACE_CONFIG", 2, 0x079d }, { "HUBPREQ3_DCSURF_PRIMARY_SURFACE_ADDRESS", 2, 0x089e },
    { "HUBPREQ3_DCSURF_PRIMARY_SURFACE_ADDRESS_HIGH", 2, 0x089f }, { "HUBPREQ3_DCSURF_SURFACE_PITCH", 2, 0x089b }, { "HUBP3_DCHUBP_CNTL", 2, 0x0888 }, { "HUBP3_DCSURF_SURFACE_CONFIG", 2, 0x0879 },
    { "HUBP0_DCSURF_ADDR_CONFIG", 2, 0x05e6 }, { "HUBP0_DCSURF_TILING_CONFIG", 2, 0x05e7 }, { "HUBP0_DCSURF_PRI_VIEWPORT_START", 2, 0x05e9 }, { "HUBP0_DCSURF_PRI_VIEWPORT_DIMENSION", 2, 0x05eb },
    { "DPP_TOP0_DPP_CONTROL", 2, 0x0cc5 }, { "DPP_TOP1_DPP_CONTROL", 2, 0x0e30 }, { "DPP_TOP2_DPP_CONTROL", 2, 0x0f9b }, { "DPP_TOP3_DPP_CONTROL", 2, 0x1106 },
    { "MPCC0_MPCC_CONTROL", 3, 0x0003 }, { "MPCC0_MPCC_STATUS", 3, 0x000e }, { "MPCC1_MPCC_CONTROL", 3, 0x0018 }, { "MPCC1_MPCC_STATUS", 3, 0x0023 },
    { "MPCC2_MPCC_CONTROL", 3, 0x002d }, { "MPCC2_MPCC_STATUS", 3, 0x0038 }, { "MPCC3_MPCC_CONTROL", 3, 0x0042 }, { "MPCC3_MPCC_STATUS", 3, 0x004d },
    { "OPP_PIPE0_OPP_PIPE_CONTROL", 2, 0x188c }, { "OPP_PIPE1_OPP_PIPE_CONTROL", 2, 0x18e6 }, { "OPP_PIPE2_OPP_PIPE_CONTROL", 2, 0x1940 }, { "OPP_PIPE3_OPP_PIPE_CONTROL", 2, 0x199a },
    { "DIG0_DIG_FE_CNTL", 2, 0x2093 }, { "DIG0_DIG_FE_CLK_CNTL", 2, 0x2094 }, { "DIG0_DIG_FE_EN_CNTL", 2, 0x2095 }, { "DIG0_DIG_BE_CNTL", 2, 0x20bc },
    { "DIG0_DIG_BE_CLK_CNTL", 2, 0x20bb }, { "DIG0_DIG_BE_EN_CNTL", 2, 0x20bd }, { "DIG1_DIG_FE_CNTL", 2, 0x21b7 }, { "DIG1_DIG_FE_CLK_CNTL", 2, 0x21b8 },
    { "DIG1_DIG_FE_EN_CNTL", 2, 0x21b9 }, { "DIG1_DIG_BE_CNTL", 2, 0x21e0 }, { "DIG1_DIG_BE_CLK_CNTL", 2, 0x21df }, { "DIG1_DIG_BE_EN_CNTL", 2, 0x21e1 },
    { "DIG2_DIG_FE_CNTL", 2, 0x22db }, { "DIG2_DIG_FE_CLK_CNTL", 2, 0x22dc }, { "DIG2_DIG_FE_EN_CNTL", 2, 0x22dd }, { "DIG2_DIG_BE_CNTL", 2, 0x2304 },
    { "DIG2_DIG_BE_CLK_CNTL", 2, 0x2303 }, { "DIG2_DIG_BE_EN_CNTL", 2, 0x2305 }, { "DIG3_DIG_FE_CNTL", 2, 0x23ff }, { "DIG3_DIG_FE_CLK_CNTL", 2, 0x2400 },
    { "DIG3_DIG_FE_EN_CNTL", 2, 0x2401 }, { "DIG3_DIG_BE_CNTL", 2, 0x2428 }, { "DIG3_DIG_BE_CLK_CNTL", 2, 0x2427 }, { "DIG3_DIG_BE_EN_CNTL", 2, 0x2429 },
    { "DIG0_STREAM_MAPPER_CONTROL", 2, 0x1f0d }, { "DIG1_STREAM_MAPPER_CONTROL", 2, 0x1f0e }, { "DIG2_STREAM_MAPPER_CONTROL", 2, 0x1f0f }, { "DIG3_STREAM_MAPPER_CONTROL", 2, 0x1f10 },
    { "DP0_DP_LINK_CNTL", 2, 0x211e }, { "DP0_DP_VID_STREAM_CNTL", 2, 0x2122 }, { "DP1_DP_LINK_CNTL", 2, 0x2242 }, { "DP1_DP_VID_STREAM_CNTL", 2, 0x2246 },
    { "DP2_DP_LINK_CNTL", 2, 0x2366 }, { "DP2_DP_VID_STREAM_CNTL", 2, 0x236a }, { "DP3_DP_LINK_CNTL", 2, 0x248a }, { "DP3_DP_VID_STREAM_CNTL", 2, 0x248e },
    { "UNIPHYA_LINK_CNTL", 2, 0x286d }, { "UNIPHYB_LINK_CNTL", 2, 0x286f }, { "UNIPHYC_LINK_CNTL", 2, 0x2871 }, { "UNIPHYD_LINK_CNTL", 2, 0x2873 },
    { "SYMCLKA_CLOCK_ENABLE", 1, 0x00a0 }, { "SYMCLKB_CLOCK_ENABLE", 1, 0x00a1 }, { "SYMCLKC_CLOCK_ENABLE", 1, 0x00a2 }, { "SYMCLKD_CLOCK_ENABLE", 1, 0x00a3 },
    { "DC_GPIO_HPD_A", 2, 0x28f5 }, { "HPD1_DC_HPD_INT_STATUS", 2, 0x1762 }, { "HPD2_DC_HPD_INT_STATUS", 2, 0x176a }, { "HPD3_DC_HPD_INT_STATUS", 2, 0x1772 },
    { "RDPCSTX0_RDPCSTX_CNTL", 2, 0x2930 }, { "RDPCSTX0_RDPCSTX_PHY_CNTL0", 2, 0x2940 }, { "RDPCSTX1_RDPCSTX_CNTL", 2, 0x2a08 }, { "RDPCSTX1_RDPCSTX_PHY_CNTL0", 2, 0x2a18 },
    { "RDPCSTX2_RDPCSTX_CNTL", 2, 0x2ae0 }, { "RDPCSTX2_RDPCSTX_PHY_CNTL0", 2, 0x2af0 }, { "RDPCSTX3_RDPCSTX_CNTL", 2, 0x2bb8 }, { "RDPCSTX3_RDPCSTX_PHY_CNTL0", 2, 0x2bc8 },
    { "DMCUB_CNTL", 2, 0x01f6 }, { "DMCUB_SEC_CNTL", 2, 0x01ce }, { "DMCUB_INTERRUPT_STATUS", 2, 0x01c7 }, { "DMCUB_TIMER_CURRENT", 2, 0x01fd },
    { "DMCUB_SCRATCH0", 2, 0x01e3 }, { "DMCUB_SCRATCH1", 2, 0x01e4 }, { "DMCUB_SCRATCH2", 2, 0x01e5 }, { "DMCUB_SCRATCH3", 2, 0x01e6 },
    { "DMCUB_SCRATCH4", 2, 0x01e7 }, { "DMCUB_SCRATCH5", 2, 0x01e8 }, { "DMCUB_SCRATCH6", 2, 0x01e9 }, { "DMCUB_SCRATCH7", 2, 0x01ea },
    { "DMCUB_SCRATCH8", 2, 0x01eb }, { "DMCUB_SCRATCH9", 2, 0x01ec }, { "DMCUB_SCRATCH10", 2, 0x01ed }, { "DMCUB_SCRATCH11", 2, 0x01ee },
    { "DMCUB_SCRATCH12", 2, 0x01ef }, { "DMCUB_SCRATCH13", 2, 0x01f0 }, { "DMCUB_SCRATCH14", 2, 0x01f1 }, { "DMCUB_SCRATCH15", 2, 0x01f2 },
    { "DMCUB_INBOX1_BASE_ADDRESS", 2, 0x01d4 }, { "DMCUB_INBOX1_SIZE", 2, 0x01d5 }, { "DMCUB_INBOX1_WPTR", 2, 0x01d6 }, { "DMCUB_INBOX1_RPTR", 2, 0x01d7 },
    { "DMCUB_OUTBOX1_BASE_ADDRESS", 2, 0x01dc }, { "DMCUB_OUTBOX1_SIZE", 2, 0x01dd }, { "DMCUB_OUTBOX1_WPTR", 2, 0x01de }, { "DMCUB_OUTBOX1_RPTR", 2, 0x01df },
    { "DMCUB_REGION4_OFFSET", 2, 0x0196 }, { "DMCUB_REGION4_OFFSET_HIGH", 2, 0x0197 }, { "DMCUB_REGION4_TOP_ADDRESS", 2, 0x01a1 }, { "DMCUB_REGION3_CW7_OFFSET", 2, 0x01c3 },
};

// Liveness: the four OTG frame counters (OTG_FRAME_COUNT [23:0]). The kext reads them twice, 50 ms apart: an OTG that is running advances
// (about 3 to 9 frames in 50 ms at 60 to 180 Hz); a dark one does not. Same rules as the table above.
#define N48GOP_LIVE_COUNT 4u
static const struct n48gop_reg n48gop_live[N48GOP_LIVE_COUNT] = {
    { "OTG0_OTG_STATUS_FRAME_COUNT", 2, 0x1b4d }, { "OTG1_OTG_STATUS_FRAME_COUNT", 2, 0x1bcd },
    { "OTG2_OTG_STATUS_FRAME_COUNT", 2, 0x1c4d }, { "OTG3_OTG_STATUS_FRAME_COUNT", 2, 0x1ccd },
};

// The count of registers the table must hold (the host test checks both the count and each row).
static inline uint32_t n48gop_count(void) { return N48GOP_COUNT; }

#endif /* N48_GOPSNAP_H */
