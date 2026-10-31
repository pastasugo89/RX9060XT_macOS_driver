# Metal bundle 29: source, build and checks (2026-10-31)

Work dir: `research/builds/macos-20261031/bundle29-src/`. Nothing was installed, no git commits, nothing outside this directory was changed (scratch files only under the session scratchpad).

## 1. Which source produced bundle 28

The report (`research/reports/login_archive_recovery_20261030.md`) says bundle 28 came from "the HEAD bridge plus the factory". That is not what the binary contains. The file that matches the bundle-28 binary is `archive-recovery/Navi48Device-archive-only.m`:

- The bundle-28 binary contains the log string "no user cache directory" (only in the archive-only source) and does not contain "actual RADV backend could not reserve" (only in git HEAD `Navi48Device.m`, commits f9be0ed / 4ba5d34).
- Rebuilding that file reproduces the binary (section 2).

So the bundle-28 source is `archive-recovery/Navi48Device-archive-only.m` (sha256 `22639e15971eec6c892172141fa722c887405fab94ff70d529daba86cf8642d0`). It was copied to `src/Navi48Device.m`. The 30 `n48_*.h` headers were copied from `cobalt64/tools/native/navi48metal/` and are identical to the archive build inputs. The uncommitted worktree changes (dual-source, page-list imports) are not included.

## 2. Step A: baseline reproduction (`build-base/`)

Built with the unmodified `build.sh` (copied to `build-base/tree/`), x86_64, default SDK, `N48_LAZY=1 N48_9D=1 ASIC=navi44`. RADV and n48xlate were the archive copies (not rebuilt). The spvcache came from the archive bundle (230 .spv / .meta.json pairs, identical hashes). `N48_VK_INC` pointed at `research/ext/mesa-darwin/include` because `/opt/homebrew` has no Vulkan headers.

| | sha256 |
|---|---|
| bundle-28 binary (archive-recovery) | `0363d9963e3f09197f64c52fdbff3418ed622efac89a9f8167f9246dc95a8421` |
| baseline rebuild (`build-base`) | `5be78551e39a2f626144c97886e82c7a8ec3d895a59cddaffe7f45e93dc96dd4` |

Not byte-identical, but close:
- Same file size (673280 bytes), same Mach-O sections and sizes (`otool -l`), same `nm` symbol list, identical `__text`.
- 85 differing bytes in total. 16 are the LC_UUID. Several are the build-time strings `__DATE__` / `__TIME__` ("Oct 30 2026 14:16:06" in the archive, "Oct 31 ... 12:56:41" in the rebuild). The rest are in the ad-hoc code-signature blob at file offset 649920.
- Pinning `__DATE__` / `__TIME__` to the archive values on an unsigned build removes the string difference. What remains is the LC_CODE_SIGNATURE load command, which only the signed build has, and the LC_UUID. The LC_UUID difference was not explained further.
- Bundle-28 `libvulkan_radeon.dylib` and `libn48xlate.dylib` are byte-identical to the archive copies. The 460 spvcache files are identical.

Conclusion: the baseline is reproduced closely enough to proceed.

## 3. Step B: fixes (`src/Navi48Device.m`, bundle-29 line numbers)

Each fix is guarded and logs once with the file's existing macros (`N48_ONCE` / `N48LOG`). `PATCH.diff` is the full diff against bundle 28 (including the Info.plist change).

1. **Null view / sampler guard** (descriptor fill, lines ~5110-5113 and ~5131). A texture with no VkImageView is replaced by the existing 1x1 dummy. A sampler with no VkSampler is replaced by the existing default sampler. Each replacement logs once. If the dummy cannot be made, the old behaviour (write NULL) is kept.
2. **Sampled reads honour `MTLTextureDescriptor.swizzle`** (texture init, lines ~2575-2585; ivar 2383; accessor `n48SampleView` 2986; destroyed in dealloc 2618; used in the descriptor fill and the descriptor-cache signature, 5110 and 5582). Created only when the swizzle is not the default RGBA, the texture is not depth/stencil, not a texture buffer, and not multisampled. The view uses the same image, format and range as `_view`, with the components from `n48_view_map(_fmt, swizzle)`. This is the same mapping code as the explicit view path, not a call into it. Storage images and attachments still use the identity view (`n48AttViewLevel`, unchanged). If creation fails, it logs once and keeps the identity view.
3. **Memoised in-process translation failures** (`n48x_translate_fn`, helpers at lines ~3362-3370, lookup at 3489-3490, store at 3520). A bounded `NSCache` (countLimit 256) keyed by AIR identity (sha, or the linked key), stage, and the function-constant dictionary. Only DETERMINISTIC failures are stored: `N48X_E_CAP`, `_SKIP_CRASH`, `_SKIP_FAIL`, `_READER`, `_REFUSED`. Never stored: `_SKIP_LIVE` (another process is translating), `_IO`, `_UNAVAILABLE`, `_TIMEOUT` (transient; the hot-swap still picks up late results). The lookup happens after the on-disk `.spv` check, so an installed result always wins. A hit returns NO immediately, which takes the same fallback path as a failed translation. Note: this memo is per process, and the constants key uses the private selector `functionConstantsDictionary`. If that selector is missing, the key does not distinguish specialisations.
4. **Format 84 (ARGB8)** (format table entry line 2273, flag `N48F_ARGB` line 2243, view map line 2286, render refusal lines 4040-4041). Format 84 maps to `VK_FORMAT_R8G8B8A8_UNORM` (same bytes). Sampled reads use the mapping R<-G, G<-B, B<-A, A<-R, which assumes memory order A,R,G,B. A render pipeline with format 84 as a colour attachment returns nil and an NSError (code 43). The NullMoth reference was not used for this, because `case 84` was not found in the reference checkout (see section 6).
5. **Default sampler for unbound slots** (line ~4277-4285): nearest min/mag, notMipmapped, clamp-to-edge on all axes, `lodMinClamp = 0`, `lodMaxClamp = 0`. Logs once.

Structural check: `clang -fsyntax-only -Wall -Wextra` gives 0 warnings and 0 errors on both the baseline and the modified file. The same flags with `-Werror` are used by the build; the build passed.

## 4. Step C: version and build (`build-29/`)

- `Info.plist`: CFBundleVersion 28 -> 29. CFBundleShortVersionString (0.1.1) was left unchanged.
- Built with the same `build.sh` command and the bundle-28 RADV / translator dylibs (the translator swap is a later step).
- `codesign --verify --deep --strict -vv` passes ("valid on disk", "satisfies its Designated Requirement"). Ad-hoc, identifier `com.navi48.metal`, same resource count as bundle 28 (462 files).
- sha256 of `build-29/Navi48Metal.bundle/Contents/MacOS/Navi48Metal`: **`170b1c104cf94e4d5fbfad5a04e94135e0f503ad4fc1f82bf442b1cc6d929e6b`** (rebuilt after the fix 3 change; the earlier build `19382fd7…` is superseded).
- The new strings are present in the binary (fix messages and the memo message).

## 5. Step D: tests (`tests/`)

Built with `cc -O1 -Wall -Wextra -Werror -I src` and run against `src/` (or `build-base/tree/` for the baseline). `tests/summary-c.txt`, `tests/logs/` hold the output.

Pass on bundle 29 (rc 0): test-asic, test-btcache, test-cblog, test-cienv, test-crc, test-dispflip, test-drawcache, test-dumpacl, test-heapalloc, test-hotswap, test-impcache, test-ioalias, test-ledger, test-occ, test-plane, test-pool, test-t1, test-texdesc (11740 checks), test-xlate-linked.

Fail with the same failure set on bundle 28 (pre-existing, not caused by this change):
- test-depth: 1 of 133.
- test-intfmt: 1 (a stale pin, "Info.plist CFBundleVersion is 20: build 19").
- test-m6route: 9 of 66. test-m6x: 6 of 153. These read repo-relative paths (`../../../src/navi48-bringup/...`) that do not exist in this layout.
- test-xlate: 7 of 134 (overrides.txt path, and a child-death check).

Not run:
- test-gate: needs the repo-relative `navi48-bringup` header.
- test-vkdepth: needs `test-depth-shaders.h` and a Vulkan link. The link was not attempted with libvulkan.
- test-vkimage: link fails (no Vulkan loader) and it needs a device.
- test-xlate-corpus, test-xlate-linked-real: need corpus arguments.

New tests: `tests/test-b29-fixes.c` (fixes, source-text) and `tests/test-b29-key.c` (user-cache key sensitivity, 3/3 pass). It is a source-text check (like test-texdesc), not an execution test, since the fixes live in an Objective-C file that needs Vulkan and Metal to link. Result: 15/15 pass on bundle 29; 14/15 on the baseline (the one that passes on the baseline checks text that already existed).

Fix 3 and fix 4 do not have a behavioural host test. The cache and the format table are in the Objective-C file and cannot be loaded without Vulkan / Metal.

## 6. Notes on the brief

- The NullMoth references named in the brief (`plugin/NVMTLDevice.m` case 84, `nvmtl_vk.c` "no sampled view", `NVMTLLibraryLoad.m` nvmtl_link_failures, `NVMTLObjects.m` nvmtl_texture_desc_swizzle) were not found in the checkout at `research/refs/nvidia-macos-driver` (branch main). The fixes were implemented from the brief and the code, not from those files.
- The format-84 channel order is an assumption (section 3, item 4).

## 7. Risks

- Nothing ran on hardware. The bundle has not been installed, and no login or WindowServer test was done.
- Fix 2 creates an extra VkImageView only for textures with a non-default swizzle. The descriptor-cache signature now uses the sampled view.
- Fix 3 is process-local and never expires. A transient in-process I/O failure (N48X_E_IO) is also memoised for that process. The constants key depends on a private selector.
- Fix 4: format 84 can still be created as a texture with render-target usage and used by clears or blits. Only the render pipeline refuses it. The channel-order mapping is unverified.
- Fix 1 and fix 5 change behaviour only for unbound or broken slots. Fix 5 changes the default sampler's LOD clamp to 0 (level 0 only).
- The build's temporary staging directories (under the system temp folder) are left behind by `build.sh` itself. Nothing was deleted.

## 8. Translator swap: which caches survive (answer to the coordinator)

Where the keys come from:
- Bundle lookup path (`n48_spv_dirs`, Navi48Device.m ~3626): the bundle's `Resources/spvcache` (`/Library/GPUBundles/Navi48Metal.bundle/Contents/Resources/spvcache` once installed), then the user dir K, then the side dir `/private/var/tmp/n48m-spv`. The `/Library/GPUBundles` path is the bundle's own resource path, not a separate cache.
- Sha for a function: `n48_sha256hex(bitcodeData)` (Navi48Device.m ~3483, ~3908); for a linked stage `lk->lsha` (~3485). Neither includes the translator.
- User dir K (`n48x_setup_locked`, ~3393-3430): `<confstr user cache>/com.navi48.xlate/K` with `K = n48x_key(LC_UUID of the libn48xlate.dylib FILE on disk, reader id (dyld shared-cache UUID), sha256 of the override table, kern.osversion)` (n48_xlate.h ~129-141). The file's LC_UUID is read by `n48x_file_uuid` (n48_xlate.h ~448). The sha256 of the dylib is NOT part of K.
- Markers `.fail`, `.crash`, `.inflight` and translated `.spv` live inside K, so they are keyed by sha AND by the translator LC_UUID.

Answers:
- (a) In-process `.fail` / `.crash` markers from the old translator: IGNORED by a rebuilt translator whose LC_UUID differs, because they sit in the old K directory. `ld` derives LC_UUID from the content, and the baseline rebuild above already showed LC_UUID changing between builds. The existing key test (`test-b29-key`) confirms K changes with the LC_UUID and with the OS build, and stays fixed for a repeat. No code change was needed. A replaced dylib with an identical LC_UUID would share K; that is not expected from ld64.
- (b) User-dir `.spv` from the old translator: IGNORED for the same reason (different K).
- (c) System-wide precomputed spvcache (the bundle's `Resources/spvcache`): NOT invalidated. It is read first and is not keyed by the translator. The installed bundle 28 holds 230 `.spv` / `.meta.json` pairs (460 files, identical to the archive), not 212.
- Not covered, flagged: the SIDE DIRECTORY `/private/var/tmp/n48m-spv` (452 files, 226 pairs, currently present) holds translator output written by `<sha>.spv` atomic rename and is keyed by sha alone. Bundle 29 reads it for every non-sandboxed process and WindowServer (n48_spv_dirs). Entries from the old translator WILL be reused. This was left unchanged because the brief asked for no invalidation of the precomputed cache and the side dir is a different store. Decision needed before the translator swap: clear it, or version its directory name by translator LC_UUID.
