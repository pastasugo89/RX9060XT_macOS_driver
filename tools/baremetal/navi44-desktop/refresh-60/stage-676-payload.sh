#!/bin/bash
# Stage-time step for the 0.0.676 payload (payload v12: the 0.0.675 release + the PMFW zero-RPM fan option through the OverDrive table (boot-arg
# navi48-fan-zerorpm=0 keeps the fans spinning; absent = nothing read or written; ioreg property Navi48,Fan), the boot GFXCLK cap navi48-gfxmax=<MHz> (absent =
# the PMFW minimum, as 0.0.675) and the AUTO UCLK pin kept for the boot (the 10-minute release only with navi48-uclkpin-release=1). Staged only: nothing is
# installed, no EFI is mounted, no live file is written.
# The baseline is payload v11 (its candidate state is the live EFI: 0.0.675, installed). The guard and the Metal expectations are derived from the LIVE guard and
# the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either; each run writes a NEW output directory.
# usage: stage-676-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261114/kernel-676/kernel-payload-v12)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261114/kernel-676/kernel-payload-v12}
CAND="$ROOT/research/builds/macos-20261114/kernel-676/kernel-contexts-v12"
BASE="$ROOT/research/builds/macos-20261112/kernel-675/kernel-payload-v11"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
