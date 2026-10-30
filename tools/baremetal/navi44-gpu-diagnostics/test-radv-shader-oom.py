#!/usr/bin/env python3
"""Fault-inject the actual RADV graphics shader factory, without a GPU.

This tests the factory's error propagation. Full Vulkan pipeline teardown and
hardware memory-pressure behavior require separate integration tests.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[3]
shader_source = (root / 'research/ext/mesa-darwin/src/amd/vulkan/radv_shader.c').read_text()
debug_start = shader_source.index('void\nradv_shader_debug_info_finish(')
debug_end = shader_source.index('\n}\n', debug_start) + 3
debug_finish = shader_source[debug_start:debug_end]
source = (root / 'research/ext/mesa-darwin/src/amd/vulkan/radv_pipeline_graphics.c').read_text()
start = source.index('VkResult\nradv_graphics_shaders_create(')
opening = source.index('{', start)
depth = 1
end = opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
factory = source[start:end]
prefix = r'''
#include <stdbool.h>
#include <stdlib.h>
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
typedef int VkResult;
#define VK_SUCCESS 0
#define VK_ERROR_OUT_OF_DEVICE_MEMORY -2
#define MESA_VULKAN_SHADER_STAGES 8
struct radv_device { int unused; };
struct vk_pipeline_cache { int unused; };
struct radv_shader_debug_info {
 bool dump_shader; uint32_t stages;
 char *spirv; uint32_t spirv_size;
 char *nir_string, *disasm_string, *ir_string, *args_string;
 void *statistics, *debug_info; uint32_t debug_info_count;
};
struct radv_shader { int id; struct radv_shader_debug_info dbg; };
struct radv_shader_binary { int id; };
static unsigned live;
static void *tracked_malloc(size_t size) { void *p=malloc(size); assert(p); live++; return p; }
static void tracked_free(void *p) { if(p) { assert(live); live--; free(p); } }
#define malloc tracked_malloc
#define free tracked_free
void radv_shader_debug_info_finish(struct radv_shader_debug_info *);
static int failing;
static struct radv_shader *radv_shader_create(struct radv_device *device,
 struct vk_pipeline_cache *cache, struct radv_shader_binary *binary,
 bool skip, struct radv_shader_debug_info *debug) {
 (void)device; (void)cache;
 if(binary->id == failing) { radv_shader_debug_info_finish(debug); return NULL; }
 struct radv_shader *shader=malloc(sizeof *shader);
 assert(shader); shader->id=binary->id; memset(&shader->dbg,0,sizeof shader->dbg);
 if(skip) { shader->dbg=*debug; memset(debug,0,sizeof *debug); }
 else radv_shader_debug_info_finish(debug);
 return shader;
}
'''
suffix = r'''
static void init_debug(struct radv_shader_debug_info *d) {
 *d=(struct radv_shader_debug_info){0};
 d->spirv=malloc(8); d->nir_string=malloc(8); d->disasm_string=malloc(8);
 d->ir_string=malloc(8); d->args_string=malloc(8);
 d->statistics=malloc(8); d->debug_info=malloc(8);
}
int main(void) {
 struct radv_shader_binary storage[9];
 struct radv_shader_debug_info debug[8]={{0}}, gsdebug={0};
 for(int i=0;i<9;i++)storage[i].id=i;
 for(int uncached=0;uncached<2;uncached++)for(failing=-1;failing<9;failing++) {
  for(int i=0;i<8;i++)init_debug(&debug[i]);
  init_debug(&gsdebug);
  struct radv_shader *shaders[8]={0}, *copy=NULL;
  struct radv_shader_binary *binaries[8];
  for(int i=0;i<8;i++)binaries[i]=&storage[i];
  VkResult r=radv_graphics_shaders_create(NULL,NULL,uncached,shaders,binaries,debug,
     &copy,&storage[8],&gsdebug);
  assert(r==(failing<0?VK_SUCCESS:VK_ERROR_OUT_OF_DEVICE_MEMORY));
  if(r==VK_SUCCESS) {
   for(int i=0;i<8;i++)assert(shaders[i] && shaders[i]->id==i);
   assert(copy && copy->id==8);
  }
  for(int i=0;i<8;i++)if(shaders[i]) { radv_shader_debug_info_finish(&shaders[i]->dbg); free(shaders[i]); }
  if(copy) { radv_shader_debug_info_finish(&copy->dbg); free(copy); }
  assert(live==0);
 }
 struct radv_shader *empty[8]={0}, *copy=NULL;
 struct radv_shader_binary *none[8]={0};
 assert(radv_graphics_shaders_create(NULL,NULL,false,empty,none,debug,&copy,NULL,&gsdebug)==VK_SUCCESS);
 puts("PASS: actual RADV factory propagates failures for all eight stages and GS copy, cleans all debug allocations with cached/uncached ownership, and preserves successful/empty paths. GPU pipeline integration untested.");
}
'''
with tempfile.TemporaryDirectory(prefix='navi44-radv-oom-') as directory:
    tmp = Path(directory)
    (tmp / 'probe.c').write_text(prefix + debug_finish + factory + suffix)
    subprocess.run(['clang', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', str(tmp / 'probe.c'), '-o', str(tmp / 'probe')], check=True)
    subprocess.run([str(tmp / 'probe')], check=True)
