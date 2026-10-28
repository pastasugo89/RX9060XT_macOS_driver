#include "cppc.hpp"
#include <stdio.h>
#include <vector>
#include <assert.h>
using namespace n44cppc;
static unsigned checks;
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
struct IO {
    bool supported = true, online = true, corruptVerify = false, dropRequestOnce = false;
    unsigned calls = 0, failAt = 0;
    uint64_t en = 0x20, req = 0xaabbccdd12345678ull, cap = 0xc88c3c14;
    std::vector<uint32_t> writes;
    bool profile() { return supported; }
    bool read(uint32_t r, uint64_t &v) {
        if (++calls == failAt) return false;
        v = r == kEnable ? en : r == kRequest ? req : cap;
        if (r == kRequest && corruptVerify && writes.size() >= 2) v ^= 1;
        return true;
    }
    bool write(uint32_t r, uint64_t v) {
        writes.push_back(r);
        if (++calls == failAt) return false;
        if (r == kRequest && dropRequestOnce) { dropRequestOnce = false; return true; }
        if (r == kEnable) en = v; else if (r == kRequest) req = v; else assert(false);
        return true;
    }
};
struct Batch {
    Core cores[kCpus]; IO io[kCpus];
    bool run(Phase phase) {
        for (unsigned i = 0; i < kCpus; i++) {
            cores[i].seen = false;
            if (io[i].online) step(cores[i], phase, io[i]);
        }
        return complete(cores);
    }
};
int main() {
    const char brand[] = "AMD Ryzen 7 7700 8-Core Processor";
    CHECK(profile(true, 0x19, 0x61, 2, 1u << 27, false, brand));
    CHECK(!profile(true, 0x19, 0x61, 2, 0, false, brand));
    CHECK(!profile(true, 0x19, 0x61, 2, 1u << 27, true, brand));
    CHECK(!profile(false, 0x19, 0x61, 2, 1u << 27, false, brand));
    CHECK(!profile(true, 0x19, 0x61, 2, 1u << 27, false, "AMD Ryzen 7 7700X 8-Core Processor"));
    CHECK(!profile(true, 0x19, 0x61, 1, 1u << 27, false, brand));
    CHECK(!profile(true, 0x1a, 0x61, 2, 1u << 27, false, brand));
    CHECK(!profile(true, 0x19, 0x21, 2, 1u << 27, false, brand));
    const Caps c = decode(0xc88c3c14);
    CHECK(c.lowest == 20 && c.efficient == 60 && c.nominal == 140 && c.highest == 200);
    uint64_t target = 0;
    CHECK(request(0xaabbccdd12345678ull, 0xc88c3c14, 128, target) && target == 0xaabbccdd800014c8ull);
    CHECK(!request(0, 0, 128, target));
    CHECK(!request(0, 0x148c3cc8, 128, target)); // reversed CAP1 is invalid
    CHECK(!request(0, 0xc88c3c14, 256, target));
    for (unsigned epp = 0; epp < 256; epp++) {
        CHECK(request(0xffff123400000000ull, 0xc88c3c14, epp, target));
        CHECK((target >> 32) == 0xffff1234 && ((target >> 24) & 255) == epp);
        CHECK(((target >> 16) & 255) == 0 && ((target >> 8) & 255) == 20 && (target & 255) == 200);
    }
    { Batch b; const auto o = activate(b); CHECK(o.active);
      for (unsigned i = 0; i < kCpus; i++) {
          CHECK(b.io[i].en == 0x21 && b.io[i].req == 0xaabbccdd800014c8ull);
          CHECK(b.io[i].writes.size() == 2 && b.io[i].writes[0] == kEnable && b.io[i].writes[1] == kRequest);
      }
      CHECK(b.run(Phase::Restore));
      for (auto &io : b.io) CHECK(io.en == 0x20 && io.req == 0xaabbccdd12345678ull);
    }
    // Every single read/write failure on every CPU: successful partial writes must roll back.
    for (unsigned cpu = 0; cpu < kCpus; cpu++) for (unsigned fail = 1; fail <= 8; fail++) {
        Batch b; b.io[cpu].failAt = fail; const auto o = activate(b);
        CHECK(!o.active && o.restored);
        for (const auto &io : b.io) CHECK(io.en == 0x20 && io.req == 0xaabbccdd12345678ull);
    }
    { Batch b; b.io[7].online = false; CHECK(!activate(b).active);
      for (const auto &io : b.io) CHECK(io.writes.empty()); }
    { Batch b; b.io[9].supported = false; CHECK(!activate(b).active);
      for (const auto &io : b.io) CHECK(io.writes.empty()); }
    { Batch b; b.io[2].cap = 0; const auto o = activate(b); CHECK(!o.active && o.restored && o.failed == Phase::Plan);
      for (const auto &io : b.io) CHECK(io.en == 0x20 && io.req == 0xaabbccdd12345678ull); }
    { Batch b; for (auto &io : b.io) io.en = 1; CHECK(activate(b).active);
      for (const auto &io : b.io) CHECK(io.writes.size() == 1 && io.writes[0] == kRequest); }
    { Batch b; CHECK(b.run(Phase::Observe)); for (const auto &io : b.io) CHECK(io.writes.empty()); }
    { Batch b; b.io[3].dropRequestOnce = true; const auto o = activate(b);
      CHECK(!o.active && o.restored && o.failed == Phase::Verify);
      for (const auto &io : b.io) CHECK(io.en == 0x20 && io.req == 0xaabbccdd12345678ull); }
    { Batch b; b.io[3].corruptVerify = true; const auto o = activate(b);
      CHECK(!o.active && !o.restored && o.failed == Phase::Verify); }
    { Batch b; CHECK(activate(b).active); b.io[5].failAt = b.io[5].calls + 1;
      CHECK(!b.run(Phase::Restore)); CHECK(b.cores[5].saved);
      CHECK(b.run(Phase::Restore)); CHECK(!b.cores[5].saved); }
    printf("CPPC transaction: %u checks PASS\n", checks);
}
