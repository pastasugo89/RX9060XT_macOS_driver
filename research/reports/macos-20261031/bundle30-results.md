# Metal bundle 30: vertex-only render pipelines and invisible fallback (2026-10-31)

Work dir: `research/builds/macos-20261031/bundle30-src/` (copy of bundle29-src with `cp -Rp`). Edited: `src/Navi48Device.m`, `src/Info.plist` (CFBundleVersion 29 -> 30, the same key bundle 29 bumped), `tests/test-depth.c` (one assertion updated for the new depth-write expression), new `tests/test-b30-vonly.sh`. Nothing was installed, nothing committed, bundle29-src was not touched, no sudo.

## 1. Changes (`src/Navi48Device.m`, bundle-30 line numbers)

- **Vertex-only pipeline** (`vonly = (d.fragmentFunction == nil)`, ~3963): no fragment lookup, translation, reflection or module build. The fragment is considered satisfied in both `n48_pl_stages_ready(...)` checks (the inproc translate sets `tf = (vonly || fsd)`, so `n48x_translate_fn` is never called with nil). The error reported is the vertex one.
- **No fragment SPIR-V**: `fsp` nil, `rf` NULL, `fep` stays "main", `_fs = VK_NULL_HANDLE` (~4021). `n48_stage_dsl(NULL, 1, ...)` creates an empty set 1 (verified: 0 bindings, valid layout; the fallback path already used this).
- **Stage count**: `.stageCount = n48_pl_stage_count(_fs != VK_NULL_HANDLE)` in `n48Build` (1 stage when no fragment module). Destroy path already checks `if (_fs)`.
- **Colour write masks**: `if (vonly || n48_pl_fb_invisible(fb, n48_magenta_kill())) wm = 0;` (~4076).
- **Log**: `pipeline: no fragment function: vertex-only pipeline (depth/stencil only, colour write masks 0)` once per pipeline (~4030).
- **Hot-swap**: vertex-only registers `@[ sv ]` only (~4180). `n48HotRebuild` builds from `_hsDesc` with noFallback; it works with a nil fragment (no fragment lookup).
- **Audit item 7**: `n48_dump_pipeline` (~2042) skips a nil fragment (it would have added a "fragment function is nil" note). Other paths checked and left unchanged: `n48x_prop` and `n48x_linkage_check` are nil-safe; `n48_fn_sha(nil)` returns nil; the draw path fills set 1 only when `npbF != 0`; Metal reflection (`refl`) is ignored by this driver, so nothing returns fragment arguments; `_need` holds vertex bindings only. Item 8 (N48_ONCE text) not changed.
- **Invisible fallback (coordinator request)**: when `fb` is true, colour write masks are 0 (`n48_pl_fb_invisible`), and in `n48Build` `depthWriteEnable` and `stencilTestEnable` are forced off (`inv`), so the fallback writes no depth and no stencil. The FALLBACK log lines are unchanged. The pipeline log names `FALLBACK invisible` or `FALLBACK magenta`.
- **Kill file**: `/private/tmp/n48m-magenta` (`N48_MAGENTA_FILE`, `n48_magenta_kill()`), read once per process with `dispatch_once`, same style as `N48_NOUINT_FILE`. If present, fallback draws magenta exactly as before (colour and depth/stencil written). Compute fallback not touched.
- **Helpers** (block `n48-vonly-helpers`, ~3922): `n48_pl_stages_ready`, `n48_pl_stage_count`, `n48_pl_fb_invisible`. The host test extracts this block from the real file.

## 2. Build

Staged in `build-30-tree/` (copy of `build-29-newxlate/build.sh` and the headers, `Info.plist`, `Navi48Device.m` from `src/`). `build.sh` run with the bundle-29 inputs: `N48_VK_INC=research/ext/mesa-darwin/include`, `N48_RADV_LIB` and `N48_XLATE_LIB` from `build-29-newxlate/.../Resources/`, `N48_SPVCACHE_DIR` = that tree's spvcache (230 .spv / 230 .meta.json, 460 files, identical sha of the file list). Defaults: navi44, N48_LAZY=1, N48_9D=1. The tar was extracted to `build-30/Navi48Metal.bundle`. Log: `build-30-tree.log`.

| item | value |
|---|---|
| `build-30/Navi48Metal.bundle/Contents/MacOS/Navi48Metal` | `8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230` |
| `Resources/libn48xlate.dylib` | `9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a` (as required) |
| `Resources/libvulkan_radeon.dylib` | `f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155` (as required) |
| `src/Navi48Device.m` | `27d61905c873ff49b38a530d12ae51ed8dd6bf0d3f8d6cbfac720ba52b3b96e0` |

`codesign --verify --deep --strict -vv`: valid on disk, satisfies its Designated Requirement (`build-30/verify-deep-strict.txt`). CFBundleVersion reads 30. The binary contains the new strings.

Note: the binary is not byte-identical to any earlier build (different inputs and `__DATE__`/`__TIME__`, as RESULTS for bundle 29 explains).

## 3. Tests

Same runner, same flags as bundle 29, run from `tests/` against `../src` (`summary-b30.txt`, logs in `tests/logs/`). Bundle 29 run through the same script gives the same results, except test-depth, which I updated (see below):

- Pass (rc 0): asic, btcache, cblog, cienv, crc, dispflip, drawcache, dumpacl, heapalloc, hotswap, impcache, ioalias, ledger, occ, plane, pool, t1, texdesc (11740 checks), xlate-linked, b29-fixes (15), b29-key.
- Pre-existing failures, same as bundle 29: test-depth 1 of 133 (multisample binding), test-intfmt 1 (stale version pin), test-m6route, test-m6x (repo-relative paths), test-xlate (overrides.txt path).
- New: `test-b30-vonly.sh`: 10 helper checks plus 16 source-wiring checks, PASS.
- test-depth: its check asserted the old `.depthWriteEnable = dv.depthWrite ? ...` text. I changed the assertion to the new expression (`(dv.depthWrite && !inv)`). The failure would be the same without the update.

Not run: anything on hardware, WindowServer, or iconservicesagent. No execution test of the pipeline itself (needs Metal and Vulkan).

## 4. Doubts

- Whether RADV accepts a pipeline with no fragment stage and colour masks 0 on the target GPU: not tested.
- Invisible fallback: the icon stays transparent until the hot-swap (~0.8 s), by design. Depth and stencil writes are off in the fallback variant; a fallback draw that a client expects to write stencil for a later pass will not do so.
- `n48_magenta_kill()` is called from the variant builder too; the one-time read happens on the first pipeline, so the kill-file log line appears there.
- The `build-30-tree/` staging dir holds an arm64 sanity binary (`build/sanity`, not shipped) and the tar; `build-30/` holds the shipped bundle.
