#include <cstdio>
#include <cstdint>
#include "gfxhub_fault_pure.h"

int main() {
    using amdgpu::cp_debug_allow_utcl1_fault_recovery;
    using amdgpu::kCpDebugUtcl1ErrorHaltDisable;
    unsigned checks = 0;
    unsigned failures = 0;
    auto expect = [&](bool ok, const char *name) {
        ++checks;
        if (!ok) { ++failures; std::fprintf(stderr, "FAIL %s\n", name); }
    };

    constexpr uint32_t samples[] = {0u, 0x40000000u, 0x80007fffu, 0xffffffffu};
    for (uint32_t before : samples) {
        const uint32_t after = cp_debug_allow_utcl1_fault_recovery(before);
        expect((after & kCpDebugUtcl1ErrorHaltDisable) != 0,
               "CP_DEBUG halt-disable bit set");
        expect((after & ~kCpDebugUtcl1ErrorHaltDisable) ==
                   (before & ~kCpDebugUtcl1ErrorHaltDisable),
               "CP_DEBUG unrelated bits preserved");
        expect(cp_debug_allow_utcl1_fault_recovery(after) == after,
               "CP_DEBUG RMW idempotent");
    }
    std::printf("gfxhub_fault_test: %u checks, %u failed\n", checks, failures);
    return failures ? 1 : 0;
}
