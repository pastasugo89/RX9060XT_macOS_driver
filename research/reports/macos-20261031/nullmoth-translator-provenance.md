# PROVENANCE: nullmoth-xlate-v1

Staging directory (build and test only here):
`research/builds/macos-20261031/nullmoth-xlate-v1` (relative to the project root `rx9060xt_metal_driver`).

## Sources

| Component | Source | Identity |
|---|---|---|
| NullMoth translator (base) | git repo `research/refs/nvidia-macos-driver`, `origin/HEAD`, `git archive ... translator` | commit `ceba63c15ba9d81deea7cd1c5dcc4c79497bea8f` (2026-10-30 10:41:00 -0700, "Changelog 2.6.5: credit mickys; plain cube-as-array comment"). The working tree was not used. |
| n48xlate crate (ours) | `cobalt64/third-party/metal2vulkan-n48/n48xlate` (copied, not modified in place) | `src/` and `tests/` byte-identical to ours; `Cargo.toml` changed only in the `metal2vulkan` path (`".."` to `"../translator"`). |
| Our patch (reference only) | `cobalt64/third-party/metal2vulkan-n48/patches/0001-metal2vulkan-changes-for-n48xlate.patch` | sha256 `96e26cfbfc5957a62662448b97e6b138e9c7b36286ef5c8ef8e761436499ec3b`, 1328 lines, 36 hunks in 14 files. Base was steelbrain/metal2vulkan @43c46ac. |
| Old dylib (reference) | `research/ext/m2v/metal2vulkan/target/release/libn48xlate.dylib` (read-only use) | sha256 `9a0b6077fb6703be1193d4e68ae507cd3245a839bd4864b89502b4a8d0cd0c33`, unsigned, install name `/Users/.../research/ext/m2v/metal2vulkan/target/release/deps/libn48xlate.dylib`, exports `n48x_abi_version`, `n48x_free`, `n48x_translate`, `n48x_translate_linked`, ABI 2. |

## Where things are in the staging directory

- `translator/Cargo.toml`: workspace root added by this port (members `translator`, `n48xlate`; `wrapper` excluded because it needs spirv-tools/C++; `[profile.release] incremental = true` copied from NullMoth's crate, which is ignored when not at the root).
- `translator/Cargo.lock`: copied from NullMoth's `translator/Cargo.lock`, then updated by cargo for the n48xlate dependencies.
- `translator/translator/`: NullMoth's crate (`metal2vulkan` 0.1.0), with the port applied (see PORTING.md).
- `translator/wrapper/`: NullMoth's C-ABI wrapper, unmodified, not built (excluded).
- `translator/n48xlate/`: our crate, see above.
- `translator/LICENSE`, `translator/COPYING`: NullMoth's licence texts (LGPL-3.0-or-later; `translator/Cargo.toml` says `license = "LGPL-3.0-or-later"`).
- `COPYING`, `NOTICE`: our third-party licence texts; `n48xlate-README-ours.txt`: our third-party README.
- `work/pristine/`: unmodified snapshot of NullMoth's `src/` and `tests/` taken before the port, for diffing.
- `work/hunks/`: the 36 per-hunk diffs of our patch, used for the classification.

## Toolchain

- `rustup-init` was fetched from `https://static.rust-lang.org/rustup/dist/x86_64-apple-darwin/rustup-init` and checked against the upstream `rustup-init.sha256` (OK). `https://sh.rustup.rs` did not resolve from this machine (DNS failure), so the documented one-liner was not used; the installer itself was run with the same options (`-y --no-modify-path --default-toolchain stable --profile minimal`).
- Installed into the user's home (`~/.rustup`, `~/.cargo`). Nothing was installed into `/Library`, and no `sudo` was used.
- `rustc 1.99.1 (58cf8f9c3 2026-10-13)`, `cargo 1.99.1 (5f94df478 2026-08-27)`, host `x86_64-apple-darwin` (so no `rustup target add` was needed). Both crates declare `rust-version = "1.87"`, which is satisfied.

## Git

No commit was made. The project repository shows pre-existing modifications under `cobalt64/` and `tools/` (for example `cobalt64/tools/native/navi48metal/Navi48Device.m`). They predate this work; this task only read from `cobalt64/` and `research/ext/`.
