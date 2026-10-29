// Host-test stand-in for <IOKit/IOReturn.h>: the return type and the codes the kext modules under test use.
#pragma once
#include <cstdint>
typedef int kern_return_t;
typedef kern_return_t IOReturn;
#define KERN_SUCCESS            0
#define kIOReturnSuccess        0
#define kIOReturnError          ((IOReturn)0xe00002bc)
#define kIOReturnNoMemory       ((IOReturn)0xe00002bd)
#define kIOReturnBadArgument    ((IOReturn)0xe00002c2)
#define kIOReturnExclusiveAccess ((IOReturn)0xe00002c5)
#define kIOReturnNotReady       ((IOReturn)0xe00002d8)
#define kIOReturnTimeout        ((IOReturn)0xe00002d6)
#define kIOReturnUnsupported    ((IOReturn)0xe00002c7)
#define kIOReturnNotFound       ((IOReturn)0xe00002f0)
#define kIOReturnIOError        ((IOReturn)0xe00002ca)
#define kIOReturnNoResources    ((IOReturn)0xe00002be)
#define kIOReturnNotPermitted   ((IOReturn)0xe00002e2)
#define kIOReturnBusy           ((IOReturn)0xe00002d5)
#define kIOReturnAborted        ((IOReturn)0xe00002eb)
#define kIOReturnInternalError  ((IOReturn)0xe00002cc)
#define kIOReturnInvalid        ((IOReturn)0xe0000001)
#define kIOReturnOverrun        ((IOReturn)0xe00002e8)
#define kIOReturnNoDevice       ((IOReturn)0xe00002c0)
#define kIOReturnNotAttached    ((IOReturn)0xe00002d9)
#define kIOReturnUnderrun       ((IOReturn)0xe00002e7)
