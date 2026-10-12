#!/bin/bash
#
# fetch-firmware.sh - copy the AMD firmware the Navi48 bring-up kext embeds from a local
# linux-firmware checkout into src/navi48-bringup/firmware/ (gitignored; never commit it).
#
# This script does NOT use the network. Clone linux-firmware yourself first:
#     git clone https://gitlab.com/kernel-firmware/linux-firmware.git
#   (mirror: https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git)
#
# Usage:  [ASIC=navi44|navi48] tools/fetch-firmware.sh <path>
#   <path> is a linux-firmware checkout, or a directory containing amdgpu/ (e.g. /usr/lib/firmware
#   on a Linux system: the installed .bin.zst files are decompressed with zstd).
#   ASIC selects the set (default navi44 = RX 9060 XT); it must match `make ASIC=...`.
#
# The blobs are AMD's, under AMD's redistribution licence (LICENSE.amdgpu in linux-firmware).
set -euo pipefail

ASIC="${ASIC:-navi44}"
if [ $# -ne 1 ] || [ ! -d "$1" ]; then
    echo "usage: [ASIC=navi44|navi48] $0 <path-to-linux-firmware-checkout or /usr/lib/firmware>" >&2
    echo "clone it first: git clone https://gitlab.com/kernel-firmware/linux-firmware.git" >&2
    exit 2
fi
SRC="$1/amdgpu"
[ -d "$SRC" ] || { echo "fetch-firmware.sh: no amdgpu/ directory in $1" >&2; exit 2; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DST="$REPO/src/navi48-bringup/firmware"
mkdir -p "$DST"

# name  sha256 of the copy this project was developed against (a different linux-firmware
# revision may differ: a mismatch is a warning, not an error)
BLOBS_NAVI48="
gc_12_0_1_imu     b3b301fb636efc77b63ce4d2ced0f90c851d03c19681852faa45598e6f5773fd
gc_12_0_1_me      5549655093724b3e3b5fa016e8f1ef6ce3976209432230852cd94acbc1c245cb
gc_12_0_1_mec     72b25088072d630d115748ee3607d0db481b22a15260af3d0d599e516a0d7abb
gc_12_0_1_pfp     6dc9e6d22e0f9ddd04f12eedb5d1f6affae6d76d2993567aafde0e1619071c15
gc_12_0_1_rlc     6ba4459532246a5c415d3cb33c9b1248294e48f67b827e2accb292a8d1a5c0ec
gc_12_0_1_uni_mes bf26e0300989ebd011e991d76396e2c1673e1caa502fb6d8413e387eb1456676
psp_14_0_3_sos    23bea01a0c6f36d00759d0765d46cb4cb4aa87398b2fbccacbf547a890c0bf51
psp_14_0_3_ta     38d6691bf64232946cd5ce5735363c7c2877830ff640b9b95516403257fe2922
sdma_7_0_1        73c29e1c1714ebc95d2221ba56e187910902891593010653bf9518937e414a59
smu_14_0_3        3221ef2ddb341570eeb727e1e16f170bfb2ea1230be4a7eb248d0b183fbfbf15
"
# Navi 44 (RX 9060 XT): sha256 of linux-firmware 20260916, the exact blobs Linux amdgpu loaded on the
# reference card (versions in research/hw_dump/firmware_info.txt).
BLOBS_NAVI44="
gc_12_0_0_imu     aa15e5b3156bffc45e0c50bccbcd364fbd3f958531b695b7487a803d780b8328
gc_12_0_0_me      17487eb283d479ddb6331bc850a623e3f1217907e25aa5acf89602fb3eaeaf94
gc_12_0_0_mec     28b1e5bae440044887bab53a374db7bb971f7cc2780ab2b55c561e19f24d7fac
gc_12_0_0_pfp     5ec7a4341c22676da98d64cbc8dc5d820f3f13f199ea7e572f4064de406e715c
gc_12_0_0_rlc     6436b582734a413456fff3d3c7195e71cc9e78a7ed31ee21c83ffd6fae1ad186
gc_12_0_0_uni_mes ee058438467479d05d3d54ec9b0a592cac50bfa3834e65c6e90bd0e675c087d1
psp_14_0_2_sos    7b538448b57d4f9dd06b2eea90d4f86a16e65e3027cdecee8db71c2c5f1fa243
psp_14_0_2_ta     81d55b4e59bbb91c95ce4edf546c3870275ef426d0279970c3e7e33e62a68115
sdma_7_0_0        beaafb53993a106edd392392d5896245ae2a957c6d0f495d0002eec72ad8ad38
smu_14_0_2        1b2054e3f710d1ab8dbdf6ff35914ad376b51caa6337831260c955add874b2ee
"
case "$ASIC" in
    navi44) BLOBS="$BLOBS_NAVI44" ;;
    navi48) BLOBS="$BLOBS_NAVI48" ;;
    *) echo "fetch-firmware.sh: ASIC must be navi44 or navi48" >&2; exit 2 ;;
esac
# a build holds ONE profile's blobs: drop the other set so the Makefile cannot mix them
rm -f "$DST"/gc_12_0_*.bin "$DST"/psp_14_0_*.bin "$DST"/sdma_7_0_*.bin "$DST"/smu_14_0_*.bin
if command -v sha256sum >/dev/null 2>&1; then SHA() { sha256sum "$1" | awk '{print $1}'; }
else SHA() { shasum -a 256 "$1" | awk '{print $1}'; }; fi

while read -r name want; do
    [ -n "$name" ] || continue
    if [ -f "$SRC/$name.bin" ]; then
        cp "$SRC/$name.bin" "$DST/$name.bin"
    elif [ -f "$SRC/$name.bin.zst" ] && command -v zstd >/dev/null 2>&1; then
        zstd -dqf -o "$DST/$name.bin" "$SRC/$name.bin.zst"
    else
        echo "MISSING  $name.bin (not in $SRC)" >&2
        exit 1
    fi
    got="$(SHA "$DST/$name.bin")"
    if [ "$got" = "$want" ]; then echo "ok       $name.bin ($(wc -c < "$DST/$name.bin" | tr -d ' ') bytes)"
    else echo "DIFFERS  $name.bin (sha256 $got; developed against $want) - copied anyway"; fi
done <<< "$BLOBS"
cp "$1/LICENSE.amdgpu" "$DST/" 2>/dev/null || cp /usr/share/licenses/linux-firmware-amdgpu/LICENSE.amdgpu "$DST/" 2>/dev/null || true
echo "copied the $ASIC set into $DST"
