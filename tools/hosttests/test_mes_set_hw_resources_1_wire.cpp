#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "amd/mes_api_wire.h"

#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "The MES wire test requires the little-endian target ABI"
#endif

static int check_word(const uint32_t *dwords, unsigned index, uint32_t want,
                      const char *field)
{
    if (dwords[index] == want) return 0;
    fprintf(stderr, "%s: dw%u got %#010x, expected %#010x\n",
            field, index, dwords[index], want);
    return 1;
}

int main(void)
{
    MES_SetHwResources1_Wire packet;
    memset(&packet, 0, sizeof(packet));
    packet.header = 0x00040131;
    packet.api_status.fence_addr = 0x1122334455667788ULL;
    packet.api_status.fence_value = 0x99aabbccddeeff00ULL;
    packet.timestamp = 0x0123456789abcdefULL;
    packet.flags = 0x2468ace0;
    packet.mes_debug_ctx_mc_addr = 0x0fedcba987654321ULL;
    packet.mes_debug_ctx_size = 0x13579bdf;
    packet.mes_kiq_unmap_timeout = 0x0a; // Navi44 GC12.0: mes_v12_0.c
    packet.coop_sch_shared_mc_addr = 0x1020304050607080ULL;
    packet.cleaner_shader_fence_mc_addr = 0x8877665544332211ULL;

    const uint32_t *dw = reinterpret_cast<const uint32_t *>(&packet);
    int failed = 0;
    failed |= check_word(dw, 0, 0x00040131, "header");
    failed |= check_word(dw, 2, 0x55667788, "api_status.fence_addr low");
    failed |= check_word(dw, 3, 0x11223344, "api_status.fence_addr high");
    failed |= check_word(dw, 4, 0xddeeff00, "api_status.fence_value low");
    failed |= check_word(dw, 5, 0x99aabbcc, "api_status.fence_value high");
    failed |= check_word(dw, 6, 0x89abcdef, "timestamp low");
    failed |= check_word(dw, 7, 0x01234567, "timestamp high");
    failed |= check_word(dw, 8, 0x2468ace0, "flags");
    failed |= check_word(dw, 10, 0x87654321, "debug address low");
    failed |= check_word(dw, 11, 0x0fedcba9, "debug address high");
    failed |= check_word(dw, 12, 0x13579bdf, "debug size");
    failed |= check_word(dw, 13, 0x0a, "Navi44 K.I.Q. unmap timeout");
    failed |= check_word(dw, 14, 0x50607080, "coop address low");
    failed |= check_word(dw, 15, 0x10203040, "coop address high");
    failed |= check_word(dw, 16, 0x44332211, "cleaner fence low");
    failed |= check_word(dw, 17, 0x88776655, "cleaner fence high");
    failed |= check_word(dw, 18, 0, "reserved tail");

    if (!failed) puts("MES SET_HW_RESOURCES_1 wire layout: PASS (64 dwords)");
    return failed ? 1 : 0;
}
