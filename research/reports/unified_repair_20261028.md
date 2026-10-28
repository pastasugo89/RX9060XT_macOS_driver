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
