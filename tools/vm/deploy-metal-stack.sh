#!/usr/bin/env bash
# deploy-metal-stack.sh - installa nel guest della VM di TEST gli artefatti userspace del deploy Metal (Navi48Metal).
# Piano: research/reports/metal_deploy_plan.md (sez. 4.2-4.6 e 8). Artefatti: /mnt/vm/builds/metal-stack-20261021/ (SHA256SUMS).
#
# Modalita' (una sola per chiamata; default --check):
#   --check      solo host: sha256 del pacchetto, file richiesti, architettura Mach-O, sintassi, lock della VM. Nessun SSH.
#   --dry-run    come --check, poi stampa ESATTAMENTE i comandi che --deploy eseguirebbe nel guest. Nessun SSH, nessuna scrittura.
#   --deploy     copia il pacchetto nel guest (tar via SSH), verifica sha256 nel guest, installa. Richiede la VM di test gia' avviata
#                (lo avvia l'operatore con tools/vm/start-gpu-test-vm.sh --start). Non avvia la VM, non imposta boot-arg, non riavvia.
#   --verify     solo lettura nel guest: versione macOS, SIP, boot-arg, kext caricati, bundle, daemon.
#   --shutdown   spegnimento del guest con `sudo -n /sbin/shutdown -h now`; poi attesa dell'uscita di QEMU (max 8 minuti).
#   --arm-check  solo lettura (host e guest): presupposti di --arm-desktop, in ordine; si ferma al primo errore.
#   --arm-desktop  arma il desktop GPU su UN monitor (fase P2, Navi 44). Prima verifica i presupposti (macOS 26.6.2/25G83,
#                0 utenti, boot-arg P2, navi48-fb2 assente, kext di bring-up caricato allo stage 17, nub Metal pubblicato,
#                bundle installato e firmato, pipe adottata e non ancora armata); solo dopo agisce e chiede di digitare ARM.
#                Se un passo fallisce dopo il riavvio di WindowServer, rollback (pipearm 0, fbname 0, flag rimosso): il desktop
#                torna su CPU. Con --dry-run stampa il piano (host e guest), nessun SSH e nessuna scrittura: va eseguito prima.
#                Riferimento: research/reports/metal_deploy_plan.md sez. 8.2 (P0 -> P1 -> P2).
#
# Opzioni:
#   --src DIR          pacchetto (default /mnt/vm/builds/metal-stack-20261021)
#   --accel-kext PATH  Navi48Accel.kext da installare (default: DIR/kext/Navi48Accel.kext se presente; NON e' nella raccolta 21/10)
#   --no-accel         non installare il kext aux
#   --accel-resume     kext gia' copiato in /Library/Extensions: rilancia solo kmutil libraries/load (dopo l'approvazione utente)
#   --daemon           avvia anche com.navi48.translate con launchctl bootstrap (i file del daemon sono sempre copiati)
#   --force-quit       in --shutdown: dopo 8 minuti senza uscita di QEMU, invia QMP quit (ultima risorsa)
#   --yes              in --deploy non chiede conferma interattiva
#
# Ambiente (default): N48_TEST_HOST=127.0.0.1  N48_TEST_PORT=2223  N48_TEST_USER=test  N48_TEST_SSH_KEY=(vuoto: chiave di default)
#
# Mai toccata da questo script: la VM di build (porta 2222, /mnt/vm/images/macos-build), il kext bring-up Navi48Bringup
# (iniettato da OpenCore: vedi tools/vm/prepare-gpu-test-stage.py), `kmutil install --update-all`, SIP, nvram.
#
# Sudo nel guest: nessuna password. Ogni comando privilegiato usa `sudo -n`. Se manca la regola sudoers, lo script si
# ferma prima di modificare qualcosa (exit 4) e stampa la configurazione (`--sudo-help`).
#
# Codici di uscita: 0 ok; 1 errore di verifica o di argomenti; 2 avviso bloccante (VM non raggiungibile, pacchetto incompleto);
# 3 approvazione utente richiesta per il kext aux (vedi sez. "Approvazione" in --help); 4 sudo non disponibile nel guest.

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SRC_DEFAULT=/mnt/vm/builds/metal-stack-20261021
TEST_VM="${N48_TEST_VM:-/mnt/vm/images/macos-gpu-test}"   # override only for tests on a copy (read-only modes)
HOST="${N48_TEST_HOST:-127.0.0.1}"
PORT="${N48_TEST_PORT:-2223}"
GUEST_USER="${N48_TEST_USER:-test}"
KEY="${N48_TEST_SSH_KEY:-}"
STAMP="$(date +%Y%m%d-%H%M%S)"

MODE=check
SRC="$SRC_DEFAULT"
ACCEL_KEXT=""
DO_ACCEL=1
ACCEL_RESUME=0
DO_DAEMON=0
FORCE_QUIT=0
ASSUME_YES=0
DRY_RUN=0

die()  { echo "ERRORE: $*" >&2; exit 1; }
warn() { echo "AVVISO: $*" >&2; }
step() { echo; echo "== $*"; }

usage() {
  sed -n '2,/^set -euo pipefail/p' "$0" | sed '/^set -euo pipefail/d; s/^# \{0,1\}//'
}

sudo_help() {
  cat <<'TXT'
Configurazione sudo per il guest di TEST (una volta sola, da un terminale del guest con la password dell'utente test;
NON eseguita da questo script). Solo sulla VM di test, MAI sulla VM di build.

  sudo visudo -f /etc/sudoers.d/navi48-test

Contenuto minimo per lo spegnimento (--shutdown):

  test ALL=(root) NOPASSWD: /sbin/shutdown

Contenuto per il nub Metal (--arm-desktop e le ricette M6 chiamano `sudo -n ~/n48-metal/n48nub`; sudoers vuole il percorso
assoluto: sostituire /Users/test con la home reale dell'utente di test):

  test ALL=(root) NOPASSWD: /Users/test/n48-metal/n48nub

Contenuto per --deploy (equivale a root per questi comandi: accettabile solo nella VM di test):

  test ALL=(root) NOPASSWD: /bin/mkdir, /bin/mv, /bin/cp, /bin/chmod, /usr/sbin/chown, /usr/bin/tar, /usr/bin/xattr, \
/usr/bin/kmutil, /bin/launchctl, /sbin/shutdown

Contenuto per i test P0 (mtlprobe con `sudo N48M_ALLOW=1`: serve SETENV per la variabile sulla riga di comando):

  test ALL=(root) SETENV: NOPASSWD: /Users/test/navi48-staging/mtlprobe *

Verifica (nel guest): sudo -n -l /sbin/shutdown   (deve stampare la regola, senza chiedere password)
Verificare che /etc/sudoers includa /etc/sudoers.d (riga #includedir). Sostituire "test" con l'utente reale se diverso.
TXT
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) MODE=check ;;
    --dry-run) DRY_RUN=1; if [[ "$MODE" == check ]]; then MODE=dry-run; fi ;;
    --deploy) MODE=deploy ;;
    --verify) MODE=verify ;;
    --shutdown) MODE=shutdown ;;
    --arm-check) MODE=arm-check ;;
    --arm-desktop) MODE=arm ;;
    --src) SRC="${2:?--src richiede una directory}"; shift ;;
    --accel-kext) ACCEL_KEXT="${2:?--accel-kext richiede un percorso}"; shift ;;
    --no-accel) DO_ACCEL=0 ;;
    --accel-resume) ACCEL_RESUME=1 ;;
    --daemon) DO_DAEMON=1 ;;
    --force-quit) FORCE_QUIT=1 ;;
    --yes) ASSUME_YES=1 ;;
    --sudo-help) sudo_help; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) die "opzione sconosciuta: $1 (vedi --help)" ;;
  esac
  shift
done

# ---------------------------------------------------------------- ssh (solo modalita' che toccano il guest)
SSH_OPTS=(-p "$PORT" -o BatchMode=yes -o ConnectTimeout=10)
[[ -n "$KEY" ]] && SSH_OPTS+=(-i "$KEY")
SSH_TARGET="$GUEST_USER@$HOST"

guest_reachable() {
  ssh -n "${SSH_OPTS[@]}" "$SSH_TARGET" 'true' >/dev/null 2>&1   # -n: keep stdin for the ARM confirmation that follows
}

# ---------------------------------------------------------------- controlli locali (nessun SSH, nessuna scrittura)
REQUIRED=(
  bundle/Navi48Metal.bundle.tar
  radv/libvulkan_radeon.dylib
  m2v/metal2vulkan
  m2v/libn48xlate.dylib
  spirv/spirv-val
  mtlprobe/mtlprobe
  daemon/com.navi48.translate.plist
  daemon/usr-local-navi48/pc-translate.sh
  daemon/usr-local-navi48/pc-translate.py
  daemon/usr-local-navi48/n48-llvm-dis
  daemon/usr-local-navi48/n48-spirv-val-stub
  daemon/usr-local-navi48/n48-translate.sb
  daemon/usr-local-navi48/overrides.txt
  daemon/usr-local-navi48/metal2vulkan
  daemon/usr-local-navi48/spirv-val
  navi48accel/INSTALL.md
  autoarm/install.sh
  tools/n48nub
)
MACHO_X86=(radv/libvulkan_radeon.dylib m2v/metal2vulkan m2v/libn48xlate.dylib spirv/spirv-val daemon/usr-local-navi48/metal2vulkan daemon/usr-local-navi48/spirv-val tools/n48nub)

local_check() {
  local rc=0 f
  step "Controlli locali su $SRC"
  [[ -d "$SRC" ]] || die "pacchetto assente: $SRC"
  if [[ -f "$SRC/SHA256SUMS" ]]; then
    if (cd "$SRC" && sha256sum -c --quiet SHA256SUMS); then
      echo "sha256 del pacchetto: OK ($(wc -l < "$SRC/SHA256SUMS") file)"
    else
      echo "sha256 del pacchetto: FALLITO" >&2; rc=1
    fi
  else
    echo "SHA256SUMS mancante" >&2; rc=1
  fi
  for f in "${REQUIRED[@]}"; do
    [[ -s "$SRC/$f" ]] || { echo "mancante o vuoto: $f" >&2; rc=1; }
  done
  for f in "${MACHO_X86[@]}"; do
    [[ -s "$SRC/$f" ]] || continue
    if file -b "$SRC/$f" | grep -q 'x86_64'; then :; else echo "non x86_64: $f" >&2; rc=1; fi
  done
  if [[ -s "$SRC/bundle/Navi48Metal.bundle.tar" ]]; then
    tar -tf "$SRC/bundle/Navi48Metal.bundle.tar" | grep -q '^Navi48Metal.bundle/Contents/MacOS/Navi48Metal$' \
      || { echo "bundle senza Contents/MacOS/Navi48Metal" >&2; rc=1; }
    n=$(tar -tf "$SRC/bundle/Navi48Metal.bundle.tar" | grep -c 'spvcache/.*\.spv$' || true)
    echo "bundle: spvcache con $n file .spv"
    [[ "$n" -gt 0 ]] || { echo "bundle senza spvcache" >&2; rc=1; }
  fi
  bash -n "$SRC/daemon/usr-local-navi48/pc-translate.sh" && echo "sintassi pc-translate.sh: OK" || rc=1
  for f in install.sh uninstall.sh n48-autoarm.sh n48-autoarm-watch.sh; do
    [[ -s "$SRC/autoarm/$f" ]] && { sh -n "$SRC/autoarm/$f" || { echo "sintassi autoarm/$f: FALLITA" >&2; rc=1; }; }
  done
  if [[ -s "$SRC/kext/Navi48Accel.kext/Contents/Info.plist" ]]; then
    echo "kext aux presente nella raccolta: $(grep -A1 CFBundleVersion "$SRC/kext/Navi48Accel.kext/Contents/Info.plist" | tail -1 | tr -d ' \t')"
  else
    warn "Navi48Accel.kext NON presente in $SRC/kext: il passo kext aux sara' saltato se non passi --accel-kext"
  fi
  [[ -s "$SRC/navi48test/navi48test" ]] || warn "navi48test non presente nella raccolta (non indispensabile per T0-T7)"
  # Lock della VM di test: solo informativo, non avvia nulla.
  if [[ -f "$TEST_VM/.vm.lock" ]]; then
    exec 9<>"$TEST_VM/.vm.lock"
    if flock -n 9; then echo "VM di test: lock libero (VM non in esecuzione)"; else echo "VM di test: lock occupato (VM in esecuzione o in preparazione)"; fi
    flock -u 9 2>/dev/null || true
    exec 9>&-
  else
    warn "lock della VM di test assente: $TEST_VM/.vm.lock"
  fi
  return $rc
}

# ---------------------------------------------------------------- script remoto (letto da bash -s nel guest)
remote_script() {
  # STAGE va espanso nel guest ($HOME): non passa da %q.
  printf 'STAMP=%s\nSTAGE="$HOME/navi48-deploy/%s"\nDO_DAEMON=%s\nDO_ACCEL=%s\nACCEL_RESUME=%s\nACCEL_KEXT_NAME=%s\n' \
    "$STAMP" "$STAMP" "$DO_DAEMON" "$DO_ACCEL" "$ACCEL_RESUME" "Navi48Accel.kext"
  cat <<'REMOTE'
set -euo pipefail
echo "== preflight"
PV=$(sw_vers -productVersion); BV=$(sw_vers -buildVersion)
echo "macOS $PV ($BV)"
[ "$PV" = "26.6.2" ] && [ "$BV" = "25G83" ] || { echo "ERRORE: versione attesa 26.6.2 / 25G83"; exit 1; }
csrutil status || true
sudo -n -l /bin/mkdir >/dev/null 2>&1 || { echo "NO_SUDO: regola sudoers assente (deploy-metal-stack.sh --sudo-help)"; exit 4; }
[ -f "$STAGE/SHA256SUMS" ] || { echo "ERRORE: pacchetto non trasferito in $STAGE"; exit 1; }
echo "== verifica sha256 nel guest"
( cd "$STAGE" && shasum -a 256 -c SHA256SUMS > "$STAGE/sha-check.txt" 2>&1 ) || { cat "$STAGE/sha-check.txt"; echo "ERRORE: sha256 nel guest diversi"; exit 1; }
echo "sha256 nel guest: OK"

echo "== bundle in /Library/GPUBundles"
sudo -n mkdir -p /Library/GPUBundles
if [ -d /Library/GPUBundles/Navi48Metal.bundle ]; then
  sudo -n mv /Library/GPUBundles/Navi48Metal.bundle "/Library/GPUBundles/Navi48Metal.bundle.prev-$STAMP"
  echo "bundle precedente spostato in Navi48Metal.bundle.prev-$STAMP"
fi
sudo -n tar --no-xattrs -xf "$STAGE/bundle/Navi48Metal.bundle.tar" -C /Library/GPUBundles
sudo -n chown -R root:wheel /Library/GPUBundles/Navi48Metal.bundle
codesign --verify --strict -v /Library/GPUBundles/Navi48Metal.bundle
echo "spvcache nel bundle: $(ls /Library/GPUBundles/Navi48Metal.bundle/Contents/Resources/spvcache/*.spv | wc -l) .spv"

echo "== daemon di traduzione (file sempre copiati; avvio solo con --daemon)"
sudo -n mkdir -p /usr/local/navi48
sudo -n cp "$STAGE"/daemon/usr-local-navi48/* /usr/local/navi48/
sudo -n chown -R root:wheel /usr/local/navi48
sudo -n chmod 755 /usr/local/navi48
for f in pc-translate.sh pc-translate.py n48-llvm-dis n48-spirv-val-stub metal2vulkan spirv-val; do sudo -n chmod 755 "/usr/local/navi48/$f"; done
sudo -n chmod 644 /usr/local/navi48/overrides.txt /usr/local/navi48/n48-translate.sb
# La directory di stato va creata PRIMA del bootstrap: StandardOutPath del plist la apre prima dello script (piano 4.3).
sudo -n mkdir -p /private/var/tmp/n48m-translate-state
sudo -n cp "$STAGE/daemon/com.navi48.translate.plist" /Library/LaunchDaemons/com.navi48.translate.plist
sudo -n chown root:wheel /Library/LaunchDaemons/com.navi48.translate.plist
sudo -n chmod 644 /Library/LaunchDaemons/com.navi48.translate.plist
if [ "$DO_DAEMON" = 1 ]; then
  sudo -n launchctl bootout system/com.navi48.translate 2>/dev/null || true
  sudo -n launchctl bootstrap system /Library/LaunchDaemons/com.navi48.translate.plist
  launchctl print system/com.navi48.translate 2>&1 | head -8
else
  echo "daemon non avviato (--daemon non passato)"
fi

echo "== strumenti utente (~/navi48-staging, nessun privilegio)"
mkdir -p "$HOME/navi48-staging"
cp "$STAGE/mtlprobe/mtlprobe" "$HOME/navi48-staging/mtlprobe"; chmod 755 "$HOME/navi48-staging/mtlprobe"
if [ -f "$STAGE/navi48test/navi48test" ]; then cp "$STAGE/navi48test/navi48test" "$HOME/navi48-staging/navi48test"; chmod 755 "$HOME/navi48-staging/navi48test"; fi
# n48nub (publish / withdraw / status del nub Navi48MetalNub): il percorso e' quello che --arm-desktop e lo stage M6 si aspettano.
mkdir -p "$HOME/n48-metal"
cp "$STAGE/tools/n48nub" "$HOME/n48-metal/n48nub"; chmod 755 "$HOME/n48-metal/n48nub"

if [ "$DO_ACCEL" = 1 ] && [ -d "$STAGE/kext/$ACCEL_KEXT_NAME" ]; then
  echo "== kext aux $ACCEL_KEXT_NAME (Auxiliary KC)"
  VER=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$STAGE/kext/$ACCEL_KEXT_NAME/Contents/Info.plist")
  DST="/Library/Extensions/Navi48Accel-$VER.kext"
  if [ "$ACCEL_RESUME" = 0 ]; then
    [ ! -e "$DST" ] || { echo "ERRORE: $DST esiste gia': ogni versione va in un percorso nuovo (navi48accel INSTALL)"; exit 1; }
    mkdir -p "$HOME/navi48-backup/auxkc-pre-$VER"
    [ -f /Library/KernelCollections/AuxiliaryKernelExtensions.kc ] && sudo -n cp /Library/KernelCollections/AuxiliaryKernelExtensions.kc "$HOME/navi48-backup/auxkc-pre-$VER/" || echo "AuxKC non presente: nessun backup"
    sudo -n cp -R "$STAGE/kext/$ACCEL_KEXT_NAME" "$DST"
    sudo -n chown -R root:wheel "$DST"
    sudo -n chmod -R go-w "$DST"
    sudo -n xattr -cr "$DST"
  fi
  DST="/Library/Extensions/Navi48Accel-$VER.kext"
  sudo -n kmutil libraries -p "$DST" -a x86_64
  set +e; OUT=$(sudo -n kmutil load -p "$DST" 2>&1); RC=$?; set -e
  echo "$OUT" | tail -6
  if [ "$RC" != 0 ]; then
    echo "ACCEL_LOAD_FAILED rc=$RC: se il messaggio chiede approvazione/consenso, approvare in Impostazioni di Sistema >"
    echo "Privacy e sicurezza (una volta per binario), poi rilanciare con --accel-resume. Non usare kmutil install --update-all."
    exit 3
  fi
  kmutil showloaded --list-only | grep -i 'accelprobe' || echo "kext aux non risulta caricato"
else
  echo "== kext aux: saltato (--no-accel o $ACCEL_KEXT_NAME assente nel pacchetto)"
fi

echo "== riepilogo"
{ echo "deploy $STAMP"; cd "$STAGE" && shasum -a 256 bundle/Navi48Metal.bundle.tar tools/n48nub; } > "$HOME/navi48-staging/deployed-$STAMP.txt"
echo "DEPLOY_OK (manifest: $HOME/navi48-staging/deployed-$STAMP.txt)"
REMOTE
}

remote_verify_script() {
  cat <<'REMOTE'
sw_vers -productVersion; sw_vers -buildVersion
csrutil status || true
echo "boot-args: $(nvram boot-args 2>/dev/null || echo n/a)"
kmutil showloaded --list-only 2>/dev/null | grep -iE 'navi48|accelprobe|AMDRadeon|AMD' || echo "kext navi48/accelprobe: nessuno caricato"
ls -ld /Library/GPUBundles/Navi48Metal.bundle 2>&1 || true
launchctl print system/com.navi48.translate 2>&1 | head -4 || true
ls ~/navi48-staging 2>/dev/null || true
REMOTE
}

# ---------------------------------------------------------------- armamento del desktop, un monitor (fase P2, Navi 44)
# Sostituisce per Navi 44 la ricetta di Cobalt64 tools/pc/arm-gpu-desktop.sh (che non verifica i presupposti). Stesse chiamate
# navi48test (pipeagdc, fbname, pipearm, pipereload, killall WindowServer), ma ogni presupposto e' letto PRIMA di qualunque azione.
# Non esegue pipeadopt: l'adozione e' la fase P1 (presupposto qui, non azione).

# Host, sola lettura: il piano della VM di test deve descrivere la fase P2 (il guest non e' ancora interrogato).
local_arm_check() {
  step "Presupposti dal piano della VM di test (sola lettura: $TEST_VM/test-plan.json)"
  python3 -I - "$TEST_VM" <<'PY'
import fcntl, hashlib, json, pathlib, sys
vm = pathlib.Path(sys.argv[1])
plan = json.loads((vm / 'test-plan.json').read_text())
def vm_running(vm):
    # the launcher holds an exclusive flock on .vm.lock for the whole QEMU run
    handle = (vm / '.vm.lock').open('r')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        handle.close()
def efi_verified(vm, plan):
    if vm_running(vm):
        # VM up: the live qcow2 is not comparable (QEMU writes it). Use the digest recorded at --start, which must equal the plan.
        record = vm / '.launch-efi.sha256'
        if not record.is_file():
            return False
        return record.read_text().split()[0] == plan.get('efi_sha256')
    return hashlib.sha256((vm / plan['efi']).read_bytes()).hexdigest() == plan.get('efi_sha256')
ba = plan['boot_args'].split()
checks = {
    'stage 17': plan.get('stage') == 17,
    'native S1b (navi48-native=1)': bool(plan.get('native_s1b')),
    'Metal nub (navi48-metal=1)': bool(plan.get('metal')),
    'display route (navi48-metal-disp=1)': bool(plan.get('metal_disp')),
    'WindowServer client (navi48-metal-ws=1)': bool(plan.get('metal_ws')),
    'RX 9060 XT unico monitor (UEFI Output Max, N4X_GPU_PRIMARY=1 al lancio)': bool(plan.get('primary_display')),
    'interrupts esplicito': 'navi48-interrupts=0' in ba or 'navi48-interrupts=1' in ba,
    'navi48-fb2 assente': not any(f.startswith('navi48-fb2') for f in ba),
    'navi48-m6 assente (Navi 44 lo rifiuta)': not any(f.startswith('navi48-m6') for f in ba),
    'EFI verificata': efi_verified(vm, plan),
}
for name, ok in checks.items():
    print(('ok    ' if ok else 'FAIL  ') + name)
sys.exit(0 if all(checks.values()) else 1)
PY
}

# Guest: i presupposti, nell'ordine in cui fermano l'esecuzione. Con ARM_MODE=check esce dopo le verifiche.
remote_arm_script() {
  printf 'ARM_MODE=%s\n' "$1"
  printf 'ARM_FBNAME=%s\n' "${N48_ARM_FBNAME:-0}"
  cat <<'REMOTE'
set -u
NT="$HOME/navi48-staging/navi48test"
NM="$HOME/n48-metal/n48nub"
fail() { echo "ARM_STOP: $*"; exit 1; }
ok()   { echo "CHECK ok: $*"; }
PV=$(sw_vers -productVersion); BV=$(sw_vers -buildVersion)
[ "$PV" = "26.6.2" ] && [ "$BV" = "25G83" ] || fail "macOS $PV ($BV): atteso 26.6.2 / 25G83"
ok "macOS 26.6.2 / 25G83"
who | grep -q . && fail "utenti connessi: l'armamento riavvia WindowServer (serve 0 utenti)"
ok "nessun utente connesso"
BA=$(nvram boot-args 2>/dev/null | sed 's/^boot-args[[:space:]]*//')
TOK=$(printf '%s\n' $BA)
for need in navi48bringup=1 navi48-stage=17 navi48-metal=1 navi48-metal-disp=1 navi48-metal-ws=1; do
  printf '%s\n' "$TOK" | grep -qx "$need" || fail "boot-arg $need assente (boot-args: $BA)"
done
ok "boot-arg P2 presenti (navi48bringup, navi48-stage=17, navi48-metal, navi48-metal-disp, navi48-metal-ws)"
printf '%s\n' "$TOK" | grep -q '^navi48-fb2' && fail "navi48-fb2 presente: la rotta framebuffer Apple deve essere assente"
ok "navi48-fb2 assente"
kmutil showloaded --list-only 2>/dev/null | grep -qi 'com.navi48.bringup' || fail "kext di bring-up com.navi48.bringup non caricato"
ok "kext di bring-up caricato (stage 17 dal boot-arg; lo stage raggiunto va letto dal log seriale)"
kmutil showloaded --list-only 2>/dev/null | grep -qi 'com.hackintosh.RDNA4FB' || fail "RDNA4FB non caricato: il framebuffer della pipe (Navi 44) non c'e'; caricare il kext patchato prima dell'armamento"
ok "RDNA4FB caricato (framebuffer della pipe, match 0x7590)"
[ -x "$NT" ] || fail "navi48test assente: $NT"
ok "navi48test presente"
[ -x "$NM" ] || fail "n48nub assente: $NM"
sudo -n "$NM" status 2>&1 | grep -q 'Navi48MetalNub present' || fail "nub Metal non pubblicato: pubblicarlo prima (fase P0)"
ok "nub Metal pubblicato"
[ -d /Library/GPUBundles/Navi48Metal.bundle ] && codesign --verify --strict /Library/GPUBundles/Navi48Metal.bundle >/dev/null 2>&1 \
  || fail "bundle Navi48Metal assente o firma non valida (deploy-metal-stack.sh --deploy)"
ok "bundle installato, firma valida"
FL=$(sudo -n "$NT" accel pipestat 0 2>&1 | sed -n 's/^ *flags[^:]*: *\(0x[0-9a-fA-F]*\).*/\1/p' | head -1)
[ -n "$FL" ] || fail "pipestat 0 non riporta 'flags': formato diverso, nessuna azione eseguita"
FLV=$((FL))
(( FLV & 2 )) || fail "pipe non adottata (flags $FL): eseguire prima la fase P1 (adozione)"
ok "pipe adottata (flags $FL)"
(( FLV & 4 )) && { echo "pipe gia' armata (flags $FL): nulla da fare"; exit 0; }
ok "pipe non ancora armata"
[ "$ARM_MODE" = check ] && { echo "ARM_CHECK_PASS: presupposti verificati, nessuna azione eseguita"; exit 0; }

# ---- azioni: solo dopo tutti i presupposti. Il rollback riporta la pipe disarmata e il desktop su CPU al riavvio.
rollback() {
  echo "ROLLBACK: $*"
  sudo -n "$NT" accel pipearm 0 >/dev/null 2>&1 || true
  sudo -n "$NT" accel fbname 0 >/dev/null 2>&1 || true
  sudo -n rm -f /private/tmp/n48m-headless-no || true
}
sudo -n touch /private/tmp/n48m-headless-no && sudo -n chmod 644 /private/tmp/n48m-headless-no || fail "flag headless-no non creato"
AG=$(sudo -n "$NT" accel pipeagdc 1 2>&1); echo "$AG" | grep -E 'agdc status'
echo "$AG" | grep -Eq 'agdc status +: (0|12) ' || { rollback "pipeagdc 1"; fail "pipeagdc 1 non pubblicato (serve boot-arg navi48-agdc=1; status 1 = assente): desktop lasciato su CPU"; }   # 12 = already published in this boot
if [ "$ARM_FBNAME" = 1 ]; then
  sudo -n "$NT" accel fbname 1 2>&1 | grep -E 'class name NOW' || { rollback "fbname 1"; fail "fbname 1 senza nome di classe"; }
else
  echo "fbname 1 saltato (N48_ARM_FBNAME=0): la pipe accetta il nome RDNA4FB senza rinomina"
fi
sudo -n "$NT" accel pipearm 1 2>&1 | grep 0xccf || { rollback "pipearm 1"; fail "pipearm 1 rifiutata"; }
sudo -n "$NT" accel pipereload 2>&1 | tail -1
sudo -n launchctl asuser 501 launchctl setenv CI_USE_MTL_DAG_FOR_CIKL_SRC 0 || echo "AVVISO: backstop CIKL non impostato (nessun dominio utente): non fatale"
sudo -n killall -9 WindowServer; sleep 15
pgrep -x WindowServer >/dev/null || { rollback "WindowServer non ripartito"; fail "WindowServer non in esecuzione dopo il riavvio"; }
FL2=$(sudo -n "$NT" accel pipestat 0 2>&1 | sed -n 's/^ *flags[^:]*: *\(0x[0-9a-fA-F]*\).*/\1/p' | head -1)
(( ${FL2:-0} & 4 )) || { rollback "pipe non armata dopo il riavvio"; fail "pipe non armata dopo il riavvio (flags ${FL2:-?})"; }
echo "ARM_OK: WindowServer ripartito, pipe armata (flags $FL2). Verificare il monitor e raccogliere i log (metal_deploy_plan.md 8.4)."
REMOTE
}

print_arm_plan() {
  echo
  echo "== Piano di --arm-desktop (P2, un monitor). Nessun comando eseguito in --dry-run."
  echo "1) host, sola lettura: presupposti del piano della VM di test (sotto)."
  echo "2) guest, sola lettura (ARM_MODE=check): macOS, 0 utenti, boot-arg, navi48-fb2 assente, kext, nub, bundle, pipe adottata."
  echo "3) conferma digitata ARM; poi guest (ARM_MODE=arm): accel pipeagdc 1, [fbname 1 solo con N48_ARM_FBNAME=1], pipearm 1, pipereload, killall -9 WindowServer,"
  echo "   verifica pipe armata. Rollback se un passo fallisce dopo i presupposti (pipearm 0, fbname 0, flag rimosso)."
  echo "   Script guest:"
  remote_arm_script arm | sed 's/^/   | /'
}

do_arm_check() {
  local_arm_check || die "presupposti del piano non soddisfatti"
  guest_reachable || { echo "VM di test non raggiungibile su $HOST:$PORT: avviarla con tools/vm/start-gpu-test-vm.sh --start" >&2; exit 2; }
  step "Presupposti nel guest (sola lettura)"
  set +e
  remote_arm_script check | ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'bash -s'
  rc=$?
  set -e
  exit "$rc"
}

do_arm() {
  local_arm_check || die "presupposti del piano non soddisfatti: nessuna azione"
  if [[ "$DRY_RUN" == 1 ]]; then
    print_arm_plan
    echo; echo "DRY-RUN ARM OK: nessun SSH, nessuna scrittura."
    exit 0
  fi
  guest_reachable || { echo "VM di test non raggiungibile su $HOST:$PORT: avviarla con tools/vm/start-gpu-test-vm.sh --start" >&2; exit 2; }
  read -r -p "Armare il desktop GPU sul monitor? Riavvia WindowServer (0 utenti). Scrivi ARM per continuare: " ans
  [[ "$ans" == ARM ]] || die "armamento annullato"
  mkdir -p "$TEST_VM/diagnostics/arm"
  local LOG="$TEST_VM/diagnostics/arm/arm-$STAMP.log"
  exec > >(tee -a "$LOG") 2>&1
  echo "log: $LOG"
  step "Presupposti nel guest"
  set +e
  remote_arm_script check | ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'bash -s'
  rc=$?
  set -e
  [[ $rc == 0 ]] || { echo "ARMAMENTO NON ESEGUITO: presupposto non soddisfatto (exit $rc), desktop lasciato su CPU"; exit "$rc"; }
  step "Armamento nel guest"
  set +e
  remote_arm_script arm | ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'bash -s'
  rc=$?
  set -e
  echo "exit guest: $rc"
  exit "$rc"
}

# ---------------------------------------------------------------- stampa del piano (dry-run) e esecuzione (deploy)
print_plan() {
  echo
  echo "== Piano di --deploy (nessun comando eseguito in --dry-run)"
  echo "Guest: $SSH_TARGET porta $PORT   pacchetto: $SRC   staging remoto: ~/navi48-deploy/$STAMP"
  echo
  echo "1) trasferimento:"
  echo "   tar -C \"$SRC\" -cf - . | ssh ${SSH_OPTS[*]} $SSH_TARGET 'mkdir -p ~/navi48-deploy/$STAMP && tar -C ~/navi48-deploy/$STAMP -xf -'"
  echo "2) script nel guest (bash -s), passi: preflight 26.6.2/25G83, sha256 nel guest, bundle, daemon, strumenti, kext aux:"
  remote_script | sed 's/^/   | /'
  echo "3) nessun passo: avvio VM, boot-arg (EFI: tools/vm/prepare-gpu-test-stage.py), riavvio, kmutil install --update-all."
}

confirm() {
  [[ "$ASSUME_YES" = 1 ]] && return 0
  read -r -p "Confermare il deploy sul guest di TEST ($SSH_TARGET)? [scrivi DEPLOY] " ans
  [[ "$ans" == DEPLOY ]] || die "deploy annullato"
}

do_deploy() {
  local_check || die "controlli locali non superati: nessuna modifica eseguita"
  guest_reachable || { echo "VM di test non raggiungibile su $HOST:$PORT: avviarla con tools/vm/start-gpu-test-vm.sh --start" >&2; exit 2; }
  confirm
  mkdir -p "$TEST_VM/diagnostics/deploy"
  local LOG="$TEST_VM/diagnostics/deploy/deploy-$STAMP.log"
  exec > >(tee -a "$LOG") 2>&1
  echo "log: $LOG"
  step "Trasferimento del pacchetto nel guest"
  tar -C "$SRC" -cf - . | ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "mkdir -p \"\$HOME/navi48-deploy/$STAMP\" && tar -C \"\$HOME/navi48-deploy/$STAMP\" -xf -"
  step "Esecuzione nel guest"
  set +e
  remote_script | ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'bash -s'
  rc=$?
  set -e
  echo "exit guest: $rc"
  exit "$rc"
}

do_verify() {
  guest_reachable || { echo "VM di test non raggiungibile su $HOST:$PORT" >&2; exit 2; }
  remote_verify_script | ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'bash -s'
}

do_shutdown() {
  guest_reachable || { echo "VM di test non raggiungibile: nulla da spegnere" >&2; exit 2; }
  if ! ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'sudo -n -l /sbin/shutdown >/dev/null 2>&1'; then
    echo "NO_SUDO: spegnimento via sudo non autorizzato nel guest. Configurare con: $SCRIPT_NAME --sudo-help" >&2
    exit 4
  fi
  echo "richiesto spegnimento: sudo -n /sbin/shutdown -h now"
  ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'sudo -n /sbin/shutdown -h now' || true
  for i in $(seq 1 96); do   # 96 x 5 s = 8 minuti
    if ! pgrep -af qemu-system | grep -v pgrep | grep -q 'macos-gpu-test/qmp.sock'; then
      echo "QEMU della VM di test uscito dopo circa $((i*5)) s"; return 0
    fi
    sleep 5
  done
  if [[ "$FORCE_QUIT" = 1 ]]; then
    warn "QEMU ancora attivo dopo 8 minuti: QMP quit (ultima risorsa, --force-quit)"
    python3 -I "$(dirname "$0")/qmp.py" --socket "$TEST_VM/qmp.sock" quit
  else
    echo "QEMU ancora attivo dopo 8 minuti. Ripetere con --force-quit solo se confermato." >&2
    exit 2
  fi
}

case "$MODE" in
  check)
    local_check && echo "CHECK OK: pacchetto pronto per --dry-run / --deploy" || { echo "CHECK FALLITO"; exit 1; }
    ;;
  dry-run)
    local_check || { echo "CHECK FALLITO: il piano non sarebbe eseguibile"; exit 1; }
    print_plan
    echo; echo "DRY-RUN OK: nessun SSH, nessuna scrittura."
    ;;
  deploy) do_deploy ;;
  verify) do_verify ;;
  shutdown) do_shutdown ;;
  arm-check) do_arm_check ;;
  arm) do_arm ;;
esac
