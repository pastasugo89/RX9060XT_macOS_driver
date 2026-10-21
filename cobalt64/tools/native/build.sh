#!/bin/sh
# build.sh - builds the userspace tools of tools/native on the Mac (Apple clang, the Command Line Tools are enough).
#
# RECONSTRUCTION, MINIMAL (2026-10-21). The Cobalt64 build.sh is not in the published snapshot; this one was rebuilt by us
# with only what the tree needs today. It builds n48nub. It does NOT build n48mode: tools/native/n48mode.c is not in the tree
# (the native_s2d tests expect "n48mode:n48mode.c" here, so those tests stay failing until n48mode.c is restored).
# The list is "binary:source" pairs; add a pair to build another tool from this directory.
#
#   sh tools/native/build.sh          (run from anywhere; writes the binaries next to this script)
#
# License: MIT, as the project.
set -eu
cd "$(dirname "$0")"
TOOLS="n48nub:n48nub.c"
for t in $TOOLS; do
    bin=${t%%:*}
    src=${t#*:}
    clang -std=c11 -Wall -Wextra -O2 -o "$bin" "$src" -framework IOKit -framework CoreFoundation
    echo "built tools/native/$bin"
done
