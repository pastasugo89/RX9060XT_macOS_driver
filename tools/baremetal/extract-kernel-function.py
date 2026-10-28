#!/usr/bin/env python3
"""Extract bounded symbol bytes from a BootKC into non-runnable analysis objects.
No kernel/config writes. Disassembly is static, before OpenCore/runtime changes.
"""
import argparse
import hashlib
import importlib.util
import json
import struct
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location('patch_audit', Path(__file__).with_name('audit-kernel-patches.py'))
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('kernel', type=Path)
p.add_argument('output', type=Path)
p.add_argument('symbols', nargs='+')
a = p.parse_args()
if a.output.exists():
    p.error('Use a new output directory')
b = a.kernel.read_bytes(); digest = hashlib.sha256(b).hexdigest()
_, segments, symbols = audit.layout(b)
by_name = {name: address for address, name in symbols}
records = []
a.output.mkdir(parents=True)
for name in a.symbols:
    if not name.startswith('_') or any(x in name for x in ('/', '\\', '..')):
        raise ValueError('Invalid symbol name')
    address = by_name[name]
    segment = next(s for s in segments if s[2] <= address < s[2] + s[1])
    if segment[3] not in ('__TEXT', '__TEXT_EXEC'):
        raise ValueError('Not a text symbol')
    end = min(s[0] for s in symbols if s[0] > address)
    size = end - address
    if not 0 < size <= 0x20000 or address + size > segment[2] + segment[1]:
        raise ValueError('Unbounded or cross-segment symbol')
    offset = address - segment[2] + segment[0]
    code = b[offset:offset+size]
    header = struct.pack('<IiiIIIII', 0xfeedfacf, 0x1000007, 3, 1, 1, 152, 0, 0)
    load = struct.pack('<II16sQQQQiiII', 0x19, 152, b'__TEXT', address, size, 4096, size, 7, 5, 1, 0)
    section = struct.pack('<16s16sQQIIIIIIII', b'__text', b'__TEXT', address, size, 4096, 4, 0, 0, 0x80000400, 0, 0, 0)
    obj = a.output / (name + '.analysis.o')
    obj.write_bytes((header+load+section).ljust(4096,b'\0')+code)
    obj.chmod(0o644)
    with (a.output / (name + '.asm')).open('w') as out:
        subprocess.run(['xcrun','llvm-objdump','--macho','--disassemble',str(obj)],stdout=out,check=True)
    records.append({'symbol':name,'address':hex(address),'file_offset':hex(offset),'size':size,
                    'bytes_sha256':hashlib.sha256(code).hexdigest(),'boundary':'next defined symbol; may include padding'})
if hashlib.sha256(a.kernel.read_bytes()).hexdigest()!=digest:
    raise ValueError('Kernel changed during extraction')
(a.output/'manifest.json').write_text(json.dumps({'kernel_sha256':digest,'records':records,
    'scope':'static original function bytes, no runtime state or original-source recovery','source_mutations':0},indent=2)+'\n')
print(json.dumps({'functions':len(records),'source_mutations':0,'output':str(a.output)}))
