#!/usr/bin/env python3
"""Read the candidate's IORegistry state; never access MSRs or change policy.

Success requires actual per-CPU request readback, rather than mere kext loading.
APERF/MPERF ratios describe busy-cycle frequency relative to the CPU reference;
they are not GHz readings, total utilization, package power or proof of C6.
"""
import argparse
import json
import plistlib
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--samples", type=int, default=3)
parser.add_argument("--interval", type=float, default=1.2)
args = parser.parse_args()
if not 2 <= args.samples <= 20 or not 0.5 <= args.interval <= 5:
    parser.error("samples must be 2..20 and interval 0.5..5 seconds")
previous = {}
for sample in range(args.samples):
    raw = subprocess.check_output(["ioreg", "-a", "-r", "-l", "-c", "Navi44CPPC"])
    nodes = plistlib.loads(raw) if raw.strip() else []
    if len(nodes) != 1:
        raise SystemExit("No unique Navi44CPPC service; activation is not proven.")
    node = nodes[0]
    rows = node.get("CPPC,Cores", [])
    if len(rows) != 16 or {r.get("CPU") for r in rows} != set(range(16)):
        raise SystemExit("Missing/duplicate CPU records; activation is not proven.")
    if node.get("CPPC,RequestedMode") != 1 or node.get("CPPC,ActiveVerified") != 1:
        raise SystemExit("CPPC is not verified active: " + str(node.get("CPPC,State", "unknown")))
    ratios = {}
    for row in rows:
        cpu = row["CPU"]
        cap = row["Capability1"]
        lo, efficient, nominal, hi = [(cap >> shift) & 255 for shift in (0, 8, 16, 24)]
        req = row["Request"]
        if (not row["Seen"] or row["Error"] or row["Enable"] != row["OriginalEnable"] | 1 or
                not 0 < lo <= efficient <= nominal <= hi or lo == hi or
                req != row["TargetRequest"] or req & 0xffffff != (lo << 8) | hi or
                (req >> 24) & 255 != 128 or req >> 32 != row["OriginalRequest"] >> 32):
            raise SystemExit(f"CPU {cpu}: request/capability readback mismatch")
        old = previous.get(cpu)
        if old and row["PerfValid"] and old["PerfValid"] and row["PerfSample"] > old["PerfSample"]:
            da = (row["APERF"] - old["APERF"]) & ((1 << 64) - 1)
            dm = (row["MPERF"] - old["MPERF"]) & ((1 << 64) - 1)
            if dm:
                ratios[cpu] = round(da / dm, 4)
        previous[cpu] = row
    print(json.dumps({"sample": sample + 1, "state": node["CPPC,State"],
                      "verified_cpus": 16, "busy_frequency_ratio": ratios}))
    if sample + 1 < args.samples:
        time.sleep(args.interval)
