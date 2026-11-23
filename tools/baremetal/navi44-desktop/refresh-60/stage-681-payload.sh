#!/bin/bash
# Stage the 0.0.681 kernel and activation guard against the recorded 0.0.680 EFI.
# Usage: stage-681-payload.sh [OUTPUT_DIR]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
BUILDS="$ROOT/research/builds/macos-20261123"
CAND="$BUILDS/kernel-681/kernel-contexts-v17"
BASE="$BUILDS/kernel-680/kernel-payload-v16"
OUT=${1:-$BUILDS/kernel-681/kernel-payload-v17}
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
