#!/usr/bin/env bash
# Offline Linux amdgpu oracle. Default is a read-only host preflight.
# This script never binds/unbinds devices, resets the GPU, or uses host disks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:---check}"
if [[ $# -gt 1 || ( "$MODE" != --check && "$MODE" != --start ) ]]; then
  echo "Uso: $0 [--check|--start]" >&2
  exit 2
fi

GPU=0000:03:00.0
VMROOT=/mnt/vm/images
BUILD_LOCK="$VMROOT/macos-build/.vm.lock"
TEST_LOCK="$VMROOT/macos-gpu-test/.vm.lock"
KERNEL=/boot/vmlinuz-linux-cachyos
MODULES="/lib/modules/$(uname -r)"

failures=0
block() { echo "BLOCCO: $*" >&2; failures=1; }
need_file() { [[ -r "$1" ]] || block "file non leggibile: $1"; }

for bin in qemu-system-x86_64 mkinitcpio flock python3 timeout sha256sum; do
  command -v "$bin" >/dev/null || block "comando mancante: $bin"
done
need_file "$KERNEL"
need_file "$MODULES/modules.dep"
need_file "$ROOT/tools/vm/linux-oracle.init"
[[ -d /sys/bus/pci/devices/$GPU ]] || block "GPU $GPU non presente"
[[ -r /dev/kvm && -w /dev/kvm ]] || block "/dev/kvm non accessibile in lettura/scrittura"
[[ -x /usr/lib/initcpio/busybox ]] || block "busybox initramfs di mkinitcpio non disponibile"
[[ -d /usr/lib/firmware/amdgpu ]] || block "firmware amdgpu locale non disponibile"

if mountpoint -q /mnt/vm; then
  vm_uuid="$(findmnt -n -o UUID --target /mnt/vm 2>/dev/null || true)"
  [[ "$vm_uuid" == be2a9624-d2c1-4778-ac99-fcf9258d3328 ]] || block "UUID /mnt/vm inatteso: ${vm_uuid:-assente}"
else
  block "/mnt/vm non montato: l'output va scritto su storage controllato"
fi

# Existing QEMU activity is a global exclusion: do not compete for KVM, RAM,
# or the GPU while another VM/test owns host resources.
for proc in /proc/[0-9]*; do
  exe="$(readlink -f "$proc/exe" 2>/dev/null || true)"
  if [[ "${exe##*/}" == qemu-system-x86_64 ]]; then
    pid="${proc##*/}"
    echo "QEMU attivo PID $pid (qemu-system-x86_64)" >&2
    block "terminare normalmente le VM concorrenti prima del runner"
  fi
done
for lock in "$BUILD_LOCK" "$TEST_LOCK"; do
  [[ -e "$lock" ]] || { block "lock VM richiesto ma assente: $lock"; }
done
if [[ -e "$BUILD_LOCK" ]]; then
  exec {build_lock_fd}<"$BUILD_LOCK" || block "lock non leggibile: $BUILD_LOCK"
  if [[ -n "${build_lock_fd:-}" ]]; then
    if ! flock -n -x "$build_lock_fd"; then
      block "lock VM occupato: $BUILD_LOCK"
      exec {build_lock_fd}<&-
      unset build_lock_fd
    fi
  fi
fi
if [[ -e "$TEST_LOCK" ]]; then
  exec {test_lock_fd}<"$TEST_LOCK" || block "lock non leggibile: $TEST_LOCK"
  if [[ -n "${test_lock_fd:-}" ]]; then
    if ! flock -n -x "$test_lock_fd"; then
      block "lock VM occupato: $TEST_LOCK"
      exec {test_lock_fd}<&-
      unset test_lock_fd
    fi
  fi
fi

preflight_out="$(python3 "$ROOT/tools/vm/gpu-preflight.py" 2>&1)" || {
  printf '%s\n' "$preflight_out"
  block "preflight GPU/VFIO fallito"
}
printf '%s\n' "$preflight_out"

driver="$(readlink -f "/sys/bus/pci/devices/$GPU/driver" 2>/dev/null || true)"
[[ "${driver##*/}" == vfio-pci ]] || block "$GPU non è già associata a vfio-pci"
group="$(basename "$(readlink -f "/sys/bus/pci/devices/$GPU/iommu_group" 2>/dev/null || true)")"
[[ -n "$group" && -r "/dev/vfio/$group" && -w "/dev/vfio/$group" ]] || block "device VFIO $group non accessibile"
available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
(( available_kib >= 8 * 1024 * 1024 )) || block "RAM disponibile inferiore a 8 GiB"
memlock_kib="$(ulimit -l)"
[[ "$memlock_kib" == unlimited ]] || (( memlock_kib >= 6 * 1024 * 1024 )) || block "memlock corrente ${memlock_kib} KiB, servono 6 GiB; non viene modificato"

if (( failures )); then
  echo "Controllo non superato; nessuna VM avviata e nessun file generato." >&2
  exit 2
fi
echo "Preflight statico superato: kernel $(uname -r), amdgpu/VFIO pronti, nessuna VM concorrente."
echo "Il guest riceverà solo $GPU, senza dischi o rete; l'output sarà un nuovo report sotto research/hw_dump/."
[[ "$MODE" == --check ]] && { echo "--check: nessuna initramfs costruita, GPU aperta o VM avviata."; exit 0; }

OUT="$ROOT/research/hw_dump/linux-oracle-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$OUT"
TMP="$(mktemp -d /tmp/linux-oracle.XXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
cat >"$TMP/mkinitcpio.conf" <<EOF
MODULES=(amdgpu virtio_pci 9p 9pnet_virtio)
BINARIES=()
FILES=($ROOT/tools/vm/linux-oracle.init)
HOOKS=(base modconf)
COMPRESSION=zstd
EOF

if ! mkinitcpio -k "$(uname -r)" -c "$TMP/mkinitcpio.conf" -g "$TMP/initramfs.img" >"$OUT/mkinitcpio.log" 2>&1; then
  cat "$OUT/mkinitcpio.log" >&2
  echo "mkinitcpio failed" >"$OUT/runtime-result.txt"
  exit 1
fi
[[ -s "$TMP/initramfs.img" ]] || { echo "Initramfs non creata." >&2; exit 1; }
sha256sum "$TMP/initramfs.img" >"$OUT/initramfs.sha256"
exec {oracle_lock_fd}>"/tmp/rx9060xt-linux-oracle-${UID}.lock"
flock -n -x "$oracle_lock_fd" || { echo "Runner Linux oracle già attivo." >&2; exit 1; }
WATCHDOG_SECONDS=240
QMP_SOCKET="$OUT/qmp.sock"
QEMU_PID=
shutdown_qemu() {
  if [[ -n "$QEMU_PID" ]] && kill -0 "$QEMU_PID" 2>/dev/null; then
    if ! python3 "$ROOT/tools/vm/qmp.py" --socket "$QMP_SOCKET" quit >/dev/null 2>&1; then
      kill -TERM "$QEMU_PID" 2>/dev/null || true
    fi
    wait "$QEMU_PID" 2>/dev/null || true
    QEMU_PID=
  fi
}
cleanup() {
  shutdown_qemu
  rm -rf -- "$TMP"
}
trap cleanup EXIT
trap 'shutdown_qemu; exit 130' INT
trap 'shutdown_qemu; exit 143' TERM
echo "Avvio guest Linux oracle: risultati in $OUT"
set +e
timeout --foreground --signal=TERM --kill-after=20s "${WATCHDOG_SECONDS}s" qemu-system-x86_64 \
  -no-user-config -nodefaults \
  -machine q35,accel=kvm -cpu host -m 6G -smp 4 \
  -display none -monitor none -serial "file:$OUT/qemu-serial.txt" \
  -qmp "unix:$QMP_SOCKET,server=on,wait=off" \
  -kernel "$KERNEL" -initrd "$TMP/initramfs.img" \
  -append "console=ttyS0,115200n8 rdinit=$ROOT/tools/vm/linux-oracle.init loglevel=7 panic=-1" \
  -device "vfio-pci,host=$GPU" \
  -virtfs "local,path=$OUT,mount_tag=linux_oracle,security_model=none,id=oracle" \
  -no-reboot &
QEMU_PID=$!
wait "$QEMU_PID"
qemu_status=$?
QEMU_PID=
set -e
if (( qemu_status == 124 )); then
  result="watchdog_timeout_${WATCHDOG_SECONDS}s"
elif (( qemu_status == 137 )); then
  result="watchdog_killed_after_timeout"
elif grep -q 'linux-oracle guest end; poweroff' "$OUT/guest-serial-capture.txt" 2>/dev/null; then
  result="guest_poweroff_qemu_exit_${qemu_status}"
else
  result="qemu_exit_${qemu_status}_without_guest_completion"
fi
printf '%s\n' "$result" >"$OUT/runtime-result.txt"
echo "Linux oracle: $result (QEMU exit $qemu_status)"
exit "$qemu_status"
