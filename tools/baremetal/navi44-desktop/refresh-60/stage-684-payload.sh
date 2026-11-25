#!/bin/bash
# Stage the 0.0.684 kernel (display clock floors + boot clock trace) and activation guard against the recorded 0.0.683 EFI.
# The guard is derived from the LIVE guard (whatever Metal bundle it pins); only the five kernel lines change 683 -> 684.
# Usage: stage-684-payload.sh [OUTPUT_DIR]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
BUILDS="$ROOT/research/builds/macos-20261125"
CAND="$BUILDS/kernel-684/kernel-contexts-v20"
BASE="$BUILDS/kernel-683/kernel-payload-v19"
OUT=${1:-$BUILDS/kernel-684/kernel-payload-v20}
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
