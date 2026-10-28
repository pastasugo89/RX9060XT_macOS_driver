#!/usr/bin/env python3
"""Build a staging-only x86_64 CPPC candidate using MacKernelSDK and Lilu sources.

No installation/loading or modification of the boot EFI is performed.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--sdk", type=Path, required=True, help="MacKernelSDK directory")
parser.add_argument("--lilu", type=Path, required=True, help="Lilu source root")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
sdk, lilu, out = args.sdk.resolve(), args.lilu.resolve(), args.out.resolve()
here = Path(__file__).resolve().parent
out.mkdir(parents=True, exist_ok=True)
sysroot = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
common = ["-arch", "x86_64", "-target", "x86_64-apple-macos11.0", "-isysroot", sysroot,
          "-I" + str(sdk / "Headers"), "-isystem", str(lilu / "Lilu"), "-I" + str(here),
          "-DKERNEL", "-DKERNEL_PRIVATE", "-DDRIVER_PRIVATE", "-DAPPLE", "-DNeXT",
          "-D_FORTIFY_SOURCE=0", "-DPRODUCT_NAME=Navi44CPPC", "-DMODULE_VERSION=0.0.1",
          "-DLILU_CUSTOM_IOKIT_INIT", "-nostdinc", "-fno-builtin", "-fno-common",
          "-fno-stack-protector", "-mkernel", "-mno-red-zone", "-mno-sse", "-mno-sse2",
          "-mno-avx", "-mno-mmx", "-msoft-float", "-Wall", "-Wextra", "-Werror", "-Os", "-g"]
objects = []
with (out / "build.log").open("w") as log:
    for source in [here / "Navi44CPPC.cpp", lilu / "Lilu/Library/plugin_start.cpp", here / "kmod_info.c"]:
        obj = out / (source.stem + ".o")
        cpp = source.suffix == ".cpp"
        flags = ["-std=c++17", "-fno-exceptions", "-fno-rtti", "-fcheck-new", "-fno-c++-static-destructors"] if cpp else []
        subprocess.run(["clang++" if cpp else "clang", *common, *flags, "-c", str(source), "-o", str(obj)],
                       stdout=log, stderr=log, check=True)
        objects.append(str(obj))
    bundle = out / "Navi44CPPC.kext"
    executable = bundle / "Contents/MacOS/Navi44CPPC"
    executable.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["clang++", "-arch", "x86_64", "-target", "x86_64-apple-macos11.0",
                    "-isysroot", sysroot, "-nostdlib", "-Xlinker", "-kext", *objects,
                    "-L" + str(sdk / "Library/x86_64"), "-lkmodc++", "-lkmod", "-o", str(executable)],
                   stdout=log, stderr=log, check=True)
info = {"CFBundleIdentifier": "com.navi44.cppc", "CFBundleName": "Navi44CPPC",
        "CFBundleExecutable": "Navi44CPPC", "CFBundleVersion": "0.0.1",
        "CFBundleShortVersionString": "0.0.1", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "KEXT", "OSBundleRequired": "Root",
        "IOKitPersonalities": {"Navi44CPPC": {"CFBundleIdentifier": "com.navi44.cppc",
            "IOClass": "Navi44CPPC", "IOMatchCategory": "Navi44CPPC",
            "IOProviderClass": "IOACPIPlatformDevice", "IOResourceMatch": "ACPI",
            "IOPropertyMatch": {"processor-index": 0}}},
        "OSBundleLibraries": {"as.vit9696.Lilu": "1.7.3", "com.apple.kpi.iokit": "20.0.0",
            "com.apple.kpi.libkern": "20.0.0", "com.apple.kpi.mach": "20.0.0",
            "com.apple.kpi.unsupported": "20.0.0", "com.apple.kpi.bsd": "20.0.0"}}
(bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(info, sort_keys=False))
resources = bundle / "Contents/Resources"
resources.mkdir(exist_ok=True)
shutil.copyfile(lilu / "LICENSE.txt", resources / "LICENSE-Lilu.txt")
subprocess.run(["xattr", "-cr", str(bundle)], check=True)
subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
manifest = {str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in bundle.rglob("*") if p.is_file()}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Built staging candidate: {bundle}")
