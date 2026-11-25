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
        puts("PASS: ANGLE cubemap descriptor, reported usage, six-face GPU mipmap readback and the cube / face / array views");
    }
    return 0;
}
