# Ryzen 7700 CPPC candidate

This is an unbooted candidate for the observed Ryzen 7 7700, family19h/model61h/stepping2, 16logical CPUs, full-MSR CPPC, bare metal, Darwin25.6. It is not a claim that CPU power management is fixed on the machine.

The default mode only reads CPPC state and APERF/MPERF counters into IORegistry. `n44-cppc=1` requests autonomous balanced CPPC: hardware-advertised lowest/highest bounds, desired performance0, EPP128. `-n44cppcoff` disables the plugin. These are boot arguments, not an unprivileged runtime control interface. Do not combine it with another CPU policy driver; activation also checks for AMDRyzenCPUPowerManagement.

All16CPU snapshots must succeed before writes begin. The driver enables CPPC, rereads capabilities, prepares every request, writes, then verifies every CPU. Any failing phase triggers restoration of saved request/enable values, with restoration readback. Invalid capabilities have no guessed fallback limits. Only CPPC_ENABLE and CPPC_REQUEST can be written; reserved bits are preserved. Fused limits, boost enable, P-states, SMU, PPT/TDC/EDC, fan controls and CPU dispatch are not modified. Hardware autonomous scaling is the policy; this does not implement XNU preferred-core scheduling.

The safe writer is resolved by the existing Lilu KernelPatcher symbol API, without patching kernel instructions. No raw WRMSR or address-scanning fallback exists. Absence of that function leaves the driver read-only. The IOKit service matches the observed ACPI processor-index0 node and joins its power tree; power-driver registration failure aborts startup before policy writes. Power callbacks only publish awake/resume flags; the workloop performs resume checks and restores/reapplies the policy. Stop cancels its timer under an IOCommandGate and attempts restoration. The Lilu plugin cannot safely be unloaded after registering its callback; recovery is by disabling it in the boot EFI and rebooting.

Build dependencies are the existing MacKernelSDK staging and official Lilu source commit `0249c3a918c68a43891350f35fded615b1575776` (v1.7.3development, matching the installed1.7.3). The build includes Lilu's copyright/license in the artifact. No additional kext is installed by the build:

```sh
python3 tools/baremetal/navi44-cppc/build.py \
  --sdk research/builds/macos-20261027/sdk/MacKernelSDK \
  --lilu research/ext/Lilu-1.7.3-audit/source \
  --out research/builds/macos-20261028/unified/cppc-candidate
clang++ -std=c++17 -Wall -Wextra -Werror -O1 \
  -fsanitize=address,undefined tools/baremetal/navi44-cppc/test.cpp \
  -o research/builds/macos-20261028/unified/test-cppc
research/builds/macos-20261028/unified/test-cppc
```

The transaction suite injects every single read/write fault at every CPU, dropped writes, inconsistent readback, invalid capabilities, missing CPUs, wrong profiles, and restoration failure/retry. Those checks prove the transaction logic with simulated registers, not the kernel lifecycle or real frequency/energy behavior. A real boot must confirm callback resolution, matching, all16snapshots, activation/readback and idle/load behavior. `check.py` reads IORegistry after that boot and fails if activation is not verified; kext presence alone is insufficient. Its APERF/MPERF ratios are relative busy-cycle frequencies, not power or C-state measurements.

Register references: [Linux MSR definitions](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/msr-index.h), [AMD pstate documentation](https://docs.kernel.org/admin-guide/pm/amd-pstate.html), [FreeBSD implementation](https://github.com/freebsd/freebsd-src/blob/main/sys/x86/cpufreq/hwpstate_amd.c). The code here is an independent transaction implementation; these references were used to check register numbers, bitfields and autonomous-request semantics.
