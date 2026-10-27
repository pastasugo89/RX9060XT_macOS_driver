#!/usr/bin/env python3
"""Populate OpCore Simplify's local B840 package cache; no boot-device writes."""
import argparse
import contextlib
import hashlib
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "research/ext/OpCore-Simplify"
PIN = "f0e1e441bb455c33e9695a9c9c50e8ca931d4de8"
AMD_URL = "https://raw.githubusercontent.com/laobamac/AMD_Vanilla/a174cca80efe2377fde3b902666c70863ea66454/patches.plist"
AMD_BLOB = "53b4b7e4bfa0951d1b2b1001c5d94e4d6f28eeed"
AMD_SHA = "0f164799520bc876f40baa851109ca45290d78bef46baa1358fd65a000fbca20"
PACKAGES = {"Lilu", "VirtualSMC", "RTL812xLucy", "USBToolBox", "UTBDefault",
            "CtlnaAHCIPort", "NVMeFix", "AppleMCEReporterDisabler", "RestrictEvents"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patches-only", action="store_true")
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if head != PIN:
        raise SystemExit("Unexpected upstream revision")
    audit = REPO / "audit"
    audit.mkdir(exist_ok=True)
    with urlopen(AMD_URL, timeout=20) as response:
        data = response.read()
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if blob != AMD_BLOB:
        raise SystemExit("Pinned AMD patch blob identity differs")
    # Match the locally reviewed text snapshot's final newline exactly.
    normalized = next((value for value in (data, data + b"\n")
                       if hashlib.sha256(value).hexdigest() == AMD_SHA), None)
    if normalized is None:
        raise SystemExit("Pinned AMD patch SHA256 differs")
    destination = audit / "laobamac-patches.plist"
    if destination.exists() and destination.read_bytes() != normalized:
        raise SystemExit("Different existing AMD patch file; left unchanged")
    if not destination.exists():
        destination.write_bytes(normalized)
    if not args.patches_only:
        sys.path.insert(0, str(REPO))
        from Scripts.gathering_files import gatheringFiles
        from Scripts.kext_maestro import KextMaestro
        maestro = KextMaestro()
        if not PACKAGES <= {k.name for k in maestro.kexts}:
            raise SystemExit("Upstream package catalog changed")
        for kext in maestro.kexts:
            kext.checked = kext.name in PACKAGES
        with (audit / "gather-b840.log").open("w") as log, contextlib.redirect_stdout(log):
            if not gatheringFiles().gather_bootloader_kexts(maestro.kexts, "25.6.0"):
                raise RuntimeError("Package download failed; inspect audit/gather-b840.log")
    print("Pinned AMD patches ready; package cache " + ("unchanged" if args.patches_only else "populated"))
    print("The B840 builder separately pins OpenCore 1.0.8 DEBUG and validates every output payload.")


if __name__ == "__main__":
    main()
