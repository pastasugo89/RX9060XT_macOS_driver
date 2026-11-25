// Runtime regression for render passes without attachments (bundle 44) and their empty-target case and the RGBA8Uint colour format (bundle 45).
// Basemark's passes name only renderTargetWidth and renderTargetHeight. The probe checks:
//   1. a draw into a sized attachment-less pass (8 x 2) stores into a device buffer and the buffer reads back;
//   2. defaultRasterSampleCount 4 with a rasterSampleCount 4 pipeline draws the same way;
//   3. a visibility result buffer on an attachment-less pass receives a nonzero Boolean result;
//   4. renderTargetArrayLength 2 is accepted;
//   5. an empty target (no attachments, no size) is an encoder whose draws store nothing, and the command buffer completes;
//   6. a refused descriptor (sample count 3) returns nil, and a later pass on the same command buffer completes;
//   7. a colour pipeline with pixel format RGBA8Uint (73) is created, draws, and reads back (1, 2, 3, 4).
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
    "fragment void store(device uint *out [[buffer(0)]]) { out[0] = 0x5EEDu; }\n"
    "fragment uint4 wu() { return uint4(1, 2, 3, 4); }\n";

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
        MTLRenderPipelineDescriptor *ud = [MTLRenderPipelineDescriptor new];
        ud.vertexFunction = [lib newFunctionWithName:@"vs"];
        ud.fragmentFunction = [lib newFunctionWithName:@"wu"];
        ud.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Uint;
        id<MTLRenderPipelineState> psoU = [dev newRenderPipelineStateWithDescriptor:ud error:&error];
        if (!psoU) { NSLog(@"RGBA8Uint pipeline %@", error); return 2; }
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

        // 5. an empty target: the encoder exists, its draw stores nothing, and the command buffer completes
        memset(out.contents, 0, out.length);
        id<MTLCommandBuffer> ecb = [q commandBuffer];
        id<MTLRenderCommandEncoder> eenc = [ecb renderCommandEncoderWithDescriptor:attachmentless(0, 0, 0)];
        report(eenc != nil, "a pass without attachments and with a zero render target is an encoder (an empty target)");
        if (eenc) {
            [eenc setRenderPipelineState:pso1];
            [eenc setFragmentBuffer:out offset:0 atIndex:0];
            [eenc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [eenc endEncoding];
        }
        [ecb commit];
        [ecb waitUntilCompleted];
        report(ecb.status == MTLCommandBufferStatusCompleted && *(uint32_t *)out.contents == 0u, "the empty target's draw stores nothing and its command buffer completes");

        // 6. a refused descriptor: nil, and a later pass on the same command buffer still completes
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLRenderCommandEncoder> refused3 = [cb renderCommandEncoderWithDescriptor:attachmentless(8, 2, 3)];
        report(refused3 == nil, "a pass with three samples is refused with nil");
        id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:attachmentless(8, 2, 0)];
        report(enc != nil, "a valid pass after a refusal on the same command buffer is created");
        memset(out.contents, 0, out.length);
        if (enc) {
            [enc setRenderPipelineState:pso1];
            [enc setFragmentBuffer:out offset:0 atIndex:0];
            [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [enc endEncoding];
        }
        [cb commit];
        [cb waitUntilCompleted];
        report(cb.status == MTLCommandBufferStatusCompleted && *(uint32_t *)out.contents == 0x5EEDu, "the command buffer after the refusal completes and its pass stores");

        // 7. RGBA8Uint colour attachment: the pipeline exists, draws, and reads back (1, 2, 3, 4)
        id<MTLTexture> utex = nil;
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Uint width:8 height:2 mipmapped:NO];
        td.storageMode = MTLStorageModeManaged;
        td.usage = MTLTextureUsageRenderTarget;
        utex = [dev newTextureWithDescriptor:td];
        report(utex != nil, "an RGBA8Uint render target texture is created");
        if (utex) {
            MTLRenderPassDescriptor *up = [MTLRenderPassDescriptor renderPassDescriptor];
            up.colorAttachments[0].texture = utex;
            up.colorAttachments[0].loadAction = MTLLoadActionDontCare;
            up.colorAttachments[0].storeAction = MTLStoreActionStore;
            id<MTLCommandBuffer> ucb = [q commandBuffer];
            id<MTLRenderCommandEncoder> uenc = [ucb renderCommandEncoderWithDescriptor:up];
            if (uenc) {
                [uenc setRenderPipelineState:psoU];
                [uenc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                [uenc endEncoding];
            }
            [ucb commit];
            [ucb waitUntilCompleted];
            uint8_t px[8 * 2 * 4] = { 0 };
            [utex getBytes:px bytesPerRow:8 * 4 fromRegion:MTLRegionMake2D(0, 0, 8, 2) mipmapLevel:0];
            report(ucb.status == MTLCommandBufferStatusCompleted && px[0] == 1 && px[1] == 2 && px[2] == 3 && px[3] == 4 && px[60] == 1,
                   "an RGBA8Uint colour pass draws and reads back (1, 2, 3, 4)");
        }

        printf("test-noattach-runtime: %s (%d failed)\n", failures ? "FAILED" : "passed", failures);
        return failures ? 1 : 0;
    }
}
