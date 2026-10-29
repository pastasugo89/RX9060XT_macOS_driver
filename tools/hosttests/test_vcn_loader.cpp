// Host-only test of registration into the actual loader. No PSP or GPU calls.
#include "fw_loader.h"
#include "native_vcn_firmware_pure.h"
#include "../fw/fw_table.h"
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
namespace amdgpu {
void n48_logf(const char *, ...) {}
const FwBlob *fw_get(FwId) { return nullptr; }
kern_return_t psp_fw_buf_stage(DeviceContext &, PSPContext &, const void *, uint32_t, uint64_t *) {
    assert(false && "registration must not stage or touch hardware"); return kIOReturnError;
}
}
int main(int argc, char **argv) {
    if (argc!=2) return 2;
    std::ifstream f(argv[1],std::ios::binary); if (!f) return 2;
    std::vector<uint8_t> b((std::istreambuf_iterator<char>(f)),std::istreambuf_iterator<char>());
    auto plan=n48vcn::firmware_plan(b.data(),b.size()); assert(plan.valid);
    amdgpu::FwLoaderState st;
    assert(amdgpu::fw_loader_add_vcn(st,b.data(),b.size())==kIOReturnBadArgument);
    amdgpu::DeviceContext dev{}; amdgpu::PSPContext psp{};
    st.dev=&dev; st.psp=&psp;
    assert(amdgpu::fw_loader_add_vcn(st,b.data(),b.size())==kIOReturnSuccess);
    assert(st.count==1 && st.entries[0].fw_type==13 && st.entries[0].src==b.data()+plan.payloadOffset &&
           st.entries[0].size==plan.payloadSize && !st.entries[0].staged && st.entries[0].mc==0);
    assert(amdgpu::fw_loader_add_vcn(st,b.data(),b.size())==kIOReturnExclusiveAccess && st.count==1);
    amdgpu::FwLoaderState full; full.dev=&dev;full.psp=&psp;full.count=full.kMaxEntries;
    assert(amdgpu::fw_loader_add_vcn(full,b.data(),b.size())==kIOReturnNoResources);
    b[12]=4;
    amdgpu::FwLoaderState wrong;wrong.dev=&dev;wrong.psp=&psp;
    assert(amdgpu::fw_loader_add_vcn(wrong,b.data(),b.size())==kIOReturnBadArgument && wrong.count==0);
    puts("VCN loader registration: PASS, no GPU or PSP calls");
}
