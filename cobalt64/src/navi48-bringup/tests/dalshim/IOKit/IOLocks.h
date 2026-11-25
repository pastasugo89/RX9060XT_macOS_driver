//  tests/dalshim/IOKit/IOLocks.h - IOLock as a pthread mutex, with an acquisition counter the test reads.
#pragma once
#include <pthread.h>
struct IOLock { pthread_mutex_t m; };
extern int gDalShimLockCount, gDalShimLockAllocFail;
static inline IOLock *IOLockAlloc(void) { if (gDalShimLockAllocFail) return nullptr; IOLock *l = new IOLock; pthread_mutex_init(&l->m, nullptr); return l; }
static inline void IOLockFree(IOLock *l) { pthread_mutex_destroy(&l->m); delete l; }
static inline void IOLockLock(IOLock *l) { pthread_mutex_lock(&l->m); gDalShimLockCount++; }
static inline void IOLockUnlock(IOLock *l) { pthread_mutex_unlock(&l->m); }
static inline bool IOLockTryLock(IOLock *l) { if (pthread_mutex_trylock(&l->m) != 0) return false; gDalShimLockCount++; return true; }   // 0.0.685 (smu_lock_try_enter)
