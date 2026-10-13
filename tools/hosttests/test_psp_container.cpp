// Host test: the kext's PSP sos.bin container parser (psp.cpp PspLoader::parseContainer) on a real firmware blob.
// Usage: test_psp_container <psp_*_sos.bin>   (run.sh decompresses the installed .bin.zst)
#include "psp.hpp"
#include <cstdio>
#include <vector>
struct NoHw final : n48::HwAccess {
	uint32_t regReadIp(uint16_t, uint8_t, uint8_t, uint32_t) override { return 0xFFFFFFFFu; }
	bool regWriteIp(uint16_t, uint8_t, uint8_t, uint32_t, uint32_t) override { return false; }
	bool vramWrite(uint64_t, const void *, size_t) override { return false; }
	bool vramMemset(uint64_t, uint8_t, size_t) override { return false; }
};
int main(int argc, char **argv) {
	if (argc != 2) { std::fprintf(stderr, "usage: %s sos.bin\n", argv[0]); return 2; }
	FILE *f = std::fopen(argv[1], "rb"); if (!f) { std::perror(argv[1]); return 2; }
	std::vector<uint8_t> b; uint8_t buf[65536]; size_t n;
	while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) b.insert(b.end(), buf, buf + n);
	std::fclose(f);
	NoHw hw; n48::PspLoader p(hw);
	if (!p.parseContainer(b.data(), b.size())) { std::puts("FAIL: parseContainer"); return 1; }
	struct { const char *name; const n48::SubBin &s; } subs[] = {
		{"kdb", p.kdb}, {"spl", p.spl}, {"sys_drv", p.sys}, {"sos", p.sos}, {"soc_drv", p.soc}, {"intf_drv", p.intf},
		{"dbg_drv", p.dbg}, {"ras_drv", p.ras}, {"ipkeymgr", p.ipkey}, {"toc", p.toc}, {"rl", p.rl}, {"spdm", p.spdm} };
	unsigned present = 0;
	for (auto &s : subs) {
		if (s.s.present()) present++;
		std::printf("  %-9s %s size %7u version 0x%08x\n", s.name, s.s.present() ? "present" : "absent ", s.s.size, s.s.version);
	}
	// The pre-SOS chain needs at least KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV and SOS (psp.hpp step 2-3).
	bool ok = p.kdb.present() && p.spl.present() && p.sys.present() && p.soc.present() && p.intf.present() && p.sos.present();
	std::printf("%u sub-images; chain prerequisites %s\n", present, ok ? "present: PASS" : "MISSING: FAIL");
	return ok ? 0 : 1;
}
