# PORTING: our metal2vulkan patch onto NullMoth's translator

Input: `cobalt64/third-party/metal2vulkan-n48/patches/0001-metal2vulkan-changes-for-n48xlate.patch` (36 hunks, 14 files).
Target: NullMoth translator at `ceba63c15ba9d81deea7cd1c5dcc4c79497bea8f` (`translator/translator`).

## Method

1. `patch --dry-run` of each file against NullMoth's tree: 18 hunks applied cleanly, 17 failed (including the workspace `Cargo.toml` hunk, which is expected to fail), and `CHANGELOG.md` is not in the tree. Clean application says nothing about whether a change is needed, so it is not used as the classification.
2. Test-first classification. Each hunk in the patch carries its own regression tests. The 11 new tests from the patch were applied to an unmodified NullMoth tree (`work/pristine/` is the snapshot). Results before any code port:
   - already passing on pristine (7): `a_raw_aggregate_array_of_vectors_load_is_built_element_wise`, `native_raw_call_offset_reaches_loop_helper_defined_before_kernel`, `..._defined_after_kernel`, `..._passed_directly`, `native_raw_call_offset_80_reaches_loop_helper`, `native_raw_pointer_offset_survives_aggregate_helper_round_trip`, `native_raw_call_offset_is_delivered_or_refused_never_dropped`.
   - failing on pristine (4): `resource_wrapper_collapse_keeps_both_resources_in_a_mixed_struct_{texture,sampler}_first`, `f32_bit_special_literals_in_half_code_become_binary16`, `a_narrower_vector_load_reads_the_low_lanes_of_the_leading_vector`. Each of these was ported and then passes.
3. Full-suite regression check (see RESULTS.md): NullMoth's `metal2vulkan --lib` run before and after the port, with and without an always-pass validator stub; the failing sets are identical apart from the new tests.
4. The "already-present" rows below are therefore established by behaviour (the patch's own regression tests pass on NullMoth), not by reading equivalent code line for line. The caveat is that I did not separately confirm those tests fail on the unpatched steelbrain base, so their sensitivity is unverified.

## Hunk table

Status values: **ported** = code applied (or adapted) in the staging tree; **already-present** = NullMoth's fork passes the patch's regression test for this behaviour, so no change was made; **dropped** = not needed, with the reason.

| # | File | Hunk (patch @@) | Purpose | Status |
|---|---|---|---|---|
| 1 | CHANGELOG.md | `@@ -7,6 +7,22` | Changelog entries for `Validation`, the `n48xlate` crate, ABI 2 | dropped: documentation of our fork; NullMoth keeps its own changelog. Recorded here instead. |
| 2 | Cargo.toml | `@@ -1,5 +1,5` | Workspace members `["validation", "n48xlate"]` | ported (adapted): staging workspace at `translator/Cargo.toml` with members `translator`, `n48xlate`; `wrapper` excluded. |
| 3 | src/lib.rs | `@@ -54,6 +54,21` | Add `enum Validation { External, Skip }` with docs | ported |
| 4 | src/lib.rs | `@@ -487,6 +502,7` | `translate_sanitized_native_specialized_reflected_with_options` passes `Validation::External` | ported (call site at NullMoth line ~420) |
| 5 | src/lib.rs | `@@ -679,11 +695,40` | `translate_reflected_with_options` passes `External`; add `translate_sanitized_native_reflected_unvalidated` | ported (the new function is the entry n48xlate calls) |
| 6 | src/lib.rs | `@@ -767,7 +812,14` | `translate_sanitized_native_reflected` passes `External` | ported |
| 7 | src/lib.rs | `@@ -776,6 +828,7` | `translate_sanitized_native_reflected_with_layout` gains a `validation` parameter | ported |
| 8 | src/lib.rs | `@@ -806,6 +859,7` | the layout function forwards `validation` to the carrier | ported |
| 9 | src/lib.rs | `@@ -1325,7 +1379,16` | `translate_sanitized_with_meta` passes `External` | ported |
| 10 | src/lib.rs | `@@ -1343,6 +1406,7` | carrier `translate_sanitized_with_meta_prevalidated_carrier` gains `validation` | ported |
| 11 | src/lib.rs | `@@ -1392,7 +1456,9` | the `spirv_val_bytes` gate runs only when `validation == External` | ported. The two structural rejects (`reject_function_constant_erased_effects`, `reject_imageblock_only_effects`) still run in both modes. |
| 12 | src/native/emitter/body/calls.rs | `@@ -610,6 +610,7` | call `refuse_undelivered_raw_cursor` before passing a pointer argument | already-present: `native_raw_call_offset_*` and `..._never_dropped` pass on NullMoth. Not applied. |
| 13 | src/native/emitter/body/calls.rs | `@@ -618,6 +619,45` | define `refuse_undelivered_raw_cursor` (refuse a cursor that cannot cross a call) | already-present (as 12) |
| 14 | src/native/emitter/body/calls.rs | `@@ -877,6 +917,20` | refuse a cursor for a helper already emitted without it (`started_functions`) | already-present (as 12) |
| 15 | src/native/emitter/body/core_inst.rs | `@@ -529,6 +529,17` | `raw_root_is_inline_param` helper | already-present: `native_raw_pointer_offset_survives_aggregate_helper_round_trip` passes |
| 16 | src/native/emitter/body/core_inst.rs | `@@ -579,6 +590,13` | comment: cursor must survive a second inline hop | dropped: comment only, goes with 15 |
| 17 | src/native/emitter/body/core_inst.rs | `@@ -586,7 +604,9` | `inline_raw` filter accepts an already-inlined raw parameter | already-present (as 15) |
| 18 | src/native/emitter/body/core_inst.rs | `@@ -700,9 +720,11` | keep the raw root for an inlined raw parameter | already-present (as 15) |
| 19 | src/native/emitter/body/vector_store.rs | `@@ -1178,7 +1178,28` | narrowing case: a `<k x T>` load of the low lanes of a wider leading vector | ported (adapted: NullMoth already had a `widen` path, so the new guard is `!direct && !bitcast && !widen && narrow_lanes.is_none()`) |
| 20 | src/native/emitter/body/vector_store.rs | `@@ -1211,6 +1232,42` | emit the low-lane load (`OpCompositeExtract` for one lane, `OpVectorShuffle` for several, then `OpBitcast`) | ported (as 19) |
| 21 | src/native/emitter/functions.rs | `@@ -356,6 +356,7` | record `started_functions` at `emit_function` entry | already-present (as 12) |
| 22 | src/native/emitter/memory/device_addr.rs | `@@ -18,6 +18,23` | route the raw value load through `emit_raw_value_load` | already-present: `a_raw_aggregate_array_of_vectors_load_is_built_element_wise` passes |
| 23 | src/native/emitter/memory/device_addr.rs | `@@ -29,7 +46,7` | lane offset includes the `base_byte` argument | already-present (as 22) |
| 24 | src/native/emitter/memory/device_addr.rs | `@@ -43,9 +60,42` | array element-wise raw load at LLVM allocation stride | already-present (as 22) |
| 25 | src/native/emitter/mod.rs | `@@ -194,6 +194,9` | `started_functions: HashSet<String>` field | already-present (as 12) |
| 26 | src/native/emitter/mod.rs | `@@ -543,6 +546,11` | run `propagate_raw_buffer_params` after inlining leaf helpers | already-present: NullMoth has `propagate_raw_buffer_params`; the call-order tests pass |
| 27 | src/native/emitter/mod.rs | `@@ -632,6 +640,7` | initialise `started_functions` | already-present (as 25) |
| 28 | src/native/emitter/mod.rs | `@@ -2838,6 +2847,7` | emit functions in `callers_before_raw_callees` order | already-present: `native_raw_call_offset_reaches_loop_helper_defined_before_kernel` passes |
| 29 | src/native/emitter/mod.rs | `@@ -2885,6 +2895,92` | `callers_before_raw_callees` (topological order on raw-cursor call edges) | already-present (as 28) |
| 30 | src/native/emitter/types.rs | `@@ -572,6 +572,11` | `Float32Bits` literal used as `half` becomes binary16 (`+qnan`, `+inf`) | ported (applied cleanly). `f32_bit_special_literals_in_half_code_become_binary16` failed on pristine and passes now. |
| 31 | src/native/ir/mod.rs | `@@ -289,6 +289,17` | track pointer roots through `insertvalue` / `extractvalue` | already-present: round-trip test passes |
| 32 | src/native/ir/mod.rs | `@@ -305,6 +316,55` | `metal2vulkan.inline_parameter` proxy roots and aggregate field map | already-present (as 31) |
| 33 | src/native/tests/buffers.rs | `@@ -13970,3 +13970,425` | 11 regression tests (the `native_raw_*`, `a_narrower_*`, `a_raw_aggregate_*` tests) | ported as tests. The hunk failed to apply (NullMoth's file tail differs). The 422 added lines were appended verbatim at the end of the file. |
| 34 | src/native/tests/types.rs | `@@ -3198,3 +3198,26` | test `f32_bit_special_literals_in_half_code_become_binary16` | ported as test (applied cleanly) |
| 35 | src/passes/resources/collapse.rs | `@@ -1405,7 +1405,20` | keep the emitter's sidecar resource paths when rebuilding a struct insert | ported (applied cleanly). Makes the two collapse tests pass. |
| 36 | src/passes/resources/collapse.rs | `@@ -1867,6 +1880,117` | two regression tests `resource_wrapper_collapse_keeps_both_resources_in_a_mixed_struct_*` | ported as tests (applied cleanly) with one API adaptation, below |

Counts: ported 17 (rows 2-11, 19-20, 30, 33-36; rows 33, 34 and 36 are test-only), already-present 17 (rows 12-15, 17-18, 21-29, 31-32), dropped 2 (rows 1, 16). Total 36.

## API adaptations (every change needed to compile or keep behaviour)

1. **metal2vulkan (NullMoth)**: the `Validation` enum, the `validation` parameter on the two internal functions, and `translate_sanitized_native_reflected_unvalidated` (rows 3-11). This was the only compile error in n48xlate (`cannot find function translate_sanitized_native_reflected_unvalidated`). Callers outside the reflected path keep `Validation::External`, so their behaviour is unchanged.
2. **Test adaptation** (row 36): our test used `HashSet::from([...])`. NullMoth's `HashSet` is the fxhash alias, so the test uses `crate::fxhash::set_from([texture, sampler])`. The assertions are unchanged.
3. **Test placement** (row 33): the buffers test block was appended verbatim, since the hunk context no longer matched.
4. **Workspace** (row 2): the root `translator/Cargo.toml` is new (it did not exist upstream).
5. **n48xlate**: `src/` is byte-identical to ours (`diff -rq` empty). Only `Cargo.toml` changed (`metal2vulkan` path). The exported C ABI (`n48x_abi_version`, `n48x_free`, `n48x_translate`, `n48x_translate_linked`) and the header contract are unchanged, and `n48x_abi_version()` returns 2.

No assertion was weakened and no test fixture path had to be changed.

## Not ported, and why it matters

- Rows 12-14, 21, 25, 27, 28, 29 (raw-cursor refusal and ordering) and rows 15-18 (inline-parameter cursor) were not applied. The reason is the test evidence above, not a claim that the code is identical. If NullMoth's output for a real shader differs in a way that depends on these paths, the corpus comparison in RESULTS.md is where that shows up. It does not show it for the 48 shaders tested, but those shaders are not a proof.

## Phase 2: configuration for the Metal bundle (added)

Two port changes, both needed for the bundle's binding model, and both outside NullMoth's defaults:

- **Bindless routing switches** (`passes/resources/buffer_addresses.rs`, `passes/stage_input/mod.rs`, `texture_array.rs`, `lib.rs`): `metal2vulkan::set_bindless_routing(plain_textures, texture_arrays)`. Defaults `(true, true)` are NullMoth's behaviour. The `plain` switch gates ordinary-texture heap routing (`stage_input`), which is what declares the BufferAddressTable for texture shaders. The `arrays` switch gates texture-array element routing.
- **n48xlate settings** (`n48xlate/src/lib.rs`): `BINDLESS_PLAIN = false`, `BINDLESS_ARRAYS = true`, set before each translation. Also a refusal: a module whose reflection contains a BufferAddressTable is refused (return code 1), because the bundle refuses any buffer descriptor at binding >= 32.

Evidence (48 inputs, final dylib): spirv-val (vulkan1.3) PASS 48/48; no BufferAddressTable; meta equal to OLD apart from `reflection_version`; capabilities gained: only 55 (3 modules). The SPIR-V differs from OLD by NullMoth fixes (OpIsNan/OpSelect pairs in fragment shaders, +67 instructions total).

## Phase 3 change

`BINDLESS_ARRAYS` set to `false` in the n48xlate wrapper. Texture arrays take the classic per-binding descriptor-array path (same output as OLD on the test input in RESULTS.md, Phase 3). The BAT refusal guard is kept.
