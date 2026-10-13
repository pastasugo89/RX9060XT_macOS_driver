// Host-test stand-in for <IOKit/IOLib.h>: only what the freestanding kext modules under test call.
#pragma once
#include <cstdio>
#include <cstring>   // before the kext's own extern "C" memcpy declaration (amdgpu_regs.h)
#include <cstdarg>
#include <cstdint>
static inline void IOLog(const char *fmt, ...) { va_list a; va_start(a, fmt); std::vprintf(fmt, a); va_end(a); }
static inline void IOSleep(unsigned) {}
static inline void IODelay(unsigned) {}
