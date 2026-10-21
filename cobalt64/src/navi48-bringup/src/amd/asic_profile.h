//
//  asic_profile.h — compile-time ASIC profile (RX 9060 XT port).
//
//  The kext is built for ONE profile, chosen by the Makefile (ASIC=navi44, the
//  default, or ASIC=navi48), which passes -DN4X_ASIC_NAVI48 for Navi 48. The
//  profile fixes what cannot come from the hardware at run time:
//    - the embedded firmware set (the PSP verifies signatures: the Navi 48 and
//      Navi 44 blobs are NOT interchangeable, see research/reports/01 §3.3);
//    - the PCI device ids the kext accepts (probe() refuses any other card);
//    - fallback GFX geometry, used only if the discovery GC table is unreadable
//      (normally the topology comes from gc_info, as in Linux).
//  IP versions and register bases always come from on-die IP discovery.
//
#pragma once

#if defined(N4X_ASIC_NAVI48)
// ---- Navi 48: RX 9070 / 9070 XT (0x7550), Radeon AI PRO R9700 (0x7551) ----
#define N4X_ASIC_NAME            "Navi 48"
#define N4X_ASIC_DEV0            0x7550
#define N4X_ASIC_DEV1            0x7551
#define N4X_ASIC_MARKETING(dev)  ((dev) == 0x7550 ? "RX 9070/XT" : "R9700")
#define N4X_ASIC_GC_MINOR_REV    1     // GC 12.0.1, gfx1201
#define N4X_ASIC_MAX_SE          4
#define N4X_ASIC_MAX_SA_PER_SE   2
#define N4X_ASIC_MAX_RB_PER_SE   4
#define N4X_ASIC_MAX_CU_PER_SA   8
// firmware symbol / name stems (tools/embed-firmware.py: fw_<stem>[])
#define N4X_FW_SYM(stem)         N4X_FW_SYM_48_##stem
#define N4X_FW_SYM_48_PSP_SOS    fw_psp_14_0_3_sos
#define N4X_FW_SYM_48_PSP_TA     fw_psp_14_0_3_ta
#define N4X_FW_SYM_48_GC_IMU     fw_gc_12_0_1_imu
#define N4X_FW_SYM_48_GC_PFP     fw_gc_12_0_1_pfp
#define N4X_FW_SYM_48_GC_ME      fw_gc_12_0_1_me
#define N4X_FW_SYM_48_GC_MEC     fw_gc_12_0_1_mec
#define N4X_FW_SYM_48_GC_UNI_MES fw_gc_12_0_1_uni_mes
#define N4X_FW_SYM_48_GC_RLC     fw_gc_12_0_1_rlc
#define N4X_FW_SYM_48_SMU        fw_smu_14_0_3
#define N4X_FW_SYM_48_SDMA       fw_sdma_7_0_1
#define N4X_FW_PSP               "psp_14_0_3"
#define N4X_FW_GC                "gc_12_0_1"
#define N4X_FW_SMU               "smu_14_0_3"
#define N4X_FW_SDMA              "sdma_7_0_1"
// ---- display connector map (DCN 4.1.0): the link encoder / DIG / DDC line / HPD of each connector. Cobalt64's Navi 48 values.
// Used by nothing yet: navi48_disp2.h, navi48_dmubcmd.h and the guards still hard-code Navi 48. Switch them to these only
// after the GOP observation (research/display/gop_vm_readout_plan.md). DDC/AUX line index = the "line" (ddcN in Cobalt64).
#define N4X_DISP_DP_DIG          1     // DP: DIG1 / UNIPHY_B (PHY B) / DP_AUX1 / HPD2
#define N4X_DISP_DP_PHY          1
#define N4X_DISP_DP_LINE         1
#define N4X_DISP_DP_HPD          2
#define N4X_DISP_HDMI1_DIG       2     // monitor A: DIG2 / UNIPHY_C / ddc2 / HPD3
#define N4X_DISP_HDMI1_PHY       2
#define N4X_DISP_HDMI1_LINE      2
#define N4X_DISP_HDMI1_HPD       3
#define N4X_DISP_HDMI2_DIG       3     // monitor B: DIG3 / UNIPHY_D / ddc3 / HPD4
#define N4X_DISP_HDMI2_PHY       3
#define N4X_DISP_HDMI2_LINE      3
#define N4X_DISP_HDMI2_HPD       4
#define N4X_DISP_HAS_PHY_D       1
// Multi-display features (M6 / M6 flip / disp2 / dmubcmd / mode trial) are Navi 48 only for now: they address PHY D, DIG3 or the
// Navi 48 same-mode golden. Navi 44 refuses them cleanly (dcn/navi48_disp_profile.h).
#define N4X_DISP_M6_SUPPORTED    1
#define N4X_DISP_MODETRIAL_SUPPORTED 1
// Endpoint fallback (apple/display_pipe_guard.h, apple/DisplayPipeGuard.cpp): used only when neither route A nor the live
// Console size is available. 0.0.513's documented 1920x1080 with CEA-861 1080p60 blanking, unchanged.
#define N4X_AGDC_FB_W            1920u
#define N4X_AGDC_FB_H            1080u
#define N4X_AGDC_FB_HBLANK       280u
#define N4X_AGDC_FB_HSYNC_OFF    88u
#define N4X_AGDC_FB_HSYNC_W      44u
#define N4X_AGDC_FB_VBLANK       45u
#define N4X_AGDC_FB_VSYNC_OFF    4u
#define N4X_AGDC_FB_VSYNC_W      5u
#define N4X_AGDC_FB_REFRESH_HZ   60u
#else
// ---- Navi 44 (default): RX 9060 XT / RX 9060 / RX 9050 (0x7590) ----
#define N4X_ASIC_NAVI44          1
#define N4X_ASIC_NAME            "Navi 44"
#define N4X_ASIC_DEV0            0x7590
#define N4X_ASIC_DEV1            0x7590
#define N4X_ASIC_MARKETING(dev)  ((void)(dev), "RX 9060 XT/9060/9050")
#define N4X_ASIC_GC_MINOR_REV    0     // GC 12.0.0, gfx1200
#define N4X_ASIC_MAX_SE          2
#define N4X_ASIC_MAX_SA_PER_SE   2
#define N4X_ASIC_MAX_RB_PER_SE   4
#define N4X_ASIC_MAX_CU_PER_SA   8
#define N4X_FW_SYM(stem)         N4X_FW_SYM_44_##stem
#define N4X_FW_SYM_44_PSP_SOS    fw_psp_14_0_2_sos
#define N4X_FW_SYM_44_PSP_TA     fw_psp_14_0_2_ta
#define N4X_FW_SYM_44_GC_IMU     fw_gc_12_0_0_imu
#define N4X_FW_SYM_44_GC_PFP     fw_gc_12_0_0_pfp
#define N4X_FW_SYM_44_GC_ME      fw_gc_12_0_0_me
#define N4X_FW_SYM_44_GC_MEC     fw_gc_12_0_0_mec
#define N4X_FW_SYM_44_GC_UNI_MES fw_gc_12_0_0_uni_mes
#define N4X_FW_SYM_44_GC_RLC     fw_gc_12_0_0_rlc
#define N4X_FW_SYM_44_SMU        fw_smu_14_0_2
#define N4X_FW_SYM_44_SDMA       fw_sdma_7_0_0
#define N4X_FW_PSP               "psp_14_0_2"
#define N4X_FW_GC                "gc_12_0_0"
#define N4X_FW_SMU               "smu_14_0_2"
#define N4X_FW_SDMA              "sdma_7_0_0"
// ---- display connector map (DCN 4.1.0), from the VBIOS displayobjectinfo of 113-P816G493-S05 (research/display/README.md §1).
// Not yet used by the display code (see the Navi 48 block above). HAS_PHY_D 0: no UNIPHY_D on this board.
#define N4X_DISP_DP_DIG          0     // DP: DIGA / UNIPHY_A (PHY A) / DDC1 - AUX0 (line 0) / HPD1
#define N4X_DISP_DP_PHY          0
#define N4X_DISP_DP_LINE         0
#define N4X_DISP_DP_HPD          1
#define N4X_DISP_HDMI1_DIG       1     // HDMI-A-1: DIGB / UNIPHY_B (PHY B) / DDC2 (line 1) / HPD2
#define N4X_DISP_HDMI1_PHY       1
#define N4X_DISP_HDMI1_LINE      1
#define N4X_DISP_HDMI1_HPD       2
#define N4X_DISP_HDMI2_DIG       2     // HDMI-A-2: DIGC / UNIPHY_C (PHY C) / DDC3 (line 2) / HPD3
#define N4X_DISP_HDMI2_PHY       2
#define N4X_DISP_HDMI2_LINE      2
#define N4X_DISP_HDMI2_HPD       3
#define N4X_DISP_HAS_PHY_D       0
#define N4X_DISP_M6_SUPPORTED    0     // Navi 44: no PHY D / DIG3 monitor B, multi-display refused
#define N4X_DISP_MODETRIAL_SUPPORTED 0   // Navi 44: no same-mode golden yet (the GOP dump covers only part of it)
// Endpoint fallback (apple/display_pipe_guard.h, apple/DisplayPipeGuard.cpp): the board's native panel mode 2560x1440, from the
// SINK-A 2560x1440@120 CTA DTD row of src/dcn41/dcn41_modes_navi44.h (totals 2720x1525, front 48/3, sync 32/10, 119.998 Hz,
// 497.75 MHz). Used only when neither route A nor the live Console size is available.
#define N4X_AGDC_FB_W            2560u
#define N4X_AGDC_FB_H            1440u
#define N4X_AGDC_FB_HBLANK       160u     // 2720 - 2560
#define N4X_AGDC_FB_HSYNC_OFF    48u      // h_front
#define N4X_AGDC_FB_HSYNC_W      32u
#define N4X_AGDC_FB_VBLANK       85u      // 1525 - 1440
#define N4X_AGDC_FB_VSYNC_OFF    3u       // v_front
#define N4X_AGDC_FB_VSYNC_W      10u
#define N4X_AGDC_FB_REFRESH_HZ   120u     // nominal; the derived clock 2720 * 1525 * 120 = 497.76 MHz is the row's 497.75 MHz
#endif

// Symbol size companion: fw_<stem>_size
#define N4X_FW_CAT_(a, b)        a##b
#define N4X_FW_CAT(a, b)         N4X_FW_CAT_(a, b)
#define N4X_FW_SIZE(stem)        N4X_FW_CAT(N4X_FW_SYM(stem), _size)
