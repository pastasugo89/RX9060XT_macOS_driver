#!/usr/bin/env bash
# Extract the executable text from the pinned gfx1200 HSACO and embed it.
# The object symbol/descriptor are checked so a stale assembly listing or a
# different compiler output cannot silently change the kernel ABI.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HSACO="$REPO/../../../research/artifacts/compute/kernels/vadd_ir.hsaco"
LLVM_BIN="${LLVM_BIN:-/usr/bin}"
OBJCOPY="$LLVM_BIN/llvm-objcopy"
READELF="$LLVM_BIN/llvm-readelf"
for tool in "$OBJCOPY" "$READELF"; do
  [[ -x "$tool" ]] || { echo "missing tool: $tool" >&2; exit 1; }
done
[[ -f "$HSACO" ]] || { echo "missing pinned artifact: $HSACO" >&2; exit 1; }
"$READELF" -n "$HSACO" | grep -q 'amdhsa.target:.*gfx1200' || {
  echo "vadd HSACO target is not gfx1200" >&2; exit 1;
}
"$READELF" -s "$HSACO" | grep -Eq '196 FUNC .* vadd_ir$' || {
  echo "vadd_ir symbol is not the audited 196-byte function" >&2; exit 1;
}
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$OBJCOPY" -O binary --only-section=.text "$HSACO" "$tmp/text.bin"
"$OBJCOPY" -O binary --only-section=.rodata "$HSACO" "$tmp/rodata.bin"
python3 - "$tmp/text.bin" "$tmp/rodata.bin" <<'PY'
import pathlib, struct, sys
text, rodata = (pathlib.Path(p).read_bytes() for p in sys.argv[1:])
if len(text) != 640 or len(rodata) != 64:
    raise SystemExit(f"unexpected vadd sections: text={len(text)}, descriptor={len(rodata)}")
rsrc3, rsrc1, rsrc2 = struct.unpack_from("<III", rodata, 44)
props = struct.unpack_from("<H", rodata, 56)[0]
kernarg_size = struct.unpack_from("<I", rodata, 8)[0]
user_sgprs = (rsrc2 >> 1) & 0x1f
if (rsrc3, rsrc1, rsrc2, props, kernarg_size, user_sgprs) != (0x20, 0xE00F0000, 0x88, 0x040a, 28, 4):
    raise SystemExit(f"unexpected gfx1200 descriptor RSRC {rsrc3:#x}/{rsrc1:#x}/{rsrc2:#x}")
if not (props & (1 << 1) and props & (1 << 3) and props & (1 << 10)):
    raise SystemExit(f"descriptor missing dispatch_ptr/kernarg_ptr/wave32 properties: {props:#x}")
print("vadd_ir: gfx1200 HSACO validated; text=640B (symbol=196B), kernarg=28B, "
      "user_sgprs=4, dispatch_ptr+kernarg_ptr+wave32, RSRC=0x20/0xe00f0000/0x88")
PY
cp "$tmp/text.bin" "$REPO/shaders/vadd_ir.bin"
cat > "$REPO/firmware/WHENCE.shader_vadd_ir.txt" <<'EOF'
Blob:     shader_vadd_ir.bin
Symbol:   fw_shader_vadd_ir (src/fw/fw_shader_vadd_ir.c)
Size:     640 bytes extracted from the pinned gfx1200 HSACO .text section
Origin:   project compute test artifact research/artifacts/compute/kernels/vadd_ir.hsaco
License:  project repository license; this is not vendor firmware.
ABI:      vadd_ir.kd descriptor: 28-byte kernarg, three global pointers and u32 n.
          RSRC3/1/2 = 0x20/0xe00f0000/0x88; code symbol length 196 bytes.
Build:    tools/build-vadd-ir.sh
EOF
python3 "$REPO/tools/embed-firmware.py" "$REPO/shaders/vadd_ir.bin" \
  "$REPO/src/fw/fw_shader_vadd_ir.c" fw_shader_vadd_ir
python3 "$REPO/tools/embed-firmware.py" --verify "$REPO/shaders/vadd_ir.bin" \
  "$REPO/src/fw/fw_shader_vadd_ir.c"
