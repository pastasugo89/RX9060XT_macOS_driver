#!/usr/bin/env python3
"""Offline tests for the pure parsers and fail-closed status semantics."""

import importlib.util
import contextlib
import io
import os
import unittest
from unittest import mock


MODULE_PATH = os.path.join(os.path.dirname(__file__), "macos_thermal_watch.py")
SPEC = importlib.util.spec_from_file_location("macos_thermal_watch", MODULE_PATH)
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


class ThermalMonitorTests(unittest.TestCase):
    def test_exact_cpu_label_is_parsed(self):
        self.assertEqual(watch._parse_temperature("CPU die temperature: 42.5 C\n", "CPU die temperature"), 42.5)

    def test_generic_temperature_labels_are_rejected(self):
        self.assertIsNone(watch._parse_temperature("Temperature: 42 C\n", "CPU die temperature"))
        self.assertIsNone(watch._parse_temperature("GPU die temperature: 55 C\n", "CPU die temperature"))

    def test_invalid_values_are_rejected(self):
        for value in ("-1", "126", "nan", "inf"):
            self.assertIsNone(watch._parse_temperature("CPU die temperature: {} C".format(value), "CPU die temperature"))

    def test_generic_gpu_temperature_never_maps_to_discrete_radeon(self):
        raw = {
            "powermetrics": "CPU die temperature: 44 C\nGPU die temperature: 55 C\n",
            "displays": "Vendor: 0x1002\nDevice ID: 0x7590\n",
            "source_status": {},
        }
        snapshot = watch.build_snapshot(raw, now="fixture")
        self.assertEqual(snapshot["temperatures"]["cpu"]["status"], "UNKNOWN")
        self.assertEqual(snapshot["temperatures"]["cpu"]["candidate_celsius_unverified"], 44.0)
        self.assertEqual(snapshot["temperatures"]["rx9060xt"]["status"], "UNKNOWN")
        self.assertEqual(snapshot["temperatures"]["rx9060xt"]["candidate_celsius_unattributed"], 55.0)
        self.assertTrue(snapshot["system_sensors"]["rx9060xt_pci_match_seen"])

    def test_xcpm_zero_and_pmset_absence_do_not_imply_safety(self):
        raw = {
            "sysctl": "machdep.xcpm.cpu_thermal_level: 0\nmachdep.xcpm.gpu_thermal_level: 0\n",
            "pmset": "Note: No thermal warning level has been recorded\n",
            "source_status": {},
        }
        snapshot = watch.build_snapshot(raw, now="fixture")
        self.assertEqual(snapshot["thermal_protection"], "UNKNOWN")
        self.assertEqual(snapshot["safety_assessment"], "UNKNOWN")
        self.assertEqual(snapshot["system_sensors"]["xcpm_thermal_levels_uninterpreted"]["machdep.xcpm.cpu_thermal_level"], "0")
        self.assertEqual(watch.check_exit_code(snapshot), 2)

    def test_check_never_returns_success_without_protection_evidence(self):
        complete_temps = {
            "temperatures": {
                "cpu": {"status": "REPORTED"},
                "rx9060xt": {"status": "REPORTED"},
            },
            "thermal_protection": "UNKNOWN",
        }
        self.assertEqual(watch.check_exit_code(complete_temps), 3)

    def test_ioreg_sensor_node_fixture_is_counted_but_not_decoded(self):
        raw = {
            "iohwsensor": "+-o TG0B  <class IOHWSensor, id 0x100, registered, matched, active, busy 0>\n",
            "source_status": {},
        }
        snapshot = watch.build_snapshot(raw, now="fixture")
        self.assertEqual(snapshot["system_sensors"]["iohwsensor_class_nodes_seen"], 1)
        self.assertFalse(snapshot["system_sensors"]["iohwsensor_values_decoded"])

    def test_collect_snapshot_accepts_filtered_source_records(self):
        outputs = {
            "/usr/bin/powermetrics": "powermetrics must be invoked as the superuser\n",
            "/usr/sbin/ioreg": "",
            "/usr/sbin/system_profiler": "Vendor: 0x1002\nDevice ID: 0x7590\n",
            "/usr/bin/kmutil": "",
            "/usr/bin/pmset": "Note: No thermal warning level has been recorded\n",
            "/usr/sbin/sysctl": "machdep.xcpm.cpu_thermal_level: 0\nmachdep.xcpm.gpu_thermal_level: 0\n",
        }

        def fake_run(argv, timeout=8):
            return {
                "available": True,
                "returncode": 1 if argv[0] == "/usr/bin/powermetrics" else 0,
                "stdout": outputs.get(argv[0], ""),
                "stderr": "",
            }

        with mock.patch.object(watch, "_run", side_effect=fake_run) as mocked:
            snapshot = watch.collect_snapshot()
        self.assertEqual(mocked.call_count, 7)
        self.assertEqual(snapshot["temperatures"]["cpu"]["status"], "UNKNOWN")
        self.assertEqual(snapshot["temperatures"]["rx9060xt"]["status"], "UNKNOWN")
        self.assertEqual(snapshot["system_sensors"]["powermetrics_smc"]["returncode"], 1)
        self.assertEqual(snapshot["system_sensors"]["powermetrics_smc"]["diagnostic"], "powermetrics must be invoked as the superuser")
        self.assertEqual(watch.check_exit_code(snapshot), 2)
        self.assertFalse(any("sudo" in call.args[0] for call in mocked.call_args_list))

    def test_source_failure_diagnostic_uses_stderr_then_stdout(self):
        self.assertEqual(
            watch._source_record({"available": True, "returncode": 1, "stdout": "ignored", "stderr": "denied"})["diagnostic"],
            "denied",
        )
        self.assertEqual(
            watch._source_record({"available": True, "returncode": 1, "stdout": "must be root", "stderr": ""})["diagnostic"],
            "must be root",
        )

    def test_cli_refuses_root_without_querying_os(self):
        stderr = io.StringIO()
        with mock.patch.object(watch.os, "geteuid", return_value=0), \
                mock.patch.object(watch, "collect_snapshot") as collect, \
                contextlib.redirect_stderr(stderr):
            result = watch.main(["--check"])
        self.assertEqual(result, 77)
        collect.assert_not_called()
        self.assertIn("unprivileged user", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
