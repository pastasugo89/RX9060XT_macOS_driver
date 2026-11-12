# RX 9060 XT macOS driver (Navi 44)

An experimental GPU driver stack that brings the AMD Radeon RX 9060 XT (Navi 44, RDNA 4, gfx1200, PCI ID `1002:7590`)
to Metal-accelerated desktop use on macOS Tahoe 26.6.2 (build 25G83), on an x86_64 PC booted with OpenCore.

The driver parts are written for this project. They reuse open work from other projects, credited below. The project
started as the Navi 44 port of [Cobalt64](cobalt64/README.md), which targets the RX 9070 XT (Navi 48). The code still
carries Cobalt64's structure and some Navi 48 names.

> [!WARNING]
> **Read the safety section before you build or install anything.** The kernel extension writes GPU registers directly.
> A wrong build, a different GPU or a bad power setting can freeze or restart the machine. Use a machine you can recover.

## Contents

- [Safety](#safety)
- [Status](#status)
- [Supported hardware](#supported-hardware)
- [How it is structured](#how-it-is-structured)
- [Repository layout](#repository-layout)
- [Building](#building)
- [Installing and running](#installing-and-running)
- [Licences](#licences)
- [Credits](#credits)
- [Documentation](#documentation)
- [Contributing](#contributing)

## Safety

- **Experimental kernel code.** `Navi48Bringup.kext` programs the PCIe BARs, PSP, SMU, GFX, SDMA, MES and the display
  engine directly. A mistake can freeze, hang or restart the machine, and can leave the display in a bad state.
- **Do not change GPU clocks or power limits by hand.** On the test machine, a manual power change pushed the card to
  about 170 W and froze the desktop until a restart.
- **OpenCore is required.** Keep a second OpenCore entry that does not load the driver, and back up your EFI partition
  before each test. The project's own recovery notes are in
  [`tools/baremetal/navi44-desktop/kernel-efi/RECOVERY.md`](tools/baremetal/navi44-desktop/kernel-efi/RECOVERY.md) (in Italian).
- **One macOS build.** Everything is built and tested on macOS Tahoe 26.6.2 (build 25G83). Other builds will probably
  fail or behave differently.
- **One test machine.** Results come from a single Ryzen 7 7700 system with one RX 9060 XT. They do not generalise.
- **No warranty.** Every component is provided as is, under its own licence (see [Licences](#licences)). Data loss and
  hardware damage are your responsibility.
- **Unofficial.** This project is not made, endorsed or supported by Apple or AMD.

## Status

Status as of kernel 0.0.675 (commit `83678ea`, 12 November 2026), installed on the test machine. The newest Italian entries
are in [`STATO.md`](STATO.md). The English summary and roadmap are in [`docs/STATUS.md`](docs/STATUS.md).

| Area | Status | Notes |
|---|---|---|
| GPU bring-up (PSP, SMU, GFX, SDMA, MES, display) | Working | Runs on the test machine. |
| Accelerated desktop (WindowServer composited by Metal on the GPU) | Working | Most system apps run accelerated. |
| Metal translation (`Navi48Metal.bundle`) | Working, partial | Icon rendering fixed in bundle 38. Some API paths are still missing. |
| Browsers (Brave) | Partial | GPU acceleration is on. WebGL and WebGPU were reported working. Smooth frame pacing is not yet verified. |
| Display at 2560x1440, 120 Hz | Working | Test monitor: 1440p 120 Hz LG over DisplayPort. |
| Display at 60 Hz | Experimental | Opt-in. The black band at the top was fixed in kernel 0.0.673. |
| GPU contexts | Working | 64 logical contexts on 8 dynamic VMIDs (kernel 0.0.667 and later). |
| Compute (internal test shaders) | Partial | Compute test shaders pass. There is no public compute API. |
| GFX clock gating | Working | Active since kernel 0.0.675, as in Linux's `gfx_v12_0`. Boot-argument `navi48-cg=0` turns it off. |
| GPU clock range and power management | Not working | The core clock (GFXCLK) is still clamped to 500 MHz. The full PMFW range is not used yet. |
| Thermal protection | Working, new | Since 0.0.675: warning at 90 °C. At 100 °C the watchdog clamps GFXCLK low through the SMU, and releases after 10 s below 85 °C. GPU work is no longer refused. |
| Sensors and fan control exposed to macOS | Not working | Planned next. |
| Hardware video decoding and encoding (VCN) | Not working | No hardware video path. |
| Public Vulkan driver | Not working | RADV is used inside the Metal path only. It is not offered as a Vulkan driver. |
| OpenCL, ROCm/HIP | Not working | |
| Multiple monitors | Not working | Experimental code sits behind boot-arguments and is not validated. |
| HDR | Not working | |
| Recovery from GPU faults | Not robust | A GPU fault can leave the desktop frozen until a restart (`DEVICE_LOST`). |
| Sleep and wake | Not verified | |
| Other GPUs | Not supported | See [Supported hardware](#supported-hardware). |

Rough estimate by the maintainer, not a measurement: about 55 to 60 percent of the way to a daily-use driver, and about
35 to 40 percent of a complete driver.

## Supported hardware

- **Supported GPU:** AMD Radeon RX 9060 XT, Navi 44, PCI ID `1002:7590` (16 GB). Nothing else is supported.
- **Tested on:** one machine, with an AMD Ryzen 7 7700, an RX 9060 XT 16 GB and one LG 1440p 120 Hz monitor on DisplayPort.
- **Navi 48 (RX 9070 XT):** the `ASIC=navi48` build option comes from the Cobalt64 base. It is not tested in this repository.
- **Other Navi 44 and Navi 48 cards:** may work with changes, but nobody has tested them here. If you have one, please
  send a [hardware report](.github/ISSUE_TEMPLATE/hardware_report.yml).

## How it is structured

```
Metal apps
    |
WindowServer (Apple) --> Navi48Metal.bundle  (Metal device; MIT)
                              |  AIR -> SPIR-V via libn48xlate (LGPL-3.0-or-later, loaded at run time)
                              v
                         RADV (Mesa Vulkan, Darwin backend; Mesa patches, MIT)
                              |  user client "N48N"
                              v
Navi48Accel.kext  (auxiliary IOAccelerator, AuxKC)
Navi48Bringup.kext  (kernel, BSD-3-Clause)  --> PCIe, PSP, SMU, GFX, SDMA, MES, DCN 4.1
RDNA4FB  (display framebuffer kext, BSD-3-Clause upstream; patches here add Navi 44)
```

| Component | Path | What it does |
|---|---|---|
| Navi48Bringup | `cobalt64/src/navi48-bringup` | Kernel extension. GPU bring-up, display mode-setting, and the `N48N` user client that exposes buffers, command submission and scanout. Includes the thermal watchdog. |
| dcn41 helpers | `cobalt64/src/dcn41` | Display engine helpers and generated DCN 4.1 register headers. |
| xlat12 | `cobalt64/src/xlat12` | Translation of Apple's GFX10.3 command stream to gfx12. |
| Navi48Accel | `cobalt64/tools/native/navi48accel` | Auxiliary accelerator kext that runs in the AuxKC. |
| Navi48Metal | `cobalt64/tools/native/navi48metal` | Metal device bundle that runs Metal on RADV. Has a build script and an install guide. |
| n48xlate | `cobalt64/third-party/metal2vulkan-n48` | In-process translator library (C ABI) built on NullMoth's translator. |
| RADV Darwin port | `cobalt64/mesa-patches` | Patch series for Mesa's RADV driver: macOS backend and the Navi 44 profile. |
| RDNA4FB patches | `cobalt64/third-party/rdna4fb-n44` | Patch series for the RDNA4FB display kext, adding Navi 44 device matching and timing. |
| Tools | `tools/` | Host tests, Linux-side checks, and bare-metal and VM deployment scripts for the maintainer's machines. |

## Repository layout

| Path | Contents | Licence |
|---|---|---|
| `cobalt64/` | Driver code and build inputs (kext, Metal bundle, RADV patches, translator, native tools). Subtree of Cobalt64 with Navi 44 changes. | MIT, with exceptions listed in [Licences](#licences) |
| `tools/` | Host tests, Linux checks, deployment and recovery scripts. Most are for the maintainer's machines. | See [Licences](#licences) |
| `baselines/0.0.665/` | Reproducible source and build record for kext 0.0.665 (issue #1). | See that directory |
| `research/reports/` | Analysis reports, mostly in Italian. The `macos-20261101/` and `macos-20261112/` reports are in English. | See [Licences](#licences) |
| `research/hw_dump/` | Hardware dumps, logs and test records from the test machine. | See [Licences](#licences) |
| `research/display/`, `research/notes/`, `research/tools/`, `research/artifacts/` | Display data, measurements, decoders and analysis outputs. | See [Licences](#licences) |
| `*.md` at the top level | Status, plan and checklist documents (Italian). | See [Licences](#licences) |

Not tracked by git (see `.gitignore`): `research/ext/` (third-party projects and tools), `research/src/` (Linux and Mesa
reference trees), `research/refs/` (cloned reference projects), `research/macos/` (files extracted from macOS, for local
analysis only) and `research/builds/` (local build trees).

## Building

Build on macOS, with the Xcode Command Line Tools installed. The kext, the Metal bundle and the helpers are x86_64.
Nothing in this list is vendored. Fetch each item yourself.

| Needed | Where |
|---|---|
| RDNA4FB, for `MacKernelSDK` | `git clone https://github.com/somestupidgirl/RDNA4FB` |
| linux-firmware, for the AMD firmware | `git clone https://gitlab.com/kernel-firmware/linux-firmware.git` |
| Mesa, at commit `f5cb8ee032adabef599ae892ec4e42d796b84da9` | `https://gitlab.freedesktop.org/mesa/mesa.git` |
| NullMoth's translator, tag `v2.7.2` | `https://github.com/nullmoth/nvidia-macos-driver` (Rust 1.87 or newer) |

Run the steps below from the repository root. The full details for each step are in the file named in the step.

### 1. Kernel extension (Navi48Bringup)

```sh
cd cobalt64
tools/fetch-firmware.sh /path/to/linux-firmware     # copies the firmware files into src/navi48-bringup/firmware/
make -C src/navi48-bringup MKSDK=/path/to/RDNA4FB/MacKernelSDK all
```

The output is `src/navi48-bringup/build/Navi48Bringup.kext`. The default ASIC is `navi44`. Check the build as described
in [`cobalt64/BUILDING.md`](cobalt64/BUILDING.md), which also lists the firmware files the kext embeds.

### 2. RADV (Mesa)

```sh
git clone https://gitlab.freedesktop.org/mesa/mesa.git && cd mesa
git checkout f5cb8ee032adabef599ae892ec4e42d796b84da9
git am /path/to/repository/cobalt64/mesa-patches/*.patch     # apply in numeric order
```

The default build targets Navi 44. Add `-Dc_args=-DRADV_DARWIN_NAVI48` for Navi 48. See
[`cobalt64/mesa-patches/README.txt`](cobalt64/mesa-patches/README.txt).

### 3. Translator library (n48xlate)

```sh
git clone https://github.com/nullmoth/nvidia-macos-driver && cd nvidia-macos-driver
git checkout v2.7.2
patch -p1 < /path/to/repository/cobalt64/third-party/metal2vulkan-n48/patches/0003-n48xlate-on-nullmoth-translator-v2.7.2.patch
cd translator && MACOSX_DEPLOYMENT_TARGET=12.0 cargo build --release -p n48xlate --target x86_64-apple-darwin
```

The output is `translator/target/x86_64-apple-darwin/release/libn48xlate.dylib`. The licence is LGPL-3.0-or-later. See
[`cobalt64/third-party/metal2vulkan-n48/README.txt`](cobalt64/third-party/metal2vulkan-n48/README.txt).

### 4. Metal bundle (Navi48Metal)

```sh
cd cobalt64/tools/native/navi48metal
ASIC=navi44 N48_RADV_LIB=/path/to/libvulkan_radeon.dylib N48_XLATE_LIB=/path/to/libn48xlate.dylib \
  N48_VK_INC=-I/path/to/mesa/include N48_SPVCACHE_DIR=/path/to/spvcache ./build.sh
```

The output is `build/Navi48Metal.bundle.tar`. The build script and its environment variables are described in
[`INSTALL.md`](cobalt64/tools/native/navi48metal/INSTALL.md) (in Italian).

The translation cache (`spvcache`) is generated locally from macOS shaders and is not distributed. Without one, the
build needs `N48_ALLOW_EMPTY_SPVCACHE=1`, and the bundle then shows only the fallback placeholders.

### 5. Auxiliary kext (Navi48Accel)

```sh
cd cobalt64/tools/native/navi48accel
make MKSDK=/path/to/RDNA4FB/MacKernelSDK
```

Install and load steps are in [`INSTALL.md`](cobalt64/tools/native/navi48accel/INSTALL.md). Do not use
`kmutil install --update-all`. That guide explains why.

### 6. Helper tools (macOS)

```sh
sh cobalt64/tools/native/build.sh                   # builds n48nub, the user-client helper
sh cobalt64/tools/native/mtlprobe/build.sh          # builds mtlprobe, the Metal probe
```

### 7. Checks that run on Linux

These do not need the GPU or macOS:

- `tools/linux-check-kext.sh [file.cpp ...]` compiles the kext sources with `-fsyntax-only` against `MacKernelSDK`
  (set `MKSDK` to its path).
- `tools/mesa-shim-check.sh` checks RADV's canned gfx1200 record with Mesa's drm-shim. It needs a Mesa tree with the
  patches applied; see the script header.
- `tools/hosttests/run.sh` runs the host tests of the kext code. See [CONTRIBUTING.md](CONTRIBUTING.md#tests).

## Installing and running

- **There is no installer for general use.** The scripts under `tools/baremetal/` and `tools/vm/` were written for the
  maintainer's own machines. They contain machine-specific paths, partition UUIDs and EFI layouts. Do not run them
  unchanged.
- **Development history.** Early tests ran in a macOS virtual machine with the GPU passed through. The procedure is in
  [`VM_MACOS.md`](VM_MACOS.md) (in Italian).
- **Bare-metal history.** The bare-metal bring-up and the OpenCore configuration are described in
  [`research/reports/baremetal_bringup.md`](research/reports/baremetal_bringup.md) (in Italian). Boot-arguments are
  listed in the kext source comments and in
  [`INSTALL.md`](cobalt64/tools/native/navi48metal/INSTALL.md), section 7.
- **Before you test:** read the [Safety](#safety) section and the newest entries in [`STATO.md`](STATO.md).

## Licences

This repository has no single licence. Each part is licensed under the file named in the table. Where a directory has no
licence file, the table says so.

| Part | Path | Licence and file |
|---|---|---|
| Cobalt64 base, Navi 44 changes, Metal bundle, Navi48Accel, native tools, tests | `cobalt64/` (except below) | MIT. [`cobalt64/LICENSE`](cobalt64/LICENSE) |
| Navi48Bringup kext | `cobalt64/src/navi48-bringup/` | BSD 3-Clause. [`LICENSE`](cobalt64/src/navi48-bringup/LICENSE) and [`NOTICE`](cobalt64/src/navi48-bringup/NOTICE) |
| n48xlate and the changes to NullMoth's translator and metal2vulkan | `cobalt64/third-party/metal2vulkan-n48/` | LGPL-3.0-or-later. [`COPYING`](cobalt64/third-party/metal2vulkan-n48/COPYING) and [`NOTICE`](cobalt64/third-party/metal2vulkan-n48/NOTICE) |
| RADV Darwin patches | `cobalt64/mesa-patches/` | The patches are changes to Mesa and carry Mesa's licence (MIT). See [`README.txt`](cobalt64/mesa-patches/README.txt) |
| RDNA4FB patches | `cobalt64/third-party/rdna4fb-n44/` | Patches to RDNA4FB, which is BSD 3-Clause. See [`THIRD-PARTY-LICENSES.txt`](cobalt64/third-party/THIRD-PARTY-LICENSES.txt) |
| Third-party licence texts | `cobalt64/third-party/THIRD-PARTY-LICENSES.txt` | Lists the licences of the code that the kext adapts. |
| Host tests and tools | `tools/` | No licence file and no licence statement yet. |
| Reports, notes and dumps | `research/`, top-level `*.md` | No licence file yet. |

Notes:

- **Linux amdgpu.** The kext uses the register headers, which AMD distributes under MIT. The kernel driver sources are
  GPL-2.0 or dual-licensed, depending on the file. Where code is taken from them, keep that file's own licence and
  SPDX header.
- **Not included, and not to be redistributed:**
  - **AMD firmware** (from linux-firmware). It is under AMD's firmware licence. Fetch it yourself. Do not redistribute it.
  - **Apple software.** macOS, Apple's frameworks, binaries, installers and shader compilers are not part of this project.
  - **Other projects' code.** Mesa, RDNA4FB, NullMoth's translator, OpenCore and metal2vulkan are fetched from upstream.
    NullMoth's other components have different licences (PolyForm Noncommercial) and are not part of this repository.

## Credits

This project builds on the following open work. Only projects that the code or the test setup actually use are listed.

- **Cobalt64**: the base of the `cobalt64/` directory (MIT). <https://cobalt64.com>
- **RDNA4FB** (Sunneva N. Mariu, somestupidgirl): the display kext that the RDNA4FB patches modify (BSD 3-Clause). The
  kext build also uses the `MacKernelSDK` headers that come with its clone. <https://github.com/somestupidgirl/RDNA4FB>
- **mac-amdgpu** (lemonade-sdk, Geramy Loveless): the IP-block bring-up sequences (MIT). <https://github.com/lemonade-sdk/mac-amdgpu>
- **NullMoth**: the translator base of n48xlate (LGPL-3.0-or-later). <https://github.com/nullmoth/nvidia-macos-driver>
- **metal2vulkan** (steelbrain, Anees Iqbal and contributors): the translator that NullMoth's version derives from
  (LGPL-3.0-or-later). <https://github.com/steelbrain/metal2vulkan>
- **Mesa and RADV** (MIT). <https://gitlab.freedesktop.org/mesa/mesa>
- **Linux amdgpu** (AMD and the kernel community): register definitions and reference documentation.
- **OpenCore** and **Lilu**, **VirtualSMC** (Acidanthera): the boot loader and kexts used on the test machine.
- **USBToolBox**: the USB port-mapping approach used by the test setup.
- **OpCore-Simplify** (lzhoang2601, BSD 3-Clause): used to generate the EFI configuration for the test machine.
- **VoodooHDA**: the audio driver used on the test machine.

Cobalt64 is an independent project. It is not affiliated with or endorsed by AMD or Apple. AMD, Radeon and RDNA are
trademarks of Advanced Micro Devices, Inc. Apple, Mac, macOS and Metal are trademarks of Apple Inc.

## Documentation

- [`docs/STATUS.md`](docs/STATUS.md): status, known problems and roadmap, in English.
- [`STATO.md`](STATO.md): current status, with the newest entries at the end (Italian).
- [`COMPLETEZZA_DRIVER_GPU.md`](COMPLETEZZA_DRIVER_GPU.md): checklist for a complete driver (Italian).
- [`PIANO_DRIVER_METAL_RX9060XT.md`](PIANO_DRIVER_METAL_RX9060XT.md): development plan (Italian).
- [`FASI.md`](FASI.md): development phases and their state (Italian).
- [`research/reports/`](research/reports/): analysis reports. Start with `01` to `08` (Italian) or `macos-20261112/`
  (English).
- [`baselines/0.0.665/README.md`](baselines/0.0.665/README.md): how the 0.0.665 baseline was reproduced (English).
- [`cobalt64/README.md`](cobalt64/README.md): the upstream Cobalt64 README. It describes the RX 9070 XT, not this project's
  status.

## Contributing

- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests, hardware reports and what not to submit.
- [SECURITY.md](SECURITY.md): how to report security issues privately.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): expected behaviour in project spaces.

Open an [issue](https://github.com/pastasugo89/RX9060XT_macOS_driver/issues/new/choose) for bugs, feature requests or
hardware reports.
