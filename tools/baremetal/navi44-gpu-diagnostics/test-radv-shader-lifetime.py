#!/usr/bin/env python3
"""Inject failures into the real RADV shader factory, upload and destructor.

Hardware allocation, DMA, RTLD and Vulkan cache bookkeeping are controlled
stubs. The extracted production functions must balance ownership at every exit.
This does not execute GPU commands or qualify a complete Vulkan pipeline.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
mesa = root / 'research/ext/mesa-darwin/src/amd/vulkan'
shader = (mesa / 'radv_shader.c').read_text()
cache = (mesa / 'radv_pipeline_cache.c').read_text()


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int VkResult;
#define VK_SUCCESS 0
#define VK_ERROR_OUT_OF_HOST_MEMORY -1
#define VK_ERROR_OUT_OF_DEVICE_MEMORY -2
#define VK_ERROR_INITIALIZATION_FAILED -3
#define VK_ERROR_INVALID_OPAQUE_CAPTURE_ADDRESS -4
#define RADV_BINARY_TYPE_LEGACY 0
#define RADV_BINARY_TYPE_RTLD 1
#define mtx_plain 0
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
enum Failure { OK, OBJECT, ARENA, CODE, DMA_GET, DMA_SUBMIT, RTLD_FIRST, RTLD_SECOND, RTLD_UPLOAD, REPLAY };
static enum Failure failure;
static unsigned live, mutexes, objects, dma_owned, rtld_owned, rtld_calls, calloc_calls;
static void *tracked_malloc(size_t n) { void *p=malloc(n); assert(p); ++live; return p; }
static void tracked_free(void *p) { if(p) { assert(live); --live; free(p); } }
static void *tracked_calloc(size_t n, size_t size) {
 ++calloc_calls;
 if((failure==OBJECT && calloc_calls==1) || (failure==CODE && calloc_calls==2))return NULL;
 void *p=tracked_malloc(n*size); memset(p,0,n*size); return p;
}
#define malloc tracked_malloc
#define calloc tracked_calloc
#define free tracked_free
struct radv_shader_debug_info {
 bool dump_shader; uint32_t stages;
 char *spirv; uint32_t spirv_size;
 char *nir_string, *disasm_string, *ir_string, *args_string;
 void *statistics, *debug_info; uint32_t debug_info_count;
};
struct vk_device { int unused; };
struct vk_pipeline_cache_object { int initialized; };
struct radeon_winsys_bo { int unused; };
struct arena { struct radeon_winsys_bo *bo; void *ptr; };
union radv_shader_arena_block { struct { struct arena *arena; size_t offset; }; };
struct radv_shader {
 struct vk_pipeline_cache_object base; int replay_mtx; bool has_replay_alloc;
 struct radeon_winsys_bo *bo; union radv_shader_arena_block *alloc; uint64_t va, upload_seq;
 int info, config; unsigned max_waves, code_size, exec_size; unsigned char hash[32];
 void *code; struct radv_shader_debug_info dbg;
};
struct radv_shader_binary { int type; unsigned total_size; int info, config; };
struct radv_shader_binary_legacy { struct radv_shader_binary base; unsigned code_size, exec_size; unsigned char data[16]; };
struct radv_serialized_shader_arena_block { int unused; };
struct radv_device { struct vk_device vk; bool shader_use_invisible_vram; };
struct radv_physical_device { struct { int gfx_level; } info; };
struct radv_shader_binary_layout { void *code; };
struct radv_shader_dma_submission { void *ptr; };
struct ac_rtld_binary { unsigned rx_size, exec_size; };
struct ac_rtld_upload_info { struct ac_rtld_binary *binary; uint64_t rx_va; void *rx_ptr; };
static const int radv_shader_ops=0;
static const struct radv_physical_device pdev={0};
static void simple_mtx_init(int *m,int kind) { (void)kind; *m=1; ++mutexes; }
static void simple_mtx_destroy(int *m) { assert(*m==1 && mutexes); *m=0; --mutexes; }
static void vk_pipeline_cache_object_init(struct vk_device *d,struct vk_pipeline_cache_object *o,const int *ops,const void *key,size_t n) {
 (void)d; (void)ops; (void)key; (void)n; o->initialized=1; ++objects;
}
static void vk_pipeline_cache_object_finish(struct vk_pipeline_cache_object *o) { assert(o->initialized && objects); --objects; }
static void _mesa_blake3_compute(const void *data,size_t size,void *hash) { (void)data; (void)size; memset(hash,1,32); }
static unsigned radv_get_max_waves(struct radv_device *d,const int *config,const int *info) { (void)d; (void)config; (void)info; return 1; }
#ifdef USE_LIBELF
static const struct radv_physical_device *radv_device_physical(struct radv_device *d) { (void)d; return &pdev; }
static uint64_t radv_shader_get_va(struct radv_shader *s) { return s->va; }
static void util_streaming_load_memcpy(void *dst,const void *src,size_t size) { memcpy(dst,src,size); }
static bool radv_open_rtld_binary(int level,const struct radv_shader_binary *bin,struct ac_rtld_binary *out) {
 (void)level; (void)bin; ++rtld_calls;
 if((failure==RTLD_FIRST && rtld_calls==1) || (failure==RTLD_SECOND && rtld_calls==2))return false;
 out->rx_size=out->exec_size=16; ++rtld_owned; return true;
}
static void ac_rtld_close(struct ac_rtld_binary *b) { (void)b; assert(rtld_owned); --rtld_owned; }
static bool ac_rtld_upload(struct ac_rtld_upload_info *i) {
 if(failure==RTLD_UPLOAD)return false; memset(i->rx_ptr,0x42,16); return true;
}
#endif
static struct radv_shader_binary_layout radv_shader_binary_get_layout(struct radv_shader_binary_legacy *b) {
 return (struct radv_shader_binary_layout){b->data};
}
static union radv_shader_arena_block *radv_alloc_shader_memory(struct radv_device *d,unsigned size,bool replayable,struct radv_shader *s) {
 (void)d; (void)replayable; (void)s; if(failure==ARENA)return NULL;
 union radv_shader_arena_block *a=malloc(sizeof *a); a->offset=0;
 a->arena=malloc(sizeof *a->arena); a->arena->bo=malloc(sizeof *a->arena->bo);
 a->arena->ptr=malloc(size); return a;
}
static union radv_shader_arena_block *radv_replay_shader_arena_block(struct radv_device *d,struct radv_serialized_shader_arena_block *b,struct radv_shader *s) {
 (void)b; if(failure==REPLAY)return NULL; return radv_alloc_shader_memory(d,16,true,s);
}
static void radv_free_shader_memory(struct radv_device *d,union radv_shader_arena_block *a) {
 (void)d; if(!a)return; free(a->arena->ptr); free(a->arena->bo); free(a->arena); free(a);
}
static uint64_t radv_buffer_get_va(struct radeon_winsys_bo *bo) { (void)bo; return 4096; }
static unsigned char dma_buffer[16];
static struct radv_shader_dma_submission submission={dma_buffer};
static struct radv_shader_dma_submission *radv_shader_dma_get_submission(struct radv_device *d,struct radeon_winsys_bo *b,uint64_t va,unsigned size) {
 (void)d; (void)b; (void)va; (void)size; if(failure==DMA_GET)return NULL; assert(!dma_owned); dma_owned=1; return &submission;
}
static void radv_shader_dma_push_submission(struct radv_device *d,struct radv_shader_dma_submission *s,uint64_t seq) {
 (void)d; (void)s; (void)seq; assert(dma_owned==1); dma_owned=0;
}
static bool radv_shader_dma_submit(struct radv_device *d,struct radv_shader_dma_submission *s,uint64_t *seq) {
 radv_shader_dma_push_submission(d,s,0); if(failure==DMA_SUBMIT)return false; *seq=1; return true;
}
static void radv_shader_wait_for_upload(struct radv_device *d,uint64_t seq) { (void)d; (void)seq; assert(!dma_owned); }
static void radv_precompute_registers(struct radv_device *d,struct radv_shader *s) {
 (void)d; assert(s->code && s->code_size==16); for(unsigned i=0;i<16;i++)assert(((unsigned char *)s->code)[i]==0x42);
}
static void radv_shader_unref(struct radv_device *d,struct radv_shader *s);
'''

suffix = r'''
static void radv_shader_unref(struct radv_device *d,struct radv_shader *s) { radv_shader_destroy(&d->vk,&s->base); }
static void init_debug(struct radv_shader_debug_info *d) {
 *d=(struct radv_shader_debug_info){0};
 d->spirv=malloc(8); d->nir_string=malloc(8); d->disasm_string=malloc(8);
 d->ir_string=malloc(8); d->args_string=malloc(8);
 d->statistics=malloc(8); d->debug_info=malloc(8);
}
int main(void) {
 unsigned tested=0;
 for(unsigned invisible=0;invisible<2;invisible++)for(int type=0;type<2;type++)for(failure=OK;failure<=REPLAY;failure++) {
  if((failure==DMA_GET || failure==DMA_SUBMIT) && !invisible)continue;
  if((failure==RTLD_FIRST || failure==RTLD_SECOND || failure==RTLD_UPLOAD) && type!=RADV_BINARY_TYPE_RTLD)continue;
#ifndef USE_LIBELF
  if(type==RADV_BINARY_TYPE_RTLD && failure!=OK && failure!=OBJECT)continue;
#endif
  struct radv_device device={.shader_use_invisible_vram=invisible};
  struct radv_shader_binary_legacy binary={.base={.type=type,.total_size=sizeof binary},.code_size=16,.exec_size=16};
  memset(binary.data,0x42,sizeof binary.data);
  struct radv_shader_debug_info debug; init_debug(&debug);
  struct radv_serialized_shader_arena_block replay={0};
  struct radv_shader *out=(void *)(uintptr_t)1;
  calloc_calls=rtld_calls=0;
  VkResult result=radv_shader_create_uncached(&device,&binary.base,false,failure==REPLAY?&replay:NULL,&debug,&out);
  struct radv_shader_debug_info zero={0}; assert(!memcmp(&debug,&zero,sizeof zero));
  bool success=failure==OK;
#ifndef USE_LIBELF
  if(type==RADV_BINARY_TYPE_RTLD)success=false;
#endif
  assert((result==VK_SUCCESS)==success);
  if(success) { assert(out && out->dbg.spirv); radv_shader_unref(&device,out); }
  else assert(out==NULL);
  assert(live==0 && mutexes==0 && objects==0 && dma_owned==0 && rtld_owned==0);
  ++tested;
 }
 printf("PASS: %u actual shader factory/upload/destructor paths; object, arena, code, DMA, RTLD and replay failures leave no tracked allocations, mutexes or cache objects. Hardware integration untested.\n",tested);
}
'''

parts = [prefix,
         function(shader, 'void\nradv_shader_debug_info_finish('),
         function(cache, 'static void\nradv_shader_destroy('),
         function(shader, 'static bool\nradv_shader_binary_upload('),
         function(shader, 'static bool\nradv_shader_upload('),
         function(shader, 'VkResult\nradv_shader_create_uncached('),
         suffix]

with tempfile.TemporaryDirectory(prefix='navi44-radv-lifetime-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.c').write_text('\n'.join(parts))
    for elf in (False, True):
        command = ['clang', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                   '-Wno-unused-const-variable', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        if elf:
            command.append('-DUSE_LIBELF=1')
        subprocess.run(command + [str(tmp / 'probe.c'), '-o', str(tmp / 'probe')], check=True)
        subprocess.run([str(tmp / 'probe')], check=True)
