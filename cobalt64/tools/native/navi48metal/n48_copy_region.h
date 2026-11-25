// Shared-image copy overlap, in root-image coordinates. Texture copies have equal extents.
#ifndef N48_COPY_REGION_H
#define N48_COPY_REGION_H
#include <stdint.h>
static inline int n48cr_axis_overlap(uint64_t a, uint64_t b, uint64_t size) {
    return a <= b ? b - a < size : a - b < size;
}
static inline int n48cr_overlap(uint32_t amip, uint32_t alayer, uint64_t ax, uint64_t ay, uint64_t az,
                                uint32_t bmip, uint32_t blayer, uint64_t bx, uint64_t by, uint64_t bz,
                                uint64_t width, uint64_t height, uint64_t depth) {
    return amip == bmip && alayer == blayer && n48cr_axis_overlap(ax, bx, width) &&
           n48cr_axis_overlap(ay, by, height) && n48cr_axis_overlap(az, bz, depth);
}
#endif
