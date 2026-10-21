#!/usr/bin/env bash
set -euo pipefail
VM_DIR=/mnt/vm/images/macos-build
mountpoint -q /mnt/vm || { echo '/mnt/vm non è montato: fermarsi.' >&2; exit 1; }
[[ "$(findmnt -n -o UUID --target /mnt/vm)" == be2a9624-d2c1-4778-ac99-fcf9258d3328 ]] || {
  echo 'Volume VM inatteso: fermarsi.' >&2; exit 1;
}
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo 'KVM non accessibile al tuo utente.' >&2; exit 1; }
[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || { echo 'Avvia dal Terminale del desktop Linux.' >&2; exit 1; }
for file in OpenCore-Boot.sh mac_hdd_ng.img BaseSystem.img OVMF_CODE_4M.fd OVMF_VARS-1920x1080.fd OpenCore/OpenCore.tahoe.qcow2; do
  [[ -s "$VM_DIR/$file" ]] || { echo "Manca $file: esegui prima prepare-build-vm.sh." >&2; exit 1; }
done
[[ -s /mnt/vm/installers/tahoe-25G83/Tahoe25G83.iso ]] || { echo 'Manca il supporto locale Tahoe 25G83.' >&2; exit 1; }
if grep -Fq 'OpenCore/OpenCore.verbose.qcow2' "$VM_DIR/OpenCore-Boot.sh"; then
  [[ -s "$VM_DIR/OpenCore/OpenCore.verbose.qcow2" ]] || { echo 'Manca la copia EFI diagnostica.' >&2; exit 1; }
elif ! grep -Fq 'OpenCore/OpenCore.tahoe.qcow2' "$VM_DIR/OpenCore-Boot.sh"; then
  echo 'La configurazione di avvio non è ancora aggiornata a Tahoe: esegui prepare-build-vm.sh.' >&2; exit 1;
fi
if [[ "$(cat /sys/module/kvm/parameters/ignore_msrs)" != Y ]]; then
  echo 'Prima abilita il parametro KVM per questa sessione, nel tuo terminale:' >&2
  echo "printf '1\\n' | sudo tee /sys/module/kvm/parameters/ignore_msrs" >&2
  exit 1
fi
MEM_AVAILABLE_KIB="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
if (( MEM_AVAILABLE_KIB < 14 * 1024 * 1024 )); then
  echo 'Servono almeno 14 GiB di RAM disponibile per avviare questa configurazione da 12 GiB.' >&2
  echo 'Chiudi applicazioni o arresta regolarmente il server Minecraft e riprova.' >&2
  exit 1
fi
cd "$VM_DIR"
exec 9>.vm.lock
flock -n 9 || { echo 'La VM o la preparazione è già in esecuzione.' >&2; exit 1; }
echo 'Avvio QEMU. Lascia aperto questo terminale fino allo spegnimento di macOS.'
exec bash ./OpenCore-Boot.sh
