#!/usr/bin/env python3
"""Host tests for tools/vm/gpu-safety-watchdog.py: the decision cases, every scenario with a fake serial log and a fake QMP
socket, and the consistency of the thresholds with the kext header. Run: python3 tools/hosttests/test_gpu_safety_watchdog.py"""
import importlib.util
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "vm" / "gpu-safety-watchdog.py"
HEADER = ROOT / "cobalt64" / "src" / "navi48-bringup" / "src" / "amd" / "n4x_safety_pure.h"

_spec = importlib.util.spec_from_file_location("gpu_safety_watchdog", SCRIPT)
gsw = importlib.util.module_from_spec(_spec)
sys.modules["gpu_safety_watchdog"] = gsw
_spec.loader.exec_module(gsw)


class DecisionCases(unittest.TestCase):
    def test_unit_cases(self):
        self.assertEqual(gsw.unit_cases(), [])

    def test_heartbeat_parser_on_the_kext_format(self):
        # The exact shape formatted by n4xs::format_heartbeat (n4x_safety_pure.h), also asserted by test_n4x_safety_pure.cpp.
        line = "[  12.345] N4X-SAFETY t=12345 hotspot=30 edge=na mem=na ppt=na state=OK reason=none proto=1 thm=0x1e000000"
        p = gsw.parse_safety_line(line)
        self.assertEqual(p["kind"], "hb")
        self.assertEqual((p["t_ms"], p["hot"], p["state"], p["proto"]), (12345, 30, "OK", "1"))

    def test_na_hotspot_and_trip(self):
        p = gsw.parse_safety_line("N4X-SAFETY t=5 hotspot=na edge=na mem=na ppt=na state=TRIP reason=sensor-invalid proto=0 thm=0xffffffff")
        self.assertIsNone(p["hot"])
        self.assertEqual(p["state"], "TRIP")

    def test_stop_line_is_not_trip(self):
        p = gsw.parse_safety_line("N4X-SAFETY t=9 hotspot=91 edge=na mem=na ppt=na state=STOP reason=none proto=1 thm=0x0")
        self.assertEqual(p["state"], "STOP")

    def test_thresholds_match_the_kext_header(self):
        text = HEADER.read_text(encoding="utf-8")
        warn = int(re.search(r"kDefaultWarnC\s*=\s*(\d+)", text).group(1))
        trip = int(re.search(r"kDefaultTripC\s*=\s*(\d+)", text).group(1))
        self.assertEqual((warn, trip), (gsw.DEFAULT_WARN_C, gsw.DEFAULT_TRIP_C))

    def test_bad_thresholds_are_refused(self):
        with self.assertRaises(ValueError):
            gsw.Watchdog(warn_c=80, trip_c=75)


class Scenarios(unittest.TestCase):
    """Each scenario: a fake kext writes lines to a serial log, a fake QEMU listens on a QMP socket, the real loop decides."""

    def _run(self, name):
        with tempfile.TemporaryDirectory(prefix="gsw-test-") as tmp:
            ok, detail = gsw.run_scenario(name, workdir=tmp)
        self.assertTrue(ok, "scenario %s: %s" % (name, detail))

    def test_ok_no_stop(self):
        self._run("ok")

    def test_warn_logs_but_does_not_stop(self):
        self._run("warn")

    def test_kext_trip_stops_the_vm(self):
        self._run("trip")

    def test_heartbeat_lost_stops_the_vm(self):
        self._run("lost")

    def test_host_temperature_stops_the_vm(self):
        self._run("hot")

    def test_clean_kext_stop_does_not_stop_the_vm(self):
        self._run("stop")

    def test_max_runtime_stops_the_vm(self):
        self._run("maxrt")

    def test_malformed_line_warns_only(self):
        self._run("malformed")

    def test_no_sensor_stops_the_vm(self):
        self._run("nosensor")

    def test_dry_run_never_sends_quit(self):
        sent = []
        wd = gsw.Watchdog()
        wd.feed("N4X-SAFETY t=1 hotspot=95 edge=na mem=na ppt=na state=TRIP reason=trip-temp proto=1 thm=0x0", 0.0)
        with tempfile.TemporaryDirectory(prefix="gsw-test-") as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "serial.log").write_text("", encoding="utf-8")
            log = gsw.Log(tmp / "w.log")
            gsw.stop_vm(tmp / "qmp.sock", True, log, lambda: False, quit_fn=lambda p: sent.append(p))
            log.close()
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
