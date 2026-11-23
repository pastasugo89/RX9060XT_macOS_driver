// 0.0.677 host test (0.0.679: Linux's units by default, navi48-gfxdb=0 = the 0.0.676 index): the kernel GFX queue's doorbell (amd/cp_doorbell_pure.h) and source pins on its consumers.
// Build: clang++ -std=c++17 -I src tests/gfx_doorbell677_test.cpp ; run: ./a.out <kernel source dir (holding src/)> <linux drm/amd dir>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <fstream>
#include <sstream>
#include <regex>
#include "amd/cp_doorbell_pure.h"

static int fails = 0, checks = 0;
static void expect(bool ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } }
static std::string slurp(const std::string &p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static size_t count(const std::string &s, const std::string &n) { size_t c = 0, at = 0; while ((at = s.find(n, at)) != std::string::npos) { c++; at += n.size(); } return c; }

using namespace n48db;

// AMDGPU_NAVI10_DOORBELL_ASSIGNMENT (amdgpu_doorbell.h), the map amd/amdgpu_ip.h DoorbellIndex carries.
static uint32_t kKiq = 0x000, kMesRing0 = 0x00B, kUqEnd = 0x08A, kGfxRing0 = 0x08B, kGfxUqEnd = 0x0FF;

static void test_pure() {
    const uint32_t gfxLo = window_reg(kGfxRing0), gfxHi = window_reg(kGfxUqEnd), mecLo = window_reg(kKiq), mecHi = window_reg(kUqEnd);
    expect(gfxLo == 0x458 && gfxHi == 0x7F8 && mecLo == 0x000 && mecHi == 0x450, "Linux's window registers (gfx_v12_0_cp_set_doorbell_range)");
    // the fix: Linux's index
    const uint32_t lx = kgq_index(kGfxRing0, kModeLinux);
    expect(lx == 0x116 && byte_offset(lx) == 0x458, "gfx_ring0 << 1 = 0x116, byte 0x458 (gfx_v12_0.c:927, WDOORBELL64)");
    expect(where(lx, gfxLo, gfxHi, mecLo, mecHi) == kInGfx && qword_aligned(lx), "the Linux doorbell is in the GFX window and qword-aligned");
    // the bug: the pre-0.0.677 index
    const uint32_t old = kgq_index(kGfxRing0, kModeLegacy);
    expect(old == 0x8B && byte_offset(old) == 0x22C, "the old index 0x8B, byte 0x22C");
    expect(where(old, gfxLo, gfxHi, mecLo, mecHi) == kInMec && !qword_aligned(old), "the old doorbell lands in the COMPUTE window, at an odd dword");
    // the boot-arg
    // 0.0.679: Linux's index is the default (the 0.0.676..0.0.678 index sits in the MEC window and leaves the fetcher busy once the KCQ is mapped);
    // navi48-gfxdb=0 is the kill switch.
    expect(mode_of(false, 0) == kModeLinux && mode_of(true, 1) == kModeLinux && mode_of(true, 0) == kModeLegacy && mode_of(true, 7) == kModeLinux,
           "navi48-gfxdb: Linux's index by default (0.0.679); 0 = the 0.0.676..0.0.678 index");
    // the legacy doorbell map (navi48-doorbell-legacy=1: gfx_ring0 = 0) keeps 0 either way
    expect(kgq_index(0, kModeLinux) == 0 && kgq_index(0, kModeLegacy) == 0, "legacy map: index 0 in both modes");
    // the MES ring is untouched by 0.0.677 and is inside the MEC window
    expect(where(kMesRing0, gfxLo, gfxHi, mecLo, mecHi) == kInMec, "the MES ring doorbell (dword 0x0B) is in the MEC window");
    expect(where(0x300, gfxLo, gfxHi, mecLo, mecHi) == kOutside, "outside both");
}

static void test_linux(const char *lxdir) {
    if (!lxdir) { printf("(Linux cross-check skipped)\n"); return; }
    const std::string root = lxdir;
    const std::string gfx = slurp(root + "/amdgpu/gfx_v12_0.c"), db = slurp(root + "/amdgpu/amdgpu_doorbell.h");
    expect(gfx.find("ring->doorbell_index = adev->doorbell_index.gfx_ring0 << 1;") != std::string::npos, "Linux shifts gfx_ring0 by one");
    expect(gfx.find("(adev->doorbell_index.gfx_ring0 * 2) << 2);") != std::string::npos, "Linux's GFX window lower");
    expect(gfx.find("(adev->doorbell_index.userqueue_end * 2) << 2);") != std::string::npos, "Linux's MEC window upper");
    auto val = [&](const char *name) -> long {
        std::smatch m; std::regex r(std::string(name) + "\\s*=\\s*(0x[0-9A-Fa-f]+)");
        return std::regex_search(db, m, r) ? std::stol(m[1].str(), nullptr, 16) : -1;
    };
    expect(val("AMDGPU_NAVI10_DOORBELL_GFX_RING0") == kGfxRing0 && val("AMDGPU_NAVI10_DOORBELL_GFX_USERQUEUE_END") == kGfxUqEnd &&
           val("AMDGPU_NAVI10_DOORBELL_KIQ") == kKiq && val("AMDGPU_NAVI10_DOORBELL_USERQUEUE_END") == kUqEnd &&
           val("AMDGPU_NAVI10_DOORBELL_MES_RING0") == kMesRing0, "the Navi10 map values");
}

static void test_sources(const char *dir) {
    if (!dir) { printf("(source pins skipped)\n"); return; }
    const std::string root = dir;
    const std::string cp = slurp(root + "/src/amd/cp_v12_0.cpp"), ip = slurp(root + "/src/amd/amdgpu_ip.h"), n1c = slurp(root + "/src/amd/native_s1c.cpp");
    const std::string br = slurp(root + "/src/Navi48Bringup.cpp");
    expect(!cp.empty() && !ip.empty() && !n1c.empty() && !br.empty(), "sources read");
    expect(ip.find("uint32_t gfx_ring0           = 0x08B;") != std::string::npos && ip.find("uint32_t userqueue_end   = 0x08A;") != std::string::npos,
           "the kext's map is the Navi10 map");
    expect(cp.find("cp.doorbell_index = n48db::kgq_index(dev.doorbell.index.gfx_ring0, gGfxDbMode);") != std::string::npos, "the queue index is kgq_index");
    expect(count(cp, "cp.doorbell_index = ") == 2, "assigned only at reset (0) and in cp_init_full");
    expect(cp.find("n48db::window_reg(dev.doorbell.index.gfx_ring0));") != std::string::npos, "the GFX window comes from gfx_ring0, not from the queue index");
    expect(cp.find("(cp.doorbell_index * 2u) << 2") == std::string::npos, "no window from the queue index");
    expect(cp.find("REG_SET_FIELD(tmp, CP_RB_DOORBELL_CONTROL, DOORBELL_OFFSET, cp.doorbell_index);") != std::string::npos, "the MQD uses the queue index");
    expect(cp.find("in.doorbell_offset = cp.doorbell_index;") != std::string::npos, "ADD_QUEUE uses the queue index");
    expect(cp.find("static_cast<uint64_t>(cp.doorbell_index) *\n                         kCPDoorbellStride;") != std::string::npos, "cp_kick_doorbell writes at index * 4");
    expect(n1c.find("const uint64_t off = (uint64_t)cp.doorbell_index * kCPDoorbellStride;") != std::string::npos, "the native ring writes at index * 4");
    expect(count(n1c, "cp.doorbell_index") == 4, "native: the doorbell write and the three MES frames, all from the queue index");
    expect(cp.find("\"navi48-gfxdb\"") != std::string::npos, "the kill switch is read");
    expect(br.find("setProperty(\"Navi48,GfxDoorbell\", t);") != std::string::npos, "Navi48,GfxDoorbell published");
}

int main(int argc, char **argv) {
    test_pure();
    test_sources(argc > 1 ? argv[1] : nullptr);
    test_linux(argc > 2 ? argv[2] : nullptr);
    printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
    return fails ? 1 : 0;
}
