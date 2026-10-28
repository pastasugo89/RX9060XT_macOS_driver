// Cache symbol predicates for immutable dyld shared-cache return PCs only.
// Caller serializes access with N48S.mu. This caches no IOSurface verdict:
// a negative call stack must still be reconsidered from a different caller.
#ifndef N48_BTCACHE_H
#define N48_BTCACHE_H
#include <stdint.h>
#include <stddef.h>
#define N48BT_CAP 256u
typedef struct { uintptr_t pc[N48BT_CAP]; unsigned char hit[N48BT_CAP]; } n48bt_cache;
static inline size_t n48bt_index(uintptr_t pc) {
    return (size_t)(((pc >> 4) ^ (pc >> 13)) & (N48BT_CAP - 1u));
}
static inline int n48bt_lookup(const n48bt_cache *cache, uintptr_t pc, int *hit) {
    if (!pc || cache->pc[n48bt_index(pc)] != pc) return 0;
    *hit = cache->hit[n48bt_index(pc)] != 0;
    return 1;
}
static inline void n48bt_put(n48bt_cache *cache, uintptr_t pc, int immutable_shared_image, int hit) {
    if (!pc || !immutable_shared_image) return;
    const size_t i = n48bt_index(pc);
    cache->pc[i] = pc;
    cache->hit[i] = hit != 0;
}
#endif
