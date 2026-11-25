// GPU regression for the cubemap descriptor used by ANGLE and its blit path.
// Build with clang -fobjc-arc -framework Foundation -framework Metal -framework IOKit.
// Pass an absolute Navi48Metal.bundle path. The probe loads it only into this process.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <Metal/Metal.h>

@protocol Navi48ProbeDevice <MTLDevice>
- (instancetype)initWithAcceleratorPort:(uint32_t)port;
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("Navi48Accelerator"));
        if (!service) { fprintf(stderr, "missing Navi48 accelerator\n"); return 2; }
        NSBundle *bundle = [NSBundle bundleWithPath:@(argv[1])];
        NSError *error = nil;
        if (![bundle loadAndReturnError:&error]) {
            fprintf(stderr, "cannot load requested bundle: %s\n", (error.localizedDescription ?: @"invalid bundle").UTF8String);
            return 2;
        }
        id<Navi48ProbeDevice> dev = [[bundle.principalClass alloc] initWithAcceleratorPort:service];
        IOObjectRelease(service);
        if (!dev) { fprintf(stderr, "could not open Navi48 device\n"); return 2; }

        MTLTextureUsage supported = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
        MTLTextureDescriptor *d = [MTLTextureDescriptor textureCubeDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm size:1 mipmapped:NO];
        d.usage = supported | MTLTextureUsageShaderWrite;
        d.storageMode = MTLStorageModeManaged;
        id<MTLTexture> tex = [dev newTextureWithDescriptor:d];
        if (!tex) { fprintf(stderr, "1x1 cube with ANGLE usage was refused\n"); return 1; }
        if (tex.usage != supported || tex.textureType != MTLTextureTypeCube) {
            fprintf(stderr, "unexpected cube usage/type: %lu/%lu\n", (unsigned long)tex.usage, (unsigned long)tex.textureType);
            return 1;
        }

        d = [MTLTextureDescriptor textureCubeDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm size:4 mipmapped:YES];
        d.usage = supported | MTLTextureUsageShaderWrite;
        d.storageMode = MTLStorageModeManaged;
        tex = [dev newTextureWithDescriptor:d];
        if (!tex || tex.mipmapLevelCount != 3) { fprintf(stderr, "mipmapped cube allocation failed\n"); return 1; }
        for (NSUInteger face = 0; face < 6; face++) {
            uint8_t input[64];
            memset(input, (int)(48 + face * 24), sizeof(input));
            [tex replaceRegion:MTLRegionMake2D(0, 0, 4, 4) mipmapLevel:0 slice:face withBytes:input bytesPerRow:16 bytesPerImage:64];
        }
        id<MTLCommandQueue> queue = [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [queue commandBuffer];
        id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
        if (!blit) { fprintf(stderr, "blit setup failed\n"); return 1; }
        [blit generateMipmapsForTexture:tex];
        [blit endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted) {
            fprintf(stderr, "cube mipmap blit failed: %s\n", cb.error.localizedDescription.UTF8String);
            return 1;
        }
        for (NSUInteger face = 0; face < 6; face++) {
            uint8_t result[4] = {0};
            [tex getBytes:result bytesPerRow:4 bytesPerImage:4 fromRegion:MTLRegionMake2D(0, 0, 1, 1) mipmapLevel:2 slice:face];
            for (NSUInteger i = 0; i < 4; i++) {
                if (result[i] != 48 + face * 24) { fprintf(stderr, "wrong mipmap value on face %lu\n", (unsigned long)face); return 1; }
            }
        }
        // bundle 40: views of the mipmapped cube (a 2D view of one face, a cube view, a 2D-array view, the one-argument view). Each probe reads the texel a view names
        // and must equal the root's texel at the level and face the view maps to (the faces hold 48 + 24 * face at every level, the mipmaps being box averages of constants).
        id<MTLTexture> face = [tex newTextureViewWithPixelFormat:MTLPixelFormatRGBA8Unorm textureType:MTLTextureType2D levels:NSMakeRange(1, 1) slices:NSMakeRange(2, 1)];
        id<MTLTexture> cube = [tex newTextureViewWithPixelFormat:MTLPixelFormatRGBA8Unorm textureType:MTLTextureTypeCube levels:NSMakeRange(0, 3) slices:NSMakeRange(0, 6)];
        id<MTLTexture> arr = [tex newTextureViewWithPixelFormat:MTLPixelFormatRGBA8Unorm textureType:MTLTextureType2DArray levels:NSMakeRange(0, 3) slices:NSMakeRange(1, 3)];
        id<MTLTexture> whole = [tex newTextureViewWithPixelFormat:MTLPixelFormatRGBA8Unorm];
        if (!face || !cube || !arr || !whole) { fprintf(stderr, "a cube view was refused (face %d, cube %d, array %d, whole %d)\n", face != nil, cube != nil, arr != nil, whole != nil); return 1; }
        if (face.textureType != MTLTextureType2D || face.width != 2 || face.height != 2 || face.mipmapLevelCount != 1 || face.arrayLength != 1 ||
            cube.textureType != MTLTextureTypeCube || cube.mipmapLevelCount != 3 || arr.textureType != MTLTextureType2DArray || arr.arrayLength != 3 ||
            whole.textureType != MTLTextureTypeCube || whole.mipmapLevelCount != 3) {
            fprintf(stderr, "view shape is wrong (face %lu/%lu levels %lu, cube levels %lu, array length %lu)\n", (unsigned long)face.width, (unsigned long)face.textureType,
                    (unsigned long)face.mipmapLevelCount, (unsigned long)cube.mipmapLevelCount, (unsigned long)arr.arrayLength);
            return 1;
        }
        struct { __unsafe_unretained id<MTLTexture> view; NSUInteger viewLevel, viewSlice, rootLevel, rootSlice; } probes[] = {
            { face, 0, 0, 1, 2 }, { arr, 0, 0, 0, 1 }, { cube, 2, 5, 2, 5 }, { whole, 1, 4, 1, 4 } };
        for (size_t i = 0; i < sizeof probes / sizeof *probes; i++) {
            uint8_t viaView[4] = {0}, viaRoot[4] = {0};
            [probes[i].view getBytes:viaView bytesPerRow:4 bytesPerImage:4 fromRegion:MTLRegionMake2D(0, 0, 1, 1) mipmapLevel:probes[i].viewLevel slice:probes[i].viewSlice];
            [tex getBytes:viaRoot bytesPerRow:4 bytesPerImage:4 fromRegion:MTLRegionMake2D(0, 0, 1, 1) mipmapLevel:probes[i].rootLevel slice:probes[i].rootSlice];
            if (memcmp(viaView, viaRoot, 4) != 0 || viaView[0] != 48 + probes[i].rootSlice * 24) { fprintf(stderr, "view probe %lu reads the wrong texels\n", (unsigned long)i); return 1; }
        }
        // Exercise the WebGL framebuffer path: clear through a face view with
        // nonzero base mip and face, then read the root and a neighboring face.
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = face;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(1, 0, 0, 1);
        cb = [queue commandBuffer];
        id<MTLRenderCommandEncoder> render = [cb renderCommandEncoderWithDescriptor:pass];
        if (!render) { fprintf(stderr, "cube face render attachment was refused\n"); return 1; }
        [render endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted) {
            fprintf(stderr, "cube face render pass failed: %s\n", cb.error.localizedDescription.UTF8String);
            return 1;
        }
        uint8_t pixel[4], adjacent[4];
        const uint8_t red[4] = {255, 0, 0, 255};
        const uint8_t unchanged[4] = {72, 72, 72, 72};
        MTLRegion onePixel = MTLRegionMake2D(0, 0, 1, 1);
        [tex getBytes:pixel bytesPerRow:4 bytesPerImage:4 fromRegion:onePixel mipmapLevel:1 slice:2];
        [tex getBytes:adjacent bytesPerRow:4 bytesPerImage:4 fromRegion:onePixel mipmapLevel:1 slice:1];
        if (memcmp(pixel, red, sizeof pixel) || memcmp(adjacent, unchanged, sizeof adjacent)) {
            fprintf(stderr, "cube face attachment did not clear just its own subresource\n");
            return 1;
        }
        // Both views share one VkImage. Copy between different root faces
        // and confirm the source and an unrelated subresource keep their bytes.
        id<MTLTexture> destFace = [tex newTextureViewWithPixelFormat:MTLPixelFormatRGBA8Unorm
            textureType:MTLTextureType2D levels:NSMakeRange(1, 1) slices:NSMakeRange(4, 1)];
        if (!destFace) { fprintf(stderr, "destination cube view was refused\n"); return 1; }
        cb = [queue commandBuffer];
        blit = [cb blitCommandEncoder];
        [blit copyFromTexture:face sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
                   sourceSize:MTLSizeMake(1, 1, 1) toTexture:destFace destinationSlice:0
              destinationLevel:0 destinationOrigin:MTLOriginMake(1, 1, 0)];
        [blit endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted) {
            fprintf(stderr, "shared image copy failed: %s\n", cb.error.localizedDescription.UTF8String);
            return 1;
        }
        uint8_t copied[4];
        [tex getBytes:copied bytesPerRow:4 bytesPerImage:4
             fromRegion:MTLRegionMake2D(1, 1, 1, 1) mipmapLevel:1 slice:4];
        [tex getBytes:pixel bytesPerRow:4 bytesPerImage:4 fromRegion:onePixel mipmapLevel:1 slice:2];
        [tex getBytes:adjacent bytesPerRow:4 bytesPerImage:4 fromRegion:onePixel mipmapLevel:1 slice:1];
        if (memcmp(copied, red, sizeof copied) || memcmp(pixel, red, sizeof pixel) ||
            memcmp(adjacent, unchanged, sizeof adjacent)) {
            fprintf(stderr, "shared image copy addressed the wrong subresource\n");
            return 1;
        }
        MTLTextureDescriptor *linearDesc = [MTLTextureDescriptor
            texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];
        linearDesc.storageMode = MTLStorageModeManaged;
        MTLTextureDescriptor *srgbDesc = [linearDesc copy];
        srgbDesc.pixelFormat = MTLPixelFormatRGBA8Unorm_sRGB;
        id<MTLTexture> linear = [dev newTextureWithDescriptor:linearDesc];
        id<MTLTexture> srgb = [dev newTextureWithDescriptor:srgbDesc];
        if (!linear || !srgb) { fprintf(stderr, "sRGB/linear textures were refused\n"); return 1; }
        const uint8_t raw[4] = {23, 71, 142, 255};
        [linear replaceRegion:onePixel mipmapLevel:0 withBytes:raw bytesPerRow:4];
        cb = [queue commandBuffer];
        blit = [cb blitCommandEncoder];
        [blit copyFromTexture:linear sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
                   sourceSize:MTLSizeMake(1, 1, 1) toTexture:srgb destinationSlice:0
              destinationLevel:0 destinationOrigin:MTLOriginMake(0, 0, 0)];
        [blit endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted) {
            fprintf(stderr, "sRGB/linear copy failed: %s\n", cb.error.localizedDescription.UTF8String);
            return 1;
        }
        [srgb getBytes:copied bytesPerRow:4 fromRegion:onePixel mipmapLevel:0];
        if (memcmp(copied, raw, sizeof copied)) {
            fprintf(stderr, "sRGB/linear copy changed the stored bytes\n");
            return 1;
        }
        puts("PASS: ANGLE cubemap descriptor, reported usage, six-face GPU mipmap readback, cube / face / array views, face attachment clear, and texture copy readback");
    }
    return 0;
}
