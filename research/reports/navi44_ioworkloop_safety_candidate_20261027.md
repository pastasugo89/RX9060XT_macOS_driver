# Navi44 IOWorkLoop watchdog candidate — 2026-10-27

## Scope

This is a separate build candidate at `research/builds/macos-20261027/desktop-prep/navi44-psp-ioworkloop-candidate`. The existing stage1 candidate and EFI were not changed. The kext was built and inspected only; it was not loaded or run against the GPU.

## Implementation

The copied source replaces the manually started kernel thread with a dedicated `IOWorkLoop` and `IOTimerEventSource` using `kIOTimerEventSourceOptionsPriorityWorkLoop`. The first callback is scheduled after 1 ms and later callbacks rearm every 250 ms. Each callback performs one BAR5 read, decodes it and publishes the same atomic PSP eligibility snapshot. It rearms before publishing an eligible sample; a timer rearm failure latches TRIP and refuses PSP entry. Workloop/timer creation and event-source attachment failures also fail closed. `ready_for_psp()` refuses while teardown is in progress.

Teardown uses an atomic lifecycle state machine: `stop()` waits for `start()` initialization, claims the stop transition, and makes duplicate stop calls wait through final release. It sets the stop flag, cancels the timer, removes the event source synchronously, cancels once more to cover a callback rearm race, then releases the timer and workloop before `Navi48Bringup::stop()` reaches BAR5 unmapping. If the timer/workloop pair is inconsistent or removal keeps failing, the code retains the resources and blocks teardown; it never treats a failed removal as proof that callbacks have drained. This intentionally risks a hung stop/unload in that fault case.

The synchronization basis is the local MacKernelSDK headers: `IOTimerEventSource.h` documents `PriorityWorkLoop` callbacks on the workloop thread and `cancelTimeout()` preventing future actions; `IOWorkLoop.h` documents synchronous `removeEventSource()` acknowledgement, event-source ownership, and `free()` waiting for the workloop thread to terminate. Because the callback and removal acknowledgement use that same workloop thread, successful removal is expected to follow completion of any in-flight callback. This is based on the documented dispatch contract, not runtime validation on Tahoe.

The copied `smu_protections_verified()` flag was changed to atomic loads/stores because the watchdog heartbeat can read it while the bring-up ladder updates it.

## Verification

- Full x86_64 Navi44 build of the final lifecycle-state version: exit code 0. Build log: `research/builds/macos-20261027/desktop-prep/navi44-psp-ioworkloop-candidate/build-ioworkloop-lifecycle.log`.
- The final binary is a Mach-O 64-bit kext for `x86_64`; `Info.plist` passes `plutil -lint` and contains PCI match `0x75901002`.
- `codesign --verify --verbose=2` reports a valid bundle. The signature is the build's ad-hoc signature; this is not evidence of runtime compatibility.
- SHA-256 of `build-ioworkloop-lifecycle/Navi48Bringup.kext/Contents/MacOS/Navi48Bringup`: `351afbe949d1a3a2ffe6be3cdbd4b20ecb85a0d311ebe42050b87ec50b02d49b`.
- The earlier `7b96f043…` build in `build-ioworkloop` is preserved unchanged; it predates the final start/stop lifecycle-state arbitration. It was separately used to prepare a local, undistributed EFI candidate.
- Host pure-logic test: `42 checks, 0 failed` (`tests/n4x_safety_ioworkloop_test.cpp`). This covers sample freshness, invalid/WARN/TRIP refusal and the new watchdog-failure reason; it does not simulate IOKit timer/workloop teardown.
- The full build reported unrelated shadow warnings in `Navi48Bringup.cpp` and `amdgpu_init.cpp`, an unused constant in `compute_test.cpp`, a signedness warning in `navi48_dcn.cpp`, and `-fapple-kext` being ignored on C compilation. `n4x_safety.cpp` emitted no compiler warning.

## Limits

No bare-metal sensor comparison or IOWorkLoop runtime test was performed. The THM decode remains explicitly unvalidated on this hardware. The PSP gate still admits based on one fresh OK sample; after `stagePSP()` starts, a later WARN/TRIP does not cancel the PSP chain. Thus this change improves watchdog scheduling and teardown synchronization, but it does not establish verified thermal protection or authorize a PSP-stage hardware run by itself.
