// Exercise the real bundle factory without initializing a device or opening GPU
// clients. The zero-initialized receiver is intentionally never released: its
// inherited destructor expects a fully initialized IOAccel device. This probe
// covers only the factory error boundary, not RenderBox fallback or GPU work.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <unistd.h>

@interface NSObject (N48ArchiveProbe)
- (id)newBinaryArchiveWithDescriptor:(MTLBinaryArchiveDescriptor *)descriptor error:(NSError **)error;
@end

int main(int argc, char **argv) {
    if (argc != 2) return 64;
    if (!dlopen(argv[1], RTLD_NOW | RTLD_LOCAL)) { fprintf(stderr, "%s\n", dlerror()); return 65; }
    Class cls = NSClassFromString(@"Navi48Device");
    SEL selector = @selector(newBinaryArchiveWithDescriptor:error:);
    Method own = class_getInstanceMethod(cls, selector);
    Method inherited = class_getInstanceMethod(class_getSuperclass(cls), selector);
    if (!cls || !own || method_getImplementation(own) == method_getImplementation(inherited)) return 66;
    id device = class_createInstance(cls, 0);
    MTLBinaryArchiveDescriptor *descriptor = [MTLBinaryArchiveDescriptor new];
    for (int i = 0; i < 3; ++i) {
        descriptor.url = i == 0 ? nil : [NSURL fileURLWithPath:i == 1 ? @"/nonexistent/archive.metallib" : @"/System/Library/PrivateFrameworks/RenderBox.framework/Resources/binary.metallib"];
        NSError *error = nil;
        id archive = [device newBinaryArchiveWithDescriptor:descriptor error:&error];
        if (archive || ![error.domain isEqualToString:MTLBinaryArchiveDomain] || !error.localizedDescription.length) _exit(67);
        if ([device newBinaryArchiveWithDescriptor:descriptor error:NULL]) _exit(68);
    }
    puts("PASS: six actual factory calls return nil/error without the native loader or a GPU client; RenderBox fallback remains untested.");
    fflush(stdout);
    _exit(0);
}
