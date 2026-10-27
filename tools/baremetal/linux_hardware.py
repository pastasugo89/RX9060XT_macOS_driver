"""Read-only Linux hardware export for OpCore Simplify (AMD desktop scope).

No disk contents, MAC addresses, DMI serials, EDIDs or Wi-Fi credentials are read.
This collector reports hardware, never graphics compatibility or boot success.
"""
import json
import re
import shlex
import subprocess
from pathlib import Path


def read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return default


def pci_path(device):
    parts = device.resolve().parts
    root = next((p for p in parts if re.fullmatch(r"pci[0-9a-f]{4}:[0-9a-f]{2}", p)), None)
    if root is None:
        raise ValueError(f"Cannot resolve PCI root for {device}")
    root_path = Path(*parts[:parts.index(root) + 1])
    uid = read(root_path / "firmware_node/uid")
    if not uid:
        raise ValueError(f"Missing ACPI PCI root UID: {root_path}")
    result = f"PciRoot(0x{int(uid, 0):x})"
    for part in parts[parts.index(root) + 1:]:
        match = re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:([0-9a-f]{2})\.([0-7])", part)
        if match:
            result += f"/Pci(0x{int(match[1], 16):x},0x{int(match[2]):x})"
    return result


def collect():
    cpu_records = [dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
                   for block in Path("/proc/cpuinfo").read_text().split("\n\n") if block.strip()]
    cpu_records = [{k.strip(): v.strip() for k, v in record.items()} for record in cpu_records]
    first = cpu_records[0]
    if first.get("vendor_id") != "AuthenticAMD":
        raise ValueError("This Linux collector currently supports AMD desktops only; import a Hardware Sniffer report for other hardware.")
    # AMD Family 19h, model 61h: the observed Raphael desktop CPU family.
    if (first.get("cpu family"), first.get("model")) != ("25", "97"):
        raise ValueError("CPU codename is not mapped by this scoped collector; import a complete hardware report.")
    dmi = Path("/sys/class/dmi/id")
    board = f"{read(dmi / 'board_vendor')} {read(dmi / 'board_name')}".strip()
    chipset = re.search(r"\b(?:B[34568]\d{2}|X[3678]\d{2}E?|A[3568]\d{2})\b", board)
    if not chipset:
        raise ValueError("Cannot identify chipset from motherboard model; import a complete report.")
    if not Path("/sys/firmware/efi").is_dir():
        raise ValueError("Run the collector from a UEFI Linux boot.")
    secure_files = list(Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"))
    if len(secure_files) != 1:
        raise ValueError("Cannot read UEFI SecureBoot state.")
    secure = secure_files[0].read_bytes()
    if len(secure) != 5 or secure[4] not in (0, 1):
        raise ValueError("Unexpected UEFI SecureBoot variable format.")
    cores = {(r["physical id"], r["core id"]) for r in cpu_records}
    flags = first["flags"].upper().replace("SSE4_1", "SSE4.1").replace("SSE4_2", "SSE4.2")
    report = {
        "Motherboard": {"Name": board, "Chipset": chipset[0], "Platform": "Desktop"},
        "BIOS": {"Version": read(dmi / "bios_version"), "Release Date": read(dmi / "bios_date"),
                 "Firmware Type": "UEFI", "Secure Boot": "Enabled" if secure[4] else "Disabled"},
        "CPU": {"Manufacturer": "AMD", "Processor Name": first["model name"], "Codename": "Raphael",
                "Core Count": str(len(cores)), "CPU Count": str(len({c[0] for c in cores})),
                "SIMD Features": flags},
        "GPU": {}, "Network": {}, "USB Controllers": {}, "Storage Controllers": {},
        "Input": {}, "System Devices": {}, "Monitor": {},
    }
    names = {}
    output = subprocess.run(["lspci", "-Dnnmm"], check=True, capture_output=True, text=True).stdout
    for line in output.splitlines():
        tokens = shlex.split(line)
        if len(tokens) >= 4:
            names[tokens[0]] = tokens[3]
    gpu_devices = {}
    for device in sorted(Path("/sys/bus/pci/devices").iterdir()):
        vendor, dev = read(device / "vendor")[2:].upper(), read(device / "device")[2:].upper()
        device_class = int(read(device / "class"), 16)
        name = f"{names.get(device.name, vendor + ':' + dev)} ({device.name})"
        props = {"Bus Type": "PCI", "Device ID": f"{vendor}-{dev}", "PCI Path": pci_path(device)}
        subsystem_vendor = read(device / "subsystem_vendor")[2:].upper()
        subsystem_device = read(device / "subsystem_device")[2:].upper()
        props["Subsystem ID"] = subsystem_device + subsystem_vendor
        acpi = read(device / "firmware_node/path").replace("_SB_", "_SB")
        if acpi:
            props["ACPI Path"] = acpi
        category = ("GPU" if device_class >> 16 == 3 else "Network" if device_class >> 16 == 2
                    else "USB Controllers" if device_class >> 8 == 0x0C03
                    else "Storage Controllers" if device_class >> 16 == 1 else "System Devices")
        if category == "GPU":
            if vendor != "1002":
                raise ValueError("This scoped collector currently exports AMD GPUs only.")
            codename = re.search(r"Navi \d+", name)
            if not codename:
                raise ValueError(f"Cannot identify GPU codename: {name}")
            props.update({"Manufacturer": "AMD", "Codename": codename[0], "Device Type": "Discrete GPU"})
            # Current assigned BAR0 size, not merely support for resize.
            start, end, _ = device.joinpath("resource").read_text().splitlines()[0].split()
            large_bar = int(end, 16) - int(start, 16) + 1 > 256 * 1024**2
            props["Resizable BAR"] = "Enabled" if (device / "resource0_resize").exists() and large_bar else "Disabled"
            props.pop("Bus Type")
            gpu_devices[device.resolve()] = name
        report[category][name] = props
    for connector in sorted(Path("/sys/class/drm").glob("card*-*")):
        if read(connector / "status") != "connected":
            continue
        card = connector.name.split("-", 1)[0]
        gpu = gpu_devices.get((Path("/sys/class/drm") / card / "device").resolve())
        modes = read(connector / "modes").splitlines()
        kind = connector.name.split("-", 1)[1].split("-", 1)[0]
        if gpu and modes:
            report["Monitor"][connector.name] = {"Connector Type": kind, "Resolution": modes[0], "Connected GPU": gpu}
    for event in sorted(Path("/sys/class/input").glob("event*")):
        device = event / "device"
        if read(device / "id/bustype") == "0003":
            report["Input"][f"{read(device / 'name')} ({event.name})"] = {"Bus Type": "USB"}
    if not report["GPU"]:
        raise ValueError("No identifiable AMD display controller found.")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = collect()
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"Exported read-only hardware report: {args.output}")
