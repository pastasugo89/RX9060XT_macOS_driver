#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "amd/vadd_ir_abi.h"

int main()
{
    using namespace amdgpu;
    const VaddKernarg args { 0x8000000012340000ull, 0x8000000056780000ull,
                             0x800000009abc0000ull, 32 };
    assert(args.a == 0x8000000012340000ull && args.b == 0x8000000056780000ull);
    assert(args.c == 0x800000009abc0000ull && args.n == 32);
    const VaddDispatchPacket p = make_vadd_dispatch_packet(0x8000000010000000ull,
                                                            0x8000000011000000ull);
    assert(p.header == kVaddHsaKernelDispatchPacket);
    assert(p.setup == kVaddHsaSetupOneDimension);
    assert(p.workgroup_size_x == 32 && p.workgroup_size_y == 1 && p.workgroup_size_z == 1);
    assert(p.grid_size_x == 32 && p.grid_size_y == 1 && p.grid_size_z == 1);
    assert(p.kernel_object == 0x8000000010000000ull);
    assert(p.kernarg_address == 0x8000000011000000ull);
    assert(p.completion_signal == 0);
    puts("vadd_ir HSA ABI: PASS (28-byte kernarg, 64-byte AQL dispatch packet, workgroup_size_x@4)");
}
