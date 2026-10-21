/*
 * n48nub - publish, withdraw and inspect the software nub Navi48MetalNub (kext Navi48Bringup, ABI 1.8; the nub
 * is what the aux accelerator kext Navi48Accel matches).
 *
 * RECONSTRUCTION, NOT THE ORIGINAL. The tool of Cobalt64 (tools/native/n48nub.c) is not in the published Cobalt64
 * snapshot, so this file was rebuilt by us from the contract the rest of the tree fixes: Navi48NativeABI.h (the
 * Hello selector and its flags, selectors 19 and 20, the ABI version), Navi48MetalNub.cpp and Navi48MetalOps.h (what
 * the two selectors return and which properties the nub carries), the native client's selector switch in src/ (the
 * argument shapes), the
 * expectations of tests/native_metal_test.cpp and tests/native_metal_plant.sh, and the output the scripts parse
 * (autoarm/n48-autoarm.sh, arm-gpu-desktop.sh, tools/vm/deploy-metal-stack.sh, navi48accel/verify.sh). Where those
 * sources do not fix a detail (the wording after the first line, the exit codes of status), the choice is ours.
 *
 * Usage (as root, the kext refuses others):  n48nub publish | withdraw | status
 *   publish   Hello, then selector 19 N48N_SEL_METAL_NUB_PUBLISH: the kext registers Navi48MetalNub.
 *   withdraw  Hello, then selector 20 N48N_SEL_METAL_NUB_WITHDRAW: the nub (and the accelerator under it) is terminated.
 *   status    no kernel call: looks the nub up in the IORegistry and prints its registry ID and Navi48,* properties.
 * Exit codes: 0 done (status: nub present); 1 refused / failed (status: nub absent); 2 usage.
 *
 * License: MIT, as the project (cobalt64/LICENSE).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <mach/mach.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOReturn.h>
#include <CoreFoundation/CoreFoundation.h>
#include "../../src/navi48-bringup/src/Navi48UserClientABI.h" /* NAVI48_UC_SERVICE_NAME */
#include "../../src/navi48-bringup/src/Navi48NativeABI.h"     /* N48N_UC_TYPE, N48N_SEL_HELLO, N48N_SEL_METAL_NUB_*, N48N_ABI_* */

#define N48NUB_NAME      "Navi48MetalNub"
#define N48NUB_MIN_MINOR 8u   /* selectors 19 / 20 exist since ABI 1.8 (kext 0.0.610); an older kernel is refused before any call */

/* IOReturn text for the codes the nub and the native client can return; anything else prints "unknown". */
static const char *ret_name(kern_return_t kr)
{
    switch ((uint32_t)kr) {
    case KERN_SUCCESS:            return "Success";
    case kIOReturnError:          return "Error";
    case kIOReturnNoMemory:       return "NoMemory";
    case kIOReturnNotPrivileged:  return "NotPrivileged";
    case kIOReturnBadArgument:    return "BadArgument";
    case kIOReturnNotReady:       return "NotReady";
    case kIOReturnNotFound:       return "NotFound";
    case kIOReturnUnsupported:    return "Unsupported";
    case kIOReturnExclusiveAccess:return "ExclusiveAccess";
    case kIOReturnBusy:           return "Busy";
    case kIOReturnNotPermitted:   return "NotPermitted";
    default:                      return "unknown";
    }
}

/* The code as the scripts expect it: "0" for success, hex otherwise. */
static const char *rc_text(kern_return_t kr, char *buf, size_t n)
{
    if (kr == KERN_SUCCESS) snprintf(buf, n, "0");
    else snprintf(buf, n, "0x%x", (unsigned)kr);
    return buf;
}

static void print_verdict(const char *verb, kern_return_t kr)
{
    char b[16];
    printf("%s: %s (%s)\n", verb, rc_text(kr, b, sizeof b), ret_name(kr));
}

static const char *state_name(uint64_t s)
{
    switch (s) {
    case 0: return "off";
    case 1: return "published";
    case 2: return "terminating";
    default: return "unknown";
    }
}

/* Opens the native client (type 'N48N') of the Navi48Bringup service. */
static int n48n_open(io_connect_t *c)
{
    io_service_t svc = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching(NAVI48_UC_SERVICE_NAME));
    if (!svc) {
        fprintf(stderr, "n48nub: service %s not found (is the bring-up kext loaded?)\n", NAVI48_UC_SERVICE_NAME);
        return 1;
    }
    kern_return_t kr = IOServiceOpen(svc, mach_task_self(), N48N_UC_TYPE, c);
    IOObjectRelease(svc);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "n48nub: IOServiceOpen(N48N) failed: 0x%x (%s)\n", (unsigned)kr, ret_name(kr));
        return 1;
    }
    return 0;
}

/* Selector 0 with the minor flag: out[0] = ABI | MINOR << 16, out[1] = kext build, out[2] = max IBs, out[3] = vmid. */
static kern_return_t n48n_hello(io_connect_t c, uint32_t *kabi, uint32_t *kminor, uint64_t *kbuild)
{
    const uint64_t in[2] = { N48N_ABI_VERSION, N48N_HELLO_F_MINOR };
    uint64_t out[4] = { 0, 0, 0, 0 };
    uint32_t n = 4;
    kern_return_t kr = IOConnectCallScalarMethod(c, N48N_SEL_HELLO, in, 2, out, &n);
    if (kr != KERN_SUCCESS) return kr;
    *kabi = (uint32_t)(out[0] & 0xffffu);
    *kminor = (uint32_t)((out[0] >> 16) & 0xffffu);
    *kbuild = out[1];
    return KERN_SUCCESS;
}

/* Hello on an open client; 0 = done, 1 = refused (the message says why). */
static int hello(io_connect_t *c)
{
    uint32_t kabi = 0, kminor = 0;
    uint64_t kbuild = 0;
    kern_return_t kr = n48n_hello(*c, &kabi, &kminor, &kbuild);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "n48nub: Hello failed: 0x%x (%s)\n", (unsigned)kr, ret_name(kr));
        return 1;
    }
    if (kabi != N48N_ABI_VERSION || kminor < N48NUB_MIN_MINOR) {
        fprintf(stderr, "n48nub: the kernel speaks ABI %u.%u, which has no Metal nub selectors (needs ABI %u.%u or later)\n",
                kabi, kminor, N48N_ABI_VERSION, N48NUB_MIN_MINOR);
        return 1;
    }
    printf("  Hello: kernel ABI %u.%u (tool %u.%u), kext build %llu\n", kabi, kminor,
           N48N_ABI_VERSION, N48N_ABI_MINOR, (unsigned long long)kbuild);
    return 0;
}

static int cmd_publish(void)
{
        io_connect_t c = 0;
        if (n48n_open(&c)) return 1;
        if (hello(&c)) return 1;
        const uint64_t in[1] = { 0 }; uint64_t o[4] = { 0, 0, 0, 0 };
        uint32_t n = 4;
        kern_return_t kr = IOConnectCallScalarMethod(c, N48N_SEL_METAL_NUB_PUBLISH, in, 1, o, &n);
        IOServiceClose(c);
        print_verdict("publish", kr);
        if (kr != KERN_SUCCESS) return 1;
        printf("  state %llu (%s): nub registry entry 0x%llx, ops table ABI %llu, %llu bytes\n",
               (unsigned long long)o[0], state_name(o[0]), (unsigned long long)o[1],
               (unsigned long long)o[2], (unsigned long long)o[3]);
        return 0;
}

static int cmd_withdraw(void)
{
        io_connect_t c = 0;
        if (n48n_open(&c)) return 1;
        if (hello(&c)) return 1;
        const uint64_t in[1] = { 0 }; uint64_t o[1] = { 0 };
        uint32_t n = 1;
        kern_return_t kr = IOConnectCallScalarMethod(c, N48N_SEL_METAL_NUB_WITHDRAW, in, 1, o, &n);
        IOServiceClose(c);
        print_verdict("withdraw", kr);
        if (kr != KERN_SUCCESS) return 1;
        printf("  previous state %llu (%s)\n", (unsigned long long)o[0], state_name(o[0]));
        return 0;
}

/* One Navi48,* property of the nub as a number; prints "absent" when the key is missing or not a number. */
static void show_prop(io_registry_entry_t e, const char *key)
{
    CFStringRef k = CFStringCreateWithCString(kCFAllocatorDefault, key, kCFStringEncodingUTF8);
    CFTypeRef v = k ? IORegistryEntryCreateCFProperty(e, k, kCFAllocatorDefault, 0) : NULL;
    if (k) CFRelease(k);
    if (v && CFGetTypeID(v) == CFNumberGetTypeID()) {
        long long x = 0;
        CFNumberGetValue((CFNumberRef)v, kCFNumberSInt64Type, &x);
        printf("  %s = %lld\n", key, x);
    } else {
        printf("  %s = absent\n", key);
    }
    if (v) CFRelease(v);
}

static int cmd_status(void)
{
    io_service_t svc = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching(N48NUB_NAME));
    if (!svc) {
        printf("NO %s in the registry\n", N48NUB_NAME);
        return 1;
    }
    uint64_t id = 0;
    IORegistryEntryGetRegistryEntryID(svc, &id);
    printf("%s present, registry ID 0x%llx\n", N48NUB_NAME, (unsigned long long)id);
    show_prop(svc, "Navi48,Ready");
    show_prop(svc, "Navi48,MetalABI");
    show_prop(svc, "Navi48,TaskVASize");
    show_prop(svc, "Navi48,VRAMBytes");
    IOObjectRelease(svc);
    return 0;
}

static void usage(FILE *f)
{
    fprintf(f, "usage: n48nub publish | withdraw | status   (publish and withdraw need root)\n");
}

int main(int argc, char **argv)
{
    if (argc != 2) { usage(stderr); return 2; }
    if (strcmp(argv[1], "publish") == 0) return cmd_publish();
    if (strcmp(argv[1], "withdraw") == 0) return cmd_withdraw();
    if (strcmp(argv[1], "status") == 0) return cmd_status();
    usage(stderr);
    return 2;
}
