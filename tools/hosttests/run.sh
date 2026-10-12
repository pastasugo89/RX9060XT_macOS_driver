#!/usr/bin/env bash
# Host tests for freestanding kext code, run on Linux against the real dumps in research/hw_dump.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/cobalt64/src/navi48-bringup/src"
OUT="${TMPDIR:-/tmp}/rx9060-hosttests"; mkdir -p "$OUT"
c++ -std=c++17 -O1 -Wall -I"$SRC" "$ROOT/tools/hosttests/test_ipdiscovery.cpp" "$SRC/ipdiscovery.cpp" -o "$OUT/test_ipdiscovery"
# Navi 44 (questa scheda): 2 SE, 2 SA/SE, 4 RB/SE, 8 CU per SA
"$OUT/test_ipdiscovery" "$ROOT/research/hw_dump/ip_discovery_table.bin" 2 2 4 8
