#!/bin/bash
# Stage-time step for the 0.0.677 payload (payload v13: the 0.0.676 release + boot-time CP busy marks (ioreg Navi48,CpBusyMarks; navi48-cpmark=0 off), an
# opt-in queue census (navi48-cpcensus=1) and opt-in A/B switches navi48-gfxdb=1 (Linux's GFX doorbell index) and navi48-kiqsched=0 (no KIQ scheduler write);
# defaults = 0.0.676 plus reads). Staged only: nothing is installed, no EFI is mounted, no live file is written.
# The baseline is payload v12 (its candidate state is the live EFI: 0.0.676, installed). The guard and the Metal expectations are derived from the LIVE guard and
# the LIVE Metal bundle at the moment this runs (read only). Re-run it after any change of either; each run writes a NEW output directory.
# usage: stage-677-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261117/kernel-677/kernel-payload-v13)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261117/kernel-677/kernel-payload-v13}
CAND="$ROOT/research/builds/macos-20261117/kernel-677/kernel-contexts-v13"
BASE="$ROOT/research/builds/macos-20261114/kernel-676/kernel-payload-v12"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
