# Login stutter, Music hang, Discord voice crash: causes and fix plan (kernel 0.0.681, bundle 39)

Date: 2026-11-25. Scope: read-only. No sudo, no GPU state change, no install, no edits to tracked files.

Live stack: Navi48Bringup 0.0.681 (GFXCLK under PMFW DPM), Metal bundle 39, RDNA4FB 0.0.9. The machine booted at
15:11:09 and WindowServer (pid 596) started at 15:11:40. The login-time evidence below comes from this boot. The Discord
evidence comes from the only two Discord sessions on disk (2026-11-12 and 2026-11-23).

Sources:
- the unified log (`/usr/bin/log show`), including the bundle's `T1` timing lines;
- `/Library/Logs/DiagnosticReports/Discord_2026-11-23-194148_*.hang`, a system-wide stackshot (577 processes) taken 221 s after a boot;
- the Discord logs and crash-event files;
- `ioreg`, `ps`, and the source code.

The kernel's own `N1C_LOG`/IOLog lines do not reach the unified log on this boot, as the 11-23 Brave report already noted. So the kernel side
needs the root commands in section 5.

## 0. Summary (ranked)

| # | Symptom | Root cause | Where | Confidence |
|---|---|---|---|---|
| 1 | Login freezes of about 2 s | WindowServer's render thread blocks inside `vkCreateGraphicsPipelines` for a draw-time pipeline variant: **2133 ms** at 15:11:57.7 and **1872 ms** at 15:12:03.6. At the same time every other GPU client stops logging, then all of them resume in the same 100 ms. That points to a shared bottleneck below the bundle (the kernel's global locks, the single ring, or a 2 s wait cap). | bundle (synchronous variant build) and kernel (the shared stall) | The freeze is in our GPU stack on the compositor thread: **high**. The exact blocker: **medium** (needs the kernel log or a spindump). |
| 2 | General stutter and CPU load | Fence and ring waits busy-spin. WindowServer used 4:40 of CPU in 18 min, almost all system time. `ring_submit_production` retakes `gCliLock`+`gRingLock` every 1 µs for 5 ms while it waits for a VMID binding, with 13+ GPU processes at login on 8 VMIDs. | kernel | high (spin), medium (share of the freezes) |
| 3 | Lag when apps open | Every GPU process pays **0.3–1.3 s** for RADV `dlopen` (dyld binding) plus device open. 13 processes did this in 4 s at login. Music opened RADV and then submitted **zero** command buffers. | bundle / RADV build | high |
| 4 | Slow pipeline compiles | The live RADV is a `debugoptimized` build: asserts on (`__assert_rtn` imported), NIR validation after every pass, and ACO validate-IR/validate-opt on by default. | RADV build (bundle workaround prepared) | high (the fact), medium (its share) |
| 5 | Underflows after login | 7 display underflow events at 53–58 s of uptime, then the 2-stage fallback pinned UCLK at 1258 MHz. These may coincide with stall 2. | kernel/display | medium |
| 6 | Apple Music hangs for a long time | **Not the GPU.** Music's main thread waited **30.36 s** on an XPC call to `accountsd`. `accountsd` was itself blocked 30 s on `passd` (PassKit account observer), and `passd` was just being launched on demand and calling back into `accountsd`. This is a daemon deadlock that only the 30 s XPC timeout broke. Music did no GPU work at all. | macOS daemons | high (this boot) |
| 7 | Discord crashes when you join voice | **Not the GPU.** The renderer calls `exit(1)` (exit status 256) **9–30 ms after Krisp's "Creating voice activity detector"**, in 4 of 4 voice joins, including the one with noise suppression off. Turning Krisp *noise suppression* off does not turn off Krisp *VAD*. The Krisp module links Intel MKL statically, and macOS reports AVX-512 on the Zen 4 CPU. | Discord/Krisp + AMD CPU | medium-high |

## 1. Symptom 1: freezes and stutter after login

### 1.1 Two stalls of about 2 s on WindowServer's render thread (measured)

The bundle's `T1` lines for WindowServer pid 596 (10 s windows):

| Window end | `gfx_pipeline` max | `cb_encode` max | `frame_gap` max |
|---|---|---|---|
| 15:12:01.227 | **2133.291 ms** (n=84, every other create < 25.6 ms) | 2155.980 ms | 2180.984 ms |
| 15:12:11.194 | **1871.896 ms** | 1904.489 ms | 1910.440 ms |
| later windows | ≤ 2.6 ms | — | at most 800 ms (Music launch), otherwise < 350 ms |

Timeline of stall 1, from the log lines on WindowServer's main thread `bef`:
- `bef` is silent from **15:11:57.719** (its last `RDNA4FB vbl: interrupt state enabled`) to **15:11:59.880** "pipeline variant topology 1 cull 0 front 1 created".
- The pipeline is `N48RenderPipelineState 0x7febc10c5400`. Its base variant (triangle list) was built on thread `1174` at 15:11:57.750 in about 3 ms.
- The shaders are **tiny**: vertex `114381bc…` is 1244 B and fragment `845c4bc3…` is 648 B (bundle spvcache hits). So the 2 s is **not** compile work, and not the 814 KB uber-shader `810f499e…`.

Stall 2 at **15:12:03.588→15:12:05.457** has the same shape:
- the same two shaders, a different colour format (pf 110 against 94);
- the same draw-time variant, built in `-[N48RenderPipelineState pipelineForTopology:cull:front:ds:]` (`Navi48Device.m:4500-4510`);
- that function calls `n48Build` → `vkCreateGraphicsPipelines` **synchronously on the encoding thread, under the pipeline's `_lock`**.

Every GPU client stalls at the same time. Bundle log lines per process in 15:11:57.6–15:12:00.1:

| Process | 57.6–57.9 | 58.0–59.8 | 59.9–60.0 |
|---|---|---|---|
| iconservicesagent | 63/61/77/111 per 100 ms | **0** | 73/187 |
| WindowServer | 7 | **0** | 34 |
| Spotlight | — | **0** | 496+134 |
| Claude | — | **0** | 26 |

PhotosReliveWidget and SafeEjectGPUService were only opening RADV at 58.1–58.7. The system as a whole kept logging (1,000–5,000 lines per 100 ms), so the whole machine was not frozen. Only the GPU clients stopped, and they all resumed together at 59.9. That is the signature of one shared resource held for about 2 s. The 2 s matches the kernel's bounded waits: `kWaitCapNs` (ring space, `own_wait`, `ring_submit_production`) and `kHangNs = 2 s` (`native_s1c_pure.h:296`). Candidates, in order:
- (a) a wait that hit the 2 s cap and then took `stall_from_wait()` (kNoBlame or recovery);
- (b) `gCliLock` held for a long time by a path that loops (`ring_put_locked` spins up to 2 s for ring space while `gCliLock`+`gRingLock` are held: `native_s1c.cpp:463-475`, called from `ring_submit_production` at `:553`);
- (c) a GPU-side stall: one job running for about 2 s on the single shared gfx ring. Every context shares one ring, so all of them wait.

Why WindowServer waits inside pipeline creation: RADV allocates shader-arena BOs, so it calls into the kernel. That is an inference; the spindump in section 5 settles it. The kernel ring log (`navi48test log`) will show whether a "ring space … no room in 2 s", a G2 stall/recovery, or a timeout fired at 15:11:57.7–59.9 and 15:12:03.6–05.5.

Discriminator for the next login: the variants are now in WindowServer's T2 pipeline cache, saved at 15:12:11 with 227 pipelines.
- If the 2 s stalls come back anyway, the cause is kernel or GPU (shared), not compile time.
- If they disappear, an uncached compile was waiting on a shared kernel resource.

### 1.2 Busy-spin waits (kernel), still present on 0.0.681

- WindowServer: 4:40.6 of CPU in 18:15 of uptime, about 26 % of a core on average. The top threads have 28–38 s of system time each against under 1 s of user time (`ps -M`). That is the `IODelay(1)` spin of the first 5 ms in `own_wait`, `n1c_wait` and `ring_submit_production` (`native_s1c.cpp:400,422,515,571`). Same finding as the 11-12 plan, item 2; still unfixed.
- At login it is worse. `ring_submit_production` gets `kBusy` from `session_bind_locked` (decision `WaitForRetirement`/`BusyBinding` when more than 8 contexts compete for the 8 VMIDs). It then retakes **both global locks every microsecond** for 5 ms. Meanwhile every BoCreate, open, close and submit of every other process needs `gCliLock`.
- 13 GPU processes opened between 15:11:53 and 15:11:58, and about 20 native clients are live now (`ioreg`). This lock churn amplifies any long hold of `gCliLock`.

### 1.3 The RADV open burst at login (bundle/RADV build)

Time from `radv open: dlopen` to `application class … opened` (this boot):

| Process | ms | Process | ms |
|---|---|---|---|
| iconservicesagent | 888 | AccessibilityUIServer | 1308 |
| NotificationCenter | 1146 | dock.extra | 938 |
| ControlCenter | 938 | Spotlight | 907 |
| avconferenced | 869 | TextInputMenuAgent | 819 |
| Finder | 745 | others | 196–453 |

About 11 CPU-seconds go into the 4 s right after login. The 11-23 spindump shows where: DockHelper spent 400 ms in `n48_radv_open_once` → `dlopen` → `dyld4::JustInTimeLoader::applyFixups` → `resolveSymbol`, binding a 20 MB `libvulkan_radeon.dylib` that is not in the shared cache. Music paid 350 ms for RADV and then submitted **0** command buffers and created no pipeline: `T1 pool … fence submitted/completed=0/0`, `drawopt: draws 0` for its whole life.

### 1.4 Debug RADV build

- `research/ext/mesa-darwin/build-shim/meson-info`: `buildtype=debugoptimized`, `b_ndebug=if-release`, so NDEBUG is undefined.
- The live dylib imports `___assert_rtn`.
- With NDEBUG undefined, `nir_validate_shader` runs after every NIR pass unless `NIR_DEBUG=novalidate` (`nir_validate.c:2466`). `aco_ir.cpp:49-53` turns on `DEBUG_VALIDATE_IR | DEBUG_VALIDATE_OPT` unless `ACO_DEBUG=novalidate`.
- Every uncached pipeline costs several times what a release build costs, on the calling thread.
- Vermilion's RADV patch 0015 (nested loop unroll, fixed_frag variant 2.0 s → 1.05 s) shows the same class of cost on the large Core Animation shaders.

### 1.5 Display at login

`Navi48,DisplayUnderflow` = "events 7 (hubp 3 optc 7 …), last at uptime 57996 ms". `Navi48,UclkPin` = "stage 1 at 53380 ms, pin at 57996 ms … pinned 1258 MHz".
- `kern.boottime` has second resolution, so stage 1 is roughly at 15:12:02.4–03.4. That is next to or inside stall 2 (15:12:03.6–05.5).
- Whether the underflow handler (SMU messages, stutter off) holds a lock that the GPU clients need, or the stall starves the display, is open. The kernel log timestamps settle it.
- The Vermilion `wm144` guard turns stutter off before a watermark change. It is relevant here: our 0.0.673+ programs watermarks at DET resize, and the underflows come about 50 s later. Worth checking against our two-stage fallback (`smu_uclkpin_pure.h`). Not a cause of the 2 s freezes as far as the evidence shows.

### 1.6 What it is not (this boot)

- **Shader translation:** only 2 in-process translations since boot, both NotificationCenter, 16 ms and 6 ms. All the rest are spvcache hits: 460 files in the bundle cache, 506 in `/private/var/tmp/n48m-spv`. The `fixed_frag` uber-shader `810f499e…` (814,668 B of SPIR-V) was a cache hit 5 times.
- **NullMoth v2.9 `fixed_frag` folding** (Vermilion `5189257`) therefore does not explain this boot. It matters after any change of the spvcache key: a bundle or translator update causes a first boot that re-translates every variant on the caller's thread, which Vermilion measures at 1.6 s each. It also matters for RADV compile time of an 800 KB module. No equivalent turned up in `patches/0004-…-v3.0.patch` (no static-initializer struct folding), but the v3.0 tree is not local, so this is **unverified**. Port it before the `xlate-v29` dylib goes live, and measure with the `T1 gfx_pipeline` lines and the "translated in N ms" lines on the first boot after the swap.
- **Lock contention in the bundle queue:** `qlock_wait` max 25 ms in the first window, then ≤ 7.5 ms.
- **No-copy fallbacks:** 9 refused host imports (`-1000072003`, Core Animation `copy_image_to_texture`). One of 33 MB and one of 14.7 MB are copied once. They are one-shot uploads and not on the stall timestamps.
- **Memory pressure, Spotlight:** not seen in the stall windows.

## 2. Symptom 2: Apple Music hangs (this boot, 15:13:27)

- Music's main thread (`2d29`) opened `com.apple.accountsd.accountmanager` at **15:13:30.328**. The next main-thread line is **15:14:00.683**, "invalidated because the current process cancelled the connection". That is a 30.36 s synchronous XPC timeout.
- In `accountsd` (pid 717, thread `2e43`):
  1. "Daemon save called for account … client=(1901)" (Music), for iTunesStore.
  2. Then `PassbookAccountChangeObserver notifying pass library`.
  3. Then at 15:13:30.361 it connects to `com.apple.passd.library`.
  4. Its next line is at **15:14:00.674**.
- `passd` (pid 1952) was **spawned on demand at 15:13:30.369**. During startup it makes synchronous `accounts-with-type-sync` / `credential-for-account` calls back to `accountsd`.
- Result: a cross-daemon deadlock that the 30 s XPC timeout breaks. Several other `accountsd` clients (pids 883, 892, 960) cancel at 15:14:00.35 at the same moment.
- Music's GPU path did nothing: admitted, RADV opened in 350 ms on a non-main thread, 0 command buffers, 0 pipelines. No Navi48Metal refusal or wait was seen in Music.
- A second main-thread gap (15:14:03 → 15:14:18, 15 s) has no matching block in the log. It may be idle.

Fix: not in our driver. Workarounds to try:
- open Wallet-dependent services once (or wait about 1 min after login) before Music, so that `passd` is already running;
- or sign out and back in under Media & Purchases, so Music stops re-saving the iTunesStore account at launch.

Root: `sudo spindump Music 10 10 -file …` during a hang would confirm the stack (`xpc_connection_send_message_with_reply_sync`).

## 3. Symptom 3: Discord crashes when joining a voice channel

### 3.1 Evidence

Crash-event files (`module_data/crashlogs/*events.log`):

| When | Event |
|---|---|
| 2026-11-12 16:18:26 | `render-process-gone { reason: 'abnormal-exit', exitCode: 256 }` |
| 2026-11-12 16:18:29 | same |
| 2026-11-12 16:22:57 | same |
| 2026-11-12 16:23:00 | same |
| 2026-11-23 19:41:24 | same |
| 2026-11-12 16:22:51 | one `child-process-gone { type: 'GPU', reason: 'crashed', exitCode: 11 }` |

Correlation with `discord_krisp.log` and `discord-webrtc_0` / `discord-last-webrtc_0`:

| Renderer gone | Last Krisp/voice line before it |
|---|---|
| 11-12 16:18:26 | `KrispNCSetup` 26.005, **`KrispVADSetup` 26.034** |
| 11-12 16:18:29 | `KrispNCSetup` 29.292, **`KrispVADSetup` 29.320** |
| 11-12 16:23:00 | `noise_canceller` 00.555, **"Creating voice activity detector" 00.583** |
| 11-23 19:41:24 | `SetNoiseCancellation: 0` (24.852), **"Creating voice activity detector, rate 48000" / `KrispVADSetup` 24.863** → `Discord Helper (Renderer)[1686]` "CoreAnalytics: Entering exit handler" **24.872**, WindowServer "Process death" 24.882 |

Reading:
- The renderer exits through `exit()`: the atexit handlers ran, so it is not a signal, not `_exit`, and not a crash. No `.ips` and no Crashpad dump exist.
- Status 256 is exit code **1**.
- It happens 9 ms after the Krisp **voice activity detector** is created.
- The 11-23 run had **noise cancellation off** and still created Krisp's VAD. That is why turning Krisp noise suppression off did not help.
- Microphone capture had started 20 ms earlier (VoodooHDA input; one `HALC_ProxyObject::SetPropertyData … 0x21686F67 ('!hog')` error at 24.840, which is probably harmless).
- The renderer is not the GPU process and logged no Navi48Metal line.

`discord_krisp.node` (x86_64 slice):
- Intel MKL is statically linked: strings `libmkl_avx512.1.dylib`, `libmkl_avx2.1.dylib`, `libmkl_mc3.1.dylib`, `mkl_msg.cat`, `MKL_ENABLE_INSTRUCTIONS`, `MKL_CBWR`.
- Also onnxruntime and DNNL.
- It imports `_exit`, `_dlopen` and `_sysctlbyname`.

On this machine, `hw.optional.avx512f/cd/dq/bw/vl/ifma/vbmi = 1` and the vendor is AuthenticAMD. **Hypothesis:** MKL's CPU dispatch takes the AVX-512 path on Zen 4 under macOS. It then either fails to load its per-CPU kernel library, whose dylib is not shipped, or rejects the CPU, and MKL's fatal-error path calls `exit(1)`. The exact message goes to stderr, which nobody captures when Discord is started from the Dock. Confidence medium-high: the timing is 4 of 4, the exit is a clean exit(1), and MKL is present. The MKL mechanism itself is not observed yet.

Also seen, not the cause:
- The Discord *main* process hang (17.9 s, `.hang` at 19:41:25). The main thread sat in `libupdater` `semaphore_wait` (updater DB busy) during the 0.0.421 → 0.0.423 module update ("Database requested by query_current_version busy; waiting" from 19:41:25.093, the exact hang start). That is Discord-internal and follows the renderer exit.
- The 11-12 GPU-process SIGSEGV (bundle 38): a single event 5 s before a voice join. The GPU helper logged no Navi48Metal lines (the same blind spot as Brave on 11-23). It is unexplained but not the voice-join pattern.

### 3.2 Fix and test (user side, no root)

1. **Capture stderr once:** quit Discord, then run `/Applications/Discord.app/Contents/MacOS/Discord 2>&1 | tee ~/discord-stderr.txt` and join voice. Expect an "Intel MKL ERROR/FATAL" line just before the renderer dies.
2. **A/B the CPU dispatch:** run `MKL_ENABLE_INSTRUCTIONS=AVX2 /Applications/Discord.app/Contents/MacOS/Discord`. Child processes inherit the variable. If voice then works, AVX-512 dispatch is confirmed. A permanent workaround is `launchctl setenv MKL_ENABLE_INSTRUCTIONS AVX2` for the session (per-user, revertible with `launchctl unsetenv`; the user decides).
3. **Without env tricks:** in Discord's Voice & Video settings, set Noise Suppression to None *and* turn off the ML/advanced voice activity option. Or use Push to Talk, so Krisp's VAD is not created. Verify in `discord_krisp.log` that no `KrispVADSetup` line appears.
4. Masking AVX-512 at the CPUID or OpenCore level is **not recommended**: it is global, and leaf 7 cannot be masked with OpenCore's `Cpuid1` mask.

## 4. Fix plan

| # | Item | Component | Effort | Risk |
|---|---|---|---|---|
| F1 | **Find the 2 s holder.** Run the section 5 commands. Then, depending on the result: no ring-space spin under `gCliLock` (drop the locks before waiting, as `ring_submit_production` already does for `kBusy`); lower or log every 2 s wait-cap expiry (`N1C_LOG` with the caller name, process and seqnos); if a GPU job ran for 2 s, find its owner (the `gOwners` record) and report it in `Navi48,Telemetry`. | kernel | S–M after diagnosis | low–medium |
| F2 | **No pipeline build on the render thread.** (a) Make cull mode and front face dynamic state (core 1.3 / `VK_EXT_extended_dynamic_state`; RADV exposes it) and make topology dynamic within its class. Most variants then disappear, and with `dynamicPrimitiveTopologyUnrestricted` (EDS3) all of them do. (b) Until then, pre-build the likely variants (line list, strip, cull back) on the thread that created the pipeline state, and on a variant miss at draw time build it on a background queue, skipping or falling back for that frame on the base variant (as other Metal-on-Vulkan layers do). | bundle (`pipelineForTopology`, `n48Build`, `Navi48Device.m:4458-4510`) | M | medium (dynamic-state correctness; test with WindowServer and iconservicesagent) |
| F3 | **Sleep instead of spin.** In `own_wait`, `n1c_wait` and `ring_submit_production`, spin at most 20–50 µs, then `IOLockSleepDeadline`/`assert_wait_deadline` with 100–250 µs rechecks. In `ring_submit_production`, back off exponentially without retaking both global locks every 1 µs. Later, EOP interrupt wake (`navi48-interrupts`). | kernel | S (timed sleeps), M (interrupts) | low |
| F4 | **Release RADV build.** Rebuild with `-Dbuildtype=release -Db_ndebug=true` (keep the debug build as an opt-in). Until then, use patch `research/builds/macos-20261125/stability/0001-bundle-radv-debug-validation-off.patch`, which sets `NIR_DEBUG=novalidate` and `ACO_DEBUG=novalidate` before `vkCreateInstance` unless they are already set; `/private/tmp/n48m-validate` keeps the validation. It is checked with `git apply --check` against HEAD `b3dbc6f`. It touches only the RADV-open block, about line 610, and is separate from the texture-view work in progress. | RADV / bundle | XS (patch), S (rebuild) | low |
| F5 | **Cheaper RADV open.** (a) Open RADV lazily on the first command buffer, pipeline or IOSurface texture, not in `initWithAcceleratorPort`. Music, Finder and the widgets would then never pay it, nor hold a context. (b) Link `libvulkan_radeon.dylib` with `-dead_strip`, `-Wl,-fixup_chains` and two-level namespace, and check `-Wl,-bind_at_load` is not set, to cut the dyld bind time measured at 200–1300 ms. | bundle + RADV build | M (lazy), S (link flags) | medium (lazy open changes admission timing) |
| F6 | **Underflow at login.** Timestamp the underflow events against the stall (kernel log). Check the Vermilion `wm144` idea: stutter off around the watermark change, then re-enable after N quiet seconds, compared with our two-stage fallback. Add a release of the UCLK pin after a quiet period (today "10-min release off"). | kernel/display | S–M | medium (display) |
| F7 | **Translator v2.9 ports** (`fixed_frag` struct folding, `5189257`) before the v3.0 `xlate-v29` dylib goes live. Measure first-boot translation (`inproc … translated in`) and `T1 gfx_pipeline`. | translator | M | low–medium (a new spvcache key means one re-translation) |
| F8 | **Log hygiene.** Rate-limit `newTexture(iosurface): allocSize … rounded up` (12,224 lines from WindowServer in 7 min) and the per-pipeline lines. RDNA4FB logs `vbl: interrupt state enabled/disabled` twice per frame (36,035 lines in 15 min). Route the kernel `N1C_LOG` lines to `os_log`, so the next incident is visible without root. | bundle, RDNA4FB, kernel | S | none |
| F9 | Music: section 2 workaround. Discord: section 3.2. | user settings | trivial | none |

Suggested order:
1. Section 5 commands now; they cover the current boot.
2. F4 patch and F8 in bundle 40/41.
3. F3 + F1 in the next kernel.
4. F2.
5. F5, F6, F7.

## 5. Root-only, read-only commands for the orchestrator (exact)

```sh
T="/Library/Application Support/Navi44/accelerated-trial/navi48test"
TS=$(date +%H%M%S)

# A. Kernel ring log of THIS boot (booted 15:11:09): look at 15:11:57-15:12:08 (uptime ~48-60 s) for
#    "ring space ... no room in 2 s", stall/G2 recovery/timeout/poison, open/close bursts, underflow + UCLK pin times.
sudo "$T" log > ~/n48-klog-$TS.txt
sudo dmesg > ~/dmesg-$TS.txt
grep -n -i -E 'ring space|stall|g2 |recover|timeout|poison|hang|underflow|uclk|stutter|open refused|budget' ~/n48-klog-$TS.txt ~/dmesg-$TS.txt | head -200

# B. Scanout / flip state (read-only)
sudo "$T" accel pipestat

# C. At the NEXT login (start right after the desktop appears, or from ssh before logging in):
#    system-wide stacks for 30 s; look for WindowServer in vkCreateGraphicsPipelines / IOConnectCall*, and kernel frames in n1c_*.
sudo spindump -notarget 30 10 -file ~/login-spindump-$(date +%H%M%S).txt

# D. While Music hangs (optional, to confirm section 2)
sudo spindump Music 10 10 -file ~/music-spindump-$(date +%H%M%S).txt

# E. Busy-spin CPU picture (optional; cpu_power may be empty on AMD)
sudo powermetrics --samplers tasks -i 1000 -n 10 > ~/powermetrics-$(date +%H%M%S).txt
```

Without root, after the next login:

```sh
/usr/bin/log show --last 5m --style compact --predicate 'process == "WindowServer" AND eventMessage CONTAINS "T1 gfx_pipeline"'
```

A `max` of about 2000 ms again means the stall is not compile time (see the discriminator in section 1.1).

## 6. Files

- Bundle: `cobalt64/tools/native/navi48metal/Navi48Device.m`:
  - 4458-4510: `n48Build` and the synchronous `pipelineForTopology` under `_lock`;
  - 600-614: RADV env before `vkCreateInstance`;
  - 4902, 5249: no-copy refresh.
- Kernel: `cobalt64/src/navi48-bringup/src/amd/native_s1c.cpp`:
  - 383-425: `gpu_gate`/`own_wait`, 2 s cap and spin;
  - 449-476: `ring_put_locked`, a 2 s spin under `gRingLock`, called with `gCliLock` held;
  - 528-583: `ring_submit_production`, a 1 µs lock re-take loop;
  - 800-822: `session_bind_locked`;
  - 937-1067: `n1c_open` under `gCliLock`.
- `native_s1c_pure.h:38,296` (wait cap, `kHangNs`).
- RADV build: `research/ext/mesa-darwin/build-shim/meson-info`, `src/compiler/nir/nir_validate.c:2466`, `src/amd/compiler/aco_ir.cpp:44-53`.
- Evidence copies (scratch, not tracked): the bundle log since boot, the 11-23 Discord `.hang` stackshot, and log windows, in the session scratchpad.
- Patch: `research/builds/macos-20261125/stability/0001-bundle-radv-debug-validation-off.patch` (not built, not installed).
