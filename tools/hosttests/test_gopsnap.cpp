// Host test for the GOP observation table (cobalt64/src/navi48-bringup/src/dcn/navi48_gopsnap.h) and the display connector
// constants of asic_profile.h (N4X_DISP_*). Read-only: it reads the header and the discovery dump, writes nothing.
// Build: tools/hosttests/run.sh   Usage: test_gopsnap <dcn_4_1_0_offset.h> <ip_discovery_table.bin> <SEG1> <SEG2> <SEG3>
//   SEG1..SEG3 are the DMU segment bases the census uses (N48DR_SEG1..3, navi48_dispread.h); the test checks them against the dump.
#include "navi48_gopsnap.h"
#include "navi48_dispread.h"
#include "ipdiscovery.hpp"
#include "amd/asic_profile.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

static int failures = 0;
#define CHECK(cond, ...) do { if (!(cond)) { ++failures; std::printf("FAIL: " __VA_ARGS__); std::printf("\n"); } } while (0)

// name -> (BASE_IDX, offset) from the header's `#define regNAME 0x..` and `#define regNAME_BASE_IDX n` lines.
static bool read_header(const char *path, std::map<std::string, std::pair<int, uint32_t>> &out) {
	FILE *f = std::fopen(path, "r");
	if (!f) { std::perror(path); return false; }
	std::map<std::string, uint32_t> off;
	std::map<std::string, int> bi;
	char line[512];
	while (std::fgets(line, sizeof line, f)) {
		char name[256], val[64];
		int idx;
		if (std::sscanf(line, "#define reg%255s %63s", name, val) == 2) {
			std::string n = name;
			if (n.size() > 9 && n.compare(n.size() - 9, 9, "_BASE_IDX") == 0) {
				n.resize(n.size() - 9);
				if (std::sscanf(val, "%d", &idx) == 1) bi[n] = idx;
			} else if (val[0] == '0' && (val[1] == 'x' || val[1] == 'X')) {
				off[n] = (uint32_t)std::strtoul(val, nullptr, 16);
			}
		}
	}
	std::fclose(f);
	for (auto &kv : off) {
		auto it = bi.find(kv.first);
		out[kv.first] = std::make_pair(it == bi.end() ? -1 : it->second, kv.second);
	}
	return !out.empty();
}

// The display profile constants (asic_profile.h): what the connector map must say for the profile this file is built for.
static void check_profile_consts() {
#if defined(N4X_ASIC_NAVI44)
	const char *prof = "navi44";
	CHECK(N4X_DISP_DP_DIG == 0 && N4X_DISP_DP_PHY == 0 && N4X_DISP_DP_LINE == 0 && N4X_DISP_DP_HPD == 1, "navi44 DP != DIG0 / PHY A / line 0 / HPD1 (VBIOS)");
	CHECK(N4X_DISP_HDMI1_DIG == 1 && N4X_DISP_HDMI1_PHY == 1 && N4X_DISP_HDMI1_LINE == 1 && N4X_DISP_HDMI1_HPD == 2, "navi44 HDMI-A-1 != DIG1 / PHY B / line 1 / HPD2 (VBIOS)");
	CHECK(N4X_DISP_HDMI2_DIG == 2 && N4X_DISP_HDMI2_PHY == 2 && N4X_DISP_HDMI2_LINE == 2 && N4X_DISP_HDMI2_HPD == 3, "navi44 HDMI-A-2 != DIG2 / PHY C / line 2 / HPD3 (VBIOS)");
	CHECK(N4X_DISP_HAS_PHY_D == 0, "navi44 must not have PHY D");
#else
	const char *prof = "navi48";
	CHECK(N4X_DISP_DP_DIG == 1 && N4X_DISP_DP_PHY == 1 && N4X_DISP_DP_LINE == 1 && N4X_DISP_DP_HPD == 2, "navi48 DP != DIG1 / PHY B / line 1 / HPD2 (Cobalt64)");
	CHECK(N4X_DISP_HDMI1_DIG == 2 && N4X_DISP_HDMI1_PHY == 2 && N4X_DISP_HDMI1_LINE == 2 && N4X_DISP_HDMI1_HPD == 3, "navi48 monitor A != DIG2 / PHY C / line 2 / HPD3 (Cobalt64)");
	CHECK(N4X_DISP_HDMI2_DIG == 3 && N4X_DISP_HDMI2_PHY == 3 && N4X_DISP_HDMI2_LINE == 3 && N4X_DISP_HDMI2_HPD == 4, "navi48 monitor B != DIG3 / PHY D / line 3 / HPD4 (Cobalt64)");
	CHECK(N4X_DISP_HAS_PHY_D == 1, "navi48 has PHY D");
#endif
	std::printf("profile %s: connector constants checked\n", prof);
}

int main(int argc, char **argv) {
	if (argc != 6) { std::fprintf(stderr, "usage: %s dcn_4_1_0_offset.h ip_discovery_table.bin SEG1 SEG2 SEG3\n", argv[0]); return 2; }

	// 1. count and uniqueness
	const size_t n = sizeof(n48gop_regs) / sizeof(n48gop_regs[0]);
	CHECK(n == N48GOP_COUNT && n48gop_count() == N48GOP_COUNT, "table holds %zu rows, N48GOP_COUNT %u", n, (unsigned)N48GOP_COUNT);
	std::map<std::string, int> seen;
	for (size_t i = 0; i < n; i++) seen[n48gop_regs[i].name]++;
	for (auto &kv : seen) CHECK(kv.second == 1, "name %s appears %d times", kv.first.c_str(), kv.second);
	std::printf("rows: %zu, unique names: %zu\n", n, seen.size());

	// 2. every row against the header: BASE_IDX and offset
	std::map<std::string, std::pair<int, uint32_t>> hdr;
	if (!read_header(argv[1], hdr)) { std::puts("FAIL: header unreadable"); return 1; }
	size_t matched = 0;
	const size_t nl = sizeof(n48gop_live) / sizeof(n48gop_live[0]);
	CHECK(nl == N48GOP_LIVE_COUNT, "liveness table holds %zu rows, N48GOP_LIVE_COUNT %u", nl, (unsigned)N48GOP_LIVE_COUNT);
	for (size_t i = 0; i < n + nl; i++) {
		const struct n48gop_reg &r = i < n ? n48gop_regs[i] : n48gop_live[i - n];
		auto it = hdr.find(r.name);
		if (it == hdr.end()) { CHECK(false, "%s not in %s", r.name, argv[1]); continue; }
		CHECK(it->second.first == r.base_idx, "%s BASE_IDX %d in header, %u in table", r.name, it->second.first, (unsigned)r.base_idx);
		CHECK(it->second.second == r.off, "%s offset %#x in header, %#x in table", r.name, it->second.second, (unsigned)r.off);
		if (it->second.first == r.base_idx && it->second.second == r.off) matched++;
	}
	std::printf("header rows matching (name, BASE_IDX, offset): %zu / %zu\n", matched, n + nl);

	// 3. DMU segment bases of the dump: the census and the table resolve BASE_IDX 1..3 through these
	FILE *f = std::fopen(argv[2], "rb");
	if (!f) { std::perror(argv[2]); return 2; }
	std::vector<uint8_t> buf(1 << 20);
	size_t got = std::fread(buf.data(), 1, buf.size(), f);
	std::fclose(f);
	IpDiscovery d;
	IpDiscovery::IpEntry dmu{};
	CHECK(d.init(buf.data(), got), "discovery init");
	CHECK(d.findIp(IpDiscovery::HwDmu, 0, dmu) && dmu.numBases >= 3, "DMU entry with >= 3 segments");
	if (dmu.numBases >= 3) {
		std::printf("DMU bases in dump: %#x %#x %#x %#x %#x\n", dmu.bases[0], dmu.bases[1], dmu.bases[2], dmu.bases[3], dmu.bases[4]);
		CHECK(dmu.bases[1] == std::strtoul(argv[3], nullptr, 0), "SEG1 %s != dump DMU base[1] %#x", argv[3], dmu.bases[1]);
		CHECK(dmu.bases[2] == std::strtoul(argv[4], nullptr, 0), "SEG2 %s != dump DMU base[2] %#x", argv[4], dmu.bases[2]);
		CHECK(dmu.bases[3] == std::strtoul(argv[5], nullptr, 0), "SEG3 %s != dump DMU base[3] %#x", argv[5], dmu.bases[3]);
	}
	CHECK(N48DR_SEG1 == 0xc0u && N48DR_SEG2 == 0x34c0u && N48DR_SEG3 == 0x9000u, "census segment constants moved");

	// 4. display connector constants of this profile
	check_profile_consts();

	std::puts(failures == 0 ? "PASS" : "FAIL");
	return failures == 0 ? 0 : 1;
}
