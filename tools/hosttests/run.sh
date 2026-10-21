#!/usr/bin/env bash
# Host tests for freestanding kext code, run on Linux against the real dumps in research/hw_dump.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/cobalt64/src/navi48-bringup/src"
OUT="${TMPDIR:-/tmp}/rx9060-hosttests"; mkdir -p "$OUT"
c++ -std=c++17 -O1 -Wall -I"$SRC" "$ROOT/tools/hosttests/test_mes_set_hw_resources_1_wire.cpp" -o "$OUT/test_mes_set_hw_resources_1_wire"
"$OUT/test_mes_set_hw_resources_1_wire"
c++ -std=c++17 -O1 -Wall -I"$SRC" "$ROOT/tools/hosttests/test_vadd_ir_abi.cpp" -o "$OUT/test_vadd_ir_abi"
"$OUT/test_vadd_ir_abi"
c++ -std=c++17 -O1 -Wall -I"$SRC" "$ROOT/tools/hosttests/test_ipdiscovery.cpp" "$SRC/ipdiscovery.cpp" -o "$OUT/test_ipdiscovery"
# Navi 44 (questa scheda): 2 SE, 2 SA/SE, 4 RB/SE, 8 CU per SA
"$OUT/test_ipdiscovery" "$ROOT/research/hw_dump/ip_discovery_table.bin" 2 2 4 8

# PSP: the kext's sos.bin container parser (psp.cpp) on the installed linux-firmware blobs.
# Navi 44 (psp_14_0_2) has no RAS_DRV and no RL; the chain skips absent components (psp.cpp loadComponent, psp_v14_0.cpp rl_load).
c++ -std=c++17 -O1 -Wall -Wno-unused-function -I"$ROOT/tools/hosttests/stub" -I"$SRC" \
    "$ROOT/tools/hosttests/test_psp_container.cpp" "$SRC/psp.cpp" -o "$OUT/test_psp_container"
for v in 14_0_2 14_0_3; do
  fw=/usr/lib/firmware/amdgpu/psp_${v}_sos.bin
  if [ -f "$fw.zst" ]; then zstd -dqf "$fw.zst" -o "$OUT/psp_${v}_sos.bin"; fw="$OUT/psp_${v}_sos.bin"; fi
  [ -f "$fw" ] || { echo "skip psp_${v}_sos (not installed)"; continue; }
  echo "psp_${v}_sos:"; "$OUT/test_psp_container" "$fw" | grep -v '^Navi48Bringup'
done

# Firmware: the kext's per-IP extractor (amd/amdgpu_ucode_extract.cpp) on the GC / SDMA blobs of both boards.
clang++ -std=c++17 -O1 -Wno-everything -I"$ROOT/tools/hosttests/stub" -I"$SRC" -I"$SRC/amd" \
    "$ROOT/tools/hosttests/test_ucode_extract.cpp" "$SRC/amd/amdgpu_ucode_extract.cpp" -o "$OUT/test_ucode_extract"
for pair in "12_0_0 7_0_0" "12_0_1 7_0_1"; do
  set -- $pair; gc=$1; sd=$2; echo "gc_$gc / sdma_$sd:"
  for k in rlc imu mes pfp me mec sdma; do
    fn=gc_${gc}_$k; [ $k = mes ] && fn=gc_${gc}_uni_mes; [ $k = sdma ] && fn=sdma_$sd
    fw=/usr/lib/firmware/amdgpu/$fn.bin
    if [ -f "$fw.zst" ]; then zstd -dqf "$fw.zst" -o "$OUT/$fn.bin"; fw="$OUT/$fn.bin"; fi
    [ -f "$fw" ] || { echo "  skip $fn (not installed)"; continue; }
    "$OUT/test_ucode_extract" $k "$fw" | tail -1
  done
done

# GOP observation table (dcn/navi48_gopsnap.h): every row against the DCN 4.1.0 header, the DMU segment bases of the dump, and the
# display connector constants of asic_profile.h for each profile. Skipped (not failed) when research/src is not cloned.
GOPHDR="$ROOT/research/src/linux/drivers/gpu/drm/amd/include/asic_reg/dcn/dcn_4_1_0_offset.h"
if [ -f "$GOPHDR" ]; then
  c++ -std=c++17 -O1 -Wall -I"$SRC" -I"$SRC/dcn" -I"$SRC/amd" "$ROOT/tools/hosttests/test_gopsnap.cpp" "$SRC/ipdiscovery.cpp" -o "$OUT/test_gopsnap"
  "$OUT/test_gopsnap" "$GOPHDR" "$ROOT/research/hw_dump/ip_discovery_table.bin" 0xc0 0x34c0 0x9000
  c++ -std=c++17 -O1 -Wall -DN4X_ASIC_NAVI48 -I"$SRC" -I"$SRC/dcn" -I"$SRC/amd" "$ROOT/tools/hosttests/test_gopsnap.cpp" "$SRC/ipdiscovery.cpp" -o "$OUT/test_gopsnap48"
  "$OUT/test_gopsnap48" "$GOPHDR" "$ROOT/research/hw_dump/ip_discovery_table.bin" 0xc0 0x34c0 0x9000
else
  echo "skip test_gopsnap (research/src DCN header not present)"
fi

# Display profile seam (dcn/navi48_disp_profile.h): formulas against dcn_4_1_0_offset.h and the live path / feature policy per ASIC.
if [ -f "$GOPHDR" ]; then
  c++ -std=c++17 -O1 -Wall -I"$SRC" "$ROOT/tools/hosttests/test_disp_profile.cpp" -o "$OUT/test_disp_profile44"
  "$OUT/test_disp_profile44" "$GOPHDR"
  c++ -std=c++17 -O1 -Wall -DN4X_ASIC_NAVI48 -I"$SRC" "$ROOT/tools/hosttests/test_disp_profile.cpp" -o "$OUT/test_disp_profile48"
  "$OUT/test_disp_profile48" "$GOPHDR"
fi
