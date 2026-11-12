# Stela (macOS 27 on x86): feasibility for this machine

Research 2026-11-12 (read-only web research; nothing downloaded or run). Verdict: **not now**. Re-evaluate when an AMD GPU path exists.

## What it is
- github.com/tylertms/Stela, GPL-2.0-or-later. Releases v0.1.0 to v0.3.1 on 11-12 Nov (v0.3.1 latest). README: "still in development. It is slow and still may not boot on supported hardware."
- Own UEFI loader (no OpenCore), an AOT+JIT arm64e -> x86-64 translator, a device model that presents an M2 Mac mini, and an NVIDIA-only Metal driver (AIR -> Mesa NIR). The guest is unmodified Apple-silicon macOS (target reported: 27.2, 26B123). Ships no Apple software.
- Requirements: x86-64-v2 Intel or AMD CPU, 8 GB, UEFI with Secure Boot off, NVMe/AHCI with 60 GB; GPU NVIDIA GTX 16 / RTX 20-50 only. Setup wipes its USB stick. Wi-Fi not working in v0.3.1.

## Against our hardware and stack
- GPU: AMD unsupported. Issue #9 (AMD GPU, RX 6950 XT + Ryzen 7 7700) closed on 12 Nov: "Hardware scope will be expanded in the future". An AMD backend would be months of work.
- CPU: Ryzen is in scope, but there are open AMD boot issues (#20, #34, #36, #41).
- Our kexts (Navi48Bringup, RDNA4FB) and Metal bundle are x86_64 code for an x86 macOS; an arm64e guest cannot load them (inference). OpenCore config does not carry over.
- NullMoth 3.0.0-beta.1 "Liberator" (11 Nov, pre-release) is a separate NVIDIA-only macOS 27.2 path on OpenCore Intel PCs (SIP lowered, AMFI off, arm64-only programs run through an added layer); no link to Stela found, no source on the release page.
- Licence: GPL-2.0-or-later; do not copy code into our MIT/LGPL-separated tree.

## Context
macOS 27 Golden Gate (14 Sep 2026) is Apple silicon only; Apple calls it the last release with Rosetta. Tahoe 26 is the last native x86 macOS, so macOS 27+ on this PC will always need translation.

## Watch
Stela issue #9 and any AMD device-model work; Ryzen boot issues; NullMoth documentation of Liberator's layer. Any test: spare disk only, CPU-only boot, never the main disk.
