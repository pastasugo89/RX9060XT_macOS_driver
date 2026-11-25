Build (macOS, Rust >= 1.87). Current base: NullMoth translator at tag v3.0
(commit 5289b35091e199644a9a2e414ee6d463c6c4c401), with patches/0004. It is the base from the v3.0 port on.
Bundles 36 to 38 embed the 2.7.2-based libn48xlate.dylib (sha256 c79adc839e8ec9dda7d042eb8469630faa5dfff304105d14c41f88fb8e522f62).
Bundles 29 to 35 embed the 2.6.5-based libn48xlate.dylib (sha256 9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a).

    git clone https://github.com/nullmoth/nvidia-macos-driver
    cd nvidia-macos-driver && git checkout v3.0
    patch -p1 < /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0004-n48xlate-on-nullmoth-translator-v3.0.patch
    # put the Cargo.lock described below at translator/Cargo.lock, then:
    cd translator && MACOSX_DEPLOYMENT_TARGET=12.0 cargo build --release --locked -p n48xlate --target x86_64-apple-darwin
    cp target/x86_64-apple-darwin/release/libn48xlate.dylib libn48xlate.dylib && codesign -s - -f libn48xlate.dylib
    # result: translator/libn48xlate.dylib (ad-hoc signed), sha256 ebb746f5cffc2ae8846fec32b3ad1f5aecb75a0d26b394251699b6fefe0c4197
    # (rustc 1.99.1 on x86_64-apple-darwin; the unsigned cargo output has sha256 934cdb65e9a04dbb6cececfca37a29be0f12a96a20c6d8beabbffe2bd242fac3)

The patch does not carry Cargo.lock. The recorded build used the Cargo.lock of the v2.7.2 port
(sha256 e2fcfad2c5109564b15887db370272a9b2603438d8dc080cba3ccc8e974a2ad1). The translator and wrapper
manifests are identical at v2.7.2 and v3.0, so that lock fits v3.0 and --locked keeps those dependency
versions. Without that file, drop --locked: cargo then resolves current crates.io versions.

The patch adds the workspace root translator/Cargo.toml and the n48xlate crate (translator/n48xlate),
so one patch is enough. Do not copy them by hand.

Bundle build (build.sh): set N48_XLATE_LIB to the built dylib, or N48_M2V_DIR to
<nvidia-macos-driver checkout>/translator (build.sh looks for n48xlate/Cargo.toml under it).

What the patch changes in NullMoth's own files:
- a Validation switch (External | Skip): the in-process entry skips the external spirv-val process
  (the two structural rejects still run in both modes);
- process-wide bindless routing switches, set by n48xlate, both off (no BufferAddressTable for ordinary textures);
- a narrowing vector load and a binary16 reading of f32 bit patterns in half code;
- resource-path retention in the resource-wrapper collapse.
Eleven regression tests come with it, and all eleven pass on v3.0. The NullMoth suite (cargo test -p metal2vulkan,
all targets) shows no regression against pristine v3.0 with either validator setting: the same tests fail in both
trees (50 with the stub validator, 28 with spirv-val v2026.4). The logs are in research/builds/macos-20261123/xlate-v29/logs.

n48xlate turns bindless texture routing off (BINDLESS_PLAIN and BINDLESS_ARRAYS in n48xlate/src/lib.rs, both false)
and refuses a module that still needs a BufferAddressTable: the Metal bundle does not bind one.
The C ABI version stays 2.

The unlinked entry (n48x_translate) does not run the visible-function closure that the upstream wrapper
applies on its function-constant entry points, because n48xlate has no function-constant values to close
against. A module whose visible-function references are never called is refused there, as before; it
translates through n48x_translate_linked with no dependencies. A called reference is refused by name on both paths.

Earlier bases, kept for reference:
- patches/0003 on v2.7.2 (commit 18ba05f38b5eadea8b5ae05834bb51c61fb4c5c3): bundles 36 to 38.
    git clone https://github.com/nullmoth/nvidia-macos-driver
    cd nvidia-macos-driver && git checkout v2.7.2
    patch -p1 < /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0003-n48xlate-on-nullmoth-translator-v2.7.2.patch
    cd translator && MACOSX_DEPLOYMENT_TARGET=12.0 cargo build --release -p n48xlate --target x86_64-apple-darwin
    # result: translator/target/x86_64-apple-darwin/release/libn48xlate.dylib
- patches/0002 on ceba63c (NullMoth 2.6.5): bundles 29 to 35.
    git clone https://github.com/nullmoth/nvidia-macos-driver
    cd nvidia-macos-driver && git checkout ceba63c15ba9d81deea7cd1c5dcc4c79497bea8f
    patch -p1 < /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0002-n48xlate-on-nullmoth-translator-ceba63c.patch
    cp /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/nullmoth-workspace/Cargo.toml translator/Cargo.toml
    cp -R /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/n48xlate translator/
    cd translator && cargo build --release -p n48xlate
- patches/0001 on steelbrain/metal2vulkan 43c46ac: bundles up to 28.
    git clone https://github.com/steelbrain/metal2vulkan
    cd metal2vulkan && git checkout 43c46ac8a24adf1a6e872b8a52c706ec9614fad0
    git apply /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0001-metal2vulkan-changes-for-n48xlate.patch
    cp -R /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/n48xlate .
    (in n48xlate/Cargo.toml set the metal2vulkan path back to "..")
    cargo build --release -p n48xlate

See NOTICE for the licence (LGPL-3.0-or-later; separate from the PolyForm Noncommercial code in this repository).
