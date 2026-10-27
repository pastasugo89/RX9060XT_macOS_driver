# RX 9060 XT desktop acceleration versus Cobalt64

Date: 27 October 2026. Scope: compare the latest bare-metal trial on the RX 9060 XT with Cobalt64's published target, source recipe, local driver stack and available macOS crash evidence. This is not a claim that Cobalt64 has been tested on Navi 44.

## Main conclusion

The working premise “RX 9060 XT and RX 9070 XT are nearly the same, so only a few values should differ” is not supported by the maintainer's own support status. Cobalt64's validated launch card is Navi 48 / RX 9070 XT (`1002:7550`, `gfx1201`); it lists Navi 44 / RX 9060 XT (`1002:7590`, `gfx1200`) as **planned**, not supported. AMD's ROCm table assigns the 9070 XT 64 CUs and `gfx1201`, while the 9060 XT has 32 CUs and `gfx1200`. Both are RDNA 4, but they are different GPU targets and require target-specific bring-up and qualification.

This is the largest explanation for the gap. It does not prove that Navi 44 cannot be accelerated: the local project already has substantial Navi 44 adaptation. It does mean Cobalt64's Navi 48 success cannot be treated as a tested Navi 44 configuration or obtained by copying a short list of boot arguments.

The latest test got as far as **arming the display pipe**, then WindowServer aborted in Core Animation's OGL imaging path. The job correctly disarmed the pipe after the first WindowServer restart and created the kill switch. That is a userspace/display-stack failure after initialization, not a failure to discover the GPU or to execute the arm command.

## What the public Cobalt64 sources establish

- The repository says desktop composition was reached on one x86_64 test PC with RX 9070 XT and Tahoe 26.6.2. Its README says other GPU families need their own display and power-management bring-up. [Cobalt64 README](https://github.com/Almosst-DEV/Cobalt64)
- Its GPU checker marks RX 9070 XT / Navi 48 as the launch GPU and RX 9060 XT / Navi 44 as planned. [Cobalt64 GPU checker](https://cobalt64.com/check?gpu=rx-9070-xt)
- The installation preview requires an RX 9070 XT and says the Cobalt64 driver must be the only Radeon driver; it specifically tells users to disable a separate RDNA4FB kext. It also describes the workflow as preview/early access, not a released general-purpose installer. [Cobalt64 installation preview](https://cobalt64.com/install)
- Cobalt64's published implementation combines a bring-up kext, native display control, a Metal-on-Vulkan bundle, a Darwin RADV port and shader translation. The successful status is therefore for a complete, coordinated stack on its tested card, not an EFI plist alone. [Cobalt64 README](https://github.com/Almosst-DEV/Cobalt64)
- AMD's GPU table distinguishes Navi 48 `gfx1201` from Navi 44 `gfx1200`; the RX 9070 XT has 64 CUs and the RX 9060 XT has 32. [AMD ROCm GPU specifications](https://rocmdocs.amd.com/en/develop/reference/gpu-specs.html)

The RX 9060 XT and RX 9070 XT share RDNA 4, but the 9060 XT is not merely a lower-clocked 9070 XT. At the graphics-driver boundary it has a different GFX IP target, fewer CUs, a different PCI device ID and a separate display/power-management qualification requirement. A matching macOS build and the same broad architecture do not erase those differences.

## Current machine and last boot

Observed running stack:

| Component | Current observed version/state |
|---|---|
| macOS | 26.6.2, build 25G83 |
| RX 9060 XT | PCI `1002:7590` |
| `com.navi48.bringup` | 0.0.664 |
| `com.hackintosh.RDNA4FB` | 0.0.8, loaded and matching Navi 44 |
| `com.navi48.accelprobe` | 0.0.7, loaded after nub publication |
| `Navi48Metal` bundle | 0.1.1, bundle build 20 |

The current stack is split across the bring-up kext, a separate Navi 44 RDNA4FB framebuffer, the accelerator helper and the Metal bundle. That differs from the current Cobalt64 install guidance, which says to disable other Radeon framebuffer drivers. We cannot apply that instruction directly: this Navi 44 port presently relies on its RDNA4FB-derived framebuffer for the matched `IOFramebuffer`/scanout path, and the prior local `fbname 1` experiment caused a separate CoreDisplay/WindowServer abort. Removing RDNA4FB or enabling `fbname 1` without replacing and validating that path would be an unsafe extrapolation.

The corrected one-shot ran at 20:07 UTC:

1. `n48nub publish` and `pipeadopt` succeeded; `pipeagdc 1` published.
2. Before arming, pipe flags were `0x3b` (adopted, not armed). `pipearm 1` changed them to `0x3f` and read back `accel+0xccf = 1`.
3. The script restarted WindowServer PID 201; new PID 487 appeared. The user logged in about ten seconds later.
4. About two seconds after login, PID 487 aborted and PID 973 appeared. The fail-safe ran `pipearm 0`, read back `accel+0xccf = 0`, and created `/private/tmp/n48m-off`.
5. Two crash reports, PID 487 and PID 973, show `EXC_CRASH/SIGABRT` in the same `CA::OGL::Context::push_surface → CA::OGL::FlattenNode::retain_surface → CA::OGL::ImagingNode::render → CA::OGL::render_layers` path. The assertion text itself is not present in these reports.

Therefore the arm command worked, but the desktop did not become stable or visibly accelerated. The earlier initial `pipestat 0` was a pre-login/pre-submit sample; the job detected the crash before its first 15-second post-login sample, so this run does not establish successful display-pipe transactions or frames. Magenta output remains a shader/pipeline correctness issue, separate from the repeated Core Animation abort.

The translator was active before this test and produced 49 validated SPIR-V outputs from runtime AIR dumps. That proves the daemon captured and translated shader records; it does **not** prove every required WindowServer pipeline was present, that the GPU results were correct, or that translation fixes `push_surface`. The saved artifacts are in `research/hw_dump/macos_accelerated_trial_20261027/` with a SHA-256 manifest.

## Concrete differences from Cobalt64's single-display arm recipe

The local `cobalt64/tools/pc/arm-gpu-desktop.sh` performs `pipeadopt → pipeagdc 1 → fbname 1 → headless flag → pipearm 1 → pipereload → WindowServer restart`, starts a PID watcher and attempts `launchctl asuser 501 launchctl setenv CI_USE_MTL_DAG_FOR_CIKL_SRC 0`.

The failed one-shot matched the pipe adoption/AGDC/arm/restart sequence, but:

1. It omitted the CIKL launchd backstop. The installed bundle has a constructor that sets the variable when the Metal bundle loads, but its own source says this can be too late if Core Image uses a CIKL string kernel first. This is a credible, testable difference because the fault stack includes `CA::OGL::ImagingNode`; it is not yet proven to be the assertion's cause.
2. It did not run Cobalt64's watcher. Instead, it treated the first post-login WindowServer PID change as immediate failure, disarmed the pipe and set `n48m-off`. Cobalt's recipe removes the per-process headless/start markers on a later PID transition and leaves the pipe armed. Our fail-safe may therefore have prevented a second WindowServer process from getting the same one controlled opportunity Cobalt's recipe allows. This is a plausible recovery-path difference, not proof that another server will succeed.
3. It omitted `fbname 1` deliberately. The local Navi 44 history records that operation causing `CoreDisplay_CreateDisplayForCGXDisplay` to abort while looking for `AMDFramebuffer`; Cobalt64's Navi 48 behavior cannot override that local failure evidence.
4. The current NVRAM uses `navi48-interrupts=0`. Cobalt's usual configuration leaves interrupts enabled, but prior Navi 44 interrupt boots logged spontaneous GCVM VMID0 faults. The latest failure is a Core Animation assertion rather than a GPU hang, so changing interrupts now is not an evidence-based fix.

## Best-supported next boot candidate

The bounded candidate described below was staged and ran on the 21:46 login-transition attempt. Its one-shot plist is now consumed and absent from `/Library/LaunchDaemons`; it will not retry on the next boot. The current `/private/tmp/n48m-off` kill switch explains why the driver is disabled now. The installed script remains at `/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh`; its launchd job is not running.

I prepared a revised one-shot candidate for a **single bounded retry**:

- set `CI_USE_MTL_DAG_FOR_CIKL_SRC=0` in launchd before restarting WindowServer and attempt the uid-501 setting, matching Cobalt64's backstop;
- after the normal arm/restart, permit one additional WindowServer PID transition and clear the headless/start markers as Cobalt64's watcher does;
- keep the pipe armed for that one recovery opportunity; if WindowServer changes PID a second time, disarm and set the kill switch;
- if the previous boot's `/private/tmp/n48m-off` still exists, archive and clear it only after verifying it is a regular root:wheel, mode-0644, zero-byte file and after consuming the explicitly staged one-shot plist; otherwise fail closed;
- keep `fbname 1` and `navi48-interrupts=1` off because local Navi 44 evidence makes those changes unjustified.

This is the most defensible next experiment, not a known fix. It may allow the login-window/user-session transition to finish; it may still hit the same assertion because the driver target is Navi 44 and Cobalt64 does not yet list it as supported. A stable result must include a WindowServer that survives the bounded observation window, no magenta/missing GUI pipelines, and nonzero display submit/frame counters. The script passed `bash -n`; the plist passed `plutil -lint`; the installed script is byte-identical to the staged candidate. No GPU action or reboot has been run while staging this revision.

That candidate has since been consumed by the latest trial. There is no accelerated-trial plist staged for the next reboot; `/private/tmp/n48m-off` remains present, keeping acceleration disabled. Do not re-arm by simply restoring the same plist: the latest WindowServer abort needs a targeted code-path investigation first.

## References

- [Cobalt64 source and validated scope](https://github.com/Almosst-DEV/Cobalt64)
- [Cobalt64 supported-GPU roadmap](https://cobalt64.com/check?gpu=rx-9070-xt)
- [Cobalt64 installation preview and framebuffer conflict guidance](https://cobalt64.com/install)
- [AMD ROCm GPU specifications (`gfx1200` / `gfx1201`)](https://rocmdocs.amd.com/en/develop/reference/gpu-specs.html)
- Local recipe: `cobalt64/tools/pc/arm-gpu-desktop.sh`
- Local comparison: `research/reports/p2_vs_cobalt_recipe.md`
- Latest run and crash evidence: `research/hw_dump/macos_accelerated_trial_20261027/`

## Latest login-transition attempt (27 October, 21:46 local)

The user reports that the translucent clock appeared after waiting at the accelerated login screen. Immediately after attempting login, the display showed verbose output and returned to the lock/login screen; the one-shot job then disabled acceleration. The system evidence confirms the sequence:

- The trial armed the pipe (`0x3b → 0x3f`, `accel+0xccf = 1`), restarted WindowServer PID 201, and observed PID 481. Login was detected.
- At 21:46:20 the job found WindowServer missing one second after login, disarmed the pipe (`accel+0xccf = 0`) and wrote `/private/tmp/n48m-off`. This was the configured fail-safe responding to a server exit, not a spontaneous disable.
- `WindowServer-2026-10-27-214633.ips` records PID 481 exiting with `EXC_CRASH/SIGABRT` (signal 6). The triggered stack is again `CA::OGL::Context::push_surface → CA::OGL::FlattenNode::retain_surface → CA::OGL::ImagingNode::render → CA::OGL::render_layers`. The report time is 21:46:33; its capture and process exit fields place the crash at 21:46:20, matching the job log.
- The diagnostic bundle does not expose the assertion's textual condition. The stack does locate the failure in Core Animation's OpenGL surface/flattening path. The translucent clock is evidence that at least some login-window rendering/composition ran with the pipe armed; it does not establish stable acceleration or correct output across all surfaces.
- This narrows the trigger to the login/session transition and its heavier or different layer/surface workload. It does not point to ReBAR, the PCI match, or initial pipe adoption. Keep the safe non-accelerated fallback for now; do not simply lengthen the watchdog or leave the same pipe armed, because the report shows a real WindowServer abort.

Artifacts from this attempt are preserved under `research/hw_dump/macos_accelerated_trial_20261027/latest-login-transition/`. The strongest next diagnostic target is the Navi44 Metal/CoreAnimation surface contract used by `push_surface`/flattening (surface lifetime, pixel format/plane metadata, and synchronization), plus the exact CIKL workaround application timing. A narrowly controlled experiment should change one of those at a time and retain the fail-safe; the present evidence does not yet justify another blind reboot with the identical candidate.

## Next controlled candidate: bypass translucent flattening

The latest trial did set `CI_USE_MTL_DAG_FOR_CIKL_SRC=0` in the system launchd domain before restarting WindowServer, and attempted the uid-501 domain setting. The same `CA::OGL::Context::push_surface → FlattenNode::retain_surface` abort still occurred at login. That makes a missing CIKL environment backstop less likely to be the sole cause.

Because the crash is specifically inside Core Animation's OGL flattening path and the user saw a translucent clock immediately beforehand, the next bounded trial is to enable macOS Accessibility's **Reduce transparency** preference for `pastasugo89`. Apple describes this setting as replacing transparent effects with solid backgrounds ([Apple Support](https://support.apple.com/en-euro/guide/mac-help/unac089/27/mac/27)). This is a targeted diagnostic/workaround hypothesis: if the login/session reaches a stable desktop, it would show the unstable path is tied to translucent/flattened layers; it will not establish that all accelerated surfaces are correct. The setting is reversible in Accessibility → Display.

The preference was set to `reduceTransparency=1` for the next trial. Its test result is in the next section. The candidate plist was consumed by that test; it is no longer staged, and `/private/tmp/n48m-off` currently keeps acceleration disabled.


## Trial with Reduce Transparency (27 October, 21:54 local)

The user clarifies the sequence: the translucent clock appears only after entering the password and pressing Return; the desktop/session begins to appear, then immediately returns to the lock/login screen. The Reduce Transparency preference had been set, but did not prevent this failure; it has been removed again because it was not useful in this test.

The trial log shows `pipearm 1` succeeded and the job restarted WindowServer PID 201 as PID 517. Login was detected at 21:54:35. PID 517 then exited; PID 909 appeared, and the one allowed PID retry was used. The kext pipe stats on the retry show that the previous WindowServer GPU client close auto-disarmed the pipe and had only two hook calls, zero pass-through/will-perform **display-pipe hook** submissions, zero scanout bytes and zero scanout frames. These counters do not count all Metal command buffers. A second WindowServer transition occurred 16 seconds after login; the job then ran the fail-safe and recreated `/private/tmp/n48m-off`. There is no current one-shot plist staged.

Two reports, `WindowServer-2026-10-27-215447.ips` (PID 517) and `WindowServer-2026-10-27-215453.ips` (PID 909), both terminate with `SIGABRT` at `CA::OGL::Context::push_surface → CA::OGL::FlattenNode::retain_surface`. The newer report shows a thread compiling a Core Animation pipeline through `CA::OGL::MetalContext::create_pipeline_state → Navi48Device → RADV`, while other threads process `FlattenNode`, masks and layer bounds. A separate thread is executing QuartzCore's `SWContext::set_surface`/shadow path. The unified log proves GPU work did run: PID 517 and PID 909 each submitted Vulkan command buffers (`vkQueueSubmit = 0`) and logged fence completion before exit. In PID 909, Navi48Metal imported a 2560×1440 BGRA IOSurface and made a render pass targeting it. This proves partial GPU rendering, but not a stable display frame: scanout/present hooks still show zero frame copies, and the 2560×1440 surface's caller was `SkyLight::CreateCompositeDestination` from `_XHWCaptureDesktop`, not `DisplaySurface::GetMTLTexture`; the classifier correctly logged `caller_DisplaySurface_GetMTLTexture=0`, so it was only a candidate, not a confirmed scanout surface. The translucent clock is evidence of visible composition, but alone does not prove the accelerated scanout path is working.

This rules out “only the login window needs a little more time” and shows that reducing transparency alone is insufficient. The crash is reproducible in the Core Animation OGL flatten/surface path during transition to the user desktop, with RADV pipeline compilation happening concurrently. The next useful work is a source-level audit of the bundle's `newTextureWithDescriptor:iosurface:plane:` / surface lifetime, and shader/pipeline error handling against the exact failed runtime pipelines, plus correlating WindowServer logs with those IOSurface IDs and dimensions. Avoid another reboot with the same build and fail-safe script; a new boot candidate should only follow a specific, isolated change and have counters proving that command submission and frame presentation occurred.

Artifacts from this attempt, including both crash reports, trial log and runtime markers, are preserved in `research/hw_dump/macos_accelerated_trial_20261027/after-reduce-transparency/`.

## Stage18: host-pointer buffer import contract (27 October, 22:02 local)

The 21:54 run exposed a concrete Vulkan contract violation in `N48Buffer initWithDevice:bytesNoCopy:length:options:deallocator:error:`. The code created a regular `VkBuffer`, then passed `VkImportMemoryHostPointerInfoEXT` to `vkAllocateMemory` with `VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT`, without placing a corresponding `VkExternalMemoryBufferCreateInfo` (with that handle type) in the buffer's `VkBufferCreateInfo.pNext`. Khronos specifies that this external-memory declaration must be included when a buffer is bound to imported/exported memory. Runtime logs from WindowServer PIDs 517 and 909 show these imports failing with `VK_ERROR_INVALID_EXTERNAL_HANDLE` (`-1000072003`) for 577,536 B, 33,177,600 B, and, in PID 517, 14,745,600 B. `newTextureWithDescriptor:iosurface:plane:` can return nil when its no-copy buffer import fails. That is a direct local code/runtime mismatch and a plausible contributor to the Core Animation flatten/surface crash; it is not yet proof that it is the only cause.

Prepared a separate `stage18-hostmem-buffer` candidate. Its only runtime-code change is to chain `VkExternalMemoryBufferCreateInfo` into this no-copy buffer's create info with `HOST_ALLOCATION_BIT_EXT`; ordinary buffer creation and IOSurface import paths are unchanged. It compiles for x86_64 with `-Wall -Wextra -Werror`, was ad-hoc signed, and `codesign --verify --strict --deep` passes. The candidate bundle version is 21. The one-shot trial script now requires bundle version 21 and uses its own consumed-marker filename.

The Stage18 bundle was installed at `/Library/GPUBundles/Navi48Metal.bundle`; Stage17/version 20 is preserved at `/Library/GPUBundles/Navi48Metal.bundle.pre-stage18-20261027`. The one-shot plist is staged at `/Library/LaunchDaemons/org.navi44.accelerated-trial.plist`, but the job is not currently bootstrapped or running. `/private/tmp/n48m-off` remains root-owned, mode 0644, empty, so this current session stays in fallback mode. At the next boot the one-shot will remove the stale kill switch only after its preflight and arm the pipe. If WindowServer fails, its existing fail-safe disarms and recreates the switch. No reboot has been performed as part of staging.

Candidate source, bundle, installer and trial artifacts are in `research/builds/macos-20261027/userspace/candidates/stage18-hostmem-buffer/`. The relevant Khronos requirement is documented in [VkExternalMemoryBufferCreateInfo](https://registry.khronos.org/VulkanSC/specs/1.0-extensions/man/html/VkExternalMemoryBufferCreateInfo.html); [VK_EXT_external_memory_host](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_external_memory_host.html) specifies host-allocation import and alignment/synchronization requirements.

## Stage18 result and exact assertion

Stage18 ran at 22:08 local. Bundle build 21/UUID `8b49cee6-0bc7-33f5-8527-99ab552711b9` was actually loaded. WindowServer 518 crashed after login, then 867 crashed again; the one-shot restored the kill switch and disarmed at 22:08:45. Its plist was consumed; another reboot does not schedule this trial again.

The missing external buffer declaration was a Vulkan contract defect, but the runtime result falsifies the hypothesis that adding it resolves these imports: the 33,177,600-byte and 14,745,600-byte no-copy buffers still fail. Other sizes already imported successfully before Stage18. Crucially, the full Core Animation log shows a normal allocated buffer immediately following the refused no-copy import, so a nil import alone cannot be equated with the fatal surface assertion.

Read-only inspection of the locally loaded QuartzCore framework identified the exact assertion at crash image offset 1500158 (push_surface +630): `found != slist->end ()`, file `ogl-context.cpp`, line 1186. The two other nearby assertions are `surf != nullptr` and `_current_surface != surf`; those are different call sites. This extraction used the exact QuartzCore UUID from this build (`f49244fc-239e-3b57-bc0f-9ec5bad7c765`); offsets are not portable to other framework builds.

The unified log confirms at 22:08:44.876: `context(10) transient surface ... not found`, plus the same failure for contexts 13 and 12. Disassembly searches a context-owned linked list for the given surface before asserting. This establishes the immediate invariant failure: a transient surface is absent from the current context's list. It does not establish whether the origin is the driver advertising incorrect capabilities, a surface lifetime/ownership issue, or Core Animation's transition between software and Metal composition. Do not bypass this assertion or present the external-buffer fix as a solution to this crash.

Full logs, two crash reports, exact assertion strings and the read-only extraction program are archived in `research/hw_dump/macos_accelerated_trial_20261027/after-stage18-20261027T2208/`. Current acceleration remains disabled by `/private/tmp/n48m-off`; no new trial has been staged. The next targeted investigation is transient surface creation/reuse and context selection at the software/Metal boundary.

## Stage19: restore Cobalt64's AMD compositor selection

On 27 October the current public upstream `Navi48Device.m` was downloaded into `research/ext/cobalt64-upstream-20261027/`. Against our baseline, the substantive differences are the Navi44 board header/device check/product name and the BOOL-return adaptation to lazyInitialize. The core surface and shader-translation implementation is already Cobalt64's. Stage19 retains the currently installed build-21 bundle and all its libraries; it does not replace translation code or claim a shader fix.

A separate read-only extraction of the exact CoreDisplay binary identified the fatal assertion at image offset 289801 in the historical boot30 reports: Display.cpp line 3228, `Failed to create MetalDevice (%s)`. This is not an assertion that AMDFramebuffer is absent. The historical record also says Navi48Metal declined devices after its start counter exceeded the limit. The earlier report's characterization of the AMDFramebuffer warning as the fatal assertion was therefore too strong. This warrants a new, bounded native-vendor trial with correct start-marker handling; it does not prove that the native path will succeed.

Stage19 restores the upstream sequence `pipeadopt -> pipeagdc 1 -> fbname 1 -> headless-no flag -> pipearm 1 -> pipereload -> WindowServer restart`. This targets the directly observed software compositor / zero display-presentation state. Before renaming it archives and clears the regular start-counter file for this explicitly staged attempt; full bundle-component SHA-256 checks precede GPU actions. On the first unexpected WindowServer disappearance/PID change, the fail-safe disarms, sets n48m-off, restores `fbname 0`, removes the headless override and restarts WindowServer into software. It does not keep retrying an auto-disarmed GPU client. Early failure after clearing an archived kill marker now recreates that marker too. Stable completion at 120 seconds leaves the native route active for user inspection.

The one-shot Stage19 plist is installed for the next boot and is not bootstrapped in the current session. Its consumed marker is unique. The installed Stage18 binary and kernel/EFI are retained; current kill switch remains present. This is a targeted candidate requiring the next real login/display trial, not a confirmed complete fix. Artifacts: `research/builds/macos-20261027/userspace/candidates/stage19-native-compositor/`.

## Stage19 preflight failure and Stage19b readiness correction

The 22:35 Stage19 attempt stopped before pipe adoption, AMD rename or arming: `publish` returned success (registry ID 0x100000548), the accelerator kext was loaded, but an immediate `n48nub status` returned absent. No new WindowServer reports appeared. A later read-only IORegistry inspection and `n48nub status` show this same nub registered, matched, active and Ready=1 with Navi48Accelerator below it. The original loaded-kext test was insufficient to establish registration readiness. This boot did not exercise the native compositor candidate.

Stage19b replaces that gate with a bounded 60-second read-only readiness poll requiring both nub Ready=1 and a registered accelerator class. It aborts if a user session appears while waiting. The exact registry predicate succeeds against the currently registered services (the standalone read-only check omits only the no-user requirement because the current session is logged in). GPU actions remain reserved for the next boot. Rollback now restores the kill switch on any failure after guard validation even when no stale marker survived reboot. Stage19 had no stale marker and exited before active=1, so its prior rollback condition had not recreated the marker; it is now restored root:wheel/0644/empty.

A unique Stage19b one-shot plist is staged for next boot, with the same native compositor sequence and first-failure class-name rollback. No new kernel or GPU-bundle binary has been installed for this correction.

## Stage19b result: eight-byte CLI readback, corrected in Stage19c

The 22:40 boot passed registry readiness at zero seconds and successfully adopted the pipe/published AGDC. `fbname 1` reported armed=1/status=0 and printed `AMDRDNA4`. The test stopped before `pipearm 1`, because the script incorrectly expected the full `AMDRDNA4FB` name in this output. This is an agent implementation error: `navi48test.c` explicitly prints eight packed name bytes, and `navi48_fbname.cpp` documents that truncation. The fail-safe correctly restored RDNA4FB and restarted software WindowServer. No new WindowServer crash report appeared. The accelerated native-compositor test still has not run.

Stage19c validates armed=1/status=0 plus the eight-byte CLI name, and independently requires the full class name AMDRDNA4FB from `ioreg -r -c RDNA4FB -d 1`. That matching uses the original RDNA4FB metacast, which the kernel explicitly preserves across the rename. The parser passed tests using the actual Stage19b CLI output, rejecting an unchanged registry class and a nonzero status. Shell syntax/plist checks pass. Other script gates were compared with the successful observed outputs (bundle hashes/version, nub/Ready, accelerator class, adopted/disarmed flags, arm status and +0xccf readback). The corrected one-shot is staged under a unique consumed marker, with no GPU/bundle/EFI binary changes. Current n48m-off remains present.

## Stage19c: first successful native accelerated desktop; Stage20 shader warmup

The 22:46 boot successfully armed the AMD route and completed the 120-second observation with WindowServer PID 517 unchanged. User reports working transparency/effects and stable interaction, with magenta regions replaced by correct content on pointer redraw. The bundle's runtime log confirms real scanout: 5,734 presents (5,734 kernel presents), 0 refused, 0 gpu_fail and 0 watchdog restores in the sampled cumulative counters; final-GPUPass writes are present. The older kernel pipe CPU-copy counter remains zero because native scanout uses the bundle's distinct presentation path. No new WindowServer crash report was found. This is evidence of actual accelerated presentation, beyond Metal initialization.

The runtime log also records 65 unique render fallback pipeline pairs and corresponding 65 `fallback -> real` hot swaps. These are the driver's explicit magenta placeholders used before AIR translation finishes. They provide a concrete explanation for startup magenta and its replacement when a region is rendered again. They do not by themselves rule out other rendering bugs after warmup.

Stage20 snapshots 132 runtime SPIR-V/reflection pairs into the existing bundle cache, yielding 167 total shader pairs. Each runtime module passed spirv-val, structure/entrypoint execution-model checks and JSON metadata shape checks; translated entrypoint `main` is accepted alongside the original AIR name. All 66 missing-shader keys recorded in the captured successful-session log are preloaded. The RADV and in-process translator libraries are byte-identical to Stage19c; executable logic is unchanged (bundle resource sealing was renewed). Bundle build 22 is signed/verified and installed, with the entire successful version-21 bundle preserved at `/Library/GPUBundles/Navi48Metal.bundle.stage19c-working`, and the successful trial script copied to `stage19c-working.sh` under the application support folder.

A unique Stage20 one-shot is staged for the next reboot, using the same verified native route and rollback. No WindowServer restart/logout/reboot occurred during preparation; PID 517 remained active. The next fresh compositor session should load these already translated shaders immediately instead of first painting their magenta placeholders. That outcome, and absence of other artifacts, must be verified at the next login. The candidate is in `research/builds/macos-20261027/userspace/candidates/stage20-warm-shaders/`, success logs in `research/hw_dump/macos_accelerated_trial_20261027/stage19c-success/`.

## Stage21: combined cache, logging and shader-latency candidate

User requested several fixes together before the next reboot. Current WindowServer remained PID 517; Stage20 had only been installed/staged, not booted. The eight-minute successful-session log contains ~193,197 lines: ~61,562 buffer creation lines, ~16,926 sampler API calls and ~16,914 sampler creation lines alone. Some windows show GPU completion around 1–2 ms under light load; this does not measure animation/app performance or establish that GPU time is always small. Existing RADV pipeline cache persistence works (736,584-byte cache saved in the observed session). New UI interactions still create uncached shaders after the Stage20 snapshot.

Stage21 (bundle 23) combines:

- 212 packaged shader/reflection pairs, including 177 runtime pairs validated with spirv-val, SPIR-V execution-model/entrypoint checks and JSON metadata checks. This extends the prewarm to shaders encountered while opening/using more UI.
- Rate limiting at 16 resource/sampler/texture informational logging sites with the existing N48LOGR rule (first eight, then one per 1024 calls). Errors, warnings, shader fallbacks and T1 performance summaries remain visible. This removes a measured high-volume CPU/logging cost, without claiming a measured frame-rate improvement yet.
- Hot-swap polling every 100 ms instead of 500 ms; the 400-ms minimum file age, two-observation stability checks, atomic installation and reference lifetime rules are retained. All 224 checks in Cobalt64's original test-hotswap pass against the candidate header. New, unseen shaders can still briefly use a fallback while being translated; this is not presented as eliminating every magenta case.
- Translator launchd scheduling changed from Background/Nice=5 to standard/default ProcessType/Nice=0 at the next boot. Ownership, sandbox, resource limits, daemon polling interval and translation implementation are retained. The current translator was not restarted during preparation.

The bundle compiles with -Wall -Wextra -Werror and its renewed signature verifies. Existing Stage20 one-shot was replaced by a unique Stage21 one-shot with matching version/component hashes and the proven native AMD recipe. Original successful version 21 remains at `/Library/GPUBundles/Navi48Metal.bundle.stage19c-working`; resource-warmed version 22 is preserved at `/Library/GPUBundles/Navi48Metal.bundle.pre-stage21-warm22`. The original translator plist is saved under the application support folder as `translate.pre-stage21.plist`. No WindowServer restart/logout/reboot was performed; current PID remains 517.

Remaining observations to track rather than silently mask: compute texture slot 0 unbound warnings occurred in the old session; new shader paths can remain uncovered until used; rate limiting and scheduler changes need actual post-boot performance comparison. The original pipeline cache uses bundle version/build time in its key, so a new bundle build can incur one cache rebuild. GPU command/resource semantics and RADV/translator binaries were not changed by Stage21. Candidate and changes/validation artifacts: `research/builds/macos-20261027/userspace/candidates/stage21-desktop-polish/`; before logs: `research/hw_dump/macos_accelerated_trial_20261027/stage19c-success/performance-before-stage21.log`.

## Stage21 observed feedback and power-off investigation

At 23:02 the user reports improved responsiveness, residual stutter, occasional magenta flashes and intermittent black band at the screen top. WindowServer PID516 survived the trial. Sampled native scanout counters show increasing presents, zero refused, GPU failures and watchdog restores; replacement/drop counters increase during activity. The measured submit-to-completion times include queue/presentation waits and are not pure GPU execution times. Some windows average ~6.3 ms at a nominal 8.33 ms presentation interval, with a CPU encode maximum ~38.7 ms in one sampled window. No visual black-band event was timestamp-correlated, so tearing/premature presentation remain hypotheses, not diagnoses. No speculative scanout register or composite-pass filtering changes were installed.

Two new fragment shader cache misses are logged for this boot; both are translated and hot-swapped (one observed around 0.9 s). These account for at least some residual magenta; prewarming already-used shaders does not remove first-use translation for all future application/UI paths. The shader outputs persist in the side cache. Compute slot-0-unbound warnings remain to investigate.

For shutdown the user confirms fans/lights really power off and then restart. This favors a firmware wake/power-on event rather than a continuous OS restart, but does not alone establish the exact source. macOS had womp=1 and powernap=1. Saved settings in stage21-observe/pmset-before.txt and applied `pmset -a womp 0 powernap 0 autorestart 0`; readback shows womp=0 and powernap=0 (autorestart is not listed by this machine, so efficacy of that key is not established). There are no scheduled wake events in `pmset -g sched`. BIOS wake-by-PCIe/network, USB, RTC and ErP are the next controls to check if power-off still returns to power-on. MSI documents those wake controls; Dortania also documents a separate USB/ACPI S5 shutdown problem, which requires this machine's controller path and is not an automatic generic patch.

A unique one-shot for the unchanged, successful Stage21 profile was restaged for the next boot so a shutdown/manual power-on test does not silently lose acceleration. It does not run in the current session. No reboot/shutdown/logout was triggered. This is not a claimed black-band fix or a confirmed shutdown fix.
