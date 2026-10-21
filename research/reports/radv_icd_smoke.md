# RADV direct-ICD enumeration on RX 9060 XT — 20 October 2026

## Result

A bounded Vulkan API test reached the compiled Darwin RADV ICD from Tahoe
26.6.2 / build 25G83. The ICD reported one device named
`AMD Radeon RX 9060 XT (RADV GFX1200)`, three queue families including compute,
and `vkCreateDevice` plus
`vkGetDeviceQueue` succeeded. The test destroyed the Vulkan device and
instance without submitting commands; the device-owned queue was invalidated
on device destruction. This is an API/device-initialization
pass, not a compute-submission result or a Vulkan conformance result.

The name and Vulkan `vendorID/deviceID` come from RADV's canned Darwin ASIC
profile (`ACD_MARKETING_NAME`, `ACD_PCI_DEVICE_ID` in
`research/ext/mesa-darwin/src/amd/common/darwin/ac_darwin_asic.h`); RADV does
not read them from live PCI enumeration on macOS. The host independently
reports the passed-through physical function as `1002:7590`
(`lspci -nnk -s 03:00.0`), so the test confirms that the selected RADV profile
matches the known hardware ID.

The call path was a small C harness using `dlopen` and the ICD's public
`vk_icdGetInstanceProcAddr`, built with Apple clang and the Vulkan headers
already in Mesa's source tree. No Vulkan loader, `vulkaninfo`, CTS, or additional
dependency was installed. `vkCreateInstance` succeeded directly; physical
device enumeration reported API `1.4.363`. The matching profiled device exposed queue
family 0 flags `0xf` count 1, family 1 flags `0xe` count 4, and family 2 flags
`0x8` count 1. Device creation selected family 0, then destroyed the device
and instance.

The initial ordinary-user invocation failed before enumeration:
`IOServiceOpen(Navi48Bringup, 'N48N')` returned `0xe00002c1` (“needs root”).
With the existing default policy, this native user client admits an
administrator. The distinct non-root application path requires both
`navi48-apps=1` and `navi48-multisession=1` plus the kernel allow-list; those
settings were not enabled or changed. The successful invocation ran as the
guest administrator. Thus RADV currently has no demonstrated ordinary-user
access under the prepared boot configuration.

The kext identified ABI 1.12 / build 664 and VMID 8. Its native S1b positive
legs again passed, including 32/32 compute lanes, while the deliberate fault
leg was refused because `CP_DEBUG.CPG_UTCL1_ERROR_HALT_DISABLE` was clear
(`0x20400400`). No fault was forced and no `CP_DEBUG` value was changed. S1b
therefore remains partial: positive PASS, fault REFUSED, overall FAIL.

## Reproduction artifacts

- Harness: `tools/vm/radv-icd-smoke.c`.
- Compiled ICD: `/mnt/vm/builds/rx9060xt-build-validation.tar.gz`,
  `deps/mesa-darwin/build-macos/src/amd/vulkan/libvulkan_radeon.dylib`.
- Root/admin result: `/mnt/vm/images/macos-gpu-test/diagnostics/radv-icd-smoke-root.log`.
- Non-root refusal: `/mnt/vm/images/macos-gpu-test/diagnostics/radv-icd-smoke-user.log`.
- Device/stage properties: `/mnt/vm/images/macos-gpu-test/diagnostics/radv-icd-smoke-ioreg.txt`.
- Full guest serial: `/mnt/vm/images/macos-gpu-test/diagnostics/serial.log`.

The host compiler check passed with `cc -std=c11 -Wall -Wextra -Werror
-I research/ext/mesa-darwin/include -fsyntax-only`. The guest build passed
with Apple clang and `-Wall -Wextra -Werror`. The GPU smoke exited 0 in the
administrator run. The VM then shut macOS down normally: serial output records
`vfs_unmountall(system) end` followed by CPU halt; QEMU exited as the guest
powered off, so the QMP socket was already absent when checked. There is no
QEMU process or guest SSH listener; VFIO still owns GPU and audio functions and
`qemu-img check` reported no image errors. EFI has been restored to stage 17
with `native_s1b` disabled and interrupts disabled.

## Limits and next gate

This test does not submit a command buffer, allocate a Vulkan buffer, compile
or run a SPIR-V shader, or prove BO/submit/wait behavior through RADV. The
kernel's separate S1b positive compute test does not fill that Vulkan gap.
The next bounded RADV test should submit one tiny compute dispatch only after a
review of the native app/admin policy and the submission teardown path; it
must keep the existing positive S1b gate and leave the refused fault leg
untouched. `vulkaninfo`, CTS, application sandbox access, IOAccelerator, Metal,
and WindowServer remain unverified.
