#!/bin/bash
# Stage the 0.0.683 kernel and activation guard against the recorded 0.0.682 EFI.
# Usage: stage-683-payload.sh [OUTPUT_DIR]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
BUILDS="$ROOT/research/builds/macos-20261125"
CAND="$BUILDS/kernel-683/kernel-contexts-v19"
BASE="$BUILDS/kernel-682/kernel-payload-v18"
OUT=${1:-$BUILDS/kernel-683/kernel-payload-v19}
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
