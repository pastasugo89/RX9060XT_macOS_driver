//
//  fw_table.cpp — implementation of ../fw/fw_table.h.
//
//  Lives in src/amd/ (not src/fw/, despite the header living there) on
//  purpose: the Makefile globs `src/fw/*.c` and `src/amd/*.cpp`, but NOT
//  `src/fw/*.cpp` (see the Makefile's CXX_SRCS/C_SRCS lines, and
//  PORTING.md rule 8 — the Makefile is not to be edited). A same-
//  directory src/fw/fw_table.cpp would therefore never be added to
//  CXX_SRCS and would silently never compile or link. Putting the C++
//  translation unit here, picked up by `$(wildcard src/amd/*.cpp)`,
//  keeps the build's existing glob untouched while still building this
//  file. fw_table.h itself is a header (not compiled directly), so its
//  location in src/fw/ has no effect on the build.
//
//  No allocation, no STL, no exceptions/RTTI. Table build strategy:
//
//  Each generated src/fw/fw_<blob>.c defines `fw_<blob>_size` as an
//  extern `const size_t` in ITS OWN translation unit — this TU only sees
//  its *declaration*, not its value, so `fw_<blob>_size` cannot be used
//  as a constant-expression initializer here (tried `constexpr FwBlob
//  kFwTable[] = { { fw_x, fw_x_size, ... }, ... };` first: clang rejects
//  it — "constexpr variable must be initialized by a constant
//  expression" / "initializer of 'fw_x_size' is unknown" — because
//  copying an extern object's *value* across translation units is not a
//  link-time-resolvable relocation the way taking its *address* is).
//  The general fix for a POD table like this is a C++ dynamic
//  initializer (global constructor), but that needs the kext's C++
//  runtime to run `__mod_init_func`-style initializers before anything
//  calls fw_get()/fw_find_by_name() — an ordering guarantee this file
//  shouldn't assume. Instead, g_table[]/g_built below are plain
//  zero-initialized globals (.bss, no initializer at all) and
//  build_table() fills them in with an ordinary function call the first
//  time either public entry point runs — ordinary runtime assignments,
//  no allocation, no static-initialization-order dependency.
//
#include "../fw/fw_table.h"
#include "asic_profile.h"

namespace amdgpu {

// ---- extern "C" symbols from the generated src/fw/fw_*.c files --------
//
// Names/format match tools/embed-firmware.py's output and the existing
// hand-written src/fw/fw_psp_sos.c: `const uint8_t <sym>[]` (64-byte
// aligned) + `const size_t <sym>_size`.
extern "C" {

// Symbols chosen by the compiled ASIC profile (asic_profile.h).
extern const uint8_t N4X_FW_SYM(PSP_SOS)[];    extern const size_t N4X_FW_SIZE(PSP_SOS);
extern const uint8_t N4X_FW_SYM(PSP_TA)[];     extern const size_t N4X_FW_SIZE(PSP_TA);
extern const uint8_t N4X_FW_SYM(GC_IMU)[];     extern const size_t N4X_FW_SIZE(GC_IMU);
extern const uint8_t N4X_FW_SYM(GC_PFP)[];     extern const size_t N4X_FW_SIZE(GC_PFP);
extern const uint8_t N4X_FW_SYM(GC_ME)[];      extern const size_t N4X_FW_SIZE(GC_ME);
extern const uint8_t N4X_FW_SYM(GC_MEC)[];     extern const size_t N4X_FW_SIZE(GC_MEC);
extern const uint8_t N4X_FW_SYM(GC_UNI_MES)[]; extern const size_t N4X_FW_SIZE(GC_UNI_MES);
extern const uint8_t N4X_FW_SYM(GC_RLC)[];     extern const size_t N4X_FW_SIZE(GC_RLC);
extern const uint8_t N4X_FW_SYM(SMU)[];        extern const size_t N4X_FW_SIZE(SMU);
extern const uint8_t N4X_FW_SYM(SDMA)[];       extern const size_t N4X_FW_SIZE(SDMA);

} // extern "C"

namespace {

constexpr uint32_t kCount = static_cast<uint32_t>(FwId::Count);

// Plain zero-initialized statics — no constructor, lands in .bss.
FwBlob g_table[kCount];
bool   g_built = false;

// Fills g_table[] with ordinary runtime assignments (reads each extern
// fw_<blob>_size's actual value — valid the moment this kext's segments
// are mapped, well before any bring-up code could call fw_get()). Safe
// to call repeatedly; only the first call does anything. Bring-up is
// single-threaded through this point, so no guard/lock is used — see
// the file header.
//
// GC_MES, GC_MES1 and GC_TOC have no embedded blob on either profile's
// non-kicker bring-up ladder (Navi 44: psp_14_0_2/gfx1200; Navi 48: psp_14_0_3/gfx1201) (uni_mes supersedes the
// legacy split MES pair; TOC is only loaded for psp_14_0_5), so those
// rows keep data=nullptr, size=0 — see fw_table.h.
void build_table() {
    if (g_built) return;

    g_table[static_cast<uint32_t>(FwId::PSP_SOS)] =
        FwBlob{ N4X_FW_SYM(PSP_SOS), N4X_FW_SIZE(PSP_SOS), N4X_FW_PSP "_sos", FwId::PSP_SOS };
    g_table[static_cast<uint32_t>(FwId::PSP_TA)] =
        FwBlob{ N4X_FW_SYM(PSP_TA), N4X_FW_SIZE(PSP_TA), N4X_FW_PSP "_ta", FwId::PSP_TA };
    g_table[static_cast<uint32_t>(FwId::GC_IMU)] =
        FwBlob{ N4X_FW_SYM(GC_IMU), N4X_FW_SIZE(GC_IMU), N4X_FW_GC "_imu", FwId::GC_IMU };
    g_table[static_cast<uint32_t>(FwId::GC_PFP)] =
        FwBlob{ N4X_FW_SYM(GC_PFP), N4X_FW_SIZE(GC_PFP), N4X_FW_GC "_pfp", FwId::GC_PFP };
    g_table[static_cast<uint32_t>(FwId::GC_ME)] =
        FwBlob{ N4X_FW_SYM(GC_ME), N4X_FW_SIZE(GC_ME), N4X_FW_GC "_me", FwId::GC_ME };
    g_table[static_cast<uint32_t>(FwId::GC_MEC)] =
        FwBlob{ N4X_FW_SYM(GC_MEC), N4X_FW_SIZE(GC_MEC), N4X_FW_GC "_mec", FwId::GC_MEC };
    g_table[static_cast<uint32_t>(FwId::GC_MES)] =
        FwBlob{ nullptr, 0, N4X_FW_GC "_mes", FwId::GC_MES };
    g_table[static_cast<uint32_t>(FwId::GC_MES1)] =
        FwBlob{ nullptr, 0, N4X_FW_GC "_mes1", FwId::GC_MES1 };
    g_table[static_cast<uint32_t>(FwId::GC_UNI_MES)] =
        FwBlob{ N4X_FW_SYM(GC_UNI_MES), N4X_FW_SIZE(GC_UNI_MES), N4X_FW_GC "_uni_mes", FwId::GC_UNI_MES };
    g_table[static_cast<uint32_t>(FwId::GC_RLC)] =
        FwBlob{ N4X_FW_SYM(GC_RLC), N4X_FW_SIZE(GC_RLC), N4X_FW_GC "_rlc", FwId::GC_RLC };
    g_table[static_cast<uint32_t>(FwId::GC_TOC)] =
        FwBlob{ nullptr, 0, N4X_FW_GC "_toc", FwId::GC_TOC };
    g_table[static_cast<uint32_t>(FwId::SMU)] =
        FwBlob{ N4X_FW_SYM(SMU), N4X_FW_SIZE(SMU), N4X_FW_SMU, FwId::SMU };
    g_table[static_cast<uint32_t>(FwId::SDMA)] =
        FwBlob{ N4X_FW_SYM(SDMA), N4X_FW_SIZE(SDMA), N4X_FW_SDMA, FwId::SDMA };

    g_built = true;
}

// Manual equality check — deliberately not strcmp/strncmp. PORTING.md /
// the task brief only guarantee memcpy/memset/strlen/strncmp out of
// <string.h> in this kernel; strcmp isn't in that guaranteed set, and a
// bounded strncmp would need an arbitrary length cap for what is really
// an unbounded exact-match. Blob names are short, static, NUL-terminated
// C strings on both sides, so a plain loop is simplest and dependency-free.
bool str_eq(const char *a, const char *b) {
    while (*a != '\0' && *b != '\0') {
        if (*a != *b) return false;
        ++a;
        ++b;
    }
    return *a == *b; // both must be at NUL simultaneously
}

} // anonymous namespace

const FwBlob *fw_get(FwId id) {
    build_table();
    uint32_t idx = static_cast<uint32_t>(id);
    if (idx >= kCount) return nullptr;
    return &g_table[idx];
}

const FwBlob *fw_find_by_name(const char *name) {
    if (name == nullptr) return nullptr;
    build_table();
    for (uint32_t i = 0; i < kCount; ++i) {
        if (str_eq(g_table[i].name, name)) return &g_table[i];
    }
    return nullptr;
}

} // namespace amdgpu
