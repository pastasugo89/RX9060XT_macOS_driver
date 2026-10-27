# SIP diagnosis and stage17 EFI preparation — 2026-10-27

## SIP and the failed P0 userspace copy

Read-only host state: `csrutil status` reports SIP enabled; `csrutil authenticated-root status` reports enabled; `nvram csr-active-config` is `%00%00%00%00`. `/Library/GPUBundles` is owned by `root:wheel` but has the `restricted` file flag and `com.apple.rootless=KernelExtensionManagement`. The SSV root is sealed/read-only, while `/Library` resolves to the Data volume. The reported `ditto ... Operation not permitted` is therefore consistent with the rootless/SIP restriction on this directory; ordinary root ownership does not override SIP. Apple documents that SIP can restrict root and still block privileged processes, while this particular subdirectory carries the explicit protection marker.

This is not a permissions repair problem. No file flags, SIP state, authenticated-root state, NVRAM, EFI, or system files were changed. The failure rollback was reported clean; the P0 bundle, aux kext, daemon, and four intended user paths remain absent.

Apple XNU defines `CSR_ALLOW_UNTRUSTED_KEXTS` as bit 0 (`0x01`) and `CSR_ALLOW_UNRESTRICTED_FS` as bit 1 (`0x02`). Thus CSR `0x03` combines both. The P0 VM passed with `0x03`; that is evidence for the VM only. The proposed EFI stage17 config also sets `0x03`, but its effect on this bare-metal boot and on this exact protected directory has not been tested. Do not treat the setting as a compatibility or safety guarantee. Apple says `/Library` is generally writable by third-party installers, which is consistent with this one nested directory having a separate rootless marker. The authenticated-root setting protects the signed system volume and does not by itself explain this Data-volume destination.

The P0 userspace installer now checks real-root SIP status before any copy. With current `csrutil status: enabled`, it stops before `ditto`. For custom CSR state it requires the filesystem bit `0x02` in `csr-active-config`; `0x03` passes this preflight, while `0x01` fails. This is a precondition check only, not proof a copy will succeed. It leaves mock roots unaffected.

## EFI stage17 transaction helper

Prepared locally at [`install-stage17-efi.sh`](../ext/navi44-stage17-preflight-20261027/tools/install-stage17-efi.sh). It defaults to read-only preflight and requires both `--apply` and the fixed confirmation token to write. It has not been run against OCBOOT. It does not load a kext, change NVRAM, install the Metal bundle, or reboot.

The helper:

- Identifies OCBOOT by macOS VolumeUUID `7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3` and name, not by a volatile `diskN`. `A140-3052` is its Linux FAT UUID. The user's latest local `diskutil list external` reports OCBOOT as `disk3s1` and the independent 128 GB recovery USB as `disk4s1`; these identifiers are informational only.
- Checks filesystem type, mountpoint, and writability. `ReadOnlyVolume` may be absent, so it accepts `WritableVolume` if supplied; otherwise it requires explicit `read-write` mount flags and fails closed if neither is available. It verifies that the stage1 archive and snapshot directory are on the same recovery device and that its physical disk differs from OCBOOT.
- Rechecks all 31 live stage1 manifest hashes and the existing independent archive SHA-256 `2beaea0412c6fc3e4681a65b5703a24f435f7201a32f44936e5e299d389f78f2`. The stage17 manifest pins a README row in addition to 34 EFI files; the helper filters that row and verifies the exact EFI file set.
- Restricts the intended diff to the experimental `Navi48Bringup` executable, three files for a new but disabled `Navi48Accel.kext`, and `config.plist`. It copies/stages the kexts first and commits `config.plist` last. Before mutation it writes and verifies a full current-EFI snapshot on the independent recovery volume. On handled failure it restores stage1 from that snapshot and preserves the failed tree. Power loss or SIGKILL is not caught; the independent archive and Linux recovery procedure remain the fallback.

Mock test [`mock-install-stage17-efi-test.sh`](../ext/navi44-stage17-preflight-20261027/tools/mock-install-stage17-efi-test.sh): **6/6 pass**. Cases cover unchanged dry-run; rejection of the Linux UUID instead of the macOS VolumeUUID; rejection of same-disk recovery and read-only target; full 34-file staged apply; and injected failure before config commit followed by exact stage1 rollback. `csr-preflight-test.sh`: **4/4 pass**. Existing P0 mock transaction test: **6/6 pass**. Bash syntax checks passed.

The real stage17 dry-run could not be executed from this agent shell: `diskutil` reports that it cannot use the DiskManagement framework. The user's local volume listing supplies the device identities, but the helper must still be run locally in dry-run mode to validate live `VolumeUUID`, filesystem, writability field/mount flags, manifests, and recovery-device separation. A command using `sudo diskutil mount disk3s1` changes the mount state and may mount the USB writable; it is not a strictly read-only operation. Running the helper afterward **without `--apply`** makes no persistent changes to OCBOOT or the recovery USB, but it creates and removes temporary verification files under `/tmp` and reads/extracts the archived stage1 into that temporary directory.

## What one reboot would and would not do

The prepared candidate is stage17, removes `-amd_no_dgpu_accel`, and sets CSR `0x03`. If the candidate were later applied to OCBOOT and booted, that boot would attempt stage17; the CSR change is effective only after that boot. Stage17 is not passive: it proceeds into PSP and hardware stages, including firmware writes and compute. This system has no verified alternate display path or CPU/GPU temperature feed, and the RX is the active display. Those limits remain even though the candidate has a framebuffer guard and a watchdog test build.

The EFI transaction does not install P0's `Navi48Metal.bundle` or user probes. The limited P0 installer would need to be run after a boot whose live CSR state includes `0x02`; it installs only the bundle and two user tools. The P0 auxiliary kext is staged disabled in the EFI and is not loaded by that installer. The separate documented `kmutil libraries` / explicit `kmutil load` gate and any approval still remain. The translator LaunchDaemon is also not installed; defer it unless the selected P0 test needs dynamic shader translation. Consequently, applying this EFI does not by itself yield an accelerated Metal test on the first boot.

P0 VM evidence remains T0-T4 headless test success with a separate virtual display and CSR `0x03`; it does not prove bare-metal display retention, rootless path writing, kext approval/load, thermal safeguards, or Metal runtime here. The next safe action is only a local dry-run after mounting the two volumes. No apply command or reboot was performed in this task.

## Primary sources

- Apple XNU `csr.h`: [`CSR_ALLOW_UNTRUSTED_KEXTS` and `CSR_ALLOW_UNRESTRICTED_FS` bit definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/csr.h).
- Apple Support: [SIP can restrict root and privileged writes](https://support.apple.com/en-gb/102149).
- Apple Platform Security: [signed system volume protections](https://support.apple.com/guide/security/signed-system-volume-security-secd698747c9/web).
- OpenCore 1.0.8 `ocvalidate` requirements: [`csr-active-config` is four-byte plist Data](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Utilities/ocvalidate/README.md).
