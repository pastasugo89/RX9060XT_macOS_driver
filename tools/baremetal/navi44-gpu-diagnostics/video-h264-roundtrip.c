#include <CoreVideo/CoreVideo.h>
#include <VideoToolbox/VideoToolbox.h>
#include <stdio.h>
#include <string.h>

// Generate one synthetic H.264 frame using a software encoder, then give the
// exact emitted format and sample to VideoToolbox. Never touches user media.
struct output { CMSampleBufferRef sample; OSStatus status; };
static void encoded(void *opaque, void *frame, OSStatus status, VTEncodeInfoFlags flags, CMSampleBufferRef sample) {
    (void)frame; (void)flags;
    struct output *o = opaque; o->status = status;
    if (sample && status == noErr) o->sample = (CMSampleBufferRef)CFRetain(sample);
}
struct decoded { unsigned callbacks; OSStatus status; bool hasImage; };
static void decoded(void *opaque, void *frame, OSStatus status, VTDecodeInfoFlags flags,
                    CVImageBufferRef image, CMTime pts, CMTime duration) {
    (void)frame; (void)flags; (void)pts; (void)duration;
    struct decoded *d = opaque; d->callbacks++; d->status = status; d->hasImage = image != NULL;
}
static OSStatus run_decode(CMSampleBufferRef sample, bool require) {
    CFStringRef key = require ? kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder
                              : kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder;
    const void *keys[] = {key}, *values[] = {kCFBooleanTrue};
    CFDictionaryRef spec = CFDictionaryCreate(NULL, keys, values, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    if (!spec) return -1;
    struct decoded d = {0};
    VTDecompressionOutputCallbackRecord cb = {decoded, &d};
    VTDecompressionSessionRef session = NULL;
    OSStatus result = VTDecompressionSessionCreate(NULL, CMSampleBufferGetFormatDescription(sample), spec, NULL, &cb, &session);
    CFRelease(spec);
    printf("mode=%s create=%d", require ? "require" : "enable", (int)result);
    if (result == noErr && session) {
        CFTypeRef value = NULL;
        OSStatus prop = VTSessionCopyProperty(session, kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder, NULL, &value);
        printf(" property=%d hardware=%s", (int)prop,
               value && CFGetTypeID(value) == CFBooleanGetTypeID() ? (CFBooleanGetValue(value) ? "true" : "false") : "unknown");
        if (value) CFRelease(value);
        VTDecodeInfoFlags flags = 0;
        result = VTDecompressionSessionDecodeFrame(session, sample, 0, NULL, &flags);
        OSStatus waited = VTDecompressionSessionWaitForAsynchronousFrames(session);
        printf(" decode=%d wait=%d callbacks=%u callback_status=%d image=%s", (int)result, (int)waited,
               d.callbacks, (int)d.status, d.hasImage ? "yes" : "no");
        VTDecompressionSessionInvalidate(session);
        CFRelease(session);
        if (result == noErr && (waited != noErr || !d.callbacks || d.status != noErr || !d.hasImage)) result = -2;
    }
    putchar('\n');
    return result;
}
int main(void) {
    const void *keys[] = {kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder};
    const void *values[] = {kCFBooleanFalse};
    CFDictionaryRef spec = CFDictionaryCreate(NULL, keys, values, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    struct output o = {0}; VTCompressionSessionRef encoder = NULL; CVPixelBufferRef buffer = NULL;
    if (!spec) return 1;
    OSStatus status = VTCompressionSessionCreate(NULL, 64, 64, kCMVideoCodecType_H264, spec, NULL, NULL, encoded, &o, &encoder);
    CFRelease(spec);
    if (status != noErr || !encoder) { printf("encoder_create=%d\n", (int)status); return 1; }
    status = CVPixelBufferCreate(NULL, 64, 64, kCVPixelFormatType_32BGRA, NULL, &buffer);
    if (status == noErr && buffer) {
        status = CVPixelBufferLockBaseAddress(buffer, 0);
        if (status == noErr) {
            memset(CVPixelBufferGetBaseAddress(buffer), 0x80, CVPixelBufferGetBytesPerRow(buffer) * CVPixelBufferGetHeight(buffer));
            CVPixelBufferUnlockBaseAddress(buffer, 0);
            status = VTCompressionSessionEncodeFrame(encoder, buffer, CMTimeMake(0, 30), CMTimeMake(1, 30), NULL, NULL, NULL);
            if (status == noErr) status = VTCompressionSessionCompleteFrames(encoder, kCMTimeInvalid);
        }
        CVPixelBufferRelease(buffer);
    }
    VTCompressionSessionInvalidate(encoder); CFRelease(encoder);
    if (status != noErr || o.status != noErr || !o.sample) {
        printf("encode=%d callback=%d sample=%s\n", (int)status, (int)o.status, o.sample ? "yes" : "no");
        if (o.sample) CFRelease(o.sample);
        return 1;
    }
    printf("Synthetic H.264 64x64: hardware_supported=%d\n", VTIsHardwareDecodeSupported(kCMVideoCodecType_H264));
    OSStatus allowed = run_decode(o.sample, false);
    (void)run_decode(o.sample, true);
    CFRelease(o.sample);
    return allowed == noErr ? 0 : 1;
}
