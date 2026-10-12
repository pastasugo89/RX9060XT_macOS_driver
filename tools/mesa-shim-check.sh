#!/usr/bin/env bash
# Verifica da Linux del record canned gfx1200 di RADV (patch Mesa 0010), senza toccare la GPU:
# il drm-shim "noop" di Mesa finge una scheda a partire da amdgpu_devices.c e vulkaninfo la interroga.
# Confronta poi le proprieta' dello shader core con quelle della scheda vera
# (research/artifacts/mesa-radv/vulkaninfo_full.txt, preso con amdgpu).
#
# Prerequisiti: albero Mesa con le patch 0001-0010 in research/ext/mesa-darwin, configurato con
#   meson setup build-shim -Dvulkan-drivers=amd -Dgallium-drivers= -Dplatforms= -Dtools=drm-shim \
#     -Dglx=disabled -Degl=disabled -Dgbm=disabled -Dllvm=disabled -Dvideo-codecs=
#   ninja -C build-shim
# (meson e mako servono nel Python usato: un venv con `pip install meson mako pyyaml packaging` basta.)
#
# Uso: tools/mesa-shim-check.sh [gfx1200|gfx1201]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MESA="${MESA:-$ROOT/research/ext/mesa-darwin}"
B="$MESA/build-shim"
GPU="${1:-gfx1200}"
REF="$ROOT/research/artifacts/mesa-radv/vulkaninfo_full.txt"
SHIM="$B/src/amd/drm-shim/libamdgpu_noop_drm_shim.so"
ICD="$B/src/amd/vulkan/radeon_devenv_icd.x86_64.json"
[ -f "$SHIM" ] && [ -f "$ICD" ] || { echo "build mancante in $B (vedi commento in testa)" >&2; exit 2; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
AMDGPU_GPU_ID="$GPU" LD_PRELOAD="$SHIM" VK_DRIVER_FILES="$ICD" VK_LOADER_LAYERS_DISABLE='*' \
  timeout 60 vulkaninfo 2>/dev/null > "$TMP/shim.txt"
grep -E "deviceName|deviceID" "$TMP/shim.txt" | head -2 | sed 's/^\s*/  /'

# proprieta' che dipendono dall'hardware (topologia, wave, GPR, subgroup), GPU0 soltanto
K='shaderEngineCount|shaderArraysPerEngineCount|computeUnitsPerShaderArray|simdPerComputeUnit|wavefrontsPerSimd|wavefrontSize|sgprsPerSimd|vgprsPerSimd|activeComputeUnitCount|minSubgroupSize|maxSubgroupSize|subgroupSize|maxComputeSharedMemorySize|timestampPeriod|deviceID'
pick() { awk '/GPU id : 0|GPU0:/{p=1} /GPU id : 1|GPU1:/{p=0} p' "$1" | grep -E "$K" | sed 's/^\s*//' | sort -u; }
pick "$REF" > "$TMP/ref.k"; pick "$TMP/shim.txt" > "$TMP/shim.k"
if [ "$GPU" != gfx1200 ]; then echo "(riferimento solo per gfx1200: confronto saltato)"; exit 0; fi
rc=0
if diff "$TMP/ref.k" "$TMP/shim.k" > "$TMP/diff"; then
  echo "OK vulkaninfo: $(wc -l < "$TMP/ref.k") proprieta' uguali alla scheda vera (id, subgroup, LDS, timestamp)"
else
  echo "DIFFERENZE vulkaninfo (< scheda vera, > shim):"; cat "$TMP/diff"; rc=1
fi

# vulkaninfo non stampa la topologia (SE/CU/RB): la si confronta campo per campo tra il record canned
# e il dump preso dalla scheda vera (research/artifacts/mesa-radv/gfx1200_canned_dump.txt).
python3 -I - "$ROOT/research/artifacts/mesa-radv/gfx1200_canned_dump.txt" "$MESA/src/amd/common/amdgpu_devices.c" <<'EOF' || rc=1
import re, sys
dump = open(sys.argv[1]).read()
src = open(sys.argv[2]).read()
rec = src[src.index('.name = "gfx1200"'):src.index('.name = "gfx1201"')]
pat = re.compile(r'\.(\w+)\s*=\s*([^,{}\n/]+?)\s*,')
def kv(t):
    d = {}
    for k, v in pat.findall(t):
        v = v.strip().replace('UINT64_C(', '').rstrip(')')
        try: v = int(v, 0)
        except ValueError: pass
        d.setdefault(k, []).append(v)
    return d
D, R = kv(dump), kv(rec)
# differenze volute: heap (su macOS li fornisce il kext), solo GFX+COMPUTE negli array per IP come nel
# record gfx1201, family scritta come macro, bit 0x10 di ids_flags ignoto all'uapi di questa Mesa
known = {'heap_usage', 'usable_heap_size', 'max_allocation', 'total_heap_size', 'family', 'ids_flags',
         'available_rings', 'capabilities_flags', 'feature', 'hw_ip_version_major', 'hw_ip_version_minor',
         'ib_size_alignment', 'ib_start_alignment', 'ip_discovery_version'}
bad = [k for k in D if k in R and k not in known and D[k] != R[k]]
same = sum(1 for k in D if k in R and k not in known and D[k] == R[k])
for k in bad: print('  DIVERSO', k, 'scheda=', D[k], 'record=', R[k])
for k in ('num_se', 'cu_active_number', 'num_rb_pipes', 'vram_bit_width', 'mall_size'):
    if k in R: print('  %-18s %s' % (k, R[k][0]))
print(('OK record canned: ' if not bad else 'ERRORE record canned: ') + '%d campi uguali al dump, %d diversi' % (same, len(bad)))
sys.exit(1 if bad else 0)
EOF
exit $rc
