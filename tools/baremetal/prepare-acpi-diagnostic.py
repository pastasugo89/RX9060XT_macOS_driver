#!/usr/bin/env python3
"""Prepare pinned B840 ACPI logging or single-CPU diagnostics; deploy config only."""
import argparse
import copy
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research/ext/opcore-simplify-b840-installer-v2"
OUTPUT = ROOT / "research/ext/opcore-simplify-b840-acpi-debug"
USB = Path("/run/media/pastasugo89/OCBOOT")
OLD = "1f8d43cf677eb2cce93fc792ebe13fd897760b4897126ae2d3988bf26b4cbc08"
GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
EXTRA = "acpi_layer=0xffffffff acpi_level=0x2087 msgbuf=1048576"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify(bundle, manifest):
    expected = {}
    for line in manifest.read_text().splitlines():
        sha, name = line.split("  ", 1)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "EFI":
            raise RuntimeError("Invalid manifest path")
        expected[name] = sha
    actual = {p.relative_to(bundle).as_posix(): digest(p)
              for p in (bundle / "EFI").rglob("*") if p.is_file()}
    if expected != actual:
        raise RuntimeError(f"Unexpected EFI contents: {bundle}")
    return len(actual)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--single-cpu", action="store_true",
                        help="Add only cpus=1 to the verified boot10/11 diagnostic EFI")
    parser.add_argument("--single-cpu-mmio-f700", action="store_true",
                        help="From the pinned cpus=1 EFI, whitelist only MMIO descriptor base 0xF7000000")
    args = parser.parse_args()
    if args.single_cpu and args.single_cpu_mmio_f700:
        raise RuntimeError("Choose only one diagnostic variant")
    base, output, expected_sha, extra, label = BASE, OUTPUT, OLD, EXTRA, "acpi-debug"
    if args.single_cpu:
        base = OUTPUT
        output = ROOT / "research/ext/opcore-simplify-b840-cpus1"
        expected_sha = "8710fe3bb6f4b4e3b18399ad4749d5262c63987ddcf32b18bf02472e794f7551"
        extra, label = "cpus=1", "cpus1"
    elif args.single_cpu_mmio_f700:
        base = ROOT / "research/ext/opcore-simplify-b840-cpus1"
        output = ROOT / "research/ext/opcore-simplify-b840-cpus1-mmio-f700"
        expected_sha = "3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976"
        extra, label = "", "cpus1-mmio-f700"
    old_path = base / "EFI/OC/config.plist"
    if digest(old_path) != expected_sha:
        raise RuntimeError("Pinned source config changed")
    baseline_count = verify(base, base / "SHA256SUMS-EFI.txt")
    before = plistlib.loads(old_path.read_bytes())
    candidate = copy.deepcopy(before)
    if args.single_cpu_mmio_f700:
        if before["Booter"]["Quirks"]["DevirtualiseMmio"] is not True:
            raise RuntimeError("Pinned cpus=1 source does not enable DevirtualiseMmio")
        if before["Booter"].get("MmioWhitelist") != []:
            raise RuntimeError("Pinned cpus=1 source has an unexpected MMIO whitelist")
        candidate["Booter"]["MmioWhitelist"] = [{
            "Address": 0xF7000000,
            "Comment": "B840 boot12 EFI runtime descriptor [0xF7000000, 0xFEE00000) contains fault CR2 0xFED802B0",
            "Enabled": True,
        }]
        restored = copy.deepcopy(candidate)
        restored["Booter"]["MmioWhitelist"] = before["Booter"]["MmioWhitelist"]
        changed_key = "Booter.MmioWhitelist"
    else:
        old_args = candidate["NVRAM"]["Add"][GUID]["boot-args"]
        new_keys = {x.split("=")[0] for x in extra.split()}
        if any(x.split("=")[0] in new_keys for x in old_args.split()):
            raise RuntimeError("Diagnostic arguments already present")
        candidate["NVRAM"]["Add"][GUID]["boot-args"] = old_args + " " + extra
        restored = copy.deepcopy(candidate)
        restored["NVRAM"]["Add"][GUID]["boot-args"] = old_args
        changed_key = f"NVRAM.Add.{GUID}.boot-args"
    if restored != before:
        raise RuntimeError("Unexpected semantic changes")
    data = plistlib.dumps(candidate, sort_keys=False)
    new_sha = hashlib.sha256(data).hexdigest()
    if output.exists():
        if (output / "EFI/OC/config.plist").read_bytes() != data:
            raise RuntimeError("Different candidate exists; left unchanged")
    else:
        output.mkdir()
        shutil.copytree(base / "EFI", output / "EFI")
        (output / "EFI/OC/config.plist").write_bytes(data)
        files = sorted(p for p in (output / "EFI").rglob("*") if p.is_file())
        (output / "SHA256SUMS-EFI.txt").write_text("".join(
            f"{digest(p)}  {p.relative_to(output).as_posix()}\n" for p in files))
    count = verify(output, output / "SHA256SUMS-EFI.txt")
    if count != baseline_count:
        raise RuntimeError("Candidate EFI file count differs")
    # The config is the only changed file. This also checks all disabled payloads.
    for path in (base / "EFI").rglob("*"):
        if path.is_file() and path != old_path:
            if digest(path) != digest(output / path.relative_to(base)):
                raise RuntimeError("Non-config payload changed")
    validator = ROOT / "research/ext/ocboot-baremetal/_tools/ocvalidate"
    checked = subprocess.run([str(validator), str(output / "EFI/OC/config.plist")],
                             check=True, text=True, capture_output=True)
    (output / "ocvalidate.txt").write_text(checked.stdout + checked.stderr)
    record = {"previous_config_sha256": expected_sha, "config_sha256": new_sha,
              "changed_key": changed_key, "added_arguments": extra,
              "efi_file_count": count, "non_config_payloads_unchanged": True,
              "ocvalidate_passed": True, "hardware_boot_tested": False}
    if args.single_cpu_mmio_f700:
        record.update({"mmio_whitelist_address": "0xF7000000",
                       "mmio_descriptor_logged": "[0xF7000000, 0xFEE00000), EFI_MEMORY_RUNTIME",
                       "boot_args_unchanged": True,
                       "candidate_is_diagnostic_only": True})
    (output / "PREPARATION.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Prepared: {output}; {count} files verified; config SHA256 {new_sha}")
    if not args.deploy:
        return
    mount = json.loads(subprocess.check_output(
        ["findmnt", "--json", "--target", str(USB)], text=True))["filesystems"][0]
    if (mount["target"], mount["source"], mount["fstype"]) != (str(USB), "/dev/sda1", "vfat"):
        raise RuntimeError("Unexpected mount")
    uuid = subprocess.check_output(["lsblk", "-no", "UUID", "/dev/sda1"], text=True).strip()
    transport = subprocess.check_output(["lsblk", "-no", "TRAN", "/dev/sda"], text=True).strip()
    if uuid != "A140-3052" or transport != "usb" or "rw" not in mount["options"].split(","):
        raise RuntimeError("Expected writable OCBOOT USB not found")
    verify(USB, base / "SHA256SUMS-EFI.txt")
    recovery = USB / "com.apple.recovery.boot/BaseSystem.dmg"
    recovery_sha = digest(recovery)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = USB / (f"_config-pre-{label}-" + stamp)
    backup.mkdir()
    target = USB / "EFI/OC/config.plist"
    shutil.copy2(target, backup / "config.plist")
    temporary = target.with_name(f"config-{label}.tmp")
    if temporary.exists():
        raise RuntimeError("Staging file exists; left unchanged")
    changed = False
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if digest(target) != expected_sha or digest(temporary) != new_sha:
            raise RuntimeError("Source or staging changed")
        os.replace(temporary, target)
        changed = True
        verify(USB, output / "SHA256SUMS-EFI.txt")
        if digest(recovery) != recovery_sha:
            raise RuntimeError("Recovery image changed")
        record.update({"deployed_at_utc": stamp, "usb_uuid": uuid, "deployed_to_usb": True,
                       "backup": str(backup / "config.plist"),
                       "recovery_sha256_before_and_after": recovery_sha})
        (output / "DEPLOYMENT.json").write_text(json.dumps(record, indent=2) + "\n")
        (backup / "DEPLOYMENT.json").write_text(json.dumps(record, indent=2) + "\n")
        os.sync()
    except BaseException:
        if changed:
            shutil.copy2(backup / "config.plist", target)
            os.sync()
        raise
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Deployed config only; previous config: {backup / 'config.plist'}")
    print("Recovery unchanged; hardware boot pending.")


if __name__ == "__main__":
    main()
