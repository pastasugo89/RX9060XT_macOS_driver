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
