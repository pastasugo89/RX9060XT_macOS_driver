#include <mach/mach_types.h>
#include <libkern/OSKextLib.h>
extern kern_return_t _start(kmod_info_t *, void *);
extern kern_return_t _stop(kmod_info_t *, void *);
extern kern_return_t Navi44CPPC_kern_start(kmod_info_t *, void *);
extern kern_return_t Navi44CPPC_kern_stop(kmod_info_t *, void *);
KMOD_EXPLICIT_DECL(com.navi44.cppc, "0.0.1", _start, _stop)
__private_extern__ kmod_start_func_t *_realmain = Navi44CPPC_kern_start;
__private_extern__ kmod_stop_func_t *_antimain = Navi44CPPC_kern_stop;
