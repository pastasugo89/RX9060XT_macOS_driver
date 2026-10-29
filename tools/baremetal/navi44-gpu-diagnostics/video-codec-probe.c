#include <stdio.h>
#include <VideoToolbox/VideoToolbox.h>

// This deliberately supplies a generic format without codec parameter sets.
// It measures session creation/property availability, not successful decoding.
static void callback(void *ref, void *frame, OSStatus status,
                     VTDecodeInfoFlags flags, CVImageBufferRef image,
                     CMTime pts, CMTime duration) {
    (void)ref; (void)frame; (void)status; (void)flags; (void)image;
    (void)pts; (void)duration;
}

static void session_probe(CMVideoCodecType type, int required) {
    CMVideoFormatDescriptionRef format = NULL;
    OSStatus status = CMVideoFormatDescriptionCreate(kCFAllocatorDefault, type,
                                                       1920, 1080, NULL, &format);
    if (status != noErr || !format) {
        printf(" mode=%s format_status=%d", required ? "require" : "enable", (int)status);
        return;
    }
    const void *key = required ? kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder
                               : kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder;
    const void *value = kCFBooleanTrue;
    CFDictionaryRef spec = CFDictionaryCreate(kCFAllocatorDefault, &key, &value, 1,
                                               &kCFTypeDictionaryKeyCallBacks,
                                               &kCFTypeDictionaryValueCallBacks);
    VTDecompressionSessionRef session = NULL;
    VTDecompressionOutputCallbackRecord cb = { callback, NULL };
    if (!spec) {
        printf(" mode=%s specification_allocation_failed", required ? "require" : "enable");
        CFRelease(format);
        return;
    }
    status = VTDecompressionSessionCreate(kCFAllocatorDefault, format, spec, NULL, &cb, &session);
    printf(" mode=%s create_status=%d", required ? "require" : "enable", (int)status);
    if (session) {
        CFTypeRef hw = NULL;
        OSStatus prop = VTSessionCopyProperty(session, kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder,
                                              kCFAllocatorDefault, &hw);
        printf(" property_status=%d hardware=%s", (int)prop,
               hw && CFGetTypeID(hw) == CFBooleanGetTypeID() ?
               (CFBooleanGetValue((CFBooleanRef)hw) ? "true" : "false") : "unknown");
        if (hw) CFRelease(hw);
        VTDecompressionSessionInvalidate(session);
        CFRelease(session);
    }
    CFRelease(spec);
    CFRelease(format);
}

int main(void) {
    struct codec { const char *name; CMVideoCodecType type; } c[] = {
        {"H264", 'avc1'}, {"HEVC", 'hvc1'}, {"VP9", 'vp09'}, {"AV1", 'av01'}
    };
    puts("Generic 1920x1080 descriptions without codec parameter sets; no video is decoded.");
    for (unsigned i=0; i<sizeof(c)/sizeof(c[0]); ++i) {
        printf("%s hardware_decode_supported=%d", c[i].name, VTIsHardwareDecodeSupported(c[i].type));
        session_probe(c[i].type, 0);
        session_probe(c[i].type, 1);
        putchar('\n');
    }
    return 0;
}
