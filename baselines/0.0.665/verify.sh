#!/bin/sh
# verify.sh - rebuild the preserved 0.0.665 bring-up source trees from public commits and check them.
#
# Usage:
#   baselines/0.0.665/verify.sh [--repo DIR]
#   baselines/0.0.665/verify.sh [--repo DIR] --build MKSDK FIRMWARE_DIR
#
#   --repo DIR          a checkout of pastasugo89/RX9060XT_macOS_driver that contains commits
#                       35d8193 and 29a371b (default: the repository this script belongs to).
#   --build MKSDK FW    also compile the unified and the eight-session trees and compare the
#                       loaded Mach-O sections with manifests/binary-sections.txt. MKSDK is a
#                       MacKernelSDK directory (see toolchain.md); FW is a directory holding the
#                       ten navi44 firmware .bin files (see firmware.md). Takes several minutes.
#
# Source check (always): each tree is extracted from its base commit with git archive, the
# patches in patches/ are applied with git apply in a temporary directory outside any git
# repository, and every file of the scope (src/, shaders/, tools/, Makefile, Info.plist,
# minus the generated src/fw/fw_*.c) is compared with its manifest (sha256).
#
# Exit status: 0 when every requested check passes, 1 when a check fails, 2 for a usage or
# setup error. On failure the temporary directory is kept and its path is printed.
set -eu
export LC_ALL=C

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
DO_BUILD=0
MKSDK=""
FWDIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) [ $# -ge 2 ] || { echo "verify.sh: --repo needs a directory" >&2; exit 2; }
                REPO=$(cd "$2" && pwd); shift 2 ;;
        --build) [ $# -ge 3 ] || { echo "verify.sh: --build needs MKSDK and FIRMWARE_DIR" >&2; exit 2; }
                 [ -d "$2" ] && [ -d "$3" ] || { echo "verify.sh: MKSDK and FIRMWARE_DIR must be directories" >&2; exit 2; }
                 DO_BUILD=1; MKSDK=$(cd "$2" && pwd); FWDIR=$(cd "$3" && pwd); shift 3 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "verify.sh: unknown argument: $1" >&2; exit 2 ;;
    esac
done

command -v git >/dev/null 2>&1 || { echo "verify.sh: git is required" >&2; exit 2; }
if command -v shasum >/dev/null 2>&1; then SHA256="shasum -a 256"; else SHA256="sha256sum"; fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/rx9060-0.0.665.XXXXXX")
KEEP=0
cleanup() { if [ "$KEEP" -eq 0 ]; then rm -rf "$WORK"; else echo "kept for inspection: $WORK"; fi; }
trap cleanup EXIT INT TERM
if git -C "$WORK" rev-parse --git-dir >/dev/null 2>&1; then
    echo "verify.sh: the temporary directory $WORK is inside a git repository; set TMPDIR elsewhere" >&2
    exit 2
fi

# The scope listing: the same files, in the same order, as the manifests.
scope_list() {
    { find src shaders tools -type f; echo Makefile; echo Info.plist; } | grep -v -E '^src/fw/fw_.*\.c$' | sort
}

echo "repository: $REPO"
echo "temporary directory: $WORK"
status=0

# name, base commit, patches applied in order, manifest = manifests/<name>.sha256
while read -r name base patches; do
    git -C "$REPO" cat-file -e "$base^{commit}" 2>/dev/null \
        || { echo "verify.sh: commit $base is not in $REPO (fetch the public main branch)" >&2; KEEP=0; exit 2; }
done <<'EOF'
unified 35d819336f907f7eae1a3bd5e93dcc6b82fc0703 0001-unified-bringup-model-on-35d8193.patch
gpu-eight-repro-v6 35d819336f907f7eae1a3bd5e93dcc6b82fc0703 0001-unified-bringup-model-on-35d8193.patch 0002-gpu-eight-repro-v6-on-0001.patch
navi44-psp-safety-candidate 29a371b8eb479926cd0664e252f40eb3e2c19b67 0003-navi44-psp-safety-candidate-on-29a371b.patch
EOF

while read -r name base patches; do
    dir="$WORK/$name"
    mkdir -p "$dir"
    git -C "$REPO" archive "$base" cobalt64/src/navi48-bringup | tar -x -C "$dir"
    tree="$dir/cobalt64/src/navi48-bringup"
    for p in $patches; do
        if ! ( cd "$tree" && git apply --check "$HERE/patches/$p" && git apply "$HERE/patches/$p" ); then
            echo "FAIL $name: $p does not apply to $base"; KEEP=1; exit 1
        fi
    done
    ( cd "$tree" && scope_list | while IFS= read -r f; do printf '%s  %s\n' "$($SHA256 "$f" | cut -c1-64)" "$f"; done ) > "$WORK/$name.actual"
    if diff -u "$HERE/manifests/$name.sha256" "$WORK/$name.actual" > "$WORK/$name.diff"; then
        echo "PASS $name: $(wc -l < "$WORK/$name.actual" | tr -d ' ') files match manifests/$name.sha256 (base $base; patches: $patches)"
    else
        echo "FAIL $name: differences against manifests/$name.sha256:"
        sed -n '1,40p' "$WORK/$name.diff"
        KEEP=1; status=1
    fi
done <<'EOF'
unified 35d819336f907f7eae1a3bd5e93dcc6b82fc0703 0001-unified-bringup-model-on-35d8193.patch
gpu-eight-repro-v6 35d819336f907f7eae1a3bd5e93dcc6b82fc0703 0001-unified-bringup-model-on-35d8193.patch 0002-gpu-eight-repro-v6-on-0001.patch
navi44-psp-safety-candidate 29a371b8eb479926cd0664e252f40eb3e2c19b67 0003-navi44-psp-safety-candidate-on-29a371b.patch
EOF

if [ "$DO_BUILD" -eq 1 ]; then
    [ -d "$MKSDK/Headers" ] || { echo "verify.sh: MKSDK is not a MacKernelSDK directory: $MKSDK" >&2; exit 2; }
    for n in gc_12_0_0_imu gc_12_0_0_me gc_12_0_0_mec gc_12_0_0_pfp gc_12_0_0_rlc gc_12_0_0_uni_mes \
             psp_14_0_2_sos psp_14_0_2_ta sdma_7_0_0 smu_14_0_2; do
        [ -f "$FWDIR/$n.bin" ] || { echo "verify.sh: missing firmware $FWDIR/$n.bin (see firmware.md)" >&2; exit 2; }
    done
    # name, make flags, build directory, label used in manifests/binary-sections.txt
    while IFS='|' read -r name flags builddir label; do
        tree="$WORK/$name/cobalt64/src/navi48-bringup"
        mkdir -p "$tree/firmware"
        cp "$FWDIR"/*.bin "$tree/firmware/"
        echo "building $name ($flags) ..."
        # shellcheck disable=SC2086
        if ! ( cd "$tree" && make -j4 $flags MKSDK="$MKSDK" XLAT12_DIR="$REPO/cobalt64/src/xlat12" \
                SHADERCACHE_DIR="$REPO/cobalt64/src/shadercache" DCN41_DIR="$REPO/cobalt64/src/dcn41" ) \
                > "$WORK/$name.build.log" 2>&1; then
            echo "FAIL build $name (log: $WORK/$name.build.log)"; KEEP=1; status=1; continue
        fi
        bin="$tree/$builddir/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup"
        python3 -I - "$bin" "$label" > "$WORK/$name.sections" <<'PY'
import struct, sys, hashlib
data = open(sys.argv[1], 'rb').read(); label = sys.argv[2]
ncmds = struct.unpack_from('<I', data, 16)[0]; pos = 32
for _ in range(ncmds):
    cmd, length = struct.unpack_from('<II', data, pos)
    if cmd == 0x19:
        for i in range(struct.unpack_from('<I', data, pos + 64)[0]):
            q = pos + 72 + i * 80
            sect, seg = struct.unpack_from('<16s16s', data, q)
            size = struct.unpack_from('<Q', data, q + 40)[0]; offset = struct.unpack_from('<I', data, q + 48)[0]
            if offset and size:
                print('%s %s,%s %d %s' % (label, seg.rstrip(b'\0').decode(), sect.rstrip(b'\0').decode(), size,
                                          hashlib.sha256(data[offset:offset+size]).hexdigest()))
    pos += length
PY
        if grep -v '^#' "$HERE/manifests/binary-sections.txt" | grep "^$label " | diff -u - "$WORK/$name.sections" > "$WORK/$name.sections.diff"; then
            echo "PASS sections $label: $(wc -l < "$WORK/$name.sections" | tr -d ' ') loaded sections identical to the preserved binary"
        else
            echo "FAIL sections $label:"; sed -n '1,30p' "$WORK/$name.sections.diff"; KEEP=1; status=1
        fi
    done <<'EOF'
unified|BUILD=build-console-guard|build-console-guard|unified-bringup-model-097b9b9f
gpu-eight-repro-v6|NATIVE_SESSIONS=8 BUILD=build-eight|build-eight|gpu-eight-repro-v6-607fd051
EOF
fi

if [ "$status" -eq 0 ]; then echo "all requested checks passed"; else echo "some checks FAILED"; fi
exit "$status"
