# Why the desktop feels slow: measurements and a ranked plan

Date: 2026-11-12, 16:17–16:31 local, uptime 7–21 min. Scope: read-only. No sudo, no settings changed, no tracked files edited.

Stack at the time:
- Kernel kext `com.navi48.bringup` 0.0.673, `com.navi48.accelprobe` 0.0.7, RDNA4FB 0.0.9, `com.navi44.cppc` 0.0.1.
- Metal bundle 38 (`stage38-swz-v1`). 120 Hz (the `refresh-60` flag is absent).

Boot-args: `-v debug=0x100 keepsyms=1 kextlog=0xffff acpi_layer=0xffffffff acpi_level=0x2087 msgbuf=1048576 … navi48-interrupts=0 … n44-cppc=1 …`. `navi48-idle-clamp` is **not** set.

What the machine was doing during the measurements:
- Light desktop use: the Claude app streaming text, plus WhatsApp and Discord open. Brave was open at 16:17 and closed by 16:30.
- Every number below comes from a live source: `ps`, the ioreg properties, or the bundle's own `T1`/`scanout` lines in the unified log (`/usr/bin/log show`, with no root needed).

---

## 0. Summary

On the light desktop, the GPU path is the bottleneck. The CPU and RAM are not.

1. **The GPU runs at its minimum clock for the whole session.** At the end of the bring-up ladder the kext sends `SetSoftMaxByFreq(GFXCLK, PMFW minimum)`. Nothing ever lifts it. Earlier serial logs show the PMFW range as 500..3500 MHz, so the cap is 500 MHz.
2. **WindowServer's GPU work is about 75–80 % of every second at 120 Hz**, even on this light desktop. That leaves almost no headroom: any animation, blur or extra layer pushes frames past the 8.33 ms deadline.
   - About 350 command buffers per second, average submit-to-done 1.9–2.3 ms, with a tail of 11–14 ms (once 39 ms).
   - 2.7 % of presents are dropped and another 2.1 % are replaced before they latch.
3. **The kernel burns about 0.75 of a CPU core busy-spinning on fences.** In a 10 s window WindowServer used **7.25 s of system time against 0.18 s of user time**, spread over six threads.
   - The fence wait (`native_s1c.cpp:1878`, `cp_v12_0.cpp:1889-1903`) runs `IODelay(1)` in a loop for the first 5 ms.
   - The number matches the GPU busy time almost exactly: each completion thread spins for the whole length of its command buffer.
4. **Every frame crosses PCIe several times.**
   - WindowServer's IOSurfaces are LINEAR images bound to **system memory**.
   - Each frame does two full-screen composite passes, a final GPUPass and a full-screen 14.7 MB D-copy into the VRAM scanout slot, with two `ALL_COMMANDS` barriers.
   - This is the structural cost a faster GFX clock will not fully remove.
5. **The CPU is fine.**
   - CPPC autonomous mode works: 4.5–5.0 GHz effective under load (APERF/MPERF).
   - RAM reports 6000 MHz. There is no memory pressure (86 % free, 0 swap).
   - The NVMe is Gen4 x4 with TRIM.
   - Spotlight, translator and spvcache costs in steady state are negligible.

The top three items are a cheap clock experiment, a kernel wait fix, and the long-term architecture (VRAM-resident surfaces with no D-copy). They are ranked in §2.

---

## 1. Evidence

### 1.1 WindowServer: GPU-waiting, not CPU-bound

**Per-thread CPU** (`ps -M -p 623`, delta over 10 s at 16:28):

| Thread | System | User |
|---|---|---|
| 4 | 2.73 s | 0.02 s |
| 7 | 1.25 s | 0.02 s |
| 8 | 1.22 s | 0.02 s |
| 5 | 0.78 s | 0.01 s |
| 9 | 0.61 s | 0.01 s |
| 6 | 0.60 s | 0.01 s |
| main | 0.02 s | 0.04 s |
| **Total** | **7.25 s** | **0.18 s** |

That is 74 % of one core, 97 % of it in the kernel.

**Cumulative since boot:** 11:27 of CPU in about 18 min of uptime. Threads 5–10 each have about 1 min of system time and about 1 s of user time.

**Interpretation:** WindowServer's own code (user time) is cheap. The system time sits in the threads that block on fences. The kext fence wait spins with `IODelay(1)` for up to 5 ms before it falls back to `IOSleep(1)` (`cobalt64/src/navi48-bringup/src/amd/native_s1c.cpp:1859-1878`, the same pattern at `:383,:405,:498,:554`; `cp_v12_0.cpp:1889-1903`). The winsys slices waits at 20 ms (`research/ext/mesa-darwin/src/amd/common/darwin/ac_darwin_sync.c:28`). With command buffers of about 2 ms, almost the whole wait is spent spinning.

**Confirmation (root):** `spindump`/`sample` in §4 would show the stacks inside `n1c_wait` / `IODelay`.

### 1.2 Frame timing: bundle T1 counters (WindowServer, 10 s windows, 16:27:34–16:29:54, 15 windows)

Histogram buckets are <0.1, <0.4, <1.6, <6.4, <25.6, <102 ms.

| Metric | Typical window |
|---|---|
| command buffers / 10 s | 3290–3640 (about 350/s) |
| `cb_gpu` (submit→done) avg / max | 1.9–2.36 ms / 11–15 ms (one 39 ms) |
| `cb_gpu` histogram | about 150 / 950 / 120 / **2200** / 60–78 / 0–2 |
| `completion_wake` avg | 0.09–0.17 ms (wake latency is good, because of the spin) |
| `frame_gap` histogram | about 900 / 200 / 1020 / 380 / **≈1170 (6.4–25.6 ms)** |
| `pipelines gfx/comp` | 0 / 0. No shader compilation in steady state. |
| `qlock_wait` | ≤ 1.5 ms max, avg 1 µs (no lock contention) |

**Scanout**, 16:30:11:
- 1199 final-GPUPass frames in 10 s, so about **120 fps** are produced.
- 2438 render-composite command buffers, so **2 full-screen composite passes per frame**. Draws "full 11382 partial 52130", and avg partial area is 0 %: every pass is full-screen.
- Cumulative: presents 84376, latched 82593, **replaced 1783**, **drops 2273**, 0 refused, 0 GPU failures, `vupdates 0`.

**Reading.** About 3 command buffers per displayed frame: two composites and a final pass with the D-copy appended. Their GPU times add up to about 0.75–0.8 s per second.

Caveats:
- This is an upper bound. Submit→done includes time queued behind the previous command buffer on the single queue.
- It still shows a GPU that is **busy most of every 8.33 ms frame on a light desktop**, with a measurable drop and replace rate (about 4.8 % of presents not shown as planned). That rate shows up as micro-stutter during animations.

### 1.3 GFX clock: clamped to the PMFW minimum

**Code path:**
- `amd/amdgpu_init.cpp:917-930` calls `smu_set_power_state(Low)` at the end of `bringup_to`.
- On Navi 44, `Low` sets `SetSoftMaxByFreq(GFXCLK, GetMinDpmFreq)` (`amd/smu_v14_0.cpp:897-913`).
- The only other callers are the failure path and the user client (`navi48test power N`, `Navi48UserClient.cpp:505-520`).
- No Metal, accel or session path lifts it, and no `SetWorkloadMask` is ever sent.
- `ctx.idleClamp` defaults to 1 (`Navi48Bringup.cpp:6950-6952`), and the boot-args do not override it.

**Logged range:** "set_power_state: PMFW GFXCLK range 500..3500 MHz; low cap 500 MHz" (`research/hw_dump/p2_boot40/serial_p2_boot40_prearm.log`, `p0_stage17_metal_boot18_serial.log`). The orchestrator's "gfx stays at 1000 MHz in metrics" is consistent with a clamped clock, either PMFW rounding or the IF 0x2E/0x33 metrics decode caveat (`research/reports/smu_metrics_if33_audit.md`).

**History:** the clamp was added when an unclamped, ungated GFX core sat at 304 W during early bring-up (comment at `amdgpu_init.cpp:917-923`). That was before GFXOFF, deep-sleep and the full SMU feature mask were running; the mask now equals Linux's (memclk report §1.1). Whether "auto" still idles hot is **unmeasured**. That is the A/B in §4.

**UCLK** is pinned at the **max** (1258 MHz) by the 0.0.673 underflow fallback (`Navi48,UclkPin`). That helps throughput and costs only idle power, so memory clock is not a performance limiter right now.

### 1.4 Memory placement and the per-frame copy

From the bundle code audit (`cobalt64/tools/native/navi48metal/Navi48Device.m`):

- **IOSurface textures** are host-pointer imports of the surface's system memory, bound to a LINEAR VkImage (NM:2966-3017).
  - The alternative path (b) keeps an optimal device-local copy, uploaded on first touch and written back in full at the end of every command buffer (NM:3018-3044, 4974-4983).
  - Either way WindowServer renders and samples over PCIe, linear, uncompressed.
- **D-copy:** `n48Finish` appends `full_barrier + vkCmdCopyBuffer(pitch*height) + full_barrier` (NM:5274-5300, 1842-1846, barriers NM:5493-5496).
  - That is 14.7 MB read from system memory and written to a visible-VRAM slot, on the single gfx queue, every frame.
  - The flip waits for the fence of the whole command buffer.
  - Damage mode exists but is off (`/private/tmp/n48m-damage`, NM:1215).
- **The kernel CPU-copy present** (`native_disp_flow.h:302-355`) is **not active**. It returns `kPfScanOwned` while the bundle owns scanout. Pipestat shows "bytes copied / frames copied 0 / 0". (One sub-audit flagged it as the main cost; the code and counters show otherwise.)
- **PCIe:** root port GPP0 and the GPU switch upstream are **Gen4 x16** (`IOPCIExpressLinkStatus` 0x7104 / 0x1104). The internal switch-to-GPU hop is Gen5 x16. That is about 25 GB/s usable.
  - Per frame: 2 full-screen composites, the final pass and the D-copy each read and/or write about 14.7 MB of system memory.
  - At 120 Hz that is several GB/s of PCIe traffic plus latency-bound linear access. Inference: this is why `cb_gpu` stays around 2 ms per pass even at low GFX clock.
- **BAR:**
  - BAR0 is 256 MiB (`ReBAR,BAR0,CurrentMB=256`). Supported mask 0x7F00 means 256 MiB–16 GiB.
  - The visible pool is about 217 MiB (`VRAM-visible 217 MiB` in T1).
  - "Above 4G decoding" is evidently already ON: `BAR0,Phys = 0x880000000`.
  - The kext never resizes the BAR and refuses lengths above 1 GiB, because Tahoe's IOPCIFamily cannot size larger (`amd/rebar_pure.h`, `Navi48Bringup.cpp:173`).
- **System RAM:** 32 GB, 86 % free, compressor 0, swap 0, pageouts 0. No pressure.

### 1.5 CPU (Navi44CPPC)

**Request and capability:**
- `CPPC,State = autonomous-balanced-verified`, EPP 128.
- Per-core request: max = highest_perf (166–196, the preferred-core ranking), min 13, desired 0 (autonomous).
- Capabilities: lowest 13, lowest nonlinear 93, nominal 117 (3.8 GHz).

**Effective clock** from a 5 s APERF/MPERF delta:
- Busy primary threads: 4.51–4.73 GHz.
- Lightly used SMT siblings: 4.77–4.97 GHz.
- Since boot: ×1.19–1.25 of 3.8 GHz, so about 4.5–4.75 GHz.

**Reading:** boost works. The 5.3 GHz single-core peak is reached only when other cores are in a deep C-state. Inference: XNU on AMD with no power-management kext idles in C1/HLT, which limits the top bin by about 5–8 %. That is not the cause of UI slowness.

The busy share of even threads (10–29 % C0 while `top` says about 95 % idle) is partly the WindowServer kernel spin (§1.1).

### 1.6 Everything else

- **Storage:**
  - macOS is on the Lexar EQ790 1 TB (NVMe, Gen4 x4, TRIM yes), on an APFS container with 45.8 GB free. NVMeFix 1.1.4 is loaded.
  - DiagnosticReports has `disk writes` resource reports: mds_stores 2.1 GB in 573 s at 14:59, Brave 2.1 GB/70 min, fileproviderd, cloudd and bird on 5–9 Nov. Also repeated `shutdown_stall` reports, which are not a runtime cost.
- **Spotlight:** enabled; mds_stores is at 0.3 % now. `/Volumes/Untitled` (Windows NTFS, FSKit, read-only) is mounted.
  - My own `find /` crawled it and drove UVFSService to about 7.5 min of CPU. That was the probe, not the system.
  - Spotlight or anything else crawling that volume would do the same.
- **Translator daemon** `/usr/local/navi48/pc-translate.sh`: a bash script polling every 0.5 s, about 0.3 s CPU per 10 s (3 % of a core). spvcache: 498 files, 3.7 MB. No new pipelines in steady state; new apps only take first-use fallbacks.
- **Bundle logging** is rate-limited on hot paths (`N48LOGR`). `T1` writes about 10 lines every 10 s per GPU process (about 20 processes load the bundle). That is negligible, but noisy.
- **Debug boot-args** (`-v`, `debug=0x100`, `kextlog=0xffff`, ACPI debug masks, 1 MB msgbuf) cost essentially nothing at runtime. `kextlog` only affects kext loading; the ACPI masks only matter with a debug AppleACPIPlatform.
- **UI settings:** Reduce Transparency is OFF (`com.apple.universalaccess reduceTransparency = 0`) and Reduce Motion is not set. Transparency means blur/material passes. Inference: these are likely the two full-screen composite passes per frame.
- **RAM speed:** `system_profiler` reports both DIMMs at **6000 MHz** (SMBIOS type 17), which suggests EXPO is on. The user should confirm in the BIOS (EXPO profile 1, FCLK 2000 MHz, UCLK=MCLK).

---

## 2. Ranked plan

Impact is on felt UI smoothness and latency; effort and risk are mine to estimate.

| # | Item | Evidence | Expected impact | Effort | Risk | Who |
|---|---|---|---|---|---|---|
| **1** | **Lift the GFXCLK clamp on the desktop.** Test now with `navi48test power 0`. Then make it permanent: in the kext, after the Metal nub publishes, switch the idle clamp to `Auto` (or default `navi48-idle-clamp=0`), and keep `Low` only for the failure path. | §1.3; the GPU is 75–80 % busy at 120 fps (§1.2) | **High.** Shader-bound GPU work scales with clock (500 → up to about 3000 MHz). The PCIe-bound part does not, so the realistic gain is perhaps 1.5–3× less GPU time per pass, with fewer drops and a smaller 11–14 ms tail. To be measured with the T1 lines. | Trivial (runtime test); small (kext) | Idle power and heat, if PMFW does not gate GFX by itself. The 304 W case was measured before the full feature mask. **Watch `metrics` for 5 min**; revert with `power 1`. | We (kernel); the user runs the root test |
| **2** | **Stop busy-spinning in fence waits.** In `n1c_wait`/`cp_wait_fence`, spin at most about 20–50 µs, then block on an event (`IOLockSleepDeadline`/`assert_wait_deadline` with a 100–250 µs re-check), woken by EOP. The IH ring/MSI path exists and is default-on in code (`Navi48Bringup.cpp:7411-7419`); `navi48-interrupts=0` is a boot-arg choice. Same pattern at ring-space and admission waits. | §1.1: 7.25 s system / 10 s in WindowServer | **Medium-high.** Frees about 0.75 core continuously. Removes six spinning high-priority threads that compete with app threads and eat the CPU boost budget. Latency stays similar, or better with an interrupt wake. | Small (sleep granularity); medium (EOP interrupt wake) | Low with a timed fallback re-check | We (kernel) |
| **3** | **Interrupt-driven VUPDATE / flip-latch accounting** so slots free on time. Today a latch is noticed only at the next present, a status call or the 50 ms watchdog (`navi48_dcn.cpp:1650-1658,1988-2013`). `vupdates 0` in the scanout log. | §1.2: 2273 drops + 1783 replaced (about 4.8 %) | **Medium.** Fewer dropped and replaced frames, steadier pacing during animations. | Medium | Medium (an IRQ storm was guarded before; keep the classifier and budget) | We (kernel + bundle) |
| **4** | **Cheap D-copy fixes:** replace the two `ALL_COMMANDS→ALL_COMMANDS` barriers with transfer-scoped ones. Run the copy on the SDMA queue or as a separate submit so the next frame's composites are not serialized behind it. Try damage mode (`/private/tmp/n48m-damage`) as an A/B. | §1.4 | **Medium.** Removes 2 full GPU drains plus up to 14.7 MB of PCIe read per frame on static or partial updates. | Small–medium | Low–medium (damage mode is off by default for a reason; A/B first) | We (bundle) |
| **5** | **VRAM-resident WindowServer surfaces.** Keep GPU-only IOSurfaces (composite intermediates sid 157/158, CoreDisplay's 3 display surfaces) in tiled device-local memory. Write back to system memory only when a CPU lock or another process actually needs the bytes (IOSurface lock/seed). | §1.4; the 2 composites + final + copy are all sysmem/linear | **High (largest structural win).** Inference: most of the 2 ms/pass is PCIe-linear traffic. | High | Medium-high (coherency with CPU readers, cross-process sharing) | We (bundle + kext) |
| **6** | **Scan out directly from the final surface** (or render the final GPUPass into the scanout slot) once #5 lands. This removes the D-copy entirely. | §1.4 | Medium-high after #5 | Medium–high | Medium | We |
| **7** | **macOS: Reduce Transparency ON** (and optionally Reduce Motion). This is a stopgap until #1/#5. | §1.6; 2 full-screen composites per frame | **Medium, immediately** (inference: fewer blur/material passes) | Trivial | None (visual only) | User (System Settings › Accessibility › Display) |
| **8** | **Refresh rate.** If items 1–4 are not yet done, 60 Hz (flag `refresh-60`) halves GPU and PCIe load per second and frees most of the headroom. 120 Hz is the goal once the GPU path is fixed. | §1.2 | Medium (smoothness versus perceived latency trade-off) | Trivial (existing flag) | Low | User/us |
| **9** | **BIOS: confirm EXPO** (6000 MT/s, FCLK 2000). Do **not** set Resizable BAR to "max/auto 16 GB" while the kext and Tahoe cannot handle more than 1 GiB (`rebar_pure.h` refuses; the plan would fall back or fail). Above 4G is already on. A BAR of 1 GiB or less (OpenCore `ResizeGpuBars`/`ResizeAppleGpuBars`, value to be checked in the OC docs) helps only after #5 puts more CPU-visible VRAM to use. | §1.4, §1.6 | Low now (EXPO is likely already on; ReBAR has no consumer yet) | User, BIOS | ReBAR at 16 GB: **high** (boot or accel failure) | User |
| **10** | **CPU fine-tuning:** let the user pick EPP 0–64 instead of 128 (Navi44CPPC policy). Investigate deeper C-states (CC6) so the top single-core bin is reached. | §1.5 | Low (about 5 % burst) | Small | Low (EPP 0 raises idle power) | We (kext) |
| **11** | **Translator daemon:** replace the 0.5 s bash poll with launchd `WatchPaths`/kqueue. **Bundle:** stop `T1` logging in idle non-WindowServer processes. | §1.6 | Low (about 3 % of a core) | Small | Low | We |
| **12** | **Background noise:** exclude `/Volumes/Untitled` (NTFS via FSKit) from Spotlight, or do not auto-mount it. Keep an eye on the fileproviderd/cloudd/bird write storms (iCloud). | §1.6 | Low–situational | Trivial | None | User |
| **13** | **Clean boot-args** when stable: drop `kextlog=0xffff`, `acpi_layer/level`, `debug=0x100`, `-v`, the large msgbuf. | §1.6 | Negligible (hygiene, faster boot text) | Trivial | Low (lose diagnostics) | User/us |
| **14** | **Per-draw CPU costs:** descriptor sets (11.3 M allocated vs 3.4 M reused), `vkCreateFramebuffer` per encoder, and `classify cache hit/miss 1/25632` in impcache. | T1 drawopt/impcache | Low (WindowServer user time is only 0.18 s/10 s) | Small | Low | We (bundle) |

**Suggested order:**
1. Run the §4 root measurements and the `power 0` A/B. This takes minutes.
2. In the same kernel build: the #2 wait fix and the #1 clamp policy.
3. #4 (bundle barriers/SDMA) and #7 meanwhile.
4. #3.
5. #5 and #6 as the main project.

---

## 3. What would not help (now)

- **Enabling ReBAR in the BIOS at full size:** refused or broken by the 1 GiB IOPCIFamily limit, and nothing would use the extra window yet.
- **Turning `navi48-interrupts=1` on by itself:** per the code audit, no native fence or flip wait consumes interrupts today. It only helps together with #2 and #3.
- **More RAM tuning or swap tuning:** no pressure.
- **Shader cache work:** zero pipelines are created in steady state; hit rate is not a factor after warm-up.

---

## 4. Root-only commands for the user/orchestrator (exact)

```sh
T="/Library/Application Support/Navi44/accelerated-trial/navi48test"

# A. Confirm the clamp and the clock state this boot (read-only)
sudo dmesg | grep -E 'idle clamp|set_power_state|uclk-pin|GFXCLK' | tail -20
sudo "$T" metrics 30 > ~/metrics-clamped-$(date +%H%M%S).txt      # gfx/soc/mem/fclk MHz, busy %, W, temps, PCIe gen

# B. Where WindowServer's system time goes (read-only)
sudo spindump WindowServer 5 10 -file ~/ws-spindump-$(date +%H%M%S).txt    # expect n1c_wait / IODelay kernel frames
sudo powermetrics --samplers tasks,cpu_power -i 1000 -n 10 > ~/powermetrics-$(date +%H%M%S).txt   # cpu_power may be empty on AMD

# C. Scanout and flip state (read-only)
sudo "$T" accel pipestat
sudo "$T" accel refresh status

# D. GFX clamp A/B. CHANGES GPU STATE; the user decides. Keep the desktop under the same light load.
sudo "$T" power 0                     # auto: SetSoftMin(0) + SetSoftMax(0xFFFF) on GFXCLK
sudo "$T" metrics 60 > ~/metrics-auto-$(date +%H%M%S).txt
#   in parallel, as the user (no root):
/usr/bin/log show --last 2m --style compact --predicate 'process == "WindowServer" AND (eventMessage CONTAINS "T1 cb_gpu" OR eventMessage CONTAINS "T1 frame_gap")'
#   stop and revert if board W or hotspot rises abnormally at idle (for example > 60 W or > 80 C at idle):
sudo "$T" power 1                     # back to the PMFW-minimum clamp
```

**Success criteria for D:**
- `cb_gpu` average and the 6.4–25.6 ms bucket drop clearly.
- `drops` and `replaced` grow more slowly (`scanout: counters` line).
- Idle board power stays reasonable.

If all three hold, item #1 goes into the next kernel build.
