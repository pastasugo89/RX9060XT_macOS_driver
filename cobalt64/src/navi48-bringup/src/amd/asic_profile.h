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
#endif

// Symbol size companion: fw_<stem>_size
#define N4X_FW_CAT_(a, b)        a##b
#define N4X_FW_CAT(a, b)         N4X_FW_CAT_(a, b)
#define N4X_FW_SIZE(stem)        N4X_FW_CAT(N4X_FW_SYM(stem), _size)
