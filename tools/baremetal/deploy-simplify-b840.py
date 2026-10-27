#!/usr/bin/env python3
"""Install the validated B840 EFI on the known OCBOOT USB, preserving rollback."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research/ext/opcore-simplify-b840-installer-v2"
PREVIOUS = ROOT / "research/ext/ocboot-baremetal-debug/EFI-installer-mmiof7"
USB = Path("/run/media/pastasugo89/OCBOOT")
OLD = "b19b38865059e382f7fa350c56b16052f200d434c8c50b1781993e52900a568d"
NEW = "1f8d43cf677eb2cce93fc792ebe13fd897760b4897126ae2d3988bf26b4cbc08"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify(bundle, manifest):
    expected = {}
    for line in manifest.read_text().splitlines():
        sha, name = line.split("  ", 1)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "EFI":
            raise RuntimeError("Invalid EFI manifest path")
        expected[name] = sha
    actual = {p.relative_to(bundle).as_posix(): digest(p) for p in (bundle / "EFI").rglob("*") if p.is_file()}
    if expected != actual:
        raise RuntimeError(f"EFI tree differs from its verified manifest: {bundle}")
    return len(actual)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    mount = json.loads(subprocess.check_output(["findmnt", "--json", "--target", str(USB)], text=True))["filesystems"][0]
    if (mount["target"], mount["source"], mount["fstype"]) != (str(USB), "/dev/sda1", "vfat"):
        raise SystemExit("Unexpected mounted target")
    uuid = subprocess.check_output(["lsblk", "-no", "UUID", "/dev/sda1"], text=True).strip()
    transport = subprocess.check_output(["lsblk", "-no", "TRAN", "/dev/sda"], text=True).strip()
    if uuid != "A140-3052" or transport != "usb":
        raise SystemExit("OCBOOT USB identity differs")
    if digest(USB / "EFI/OC/config.plist") != OLD or digest(SOURCE / "EFI/OC/config.plist") != NEW:
        raise SystemExit("Unexpected current or candidate config; left unchanged")
    old_count = verify(USB, PREVIOUS / "SHA256SUMS-EFI.txt")
    new_count = verify(SOURCE, SOURCE / "SHA256SUMS-EFI.txt")
    print(f"Verified old EFI: {old_count} files; candidate: {new_count} files")
    if args.check_only:
        print("Read-only preflight passed; no files changed")
        return
    if "rw" not in mount["options"].split(","):
        raise SystemExit("USB is read-only; mount it read-write for deployment")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = USB / ("_EFI-pre-simplify-" + stamp)
    staging = USB / ("_EFI-simplify-staging-" + stamp)
    recovery = USB / "com.apple.recovery.boot/BaseSystem.dmg"
    recovery_sha = digest(recovery)
    backup.mkdir()
    staging.mkdir()
    moved_old = False
    try:
        shutil.copytree(SOURCE / "EFI", staging / "EFI")
        verify(staging, SOURCE / "SHA256SUMS-EFI.txt")
        for path in (staging / "EFI").rglob("*"):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        os.sync()
        if digest(USB / "EFI/OC/config.plist") != OLD:
            raise RuntimeError("USB changed while staging")
        os.replace(USB / "EFI", backup / "EFI")
        moved_old = True
        os.replace(staging / "EFI", USB / "EFI")
        verify(USB, SOURCE / "SHA256SUMS-EFI.txt")
        if digest(recovery) != recovery_sha:
            raise RuntimeError("Recovery image changed")
        record = {"deployed_at_utc": stamp, "usb_uuid": uuid, "previous_config_sha256": OLD,
                  "config_sha256": NEW, "backup": str(backup), "file_count": new_count,
                  "recovery_sha256_before_and_after": recovery_sha,
                  "hardware_boot_tested": False, "deployed_to_usb": True}
        (SOURCE / "DEPLOYMENT.json").write_text(json.dumps(record, indent=2) + "\n")
        (backup / "DEPLOYMENT.json").write_text(json.dumps(record, indent=2) + "\n")
        shutil.copy2(SOURCE / "SHA256SUMS-EFI.txt", USB / ("_EFI-simplify-" + stamp + ".sha256"))
        staging.rmdir()
        os.sync()
    except BaseException:
        if moved_old and (backup / "EFI").exists():
            if (USB / "EFI").exists():
                os.replace(USB / "EFI", backup / "failed-candidate-EFI")
            os.replace(backup / "EFI", USB / "EFI")
            os.sync()
        raise
    print(f"Deployed {new_count} verified files. Previous EFI: {backup / 'EFI'}")
    print("Recovery unchanged. Hardware boot pending. Internal partitions untouched.")


if __name__ == "__main__":
    main()
