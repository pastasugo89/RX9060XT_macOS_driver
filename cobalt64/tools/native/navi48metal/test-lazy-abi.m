// GPU-free regression test against a compiled Navi48Device bundle on macOS.
// Loads only into this process: no device init, IOServiceOpen or driver install.
// The Apple superclass IMP is replaced temporarily to exercise both results.
// Usage: test-lazy-abi <bundle executable> <expected N48_LAZY: 0|1>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static BOOL baseResult;
static unsigned baseCalls;
static BOOL fakeLazy(id self, SEL cmd) {
    (void)self; (void)cmd;
    baseCalls++;
    return baseResult;
}

int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 3 || (strcmp(argv[2], "0") && strcmp(argv[2], "1"))) return 2;
    // Reference Metal explicitly so its Objective-C classes are registered.
    (void)MTLCopyAllDevices; // Do not call: GPU enumeration is unnecessary.
    void *image = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!image) { fprintf(stderr, "FAIL dlopen: %s\n", dlerror()); return 1; }
    Class cls = NSClassFromString(@"Navi48Device");
    Class base = cls ? class_getSuperclass(cls) : Nil;
    SEL lazy = sel_registerName("lazyInitialize");
    Method own = cls ? class_getInstanceMethod(cls, lazy) : NULL;
    Method parent = base ? class_getInstanceMethod(base, lazy) : NULL;
    if (!own || !parent || method_getImplementation(own) == method_getImplementation(parent)) {
        fprintf(stderr, "FAIL: device override or Apple superclass method missing\n"); return 1;
    }
    char *a = method_copyReturnType(own), *b = method_copyReturnType(parent);
    printf("lazyInitialize return: device=%s Apple=%s BOOL=%s\n", a, b, @encode(BOOL));
    BOOL typesOK = !strcmp(a, b) && !strcmp(a, @encode(BOOL)) &&
                   method_getNumberOfArguments(own) == 2 && method_getNumberOfArguments(parent) == 2;
    free(a); free(b);
    if (!typesOK) { fprintf(stderr, "FAIL: lazyInitialize ABI mismatch\n"); return 1; }

    // Deliberately never init or dealloc: retain an extra reference until
    // process exit, since the real base dealloc needs initialised GPU state.
    id object = class_createInstance(cls, 0);
    if (!object) return 1;
    void *heldUntilExit = (__bridge_retained void *)object;
    (void)heldUntilExit;
    IMP original = method_setImplementation(parent, (IMP)fakeLazy);
    BOOL (*call)(id, SEL) = (BOOL (*)(id, SEL))method_getImplementation(own);
    BOOL ok = YES;
    for (unsigned i = 0; i < 2; i++) {
        baseResult = i ? YES : NO;
        baseCalls = 0;
        BOOL result = call(object, lazy);
        printf("super=%d override=%d calls=%u\n", baseResult, result, baseCalls);
        if (result != baseResult || baseCalls != 1) ok = NO;
    }
    method_setImplementation(parent, original);
    SEL support = sel_registerName("supportLazyInitialization");
    Method sm = class_getInstanceMethod(cls, support);
    BOOL supported = sm ? ((BOOL (*)(id, SEL))method_getImplementation(sm))(object, support) : NO;
    if (!sm || supported != (atoi(argv[2]) ? YES : NO)) ok = NO;
    printf("%s: result propagation and N48_LAZY=%s (no GPU init)\n", ok ? "PASS" : "FAIL", argv[2]);
    return ok ? 0 : 1;
} }
