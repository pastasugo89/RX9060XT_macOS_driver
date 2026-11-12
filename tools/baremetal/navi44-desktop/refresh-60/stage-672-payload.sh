#!/bin/bash
# Stage-time step for the 0.0.672 payload (payload v8: the 0.0.671 release + the black-band UCLK pin and underflow monitor). Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The baseline is payload v7 (its candidate state is the live EFI the 0.0.672 EFI is derived from). The guard and the Metal expectations
# are derived from the LIVE guard and the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either;
# each run writes a NEW output directory.
# usage: stage-672-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261112/kernel-672/kernel-payload-v8)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261112/kernel-672/kernel-payload-v8}
CAND="$ROOT/research/builds/macos-20261112/kernel-672/kernel-contexts-v8"
BASE="$ROOT/research/builds/macos-20261105/kernel-671/kernel-payload-v7"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
