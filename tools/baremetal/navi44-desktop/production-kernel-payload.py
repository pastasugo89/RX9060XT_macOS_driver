#!/usr/bin/env python3
"""Prepare/check the logical-context kernel trial (0.0.666 to 0.0.675) without changing EFI or the live system.

`prepare --baseline-payload <verified earlier payload>` builds the baseline EFI from that payload's recorded hashes
instead of the mounted EFI (the EFI is not mounted and must not be touched). Such a payload is marked
live_efi_verified: false; installation must run `check --live` against the real EFI.
`--baseline-state candidate` takes the EFI that the earlier payload installs (0.0.668 is built on payload v3 that way).
The activation guard is derived from the live guard at prepare time: if that guard changes before installation,
prepare again (`check --live` refuses a stale guard).
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import plistlib
import re
import shutil
import struct
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
APP = 'Library/Application Support/Navi44/accelerated-trial'
GUARD = APP + '/accelerated-reboot-trial.sh'
PROBE = APP + '/context-isolation-probe'
METAL = 'Library/GPUBundles/Navi48Metal.bundle'
JOB = 'Library/LaunchDaemons/org.navi44.accelerated-trial.plist'
CRITICAL = (JOB, APP+'/boot-state.py', APP+'/navi48test', APP+'/n48nub', APP+'/seed-gpu-apps.py', APP+'/app-allowlist.json')
# The payload owns only OC/ and RECOVERY/ on the EFI volume. Everything else on it (CachyOS loader and scripts, BOOT/,
# System Volume Information) is never read, listed, required or written.
SCOPE = ('OC/', 'RECOVERY/')
STICK_UUID = '7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3'   # OCBOOT USB stick (earlier target)
LOCAL_UUID = '97C4AA5C-B87D-3786-B1B3-F84A76840DEF'   # CachyOS EFI partition (disk1s1): default for new payloads
EFI_UUIDS = (LOCAL_UUID, STICK_UUID)
UUID = LOCAL_UUID
PROFILE = 'stage26-logical-contexts-v1'
OLD = 'Navi48Bringup-eight-0.0.665.kext'
BASE_SHA = '607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24'
BASE_CONFIG_SHA = '92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb'
# Each release: its kext bundle, its recovery copy of the 665 config, the reviewed kernel binary, the CPU-test count,
# the strings its binary must contain, the exact list of config edits (path, old, new: checked, never assumed), and the
# extra EFI files it adds: 'baseline' means the baseline config bytes, otherwise the sha256 of the reviewed source file.
STARTUP = 'OC/Tools/startup.nsh'
STARTUP_SOURCE = Path(__file__).resolve().parent/'kernel-efi/startup.nsh'
STARTUP_SHA = '318f9fb9dc8e4419b9a8a33f58f866b961ddf7fc72fa93a178bfe71a6bbd5753'
EXTRA_SOURCES = {STARTUP: STARTUP_SOURCE}
# The 0.0.667 recovery entry (Misc/Tools[0]); 0.0.668 inherits it from its baseline and checks it.
RECOVERY_ENTRY = {'Name': 'Ripristino EFI: driver funzionanti (665)',
                  'Comment': 'Restores RECOVERY/funzionante-665.plist (kernel 665) and reboots'}
# 0.0.668 replaces the kernel that payload v3 installs (its candidate EFI is the live EFI state the baseline is taken from).
BUNDLE_667 = 'Navi48Bringup-contexts-0.0.667.kext'
KERNEL_667_SHA = '976b3375082c3f319f940b02f74fd5ff03155884a39feae771edfab62623f287'
CONFIG_667_SHA = '5ea9932d7fd53e97062021a72c6613f76bb96a3ecccce12d942fa8b796d531c6'
PROBE_667_SHA = '5afe2b52b0c0adc7a4bf1ea8f8e07437929ed9cfe066fa1f56a39240ceb000c5'   # the probe digest the 0.0.667 capability block pins
# 0.0.669 (refresh-60): built on the reviewed 0.0.668 candidate. Its guard is the live 0.0.668 guard with the 0.0.669 capability block
# and the refresh-60 hook (refresh-60/apply_refresh_guard.py, loaded by absolute path); its one system file is the refresh-60 navi48test;
# its probe is the reused 0.0.667 probe (PROBE_667_SHA). KERNEL_669_SHA is the candidate binary of kernel-contexts-v5 as its manifest
# records it now (a rebuild after a registry-property fix superseded 59d6ca43...).
BUNDLE_668 = 'Navi48Bringup-contexts-0.0.668.kext'
KERNEL_668_SHA = 'ab4c7fed6dd6c6ee52096da25d78f50bc515a51fdbfe8f591654143afe9ccb6d'
CONFIG_668_SHA = 'c8e2a26453bfcadb6afd716ad3a6927d9312c9fd290e49c37609f8d5ee8775ab'
GUARD_668_SHA = 'eaf88b0ab3a2711531c02efe22bc61bdf0012c1f0f2089fe8dd8ebd960ffd948'   # the 0.0.668 guard (payload v4's guard, live)
KERNEL_669_SHA = 'cb6fd1067edf3ebd1f12ea20a91726698bdf2833591a86d50489d31626057def'
NAVI48TEST_669_SHA = '83e7f3e3c9609ce636e138acf5a5186dbf6ef5c8951bcc6342eb21a1d058b94c'
# 0.0.670 (refresh-60b): the 0.0.669 release's EFI (payload v5, read as its candidate state) with kernel 0.0.670 and the 0.0.670 guard.
# Its base is the same reviewed 0.0.668 candidate (base_kernel_sha); its guard is the 0.0.669 guard with the 669 references moved to 670.
BUNDLE_669 = 'Navi48Bringup-contexts-0.0.669.kext'
CONFIG_669_SHA = '64fe3c2689d313dd8d076f3d7cf16edcc48eb30d94a63f42d8bf67eee019dc5b'   # payload v5's candidate configuration
KERNEL_670_SHA = 'c212c7310fb5a506d128d72dd5798725ecc2d6aaf84d7cee27dc0f6b88959eb3'   # the candidate binary of kernel-contexts-v6
GUARD_669_SHA = '36ab536ab8368d54713fd1c82fe69023bb27c56659c26e3e82d4e60b56d05cf0'   # the 0.0.669 guard (payload v5's guard, live)
PROBE_SELF_TEST_LOG_SHA = '934011ce4b4a3f4ebaabe6b69247e06f13f39387976c790ccfc65fb95c2d75ed'   # payload v4's log of the reused probe
BASE_668_MANIFEST = ROOT/'research/builds/macos-20261031/production/kernel-contexts-v4/manifest.json'
# 0.0.671 (payload v7, GTT fix): the 0.0.669 release's EFI (payload v5's candidate state, the live EFI) with kernel 0.0.671 and the 0.0.671 guard.
# Its base is the reviewed 0.0.670 candidate TREE (kernel-contexts-v6, its manifest checked by reviewed_base); its guard is the live 0.0.669 guard with
# the 669 references moved to 671 (bump_guard_671). Payload v6 (0.0.670) was never installed, so v7 carries no 670 recovery copy.
KERNEL_671_SHA = '984989280e30be5dc0d26d9760b698393be0fae99a43e2604b380c7cfdddec22'   # the candidate binary of kernel-contexts-v7
BASE_670_MANIFEST = ROOT/'research/builds/macos-20261101/refresh-60b/kernel-contexts-v6/manifest.json'
# 0.0.672 (payload v8, black band): the 0.0.671 release's EFI (payload v7's candidate state, the live EFI) with kernel 0.0.672 and the 0.0.672 guard.
# Its base is the reviewed 0.0.671 candidate TREE (kernel-contexts-v7, checked by reviewed_base) with PATCH-vs-671-deployed.diff (the UCLK pin and the
# scanout underflow monitor: the same added lines as commit ae303c7) and the 672 markers. Its guard is derived at stage time from the LIVE guard: the
# 0.0.671 guard with the live bundle-38 Metal expectations (release_for_guard reads them); bump_guard_672 moves the 671 references to 672, nothing else.
# Its only system file is still the 0.0.669 navi48test (the verb ABI did not change); its probe is the reused 0.0.667 probe.
KERNEL_672_SHA = '69f5965016d8d6700a4f4b42f23b5f4e4621c110358948adf3ee5e71ca50e00d'   # the candidate binary of kernel-contexts-v8
BUNDLE_671 = 'Navi48Bringup-contexts-0.0.671.kext'
CONFIG_671_SHA = 'fa8c993c839a5a37794a54f178fbcee3e63a06901ddffe9efa9f65eb97429d57'   # payload v7's candidate configuration (v8's baseline)
BASE_671_MANIFEST = ROOT/'research/builds/macos-20261105/kernel-671/kernel-contexts-v7/manifest.json'
# 0.0.673 (payload v9, the black band without a fixed memory clock): payload v8 (0.0.672) was never installed, so 0.0.673 replaces the LIVE 0.0.671 exactly as
# 0.0.672 would have: the 0.0.671 release's EFI (payload v7's candidate state) with kernel 0.0.673 and the 0.0.673 guard. Its base is the reviewed 0.0.672
# candidate TREE (kernel-contexts-v8, checked by reviewed_base) with kernel-0.0.673-over-0.0.672.diff (the Linux DET / watermarks for the one plane, the display
# monitor thread that runs ufmon, the UCLK pin as an AUTO underflow fallback) and the 673 markers. Its guard: the live guard with the 671 references moved to 673
# (bump_guard_673), nothing else. Its only system file is still the 0.0.669 navi48test; its probe is the reused 0.0.667 probe.
KERNEL_673_SHA = 'f53efdb50e4884c2a51c0d2cc2b9ab8d820527ea16851de4201698083dfda8f8'   # the candidate binary of kernel-contexts-v9
BASE_672_MANIFEST = ROOT/'research/builds/macos-20261112/kernel-672/kernel-contexts-v8/manifest.json'
# 0.0.674 (payload v10, the two-stage UCLK fallback): payload v9 (0.0.673) is the kernel INSTALLED now (its guard, EFI and probe are the live ones, read and checked
# at stage time). 0.0.674 replaces it exactly as 0.0.673 replaced 0.0.671: the 0.0.673 release's EFI (payload v9's candidate state) with kernel 0.0.674 and the 0.0.674
# guard. Its base is the reviewed 0.0.673 candidate TREE (kernel-contexts-v9, checked by reviewed_base) with kernel-0.0.674-over-0.0.673.diff and the 674 markers.
# Its guard: the live guard with the 673 references moved to 674 (bump_guard_674), nothing else. Its only system file is still the 0.0.669 navi48test; its probe is
# the reused 0.0.667 probe.
KERNEL_674_SHA = 'b71f535783f95c92dae163953c3579da7b0479a7841ebac120529d88f1399036'   # the candidate binary of kernel-contexts-v10
BUNDLE_673 = 'Navi48Bringup-contexts-0.0.673.kext'
CONFIG_673_SHA = 'd3a39e1a8d281e5685187a156fd03cd2803dd9393c8dac5befc40219b276272c'   # payload v9's candidate configuration (v10's baseline)
BASE_673_MANIFEST = ROOT/'research/builds/macos-20261112/kernel-673/kernel-contexts-v9/manifest.json'
# 0.0.675 (payload v11, GFX clock gating + the thermal policy that never refuses submissions): payload v10 (0.0.674) is the kernel INSTALLED now (its guard, EFI and
# probe are the live ones, read and checked at stage time). 0.0.675 replaces it exactly as 0.0.674 replaced 0.0.673: the 0.0.674 release's EFI (payload v10's
# candidate state) with kernel 0.0.675 and the 0.0.675 guard. Its base is the reviewed 0.0.674 candidate TREE (kernel-contexts-v10, checked by reviewed_base) with
# kernel-0.0.675-over-0.0.674.diff and the 675 markers. Its guard: the live guard with the 674 references moved to 675 (bump_guard_675), nothing else. Its only
# system file is still the 0.0.669 navi48test; its probe is the reused 0.0.667 probe.
KERNEL_675_SHA = '70b8dbfa950be263817f90e4e55750d3484e9ca63be0a9a6f1f83d68e08fefc2'   # the candidate binary of kernel-contexts-v11
BUNDLE_674 = 'Navi48Bringup-contexts-0.0.674.kext'
CONFIG_674_SHA = 'd75bbca200f02456180acab51ba415c7ca120a4e529d43704818078ffc2d9bd5'   # payload v10's candidate configuration (v11's baseline)
BASE_674_MANIFEST = ROOT/'research/builds/macos-20261112/kernel-674/kernel-contexts-v10/manifest.json'
REFRESH_SOURCE = Path(__file__).resolve().parent/'refresh-60/apply_refresh_guard.py'
SYSTEM_SOURCES = {APP+'/navi48test': ROOT/'research/builds/macos-20261101/refresh-60/navi48test/navi48test'}
# the Metal components the live bundle-33 guard pins (stage33-memtype-v1; its Info.plist version is 33)
METAL_33 = {'Contents/MacOS/Navi48Metal': '85c7d8bdfe8c681503a5701afc09ce3b5cddf3ef124fca587913d261c7b4fd5f',
            'Contents/Resources/libvulkan_radeon.dylib': 'f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155',
            'Contents/Resources/libn48xlate.dylib': '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a'}
RELEASES = {
    '0.0.666': {'new': 'Navi48Bringup-contexts-0.0.666.kext', 'recovery': 'RECOVERY/pre-contexts-666-config.plist',
                'from': OLD, 'from_kernel_sha': BASE_SHA, 'from_config_sha': BASE_CONFIG_SHA,
                'kernel_sha': '3ddcb7b087683c0e7a6416232534569d3aca37b747787669711db34d8f2d5f51', 'tests': 5,
                'strings': (), 'guard': 'stage26', 'metal': None, 'metal_version': None,
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': OLD, 'new': 'Navi48Bringup-contexts-0.0.666.kext'}],
                'extras': {'RECOVERY/pre-contexts-666-config.plist': 'baseline'}},
    '0.0.667': {'new': 'Navi48Bringup-contexts-0.0.667.kext', 'recovery': 'RECOVERY/pre-contexts-667-config.plist',
                'from': OLD, 'from_kernel_sha': BASE_SHA, 'from_config_sha': BASE_CONFIG_SHA,
                'kernel_sha': '976b3375082c3f319f940b02f74fd5ff03155884a39feae771edfab62623f287',   # reviewed 0.0.667 build (db8b202)
                'tests': 6, 'strings': ('navi48-off', 'application budget', 'open refused (NoResources)'),
                'edits': [
                    {'path': 'Kernel/Add/7/BundlePath', 'old': OLD, 'new': 'Navi48Bringup-contexts-0.0.667.kext'},
                    {'path': 'Misc/Tools/0/Name', 'old': 'Ripristino EFI (UEFI Shell)',
                     'new': 'Ripristino EFI: driver funzionanti (665)'},
                    {'path': 'Misc/Tools/0/Comment', 'old': 'Recovery shell: restore stage17 config',
                     'new': 'Restores RECOVERY/funzionante-665.plist (kernel 665) and reboots'}],
                'extras': {'RECOVERY/pre-contexts-667-config.plist': 'baseline',
                           'RECOVERY/funzionante-665.plist': 'baseline', STARTUP: STARTUP_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                # the LIVE bundle-30 guard (stage30-vonly-v1) is the base; its Metal expectations are bundle 30
                'guard': 'live', 'metal_version': '30',
                'metal': {'Contents/MacOS/Navi48Metal': '8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230',
                          'Contents/Resources/libn48xlate.dylib': '9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a'}},
    # The baseline is payload v3's candidate EFI (the live state): its 0.0.667 bundle and configuration, its recovery entry and files.
    # The only config edit is the kext's BundlePath. The recovery copy kept here is the 0.0.667 configuration (the baseline bytes).
    # kernel_sha: the 0.0.668 binary of kernel-contexts-v4 (built from the working-tree overlay recorded in its manifest).
    '0.0.668': {'new': 'Navi48Bringup-contexts-0.0.668.kext', 'recovery': 'RECOVERY/pre-contexts-668-config.plist',
                'from': BUNDLE_667, 'from_kernel_sha': KERNEL_667_SHA, 'from_config_sha': CONFIG_667_SHA,
                'kernel_sha': 'ab4c7fed6dd6c6ee52096da25d78f50bc515a51fdbfe8f591654143afe9ccb6d', 'tests': 6,
                # the reviewed probe of payload v3 (its code equals a fresh build of the committed probe source; see same_except_uuid)
                'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_667, 'new': 'Navi48Bringup-contexts-0.0.668.kext'}],
                'extras': {'RECOVERY/pre-contexts-668-config.plist': 'baseline'},
                # carried from the baseline (payload v3): the startup script, the 665 recovery copy and the 667 configuration copy
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                # the CURRENT live guard, which already holds the 0.0.667 capability block: only that block's kernel match moves
                'guard': 'live-668', 'metal_version': '33', 'metal': METAL_33},
    # 0.0.669 (refresh-60): the 0.0.668 release's EFI (payload v4 read as its candidate state) with kernel 0.0.669 and the 0.0.669 guard.
    # Its base is the reviewed 0.0.668 candidate, not a rebuilt 665 base (see reviewed_base); its only system file is navi48test.
    # binary_checks 'not-run': this preparation executes no research-tree binary (see DEFERRED_CHECKS).
    '0.0.669': {'new': 'Navi48Bringup-contexts-0.0.669.kext', 'recovery': 'RECOVERY/pre-contexts-669-config.plist',
                'from': BUNDLE_668, 'from_kernel_sha': KERNEL_668_SHA, 'from_config_sha': CONFIG_668_SHA,
                'kernel_sha': KERNEL_669_SHA, 'tests': 8, 'base': 'reviewed-candidate', 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_668, 'new': 'Navi48Bringup-contexts-0.0.669.kext'}],
                'extras': {'RECOVERY/pre-contexts-669-config.plist': 'baseline'},
                # carried from payload v4's candidate state: the startup script, the 665 recovery copy and the 667 configuration copy
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # the live 0.0.668 guard is the base: its capability block moves to 0.0.669 and the refresh-60 hook is added
                # Metal expectations are NOT static for 0.0.669: release_for_guard() reads them from the live guard at stage time
                # (bundle version and the three Navi48Metal digests) and checks them against the bundle on disk.
                'guard': 'live-669', 'metal_version': None, 'metal': None},
    # 0.0.670 (refresh-60b): the 0.0.669 EFI with kernel 0.0.670. Same reviewed base (0.0.668 candidate tree and binary), same refresh overlay,
    # the 0.0.670 frame-total classifier (both DRR pairs). The guard is the 0.0.669 guard (the live one) with every kernel-0.0.669 reference
    # moved to 0.0.670 (bump_guard_670); its only system file is still the navi48test of 0.0.669 (the verb ABI did not change).
    '0.0.670': {'new': 'Navi48Bringup-contexts-0.0.670.kext', 'recovery': 'RECOVERY/pre-contexts-670-config.plist',
                'from': BUNDLE_669, 'from_kernel_sha': KERNEL_669_SHA, 'from_config_sha': CONFIG_669_SHA,
                'base': 'reviewed-candidate', 'base_kernel_sha': KERNEL_668_SHA,
                'kernel_sha': KERNEL_670_SHA, 'tests': 8, 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_669, 'new': 'Navi48Bringup-contexts-0.0.670.kext'}],
                'extras': {'RECOVERY/pre-contexts-670-config.plist': 'baseline'},
                # carried from payload v5's candidate state: the startup script, the 665 recovery copy, the 667 and the 669 configuration copies
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA, 'RECOVERY/pre-contexts-669-config.plist': CONFIG_668_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # Metal expectations are read from the live guard at stage time (release_for_guard), as for 0.0.669
                'guard': 'live-670', 'metal_version': None, 'metal': None},
    # 0.0.671 (payload v7; refresh-60b + the GTT fix): the 0.0.669 EFI (payload v5's candidate state, which is the live EFI: 0.0.670 was never installed) with
    # kernel 0.0.671 and the 0.0.671 guard. Its base is the reviewed 0.0.670 candidate tree (reviewed-candidate-670). The fix: GTT BOs are wired and NOT
    # physically contiguous (no session-time contiguous allocation under gCliLock). Its only system file is still the 0.0.669 navi48test (the verb ABI did not change).
    '0.0.671': {'new': 'Navi48Bringup-contexts-0.0.671.kext', 'recovery': 'RECOVERY/pre-contexts-671-config.plist',
                'from': BUNDLE_669, 'from_kernel_sha': KERNEL_669_SHA, 'from_config_sha': CONFIG_669_SHA,
                'base': 'reviewed-candidate-670', 'base_kernel_sha': KERNEL_670_SHA,
                'kernel_sha': KERNEL_671_SHA, 'tests': 8, 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz', 'GTT BO could not be given wired pages'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_669, 'new': 'Navi48Bringup-contexts-0.0.671.kext'}],
                'extras': {'RECOVERY/pre-contexts-671-config.plist': 'baseline'},
                # carried from payload v5's candidate state (the same files as 0.0.670's list; the 0.0.670 copy of v6 is not in this EFI)
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA, 'RECOVERY/pre-contexts-669-config.plist': CONFIG_668_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # Metal expectations are read from the live guard at stage time (release_for_guard), as for 0.0.669 and 0.0.670
                'guard': 'live-671', 'metal_version': None, 'metal': None},
    # 0.0.672 (payload v8; the black band): the 0.0.671 EFI (payload v7's candidate state, which is the live EFI) with kernel 0.0.672 and the 0.0.672 guard.
    # Its base is the reviewed 0.0.671 candidate tree (reviewed-candidate-671). The change: the display UCLK pin (boot-arg navi48-uclkpin=0 turns it off;
    # registry property Navi48,UclkPin) and the scanout underflow monitor (boot-arg navi48-ufmon=0; registry property Navi48,DisplayUnderflow).
    '0.0.672': {'new': 'Navi48Bringup-contexts-0.0.672.kext', 'recovery': 'RECOVERY/pre-contexts-672-config.plist',
                'from': BUNDLE_671, 'from_kernel_sha': KERNEL_671_SHA, 'from_config_sha': CONFIG_671_SHA,
                'base': 'reviewed-candidate-671', 'base_kernel_sha': KERNEL_671_SHA,
                'kernel_sha': KERNEL_672_SHA, 'tests': 8, 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz', 'GTT BO could not be given wired pages',
                            'Navi48,UclkPin', 'Navi48,DisplayUnderflow'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_671, 'new': 'Navi48Bringup-contexts-0.0.672.kext'}],
                'extras': {'RECOVERY/pre-contexts-672-config.plist': 'baseline'},
                # carried from payload v7's candidate state: the startup script, the 665 recovery copy, the 667, 669 and 671 configuration copies
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA, 'RECOVERY/pre-contexts-669-config.plist': CONFIG_668_SHA,
                            'RECOVERY/pre-contexts-671-config.plist': CONFIG_669_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # Metal expectations are read from the live guard at stage time (release_for_guard), as for 0.0.669 to 0.0.671
                'guard': 'live-672', 'metal_version': None, 'metal': None},
    # 0.0.673 (payload v9; the black band without a fixed memory clock): the 0.0.671 EFI (payload v7's candidate state, the live EFI; payload v8 was never
    # installed) with kernel 0.0.673 and the 0.0.673 guard. Its base is the reviewed 0.0.672 candidate tree (reviewed-candidate-672). The change: the display
    # gets Linux's DET (20 segments) and watermarks (navi48-det=0 / navi48-wm=0 / navi48-sr=0 turn the steps off; registry property Navi48,DisplayArb), ufmon
    # runs on a display monitor thread (navi48-dispmon=0 turns it off), and the UCLK pin is an underflow fallback (navi48-uclkpin=1 forces it, =0 turns it off).
    '0.0.673': {'new': 'Navi48Bringup-contexts-0.0.673.kext', 'recovery': 'RECOVERY/pre-contexts-673-config.plist',
                'from': BUNDLE_671, 'from_kernel_sha': KERNEL_671_SHA, 'from_config_sha': CONFIG_671_SHA,
                'base': 'reviewed-candidate-672', 'base_kernel_sha': KERNEL_672_SHA,
                'kernel_sha': KERNEL_673_SHA, 'tests': 8, 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz', 'GTT BO could not be given wired pages',
                            'Navi48,UclkPin', 'Navi48,DisplayUnderflow', 'Navi48,DisplayArb', 'disparb: display monitor started', 'ufmon: UCLK fallback'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_671, 'new': 'Navi48Bringup-contexts-0.0.673.kext'}],
                'extras': {'RECOVERY/pre-contexts-673-config.plist': 'baseline'},
                # carried from payload v7's candidate state: the startup script, the 665 recovery copy, the 667, 669 and 671 configuration copies
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA, 'RECOVERY/pre-contexts-669-config.plist': CONFIG_668_SHA,
                            'RECOVERY/pre-contexts-671-config.plist': CONFIG_669_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # Metal expectations are read from the live guard at stage time (release_for_guard), as for 0.0.669 to 0.0.672
                'guard': 'live-673', 'metal_version': None, 'metal': None},
    # 0.0.674 (payload v10; the two-stage UCLK fallback): the 0.0.673 release's EFI (payload v9's candidate state, the live EFI) with kernel 0.0.674 and the 0.0.674
    # guard. Its base is the reviewed 0.0.673 candidate tree (reviewed-candidate-673). The change: a display underflow first forces the stutter off again (stage 1,
    # no pin); the next trigger pins the memory clock (stage 2); an AUTO pin is released once after 10 min with the display on and no counted underflow (navi48-uclkpin=1
    # keeps its pin); an OPTC-only status is still one event (diagnostic optcOnly count; the brief's exclusion was not applied, see navi48_ufmon_pure.h). Its guard is derived at stage time from the LIVE guard
    # (payload v9's guard, installed): bump_guard_674 moves the 673 references to 674, nothing else.
    '0.0.674': {'new': 'Navi48Bringup-contexts-0.0.674.kext', 'recovery': 'RECOVERY/pre-contexts-674-config.plist',
                'from': BUNDLE_673, 'from_kernel_sha': KERNEL_673_SHA, 'from_config_sha': CONFIG_673_SHA,
                'base': 'reviewed-candidate-673', 'base_kernel_sha': KERNEL_673_SHA,
                'kernel_sha': KERNEL_674_SHA, 'tests': 8, 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz', 'GTT BO could not be given wired pages',
                            'Navi48,UclkPin', 'Navi48,DisplayUnderflow', 'Navi48,DisplayArb', 'disparb: display monitor started', 'ufmon: UCLK fallback',
                            '10 min without underflow', 'OPTC alone %llu', 'fallback stage 1 (stutter off, no pin)'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_673, 'new': 'Navi48Bringup-contexts-0.0.674.kext'}],
                'extras': {'RECOVERY/pre-contexts-674-config.plist': 'baseline'},
                # carried from payload v9's candidate state: the startup script, the 665 recovery copy, and the 667, 669, 671 and 673 configuration copies
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA, 'RECOVERY/pre-contexts-669-config.plist': CONFIG_668_SHA,
                            'RECOVERY/pre-contexts-671-config.plist': CONFIG_669_SHA, 'RECOVERY/pre-contexts-673-config.plist': CONFIG_671_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # Metal expectations are read from the live guard at stage time (release_for_guard), as for 0.0.669 to 0.0.673
                'guard': 'live-674', 'metal_version': None, 'metal': None},
    # 0.0.675 (payload v11; GFX clock gating + thermal policy): the 0.0.674 release's EFI (payload v10's candidate state, the live EFI) with kernel 0.0.675 and the
    # 0.0.675 guard. Its base is the reviewed 0.0.674 candidate tree (reviewed-candidate-674). The change: Linux gfx_v12_0_update_gfx_clock_gating runs once after
    # the full bring-up ladder (navi48-cg=0 turns it off, navi48-cg-ints=0 leaves the CP interrupt enables untouched; registry property Navi48,ClockGating), and a
    # thermal TRIP (default 100 C, WARN 90 C) clamps GFXCLK to the PMFW minimum through the SMU until the hotspot stays below 85 C for 10 s instead of refusing
    # submissions. The idle clamp default is unchanged. Its guard is derived at stage time from the LIVE guard (payload v10's guard, installed): bump_guard_675
    # moves the 674 references to 675, nothing else.
    '0.0.675': {'new': 'Navi48Bringup-contexts-0.0.675.kext', 'recovery': 'RECOVERY/pre-contexts-675-config.plist',
                'from': BUNDLE_674, 'from_kernel_sha': KERNEL_674_SHA, 'from_config_sha': CONFIG_674_SHA,
                'base': 'reviewed-candidate-674', 'base_kernel_sha': KERNEL_674_SHA,
                'kernel_sha': KERNEL_675_SHA, 'tests': 8, 'probe_reuse': PROBE_667_SHA,
                'strings': ('navi48-off', 'application budget', 'open refused (NoResources)', 'the hi pool could not take it',
                            'refresh60: verb action', 'Navi48,RefreshHz', 'GTT BO could not be given wired pages',
                            'Navi48,UclkPin', 'Navi48,DisplayUnderflow', 'Navi48,DisplayArb', 'disparb: display monitor started', 'ufmon: UCLK fallback',
                            '10 min without underflow', 'OPTC alone %llu', 'fallback stage 1 (stutter off, no pin)',
                            'Navi48,ClockGating', 'navi48-cg-ints', 'event=%s reason=%s hotspot=%d power_state=%u',
                            'TRIP clamps GFXCLK, never refuses submissions'),
                'edits': [{'path': 'Kernel/Add/7/BundlePath', 'old': BUNDLE_674, 'new': 'Navi48Bringup-contexts-0.0.675.kext'}],
                'extras': {'RECOVERY/pre-contexts-675-config.plist': 'baseline'},
                # carried from payload v10's candidate state: the startup script, the 665 recovery copy, and the 667, 669, 671, 673 and 674 configuration copies
                'carried': {STARTUP: STARTUP_SHA, 'RECOVERY/funzionante-665.plist': BASE_CONFIG_SHA,
                            'RECOVERY/pre-contexts-667-config.plist': BASE_CONFIG_SHA, 'RECOVERY/pre-contexts-669-config.plist': CONFIG_668_SHA,
                            'RECOVERY/pre-contexts-671-config.plist': CONFIG_669_SHA, 'RECOVERY/pre-contexts-673-config.plist': CONFIG_671_SHA,
                            'RECOVERY/pre-contexts-674-config.plist': CONFIG_673_SHA},
                'recovery_entry': RECOVERY_ENTRY,
                'system_files': {APP+'/navi48test': NAVI48TEST_669_SHA},
                'binary_checks': 'not-run', 'self_test_log_sha': PROBE_SELF_TEST_LOG_SHA,
                # Metal expectations are read from the live guard at stage time (release_for_guard), as for 0.0.669 to 0.0.674
                'guard': 'live-675', 'metal_version': None, 'metal': None},
}
# binary_checks 'not-run' (0.0.669): the OpenCore validator and the probe's self-test are research-tree executables, so the preparation
# does not run them. The payload records that; the installer must validate EFI/OC/config.plist before installing.
DEFERRED_CHECKS = {'ocvalidate': 'not run: research-tree executable; validate EFI/OC/config.plist before installation',
                   'probe_self_test': 'not re-run: research-tree executable; evidence/probe-self-test.log is the recorded log of the identical reused probe'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and p.as_posix() == name


def tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Missing/unsafe tree: '+str(root))
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ValueError('Unsafe file: '+str(p))
        if p.is_file(): result[p.relative_to(root).as_posix()] = sha(p)
    return result


def metadata(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Unsafe target: '+str(path))
    return {'sha256': sha(path), 'mode': path.stat().st_mode & 0o777} if path.exists() else None


def scoped(inventory):
    return {k: v for k, v in inventory.items() if k.startswith(SCOPE)}


def scoped_tree(root):
    """Inventory of the payload-owned EFI paths (OC/ and RECOVERY/) only; the rest of the volume is never read."""
    result = {}
    for top in ('OC', 'RECOVERY'):
        base = root/top
        if base.is_symlink() or not base.is_dir(): raise ValueError('Missing/unsafe tree: '+str(base))
        for p in sorted(base.rglob('*')):
            if p.is_symlink() or not (p.is_file() or p.is_dir()): raise ValueError('Unsafe file: '+str(p))
            if p.is_file(): result[p.relative_to(root).as_posix()] = sha(p)
    return result


def efi_mount(uuid):
    """Mount point of the single mounted EFI partition with this VolumeUUID (the mount root; EFI/ is below it)."""
    listing = plistlib.loads(subprocess.check_output(['diskutil','list','-plist']))
    matches = []
    for disk in listing.get('AllDisksAndPartitions', []):
        for part in disk.get('Partitions', []):
            if part.get('Content') != 'EFI': continue
            info = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',part['DeviceIdentifier']]))
            if str(info.get('VolumeUUID','')).upper() == uuid: matches.append(info)
    if len(matches) != 1 or not matches[0].get('MountPoint'):
        raise ValueError('Expected one mounted EFI partition with VolumeUUID %s' % uuid)
    return Path(matches[0]['MountPoint'])


def boot_uuid():
    return subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],text=True).strip().lower()


def baseline_config(data, bundle=OLD):
    entries = [e for e in data['Kernel']['Add'] if e.get('Enabled') and 'Navi48Bringup' in e.get('BundlePath','')]
    if len(entries) != 1 or entries[0]['BundlePath'] != bundle:
        raise ValueError('Expected exactly one active baseline entry: ' + bundle)
    return entries[0]


def diff_paths(a, b, prefix=''):
    """Paths (like Kernel/Add/7/BundlePath) at which two plist values differ."""
    if type(a) is not type(b):
        return [prefix]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f'{prefix}/{k}')
            else:
                out += diff_paths(a[k], b[k], f'{prefix}/{k}')
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [prefix]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f'{prefix}/{i}')
        return out
    return [] if a == b else [prefix]


def path_slot(data, path):
    """(container, key) for a slash path such as Kernel/Add/7/BundlePath; list indexes are integers."""
    parts = path.split('/')
    node = data
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    return node, (int(last) if isinstance(node, list) else last)


def expected_config(original, rel):
    """The baseline boot configuration with exactly the release's listed edits; each edit must find its listed old value."""
    config = copy.deepcopy(original)
    for edit in rel['edits']:
        container, key = path_slot(config, edit['path'])
        if container[key] != edit['old']:
            raise ValueError('Baseline value differs from the listed edit: ' + edit['path'])
        container[key] = edit['new']
    return config


PROBE_BLOCK = r'''[[ $(shasum -a 256 "$APP/context-isolation-probe" | cut -d " " -f 1) == PROBE_DIGEST ]] || { echo 'STOP context profile checker changed'; exit 1; }
profilecheck=$("$APP/context-isolation-probe" --check-profile 2>&1) || { echo "STOP dynamic context profile: $profilecheck"; exit 1; }
echo "CONTEXT_PROFILE_VERIFIED=$profilecheck"
logicalpage=$("$NT" accel sessstat 95 2>&1) || { echo "STOP logical context diagnostic page: $logicalpage"; exit 1; }
printf '%s\n' "$logicalpage" | grep -Eq 'slot / VMID / session[[:space:]]*:[[:space:]]*63[[:space:]]*/' || { echo 'STOP missing logical context 63'; exit 1; }
echo 'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64'
'''


# Inserted before the live guard's fbidentity line. Loaded 0.0.667: the capability checks (dynamic VMID, logical
# context 63). Loaded 0.0.665 (the recovery entry restored that configuration): the checks are skipped and the live guard
# runs as it always has. Any other kernel stops. Only additions: no live line is removed or changed.
KERNEL_BRANCH = r'''if printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(0\.0\.667\)'; then
PROBE_BLOCK_HERE
elif printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(0\.0\.665\)'; then
echo 'CAPABILITY_CHECKS=skipped for kernel 0.0.665 (recovery configuration)'
else
echo 'STOP expected kernel 667 or 665'; exit 1
fi
'''
# 0.0.668: the same block with its kernel match and its STOP text moved to 0.0.668 (the 0.0.665 branch stays).
KERNEL_BRANCH_668 = KERNEL_BRANCH.replace(r'\(0\.0\.667\)', r'\(0\.0\.668\)').replace('STOP expected kernel 667 or 665', 'STOP expected kernel 668 or 665')
# 0.0.669: the same block with its kernel match and its STOP text moved to 0.0.669 (the 0.0.665 branch stays).
KERNEL_BRANCH_669 = KERNEL_BRANCH_668.replace(r'\(0\.0\.668\)', r'\(0\.0\.669\)').replace('STOP expected kernel 668 or 665', 'STOP expected kernel 669 or 665')


def capability_block(branch, probe_sha):
    """A kernel branch with its probe check filled in: the block as guard_live inserts it."""
    return branch.replace('PROBE_BLOCK_HERE\n', PROBE_BLOCK.replace('PROBE_DIGEST', probe_sha))


def bump_guard(original, probe_sha):
    """0.0.668: the live guard with its reviewed 0.0.667 capability block replaced by the 0.0.668 block. Only that block
    changes: its kernel match and STOP text move to 0.0.668, the 0.0.665 branch stays, and the probe digest follows the staged
    probe (identical when the probe is byte-identical). The block must be there exactly once, as the reviewed 0.0.667 insertion
    with the 0.0.667 probe digest; everything else in the guard is kept byte for byte."""
    old = capability_block(KERNEL_BRANCH, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.667 capability block')
    return original.replace(old, capability_block(KERNEL_BRANCH_668, probe_sha))


def bump_guard_669(original, probe_sha):
    """0.0.669: the 0.0.668 guard with its reviewed 0.0.668 capability block replaced by the 0.0.669 block. As in bump_guard, only
    that block changes: its kernel match and STOP text move to 0.0.669, the 0.0.665 branch stays, the probe digest follows the probe."""
    old = capability_block(KERNEL_BRANCH_668, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.668 capability block')
    return original.replace(old, capability_block(KERNEL_BRANCH_669, probe_sha))


# 0.0.670: the same capability block with its kernel match and STOP text moved to 0.0.670 (the 0.0.665 branch stays).
KERNEL_BRANCH_670 = KERNEL_BRANCH_669.replace(r'\(0\.0\.669\)', r'\(0\.0\.670\)').replace('STOP expected kernel 669 or 665', 'STOP expected kernel 670 or 665')
# The refresh-60 hook names kernel 0.0.669 on three lines (its comment, its regex, its skip message). 0.0.670 moves exactly these lines.
HOOK_669_LINES = (
    ("# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.669 and",
     "# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.670 and"),
    (r"  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.669\)'",
     r"  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.670\)'"),
    ("    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.669 and RDNA4FB 0.0.9'",
     "    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.670 and RDNA4FB 0.0.9'"),
)


def bump_guard_670(original, probe_sha):
    """0.0.670: the 0.0.669 guard (the live guard, with the reviewed 0.0.669 capability block and the refresh-60 hook) with every reference to
    kernel 0.0.669 moved to 0.0.670: the capability block (its kernel match and STOP text) and the three hook lines of HOOK_669_LINES. Each
    replacement must find its line exactly once, and no 0.0.669 reference may remain. The probe digest follows the probe. Nothing else changes."""
    old = capability_block(KERNEL_BRANCH_669, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.669 capability block')
    text = original.replace(old, capability_block(KERNEL_BRANCH_670, probe_sha))
    for before, after in HOOK_669_LINES:
        if text.count(before) != 1:
            raise ValueError('Activation guard lacks the reviewed refresh-60 hook line: ' + before[:60])
        text = text.replace(before, after)
    if re.search(r'0\.0\.669|kernel 669', text):
        raise ValueError('Activation guard still names kernel 0.0.669 after the 0.0.670 bump')
    return text


# 0.0.671 (payload v7): the same rule as 0.0.670, applied to the LIVE 0.0.669 guard (payload v5's, installed now): the capability block's kernel match
# and STOP text move to 0.0.671 (the 0.0.665 branch stays), and the three refresh-60 hook lines that name 0.0.669 move to 0.0.671. Nothing else changes.
KERNEL_BRANCH_671 = KERNEL_BRANCH_669.replace(r'\(0\.0\.669\)', r'\(0\.0\.671\)').replace('STOP expected kernel 669 or 665', 'STOP expected kernel 671 or 665')
# (written out, not derived: the hook's regex spells the version as 0\.0\.669, so a plain string replacement of 0.0.670 would not reach it)
HOOK_669_TO_671_LINES = (
    ("# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.669 and",
     "# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.671 and"),
    (r"  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.669\)'",
     r"  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.671\)'"),
    ("    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.669 and RDNA4FB 0.0.9'",
     "    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.671 and RDNA4FB 0.0.9'"),
)


def bump_guard_671(original, probe_sha):
    """0.0.671: the live 0.0.669 guard (payload v5's, with its reviewed 0.0.669 capability block and the refresh-60 hook) with every reference to kernel
    0.0.669 moved to 0.0.671, exactly as bump_guard_670 does for 0.0.670. Each replacement must find its line exactly once, and no 0.0.669 reference
    may remain. The probe digest follows the probe. Nothing else changes."""
    old = capability_block(KERNEL_BRANCH_669, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.669 capability block')
    text = original.replace(old, capability_block(KERNEL_BRANCH_671, probe_sha))
    for before, after in HOOK_669_TO_671_LINES:
        if text.count(before) != 1:
            raise ValueError('Activation guard lacks the reviewed refresh-60 hook line: ' + before[:60])
        text = text.replace(before, after)
    if re.search(r'0\\?\.0\\?\.669|kernel 669', text):   # the plain and the regex-escaped spelling
        raise ValueError('Activation guard still names kernel 0.0.669 after the 0.0.671 bump')
    return text


# 0.0.672 (payload v8): the same rule as 0.0.671, applied to the LIVE guard at stage time: the capability block's kernel match and STOP text move to
# 0.0.672 (the 0.0.665 branch stays), and the three refresh-60 hook lines that name 0.0.671 move to 0.0.672. Nothing else changes.
KERNEL_BRANCH_672 = KERNEL_BRANCH_671.replace(r'\(0\.0\.671\)', r'\(0\.0\.672\)').replace('STOP expected kernel 671 or 665', 'STOP expected kernel 672 or 665')
# (written out, as HOOK_669_TO_671_LINES is: the hook's regex spells the version as 0\.0\.671)
HOOK_671_TO_672_LINES = (
    ("# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.671 and",
     "# 0644 regular file AND the loaded kexts are com.navi48.bringup 0.0.672 and"),
    (r"  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.671\)'",
     r"  local re_bringup='com\.navi48\.bringup[[:space:]]+\(0\.0\.672\)'"),
    ("    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.671 and RDNA4FB 0.0.9'",
     "    echo 'REFRESH60_SKIPPED loaded kexts are not 0.0.672 and RDNA4FB 0.0.9'"),
)


def bump_guard_672(original, probe_sha):
    """0.0.672: the live 0.0.671 guard (payload v7's, or the live one, which differs only in its bundle-38 Metal expectations: those are kept
    byte for byte) with every reference to kernel 0.0.671 moved to 0.0.672, exactly as bump_guard_671 does for 0.0.671. Each replacement must find
    its line exactly once, and no 0.0.671 reference may remain. The probe digest follows the probe. Nothing else changes."""
    old = capability_block(KERNEL_BRANCH_671, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.671 capability block')
    text = original.replace(old, capability_block(KERNEL_BRANCH_672, probe_sha))
    for before, after in HOOK_671_TO_672_LINES:
        if text.count(before) != 1:
            raise ValueError('Activation guard lacks the reviewed refresh-60 hook line: ' + before[:60])
        text = text.replace(before, after)
    if re.search(r'0\\?\.0\\?\.671|kernel 671', text):   # the plain and the regex-escaped spelling
        raise ValueError('Activation guard still names kernel 0.0.671 after the 0.0.672 bump')
    return text


# 0.0.673 (payload v9): the 0.0.672 rule applied to the LIVE (0.0.671) guard, with 673 in place of 672: the capability block's kernel match and STOP text
# and the three refresh-60 hook lines that name 0.0.671 move to 0.0.673. Nothing else changes.
KERNEL_BRANCH_673 = KERNEL_BRANCH_671.replace(r'\(0\.0\.671\)', r'\(0\.0\.673\)').replace('STOP expected kernel 671 or 665', 'STOP expected kernel 673 or 665')
HOOK_671_TO_673_LINES = tuple((before, after.replace('0.0.672', '0.0.673').replace(r'0\.0\.672', r'0\.0\.673')) for before, after in HOOK_671_TO_672_LINES)


def bump_guard_673(original, probe_sha):
    """0.0.673: the live 0.0.671 guard with every reference to kernel 0.0.671 moved to 0.0.673, exactly as bump_guard_672 does for 0.0.672 (each
    replacement must find its line exactly once, no 0.0.671 reference may remain, the bundle Metal expectations are kept byte for byte)."""
    old = capability_block(KERNEL_BRANCH_671, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.671 capability block')
    text = original.replace(old, capability_block(KERNEL_BRANCH_673, probe_sha))
    for before, after in HOOK_671_TO_673_LINES:
        if text.count(before) != 1:
            raise ValueError('Activation guard lacks the reviewed refresh-60 hook line: ' + before[:60])
        text = text.replace(before, after)
    if re.search(r'0\\?\.0\\?\.671|kernel 671', text):   # the plain and the regex-escaped spelling
        raise ValueError('Activation guard still names kernel 0.0.671 after the 0.0.673 bump')
    return text


# 0.0.674 (payload v10): the 0.0.673 rule applied to the LIVE (0.0.673) guard, with 674 in place of 673: the capability block's kernel match and STOP text
# and the three refresh-60 hook lines that name 0.0.673 move to 0.0.674. Nothing else changes.
KERNEL_BRANCH_674 = KERNEL_BRANCH_673.replace(r'\(0\.0\.673\)', r'\(0\.0\.674\)').replace('STOP expected kernel 673 or 665', 'STOP expected kernel 674 or 665')
HOOK_673_TO_674_LINES = tuple((after, after.replace('0.0.673', '0.0.674').replace(r'0\.0\.673', r'0\.0\.674')) for _, after in HOOK_671_TO_673_LINES)


def bump_guard_674(original, probe_sha):
    """0.0.674: the live 0.0.673 guard with every reference to kernel 0.0.673 moved to 0.0.674, exactly as bump_guard_673 does for 0.0.673 (each
    replacement must find its line exactly once, no 0.0.673 reference may remain, the bundle Metal expectations are kept byte for byte)."""
    old = capability_block(KERNEL_BRANCH_673, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.673 capability block')
    text = original.replace(old, capability_block(KERNEL_BRANCH_674, probe_sha))
    for before, after in HOOK_673_TO_674_LINES:
        if text.count(before) != 1:
            raise ValueError('Activation guard lacks the reviewed refresh-60 hook line: ' + before[:60])
        text = text.replace(before, after)
    if re.search(r'0\\?\.0\\?\.673|kernel 673', text):   # the plain and the regex-escaped spelling
        raise ValueError('Activation guard still names kernel 0.0.673 after the 0.0.674 bump')
    return text


# 0.0.675 (payload v11): the 0.0.674 rule applied to the LIVE (0.0.674) guard, with 675 in place of 674: the capability block's kernel match and STOP text
# and the three refresh-60 hook lines that name 0.0.674 move to 0.0.675. Nothing else changes.
KERNEL_BRANCH_675 = KERNEL_BRANCH_674.replace(r'\(0\.0\.674\)', r'\(0\.0\.675\)').replace('STOP expected kernel 674 or 665', 'STOP expected kernel 675 or 665')
HOOK_674_TO_675_LINES = tuple((after, after.replace('0.0.674', '0.0.675').replace(r'0\.0\.674', r'0\.0\.675')) for _, after in HOOK_673_TO_674_LINES)


def bump_guard_675(original, probe_sha):
    """0.0.675: the live 0.0.674 guard with every reference to kernel 0.0.674 moved to 0.0.675, exactly as bump_guard_674 does for 0.0.674 (each
    replacement must find its line exactly once, no 0.0.674 reference may remain, the bundle Metal expectations are kept byte for byte)."""
    old = capability_block(KERNEL_BRANCH_674, PROBE_667_SHA)
    if original.count(old) != 1:
        raise ValueError('Activation guard lacks the reviewed 0.0.674 capability block')
    text = original.replace(old, capability_block(KERNEL_BRANCH_675, probe_sha))
    for before, after in HOOK_674_TO_675_LINES:
        if text.count(before) != 1:
            raise ValueError('Activation guard lacks the reviewed refresh-60 hook line: ' + before[:60])
        text = text.replace(before, after)
    if re.search(r'0\\?\.0\\?\.674|kernel 674', text):   # the plain and the regex-escaped spelling
        raise ValueError('Activation guard still names kernel 0.0.674 after the 0.0.675 bump')
    return text


def refresh_patch(text):
    """The refresh-60 hook (additions only) from tools/baremetal/navi44-desktop/refresh-60/apply_refresh_guard.py. The module is loaded
    by its absolute path; sys.path is not changed."""
    spec = importlib.util.spec_from_file_location('apply_refresh_guard', REFRESH_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.apply_refresh_patch(text)


METAL_COMPONENTS = ('Contents/MacOS/Navi48Metal', 'Contents/Resources/libvulkan_radeon.dylib', 'Contents/Resources/libn48xlate.dylib')


def live_metal_pins(guard_text):
    """The Metal bundle a guard expects, read from the guard itself: its bundle version and the digests of the three components."""
    versions = re.findall(r'"\$bundle_version" == (\d+) \]\]', guard_text)
    if len(versions) != 1:
        raise ValueError('The guard must expect exactly one Metal bundle version')
    pins = dict(re.findall(r'shasum -a 256 "/Library/GPUBundles/Navi48Metal\.bundle/(Contents/[^"]+)" \| cut -d " " -f 1\) == ([0-9a-f]{64})',
                           guard_text))
    if set(pins) != set(METAL_COMPONENTS):
        raise ValueError('The guard pins %s, expected the three Navi48Metal components' % sorted(pins))
    return versions[0], pins


def release_for_guard(rel, guard_text):
    """0.0.669/0.0.670: the release with the Metal bundle its guard expects (read from that guard; see live_metal_pins). Other releases unchanged."""
    if rel['guard'] not in ('live-669', 'live-670', 'live-671', 'live-672', 'live-673', 'live-674', 'live-675'):
        return rel
    version, pins = live_metal_pins(guard_text)
    return {**rel, 'metal': pins, 'metal_version': version}


def guard_669(original, probe_sha):
    """The 0.0.669 guard, derived at stage time from the LIVE guard: apply_refresh_patch(bump_guard_669(original)). The bump requires the
    reviewed 0.0.668 capability block exactly once and changes nothing else; the refresh-60 hook adds lines only. Every other line of the
    live guard (its profile, its Metal expectations) is kept byte for byte, so the derived guard expects whatever bundle the live guard expects."""
    return refresh_patch(bump_guard_669(original, probe_sha))


def guard_live(original, probe_sha, version):
    """The live bundle-30 guard plus only the 0.0.667 branch (see KERNEL_BRANCH). Profile name, Metal hashes and every
    other live line are the live file's own."""
    if version != '0.0.667': raise ValueError('The live guard is only derived for 0.0.667')
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    kext_check = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    if original.count(kext_check) != 1: raise ValueError('Unexpected kext check in the live guard')
    marker = 'fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)'
    branch = capability_block(KERNEL_BRANCH, probe_sha)
    replace(marker, branch + marker)
    return original


def make_guard(rel, original, probe_sha, version):
    if rel['guard'] == 'live-668':
        if version != '0.0.668': raise ValueError('The live-668 guard is only derived for 0.0.668')
        return bump_guard(original, probe_sha)
    if rel['guard'] == 'live-669':
        if version != '0.0.669': raise ValueError('The live-669 guard is only derived for 0.0.669')
        return guard_669(original, probe_sha)
    if rel['guard'] == 'live-670':
        if version != '0.0.670': raise ValueError('The live-670 guard is only derived for 0.0.670')
        return bump_guard_670(original, probe_sha)
    if rel['guard'] == 'live-671':
        if version != '0.0.671': raise ValueError('The live-671 guard is only derived for 0.0.671')
        return bump_guard_671(original, probe_sha)
    if rel['guard'] == 'live-672':
        if version != '0.0.672': raise ValueError('The live-672 guard is only derived for 0.0.672')
        return bump_guard_672(original, probe_sha)
    if rel['guard'] == 'live-673':
        if version != '0.0.673': raise ValueError('The live-673 guard is only derived for 0.0.673')
        return bump_guard_673(original, probe_sha)
    if rel['guard'] == 'live-674':
        if version != '0.0.674': raise ValueError('The live-674 guard is only derived for 0.0.674')
        return bump_guard_674(original, probe_sha)
    if rel['guard'] == 'live-675':
        if version != '0.0.675': raise ValueError('The live-675 guard is only derived for 0.0.675')
        return bump_guard_675(original, probe_sha)
    return guard_live(original, probe_sha, version) if rel['guard'] == 'live' else guard_text(original, probe_sha, version)


def guard_text(original, probe_sha, version):
    """The stage26 guard transformation (0.0.666 payload only)."""
    build = version.rsplit('.', 1)[1]
    version_re = version.replace('.', r'\.')
    def replace(old, new):
        nonlocal original
        if original.count(old) != 1: raise ValueError('Unexpected activation guard baseline: '+old[:80])
        original = original.replace(old, new)
    replace('PROFILE=stage25-archive-boundary-v1', 'PROFILE='+PROFILE)
    replace("echo 'CANDIDATE=stage25-archive-boundary'", "echo 'CANDIDATE=stage26-logical-contexts'")
    marker = '[[ "$loaded" == *com.navi48.bringup* && "$loaded" == *com.hackintosh.RDNA4FB* ]] || { echo \'STOP bringup or RDNA4FB kext missing\'; exit 1; }'
    replace(marker, marker + '\n' + r'''printf '%s\n' "$loaded" | grep -Eq 'com\.navi48\.bringup[[:space:]]+\(@RE@\)' || { echo 'STOP expected kernel @BUILD@'; exit 1; }'''
            .replace('@RE@', version_re).replace('@BUILD@', build))
    marker = 'fbidentity=$(ioreg -r -c RDNA4FB -d 1 -w 0 2>/dev/null || true)'
    probe = r'''[[ $(shasum -a 256 "$APP/context-isolation-probe" | cut -d " " -f 1) == PROBE_DIGEST ]] || { echo 'STOP context profile checker changed'; exit 1; }
profilecheck=$("$APP/context-isolation-probe" --check-profile 2>&1) || { echo "STOP dynamic context profile: $profilecheck"; exit 1; }
echo "CONTEXT_PROFILE_VERIFIED=$profilecheck"
logicalpage=$("$NT" accel sessstat 95 2>&1) || { echo "STOP logical context diagnostic page: $logicalpage"; exit 1; }
printf '%s\n' "$logicalpage" | grep -Eq 'slot / VMID / session[[:space:]]*:[[:space:]]*63[[:space:]]*/' || { echo 'STOP missing logical context 63'; exit 1; }
echo 'LOGICAL_CONTEXT_CAPACITY_VERIFIED=64'
'''.replace('PROBE_DIGEST', probe_sha)
    replace(marker, probe+'\n'+marker)
    return original


def release_of(m):
    version = m.get('candidate_version', '0.0.666')
    if version not in RELEASES:
        raise ValueError('Unknown candidate release: '+version)
    return version, RELEASES[version]


def baseline_sources(snapshot, state='baseline'):
    """The live EFI as recorded by an earlier verified payload. state 'baseline': the EFI before that payload's release (its
    baseline_efi_files, hashed from the live EFI when it was prepared; OC/config.plist from its recovery copy). state
    'candidate': the EFI that payload installs, i.e. the live state once it is installed (its candidate_efi_files, as staged).
    Returns {path: source}."""
    if state not in ('baseline', 'candidate'):
        raise ValueError('Unknown baseline state: ' + state)
    verify(snapshot, live=False)
    m = json.loads((snapshot/'manifest.json').read_text())
    _, rel = release_of(m)
    sources = {}
    recorded = scoped(m['candidate_efi_files'] if state == 'candidate' else m['baseline_efi_files'])
    for name, digest in recorded.items():
        if not safe(name):
            raise ValueError('Unsafe baseline path: '+name)
        path = snapshot/'EFI'/rel['recovery'] if (state == 'baseline' and name == 'OC/config.plist') else snapshot/'EFI'/name
        if sha(path) != digest:
            raise ValueError('Snapshot differs from its recorded %s state: %s' % (state, name))
        sources[name] = path
    return sources


def verify(payload, live=False, efi=None, system_root=Path('/')):
    if payload.is_symlink(): raise ValueError('Symlink payload')
    m = json.loads((payload/'manifest.json').read_text())
    if m.get('schema') != 1 or m.get('profile') != PROFILE or m.get('status') != 'prepared-not-installed':
        raise ValueError('Unexpected kernel payload profile')
    version, rel = release_of(m)
    if rel['guard'] in ('live-669', 'live-670', 'live-671', 'live-672', 'live-673', 'live-674', 'live-675'):
        rel = release_for_guard(rel, (payload/'system'/GUARD).read_text())
    actual = tree(payload); actual.pop('manifest.json')
    if actual != m['files'] or set(actual) != set(m['file_modes']): raise ValueError('Payload inventory changed')
    for name in actual:
        if not safe(name) or not name.startswith(('EFI/','system/','evidence/')) or (payload/name).stat().st_mode & 0o777 != m['file_modes'][name]:
            raise ValueError('Payload path/mode changed: '+name)
    system = {p[7:] for p in actual if p.startswith('system/')}
    if system != {GUARD,PROBE,*rel.get('system_files',{})} or set(m['system_before']) != system or set(m['critical_system_files']) != set(CRITICAL):
        raise ValueError('Unexpected system write or dependency set')
    if any(m['file_modes']['system/'+name] != 0o755 for name in system):
        raise ValueError('System executables require mode 755')
    for name, digest in rel.get('system_files',{}).items():
        if sha(payload/'system'/name) != digest: raise ValueError('System file is not the reviewed file: '+name)
    base, staged = m['baseline_efi_files'], tree(payload/'EFI')
    if staged != m['candidate_efi_files'] or base['OC/config.plist'] != m['baseline_config_sha256'] or staged['OC/config.plist'] != m['candidate_config_sha256']:
        raise ValueError('EFI inventory changed')
    if base['OC/config.plist'] != rel['from_config_sha']:
        raise ValueError('Baseline boot configuration is not the reviewed configuration of release ' + version)
    for name, digest in base.items():
        if not safe(name) or (name != 'OC/config.plist' and staged.get(name) != digest):
            raise ValueError('Original EFI path changed: '+name)
    additions = {k:v for k,v in staged.items() if k not in base}
    kexts = {k for k in additions if k.startswith('OC/Kexts/'+rel['new']+'/')}
    if not kexts or additions != m['add_files'] or set(additions) != kexts | set(rel['extras']):
        raise ValueError('Unexpected EFI additions')
    for name, want in rel['extras'].items():
        if additions[name] != (base['OC/config.plist'] if want == 'baseline' else want):
            raise ValueError('Unexpected content for EFI addition: '+name)
    original = plistlib.loads((payload/'EFI'/rel['recovery']).read_bytes())
    staged_config = plistlib.loads((payload/'EFI/OC/config.plist').read_bytes())
    listed = sorted(e['path'] for e in rel['edits'])
    if sorted(d[1:] for d in diff_paths(original, staged_config)) != listed or staged_config != expected_config(original, rel):
        raise ValueError('Boot configuration differs from the reviewed edits')
    if 'config_edits' in m and m['config_edits'] != rel['edits']:
        raise ValueError('Manifest config edits differ from the reviewed edits')
    if 'recovery_entry' in rel:   # the recovery entry (Misc/Tools[0]) and the recovery files it restores are reviewed text
        entry = staged_config['Misc']['Tools'][0]
        if {k: entry.get(k) for k in ('Name', 'Comment')} != rel['recovery_entry'] or entry.get('Path') != 'OpenShell.efi':
            raise ValueError('Recovery entry differs from the reviewed text')
    for name, digest in rel.get('carried', {}).items():
        if staged.get(name) != digest:
            raise ValueError('Recovery file carried from the baseline differs: ' + name)
    bundle = payload/'EFI/OC/Kexts'/rel['new']
    if rel['kernel_sha'] is None or sha(bundle/'Contents/MacOS/Navi48Bringup') != rel['kernel_sha']:
        raise ValueError('Unexpected kernel binary')
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != 'com.navi48.bringup' or info['CFBundleVersion'] != version:
        raise ValueError('Unexpected kernel identity')
    for name, digest in (rel['metal'] or {}).items():
        if m['working_metal_files'].get(name) != digest: raise ValueError('Working Metal is not the reviewed bundle %s: %s' % (rel['metal_version'], name))
    subprocess.run(['codesign','--verify','--strict',str(bundle)],check=True)
    if rel.get('probe_reuse') and sha(payload/'system'/PROBE) != rel['probe_reuse']:
        raise ValueError('Probe is not the reviewed binary of this release')
    guard = (payload/'system'/GUARD).read_text()
    old_guard = payload/'evidence/original-guard.sh'
    if sha(old_guard) != m['system_before'][GUARD]['sha256'] or guard != make_guard(rel, old_guard.read_text(), sha(payload/'system'/PROBE), version):
        raise ValueError('Activation guard differs from the reviewed transformation')
    if rel['metal'] and any(digest not in guard for digest in rel['metal'].values()):
        raise ValueError('Activation guard does not pin the reviewed Metal components')
    if rel.get('binary_checks') == 'not-run':   # the record of the checks this release does not execute, and the reviewed self-test log
        if (m.get('deferred_checks') != {**DEFERRED_CHECKS, 'probe_self_test_log_sha256': rel['self_test_log_sha']}
                or sha(payload/'evidence/probe-self-test.log') != rel['self_test_log_sha']):
            raise ValueError('Deferred binary checks differ from the reviewed record')
    subprocess.run(['/bin/bash','-n',str(payload/'system'/GUARD)],check=True)
    if m['efi_volume_uuid'] not in EFI_UUIDS: raise ValueError('Unexpected EFI volume identity')
    if live:
        if boot_uuid() != m['prepared_boot_uuid']: raise ValueError('Payload prepared in another boot')
        if subprocess.check_output(['sw_vers','-buildVersion'],text=True).strip() != '25G83': raise ValueError('Different macOS build')
        if efi is None: efi = efi_mount(m['efi_volume_uuid'])/'EFI'
        volume = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(efi.parent)]))
        if volume.get('MountPoint') != str(efi.parent) or volume.get('VolumeUUID','').upper() != m['efi_volume_uuid'] or volume.get('FilesystemType') != 'msdos':
            raise ValueError('Wrong mounted EFI volume')
        if scoped_tree(efi) != scoped(base): raise ValueError('Live EFI differs from baseline')
        if tree(system_root/METAL) != m['working_metal_files']: raise ValueError('Working Metal changed')
        for name, expected in {**m['system_before'], **m['critical_system_files']}.items():
            if not safe(name) or metadata(system_root/name) != expected: raise ValueError('Live system dependency changed: '+name)
    return m


def same_except_uuid(a, b):
    """True when two 64-bit little-endian Mach-O files differ only in their LC_UUID load command: the link step's UUID is
    not reproducible from the same source, the code and data are."""
    def uuid_span(data):
        if len(data) < 32 or struct.unpack_from('<I', data, 0)[0] != 0xfeedfacf:
            raise ValueError('Not a 64-bit little-endian Mach-O file')
        off, spans = 32, []
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            cmd, size = struct.unpack_from('<II', data, off)
            if size < 8 or off + size > len(data):
                raise ValueError('Malformed Mach-O load commands')
            if cmd == 0x1b:   # LC_UUID: the 16 UUID bytes follow the 8-byte command header
                spans.append((off + 8, off + 24))
            off += size
        if len(spans) != 1:
            raise ValueError('Expected exactly one LC_UUID load command')
        return spans[0]
    if len(a) != len(b):
        return False
    (s, e), (s2, e2) = uuid_span(a), uuid_span(b)
    return (s, e) == (s2, e2) and a[:s] + a[e:] == b[:s] + b[e:]


def reviewed_base(build, rel):
    """Whether the candidate's base is proven. 0.0.666-0.0.668 rebuild the 665 base and record its seven Mach-O sections. 0.0.669 does not
    rebuild it: its base is the reviewed 0.0.668 candidate (kernel-contexts-v4), whose tree and binary the build recorded as base_verified."""
    if rel.get('base') is None:
        return len(build.get('baseline_sections', {})) == 7
    proof = build.get('base_verified') or {}
    if rel['base'] == 'reviewed-candidate-674':   # 0.0.675: the reviewed 0.0.674 candidate TREE (kernel-contexts-v10), its binary and inputs checked
        base = json.loads(BASE_674_MANIFEST.read_text())
        return (proof.get('manifest') == str(BASE_674_MANIFEST.relative_to(ROOT)) and proof.get('binary_sha256') == rel['base_kernel_sha']
                and proof.get('candidate_inputs_checked') == len(base.get('candidate_inputs', {}))
                and base.get('candidate_version') == '0.0.674' and base.get('candidate_binary_sha256') == rel['base_kernel_sha']
                and build.get('baseline_inputs') == base.get('candidate_inputs'))
    if rel['base'] == 'reviewed-candidate-673':   # 0.0.674: the reviewed 0.0.673 candidate TREE (kernel-contexts-v9), its binary and inputs checked
        base = json.loads(BASE_673_MANIFEST.read_text())
        return (proof.get('manifest') == str(BASE_673_MANIFEST.relative_to(ROOT)) and proof.get('binary_sha256') == rel['base_kernel_sha']
                and proof.get('candidate_inputs_checked') == len(base.get('candidate_inputs', {}))
                and base.get('candidate_version') == '0.0.673' and base.get('candidate_binary_sha256') == rel['base_kernel_sha']
                and build.get('baseline_inputs') == base.get('candidate_inputs'))
    if rel['base'] == 'reviewed-candidate-672':   # 0.0.673: the reviewed 0.0.672 candidate TREE (kernel-contexts-v8), its binary and inputs checked
        base = json.loads(BASE_672_MANIFEST.read_text())
        return (proof.get('manifest') == str(BASE_672_MANIFEST.relative_to(ROOT)) and proof.get('binary_sha256') == rel['base_kernel_sha']
                and proof.get('candidate_inputs_checked') == len(base.get('candidate_inputs', {}))
                and base.get('candidate_version') == '0.0.672' and base.get('candidate_binary_sha256') == rel['base_kernel_sha']
                and build.get('baseline_inputs') == base.get('candidate_inputs'))
    if rel['base'] == 'reviewed-candidate-671':   # 0.0.672: the reviewed 0.0.671 candidate TREE (kernel-contexts-v7), its binary and inputs checked
        base = json.loads(BASE_671_MANIFEST.read_text())
        return (proof.get('manifest') == str(BASE_671_MANIFEST.relative_to(ROOT)) and proof.get('binary_sha256') == rel['base_kernel_sha']
                and proof.get('candidate_inputs_checked') == len(base.get('candidate_inputs', {}))
                and base.get('candidate_version') == '0.0.671' and base.get('candidate_binary_sha256') == rel['base_kernel_sha']
                and build.get('baseline_inputs') == base.get('candidate_inputs'))
    if rel['base'] == 'reviewed-candidate-670':   # 0.0.671: the reviewed 0.0.670 candidate TREE (kernel-contexts-v6), its binary and inputs checked
        base = json.loads(BASE_670_MANIFEST.read_text())
        return (proof.get('manifest') == str(BASE_670_MANIFEST.relative_to(ROOT)) and proof.get('binary_sha256') == rel['base_kernel_sha']
                and proof.get('candidate_inputs_checked') == len(base.get('candidate_inputs', {}))
                and base.get('candidate_version') == '0.0.670' and base.get('candidate_binary_sha256') == rel['base_kernel_sha']
                and build.get('baseline_inputs') == base.get('candidate_inputs'))
    base = json.loads(BASE_668_MANIFEST.read_text())
    base_sha = rel.get('base_kernel_sha', rel['from_kernel_sha'])   # 0.0.670 is built on the same 0.0.668 candidate as 0.0.669
    return (rel['base'] == 'reviewed-candidate' and proof.get('manifest') == str(BASE_668_MANIFEST.relative_to(ROOT))
            and proof.get('binary_sha256') == base_sha and proof.get('candidate_inputs_checked') == len(base.get('candidate_inputs', {}))
            and base.get('candidate_version') == '0.0.668' and base.get('candidate_binary_sha256') == base_sha
            and build.get('baseline_inputs') == base.get('candidate_inputs'))


def prepare(candidate, output, baseline_payload=None, baseline_state='baseline'):
    buildroot = (ROOT/'research/builds').resolve()
    output = output.resolve(); candidate = candidate.resolve()
    if output == buildroot or not output.is_relative_to(buildroot) or output.exists() or not candidate.is_relative_to(buildroot):
        raise ValueError('Use a new output and existing candidate under research/builds')
    build = json.loads((candidate/'manifest.json').read_text())
    version, rel = release_of(build)
    deferred = rel.get('binary_checks') == 'not-run'
    if deferred and baseline_payload is None:
        raise ValueError(version + ' is prepared only from a recorded payload (--baseline-payload), never from the mounted EFI')
    if (build.get('status') != 'built-cpu-tested-not-installed-hardware-unverified' or build.get('profile') != {'hardware_slots':8,'logical_contexts':64}
            or rel['kernel_sha'] is None or build.get('candidate_binary_sha256') != rel['kernel_sha'] or len(build.get('cpu_tests',[])) != rel['tests']
            or not reviewed_base(build, rel) or not set(rel['strings']) <= set(build.get('required_strings', []))):
        raise ValueError('Candidate is not the verified kernel-%s build' % version)
    if build['prepared_boot_uuid'].lower() != boot_uuid(): raise ValueError('Build belongs to another boot')
    source = candidate/'candidate-source'
    for name, digest in build['candidate_inputs'].items():
        if not safe(name) or sha(source/name) != digest: raise ValueError('Candidate source changed')
    bundle = candidate/build['candidate_bundle']
    if not bundle.resolve().is_relative_to(candidate) or sha(bundle/'Contents/MacOS/Navi48Bringup') != rel['kernel_sha']:
        raise ValueError('Candidate bundle changed')
    live = baseline_payload is None
    if live:
        live_efi = efi_mount(UUID)/'EFI'
        sources = {name: live_efi/name for name in scoped_tree(live_efi)}
    else:
        sources = baseline_sources(baseline_payload, baseline_state)
    before = {name: sha(path) for name, path in sources.items()}
    config_bytes = sources['OC/config.plist'].read_bytes()
    config = plistlib.loads(config_bytes); entry = baseline_config(config, rel['from'])
    if (before.get('OC/Kexts/'+rel['from']+'/'+entry['ExecutablePath']) != rel['from_kernel_sha'] or before['OC/config.plist'] != build['active_baseline']['config_sha256']
            or build['active_baseline']['kernel_sha256'] != rel['from_kernel_sha'] or build['active_baseline']['config_sha256'] != rel['from_config_sha']):
        raise ValueError('Working EFI is not the compiled baseline')
    if any(k.startswith('OC/Kexts/'+rel['new']+'/') or k in rel['extras'] for k in before):
        raise ValueError('Candidate/recovery EFI paths already exist')
    if any(x.get('BundlePath') == rel['new'] for x in config['Kernel']['Add']): raise ValueError('Candidate already listed in config')
    original_guard = (Path('/')/GUARD).read_text()
    rel = release_for_guard(rel, original_guard)   # 0.0.669: the Metal bundle the LIVE guard expects
    baseline_system = {name:metadata(Path('/')/name) for name in (GUARD,PROBE,*rel.get('system_files',{}))}
    critical = {name:metadata(Path('/')/name) for name in CRITICAL}
    if any(v is None for v in critical.values()) or baseline_system[GUARD] is None or any(baseline_system[name] is None for name in rel.get('system_files',{})): raise ValueError('Missing boot dependency')
    metal = tree(Path('/')/METAL)
    if rel['guard'] in ('live-669', 'live-670', 'live-671', 'live-672', 'live-673', 'live-674', 'live-675') and any(metal.get(name) != digest for name, digest in rel['metal'].items()):
        raise ValueError('The live Metal bundle is not the one the live guard expects (bundle %s)' % rel['metal_version'])
    output.mkdir(parents=True)
    (output/'evidence').mkdir()
    shutil.copyfile(candidate/'manifest.json',output/'evidence/build-manifest.json')
    (output/'evidence/original-guard.sh').write_text(original_guard)
    efi_out = output/'EFI'
    for name, path in sources.items():
        (efi_out/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, efi_out/name)
    if tree(efi_out) != before: raise ValueError('Staged baseline differs from the recorded baseline')
    shutil.copytree(bundle, efi_out/'OC/Kexts'/rel['new'])
    for name, want in rel['extras'].items():
        data = config_bytes if want == 'baseline' else EXTRA_SOURCES[name].read_bytes()
        if want != 'baseline' and hashlib.sha256(data).hexdigest() != want: raise ValueError('Not the reviewed file: '+name)
        (efi_out/name).parent.mkdir(parents=True, exist_ok=True)
        (efi_out/name).write_bytes(data)
    (efi_out/'OC/config.plist').write_bytes(plistlib.dumps(expected_config(config, rel), sort_keys=False))
    verifier = ROOT/'research/ext/navi44-baremetal-stage1-candidate-20261027/tools/ocvalidate'
    if not deferred:   # the validator is a research-tree executable: a deferred release leaves it to the installer (DEFERRED_CHECKS)
        subprocess.run([str(verifier), str(efi_out/'OC/config.plist')], check=True)
    target = output/'system'/PROBE; target.parent.mkdir(parents=True)
    probe_source = ROOT/'tools/baremetal/navi44-gpu-diagnostics/context-isolation-probe.cpp'
    command = ['clang++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(source/'src'),str(probe_source),'-framework','IOKit','-framework','CoreFoundation','-o',str(target)]
    subprocess.run(command,check=True);target.chmod(0o755)
    probe_reuse_record = None
    if rel.get('probe_reuse'):
        # The reviewed probe is reused when a fresh build of this source differs from it only in its LC_UUID; then the probe file,
        # and the guard's probe digest, stay exactly as reviewed. Any other difference refuses the release.
        reviewed_source = (baseline_payload/'system'/PROBE) if baseline_payload is not None else (Path('/')/PROBE)
        reviewed = reviewed_source.read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != rel['probe_reuse'] or not same_except_uuid(target.read_bytes(), reviewed):
            raise ValueError('The reviewed probe is not a fresh build of this source (apart from its UUID)')
        target.write_bytes(reviewed); target.chmod(0o755)
        probe_reuse_record = {'reviewed_sha256': rel['probe_reuse'], 'reviewed_from': str(reviewed_source),
                              'checked': 'identical to a fresh build of the probe source except LC_UUID'}
    if deferred:   # not executed: the probe is a research-tree executable; its evidence is the recorded log of the identical reused binary
        recorded_log = baseline_payload/'evidence/probe-self-test.log'
        if sha(recorded_log) != rel['self_test_log_sha'] or sha(target) != rel['probe_reuse']:
            raise ValueError('The recorded probe self-test is not the log of the reviewed probe')
        shutil.copyfile(recorded_log, output/'evidence/probe-self-test.log')
    else:
        with (output/'evidence/probe-self-test.log').open('w') as log:
            subprocess.run([str(target),'--self-test'],stdout=log,stderr=subprocess.STDOUT,check=True)
    for name, digest in rel.get('system_files',{}).items():   # the reviewed system files of the release (navi48test): copied, never built
        source_file = SYSTEM_SOURCES[name]
        if source_file.is_symlink() or sha(source_file) != digest: raise ValueError('Not the reviewed file: '+name)
        target_file = output/'system'/name
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(source_file.read_bytes()); target_file.chmod(0o755)
    guard = output/'system'/GUARD
    if rel['metal'] and ('"$bundle_version" == %s ' % rel['metal_version']) not in original_guard:
        raise ValueError('Live guard does not expect Metal bundle %s' % rel['metal_version'])
    guard.write_text(make_guard(rel, original_guard, sha(target), version)); guard.chmod(0o755)
    staged = tree(efi_out)
    files = tree(output)
    m = {'schema':1,'status':'prepared-not-installed','profile':PROFILE,'candidate_version':version,
         'prepared_boot_uuid':boot_uuid(),'efi_volume_uuid':UUID,
         'baseline_efi_files':before,'candidate_efi_files':staged,
         'baseline_config_sha256':before['OC/config.plist'],
         'candidate_config_sha256':staged['OC/config.plist'],
         'config_edits':rel['edits'],'recovery_copy':rel['recovery'],
         'baseline_source':'live-efi' if live else 'recorded-payload:%s%s' % (baseline_payload.name, '' if baseline_state == 'baseline' else ':' + baseline_state),
         'live_efi_verified': live,
         'add_files':{k:v for k,v in staged.items() if k not in before},
         'system_before':baseline_system,'critical_system_files':critical,
         'working_metal_files':metal,'files':files,
         'file_modes':{k:(output/k).stat().st_mode & 0o777 for k in files},
         'candidate_kernel_sha256':rel['kernel_sha'],'probe_build_command':command,'probe_reuse':probe_reuse_record,
         'probe_source_sha256':sha(probe_source),'preparer_sha256':sha(Path(__file__)),
         'hardware_validation':'not performed','installation':'not performed'}
    if deferred: m['deferred_checks'] = {**DEFERRED_CHECKS, 'probe_self_test_log_sha256': rel['self_test_log_sha']}
    (output/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    verify(output, live=live)
    return m


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prep = commands.add_parser('prepare');prep.add_argument('--candidate',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    prep.add_argument('--baseline-payload',type=Path,help='offline: take the baseline EFI from this verified payload instead of the mounted EFI')
    prep.add_argument('--baseline-state',choices=('baseline','candidate'),default='baseline',
                      help="which EFI state of --baseline-payload is the live one: its baseline (default) or its candidate (0.0.668 on payload v3)")
    check = commands.add_parser('check');check.add_argument('payload',type=Path);check.add_argument('--live',action='store_true')
    args = parser.parse_args()
    m = prepare(args.candidate,args.output,args.baseline_payload,args.baseline_state) if args.command == 'prepare' else verify(args.payload,args.live)
    print(json.dumps({'profile':m['profile'],'candidate_version':m.get('candidate_version','0.0.666'),'files_verified':len(m['files']),
                      'live_efi_verified':m.get('live_efi_verified',True),'installed':False,'hardware_validation':m['hardware_validation']},indent=2))


if __name__ == '__main__': main()
