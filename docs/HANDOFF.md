# Handoff for another AI agent (kept current by the orchestrator)

Last update: 2026-11-25, after the 0.0.682 and bundle 41 candidates were staged. Repo: github.com/pastasugo89/RX9060XT_macOS_driver (branch `main`, protected:
only the owner account pushes directly; others via PR with 1 approval). Licence: PolyForm Noncommercial 1.0.0
(root LICENSE); upstream parts keep MIT/BSD-3/LGPL (see README "Licences"). The user writes in Italian; answer in Italian.

## Live machine state
- macOS Tahoe 26.6.2 (25G83), OpenCore on the CachyOS EFI (VolumeUUID 97C4AA5C-B87D-3786-B1B3-F84A76840DEF), GRUB entry
  "macOS Tahoe (OpenCore)". Recovery: OpenCore entry "Ripristino EFI: driver funzionanti (665)"; every kernel payload
  keeps `RECOVERY/pre-contexts-<ver>-config.plist` (previous config).
- Kernel kext Navi48Bringup **0.0.681** (installed by a parallel Codex agent; merged in main 4c495d0). Features: 64 contexts
  on 8 VMIDs (per-UID 48), Linux DET/watermarks (0.0.673), UCLK underflow fallback pinned for the boot (0.0.676),
  GFX clock gating (0.0.675), thermal clamp at 100 C (0.0.675), fan zero-RPM opt-in `navi48-fan-zerorpm=0` (0.0.676),
  CP busy marks (0.0.677), compute preamble (0.0.678), **GFXCLK DPM via boot gate** (0.0.678) which works since the
  Linux GFX doorbell index (0.0.679), telemetry `Navi48,Telemetry` (0.0.681). Interrupts still off (`navi48-interrupts=0`).
- Metal bundle **39** (ANGLE cubemap usage fix; Codex). RDNA4FB 0.0.9. 60 Hz disabled (flag removed 2026-11-12).
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
  the staged versions are kernel 0.0.682 and Metal bundle 41.

## Candidates prepared on 2026-11-25

- Kernel **0.0.682**, still on the 0.0.681 source lineage. The reviewed overlay and stage script are in
  `tools/baremetal/navi44-desktop/refresh-60/`. The signed kext, 11 passing host tests and build manifest are in
  `research/builds/macos-20261125/kernel-682/kernel-contexts-v18-reviewed/`. The matching EFI payload is
  `research/builds/macos-20261125/kernel-682/kernel-payload-v18/`. OpenCore validation and a round trip on a
  copy of the EFI passed. Ring submission releases the global locks before retrying. Timed wait backoff is on
  by default (`navi48-waitsleep=0` restores the legacy timing). The existing `navi48-interrupts=0` remains in the
  EFI config. Guarded interrupts and EOP wake (`navi48-interrupts=2`) and soft recovery (`navi48-softrec=1`) are
  separate opt-ins. The new kext and opt-ins still need GPU validation.
- Metal **41**, with bundle 40 texture views, the NullMoth v3.0 translator and release RADV with 0012. It also
  limits frequent IOSurface and successful pipeline-variant logs and disables optional validation in debug
  RADV by default. The RADV build uses Mesa `afc608b523f0` with patches 0010 and 0012, Meson release,
  `-Db_ndebug=true` and `-Doptimization=3`. Re-signing the release dylib reproduces the bundled RADV hash.
  The signed bundle is in `research/builds/macos-20261125/bundle41-combined/` and the payload is in
  `research/builds/macos-20261031/trial-b41/payload/`. The isolated runtime probe on kernel 0.0.681 passed
  cubemap allocation, six-face mipmaps, texture-view reads and a render-and-readback on a nonzero face/mip.
  Brave and WindowServer with bundle 41 still need testing.
- Live remains **0.0.681 / 39**. Installation requires the user's go-ahead and a stable boot latch. The
  bundle 41 payload was staged against the live 0.0.681/39 guard. For a combined installation, apply the
  reviewed 0.0.682 EFI and matching guard first, then restage bundle 41 against that guard before installing
  it with `install-trial.sh --version 41`. Reboot once after validating both. The two guard transformations
  were checked offline and produce the same file in either order. Roll back Metal before rolling back the
  kernel so the intermediate guard still matches the EFI.
- Bundle 40 remains separately built and uninstalled at `research/builds/macos-20261125/bundle40-views/`.
  RDNA4FB 0.0.10 is a separate candidate at `research/builds/macos-20261123/rdna4fb-0.0.10/`.

## Next planned steps

1. After the user's approval, install both candidates with the current boot arguments. After reboot, verify
   the latch, telemetry and WindowServer, then run Aquarium and the WebGL 2 framebuffer test in Brave.
2. Run A/B trials for guarded interrupts and soft recovery independently, one boot at a time.
3. Review the separate sRGB/linear copy change, reduce draw-time pipeline variants (F2), and defer RADV open
   until it is needed (F5). Continue with dynamic UCLK without underflows, GFXOFF, VRAM management, VCN and
   multi-monitor. The macOS 26.7.x port stays separate because the current stack is pinned to build 25G83.

## Key reports
docs/STATUS.md; STATO.md (Italian log); research/reports/macos-20261112/*.md; research/reports/macos-20261114/
gfx-activity-investigation.md; research/reports/macos-20261123/brave-webgl-679.md; research/reports/macos-20261125/
{stability-performance,vermilion-audit}.md.
