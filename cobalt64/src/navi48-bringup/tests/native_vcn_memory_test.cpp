#include "native_vcn_memory_pure.h"
#include <cassert>
#include <cstdio>
using namespace n48vcn;
int main() {
    auto p=psp_memory(0x100000000ull,4096);
    assert(p.valid && p.stack==0x100000000ull && p.context==p.stack+128*1024 &&
           p.shared==p.context+512*1024 && p.totalBytes==128*1024+512*1024+4096);
    assert(!psp_memory(1,4096).valid && !psp_memory(0,0).valid && !psp_memory(0,4095).valid);
    assert(!psp_memory(UINT64_MAX-4095,4096).valid);
    assert(!psp_memory(0,UINT64_MAX-4095).valid);
    for (uint64_t n=4096;n<=1024*1024;n+=4096) {
        p=psp_memory(0x100000,n);
        assert(p.valid && p.shared + n == p.stack + p.totalBytes);
    }
    puts("VCN PSP memory layout: PASS; no allocation, PSP or MMIO");
}
