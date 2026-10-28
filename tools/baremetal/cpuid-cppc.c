/* Read-only userspace CPUID inventory. No MSR, SMN or PCI access. */
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    unsigned a, b, c, d;
    char vendor[13] = {0};
    __cpuid(0, a, b, c, d);
    memcpy(vendor, &b, 4); memcpy(vendor + 4, &d, 4); memcpy(vendor + 8, &c, 4);
    __cpuid(1, a, b, c, d);
    const unsigned baseFamily = (a >> 8) & 15, baseModel = (a >> 4) & 15;
    const unsigned family = baseFamily == 15 ? baseFamily + ((a >> 20) & 255) : baseFamily;
    const unsigned model = (baseFamily == 6 || baseFamily == 15) ? baseModel + (((a >> 16) & 15) << 4) : baseModel;
    printf("vendor=%s family=0x%x model=0x%x stepping=%u hypervisor=%u\n",
           vendor, family, model, a & 15, (c >> 31) & 1);
    unsigned max = __get_cpuid_max(0x80000000, NULL);
    if (max < 0x80000008 || strcmp(vendor, "AuthenticAMD")) return 1;
    char brand[49] = {0};
    for (unsigned i = 0; i < 3; i++) {
        __cpuid_count(0x80000002 + i, 0, a, b, c, d);
        const uint32_t words[] = { a, b, c, d };
        memcpy(brand + i * 16, words, 16);
    }
    printf("brand=\"%s\"\n", brand);
    __cpuid_count(0x80000008, 0, a, b, c, d);
    printf("CPUID.80000008.EBX=0x%08x cppc_msr=%u\n", b, (b >> 27) & 1);
    __cpuid_count(0x80000007, 0, a, b, c, d);
    printf("CPUID.80000007.EDX=0x%08x invariant_tsc=%u core_performance_boost=%u\n",
           d, (d >> 8) & 1, (d >> 9) & 1);
    return 0;
}
