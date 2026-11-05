Build (macOS, Rust >= 1.87). Current base: NullMoth translator at tag v2.7.2
(commit 18ba05f38b5eadea8b5ae05834bb51c61fb4c5c3). It is the base from bundle 36 on.
Bundles 29 to 35 embed the 2.6.5-based libn48xlate.dylib (sha256 9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a).

    git clone https://github.com/nullmoth/nvidia-macos-driver
    cd nvidia-macos-driver && git checkout v2.7.2
    patch -p1 < /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0003-n48xlate-on-nullmoth-translator-v2.7.2.patch
    cd translator && MACOSX_DEPLOYMENT_TARGET=12.0 cargo build --release -p n48xlate --target x86_64-apple-darwin
    # result: translator/target/x86_64-apple-darwin/release/libn48xlate.dylib

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
Eleven regression tests come with it; the NullMoth suite shows no regression (see RESULTS.md in the build folder).

n48xlate turns bindless texture routing off (BINDLESS_PLAIN and BINDLESS_ARRAYS in n48xlate/src/lib.rs, both false)
and refuses a module that still needs a BufferAddressTable: the Metal bundle does not bind one.
The C ABI version stays 2.

Earlier bases, kept for reference:
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

See NOTICE for the licence (LGPL-3.0-or-later; separate from the MIT code in this repository).
