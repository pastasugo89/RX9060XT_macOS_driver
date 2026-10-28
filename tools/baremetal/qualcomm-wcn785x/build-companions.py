#!/usr/bin/env python3
"""Build pinned, unmodified Lilu Bluetooth companions into staging only."""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
for name in ('sdk', 'lilu', 'brcm', 'intel', 'out'):
    p.add_argument('--' + name, type=Path, required=True)
a = p.parse_args()
sdk, lilu, brcm, intel, out = [getattr(a, n).resolve() for n in ('sdk', 'lilu', 'brcm', 'intel', 'out')]
pins = {lilu: '0249c3a918c68a43891350f35fded615b1575776',
        brcm: '65389020769837e92e9fb939bac34bd9a3e25bb2',
        intel: 'a414375505fa3b014be32f8fca31b5bbfdf9f10f'}
for repo, rev in pins.items():
    assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == rev
    assert not subprocess.check_output(['git', '-C', str(repo), 'diff', 'HEAD', '--'], text=True).strip()
if out.exists():
    raise SystemExit('Output already exists; use a new staging directory')
out.mkdir(parents=True)
sysroot = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
common = ['-arch', 'x86_64', '-target', 'x86_64-apple-macos11.0', '-isysroot', sysroot,
          '-isystem', str(sdk / 'Headers'), '-isystem', str(lilu / 'Lilu'),
          '-DKERNEL', '-DKERNEL_PRIVATE', '-DDRIVER_PRIVATE', '-DAPPLE', '-DNeXT',
          '-D_FORTIFY_SOURCE=0', '-nostdinc', '-fno-builtin', '-fno-common',
          '-fno-stack-protector', '-mkernel', '-mno-red-zone', '-mno-sse', '-mno-sse2',
          '-mno-avx', '-mno-mmx', '-msoft-float', '-Wall', '-Wextra', '-Os', '-g']
products = [
    ('BlueToolFixup', '2.7.3', 'as.acidanthera.BlueToolFixup', brcm / 'BrcmPatchRAM/BlueToolFixup.cpp',
     brcm / 'BrcmPatchRAM/BlueToolFixup-Info.plist', True, brcm),
    ('IntelBTPatcher', '2.5.0', 'com.zxystd.IntelBTPatcher', intel / 'IntelBTPatcher/IntelBTPatcher.cpp',
     intel / 'IntelBTPatcher/Info.plist', False, intel)]
for name, version, identifier, source, template, custom, repo in products:
    work = out / name
    work.mkdir()
    glue = work / 'kmod_info.c'
    glue.write_text(f'''#include <mach/mach_types.h>
#include <libkern/OSKextLib.h>
extern kern_return_t _start(kmod_info_t *, void *);
extern kern_return_t _stop(kmod_info_t *, void *);
extern kern_return_t {name}_kern_start(kmod_info_t *, void *);
extern kern_return_t {name}_kern_stop(kmod_info_t *, void *);
KMOD_EXPLICIT_DECL({identifier}, "{version}", _start, _stop)
__private_extern__ kmod_start_func_t *_realmain = {name}_kern_start;
__private_extern__ kmod_stop_func_t *_antimain = {name}_kern_stop;
''')
    flags = common + [f'-DPRODUCT_NAME={name}', f'-DMODULE_VERSION={version}']
    if custom:
        flags += ['-DLILU_CUSTOM_IOKIT_INIT=1']
    objects = []
    with (work / 'build.log').open('w') as log:
        for src in (source, lilu / 'Lilu/Library/plugin_start.cpp', glue):
            obj = work / (src.stem + '.o')
            cpp = src.suffix == '.cpp'
            extra = ['-std=c++17', '-fno-exceptions', '-fno-rtti', '-fcheck-new', '-fno-c++-static-destructors'] if cpp else []
            subprocess.run(['clang++' if cpp else 'clang', *flags, *extra, '-c', str(src), '-o', str(obj)],
                           stdout=log, stderr=log, check=True)
            objects.append(str(obj))
        bundle = out / (name + '.kext')
        exe = bundle / 'Contents/MacOS' / name
        exe.parent.mkdir(parents=True)
        subprocess.run(['clang++', '-arch', 'x86_64', '-target', 'x86_64-apple-macos11.0', '-isysroot', sysroot,
                        '-nostdlib', '-Xlinker', '-kext', *objects, '-L' + str(sdk / 'Library/x86_64'),
                        '-lkmodc++', '-lkmod', '-o', str(exe)], stdout=log, stderr=log, check=True)
    text = template.read_text()
    substitutions = {'DEVELOPMENT_LANGUAGE': 'en', 'EXECUTABLE_NAME': name, 'PRODUCT_BUNDLE_IDENTIFIER': identifier,
                     'PRODUCT_NAME': name, 'PRODUCT_NAME:rfc1034identifier': name, 'MODULE_VERSION': version,
                     'MARKETING_VERSION': version, 'CURRENT_PROJECT_VERSION': version, 'PRODUCT_BUNDLE_PACKAGE_TYPE': 'KEXT'}
    for key, value in substitutions.items():
        text = text.replace('$(' + key + ')', value)
    assert '$(' not in text
    info = plistlib.loads(text.encode())
    (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info, sort_keys=False))
    resources = bundle / 'Contents/Resources'
    resources.mkdir()
    for origin, dest in ((lilu / 'LICENSE.txt', 'LICENSE-Lilu.txt'),):
        shutil.copyfile(origin, resources / dest)
    licenses = sorted(x for x in repo.iterdir() if x.is_file() and x.name.lower().startswith('license'))
    assert licenses, 'Missing upstream license'
    for license in licenses:
        shutil.copyfile(license, resources / license.name)
    subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
manifest = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in out.rglob('*') if f.is_file() and '.kext/' in str(f)}
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Built staging companions:', out)
