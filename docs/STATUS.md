# Status and roadmap

This is the English summary of the project state. It is derived from the Italian documents [`STATO.md`](../STATO.md)
(newest entries at the end), [`COMPLETEZZA_DRIVER_GPU.md`](../COMPLETEZZA_DRIVER_GPU.md) (sections 18 and 19) and the
reports in [`research/reports/macos-20261112/`](../research/reports/macos-20261112/) (English). Where those documents
disagree, the newest dated entry wins, and this file says so.

The status is for one test machine: AMD Ryzen 7 7700, RX 9060 XT 16 GB, one 1440p 120 Hz monitor on DisplayPort, macOS
Tahoe 26.6.2 (build 25G83), OpenCore. Results do not generalise to other hardware.

## State at kernel 0.0.675

Kernel 0.0.675 (commit `83678ea`) is installed on the test machine. It adds two things over 0.0.674:

- **GFX clock gating.** The kernel runs Linux's `gfx_v12_0` clock-gating routine once after bring-up, under RLC safe
  mode, with the cg flags of GC 12.0.0 (CGCG/CGLS, 3D, MGCG, FGCG, repeater FGCG, perf clock, CP idle polling and
  busy/idle interrupts). Before this, the RLC had every clock-gating override set and CGCG off, so the GFX block toggled
  at full clock with no work. Boot-arguments `navi48-cg=0` and `navi48-cg-ints=0` turn parts of this off.
- **Thermal clamp instead of a freeze.** On 12 November 2026 a hotspot of 85 to 87 °C latched the old 80 °C trip, and the
  desktop froze for good. The watchdog now warns at 90 °C. At 100 °C it clamps GFXCLK low through the SMU, and it
  releases the clamp after 10 s below 85 °C. GPU work is no longer refused.

GFXCLK is still clamped at 500 MHz. The idle clamp default is unchanged.

Clock gating and the new thermal behaviour are new. They need soak testing before anyone relies on them.

## What works (test machine)

| Area | Status | Evidence and limits |
|---|---|---|
| GPU bring-up | Working | PSP, SMU, IMU/RLC, GFX, MES and SDMA initialise on the test machine. |
| Accelerated desktop | Working | WindowServer composites through the Metal bundle, and most system apps run accelerated. |
| Metal translation | Working, partial | Icons fixed in bundle 38 (grey and alpha layers in RG8 IOSurfaces were not swizzled before). Some items remain: the default style of Find My and the rocket tip of Games in dark mode. Icons cached inside System Settings stay old until the cache renews. |
| GPU contexts | Working | 64 logical contexts over 8 dynamic VMIDs, kernel 0.0.667 and later. The earlier 8-session limit is lifted. |
| Display 2560x1440 at 120 Hz | Working | The default mode. |
| Black band at the top | Fixed in 0.0.673 | The GOP left the display only 3 DET segments (192 KB). 0.0.673 gives DET0 20 segments and programs Linux's watermarks. |
| Compute, internal tests | Partial | The shader baseline and the `vadd_ir` test pass. There is no public compute API. |

## Known problems

- **Browsers.** Brave runs with GPU acceleration, and WebGL and WebGPU were reported working. A trial in October showed
  only three animation callbacks in about 16 seconds, so frame pacing is not yet verified.
- **Video.** There is no hardware decoding (VCN). Video playback stutters.
- **60 Hz.** Opt-in, behind a flag file. The 0.0.673 fix removed the black band in most sessions. On 12 November one boot
  at 60 Hz showed only the pointer on a black screen after `WINDOWSERVER_READY`. Cause open. The 60 Hz mode is kept off
  after that.
- **Underflow after login.** On the first boot of 0.0.673, three display underflows occurred about 10 seconds after
  login. The fallback then pinned UCLK at 1258 MHz, which costs about 8 W. A two-stage fallback (stutter off first, then the pin)
followed in 0.0.674.
- **Power.** The unclamped GPU at full clock drew about 170 W at idle, which is the board limit. The 500 MHz clamp keeps
  power down. The effect of clock gating on idle power has not yet been measured in a written report.
- **Recovery.** A GPU fault can leave the desktop frozen until a restart (`DEVICE_LOST` on every submission). Do not
  change GPU clocks or power limits by hand.
- **Multi-monitor.** Experimental paths for a second and third display exist behind boot-arguments (`navi48-m6`,
  `navi48-m6flip`, `navi48-m6flip1`). They are not validated.
- **Other items from earlier reports.** A `vkCreateDescriptorPool` failure at the login peak was recorded on 31 October.
  Its current status is not known.
- **Sleep and wake.** Not verified.

## Not started or not working

- GPU clock range: the core clock is clamped at 500 MHz. The full PMFW range, with a clock ladder, is the next step.
- Sensors exposed to macOS, and fan control. Both are planned after the clock ladder.
- Hardware video (VCN) decode and encode.
- A public Vulkan driver. RADV is used inside the Metal path only.
- OpenCL, ROCm and HIP.
- HDR.
- Robust recovery from GPU faults.

## Roadmap

The next work on power is in this order: a clock ladder up to the full PMFW range, then sensors exposed to macOS, then fan
control. Power work needs one reboot per step, with idle and load power and temperature measured read-only at each step.

The broader plan follows the phases in `COMPLETEZZA_DRIVER_GPU.md`, section 19:

| Phase | Result to deliver | Condition to move on |
|---|---|---|
| A. Contract | Hardware and API inventory, capability register, reproducible baseline | No required capability without classification and a planned test |
| B. Foundations | Paged memory, multiple clients, scheduler, synchronisation, isolation, recovery | Stress tests independent of the apps, and correct release of resources |
| C. Metal | Compiler and runtime that conform to the chosen profile | Full semantic tests for the chosen profile, with no admission by name |
| D. macOS and display | Compositor, IOSurface, drawables, 60/120 Hz modes, power cycle | Stable general desktop, and frames presented correctly |
| E. Video and browsers | VCN or VideoToolbox, and standard browser back-ends | Codecs and web conformance tests verified |
| F. APIs and compute | Public Vulkan ICD, GL/GLES/EGL, OpenCL, compute frameworks | Each path has its own closed test suite |
| G. Advanced features | Modern hardware features, ROCm/HIP if the product includes them | Separate evidence for each feature or runtime |
| H. Qualification | Performance, soak tests, packaging and rollback | A closed matrix for the final product, and a publishable report |

The phases can overlap when they are independent. Completing D or E does not mean F or G is complete.

## Estimate

The maintainer's rough estimate, which is not a measurement: about 55 to 60 percent of a daily-use driver, and about 35 to
40 percent of a complete driver.
