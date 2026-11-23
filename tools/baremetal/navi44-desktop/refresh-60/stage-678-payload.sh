#!/bin/bash
# Stage-time step for the 0.0.678 payload (payload v14: the 0.0.677 release + the ComputeDispatch fix (the GFX12 compute preamble in the boot and native S1b
# dispatch IBs, no COMPUTE_* readback on success; navi48-cdfix=0 = the 0.0.677 stream; sub-marks inside ComputeDispatch) and GFXCLK under PMFW DPM (SetSoftMax 0xffff
# / SetSoftMin 0 + SetWorkloadMask(bootup default)) in place of the 500 MHz clamp, applied only when the command fetcher is idle at the end of runStages
# (navi48-dpm=0 keeps the clamp; navi48-gfxmax still caps; ioreg Navi48,Dpm). Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The baseline is payload v13 (its candidate state is the live EFI: 0.0.677, installed). The guard and the Metal expectations are derived from the LIVE guard and
# the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either; each run writes a NEW output directory.
# usage: stage-678-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261123/kernel-678/kernel-payload-v14)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261123/kernel-678/kernel-payload-v14}
CAND="$ROOT/research/builds/macos-20261123/kernel-678/kernel-contexts-v14"
BASE="$ROOT/research/builds/macos-20261117/kernel-677/kernel-payload-v13"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
