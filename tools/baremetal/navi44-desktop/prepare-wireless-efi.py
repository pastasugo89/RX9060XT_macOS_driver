#!/usr/bin/env python3
"""Prepare the verified B840 USB matcher/PCI visibility changes in a new EFI copy.

This restores enumeration prerequisites; it does not supply a Qualcomm driver.
The source must be the inspected OCBOOT EFI directory, never a live destination.
"""
import argparse
import hashlib
import plistlib
import shutil
from pathlib import Path

BASE_CONFIG_SHA = "b8351af96eda59bdb278b48ed70a96fa0a02f6906dbbeb527c20a21112a9701d"
CONTROLLERS = {"XH00": ("5:0:0", 14), "XHC0": ("10:0:3", 4),
               "XHC1": ("10:0:4", 4), "XHC2": ("11:0:0", 1)}


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists() or output == source or source in output.parents:
        raise ValueError("output must be a new directory outside the source EFI")
    config_path = source / "OC/config.plist"
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != BASE_CONFIG_SHA:
        raise ValueError("source config differs from the inspected boot baseline")
    config = plistlib.loads(config_path.read_bytes())
    entries = [x for x in config["ACPI"]["Add"]
               if x["Path"] == "SSDT-Disable_Network_GPP7.aml"]
    if len(entries) != 1 or not entries[0]["Enabled"]:
        raise ValueError("expected exactly one enabled Wi-Fi masking SSDT")
    entries[0]["Enabled"] = False
    relative = Path("OC/Kexts/USBMapB840.kext/Contents/Info.plist")
    usb = plistlib.loads((source / relative).read_bytes())
    personalities = usb["IOKitPersonalities"]
    if set(personalities) != set(CONTROLLERS):
        raise ValueError("unexpected USB controller personalities")
    for name, (bdf, count) in CONTROLLERS.items():
        personality = personalities[name]
        properties = personality["IOProviderMergeProperties"]
        if int.from_bytes(properties["port-count"], "little") != count:
            raise ValueError(f"unexpected port count for {name}")
        personality["IOParentMatch"] = {"IOPropertyMatch": {"pcidebug": bdf}}
    shutil.copytree(source, output)
    (output / "OC/config.plist").write_bytes(plistlib.dumps(config, sort_keys=False))
    (output / relative).write_bytes(plistlib.dumps(usb, sort_keys=False))
    print(f"Prepared {output}; source EFI unchanged. Qualcomm driver still required.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_efi", type=Path)
    parser.add_argument("output_efi", type=Path)
    args = parser.parse_args()
    prepare(args.source_efi, args.output_efi)
