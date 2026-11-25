#!/bin/bash
# Stage the 0.0.685 kernel (SMU mailbox health latch, display clock floors off by default and guarded, self-limiting clock trace) and activation
# guard against the recorded 0.0.684 EFI (payload v20-b45, the one installed). The guard is derived from the LIVE guard (whatever Metal bundle it
# pins); only the five kernel lines change 684 -> 685.
# Usage: stage-685-payload.sh [OUTPUT_DIR]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
BUILDS="$ROOT/research/builds/macos-20261125"
CAND="$BUILDS/kernel-685/kernel-contexts-v21"
BASE="$BUILDS/kernel-684/kernel-payload-v20-b45"
OUT=${1:-$BUILDS/kernel-685/kernel-payload-v21}
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
