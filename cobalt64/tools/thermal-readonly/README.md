# macOS thermal telemetry inventory

## RX 9060 XT telemetry

The driver snapshot is published as the `Navi48,Telemetry` dictionary on the `Navi48Bringup` IORegistry service
when an administrator requests a sample. Applications can read the cached dictionary without administrator access.
It includes a monotonic sample timestamp, the watchdog's independent THM hotspot, clamp state, physical VRAM and
the driver's VRAM pools. PMFW readings cover clocks, GFX and memory activity, edge, hotspot and memory temperature,
fan RPM and PWM, power and PCIe link. `SMULayoutVerified` describes the firmware layout. A range check alone leaves
the PMFW readings provisional. Missing fields are unavailable. Free allocator space excludes firmware and reserves.

```sh
# Sample every two seconds until interrupted. Also works on 0.0.680 via navi48test.
sudo /usr/bin/python3 -B tools/baremetal/navi44-gpu-diagnostics/gpu-telemetry.py --sample --count 0
# Read the latest published IORegistry sample on a kernel with the new property.
/usr/bin/python3 -B tools/baremetal/navi44-gpu-diagnostics/gpu-telemetry.py
```

Programmatic readers should check `SampleUptimeMs` to distinguish a new snapshot from a cached one. Sampling uses
the existing read-only metrics verb and does not change the fan or power policy.

## macOS inventory

`macos_thermal_watch.py` is a manually run, read-only inventory of macOS thermal telemetry. It is not a thermal protection mechanism: it does not load a kext, read device registers, alter fan or power controls, stop a workload, or shut down the computer. It is not started automatically.

Run one snapshot and make unknown CPU/GPU temperatures a nonzero result:

```sh
python3 -B cobalt64/tools/thermal-readonly/macos_thermal_watch.py --check
```

Record snapshots to a JSONL file only when explicitly requested:

```sh
python3 -B cobalt64/tools/thermal-readonly/macos_thermal_watch.py --count 12 --interval 5 --output ./thermal-snapshots.jsonl
```

The output is filtered to temperature status, display identity, selected kext names and qualitative OS thermal states. It does not include raw IORegistry, `kmutil`, or `system_profiler` output.

## Status and exit codes

- `UNKNOWN` means there is no verified reading attributed to that device. A possible CPU SMC reading is retained only as `candidate_celsius_unverified`; a generic GPU label is retained only as `candidate_celsius_unattributed`.
- `thermal_protection` and `safety_assessment` remain `UNKNOWN`. A reported temperature would not prove the platform's protection path is functioning.
- `--check` returns `2` when either CPU or RX 9060 XT temperature is unknown. It returns `3` if readings become available but protection remains unknown. It never returns `0` as a safety pass.
- When launched as root, the program refuses to query and exits `77`.
- Without `--check`, exit code `0` means only that a snapshot was emitted; inspect the JSON status fields.

The program invokes fixed macOS query commands without `sudo`. `--output` appends to the file named by the caller. Repeated sampling requires explicit `--count` and `--interval` options.

Offline parser tests (no macOS commands or hardware access):

```sh
python3 -B cobalt64/tools/thermal-readonly/test_macos_thermal_watch.py
```
