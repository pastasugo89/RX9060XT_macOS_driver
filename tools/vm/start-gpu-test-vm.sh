#!/usr/bin/env bash
# Prepared, bounded test configuration. Never changes host PCI driver bindings.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VM=/mnt/vm/images/macos-gpu-test
BASE=/mnt/vm/images/macos-build
MODE="${1:---check}"
[[ "$MODE" == --check || "$MODE" == --probe || "$MODE" == --start || "$MODE" == --stop-watchdog ]] || {
  echo 'Uso: start-gpu-test-vm.sh [--check|--probe|--start|--stop-watchdog]' >&2; exit 1;
}
# --stop-watchdog: ends ONLY the host safety watchdog (explicit, by its PID file). It does not stop the VM; without the watchdog
# a running VM has no host-side stop, so stop the VM too if you stop this.
if [[ "$MODE" == --stop-watchdog ]]; then
  wdpid_file=/mnt/vm/images/macos-gpu-test/diagnostics/gpu-safety-watchdog.pid
  if [[ -s "$wdpid_file" ]] && wd_pid="$(cat "$wdpid_file")" && [[ "$wd_pid" =~ ^[0-9]+$ ]] \
     && grep -q 'gpu-safety-watchdog' "/proc/$wd_pid/cmdline" 2>/dev/null; then
    kill -TERM "$wd_pid"
    echo "Watchdog di sicurezza $wd_pid: SIGTERM inviato. La VM, se e' in esecuzione, NON e' stata fermata."
  else
    echo 'Nessun watchdog di sicurezza attivo (PID file assente o stale).'
    rm -f "$wdpid_file"
  fi
  exit 0
fi
mountpoint -q /mnt/vm
[[ "$(findmnt -n -o UUID --target /mnt/vm)" == be2a9624-d2c1-4778-ac99-fcf9258d3328 ]]
for file in test-plan.json OpenCore-Boot.sh mac_hdd_ng.img OVMF_CODE_4M.fd OVMF_VARS-1920x1080.fd OpenCore/OpenCore.stage1.qcow2; do
  [[ -s "$VM/$file" ]] || { echo "Manca $VM/$file" >&2; exit 1; }
done
blocked=0
python3 "$ROOT/tools/vm/gpu-preflight.py" || blocked=1
exec 8<"$BASE/.vm.lock"
if ! flock -n -x 8; then
  echo 'BLOCCO: arrestare regolarmente la VM di compilazione prima del test.' >&2
  blocked=1
fi
python3 - "$VM" <<'PY'
import hashlib, json, os, pathlib, subprocess, sys
vm = pathlib.Path(sys.argv[1])
plan = json.loads((vm / 'test-plan.json').read_text())
assert plan['stage'] in (1, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17) and isinstance(plan['interrupts'], bool)
assert not plan.get('smu_full', False) or plan['stage'] == 9
assert not plan.get('native_s1b', False) or plan['stage'] == 17
assert ('navi48-smu-full=1' in plan['boot_args'].split()) == plan.get('smu_full', False)
assert ('navi48-native=1' in plan['boot_args'].split()) == plan.get('native_s1b', False)
assert ('navi48-vadd-ir=1' in plan['boot_args'].split()) == plan.get('vadd_ir', False)
assert ('navi48-gopsnap=1' in plan['boot_args'].split()) == plan.get('gopsnap', False)
ba = plan['boot_args'].split()
# Metal boot-args (same keys and readers as prepare-gpu-test-stage.py: Navi48MetalNub.cpp:214, Navi48NativeClient.cpp:64,
# native_disp.cpp:573, Navi48Accel.cpp:86): each must match the plan's flag, and the phase rules must hold.
assert ('navi48-metal=1' in ba) == plan.get('metal', False)
assert ('navi48-metal-ws=1' in ba) == plan.get('metal_ws', False)
assert ('navi48-metal-disp=1' in ba) == plan.get('metal_disp', False)
assert ('navi48-aux=0' in ba) == plan.get('aux_kill', False)
assert ('navi48-agdc=1' in ba) == plan.get('agdc', False), 'navi48-agdc and plan agdc flag disagree'
# rdna4-vbl (RDNA4FB emulated VBL, framebuffer.cpp:2075): must match the plan, see prepare-gpu-test-stage.py --rdna4-vbl.
assert ('rdna4-vbl=1' in ba) == plan.get('rdna4_vbl', False), 'rdna4-vbl and plan rdna4_vbl flag disagree'
# navi48-multisession / navi48-apps / npci (prepare-gpu-test-stage.py --multisession --apps --npci): same rule, fail closed.
assert ('navi48-multisession=1' in ba) == plan.get('multisession', False), 'navi48-multisession and plan multisession disagree'
assert ('navi48-apps=1' in ba) == plan.get('apps', False), 'navi48-apps and plan apps disagree'
assert ('npci=0x2000' in ba) == plan.get('npci', False), 'npci=0x2000 and plan npci disagree'
assert not plan.get('apps', False) or plan.get('multisession', False), 'navi48-apps needs navi48-multisession (native_g4_pure.h)'
if plan.get('metal'):
    assert plan['stage'] == 17 and plan.get('native_s1b') and 'navi48-native=1' in ba, 'navi48-metal needs stage17 with the S1b gate'
    assert not plan.get('aux_kill') and 'navi48-aux=1' in ba, 'Metal boot: the aux kext switch must be explicitly on'
if plan.get('metal_ws') or plan.get('metal_disp'):
    assert plan.get('metal') and plan.get('primary_display'), 'metal-ws and metal-disp follow P0 and need the RX 9060 XT as the only display'
ADMITTED = {'navi48-stage', 'navi48-interrupts', 'navi48-smu-full', 'navi48-native', 'navi48-vadd-ir', 'navi48-gopsnap',
            'navi48-metal', 'navi48-metal-ws', 'navi48-metal-disp', 'navi48-aux', 'navi48-agdc',
            'navi48-multisession', 'navi48-apps'}
navi = [f for f in ba if f.startswith('navi48-')]
assert all(f.split('=')[0] in ADMITTED and f.count('=') == 1 for f in navi), f'boot-arg not admitted: {navi}'
assert len({f.split('=')[0] for f in navi}) == len(navi), f'duplicate navi48 key: {navi}'
# The EFI's UEFI Output Resolution (Max with --primary) and the launcher's display layout (N4X_GPU_PRIMARY) must describe the same run.
primary_env = os.environ.get('N4X_GPU_PRIMARY', '0') == '1'
assert primary_env == bool(plan.get('primary_display', False)), 'EFI e N4X_GPU_PRIMARY non coerenti: rieseguire prepare-gpu-test-stage.py con o senza --primary'
for flag in ('navi48bringup=1', f"navi48-stage={plan['stage']}", f"navi48-interrupts={int(plan['interrupts'])}"):
    assert flag in ba
assert hashlib.sha256((vm / plan['efi']).read_bytes()).hexdigest() == plan['efi_sha256'], 'EFI diversa dal piano verificato'
backing = pathlib.Path(plan['snapshot']) / 'mac_hdd_ng.img'
info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(vm / 'mac_hdd_ng.img')]))
assert pathlib.Path(info['full-backing-filename']) == backing
assert backing.is_file()
print(f"Overlay, EFI e piano stage{plan['stage']} verificati.")
PY
(( blocked == 0 )) || exit 2
# GPU option ROM options (launcher): N4X_GPU_ROMBAR=1 exposes the physical ROM BAR (no file, no PCIR check here); N4X_GPU_ROMFILE
# is a file override and must be this card's VBIOS. The two are exclusive; unset keeps rombar=0.
case "${N4X_GPU_ROMBAR:-0}" in 0|1) ;; *) echo 'N4X_GPU_ROMBAR accetta solo 0 o 1.' >&2; exit 1 ;; esac
if [[ -n "${N4X_GPU_ROMFILE:-}" && "${N4X_GPU_ROMBAR:-0}" == 1 ]]; then
  echo 'N4X_GPU_ROMFILE e N4X_GPU_ROMBAR=1 non possono essere impostate insieme.' >&2; exit 1
fi
if [[ "${N4X_GPU_ROMBAR:-0}" == 1 ]]; then echo 'ROM fisica: rombar=1 (QEMU la legge dalla scheda via VFIO).'; fi
# N4X_GPU_PRIMARY=1: the RX 9060 XT is the only display (no emulated VGA, no GTK window; the launcher applies it). It needs the
# physical ROM (N4X_GPU_ROMBAR=1); a file override is not allowed with it.
case "${N4X_GPU_PRIMARY:-0}" in 0|1) ;; *) echo 'N4X_GPU_PRIMARY accetta solo 0 o 1.' >&2; exit 1 ;; esac
# N4X_GPU_ROOTPORT (opt-in, 2026-10-21): GPU behind a pcie-root-port; the launcher applies it. Unset: root bus, unchanged.
case "${N4X_GPU_ROOTPORT:-0}" in 0|1) ;; *) echo 'N4X_GPU_ROOTPORT accetta solo 0 o 1.' >&2; exit 1 ;; esac
if [[ "${N4X_GPU_PRIMARY:-0}" == 1 ]]; then
  [[ "${N4X_GPU_ROMBAR:-0}" == 1 && -z "${N4X_GPU_ROMFILE:-}" ]] || { echo 'N4X_GPU_PRIMARY=1 richiede N4X_GPU_ROMBAR=1 e non N4X_GPU_ROMFILE.' >&2; exit 1; }
  echo 'Display primario: la RX 9060 XT è l'"'"'unico display (nessuna VGA emulata, nessuna finestra GTK).'
fi
# Optional GPU option ROM for the GOP observation (launcher: N4X_GPU_ROMFILE). Must be this card's VBIOS: PCIR 1002:7590, part 113-P816G493-S05.
if [[ -n "${N4X_GPU_ROMFILE:-}" ]]; then
  python3 - "$N4X_GPU_ROMFILE" <<'PY' || { echo 'N4X_GPU_ROMFILE rifiutata: non è il VBIOS della RX 9060 XT.' >&2; exit 1; }
import hashlib, pathlib, re, struct, sys
rom = pathlib.Path(sys.argv[1]).read_bytes()
pcir = rom.find(b'PCIR')
assert rom[:2] == b'\x55\xaa' and pcir >= 0, 'not an option ROM'
vendor, device = struct.unpack_from('<HH', rom, pcir + 4)
assert (vendor, device) == (0x1002, 0x7590), f'PCIR {vendor:04x}:{device:04x}'
assert b'113-P816G493-S05' in rom, 'part number 113-P816G493-S05 not found'
print(f'ROM esposta: {sys.argv[1]} sha256 {hashlib.sha256(rom).hexdigest()} ({len(rom)} byte, 1002:7590, 113-P816G493-S05)')
PY
fi
if [[ "$MODE" == --check ]]; then
  echo 'Controlli preliminari superati; nessuna VM avviata.'
  exit 0
fi
[[ -r /dev/kvm && -w /dev/kvm ]]
[[ "$(cat /sys/module/kvm/parameters/ignore_msrs)" == Y ]]
[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]
memlock="$(ulimit -Sl)"
if [[ "$memlock" != unlimited ]] && (( memlock < 14 * 1024 * 1024 )); then
  echo "MEMLOCK troppo basso ($memlock KiB): aumentarlo solo per il processo di test prima dell'avvio." >&2
  exit 1
fi
for address in 0000:03:00.0 0000:03:00.1; do
  group="$(basename "$(readlink -f "/sys/bus/pci/devices/$address/iommu_group")")"
  [[ -r "/dev/vfio/$group" && -w "/dev/vfio/$group" ]] || {
    echo "VFIO non accessibile per il gruppo $group." >&2; exit 1;
  }
done
available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
(( available >= 14 * 1024 * 1024 )) || { echo 'Servono 14 GiB disponibili.' >&2; exit 1; }
exec 9>"$VM/.vm.lock"
flock -n 9 || { echo 'VM di test già in esecuzione.' >&2; exit 1; }
cd "$VM"
if [[ "$MODE" == --probe ]]; then
  export N48_START_PAUSED=1
  echo 'Apertura VFIO con QEMU in pausa: nessun codice guest eseguito. Interrogare QMP, poi terminare QEMU.'
else
  echo 'Avvio dello stage preparato, con lo stato IRQ fissato dal piano e senza stack Metal. Log in diagnostics/serial.log.'
fi
# Digest of the EFI as verified at launch (the live qcow2 changes while QEMU runs). deploy-metal-stack.sh --arm-check compares
# this record with test-plan.json while the VM is up. Written only for --start.
if [[ "$MODE" == --start ]]; then
  # n4x safety: the host watchdog must be running before QEMU starts, and the VM does not start without it (fail closed).
  # Lock 9 is held here, so no QEMU is running: the old QMP socket and serial log are stale and are set aside.
  diag="$VM/diagnostics"; mkdir -p "$diag"
  if [[ -e "$diag/serial.log" ]]; then mv "$diag/serial.log" "$diag/serial.log.$(date +%Y%m%dT%H%M%S)"; fi
  rm -f "$VM/qmp.sock" "$diag/gpu-safety-watchdog.pid"
  wd_log="$diag/gpu-safety-watchdog.log"
  wd_args=(--serial "$diag/serial.log" --qmp "$VM/qmp.sock" --log "$wd_log" --pidfile "$diag/gpu-safety-watchdog.pid"
           --events-dir "$ROOT/research/hw_dump/gpu_safety_events"
           --warn-c "${N4X_SAFETY_WARN_C:-75}" --trip-c "${N4X_SAFETY_TRIP_C:-80}" --max-runtime "${N4X_SAFETY_MAX_S:-3600}")
  if [[ -n "${N4X_SAFETY_DRY_RUN:-}" ]]; then
    echo 'ATTENZIONE: N4X_SAFETY_DRY_RUN impostato: il watchdog registra lo stop ma NON ferma la VM.' >&2
    wd_args+=(--dry-run)
  fi
  # stdout is a copy of the log file the watchdog writes itself: only stderr (tracebacks) goes to the log here.
  setsid -f python3 -I "$ROOT/tools/vm/gpu-safety-watchdog.py" "${wd_args[@]}" </dev/null >/dev/null 2>>"$wd_log"
  for _ in $(seq 1 100); do
    grep -q 'READY pid=' "$wd_log" 2>/dev/null && break
    sleep 0.1
  done
  if ! grep -q 'READY pid=' "$wd_log" 2>/dev/null; then
    if [[ -s "$diag/gpu-safety-watchdog.pid" ]]; then kill -TERM "$(cat "$diag/gpu-safety-watchdog.pid")" 2>/dev/null || true; fi
    echo 'Watchdog di sicurezza non avviato: VM NON avviata (vedi gpu-safety-watchdog.log).' >&2
    exit 1
  fi
  echo "Watchdog di sicurezza attivo (PID $(cat "$diag/gpu-safety-watchdog.pid")). Log: $wd_log. Stop solo esplicito: --stop-watchdog."
  printf '%s  %s\n' "$(sha256sum OpenCore/OpenCore.stage1.qcow2 | cut -d' ' -f1)" "$(date -Is)" > .launch-efi.sha256
fi
exec bash ./OpenCore-Boot.sh
