// Host test for the display profile seam (cobalt64/src/navi48-bringup/src/dcn/navi48_disp_profile.h).
// Build: tools/hosttests/run.sh (once for the default Navi 44 profile, once with -DN4X_ASIC_NAVI48).
// Usage: test_disp_profile <dcn_4_1_0_offset.h>
// Checks every absolute dword formula against the DCN 4.1.0 header, the live-path values of each profile (Navi 48 = Cobalt64,
// Navi 44 = the GOP dump of boot15), and that Navi 44 refuses every multi-display feature. Read-only.
#include "dcn/navi48_disp_profile.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>

static int failures = 0;
#define CHECK(cond, ...) do { if (!(cond)) { ++failures; std::printf("FAIL: " __VA_ARGS__); std::printf("\n"); } } while (0)

static std::map<std::string, uint32_t> read_offsets(const char *path) {
	std::map<std::string, uint32_t> off;
	FILE *f = std::fopen(path, "r");
	if (!f) { std::perror(path); return off; }
	char line[512];
	while (std::fgets(line, sizeof line, f)) {
		char name[256], val[64];
		if (std::sscanf(line, "#define reg%255s %63s", name, val) == 2 && val[0] == '0' && (val[1] == 'x' || val[1] == 'X'))
			off[name] = (uint32_t)std::strtoul(val, nullptr, 16);
	}
	std::fclose(f);
	return off;
}

int main(int argc, char **argv) {
	if (argc != 2) { std::fprintf(stderr, "usage: %s dcn_4_1_0_offset.h\n", argv[0]); return 2; }
	const std::map<std::string, uint32_t> off = read_offsets(argv[1]);
	CHECK(!off.empty(), "header unreadable");
	const uint32_t seg2 = n4xdisp::kSeg2;
	CHECK(seg2 == 0x34c0u, "DMU segment 2 is %#x, not 0x34c0 (dump)", seg2);

	// 1. formulas against the header, for all four links / DIGs
	for (uint32_t n = 0; n < 4; n++) {
		char a[64], b[64], c[64];
		std::snprintf(a, sizeof a, "DP%u_DP_VID_STREAM_CNTL", n);
		std::snprintf(b, sizeof b, "DP%u_DP_STEER_FIFO", n);
		std::snprintf(c, sizeof c, "DIG%u_DIG_FIFO_CTRL0", n);
		CHECK(off.count(a) && n4xdisp::dpVidAbs(n) == seg2 + off.at(a), "dpVidAbs(%u) = %#x, header %s + seg2", n, n4xdisp::dpVidAbs(n), a);
		CHECK(off.count(b) && n4xdisp::dpSteerAbs(n) == seg2 + off.at(b), "dpSteerAbs(%u) = %#x, header %s + seg2", n, n4xdisp::dpSteerAbs(n), b);
		CHECK(off.count(c) && n4xdisp::digFifoCtrl0Abs(n) == seg2 + off.at(c), "digFifoCtrl0Abs(%u) = %#x, header %s + seg2", n, n4xdisp::digFifoCtrl0Abs(n), c);
	}

	// 2. live path of this profile
#if defined(N4X_ASIC_NAVI44)
	const char *prof = "navi44";
	CHECK(n4xdisp::kLitDp == 0 && n4xdisp::kLitDig == 0 && n4xdisp::kLitSymclk == 0, "navi44 live path is not DP0 / DIG0 / SYMCLKA");
	CHECK(n4xdisp::dpVidAbs(0) == 0x55E2u && n4xdisp::dpSteerAbs(0) == 0x55E3u && n4xdisp::digFifoCtrl0Abs(0) == 0x555Bu,
	      "navi44 live absolute dwords are not the dump values (0x55E2 / 0x55E3 / 0x555B)");
#else
	const char *prof = "navi48";
	CHECK(n4xdisp::kLitDp == 1 && n4xdisp::kLitDig == 1 && n4xdisp::kLitSymclk == 1, "navi48 live path is not DP1 / DIG1 / SYMCLKB");
	CHECK(n4xdisp::dpVidAbs(1) == 0x5706u && n4xdisp::dpSteerAbs(1) == 0x5707u && n4xdisp::digFifoCtrl0Abs(1) == 0x567Fu,
	      "navi48 live absolute dwords changed (expected 0x5706 / 0x5707 / 0x567F)");
#endif

	// 3. feature policy: Navi 48 keeps every feature, Navi 44 refuses every one
	using namespace n4xdisp;
	const Feature all[] = { kFeatM6, kFeatM6Flip, kFeatM6Flip1, kFeatDisp2, kFeatDmubCmd, kFeatModeTrial };
#if defined(N4X_ASIC_NAVI44)
	for (Feature f : all) CHECK(!supported(f), "navi44 must refuse feature %d", (int)f);
#else
	for (Feature f : all) CHECK(supported(f), "navi48 must keep feature %d", (int)f);
#endif

	std::printf("profile %s: %s\n", prof, failures == 0 ? "checks passed" : "checks FAILED");
	std::puts(failures == 0 ? "PASS" : "FAIL");
	return failures == 0 ? 0 : 1;
}
