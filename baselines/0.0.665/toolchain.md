# Toolchain of the 0.0.665 baseline

Host and tools below were recorded on the research host on 2026-11-05 and are the same ones the
preserved builds used (their build logs show the same compiler, deployment target and SDK path).
Paths are written as `<repo>` (the repository root) and `<MKSDK>` (the MacKernelSDK directory).

## Host and tools

| item | value |
|---|---|
| host | x86_64, macOS 26.6.2 (build 25G83), Darwin 25.6.0 |
| C/C++ compiler | Apple clang 21.0.0 (clang-2100.1.1.101), `/Library/Developer/CommandLineTools/usr/bin/clang`, target `x86_64-apple-darwin25.6.0` |
| linker | `ld` PROJECT:ld-1267 (Apple, build of 8 June 2026), invoked by clang |
| SDK | `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`, a symlink to `MacOSX26.5.sdk` (SDK version 26.5). Found by `xcrun --sdk macosx --show-sdk-path` |
| deployment target | macOS 11.0 (`DEPLOY := 11.0`, `-target x86_64-apple-macos11.0`) |
| make | GNU Make 3.81 (Apple) |
| python3 | 3.9.6 (Command Line Tools), used by `tools/embed-firmware.py` through the Makefile |
| signing | `codesign --force --sign -` (ad hoc), as in the Makefile |

Xcode.app is not installed (`xcode-select` points to the Command Line Tools; `xcodebuild` refuses to
run). The build needs only the Command Line Tools.

## MacKernelSDK

The Makefile's default is `MKSDK := ../RDNA4FB/MacKernelSDK` and always has to be overridden. The
preserved SDK is `research/builds/macos-20261027/sdk/MacKernelSDK` (not in the repository).

- Upstream: `https://github.com/acidanthera/MacKernelSDK`.
- Revision that matches the preserved tree: **3f750085caa17ec3a7880f11c11bf4f48cd6a164**
  (2026-09-24, "Fix IOPCIHostBridge instance layout for macOS Tahoe").
  - `Headers/` tree `018f0289fda8f85e8d917c3ce2b8b136c6fb695f`: all 1214 header files are identical
    (blob id and mode) to the preserved `Headers/`.
  - `Library/` tree `38c0cec08ed59836776912f479a1ac57dbe909b0`.
- The RDNA4FB clone pins MacKernelSDK at `05094e5e88cec7caedbfb35e8449ed0db94bf95b` (submodule
  gitlink in `https://github.com/somestupidgirl/RDNA4FB`). That revision has the same `Library/`
  tree but a different `Headers/` tree (`c5667759…`). It has not been tested whether it builds the
  same kext. Use 3f750085 to match the preserved build.
- `Library/x86_64/libkmodc++.a` is not in the upstream tree. It is the x86_64 slice of the upstream
  universal archive:

  ```
  lipo -thin x86_64 <MKSDK>/Library/universal/libkmodc++.a -output <MKSDK>/Library/x86_64/libkmodc++.a
  ```

  The result matches the preserved file (sha256 fb488b74fc47fb17b8c289772a62bbf92cdae58f827cb7c71de9b08d1f80f915).
  `Library/x86_64/libkmod.a` is the upstream file (sha256 7a751671bbe96c9c7b5416078df600b768c00c0dc5178d8acd8f52539c7ccd4e).

Checking a local copy against the upstream tree (no download needed when the clone exists):

```
git -C <clone-of-MacKernelSDK> rev-parse 3f750085caa17ec3a7880f11c11bf4f48cd6a164:Headers   # 018f0289…
```

## Make commands

Run in the reconstructed tree (`cobalt64/src/navi48-bringup` from the base commit with the patches
applied) after the firmware has been copied into its `firmware/` directory. `XLAT12_DIR`,
`SHADERCACHE_DIR` and `DCN41_DIR` point at the repository's own `cobalt64/src/` directories, which
have not changed since 2026-10-12 (`git log`).

- **0.0.665 eight-session kext (`607fd051…`)**, from `gpu-eight-repro-v6/manifest.json` `build_command`
  (paths sanitized):

  ```
  make -j4 NATIVE_SESSIONS=8 BUILD=build-eight MKSDK=<MKSDK> XLAT12_DIR=<repo>/cobalt64/src/xlat12 \
       SHADERCACHE_DIR=<repo>/cobalt64/src/shadercache DCN41_DIR=<repo>/cobalt64/src/dcn41
  ```

  `LOGICAL_CONTEXTS` is not given, so it takes the value of `NATIVE_SESSIONS` (8).

- **0.0.665 unified console-guard kext (`097b9b9f…`)**. Its make line is not recorded. The flags below
  are those in its build log (`unified/bringup-model/build-repro-baseline.log`), which has no
  `-DN48_MAX_NATIVE_SESSIONS`, consistent with the Makefile of commit 35d8193:

  ```
  make -j4 BUILD=build-console-guard MKSDK=<MKSDK> XLAT12_DIR=… SHADERCACHE_DIR=… DCN41_DIR=…
  ```

- **Production chain** (`tools/baremetal/navi44-desktop/build-production-contexts.py`, HEAD):
  line 370 runs `make -j4 NATIVE_SESSIONS=8 LOGICAL_CONTEXTS=<profile> BUILD=<dir> MKSDK=… XLAT12_DIR=…
  SHADERCACHE_DIR=… DCN41_DIR=…`. The 665 baseline is rebuilt with profile 8 (line 391); the
  0.0.666–0.0.670 candidates with profile 64 (line 421).
- **Probe** that the payload builds and pins (`production-kernel-payload.py`, HEAD, line 732):

  ```
  clang++ -std=c++17 -O2 -Wall -Wextra -Werror -I <candidate>/src \
      tools/baremetal/navi44-gpu-diagnostics/context-isolation-probe.cpp -framework IOKit -framework CoreFoundation -o <out>
  ```

- **Navi44 build of 2026-10-27** (`research/builds/macos-20261027/BUILD_REPORT.md`, line 48):
  `make -C <tree> all ASIC=navi44 APPLE_ROUTE=0 MKSDK=<MKSDK>`. These are the Makefile defaults.

## Effective compile and link flags

From the build logs (the same for both kext trees; `-DN48_MAX_NATIVE_SESSIONS=8` only in the eight-session
build; `-DN48_MAX_LOGICAL_CONTEXTS` is added by the current Makefile):

```
clang++ -arch x86_64 -target x86_64-apple-macos11.0 -isysroot <SDK> -I<MKSDK>/Headers -Isrc -Isrc/amd \
  -I<xlat12> -I<shadercache> -I<dcn41> -mmacosx-version-min=11.0 -DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE \
  -DAPPLE -DNeXT -DN4X_APPLE_ROUTE=0 -D_FORTIFY_SOURCE=0 -nostdinc -fno-builtin -fno-common \
  -fno-stack-protector -mkernel -fapple-kext -Wall -Os -g -std=c++17 -fno-exceptions -fno-rtti \
  -fcheck-new -fno-c++-static-destructors -MMD -MP -c <src> -o <obj>
clang++ -arch x86_64 -target x86_64-apple-macos11.0 -isysroot <SDK> -nostdlib -Xlinker -kext \
  -L<MKSDK>/Library/x86_64 -lkmodc++ -lkmod -Wl,-no_deduplicate <objects> -o <kext binary>
```

The C objects use `clang` with the same flags minus the C++ ones. The Makefile then sets the
`Info.plist` with the PCI id (`0x75901002`), runs an undefined-symbol check on `nm -u`, and signs.

## Known limits

- The make line for the 097b9b9f kext is inferred from its log flags and not recorded.
- The preserved build log of 0.0.665 does not record the `python3` binary; `embed-firmware.py` output
  is byte-identical in the rebuilt sections, so this does not affect the loaded code.
- The preserved MacKernelSDK is equal to upstream 3f750085 in Headers and in the two libraries
  (checked blob by blob). Whether it is the copy used on 2026-10-28 is shown indirectly by the
  identical loaded sections, not by a timestamp.
