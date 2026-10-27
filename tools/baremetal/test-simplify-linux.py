#!/usr/bin/env python3
"""Integration checks against the pinned fork and the actual Linux report."""
import copy
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "research/ext/OpCore-Simplify"
sys.path.insert(0, str(REPO))
from Scripts.compatibility_checker import CompatibilityChecker
from Scripts.hardware_customizer import HardwareCustomizer
from Scripts.config_prodigy import ConfigProdigy
from Scripts.datasets import kext_data
from Scripts import utils


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((REPO / "Report-Linux.json").read_text())
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.head = patch.object(utils.Utils, "head", lambda *a, **k: None)
        self.input = patch.object(utils.Utils, "request_input", lambda *a, **k: "")
        self.sleep = patch("Scripts.compatibility_checker.time.sleep", lambda *_: None)
        self.head.start(); self.input.start(); self.sleep.start()

    def tearDown(self):
        self.sleep.stop(); self.input.stop(); self.head.stop(); self.output.__exit__(None, None, None)

    def experimental(self):
        return CompatibilityChecker(allow_unaccelerated=True).check_compatibility(copy.deepcopy(self.report))[0]

    def test_default_still_rejects_9060(self):
        with self.assertRaises(SystemExit):
            CompatibilityChecker().check_compatibility(self.report)

    def test_experimental_retains_real_unsupported_display_without_oclp(self):
        report = self.experimental()
        customized, disabled, oclp = HardwareCustomizer().hardware_customization(report, "25.6.0")
        gpu = next(iter(customized["GPU"].values()))
        self.assertEqual(gpu["Device ID"], "1002-7590")
        self.assertEqual(gpu["Compatibility"], (None, None))
        self.assertTrue(gpu["Unaccelerated"])
        self.assertFalse(any("GPU" in name for name in disabled))
        self.assertFalse(oclp)
        self.assertFalse(any("Unaccelerated" in g for g in self.report["GPU"].values()))

    def test_missing_cpu_instruction_sets_still_rejected(self):
        self.report["CPU"]["SIMD Features"] = "AVX AVX2"
        with self.assertRaises(SystemExit):
            self.experimental()

    def test_ambiguous_multiple_unsupported_displays_rejected(self):
        self.report["GPU"]["Second unsupported AMD GPU"] = copy.deepcopy(next(iter(self.report["GPU"].values())))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.experimental()

    def test_older_os_does_not_silently_use_wrong_amd_flag(self):
        with self.assertRaisesRegex(ValueError, "23 or newer"):
            HardwareCustomizer().hardware_customization(self.experimental(), "22.6.0")

    def test_supported_gpu_keeps_normal_compatibility(self):
        gpu = next(iter(self.report["GPU"].values()))
        gpu.update({"Codename": "Navi 23", "Device ID": "1002-73FF"})
        checked = self.experimental()
        gpu = next(iter(checked["GPU"].values()))
        self.assertNotEqual(gpu["Compatibility"], (None, None))
        self.assertNotIn("Unaccelerated", gpu)

    def test_disable_acceleration_argument_does_not_require_graphics_kext(self):
        report = self.experimental()
        kexts = copy.deepcopy(kext_data.kexts)
        for kext in kexts:
            kext.checked = False
        args = ConfigProdigy().boot_args(report, "25.6.0", False, kexts, {"Booter": {"Quirks": {"ResizeAppleGpuBars": 0}}})
        self.assertIn("-amd_no_dgpu_accel", args.split())
        self.assertNotIn("-wegnoegpu", args.split())

    def test_linux_export_menu_produces_valid_live_report(self):
        spec = importlib.util.spec_from_file_location("opcore_simplify_test", REPO / "OpCore-Simplify.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        with patch.object(utils.Utils, "request_input", lambda *a, **k: "e"):
            path, report = app.OCPE(allow_unaccelerated=True).select_hardware_report()
        self.assertTrue(Path(path).is_file())
        self.assertEqual(report["Motherboard"]["Chipset"], "B840")
        self.assertEqual(next(iter(report["GPU"].values()))["Device ID"], "1002-7590")


if __name__ == "__main__":
    unittest.main(verbosity=2)
