#!/bin/bash
# Stage the 0.0.682 kernel and activation guard against the recorded 0.0.681 EFI.
# Usage: stage-682-payload.sh [OUTPUT_DIR]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
BUILDS="$ROOT/research/builds"
CAND="$BUILDS/macos-20261125/kernel-682/kernel-contexts-v18-reviewed"
BASE="$BUILDS/macos-20261123/kernel-681/kernel-payload-v17"
OUT=${1:-$BUILDS/macos-20261125/kernel-682/kernel-payload-v18}
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
