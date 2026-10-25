#!/usr/bin/env bash
# Test della EFI OpenCore di research/ext/ocboot-baremetal sul processore reale dell'host (Ryzen 7 7700) in QEMU/KVM.
# Non tocca hardware reale: la "chiavetta" e' un'immagine GPT+FAT32 (baremetal-efi-test/master-disk.img, costruita con mtools).
#   --check        verifica sorgenti, immagine master e OVMF; non avvia nulla.
#   --start-a      Prova A: nessuna GPU in passthrough, display VGA std (VNC locale 127.0.0.1:5901).
#   --start-b      Prova B: RX 9060 XT (0000:03:00.0 + audio .1) in vfio-pci come unico display (-vga none).
#   --shot NAME    screendump QMP della VM in corso, convertito in PNG in research/ext/ocboot-baremetal/qemu-test/.
#   --quit         quit QMP (nessun disco da proteggere: e' un test di ripristino).
# Ogni avvio usa una copia (reflink) della master e variabili OVMF nuove: le run non si contaminano a vicenda.
# Una sola VM alla volta. Il launcher non modifica gli script delle VM esistenti (usa solo i loro file OVMF).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T=/mnt/vm/images/baremetal-efi-test
OVMF_DIR=/mnt/vm/images/macos-gpu-test          # stessi file OVMF degli script tools/vm/ (CODE 4M, VARS 1920x1080)
OVMF_CODE="$OVMF_DIR/OVMF_CODE_4M.fd"
OVMF_VARS_SRC="$OVMF_DIR/OVMF_VARS-1920x1080.fd"
MASTER="$T/master-disk.img"
EFI_SRC="$ROOT/research/ext/ocboot-baremetal/EFI"
SUMS="$ROOT/research/ext/ocboot-baremetal/SHA256SUMS-EFI.txt"
INST=/mnt/vm/installers/tahoe-25G83
QMP_SOCK="$T/qmp.sock"
SHOTS="$ROOT/research/ext/ocboot-baremetal/qemu-test"
QMP_PY="$ROOT/tools/vm/qmp.py"
VNC_DISPLAY="127.0.0.1:1"                        # VNC locale: porta 5901
GPU_BDF=0000:03:00.0
GPU_AUDIO_BDF=0000:03:00.1
MODE="${1:---check}"

case "$MODE" in
  --check|--start-a|--start-b|--quit) ;;
  --shot) [[ -n "${2:-}" && "$2" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'Uso: --shot NOME' >&2; exit 1; } ;;
  *) echo 'Uso: test-baremetal-efi.sh [--check|--start-a|--start-b|--shot NOME|--quit]' >&2; exit 1 ;;
esac

# Il nome del processo (comm) e' troncato a 15 caratteri: si cerca l'eseguibile all'inizio della riga di comando.
qemu_running() { pgrep -f '(^|/)qemu-system-x86_64 ' >/dev/null 2>&1; }

check_sources() {
  local ok=1
  # 1) EFI sorgente contro SHA256SUMS-EFI.txt (percorsi relativi alla cartella ocboot-baremetal)
  ( cd "$ROOT/research/ext/ocboot-baremetal" && sha256sum -c --quiet SHA256SUMS-EFI.txt ) \
    && echo 'EFI sorgente: file conformi a SHA256SUMS-EFI.txt' || { echo 'EFI sorgente: checksum NON conformi' >&2; ok=0; }
  # 2) BaseSystem e chunklist dell'installer (sha1 da media-manifest.json: 2a6d9bc3...)
  local s1; s1="$(sha1sum "$INST/BaseSystem.dmg" | cut -d' ' -f1)"
  [[ "$s1" == 2a6d9bc3ad569778e86706ad65b51ef0da980ab0 ]] && echo 'BaseSystem.dmg sha1 = manifest' || { echo "BaseSystem.dmg sha1 errato: $s1" >&2; ok=0; }
  local ck; ck="$(head -c 4 "$INST/BaseSystem.chunklist")"
  [[ "$ck" == CNKL ]] && echo 'BaseSystem.chunklist: magic CNKL' || { echo 'chunklist senza magic CNKL' >&2; ok=0; }
  # 3) immagine master (GPT con partizione ESP) e OVMF
  [[ -s "$MASTER" ]] && echo "immagine master: $(stat -c %s "$MASTER") byte" || { echo "manca $MASTER" >&2; ok=0; }
  if [[ -s "$MASTER" ]]; then
    sfdisk -d "$MASTER" 2>/dev/null | grep -q 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B' \
      && echo 'GPT: partizione ESP presente' || { echo 'GPT: ESP non trovata' >&2; ok=0; }
  fi
  for f in "$OVMF_CODE" "$OVMF_VARS_SRC"; do
    [[ -s "$f" ]] && echo "OVMF: $f" || { echo "manca $f" >&2; ok=0; }
  done
  [[ -r /dev/kvm && -w /dev/kvm ]] && echo '/dev/kvm: accessibile' || { echo '/dev/kvm non accessibile' >&2; ok=0; }
  [[ "$(cat /sys/module/kvm/parameters/ignore_msrs 2>/dev/null)" == Y ]] && echo 'kvm ignore_msrs=Y' \
    || { echo 'kvm ignore_msrs non Y (richiesto dagli script VM esistenti)' >&2; ok=0; }
  (( ok == 1 ))
}

check_gpu_for_b() {
  local ok=1 addr group
  for addr in "$GPU_BDF" "$GPU_AUDIO_BDF"; do
    local drv="" group=""
    drv="$(readlink -f "/sys/bus/pci/devices/$addr/driver" 2>/dev/null || true)"; drv="${drv##*/}"
    [[ "$drv" == vfio-pci ]] && echo "$addr: vfio-pci" || { echo "$addr non e' in vfio-pci (driver: ${drv:-nessuno})" >&2; ok=0; }
    group="$(readlink -f "/sys/bus/pci/devices/$addr/iommu_group" 2>/dev/null || true)"; group="${group##*/}"
    [[ -n "$group" && -r "/dev/vfio/$group" && -w "/dev/vfio/$group" ]] \
      && echo "$addr: gruppo IOMMU $group accessibile" || { echo "$addr: /dev/vfio/$group non accessibile" >&2; ok=0; }
  done
  local memlock; memlock="$(ulimit -Sl)"
  if [[ "$memlock" == unlimited ]] || (( memlock >= 10 * 1024 * 1024 )); then echo "MEMLOCK: $memlock KiB"
  else echo "MEMLOCK troppo basso ($memlock KiB) per il passthrough di 8 GiB" >&2; ok=0; fi
  (( ok == 1 ))
}

# Per-run directory: serial, debugcon, OVMF vars copy, reflinked USB image.
prepare_run() {
  local tag="$1" stamp run
  stamp="$(date +%Y%m%dT%H%M%S)"
  run="$T/runs/$tag-$stamp"
  mkdir -p "$run"
  cp --reflink=auto "$OVMF_VARS_SRC" "$run/OVMF_VARS.fd"
  # N4X_STICK_SRC: immagine alternativa per esperimenti (es. config con un solo quirk cambiato); default: la master.
  local src="${N4X_STICK_SRC:-$MASTER}"
  [[ -s "$src" ]] || { echo "Immagine chiavetta non trovata: $src" >&2; exit 1; }
  cp --reflink=auto "$src" "$run/usb-stick.img"
  echo "$src" > "$run/stick-source.txt"
  echo "$run"
}

start_vm() {
  local tag="$1"
  check_sources || { echo 'Controlli sorgenti falliti: VM NON avviata.' >&2; exit 1; }
  if qemu_running; then echo 'Una VM QEMU e gia in esecuzione: VM NON avviata.' >&2; exit 1; fi
  mkdir -p "$T/runs"
  exec 9>"$T/.vm.lock"
  flock -n 9 || { echo 'Lock di test occupato: VM NON avviata.' >&2; exit 1; }
  local run; run="$(prepare_run "$tag")"
  rm -f "$QMP_SOCK"

  # Comune: 8 vCPU (4 core x 2 thread, limite del coordinatore; il Ryzen 7 7700 reale e' 8c/16t), 8 GiB, q35, -cpu host,+topoext,
  # nessun device Apple/SMC/NIC emulato. Override: N4X_SMP, N4X_CPU_OPT, N4X_MEM (solo esperimenti documentati in QEMU_TEST.md).
  local args=(
    -name "baremetal-efi-test-$tag,process=baremetal-efi-test-$tag"
    -machine q35,accel=kvm
    -cpu "${N4X_CPU_OPT:-host,kvm=on,+invtsc,+topoext}"
    -smp "${N4X_SMP:-8,cores=4,threads=2,sockets=1}"
    -m "${N4X_MEM:-8G}"
    -nodefaults -no-user-config
    -no-reboot
    -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE"
    -drive "if=pflash,format=raw,file=$run/OVMF_VARS.fd"
    -device qemu-xhci,id=xhci
    -device usb-kbd,bus=xhci.0
    -device usb-tablet,bus=xhci.0
    -drive "id=usbstick,if=none,format=raw,file=$run/usb-stick.img"
    -device usb-storage,bus=xhci.0,drive=usbstick
    -serial "file:$run/serial.log"
    -debugcon "file:$run/debugcon.log" -global isa-debugcon.iobase=0x402
    -qmp "unix:$QMP_SOCK,server=on,wait=off"
  )
  if [[ "$tag" == A ]]; then
    args+=(-vga std -display "vnc=$VNC_DISPLAY")
    echo 'Prova A: nessuna GPU in passthrough, VGA std (GOP di OVMF/QEMU), VNC 127.0.0.1:5901.'
  else
    echo 'Prova B: RX 9060 XT come unico display. Nessuna VGA emulata, nessuna finestra. Nessun kext GPU nostro nel bundle.'
    echo 'Il display della scheda non e visibile da QMP: verifica solo tramite seriale/debugcon e log OpenCore.'
    args+=(-vga none -display none
      -device "vfio-pci,host=$GPU_BDF,rombar=1"
      -device "vfio-pci,host=$GPU_AUDIO_BDF")
  fi
  echo "Run: $run"
  cd "$run"
  setsid -f qemu-system-x86_64 "${args[@]}" </dev/null >"$run/qemu.stdout" 2>"$run/qemu.stderr"
  for _ in $(seq 1 100); do [[ -S "$QMP_SOCK" ]] && break; sleep 0.1; done
  sleep 1
  python3 -I "$QMP_PY" --socket "$QMP_SOCK" query-status || true
  echo "$run" > "$T/.current-run"
}

case "$MODE" in
  --check)
    check_sources && echo 'Controlli sorgenti e OVMF superati. Nessuna VM avviata.'
    echo "Prova B (GPU): controllo passthrough"
    check_gpu_for_b || echo '(Prova B non ancora pronta: vedi messaggi sopra)'
    ;;
  --start-a) start_vm A ;;
  --start-b)
    check_gpu_for_b || { echo 'Prerequisiti GPU non soddisfatti: VM NON avviata.' >&2; exit 1; }
    start_vm B ;;
  --shot)
    mkdir -p "$SHOTS"
    ppm="$T/shot-$2.ppm"
    python3 -I "$QMP_PY" --socket "$QMP_SOCK" screendump "{\"filename\": \"$ppm\"}" >/dev/null
    magick "$ppm" "$SHOTS/$2.png"
    rm -f "$ppm"
    echo "Screenshot: $SHOTS/$2.png"
    ;;
  --quit)
    python3 -I "$QMP_PY" --socket "$QMP_SOCK" quit >/dev/null || true
    for _ in $(seq 1 50); do qemu_running || break; sleep 0.2; done
    qemu_running && echo 'QEMU ancora in esecuzione dopo quit.' >&2 || echo 'QEMU terminato.'
    ;;
esac
