// Controlled native-ABI exercise through the real IOAccelerator provider.
// --self-test never opens IOKit; --run requires a dynamic-VMID kernel, build 666 or later.
// This checks command/data address-space isolation, not shaders or Metal.
#include <IOKit/IOKitLib.h>
#include <unistd.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "Navi48NativeABI.h"
#include "amd/amdgpu_pm4.h"

namespace {
constexpr uint32_t kMinBuild = 666, kMaxClients = 32, kWords = 64;
constexpr uint64_t kVa = 0x40000000ull, kBytes = 16384, kResultOffset = 4096;
constexpr uint32_t kGuard = 0xcdcdcdcdu, kFirst = 16, kPayload = 16, kIbWords = 32;

bool call_ok(kern_return_t result, const char *operation) {
    if (result == KERN_SUCCESS) return true;
    std::fprintf(stderr, "%s failed: 0x%x\n", operation, static_cast<unsigned>(result));
    return false;
}

uint32_t seed_for(uint32_t client, uint32_t round) {
    return 0x90000000u ^ ((client + 1u) << 16) ^ ((round + 1u) << 5);
}

void packet(uint32_t *words, uint32_t seed) {
    const uint64_t address = kVa + kResultOffset + kFirst * sizeof(uint32_t);
    words[0] = amdgpu::pm4_header(amdgpu::kPM4OpWriteData, 2u + kPayload);
    words[1] = amdgpu::pm4_write_data_control(
        amdgpu::kPM4WriteDataEngineME, amdgpu::kPM4WriteDataDstSelMemory, true);
    words[2] = static_cast<uint32_t>(address);
    words[3] = static_cast<uint32_t>(address >> 32);
    for (uint32_t i = 0; i < kPayload; ++i) words[4 + i] = seed ^ i;
    for (uint32_t i = 4 + kPayload; i < kIbWords; ++i) words[i] = amdgpu::pm4_nop();
}

bool verify(const volatile uint32_t *words, uint32_t seed) {
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    for (uint32_t i = 0; i < kWords; ++i) {
        const uint32_t expected = i >= kFirst && i < kFirst + kPayload ? seed ^ (i - kFirst) : kGuard;
        const uint32_t actual = words[i];
        if (actual != expected) {
            std::fprintf(stderr, "data/guard mismatch at word %u: 0x%x, expected 0x%x\n", i, actual, expected);
            return false;
        }
    }
    return true;
}

struct Client {
    io_connect_t connection = IO_OBJECT_NULL;
    mach_vm_address_t cpu = 0;
    mach_vm_size_t mapped = 0;
    uint32_t handle = 0, context = 0, expected = 0;
    uint64_t sequence = 0;

    Client() = default;
    Client(const Client &) = delete;
    Client &operator=(const Client &) = delete;
    ~Client() { (void)close(); }

    bool close() {
        bool ok = true;
        if (connection != IO_OBJECT_NULL) {
            if (cpu != 0) {
                ok = call_ok(IOConnectUnmapMemory64(connection, handle, mach_task_self(), cpu), "CPU unmap");
                cpu = 0;
            }
            // Close exercises the kernel retirement, park and fence-unmap path.
            ok = call_ok(IOServiceClose(connection), "IOServiceClose") && ok;
            connection = IO_OBJECT_NULL;
        }
        mapped = 0; handle = 0; context = 0; sequence = 0;
        return ok;
    }

    bool open(io_service_t service, bool allocateBuffers = true) {
        if (!call_ok(IOServiceOpen(service, mach_task_self(), N48N_UC_TYPE, &connection), "IOAccelerator native open")) return false;
        const uint64_t hello[] = {N48N_ABI_VERSION, N48N_HELLO_F_MINOR};
        uint64_t output[4] = {}; uint32_t count = 4;
        if (!call_ok(IOConnectCallScalarMethod(connection, N48N_SEL_HELLO, hello, 2, output, &count), "Hello")) return false;
        if (count != 4 || (output[0] & 0xffffu) != N48N_ABI_VERSION ||
            output[1] < kMinBuild || output[3] != N48N_VMID_DYNAMIC) {
            std::fprintf(stderr, "Refused: requires kernel build 666 or later with dynamic VMIDs; no test work submitted.\n");
            return false;
        }
        n48n_info info{}; size_t size = sizeof(info);
        if (!call_ok(IOConnectCallStructMethod(connection, N48N_SEL_QUERYINFO, nullptr, 0, &info, &size), "QueryInfo")) return false;
        if (size != sizeof(info) || info.kext_build < kMinBuild ||
            info.abi_version != N48N_ABI_VERSION || !(info.flags & N48N_INFO_DYNAMIC_VMID) ||
            (info.flags & N48N_INFO_HUNG) || info.vmid != N48N_VMID_DYNAMIC) {
            std::fprintf(stderr, "Refused: kernel capabilities/state do not match the candidate.\n");
            return false;
        }
        if (!allocateBuffers) return true;
        const n48n_gem_create_in create{kBytes, 4096, N48N_GEM_DOMAIN_GTT, 0};
        count = 4;
        if (!call_ok(IOConnectCallMethod(connection, N48N_SEL_BOCREATE, nullptr, 0,
                     &create, sizeof(create), output, &count, nullptr, nullptr), "GTT BO create")) return false;
        if (count != 4 || output[0] == 0 || output[0] > UINT32_MAX || output[1] < kBytes || output[2] != N48N_GEM_DOMAIN_GTT) return false;
        handle = static_cast<uint32_t>(output[0]);
        if (!call_ok(IOConnectMapMemory64(connection, handle, mach_task_self(), &cpu, &mapped, kIOMapAnywhere), "CPU map")) return false;
        if (mapped < kBytes) return false;
        std::memset(reinterpret_cast<void *>(cpu), 0, kBytes);
        auto *result = reinterpret_cast<uint32_t *>(cpu + kResultOffset);
        for (uint32_t i = 0; i < kWords; ++i) result[i] = kGuard;
        n48n_gem_va map{};
        map.handle = handle; map.operation = N48N_VA_OP_MAP;
        map.flags = N48N_VM_PAGE_READABLE | N48N_VM_PAGE_WRITEABLE | N48N_VM_PAGE_EXECUTABLE;
        map.va_address = kVa; map.map_size = kBytes;
        if (!call_ok(IOConnectCallStructMethod(connection, N48N_SEL_GEMVA, &map, sizeof(map), nullptr, nullptr), "GPU VA map")) return false;
        const n48n_ctx allocate{N48N_CTX_OP_ALLOC, 0, 0, 0}; n48n_ctx allocated{};
        size = sizeof(allocated);
        if (!call_ok(IOConnectCallStructMethod(connection, N48N_SEL_CTX, &allocate, sizeof(allocate), &allocated, &size), "Context allocate")) return false;
        if (size != sizeof(allocated) || allocated.op == 0) return false;
        context = allocated.op;
        return true;
    }

    bool submit(uint32_t client, uint32_t round) {
        expected = seed_for(client, round);
        packet(reinterpret_cast<uint32_t *>(cpu), expected);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        struct { n48n_cs_in header; n48n_cs_ib ib; } request{};
        static_assert(sizeof(request) == 64, "one native IB request");
        request.header.abi = N48N_ABI_VERSION;
        request.header.ctx_id = context; request.header.num_ibs = 1;
        request.ib.va_start = kVa; request.ib.ib_bytes = kIbWords * sizeof(uint32_t);
        request.ib.ip_type = N48N_HW_IP_GFX;
        uint32_t count = 1;
        if (!call_ok(IOConnectCallMethod(connection, N48N_SEL_SUBMIT, nullptr, 0,
                     &request, sizeof(request), &sequence, &count, nullptr, nullptr), "Submit")) return false;
        return count == 1 && sequence != 0;
    }

    bool wait() const {
        const uint64_t input[] = {sequence, N48N_WAIT_CAP_NS, context};
        uint64_t output[3] = {}; uint32_t count = 3;
        if (!call_ok(IOConnectCallScalarMethod(connection, N48N_SEL_WAITSEQ, input, 3, output, &count), "WaitSeq")) return false;
        return count == 3 && output[0] == 0 && output[1] >= sequence;
    }

    bool check() const { return verify(reinterpret_cast<volatile uint32_t *>(cpu + kResultOffset), expected); }
};

bool self_test() {
    uint32_t code[kIbWords + 2]; code[0] = 0x1234; code[kIbWords + 1] = 0x5678;
    packet(code + 1, seed_for(31, 1023));
    if (code[0] != 0x1234 || code[kIbWords + 1] != 0x5678 || code[1] != 0xc0123700u ||
        code[2] != 0x00100500u || code[3] != kVa + kResultOffset + kFirst * 4u || code[4] != 0) return false;
    for (uint32_t i = 0; i < kPayload; ++i) if (code[5 + i] != (seed_for(31, 1023) ^ i)) return false;
    for (uint32_t i = 4 + kPayload; i < kIbWords; ++i) if (code[1 + i] != amdgpu::pm4_nop()) return false;
    uint32_t data[kWords];
    for (uint32_t i = 0; i < kWords; ++i) data[i] = i >= kFirst && i < kFirst + kPayload ? 1234u ^ (i - kFirst) : kGuard;
    if (!verify(data, 1234)) return false;
    // Every client/round pair has a different signature over the supported range.
    for (uint32_t c = 0; c < kMaxClients; ++c)
        for (uint32_t r = 0; r < 1024; ++r)
            if (seed_for(c, r) == seed_for(c + 1, r) || seed_for(c, r) == seed_for(c, r + 1)) return false;
    std::puts("PASS: command encoding, bounds, guard expectations and distinct signatures; no IOKit calls or GPU work.");
    return true;
}
} // namespace

int main(int argc, char **argv) {
    if (argc == 2 && std::strcmp(argv[1], "--self-test") == 0) return self_test() ? 0 : 1;
    const bool profileOnly = argc == 2 && std::strcmp(argv[1], "--check-profile") == 0;
    if (!profileOnly && (argc != 2 || std::strcmp(argv[1], "--run") != 0)) {
        std::puts("Usage: context-isolation-probe --self-test | --check-profile | --run\n"
                  "--check-profile: open/Hello/QueryInfo/close one native client; no BOs or submissions.\n"
                  "--run: kernel build 666 or later only, root, 16 concurrent IOAccelerator connections, 32 rounds;\n"
                  "same GPU VA/different BOs and patterns, guard checks, explicit fence waits and close/reopen.\n"
                  "One process, admin role, sequential submissions. Does not qualify shaders, Metal,\n"
                  "application admission, simultaneous CPU submits, video or rendering performance.\n"
                  "No IOKit calls made without --run or --check-profile.");
        return argc == 1 ? 0 : 2;
    }
    if (geteuid() != 0) { std::fputs("Requires root for this admin-role probe.\n", stderr); return 2; }
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("Navi48Accelerator"));
    if (service == IO_OBJECT_NULL) { std::fputs("IOAccelerator provider missing.\n", stderr); return 1; }
    if (profileOnly) {
        Client client;
        bool ok = client.open(service, false);
        ok = client.close() && ok;
        IOObjectRelease(service);
        std::printf("{\"status\":\"%s\",\"min_kernel_build\":666,\"dynamic_vmids\":%s,\"gpu_submissions\":0}\n",
                    ok ? "pass" : "fail", ok ? "true" : "false");
        return ok ? 0 : 1;
    }
    constexpr uint32_t clients = 16, rounds = 32;
    Client connections[clients];
    bool ok = true; uint32_t completed = 0, reopened = 0, opened = 0;
    for (auto &c : connections) {
        if (!(ok = c.open(service))) break;
        ++opened;
    }
    for (uint32_t round = 0; ok && round < rounds; ++round) {
        // Interleave reverse and forward traversal to change the eviction order.
        for (uint32_t n = 0; n < clients && ok; ++n) {
            const uint32_t index = round & 1 ? clients - 1 - n : n;
            ok = connections[index].submit(index, round) && connections[index].wait();
            if (ok) ++completed;
        }
        // Check all owners after all writes: a later wrong-root write must be caught.
        for (const auto &c : connections) if (ok) ok = c.check();
        if (ok && round + 1 < rounds && round % 4 == 3) {
            const uint32_t index = (round / 4) % clients;
            ok = connections[index].close() && connections[index].open(service);
            if (ok) ++reopened;
        }
    }
    for (auto &c : connections) if (!c.close()) ok = false;
    IOObjectRelease(service);
    std::printf("{\"status\":\"%s\",\"required_kernel_build\":666,\"requested_connections\":16,"
                "\"initial_connections_opened\":%u,"
                "\"submits_completed\":%u,\"close_reopen_cycles\":%u,"
                "\"scope\":\"native command/data isolation; one process, admin role; no shader/Metal qualification\"}\n",
                ok ? "pass" : "fail", opened, completed, reopened);
    return ok ? 0 : 1;
}
