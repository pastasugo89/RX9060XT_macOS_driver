#!/usr/bin/env python3
"""Stage the reviewed archive-boundary recovery for the next boot only.

Requires the exact software-recovery boot and prior pending attempt recorded in
the manifest. Leaves the kill switch present; never restarts WindowServer or the
boot job. Saves the abandoned attempt rather than labelling it successful.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
STAGED = ROOT / 'research/builds/macos-20261030/archive-recovery'
APP = Path('/Library/Application Support/Navi44/accelerated-trial')
LIVE = Path('/Library/GPUBundles/Navi48Metal.bundle')
SCRIPT = APP / 'accelerated-reboot-trial.sh'
STATE = APP / 'boot-state.json'
KILL = Path('/private/tmp/n48m-off')

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def atomic(p, data, mode):
    fd, name = tempfile.mkstemp(prefix='.archive-recovery-', dir=p.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, p)
    finally:
        if os.path.exists(name): os.unlink(name)

def swap(a, b):
    fn = ctypes.CDLL(None, use_errno=True).renamex_np
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    if fn(os.fsencode(a), os.fsencode(b), 2):
        raise OSError(ctypes.get_errno(), 'atomic bundle swap failed')

def main():
    if os.geteuid() != 0: raise ValueError('Root required')
    manifest = json.loads((STAGED / 'manifest.json').read_text())
    boot = subprocess.check_output(['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip()
    if boot.lower() != manifest['current_boot'].lower(): raise ValueError('Boot changed')
    for path in (APP, LIVE, SCRIPT, STATE, KILL):
        if path.is_symlink() or path.stat().st_uid != 0: raise ValueError('Unsafe path: '+str(path))
    meta = KILL.stat()
    if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o644 or meta.st_size or meta.st_nlink != 1:
        raise ValueError('Unrecognized software kill switch')
    running = subprocess.run(['pgrep','-f','[b]ash /Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh'],capture_output=True,text=True)
    if running.returncode != 1: raise ValueError('Boot guard running or process query failed')
    spec = importlib.util.spec_from_file_location('boot_state', APP / 'boot-state.py')
    state = importlib.util.module_from_spec(spec); spec.loader.exec_module(state)
    with state.transaction(STATE):
        before = state.read(STATE)
        if before['phase'] != 'pending' or before['boot'].lower() != manifest['expected_prior_attempt_boot'].lower():
            raise ValueError('Not the reviewed abandoned attempt')
        for file, expected in manifest['baseline'].items():
            if digest(LIVE / file) != expected: raise ValueError('Baseline changed: '+file)
        candidate = STAGED / 'Navi48Metal.bundle'
        for file, expected in manifest['candidate'].items():
            if digest(candidate / file) != expected: raise ValueError('Candidate changed: '+file)
        subprocess.run(['codesign','--verify','--deep','--strict',str(candidate)],check=True)
        subprocess.run(['bash','-n',str(STAGED / 'accelerated-reboot-trial.sh')],check=True)
        work = Path(tempfile.mkdtemp(prefix='archive-recovery-',dir=APP)); work.chmod(0o700)
        saved_script = SCRIPT.read_bytes(); saved_state = STATE.read_bytes()
        atomic(work / 'original-script.sh', saved_script, 0o600)
        atomic(work / 'abandoned-boot-state.json', saved_state, 0o600)
        shutil.copy2(STAGED / 'manifest.json', work / 'manifest.json')
        shutil.copy2('/private/var/tmp/navi44-accelerated-trial/run.log', work / 'original-run.log')
        other = work / 'baseline.bundle'; shutil.copytree(candidate, other)
        for path in [other, *other.rglob('*')]: os.chown(path, 0, 0)
        exchanged = False
        try:
            swap(LIVE, other); exchanged = True
            atomic(SCRIPT, (STAGED / 'accelerated-reboot-trial.sh').read_bytes(), 0o755)
            subprocess.run(['codesign','--verify','--deep','--strict',str(LIVE)],check=True)
            if digest(LIVE / 'Contents/MacOS/Navi48Metal') != manifest['candidate']['Contents/MacOS/Navi48Metal']:
                raise ValueError('Installed bundle differs')
            # Remove only the exact archived pending record, as the final step.
            # The next normal boot will create a new pending attempt via begin().
            if state.read(STATE) != before: raise ValueError('State changed')
            STATE.unlink()
            atomic(work / 'installed-next-boot.json', json.dumps({'boot':boot,'backup':str(work),'activated':False,'rebooted':False,'kill_switch_kept':KILL.exists()},indent=2).encode(), 0o600)
        except BaseException:
            if exchanged: swap(LIVE, other)
            atomic(SCRIPT, saved_script, 0o755)
            atomic(STATE, saved_state, 0o600)
            raise
        print(json.dumps({'installed_for_next_boot':True,'backup':str(work),'activated':False,'rebooted':False}))

if __name__ == '__main__': main()
