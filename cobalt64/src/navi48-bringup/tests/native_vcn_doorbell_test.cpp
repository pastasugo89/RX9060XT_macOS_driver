#include "native_vcn_doorbell_pure.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
using namespace n48vcn;
int main() {
    // Compare every valid base against an independently assembled reference,
    // with varied reserved fields. Neither implementation touches hardware.
    for (uint32_t i=0; i<=1023; ++i) for (uint32_t seed : {0u, 0xffffffffu, 0x0e000040u, 0x580aaaaau}) {
        const auto p = doorbell0(seed, true, i);
        if (i > 1016) { assert(!p.valid && p.value == seed); continue; }
        const uint32_t reference = (seed & 0x0e000040u) | 0x40100009u | (i << 7);
        assert(p.valid && p.value == reference);
        assert((p.value & ~kTouched) == (seed & ~kTouched));
        const auto off = doorbell0(seed, false, i);
        assert(off.valid && off.value == (seed & ~kSize));
    }
    assert(kEntryBaseIndex == 2u && kEntryOffset == 0x01cfu);
    puts("VCN doorbell planning: PASS; no MMIO or video decoding");
}
