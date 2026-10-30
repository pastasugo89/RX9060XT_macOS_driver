#!/usr/bin/env python3
"""Exercise actual compute creation paths with an injected shader failure.

The pipeline test extracts its compilation/cleanup block; shader-object tests
extract complete functions. Vulkan/GPU and compiler dependencies are stubbed.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
mesa = root / 'research/ext/mesa-darwin/src/amd/vulkan'
pipeline = (mesa / 'radv_pipeline_compute.c').read_text()
objects = (mesa / 'radv_shader_object.c').read_text()


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    end, depth = opening + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


start = pipeline.index('   struct radv_shader_debug_info cs_dbg = {0};')
end = pipeline.index('\ndone:', start)
block = pipeline[start:end]
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int VkResult;
#define VK_SUCCESS 0
#define VK_ERROR_OUT_OF_DEVICE_MEMORY -2
#define VK_ERROR_INCOMPATIBLE_SHADER_BINARY_EXT -3
#define MESA_SHADER_COMPUTE 5
#define BLAKE3_KEY_LEN 32
static int failing, live, cached, dumped, finished;
static void *tracked_malloc(size_t n) { void *p=malloc(n); assert(p); live++; return p; }
static void tracked_free(void *p) { if(p) { assert(live>0); live--; free(p); } }
#define malloc tracked_malloc
#define free tracked_free
struct radv_compiler_info { int unused; };
struct radv_device { struct radv_compiler_info compiler_info; };
struct radv_shader { int unused; };
struct radv_shader_binary { uint32_t total_size; };
struct radv_shader_stage { void *nir; struct { int64_t duration; } feedback; };
struct radv_shader_debug_info { int unused; };
struct vk_pipeline_cache { int unused; };
struct radv_pipeline_base { bool is_internal; struct radv_shader *shaders[8]; };
struct radv_pipeline { struct radv_pipeline_base base; };
struct radv_shader_object { struct radv_shader *shader; struct radv_shader_binary *binary; };
typedef struct { int unused; } VkShaderCreateInfoEXT;
struct blob_reader { const unsigned char *data; size_t size, offset; };
static const void *blob_read_bytes(struct blob_reader *b,size_t n) {
 assert(n<=b->size-b->offset); const void *p=b->data+b->offset; b->offset+=n; return p;
}
static uint32_t blob_read_uint32(struct blob_reader *b) { uint32_t out; memcpy(&out,blob_read_bytes(b,sizeof out),sizeof out); return out; }
static void _mesa_blake3_compute(const void *data,size_t n,void *out) { (void)data; (void)n; memset(out,0,32); }
static void radv_shader_stage_init(const VkShaderCreateInfoEXT *c,struct radv_shader_stage *s) { (void)c; s->nir=malloc(8); }
static void ralloc_free(void *p) { free(p); }
static struct radv_shader_binary *radv_compile_cs(const struct radv_compiler_info *c,struct radv_shader_stage *s,bool internal,struct radv_shader_debug_info *dbg) {
 (void)c; (void)s; (void)internal; (void)dbg; struct radv_shader_binary *b=malloc(sizeof *b); b->total_size=sizeof *b; return b;
}
static struct radv_shader *radv_shader_create(struct radv_device *d,struct vk_pipeline_cache *cache,const struct radv_shader_binary *bin,bool skip,struct radv_shader_debug_info *dbg) {
 (void)d; (void)cache; (void)bin; (void)skip; (void)dbg; return failing?NULL:malloc(sizeof(struct radv_shader));
}
static int64_t os_time_get_nano(void) { return 100; }
static void radv_pipeline_cache_insert(struct radv_device *d,struct vk_pipeline_cache *c,struct radv_pipeline_base *p) {
 (void)d; (void)c; assert(p->shaders[MESA_SHADER_COMPUTE]); cached++;
}
static bool radv_can_dump_shader_stats(const struct radv_compiler_info *c,void *nir) { (void)c; assert(nir); return true; }
static void radv_dump_shader_stats(struct radv_device *d,struct radv_pipeline_base *p,struct radv_shader *s,FILE *out) { (void)d; (void)p; (void)out; assert(s); dumped++; }
static void radv_pipeline_stage_finish(struct radv_shader_stage *s) { ralloc_free(s->nir); s->nir=NULL; finished++; }
static VkResult pipeline_block(struct radv_device *device,struct radv_pipeline *pipeline,bool skip_shaders_cache) {
 VkResult result=VK_SUCCESS;
 struct vk_pipeline_cache *cache=NULL;
 const struct radv_compiler_info *compiler_info=&device->compiler_info;
 struct radv_shader_stage cs_stage={0};
 VkShaderCreateInfoEXT ci={0}; radv_shader_stage_init(&ci,&cs_stage);
 int64_t stage_start=0;
'''
between = r'''
 return result;
}
'''
suffix = r'''
int main(void) {
 struct radv_device device={0};
 for(failing=0;failing<=1;failing++) {
  for(int skip=0;skip<=1;skip++) {
   struct radv_pipeline pipeline={0}; cached=dumped=finished=0;
   VkResult r=pipeline_block(&device,&pipeline,skip);
   assert(r==(failing?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS));
   assert(cached==(!failing && !skip) && dumped==!failing && finished==1);
   free(pipeline.base.shaders[MESA_SHADER_COMPUTE]); assert(live==0);
  }
  struct radv_shader_object object={0}; VkShaderCreateInfoEXT ci={0};
  VkResult r=radv_shader_object_init_compute(&object,&device,&ci);
  assert(r==(failing?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS));
  free(object.shader); free(object.binary); assert(live==0);
  unsigned char bytes[32+4+sizeof(struct radv_shader_binary)]={0};
  uint32_t size=sizeof(struct radv_shader_binary); memcpy(bytes+32,&size,4);
  struct radv_shader_binary binary={.total_size=sizeof binary}; memcpy(bytes+36,&binary,sizeof binary);
  struct blob_reader blob={bytes,sizeof bytes,0};
  struct radv_shader *shader=NULL; struct radv_shader_binary *binary_out=NULL;
  r=radv_shader_object_init_binary(&device,&blob,&shader,&binary_out);
  assert(r==(failing?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS));
  assert((const void *)binary_out==(const void *)(bytes+36));
  free(shader); assert(live==0);
 }
 puts("PASS: compute pipeline cleanup/cache insertion and compute/binary shader objects propagate shader failures; eight controlled paths, no tracked leaks or NULL stats dumps. Full Vulkan integration untested.");
}
'''

source = prefix + block + between
source += function(objects, 'static VkResult\nradv_shader_object_init_compute(')
source += function(objects, 'static VkResult\nradv_shader_object_init_binary(')
source += suffix
with tempfile.TemporaryDirectory(prefix='navi44-radv-compute-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.c').write_text(source)
    subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', str(tmp / 'probe.c'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
