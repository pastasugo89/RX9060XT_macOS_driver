# Baseline 0.0.665 (Navi44): reproducible source and build record

This directory answers issue #1 ("Reproducing the documented 0.0.665 baseline from public sources").
It reconstructs the preserved 0.0.665 source trees from public commits of this repository, gives a
script that checks them, records the toolchain and firmware inputs, and states what was and was not
reproduced byte for byte.

Nothing here is a binary, a firmware blob, an Apple file, an EFI configuration or a personal path.

## Results at a glance

- **Source:** three preserved trees are reconstructed exactly from public commits and patches.
  `verify.sh` matches all 236 + 236 + 235 files against the sha256 manifests.
- **Loaded code:** both preserved kext binaries are reproduced section for section. For `unified`
  (097b9b9f) all 64 object files have identical code and data. For the eight-session kext (607fd051)
  all seven loaded sections match.
- **Whole file:** the eight-session kext 607fd051 is reproduced byte for byte, with the conditions in
  "Byte-level identity" below. The unified kext 097b9b9f cannot be reproduced whole from the repository
  (see "Byte-level identity").
- **0.0.666 to 0.0.670:** every recorded overlay and refresh input is now in a public commit. A few
  inputs are not in the repository: see "Production chain 0.0.666 to 0.0.670".

## Contents

| path | content |
|---|---|
| `patches/0001-unified-bringup-model-on-35d8193.patch` | unified bring-up tree on top of commit 35d8193 |
| `patches/0002-gpu-eight-repro-v6-on-0001.patch` | eight-session 0.0.665 tree on top of the unified tree |
| `patches/0003-navi44-psp-safety-candidate-on-29a371b.patch` | experimental PSP-safety candidate on top of commit 29a371b |
| `manifests/*.sha256` | sha256 of every file in the reconstructed scope of each tree |
| `manifests/binary-sections.txt` | size and sha256 of each loaded Mach-O section of the two preserved kext binaries |
| `verify.sh` | reconstructs and checks the trees; with `--build` also compiles and compares the sections |
| `toolchain.md` | compiler, linker, SDK, MacKernelSDK revision, make lines and flags |
| `firmware.md` | the ten AMD blobs the kext embeds, with sha256 and the upstream reference |

## Lineage

Each preserved tree was compared file by file with every public commit that touches
`cobalt64/src/navi48-bringup`. Closest commits and the chain that reproduces each tree exactly:

| preserved tree (research/builds/macos-20261028/) | closest public commit | differing files | exact reconstruction |
|---|---|---|---|
| `unified/bringup-model` (kext 097b9b9f) | 35d819336f907f7eae1a3bd5e93dcc6b82fc0703 (2026-10-28) | 5 changed, 1 preserved-only, 2 extra | 35d8193 + patch 0001 |
| `gpu-eight-repro-v6` (kext 607fd051; BASE of the production chain) | de744f02fdd72b16855e79a522d16278b8f54d8e (2026-10-29), 8 files | 8 changed, 1 preserved-only, 2 extra | 35d8193 + patch 0001 + patch 0002 |
| `unified/bringup-model/navi44-psp-safety-candidate` (experimental) | 29a371b8eb479926cd0664e252f40eb3e2c19b67 (2026-10-25) | 4 changed, 2 extra | 29a371b + patch 0003 |

Notes on the lineage:

- `gpu-eight-repro-v6/baseline-source/` has byte-identical `src/`, `shaders/`, `tools/`, `Makefile` and
  `Info.plist` to `unified/bringup-model`, so it is not a fourth tree.
- `src/amd/n4x_console_guard.h` (the console guard that 097b9b9f's source carries) is in no commit of
  the repository, including the pre-rewrite history. It exists only in the preserved tree; patch 0001
  adds it. This is the console-protection difference that `DRIVER_PRODUZIONE.md` mentions.
- Patch 0001 also changes `Navi48Bringup.cpp`, `amd/n4x_safety.cpp`, `amd/n4x_safety.h`,
  `amd/n4x_safety_pure.h` and `amd/smu_v14_0.cpp` (the PSP/SMU and safety sources that
  `DRIVER_PRODUZIONE.md` describes). It also removes `tools/build-shader.sh` and
  `tools/build-vadd-ir.sh`, which the preserved tree does not have.
- Patch 0002 is the eight-session overlay: the `NATIVE_SESSIONS` Makefile of commit f9971e0,
  `native_s1c.cpp`, `native_s1c.h`, `native_g2_pure.h`, `Navi48MetalNub.cpp` (the version markers 664 to
  665) and `Info.plist` (0.0.664 to 0.0.665).
- The base commits are ancestors of `main` and of the current HEAD (checked for 35d8193, 29a371b, de744f0).

## Reconstruct and verify

```
baselines/0.0.665/verify.sh                          # source check: exits 0 when all three trees match
baselines/0.0.665/verify.sh --build <MKSDK> <FW>     # also compiles the two kext trees and compares sections
```

`<FW>` is a directory with the ten `.bin` files of `firmware.md`. `verify.sh` creates its work
directory under `$TMPDIR` and refuses a `$TMPDIR` that is inside a git repository. That matters:
`git apply` run inside a repository resolves patch paths from the repository root and silently skips
paths outside the current directory, so the patches must be applied outside any repository. The
manual equivalent is:

```
git archive 35d819336f907f7eae1a3bd5e93dcc6b82fc0703 cobalt64/src/navi48-bringup | tar -x -C <tmp>
cd <tmp>/cobalt64/src/navi48-bringup && git apply <repo>/baselines/0.0.665/patches/0001-unified-bringup-model-on-35d8193.patch
```

Generated outputs are excluded from the scope: `src/fw/fw_*.c` (produced by the Makefile from
`firmware/*.bin` and `shaders/*.bin`, plus zero-length stubs). The tracked `src/fw/fw_table.h` is kept.
The scope is `src/`, `shaders/`, `tools/`, `Makefile` and `Info.plist`. `tests/`, `hosttest/`, `LICENSE`
and `NOTICE` are not part of the build and are not reconstructed.

## Build the eight-session kext (607fd051)

1. Reconstruct the tree (above). Get the ten navi44 blobs from linux-firmware with
   `ASIC=navi44 cobalt64/tools/fetch-firmware.sh <linux-firmware checkout>`. The script fills
   `cobalt64/src/navi48-bringup/firmware/` in the repository (gitignored). Copy the `.bin` files from
   there into the reconstructed tree's `firmware/` directory (see `firmware.md`).
2. Install the MacKernelSDK from `acidanthera/MacKernelSDK` at 3f750085 and make the x86_64 slice of
   `libkmodc++.a` (see `toolchain.md`).
3. In the tree:

   ```
   make -j4 NATIVE_SESSIONS=8 BUILD=build-eight MKSDK=<MKSDK> XLAT12_DIR=<repo>/cobalt64/src/xlat12 \
        SHADERCACHE_DIR=<repo>/cobalt64/src/shadercache DCN41_DIR=<repo>/cobalt64/src/dcn41
   ```

4. Check the result with `verify.sh --build` or by comparing the sections in `manifests/binary-sections.txt`.

The production chain builds the same base again with `LOGICAL_CONTEXTS=8`
(`tools/baremetal/navi44-desktop/build-production-contexts.py`, HEAD line 391). That is the profile
that `NATIVE_SESSIONS=8` already implies.

## Byte-level identity

Two facts govern what can match. Each Mach-O kext records, in its symbol table, the absolute path and
the modification time of each object file it was linked from (N_OSO entries), and the directories of its
source files (N_SO entries). The LC_UUID and the ad-hoc code signature are derived from the file contents.
So a rebuild at another absolute path, or from object files with other timestamps, differs in those
places (the string table can also change size), but not in the loaded code.

Local test on the research host (rebuilds in `research/builds/macos-20261105/`, not published):

- **607fd051 (eight-session):** the rebuild differs only in the build-directory digits of the symbol
  table, the LC_UUID and the signature. Rebuilt at a directory whose path has the same length
  (`macos-20261105` for `macos-20261028`) with the object files' recorded timestamps restored, then
  with the 121 digit strings rewritten back, the original LC_UUID restored and the kext re-signed
  ad hoc, the result is **byte-identical**: sha256 607fd0513cac568996d788f4037ba4824ed005cc4ff6eb32d6220dbcd196fd24.
  A rebuild at an arbitrary path gives the same sections and differs in the string table, the LC_UUID
  and the signature only.
- **097b9b9f (unified console guard):** all 64 object files have code and data identical to the
  reconstruction, and the seven loaded sections match. The whole file does not: its symbol table
  records three source directories, written when the objects were compiled (`.../unified/bringup-model/src/`,
  `.../desktop-prep/navi44-console-guard-candidate/src/` and `.../macos-20261028/src/cobalt64/src/dcn41/`).
  The last one no longer exists in the research tree. The file is 4651184 bytes; a clean rebuild gives
  4651120 bytes. The whole-file hash cannot be reproduced from the repository.

The `--build` mode of `verify.sh` checks loaded sections only, which is what matters for the code.

## Production chain 0.0.666 to 0.0.670

The chain (`build-production-contexts.py`, `production-kernel-payload.py`) builds candidates from the 665
base plus overlays. Source commit of each candidate, and what its inputs are now:

| candidate | source commit (from its manifest) | public equivalent | inputs |
|---|---|---|---|
| 0.0.666 | d70a33129e61862b9a3b279328e620b762d0e0e5 (pre-rewrite) | the same navi48-bringup tree as public 22ca3c2 | the overlay files equal that commit; the one difference is the 0.0.666 version marker in `native_s1c.h` (664 to 666), which the build sets; base = the eight-session tree |
| 0.0.667 | db8b20288eae938c6a4fca0e6304d599f1a98614 | public 7342665 (identical tree; the kill-switch commit) | committed |
| 0.0.668 | b0a8a950235fb3c0d80ca32a0a65756ec98cb655 | public, same hash | 10 of 12 overlay files equal the commit; `native_s1c.cpp` (9139dac3) and `native_g4_pure.h` (f13ee081) were uncommitted at the time and are in commits cf79765 and later |
| 0.0.669 | a5b32c3b109cea4df26c415d736f2c12bcba4b5a | public, same hash | refresh overlay (5 files) is in 0b364ae; `navi48_refresh_pure.h` 4dc3fb7e is in 0b364ae |
| 0.0.670 | 0b364ae2cfdfc3263da56352346117f74511e0bc | public, same hash | refresh overlay is in 0b364ae, except `navi48_refresh_pure.h` 81534f43, which is in aa34a28 |

Also checked:

- The refresh hunk file `tools/baremetal/navi44-desktop/refresh-60/navi48bringup-refresh60.patch` is tracked
  and has the recorded sha256 (950c63fe…).
- The kill switch of db8b202 (block sha256 6942f5eb…) is in the tracked tree.
- The probe source `tools/baremetal/navi44-gpu-diagnostics/context-isolation-probe.cpp` is tracked and
  has the sha256 that the payload manifests record (7efbb5a7…).
- The six CPU suites of the chain have the recorded sha256 at HEAD. The two 0.0.669 refresh suites
  (5a5190b5…, d7f0b5c9…) are in 0b364ae; HEAD carries the 0.0.670 revisions.
- `startup.nsh` (tracked) matches the payload's sha256.

Not in the repository (remaining inputs):

1. **The 0.0.668 candidate tree** (`research/builds/macos-20261031/production/kernel-contexts-v4/candidate-source`),
   the base of 0.0.669 and 0.0.670. It is local only. It should be reconstructible from the 665 base,
   the public overlay and the kill switch, but this was not regenerated end to end here.
2. **`navi48test`** (system file of the 0.0.669 and later payloads, sha256 83e7f3e3…). Its refresh-era
   source is local only. The tracked `cobalt64/tools/pc/navi48test.c` is a different file (79 lines
   differ from the local refresh-era source).
3. **OpenCore validator** `ocvalidate` (`research/ext/...`, third-party, not tracked). It validates the EFI
   configuration and is not part of the kext build.
4. **Metal bundle digests** that the payload guard expects (userspace `Navi48Metal.bundle`, not the kext).
5. **0.0.671** (the GTT fix) is in HEAD now. It was not analysed here.

## Open items

- The make line of the unified kext 097b9b9f is not recorded (its flags are; see `toolchain.md`).
- The upstream linux-firmware commit is not pinned. The ten sha256 values match the table in
  `cobalt64/tools/fetch-firmware.sh`, which names linux-firmware 20260916.
- MacKernelSDK: the RDNA4FB submodule pin (05094e5e) has a different `Headers/` tree. Its build output
  has not been tested.
- `cobalt64/BUILDING.md` lists the Navi48 firmware set as the one the kext embeds; the default
  `ASIC=navi44` embeds the set in `firmware.md`.

## Public history notes

- The `main` branch was rewritten to change author emails (reflog entry "rewrite author emails"). Some
  hashes in code comments and manifests are pre-rewrite. Their trees equal the public commits: db8b202 =
  7342665 and c440e35 = 0f26a43 (identical `navi48-bringup` trees), and d70a331 = 22ca3c2 (identical tree).
  The commit hashes cited in this directory are the public ones.
- HEAD moved to 644c07d during this work. That commit adds the GTT buffer fix and the 0.0.671 build
  scripts. Every commit cited here is an ancestor of it, and the 0.0.671 work is not analysed here.
