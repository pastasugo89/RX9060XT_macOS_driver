#!/bin/bash
# Stage-time step for the 0.0.669 payload. Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The guard and the Metal expectations are derived from the LIVE guard and the LIVE Metal bundle at the moment this runs (read only).
# Re-run it after any change of either (a new Metal bundle, a new guard profile); each run writes a NEW output directory.
# usage: stage-669-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../refresh-60/kernel-payload-v5)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261101/refresh-60/kernel-payload-v5}
CAND="$ROOT/research/builds/macos-20261101/refresh-60/kernel-contexts-v5"
BASE="$ROOT/research/builds/macos-20261031/production/kernel-payload-v4"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
