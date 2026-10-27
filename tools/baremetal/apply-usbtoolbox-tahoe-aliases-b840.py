#!/usr/bin/env python3
"""Apply only the reviewed BOOT17 Tahoe aliases to the known OCBOOT EFI."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone


REPO = Path(__file__).resolve().parents[2]
BOOT16 = REPO / "research/ext/usbtoolbox-linux-port-candidate"
BOOT17 = REPO / "research/ext/usbtoolbox-linux-tahoe-boot17-candidate"
BOOT16_MANIFEST = BOOT16 / "SHA256SUMS-EFI.txt"
BOOT17_MANIFEST = BOOT17 / "SHA256SUMS-EFI.txt"
BOOT17_EFI = BOOT17 / "EFI"
DEVICE = "/dev/sda1"
EXPECTED_UUID = "A140-3052"
EXPECTED_MOUNT = Path("/run/media/pastasugo89/OCBOOT")
INFO = "EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist"
CONFIG = "EFI/OC/config.plist"
VALIDATOR = REPO / "research/ext/ocboot-baremetal/_dl/opencore/src/Utilities/ocvalidate/ocvalidate.linux"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_manifest(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        rel = rel.strip()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"SHA256 errato nel manifest {path}: {line!r}")
        if not rel.startswith("EFI/") or ".." in Path(rel).parts or rel in expected:
            raise ValueError(f"Percorso manifest non valido o duplicato: {rel}")
        expected[rel] = digest
    return expected


def verify_tree(root: Path, expected: dict[str, str]) -> dict[str, str]:
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.parts[len(root.parts)] == "EFI"
    }
    if actual_paths != set(expected):
        raise RuntimeError(
            f"albero EFI diverso dal manifest: extra={sorted(actual_paths - set(expected))}, "
            f"missing={sorted(set(expected) - actual_paths)}"
        )
    actual = {rel: sha256(root / rel) for rel in expected}
    mismatched = [rel for rel, digest in expected.items() if actual[rel] != digest]
    if mismatched:
        raise RuntimeError(f"manifest non corrispondente ({len(mismatched)} file): {mismatched}")
    return actual


def check_volume() -> None:
    uuid = subprocess.run(
        ["lsblk", "-ndo", "UUID", DEVICE], check=True, capture_output=True, text=True
    ).stdout.strip()
    transport = subprocess.run(
        ["lsblk", "-ndo", "TRAN", "/dev/sda"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if uuid != EXPECTED_UUID or transport != "usb":
        raise RuntimeError(f"identità volume inattesa su {DEVICE}: uuid={uuid!r}, transport={transport!r}")
    rows = subprocess.run(
        ["findmnt", "-rn", "-S", DEVICE, "-o", "SOURCE,TARGET,FSTYPE,OPTIONS"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if len(rows) != 1:
        raise RuntimeError(f"atteso un solo mount per {DEVICE}, trovato: {rows!r}")
    fields = rows[0].split()
    if (
        len(fields) < 4
        or fields[1] != str(EXPECTED_MOUNT)
        or fields[2] != "vfat"
        or "rw" not in fields[3].split(",")
    ):
        raise RuntimeError(f"stato mount inatteso: {rows[0]!r}")


def fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as error:
        if error.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
            raise
        os.sync()


def atomic_replace(destination: Path, source: Path) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".usbmap-tahoe-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    if not EXPECTED_MOUNT.is_mount():
        raise RuntimeError(f"OCBOOT non montato: {EXPECTED_MOUNT}")
    check_volume()

    boot16 = parse_manifest(BOOT16_MANIFEST)
    boot17 = parse_manifest(BOOT17_MANIFEST)
    if len(boot16) != 28 or set(boot16) != set(boot17):
        raise RuntimeError("manifest BOOT16/BOOT17 non hanno gli stessi 28 percorsi EFI")
    changed = {path for path in boot16 if boot16[path] != boot17[path]}
    if changed != {INFO}:
        raise RuntimeError(f"BOOT17 deve cambiare solo {INFO}: {sorted(changed)}")
    if boot16[CONFIG] != boot17[CONFIG]:
        raise RuntimeError("config BOOT17 differisce da BOOT16")
    if not VALIDATOR.is_file():
        raise FileNotFoundError(f"ocvalidate 1.0.8 non trovato: {VALIDATOR}")
    if verify_tree(BOOT17, boot17) != boot17:
        raise RuntimeError("la candidata BOOT17 locale non passa il proprio manifest")

    # Stop before writing unless all 28 active payloads are exactly BOOT16.
    mounted = verify_tree(EXPECTED_MOUNT, boot16)
    if mounted == boot17:
        raise RuntimeError("BOOT17 risulta già attiva; rifiuto un deploy ripetuto")
    if mounted != boot16:
        raise RuntimeError("EFI attiva non coincide con BOOT16")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = BOOT17 / "deploy-evidence" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup = backup_dir / "USBMapB840-Info.plist.BOOT16"
    shutil.copyfile(EXPECTED_MOUNT / INFO, backup)
    with backup.open("rb") as handle:
        os.fsync(handle.fileno())
    fsync_directory(backup_dir)
    if sha256(backup) != boot16[INFO]:
        raise RuntimeError("backup Info BOOT16 non coincide con il manifest")
    shutil.copyfile(BOOT16_MANIFEST, backup_dir / "SHA256SUMS-EFI.BOOT16.txt")

    record: dict[str, object] = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "device": DEVICE,
        "uuid": EXPECTED_UUID,
        "baseline": "BOOT16",
        "candidate": "BOOT17 local Tahoe schema aliases",
        "preflight_manifest": "PASS (28/28 BOOT16 payloads)",
        "changed_path": INFO,
        "backup_directory": str(backup_dir.resolve()),
        "backup_sha256": sha256(backup),
        "boot16_info_sha256": boot16[INFO],
        "boot17_info_sha256": boot17[INFO],
    }
    try:
        atomic_replace(EXPECTED_MOUNT / INFO, BOOT17 / INFO)
        observed = verify_tree(EXPECTED_MOUNT, boot17)
        record["post_manifest"] = "PASS (28/28 BOOT17 payloads)"
        validation = subprocess.run(
            [str(VALIDATOR), str(EXPECTED_MOUNT / CONFIG)], capture_output=True, text=True, check=False
        )
        record["ocvalidate_returncode"] = validation.returncode
        record["ocvalidate_output"] = (validation.stdout + validation.stderr).strip()
        if validation.returncode:
            raise RuntimeError(f"ocvalidate ha fallito: {record['ocvalidate_output']}")
        os.sync()
        record["post_info_sha256"] = observed[INFO]
        record["result"] = "BOOT17 applied; only Info.plist changed; manifest and ocvalidate passed"
    except Exception as error:
        record["deployment_error"] = f"{type(error).__name__}: {error}"
        atomic_replace(EXPECTED_MOUNT / INFO, backup)
        restored = verify_tree(EXPECTED_MOUNT, boot16)
        record["rollback"] = "PASS (28/28 BOOT16 payloads)"
        record["rollback_info_sha256"] = restored[INFO]
        os.sync()
        (backup_dir / "deployment-result.json").write_text(json.dumps(record, indent=2) + "\n")
        raise

    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (backup_dir / "deployment-result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
