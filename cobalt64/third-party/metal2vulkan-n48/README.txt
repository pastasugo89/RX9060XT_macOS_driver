Build (macOS, Rust >= 1.87). Current base: NullMoth translator (since bundle 29, 31 October 2026):
    git clone https://github.com/nullmoth/nvidia-macos-driver
    cd nvidia-macos-driver && git checkout ceba63c15ba9d81deea7cd1c5dcc4c79497bea8f
    patch -p1 < /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0002-n48xlate-on-nullmoth-translator-ceba63c.patch
    cp /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/nullmoth-workspace/Cargo.toml translator/Cargo.toml
    cp -R /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/n48xlate translator/
    cd translator && cargo build --release -p n48xlate     # target/release/libn48xlate.dylib
n48xlate turns bindless texture routing off (BINDLESS_PLAIN / BINDLESS_ARRAYS in
n48xlate/src/lib.rs) and refuses a module that still needs a BufferAddressTable: the
Metal bundle does not bind one.

Previous base (bundles up to 28), kept for reference:
    git clone https://github.com/steelbrain/metal2vulkan
    cd metal2vulkan && git checkout 43c46ac8a24adf1a6e872b8a52c706ec9614fad0
    git apply /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/patches/0001-metal2vulkan-changes-for-n48xlate.patch
    cp -R /path/to/rx9060xt_metal_driver/cobalt64/third-party/metal2vulkan-n48/n48xlate .
    (in n48xlate/Cargo.toml set the metal2vulkan path back to "..")
    cargo build --release -p n48xlate
See NOTICE for the licence (LGPL-3.0-or-later; separate from the MIT code in this repository).
