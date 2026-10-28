# Unified repair preparation — 28 October 2026

## GPU identity correction (prepared, not installed)

The USB boot filesystem (OCBOOT UUID `7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3`) was mounted read-only using mount_msdos. `fsck_msdos -n` completed without directory/cluster errors and left its existing dirty flag unchanged. A complete EFI copy is in ignored staging `research/builds/macos-20261028/unified/efi-baseline/EFI`. The baseline config SHA-256 is `b8351af96eda59bdb278b48ed70a96fa0a02f6906dbbeb527c20a21112a9701d`.

The framebuffer source staging baseline matches the boot USB binary SHA-256 `f51ac257f5ab4f2fa8136c9e7d8cbe0fa1205c4e911350a547d0f2a72f8b6468`. Its source already distinguishes PCI 7590 from Navi48, but the service retains the personality's hard-coded RX9070 Series model. The tracked `tools/baremetal/navi44-desktop/rdna4fb-model.patch` removes that personality default and publishes the hardware-selected model on the framebuffer as well as its PCI provider. Apply with `patch -p1` to the `RDNA4FB-desktop-navi44-candidate` source baseline. No PCI IDs are spoofed or changed.

The bringup baseline matches the USB binary SHA-256 `5bec24149c64479fd00f3fbe0b7a44c37a68568453e7272944e3e9d0dc6ebcd9`. Its Metal nub now uses the ASIC profile model; the Navi48 build retains its R9700 distinction by reading the provider PCI device ID. Navi44 uses the validated RX9060 XT board name. Only the nub source and ASIC header were copied into this matching source baseline.

Both candidates compile for x86_64, pass strict ad-hoc signature verification and resolve their imports via `kmutil libraries` against the running kernel collections. This proves build/link preparation; System Information after boot is still needed to prove the displayed name. No kext was loaded or replaced in the running session.

Candidate outputs:

- RDNA4FB SHA-256: `ce5f700af0433b595625b348a53204191ce4abea232b2df730a3b72cdd1907af`
- Navi48Bringup SHA-256: `ab6e1f7aa0f61c7e38019342d8c9a6e68266d7a069a59fa9b758f593cd52f722`

## USB and wireless prerequisites (local EFI only)

Revalidated live PCI parent BDFs: XH00 5:0:0, XHC0 10:0:3, XHC1 10:0:4, XHC2 11:0:0. All four running XHCI services have 14 merged port entries and port-count 1; the baseline plist correctly has distinct controller port counts 14/4/4/1. The staged correction changes only the four IOParentMatch dictionaries to exact pcidebug property matching. Every IOProviderMergeProperties dictionary, including all port data and connector types, remains byte-for-byte semantically identical. Runtime enumeration still needs a boot test.

`prepare-wireless-efi.py` now reproduces this change from the exact inspected config hash, rejects an existing destination, preserves the source EFI, and disables only the SSDT that masks the Qualcomm PCI function. It ran against the saved baseline; OpenCore 1.0.8 ocvalidate reports no issues. The combined local candidate additionally contains the GPU identity kexts. Nothing has been written to the boot USB. Restoring PCI/USB enumeration does not implement Qualcomm firmware loading or the Wi-Fi/Bluetooth driver; these requirements remain unresolved.

## CPU power-management source audit

Actual CPUID from sysctl is family 25 (19h), model 97 (61h), consistent with Ryzen7700/Raphael. Audited `DrogaBox/SMCAMDProcessor-personal` at commit `c214eed5f1239df19e6c547c61931536fdf14db6` (downloaded locally, not installed). Its current [README](https://github.com/DrogaBox/SMCAMDProcessor-personal) advertises opt-in CPPC Active via -amdcppcactive, but the implementation contradicts this: AMDRyzenCPUPowerManagement.cpp lines1426–1432 forcibly set cppcActiveMode=false even when the boot argument is present. applyEPPControl is a no-op (lines1054–1057). The Zen4 profile disables both legacy P-state writes and custom PM dispatch (header lines373–380). Adding this release would therefore supply telemetry rather than the requested CPPC frequency policy. It cannot be recorded as a power-management fix. No MSR/SMU controls, privilege-bypass argument or additional CPU kext was installed. ProvideCurrentCpuInfo is already true in the actual boot config.

## Shutdown ACPI audit

The user confirms actual fan/light power-off before power-on. Built ACPICA iasl 20260930 for this macOS in a separate bin-macos/obj-macos directory; the original Linux binary remains intact. Decompiled the local firmware DSDT and all15 SSDTs into ignored unified/acpi staging. The real root _PTS calls TPM.TPTS, MPTS, SPTS, PCI0.GPTS and PCI0.NPTS. SPTS has an explicit S5 branch setting PWDE=1; MPTS is defined in SSDT9 and invokes additional firmware callbacks; NPTS forwards to APTS in SSDT1, whose only branch is an empty S3 branch. This does not establish which wake source reactivates the board. Do not replace the entire _PTS or discard its existing calls.

The [Dortania shutdown recipe](https://dortania.github.io/OpenCore-Post-Install/usb/misc/shutdown.html) requires identifying the relevant USB controller from its wake method. Current DSDT _PRW methods are on bridges/devices, and the SSDT8 wake resources examined are under GPP0.SWUS, not proof that the Wi-Fi/USB controller needs that recipe. No generic shutdown AML was installed. [MSI documents](https://us.msi.com/support/technical_details/MB_Wake_On_LAN) Resume By PCI-E/Networking and ErP as controls for wake after shutdown; firmware setting state remains unverified. Previously applied womp=0 and powernap=0 remain only OS-side mitigations; successful S5 without restart requires a physical test.

## Translator steady-state overhead correction (installed)

The existing pc-translate.sh scans every0.5s and executes up to two grep children per previously-decided shader. With212 cached shader decisions, a controlled Bash3.2.57 benchmark measured0.8283s for one lookup sweep versus0.1013s using the new in-memory newline-delimited exact-SHA index (including loading it). This is a microbenchmark of the decision path, not a desktop frame-rate or stutter measurement. The daemon now reads the done list once per scan, does built-in exact-key lookups, and updates the index only after persisting new decisions. Refresh on every scan preserves done-list changes; old translator keys, both previous successes and failures, still retry. The translator key/output format, sandbox, uid ownership, size/time/memory limits and SPIR-V validation are unchanged.

Validation: dedicated cache regression checks pass on the actual system Bash3; existing daemon suite33checks pass; suite with sandbox35checks pass using three distinct real local CoreAnimation AIR modules under fixture filenames expected by the test. A deliberately broken cache that ignores translator version keys makes8of33checks fail, proving invalidation regression coverage. The corresponding planted-defect selector was updated for the new implementation.

After confirming no metal2vulkan job was running, installed only pc-translate.sh and restarted com.navi48.translate. The installed source SHA-256 is `5e532880520c46e49bdb33c91b175dc6c003b048704aabc22fcce62666cac9db`. Backup: `/Library/Application Support/Navi44/accelerated-trial/pc-translate.pre-decided-cache-20261028.sh`. launchctl reports running with PID21878; WindowServer remains PID517. No GPU reset, logout or reboot occurred. The actual service is now the optimized implementation; graphics correctness and elimination of residual stutter remain unproven.

## Requirement audit at this checkpoint — full goal remains active

| Requirement | Authoritative result | Remaining evidence/work |
|---|---|---|
| Commit prior work and each change | Prior work preserved; this checkpoint commits67650bb,2d202bc,9725d5b,358fc74 | Keep subsequent changes committed; no push requested |
| RX9060XT name | Corrected kernel sources; two compiled/signed/import-resolved local candidates | Deploy combined EFI and verify IORegistry/System Information after boot |
| Wi-Fi | Exact Qualcomm PCI visibility change prepared and ocvalidate passes | Compatible17cb:1107 macOS driver remains missing; enumeration alone is insufficient |
| Bluetooth | Exact USB parent matchers prepared; original port dictionaries preserved | Boot enumeration of0489:e10a, firmware/transport support, pairing test missing |
| CPU power management | Actual19h/61h confirmed; current Tahoe fork CPPC controls are no-ops | Implement/identify a supported actual policy and verify frequency/power behavior |
| GPU responsiveness | Resident translation overhead correction installed;35checks pass | Desktop stutter/frame-time comparison still needed |
| No magenta | First-use shader placeholders still exist; daemon index optimization preserves translations | General first-use behavior still unresolved; cache warmup cannot prove elimination |
| No black band | Native presents continue without GPU failures; no timestamp-correlated event | Correlate an actual visible event before selecting a presentation/resource fix |
| No shutdown power-on | Actual ACPI callback chain audited, OS network wake mitigations verified | Firmware wake source and physical S5 test unresolved |
| Ready for one reboot | Combined EFI exists only in local staging; boot USB mounted read-only, unchanged | Not ready; the prior one-shot was consumed by this morning's boot, no replacement staged |

Fresh capture `current-scanout.log` shows native presents increasing, zero GPU failures/refusals/watchdog restores and both GPUPass/composite presentations. PID517 is the present WindowServer, rather than the previous evening's PID516. The original stage21-shutdown-check one-shot has been consumed. This checkpoint does not authorize describing the combined repair as finished or asking the user to reboot. The actual staged kernel changes are model properties only; no black-band patch has been smuggled into them.

## CPUID capability check and bounded CRC observation

Added and ran the read-only userspace tool `tools/baremetal/cpuid-cppc.c`, compiled with -Wall -Wextra -Werror. Actual CPU: AuthenticAMD family19h model61h stepping2, hypervisor bit0; CPUID80000008.EBX=791ef257, CPPC MSR support bit27=1; CPUID80000007.EDX=6799, invariant TSC and Core Performance Boost bits both1. This proves the full-MSR CPPC interface is advertised; it does not prove which CPPC requests firmware or the OS currently programs. No MSR read/write was attempted from userspace.

Cross-checking primary [Linux MSR definitions](https://raw.githubusercontent.com/torvalds/linux/master/arch/x86/include/asm/msr-index.h) and [FreeBSD hwpstate_amd.c](https://github.com/freebsd/freebsd-src/blob/main/sys/x86/cpufreq/hwpstate_amd.c) also found a defect in the downloaded telemetry fork: it decodes highest performance as CAP1&ff, but the capability register has lowest performance in bits0–7 and highest in bits24–31. Request register field ordering is different. No source from these kernels was incorporated into a hardware-writing kext at this checkpoint.

Enabled the installed driver's existing CRC diagnostic for30seconds with row step64 and noslot, then removed the flag using a bounded root process EXIT trap. Diagnostic logs confirm enable/disable; WindowServer stayed517. The sample reports source instability only when a later GPU command buffer for the same surface was already submitted; changed_outside_cbs=0 and src_changed_before_present=0 in the sampled summaries. Slot reads were deliberately disabled, so slot_ne_src=0 cannot prove correct slot contents. Alias counters show ws_would flush/reupload=0/0 during this observation. These results do not justify enabling WindowServer alias changes or claiming the black band is fixed. Logs are local staging crc-noslot-30s.log and crc-ioalias.log.

User clarification: not physically at the computer; black band repeatedly flashes for up to about1second over the upper fifth of the screen. No precise event timestamp is available. A native screencapture attempt returned `could not create image from display`; no screenshot was captured, and no screen-recording permission settings were changed.

## Stage22 / bundle24: bounded wait on CA's background pipeline compilation queue (prepared)

The captured crash stacks show QuartzCore MetalContext pipeline creation calling the synchronous Metal factory on `com.apple.coreanimation.pipelines`. Existing WindowServer policy immediately returns a magenta render/no-op compute placeholder for any uncached shader, even on that dedicated compilation queue. The new exception waits for the external daemon only on that exact queue, only when pthread_main_np reports a background thread, and never for forced-fallback/test modes. Main, render-server, root/default and unknown queues retain immediate fallback. Applications retain their existing3s rule. WindowServer gets a separate1.5s maximum with the same3-consecutive-timeout/per-key suppression. No LLVM/translator library is loaded into WindowServer; ownership/sandbox/validation/hot-swap rules are retained. This targets first-use placeholder flashes; late/failed translations and misses on other queues still use the fallback, so universal elimination is not proven.

The pure context matrix covers all combinations of WS/app/force/test/main-thread and7queue labels (including null and prefix lookalikes), and separate deadline boundaries. The real Objective-C call sites are checked to use the actual current queue/thread and dump AIR before waiting. Gate suite436checks pass; in-process translator suite134checks pass. The bundle compiles with -Wall -Wextra -Werror for x86_64 and verifies with strict deep signing. It preserves byte-identical Stage21 RADV and libn48xlate baseline libraries. Candidate-only resource warmup validates185runtime SPIR-V/reflection pairs and adds8previously encountered shaders, yielding220packaged pairs; this is coverage of observed shaders, not all future UI/app paths.

Candidate: ignored `research/builds/macos-20261028/unified/stage22-compile-wait/Navi48Metal.bundle`, CFBundleVersion24. Complete local file hashes in bundle-manifest.json. No install, WindowServer restart, GPU reset or reboot was performed. This new bundle still needs the guarded boot/runtime test; no black-band fix is claimed by this change. The prior native boot script remains tied to installed bundle23 and must be regenerated before any deployment of24.

### Correct CPPC telemetry ranking patch

Prepared `smcamd-cppc-cap1-ranking.patch` against the exact audited c214eed5f1239df19e6c547c61931536fdf14db6 source. It corrects both the CAP1 HighestPerformance extraction and its incorrect comment from bits7:0 to bits31:24, matching independently checked Linux and FreeBSD register definitions. This prevents reporting lowest performance as the preferred-core ranking. It does not enable CPPC policy writes or establish CPU frequency scaling. No CPU kext binary was built/installed for this isolated source correction.
