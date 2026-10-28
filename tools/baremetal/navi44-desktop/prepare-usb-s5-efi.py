#!/usr/bin/env python3
"""Copy an EFI into a new directory and add the inspected B840 USB S5 candidate.

Requires the unmodified firmware DSDT and compiled SSDT-B840-USB-S5.aml.
This never deploys to the boot volume or initiates shutdown.
"""
import argparse
import hashlib
import plistlib
import shutil
from pathlib import Path

DSDT_SHA = "71643c459b246e35bd1ca9defe32c1422cf98574250a459796344f02dfc23447"
NAME = "SSDT-B840-USB-S5.aml"


def table(path, signature):
    data = path.read_bytes()
    if (len(data) < 36 or data[:4] != signature or
            int.from_bytes(data[4:8], "little") != len(data) or sum(data) & 255):
        raise ValueError(f"invalid ACPI table: {path}")
    return data


def prepare(source, aml, dsdt, output):
    source, output = source.resolve(), output.resolve()
    if output.exists() or source == output or source in output.parents:
        raise ValueError("output must be a new directory outside the source EFI")
    firmware = table(dsdt, b"DSDT")
    if hashlib.sha256(firmware).hexdigest() != DSDT_SHA:
        raise ValueError("DSDT differs from the inspected B840 firmware")
    if firmware.count(b"_PTS\x01") != 1:
        raise ValueError("expected exactly one one-argument _PTS method signature")
    ssdt = table(aml, b"SSDT")
    if ssdt[16:24].rstrip(b" \0") != b"USB-S5":
        raise ValueError("expected the production USB-S5 SSDT, not a test fixture")
    config = plistlib.loads((source / "OC/config.plist").read_bytes())
    if any(x["Path"] == NAME for x in config["ACPI"]["Add"]):
        raise ValueError("S5 candidate already present")
    if any(b"_PTS" in x.get("Find", b"") or b"ZPTS" in x.get("Replace", b"")
           for x in config["ACPI"]["Patch"] if x["Enabled"]):
        raise ValueError("an existing _PTS patch requires manual reconciliation")
    config["ACPI"]["Patch"].append({
        "Base": "", "BaseSkip": 0,
        "Comment": "B840 USB S5: preserve root _PTS as ZPTS for guarded Darwin wrapper",
        "Count": 1, "Enabled": True, "Find": b"_PTS\x01", "Limit": 0,
        "Mask": b"", "OemTableId": firmware[16:24], "Replace": b"ZPTS\x01",
        "ReplaceMask": b"", "Skip": 0, "TableLength": len(firmware),
        "TableSignature": b"DSDT"})
    config["ACPI"]["Add"].append({"Comment": "B840 guarded USB PME off for Darwin S5 only",
                                   "Enabled": True, "Path": NAME})
    shutil.copytree(source, output)
    (output / "OC/ACPI" / NAME).write_bytes(ssdt)
    (output / "OC/config.plist").write_bytes(plistlib.dumps(config, sort_keys=False))
    print(f"Prepared {output}; source EFI unchanged; physical S5 test still required.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["source_efi", "ssdt_aml", "firmware_dsdt", "output_efi"]:
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    prepare(args.source_efi, args.ssdt_aml, args.firmware_dsdt, args.output_efi)
