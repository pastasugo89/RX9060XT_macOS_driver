# Why the PMFW reports 100 % GFX activity on the idle desktop, the zero-RPM fan option, and kernel 0.0.676

Date: 2026-11-14 to 2026-11-17. Kernel 0.0.675 is live (commit 83678ea, payload v11). The analysis is code reading plus earlier read-only data. No register was written and no GPU state was changed.

Sources:
- Deployed tree: `research/builds/macos-20261112/kernel-675/kernel-contexts-v11/candidate-source`.
- Linux: `research/ext/amdgpu-port-study/drm-kmod` (MIT), plus upstream `smu_v14_0_2_ppt.c` and `smu14_driver_if_v14_0.h` from torvalds/linux master, fetched 2026-11-14. The upstream driver header is byte-identical to the local copy.

## Part A: GFX activity at 100 %

### Conclusion

The busy signal is real 3D work at 500 MHz, so this is cause (1). Confidence: high that no kernel-side keep-alive or poll exists; medium that real work alone explains 100 % until the display-sleep A/B is run.

| Candidate cause | Verdict | Evidence |
|---|---|---|
| (1) Real work saturating a 500 MHz GPU | **Most likely** | See the three points below this table. |
| (2) A CP or queue that never idles | Not found | See the list below this table. |
| (3) Our MMIO polling of GC, counted as busy | Not found | No periodic GC MMIO. Fence and idle waits poll a write-back seqno in system memory (`native_s1c.cpp` own_wait / ring_put_locked / retired_now). The thermal watchdog reads only THM_TCON_CUR_TMP (BAR5, `n4x_safety.cpp`). The DCN monitor threads touch only DCN and SMU registers. |
| (4) A decode error | Ruled out as the cause; there is a field mix-up | Our `SmuMetrics` equals Linux's IF 0x2E `SmuMetrics_t`. `MovingAverageGfxActivity` is at byte 0x5A (dword 22, high half); `AverageGfxActivity` is at 0x7C (dword 31, low half). `navi48test metrics` prints **AverageGfxActivity** (`Navi48UserClient.cpp:494`). The 100 % in the power-gating study was **MovingAverage**. Both can be compared from one raw dump (below). GRBM_STATUS shows GUI_ACTIVE independently, so 100 % is not a decode artefact. |

Evidence for cause (1):
- Every GRBM_STATUS sample shows the 3D pipeline busy, not only the CP:
  - 0xad40382c: SPI, SC, DB busy.
  - 0xedf1582c: TA, GE, SX, SPI, BCI, SC, DB, CB busy.
  - Both: CP_BUSY and GUI_ACTIVE.
- CP_STAT 0x80068600 is ROQ_RING + ROQ_INDIRECT1 + PFP + ME + QUERY busy: the CP is executing an IB, not spinning on a poll.
- WindowServer submits about 350 command buffers/s at about 2 ms each, which is 0.75 to 0.8 s of GPU time per second (`performance-plan.md` §1.2). That work is two full-screen composites plus a final pass and a 14.7 MB D-copy per frame, all over PCIe to linear system memory, at 500 MHz.

What was checked for cause (2), with nothing found:
- **`cp_v12_0.cpp`:** the ring tests and fetch probe run once at boot. No periodic submission, no ring-resident WAIT_REG_MEM. CP_RB_WPTR_POLL_CNTL is Linux's 0x00900100 since 0.0.675.
- **Per-submit packets:** each submit wraps the IBs in 2 RELEASE_MEM packets, the same as Linux `gfx_v12_0_ring_emit_fence`. There is no WAIT_REG_MEM and no ACQUIRE_MEM.
- **MES (`mes_v12_1.cpp`):** SET_HW_RESOURCES matches Linux (`oversubscription_timer` 50). Quanta are 0. There is no periodic MES_MISC.
- **Queues:** the KCQ stays mapped with rptr == wptr, as Linux's KCQs do. No KIQ queue is mapped.
- **Bundle:** the 1 s tick only stats files and calls a status ioctl. The D-copy is appended only to command buffers that wrote a display surface (`Navi48Device.m:1207-1210`).
- **The G1 WAIT_REG_MEM hang test** runs only with `navi48-g1=1`.

Two factors are not kernel faults:
- **GFXOFF:** DisallowGfxOff is sent once at init. It keeps GFX powered but does not make the PMFW report busy. Linux with `gfxoff=0` reads about 0 % at idle.
- **SetWorkloadMask:** it is never sent. That affects DPM policy, not the activity reading.

So the open question is why WindowServer redraws the full screen at 120 Hz on a "static" desktop. This is a bundle / damage-tracking question; "avg partial area 0 %" in the scanout counters says every pass is full-screen. It is not a kernel bug.

### What 0.0.676 does about it: the clock-ladder step, not a "fix"

- **New boot-arg `navi48-gfxmax=<MHz>`.** The boot idle clamp sends SetSoftMaxByFreq(GFXCLK, cap) instead of the PMFW minimum. The cap is bounded to the PMFW range [GetMinDpmFreq, GetMaxDpmFreq].
- **Default unchanged.** Without the boot-arg the clamp is exactly 0.0.675's Low.
- **Thermal behaviour.** The thermal TRIP clamp still goes to the PMFW minimum. The RESTORE after a TRIP returns to the cap.
- **No live path.** The user client still accepts power states 0..4 only, so the cap cannot be changed on the live desktop.
- **`navi48-idle-clamp=0`** ignores the cap.
- **Registry:** `Navi48,GfxMax` is published only when a cap is set.

Suggested ladder, one reboot per rung, measured read-only at each: `navi48-gfxmax=1000` → 1500 → 2000 → 2500 → absent the clamp (`navi48-idle-clamp=0`).

At each rung, compare:
- AverageGfxActivity and MovingAverageGfxActivity;
- GRBM_STATUS GUI_ACTIVE duty (below);
- T1 `cb_gpu` average and its 6.4–25.6 ms bucket;
- board and socket power, and hotspot.

If activity falls below 100 % at 1000 to 1500 MHz with idle power still near 30 W, the chicken-and-egg is confirmed and the cap can climb.

### Read-only commands for the orchestrator

What is strictly read-only (source checked):
- **`navi48test regs`:** reads BAR5 dwords with RREG32. It makes no GRBM_GFX_INDEX or GRBM_GFX_CNTL write (`navi48test.c:114-157`, `Navi48UserClient.cpp` doRegRead).
- **`navi48test log`, `counters`, `info`, `accel status`:** read-only.
- **`navi48test metrics N`:** not pure. It sends GetDriverIfVersion and TransferTableSmu2Dram, and reads VRAM through MM_INDEX/MM_DATA. It changes no clock or power state, and it has been used before.
- **Not to be used:** `accel queuestate`, `schedstate` and `ringstate` are refused on a native boot. `power`, `poke`, `submit`, `test` and `hangtest` change state.

Registers:
- Absolute dword = GC base + offset, with idx0 = 0x1260 and idx1 = 0xA000 (`gc_12_0_0_offset.h`). 0x2004 = GRBM_STATUS is verified.
- Per-queue HQD registers (CP_HQD_ACTIVE 0x320B; MES set 0xC8xx) need a GRBM_GFX_CNTL select **write**, so they are skipped.
- The GFX HQD set reads bank 0, the kernel GFX queue. GRBM_GFX_CNTL is read to confirm the select is 0.

```sh
T="/Library/Application Support/Navi44/accelerated-trial/navi48test"

# 1. Which activity field says 100 %: one metrics read, then its raw dump (dword 22 hi16 = MovingAverageGfxActivity, dword 31 lo16 = AverageGfxActivity,
#    dwords 0..10 = CurrClock[GFX,SOC,UCLK,FCLK,DCLK0,VCLK0,DISPCLK,DPPCLK,DPREFCLK,DCFCLK,DTBCLK], dword 11 = GfxclkTarget|PreDs, 12 = PostDs|FclkPreDs)
sudo "$T" metrics 1
sudo "$T" log | grep -E 'metrics( raw|:)' | tail -8

# 2. One status snapshot (selects included so the bank of the HQD rows is known)
sudo "$T" regs <<'EOF'
0x2004 GRBM_STATUS
0x2002 GRBM_STATUS2
0x2007 GRBM_STATUS3
0x2005 GRBM_STATUS_SE0
0x2006 GRBM_STATUS_SE1
0x219F CP_BUSY_STAT
0x21A0 CP_STAT
0x219D CP_STALLED_STAT1
0x219E CP_STALLED_STAT2
0x219C CP_STALLED_STAT3
0x21A1 CP_ME_HEADER_DUMP
0x21A2 CP_PFP_HEADER_DUMP
0x2084 CP_CPC_STATUS
0x2085 CP_CPC_BUSY_STAT
0x208A CP_CPC_BUSY_STAT2
0x2087 CP_CPF_STATUS
0x2088 CP_CPF_BUSY_STAT
0x2093 CP_CPF_BUSY_STAT2
0x208E CP_MEC_ME1_HEADER_DUMP
0x21C2 CP_RB_WPTR_POLL_CNTL
0x3049 CP_INT_CNTL
0x306A CP_INT_CNTL_RING0
0xA900 GRBM_GFX_CNTL(select)
0xC200 GRBM_GFX_INDEX
0x30E0 CP_GFX_HQD_ACTIVE(bank0)
0x30E8 CP_GFX_HQD_RPTR(bank0)
0x30F1 CP_GFX_HQD_WPTR(bank0)
0x31A0 CP_RB_ACTIVE
0xEE6C RLC_GPM_STAT
0xEC04 RLC_STAT
0xEC43 RLC_PG_CNTL
0xEC48 RLC_CGTT_MGCG_OVERRIDE
0xEC49 RLC_CGCG_CGLS_CTRL
0xA803 CP_ME_CNTL
EOF

# 3. GUI_ACTIVE duty cycle: 400 timestamped samples of GRBM_STATUS + CP_STAT + the two header dumps in ONE process (about 1 ms per row)
for i in $(seq 1 100); do printf '0x2004 GRBM_STATUS\n0x21A0 CP_STAT\n0x21A1 ME_HDR\n0x21A2 PFP_HDR\n'; done > /tmp/gc-duty.txt
sudo "$T" regs < /tmp/gc-duty.txt > ~/gc-duty-desktop-$(date +%H%M%S).txt
#   GUI_ACTIVE = bit 31 of GRBM_STATUS; header opcode = bits [15:8] of the dumps (0x3C WAIT_REG_MEM every time = a spin; 0x3F/0x49/0x2D/0x58 = normal IB work)

# 4. The display-pipeline A/B (the user runs pmset; everything else is read-only)
sudo "$T" metrics 20 > ~/metrics-display-on-$(date +%H%M%S).txt
sudo "$T" regs < /tmp/gc-duty.txt > ~/gc-duty-on-$(date +%H%M%S).txt
pmset displaysleepnow                       # the user: display asleep, WindowServer stops compositing
sleep 15; sudo "$T" metrics 20 > ~/metrics-display-off-$(date +%H%M%S).txt
sudo "$T" regs < /tmp/gc-duty.txt > ~/gc-duty-off-$(date +%H%M%S).txt
#   then wake the display (key press). As the user, no root:
/usr/bin/log show --last 3m --style compact --predicate 'process == "WindowServer" AND (eventMessage CONTAINS "T1 cb_gpu" OR eventMessage CONTAINS "scanout:")'
```

How to read the results:

| Observation | Meaning |
|---|---|
| Activity and GUI_ACTIVE duty fall to about 0 with the display asleep | The load is WindowServer's (cause 1). Fix it with the clock ladder and the bundle work (damage, VRAM surfaces). |
| Activity stays at 100 % with the display asleep and T1 shows no command buffers | A CP or RLC that never idles (cause 2 or 3). Then the header dumps show where: a constant 0x3C means a poll. |
| Static desktop (no cursor, no clock seconds, no streaming text) vs light use | If the duty barely changes, WindowServer redraws without damage. That is a bundle question. |
| MovingAverage 100 % while Average is lower | The PMFW's long average lags. Use AverageGfxActivity (what Linux reports). |

## Part B: zero-RPM off (`navi48-fan-zerorpm=0`)

### Linux path ported (MIT, `smu_v14_0_2_ppt.c` master)

- **Support check.** `PP_OD_EDIT_FAN_ZERO_RPM_ENABLE` requires `smu_v14_0_2_is_od_feature_supported(ZERO_FAN_BIT 11)`, which is PPTable `SkuTable.OverDriveLimitsBasicMax.FeatureCtrlMask` bit 11.
- **Range check.** The value must lie in [BasicMin.FanZeroRpmEnable, BasicMax.FanZeroRpmEnable]. Linux then sets FanZeroRpmEnable and FeatureCtrlMask |= BIT(11).
- **Commit.** `normalize_feature_mask` clears every bit whose fields equal the boot table. For a zero-RPM edit alone, the upload mask is exactly BIT(11).
- **Upload.** `upload_overdrive_table` sends TransferTableDram2Smu(TABLE_OVERDRIVE = 8). `(read_arg & 0xff) == 0xFF` means invalid content, with the OD_FAIL_e code in `arg >> 16`.
- **Inputs.** The boot table comes from TransferTableSmu2Dram(8). The PPTable comes from TransferTableSmu2Dram(TABLE_COMBO_PPTABLE = 1), with PPTable_t at `smu_14_0_2_powerplay_table.smc_pptable`.

### Layout evidence and validation (the PMFW speaks IF 0x33; the header is 0x2E)

Offsets are from Linux's own structs. The host test includes the Linux header and checks every constant with `offsetof`:
- **OverDriveTable_t:** 156 bytes. FeatureCtrlMask @0, UclkFmin/Fmax @0x1C/0x1E, FanTargetTemperature @0x3A, **FanZeroRpmEnable @0x3C**, FanZeroRpmStopTemp @0x3D, FanMode @0x3E, MaxOpTemp @0x3F.
- **PPTable_t:** 0x1174 bytes, SkuTable at +0x1C (size 0xDE0). In SkuTable: OD BasicMin @0xAA0, BasicMax @0xB00, MsgLimits FanStopTempMin/Max @0xA68/0xA6A. smc_pptable sits at combo offset 0x540.

The kernel trusts nothing until each check below passes. Any failure means nothing is written; after the upload nothing more is ever written.

1. **The combo PPTable describes itself.** The header's PPTable_t start and size and SkuTable start and size must equal the 0x2E values (0x540/0x1174, 0x55C/0xDE0). `SkuTable.Version` must be PPTABLE_VERSION 0x1B; the header comment says "increment this version if SkuTable_t or BoardTable_t change". The limits must also be self-consistent: zero-fan limits boolean, stop-temp min ≤ max ≤ 120, and so on.
2. **ZERO_FAN must be advertised.** BasicMax mask bit 11 must be set, both masks non-zero, and 0 must lie within [zeroMin, zeroMax].
3. **The OD table is read twice and must be identical.** The slot is canary-filled before each read, so "the PMFW wrote nothing" is detected. The fan block must also be plausible against the limits:
   - zero-RPM and FanMode are booleans;
   - the stop temperature is inside MsgLimits and non-zero;
   - target and MaxOpTemp are inside their limits;
   - UclkFmin ≤ UclkFmax inside the UCLK limits;
   - GfxclkFoffset is inside its limits.
   The test shows a table shifted by 1 to 4 bytes is refused.
4. **The upload changes one field.** It is the table as read, with only FanZeroRpmEnable = 0 and FeatureCtrlMask = BIT(11). The PMFW applies only the zero-fan fields and validates them itself. The image is staged in VRAM and read back before the message is sent.
5. **Read-back after the upload** must equal the upload byte for byte outside FeatureCtrlMask, with FanZeroRpmEnable = 0.

Independent evidence the 0x2E layout holds on this card and PMFW: Linux 7.2 on the same board (`research/hw_dump/sysfs_power.txt`) decoded the OD limits as SCLK_OFFSET -500..1000 MHz, MCLK 97..1500 MHz and VDDGFX -200..0 mV. It decoded the OD table as OD_MCLK 97/1259 MHz. All of these are plausible, and they come from SkuTable.OverDriveLimitsBasic* and OverDriveTable_t.UclkFmin/Fmax with the 0x2E header. The fan fields of the OD table have never been decoded on this card. Step 3 and the boot log of the full table (next section) are the evidence to check after the first boot.

### Behaviour

**When and where it runs.**
- Once per boot, in `Navi48Bringup::runStages`, right after GFX clock gating and before the native self-test and any client.
- Only on the full bring-up path (ladder reached its target, MES up, SMU online) and after the protection gate (THROTTLERS, FW_CTF and FAN_CONTROL running, so EnableAllSmuFeatures ran).
- The whole sequence runs under the shared SMU mailbox lock. It refuses to run unlocked.

**Boot-arg.**
- `navi48-fan-zerorpm` absent: nothing is read or written. The default build behaves exactly as 0.0.675.
- `=0`: zero RPM off, so the fans always spin.
- `=1`: zero RPM on.
- Any other value: nothing.

**Logging.** The boot log has `fan-od:` lines with:
- the combo header;
- the OD limits BasicMin and BasicMax in hex;
- the OD table in hex;
- the decoded fields, the upload kr and arg, and the verdict.

**Registry.** `ioreg -l -w0 | grep Navi48,Fan` shows:
- the wanted state and the verdict;
- FanZeroRpmEnable before → after;
- the stop temperature, FanMode and target temperature;
- the upload kr and arg;
- the PPTable SkuTable offset, size and version, the OD mask and the limits;
- fan rpm and PWM from one metrics read at boot. Live values: `navi48test metrics`.

**navi48test.** No new verb was added. A dump verb would need a new user-client selector plus a new navi48test system file in the payload. The full tables are logged at boot instead.

### Risks

- **Wrong layout in the fan block that still passes every check.** This is very unlikely given the cross-checks. The impact is bounded: the upload mask is BIT(11) only, so the PMFW looks only at the zero-fan fields and range-checks them itself. Fans spinning is the thermally safe direction.
- **The PMFW may reject the upload** (TABLE_TRANSFER_FAILED) or the read-back may differ. Then the verdict says so and nothing more is written. The PMFW OD state may or may not have changed; the next boot without the boot-arg reads it fresh, and the setting is not persistent across a power cycle.
- **The VRAM slot is shared with `smu_read_metrics`.** The sequence runs at boot before any client. A metrics read racing it at that moment would read one bad snapshot, nothing more. It uses the MM_INDEX window like `smu_read_metrics` does, without gVramMmLock, which is the existing precedent.
- **Acoustics.** The fans run at their minimum PWM at idle. That is a user choice.

## Part C: the UCLK pin is kept for the boot

On 2026-11-14 the 0.0.675 one-time quiet release at about 671 s was followed within 10 to 42 s by four OPTC-only underflows, a re-pin and a visible band.

0.0.676 changes the default:
- The 10-minute release of an AUTO pin is **off by default**: once the fallback pins, the pin holds for the boot.
- Boot-arg `navi48-uclkpin-release=1` restores the 0.0.674/0.0.675 behaviour.
- The display-off release and the re-pin when the display returns are unchanged.
- `Navi48,UclkPin` now shows "10-min release armed / used / off".

Code: `smu_uclkpin_pure.h` `fb::quiet_release_enabled` and `fb::init(..., quietRelease)`; `navi48_dcn.cpp` arb_monitor_loop. No fix for the cause is attempted.

### Why switches still underflow at OPTC/ODM and not at HUBP: hypotheses

The facts: HUBP0 status clean (0x000f0002), ODM0_OPTC_INPUT_GLOBAL_CONTROL 0x400 (underflow occurred), and the underflows stop while UCLK is pinned. Together these say the trigger is a UCLK p-state switch. The starvation is seen downstream of HUBP: the DPP→MPC→OPP→OPTC input FIFO ran dry while HUBP's request side never flagged an underflow.

| # | Hypothesis | What it predicts | Read-only discriminator |
|---|---|---|---|
| H1 | **DCFCLK / DISPCLK / DPPCLK move with no hard minimum.** Linux's dcn401 clk_mgr sends hard mins (DCFCLK, DCFCLK deep sleep, DISPCLK/DPPCLK via DALSMC). We send none, so the PMFW may drop DCFCLK (Linux pp_dpm_dcefclk shows 147/236/1800 MHz) or deep-sleep it around a UCLK switch. The return path then cannot refill the pipe after the blackout. | DCFCLK low or changing near events. DISPCLK/DPPCLK at GOP values but DCFCLK at 147. | Sample `navi48test metrics 1` + the `metrics raw` log line repeatedly (CurrClock[9] DCFCLK, [6] DISPCLK, [7] DPPCLK, [2] UCLK, [3] FCLK in dwords 0..10) with `navi48-uclkpin-release=1` set for one boot, and correlate with the `ufmon:` event times in `navi48test log`. |
| H2 | **FCLK p-state switches.** FCLK still moves 1096↔2016 MHz. Our FCLK watermark of 8.8 µs assumes 0 blackout, so if an FCLK switch is tied to the UCLK switch (or has its own blackout), the allowed window is too short. | Events coincide with FCLK transitions. With UCLK pinned, FCLK may still move without events (the pin may also hold FCLK higher). | Same sampling. Check whether FCLK changes while UCLK is pinned, and whether events ever occur with UCLK pinned. Read DCHUBBUB_ARB_WATERMARK_CHANGE_CNTL and the A/B fclk watermark sets back (already in `Navi48,DisplayArb`). |
| H3 | **The UCLK switch is longer than the vblank, with no FW-assisted switching.** The 85-line vblank at 1440p120 is about 0.46 ms. Without FAMS/SubVP the switch can land in active time. DET 20 segments covers HUBP (status clean), but downstream FIFOs (OPP/ODM input) are small and refill at DPPCLK/DISPCLK. | Events only at 120 Hz, much rarer at 60 Hz (longer vblank). | Compare event rates at 60 and 120 Hz. Read OTG0 vertical position at event time from the ufmon log. |
| H4 | **ODM/OPTC input FIFO settings left at GOP values.** OPTC_DATA_SOURCE_SELECT, OPTC_MEMORY_CONFIG and the ODM input FIFO thresholds; a too-small FIFO or wrong segment config would make OPTC the first to see starvation. | A constant config that differs from what Linux programs for one 1440p plane. | Read the OPTC0 registers (OPTC_DATA_SOURCE_SELECT, OPTC_MEMORY_CONFIG, OPTC_INPUT_CLOCK_CONTROL, OPTC_INPUT_GLOBAL_CONTROL, ODM_MEM_PWR_CTRL) once with `regs` and compare with Linux dcn401 `optc401_set_odm_bypass` / `optc35_set_odm_combine` defaults. |

H1 is the most consistent with "pinning UCLK fixes it but HUBP never sees it". It is also the gap with the clearest Linux counterpart, the DALSMC hard mins.

## 0.0.676: build, payload, tests

### Changes

Overlay patch over the 0.0.675 candidate tree:
- File: `research/builds/macos-20261114/kernel-676/PATCHES/kernel-0.0.676-over-0.0.675.diff`
- sha256 `4b79b4ce491aa073f62a677854ad7b939803c9250d86c8ff798f85ee5dc46fd6`
- The same changes are in the HEAD worktree: `PATCH-vs-HEAD.diff`.

| File | Change |
|---|---|
| `src/amd/smu_od_pure.h` (new) | Layout, validation, upload image, read-back check, boot-arg and verdict names. |
| `src/amd/smu_fan_od.cpp` (new) | The kernel sequence, logging and the `Navi48,Fan` text. |
| `src/amd/smu_gfxmax_pure.h` (new) | The navi48-gfxmax cap. |
| `src/amd/smu_v14_0.cpp` | `SMUPowerState::BootCap` (:923) and the boot-cap globals (:877). |
| `src/amd/amdgpu_smu.h` | Declarations; BootCap = 5 (:302). |
| `src/amd/amdgpu_init.cpp:924-930` | The idle clamp uses `smu_gfx_boot_state()`. The failure clamp stays Low. |
| `src/Navi48Bringup.cpp:6955-6966` | navi48-gfxmax parsing and the thermal restore state. |
| `src/Navi48Bringup.cpp:~7160` | The fan step after clock gating; `Navi48,Fan` and `Navi48,GfxMax`. |
| `src/amd/smu_uclkpin_pure.h:112-122` | `quiet_release_enabled` and the `init` parameter. |
| `src/dcn/navi48_dcn.cpp:2456, 2542-2548` | The release boot-arg and the registry text. |
| `Info.plist` | 0.0.676. |

Markers 675 → 676 are set by the build script.

### Build and payload

- **Candidate:** `research/builds/macos-20261114/kernel-676/kernel-contexts-v12`. Built by `build-production-contexts.py --version 0.0.676` on the reviewed 0.0.675 tree. Base verified: 276 inputs and binary 70b8dbfa…. All 8 CPU tests pass. The warning count is the same as 0.0.675's (32).
- **Kernel binary sha256:** `5867c432e22960ba204b9d7074b0785c2f46d8fcdbb44dd04732d9c59a21f30a`.
- **Payload v12:** `research/builds/macos-20261114/kernel-676/kernel-payload-v12`, staged by `refresh-60/stage-676-payload.sh` over payload v11.
  - 122 files verified.
  - Candidate config sha256 `86925433d4bf6f23cb8ad35aa1571a1e61d005bc7e216356bb19d65765e4c287`.
  - EFI = v11's EFI plus `OC/Kexts/Navi48Bringup-contexts-0.0.676.kext` and `RECOVERY/pre-contexts-676-config.plist`; config change: Kernel/Add/7/BundlePath only.
- **ocvalidate 1.0.8:** no issues (`ocvalidate-kernel-payload-v12.log`).
- **Guard:**
  - Input: the live guard, sha `3c5f0625…`. This is payload v11's guard and was re-checked on 2026-11-17: the live system still runs 0.0.675.
  - Output: sha `9db4950a4b383283b9c3f7044ace4080f781e6b6605b4c92b1949b7fda16ded5`.
  - Exactly 5 lines change, each 675 → 676: lines 57, 74, 85, 233 and 243 (the capability match, the STOP text and the three refresh-60 hook lines).

### Tests

- **`run-host-tests.sh`** → `host-tests-676.stdout`, all PASS:
  - fan_od676: 141 checks, on HEAD and on the overlay tree;
  - disparb 140, ufmon 37, uclkpin 88 (HEAD and overlay);
  - cg675 and safety (HEAD and overlay);
  - native_s2a/s2d: identical to clean HEAD (35 pre-existing FAIL lines).
- **Tool tests:** `test-refresh60h-payload.py` (new, 21 tests) passes. So do `test-refresh60g/f`, `test-production-contexts-build.py` (22), `test-production-kernel-guard.py` and `test-apply-refresh-guard.py`.

### Install notes (for the orchestrator; nothing was installed)

- Install payload v12 with the existing unified installer flow, like payload v11. EFI and the guard need root, then reboot.
- The default boot behaves as 0.0.675, plus the UCLK pin holding for the boot.
- Opt-ins, one per boot:
  - `navi48-fan-zerorpm=0`: then check `ioreg -l -w0 | grep Navi48,Fan` for "applied and verified", read the `fan-od:` lines in `navi48test log`, and confirm rpm > 0 at idle with `navi48test metrics`.
  - `navi48-gfxmax=<MHz>`: the clock ladder.
  - `navi48-uclkpin-release=1`: only to reproduce the H1–H3 measurements.
- Recovery: the OpenCore entry and `RECOVERY/pre-contexts-676-config.plist` (the 0.0.675 configuration).

---

## Follow-up 2026-11-17: Part A was wrong. The CP fetcher never idles, and the kernel GFX doorbell is in the wrong window

### What the display-sleep test showed (orchestrator, 0.0.676 live)

The display was off from 20:39:36. During that time:
- The PMFW reports 100 % on both activity fields.
- WindowServer submits about 80 command buffers/s at 0.5 ms each, so only a few percent of GPU time.

The register samples while the display was off:

| Register (200 samples) | Bit | Share of samples |
|---|---|---|
| GRBM_STATUS | GUI_ACTIVE | 100 % |
| GRBM_STATUS | CP_BUSY | 100 % |
| GRBM_STATUS | 3D blocks | 29.5 % |
| GRBM_STATUS2 | CPF_BUSY | 99.5 % |
| GRBM_STATUS2 | CPC_BUSY | 0 |
| GRBM_STATUS2 | CPG_BUSY | 0 |
| CP_STAT | (value 0) | 58 % |

So the **command fetcher (CPF) is busy all the time while ME, PFP and the MEC are idle**. The Part A conclusion ("real 3D work at 500 MHz") is refuted.

### The bug, from code against Linux (confidence: high that it is a bug; medium-high that it is the cause)

**What Linux does** (`gfx_v12_0.c:927` and `:2844-2856`, MIT):
- The kernel GFX ring uses `ring->doorbell_index = adev->doorbell_index.gfx_ring0 << 1`, which is 0x8B << 1 = **0x116**.
- That single number goes into three places:
  - the MQD's `CP_RB_DOORBELL_CONTROL.DOORBELL_OFFSET`;
  - the MES ADD_QUEUE / RESET / REMOVE `doorbell_offset`;
  - `WDOORBELL64(ring->doorbell_index)`, i.e. byte **0x458**, which is QWORD-aligned.
- The doorbell windows are written in the same QWORD units:
  - GFX = bytes [(0x8B·2)<<2, (0xFF·2)<<2] = **[0x458, 0x7F8]**;
  - MEC = [(0x000·2)<<2, (0x8A·2)<<2] = **[0x000, 0x450]**.
- Compute (`(mec_ring0+id) << 1`) and MES (`mes_ring0 << 1`) are shifted the same way.

**What our kext does** (since 0.0.18):
- It programs the two windows exactly as Linux does (`cp_set_doorbell_range`).
- But it uses the **unshifted** `gfx_ring0` (0x8B) as the queue's doorbell (`cp_init_full`).
- So the MQD says DOORBELL_OFFSET 0x8B. Every submission (`native_s1c.cpp` ring_put, `cp_kick_doorbell`) writes its 64-bit doorbell at byte **0x22C**.

Byte 0x22C is **inside the compute window**, below the GFX window, at an odd dword. The consequences:
- The GFX CP never receives the doorbell.
- The write lands in the MEC range at an offset that no compute queue owns. That is an unmapped doorbell, and the MES is told to handle those (CP_UNMAPPED_DOORBELL ENABLE, `mes_enable_unmapped_doorbell_handling`).
- The GFX queue only learns its wptr through the wptr-poll path (the MQD's `cp_rb_wptr_poll_addr` and CP_RB_WPTR_POLL_CNTL), or through the MES relaying the unmapped doorbell.

Either path keeps the fetcher side of the CP busy without ME or PFP work. That is what the samples show. The header comment in `amd/amdgpu_ip.h`, which says "CP uses these numbers as DWORD indices directly … ring->doorbell_index = adev->doorbell_index.gfx_ring0", contradicts `gfx_v12_0.c:927`.

Other differences found, which 0.0.677 does not change:

| Difference | Ours | Linux | Status |
|---|---|---|---|
| MES pipe 1 (MES KIQ) | `CP_MES_CNTL` 0x04000000: pipe 1 never activated, no KIQ HQD, no set_hw_resources on pipe 1, yet `RLC_CP_SCHEDULERS` designates me3/pipe1/q0 with the enable bit | 0x0C000000; the Linux oracle dmesg prints both writes | Second candidate; registers below tell |
| MES ring / KCQ doorbells | Also unshifted (dword 0x0B, 0x03..) | Shifted | Both sit inside the MEC window and work; a later alignment |
| `sdma_hqd_mask` | 0x0F | 0xFC | MES "owns" SDMA queues 0–3 that we program by hand; SDMA is idle in the samples |

### Read-only `regs` lists (no select writes; run as root with navi48test)

```sh
T="/Library/Application Support/Navi44/accelerated-trial/navi48test"

# A. One snapshot: windows, the gfx queue's doorbell and pointers (bank 0 = the kernel GFX queue; GRBM_GFX_CNTL read to confirm the select is 0), MES, faults
sudo "$T" regs <<'EOF2'
0xA900 GRBM_GFX_CNTL(select;expect0)
0xC200 GRBM_GFX_INDEX
0x305A CP_RB_DOORBELL_RANGE_LOWER(expect0x458)
0x305B CP_RB_DOORBELL_RANGE_UPPER(expect0x7f8)
0x305C CP_MEC_DOORBELL_RANGE_LOWER(expect0)
0x305D CP_MEC_DOORBELL_RANGE_UPPER(expect0x450)
0x30ED CP_RB_DOORBELL_CONTROL(OFFSET[27:2],EN30,HIT31)
0xA880 CP_UNMAPPED_DOORBELL
0x21C2 CP_RB_WPTR_POLL_CNTL
0x30EB CP_RB_WPTR_POLL_ADDR_LO
0x30DE CP_GFX_MQD_BASE_ADDR
0x30E0 CP_GFX_HQD_ACTIVE
0x30E1 CP_GFX_HQD_VMID
0x30E6 CP_GFX_HQD_BASE
0x30E8 CP_GFX_HQD_RPTR
0x30E9 CP_GFX_HQD_RPTR_ADDR
0x30EF CP_GFX_HQD_CNTL
0x30F0 CP_GFX_HQD_CSMD_RPTR
0x30F1 CP_GFX_HQD_WPTR
0x30F2 CP_GFX_HQD_WPTR_HI
0x21C0 CP_RB0_RPTR
0x3054 CP_RB0_WPTR
0x3055 CP_RB0_WPTR_HI
0x3041 CP_RB0_CNTL
0x31A0 CP_RB_ACTIVE
0xC807 CP_MES_CNTL(Linux0x0c000000)
0xA98A RLC_CP_SCHEDULERS
0xC80D CP_MES_HEADER_DUMP(bank-ambiguous)
0xC813 CP_MES_INSTR_PNTR(bank-ambiguous)
0xA803 CP_ME_CNTL
0xC904 CP_MEC_RS64_CNTL
0x2827 GCVM_L2_STATUS
0x282C GCVM_L2_PROTECTION_FAULT_CNTL
0x282D GCVM_L2_PROTECTION_FAULT_CNTL2
0x2830 GCVM_L2_PROTECTION_FAULT_STATUS_LO32
0x2831 GCVM_L2_PROTECTION_FAULT_STATUS_HI32
0x2832 GCVM_L2_PROTECTION_FAULT_ADDR_LO32
0x2833 GCVM_L2_PROTECTION_FAULT_ADDR_HI32
0x2819 GCUTCL2_GROUP_RET_FAULT_STATUS
0x2884 GCVM_CONTEXT0_CNTL
0x288C GCVM_CONTEXT8_CNTL
EOF2

# B. Duty cycle of the fetcher's sub-units: 100 x 8 rows in one process (display off and on)
for i in $(seq 1 100); do printf '0x2002 GRBM_STATUS2\n0x2087 CP_CPF_STATUS\n0x2088 CP_CPF_BUSY_STAT\n0x2093 CP_CPF_BUSY_STAT2\n0x2089 CP_CPF_STALLED_STAT1\n0x2084 CP_CPC_STATUS\n0x30E8 CP_GFX_HQD_RPTR\n0x30F1 CP_GFX_HQD_WPTR\n'; done > /tmp/cpf-duty.txt
sudo "$T" regs < /tmp/cpf-duty.txt > ~/cpf-duty-$(date +%H%M%S).txt
```

Notes on these reads:
- `regs` makes no select write.
- The HQD rows read GRBM_GFX_CNTL bank 0 (ME0 / pipe 0 / queue 0, the kernel GFX queue), provided A's first row reads 0.
- The CP_MES_* per-pipe rows are ambiguous without a select, and the select is not written.
- Compute and MES HQD pointers need a select write, so they are skipped.

**Decode** (`gc_12_0_0_sh_mask.h`):

| Register | Bits |
|---|---|
| CP_CPF_STATUS | POST_WPTR_GFX_BUSY 0, CSF_BUSY 1, ROQ_RING 5, ROQ_IND1 6, HQD_BUSY 15, UTCL2IU_BUSY 17, RCIU_BUSY 18, RCIU_GFX 19, RCIU_CMP 20, GCRIU 23, **MES_HQD_BUSY 24**, **CPF_GFX_BUSY 26**, **CPF_CMP_BUSY 27**, **CPC_CPF_BUSY 30**, CPF_BUSY 31 |
| CP_CPF_BUSY_STAT | CSF_RING 1, CSF_IND1 2, HQD_DISPATCH 12, HQD_IQ_TIMER 13, HQD_PQ_FETCHER 18, HQD_IB_FETCHER 19, HQD_CONSUMED_RPTR 22, HQD_FETCHER_ARB 23, **HQD_WPTR_POLL_BUSY 29**, HQD_PQ_BUSY 30, HQD_IB_BUSY 31 |
| CP_CPF_BUSY_STAT2 | MES_HQD_DISPATCH 12, MES_HQD_MESSAGE 17, **MES_HQD_PQ_FETCHER 18**, MES_HQD_FETCHER_ARB 23, MES_HQD_PQ_BUSY 30, **MES_UNMAPPED_DOORBELL_BUSY 31** |
| CP_CPF_STALLED_STAT1 | RING_FETCHING 0, INDR1_FETCHING 1, UTCL2IU_WAITING_ON_FREE 7 / TAGS 8, **GFX_UTCL1_WAITING_ON_TRANS 9**, CMP_UTCL1_WAITING_ON_TRANS 10 |

**How to read the results:**

| Observation | Meaning |
|---|---|
| CP_RB_DOORBELL_CONTROL OFFSET field = 0x8B and HIT (bit 31) never set, while CP_GFX_HQD_WPTR advances | Confirms the doorbell bug |
| HQD_WPTR_POLL_BUSY, or MES_UNMAPPED_DOORBELL_BUSY / MES_HQD_* constantly set | The busy source; fixed by 0.0.677 |
| MES_HQD_* constant together with CP_MES_CNTL = 0x04000000 | Points also at the missing MES KIQ pipe (the next fix) |
| GFX_UTCL1_WAITING_ON_TRANS or UTCL2IU_* constant | A stalled translation. Check the fault registers in list A |

Fault status 0x00840d5c decodes to: write, mapping error, client CID 6 = CPG, VMID 8. That is a CPG write in a native VMID, distinct from the CPF; noted, not chased here.

## 0.0.677: the kernel GFX queue's doorbell in Linux's units (staged, not installed)

**Change** (overlay `research/builds/macos-20261117/kernel-677/PATCHES/kernel-0.0.677-over-0.0.676.diff`, sha256 `3349a9c26bf2f6c25a58c332597aec5e337e8f6ea39e7aec35124187492b686f`):
- **`amd/cp_doorbell_pure.h` (new):** `kgq_index` = gfx_ring0 << 1 (Linux), the window encoding, and a where/alignment check.
- **`amd/cp_v12_0.cpp` `cp_init_full` (:2531-2534):** `cp.doorbell_index = kgq_index(gfx_ring0, mode)`. The index, byte offset, window and alignment are logged.
- **`cp_set_doorbell_range` (:2127):** the GFX window comes from `gfx_ring0` itself, as in Linux. The register value is unchanged in both modes.
- **`cp_doorbell_describe` (:2210)** and **`Navi48Bringup.cpp:7176`:** publish ioreg **`Navi48,GfxDoorbell`**.
- **Consumers:** every user of the queue's doorbell already reads `cp.doorbell_index`, so all of them move together to 0x116 / byte 0x458: the MQD, MES ADD_QUEUE / RESET / REMOVE, the native ring doorbell, `cp_kick_doorbell` and the G1 / Apple-route helpers.
- **Kill switch:** boot-arg **`navi48-gfxdb=0`** restores the pre-0.0.677 index exactly.
- **Unchanged:** the MES ring and the compute queue doorbells.

**Build and payload:**

| Item | Value |
|---|---|
| Candidate | `research/builds/macos-20261117/kernel-677/kernel-contexts-v13`, base 0.0.676 verified, 8/8 CPU tests pass |
| Kext sha256 | **`1015bef0355eda9a22134f5101fe3f64fa8b5ae4f8f2b7e1bbebdba83f530fe5`** |
| Payload v13 | `research/builds/macos-20261117/kernel-677/kernel-payload-v13`, 126 files |
| Config sha256 | `c42dc0d3236af1caeb8b5d2a90c60a0c3b534c5cd99e539cc90ddbb6392d3d23`; the only change is `Kernel/Add/7/BundlePath` |
| Recovery | `RECOVERY/pre-contexts-677-config.plist` is the 0.0.676 configuration |
| ocvalidate | 1.0.8: no issues |
| Guard | Derived from the live 0.0.676 guard (`9db4950a…`) to `e97b4c89b9093d96021ff26117769816bf965f86fe84af72603fa35432e43eea`; exactly 5 lines change, each 676 → 677 |

**Tests**, all pass:
- `run-host-tests.sh` → `host-tests-677.stdout`:
  - gfx_doorbell677: 26 checks, on HEAD and on the overlay. It checks the Linux formulas and the Navi10 map values parsed from the Linux sources; that the old index lands in the MEC window at an odd dword; and source pins on every consumer.
  - fan_od676 141, disparb 140, ufmon 37, uclkpin 88, cg675, safety.
  - native_s2a/s2d: same as clean HEAD.
- Tool tests: `test-refresh60i-payload.py` (new, 21 tests), `g`, `h`, `test-production-contexts-build.py`, `test-production-kernel-guard.py`, `test-apply-refresh-guard.py`.

**Risk and acceptance:**
- **Risk.** If the GFX CP does not take a doorbell at 0x458, the boot ring test fails at PM4Test. The ladder then stops, the desktop has no acceleration, and recovery is a reboot with `navi48-gfxdb=0`. This is the configuration Linux runs on this card.
- **Acceptance, read-only, after the boot:**
  - `ioreg -l -w0 | grep GfxDoorbell` shows "index 278 (byte 0x458) … inside the GFX window, qword-aligned".
  - List A shows CP_RB_DOORBELL_CONTROL OFFSET 0x116 with HIT set.
  - List B with the display off shows CPF_BUSY far below 99 %.
  - `navi48test metrics` shows GFX activity well below 100 % with the display off.
- **If CPF stays busy**, the next candidate is the MES KIQ pipe: activate pipe 1 with its queue and set_hw_resources as `mes_v12_0_kiq_hw_init` does, or drop the RLC_CP_SCHEDULERS enable.

---

## Reassessment 2026-11-23: the doorbell is not the cause; 0.0.677 rebuilt as an observation build

### What the live lists showed (orchestrator, 2026-11-17, display on, 0.0.676)

**List A:**
- The doorbell is received at the old offset: CP_RB_DOORBELL_CONTROL = 0xc000022c, i.e. offset 0x8B, EN, **HIT=1**.
- The scheduler state: CP_MES_CNTL = 0x04000000 (MES pipe 0 only) and RLC_CP_SCHEDULERS = 0x30e8 (scheduler0 = 0xe8, me3/pipe1/queue0 enabled; scheduler1 = 0x30, disabled).
- CP_ME_CNTL = 0x0100a000: PFP/ME pipe 1 disabled, CE halted.
- All four MEC pipes are active.

**List B:**
- CP_CPF_STATUS = **0x88000001** in 100 % of samples: CPF_BUSY + **CPF_CMP_BUSY** + **POST_WPTR_GFX_BUSY**.
- CP_CPF_BUSY_STAT = 0 and CP_CPF_BUSY_STAT2 = 0 in 100 %.
- GRBM_STATUS2 = 0x14100000: CPF_BUSY, RLC_BUSY, EA_LINK_BUSY.
- CP_GFX_HQD_RPTR = 0 and CP_GFX_HQD_WPTR = 0x1bb290, both constant.

### (1) Is the 0.0.677 doorbell change still justified?

No, not as a fix.
- HIT=1 shows that the GFX CP takes the doorbell at dword 0x8B. The window filter does not drop it, so the doorbell is not the busy source. My 2026-11-17 conclusion on this point was wrong.
- The Linux index stays in 0.0.677 only as an **opt-in A/B** (`navi48-gfxdb=1`). The **default is the 0.0.676 index**.

### (2) The remaining candidates

**CPF_CMP_BUSY and the MES KIQ slot.** "CPF busy on behalf of compute" is set permanently while every CPC/MEC bit and every HQD/MES busy-stat bit is clear. That suggests a request pending toward a compute-side consumer that never takes it.
- The only compute-side difference from Linux that I found is the KIQ:
  - Linux runs MES pipe 1 as the KIQ (`mes_v12_0_kiq_hw_init`): CP_MES_CNTL 0x0C000000, its queue, and SET_HW_RESOURCES on pipe 1.
  - Linux and we both write RLC_CP_SCHEDULERS = me3/pipe1/q0 | 0x80.
  - We never start pipe 1, so the scheduler queue that the RLC/CP are told about does not exist.
- Confidence: medium, the best candidate so far. It is not proven.

**The kernel compute queue.** This is the other compute-side object: the KCQ on MEC pipe 0, mapped through MES and idle. `navi48-kcq=0` (existing boot-arg) removes it for an A/B test.

**POST_WPTR_GFX_BUSY.** This is the CPF's write-pointer posting toward the GFX queue. It may be the same stuck pipeline: the RS64 GFX ME posts its wptr through the CPF, and the CPF stays busy as a whole.

**CP_GFX_HQD_RPTR = 0 and a constant WPTR.** This is very likely not a stall. Over the same period the desktop kept running and the kernel's own fences retired. On RS64 GFX12 the HQD registers are the queue's save/restore image. While the queue is resident, the live read pointer is the write-back word at RPTR_ADDR, which the kext's fence path uses. CP_RB0_RPTR (0x21C0) is the legacy view. This is low-confidence; the boot census below settles it.

**Linux with GFXOFF disabled would be the reference.** No such measurement exists. The Linux oracle reaches GFXOFF at idle, which requires an idle CP, so on Linux the CPF does idle.

### (3) Discriminators that need no live reads of banked registers

0.0.677 now logs the evidence at boot itself.

**Boot-time busy marks** (default on; `navi48-cpmark=0` turns them off):
- They run after every bring-up stage from CPInit (CPInit, MESInit, GFXInit, SDMAInit, PM4Test, ComputeDispatch) and once at the end of runStages, after clock gating and the fan step.
- Each mark takes 16 samples, 50 µs apart, of **unbanked status registers only**: GRBM_STATUS/2, CP_STAT, CP_CPF_STATUS, CP_CPF_BUSY_STAT/2, CP_CPF_STALLED_STAT1, CP_CPC_STATUS, CP_MES_CNTL, RLC_CP_SCHEDULERS. No select and no write.
- It logs the first sample and per-bit counts: GUI_ACTIVE, CP_BUSY, CPF/CPC/CPG/RLC_BUSY, POST_WPTR_GFX_BUSY, HQD_BUSY, MES_HQD_BUSY, CPF_GFX_BUSY, CPF_CMP_BUSY, CPC_CPF_BUSY, MEC1_BUSY, MES_BUSY.
- The results are in ioreg **`Navi48,CpBusyMarks`** and in `navi48test log | grep cpmark`.
- The first stage whose mark shows CPF_CMP_BUSY 16/16 names the culprit:
  - MESInit → the MES / KIQ setup;
  - PM4Test → the KGQ or KCQ mapping;
  - only at end-of-runStages → clock gating or the fan step.

**Queue census** (opt-in, `navi48-cpcensus=1`):
- Runs once at boot, before any client.
- Reads the HQD registers of me0/p0/q0 (KGQ), me1/p0/q0–1 (KCQ slots), me3/p0/q0 (MES scheduler) and me3/p1/q0 (the KIQ slot), plus CP_MES_INSTR_PNTR and MSTATUS for the MES slots.
- It uses kernel GRBM_GFX_CNTL select writes, as the bring-up already does in `cp_dump_gfx_hqd` and `mes_queue_init`, and restores select 0.
- It never reads a *_HEADER_DUMP register.

**A/B boot-args, one per boot, defaults unchanged:**

| Boot-arg | Effect |
|---|---|
| `navi48-kiqsched=0` | Skips the RLC_CP_SCHEDULERS KIQ write |
| `navi48-kcq=0` | Existing: no kernel compute queue |
| `navi48-gfxdb=1` | Linux's GFX doorbell index |

Compare `Navi48,CpBusyMarks` and the SMU activity (`navi48test metrics`) across boots.

### The WindowServer crash of 2026-11-17

**The crash mechanism is a RADV error-path bug (high confidence).** It is in our mesa fork, `research/ext/mesa-darwin/src/amd/vulkan/radv_cmd_buffer.c:1380-1420`:
- `radv_create_cmd_buffer` calls `radv_create_cmd_stream`.
- On failure, it calls `radv_destroy_cmd_buffer` **before** `list_inithead(&cmd_buffer->msrtss_transients)`, before `accel_struct_buffers` is created, and before `vk_object_base_init` of the push sets.
- `radv_destroy_msrtss_transients` then walks a zeroed list head (`list_for_each_entry_safe`) and dereferences NULL: SIGSEGV in `radv_destroy_cmd_buffer`.
- `radv_create_cmd_stream` fails when `ws->cs_create` → `radv_amdgpu_cs_get_new_ib` cannot get an IB buffer object.

So **any** kernel refusal of a GTT/VRAM buffer object becomes a WindowServer crash. Refusals in `native_s1c.cpp` (BoCreate) include:
- `BoCreate refused (NoMemory)` for GTT wired pages;
- the shared VRAM budget;
- the visible-VRAM cap;
- the global GTT plus host-import cap;
- `NoResources`, when a session runs out of BO handles;
- `gpu_gate` (HUNG).

"Crashing at every login until reboot" points to a persistent kernel state, not to the reads themselves. Candidates:
- a HUNG latch;
- a session closed "LEAKED (HUNG)" whose memory stays held;
- a global pool exhausted by a leak.

**Fix for the bundle (not part of this kernel build):** initialise `msrtss_transients`, `ray_history`, `accel_struct_buffers` and the push-set bases before `radv_create_cmd_stream`, or make the destroy path tolerate them uninitialised.

**Could the `regs` reads have caused it?**
- `doRegRead` (`Navi48UserClient.cpp`) is a bare uncached RREG32 of a bounds-checked BAR5 dword. It takes no lock, so it cannot block WindowServer's paths, and it writes no select register.
- The only plausible hardware side effect is reading debug FIFOs: CP_ME/PFP/MEC/MES `*_HEADER_DUMP`, which hang-dump code reads to pop entries. It could also be reading MES-owned registers while MES runs.
- The 2026-11-12 loop read CP_ME/PFP_HEADER_DUMP about 100 times each with no effect. The 2026-11-17 list A added CP_MES_HEADER_DUMP and CP_MES_INSTR_PNTR.
- A GPU stall caused that way would show up as `native-s1c: HUNG:` / `stall:` lines.
- Conclusion: not excluded, not likely. The orchestrator's new rule (no live CP/HQD/MES/select reads) is right regardless, and 0.0.677 moves those reads to boot.

**Read-only check of that boot.** The unified log keeps kernel lines across reboots; no root is needed on an admin account:

```sh
/usr/bin/log show --start '2026-11-17 20:35:00' --end '2026-11-17 21:30:00' --style compact \
  --predicate '(process == "kernel" AND eventMessage CONTAINS "Navi48Bringup") OR (process == "WindowServer" AND (eventMessage CONTAINS "radv" OR eventMessage CONTAINS "n48"))' \
  | grep -E 'HUNG|stall|open refused|BoCreate refused|client closed|LEAKED|radv-darwin|ERROR_OUT_OF' | head -80
```

| Result | Meaning |
|---|---|
| `HUNG:` / `stall:` lines just before the crash | A GPU stall, possibly read-related; investigate further |
| `BoCreate refused` with a budget or cap reason | A leak, unrelated to the reads |

### 0.0.677 as rebuilt (staged, not installed)

The doorbell-only build of 2026-11-17 was never installed. It was replaced by this build.

**Overlay:** `research/builds/macos-20261117/kernel-677/PATCHES/kernel-0.0.677-over-0.0.676.diff`, sha256 `85943e2fbe677da7e2178a50a4a081385a3b77b20437bb30e35aa566054daca8`.

**New files:**
- `amd/cp_census_pure.h`: register tables checked against Linux offsets, BASE_IDX and bit positions; counting; switches.
- `amd/cp_census.cpp`: the marks, the census, and the registry text.

**Changed files** (HEAD-worktree line numbers):

| File | Change |
|---|---|
| `amd/amdgpu_init.cpp:914` | A mark after each stage from CPInit |
| `Navi48Bringup.cpp:7180-7184` | The end mark, the census and `Navi48,CpBusyMarks` |
| `amd/mes_v12_1.cpp:1552-1563` | `navi48-kiqsched=0` A/B |
| `amd/cp_doorbell_pure.h`, `amd/cp_v12_0.cpp` | The GFX doorbell index as an opt-in only (`navi48-gfxdb=1`); `Navi48,GfxDoorbell` |
| `amd/amdgpu_cp.h` | Declarations |
| `Info.plist` | 0.0.677 |

**Default behaviour:** exactly 0.0.676, plus boot-time unbanked status reads and two registry properties.

**Build and payload:**

| Item | Value |
|---|---|
| Kext sha256 | **`c0840881940cfc154a7cf82dbcb8599d853e6099ffd504d40150dbfeaf10ae1d`** |
| Candidate | `kernel-contexts-v13`; 0.0.676 base verified; 8/8 CPU tests pass |
| Payload v13 | `kernel-payload-v13`, 126 files, staged against the live guard `9db4950a…` (re-checked 2026-11-23; 0.0.676 is loaded) |
| Guard | `e97b4c89b9093d96021ff26117769816bf965f86fe84af72603fa35432e43eea`; 5 lines, each 676 → 677 |
| Config sha256 | `c42dc0d3236af1caeb8b5d2a90c60a0c3b534c5cd99e539cc90ddbb6392d3d23`; only the BundlePath changes |
| ocvalidate | 1.0.8: no issues |

**Tests** (all pass):
- `host-tests-677.stdout`:
  - cp_census677: 126 checks, on HEAD and on the overlay. Offsets, BASE_IDX and bits are parsed from Linux `gc_12_0_0_offset.h` / `sh_mask.h`. It checks the live sample decode, that there is no register write before the opt-in census, and that select 0 is restored.
  - gfx_doorbell677: 26 checks.
  - fan_od676, disparb, ufmon, uclkpin, cg675, safety.
  - native_s2a/s2d: same as clean HEAD.
- Tool tests: `test-refresh60i-payload.py` (21), g, h, `test-production-contexts-build.py`, the guard test, and the apply-refresh-guard test.

**Risk.** The marks are 16 × 10 MMIO reads per stage, about 1 ms, at boot only. The census and the A/B switches are opt-in. Recovery: `RECOVERY/pre-contexts-677-config.plist`, the 0.0.676 configuration.
