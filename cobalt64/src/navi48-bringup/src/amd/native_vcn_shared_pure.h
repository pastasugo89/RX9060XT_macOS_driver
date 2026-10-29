// VCN 5 shared control-block initial bytes for a discrete GPU. No hardware IO.
// Layout follows amdgpu_vcn5_fw_shared and vcn_v5_0_0_sw_init in Linux AMDGPU.
// AMD copyright and permission notice: VCN-AMD-LICENSE.txt in this directory.
#pragma once
#include <stddef.h>
#include <stdint.h>
namespace n48vcn {
struct Vcn5Shared {
    uint32_t present; uint8_t reserved0[12];
    uint8_t queueEnabled, queueMode, queueStatus, reserved1[5];
    uint8_t reserved2[8];
    uint8_t logEnabled, reserved3[3]; uint32_t logLo, logHi, logSize;
    uint8_t reserved4[20];
    uint32_t ringEnabled, ringInfo[12];
    uint8_t smuType, reserved5[3];
    uint8_t drmMethod, reserved6[3];
    uint8_t reserved7[404];
};
static_assert(sizeof(Vcn5Shared)==532 && offsetof(Vcn5Shared,queueEnabled)==16 &&
              offsetof(Vcn5Shared,logEnabled)==32 && offsetof(Vcn5Shared,ringEnabled)==68 &&
              offsetof(Vcn5Shared,smuType)==120, "VCN 5 shared ABI layout");
constexpr uint32_t kUnifiedQueueFlag=1u<<2, kSmuInterfaceFlag=1u<<11;
// Only for an empty, CPU-owned control block before any firmware access.
inline void init_discrete(Vcn5Shared &s) {
    s = Vcn5Shared{};
    s.present = kUnifiedQueueFlag | kSmuInterfaceFlag;
    s.queueEnabled = 1;
    s.smuType = 0; // upstream AMDGPU_VCN_SMU_DPM_INTERFACE_DGPU
}
}
