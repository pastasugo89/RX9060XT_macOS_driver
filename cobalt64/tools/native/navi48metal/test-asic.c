// test-asic.c - host test of n48_asic.h (the board profile of the Metal bundle). Run for both boards:
//   cc -std=c11 -Wall -Wextra -Werror -I. test-asic.c -o /tmp/test-asic && /tmp/test-asic
//   cc -std=c11 -Wall -Wextra -Werror -DN4X_ASIC_NAVI48 -I. test-asic.c -o /tmp/test-asic48 && /tmp/test-asic48
#include <stdio.h>
#include <string.h>
#include "n48_asic.h"
int main(void) {
    int ok = 1;
#ifdef N4X_ASIC_NAVI48
    ok &= !strcmp(N48M_PRODUCT_NAME, "RX 9070 XT") && N48M_PCI_DEVICE == 0x7550u && n48m_radv_matches(0x1002, 0x7550) && !n48m_radv_matches(0x1002, 0x7590);
#else
    ok &= !strcmp(N48M_PRODUCT_NAME, "RX 9060 XT") && N48M_PCI_DEVICE == 0x7590u && !strcmp(N48M_GFX_NAME, "gfx1200") && n48m_radv_matches(0x1002, 0x7590) && !n48m_radv_matches(0x1002, 0x7550) && !n48m_radv_matches(0x10de, 0x7590);
#endif
    printf("%s: %s\n", N48M_PRODUCT_NAME, ok ? "PASS" : "FAIL"); return !ok;
}
