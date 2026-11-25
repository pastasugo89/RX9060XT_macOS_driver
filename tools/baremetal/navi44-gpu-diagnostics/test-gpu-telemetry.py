#!/usr/bin/env python3
"""Offline validation of the cached and legacy telemetry formats."""

import importlib.util
from pathlib import Path
import plistlib
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('telemetry', Path(__file__).with_name('gpu-telemetry.py'))
telemetry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(telemetry)

METRICS = '''!! firmware driver-interface version 0x33 is newer than the layout this
!! build decodes; values are UNVERIFIED (range check: passed)
clocks  gfx 1000 MHz  soc 1371 MHz  mem 1258 MHz  fclk 2016 MHz
temps   edge 45 C  hotspot 47 C  mem 44 C   fan 0 rpm (0%)
power   socket 34 W  board 34 W   busy gfx 48%  mem 2%
link    PCIe gen 4 x16   (snapshot 1004)
'''
VRAM = '''accel vramstat: BAR0 phys 0x0, mapped 256 MiB (0x10000000 bytes), vramLimit 256 MiB (0x10000000), VRAM 16384 MiB, vramBase 32 MiB
  visible pool: 227540992 bytes total (217 MiB), 168673280 bytes free (160 MiB), GMC visible size 256 MiB
  hi pool     : not created
'''


class TelemetryTests(unittest.TestCase):
    def test_legacy_zero_rpm_and_unverified_layout(self):
        sample = telemetry.legacy_sample(METRICS, VRAM)
        self.assertEqual((sample['SMUInterfaceVersion'], sample['SMULayoutVerified']), (51, 0))
        self.assertEqual((sample['FanRPM'], sample['FanPWMPercent']), (0, 0))
        self.assertNotIn('THMHotspotC', sample)
        telemetry.add_allocator_usage(sample)
        self.assertEqual(sample['VRAMAllocatorUsedBytes'], 227540992 - 168673280)

    def test_unreliable_measurements_are_omitted(self):
        for invalid in (METRICS.replace('passed', 'FAILED'), METRICS.replace('hotspot 47', 'hotspot 130')):
            sample = telemetry.legacy_sample(invalid, VRAM)
            self.assertEqual(sample['SMUValuesPlausible'], 0)
            self.assertNotIn('FanRPM', sample)
            self.assertIn('PhysicalVRAMBytes', sample)

    def test_registry_read_needs_no_administrative_tool(self):
        fixture = {'Schema': 1, 'SampleUptimeMs': 123, 'THMHotspotC': 47, 'SMULayoutVerified': 0}
        with patch.object(telemetry, 'command', return_value=plistlib.dumps([{telemetry.PROPERTY: fixture}])) as command:
            sample = telemetry.registry_sample()
        self.assertEqual(sample, {**fixture, 'Source': 'IORegistry'})
        command.assert_called_once_with('/usr/sbin/ioreg', '-a', '-r', '-c', 'Navi48Bringup', '-d', '1')


if __name__ == '__main__':
    unittest.main()
