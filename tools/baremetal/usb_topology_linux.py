#!/usr/bin/env python3
"""Read-only Linux USB topology collector for planning a macOS USB map.

This is a support collector, not an official USBToolBox component. It reads
USB and PCI sysfs identity/topology attributes only. It never opens input
event devices, reads storage contents, or writes to a controller.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USB_DEVICES = Path("/sys/bus/usb/devices")
PCI_BDF_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])(?![0-9a-fA-F])")
ROOT_HUB_RE = re.compile(r"^usb(\d+)$")
PORT_RE = re.compile(r"^usb\d+-port(\d+)$")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def safe_text(value: str | None, limit: int = 100) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] or None


def pci_bdf(root_hub: Path) -> str | None:
    # Linux exposes the HCD's PCI address as the root hub's serial on this host.
    serial = read_text(root_hub / "serial")
    if serial and PCI_BDF_RE.fullmatch(serial):
        return serial.lower()

    # Fallback: the nearest PCI function in the resolved sysfs ancestry.
    matches = PCI_BDF_RE.findall(str(root_hub.resolve()))
    return matches[-1].lower() if matches else None


def pcidebug_decimal(bdf: str | None) -> str | None:
    """Format PCI BDF as USBToolBox's native decimal bus:device:function text."""
    if not bdf:
        return None
    _domain, bus, device, function = re.fullmatch(
        r"([0-9a-f]{4}):([0-9a-f]{2}):([0-9a-f]{2})\.([0-7])", bdf.lower()
    ).groups()
    return f"{int(bus, 16)}:{int(device, 16)}:{int(function, 16)}"


def speed_side(speed: str | None) -> str:
    try:
        mbps = float(speed or "")
    except ValueError:
        return "unknown"
    if mbps >= 5000:
        return "superspeed"
    if mbps >= 480:
        return "usb2"
    return "low-full-speed"


def device_speed(speed: str | None) -> str:
    side = speed_side(speed)
    if side == "superspeed":
        return "SuperSpeed"
    if side == "usb2":
        return "USB 2.0 high-speed"
    if side == "low-full-speed":
        return "USB 1.x/USB 2.0 low-or-full-speed"
    return "unknown"


def acpi_info(port: Path) -> dict[str, Any]:
    node = port / "firmware_node"
    if not node.exists():
        return {"path": None, "adr_hex": None, "adr_decimal": None, "node_name": None}
    resolved = node.resolve()
    path = read_text(resolved / "path")
    adr = read_text(resolved / "adr")
    try:
        adr_decimal = int(adr, 0) if adr is not None else None
    except ValueError:
        adr_decimal = None
    return {
        "path": path,
        "adr_hex": adr,
        "adr_decimal": adr_decimal,
        "node_name": path.rsplit(".", 1)[-1] if path else resolved.name,
    }


def physical_location(port: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    location = port / "physical_location"
    if not location.is_dir():
        return result
    for child in sorted(location.iterdir()):
        value = read_text(child)
        if value is not None:
            result[child.name] = value
    return result


def usb_devices_by_root_port(busnum: str) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    try:
        entries = list(USB_DEVICES.iterdir())
    except OSError:
        return result

    for path in entries:
        # Device nodes have idVendor/idProduct; interface nodes do not. This
        # avoids reading configuration descriptors or interface event streams.
        vid = read_text(path / "idVendor")
        pid = read_text(path / "idProduct")
        if vid is None or pid is None:
            continue
        if read_text(path / "busnum") != busnum:
            continue
        devpath = read_text(path / "devpath")
        if not devpath or devpath == "0":
            continue
        try:
            root_port = int(devpath.split(".", 1)[0], 10)
        except ValueError:
            continue

        result.setdefault(root_port, []).append(
            {
                "sysfs_name": path.name,
                "route": devpath,
                "vid_pid": f"{vid.lower()}:{pid.lower()}",
                "manufacturer": safe_text(read_text(path / "manufacturer")),
                "product": safe_text(read_text(path / "product")),
                "speed_mbps": read_text(path / "speed"),
                "speed_class": device_speed(read_text(path / "speed")),
                "device_class_hex": read_text(path / "bDeviceClass"),
            }
        )

    for devices in result.values():
        devices.sort(key=lambda item: item["route"])
    return result


def root_hubs() -> list[Path]:
    try:
        entries = list(USB_DEVICES.iterdir())
    except OSError:
        return []
    hubs = [p for p in entries if ROOT_HUB_RE.fullmatch(p.name)]
    return sorted(hubs, key=lambda p: int(ROOT_HUB_RE.fullmatch(p.name).group(1)))


def collect_snapshot() -> dict[str, Any]:
    controllers: dict[str, dict[str, Any]] = {}
    for hub in root_hubs():
        bdf = pci_bdf(hub)
        if not bdf:
            continue
        busnum = read_text(hub / "busnum") or ""
        maxchild = read_text(hub / "maxchild")
        root_speed = read_text(hub / "speed")
        side = speed_side(root_speed)
        match = ROOT_HUB_RE.fullmatch(hub.name)
        hub_bus = int(match.group(1))
        iface = next((p for p in hub.glob("*:1.0") if p.is_dir()), None)
        if iface is None:
            continue

        controller = controllers.setdefault(
            bdf,
            {
                "pci_bdf": bdf,
                "usbtoolbox_pcidebug_decimal": pcidebug_decimal(bdf),
                "sysfs_controller_path": str(hub.resolve().parent),
                "root_hubs": [],
            },
        )
        root_hub_record: dict[str, Any] = {
            "linux_bus_number": int(busnum) if busnum.isdigit() else busnum,
            "sysfs_root_hub": hub.name,
            "root_hub_speed_mbps": root_speed,
            "side": side,
            "maxchild": int(maxchild) if maxchild and maxchild.isdigit() else maxchild,
            "ports": [],
        }
        devices_by_port = usb_devices_by_root_port(busnum)

        ports = []
        for port in iface.iterdir():
            port_match = PORT_RE.fullmatch(port.name)
            if not port_match:
                continue
            linux_port = int(port_match.group(1))
            acpi = acpi_info(port)
            peer = port / "peer"
            peer_record = None
            if peer.exists():
                peer_path = peer.resolve()
                peer_match = PORT_RE.fullmatch(peer_path.name)
                peer_hub = peer_path.parent.parent if len(peer_path.parents) > 1 else None
                peer_bdf = pci_bdf(peer_hub) if peer_hub and peer_hub.name.startswith("usb") else None
                peer_bus_match = ROOT_HUB_RE.fullmatch(peer_hub.name) if peer_hub else None
                peer_speed = read_text(peer_hub / "speed") if peer_bus_match else None
                peer_record = {
                    "pci_bdf": peer_bdf,
                    "linux_bus_number": int(peer_bus_match.group(1)) if peer_bus_match else None,
                    "root_hub_side": speed_side(peer_speed),
                    "linux_port": int(peer_match.group(1)) if peer_match else None,
                    "acpi_adr_hex": acpi_info(peer_path)["adr_hex"],
                    "acpi_adr_decimal": acpi_info(peer_path)["adr_decimal"],
                }

            ports.append(
                {
                    "linux_root_port": linux_port,
                    "acpi_path": acpi["path"],
                    "acpi_child_name": acpi["node_name"],
                    "acpi_adr_hex": acpi["adr_hex"],
                    "acpi_raw_port_number": acpi["adr_decimal"],
                    "connect_type_from_firmware": read_text(port / "connect_type"),
                    "location_raw_hex": read_text(port / "location"),
                    "physical_location_from_firmware": physical_location(port),
                    "peer_companion": peer_record,
                    "devices": devices_by_port.get(linux_port, []),
                }
            )
        ports.sort(key=lambda item: item["linux_root_port"])
        root_hub_record["ports"] = ports
        controller["root_hubs"].append(root_hub_record)

    for controller in controllers.values():
        controller["root_hubs"].sort(key=lambda item: (item["side"], item["linux_bus_number"]))

    debugfs_usb = Path("/sys/kernel/debug/usb")
    debugfs_xhci = sorted(str(p) for p in debugfs_usb.glob("xhci*") if p.exists()) if debugfs_usb.exists() else []
    return {
        "schema": "linux-usb-topology-support/v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "read_scope": [
            "/sys/bus/usb/devices topology and identity attributes",
            "/sys/bus/pci/devices-derived PCI BDF from USB root hub ancestry",
            "ACPI firmware_node path/adr and read-only port location attributes",
        ],
        "not_read": ["input events or keycodes", "USB storage contents", "peripheral serial strings", "raw MMIO"],
        "debugfs": {
            "debugfs_mounted": Path("/sys/kernel/debug").is_mount(),
            "usb_directory_available": debugfs_usb.exists(),
            "xhci_nodes": debugfs_xhci,
        },
        "controllers": sorted(controllers.values(), key=lambda item: item["pci_bdf"]),
    }


def stable_devices(
    snapshot: dict[str, Any], match_vid_pid: str | None = None
) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    result: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for controller in snapshot["controllers"]:
        for hub in controller["root_hubs"]:
            for port in hub["ports"]:
                for device in port["devices"]:
                    if match_vid_pid and device["vid_pid"].lower() != match_vid_pid.lower():
                        continue
                    key = (controller["pci_bdf"], hub["side"], port["linux_root_port"], device["route"])
                    result[key] = {
                        "controller_bdf": controller["pci_bdf"],
                        "usbtoolbox_pcidebug_decimal": controller["usbtoolbox_pcidebug_decimal"],
                        "root_hub_side": hub["side"],
                        "linux_root_port": port["linux_root_port"],
                        "acpi_raw_port_number": port["acpi_raw_port_number"],
                        "acpi_path": port["acpi_path"],
                        "peer_companion": port["peer_companion"],
                        "physical_label": None,
                        "physical_label_source": None,
                        **device,
                    }
    return result


def print_inventory(snapshot: dict[str, Any]) -> None:
    print("Controller        pcidebug    Root hub    Linux p  ACPI raw  Peer       Device")
    print("----------------  ----------  ----------  -------  --------  ---------  ------------------------------")
    for controller in snapshot["controllers"]:
        for hub in controller["root_hubs"]:
            for port in hub["ports"]:
                peer = port["peer_companion"]
                peer_text = "-"
                if peer:
                    peer_side = "SS" if peer["root_hub_side"] == "superspeed" else "USB2"
                    peer_text = f"{peer_side}:p{peer['linux_port']}@raw{peer['acpi_adr_decimal']}"
                device_text = "; ".join(
                    f"{d['vid_pid']} {d['product'] or ''} ({d['speed_mbps']} Mb/s)".strip()
                    for d in port["devices"]
                ) or "-"
                acpi_raw = port["acpi_raw_port_number"]
                print(
                    f"{controller['pci_bdf']:<16}  {controller['usbtoolbox_pcidebug_decimal'] or '-':<10}  "
                    f"{hub['side']:<10}  {port['linux_root_port']:>7}  "
                    f"{str(acpi_raw if acpi_raw is not None else '-'):>8}  "
                    f"{peer_text:<9}  {device_text}"
                )
    debugfs = snapshot["debugfs"]
    print(
        "\nDebugfs USB/xHCI: "
        + (", ".join(debugfs["xhci_nodes"]) if debugfs["xhci_nodes"] else "nessun nodo xHCI esposto")
    )
    print("I numeri Linux root-port, ACPI _ADR raw e PCI pcidebug sono campi distinti.")


def run_watch(output: Path, interval: float, match_vid_pid: str | None, prompt_label: bool) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    old = stable_devices(collect_snapshot(), match_vid_pid)
    # Never truncate an existing log: each physical-port pass should remain a
    # separate, auditable capture.
    try:
        with output.open("x", encoding="utf-8"):
            pass
    except FileExistsError:
        print(f"Il file esiste già; scegline uno nuovo: {output}", file=sys.stderr)
        return 2
    print(f"Osservo solo identità/topologia USB; log: {output}")
    print("Nessun accesso a input event/keycode o contenuti storage. Ctrl-C termina.")
    if match_vid_pid:
        print(f"Filtro dispositivo: {match_vid_pid.lower()}")
    labels: dict[tuple[str, str, int, str], str | None] = {}
    try:
        while True:
            time.sleep(interval)
            new = stable_devices(collect_snapshot(), match_vid_pid)
            for key in sorted(set(old) - set(new)):
                record = {"event": "disconnected", **old[key]}
                record["physical_label"] = labels.get(key)
                record["physical_label_source"] = "user" if labels.get(key) else None
                emit_watch_record(record, output)
            for key in sorted(set(new) - set(old)):
                physical_label = None
                if prompt_label:
                    physical_label = input("Etichetta fisica della presa (invio = da annotare dopo): ").strip() or None
                labels[key] = physical_label
                record = {"event": "connected", **new[key]}
                record["physical_label"] = physical_label
                record["physical_label_source"] = "user" if physical_label else None
                emit_watch_record(record, output)
            old = new
    except KeyboardInterrupt:
        print("Watch terminato.")
        return 0


def emit_watch_record(record: dict[str, Any], output: Path) -> None:
    record["timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(
        f"{record['timestamp_utc']} {record['event']}: {record['controller_bdf']} "
        f"{record['root_hub_side']} Linux p{record['linux_root_port']} "
        f"ACPI _ADR {record['acpi_raw_port_number']} {record['vid_pid']} "
        f"{record['product'] or ''} @ {record['route']}"
    )


def print_guide() -> None:
    print(
        "Flusso breve per attribuire i jack senza leggere tasti o file USB:\n"
        "1. Lascia collegato almeno un input Linux funzionante; sposta un solo dispositivo alla volta.\n"
        "2. Lascia la NuPhy cablata collegata; avvia `python3 tools/baremetal/usb_topology_linux.py watch --output /tmp/usb-b840-pass1-20261025-mouse.jsonl --match-vidpid 3554:f576 --prompt-label`.\n"
        "3. Sposta solo il ricevitore del mouse GravaStar, una presa alla volta, e annota il jack fisico.\n"
        "4. Il log mostra BDF, root-port Linux, ACPI _ADR, peer, etichetta inserita e route USB completo.\n"
        "   Le quattro USB2 posteriori dietro GL850 possono condividere una sola porta root: la route\n"
        "   distingue i downstream dell'hub; non aspettarti un root-port separato per ciascun jack.\n"
        "5. Senza un dispositivo USB3 collegato, il lato SuperSpeed resta dichiarato da peer/ACPI ma\n"
        "   non è un test di negoziazione a 5/10 Gbit/s. Non aprire file del dispositivo di archiviazione.\n"
        "6. Non scollegare l'unico input disponibile. Questo strumento osserva solo sysfs USB e non\n"
        "   registra tasti, mouse o eventi input.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="stampa porte, companion, ACPI _ADR e dispositivi già presenti")
    watch = sub.add_parser("watch", help="registra solo inserimenti/rimozioni e identità USB")
    watch.add_argument("--output", type=Path, default=Path("/tmp/usb-ports.jsonl"))
    watch.add_argument("--interval", type=float, default=0.5)
    watch.add_argument("--match-vidpid", help="registra solo un VID:PID, per esempio 3554:f576")
    watch.add_argument("--prompt-label", action="store_true", help="chiede l'etichetta del jack dopo ogni inserimento")
    sub.add_parser("guide", help="stampa il flusso di mappatura fisica")
    args = parser.parse_args()

    if args.command == "inventory":
        snapshot = collect_snapshot()
        print_inventory(snapshot)
        return 0
    if args.command == "watch":
        if args.interval <= 0:
            parser.error("--interval deve essere maggiore di zero")
        if args.match_vidpid and not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", args.match_vidpid):
            parser.error("--match-vidpid deve avere forma VVVV:PPPP, ad esempio 3554:f576")
        return run_watch(args.output, args.interval, args.match_vidpid, args.prompt_label)
    if args.command == "guide":
        print_guide()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
