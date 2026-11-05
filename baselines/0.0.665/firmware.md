# Firmware inputs of the navi44 kext (0.0.665 baseline)

The blobs are AMD's and are not in this repository. This file records what the kernel embeds, the
SHA-256 of each file, and where the same files are referenced upstream, so a reproducer can fetch
and check them. No blob is copied here.

## The ten embedded blobs

`cobalt64/src/navi48-bringup/Makefile` (ASIC defaults to `navi44`) embeds every `firmware/*.bin`
and requires exactly these ten names. They come from linux-firmware `amdgpu/`.

| file (firmware/) | bytes | sha256 |
|---|---:|---|
| gc_12_0_0_imu.bin | 132352 | aa15e5b3156bffc45e0c50bccbcd364fbd3f958531b695b7487a803d780b8328 |
| gc_12_0_0_me.bin | 463392 | 17487eb283d479ddb6331bc850a623e3f1217907e25aa5acf89602fb3eaeaf94 |
| gc_12_0_0_mec.bin | 455648 | 28b1e5bae440044887bab53a374db7bb971f7cc2780ab2b55c561e19f24d7fac |
| gc_12_0_0_pfp.bin | 354912 | 5ec7a4341c22676da98d64cbc8dc5d820f3f13f199ea7e572f4064de406e715c |
| gc_12_0_0_rlc.bin | 150704 | 6436b582734a413456fff3d3c7195e71cc9e78a7ed31ee21c83ffd6fae1ad186 |
| gc_12_0_0_uni_mes.bin | 734432 | ee058438467479d05d3d54ec9b0a592cac50bfa3834e65c6e90bd0e675c087d1 |
| psp_14_0_2_sos.bin | 421216 | 7b538448b57d4f9dd06b2eea90d4f86a16e65e3027cdecee8db71c2c5f1fa243 |
| psp_14_0_2_ta.bin | 274668 | 81d55b4e59bbb91c95ce4edf546c3870275ef426d0279970c3e7e33e62a68115 |
| sdma_7_0_0.bin | 47872 | beaafb53993a106edd392392d5896245ae2a957c6d0f495d0002eec72ad8ad38 |
| smu_14_0_2.bin | 333236 | 1b2054e3f710d1ab8dbdf6ff35914ad376b51caa6337831260c955add874b2ee |

Upstream reference: `tools/fetch-firmware.sh` (tracked, `cobalt64/tools/fetch-firmware.sh`) holds
the same ten SHA-256 values in its `BLOBS_NAVI44` table and says they are the copies of
linux-firmware 20260916 that Linux amdgpu loaded on the reference card. All ten preserved files
match that table exactly (checked). The script prints `ok` or `DIFFERS` per blob:

```
git clone https://gitlab.com/kernel-firmware/linux-firmware.git     # or the kernel.org mirror
ASIC=navi44 cobalt64/tools/fetch-firmware.sh <linux-firmware checkout>
```

Firmware versions the reference card reported at run time (`research/hw_dump/firmware_info.txt`,
tracked): ME 0x00000c12, PFP 0x00000c76, MEC 0x00000d7a, RLC 0x00bde160, IMU 0x0c2c2500,
SOS 0x003b0f0d, SMC 102.71.0, SDMA0 0x00798e96, MES_KIQ 0x00000093.

The linux-firmware commit itself was not checked: no network download was made for this record.
Its date label (20260916) is the only pin the repository gives.

## Files in the preserved firmware directory that are not embedded

- `LICENSE.amdgpu`: AMD's redistribution licence, copied by `fetch-firmware.sh` from linux-firmware.
  sha256 572872598565dc3513470de971a32bf9db301f47afeef3636345eadae33b2eee (the preserved copy).
- `WHENCE.shader_vadd_ir.txt`: a project note, not a linux-firmware WHENCE. It says the blob
  `shader_vadd_ir.bin` is a project compute-test artifact (640 bytes, extracted from a gfx1200 HSACO),
  under the project licence. The Makefile does not read it. sha256 3e54a3238b8b1a1d96da02d30072127b6ec42a48bf28fec79130eb56fdfd456d.

## Optional blobs that were absent (zero-length stubs)

The preserved builds did not have these files, so the Makefile embedded zero-length blobs under the
same symbols (build logs: "embedded an empty blob (optional, fail-closed)"). A reproducer must also
leave them absent:

`firmware/shadercache.bin`, `firmware/shader_blit_copy_gfx1201.bin`,
`firmware/shader_blit_copy_offen_gfx1201.bin`, `firmware/shader_blit_diag_gfx1201.bin`,
`firmware/shader_blit_diagmin_gfx1201.bin`.

They derive from Apple's shader binaries and are deliberately not in the repository (see
`cobalt64/BUILDING.md`).

## Project shader blobs (tracked, not vendor firmware)

`shaders/store_magic.bin`, `shaders/store_magic_hsa.bin` and `shaders/vadd_ir.bin` are tracked in the
repository and embedded from there; they are identical in the preserved trees.

## Documentation gap found

`cobalt64/BUILDING.md` lists the Navi48 set (`gc_12_0_1_*`, `psp_14_0_3_*`, `sdma_7_0_1`,
`smu_14_0_3`) as "the ten files the kext embeds". That is correct only for `ASIC=navi48`. The default
`ASIC=navi44` embeds the set above.
