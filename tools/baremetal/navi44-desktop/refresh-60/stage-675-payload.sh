#!/bin/bash
# Stage-time step for the 0.0.675 payload (payload v11: the 0.0.674 release + GFX clock gating, Linux gfx_v12_0_update_gfx_clock_gating run once after the full
# bring-up ladder (navi48-cg=0 off, navi48-cg-ints=0 without the CP interrupt enables; ioreg property Navi48,ClockGating), and the thermal policy that never
# refuses a submission (WARN 90 C, TRIP 100 C: GFXCLK clamped to the PMFW minimum through the SMU until the hotspot stays below 85 C for 10 s). The idle clamp
# default is unchanged. Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The baseline is payload v10 (its candidate state is the live EFI: 0.0.674, installed; the latest v10 directory, kernel-payload-v10-193959). The guard and the
# Metal expectations are derived from the LIVE guard and the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either; each
# run writes a NEW output directory.
# usage: stage-675-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261112/kernel-675/kernel-payload-v11)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261112/kernel-675/kernel-payload-v11}
CAND="$ROOT/research/builds/macos-20261112/kernel-675/kernel-contexts-v11"
BASE="$ROOT/research/builds/macos-20261112/kernel-674/kernel-payload-v10-193959"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
