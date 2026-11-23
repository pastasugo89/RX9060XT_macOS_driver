#!/bin/bash
# Stage-time step for the 0.0.679 payload (payload v15: the 0.0.678 release with the kernel GFX queue's doorbell in Linux's units by default (gfx_ring0 << 1,
# byte 0x458, inside the GFX doorbell window only; navi48-gfxdb=0 = the 0.0.676..0.0.678 byte 0x22C, inside the MEC window) and a NOP-only doorbell probe with
# busy marks at the start of ComputeDispatch; the DPM gate, the ComputeDispatch fix and the marks are unchanged). Staged only: nothing is installed, no EFI is
# mounted, no live file is written. The baseline is payload v14 (its candidate state is the live EFI: 0.0.678, installed). The guard and the Metal
# expectations are derived from the LIVE guard and the LIVE Metal bundle at the moment this runs (read only); each run writes a NEW output directory.
# usage: stage-679-payload.sh [OUTPUT_DIR]   OUTPUT_DIR must be new and under research/builds (default: .../macos-20261123/kernel-679/kernel-payload-v15)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
TOOL="$ROOT/tools/baremetal/navi44-desktop/production-kernel-payload.py"
OUT=${1:-$ROOT/research/builds/macos-20261123/kernel-679/kernel-payload-v15}
CAND="$ROOT/research/builds/macos-20261123/kernel-679/kernel-contexts-v15"
BASE="$ROOT/research/builds/macos-20261123/kernel-678/kernel-payload-v14"
python3 -B "$TOOL" prepare --candidate "$CAND" --output "$OUT" --baseline-payload "$BASE" --baseline-state candidate
python3 -B "$TOOL" check "$OUT"
