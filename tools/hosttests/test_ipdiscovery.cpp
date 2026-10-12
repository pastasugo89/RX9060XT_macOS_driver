// Host test: parse a real IP discovery dump with the kext's freestanding parser.
// Build: tools/hosttests/run.sh   Usage: test_ipdiscovery <ip_discovery_table.bin> <expect_se> <expect_sa> <expect_rb> <expect_cu_per_sh>
#include "ipdiscovery.hpp"
#include <cstdio>
#include <cstdlib>
#include <vector>

int main(int argc, char **argv) {
	if (argc != 6) { std::fprintf(stderr, "usage: %s dump se sa rb cu_per_sh\n", argv[0]); return 2; }
	FILE *f = std::fopen(argv[1], "rb");
	if (!f) { std::perror(argv[1]); return 2; }
	std::vector<uint8_t> buf(1 << 20);
	size_t n = std::fread(buf.data(), 1, buf.size(), f);
	std::fclose(f);

	IpDiscovery d;
	if (!d.init(buf.data(), n)) { std::puts("FAIL: init"); return 1; }
	IpDiscovery::IpEntry gc{};
	if (!d.findIp(IpDiscovery::HwGc, 0, gc)) { std::puts("FAIL: GC missing"); return 1; }
	IpDiscovery::GcInfo g{};
	if (!d.gcInfo(g)) { std::puts("FAIL: gcInfo"); return 1; }
	unsigned cuPerSh = 2 * (g.wgp0PerSa + g.wgp1PerSa);
	std::printf("GC %u.%u.%u  gc_info v%u.%u: se=%u sa/se=%u rb/se=%u wgp0/sa=%u wgp1/sa=%u -> cu/sh=%u, gl2c=%u gprs=%u wave=%u lds=%u\n",
	            gc.major, gc.minor, gc.revision, g.verMajor, g.verMinor, g.numSe, g.saPerSe, g.rbPerSe,
	            g.wgp0PerSa, g.wgp1PerSa, cuPerSh, g.numGl2c, g.numGprs, g.waveSize, g.ldsSize);
	bool ok = g.numSe == (unsigned)atoi(argv[2]) && g.saPerSe == (unsigned)atoi(argv[3]) &&
	          g.rbPerSe == (unsigned)atoi(argv[4]) && cuPerSh == (unsigned)atoi(argv[5]);
	std::puts(ok ? "PASS" : "FAIL: topology mismatch");
	return ok ? 0 : 1;
}
