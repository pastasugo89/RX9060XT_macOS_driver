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
        puts("PASS: ANGLE cubemap descriptor, reported usage and six-face GPU mipmap readback");
    }
    return 0;
}
