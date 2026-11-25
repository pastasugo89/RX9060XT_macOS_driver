// Exercise BC7 detection, compressed copies and fragment reads on the GPU.
// Build: clang -fobjc-arc -framework Foundation -framework Metal -framework IOKit test-bc-runtime.m -o bc-smoke
// Pass the absolute path of a Navi48Metal.bundle; it is loaded only in this process.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <Metal/Metal.h>
#include <string.h>

@protocol Navi48ProbeDevice <MTLDevice>
- (instancetype)initWithAcceleratorPort:(uint32_t)port;
@end

static void putBits(uint8_t *b, unsigned *pos, unsigned value, unsigned count) {
    for (unsigned i = 0; i < count; ++i, ++*pos)
        b[*pos / 8] |= ((value >> i) & 1u) << (*pos % 8);
}
// BC7 mode 6: one subset, 7-bit RGBA endpoints and one p-bit per endpoint.
// Both endpoints expand to (255,1,1,255), and all indices are zero.
static void makeBlock(uint8_t b[16]) {
    memset(b, 0, 16); unsigned p = 0;
    putBits(b, &p, 1u << 6, 7);
    const unsigned endpoints[] = {127,127, 0,0, 0,0, 127,127};
    for (unsigned i = 0; i < 8; ++i) putBits(b, &p, endpoints[i], 7);
    putBits(b, &p, 1, 1); putBits(b, &p, 1, 1);
    putBits(b, &p, 0, 3); // Anchor index omits its high bit.
    for (unsigned i = 1; i < 16; ++i) putBits(b, &p, 0, 4);
    if (p != 128) abort();
}
static BOOL completed(id<MTLCommandBuffer> cb, const char *label) {
    [cb commit]; [cb waitUntilCompleted];
    if (cb.status != MTLCommandBufferStatusCompleted) {
        fprintf(stderr, "%s failed (status %lu): %s\n", label, (unsigned long)cb.status,
                (cb.error.localizedDescription ?: @"no error detail").UTF8String);
        return NO;
    }
    return YES;
}
static void dumpBlock(const uint8_t *b) {
    for (unsigned i = 0; i < 16; ++i) fprintf(stderr, "%02x%s", b[i], i == 15 ? "\n" : " ");
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) { fprintf(stderr, "usage: %s /absolute/path/Navi48Metal.bundle\n", argv[0]); return 2; }
        io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("Navi48Accelerator"));
        if (!service) { fprintf(stderr, "missing Navi48 accelerator\n"); return 2; }
        NSBundle *bundle = [NSBundle bundleWithPath:@(argv[1])]; NSError *error = nil;
        if (![bundle loadAndReturnError:&error]) {
            fprintf(stderr, "cannot load requested bundle: %s\n", (error.localizedDescription ?: @"invalid bundle").UTF8String);
            IOObjectRelease(service); return 2;
        }
        id<Navi48ProbeDevice> dev = [[bundle.principalClass alloc] initWithAcceleratorPort:service];
        IOObjectRelease(service);
        if (!dev) { fprintf(stderr, "could not open Navi48 device\n"); return 2; }
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations" // Basemark still uses the legacy Mac1 query.
        BOOL family = [dev supportsFamily:MTLGPUFamilyMac1];
#pragma clang diagnostic pop
        BOOL bc = [dev supportsBCTextureCompression];
        printf("Mac1=%d supportsBCTextureCompression=%d\n", family, bc);
        if (!family || !bc) { fprintf(stderr, "Basemark BC compression capability gate failed\n"); return 1; }
        uint8_t block[16], result[16]; makeBlock(block);
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBC7_RGBAUnorm width:4 height:4 mipmapped:NO];
        d.usage = MTLTextureUsageShaderRead; d.storageMode = MTLStorageModeManaged;
        id<MTLTexture> managed = [dev newTextureWithDescriptor:d];
        if (!managed) { fprintf(stderr, "managed BC7 allocation failed\n"); return 1; }
        MTLRegion region = MTLRegionMake2D(0, 0, 4, 4);
        [managed replaceRegion:region mipmapLevel:0 withBytes:block bytesPerRow:16];
        memset(result, 0, sizeof result);
        [managed getBytes:result bytesPerRow:16 fromRegion:region mipmapLevel:0];
        if (memcmp(block, result, 16)) {
            fprintf(stderr, "managed BC7 compressed byte roundtrip failed; expected: "); dumpBlock(block);
            fprintf(stderr, "actual: "); dumpBlock(result); return 1;
        }
        MTLTextureDescriptor *edgeDesc = [MTLTextureDescriptor
            texture2DDescriptorWithPixelFormat:MTLPixelFormatBC7_RGBAUnorm_sRGB width:7 height:5 mipmapped:YES];
        edgeDesc.storageMode = MTLStorageModeManaged;
        id<MTLTexture> edge = [dev newTextureWithDescriptor:edgeDesc];
        if (!edge) { fprintf(stderr, "edge-sized BC7 sRGB texture allocation failed\n"); return 1; }
        uint8_t rows[96] = {0}, readback[96];
        for (unsigned i = 0; i < 2; i++) {
            memcpy(rows + i * 48, block, 16);
            memcpy(rows + i * 48 + 16, block, 16);
            rows[i * 48 + 17] ^= (uint8_t)(i + 1);
        }
        MTLRegion edgeRegion = MTLRegionMake2D(0, 0, 7, 5);
        memset(readback, 0xA5, sizeof readback);
        [edge getBytes:readback bytesPerRow:48 fromRegion:edgeRegion mipmapLevel:0];
        const uint8_t empty[32] = {0};
        if (memcmp(readback, empty, 32) || memcmp(readback + 48, empty, 32) || readback[32] != 0xA5) {
            fprintf(stderr, "BC7 allocation did not initialize both block rows\n"); return 1;
        }
        [edge replaceRegion:edgeRegion mipmapLevel:0 withBytes:rows bytesPerRow:48];
        memset(readback, 0xA5, sizeof readback);
        [edge getBytes:readback bytesPerRow:48 fromRegion:edgeRegion mipmapLevel:0];
        if (memcmp(readback, rows, 32) || memcmp(readback + 48, rows + 48, 32) ||
            readback[32] != 0xA5 || readback[80] != 0xA5) {
            fprintf(stderr, "BC7 block row pitch or padding was incorrect\n"); return 1;
        }
        MTLRegion tail = MTLRegionMake2D(0, 0, 1, 1);
        memset(result, 0, sizeof result);
        [edge replaceRegion:tail mipmapLevel:2 withBytes:block bytesPerRow:16];
        [edge getBytes:result bytesPerRow:16 fromRegion:tail mipmapLevel:2];
        if (memcmp(block, result, sizeof result)) { fprintf(stderr, "BC7 1x1 tail mip copy failed\n"); return 1; }
        d.storageMode = MTLStorageModePrivate;
        id<MTLTexture> tex = [dev newTextureWithDescriptor:d];
        id<MTLBuffer> upload = [dev newBufferWithLength:256 options:MTLResourceStorageModeShared];
        id<MTLBuffer> download = [dev newBufferWithLength:256 options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> queue = [dev newCommandQueue];
        if (!tex || !upload || !download || !queue) { fprintf(stderr, "private BC7 texture, buffer, or queue allocation failed\n"); return 1; }
        memset(upload.contents, 0, 256); memcpy(upload.contents, block, 16); memset(download.contents, 0xA5, 256);
        id<MTLCommandBuffer> cb = [queue commandBuffer]; id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
        if (!cb || !blit) { fprintf(stderr, "BC7 upload encoder failed\n"); return 1; }
        [blit copyFromBuffer:upload sourceOffset:0 sourceBytesPerRow:256 sourceBytesPerImage:256 sourceSize:MTLSizeMake(4,4,1)
                   toTexture:tex destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
        [blit copyFromTexture:tex sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(4,4,1)
                    toBuffer:download destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:256];
        [blit endEncoding];
        if (!completed(cb, "private BC7 upload/readback")) return 1;
        if (memcmp(block, download.contents, 16)) {
            fprintf(stderr, "private BC7 compressed byte roundtrip failed; expected: "); dumpBlock(block);
            fprintf(stderr, "actual: "); dumpBlock(download.contents); return 1;
        }
        NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
            "vertex float4 v(uint id [[vertex_id]]) { float2 p[3] = {float2(-1,-1),float2(3,-1),float2(-1,3)}; return float4(p[id],0,1); }\n"
            "fragment float4 f(texture2d<float> t [[texture(0)]]) { return t.read(uint2(0,0)); }\n";
        id<MTLLibrary> library = [dev newLibraryWithSource:source options:nil error:&error];
        if (!library) { fprintf(stderr, "shader compilation failed: %s\n", (error.localizedDescription ?: @"no detail").UTF8String); return 1; }
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [library newFunctionWithName:@"v"]; pd.fragmentFunction = [library newFunctionWithName:@"f"];
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        id<MTLRenderPipelineState> pipeline = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
        if (!pipeline) { fprintf(stderr, "pipeline creation failed: %s\n", (error.localizedDescription ?: @"no detail").UTF8String); return 1; }
        MTLTextureDescriptor *outDesc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];
        outDesc.usage = MTLTextureUsageRenderTarget; outDesc.storageMode = MTLStorageModeManaged;
        id<MTLTexture> out = [dev newTextureWithDescriptor:outDesc];
        if (!out) { fprintf(stderr, "render target allocation failed\n"); return 1; }
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = out; pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        cb = [queue commandBuffer]; id<MTLRenderCommandEncoder> render = [cb renderCommandEncoderWithDescriptor:pass];
        if (!cb || !render) { fprintf(stderr, "render encoder creation failed\n"); return 1; }
        [render setRenderPipelineState:pipeline]; [render setFragmentTexture:tex atIndex:0];
        [render drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; [render endEncoding];
        if (!completed(cb, "BC7 fragment read")) return 1;
        uint8_t pixel[4] = {0}; [out getBytes:pixel bytesPerRow:4 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
        if (pixel[0] != 255 || pixel[1] != 1 || pixel[2] != 1 || pixel[3] != 255) {
            fprintf(stderr, "BC7 decoded pixel mismatch: got (%u,%u,%u,%u), expected (255,1,1,255)\n", pixel[0],pixel[1],pixel[2],pixel[3]); return 1;
        }
        puts("PASS: Mac1/BC capability, padded BC7 rows, tail mip, managed and private copies, and decoded fragment color");
        return 0;
    }
}
