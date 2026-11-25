// Runtime regression for cull mode and front winding across draw-cache hits,
// a pipeline-state change, and a new render pass. The bundle is loaded only
// into the probe process. Pass its absolute path as the sole argument.
// Build: clang -fobjc-arc -framework Foundation -framework Metal -framework IOKit test-raster-runtime.m -o raster-smoke
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <Metal/Metal.h>

@protocol Navi48ProbeDevice <MTLDevice>
- (instancetype)initWithAcceleratorPort:(uint32_t)port;
@end

static void draw(id<MTLRenderCommandEncoder> encoder, NSUInteger x, MTLCullMode cull, MTLWinding winding) {
    [encoder setScissorRect:(MTLScissorRect){x, 0, 1, 2}];
    [encoder setCullMode:cull];
    [encoder setFrontFacingWinding:winding];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
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

        NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
            "vertex float4 vs(uint v [[vertex_id]]) { const float2 p[3] = { {-1,-1}, {3,-1}, {-1,3} }; return float4(p[v],0,1); }\n"
            "fragment float4 red() { return float4(1,0,0,1); }\n"
            "fragment float4 green() { return float4(0,1,0,1); }\n";
        id<MTLLibrary> lib = [dev newLibraryWithSource:source options:nil error:&error];
        if (!lib) { NSLog(@"library %@", error); return 2; }
        MTLRenderPipelineDescriptor *pipeline = [MTLRenderPipelineDescriptor new];
        pipeline.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        pipeline.vertexFunction = [lib newFunctionWithName:@"vs"];
        pipeline.fragmentFunction = [lib newFunctionWithName:@"red"];
        id<MTLRenderPipelineState> red = [dev newRenderPipelineStateWithDescriptor:pipeline error:&error];
        pipeline.fragmentFunction = [lib newFunctionWithName:@"green"];
        id<MTLRenderPipelineState> green = [dev newRenderPipelineStateWithDescriptor:pipeline error:&error];
        if (!red || !green) { NSLog(@"pipeline %@", error); return 2; }
        MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
            width:8 height:2 mipmapped:NO];
        desc.storageMode = MTLStorageModeManaged;
        desc.usage = MTLTextureUsageRenderTarget;
        id<MTLTexture> tex = [dev newTextureWithDescriptor:desc];
        if (!tex) return 2;
        id<MTLCommandQueue> queue = [dev newCommandQueue];
        id<MTLCommandBuffer> cb = [queue commandBuffer];
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = tex;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
        id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:pass];
        [enc setRenderPipelineState:red];
        draw(enc, 0, MTLCullModeNone, MTLWindingClockwise);
        draw(enc, 1, MTLCullModeBack, MTLWindingClockwise);
        draw(enc, 2, MTLCullModeBack, MTLWindingCounterClockwise);
        draw(enc, 3, MTLCullModeFront, MTLWindingCounterClockwise);
        [enc setRenderPipelineState:green];
        draw(enc, 4, MTLCullModeBack, MTLWindingClockwise);
        draw(enc, 5, MTLCullModeBack, MTLWindingCounterClockwise);
        [enc endEncoding];
        pass.colorAttachments[0].loadAction = MTLLoadActionLoad;
        enc = [cb renderCommandEncoderWithDescriptor:pass];
        [enc setRenderPipelineState:green];
        draw(enc, 6, MTLCullModeBack, MTLWindingClockwise);
        draw(enc, 7, MTLCullModeBack, MTLWindingCounterClockwise);
        [enc endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted) { NSLog(@"command buffer %@", cb.error); return 2; }
        uint8_t p[8][4] = {0};
        [tex getBytes:p bytesPerRow:sizeof p fromRegion:MTLRegionMake2D(0, 0, 8, 1) mipmapLevel:0];
        printf("raster:");
        for (unsigned i = 0; i < 8; ++i) printf(" %u/%u", p[i][0], p[i][1]);
        puts("");
        BOOL ok = p[0][0] == 255 && p[1][0] + p[2][0] == 255 && p[3][0] == p[1][0]
               && p[4][1] == p[1][0] && p[5][1] == p[2][0] && p[6][1] == p[4][1] && p[7][1] == p[5][1];
        return ok ? 0 : 1;
    }
}
