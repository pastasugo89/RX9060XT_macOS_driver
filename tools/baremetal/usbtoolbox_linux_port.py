#!/usr/bin/env python3
"""Linux sysfs adapter for the pinned, official USBToolBox map generator.

The upstream project does not support Linux discovery. This adapter reads the
existing read-only sysfs collector, translates verified ACPI _ADR ports into
USBToolBox's controller/port model, and calls upstream BaseUSBMap.build_kext().
It does not read input events, storage contents, peripheral serials, or MMIO.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UPSTREAM_URL = "https://github.com/USBToolBox/tool.git"
UPSTREAM_COMMIT = "0c6823a2c643a4488888938451194723dc9ae29a"
DEFAULT_UPSTREAM = Path("research/ext/usbtoolbox-tool")
DEFAULT_OUTPUT = Path("research/ext/usbtoolbox-linux-port-candidate")
MODEL_IDENTIFIER = "MacPro7,1"
PCI_DEVICES = Path("/sys/bus/pci/devices")
BOOT15_CONFIG_SHA256 = "7bbf4e3e3eaf7ec13aa52780c82412a9b2a5b9dac8de98cba990fb4d884cdafb"
TAHOE_PORT_ALIASES = {
    "usb-port-number": "port",
    "usb-port-type": "UsbConnector",
}

# These are only used to avoid installing upstream's terminal-color and cursor
# packages on Linux. The actual menu entry points are replaced by strict
# noninteractive shims below; no keyboard or terminal input is consumed.
def install_display_only_dependency_shims() -> None:
    if importlib.util.find_spec("termcolor2") is None:
        termcolor = types.ModuleType("termcolor2")

        class PlainColor:
            def __init__(self, value: Any):
                self.value = str(value)

            def __getattr__(self, _name: str) -> "PlainColor":
                return self

            def __str__(self) -> str:
                return self.value

        termcolor.c = lambda value: PlainColor(value)  # type: ignore[attr-defined]
        sys.modules["termcolor2"] = termcolor

    if importlib.util.find_spec("ansiescapes") is None:
        ansi = types.ModuleType("ansiescapes")
        ansi.cursorSavePosition = ""  # type: ignore[attr-defined]
        ansi.eraseDown = ""  # type: ignore[attr-defined]
        ansi.cursorPrevLine = ""  # type: ignore[attr-defined]
        sys.modules["ansiescapes"] = ansi


def load_upstream(upstream: Path):
    upstream = upstream.resolve()
    if not (upstream / "base.py").is_file() or not (upstream / "resources/Info.plist").is_file():
        raise ValueError(f"USBToolBox checkout incompleto: {upstream}")
    revision = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != UPSTREAM_COMMIT:
        raise ValueError(f"USBToolBox deve essere pinned a {UPSTREAM_COMMIT}; trovato {revision}")
    remote = subprocess.run(
        ["git", "-C", str(upstream), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if remote.rstrip("/") not in {UPSTREAM_URL, UPSTREAM_URL.removesuffix(".git")}:
        raise ValueError(f"Remote upstream inatteso: {remote}")

    install_display_only_dependency_shims()
    sys.path.insert(0, str(upstream))
    import base as upstream_base  # noqa: PLC0415
    from Scripts import shared, utils  # noqa: PLC0415

    return upstream_base, shared, utils, revision


def pci_identity(bdf: str) -> tuple[str, str, str]:
    directory = PCI_DEVICES / bdf
    vendor = read_sysfs(directory / "vendor")
    device = read_sysfs(directory / "device")
    pci_class = read_sysfs(directory / "class")
    if not vendor or not device or not pci_class:
        raise ValueError(f"PCI identity incompleta per {bdf}")
    return vendor.removeprefix("0x").lower(), device.removeprefix("0x").lower(), pci_class.removeprefix("0x").lower()


def read_sysfs(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def classify_port(
    controller_bdf: str,
    raw_index: int,
    side: str,
    peer: dict[str, Any] | None,
    devices: list[dict[str, Any]],
    usb_types: Any,
) -> tuple[Any, str, str, str]:
    ids = {device["vid_pid"].lower() for device in devices}

    if controller_bdf == "0000:05:00.0" and raw_index == 9 and "0db0:0076" in ids:
        return usb_types.Internal, "observed", "Mystic Light USB device 0db0:0076 on this ACPI raw port", "internal"
    if controller_bdf == "0000:05:00.0" and raw_index == 10 and "0489:e10a" in ids:
        return usb_types.Internal, "observed", "Foxconn Bluetooth USB device 0489:e10a on this ACPI raw port", "internal"
    if controller_bdf == "0000:0b:00.0" and raw_index == 1 and "05e3:0608" in ids:
        return usb_types.Internal, "observed", "Internal GL850 hub 05e3:0608 is attached to this root port", "internal"

    if peer is not None:
        return (
            usb_types.USB3TypeA,
            "assumed",
            "USB2/SuperSpeed companion pair; USB 3 Type-A is the inclusive default. A Type-C jack may be among these ports; the physical jack is not identified.",
            "external_usb3_default_type_a",
        )

    if side == "usb2" and controller_bdf == "0000:05:00.0" and 11 <= raw_index <= 14:
        return (
            usb_types.USBTypeA,
            "deduced",
            "USB2-only root port; the MSI manual lists four USB2 front-panel Type-A ports. This count-level match does not identify this raw index with a physical jack.",
            "usb2_type_a_by_manual_count",
        )

    if side == "usb2":
        return (
            usb_types.USBTypeA,
            "assumed",
            "USB2-only root port with no physical jack label; retained as USB Type-A to keep the port available.",
            "unknown_usb2_retained_type_a_default",
        )

    # Keep an unexpected port represented instead of silently excluding it.
    return (
        usb_types.USB3TypeA,
        "assumed",
        "No physical connector identity is available; retained with USB 3 Type-A default so the port remains mapped.",
        "unknown_retained_type_a_default",
    )


def speed_enum(speed_mbps: str | None, speeds: Any) -> Any:
    try:
        rate = float(speed_mbps or "")
    except ValueError:
        return speeds.Unknown
    if rate < 10:
        return speeds.LowSpeed
    if rate < 100:
        return speeds.FullSpeed
    if rate < 1000:
        return speeds.HighSpeed
    return speeds.SuperSpeed


def make_upstream_controllers(snapshot: dict[str, Any], shared: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    controllers_by_bdf: dict[str, dict[str, Any]] = {}
    port_metadata: list[dict[str, Any]] = []
    raw_port_owners: set[tuple[str, int]] = set()
    for observed in snapshot["controllers"]:
        bdf = observed["pci_bdf"]
        vendor, device, pci_class = pci_identity(bdf)
        if not pci_class.startswith("0c0330"):
            continue
        controller_path = next(
            (p.get("acpi_path") for h in observed["root_hubs"] for p in h["ports"] if p.get("acpi_path")),
            None,
        )
        acpi_controller_name = controller_path.rpartition(".RHUB.")[0].rsplit(".", 1)[-1] if controller_path else None
        record = {
            "name": re.sub(
                r"[^A-Za-z0-9_]+",
                "_",
                acpi_controller_name or f"XHCI_{bdf.replace(':', '_').replace('.', '_')}",
            ),
            # Deliberately omit identifiers.bdf/acpi_path. USBToolBox's real
            # native matcher then selects the unique PCI vendor:device ID.
            "identifiers": {"pci_id": [vendor, device]},
            "class": shared.USBControllerTypes.XHCI,
            "ports": [],
        }
        if record["name"] in {c["name"] for c in controllers_by_bdf.values()}:
            raise ValueError(f"Nome controller ACPI duplicato: {record['name']}")

        for hub in observed["root_hubs"]:
            side = hub["side"]
            if side not in {"usb2", "superspeed"}:
                continue
            usb_class = shared.USBDeviceSpeeds.HighSpeed if side == "usb2" else shared.USBDeviceSpeeds.SuperSpeed
            for port in hub["ports"]:
                raw_index = port.get("acpi_raw_port_number")
                if not isinstance(raw_index, int) or not 1 <= raw_index <= 15:
                    raise ValueError(f"_ADR raw non valido su {bdf}: {port.get('acpi_raw_port_number')}")
                raw_key = (bdf, raw_index)
                if raw_key in raw_port_owners:
                    raise ValueError(f"_ADR raw {raw_index} duplicato sul controller {bdf}")
                raw_port_owners.add(raw_key)

                peer = port.get("peer_companion")
                connector, confidence, explanation, classification = classify_port(
                    bdf, raw_index, side, peer, port["devices"], shared.USBPhysicalPortTypes
                )
                device_records = []
                for device_record in port["devices"]:
                    product = device_record.get("product") or device_record["vid_pid"]
                    device_records.append(
                        {
                            "name": f"{product} [{device_record['vid_pid']}]" if product != device_record["vid_pid"] else device_record["vid_pid"],
                            "speed": speed_enum(device_record.get("speed_mbps"), shared.USBDeviceSpeeds),
                            "devices": [],
                        }
                    )

                mapped_port = {
                    "name": f"{'SS' if side == 'superspeed' else 'HS'}{raw_index:02d}",
                    "comment": f"Linux ACPI _ADR raw {raw_index}; {confidence} connector classification: {explanation}",
                    "index": raw_index,
                    "class": usb_class,
                    "type": None,
                    "guessed": connector,
                    "devices": device_records,
                    "selected": True,
                }
                record["ports"].append(mapped_port)
                port_metadata.append(
                    {
                        "controller_pci_bdf_linux": bdf,
                        "controller_pci_id": f"{vendor}:{device}",
                        "controller_acpi_name": record["name"],
                        "root_hub_side": side,
                        "linux_root_port": port["linux_root_port"],
                        "linux_acpi_path": port.get("acpi_path"),
                        "acpi_adr_raw_port_number": raw_index,
                        "peer_companion": peer,
                        "connector_type": int(connector),
                        "connector_classification": classification,
                        "classification_confidence": confidence,
                        "classification_basis": explanation,
                        "devices_observed_by_usb_id_only": [
                            {k: d.get(k) for k in ("vid_pid", "product", "speed_mbps", "route")}
                            for d in port["devices"]
                        ],
                        "selected": True,
                    }
                )

        record["ports"].sort(key=lambda p: p["index"])
        controllers_by_bdf[bdf] = record

    if not controllers_by_bdf:
        raise ValueError("Nessun controller xHCI PCI disponibile in sysfs")
    controllers = sorted(controllers_by_bdf.values(), key=lambda c: c["name"])
    pci_ids = [tuple(c["identifiers"]["pci_id"]) for c in controllers]
    if len(pci_ids) != len(set(pci_ids)):
        raise ValueError("PCI vendor:device non univoco; il matcher nativo USBToolBox non può selezionarlo senza BDF")
    return controllers, port_metadata


class ControlledBuilderPrompts:
    """Strict mocks for the two upstream UI surfaces used by build_kext()."""

    def __init__(self, utils: Any, model: str):
        self.utils = utils
        self.model = model
        self.model_prompts = 0
        self.build_menus = 0

        owner = self

        class ModelPrompt:
            def __init__(self, title: str, prompt: str, _details: Any = None):
                if title != "Enter Model Identifier" or prompt != "Enter the model identifier: ":
                    raise RuntimeError(f"Prompt upstream inatteso: {title!r} / {prompt!r}")

            def start(self) -> str:
                owner.model_prompts += 1
                return owner.model

        class BuildMenu:
            EXIT_MENU = utils.TUIMenu.EXIT_MENU

            def __init__(self, title: str, prompt: str, *_args: Any, **_kwargs: Any):
                if title != "Building USBMap" or prompt != "Select an option: ":
                    raise RuntimeError(f"Menu upstream inatteso: {title!r} / {prompt!r}")
                owner.build_menus += 1

            def head(self) -> None:
                return None

            def print_options(self) -> None:
                return None

            def select(self) -> Any:
                return self.EXIT_MENU

        self.ModelPrompt = ModelPrompt
        self.BuildMenu = BuildMenu

    def install(self) -> None:
        self.utils.TUIOnlyPrint = self.ModelPrompt
        self.utils.TUIMenu = self.BuildMenu

    def validate(self) -> None:
        if self.model_prompts != 1 or self.build_menus != 1:
            raise RuntimeError(
                f"Superfici UI upstream inattese: model={self.model_prompts}, menu build={self.build_menus}"
            )


def generate_candidate(upstream: Path, output: Path, model: str) -> Path:
    if model != MODEL_IDENTIFIER:
        raise ValueError(f"Per questa EFI il modello registrato è {MODEL_IDENTIFIER}; ricevuto {model}")
    if output.exists():
        raise FileExistsError(f"L'output esiste già; non verrà sovrascritto: {output}")

    base_module, shared, utils, upstream_revision = load_upstream(upstream)
    from usb_topology_linux import collect_snapshot  # noqa: PLC0415

    snapshot = collect_snapshot()
    controllers, port_metadata = make_upstream_controllers(snapshot, shared)
    counts = {c["name"]: len(c["ports"]) for c in controllers}
    expected_counts = {"XH00": 14, "XHC0": 4, "XHC1": 4, "XHC2": 1}
    if counts != expected_counts:
        raise ValueError(f"Conteggi porte inattesi per la topologia B840 corrente: {counts}; attesi {expected_counts}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    old_current_dir = shared.current_dir
    try:
        shared.current_dir = stage
        builder = base_module.BaseUSBMap.__new__(base_module.BaseUSBMap)
        builder.utils = utils.Utils("USBToolBox Linux adapter")
        builder.controllers = controllers
        builder.controllers_historical = controllers
        builder.json_path = stage / "usb.json"
        builder.settings_path = stage / "settings.json"
        builder.settings = {
            "show_friendly_types": True,
            "use_native": True,
            "use_legacy_native": False,
            "add_comments_to_map": True,
            "auto_bind_companions": False,
        }

        prompt_guard = ControlledBuilderPrompts(utils, model)
        old_tui_menu = utils.TUIMenu
        old_tui_print = utils.TUIOnlyPrint
        prompt_guard.install()
        try:
            result = base_module.BaseUSBMap.build_kext(builder)
        finally:
            utils.TUIMenu = old_tui_menu
            utils.TUIOnlyPrint = old_tui_print
        prompt_guard.validate()
        if result is not True:
            raise RuntimeError("USBToolBox BaseUSBMap.build_kext() non ha completato la generazione")

        map_path = stage / "USBMap.kext/Contents/Info.plist"
        if not map_path.is_file():
            raise RuntimeError("Il builder ufficiale non ha creato USBMap.kext/Contents/Info.plist")
        plist = plistlib.loads(map_path.read_bytes())
        tahoe_property_count = add_tahoe_port_aliases(plist)
        map_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))
        verify_generated_plist(plist, controllers, shared)

        metadata = {
            "schema": "usbtoolbox-linux-port-candidate/v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "implementation": "local Linux adapter; not an official USBToolBox platform",
            "upstream": {
                "repository": UPSTREAM_URL,
                "commit": upstream_revision,
                "license": "MIT; see upstream LICENSE",
                "generator": "BaseUSBMap.build_kext",
                "native_output": True,
                "runtime_kext_required": False,
            },
            "target_model": model,
            "controller_match_strategy": "USBToolBox native IOParentMatch with unique PCI vendor:device ID; Linux BDF is metadata only",
            "linux_inventory_source": "read-only sysfs USB topology, PCI identity and ACPI firmware_node path/_ADR",
            "assumption_policy": "all discovered ports are selected; non-internal connector types are provisional and retained",
            "tahoe_port_schema": {
                "added_properties": TAHOE_PORT_ALIASES,
                "conversion": "copy the existing legacy property values without changing their type or contents",
                "source_basis": "USBToolBox/kext 1.2.0 USBToolBox.cpp fixMapForTahoe() copies port to usb-port-number and UsbConnector to usb-port-type for Darwin major >= 25",
                "properties_added": tahoe_property_count,
            },
            "controller_port_counts": counts,
            "ports": port_metadata,
            "read_scope": snapshot.get("read_scope"),
            "not_read": snapshot.get("not_read"),
            "physical_jack_limit": "MSI manual establishes connector counts/types but not the raw-index-to-jack mapping; Type-C jack identity/switch behavior is unknown.",
        }
        (stage / "porting-metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (stage / "UPSTREAM-NOTICE.txt").write_text(
            "USBToolBox source is MIT-licensed. This candidate was generated by the official USBToolBox BaseUSBMap.build_kext() at the pinned commit in porting-metadata.json.\n"
            "The local Linux adapter adds Tahoe compatibility aliases using the same legacy-to-new property copies as USBToolBox kext 1.2.0 fixMapForTahoe(); this post-processing is not part of the pinned USBToolBox tool source.\n"
            "The Linux sysfs discovery adapter and connector classifications are local, provisional work; USBToolBox upstream does not claim Linux support. See LICENSE in the pinned source checkout.\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
        return output
    except Exception:
        if stage.exists():
            import shutil

            shutil.rmtree(stage)
        raise
    finally:
        shared.current_dir = old_current_dir


def add_tahoe_port_aliases(plist: dict[str, Any]) -> int:
    """Mirror USBToolBox kext 1.2.0 fixMapForTahoe() in native maps.

    Native AppleUSBHostMergeProperties maps do not load the USBToolBox runtime,
    so add the same aliases to each generated port while retaining legacy keys.
    """
    personalities = plist.get("IOKitPersonalities")
    if not isinstance(personalities, dict) or not personalities:
        raise ValueError("IOKitPersonalities mancante: impossibile aggiungere lo schema Tahoe")
    updated = 0
    for personality_name, personality in personalities.items():
        merge = personality.get("IOProviderMergeProperties")
        ports = merge.get("ports") if isinstance(merge, dict) else None
        if not isinstance(ports, dict) or not ports:
            raise ValueError(f"Mappa porte mancante in {personality_name}")
        for port_name, properties in ports.items():
            if not isinstance(properties, dict):
                raise ValueError(f"Proprietà porta non valida: {personality_name}/{port_name}")
            legacy_values = {
                "usb-port-number": properties.get("port"),
                "usb-port-type": properties.get("UsbConnector"),
            }
            if not isinstance(legacy_values["usb-port-number"], bytes):
                raise ValueError(f"port Data assente o invalido: {personality_name}/{port_name}")
            if type(legacy_values["usb-port-type"]) is not int:
                raise ValueError(f"UsbConnector intero assente o invalido: {personality_name}/{port_name}")
            for alias, legacy_key in TAHOE_PORT_ALIASES.items():
                expected = legacy_values[alias]
                if alias in properties and properties[alias] != expected:
                    raise ValueError(f"Alias Tahoe discordante {alias}: {personality_name}/{port_name}")
                if alias not in properties:
                    properties[alias] = expected
                    updated += 1
    return updated


def verify_generated_plist(plist: dict[str, Any], controllers: list[dict[str, Any]], shared: Any) -> None:
    personalities = plist.get("IOKitPersonalities")
    if not isinstance(personalities, dict) or len(personalities) != len(controllers):
        raise ValueError("IOKitPersonalities non corrisponde ai controller tradotti")
    by_id = {
        (c["identifiers"]["pci_id"][0], c["identifiers"]["pci_id"][1]): c for c in controllers
    }
    seen_ids = set()
    for personality in personalities.values():
        if personality.get("IOProviderClass") != "AppleUSBHostController":
            raise ValueError("Il generatore non ha prodotto una personality nativa AppleUSBHostController")
        parent_match = personality.get("IOParentMatch", {}).get("IOPCIPrimaryMatch")
        if not isinstance(parent_match, str):
            raise ValueError(f"IOParentMatch PCI ID assente o non stringa: {parent_match!r}")
        normalized = parent_match.removeprefix("0x").lower()
        matches = [pair for pair in by_id if normalized == pair[1] + pair[0]]
        if len(matches) != 1 or matches[0] in seen_ids:
            raise ValueError(f"IOPCIPrimaryMatch non univoco: {parent_match}")
        seen_ids.add(matches[0])
        source_controller = by_id[matches[0]]
        merge = personality.get("IOProviderMergeProperties", {})
        ports = merge.get("ports", {})
        mapped_raw = {
            int.from_bytes(port["port"], "little"): int(port["UsbConnector"])
            for port in ports.values()
        }
        for port_name, port in ports.items():
            if port.get("usb-port-number") != port.get("port"):
                raise ValueError(f"usb-port-number non corrisponde a port: {port_name}")
            if port.get("usb-port-type") != port.get("UsbConnector"):
                raise ValueError(f"usb-port-type non corrisponde a UsbConnector: {port_name}")
        expected_raw = {port["index"]: int(port["guessed"]) for port in source_controller["ports"]}
        if mapped_raw != expected_raw:
            raise ValueError(f"Indici/connector generati non corrispondono a {source_controller['name']}: {mapped_raw}")
        port_count = int.from_bytes(merge.get("port-count", b""), "little")
        if port_count != max(expected_raw):
            raise ValueError(f"port-count generato {port_count}, atteso {max(expected_raw)}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def prepare_config_candidate(candidate_root: Path, baseline_efi: Path, ocvalidate: Path) -> dict[str, Any]:
    candidate_root = candidate_root.resolve()
    baseline_efi = baseline_efi.resolve()
    ocvalidate = ocvalidate.resolve()
    if not (candidate_root / "USBMap.kext/Contents/Info.plist").is_file():
        raise ValueError(f"Manca la mappa nativa generata nella candidata: {candidate_root}")
    if not (candidate_root / "porting-metadata.json").is_file():
        raise ValueError("Mancano i metadati del builder USBToolBox pinned")
    source_config = baseline_efi / "OC/config.plist"
    if not source_config.is_file():
        raise ValueError(f"Config Boot15 non trovato: {source_config}")
    source_hash = file_sha256(source_config)
    if source_hash != BOOT15_CONFIG_SHA256:
        raise ValueError(f"La baseline non è il config Boot15 previsto: SHA256 {source_hash}")
    destination_efi = candidate_root / "EFI"
    if destination_efi.exists():
        raise FileExistsError(f"EFI candidata già presente; non verrà sovrascritta: {destination_efi}")
    if not ocvalidate.is_file():
        raise FileNotFoundError(f"ocvalidate non trovato: {ocvalidate}")

    shutil.copytree(baseline_efi, destination_efi)
    config_path = destination_efi / "OC/config.plist"
    original_config = plistlib.loads(source_config.read_bytes())
    candidate_config = copy.deepcopy(original_config)
    entries = candidate_config["Kernel"]["Add"]
    usbmap_entries = [entry for entry in entries if entry.get("BundlePath") == "USBMapB840.kext"]
    if len(usbmap_entries) != 1 or usbmap_entries[0].get("Enabled") is not False:
        raise ValueError("La baseline Boot15 deve avere una sola voce USBMapB840.kext disabilitata")
    usbmap_entries[0]["Enabled"] = True
    plistlib.dump(candidate_config, config_path.open("wb"), fmt=plistlib.FMT_XML, sort_keys=True)

    generated_info = candidate_root / "USBMap.kext/Contents/Info.plist"
    destination_info = destination_efi / "OC/Kexts/USBMapB840.kext/Contents/Info.plist"
    if not destination_info.is_file():
        raise ValueError(f"Bundle USBMapB840.kext della baseline incompleto: {destination_info}")
    destination_info.write_bytes(generated_info.read_bytes())

    semantic_check = copy.deepcopy(candidate_config)
    candidate_entry = next(entry for entry in semantic_check["Kernel"]["Add"] if entry.get("BundlePath") == "USBMapB840.kext")
    candidate_entry["Enabled"] = False
    if semantic_check != original_config:
        raise ValueError("Il confronto semantico mostra differenze oltre alla riattivazione della voce USBMapB840")

    validation = subprocess.run(
        [str(ocvalidate), str(config_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    validation_record = {
        "tool": str(ocvalidate),
        "expected_version": "OpenCore 1.0.8",
        "return_code": validation.returncode,
        "passed": validation.returncode == 0,
        "stdout": validation.stdout.strip(),
        "stderr": validation.stderr.strip(),
    }
    (candidate_root / "ocvalidate.txt").write_text(
        validation.stdout + validation.stderr,
        encoding="utf-8",
    )

    baseline_hashes = tree_hashes(baseline_efi)
    candidate_hashes = tree_hashes(destination_efi)
    unchanged = sorted(
        rel for rel, old_hash in baseline_hashes.items() if candidate_hashes.get(rel) == old_hash
    )
    changed = sorted(
        rel for rel, old_hash in baseline_hashes.items() if rel in candidate_hashes and candidate_hashes[rel] != old_hash
    )
    removed = sorted(set(baseline_hashes) - set(candidate_hashes))
    added = sorted(set(candidate_hashes) - set(baseline_hashes))
    expected_changed = ["OC/Kexts/USBMapB840.kext/Contents/Info.plist", "OC/config.plist"]
    if changed != expected_changed or removed or added:
        raise ValueError(f"Diff EFI inatteso: changed={changed}, removed={removed}, added={added}")

    diff_record = {
        "baseline_config_sha256": source_hash,
        "candidate_config_sha256": file_sha256(config_path),
        "semantic_config_change": "only Kernel.Add[USBMapB840.kext].Enabled changes false to true",
        "usbmapb840_enabled_in_candidate": True,
        "native_usbtoolbox_info_plist_replaces_its_contents": True,
        "efi_bundle_path_reused": "OC/Kexts/USBMapB840.kext",
        "efi_baseline_file_count": len(baseline_hashes),
        "efi_candidate_file_count": len(candidate_hashes),
        "unchanged_file_count": len(unchanged),
        "changed_paths": changed,
        "added_paths": added,
        "removed_paths": removed,
        "ocvalidate": validation_record,
    }
    (candidate_root / "efi-candidate-diff.json").write_text(
        json.dumps(diff_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    metadata_path = candidate_root / "porting-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["efi_candidate"] = diff_record
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if validation.returncode != 0:
        raise RuntimeError(f"ocvalidate 1.0.8 ha rifiutato la config candidata; dettagli in {candidate_root / 'ocvalidate.txt'}")
    return diff_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="genera una candidata nativa usando il builder ufficiale pinned")
    generate.add_argument("--upstream", type=Path, default=DEFAULT_UPSTREAM)
    generate.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    generate.add_argument("--model", default=MODEL_IDENTIFIER)
    config = sub.add_parser("prepare-config", help="prepara una EFI candidata locale da Boot15 e valida la config")
    config.add_argument("--candidate", type=Path, default=DEFAULT_OUTPUT)
    config.add_argument(
        "--baseline-efi",
        type=Path,
        default=Path("research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch-usb-native/EFI"),
    )
    config.add_argument(
        "--ocvalidate",
        type=Path,
        default=Path("research/ext/ocboot-baremetal/_dl/opencore/src/Utilities/ocvalidate/ocvalidate.linux"),
    )
    args = parser.parse_args()

    if args.command == "generate":
        output = generate_candidate(args.upstream, args.output, args.model)
        print(f"USBToolBox ufficiale ha generato la candidata nativa: {output}")
        print(f"Metadata Linux e limiti: {output / 'porting-metadata.json'}")
        print("La candidata resta locale e non è stata installata o attivata in OpenCore.")
        return 0
    if args.command == "prepare-config":
        result = prepare_config_candidate(args.candidate, args.baseline_efi, args.ocvalidate)
        print(f"Config Boot15 candidata creata localmente: {args.candidate.resolve() / 'EFI/OC/config.plist'}")
        print(f"Confronto EFI: {result['unchanged_file_count']} file invariati; changed={result['changed_paths']}; added={result['added_paths']}")
        print(f"ocvalidate 1.0.8: {'PASS' if result['ocvalidate']['passed'] else 'FAIL'}")
        print("Nessuna scrittura sulla chiavetta di boot.")
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Errore: {error}", file=sys.stderr)
        raise SystemExit(1)
