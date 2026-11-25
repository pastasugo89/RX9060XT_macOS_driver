Mesa patches (RADV Darwin / macOS port for the Navi 48 native kext)
===================================================================

These patches add a macOS backend to Mesa's RADV Vulkan driver so that it
talks to the Navi48 bring-up kext (user-client ABI "N48N") instead of a DRM
node. Only our changes are included, not the Mesa tree.

Upstream base (apply on top of exactly this commit):
    mesa  f5cb8ee032adabef599ae892ec4e42d796b84da9   (VERSION 26.3.0-devel)
    https://gitlab.freedesktop.org/mesa/mesa.git

Licence: Mesa is MIT licensed. These patches are changes to Mesa and are
released under the same licence (see Mesa's docs/license.rst and
third-party/THIRD-PARTY-LICENSES.txt).

Apply:
    git clone https://gitlab.freedesktop.org/mesa/mesa.git
    cd mesa
    git checkout f5cb8ee032adabef599ae892ec4e42d796b84da9
    git am /path/to/Navi48-MacOS/mesa-patches/000[1-9]-*.patch /path/to/Navi48-MacOS/mesa-patches/0010-*.patch
    git apply /path/to/Navi48-MacOS/mesa-patches/0011-*.patch /path/to/Navi48-MacOS/mesa-patches/0012-*.patch
(The patch author and date headers of 0001-0010 are placeholders; "git am"
works as-is for those. 0011 and 0012 are plain git diffs without a mail header:
"git am" rejects them with "Patch format detection failed", so apply them with
"git apply" (or "patch -p1") after 0010.)

Order matters: 0001 .. 0012. The kext ABI header that patches 0002-0004 mirror
is src/navi48-bringup/src/Navi48NativeABI.h in this repository; Mesa's copy and
the kext's copy must be the same ABI version (currently 1.11 or newer).

0010 (rx9060xt-metal-driver) adds a compile-time ASIC profile to the Darwin
backend (src/amd/common/darwin/ac_darwin_asic.h) and a gfx1200 canned record:
the default is now Navi 44 / RX 9060 XT (gfx1200, PCI 0x7590). Build Mesa with
-DRADV_DARWIN_NAVI48 (e.g. -Dc_args=-DRADV_DARWIN_NAVI48) for the original
Navi 48 behaviour. It must match the kext's `make ASIC=...`.

0012 (radv-cmd-buffer-teardown-after-failed-cmd-stream) changes
src/amd/vulkan/radv_cmd_buffer.c and src/amd/vulkan/tools/radv_rra.c: the
msrtss_transients list is initialised before the command stream is created,
the accel_struct_buffers set is NULL-checked after creation, and
radv_rra_accel_struct_buffers_unref() accepts a NULL set. It addresses the
radv_destroy_cmd_buffer() fault seen on 2026-11-17 when command stream
creation fails.
