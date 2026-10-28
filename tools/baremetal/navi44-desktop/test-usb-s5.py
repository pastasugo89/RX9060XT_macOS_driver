#!/usr/bin/env python3
"""Execute B840 S5 AML regression cases in ACPICA's simulated operation regions.

This loads only the synthetic fixtures and candidate SSDT. Never pass acpiexec
the -do option (that disables region simulation). No firmware AML is executed.
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("iasl", type=Path)
parser.add_argument("acpiexec", type=Path)
parser.add_argument("--ssdt", type=Path, default=here / "SSDT-B840-USB-S5.dsl")
args = parser.parse_args()
iasl, acpiexec = args.iasl.resolve(), args.acpiexec.resolve()
methods = [f"T{variant}{i:02}" for i in range(4) for variant in "VDCF"]
commands = "osi install Darwin;" + ";".join("execute " + m for m in methods + ["WR03", "WR05"])
commands += ";osi remove Darwin;execute WO05"
with tempfile.TemporaryDirectory(prefix="navi44-usb-s5-test-") as work:
    work = Path(work)
    amls = []
    for source, name in [(here / "test-usb-s5.dsl", "fixture"),
                         (args.ssdt.resolve(), "candidate"),
                         (here / "test-usb-s5-fields.dsl", "fields")]:
        result = subprocess.run([str(iasl), "-p", str(work / name), str(source)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        amls.append(str(work / (name + ".aml")))
    # -dt disables the debugger's allocator accounting, not operation-region
    # simulation. AML evaluation errors and all fixture return codes still fail.
    result = subprocess.run([str(acpiexec), "-dt", "-b", commands, *amls],
                            capture_output=True, text=True, timeout=30)
    log = result.stdout + result.stderr
    values = re.findall(r"\[Integer\] = ([0-9A-Fa-f]+)", log)
    if (result.returncode or len(values) != 19 or any(int(v, 16) for v in values)
            or "ACPI Error:" in log or "failed with status" in log):
        raise SystemExit("S5 simulation FAILED:\n" + log)
    print("S5 simulation: 19 cases PASS (four device guards, PME bit preservation, original _PTS, S3, Darwin/non-Darwin S5)")
