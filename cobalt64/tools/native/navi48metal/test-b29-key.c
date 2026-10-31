// bundle 29: the user-cache directory K (n48x_key, n48_xlate.h) changes with the translator's LC_UUID, and with nothing else that a rebuild of the same
// source would keep. Build/run: cc -O1 -Wall -Wextra -Werror -I. -o bin/test-b29-key test-b29-key.c && bin/test-b29-key
#include <stdio.h>
#include <string.h>
#include <CommonCrypto/CommonDigest.h>
#include "n48_xlate.h"
static int fails = 0;
static void key(char out[17], uint8_t ldr, const char *os) {
    uint8_t xl[16], rd[16], ov[32];
    memset(xl, 0, 16); xl[0] = ldr; memset(rd, 7, 16); n48x_override_hash(ov);
    n48x_key(out, xl, rd, ov, os);
}
int main(void) {
    char a[17], b[17], c[17], d[17];
    key(a, 1, "25G83"); key(b, 2, "25G83"); key(c, 1, "25G83"); key(d, 1, "25G84");
    printf("K(uuid 1) = %s, K(uuid 2) = %s, K(uuid 1 again) = %s, K(other OS build) = %s\n", a, b, c, d);
    if (strcmp(a, b) == 0) { fails++; printf("FAIL: a different translator LC_UUID keeps the same K\n"); }
    if (strcmp(a, c) != 0) { fails++; printf("FAIL: K is not deterministic\n"); }
    if (strcmp(a, d) == 0) { fails++; printf("FAIL: a different OS build keeps the same K\n"); }
    printf("test-b29-key: %s\n", fails ? "FAILED" : "PASS");
    return fails ? 1 : 0;
}
