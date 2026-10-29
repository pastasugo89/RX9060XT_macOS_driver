#include "native_vcn_firmware_pure.h"
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
using namespace n48vcn;
static void put32(std::vector<uint8_t>& b, size_t at, uint32_t n) {
    for (unsigned i=0;i<4;i++) b[at+i]=(uint8_t)(n>>(i*8));
}
int main(int argc, char **argv) {
    std::vector<uint8_t> b(8192);
    put32(b,0,8192); put32(b,4,32); b[8]=1; b[12]=5; put32(b,16,0x0910c01a);
    put32(b,20,4096); put32(b,24,32);
    auto p=firmware_plan(b.data(),b.size());
    assert(p.valid && p.payloadOffset==32 && p.payloadSize==4096 && p.pspBytes==4096 && p.cacheBytes==8192);
    assert(!firmware_plan(nullptr,0).valid && !firmware_plan(b.data(),31).valid);
    auto original=b;
    put32(b,20,0); assert(!firmware_plan(b.data(),b.size()).valid); b=original;
    put32(b,24,31); assert(!firmware_plan(b.data(),b.size()).valid); b=original;
    put32(b,24,0xfffffff0u); put32(b,20,0x100u); assert(!firmware_plan(b.data(),b.size()).valid); b=original;
    put32(b,0,8193); assert(!firmware_plan(b.data(),b.size()).valid); b=original;
    b[8]=2; assert(!firmware_plan(b.data(),b.size()).valid); b=original;
    b[12]=4; assert(!firmware_plan(b.data(),b.size()).valid); b=original;
    put32(b,20,4095); p=firmware_plan(b.data(),b.size()); assert(p.valid && p.pspBytes==4096 && p.cacheBytes==8192);
    put32(b,20,4088); p=firmware_plan(b.data(),b.size()); assert(p.valid && p.cacheBytes==4096);
    puts("VCN firmware header and sizing: PASS; synthetic only, no PSP or MMIO");
    if (argc > 1) {
        std::ifstream file(argv[1], std::ios::binary);
        if (!file) return 2;
        std::vector<uint8_t> real((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        p=firmware_plan(real.data(),real.size());
        if (!p.valid) { puts("Real firmware header rejected"); return 3; }
        printf("Real firmware: version=%#x, payload=%u at %u, PSP=%llu, cache=%llu; no signature or hardware validation\n",
               p.version,p.payloadSize,p.payloadOffset,(unsigned long long)p.pspBytes,(unsigned long long)p.cacheBytes);
    }
}
