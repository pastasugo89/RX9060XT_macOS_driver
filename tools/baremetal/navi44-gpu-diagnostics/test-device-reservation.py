#!/usr/bin/env python3
"""Run the actual Metal initializer with deterministic admission/backend failures.

The superclass and backend are stubs; this verifies ordering and device exposure,
not IOAccel ABI, hardware resource acquisition, or rendering.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
source = (root / 'cobalt64/tools/native/navi48metal/Navi48Device.m').read_text()
start = source.index('- (instancetype)initWithAcceleratorPort:(uint32_t)port {')
end = source.index('\n- (BOOL)supportLazyInitialization', start)
initializer = source[start:end]
prefix = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdint.h>
#define os_log(...) ((void)0)
#define NSLog(...) ((void)0)
#define N48LOG(...) ((void)0)
static int ws, declined, backend, superFails, opens, supers, census;
static uint32_t n48_acc_port;
static const char *n48_admit(uint32_t port) { (void)port; return declined?"denied":NULL; }
static BOOL n48_is_ws(void) { return ws; }
static BOOL n48_radv_open(NSError **error) { (void)error; opens++; return backend; }
static void n48_census_log(void) { census++; }
@interface ProbeSuper : NSObject
- (instancetype)initWithAcceleratorPort:(uint32_t)port;
@end
@implementation ProbeSuper
- (instancetype)initWithAcceleratorPort:(uint32_t)port {
 (void)port; supers++; self=[super init]; return superFails?nil:self;
}
@end
@interface Navi48Device : ProbeSuper @end
@implementation Navi48Device
'''
suffix = r'''
@end
int main(void) { @autoreleasepool {
 for(ws=0;ws<=1;ws++)for(declined=0;declined<=1;declined++)
 for(backend=0;backend<=1;backend++)for(superFails=0;superFails<=1;superFails++) {
  opens=supers=census=0; n48_acc_port=0;
  id dev=[[Navi48Device alloc] initWithAcceleratorPort:123];
  BOOL expected=!superFails && !declined && (ws || backend);
  assert((dev!=nil)==expected);
  assert(supers==1);
  assert(opens==(!superFails && !declined && !ws));
  assert(census==expected);
  assert(n48_acc_port==(expected && ws?123u:0u));
 }
 puts("PASS: 16 initializer paths; no non-WS device exposed after backend refusal, superclass initialization retained, WS path unchanged. Hardware integration untested.");
} }
'''
with tempfile.TemporaryDirectory(prefix='navi44-device-reserve-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.m').write_text(prefix + initializer + suffix)
    subprocess.run(['clang', '-O1', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-framework', 'Foundation', str(tmp / 'probe.m'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
