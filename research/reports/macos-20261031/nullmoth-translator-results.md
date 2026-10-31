# RESULTS: NullMoth-based n48xlate, build and test (2026-10-31)

Deliverable: `libn48xlate.dylib` (ad-hoc signed) in this directory. Provenance: `PROVENANCE.md`. Port: `PORTING.md`.

## Headline

- **Build**: `n48xlate` builds in release (`x86_64-apple-darwin`, `MACOSX_DEPLOYMENT_TARGET=12.0`). The C ABI is unchanged: the same four `n48x_*` exports, `n48x_abi_version() == 2`.
- **Tests, default run** (`cargo test --release -p n48xlate`): 16 passed, 0 failed. Caveat: 3 of them are the corpus tests, which do nothing unless `N48X_CORPUS` is set.
- **Tests, with the 35-shader corpus** (`N48X_CORPUS`, set A): 1 passed, **2 failed** (see below). The failures are real and were not weakened.
- **Translator tests** (NullMoth `metal2vulkan --lib`): the port adds 11 regression tests, 4 of which failed before the port and pass after it. With an always-pass validator stub the failing set is identical to the pristine tree (39 failures, pre-existing).
- **Output change**: the new dylib translates all 48 inputs successfully, but its output differs from the daemon's reference on 46 of 48 SPIR-V modules and on all 48 meta files. The old dylib reproduces the reference byte-for-byte on all 48. The differences are not cosmetic (see Risks).
- **spirv-val was not available**, so **no output of either dylib was validated by a Vulkan validator**. This is the most important open item.

## Toolchain

- rustup via `static.rust-lang.org` (`sh.rustup.rs` unreachable), checksum verified. Installed into `~/.rustup`, `~/.cargo`.
- `rustc 1.99.1 (58cf8f9c3 2026-10-13)`, `cargo 1.99.1 (5f94df478 2026-08-27)`, host `x86_64-apple-darwin`. Crates declare `rust-version = 1.87`; the build was not run with 1.87 itself.
- Clang: Apple clang 21.0.0 (for the harness).
- `spirv-val`, `spirv-dis`, `llvm-dis`: not on PATH; no Vulkan SDK under `/Applications` or `~/VulkanSDK`. Not installed (`cargo install` not permitted).

## Build commands

```
cd research/builds/macos-20261031/nullmoth-xlate-v1/translator
MACOSX_DEPLOYMENT_TARGET=12.0 cargo build --release -p n48xlate --target x86_64-apple-darwin
# output: translator/target/x86_64-apple-darwin/release/libn48xlate.dylib  -> copied to ./libn48xlate.dylib, then:
codesign -s - -f libn48xlate.dylib
```

- Install name: `otool -D` shows `/…/translator/target/x86_64-apple-darwin/release/deps/libn48xlate.dylib`. The old dylib's id is `/…/research/ext/m2v/metal2vulkan/target/release/deps/libn48xlate.dylib`. Neither is `@rpath`, so per the rule (change only when the old one is `@rpath`) **`install_name_tool` was not run**. Both are build-tree paths.
- `nm -gU`: the new and old dylibs export the identical four symbols: `_n48x_abi_version _n48x_free _n48x_translate _n48x_translate_linked`.
- `otool -L` (both): `libSystem.B.dylib`, `libiconv.2.dylib`, and the self id. No other dependencies.
- Old dylib is unsigned. New dylib: ad-hoc signed, identifier `libn48xlate-55554944ab81df4297b13d7a93f7a71ba8241399`, verified (`codesign --verify`: valid on disk, satisfies its designated requirement).

## Hashes

| artifact | sha256 |
|---|---|
| old `libn48xlate.dylib` (`research/ext/m2v/metal2vulkan/target/release/`) | `9a0b6077fb6703be1193d4e68ae507cd3245a839bd4864b89502b4a8d0cd0c33` |
| new, before signing | `230b2787b8424f94ef3e8a2199e011f0b5674fd68489eba298845efc1982ad3e` |
| new, signed (deliverable `./libn48xlate.dylib`) | `51c15172c9b2e0b22f65f3fe974c4b39bf3ff46b7418af42969dff2f6c68bb9f` |
| our patch `0001-…n48xlate.patch` | `96e26cfbfc5957a62662448b97e6b138e9c7b36286ef5c8ef8e761436499ec3b` |

The signed deliverable was re-run over corpus set A; its results are identical to the build-tree dylib's.

## Tests

### metal2vulkan (NullMoth translator) lib tests

| run | passed | failed | notes |
|---|---|---|---|
| pristine NullMoth, no stub | 1714 | 508 | failures are `cannot run spirv-val` (the validator is absent; 501 log lines) |
| ported, no stub | 1719 | 514 | the same 508, plus the 6 new tests that call the external validator (same cause) |
| pristine, `METAL2VULKAN_SPIRV_VAL=/usr/bin/true` | 2183 | 39 | |
| ported, same stub | 2194 | 39 | identical failing set; +11 new passing tests |

The 39 remaining failures (with the stub) are tests that assert real `spirv-val` verdicts (for example `*_matches_vulkan_validation`, `owned_*`) or depend on a real validator. They fail on both trees. The stub is an always-pass validator, as the daemon uses; it means those tests check structure, not validity.

Patch-derived regression tests (against pristine NullMoth, then after the port): 7 already passing with no change (`native_raw_*` ×5, `a_raw_aggregate_array_*`, `native_raw_pointer_offset_survives_*`), and 4 failing that now pass (`resource_wrapper_collapse_keeps_both_*` ×2, `f32_bit_special_*`, `a_narrower_vector_load_*`).

### n48xlate

| run | result |
|---|---|
| `cargo test --release -p n48xlate` (default) | unit 0; corpus 3 pass (no-op, `N48X_CORPUS` unset); linked 10 pass; stack 3 pass. **16 passed, 0 failed.** |
| `… --features test-hooks --test hooks` | 4 passed (`abi_version_is_two`, `bad_arguments_are_3`, `refusals_are_1`, `a_panic_is_caught_and_reported_as_2`) |
| `N48X_CORPUS=<set A> N48X_OVERRIDES=overrides.txt cargo test --release -p n48xlate --test corpus` | **1 passed, 2 failed** (below) |

Corpus failures, not weakened:

1. `translation_equals_the_daemon_pipeline` **fails**: 34 SPIR-V differ from the daemon reference, 1 meta differs (`SimpleColorFragment`, the version field only). 0 identical. This is the same finding as the table below: NullMoth's output is not the daemon's output.
2. `skip_path_never_runs_the_validator_and_keeps_the_rejects` **fails** on `rejects_seen > 0`. The first half passes: all 35 translate with a failing validator configured, so the Skip path never reaches the validator. The assertion needs a corpus entry the daemon refused (so a post-validation reject fires). **Set A has no such entry**, and no daemon-refused AIR exists in this research tree (see below). This is a coverage gap in the corpus, not a dropped reject: both rejects are present in NullMoth (`reject_function_constant_erased_effects`, `reject_imageblock_only_effects`), and both run after the validator in both modes (`src/lib.rs`).
3. `external_path_still_calls_the_validator` **passes**: with a failing validator the external gate refuses.

Other test files: `linked.rs` (10) and `stack.rs` (3, including the 512 KiB vs 64 MiB stack case) pass.

`cli-identical.sh` was not run. It compares the steelbrain command-line tool, which this build does not produce.

## Corpus comparison: old dylib vs new dylib

### Method

- The AIR bitcode is converted to LLVM text by Apple's own GPUCompiler LLVM (`/System/Library/PrivateFrameworks/GPUCompiler.framework/Versions/Current/Libraries/libLLVM.dylib`, via `n48x_reader_load`/`n48x_reader_print` in `n48_xlate.h`). This is the production first stage. `n48x_translate` takes that LLVM text, so the input is **AIR bitcode -> LLVM text -> `n48x_translate`**, not raw bitcode.
- The overrides table (`n48x_local_for`) supplies the threadgroup size for `sum_rgba_columns`, `sum_rgba_rows`, `write_tex`.
- Both dylibs are loaded with `n48x_xlib_load` (ABI check included) and run in one harness process, `harness/xlate_compare.c`, in a cleared environment (`env -i`, no `METAL2VULKAN_*` variables).
- Reference: the daemon's `.spv` and `.meta.json` from `research/ext/spvcache-25G83/spvcache` (set A) and `research/hw_dump/…/translator/output` and `…/navi48-spv` (sets B, C).
- Meta is compared as parsed JSON, as `corpus.rs` does. SPIR-V is compared byte-for-byte.

### Inputs

- **Set A** (35): `research/ext/spvcache-25G83/air/{SkyLight,CoreDisplay}/*.air`, the carved AIR blobs with their reference `.spv`.
- **Set B** (11): `research/hw_dump/macos_stage17_run_20261027/translator/input/501/*.air`. The translate log marks all 11 OK, and the output directory holds their reference outputs.
- **Set C** (2): `research/ext/n48m-air-boot27-20261021/*.air`, reference in `hw_dump/macos_accelerated_trial_20261027/navi48-spv/`.
- **Previously failed**: none found. I searched `research/` for `*.air`, `*.ll`, `*.bc`, `translate*.log*`, `*.metallib`, and for `xlate fail`, `rc=[1-9]`, `translation failed`, `refus`. Every translate log found records only OK outcomes, and `spvcache-25G83/translate.log.rc` is 35× `rc=0`. The `.ll` files in `research/artifacts/compute/src` and NullMoth's own `testdata/fixtures` are LLVM text, not failures.

### Table (old vs new; spirv-val column n/a, not installed)

`old/new rc`: `n48x_translate` return code (0 = translated). `spv B`: SPIR-V bytes. `== ref`: byte or JSON equality with the daemon reference. `spv old==new`: old and new SPIR-V byte-identical.

| set | shader | sha256 (12) | old rc | new rc | old spv B | new spv B | spirv-val | old spv==ref | new spv==ref | old meta==ref | new meta==ref | spv old==new |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | SimpleTextureLightingVertex | 13703fd14f1a | 0 | 0 | 1556 | 1588 | n/a | yes | no | yes | no | no |
| A | ColorFillYCbCr_ChromaOnly | 1493852ac3ac | 0 | 0 | 852 | 868 | n/a | yes | no | yes | no | no |
| A | BlurCompositeVertex | 2a1b182e0bef | 0 | 0 | 1248 | 1272 | n/a | yes | no | yes | no | no |
| A | ColorFill | 2c1b8ac933ee | 0 | 0 | 904 | 920 | n/a | yes | no | yes | no | no |
| A | InPlaceAlphaUnpremultiply | 2fd8d7dedf97 | 0 | 0 | 1008 | 1016 | n/a | yes | no | yes | no | no |
| A | ShadowHorizontalBlurFragment | 356d1b7136f8 | 0 | 0 | 17504 | 18072 | n/a | yes | no | yes | no | no |
| A | SimpleVertexShadow | 3b7fb2ca5c2a | 0 | 0 | 1100 | 1124 | n/a | yes | no | yes | no | no |
| A | UberCompositeVertex | 487fa598d7a4 | 0 | 0 | 1492 | 1516 | n/a | yes | no | yes | no | no |
| A | RippleFragment | 4e193d4d6cfe | 0 | 0 | 6944 | 7700 | n/a | yes | no | yes | no | no |
| A | AlphaTextureFragment | 53cf3c1e40b2 | 0 | 0 | 1824 | 2320 | n/a | yes | no | yes | no | no |
| A | ColorFillYCbCr | 600fb59bb8c7 | 0 | 0 | 1092 | 1116 | n/a | yes | no | yes | no | no |
| A | SimpleTextureLightingFragment | 71852acccef2 | 0 | 0 | 4396 | 4908 | n/a | yes | no | yes | no | no |
| A | SimpleGrayscale | 7401147e2517 | 0 | 0 | 1812 | 2308 | n/a | yes | no | yes | no | no |
| A | BlurComposite | 89789ef9012d | 0 | 0 | 4736 | 5560 | n/a | yes | no | yes | no | no |
| A | SimpleTextureScaleToSDRFragment | 8b358ad52c8c | 0 | 0 | 3760 | 4256 | n/a | yes | no | yes | no | no |
| A | InPlaceSover | 8ca23b41fba9 | 0 | 0 | 1028 | 1044 | n/a | yes | no | yes | no | no |
| A | ShadowVerticalBlurRGBAFragment | 9050a053aa29 | 0 | 0 | 19476 | 20092 | n/a | yes | no | yes | no | no |
| A | SimpleColorVertex | 92f07c78294c | 0 | 0 | 1100 | 1124 | n/a | yes | no | yes | no | no |
| A | UberResampleLanczosFragmentBGRA | a02f84e4f909 | 0 | 0 | 2740 | 3352 | n/a | yes | no | yes | no | no |
| A | SimpleTextureFragmentUV | a0a6a7443078 | 0 | 0 | 3408 | 3904 | n/a | yes | no | yes | no | no |
| A | TextureCopy | a52d359769df | 0 | 0 | 3356 | 3852 | n/a | yes | no | yes | no | no |
| A | ViewportToNDC | b10dd7065774 | 0 | 0 | 1708 | 1764 | n/a | yes | no | yes | no | no |
| A | ShadowCompositeFragment | c09bdbd5a7ee | 0 | 0 | 5204 | 5792 | n/a | yes | no | yes | no | no |
| A | SimpleVertex | c21609d9f817 | 0 | 0 | 1096 | 1120 | n/a | yes | no | yes | no | no |
| A | GroupFadeTextureFragment | cc2058f94b2e | 0 | 0 | 2272 | 2784 | n/a | yes | no | yes | no | no |
| A | SimpleColorFragment | d5c2965f05c4 | 0 | 0 | 380 | 380 | n/a | yes | yes | yes | no | yes |
| A | ShadowVerticalBlurFragment | d7547059194b | 0 | 0 | 18052 | 18644 | n/a | yes | no | yes | no | no |
| A | UberCompositeFragment | d8c56dec8987 | 0 | 0 | 4728 | 5432 | n/a | yes | no | yes | no | no |
| A | SimpleTextureEDRFragment | df0fa343d102 | 0 | 0 | 1204 | 1644 | n/a | yes | no | yes | no | no |
| A | SimpleTextureFragment | e1d2b828b2ea | 0 | 0 | 772 | 1236 | n/a | yes | no | yes | no | no |
| A | SimpleMeshVertex | e27c677fd93b | 0 | 0 | 1280 | 1304 | n/a | yes | no | yes | no | no |
| A | UberResampleLanczosFragmentYCbCr | e7d61d9c840c | 0 | 0 | 3344 | 3980 | n/a | yes | no | yes | no | no |
| A | InPlaceColorOrClampEDR | f3805940c617 | 0 | 0 | 2728 | 2768 | n/a | yes | no | yes | no | no |
| A | SimpleTextureTintFragment | f3b8f399343e | 0 | 0 | 3936 | 4448 | n/a | yes | no | yes | no | no |
| A | GPUPass | f4c62e3fde05 | 0 | 0 | 10080 | 10928 | n/a | yes | no | yes | no | no |
| B | compute_apl | 1b937b0fc7de | 0 | 0 | 5904 | 6544 | n/a | yes | no | yes | no | no |
| B | compute_average_luma | 2ec9c9507cfb | 0 | 0 | 4524 | 5136 | n/a | yes | no | yes | no | no |
| B | tile_average_luma_quad | 452b2cc85209 | 0 | 0 | 9528 | 9728 | n/a | yes | no | yes | no | no |
| B | compute_apl_fast | 53383dfb3c9e | 0 | 0 | 9908 | 9676 | n/a | yes | no | yes | no | no |
| B | compute_sum_luma | 8123080cd42a | 0 | 0 | 3080 | 3060 | n/a | yes | no | yes | no | no |
| B | write_tex | 82941c47eda0 | 0 | 0 | 1832 | 1832 | n/a | yes | yes | yes | no | yes |
| B | quad_vs | 8c8b25d8e140 | 0 | 0 | 1316 | 1332 | n/a | yes | no | yes | no | no |
| B | sum_apl_and_compute_dimming_factor | c226450a3514 | 0 | 0 | 6148 | 6212 | n/a | yes | no | yes | no | no |
| B | quad_fs | c9f593d3696a | 0 | 0 | 1276 | 1708 | n/a | yes | no | yes | no | no |
| B | fill_buf | e64f769aa5de | 0 | 0 | 1444 | 1452 | n/a | yes | no | yes | no | no |
| B | tile_average_luma | ed830b9b939a | 0 | 0 | 4680 | 4736 | n/a | yes | no | yes | no | no |
| C | GPUPass | 29164ba4e5fa | 0 | 0 | 8968 | 9816 | n/a | yes | no | yes | no | no |
| C | ViewportToNDC | c0708ccd3671 | 0 | 0 | 1708 | 1764 | n/a | yes | no | yes | no | no |

Summary over 48 inputs: old translated 48/48, new 48/48. Old SPIR-V == reference 48/48; new 2/48 (`SimpleColorFragment` in A and `write_tex` in B). Old meta == reference 48/48; new 0/48 (version field always differs). Old == new SPIR-V 2/48 (the same two shaders).

## Output analysis (what changed, and why it matters)

Compared with the daemon reference, every new meta differs in one of two ways. Exactly these two; nothing else (checked for all 48 after normalising the two fields):

1. `trimmed_from_reflection_version` 55 → 56 (all 48).
2. A **new `BufferAddressTable` binding** (`set 0`, `binding 640`, `access ReadOnly`) in **25 of 48** modules.

For the SPIR-V (compared with the old output, which equals the reference):

- New total instructions 11521 vs old 10691 (+7.8%). Largest count changes: opcode 71 (+270), 17 (+78), 32 (+76), 65 (+72), 43 (+67).
- Capabilities: 28 modules gain capabilities, none lose any. The gains are `ShaderNonUniform` (5301) in 25 modules, `RuntimeDescriptorArray` (5302) in 25, `SampledImageArrayNonUniformIndexing` (5307) in 25, and `StorageImageReadWithoutFormat` (55) in 3.
- Extensions: 25 modules gain `SPV_EXT_descriptor_indexing`.

## Risks and open items

1. **Output is unvalidated (highest priority).** `spirv-val` is absent, so nothing here shows the new SPIR-V is valid. Run the validator over `out/new/*.spv` (set A/B/C under `harness/out/`) before any use. The old outputs match the daemon, so only the new outputs carry this risk.
2. **Metal bundle ABI change.** The new meta adds a `BufferAddressTable` binding at set 0, binding 640 in 25/48 modules and bumps `reflection_version` to 56. The bundle reads these bindings, so it must accept the new kind and the layout must match the descriptor set it builds. This is the most likely break.
3. **New device features required.** Descriptor indexing (`ShaderNonUniform`, `RuntimeDescriptorArray`, `SampledImageArrayNonUniformIndexing`, `SPV_EXT_descriptor_indexing`) and `StorageImage*WithoutFormat` must be enabled on the Vulkan device on Navi48. Check the device-creation feature set before switching.
4. **Cache re-keying.** The in-process cache key includes the translator's build UUID, so the new dylib will miss the existing cache and re-translate. That is expected, not a bug, but warm-cache behaviour will change.
5. **Install name is a build path** (both dylibs). Not changed, per the instructions. If the bundle loads by `@rpath`, it needs an `install_name_tool -id @rpath/libn48xlate.dylib` step later, and it must be re-signed after.
6. **Corpus coverage gap.** No daemon-refused AIR was found, so the reject path and the corpus's "refused by both" logic are untested here. Get the bundle's `xlate-corpus-prep.py` corpus (which includes refused modules) before relying on the reject tests.
7. **Patch sensitivity unverified.** 17 of the 36 patch hunks were classified already-present on the strength of the patch's own tests passing on NullMoth. I did not run those tests against the unpatched steelbrain base, so their sensitivity is not confirmed.
8. **Toolchain.** Built with rustc 1.99.1, not the crates' declared MSRV 1.87. Release profile was copied from NullMoth's crate into the staging workspace root. Codegen differences from the old build are not measured.
9. **Signature.** Ad-hoc only; no notarisation or hardened runtime.

## Harness and outputs (in this directory)

- `harness/xlate_compare.c`: builds with `clang -O1 -I cobalt64/tools/native/navi48metal -ldl`. Input TSV columns: sha, entry name, AIR path, reference spv, reference meta, set.
- `harness/inputs/`: the three input TSVs (`set-A-spvcache-25G83.tsv`, `set-B-stage17.tsv`, `set-C-boot27.tsv`) and `stage17-sha-name.txt`.
- `harness/results-*.tsv`, `harness/table-*.tsv`: per-input results (`table-*` from `harness/summarize.py`, run with `python3 -I`).
- `harness/out/`: the produced `.spv`, `.meta.json`, and reader text (`text/<sha>.ll`) for old and new.
- `harness/corpus-setA/`: the corpus layout `corpus.rs` expects (manifest, `.clang.ll`, `ref/`), used for the corpus test run.
- `logs/`: all build and test logs, including the baseline and ported test runs.
- `work/pristine/`, `work/hunks/`: the pre-port source snapshot and per-hunk patch files.

The staging tree is about 3.3 GB, almost all of it `translator/target/` (build cache).

## Phase 2: spirv-val, BufferAddressTable, bundle 29 (2026-10-31)

Validator: SPIRV-Tools `v2026.4` (tag, commit `ef96ed763b43b59b33b31b362f09a02b729fa1c9`, `github.com/KhronosGroup/SPIRV-Tools`), SPIRV-Headers `fef168c54ed2e37c314eb251806aaf9877f38465` (`github.com/KhronosGroup/SPIRV-Headers`, main). Built with cmake 4.4.4 and ninja 1.13.2 (pip, into `tools/venv`). `tools/build-spvtools/tools/spirv-val`, sha256 `a945cd3b4c5a94fbd38ba3ee8f6de83213d467c4e95a0d1deb68bdef2152872b`, `SPIRV-Tools v2026.4-0-gef96ed7`. Sanity: a truncated module is rejected (exit 1).

| side | configuration | spirv-val `--target-env vulkan1.3` |
|---|---|---|
| OLD (archive dylib) | n/a | 48/48 PASS |
| NEW, first build (BAT on, bindless on) | `harness/spirv-val-results.tsv` | 48/48 PASS |
| NEW, final (plain textures off, arrays on, refusal guard) | `harness/eval_variant.py final2` | 48/48 PASS |

What the BufferAddressTable is: one `u64` device address per Metal buffer slot, at the first free binding of the synthetic range (640), declared by the bindless texture routing (`REFLECTION.md` row "Synthesized direct-buffer address table"). The plugin must fill it per dispatch. The bundle cannot: `Navi48Device.m:5091` fails any buffer descriptor at binding >= 32. In NullMoth, the switch `plain` (ordinary textures, `stage_input`) declares it for every texture shader (25/48 modules here). `arrays` (texture-array element routing) declares it only for texture arrays; none of the 48 inputs has one.

`reflection_version` 56: the bundle never reads it (no reference in `src/`). Meta keys the bundle uses are `bindings` (StaticSampler only), `kernel_dispatch`, `local_size`; unknown kinds are ignored.

Configuration comparison (48 inputs, against OLD):

| config | BAT modules | spirv-val | meta == OLD (ignoring version) | SPIR-V identical to OLD | capabilities gained |
|---|---|---|---|---|---|
| NullMoth defaults | 25 | 48/48 | 0/48 (also BAT) | 2/48 | 55 (3), 5301/5302/5307 (25), ext descriptor_indexing (25) |
| `NVMTL_NO_BINDLESS_ALL=1` (env) | 0 | 48/48 | 48/48 | 3/48 | 55 (3) |
| final: plain off, arrays on | 0 | 48/48 | 48/48 | 3/48 | 55 (3) |

Final SPIR-V vs OLD: opcode sequences identical in 22/48. The rest differ by `OpIsNan`/`OpSelect` pairs (fragment NaN semantics, NullMoth fix) and reordering; +67 instructions in total.

Device features (step 3): the bundle's `vkCreateDevice` (`Navi48Device.m` ~566-573) copies `shaderStorageImageReadWithoutFormat` and `WriteWithoutFormat` from the device. Our RADV (`artifacts/mesa-radv/vulkaninfo_full.txt`, RADV GFX1200) reports both true. The final SPIR-V needs only capability 55, so no descriptor-indexing features are required (they appear only with the BAT route, which is now refused). No bundle change was needed.

Bundle 29 with the new translator: `bundle29-src/build-29-newxlate/` (source unchanged, `PATCH.diff` unchanged). Built with `build.sh` (`N48_XLATE_LIB` = final dylib, `N48_RADV_LIB` = bundle-28 `libvulkan_radeon.dylib` sha256 `f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155`, `N48_SPVCACHE_DIR` = the 230 existing pairs). The bundle's precomputed spvcache is still the OLD translator's output; the new translator runs only on misses. Bundle binary sha256 `2267cbbd344a0a123bc0137ebe0eac40515bfd66edeec98eb7a5bbd2a1c3da00`; embedded `libn48xlate.dylib` `b351b5ad835be00ae2ef668cf19e2b6cf185198150a1596be4a5199c5ec43f3e` (the final dylib). `codesign --verify --deep --strict` passes (`logs/bundle29-verify.txt`). Nothing installed to /Library.

Behaviour change to flag: a texture-array shader is now refused in-process (previously translated with the array-element defect that NullMoth fixed). The bundle has no path for that case, so it is refused by the translator instead of being refused by the bundle later.

## Phase 3: texture arrays (arrays = false in the final configuration)

Test input: `harness/texarray/texarray_sample.ll` (AIR text, `array_ref<texture2d<float,sample>>`, constant index 1 and dynamic index from a buffer, `air.sample_texture_2d`). Translated with `harness/xlate_text`.

| dylib | rc | SPIR-V | spirv-val vulkan1.3 |
|---|---|---|---|
| OLD | 0 | 1540 B | PASS |
| NEW arrays=true (previous final) | 1 (refused: "module needs a BufferAddressTable") | - | - |
| NEW arrays=false (final) | 0 | 1540 B, byte-identical to OLD | PASS |

Access pattern (disassembly, OLD == NEW): one `UniformConstant` array of 128 images at binding 32, `OpAccessChain %arr %uint_1` for the constant index and `OpAccessChain %arr %idx` for the dynamic index (the index is loaded from the binding-1 buffer). Element i is read, not element 0. NullMoth's array fix (heap routing) needs a BAT, so it is not available in v1; arrays=false is OLD behaviour for these inputs, and nothing that translated under OLD is refused.

Final: `libn48xlate.dylib` sha256 `9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a` (ad-hoc signed). 48-input corpus: spirv-val PASS 48/48, no BAT, meta equal to OLD ignoring version 48/48. Bundle 29 rebuilt in `bundle29-src/build-29-newxlate/` (replaced): binary sha256 `2c8ff5d043f2beb1e875193248df20184a514bc0ce07645427500597b5a49fe8`, bundle tar sha256 `e6a9c6a26e3295d269ebfa57b2b7337be967bdbb4ae11f6e194913bac055f71a`, `codesign --verify --deep --strict` passes (`logs/bundle29-final3-verify.txt`). Bundle source and PATCH.diff unchanged.
