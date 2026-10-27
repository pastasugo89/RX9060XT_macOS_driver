#!/usr/bin/env python3
"""Read-only macOS thermal telemetry inventory; not a safety controller.

This program calls only fixed, non-privileged macOS query commands. It does not
read hardware registers directly, load kernel extensions, change settings, or
trigger shutdowns. Missing or unattributed temperatures remain UNKNOWN.
"""

from __future__ import print_function

import argparse
import datetime
import json
import math
import os
import re
import subprocess
import sys
import time


GPU_PCI_ID = "1002:7590"
RC_OK = 0
RC_TELEMETRY_UNKNOWN = 2
RC_PROTECTION_UNKNOWN = 3
RC_PRIVILEGED = 77


def _run(argv, timeout=8):
    """Run one fixed read-only system query and retain only in-memory output."""
    try:
        result = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
            check=False,
        )
        return {
            "available": True,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "returncode": None,
            "stdout": "",
            "stderr": "{}: {}".format(type(exc).__name__, exc),
        }


def _one_line(value, limit=240):
    return " ".join((value or "").split())[:limit]


def _parse_temperature(text, label):
    """Accept only one explicitly labeled numeric Celsius reading."""
    pattern = re.compile(
        r"^\s*{}\s*:\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:°\s*)?C\s*$".format(
            re.escape(label)
        ),
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        temperature = float(match.group(1))
    except ValueError:
        return None
    if not math.isfinite(temperature) or temperature < 0 or temperature > 125:
        return None
    return temperature


def _source_record(result):
    diagnostic = result.get("stderr", "")
    if result.get("returncode") not in (0, None) and not diagnostic:
        diagnostic = result.get("stdout", "")
    return {
        "command_available": result.get("available", False),
        "returncode": result.get("returncode"),
        "diagnostic": _one_line(diagnostic or result.get("diagnostic", "")),
    }


def _display_identity(text):
    """Keep only non-personal display identity fields from system_profiler."""
    wanted = {
        "Chipset Model:": "chipset_model",
        "Type:": "type",
        "Bus:": "bus",
        "Vendor:": "vendor",
        "Device ID:": "device_id",
        "Revision ID:": "revision_id",
        "VRAM (Total):": "vram_total",
    }
    fields = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        for label, key in wanted.items():
            if stripped.startswith(label):
                fields[key] = stripped[len(label):].strip()
    return fields


def _loaded_thermal_kexts(text):
    """Report names and versions only; omit addresses, UUIDs and dependency IDs."""
    names = (
        "VirtualSMC", "Lilu", "SMCAMDProcessor", "AMDRyzenCPUPowerManagement",
        "SMCProcessor", "SMCSuperIO", "Navi48", "Cobalt64", "AMDSupport",
    )
    found = []
    for line in (text or "").splitlines():
        for name in names:
            if name in line:
                version_match = re.search(r"\(([^()]*)\)", line)
                entry = {"name": name}
                if version_match:
                    entry["version"] = version_match.group(1)
                if entry not in found:
                    found.append(entry)
    return found


def _pmset_summary(text):
    """Retain thermal-state sentences without mapping them to temperatures."""
    markers = (
        "thermal warning", "performance warning", "cpu power status",
        "thermal level", "power status",
    )
    return [
        _one_line(line)
        for line in (text or "").splitlines()
        if any(marker in line.lower() for marker in markers)
    ]


def _sysctl_summary(text):
    """Capture only named thermal-level keys; these are not temperatures."""
    accepted = (
        "machdep.xcpm.cpu_thermal_level",
        "machdep.xcpm.gpu_thermal_level",
    )
    result = {}
    for line in (text or "").splitlines():
        for key in accepted:
            prefix = key + ":"
            if line.startswith(prefix):
                result[key] = line[len(prefix):].strip()
    return result


def _thermal_reading(value, source, reason):
    if value is None:
        return {"status": "UNKNOWN", "celsius": None, "source": source, "reason": reason}
    return {
        "status": "REPORTED",
        "celsius": value,
        "source": source,
        "reason": "Temperatura riportata dalla sorgente indicata; non costituisce una garanzia di sicurezza.",
    }


def build_snapshot(raw, now=None):
    """Transform fixture or collected command output into a privacy-filtered snapshot."""
    display = _display_identity(raw.get("displays", ""))
    pci_text = " ".join(display.values()).lower()
    gpu_identified = GPU_PCI_ID in pci_text or (
        "vendor" in display and "device_id" in display
        and "0x1002" in display["vendor"].lower()
        and "0x7590" in display["device_id"].lower()
    )
    cpu_candidate = _parse_temperature(raw.get("powermetrics", ""), "CPU die temperature")
    gpu_candidate = _parse_temperature(raw.get("powermetrics", ""), "GPU die temperature")

    # A generic GPU die label is deliberately not attributed to this discrete
    # Radeon because the Ryzen 7 7700 also contains an integrated GPU.
    gpu_temp = None
    gpu_reason = (
        "Nessuna lettura attribuita esplicitamente alla GPU PCI {}.".format(GPU_PCI_ID)
    )
    if not gpu_identified:
        gpu_reason = (
            "La GPU PCI {} non è stata identificata nella risposta filtrata; temperatura UNKNOWN.".format(
                GPU_PCI_ID
            )
        )

    sensor_nodes = len(re.findall(r"<class\s+IOHWSensor\b", raw.get("iohwsensor", "")))
    apple_smc_present = "AppleSMC" in raw.get("applesmc", "")
    sources = raw.get("source_status", {})
    timestamp = now or datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {
        "timestamp_utc": timestamp,
        "host_os": "macOS",
        "mode": "read-only telemetry inventory",
        "read_only": True,
        "gpu_pci_id": GPU_PCI_ID,
        "temperatures": {
            "cpu": _thermal_reading(
                None,
                "powermetrics SMC label 'CPU die temperature'",
                "La label SMC non è convalidata per Ryzen 7 7700/VirtualSMC; nessuna temperatura CPU verificata.",
            ) | {
                "candidate_celsius_unverified": cpu_candidate,
                "candidate_reason": "Valore solo candidato dalla label SMC; non usarlo per decisioni di sicurezza.",
            },
            "rx9060xt": _thermal_reading(None, "nessuna sorgente verificata", gpu_reason) | {
                "candidate_celsius_unattributed": gpu_candidate,
                "candidate_reason": "Una label GPU generica potrebbe riferirsi alla GPU integrata; non è attribuita a 1002:7590.",
            },
        },
        "thermal_protection": "UNKNOWN",
        "safety_assessment": "UNKNOWN",
        "automatic_shutdown": False,
        "system_sensors": {
            "powermetrics_smc": _source_record(sources.get("powermetrics", {
                "available": False, "returncode": None, "stderr": "not collected"
            })),
            "iohwsensor_class_nodes_seen": sensor_nodes,
            "iohwsensor_values_decoded": False,
            "apple_smc_class_seen": apple_smc_present,
            "display_identity_filtered": display,
            "rx9060xt_pci_match_seen": gpu_identified,
            "loaded_thermal_related_kexts": _loaded_thermal_kexts(raw.get("kmutil", "")),
            "pmset_qualitative_state": _pmset_summary(raw.get("pmset", "")),
            "xcpm_thermal_levels_uninterpreted": _sysctl_summary(raw.get("sysctl", "")),
            "sysctl_notice": "I livelli XCPM non sono temperature e il valore 0 non dimostra sicurezza.",
        },
        "notice": (
            "Solo osservazione. Questo programma non è una protezione termica, non stabilisce soglie, "
            "non controlla ventole e non arresta il sistema. UNKNOWN richiede una sorgente verificata."
        ),
    }


def collect_snapshot():
    """Run read-only OS queries, without sudo or shell interpretation."""
    commands = {
        "powermetrics": ["/usr/bin/powermetrics", "--samplers", "smc", "-n", "1", "-i", "1000"],
        "iohwsensor": ["/usr/sbin/ioreg", "-r", "-c", "IOHWSensor", "-l", "-w0"],
        "applesmc": ["/usr/sbin/ioreg", "-r", "-c", "AppleSMC", "-l", "-w0"],
        "displays": ["/usr/sbin/system_profiler", "SPDisplaysDataType", "-detailLevel", "mini"],
        "kmutil": ["/usr/bin/kmutil", "showloaded"],
        "pmset": ["/usr/bin/pmset", "-g", "therm"],
        "sysctl": ["/usr/sbin/sysctl", "machdep.xcpm.cpu_thermal_level", "machdep.xcpm.gpu_thermal_level"],
    }
    outputs = {}
    status = {}
    for name, argv in commands.items():
        result = _run(argv)
        outputs[name] = result["stdout"]
        status[name] = result
    outputs["source_status"] = status
    return build_snapshot(outputs)


def check_exit_code(snapshot):
    temps = snapshot.get("temperatures", {})
    if any(temps.get(key, {}).get("status") != "REPORTED" for key in ("cpu", "rx9060xt")):
        return RC_TELEMETRY_UNKNOWN
    # Even fully populated temperatures do not prove an active thermal
    # protection mechanism, so --check never returns success.
    return RC_PROTECTION_UNKNOWN


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only macOS temperature telemetry inventory; not a thermal safety controller."
    )
    parser.add_argument("--output", help="append JSONL snapshots to this explicit path (default: stdout)")
    parser.add_argument("--count", type=int, default=1, help="number of snapshots (1..1000; default 1)")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between snapshots (1..3600)")
    parser.add_argument("--check", action="store_true", help="one snapshot; nonzero unless telemetry and protection are known")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("Run this inventory as an unprivileged user; it will not query sensors as root.", file=sys.stderr)
        return RC_PRIVILEGED
    if args.count < 1 or args.count > 1000:
        print("--count must be between 1 and 1000", file=sys.stderr)
        return 64
    if not math.isfinite(args.interval) or args.interval < 1 or args.interval > 3600:
        print("--interval must be between 1 and 3600 seconds", file=sys.stderr)
        return 64
    if args.check and args.count != 1:
        print("--check accepts exactly one snapshot", file=sys.stderr)
        return 64

    output = open(args.output, "a", encoding="utf-8") if args.output else None
    try:
        latest = None
        for index in range(args.count):
            latest = collect_snapshot()
            line = json.dumps(latest, ensure_ascii=False, sort_keys=True)
            if output:
                output.write(line + "\n")
                output.flush()
            else:
                print(line)
            if index + 1 < args.count:
                time.sleep(args.interval)
    finally:
        if output:
            output.close()

    if args.check:
        code = check_exit_code(latest)
        print("CHECK={} thermal_protection={} (nessun esito di sicurezza)".format(
            "UNKNOWN" if code == RC_TELEMETRY_UNKNOWN else "INCOMPLETE",
            latest["thermal_protection"],
        ), file=sys.stderr)
        return code
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
