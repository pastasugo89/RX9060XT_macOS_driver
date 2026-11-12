#!/bin/bash
# Stage-time step for the 0.0.674 payload (payload v10: the 0.0.673 release + the two-stage UCLK fallback (stage 1 = the stutter forced off again, no pin;
# stage 2 = the pin on the next trigger; one time-limited release of an AUTO pin after 10 min without a counted underflow) and the OPTC-only status
# counted as a diagnostic next to its event). Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The baseline is payload v9 (its candidate state is the live EFI: 0.0.673, installed). The guard and the Metal expectations are derived from the LIVE guard
# and the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either; each run writes a NEW output directory.
# usage: stage-674-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261112/kernel-674/kernel-payload-v10)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261112/kernel-674/kernel-payload-v10}
CAND="$ROOT/research/builds/macos-20261112/kernel-674/kernel-contexts-v10"
BASE="$ROOT/research/builds/macos-20261112/kernel-673/kernel-payload-v9"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
