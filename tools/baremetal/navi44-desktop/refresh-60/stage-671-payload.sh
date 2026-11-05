#!/bin/bash
# Stage-time step for the 0.0.671 payload (payload v7: refresh-60b + the GTT fix). Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The baseline is payload v5 (its candidate state is the live EFI the 0.0.671 EFI is derived from; v6/0.0.670 was never installed). The guard and the
# Metal expectations are derived from the LIVE guard and the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either;
# each run writes a NEW output directory.
# usage: stage-671-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261105/kernel-671/kernel-payload-v7)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261105/kernel-671/kernel-payload-v7}
CAND="$ROOT/research/builds/macos-20261105/kernel-671/kernel-contexts-v7"
BASE="$ROOT/research/builds/macos-20261101/refresh-60/kernel-payload-v5"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
