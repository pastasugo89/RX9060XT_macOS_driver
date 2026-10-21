#!/usr/bin/env bash
# Prepare the build VM without touching host disks, VFIO, or system settings.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VM_DIR=/mnt/vm/images/macos-build
UPSTREAM="$ROOT/research/ext/OSX-KVM"
FILES_ONLY=0
case "${1:-}" in
  '') ;;
  --files-only) FILES_ONLY=1 ;;
  *) echo 'Uso: bash tools/vm/prepare-build-vm.sh [--files-only]' >&2; exit 1 ;;
esac

mountpoint -q /mnt/vm || { echo '/mnt/vm non è montato: fermarsi.' >&2; exit 1; }
VOLUME_UUID="$(findmnt -n -o UUID --target /mnt/vm)"
[[ "$VOLUME_UUID" == be2a9624-d2c1-4778-ac99-fcf9258d3328 ]] || {
  echo 'Il volume montato non è quello preparato per la VM.' >&2; exit 1;
}
for cmd in python3 qemu-img flock; do
  command -v "$cmd" >/dev/null || { echo "Manca $cmd" >&2; exit 1; }
done
[[ -f "$UPSTREAM/OpenCore-Boot.sh" ]] || { echo 'OSX-KVM non trovato.' >&2; exit 1; }
mkdir -p "$VM_DIR/OpenCore"
exec 9>"$VM_DIR/.vm.lock"
flock -n 9 || { echo 'La VM o la preparazione è già in esecuzione.' >&2; exit 1; }

python3 - "$UPSTREAM" "$VM_DIR" <<'PY'
from pathlib import Path
import shutil
import sys
upstream, vm = map(Path, sys.argv[1:])
for relative in ('OVMF_CODE_4M.fd', 'OVMF_VARS-1920x1080.fd', 'OpenCore/OpenCore.qcow2'):
    destination = vm / relative
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise SystemExit(f'Percorso inatteso: {destination}')
        continue
    with (upstream / relative).open('rb') as source, destination.open('xb') as target:
        shutil.copyfileobj(source, target)
boot = vm / 'OpenCore-Boot.sh'
if not boot.exists():
    text = (upstream / 'OpenCore-Boot.sh').read_text()
    changes = {
        'ALLOCATED_RAM="4096"': 'ALLOCATED_RAM="12288"',
        'CPU_CORES="2"': 'CPU_CORES="4"',
        'CPU_THREADS="4"': 'CPU_THREADS="8"',
        '-cpu Skylake-Client,-hle,-rtm,': '-cpu Skylake-Client,-pcid,-hle,-rtm,',
        'id=OpenCoreBoot,if=none,snapshot=on,': 'id=OpenCoreBoot,if=none,',
        'hostfwd=tcp::2222-:22': 'hostfwd=tcp:127.0.0.1:2222-:22',
        '  -machine q35\n': '  -machine q35\n  -display gtk\n',
    }
    for old, new in changes.items():
        if text.count(old) != 1:
            raise SystemExit(f'Script upstream diverso dal previsto: {old}')
        text = text.replace(old, new)
    with boot.open('x') as output:
        output.write(text)
    boot.chmod(0o755)
else:
    print('Conservo lo script di avvio già esistente.')
PY

if [[ ! -e "$VM_DIR/mac_hdd_ng.img" ]]; then
  qemu-img create -f qcow2 "$VM_DIR/mac_hdd_ng.img" 128G
else
  python3 - "$VM_DIR/mac_hdd_ng.img" <<'PY'
import json, subprocess, sys
info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', sys.argv[1]], text=True))
if info['format'] != 'qcow2':
    raise SystemExit('Il disco esistente non è qcow2: fermarsi.')
print('Conservo il disco virtuale esistente, senza inizializzarlo.')
PY
fi
bash -n "$VM_DIR/OpenCore-Boot.sh"
if (( FILES_ONLY )); then
  echo "File di base predisposti in $VM_DIR. Eseguire la preparazione completa per verificare i supporti Tahoe locali."
  exit 0
fi

MEDIA_DIR=/mnt/vm/installers/tahoe-25G83
for file in "$VM_DIR/BaseSystem.img" "$VM_DIR/OpenCore/OpenCore.tahoe.qcow2" "$MEDIA_DIR/Tahoe25G83.iso" "$MEDIA_DIR/media-manifest.json"; do
  [[ -s "$file" ]] || { echo "Supporto Tahoe locale mancante: $file. Nessun altro macOS verrà scaricato." >&2; exit 1; }
done
python3 - "$VM_DIR" "$MEDIA_DIR" <<'PY'
import json
import sys
from pathlib import Path
vm, media = map(Path, sys.argv[1:])
manifest = json.loads((media / 'media-manifest.json').read_text())
assert manifest['product_version'] == '26.6.2' and manifest['build'] == '25G83'
assert (vm / 'BaseSystem.img').stat().st_size == manifest['basesystem_raw_size']
assert (media / 'Tahoe25G83.iso').stat().st_size == manifest['iso_size']
boot = vm / 'OpenCore-Boot.sh'
text = boot.read_text()
if '-cpu Skylake-Client,-hle,-rtm,' in text:
    text = text.replace('-cpu Skylake-Client,-hle,-rtm,', '-cpu Skylake-Client,-pcid,-hle,-rtm,')
old = 'file="$REPO_PATH/OpenCore/OpenCore.qcow2"'
new = 'file="$REPO_PATH/OpenCore/OpenCore.tahoe.qcow2"'
if old in text:
    assert text.count(old) == 1
    text = text.replace(old, new)
else:
    assert sum(text.count(path) for path in (new, 'file="$REPO_PATH/OpenCore/OpenCore.verbose.qcow2"')) == 1
if 'id=OfflineInstaller,' not in text:
    anchor = '  -monitor stdio\n'
    assert text.count(anchor) == 1
    extra = ('  -drive id=OfflineInstaller,if=none,format=raw,readonly=on,file="/mnt/vm/installers/tahoe-25G83/Tahoe25G83.iso"\n'
             '  -device ide-cd,bus=sata.5,drive=OfflineInstaller\n')
    text = text.replace(anchor, extra + anchor)
boot.write_text(text)
PY
bash -n "$VM_DIR/OpenCore-Boot.sh"
qemu-img info -f raw "$VM_DIR/BaseSystem.img" >/dev/null
echo
echo 'Tahoe 26.6.2 (25G83) locale: nessun download di Sequoia.'
echo 'Preparazione completata: 12 GiB RAM, 8 vCPU, disco virtuale 128 GiB, SMBIOS MacPro7,1.'
echo 'Avvio: bash tools/vm/start-build-vm.sh'
