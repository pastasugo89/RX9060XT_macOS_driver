# Feasibility: 60 Hz scanout on Navi 44 (read-only study)

Date: 2026-10-31. Method: static reading of the repo. Nothing was run against the GPU, no kext was loaded or unloaded, no register was written, NootRX/NootedRed sources were not read, and no AMD firmware was disassembled.

Repo root: `/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver`. Paths below are relative to it.

## Summary

- **Approach A (keep 497.75 MHz, stretch OTG_V_TOTAL to 3050)** gives 497.75e6 / (2720 x 3050) = **59.9988 Hz**. H timing, pixel clock and DP link stay unchanged. The change is +1525 lines. The repo's helper refuses deltas above 256 (`cobalt64/src/dcn41/dcn41_otg_timing.h:116`), so it cannot be used as-is.
- The kext already has the write mechanics, but none of them fit: the locked trial is compiled off for Navi 44; the unlocked `dcnmode 101..130` path writes +20 lines, calibrated for an older 1481-line raster, not the current 1525; and that path is refused on a native boot.
- RDNA4FB reports 120 Hz and emulates VBL from a timer whose period comes from the EDID's first DTD (143.97 Hz). That mismatch exists today, independent of this task.
- Recommended: A, as a new locked absolute V_TOTAL write behind a default-off boot-arg, tested with macOS left at 120 Hz. Judder is expected during that test, but it isolates the black-band question.

## Q1. Approach A: registers and existing writers

| Register | OTG0 abs (BASE_IDX 2) | Where | Notes |
|---|---|---|---|
| OTG_V_TOTAL | 0x1b2f | `cobalt64/src/dcn41/dcn41_regs.h:96-100`, `dcn41_otg_timing.c:16` | Holds total-1, 15-bit field |
| OTG_V_TOTAL_MIN / MAX | 0x1b30 / 0x1b31 | `dcn41_otg_timing.c:17-18` | FreeSync DRR range. No field definitions in the repo |
| OTG_V_TOTAL_CONTROL | 0x1b33 | `dcn41_otg_timing.c:37` | Read-only in the repo. No field definitions |
| OTG_DOUBLE_BUFFER_CONTROL | 0x501C | `cobalt64/src/navi48-bringup/src/dcn/navi48_modetrial_pure.h:58` | DRR mode bits 25:24; 2 = start of frame (`:96`) |
| OTG_MASTER_UPDATE_LOCK | 0x1b89 | `dcn41_regs.h:34-40` | Lock bit 0, status bit 8 |
| OTG_GLOBAL_CONTROL2 | 0x1b90 | `dcn41_regs.h:42-46` | OTG_MASTER_UPDATE_LOCK_SEL bits 27:25 |

Existing writers:
- `dcn41_otg_write_timing` (`dcn41_otg_timing.c:110-131`) writes the whole timing set, including V_TOTAL, with no lock.
- `dcn41_otg_timing_adjust_v_total` (`dcn41_otg_timing.c:163-189`) applies a signed delta. The cap is `DCN41_VTOTAL_MAX_DELTA 256` (`dcn41_otg_timing.h:116`).
- `navi48_dcn.cpp:1153` (`mode()`), write at `:1244-1263`: `dcnmode 101..130` adds `kVTotalDeltaLines = 20` (`:77`). No lock, no blank, no DRR mode.
- `navi48_modetrial_pure.h:16, 721-735, 757-765`: the locked sequence (blank, DRR mode 2, master lock, write, unlock, DTO, MSA, unblank). This is the path to reuse. It is used only for rows 2 and 120.
- `dcn41_otg_lock` / `unlock` (`dcn41_otg.c:12-48`) have no callers (`research/display/primary_path_navi44.md` section 1, row 5).

Monitor acceptance: 60 Hz sits inside the EDID's GTF range of 48-180 Hz V and 30-265 kHz H (`research/display/connectors/DP-1/edid_decoded.txt:66`). The stretched timing is a fixed custom V_TOTAL, so MSA values stay constant, and Adaptive-Sync MSA-ignore is not needed. Whether this LG panel accepts a non-EDID vertical total is not established by the repo. Treat acceptance as the test result, not a given.

## Q2. Runtime paths that write timing

- No runtime path writes arbitrary DCN MMIO. ReadRegs (`N48N_SEL_READREGS`, `src/Navi48NativeABI.h:45`) and the legacy RegRead (`src/Navi48UserClientABI.h:28`) are read-only. Selector 3 writes VRAM only (`Navi48UserClientABI.h:24`).
- The only OTG timing writer is the accel verb `dcnmode` (action 77). Route: selector 13 (`Navi48UserClient.cpp:540`), then `Navi48Bringup::accelExperiment` (`Navi48Bringup.cpp:7541`), then `mode()` (`navi48_dcn.cpp:1153`).
- Refusals: `doAccelExperiment` returns `kIOReturnNotPermitted` when `n4xs::refused()` (`Navi48UserClient.cpp:541`). On a native boot, every accel verb except the three exempt pairs is refused (`Navi48Bringup.cpp:7604-7605`; `navi48_scanout_pure.h:37-39`). The exempt pairs are `dcnmode 0`, `dcnflip 0` and `dcnstate 0`. So `dcnmode 101` is refused on the native desktop boot.
- Native selector 16 (`N48N_SEL_MODE_TRIAL`, `Navi48NativeABI.h:62`) is denied on Navi 44: `mt_gate_ok` checks `kFeatModeTrial` (`navi48_dcn.cpp:2108-2109`), and `N4X_DISP_MODETRIAL_SUPPORTED` is 0 for Navi 44 (`amd/asic_profile.h:120`).
- Boot-args gate only the row-120 trial (`navi48-row120`). There is no timing-override boot-arg.
- Smallest change: a new locked absolute V_TOTAL action, reusing the row-2 sequence with a Navi 44 entry (1525 to 3050), gated by a new default-off boot-arg, and undone by `dcnmode 0`. It needs a kext rebuild, an AuxKC rebuild and a reboot. It does not need an XNU rebuild. It is not hot-loadable, so it means a load/unload cycle, which this study excludes.
- Version caveat: the source tree says 0.0.664 (`Info.plist:18-20`). The installed build is 665. Confirm the running binary matches the source before relying on line numbers.

## Q3. macOS side (RDNA4FB, `research/ext/RDNA4FB-n44/src`)

- Declared rate: `rdna4_refresh_hz` returns 120 for device 0x7590 (`framebuffer.cpp:2256-2262`; used at `:2272`). The mode timing is 497.75 MHz, H 2560+160, V 1440+85 (`:2379-2411`).
- The programmable timing range is 119-121 Hz with `maxVerticalTotal 1525` (`:2606-2609`). Any 60 Hz timing would be refused by it.
- VBL is emulated by a software timer. `fireVBL` (`:1502-1507`) uses `vblPeriodUS`, which defaults to 16667 (`framebuffer.hpp:279`). `registerForInterruptType` overwrites it from `Edid::preferredTiming` (`framebuffer.cpp:1517-1522`).
- The first base-block DTD is 2560x1440 at 143.97 Hz (`edid_decoded.txt:62`). So the emulated VBL period is 6945 us (144 Hz), not 120 Hz. This is a current mismatch by code reading. The comment at `:1517` about 59.996 Hz is stale. I did not measure it.
- If scanout is 60 Hz and macOS paces at 120 or 144 Hz, the flips are paced by a timer, not the scanout. Expect repeated or dropped frames and possible tearing. This is expected from the code, not measured.
- The kext's own `vbl_refresh` (`navi48_dcn.cpp:1682-1712`) derives the period from live OTG totals, so kext-side timing would follow V_TOTAL. RDNA4FB would not.
- To report 60 Hz consistently, change: `rdna4_refresh_hz` (`:2256-2262`), `getTimingInfoForDisplayMode` (`:2379-2411`), the timing range (`:2581-2611`), `rdna4_is_gop_timing` (`:2419-2430`), and set `vblPeriodUS` explicitly rather than from DTD 1.
- The black-band test does not need any of this. Scanout can be changed with macOS left at 120 Hz.

## Q4. Approach B: EDID 59.95 Hz DTD (241.5 MHz)

- Target timing: H 2720, V 1481, 241.5 MHz (`cobalt64/src/dcn41/dcn41_modes_navi44.h`, 2560x1440@60 row; `edid_decoded.txt:116`).
- Needs DCCG DP_DTO0 (abs 0x80/0x81, BASE_IDX 1; `navi48_dcn.cpp:1802-1803`), the OTG totals, and MSA/stream reprogramming. The kext's own sequence moves DTO after the unlock (`Navi48NativeABI.h:349`).
- Link: the 60 Hz row needs HBR x4 (`dcn41_modes_navi44.h` row 5). The live link is HBR2 x4 (`primary_path_navi44.md` section 2, DP0 row). Keeping HBR2 avoids a link retrain.
- Risk is higher than A: four interlocking blocks (DTO, MSA, the DISPCLK hold, lock ordering). Failure mode: sink loses sync, black until resync.

## Q5. Recommendation

1. Approach A. Estimate about 1-2 days: a locked absolute V_TOTAL write (register 3049) reusing the row-2 sequence, a Navi 44 table entry, a default-off boot-arg, host tests, kext and AuxKC rebuild, reboot.
2. Test scanout first, with macOS at 120 Hz. Judder is expected. Check whether the black band disappears.
3. Fix RDNA4FB reporting and VBL period only if the test is positive. Estimate about 1 day.

Failure modes:
- Unlocked write (the existing `dcnmode 101` path) can latch a torn frame. The locked sequence avoids this.
- If the restore fails, the 60 Hz raster persists until reboot. A reboot re-lights the GOP at 120 Hz.
- The monitor may show out-of-range or no signal until power cycle.
- B adds sync loss and clock-hold risk. A hang is not expected from a V_TOTAL change alone, but this was not tested.

## Stale or inconsistent items found

- `cobalt64/src/dcn41/dcn41_otg_timing.h:105` and `navi48_dcn.cpp:70` say the line rate is 88.79 kHz "on this card either way". That is the 60 Hz rate (241.5 MHz). The GOP line rate is 183.0 kHz (`edid_decoded.txt:113`, `framebuffer.cpp:2605`).
- `navi48_dcn.cpp:67-77` calibrates +20 lines from a 1481-line lit raster. The current GOP raster is 1525 lines.
- `cobalt64/src/dcn41/dcn41.h` describes the layer as "DCN 4.1 (Navi 48, gfx1201)". Navi 44 is DMU 4.1.0 / DCN 4.0.1 (`research/reports/02-linux-display-dcn401.md:3, 38-59`). The primary-path dump matched the dcn_4_1_0 OTG0 offsets for Navi 44 (`primary_path_navi44.md` section 2), but verify before relying on other offsets.
