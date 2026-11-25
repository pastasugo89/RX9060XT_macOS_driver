# Handoff for another AI agent (kept current by the orchestrator)

Last update: 2026-11-25 evening. Repo: github.com/pastasugo89/RX9060XT_macOS_driver (branch `main`, protected:
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
  next kernel 0.0.682, next bundle 40/41.

## Work in flight (subagents) and where their output goes
| Item | State | Output |
|---|---|---|
| Kernel 0.0.682: IH storm guard + EOP-wake fence waits (opt-in), soft GPU recovery (opt-in), F1 no ring-space spin under global locks + log 2 s bound expiries, F3 sleep waits + VMID backoff | running | research/builds/macos-20261125/kernel-682/ |
| Bundle format-copy patch (sRGB/linear twins) | part of the 0.0.682 agent | research/builds/macos-20261125/bundle-formatcopy/ |
| Bundle 40: texture views of cube/2D-array textures | running | research/builds/macos-20261125/bundle40-views/ |
| RADV release build (asserts/validation off, faster dlopen) | running | research/builds/macos-20261125/radv-release/ |
| macOS 26.7.2 upgrade evaluation | running | research/reports/macos-20261125/macos-26.7-upgrade.md |
| AMDHV repo audit | running | research/reports/macos-20261125/amdhv-audit.md |

## Ready but not installed
- Translator rebased on NullMoth v3.0: patches/0004, dylib `research/builds/macos-20261123/xlate-v29/libn48xlate.dylib`
  (sha ebb746f5...), byte-identical output on the 48-text corpus.
- RADV patch 0012 (cmd-buffer teardown crash fix): dylib `research/builds/macos-20261123/radv-crashfix/` (sha e64dad00...).
- Bundle stability patch: `research/builds/macos-20261125/stability/0001-bundle-radv-debug-validation-off.patch`.
- RDNA4FB 0.0.10 (refresh from OTG V_TOTAL readback): `research/builds/macos-20261123/rdna4fb-0.0.10/` (install script there).

## Next planned steps
1. Assemble bundle 40/41 = bundle 39 + cube views + translator v3.0 + RADV 0012 (+ release build if verified) +
   stability items F2 (no pipeline variant builds on the render thread), F5 (lazy RADV open), F8 (log rate limits).
2. Install kernel 0.0.682, A/B its opt-ins one boot at a time (ioreg/metrics only).
3. Then: dynamic UCLK without underflows (OPTC-level; hypotheses in research/reports/macos-20261114/gfx-activity-investigation.md),
   GFXOFF, VRAM memory management, VCN, multi-monitor (Vermilion has 2-display code, see vermilion-audit.md).

## Key reports
docs/STATUS.md; STATO.md (Italian log); research/reports/macos-20261112/*.md; research/reports/macos-20261114/
gfx-activity-investigation.md; research/reports/macos-20261123/brave-webgl-679.md; research/reports/macos-20261125/
{stability-performance,vermilion-audit}.md.
