# Handoff for another AI agent (kept current by the orchestrator)

Last update: 2026-11-25, after installing the 0.0.683 fix for Basemark startup. Repo: github.com/pastasugo89/RX9060XT_macOS_driver (branch `main`, protected:
only the owner account pushes directly; others via PR with 1 approval). Licence: PolyForm Noncommercial 1.0.0
(root LICENSE); upstream parts keep MIT/BSD-3/LGPL (see README "Licences"). The user writes in Italian; answer in Italian.

## Live machine state
- macOS Tahoe 26.6.2 (25G83), OpenCore on the CachyOS EFI (VolumeUUID 97C4AA5C-B87D-3786-B1B3-F84A76840DEF), GRUB entry
  "macOS Tahoe (OpenCore)". Recovery: OpenCore entry "Ripristino EFI: driver funzionanti (665)"; every kernel payload
  keeps `RECOVERY/pre-contexts-<ver>-config.plist` (previous config).
- Kernel kext Navi48Bringup **0.0.682** (loaded and verified). Features: 64 contexts
  on 8 VMIDs (per-UID 48), Linux DET/watermarks (0.0.673), UCLK underflow fallback pinned for the boot (0.0.676),
  GFX clock gating (0.0.675), thermal clamp at 100 C (0.0.675), fan zero-RPM opt-in `navi48-fan-zerorpm=0` (0.0.676),
  CP busy marks (0.0.677), compute preamble (0.0.678), **GFXCLK DPM via boot gate** (0.0.678) which works since the
  Linux GFX doorbell index (0.0.679), telemetry `Navi48,Telemetry` (0.0.681). Interrupts still off (`navi48-interrupts=0`).
- Metal bundle **43** is installed. Fresh Basemark processes load it. The desktop started this boot on bundle 41. RDNA4FB 0.0.9. 60 Hz disabled (flag removed 2026-11-12).
- Boot guard: `/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh` + latch
  `boot-state.json` (pending -> stable after desktop 120 s). A pending/failed latch blocks acceleration next boot
  (archive it to unblock, see STATO.md history).

## How releases are built and installed
- Kernel: overlay patch over the previous **candidate tree** (git HEAD is not the deployed lineage):
  `tools/baremetal/navi44-desktop/build-production-contexts.py`, `production-kernel-payload.py`,
  `refresh-60/stage-<ver>-payload.sh` -> `research/builds/<date>/kernel-<ver>/kernel-payload-vNN`.
  Install = swap the guard (5 lines differ: version) + `kernel-efi/install-kernel-efi.py <payload> --apply` as root,
  with backups; then the user reboots. Example script: `research/builds/macos-20261123/install678.sh`.
- Bundle: `cobalt64/tools/native/navi48metal` (build.sh), staged/installed with
  `tools/baremetal/navi44-desktop/metal-trial/stage.sh` + `install-trial.sh` (guard bump of bundle version/hashes).

## Hard rules learned (see also the user's memory files)
- Never change GPU clocks/power on the live desktop (`navi48test power 0` froze the PC 2026-11-12).
- No live `navi48test regs` reads of CP queue/HQD/MES/select registers (WindowServer crash loop after such reads
  2026-11-17, unproven). OK: ioreg, `navi48test log`, `navi48test metrics`.
- Never pipe between two `sudo -S` calls; never write the sudo password into files or commits.
- Do not read NootedRed/NootRX source. AMD firmware and Apple binaries are never committed.
- Number new releases after the highest seen anywhere (check `git fetch`, remote branches, PRs, live versions):
  the staged versions are kernel 0.0.683 and Metal bundle 43.

## Basemark startup and kernel 0.0.683

Basemark detects Metal 43 and BC7, then crashes during GPU resource-manager
initialization. It requests a 134,217,728-byte shared Metal buffer. The installed
0.0.682 kernel permits 64 MiB per GTT allocation. The driver reports
`VK_ERROR_OUT_OF_DEVICE_MEMORY` and the benchmark crashes in `bzero`. An
independent Metal allocation reproduced the failure on the RX 9060 XT.

The 0.0.683 candidate raises the per-allocation GTT limit to 128 MiB. The
512 MiB per-session budget and the host-import limits are unchanged. The
regression test exercises the maximum-size buffer with 32,768 scattered pages
and checks that an additional page exceeds the limit. The signed candidate and
the verified EFI payload are under `research/builds/macos-20261125/kernel-683/`.
All 12 host test programs passed. OpenCore validation and a simulated EFI
install and restore passed. The payload retains the Metal 43 pins and replaces
only the kernel entry in the OpenCore configuration.

The 0.0.683 kernel and matching activation guard were installed on 2026-11-25.
The installer verified the live EFI inventory after replacing the kernel entry.
The 0.0.682 EFI backup is
`/Library/Application Support/Navi44/efi-backup-20261125T160827Z`.
The original guard was backed up at
`/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.pre-683-20261125T160827Z.sh`.
The machine is still running 0.0.682. After reboot, confirm that 0.0.683 loaded
and repeat the 128 MiB shared-buffer allocation before testing Basemark.
Benchmark execution and thermal behavior under benchmark load remain unverified.

## Candidates prepared on 2026-11-25

- Kernel **0.0.682**, still on the 0.0.681 source lineage. The reviewed overlay and stage script are in
  `tools/baremetal/navi44-desktop/refresh-60/`. The signed kext, 11 passing host tests and build manifest are in
  `research/builds/macos-20261125/kernel-682/kernel-contexts-v18-reviewed/`. The matching EFI payload is
  `research/builds/macos-20261125/kernel-682/kernel-payload-v18/`. OpenCore validation and a round trip on a
  copy of the EFI passed. Ring submission releases the global locks before retrying. Timed wait backoff is on
  by default (`navi48-waitsleep=0` restores the legacy timing). The existing `navi48-interrupts=0` remains in the
  EFI config. Guarded interrupts and EOP wake (`navi48-interrupts=2`) and soft recovery (`navi48-softrec=1`) are
  separate opt-ins. Both opt-ins still need independent hardware trials.
- Metal **41**, with bundle 40 texture views, the NullMoth v3.0 translator and release RADV with 0012. It also
  limits frequent IOSurface and successful pipeline-variant logs and disables optional validation in debug
  RADV by default. The RADV build uses Mesa `afc608b523f0` with patches 0010 and 0012, Meson release,
  `-Db_ndebug=true` and `-Doptimization=3`. Re-signing the release dylib reproduces the bundled RADV hash.
  The signed bundle is in `research/builds/macos-20261125/bundle41-combined/` and the payload is in
  `research/builds/macos-20261031/trial-b41/payload/`. The isolated runtime probe on kernel 0.0.681 passed
  cubemap allocation, six-face mipmaps, texture-view reads and a render-and-readback on a nonzero face/mip.
  WindowServer and the target Brave regressions passed after installation.
- Installed **0.0.682 / 41** with the existing boot arguments and verified EFI, signed bundle, guard and
  backups. For recovery, roll back Metal before rolling back the kernel so the intermediate guard still matches
  the EFI.
- Bundle 40 remains separately built and uninstalled at `research/builds/macos-20261125/bundle40-views/`.
  RDNA4FB 0.0.10 is a separate candidate at `research/builds/macos-20261123/rdna4fb-0.0.10/`.

## First boot and browser checks

- The boot latch reached `stable` with accelerated WindowServer. IORegistry telemetry refreshed with the
  administrative probe and was readable by the logged-in user. GFX DPM was left in Auto. The established
  display-underflow fallback pinned UCLK to 1258 MHz after seven early underflows.
- Brave rendered Aquarium at 10 and 1,000 fish without WebGL context loss or a change in the GPU process.
  The WebGL 2 cubemap framebuffer reproduced the expected RGBA pixel via ANGLE Metal on the RX 9060 XT,
  with no GL error, context loss or GPU-process restart.
- Across the brief browser checks the independent hotspot reached 55 °C and the watchdog remained active
  without a clamp. Fan PWM reported zero and there was no sustained RPM reading. The firmware retains its
  default fan policy. Automatic physical spin-up and speed regulation under a warmer load remain unverified.

## Metal 42 candidate and fan diagnostics

- Metal **42** shares cull-mode and front-face variants when RADV supports and enables extended
  dynamic state. Draws still record the requested state. Topology and depth/stencil continue to
  select their own variants. The fallback keeps static raster variants.
- A texture and its views now use one layout for copies within their shared image. The driver
  checks overlap in root-image coordinates. Independent sRGB/linear images retain the raw copy.
- Isolated RX 9060 XT tests on kernel 0.0.682 produced identical raster readback with Metal 41 and
  42 across cull changes, winding changes, a PSO switch and a second pass. The probe created
  seven pipelines with 41 and two with 42. The cubemap test passed face/mip readback after a
  shared-image copy and preserved the exact bytes in a linear-to-sRGB copy.
- The signed 42 build is in `research/builds/macos-20261125/bundle42-raster-copy/`. Use the
  `stage42-raster-copy-v1` profile when staging from live bundle 41. WindowServer and Brave
  with 42 still need a boot test. Kernel 0.0.682 and Metal 41 were the active baseline for those tests.
- The fan diagnostic separates the policy request, readback and physical fan behavior. The
  change built on a copy of the deployed kernel source and passed 143 host checks. It is for a
  future kernel build. PMFW IF 0x33 RPM and physical speed regulation remain unverified.

## Metal 43 candidate for Basemark GPU

Basemark GPU 1.2.3 lists Metal only when its compression probe returns a
supported format. With bundle 41, the probe found the RX 9060 XT and returned
an empty list. The legacy Mac1 check gates the BC7 query.

Metal 43 includes the Metal 42 changes and supports BC1–BC7 sampled textures
when RADV exposes the corresponding formats. The implementation uses
block-aligned upload and readback, handles CPU row padding and small mip edges,
and initializes compressed allocations by copying blocks from a zeroed staging
buffer. The Mac1 and BC capability queries depend on verified RADV format
features.

The isolated test on the RX 9060 XT passed the capability queries, padded BC7
rows, zeroed allocations, 1×1 mip readback, private upload and fragment decoding.
The cubemap and raster tests passed too. The signed candidate is at
`research/builds/macos-20261125/bundle43-bc-textures/`. Use the
`stage43-bc-textures-v1` profile and `--allow-skip` when staging from live 41.
Metal 43 is installed with the 41 backup and a guard for kernel 0.0.682.
Basemark's native capability query in a new process now returns BC7 for the
RX 9060 XT. The UI needs a fresh process to refresh its API list. A full benchmark
run and desktop validation after reboot remain pending.


## Orchestrator session, 2026-11-25 ~18:50 (Claude)
- Synced to origin/main f12f086; the older local uncommitted state was saved as `git stash@{0}`
  ("pre-sync local work 2026-11-25 18:50") and as research/builds/macos-20261125/pre-sync/local-uncommitted.diff.
- PR #3 (telemetry) marked ready and merged (its commits were already in main).
- Live: kernel 0.0.683, bundle 43.
- Basemark crash after the 128 MiB fix (17:18, BasemarkGPU_metal-2026-11-25-171806.ips): SIGABRT in
  -[_MTLCommandEncoder dealloc] from -[N48RenderEncoder initWithCommandBuffer:descriptor:]; last driver line
  "render pass: no colour or depth/stencil attachments" (Navi48Device.m ~5818). Basemark uses an attachment-less
  render pass (renderTargetWidth/Height), and our init's `return nil` after super-init aborts the app.
  Agent running: bundle 44 = attachment-less render passes + safe nil paths -> research/builds/macos-20261125/bundle44-noattach/.
- Agent running: kernel 0.0.684 = Linux display clock floors (DALSMC) so UCLK can switch without OPTC underflows,
  plus boot logging of display clocks around ufmon events -> research/builds/macos-20261125/kernel-684/.
- 19:05 bundle 44 installed (attachment-less passes): runtime probe 8/8 OK as normal user. Basemark now reaches the
  first image and loading bar, then stops: its passes have no attachments AND renderTargetWidth/Height 0 (refused ->
  "draw without a render pipeline state" -> command buffer aborted), plus ~8000 "fragment texture(0) never bound".
  Agent running: bundle 45 (diagnostics of those descriptors + semantics) -> research/builds/macos-20261125/bundle45-basemark/.
- Kernel 0.0.684 committed (696f530), payload research/builds/macos-20261125/kernel-684/kernel-payload-v20, NOT installed
  (install needs the user's explicit go-ahead; live guard f88cb144 -> 9ffec241, 5 lines; script
  research/builds/macos-20261125/install684.sh to be generated like install678.sh).
- 19:3x Basemark completes on bundle 45/46: scores 21602 / 21532 (Medium 1080p); bundle 46 run has zero refusals
  and zero unbound-texture warnings (shadows OK). GPU under the run: activity <=73 %, GFXCLK 0.8-1.8 GHz, 31-45 W, 46 C,
  fans 0 -> the driver (submission path), not the GPU, limits the score.
- 0.0.684 BOOT PROBLEM (live now): after 1 of 5 DAL floor messages the DAL mailbox timed out and the main SMU mailbox
  stopped answering (metrics -> 0xe00002d6 timeout); desktop slow. DISPCLK/DPPCLK read 562.5 MHz (not 272.7).
  The user refused a rollback: agent running = 0.0.685 repair (safe DAL protocol, post-check, SMU-degraded mode,
  self-limiting clktrace) -> research/builds/macos-20261125/kernel-685/. A prepared (unused) rollback script:
  research/builds/macos-20261125/rollback-684-to-683.sh.

## Next planned steps

1. Relaunch Basemark to refresh backend selection and retest WindowServer, Aquarium and
   `tools/baremetal/navi44-gpu-diagnostics/test-brave-webgl2-cubemap.py`. Compare pipeline
   timing at login using the existing T1 logs.
2. Validate fan spin-up and speed regulation with an independent tachometer or visual observation
   under a monitored load. The SMU 0x33 metrics layout still needs confirmation.
3. Run A/B trials for guarded interrupts and soft recovery independently, one boot at a time.
4. Defer RADV open (F5) while preserving the device admission check. Continue with dynamic UCLK
   without underflows, GFXOFF, VRAM management, VCN and multi-monitor. The macOS 26.7.x port stays
   separate because the current stack is pinned to build 25G83.

## Key reports
docs/STATUS.md; STATO.md (Italian log); research/reports/macos-20261112/*.md; research/reports/macos-20261114/
gfx-activity-investigation.md; research/reports/macos-20261123/brave-webgl-679.md; research/reports/macos-20261125/
{stability-performance,vermilion-audit}.md.
