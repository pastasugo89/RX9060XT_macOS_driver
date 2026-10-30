#!/usr/bin/env python3
"""Verify capacity changes rebuild the real kernel object in a reused directory.

Requires the local macOS kernel SDK and firmware used by the project. Builds
only a native_s1c.o in a temporary directory; never installs or loads a kext.
"""
from pathlib import Path
import hashlib
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
source = root / 'cobalt64/src/navi48-bringup'
sdk = root / 'research/builds/macos-20261027/sdk/MacKernelSDK'

with tempfile.TemporaryDirectory(prefix='navi44-build-profile-') as directory:
    build = Path(directory)
    obj = build / 'src/amd/native_s1c.o'
    command = ['make', '-C', str(source), 'BUILD='+str(build),
               'NATIVE_SESSIONS=8', 'MKSDK='+str(sdk), str(obj)]

    def compile_profile(count):
        result = subprocess.run(command + ['LOGICAL_CONTEXTS='+str(count)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return hashlib.sha256(obj.read_bytes()).hexdigest(), obj.stat().st_mtime_ns

    original, timestamp = compile_profile(64)
    same, timestamp2 = compile_profile(64)
    assert (same, timestamp2) == (original, timestamp), 'unchanged profile recompiled'
    fixed, _ = compile_profile(8)
    assert fixed != original, 'capacity switch reused the old object'
    restored, _ = compile_profile(64)
    assert restored == original, 'returning to profile 64 is not reproducible'
    print('PASS: the real kernel object rebuilds for 64 -> 8 -> 64 contexts, reproduces its original hash, and preserves mtime for an unchanged profile.')
