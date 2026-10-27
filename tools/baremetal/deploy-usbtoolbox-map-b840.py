#!/usr/bin/env python3
"""Deploy the reviewed USBToolBox Linux-port candidate to this machine's OCBOOT EFI.

This intentionally accepts only the known A140-3052 volume and changes two files.
It requires an already-mounted writable volume and a local backup made from BOOT15.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone


REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch-usb-native"
CANDIDATE = REPO / "research/ext/usbtoolbox-linux-port-candidate"
BASELINE_MANIFEST = BASELINE / "SHA256SUMS-EFI.txt"
CANDIDATE_MANIFEST = CANDIDATE / "SHA256SUMS-EFI.txt"
DEVICE = "/dev/sda1"
EXPECTED_UUID = "A140-3052"
EXPECTED_MOUNT = "/run/media/pastasugo89/OCBOOT"
CONFIG = "EFI/OC/config.plist"
INFO = "EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist"
VALIDATOR = REPO / "research/ext/ocboot-baremetal/_tools/ocvalidate"


def parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        rel = rel.strip()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"bad SHA-256 entry in {path}: {line!r}")
        if not rel.startswith("EFI/") or ".." in Path(rel).parts:
            raise ValueError(f"manifest contains a path outside EFI: {rel}")
        if rel in result:
            raise ValueError(f"duplicate manifest path: {rel}")
        result[rel] = digest
    return result


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_tree(root: Path, expected: dict[str, str]) -> dict[str, str]:
    observed = {rel: sha256(root / rel) for rel in expected}
    mismatches = [rel for rel in expected if observed[rel] != expected[rel]]
    if mismatches:
        raise RuntimeError(f"manifest mismatch ({len(mismatches)} paths): {mismatches}")
    return observed


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as error:
        # FAT may not support fsync on directory descriptors; sync() flushes it.
        if error.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
            raise
        os.sync()


def atomic_replace(destination: Path, source: Path) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".usbmap-deploy-", dir=destination.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, destination)
        fsync_dir(destination.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def check_volume(target: Path) -> None:
    # lsblk can read the udev/sysfs identity without requiring raw-device access;
    # blkid may return empty when this account is not in the disk group.
    uuid = subprocess.run(
        ["lsblk", "-ndo", "UUID", DEVICE],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if uuid != EXPECTED_UUID:
        raise RuntimeError(f"wrong volume UUID: {uuid!r}")
    rows = subprocess.run(
        ["findmnt", "-rn", "-S", DEVICE, "-o", "SOURCE,TARGET,FSTYPE,OPTIONS"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    if len(rows) != 1:
        raise RuntimeError(f"expected one mount for {DEVICE}, got {rows!r}")
    fields = rows[0].split()
    if len(fields) < 4 or fields[1] != str(target) or fields[2] != "vfat" or "rw" not in fields[3].split(","):
        raise RuntimeError(f"unexpected mount state: {rows[0]!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    target = Path(EXPECTED_MOUNT)
    if not target.is_mount():
        raise RuntimeError(f"not mounted: {target}")
    check_volume(target)

    baseline = parse_manifest(BASELINE_MANIFEST)
    candidate = parse_manifest(CANDIDATE_MANIFEST)
    if set(baseline) != set(candidate) or len(baseline) != 28:
        raise RuntimeError("BOOT15 and candidate manifests must have the same 28 EFI paths")
    changed = {p for p in baseline if baseline[p] != candidate[p]}
    if changed != {CONFIG, INFO}:
        raise RuntimeError(f"candidate changes unexpected paths: {sorted(changed)}")

    current = {rel: sha256(target / rel) for rel in baseline}
    if current == candidate:
        raise RuntimeError("candidate already present; refusing a repeated deployment")
    if current != baseline:
        mismatch = [p for p in baseline if current[p] != baseline[p]]
        raise RuntimeError(f"mounted EFI is not the reviewed BOOT15 baseline: {mismatch}")
    if not (args.backup / "config.plist.BOOT15").is_file() or not (
        args.backup / "USBMapB840-Info.plist.BOOT15"
    ).is_file():
        raise RuntimeError("required external BOOT15 backups are missing")
    if sha256(args.backup / "config.plist.BOOT15") != baseline[CONFIG]:
        raise RuntimeError("external config backup does not match BOOT15")
    if sha256(args.backup / "USBMapB840-Info.plist.BOOT15") != baseline[INFO]:
        raise RuntimeError("external Info.plist backup does not match BOOT15")

    record: dict[str, object] = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "device": DEVICE,
        "uuid": EXPECTED_UUID,
        "baseline_manifest_sha256": sha256(BASELINE_MANIFEST),
        "candidate_manifest_sha256": sha256(CANDIDATE_MANIFEST),
        "backup_directory": str(args.backup.resolve()),
        "backup_sha256": {
            "config.plist.BOOT15": sha256(args.backup / "config.plist.BOOT15"),
            "USBMapB840-Info.plist.BOOT15": sha256(args.backup / "USBMapB840-Info.plist.BOOT15"),
        },
    }
    try:
        # The kext remains disabled until config.plist is the final replacement.
        atomic_replace(target / INFO, CANDIDATE / INFO)
        atomic_replace(target / CONFIG, CANDIDATE / CONFIG)
        observed = verify_tree(target, candidate)
        record["post_manifest"] = "PASS"
        record["post_sha256"] = {CONFIG: observed[CONFIG], INFO: observed[INFO]}
        validation = subprocess.run(
            [str(VALIDATOR), str(target / CONFIG)], capture_output=True, text=True,
        )
        record["ocvalidate_returncode"] = validation.returncode
        record["ocvalidate_output"] = (validation.stdout + validation.stderr).strip()
        if validation.returncode:
            raise RuntimeError(f"ocvalidate failed: {record['ocvalidate_output']}")
        os.sync()
        record["result"] = "candidate deployed; full manifest and ocvalidate passed"
    except Exception as error:
        record["deployment_error"] = f"{type(error).__name__}: {error}"
        # Disable first, then restore the old bundle plist.
        atomic_replace(target / CONFIG, args.backup / "config.plist.BOOT15")
        atomic_replace(target / INFO, args.backup / "USBMapB840-Info.plist.BOOT15")
        restored = verify_tree(target, baseline)
        record["rollback"] = "PASS"
        record["rollback_config_sha256"] = restored[CONFIG]
        record["rollback_info_sha256"] = restored[INFO]
        os.sync()
        (args.backup / "deployment-result.json").write_text(
            json.dumps(record, indent=2) + "\n"
        )
        raise

    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (args.backup / "deployment-result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
