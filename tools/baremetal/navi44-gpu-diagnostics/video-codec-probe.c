#include <stdio.h>
#include <VideoToolbox/VideoToolbox.h>
int main(void) {
    struct codec { const char *name; CMVideoCodecType type; } c[] = {
        {"H264", 'avc1'}, {"HEVC", 'hvc1'}, {"VP9", 'vp09'}, {"AV1", 'av01'}
    };
    for (unsigned i=0; i<sizeof(c)/sizeof(c[0]); ++i)
        printf("%s hardware_decode_supported=%d\n", c[i].name, VTIsHardwareDecodeSupported(c[i].type));
    return 0;
}
