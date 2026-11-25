// cc -std=c11 -Wall -Wextra -Werror test-copy-region.c -o /tmp/test-copy-region && /tmp/test-copy-region
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "n48_copy_region.h"
int main(void) {
    // Mip and layer numbers are already translated through each view's base.
    assert(n48cr_overlap(2, 3, 0, 0, 0, 2, 3, 3, 3, 0, 4, 4, 1));
    assert(!n48cr_overlap(2, 3, 0, 0, 0, 1, 3, 0, 0, 0, 4, 4, 1));
    assert(!n48cr_overlap(2, 3, 0, 0, 0, 2, 4, 0, 0, 0, 4, 4, 1));
    assert(!n48cr_overlap(2, 3, 0, 0, 0, 2, 3, 4, 0, 0, 4, 4, 1));
    assert(!n48cr_overlap(2, 3, 0, 0, 0, 2, 3, 0, 4, 0, 4, 4, 1));
    assert(n48cr_overlap(0, 0, 0, 0, 2, 0, 0, 0, 0, 3, 4, 4, 2));
    assert(!n48cr_overlap(0, 0, 0, 0, 2, 0, 0, 0, 0, 4, 4, 4, 2));
    assert(n48cr_axis_overlap(UINT64_MAX, UINT64_MAX - 1, 2));
    assert(!n48cr_axis_overlap(UINT64_MAX, 0, 2));
    puts("shared image copy overlap: passed");
    return 0;
}
