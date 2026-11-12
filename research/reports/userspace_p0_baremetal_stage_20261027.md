# P0 userspace preparation for bare-metal test — 27 October 2026

## Result

A staging copy of the P0 VM userspace and aux artifacts is prepared at `research/ext/navi44-userspace-p0-stage-20261027/`. The installer is intentionally limited to the Metal bundle and two user tools. It defaults to a dry-run, refuses existing paths, verifies the payload before copying, and has a mock-tested uninstaller. No file was installed under `/Library` or `/usr/local`; no launchd job was loaded; no kext or GPU tool was run. The live machine remains unchanged by this work.

## P0 provenance and artifact checks

The inputs come from `research/ext/navi44-fast-metal-p0-reference-20261027/` and the extracted P0 bundle at `research/builds/macos-20261027/userspace/reference/Navi48Metal.bundle/`. The preserved bundle tar is SHA-256 `273def324b50e35b1d2ef579cbe5c9855ff0792a134d566090357e5734835789`; after path-safety checks, its extraction matched the staged bundle tree with `diff -qr` and no differences. The preserved reference manifest also records the P0 aux and user-tool hashes.

| Component | SHA-256 | Architecture / validation |
|---|---|---|
| `Navi48Metal` executable | `7edf8e319fe5408d5cb6220ee5bd571420200cd6128805ad345a50fb86aeed2d` | x86_64; bundle signature verifies |
| `libn48xlate.dylib` | `b8e6d1883f18c79e61d239cbb9804300cf5ec9ef1062bff280e8e0a52ba4ee47` | x86_64 |
| `libvulkan_radeon.dylib` | `bddb5757d03eaf2200c2df5baec206e77913311d6941ecdfa3d28c1c6eedde3b` | x86_64 |
| `Navi48Accel` aux 0.0.7 executable | `4d5e257d880ed5fe076a933159ee6ef4d4a8d5bc93f067e3e7cf07512a7d3b8c` | x86_64; kext signature verifies |
| `mtlprobe` | `3177783fcb9f0dcb5ceaf3b01f90d279a4f80fd3e528a7c97d521d04e4d75b70` | universal x86_64 + arm64 |
| `n48nub` | `d64a430c2d3c706437986f8822d7f580502ecc2579dc2ffd869df11882052e52` | x86_64 |
| daemon `metal2vulkan` | `fb61e6ab850d01a6bcfeb9add65de46d0e932293c3ecabcd238c5c975628a3e1` | x86_64 |
| daemon `spirv-val` | `72848faaff166192ad41e375f94affb24a7d6764eefe36ad8bf04fe422d4c96d` | x86_64 |

The bundle contains 35 `.spv` and 35 `.meta.json` cache entries. I ran the staged P0 `spirv-val` v2026.4 against all 35 SPIR-V files with `--target-env vulkan1.2`; all passed. This was CPU-only validation and did not access the GPU. The translator daemon’s shell passed `bash -n`, and `pc-translate.py` passed Python AST parsing.

One packaging detail matters for later daemon use: the preserved tar stores `pc-translate.sh`, `pc-translate.py`, `n48-llvm-dis`, `n48-spirv-val-stub`, `metal2vulkan`, and `spirv-val` as mode `0644`. The P0 deploy script explicitly chmods those files to `0755` at `tools/vm/deploy-metal-stack.sh:232-249`. The staging copy now has those executable bits, and `verify-stage.sh` checks them. The executable-bit correction changes no file content or SHA-256.

## Offline install/rollback harness

`userspace-apply.sh` maps only:

- P0 bundle → `/Library/GPUBundles/Navi48Metal.bundle`
- `mtlprobe` → `~/navi48-staging/mtlprobe`
- `n48nub` → `~/n48-metal/n48nub`

It requires explicit `--root` and user-home-relative paths. Without `--apply` it is read-only. With `--apply`, it refuses any existing destination, creates missing user-tool directories, verifies copied content and bundle signature, and records a small rollback receipt. `--uninstall --apply` removes only paths that still match the staged P0 bytes; it preserves modified content and unrelated files. Its uninstaller never unloads the aux kext or withdraws the nub. The script does not install the aux kext, translator files, LaunchDaemon, boot arguments, or services.

Offline results:

- `verify-stage.sh`: PASS for payload SHA-256 manifest, known P0 hashes, code signatures, three plists, x86_64/universal architectures, executable modes, shell syntax, and 35+35 cache counts.
- `mock-transaction-test.sh`: PASS for dry-run immutability; copying only the bundle and two tools; refusal to uninstall modified content; preservation of unrelated notes and pre-existing directories; removal of only created directories when empty; and refusal to overwrite an existing bundle before copying anything.
- Real-root dry-run `userspace-apply.sh --root / --user-home Users/pastasugo89`: PASS; it reported the P0 bundle/tools as the planned payload and excluded aux and daemon. It was **not** run with `--apply`.

The mock runs as the current unprivileged uid, so it checks that newly created tool directories inherit the mock home owner. It does not execute the installer’s root-only `chown` branch (`root:wheel` bundle and original home owner for tools/receipt). That branch is present for the explicitly delegated local-Terminal command documented in the stage README, but has not been run here.

## What is and is not ready to deploy

The staged P0 bundle and tools are ready for a later, explicitly authorized **file-only** deployment after the parent’s EFI, recovery, display, and thermal preflight. This does not establish that accelerated Metal will load or run on this hardware. `n48nub` itself publishes a device when executed, and `mtlprobe` reaches GPU services; neither was executed.

The aux kext is preserved, signed, and staged for inspection, but it is not included in the installer. Installing it needs `kmutil libraries`, a separate `kmutil load`, and possible user approval. P0 used `csr-active-config=3`; the current machine reports CSR config `00 00 00 00` and SIP enabled. The reconstructed `INSTALL.md` expressly says never to use `kmutil install --update-all`. The effects of the current SIP state on aux loading have not been established.

The translator payload is preserved and made executable in staging, but its LaunchDaemon is not installed or loaded. The plist has `RunAtLoad=true`, `KeepAlive=true`, and runs as `nobody`; it writes to `/private/var/tmp/n48m-spv` and its own state/log directory. P0’s T2 quad hot-swap depended on generated probe SPIR-V in `/private/var/tmp/n48m-spv`; those two probe files are not part of the 35-entry default bundle cache. T0/T1 do not require the daemon. T2 needs a later service or separately prepared dynamic-cache path. The daemon should stay deferred until its sandbox, output directories, ownership, and lifecycle are approved for this host.

## Bare-metal differences and blockers

Current read-only `nvram`/`csrutil` output:

- boot arguments include `-amd_no_dgpu_accel` and `navi48-stage=1`;
- `csr-active-config` is `00 00 00 00`; SIP is enabled.

P0 ran in a VM with the RX not driving the display, a separate virtual console, stage 17, `navi48-metal=1`, `navi48-aux=1`, and CSR config `0x03`. It passed T0 enumeration, T1 census, T2 hot-swap, exact T3 triangle/quad, and T4 compute in that VM (`research/reports/p0_headless_metal.md`). Those results do not prove the bare-metal display, SIP/`-amd_no_dgpu_accel`, aux approval, or temperature behavior.

All live install targets were absent during the audit: `/Library/GPUBundles/Navi48Metal.bundle`, `/Library/Extensions/Navi48Accel-0.0.7.kext`, `/Library/LaunchDaemons/com.navi48.translate.plist`, `/usr/local/navi48`, `~/navi48-staging`, and `~/n48-metal`.

The elevated install could not be run from this remote execution environment: its shell has uid 501/gid 20, but `id -un` and `whoami` return `501`, `dscacheutil` returns no user for uid 501, and `dscl` on `~` returns `eServerError`. The parent’s sudo attempt in this environment reported uid 501 absent from the passwd database. The user separately confirmed that their local Terminal resolves `id -un` to `pastasugo89`; this appears specific to the remote execution environment, not a confirmed fault in the local account service. I did not attempt an escalation workaround or restart any service. The installer’s real-root dry-run is the only live-target check performed here.

Thermal telemetry remains unknown for CPU and GPU on this macOS boot, and the RX is the active display GPU with no second display cable attached. These are independent barriers to enabling the driver, even after a file-only bundle/tool deployment.

## Console framebuffer guard review

The review of the current console-guard source found a correct default refusal for unknown/invalid/overflowing/partially overlapping console ranges. The optional `navi48-console-external=1` remains a bypass: it leaves the offset unknown, after which the VRAM planner uses its fallback base and explicitly passes the no-console sentinel. It does not independently locate or reserve an external framebuffer. Do not use this override on the bare-metal GPU-primary setup.

The geometry validation has since been added in the source candidate: zero or implausible dimensions/depth, too-short stride, and row-byte multiplication overflow are rejected. A host test is at `research/builds/macos-20261027/desktop-prep/tests/console_guard_test.cpp`. At the latest review the candidate executable hash had changed from `b4ebe246…` to `5bec2414…`; neither candidate was installed or runtime-tested. The latest hash/signature check is staging evidence only.
