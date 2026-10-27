#!/usr/bin/env python3
"""Generate an offline B840 installer EFI through the patched OpCore Simplify.

Uses the downloaded, audited cache; never mounts or writes boot devices.
The B840 profile retains known firmware fixes, USB mapping and diagnostic logging.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from linux_hardware import collect

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "research/ext"
REPO = EXT / "OpCore-Simplify"
OCBASE = EXT / "ocboot-baremetal"
BASE = EXT / "ocboot-baremetal-debug/EFI-installer-mmiof7"
PIN = "f0e1e441bb455c33e9695a9c9c50e8ca931d4de8"
BASE_SHA = "b19b38865059e382f7fa350c56b16052f200d434c8c50b1781993e52900a568d"
AMD_SHA = "0f164799520bc876f40baa851109ca45290d78bef46baa1358fd65a000fbca20"
OC_SHA = "3f5f42b85703cf2c08e8dcd9245a52fb4326c9f4ef335c75b49f516cbbe131c6"
DARWIN = "25.6.0"
GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def semantic_diff(before, after, prefix=""):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            result.extend(semantic_diff(before.get(key), after.get(key), f"{prefix}.{key}".lstrip(".")))
        return result
    return [prefix] if before != after else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EXT / "opcore-simplify-b840-installer-v2")
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(EXT.resolve()), "Output must be inside ignored research/ext.")
    require(not output.exists(), "Output exists; left unchanged.")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    require(head == PIN, "Unexpected upstream revision")
    metadata = json.loads((REPO / "LOCAL_PATCH.json").read_text())
    for name, expected in metadata["modified_files"].items():
        require(digest(REPO / name) == expected, f"Local fork changed: {name}")
    require(digest(BASE / "EFI/OC/config.plist") == BASE_SHA, "Baseline config changed")
    require(digest(OCBASE / "_dl/opencore-debug/OpenCore-1.0.8-DEBUG.zip") == OC_SHA, "OpenCore archive changed")
    amd_path = REPO / "audit/laobamac-patches.plist"
    require(digest(amd_path) == AMD_SHA, "AMD patches differ from audited download")
    baseline = plistlib.loads((BASE / "EFI/OC/config.plist").read_bytes())
    report = collect()
    require(report["Motherboard"]["Chipset"] == "B840" and "MS-7E57" in report["Motherboard"]["Name"], "This profile is only for MSI MS-7E57")
    require("7700" in report["CPU"]["Processor Name"] and report["CPU"]["Core Count"] == "8", "Unexpected CPU")
    require(len(report["GPU"]) == 1 and next(iter(report["GPU"].values()))["Device ID"] == "1002-7590", "Unexpected display GPU")
    sys.path.insert(0, str(REPO))
    from Scripts import utils
    from Scripts.report_validator import ReportValidator
    from Scripts.integrity_checker import IntegrityChecker

    utils.Utils.head = lambda *a, **k: None
    def input_for_batch(self, prompt="Press Enter to continue..."):
        if prompt.startswith("Press Enter"):
            return ""
        raise RuntimeError("Interactive choice required: " + prompt)
    utils.Utils.request_input = input_for_batch
    spec = importlib.util.spec_from_file_location("opcore_simplify", REPO / "OpCore-Simplify.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    original_report = copy.deepcopy(report)
    with tempfile.TemporaryDirectory(prefix=".simplify-build-", dir=EXT) as temporary:
        work = Path(temporary)
        (work / "Report.json").write_text(json.dumps(report, indent=2) + "\n")
        valid, errors, warnings, report = ReportValidator().validate_report(str(work / "Report.json"))
        require(valid and not errors and not warnings, f"Report validation failed: {errors}, {warnings}")
        o = app.OCPE(allow_unaccelerated=True)
        report, native, oclp = o.c.check_compatibility(report)
        customized, disabled, needs_oclp = o.h.hardware_customization(report, DARWIN)
        require(not needs_oclp and not oclp, "Unexpected OCLP requirement")
        require(not any("GPU" in key for key in disabled), "GOP display GPU was disabled")
        o.ac.read_acpi_tables(str(ROOT / "research/hw_dump/baremetal_inventory/acpi"))
        require(o.ac.ensure_dsdt(), "ACPI input unavailable")
        o.ac.select_acpi_patches(customized, disabled)
        o.k.select_required_kexts(customized, DARWIN, needs_oclp, o.ac.patches)
        o.s.smbios_specific_options(customized, "MacPro7,1", DARWIN, o.ac.patches, o.k)
        selected = [k.name for k in o.k.kexts if k.checked]
        require(not set(selected) & {"WhateverGreen", "NootRX", "NootedRed", "SMCRadeonSensors"}, "Unexpected graphics kext")
        # Snapshot immutable package inputs, then use release 1.0.8 DEBUG throughout.
        for package in (REPO / "OCK_Files").iterdir():
            if package.is_dir() and package.name != "OpenCorePkg":
                ok, details = IntegrityChecker().verify_folder_integrity(str(package))
                require(ok, f"Package cache changed: {package.name}: {details}")
        cache = work / "cache"
        shutil.copytree(REPO / "OCK_Files", cache)
        shutil.rmtree(cache / "OpenCorePkg")
        shutil.copytree(OCBASE / "_dl/opencore-debug/src/X64/EFI", cache / "OpenCorePkg/EFI")
        shutil.copy2(OCBASE / "_dl/opencore-debug/src/Docs/Sample.plist", cache / "OpenCorePkg/EFI/OC/config.plist")
        for name in ("HfsPlus.efi", "apfs_aligned.efi"):
            shutil.copy2(REPO / "OCK_Files/OpenCorePkg/EFI/OC/Drivers" / name, cache / "OpenCorePkg/EFI/OC/Drivers" / name)
        o.k.ock_files_dir = str(cache)
        def pinned_patches(name, url):
            require(name == "AMD Vanilla Patches", "Unreviewed kernel patch source: " + name)
            return copy.deepcopy(plistlib.loads(amd_path.read_bytes())["Kernel"]["Patch"])
        o.co.g.get_kernel_patches = pinned_patches
        o.result_dir = str(work / "generated")
        o.build_opencore_efi(customized, disabled, "MacPro7,1", DARWIN, False)
        generated = work / "generated"
        config_path = generated / "EFI/OC/config.plist"
        config = plistlib.loads(config_path.read_bytes())
        raw_config = copy.deepcopy(config)
        (generated / "config-before-b840-profile.plist").write_bytes(config_path.read_bytes())
        # Preserve already verified board specifics; replace generic USB discovery.
        config["ACPI"]["Patch"].extend(copy.deepcopy(baseline["ACPI"]["Patch"]))
        config["ACPI"]["Add"] = [p for p in config["ACPI"]["Add"] if p["Path"] != "SSDT-USB-Reset.aml"]
        (generated / "EFI/OC/ACPI/SSDT-USB-Reset.aml").unlink()
        for name in ("USBToolBox.kext", "UTBDefault.kext", "CtlnaAHCIPort.kext"):
            shutil.rmtree(generated / "EFI/OC/Kexts" / name)
            config["Kernel"]["Add"] = [k for k in config["Kernel"]["Add"] if k["BundlePath"] != name]
        shutil.copytree(BASE / "EFI/OC/Kexts/USBMapB840.kext", generated / "EFI/OC/Kexts/USBMapB840.kext")
        usb_entry = next(k for k in baseline["Kernel"]["Add"] if k["BundlePath"] == "USBMapB840.kext")
        config["Kernel"]["Add"].append(copy.deepcopy(usb_entry))
        config["Booter"]["Quirks"]["DevirtualiseMmio"] = True
        config["Booter"]["MmioWhitelist"] = []  # F700 exception failed in boot8.
        config["PlatformInfo"]["Generic"] = copy.deepcopy(baseline["PlatformInfo"]["Generic"])
        config["Misc"]["Debug"] = copy.deepcopy(baseline["Misc"]["Debug"])
        config["Misc"]["Serial"] = copy.deepcopy(baseline["Misc"]["Serial"])
        config["Misc"]["Boot"]["HideAuxiliary"] = False
        config["NVRAM"]["WriteFlash"] = False
        config["NVRAM"]["Add"][GUID]["csr-active-config"] = bytes(4)
        config["NVRAM"]["Add"][GUID]["boot-args"] += " kextlog=0xffff"
        config["NVRAM"]["Delete"][GUID] = sorted(set(config["NVRAM"]["Delete"][GUID] + ["boot-args"]))
        config["UEFI"]["Output"] = copy.deepcopy(baseline["UEFI"]["Output"])
        # Keep only patches applicable to this actual installer kernel.
        version = (25, 6, 0)
        config["Kernel"]["Patch"] = [p for p in config["Kernel"]["Patch"]
            if (not p["MinKernel"] or tuple(map(int, p["MinKernel"].split("."))) <= version)
            and (not p["MaxKernel"] or tuple(map(int, p["MaxKernel"].split("."))) >= version)]
        for patch in config["Kernel"]["Patch"]:
            patch["Base"] = patch["Base"].strip()
        config_path.write_bytes(plistlib.dumps(config, sort_keys=False))
        require(config["Booter"]["Quirks"]["ResizeAppleGpuBars"] == 0, "ReBAR was not reduced for macOS")
        require(config["UEFI"]["Quirks"]["ResizeGpuBars"] == -1, "Unexpected global BAR resizing")
        hotplug = [p for p in config["Kernel"]["Patch"] if "IOPCIIsHotplugPort" in p["Comment"]]
        require(len(hotplug) == 1 and hotplug[0]["Enabled"], "Missing AM5 PCI enumeration patch")
        core = [p for p in config["Kernel"]["Patch"] if "cpuid_cores_per_package" in p["Comment"]]
        require(len(core) == 1 and core[0]["Replace"][1] == 8, "Incorrect physical core count")
        acpi_dir = generated / "EFI/OC/ACPI"
        for entry in config["ACPI"]["Add"]:
            data = (acpi_dir / entry["Path"]).read_bytes()
            require(entry["Enabled"] and data[:4] == b"SSDT" and sum(data) % 256 == 0, "Invalid generated SSDT")
        cpu_table = acpi_dir / "SSDT-PLUG-ALT.aml"
        subprocess.run([o.ac.acpi.iasl, "-d", str(cpu_table)], check=True, capture_output=True)
        cpu_dsl = cpu_table.with_suffix(".dsl")
        cpu_text = cpu_dsl.read_text()
        ids = [int(uid, 16) for uid in re.findall(r"Processor \([^,]+, (0x[0-9A-F]+),", cpu_text)]
        require(ids == list(range(16)), "CPU aliases do not match firmware logical processors 0..15")
        shutil.move(cpu_dsl, generated / "SSDT-PLUG-ALT.generated.dsl")
        # ocvalidate does not verify that referenced payload files actually exist.
        for section, key, directory in ((config["ACPI"], "Add", acpi_dir), (config["UEFI"], "Drivers", generated / "EFI/OC/Drivers")):
            for entry in section[key]:
                require((directory / entry["Path"]).is_file(), "Missing ACPI/UEFI payload: " + entry["Path"])
        for kext in config["Kernel"]["Add"]:
            bundle = generated / "EFI/OC/Kexts" / kext["BundlePath"]
            require((bundle / kext["PlistPath"]).is_file(), "Missing kext plist")
            require(not kext["ExecutablePath"] or (bundle / kext["ExecutablePath"]).is_file(), "Missing kext executable")
        for properties in config["DeviceProperties"]["Add"].values():
            require(not properties.get("disable-gpu"), "Display GPU unexpectedly disabled")
        require("-amd_no_dgpu_accel" in config["NVRAM"]["Add"][GUID]["boot-args"], "Missing AMD acceleration-disable argument")
        validator = subprocess.run([str(OCBASE / "_tools/ocvalidate"), str(config_path)], check=True, capture_output=True, text=True)
        (generated / "ocvalidate.txt").write_text(validator.stdout + validator.stderr)
        files = sorted(p for p in (generated / "EFI").rglob("*") if p.is_file())
        (generated / "SHA256SUMS-EFI.txt").write_text("".join(f"{digest(p)}  {p.relative_to(generated).as_posix()}\n" for p in files))
        (generated / "Report-Linux.json").write_text(json.dumps(original_report, indent=2) + "\n")
        (generated / "PREPARATION.json").write_text(json.dumps({
            "generator_commit": PIN, "local_patch": metadata,
            "opencore": "1.0.8 DEBUG", "darwin_target": DARWIN,
            "baseline_config_sha256": BASE_SHA, "config_sha256": digest(config_path),
            "amd_patch_sha256": AMD_SHA, "upstream_selected_kexts": selected,
            "profile_changed_keys": semantic_diff(raw_config, config),
            "changed_keys_from_boot8": semantic_diff(baseline, config),
            "gpu_identity": "1002-7590", "gpu_acceleration_supported": False,
            "cpu_alias_ids": ids, "firmware_tables_loaded": len(o.ac.acpi.acpi_tables),
            "efi_file_count": len(files), "ocvalidate_passed": True,
            "hardware_boot_tested": False, "deployed_to_usb": False,
            "bios_rebar": "Enabled", "bios_above4g": "Enabled", "bios_serial_com": "Disable before next boot",
        }, indent=2) + "\n")
        subprocess.run(["sha256sum", "-c", "SHA256SUMS-EFI.txt"], cwd=generated, check=True, capture_output=True)
        shutil.move(generated, output)
    print(f"Prepared and validated offline: {output}")
    print("Hardware boot remains untested. No USB or internal partition was written.")


if __name__ == "__main__":
    main()
