// Host test: the kext's per-IP firmware extractor (amd/amdgpu_ucode_extract.cpp) on real linux-firmware blobs.
// Usage: test_ucode_extract <kind> <file>   kind = sdma | rlc | imu | mes | pfp | me | mec | vcn
// Checks: at least one LOAD_IP_FW payload, every payload non-empty and inside the file. Prints the table.
#include "amdgpu_ucode_extract.h"
#include <cstdio>
#include <cstring>
#include <vector>
using namespace amdgpu;
int main(int argc, char **argv) {
	if (argc != 3) { std::fprintf(stderr, "usage: %s kind file\n", argv[0]); return 2; }
	struct { const char *k; uint64_t id; } kinds[] = {
		{"sdma", kHostFwFile_SDMA}, {"rlc", kHostFwFile_RLC}, {"imu", kHostFwFile_IMU}, {"mes", kHostFwFile_MES_UNI},
		{"pfp", kHostFwFile_CP_PFP}, {"me", kHostFwFile_CP_ME}, {"mec", kHostFwFile_CP_MEC}, {"vcn", kHostFwIPBase + 13u} };
	uint64_t id = 0; for (auto &k : kinds) if (!std::strcmp(k.k, argv[1])) id = k.id;
	if (!id) { std::fprintf(stderr, "unknown kind %s\n", argv[1]); return 2; }
	FILE *f = std::fopen(argv[2], "rb"); if (!f) { std::perror(argv[2]); return 2; }
	std::vector<uint8_t> b; uint8_t buf[65536]; size_t n;
	while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) b.insert(b.end(), buf, buf + n);
	std::fclose(f);
	UcodePayload out[kMaxUcodePayloadsPerFile];
	uint32_t c = amdgpu_ucode_extract(id, b.data(), b.size(), out);
	bool ok = c > 0;
	if (!std::strcmp(argv[1], "vcn")) {
		// Known common-header offsets; preserve the distinct PSP firmware ID.
		if (b.size() < 32 || c != 1 || out[0].fw_type != 13u) ok = false;
		else {
			auto le32 = [&](size_t at) { return (uint32_t)b[at] | ((uint32_t)b[at+1]<<8) | ((uint32_t)b[at+2]<<16) | ((uint32_t)b[at+3]<<24); };
			ok &= out[0].offset_bytes == le32(24) && out[0].size_bytes == le32(20);
		}
	}
	for (uint32_t i = 0; i < c; i++) {
		bool in = out[i].size_bytes > 0 && (uint64_t)out[i].offset_bytes + out[i].size_bytes <= b.size();
		ok &= in;
		std::printf("    fw_type %3u  offset %#8x  size %7u%s\n", out[i].fw_type, out[i].offset_bytes, out[i].size_bytes, in ? "" : "  OUT OF BOUNDS");
	}
	std::printf("  %s: %u payload(s), file %zu B: %s\n", argv[1], c, b.size(), ok ? "PASS" : "FAIL");
	return ok ? 0 : 1;
}
