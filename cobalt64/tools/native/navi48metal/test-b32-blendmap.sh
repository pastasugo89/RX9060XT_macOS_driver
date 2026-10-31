#!/bin/sh
# test-b32-blendmap.sh: bundle 32 blend-factor mapping, executed. Extracts n48_bf and n48_bf_is_src1 from Navi48Device.m (the real text, not a copy),
# compiles them with the real Metal and Vulkan headers and checks every MTLBlendFactor with dual-source off and on.
# Usage: N48_VK_INC=-I<mesa include> sh test-b32-blendmap.sh [path/to/Navi48Device.m]   (default: Navi48Device.m beside this script)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
src=${1:-$here/Navi48Device.m}
VKINC=${N48_VK_INC:--I/opt/homebrew/include}
tmp=$(mktemp -d "${TMPDIR:-/tmp}/b32blend.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
start=$(grep -n '^static VkBlendFactor n48_bf(MTLBlendFactor f, BOOL \*bad) {' "$src" | cut -d: -f1)
stop=$(grep -n '^static VkBlendOp n48_bo(' "$src" | cut -d: -f1)
if [ -z "$start" ] || [ -z "$stop" ]; then echo "FAIL: n48_bf not found in $src"; exit 1; fi
sed -n "${start},$((stop - 1))p" "$src" > "$tmp/bf.inc"
cat > "$tmp/main.m" <<'CEOF'
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <vulkan/vulkan.h>
static struct { BOOL dualSrc; } N48R;   /* the field n48_bf reads (Navi48Device.m: N48R.dualSrc) */
#include "bf.inc"
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } }
int main(void) {
    for (int on = 0; on <= 1; on++) {
        N48R.dualSrc = on ? YES : NO;
        for (int f = 0; f <= 18; f++) {
            BOOL bad = NO; VkBlendFactor v = n48_bf((MTLBlendFactor)f, &bad);
            const int is1 = f >= 15;   /* MTLBlendFactorSource1Color .. OneMinusSource1Alpha */
            char w[96];
            snprintf(w, sizeof w, "dualSrc=%d factor %d: %s", on, f, is1 ? (on ? "mapped" : "refused") : "unchanged");
            check(n48_bf_is_src1((MTLBlendFactor)f) == is1, w);
            if (is1 && !on) check(bad == YES, w);
            else if (is1) check(bad == NO && v != VK_BLEND_FACTOR_ZERO, w);
            else check(bad == NO, w);
        }
    }
    N48R.dualSrc = YES;
    BOOL b = NO;
    check(n48_bf(MTLBlendFactorSource1Color, &b) == VK_BLEND_FACTOR_SRC1_COLOR && b == NO, "Source1Color -> VK_BLEND_FACTOR_SRC1_COLOR");
    check(n48_bf(MTLBlendFactorOneMinusSource1Color, &b) == VK_BLEND_FACTOR_ONE_MINUS_SRC1_COLOR, "OneMinusSource1Color -> VK_BLEND_FACTOR_ONE_MINUS_SRC1_COLOR");
    check(n48_bf(MTLBlendFactorSource1Alpha, &b) == VK_BLEND_FACTOR_SRC1_ALPHA, "Source1Alpha -> VK_BLEND_FACTOR_SRC1_ALPHA");
    check(n48_bf(MTLBlendFactorOneMinusSource1Alpha, &b) == VK_BLEND_FACTOR_ONE_MINUS_SRC1_ALPHA, "OneMinusSource1Alpha -> VK_BLEND_FACTOR_ONE_MINUS_SRC1_ALPHA");
    printf("test-b32-blendmap: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
CEOF
clang -fobjc-arc -O1 -Wall -Wextra -Werror $VKINC -I"$tmp" -framework Foundation -framework Metal -o "$tmp/t" "$tmp/main.m"
"$tmp/t"
