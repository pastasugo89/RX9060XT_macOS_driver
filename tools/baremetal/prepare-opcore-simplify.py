#!/usr/bin/env python3
"""Prepare the pinned local OpCore Simplify fork, without writing boot devices."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "research/ext/OpCore-Simplify"
PIN = "f0e1e441bb455c33e9695a9c9c50e8ca931d4de8"
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iasl", type=Path, default=ROOT / "research/ext/acpica-src/src/generate/unix/bin/iasl")
    parser.add_argument("--macserial", type=Path, default=ROOT / "research/ext/ocboot-baremetal/_tools/macserial")
    args = parser.parse_args()
    if not REPO.exists():
        subprocess.run(["git", "clone", "https://github.com/lzhoang2801/OpCore-Simplify.git", str(REPO)], check=True)
        subprocess.run(["git", "checkout", "--detach", PIN], cwd=REPO, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if head != PIN:
        raise SystemExit("Unexpected upstream revision; left unchanged.")
    patch = HERE / "opcore-simplify-linux.patch"
    check = subprocess.run(["git", "apply", "--check", str(patch)], cwd=REPO, capture_output=True)
    if check.returncode == 0:
        subprocess.run(["git", "apply", str(patch)], cwd=REPO, check=True)
    else:
        subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=REPO, check=True)
    copies = [(HERE / "linux_hardware.py", REPO / "Scripts/linux_hardware.py"),
              (args.iasl, REPO / "Scripts/iasl"), (args.macserial, REPO / "Scripts/macserial.linux")]
    for source, target in copies:
        if target.exists() and source.read_bytes() != target.read_bytes():
            raise SystemExit(f"Different existing local file; left unchanged: {target}")
        if not target.exists():
            shutil.copy2(source, target)
    changed = subprocess.check_output(["git", "diff", "--name-only"], cwd=REPO, text=True).splitlines()
    hashes = {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest() for p in changed + ["Scripts/linux_hardware.py"]}
    metadata = {"upstream": "https://github.com/lzhoang2801/OpCore-Simplify", "commit": PIN,
                "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(), "modified_files": hashes}
    (REPO / "LOCAL_PATCH.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared {REPO} at {PIN}")
    print(f"Run: python '{REPO / 'OpCore-Simplify.py'}' --no-update --allow-unaccelerated")


if __name__ == "__main__":
    main()
