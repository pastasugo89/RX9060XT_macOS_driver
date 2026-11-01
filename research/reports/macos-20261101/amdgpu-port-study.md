# Feasibility study: reusing Linux amdgpu on macOS through a Linux-compatibility layer

Date: 2026-11-01. Project: `rx9060xt_metal_driver` (Navi 44, PCI 1002:7590, gfx1200).
Paths are relative to the project root unless they are absolute.

Mode: read-only research. No sudo, nothing installed or loaded, no commits, no tracked file edited.
Clones exist only under `research/ext/amdgpu-port-study/`, which is ignored by git (`.gitignore:4`).
NootRX and NootedRed were not read. XeGfx code (including its NullMoth-derived parts) was read for architecture and licence facts only. NullMoth's own repository was not cloned. No code was copied.

Confidence labels: **[V]** verified by us in this session (command or URL given); **[R]** reported by the upstream author or a sub-agent and not reproduced here; **[E]** our estimate, not a measurement.

---

## 1. Summary

1. **Recommendation: do not port amdgpu as a whole (option a).** Keep the current custom bring-up (option c). Import selected MIT-licensed IP-block sequences (option b), starting with SDMA 7.0 and SMU 14.0.2, behind explicit go/no-go gates. Decide on Display Core only at the M8 gate. (Section 11.)
2. **Size and coupling [V].** amdgpu, DC, powerplay, KFD and RAS total about 1.32 M lines of C and headers, excluding about 5.05 M lines of generated register headers. One IP file drags in a large framework: `sdma_v7_0.c` is 1,830 lines, but its name-based call closure reaches 216 functions in 32 files (about 47 k lines). A port of "one IP block" is not one IP block.
3. **Licence [V].** Most amdgpu, DC, powerplay and KFD files are MIT/X11 or GPL-2.0 OR MIT. The GPL-2.0-only pieces a Linux-style stack needs are the dma-fence and dma-buf core (`drivers/dma-buf/dma-fence.c`, `dma-buf.c`) and some DRM helpers (`drm_managed.c` among them). A kext that ships them is GPL-2.0, which does not fit an MIT repository. The FSF lists APSL 2.0, the licence of XNU, as "a free software license, incompatible with the GNU GPL" (https://www.gnu.org/licenses/license-list.html). Get a legal opinion before any GPL code enters the kext.
4. **The reference point is young and mixed [V/R].** XeGfx, now renamed WTLIntelGfx, was created on 2026-10-21 and has one author. Only i915 has run on it, on one author-owned Arrow Lake laptop. Its top-level licence is BSD-2, but its NOTICE declares PolyForm Noncommercial for the plugin, two kexts and the NullMoth dma-buf files. It shows that a LinuxKPI-style layer can run GPU work and a desktop on one machine (self-reported). It does not port a display engine: frames are copied into the firmware framebuffer. Our 2026-10-25 report relays a README statement that every Arrow Lake test session panicked 15 s to 4 min after start; the current README reports runs of 1, 2, 4 and 5.6 h with one open panic (I-116). That report needs an update.
5. **The current desktop blocker is not in the hardware core [V].** `research/reports/unsupported_macos_comparison_20261025.md` records zero command buffers, zero transactions and zero frames at the pipe. That gap sits in the macOS integration layer (WindowServer to accelerator to submission). Every option has to build that layer, so changing the hardware core does not remove the blocker.
6. **The FreeBSD route is the nearest precedent [V/R].** drm-kmod's `master` (Linux 6.14 base, nine mainline releases behind 7.3) already contains the RDNA4 IP blocks. Its LinuxKPI is BSD-2 (about 74 k lines) but has no dma-fence, TTM or DRM scheduler. drm-kmod supplies them: dma-fence and dma-buf are GPL-2.0-only, TTM is dual GPL-2.0 OR MIT, and the scheduler is MIT text. The dma-fence part inherits the licence issue in Section 5 (Section 7).

---

## 2. Materials and reproducibility

| Path (under `research/ext/amdgpu-port-study/`) | Source | Ref | Method |
|---|---|---|---|
| `linux-v7.3` | https://github.com/torvalds/linux | tag `v7.3`, commit `c03c1a14507dfaf8b856c2608f9ac216021fc222` (2026-10-18) | `--depth 1 --filter=blob:none --sparse`; sparse set: `drivers/gpu/drm/{amd,ttm,scheduler,display}`, `drivers/dma-buf`, `include/drm`, `include/uapi/drm` |
| `XeGfx` | https://github.com/watchthelight-labs/WTLIntelGfx (old name redirects) | HEAD `ff64f8361a11a0995dae2cf5c4528752f388d5bb` (2026-10-31) | `--depth 1`; not built or run |
| `drm-kmod` | https://github.com/freebsd/drm-kmod | clone is branch `6.12-lts`, HEAD `1d054ae` (2026-10-07); `master` (`c16de0f9`, 2026-10-08, Linux 6.14 base) checked by raw URLs and tags | `--depth 1 --branch 6.12-lts` |
| `freebsd-src` | https://github.com/freebsd/freebsd-src | HEAD `8df5184` (2026-11-01) | `--depth 1 --filter=blob:none --sparse`; sparse set `sys/compat/linuxkpi` |

Other facts used:
- `research/src/linux` is **not** a usable source for these counts. It is a shallow clone of Linux 7.3-rc6 (commit `d6d3455`, 2026-10-11) with only 3,461 files, and `drivers/` holds just `gpu/`. TTM, the scheduler and dma-buf are missing there.
- Analysis scripts are in `/private/tmp/claude-501/-Users-pastasugo89/a637e4ae-3b5e-4976-88ef-fcdc0fea14ff/scratchpad/` (outside the project): `closure.py` (include closure), `callclosure.py` (name-based call closure), `extcalls.py`, `milestone_api.py`, `subsets.py`.
- Kernel release metadata: https://www.kernel.org/releases.json. Mainline 7.3 (2026-10-18); stable 7.3.1 and 7.2.14 (2026-10-30); longterm 6.18.60, 6.12.115, 6.6.161, 6.1.191, 5.15.224, 5.10.273.

---

## 3. Linux amdgpu: when RDNA4 arrived

Presence of key files per tag, checked with HTTP HEAD requests against `raw.githubusercontent.com` **[V]**:

| Tag | `gfx_v12_0.c` (GC 12) | `sdma_v7_0.c` (SDMA 7) | `dcn401` dirs (DCN 4.0.1) | `mes_v12_0.c` (MES 12) | `psp_v14_0.c` (PSP 14) | `smu_v14_0_2_ppt.c` (SMU 14.0.2) |
|---|---|---|---|---|---|---|
| v6.8 | absent | absent | absent | absent | absent | absent |
| v6.10 | absent | absent | absent | absent | present | present |
| v6.11 | **present** | **present** | **present** | (not checked) | (not checked) | (not checked) |
| v6.12 to v7.3 | present | present | present | present (from v6.12) | present | present |

- The GFX12 IP-block commit `52cb80c12e8a647aa9c903903d58916e6c1c4d38` ("drm/amdgpu: Add gfx v12_0 ip block support (v6)") is an ancestor of v6.11 (GitHub compare: "ahead", behind 0) and not of v6.10 ("diverged") **[V]**. The v6.11 tag commit is dated 2024-09-15 **[V]**.
- So GFX12 (gfx1200 and gfx1201), SDMA 7 and DCN 4.0.1 reached mainline in **Linux 6.11 (September 2024)**. Phoronix search summaries describe 6.11 as the first RDNA4 kernel; the Phoronix pages returned HTTP 403 to our fetch tool, so that wording is **[R]** only.
- **Navi 44 needs no PCI-ID entry [V].** The string `0x7590` is absent from every amdgpu PCI table checked (v6.8 to v7.3). In v7.3, `drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c:2193-2203` matches all AMD display-class devices through `PCI_ANY_ID` entries with `CHIP_IP_DISCOVERY`. Navi 44 is therefore recognised through IP discovery. The only Navi 4x ID-like constant in `drivers/gpu/drm/amd` is the Navi 48 kicker firmware entry `{0x7551, 0xC8}` at `amdgpu_ucode.c:35`. The `0x7550xxx` hits in `smu_v13_0_6_ppt.c` are firmware versions, not PCI IDs.
- Navi 44 versus Navi 48 (v7.3) **[V]**: `smu_v14_0_2_ppt.c` exists and there is no `smu_v14_0_3` file. The 14.0.3 path is referenced from several files, including `smu_v14_0.c`, `smu_v14_0_2_ppt.c`, `amdgpu_discovery.c` and `amdgpu_psp.c`. This matches the GC 12.0.0/12.0.1 split in `research/reports/01-linux-amdgpu-bringup.md`.
- **Maintenance pace [V].** `gfx_v12_0.c` received 49 commits in the 12 months to 2026-11-01 (GitHub API, path filter). Expect a rebase every few months if we track upstream.
- "Stabilised" cannot be measured from source. Commit churn above is a proxy only.

---

## 4. Size, composition and coupling (v7.3)

### 4.1 Size **[V]** (C and headers; `wc -l` over `*.c`/`*.h`)

| Subsystem | Files | Lines | Notes |
|---|---|---|---|
| `amd/amdgpu` | 634 | 383,524 | core, IP blocks, uAPI |
| `amd/display` | 1,309 | 686,582 | DC, DML and DML2, HWSS, DMUB, `amdgpu_dm` (about 80 k) |
| `amd/pm` | 274 | 186,150 | powerplay and swsmu |
| `amd/amdkfd` | 62 | 48,727 | compute (not needed for Metal) |
| `amd/ras` | 56 | 14,882 | RAS |
| `amd/include/asic_reg` | 494 | 5,052,474 | generated register headers |
| DRM core, top level | 102 | 86,069 | `drm_*.c` |
| `drm/ttm` | 26 | 11,618 | includes tests |
| `drm/scheduler` | 10 | 5,396 | includes tests |
| `drm/display` (helpers) | 19 | 20,537 | |
| `drivers/dma-buf` | 20 | 10,089 | dma-fence, dma-buf, dma-resv |

Key files **[V]**: `gfx_v12_0.c` 5,664 lines; `mes_v12_0.c` 2,157; `sdma_v7_0.c` 1,830; `smu_v14_0_2_ppt.c` 2,995; `psp_v14_0.c` 705; `gmc_v12_0.c` 1,175; `imu_v12_0.c` 407; `ih_v7_0.c` 875; `amdgpu_discovery.c` 3,760; `amdgpu_device.c` 6,886; `amdgpu_psp.c` 5,075; `amdgpu_ttm.c` 3,012. The 44 DCN 4.0.1 files total 24,167 lines.

DC blocks (approximate, C and headers) **[V]**: DML about 86 k; DML2 about 83 k; HWSS about 37 k; DMUB about 21 k; `amdgpu_dm` about 80 k; DCN 4.0.1-specific about 24 k.

### 4.2 What one IP file pulls in **[V, approximate]**

Name-based call closure (`callclosure.py`). It ignores calls through function-pointer tables, so the true closure is larger in many cases.

| Start file | Own functions | Transitive functions | .c files reached | Lines in those files |
|---|---|---|---|---|
| `sdma_v7_0.c` | 61 | 216 | 32 | 46,585 |
| `psp_v14_0.c` | 26 | 71 | 11 | 23,521 |
| `smu_v14_0_2_ppt.c` | 54 | 93 | 4 | 6,600 (lower bound) |
| `mes_v12_0.c` | 56 | 157 | 24 | 35,942 |
| `gfx_v12_0.c` | 174 | 449 | 45 | 86,672 |

Include closure (non-generated files; generated register headers listed separately): `gfx_v12_0.c` pulls 123 files and 62 k lines, plus two generated headers of 51.6 k lines. `amdgpu_dm.c` pulls 184 files and 74 k lines.

### 4.3 Kernel-side API surface **[V, crude]**

- Across amdgpu, amdkfd, pm and ras: about 2,450 distinct external identifiers called (regex; this is an upper bound, since it also catches macros and inlines), in 35 k call sites. The biggest prefixes are `drm_*` (about 233), `dma_*` (75), `ttm_*` (53), `pci_*` (53), `pm_*` (31), `dev_*` (22) and `xa_*` (21).
- For `sdma_v7_0.c` alone: 25 distinct external identifiers (`atomic64_set`, `cpu_to_le32`, `dev_err`, `dma_fence_put`, `dma_fence_wait_timeout`, `drm_printf`, `kcalloc`, `kfree`, `le32_to_cpu`, `lower_32_bits`, `memcpy`, `memset`, `msleep`, `order_base_2`, `udelay`, `upper_32_bits`, and a few more).
- For `sdma_v7_0.c` plus `psp_v14_0.c` plus `smu_v14_0_2_ppt.c`: 58 distinct identifiers.

Reading: the OS-level surface for a small milestone is small. The real cost sits in amdgpu's internal structures (`amdgpu_device`, rings, IBs, GART/VM, IP-block registration). That is the part a LinuxKPI layer does not replace.

### 4.4 User-space ABI **[V]**

`include/uapi/drm/amdgpu_drm.h` (v7.3): 1,701 lines, 21 `DRM_IOCTL_AMDGPU_*` commands, 64 `drm_amdgpu_*` structures, 10 CS chunk IDs. Our Darwin RADV port already has a DRM-style shim (`research/ext/mesa-darwin/src/amd/common/darwin/ac_darwin_drm.c`, 926 lines, plus `ac_darwin_kext.c` 678 lines and `ac_darwin_iokit.c` 114 lines). It exposes `acd_*` calls that mirror libdrm-amdgpu, over the N48N kext ABI. The `radv_amdgpu_*` winsys in the same tree is upstream code.

---

## 5. Licences

### 5.1 Linux components **[V]** (SPDX tags, plus the MIT/X11 permission text where a file has no tag)

| Component | Production files and licence mix | Implication |
|---|---|---|
| `amd/amdgpu` | 46 SPDX MIT; 10 GPL-2.0 OR MIT; 2 GPL-2.0+; 1 GPL-2.0-only; 575 untagged files all carry MIT/X11 text. GPL-only files: `amdgpu_vkms.c/.h`, `amdgpu_atpx_handler.c` (not needed for a port) | Core is MIT. Keep copyright notices. |
| `amd/display` (DC) | 468 SPDX MIT; 26 GPL-2.0 OR MIT; 815 untagged, of which 812 carry MIT/X11 text | MIT in practice. |
| `amd/pm` (powerplay, swsmu) | 274 files, untagged, all MIT/X11 text | MIT. |
| `amd/amdkfd` | 51 GPL-2.0 OR MIT; 11 untagged MIT text | Dual. Choose MIT. |
| `drm/ttm` (production) | 12 GPL-2.0 OR MIT; 1 MIT; 3 untagged MIT text | Dual. Choose MIT. The 10 `GPL-2.0 AND MIT` files are in `ttm/tests`. |
| `drm/scheduler` (production) | 2 SPDX MIT; 4 untagged MIT text. The 4 GPL-2.0 files are in `scheduler/tests` | MIT. |
| `drivers/dma-buf` | `dma-fence.c` and `dma-buf.c` are GPL-2.0-only; 9 GPL-2.0-only, 5 GPL-2.0, 5 MIT in total; `dma-resv.c` is MIT | **GPL-2.0-only core. This is the hard constraint.** |
| DRM core, top level (102 files) | 18 files are GPL-2.0 or GPL-2.0-or-later with no MIT option, including `drm_managed.c` (GPL-2.0), `drm_sysfs.c`, `drm_lease.c`, `drm_writeback.c`, `drm_gem_*_helper.c`, `drm_fb_dma_helper.c`, `drm_of.c`, `drm_trace.h`. Files amdgpu uses most, such as `drm_gem.c`, `drm_ioctl.c`, `drm_drv.c`, `drm_file.c`, `drm_prime.c`, `drm_syncobj.c`, `drm_mm.c`, carry MIT/X11 text. `drm_exec.c` is GPL-2.0 OR MIT; `drm_gpuvm.c` is GPL-2.0-only OR MIT | Mixed. Re-implement or accept GPL per file. |
| Module strings | `MODULE_LICENSE("GPL and additional rights")` in `amdgpu_drv.c:3251`, `ttm_module.c:92`, `sched_fence.c:242` | Kernel-module labelling only. It does not change copyright terms. |

### 5.2 Other components

| Component | Licence and source | Implication for us |
|---|---|---|
| XNU (macOS kernel) | APSL 2.0 (kernel headers, e.g. `bsd/kern/kern_exec.c`: "subject to the Apple Public Source License") [V] | FSF says APSL 2.0 is incompatible with GPL [V]. Open legal question for any GPL kext. |
| AMD firmware blobs | AMD licence: redistribution in binary form allowed, reverse engineering forbidden (project PIANO §17). Secondary sources agree [R]: Debian copyright metadata and a linux-firmware fork's `LICENSE.radeon` allow binary-form redistribution only and bar reverse engineering, decompilation and disassembly (https://metadata.ftp-master.debian.org/changelogs/non-free/f/firmware-nonfree/stable_firmware-amd-graphics.copyright; https://github.com/maunalinux/linux-firmware/blob/main/LICENSE.radeon). The upstream `LICENSE.amdgpu` text itself was not retrieved (kernel.org and GitLab returned 404) | Keep blobs out of git. Our `cobalt64/.gitignore:16` already ignores `src/navi48-bringup/src/fw/fw_*.c`. |
| Cobalt64 (our base) | MIT (`cobalt64/LICENSE`, "Navi48-MacOS contributors") [V]. `cobalt64/README.md` links the MIT badge. The repository root has no `LICENSE` file in the working tree [V] | Our code is MIT. A GPL-2.0 kext would change that for the combined work. |
| metal2vulkan | GPL-2.0-or-later OR LGPL-3.0-or-later (PIANO §11.3, §17) [R] | Use as an LGPL dynamic library, as the PIANO says. |
| NullMoth | PolyForm Noncommercial 1.0.0 (PIANO §17) [R] | Read architecture only. Do not copy. |
| XeGfx / WTLIntelGfx | BSD-2 top level; PolyForm Noncommercial for parts (Section 6.4) [V] | Do not copy any part. |
| NootRX / NootedRed | Excluded. Not read by this study. | |

### 5.3 Verdict per option

- **Option a (whole amdgpu):** requires shipping GPL-2.0-only code (dma-fence and dma-buf core) unless we re-implement those APIs clean-room, and the kext would then be GPL-2.0. Clean-room re-implementation of the API is a legal judgement, not a technical one. Counsel must decide before anyone starts.
- **Option b (MIT IP-block sequences):** clean for the IP-block files: `gfx_v12_0.c`, `sdma_v7_0.c`, `smu_v14_0_2_ppt.c`, `psp_v14_0.c`, `mes_v12_0.c`, `imu_v12_0.c` and `gmc_v12_0.c` carry no SPDX tag, MIT/X11 permission text and no GPL text **[V]**. Copy only with the copyright notice kept, and never pull in the GPL-only files of Section 5.1.
- **Option c:** no new licence exposure.

*This is an engineering reading of the licence texts, not legal advice.*

---

## 6. XeGfx (WTLIntelGfx): status, architecture, reusability

### 6.1 Repository facts

- https://github.com/watchthelight-labs/WTLIntelGfx. Created 2026-10-21 (02:36 UTC); last push 2026-10-31; 21 stars; 2 forks; licence key `bsd-2-clause` (GitHub API) **[V]**.
- HEAD `ff64f836` in our clone, dated 2026-10-31 **[V]**. Oldest commit `249683e6` (2026-10-21). 188 commits (GitHub API page count, **[V]**), one contributor, 10 prereleases v0.0.22 to v0.0.47, 12 issues (8 open) **[R]**.
- Description (GitHub API) **[V]**: "Intel Xe graphics acceleration for macOS and Hackintosh: Metal and Vulkan on Iris Xe, Intel Arc and Core Ultra (Meteor Lake, Arrow Lake) iGPUs. The Linux i915 driver on XNU through FreeBSD drm-kmod...".
- drm-kmod, the FreeBSD LinuxKPI and i915 are **fetched at build time and are not in the clone** [R] (`xkpi/NOTICE.md`).

### 6.2 Compatibility layer **[R]** (sub-agent read the source; LOC are repo lines; nothing was built)

| Area | Where | Lines | Status |
|---|---|---|---|
| Memory (malloc, UMA, pages, kva, DMAP) | `shim/src/fbsd/xg_mem.c`, `xg_vm.c` (1,990); `shim/src/xnu/xg_vm.cpp` (322) | 2,818 | Real on IOMalloc and IOBufferMemoryDescriptor; a few stubs |
| kmalloc, vmalloc, dma_alloc_coherent | external (FreeBSD LinuxKPI, fetched at build time) | n/a | external |
| dma-buf, dma-fence, TTM, drm_sched | `xkpi/src/dmabuf/` (PolyForm files); core from drm-kmod (external) | n/a | dma-buf replaced; drm_sched absent |
| Workqueue, taskqueue, kthread, callouts | `shim/src/fbsd/xg_task.c` (345), `xg_sched.c` (921), `xg_kern.c` (401) | 1,667 | Real: kernel threads on XNU threads |
| Locks, RCU | `shim/src/fbsd/xg_lock.c` | 867 | Real. Custom spin buckets; panics when a spin passes 150 ms with IRQs off |
| IRQ, MSI, PCI config and BARs | `xg_pci.c` (3,253), `shim/src/xnu/xg_pci.cpp` (402) | 3,655 | Real on IOPCIDevice, IOWorkLoop, IOInterruptEventSource. BARs are never sized |
| request_firmware | `shim/src/xnu/xg_misc.cpp` (129) | 129 | One blob (`mtl_guc_70.bin`), embedded table checked first |
| DMA mapping and IOMMU | `xg_dma.c` (472), `xg_dma.cpp` (61) | 533 | Partial: 1:1 mapping only; the IOMMU check has no caller |
| devfs nodes, fds, DRM ioctls | `xg_fd.c` (1,479), `xg_fd.cpp` (438) | 1,917 | Real for open, ioctl, read, write, select. No `mmap(2)` |
| KMS and display | `kexts/XeGfxIntelFB`, `kexts/NMIntelFB` | 920 | No KMS. i915 display is off by default. IOFramebuffer kexts |
| sysctl, sysfs, stubs | `shim/src/fbsd/xg_misc.c` (1,836) | 1,836 | Private sysctl is real; no sysfs; about nine explicit stub functions |

Total of the shim files listed: about 13.4 k lines (our sum). That excludes the external LinuxKPI and drm-kmod. The author's own baseline (`docs/kpi-todo-baseline.txt`, grep-based) reports 267 of 398 symbols present **[R]**.

### 6.3 Integration with macOS **[V/R]**

- Classes (sub-agent, **[R]**): `XeGfxResident` (IOService); `NMIntelFB` (IOFramebuffer; matches any Intel PCI device, `IOPCIMatch` 0x8086 with any device ID, then looks up 84 generated display-version IDs **[V]**); `XeGfxIntelFramebuffer` (IONDRVFramebuffer, device 8086:7D67 only); `NMXAccel` (IOGraphicsAccelerator2 with IOAccel contexts); `NVDADeviceControl` (subclass of `AppleGraphicsDeviceControl`); `IOAccelXeGfxDRMClient` (IOUserClient).
- **[V]** The sandbox refuses `/dev/dri` for WindowServer. libdrm therefore sends its ioctls through the accelerator's IOKit user client when the node is refused (README "Desktop", N-245 to N-260, 0.0.28). This is the same pattern as our `acd_*` shim over N48N.
- **[V]** "Frames reach the panel through a copy into the firmware's framebuffer, because macOS does not yet send display-pipe transactions to this GPU" (README "Desktop"). That is the same class of gap as our P2 "zero transactions".
- **[V]** `kext/Info.plist:49` declares `com.apple.kpi.unsupported`, while `docs/HOW-IT-WORKS.md:34` says "Public KPIs only. No `com.apple.kpi.private`". The two statements conflict, and the first is a sustainability risk.

### 6.4 Licence **[V]**

- `LICENSE` is BSD-2-Clause (copyright watchthelight, 2026) **[V]**.
- `NOTICE` declares **PolyForm Noncommercial 1.0.0** for `plugin/`, `kexts/XeGfxAccel/`, `kexts/XeGfxAGDC/`, `userland/patches/*-macos.patch` (NullMoth's Darwin patches), and "the NullMoth dma-buf files" (`NOTICE:28-35`) **[V]**. Our grep counts: 32 PolyForm-tagged files in `kexts/` and 24 in `plugin/` **[V]**.
- Per-file headers in `xkpi/src/dmabuf/` do not name PolyForm; only NOTICE does **[V]**. That ambiguity matters.
- PolyForm Noncommercial bars commercial use and is not GPL-compatible. The GitHub badge (BSD-2) therefore overstates the licence of the whole repository.

### 6.5 Maturity and crashes **[V, from the live README and CHANGELOG]**

- 0.0.42 crashed "at about 15 to 20 s" with the I-116 rendezvous panic (CHANGELOG, 0.0.42 entry).
- Later runs, self-reported (README "Status"): desktop for 1 h (N-296), 2 h (N-297), 4 h (N-298) and 5.6 h (N-299) with the NVRAM trace off, while a script wrote about 225 GB and ran Metal draws. N-304 hit I-116 after 4 h 19 min.
- Still open: one panic under heavy disk reads (README line 29). Tracked in WTLNvidiaGfx issues #12 and #18.
- Our 2026-10-25 report relays the README of that date, which said that all Arrow Lake test sessions ended in a kernel panic 15 s to 4 min after start. The current README and CHANGELOG describe multi-hour runs. We did not check the older README revision, but `research/reports/unsupported_macos_comparison_20261025.md` should be corrected to the current account.

### 6.6 Generic or i915-specific **[R]**

- i915-specific: `xg_kext.cpp` (42 name hits), `xg_dma.c` (38), `xg_i915.h` (28), `xg_misc.c` (21). `xkpi/src/i915` is 10,918 lines, of which 10,320 are modified upstream MIT files.
- Generic: `xg_fd`, `xg_lock`, `xg_sched`, `xg_task`, `xg_mem`, most of `xg_vm` and `xg_pci`, and the firmware and sysctl code in `xg_misc`.
- NullMoth-derived (PolyForm): `kexts/XeGfxAccel` (3,020 lines in `nvrm-accel.cpp`), `plugin/` (about 30 k lines).
- For amdgpu, XeGfx has the TTM and dma-fence core (external), a one-blob firmware loader, and a device-node/ioctl path. It lacks drm_sched use, IP-block and PSP/SMU/MES registration, multi-blob firmware, the amdgpu uAPI and the device model. RADV appears only as a build patch (`userland/patches/mesa-macos.patch` changes RADV's meson build and the addrlib includes) and as a vendor branch in the plugin (`plugin/NVMTLDevice.m:620`, "AMD, RADV"). The repository contains no RADV winsys or amdgpu uAPI code.

### 6.7 What we can learn, and what we cannot take

- Can learn (ideas, not code): the IOKit user-client ioctl route when the sandbox refuses `/dev/dri`; the sequencing of WindowServer, the accelerator and the Metal plugin; the shim split into generic and driver-specific parts.
- Cannot take: any file under `plugin/`, `kexts/XeGfxAccel/`, `kexts/XeGfxAGDC/`, `userland/patches/*-macos.patch` or the NullMoth dma-buf files (PolyForm Noncommercial).

---

## 7. FreeBSD drm-kmod, the FreeBSD LinuxKPI, and the OpenBSD and NetBSD ports

Sources: local clones (`drm-kmod`, `freebsd-src`), raw.githubusercontent.com and `git ls-remote` checks **[V]**, and a sub-agent survey including cvsweb and forum results **[R]**.

### 7.1 drm-kmod (https://github.com/freebsd/drm-kmod)
- Branches **[V]**: `master`, `6.12-lts`, `6.1-lts`, `6.6-lts`, `5.15-lts`, `5.10-lts`, `5.4-lts`, `ast`, `i915_audio`, and older `*-stable` and `*-fbsd` branches. Tags run up to `drm_v6.14`.
- **The newest Linux base is `master`, which is Linux 6.14**: HEAD `c16de0f9` (2026-10-08, "drm: Reduce diff with Linux 6.14 [FreeBSD]"). Tag `drm_v6.14` peels to the same commit **[V]**.
- `6.12-lts` (HEAD `1d054ae`, 2026-10-07) is the LTS line at 6.12.110 **[R]**. Our clone at `research/ext/amdgpu-port-study/drm-kmod` is this branch, so it is not the newest.
- RDNA4 IP files **[V]** (raw HEAD checks). On `master`, `drivers/gpu/drm/amd/amdgpu/` has `gfx_v12_0.c`, `sdma_v7_0.c`, `vcn_v5_0_0.c`, `psp_v14_0.c`, `mes_v12_0.c`, `gmc_v12_0.c` and `imu_v12_0.c`; `pm/swsmu/smu14/smu_v14_0_2_ppt.c` exists; DCN 4.0.1 is at `display/dc/hubp/dcn401/`. `6.12-lts` has the same files, with DCN 4.0.1 under `display/dc/dcn401/`. Neither branch has `smu_v14_0_3_ppt.c`, as in Linux 7.3. `0x7590`, `0x7550` and `0x7551` are absent from `amdgpu_drv.c` on both branches. Binding is presumably through the `CHIP_IP_DISCOVERY` catch-all entries, as in Linux (untested) **[R]**.
- Lag **[V]**: `master` (6.14) is nine mainline releases behind 7.3 (6.15 through 7.3). `6.12-lts` is eleven behind **[derived]**. GFX12 entered mainline in 6.11 (Section 3), so both bases already contain the RDNA4 IP blocks. The gap lies in later fixes and features.
- Licences, from SPDX counts on the `6.12-lts` clone **[R]**: amdgpu has 552 files: 26 MIT, 4 GPL-2.0 OR MIT, 1 GPL-2.0, 1 GPL-2.0+, and 550 with MIT text. DC has 1,047 files: 224 MIT, 940 with MIT text. pm has 259 files, no SPDX, all MIT text. `drm/ttm` has 14 files, 11 of them GPL-2.0 OR MIT. `drm/scheduler` has 4 files with no SPDX. `dmabuf` has 8 files: 2 GPL-2.0-only, 1 MIT.
- GPL-only with no MIT option **[R]**: `amdgpu/cyan_skillfish_reg_init.c` (GPL-2.0), `amdgpu/amdgpu_vkms.h` (GPL-2.0+), `drm/drm_gem_ttm_helper.c` (GPL-2.0-or-later), `drm/drm_panel_backlight_quirks.c` and `drm/drm_writeback.c` (GPL-2.0), `dmabuf/sync_file.c` and `dmabuf/dma-fence-unwrap.c` (GPL-2.0-only).
- The amdgpu Makefile adds `linuxkpi/gplv2/include` to the include path (`amd/amdgpu/Makefile:1283-1284`). That directory holds the GPL-2.0-only `dma-fence-unwrap.h` **[R]**.
- drm-kmod has no LICENSE or COPYING file at the root **[R]**.

### 7.2 FreeBSD LinuxKPI (freebsd-src, `sys/compat/linuxkpi`)
- Sparse blobless clone, HEAD `8df5184` (2026-11-01) **[V]**.
- Size **[V]** (`.c` and `.h`): 465 files, 74,048 lines. The sub-agent counted 466 files, including 105 empty `dummy/include` files, with `common/include` at 40,653 lines and `common/src` at 33,436 lines **[R]**.
- Licence **[R]**: 128 SPDX lines: 122 BSD-2-Clause, 2 MIT, and 4 GPL dual (`siphash.h`, `linux_siphash.c`, `overflow.h`, `net_dim.h`). No GPL-only file. Most files carry untagged BSD text.
- API coverage **[V grep, R file list]**: workqueue (`common/include/linux/workqueue.h`, `common/src/linux_work.c`), kthread (`linux_kthread.c`), firmware (`linux_firmware.c`), PCI and DMA mapping (`linux_pci.c`), IRQ (`linux_interrupt.c`), timers (`linux_compat.c`), locking (`linux_lock.c`). **Not present:** dma-fence, dma-resv, TTM and the DRM scheduler (no `dma_fence`, `dma_resv` or `drm_sched` in the tree). They come from drm-kmod's own `dmabuf/`, `ttm/` and `drm/scheduler`.

### 7.3 OpenBSD (cvsweb, not cloned) **[R]**
- `sys/dev/pci/drm/amd/` exists, with `acp`, `amdgpu`, `amdkfd`, `amdxcp`, `display`, `include`, `lib`, `pm`, `powerplay` and `ras` **[V, cvsweb listing]**.
- `amdgpu/` has `gfx_v12_0.c`, `mes_v12_0.c`, `sdma_v7_0.c`, `vcn_v5_0_0.c` and `psp_v14_0.c` **[V, file names]**, plus `smu14/smu_v14_0_2_ppt.c` (sub-agent). There is no `smu_v14_0_3` file. The `display/dc/dcn401/` path returned 404, so the DCN 4.0.1 location is unconfirmed.
- File logs say "update drm to linux 6.18.16" (for example `amdgpu/mmhub_v3_3.c`, 2026-03-09). The newest change under `amd/` is dated 2026-10-27. Lag: five mainline releases behind 7.3, and 44 point releases behind 6.18.60 **[derived]**.
- PCI IDs and licences were not checked.

### 7.4 NetBSD
- cvsweb blocked the sub-agent with bot protection, and the GitHub mirror was not used. `sys/external/bsd/drm2/amdgpu/` has 7 glue files and no IP-block sources (partial look) **[R]**. The Linux base and RDNA4 coverage are **not determined**.

### 7.5 Public evidence (unverified) **[R]**
- FreeBSD forum GPU matrix: DRM 6.12 (drm-612-kmod) is needed on 15.1 and 16. RX 9060 and 9070 "work with lots of caveats". This was read from an image and not checked.
- Phoronix headline: "OpenBSD 7.7 Released … Initial Radeon RX 9070 GPU Support" (phoronix.com/news/OpenBSD-7.7-Released). The article was not read.

### 7.6 What this means for option (a)
- drm-kmod is the most current large amdgpu port on a BSD. Its `master` base already has the GFX12, SDMA 7, VCN 5, PSP 14, MES 12 and DCN 4.0.1 code, so option (a) could start from a tree that already contains the IP blocks.
- Its GPL content matches Linux: dma-fence and dma-buf (GPL-2.0-only), TTM (dual GPL-2.0 OR MIT) and some helpers. The scheduler is MIT text. Using dma-fence inherits the licence question in Section 5.
- The reusable part is the FreeBSD LinuxKPI: BSD-2 and about 74 k lines of generic Linux API. XeGfx adapts it to XNU with about 13 k lines (Section 6.2). This supports the shim estimate in Section 9 as the right order of magnitude. It is not a measurement of an amdgpu port.

### 7.7 Gaps
- NetBSD: nothing verified. OpenBSD: dates, licence and PCI IDs not checked.
- drm-kmod: `master` and `6.12-lts` were checked by raw URLs and tags, and the SPDX counts come from the `6.12-lts` clone. The GC 12.0.0 versus 12.0.1 split is not in the tree.

---

## 8. Our current code (for comparison)

| Item | Lines | Source | Note |
|---|---|---|---|
| `cobalt64/src/navi48-bringup` total | 451,258 in 390 files | **[V]** `wc -l` | |
| of which `src/fw` | 210,801 in 19 files | **[V]** | Generated firmware C arrays from `tools/embed-firmware.py`. Only `fw_table.h` is tracked. The `fw_*.c` files are ignored (`cobalt64/.gitignore:16`). Check before any commit. |
| of which `src/apple` | 79,676 (98 tracked files) | **[V]** | |
| of which `src/amd` | 38,308 (93 files) | **[V]** | Derived from mac-amdgpu (MIT), per PIANO §11.3 |
| of which `src/dcn` | 12,348 | **[V]** | |
| `research/ext/RDNA4FB-n44` | 4,123 | **[V]** | Display framebuffer kext |
| `cobalt64/tools/native/navi48accel` | 2,196 | **[V]** | |
| `cobalt64/tools/native/navi48metal` | 16,135 | **[V]** | |
| Darwin shim (`ac_darwin_*`) | 2,025 | **[V]** | `acd_*` over N48N |

Status (`STATO.md`, `COMPLETEZZA_DRIVER_GPU.md` §18): bring-up, compute and headless Metal (P0) work in the VM; accelerated desktop not yet achieved; P1/P2 show zero command buffers, transactions and frames (`research/reports/unsupported_macos_comparison_20261025.md`).

Roadmap durations (PIANO §14, nominal): M4 display 3 to 6 weeks; M5 accelerator and AGDC 4 to 8 weeks; M6 Metal bundle and WindowServer 6 to 10 weeks; M7 robustness and power, continuous; M8 full display, no estimate.

---

## 9. Options: scope, effort, risk

Effort is in person-weeks (pw). These are **[E] estimates** from the measurements in Sections 3 and 4 and the roadmap durations above. They are not measured.

| Option | What we must write | Code involved (measured) | Effort (pw, [E]) | Risk | What we get |
|---|---|---|---|---|---|
| **(a) Whole amdgpu on XNU**: LinuxKPI-class shim, DRM ioctl bridge, RADV through amdgpu uAPI | Shim for about 2,400 candidate identifiers (XeGfx's own generic shim is about 13 k lines for i915). FreeBSD LinuxKPI (BSD-2, about 74 k lines) can supply the generic part, leaving a FreeBSD-to-XNU adaptation layer; TTM, dma-fence and drm_sched glue; amdgpu bring-up through its own IP blocks; DC through a replacement for `amdgpu_dm` plus `dm_services`; IOUserClient bridge for 21 amdgpu ioctls plus DRM core ioctls | 1.32 M lines of C and headers in amd/, drm/ core about 0.13 M; per-IP closures 24 to 90 k lines | **37 to 74** (shim and OS glue 8 to 15, for 20 to 35 k lines; bring-up 12 to 20; DC 12 to 24; RADV bridge 3 to 5; TTM, fence and scheduler 2 to 10, depending on clean-room or GPL). Plus continuous rebase | **High**: GPL-2.0 core; APSL/GPL question; large surface; upstream churn | Full amdgpu IP coverage (power, reset, DC, uAPI) and RADV winsys unchanged; our N48N ABI can go. IOKit and WindowServer work still needed |
| **(b) Extract blocks into our kext (MIT sequences, our glue)** | SDMA 7 ring and copy/clear commands on our ring and VM code; SMU 14.0.2 telemetry, then clocks and fans; DCN 4.0.1 DC subset with our `dm_services`; VCN 5 | SDMA7 file 1.8 k lines (25 OS identifiers); SMU path 15.9 k lines (5 files: `smu_v14_0.c`, `smu_v14_0_2_ppt.c`, `smu_cmn.c`, `amdgpu_smu.c`, `amdgpu_pm.c`); DC subset: DML and DML2 170 k, HWSS 37 k, DMUB 21 k, DCN 4.0.1 24 k, core, link and clk_mgr about 74 k | SDMA **2 to 4**; SMU **4 to 8**; DC **12 to 24**; VCN **3 to 6** | SDMA low; SMU medium-high (PMFW ABI, thermal safety, PIANO §6.3 warning); DC high; VCN medium | Specific blocks at known cost. Keeps our architecture. Licence-clean if we import MIT files only |
| **(c) Stay with our bring-up**, adding blocks by hand from datasheets and Linux as a reference | SDMA, SMU, VCN written by us; display by register programming (RDNA4FB route); the same macOS integration as (a) and (b) | Our tree, Section 8 | PIANO M4 to M6 nominal 13 to 24 weeks (calendar, staffing unknown), plus SDMA, SMU and VCN from (b) at 9 to 18 pw. Total about **22 to 42** pw, excluding M8 display, which is decided at the gate | Medium: macOS integration unknown; more hand-written code per block | No new licence exposure. We keep control of the design |

Notes on the numbers:
- The "shim for 2,400 identifiers" count is an upper bound, not the real need. For SDMA 7 alone the external need is 25 identifiers; for SDMA, PSP and SMU together, 58. The bulk of the amdgpu cost is its internal structure, not the OS API.
- XeGfx's shim is about 13 k lines for i915, but it has no amdgpu IP blocks, no drm_sched and no multi-blob firmware. Its size is therefore not a yardstick for amdgpu.
- The XeGfx timeline (one author, 11 days, one laptop) is self-reported. It shows that a shim can get a GPU running fast on one machine. It says nothing about amdgpu's display engine, power management, or long-run stability.

---

## 10. Consequences for the rest of the stack

- **WindowServer, IOAccelerator, IOFramebuffer.** Every option needs the same accelerator and framebuffer work. XeGfx's route (IOGraphicsAccelerator2 plus an IOUserClient ioctl path, with the framebuffer copy) is a reference for that layer, not a reusable piece. Our P2 gap is in this layer.
- **Metal bundle.** Unchanged under (b) and (c). Under (a), it stays unchanged as long as RADV keeps working.
- **RADV winsys.** Our `radv_amdgpu_*` winsys is already upstream code. The custom part is the `acd_*` shim over N48N. Option (a) would replace the N48N protocol with the amdgpu uAPI (21 ioctls plus DRM core ioctls). That removes our custom ABI, but not the need for a shim.
- **Existing work.** Under (b) and (c), the bring-up, PSP firmware loading, MES, GART and discovery code stays. Under (a), the IP-block code is replaced by amdgpu's, and our IOKit, PCI, firmware and memory glue stays.

---

## 11. Recommendation and staged plan

**Decision:** keep (c) for the core. Run (b) for SDMA 7 and SMU 14.0.2 as the first two experiments. Do not adopt (a) now. Revisit DC at the M8 gate.

### Stage 0: licence and scope (about 1 week, no hardware)
- Write down the file-level import list: only MIT/X11 or dual-licensed files from Section 5.1. Exclude `dma-fence`, `dma-buf`, `drm_managed.c` and other GPL-only files.
- Ask counsel: (1) can a GPL-2.0 kext be distributed alongside an APSL-2.0 kernel; (2) is clean-room re-implementation of GPL APIs acceptable in our jurisdiction.
- Exit: written import list and licence opinion (or a decision to proceed without GPL code).

### Stage 1: SDMA 7 clear (2 to 4 weeks, test kext)
- Use the register sequences of `sdma_v7_0.c` (MIT, notice kept) inside `cobalt64/src/navi48-bringup`, with our ring, VM and firmware code. Do not pull in the amdgpu framework.
- **Go:** a pattern written by SDMA is read back by the CPU on three consecutive boots; no VMID fault; no panic; the import list has no GPL file.
- **No-go:** two boots with SDMA-related panics, or any GPL file needed. Then stop and reconsider.

### Stage 2: SMU 14.0.2 read-only (4 to 6 weeks)
- First `GetSmuVersion`, `GetDriverIfVersion` and metrics-table reads. Compare with sensors and with the Linux code path. Enable no features until thermal monitoring is validated (the PIANO §6.3 warning on `EnableAllSmuFeatures`).
- **Go:** metrics agree with sensors over a one-hour load test; no PMFW error codes; temperature and fan readings validated.
- **No-go:** any unexplained PMFW error, or a thermal event. Then keep SMU read-only.

### Stage 3: DC decision gate at M8 (about 2 weeks spike)
- Build the DCN 4.0.1 DML and HWSS subset as MIT code in a test build, list undefined symbols against our glue, and measure the `dm_services` surface.
- Decide between porting DC (12 to 24 pw) and register-level RDNA4FB.
- **Go to DC:** the spike shows a bounded symbol list and one stable mode on the panel.

### When to reconsider option (a)
Only if all of the following hold:
1. A second, independent machine reproduces an XeGfx-class desktop for hours (not the author's report alone).
2. Counsel clears a GPL-2.0 kext, or we accept GPL-2.0 for the kext.
3. A measured LinuxKPI shim compiles and runs the amdgpu PSP and GFX12 init path in a test kext without panics.

---

## 12. Questions to ask upstream

**XeGfx / WTLIntelGfx author**
1. Will the PolyForm Noncommercial parts be replaced, so that the repository is BSD-2 throughout? Do you accept MIT or BSD-only outside contributions?
2. `kext/Info.plist` declares `com.apple.kpi.unsupported`, but `docs/HOW-IT-WORKS.md` says "public KPIs only". Which is right?
3. Have you tried any AMD code path? Which LinuxKPI version and drm-kmod branch do you pin?
4. Is I-116 (a CPU not answering the rendezvous) correlated with the GPU IRQ path?
5. Why copy frames into the firmware framebuffer rather than present through display-pipe transactions? Is the missing piece the macOS side, as the README suggests?
6. Which IOAccel user-client calls does WindowServer require? Is that documented anywhere?

**FreeBSD drm-kmod and LinuxKPI maintainers**
1. Is `master` (Linux 6.14) going to move to 6.18 or 7.x? Has anyone run the GFX12 path (Navi 44 or 48) on FreeBSD, and where is the evidence?
2. Is the `linuxkpi/gplv2/include` entry on the amdgpu include path intentional? How is the GPL-2.0-only dma-buf and TTM content licensed for binary distribution?
3. Is the `CHIP_IP_DISCOVERY` catch-all binding exercised on gfx1200 (PCI 0x7590)?
4. Which firmware names does the FreeBSD port expect (`gc_12_0_0`, `psp_14_0_2`, `smu_14_0_2`), and how are they loaded?

---

## 13. Limits and unverified points

- Nothing was built, loaded or run. Sub-agent and author claims about XeGfx (Section 6.2 table, classes, performance and crashes) are **[R]** unless marked **[V]**.
- Release-note pages (Phoronix) returned 403. Release wording is from tag checks, not article text.
- Effort figures are **[E]**: judgement anchored to measured sizes and closures. They are not a plan of record.
- Closures are name-based. They miss calls through function-pointer tables, so they are lower bounds in many cases.
- The firmware licence text (`LICENSE.amdgpu`) could not be fetched from kernel.org or GitLab. The AMD licence summary comes from PIANO §17 and from secondary sources (Debian copyright metadata; a linux-firmware fork's `LICENSE.radeon`), not from the upstream file.
- The 2,450 identifier count is a regex upper bound.
- NetBSD was not determined (cvsweb blocked). OpenBSD dates and the public-evidence items in Section 7.5 are **[R]**.
- Pre-existing uncommitted change, not ours: `tools/baremetal/navi44-gpu-diagnostics/trial-cache-bundle.py` (modified, mtime 2026-10-29 18:44, last commit `0d698ec`). Left untouched.
- Concurrent changes, not ours: between 10:36 and 10:46 on 2026-11-01, other tracked files (`cobalt64/src/navi48-bringup/src/Navi48Bringup.{cpp,hpp}`, `Navi48UserClient.cpp`, `dcn/navi48_dcn.{cpp,hpp}`, `cobalt64/tools/pc/navi48test.c`, `tools/baremetal/navi44-desktop/build-production-contexts.py`) were modified and new paths were created (`dcn/navi48_refresh_pure.h`, `tests/refresh60_test.cpp`, a `0008-navi44-refresh-property` patch, `tools/baremetal/navi44-desktop/refresh-60/`). This study writes only under `research/ext/amdgpu-port-study/`, so these changes come from another session. They were left untouched and are not part of this study.
