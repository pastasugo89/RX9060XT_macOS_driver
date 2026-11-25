// Runtime regression for render passes without attachments (bundle 44). Basemark's passes name only renderTargetWidth and renderTargetHeight.
// The probe checks:
//   1. a draw into an attachment-less pass stores into a device buffer and the buffer reads back (8 x 2 target, one store per fragment);
//   2. defaultRasterSampleCount 4 with a rasterSampleCount 4 pipeline draws the same way;
//   3. a visibility result buffer on an attachment-less pass receives a nonzero Boolean result;
//   4. renderTargetArrayLength 2 is accepted;
//   5. refused descriptors (no size, sample count 3) return nil, the process survives, and a later pass on the same command buffer completes.
// The bundle is loaded only into the probe process. Pass its absolute path as the sole argument.
// Exit: 0 = every check passed, 1 = a check failed, 2 = setup failed (no bundle, no device, no library or pipeline).
// Build (x86_64, the PC's architecture; from this directory):
//   clang -arch x86_64 -fobjc-arc -Wall -Wextra -Werror -framework Foundation -framework Metal -framework IOKit test-noattach-runtime.m -o build/test-noattach-runtime
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <string.h>

@protocol Navi48ProbeDevice <MTLDevice>
- (instancetype)initWithAcceleratorPort:(uint32_t)port;
@end

static NSString *const kSource =
    @"#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "vertex float4 vs(uint v [[vertex_id]]) {\n"
    "    const float2 p[3] = { {-1, -1}, {3, -1}, {-1, 3} };\n"
    "    return float4(p[v], 0, 1);\n"
    "}\n"
    "fragment void store(device uint *out [[buffer(0)]]) { out[0] = 0x5EEDu; }\n";

static int failures;
static void report(BOOL ok, const char *what) {
    printf("%s: %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) failures++;
}

static MTLRenderPassDescriptor *attachmentless(NSUInteger w, NSUInteger h, NSUInteger samples) {
    MTLRenderPassDescriptor *p = [MTLRenderPassDescriptor renderPassDescriptor];
    p.renderTargetWidth = w;
    p.renderTargetHeight = h;
    p.defaultRasterSampleCount = samples;
    return p;
}

// One command buffer, one pass made from `pass`, a full-target triangle with `pso`, and buffer 0 bound as the store target.
// Returns the command buffer's status, or 0 when the encoder was refused (nil).
static NSInteger run_pass(id<MTLCommandQueue> q, MTLRenderPassDescriptor *pass, id<MTLRenderPipelineState> pso, id<MTLBuffer> out, id<MTLBuffer> vis) {
    id<MTLCommandBuffer> cb = [q commandBuffer];
    id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:pass];
    if (!enc) return 0;
    if (vis) [enc setVisibilityResultMode:MTLVisibilityResultModeBoolean offset:0];
    [enc setRenderPipelineState:pso];
    [enc setFragmentBuffer:out offset:0 atIndex:0];
    [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [enc endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    return cb.status;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        NSBundle *bundle = [NSBundle bundleWithPath:@(argv[1])];
        NSError *error = nil;
        if (![bundle loadAndReturnError:&error]) { NSLog(@"bundle %@", error); return 2; }
        io_service_t accel = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("Navi48Accelerator"));
        if (!accel) return 2;
        id<Navi48ProbeDevice> dev = [[bundle.principalClass alloc] initWithAcceleratorPort:accel];
        IOObjectRelease(accel);
        if (!dev) return 2;

        id<MTLLibrary> lib = [dev newLibraryWithSource:kSource options:nil error:&error];
        if (!lib) { NSLog(@"library %@", error); return 2; }
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [lib newFunctionWithName:@"vs"];
        pd.fragmentFunction = [lib newFunctionWithName:@"store"];
        pd.rasterSampleCount = 1;
        id<MTLRenderPipelineState> pso1 = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
        pd.rasterSampleCount = 4;
        id<MTLRenderPipelineState> pso4 = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
        if (!pso1 || !pso4) { NSLog(@"pipeline %@", error); return 2; }
        id<MTLCommandQueue> q = [dev newCommandQueue];
        if (!q) return 2;
        id<MTLBuffer> out = [dev newBufferWithLength:256 options:MTLResourceStorageModeShared];
        id<MTLBuffer> vis = [dev newBufferWithLength:64 options:MTLResourceStorageModeShared];
        if (!out || !vis) return 2;

        // 1. one sample, 8 x 2
        memset(out.contents, 0, out.length);
        NSInteger st = run_pass(q, attachmentless(8, 2, 0), pso1, out, nil);
        report(st == MTLCommandBufferStatusCompleted && *(uint32_t *)out.contents == 0x5EEDu, "attachment-less 8x2 pass stores through the fragment buffer");

        // 2. four samples on both sides
        memset(out.contents, 0, out.length);
        st = run_pass(q, attachmentless(8, 2, 4), pso4, out, nil);
        report(st == MTLCommandBufferStatusCompleted && *(uint32_t *)out.contents == 0x5EEDu, "attachment-less pass with defaultRasterSampleCount 4 and a 4-sample pipeline draws");

        // 3. visibility result on an attachment-less pass
        memset(vis.contents, 0, vis.length);
        MTLRenderPassDescriptor *vp = attachmentless(8, 2, 0);
        vp.visibilityResultBuffer = vis;
        memset(out.contents, 0, out.length);
        st = run_pass(q, vp, pso1, out, vis);
        report(st == MTLCommandBufferStatusCompleted && *(uint64_t *)vis.contents != 0, "visibility result of an attachment-less pass is nonzero after a drawn fragment");

        // 4. renderTargetArrayLength 2 is accepted
        MTLRenderPassDescriptor *lp = attachmentless(8, 2, 0);
        lp.renderTargetArrayLength = 2;
        memset(out.contents, 0, out.length);
        st = run_pass(q, lp, pso1, out, nil);
        report(st == MTLCommandBufferStatusCompleted && *(uint32_t *)out.contents == 0x5EEDu, "attachment-less pass with two layers is accepted and draws");

        // 5. refused descriptors: nil, no abort, and the command buffer that follows still completes
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLRenderCommandEncoder> refused0 = [cb renderCommandEncoderWithDescriptor:attachmentless(0, 0, 0)];
        report(refused0 == nil, "a pass without a render target size is refused with nil");
        id<MTLRenderCommandEncoder> refused3 = [cb renderCommandEncoderWithDescriptor:attachmentless(8, 2, 3)];
        report(refused3 == nil, "a pass with three samples is refused with nil");
        id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:attachmentless(8, 2, 0)];
        report(enc != nil, "a valid pass after two refusals on the same command buffer is created");
        memset(out.contents, 0, out.length);
        if (enc) {
            [enc setRenderPipelineState:pso1];
            [enc setFragmentBuffer:out offset:0 atIndex:0];
            [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [enc endEncoding];
        }
        [cb commit];
        [cb waitUntilCompleted];
        report(cb.status == MTLCommandBufferStatusCompleted && *(uint32_t *)out.contents == 0x5EEDu, "the command buffer after the refusals completes and its pass stores");

        printf("test-noattach-runtime: %s (%d failed)\n", failures ? "FAILED" : "passed", failures);
        return failures ? 1 : 0;
    }
}
