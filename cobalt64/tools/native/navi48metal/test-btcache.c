#include "n48_btcache.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    n48bt_cache cache = {0}; int hit = 77; unsigned checks = 0;
    assert(!n48bt_lookup(&cache, 0, &hit)); checks++;
    n48bt_put(&cache, 0, 1, 1);
    assert(!n48bt_lookup(&cache, 0, &hit)); checks++;
    for (uintptr_t pc = 0x1000; pc < 0x9000; pc += 16) {
        n48bt_put(&cache, pc, 0, 1);
        assert(!n48bt_lookup(&cache, pc, &hit)); checks++;
        n48bt_put(&cache, pc, 1, (int)(pc & 16));
        assert(n48bt_lookup(&cache, pc, &hit) && hit == !!(pc & 16)); checks++;
    }
    // Replacement must check the full address, never reuse a colliding verdict.
    uintptr_t first = 0x100000, second = first + 16;
    while (n48bt_index(first) != n48bt_index(second)) second += 16;
    n48bt_put(&cache, first, 1, 1); n48bt_put(&cache, second, 1, 0);
    assert(!n48bt_lookup(&cache, first, &hit)); checks++;
    assert(n48bt_lookup(&cache, second, &hit) && !hit); checks++;
    // An offscreen caller's negative PC does not suppress another display caller.
    n48bt_put(&cache, first, 1, 0);
    uintptr_t display = first + 16;
    while (n48bt_index(display) == n48bt_index(first)) display += 16;
    n48bt_put(&cache, display, 1, 1);
    assert(n48bt_lookup(&cache, first, &hit) && !hit); checks++;
    assert(n48bt_lookup(&cache, display, &hit) && hit); checks++;
    printf("%u shared-PC cache checks passed\n", checks);
}
