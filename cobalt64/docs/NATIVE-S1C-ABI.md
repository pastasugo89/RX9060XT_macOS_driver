# Native client ABI notes

The current wire definitions are in src/navi48-bringup/src/Navi48NativeABI.h (major1, minor12). This note records the retained Metal-nub portion; it is not a replacement for that header or the selector count/role checks in Navi48NativeClient.cpp.

## ABI 1.8 addendum

The native user-client type is N48N. After Hello, the administrator route can publish or withdraw the software Metal nub:

| Selector | Scalar input | Scalar output |
|---|---|---|
| N48N_SEL_METAL_NUB_PUBLISH (19) | flags=0 | state=1, registry entry ID, Metal ops ABI, sizeof(Navi48MetalOps) |
| N48N_SEL_METAL_NUB_WITHDRAW (20) | flags=0 | previous state |

Publish requires navi48-metal=1, a positive native S1b result, a usable non-HUNG GPU and no existing/terminating nub. It does not run automatically at kext start. The boot orchestrator explicitly requests it. Publishing registers Navi48MetalNub, whose provider is Navi48Bringup; the auxiliary accelerator matches that nub and receives the versioned software ops table through callPlatformFunction. Nub registration runs outside its state lock because matching calls back into those ops.

Withdraw is cleanup: it requires Hello and valid zero flags, but does not require the publish boot argument or another positive S1b result. It terminates the nub and its auxiliary accelerator; an absent nub returns NotFound. Final release returns the state from Terminating to Off. Native APP clients and clients opened through the accelerator route cannot invoke either selector, even if they know the numbers.

The ops ABI and size are separate from the native-client ABI. Callers must inspect the values returned by publish; display-enabled and display-disabled ops shapes differ. Do not infer that the GPU/display is ready from kext presence or from nub publication alone. The guarded desktop path separately verifies Navi48,Ready and accelerator attachment before display adoption.
