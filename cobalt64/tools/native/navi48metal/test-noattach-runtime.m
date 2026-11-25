// Runtime regression for render passes without attachments (bundle 44), the empty target and the RGBA8Uint colour format (bundle 45), and
// depth/stencil 2D-array and cube textures (bundle 46). Basemark's passes name only renderTargetWidth and renderTargetHeight. The probe checks:
//   1. a draw into a sized attachment-less pass (8 x 2) stores into a device buffer and the buffer reads back;
//   2. defaultRasterSampleCount 4 with a rasterSampleCount 4 pipeline draws the same way;
//   3. a visibility result buffer on an attachment-less pass receives a nonzero Boolean result;
//   4. renderTargetArrayLength 2 is accepted;
//   5. an empty target (no attachments, no size) is an encoder whose draws store nothing, and the command buffer completes;
//   6. a refused descriptor (sample count 3) returns nil, and a later pass on the same command buffer completes;
//   7. a colour pipeline with pixel format RGBA8Uint (73) is created, draws, and reads back (1, 2, 3, 4).
//   8. a Depth32Float 2D array texture (4 layers) is created; each layer is cleared to 1.0 by its own pass;
//   9. a depth-only pass renders depth 0.25 into layer 2 only (a per-layer depth attachment);
//  10. a compare sampler (Greater, reference 0.5) on the array gives 1.0 for layer 2 and 0.0 for the cleared layer 0;
//  11. a plain sample of layer 2 reads 0.25, and of layer 3 (cleared, not drawn) reads 1.0;
//  12. a Depth32Float cube (4 x 4) is created; face 3 is drawn at 0.25 and all faces are cleared to 1.0 first;
//  13. a plain depth-cube sample reads 0.25 in face 3 and 1.0 in face 0;
//  14. a fresh depth array layer that was never drawn or cleared reads 0.0 (driver zero-initialisation).
// Checks 8 to 14 do not need the rest of the bundle's new code to be right: each failure is reported on its own line.
// The bundle is loaded only into the probe process. Pass its absolute path as the sole argument.
// Exit: 0 = every check passed, 1 = a check failed, 2 = setup failed (no bundle, no device, no library or pipeline).
// Build (x86_64, the PC's architecture; from this directory):
//   clang -arch x86_64 -fobjc-arc -Wall -Wextra -Werror -framework Foundation -framework Metal -framework IOKit test-noattach-runtime.m -o build/test-noattach-runtime
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <Metal/Metal.h>
#include <math.h>
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
    "vertex float4 vz(uint v [[vertex_id]]) {\n"
    "    const float2 p[3] = { {-1, -1}, {3, -1}, {-1, 3} };\n"
    "    return float4(p[v], 0.25, 1);\n"
    "}\n"
    "fragment void store(device uint *out [[buffer(0)]]) { out[0] = 0x5EEDu; }\n"
    "fragment uint4 wu() { return uint4(1, 2, 3, 4); }\n"
    "fragment void sample_cmp(depth2d_array<float> dt [[texture(0)]], sampler s [[sampler(0)]],\n"
    "                         constant uint &layer [[buffer(0)]], device float *out [[buffer(1)]]) {\n"
    "    out[0] = dt.sample_compare(s, float2(0.5, 0.5), layer, 0.5);\n"
    "}\n"
    "fragment void sample_plain(depth2d_array<float> dt [[texture(0)]], sampler s [[sampler(0)]],\n"
    "                           constant uint &layer [[buffer(0)]], device float *out [[buffer(1)]]) {\n"
    "    out[0] = dt.sample(s, float2(0.5, 0.5), layer);\n"
    "}\n"
    "fragment void sample_cube(depthcube<float> c [[texture(0)]], sampler s [[sampler(0)]],\n"
    "                          constant float4 &dir [[buffer(0)]], device float *out [[buffer(1)]]) {\n"
    "    out[0] = c.sample(s, dir.xyz);\n"
    "}\n";

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

// One pass whose only attachment is a depth slice (`slice` = array layer or cube face). With `draw` set, the pipeline draws the full target.
// Returns the command buffer's status (0 when the encoder was refused).
static NSInteger depth_pass(id<MTLCommandQueue> q, id<MTLTexture> tex, NSUInteger slice, MTLLoadAction load, double clear,
                            BOOL draw, id<MTLRenderPipelineState> pso, id<MTLDepthStencilState> dss) {
    MTLRenderPassDescriptor *p = [MTLRenderPassDescriptor renderPassDescriptor];
    p.depthAttachment.texture = tex;
    p.depthAttachment.slice = slice;
    p.depthAttachment.loadAction = load;
    p.depthAttachment.clearDepth = clear;
    p.depthAttachment.storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> cb = [q commandBuffer];
    id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:p];
    if (!e) return 0;
    if (draw && pso) {
        [e setRenderPipelineState:pso];
        if (dss) [e setDepthStencilState:dss];
        [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    }
    [e endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    return cb.status;
}

// One attachment-less 1 x 1 pass with `pso`: the fragment writes one float to `out` (buffer 1). `arg` is bound at buffer 0.
// Returns YES when the command buffer completed, and stores the float in *value.
static BOOL sample_once(id<MTLCommandQueue> q, id<MTLRenderPipelineState> pso, id<MTLTexture> tex, id<MTLSamplerState> samp,
                        const void *arg, NSUInteger argLength, id<MTLBuffer> out, float *value) {
    memset(out.contents, 0, out.length);
    id<MTLCommandBuffer> cb = [q commandBuffer];
    id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:attachmentless(1, 1, 0)];
    if (!e) return NO;
    [e setRenderPipelineState:pso];
    [e setFragmentTexture:tex atIndex:0];
    [e setFragmentSamplerState:samp atIndex:0];
    [e setFragmentBytes:arg length:argLength atIndex:0];
    [e setFragmentBuffer:out offset:0 atIndex:1];
    [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [e endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    if (cb.status != MTLCommandBufferStatusCompleted) return NO;
    *value = *(float *)out.contents;
    return YES;
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
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Uint width:8 height:2 mipmapped:NO];
        td.storageMode = MTLStorageModeManaged;
        td.usage = MTLTextureUsageRenderTarget;
        id<MTLTexture> utex = [dev newTextureWithDescriptor:td];
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

        // ---- bundle 46: depth 2D arrays and cubes ----
        MTLRenderPipelineDescriptor *dd = [MTLRenderPipelineDescriptor new];   // depth only: no fragment, no colour
        dd.vertexFunction = [lib newFunctionWithName:@"vz"];
        dd.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;
        id<MTLRenderPipelineState> psoDepth = [dev newRenderPipelineStateWithDescriptor:dd error:&error];
        MTLRenderPipelineDescriptor *sd1 = [MTLRenderPipelineDescriptor new];
        sd1.vertexFunction = [lib newFunctionWithName:@"vs"];
        sd1.fragmentFunction = [lib newFunctionWithName:@"sample_cmp"];
        id<MTLRenderPipelineState> psoCmp = [dev newRenderPipelineStateWithDescriptor:sd1 error:&error];
        MTLRenderPipelineDescriptor *sd2 = [MTLRenderPipelineDescriptor new];
        sd2.vertexFunction = [lib newFunctionWithName:@"vs"];
        sd2.fragmentFunction = [lib newFunctionWithName:@"sample_plain"];
        id<MTLRenderPipelineState> psoPlain = [dev newRenderPipelineStateWithDescriptor:sd2 error:&error];
        MTLRenderPipelineDescriptor *sd3 = [MTLRenderPipelineDescriptor new];
        sd3.vertexFunction = [lib newFunctionWithName:@"vs"];
        sd3.fragmentFunction = [lib newFunctionWithName:@"sample_cube"];
        id<MTLRenderPipelineState> psoCube = [dev newRenderPipelineStateWithDescriptor:sd3 error:&error];
        report(psoDepth != nil && psoCmp != nil && psoPlain != nil && psoCube != nil, "the depth-only and depth-sampling pipelines are created");

        MTLSamplerDescriptor *cmpDesc = [MTLSamplerDescriptor new];
        cmpDesc.minFilter = MTLSamplerMinMagFilterNearest;
        cmpDesc.magFilter = MTLSamplerMinMagFilterNearest;
        cmpDesc.sAddressMode = MTLSamplerAddressModeClampToEdge;
        cmpDesc.tAddressMode = MTLSamplerAddressModeClampToEdge;
        cmpDesc.compareFunction = MTLCompareFunctionGreater;
        id<MTLSamplerState> sampCmp = [dev newSamplerStateWithDescriptor:cmpDesc];
        MTLSamplerDescriptor *plainDesc = [MTLSamplerDescriptor new];
        plainDesc.minFilter = MTLSamplerMinMagFilterNearest;
        plainDesc.magFilter = MTLSamplerMinMagFilterNearest;
        plainDesc.sAddressMode = MTLSamplerAddressModeClampToEdge;
        plainDesc.tAddressMode = MTLSamplerAddressModeClampToEdge;
        id<MTLSamplerState> sampPlain = [dev newSamplerStateWithDescriptor:plainDesc];
        MTLDepthStencilDescriptor *dsd = [MTLDepthStencilDescriptor new];
        dsd.depthCompareFunction = MTLCompareFunctionAlways;
        dsd.depthWriteEnabled = YES;
        id<MTLDepthStencilState> dssWrite = [dev newDepthStencilStateWithDescriptor:dsd];

        // 8. a 2D array of four Depth32Float layers, each cleared to 1.0 by its own pass
        MTLTextureDescriptor *ad = [MTLTextureDescriptor new];
        ad.textureType = MTLTextureType2DArray;
        ad.pixelFormat = MTLPixelFormatDepth32Float;
        ad.width = 8;
        ad.height = 8;
        ad.arrayLength = 4;
        ad.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        ad.storageMode = MTLStorageModePrivate;
        id<MTLTexture> arr = [dev newTextureWithDescriptor:ad];
        report(arr != nil && arr.textureType == MTLTextureType2DArray && arr.arrayLength == 4, "a Depth32Float 2D array texture (4 layers, Private) is created");
        BOOL clearedAll = arr != nil;
        for (NSUInteger s = 0; arr && s < 4; s++)
            clearedAll = clearedAll && depth_pass(q, arr, s, MTLLoadActionClear, 1.0, NO, nil, nil) == MTLCommandBufferStatusCompleted;
        report(clearedAll, "each of the four layers is cleared to 1.0 by a clear-only pass (per-layer depth attachments)");

        // 9. a depth-only pass draws depth 0.25 into layer 2 only
        report(arr != nil && psoDepth != nil && depth_pass(q, arr, 2, MTLLoadActionLoad, 0.0, YES, psoDepth, dssWrite) == MTLCommandBufferStatusCompleted,
               "a depth-only pass renders into layer 2 of the array");

        // 10. compare sample: Greater with reference 0.5 gives 1.0 for layer 2 (0.25) and 0.0 for layer 0 (1.0)
        float v = -1.0f;
        uint32_t layer = 2;
        BOOL okCmp2 = arr != nil && psoCmp != nil && sample_once(q, psoCmp, arr, sampCmp, &layer, sizeof(layer), out, &v);
        report(okCmp2 && fabsf(v - 1.0f) < 1e-3f, "compare sample of layer 2 (reference 0.5, Greater) gives 1.0");
        layer = 0;
        BOOL okCmp0 = arr != nil && psoCmp != nil && sample_once(q, psoCmp, arr, sampCmp, &layer, sizeof(layer), out, &v);
        report(okCmp0 && fabsf(v - 0.0f) < 1e-3f, "compare sample of the cleared layer 0 gives 0.0");

        // 11. plain samples: layer 2 reads 0.25, the cleared layer 3 reads 1.0
        layer = 2;
        BOOL okP2 = arr != nil && psoPlain != nil && sample_once(q, psoPlain, arr, sampPlain, &layer, sizeof(layer), out, &v);
        report(okP2 && fabsf(v - 0.25f) < 1e-3f, "plain sample of layer 2 reads the drawn depth 0.25");
        layer = 3;
        BOOL okP3 = arr != nil && psoPlain != nil && sample_once(q, psoPlain, arr, sampPlain, &layer, sizeof(layer), out, &v);
        report(okP3 && fabsf(v - 1.0f) < 1e-3f, "plain sample of the cleared layer 3 reads 1.0");

        // 12. a depth cube: every face cleared to 1.0, then face 3 (-Y) drawn at 0.25
        MTLTextureDescriptor *cd = [MTLTextureDescriptor textureCubeDescriptorWithPixelFormat:MTLPixelFormatDepth32Float size:4 mipmapped:NO];
        cd.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        cd.storageMode = MTLStorageModePrivate;
        id<MTLTexture> cube = [dev newTextureWithDescriptor:cd];
        report(cube != nil && cube.textureType == MTLTextureTypeCube, "a Depth32Float cube texture (4 x 4, Private) is created");
        BOOL cubeReady = cube != nil;
        for (NSUInteger f = 0; cube && f < 6; f++)
            cubeReady = cubeReady && depth_pass(q, cube, f, MTLLoadActionClear, 1.0, NO, nil, nil) == MTLCommandBufferStatusCompleted;
        cubeReady = cubeReady && depth_pass(q, cube, 3, MTLLoadActionLoad, 0.0, YES, psoDepth, dssWrite) == MTLCommandBufferStatusCompleted;
        report(cubeReady, "the six cube faces are cleared and face 3 is drawn at 0.25 (per-face depth attachments)");

        // 13. plain depth-cube samples: direction (0, -1, 0) is face 3 (0.25), (1, 0, 0) is face 0 (1.0)
        float dirMinusY[4] = { 0.0f, -1.0f, 0.0f, 0.0f };
        float dirPlusX[4] = { 1.0f, 0.0f, 0.0f, 0.0f };
        BOOL okC3 = cube != nil && psoCube != nil && sample_once(q, psoCube, cube, sampPlain, dirMinusY, sizeof(dirMinusY), out, &v);
        report(okC3 && fabsf(v - 0.25f) < 1e-3f, "depth-cube sample toward -Y (face 3) reads 0.25");
        BOOL okC0 = cube != nil && psoCube != nil && sample_once(q, psoCube, cube, sampPlain, dirPlusX, sizeof(dirPlusX), out, &v);
        report(okC0 && fabsf(v - 1.0f) < 1e-3f, "depth-cube sample toward +X (face 0) reads 1.0");

        // 14. zero-initialisation: a new array's layer is never drawn or cleared, and reads 0.0
        MTLTextureDescriptor *zd = [MTLTextureDescriptor new];
        zd.textureType = MTLTextureType2DArray;
        zd.pixelFormat = MTLPixelFormatDepth32Float;
        zd.width = 2;
        zd.height = 2;
        zd.arrayLength = 2;
        zd.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        zd.storageMode = MTLStorageModePrivate;
        id<MTLTexture> zarr = [dev newTextureWithDescriptor:zd];
        layer = 1;
        BOOL okZ = zarr != nil && psoPlain != nil && sample_once(q, psoPlain, zarr, sampPlain, &layer, sizeof(layer), out, &v);
        report(okZ && fabsf(v - 0.0f) < 1e-3f, "a fresh depth array layer that was never drawn or cleared reads 0.0 (zero-initialisation)");

        printf("test-noattach-runtime: %s (%d failed)\n", failures ? "FAILED" : "passed", failures);
        return failures ? 1 : 0;
    }
}
