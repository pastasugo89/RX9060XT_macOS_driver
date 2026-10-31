#!/bin/sh
# test-b30-vonly.sh: bundle 30 vertex-only pipeline and invisible-fallback decisions.
# 1. Extracts the n48-vonly-helpers block from Navi48Device.m (the real text, not a copy), compiles it with a harness and runs it.
# 2. Checks by source text that the helpers are wired where they must be (the Objective-C pipeline itself cannot run on a host without Metal).
# Usage: sh test-b30-vonly.sh [path/to/Navi48Device.m]     (default: Navi48Device.m beside this script)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
src=${1:-$here/Navi48Device.m}
tmp=$(mktemp -d "${TMPDIR:-/tmp}/b30vonly.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
fails=0
sed -n '/BEGIN n48-vonly-helpers/,/END n48-vonly-helpers/p' "$src" > "$tmp/helpers.inc"
if [ ! -s "$tmp/helpers.inc" ]; then echo "FAIL: helper block not found in $src"; exit 1; fi

cat > "$tmp/main.c" <<'EOF'
#include <stdio.h>
#include <stdint.h>
typedef signed char BOOL;
#define YES ((BOOL)1)
#define NO ((BOOL)0)
#include "helpers.inc"
static int fails = 0;
#define CHECK(c, what) do { if (!(c)) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); } while (0)
int main(void) {
    CHECK(n48_pl_stages_ready(NO, YES, YES) == YES, "normal pipeline, both stages present: ready");
    CHECK(n48_pl_stages_ready(NO, YES, NO) == NO, "normal pipeline, fragment missing: not ready (fallback / error path)");
    CHECK(n48_pl_stages_ready(NO, NO, YES) == NO, "normal pipeline, vertex missing: not ready");
    CHECK(n48_pl_stages_ready(YES, YES, NO) == YES, "vertex-only pipeline, vertex present, no fragment: ready");
    CHECK(n48_pl_stages_ready(YES, NO, NO) == NO, "vertex-only pipeline, vertex missing: not ready");
    CHECK(n48_pl_stage_count(NO) == 1, "no fragment module: one stage passed");
    CHECK(n48_pl_stage_count(YES) == 2, "fragment module present: two stages passed");
    CHECK(n48_pl_fb_invisible(YES, NO) == YES, "fallback without kill file: invisible");
    CHECK(n48_pl_fb_invisible(YES, YES) == NO, "fallback with magenta kill file: as before (magenta)");
    CHECK(n48_pl_fb_invisible(NO, NO) == NO, "no fallback: not invisible");
    printf("test-b30-vonly (helpers): %s\n", fails ? "FAILED" : "PASS");
    return fails ? 1 : 0;
}
EOF
if ! cc -O1 -Wall -Wextra -Werror -I"$tmp" -o "$tmp/t" "$tmp/main.c"; then echo "FAIL: harness does not compile"; exit 1; fi
if ! "$tmp/t"; then fails=$((fails + 1)); fi

# Source-text wiring (each line must be present in the file).
want() {
    if grep -F -q -- "$1" "$src"; then echo "ok  : wiring: $2"; else echo "FAIL: wiring missing: $2"; fails=$((fails + 1)); fi
}
want 'const BOOL vonly = (d.fragmentFunction == nil);' 'vertex-only decided from a nil fragment function'
want 'fsd = vonly ? nil : n48_spv_lookup(d.fragmentFunction, "fragment", &e2, &fname, &mf_);' 'no fragment lookup for a vertex-only pipeline'
want 'tf = (vonly || fsd) ? YES : n48x_translate_fn(d.fragmentFunction, "fragment", dl);' 'no in-process translation of a nil fragment'
want 'rf = vonly ? NULL : calloc(1, sizeof *rf);' 'no fragment reflection for a vertex-only pipeline'
want '_fs = VK_NULL_HANDLE;   // bundle 30' 'fragment module starts null'
want 'if (fb || !vonly) { _fs = fb ?' 'fragment module built only for magenta fallback or a real fragment'
want 'if (vonly) N48LOG("pipeline: no fragment function: vertex-only pipeline (depth/stencil only, colour write masks 0)' 'vertex-only log line'
want 'if (vonly || n48_pl_fb_invisible(fb, n48_magenta_kill())) wm = 0;' 'colour write masks 0 for vertex-only and invisible fallback'
want '.stageCount = n48_pl_stage_count(_fs != VK_NULL_HANDLE)' 'stage count follows the fragment module'
want 'n48hs_register(self, vonly ? @[ sv ] : @[ sv, sf ], NO,' 'hot-swap registers the vertex key alone for vertex-only'
want 'if (d.fragmentFunction) n48_dump_function(d.fragmentFunction, "fragment", paths, notes);' 'no fragment AIR dump for nil'
want 'const BOOL inv = n48_pl_fb_invisible(_fallback, n48_magenta_kill());' 'invisible fallback computed in the variant builder'
want '.depthWriteEnable = (dv.depthWrite && !inv) ? VK_TRUE : VK_FALSE' 'invisible fallback writes no depth'
want '.stencilTestEnable = (dv.stencilTest && !inv) ? VK_TRUE : VK_FALSE' 'invisible fallback writes no stencil'
want '#define N48_MAGENTA_FILE "/private/tmp/n48m-magenta"' 'magenta kill file path'
want 'fb ? (n48_pl_fb_invisible(YES, n48_magenta_kill()) ? ", FALLBACK invisible" : ", FALLBACK magenta") : ""' 'pipeline log names invisible / magenta fallback'

echo "test-b30-vonly: $([ "$fails" -eq 0 ] && echo PASS || echo "FAILED ($fails)")"
[ "$fails" -eq 0 ]
