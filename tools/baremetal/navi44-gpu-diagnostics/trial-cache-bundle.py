#!/usr/bin/env python3
"""Root-only, temporary Metal bundle trial; always restore bundle and APP gate.

Uses an atomic directory exchange. No reboot, boot guard, kernel, or EFI changes.
Existing processes keep their mapped image. Only the isolated browser is tested.
"""
import ctypes,hashlib,os,pathlib,shutil,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[3]
LIVE=pathlib.Path('/Library/GPUBundles/Navi48Metal.bundle')
APP=pathlib.Path('/Library/Application Support/Navi44/accelerated-trial')
TOOL=APP/'navi48test'
BASE='ed45a207dd742f74c3d3b2dccc6d9a214d919a7dd1109a30618bb0c60fcb5c3e'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def swap(a,b):
 f=ctypes.CDLL(None,use_errno=True).renamex_np
 f.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];f.restype=ctypes.c_int
 if f(os.fsencode(a),os.fsencode(b),2):raise OSError(ctypes.get_errno(),'atomic swap failed')
def gate(op):
 r=subprocess.run([str(TOOL),'accel','appallow',op,'Brave Browser'],check=True,capture_output=True,text=True)
 if 'code                    : 0 (ok)' not in r.stdout and 'code                    : 4' not in r.stdout:raise RuntimeError(r.stdout)
if os.geteuid()!=0:raise SystemExit('root required')
if digest(LIVE/'Contents/MacOS/Navi48Metal')!=BASE:raise SystemExit('Installed baseline changed')
# Preserve the exact original including signatures in a private root-owned backup.
work=pathlib.Path(tempfile.mkdtemp(prefix='cache-trial-',dir=APP));work.chmod(0o700)
other=work/'exchanged.bundle'
shutil.copytree(ROOT/'research/builds/macos-20261029/cache-candidate/Navi48Metal.bundle',other)
for p in other.rglob('*'):
 if p.is_symlink():raise SystemExit('symlink in candidate')
 os.chown(p,0,0)
subprocess.run(['codesign','--verify','--deep','--strict',str(other)],check=True)
swapped=False
try:
 gate('remove')
 swap(LIVE,other);swapped=True
 subprocess.run(['sudo','-H','-u','pastasugo89','python3',str(ROOT/'tools/baremetal/navi44-gpu-diagnostics/brave-probe.py'),'--disable-graphite','--diagnostic-log',str(ROOT/'research/builds/macos-20261029/cache-candidate/trial5.log'),'--output',str(ROOT/'research/builds/macos-20261029/cache-candidate/brave-cache-trial5.json')],check=True,timeout=70)
finally:
 if swapped:
  if digest(other/'Contents/MacOS/Navi48Metal')!=BASE:raise RuntimeError('Original backup changed; retained '+str(work))
  swap(LIVE,other)
 gate('add')
 print('Original Metal bundle and Brave gate restored. Backup:',work,flush=True)
