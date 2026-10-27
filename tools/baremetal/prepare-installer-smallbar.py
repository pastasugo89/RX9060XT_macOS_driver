#!/usr/bin/env python3
"""Prepare an offline installer EFI; never write USB devices or partitions."""
import argparse
import copy
import hashlib
import json
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "research/ext"
SOURCE = EXT / "ocboot-baremetal-debug/EFI-next3"
OUTPUT = EXT / "ocboot-baremetal-debug/EFI-installer-smallbar"
VALIDATOR = EXT / "ocboot-baremetal/_tools/ocvalidate"
EXPECTED_SOURCE_SHA256 = "d47cad652e11f86d8b912777291922568770aeb1006d1bfc080e5af359586699"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmio-f700", action="store_true",
                        help="derive the next test from smallbar: whitelist only 0xF7000000")
    args = parser.parse_args()
    source = OUTPUT if args.mmio_f700 else SOURCE
    output = OUTPUT.parent / "EFI-installer-mmiof7" if args.mmio_f700 else OUTPUT
    expected = ("007215f872830c78b5995195bf7d37b7ffa54ac09e7a111aadfa05761e136d64"
                if args.mmio_f700 else EXPECTED_SOURCE_SHA256)
    source_config = source / "EFI/OC/config.plist"
    if digest(source_config) != expected:
        raise SystemExit("Source config differs from audited baseline; inspect it first.")
    if output.exists():
        raise SystemExit(f"Output already exists; left unchanged: {output}")
    subprocess.run(["sha256sum", "-c", "SHA256SUMS-EFI.txt"], cwd=source, check=True)
    original = plistlib.loads(source_config.read_bytes())
    assert original["Booter"]["Quirks"]["DevirtualiseMmio"] is True
    assert original["Booter"]["Quirks"]["ResizeAppleGpuBars"] == (0 if args.mmio_f700 else -1)
    assert original["Booter"]["MmioWhitelist"] == []
    assert original["UEFI"]["Quirks"]["ResizeGpuBars"] == -1
    active = [e["BundlePath"] for e in original["Kernel"]["Add"] if e["Enabled"]]
    assert "VirtualSMC.kext" in active and "Lilu.kext" in active
    assert not any(any(s in name.lower() for s in ("navi", "rdna", "accel")) for name in active)

    with tempfile.TemporaryDirectory(prefix=".installer-efi-", dir=output.parent) as tmp:
        staged = Path(tmp) / "candidate"
        shutil.copytree(source / "EFI", staged / "EFI")
        config = copy.deepcopy(original)
        if args.mmio_f700:
            config["Booter"]["MmioWhitelist"] = [{
                "Address": 0xF7000000,
                "Comment": "B840 boot7 runtime MMIO descriptor: preserve F7000000..FEE00000 (126 MiB)",
                "Enabled": True,
            }]
            change = {"Booter.MmioWhitelist": {"before": [], "after": config["Booter"]["MmioWhitelist"]}}
        else:
            config["Booter"]["Quirks"]["ResizeAppleGpuBars"] = 0
            change = {"Booter.Quirks.ResizeAppleGpuBars": {"before": -1, "after": 0}}
        target = staged / "EFI/OC/config.plist"
        target.write_bytes(plistlib.dumps(config, sort_keys=False))
        reread = plistlib.loads(target.read_bytes())
        restored = copy.deepcopy(reread)
        if args.mmio_f700:
            restored["Booter"]["MmioWhitelist"] = []
        else:
            restored["Booter"]["Quirks"]["ResizeAppleGpuBars"] = -1
        assert restored == original, "Unexpected semantic config changes"
        files = sorted(p for p in (staged / "EFI").rglob("*") if p.is_file())
        for p in files:
            relative = p.relative_to(staged)
            if relative.as_posix() != "EFI/OC/config.plist":
                assert p.read_bytes() == (source / relative).read_bytes(), relative
        subprocess.run([str(VALIDATOR), str(target)], check=True)
        (staged / "SHA256SUMS-EFI.txt").write_text(
            "".join(f"{digest(p)}  {p.relative_to(staged).as_posix()}\n" for p in files)
        )
        subprocess.run(["sha256sum", "-c", "SHA256SUMS-EFI.txt"], cwd=staged, check=True)
        (staged / "PREPARATION.json").write_text(json.dumps({
            "source_config_sha256": expected,
            "candidate_config_sha256": digest(target),
            "semantic_change": change,
            "file_count": len(files),
            "other_efi_files_byte_identical": True,
            "bios_expected": {"ResizableBAR": "Enabled", "Above4GDecoding": "Enabled"},
            "gpu_driver_enabled": False,
            "hardware_boot_tested": False,
            "deployed_to_usb": False,
        }, indent=2) + "\n")
        shutil.move(str(staged), str(output))
    print(f"Prepared offline: {output}")
    print("Only semantic change:", json.dumps(change))
    print("Not hardware tested; USB and internal partitions unchanged.")


if __name__ == "__main__":
    main()
