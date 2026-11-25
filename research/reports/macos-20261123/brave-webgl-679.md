# Brave WebGL Aquarium: GPU process exits, then Brave disables WebGL (kernel 0.0.679, bundle 38)

Read-only investigation. Evidence was gathered on 2026-11-23 (20:39 to 20:44, live boot of 0.0.679) and finished on
2026-11-25. **The machine was rebooted before the report was finished.** At 2026-11-25 15:12 the live state is
Navi48Bringup **0.0.681**, RDNA4FB 0.0.9, accelprobe 0.0.7, `Navi48,Dpm` = PMFW DPM applied, `Navi48,Ready` = 1, and the
installed Metal bundle is **39** (installed 2026-11-23 21:32, uncommitted working-tree change). The kernel ring of
the 0.0.679 boot (`navi48test log`) is lost, so the kernel side is argued from indirect evidence only (section 4).

## 1. Verdict

**Cause (confidence: high for the category, medium-high for the exact call):** this is case **(b)/(d)**. It is a
Metal-bundle feature gap for **cube textures**, which Chromium then handles by dropping the GPU process. It is not a
kernel GPU hang, and not DPM or higher clocks.

- With **bundle 38**, `n48td_map` refuses every cube texture whose usage includes `MTLTextureUsageShaderWrite`
  (`git show HEAD:cobalt64/tools/native/navi48metal/n48_texdesc.h`, line 63: "ShaderWrite on a cube texture is not
  supported"). `newTexture` returns nil with error 31 (`Navi48Device.m:2717-2719`). ANGLE requests ShaderWrite on cube
  textures, including its 1x1 cube placeholder; the bundle-39 comment in `n48_texdesc.h` records this. The WebGL
  Aquarium uses cube maps for reflections and the background. The refusal has been in the code since the Cobalt64
  import (`b8fdec0`, 2026-10-12). It is not a regression of 0.0.678/0.0.679. Earlier "WebGL works" reports were very
  likely made on pages without cube maps. On 2026-10-29, `brave_postboot_observation_20261029.md` already recorded
  "WebGL disabled and GPU disabled after crash".
- **Bundle 39** (installed 21:32, uncommitted) accepts such cube textures and drops only the storage use. The
  Aquarium then gets further, and fails at the **next** gap. ANGLE asks for a cube view and per-face 2D views, and
  `newTextureView` refuses them: `Navi48Device.m:3329` "views of cube / 2D-array textures are not implemented", and
  `:3292` "only a 2D view of level 0 slice 0 exists ... nil". The GPU process exits about 3 s later (log in section 3).
- Chromium treats nil Metal objects as a lost context. A lost WebGL context on ANGLE/Metal makes the GPU process
  exit. The exit is clean: `CoreAnalytics ... Entering exit handler`, and no crashpad dump or `.ips` is written for
  the GPU helper. The browser counts each such exit as a GPU crash. After the third, it disables hardware WebGL.
  This matches the white page and then "WebGL is not supported". This last link (ANGLE turning nil into a lost
  context, and Chromium exiting on that loss) comes from how Chromium behaves. It is not shown by our logs.

**Fix:** implement Metal texture views of cube (and 2D-array) textures in the bundle: a cube view, a 2D view of one
face (slice), and level subranges. RADV supports all of these. The `VkImage` is already created
`CUBE_COMPATIBLE` with 6 layers (`n48_texdesc.h`, cube branch), so a `VkImageView` with `VIEW_TYPE_2D` /
`baseArrayLayer = face` / `baseMipLevel` is legal. Then keep bundle 39's cube ShaderWrite relaxation, commit it, and
re-test with `tools/baremetal/navi44-gpu-diagnostics/brave-probe.py` (isolated profile, counts
`webglcontextlost`).

## 2. Timeline, 2026-11-23 (0.0.679, bundle 38)

Brave 157.1.99.55 has been unchanged since Nov 5. The GPU process is `Brave Browser Helper (Aperitif) --type=gpu-process`.

| Time | Event |
|---|---|
| 20:36:56 | Browser 2404 starts. GPU process **2410**. |
| 20:37:03-04 | 2410 compiles its first MSL (UI). |
| 20:37:21.106-22.036 | 2410 compiles about 25 MSL libraries and specialisations (Aquarium) through `MTLCompilerService`. All succeed. |
| **20:37:22.194** | 2410 is gone, about **160 ms** after its last compile. launchd: `pid/2410 shutting down`, its MTLCompilerService is SIGKILLed. |
| 20:37:22.227 | GPU process **2585** starts. It compiles 2 libraries at 20:37:38.209/.359 (page reload). |
| **~20:37:38.5** | 2585 is gone, about **150 ms** after its compile. GPU process **2674** starts with `--gpu-recent-crash-count=2`. |
| 20:42 | The user restarts Brave (browser 12360). GPU process 21102 starts at 20:42:54 with `--gpu-recent-crash-count=1`. |
| 20:55:51.24 | 21102's last activity is a shader compile, then it is gone. Same pattern. |

No crashpad dump (`~/Library/Application Support/BraveSoftware/Brave-Browser/Crashpad/{new,pending,completed}`; the
newest is from 19:48) and no `.ips` for a Brave helper. The only Brave `.ips` (21:03:50, `Brave Browser`, SIGABRT in
`HIServices _RegisterApplication`) and `chrome_crashpad_handler` (21:03:45) are start-up aborts while
WindowServer was unavailable. They are unrelated. So the GPU process **exited on purpose**: it did not crash.

**Logging blind spot (0.0.679 boot):** the GPU processes 2410/2585/2674 logged only activity entries (`A`: "Metal
Compiling Shader", TCC). They logged **no** `Navi48Metal:` line and no default-level message at all. Still, ioreg
showed that 2674 held `IOAccelDevice2` and `IOAccelNavi48NativeClient`, so it ran on the bundle and RADV (it was
admitted). In the 21:36 and 21:45 runs (bundle 39), the same helper did log `Navi48Metal:` lines. I did not find out
why the 20:37 messages are missing. For the 20:37 crashes, the exact refusing call is therefore inferred from the
bundle-38 code and the bundle-39 log. It was not observed directly.

## 3. Bundle 39 run (2026-11-23 21:45, GPU process 5795): the next blocker, observed

```
21:45:56.405 APP probe: the kernel admitted this process ... Brave Browser Helper (Aperitif)
21:45:57.125 inproc: selected writable temporary shader cache .../T/TemporaryItems/com.navi48.xlate/...
21:45:58.693 inproc OK fragment 'main0' ...: translated in 8 ms        (translator works in the sandbox)
21:46:02-03  blit generateMipmapsForTexture ... (textures load)
21:46:03.232 newTextureView: refused: views of cube / 2D-array textures are not implemented
21:46:03.232 newTextureView: type 2 levels 0+1 slices 1+1 .. 5+1: only a 2D view of level 0 slice 0 exists ...; nil
21:46:03.238 (same again for a second cube map)
21:46:05.033 vkQueueSubmit = 0 / fence wait done = 0     (GPU work completes normally)
21:46:06.100 CoreAnalytics: Entering exit handler            (GPU process exits)
```

In the 21:36 run (GPU process 4062), the cube texture was created and logged "cube texture created without
ShaderWrite: storage usage dropped". Then the process exited at 21:36:50.9. Translation, admission, submission and
fences all work. The only refusals are the texture views.

## 4. What it is not

- **(a) Kernel GPU hang or recovery, and DPM: no evidence, and evidence against.**
  - The GPU process dies 150-160 ms after shader compilation. A kernel hang needs **2 s** without retired-seqno
    progress before anyone is blamed: `native_s1c_pure.h:296` `kHangNs = 2 s`, `:307 hang_expired`, the G2 stall
    path `native_s1c.cpp:338-379`. So a kernel stall cannot explain a 160 ms exit.
  - System-wide on 20:30-20:44: no `HUNG`, `DEVICE_LOST`, `vkQueueSubmit != 0` or `TIMEOUT` in any process.
    WindowServer kept presenting (`scanout: ... gpu_fail 0`). `Navi48,Ready` stayed 1. The b39 log shows fences
    completing normally right before the exit.
  - The kernel `native-s1c` / `Navi48Bringup:` IOLog lines do not reach the unified log on this boot (0 lines after
    the kext loads). A per-session G2 recovery therefore cannot be ruled out from the unified log alone. But the
    timing and the clean bundle-39 trace make it very unlikely.
  - Also new in 0.0.679: the GFX doorbell index (`a65829a`). Same argument: nothing waited long enough for a missed
    doorbell to matter.
- **(c) Admission or resource refusal: no.** "APP probe: the kernel admitted this process". The VRAM budget lines
  show no pressure. No BoCreate or open refusals (and no Ready=0).
- **Translator failure in the sandbox: no.** The GPU sandbox denies the Darwin user cache. The bundle falls back to
  `$TMPDIR/TemporaryItems` (`Navi48Device.m` `n48x_setup_locked`, about line 3665, also present in bundle 38), and
  `inproc OK` translations are logged.

**A/B for DPM, not needed for this bug.** If the orchestrator wants it anyway: boot with `navi48-dpm=0`, or with
`navi48-gfxmax=500` to reproduce the old clamp. Expected: **no change**. The Aquarium still loses the context at the
same point, with the same `newTextureView: refused` lines (with bundle 39), because the failure is in the bundle's
texture-view code and does not depend on time.

## 5. Commands for the orchestrator (root, read-only), at the next reproduction

- `navi48test log` right after the GPU process exits. Expect no `HUNG`, no `stall`, no `g2 recover`, and no `gcvm fault`
  for the Brave session. If one appears, this report is wrong on (a).
- Without root, run this while reproducing:
  `log stream --style compact --predicate 'process BEGINSWITH "Brave Browser Helper" AND eventMessage CONTAINS "Navi48Metal"'`
  and look for `newTextureView: refused` / `newTexture ... cube`.

## 6. User-side recovery (no settings were changed by this investigation)

- Brave keeps the "GPU crashed" count only for the life of the browser process. **Quit Brave completely (Cmd+Q)
  and start it again** to re-enable WebGL. Check with `brave://gpu`: "WebGL: Hardware accelerated" and no
  "disabled due to GPU process crash" line. `brave://gpu` also lists the problems log.
- Until the cube-view fix ships, the Aquarium and other pages with cube maps will disable WebGL again after 3 loads.
  Avoid them, or keep them in a separate test profile (`brave-probe.py` uses a temporary profile).
- Do not use `--ignore-gpu-blocklist` or `--disable-gpu-driver-bug-workarounds` for this. They do not address the
  cause.

## 7. Files

- `cobalt64/tools/native/navi48metal/n48_texdesc.h` (cube branch; bundle 38 line 63, bundle 39 lines 60-72)
- `cobalt64/tools/native/navi48metal/Navi48Device.m:2717` (newTexture refusal), `:3292`, `:3329` (texture-view
  refusals), `:4878-4947` (submit and fence path, no errors seen)
- `cobalt64/src/navi48-bringup/src/amd/native_s1c_pure.h:296-307`, `native_s1c.cpp:338-379` (hang threshold)
