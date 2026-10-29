#include "native_vcn_shared_pure.h"
#include "native_vcn_memory_pure.h"
#include <cassert>
#include <cstdio>
#include <cstring>
using namespace n48vcn;
int main() {
    Vcn5Shared block;
    std::memset(&block,0xff,sizeof(block));
    init_discrete(block);
    auto *b=reinterpret_cast<const unsigned char*>(&block);
    for (size_t i=0;i<sizeof(block);i++) {
        const unsigned char expected = i==0 ? 0x04 : i==1 ? 0x08 : i==16 ? 0x01 : 0x00;
        assert(b[i]==expected);
    }
    constexpr uint64_t pageAligned=(sizeof(Vcn5Shared)+4095u)&~4095u;
    static_assert(pageAligned==4096);
    auto plan=psp_memory(0x100000,pageAligned);
    assert(plan.valid && plan.totalBytes==128*1024+512*1024+4096);
    puts("VCN 5 shared ABI and initialization: PASS; offline only");
}
