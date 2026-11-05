// bundle nm272 candidate, on bundle 35: NullMoth 2.7-2.7.2 items 1, 2, 3, 4, 6 and 8 (src/n48_nm272.h, src/Navi48Device.m; RESULTS.md in the bundle directory).
// Part 1: source wiring, checked as text in Navi48Device.m and Info.plist with all whitespace removed first (so the layout of the patch does not matter):
//         each entry point exists once, the depth-bounds bit reaches the variant and the draw, the indirect dispatch prepares its textures before the GPU
//         reads the counts and refuses ThreadsDynamic kernels before recording anything, the residency selectors retain what they name, no blanket message
//         handler was added, CFBundleVersion stays 35.
// Part 2: the pure decisions in n48_nm272.h over the inputs that matter, and the depth-bounds bit against every combination of n48ds_key's inputs.
// Build/run (from tests/):  cc -O1 -Wall -Wextra -Werror -I<mesa include> -I. -o bin/test-nm272-items test-nm272-items.c && bin/test-nm272-items <dir holding Navi48Device.m and Info.plist>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "n48_nm272.h"
#include "n48_depth.h"

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
// The source with every space, tab and newline removed: needles are written without layout.
static char *squash(const char *s) {
    char *o = malloc(strlen(s) + 1); size_t k = 0;
    for (const char *p = s; *p; p++) if (*p != ' ' && *p != '\t' && *p != '\n' && *p != '\r') o[k++] = *p;
    o[k] = 0; return o;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }
static int count(const char *s, const char *needle) {
    int n = 0; size_t l = strlen(needle); if (!s || !l) return 0;
    for (const char *p = s; (p = strstr(p, needle)) != NULL; p += l) n++;
    return n;
}
static long at(const char *s, const char *needle) { const char *p = strstr(s, needle); return p ? (long)(p - s) : -1; }

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[1024];
    snprintf(path, sizeof path, "%s/Navi48Device.m", dir);
    char *raw = slurp(path);
    if (!raw) { printf("FAIL: cannot read %s\n", path); return 1; }
    char *src = squash(raw);
    snprintf(path, sizeof path, "%s/Info.plist", dir);
    char *plist = slurp(path);

    // ---- Part 1: source wiring ----
    check(count(src, "#include\"n48_nm272.h\"") == 1, "Navi48Device.m includes n48_nm272.h once");
    check(count(src, "X(vkCmdDispatchIndirect)X(vkCmdSetDepthBounds)") == 1, "the Vulkan entry points vkCmdDispatchIndirect and vkCmdSetDepthBounds are in the loader table");
    check(count(src, "BOOLdbBounds;") == 1 && count(src, "N48R.dbBounds=pf.depthBounds?YES:NO;") == 1, "the depthBounds feature is recorded on the device (N48R.dbBounds)");
    check(count(src, ".depthBiasClamp=pf.depthBiasClamp,.depthBounds=pf.depthBounds,") == 1, "the depthBounds feature is enabled at device creation");

    // item 1: requiredThreadsPerThreadgroup and the bound on maxTotalThreadsPerThreadgroup
    check(count(src, "-(MTLSize)requiredThreadsPerThreadgroup{return_reqTG;}") == 1, "item 1: the compute pipeline answers requiredThreadsPerThreadgroup");
    check(count(src, "-(NSUInteger)maxTotalThreadsPerThreadgroup{return(NSUInteger)n48nm_max_total_tg(1024,n48nm_required_product(_reqTG.width,_reqTG.height,_reqTG.depth));}") == 1,
          "item 1: maxTotalThreadsPerThreadgroup is bounded by the required size");
    check(count(src, "staticvoidn48_set_required(idpipe,iddesc){") == 1 && count(src, "[(N48ComputePipelineState*)pipen48SetRequired:s];") == 1,
          "item 1: the descriptor's required size is copied into the pipeline it creates");
    check(count(src, "[selfn48NewComputePipelineD:derror:error];}") == 2 && count(src, "[selfn48NewComputePipelineD:derror:&e];if(h)h(p,e);}") == 1
          && count(src, "[selfn48NewComputePipelineD:derror:&e];if(h)h(p,nil,e);}") == 1,
          "item 1: all four descriptor entry points go through the required-size copy");
    check(count(src, "n48NewComputePipeline:d.computeFunctionerror:error];n48_set_required(p,d)") == 1, "item 1: the copy happens after creation, from the same descriptor");

    // item 2: depth bounds
    check(count(src, "-(void)setDepthTestMinBound:(float)lomaxBound:(float)hi{") == 1, "item 2: setDepthTestMinBound:maxBound: is implemented on the render encoder");
    check(count(src, "if(!N48R.dbBounds){N48_ONCE(\"setDepthTestMinBound:maxBound:refused") == 1, "item 2: refused (logged once) when the device has no depthBounds feature");
    check(count(src, "_dbOn=YES;_dbLo=n48nm_db_lo(lo);_dbHi=n48nm_db_hi(hi);") == 1, "item 2: the range is recorded clamped to [0, 1]");
    check(count(src, "constBOOLdbOn=_dbOn&&[_pson48HasDepth];") == 1, "item 2: the test applies only to a pipeline with a depth attachment");
    check(count(src, "uint32_tdk=[_pson48DSKey:&_dsi];") == 1 && count(src, "if(dbOn)dk|=N48NM_DS_DEPTH_BOUNDS;") == 1,
          "item 2: the depth bounds bit is added to the depth/stencil key after n48DSKey (the key itself is unchanged)");
    check(count(src, "if(_dcOn&&!dbOn){") == 1, "item 2: the last-answer cache is bypassed for the depth bounds variant (its word has no bit 31)");
    check(count(src, "if(dbOn)vkCmdSetDepthBounds(cmd,_dbLo,_dbHi);") == 1, "item 2: the range is set on the command buffer before the draw");
    check(at(src, "vkCmdSetDepthBias(cmd,_bias[0],_bias[1],_bias[2]);") < at(src, "if(dbOn)vkCmdSetDepthBounds(") && at(src, "if(dbOn)vkCmdSetDepthBounds(") > 0,
          "item 2: the range is set after the depth bias, inside the depth/stencil block");
    check(count(src, "constBOOLdbt=(dk&N48NM_DS_DEPTH_BOUNDS)!=0;") == 1 && count(src, ".depthBoundsTestEnable=dbt?VK_TRUE:VK_FALSE,.minDepthBounds=0.0f,.maxDepthBounds=1.0f,") == 1,
          "item 2: the variant enables the test, with the static range [0, 1] behind the dynamic one");
    check(count(src, "if(dbt)dyn[_pc.ndyn]=VK_DYNAMIC_STATE_DEPTH_BOUNDS;") == 1 && count(src, "VkDynamicStatedyn[9];") == 1
          && count(src, ".dynamicStateCount=_pc.ndyn+(dbt?1u:0u),.pDynamicStates=dyn};") == 1,
          "item 2: DEPTH_BOUNDS is dynamic state of the variant, after the config's states (array sized for nine entries)");
    check(count(src, "BOOL_dbOn;float_dbLo,_dbHi;") == 1, "item 2: the recorded range lives in the render encoder");

    // item 3: texture views from a descriptor
    check(count(src, "-(id)newTextureViewWithDescriptor:(id)d{") == 1, "item 3: newTextureViewWithDescriptor: is implemented on the texture");
    check(count(src, "n48nm_tvd_resolve(&in,self.pixelFormat,[selfmipmapLevelCount],slices,&out);") == 1, "item 3: the zero fields are resolved against the texture (n48nm_tvd_resolve)");
    check(count(src, "return[selfnewTextureViewWithPixelFormat:(MTLPixelFormat)out.pftextureType:(MTLTextureType)out.tt") == 1, "item 3: the view goes through the existing view code");
    check(count(src, "[dvalueForKey:@\"pixelFormat\"]") == 1 && count(src, "[dvalueForKey:@\"swizzle\"]") == 1, "item 3: the descriptor is read by key (no macOS 26 SDK type in the build)");

    // item 4: colour attachment map (accepted and ignored on a Metal 3 encoder)
    long re = at(src, "@implementationN48RenderEncoder"), ce = at(src, "@implementationN48ComputeEncoder"), cm = at(src, "-(void)setColorAttachmentMap:(id)map{");
    check(count(src, "-(void)setColorAttachmentMap:(id)map{if(map)N48_ONCE(") == 1 && re > 0 && cm > re && cm < ce,
          "item 4: setColorAttachmentMap: is accepted by the render encoder (logged once, no failure)");

    // item 6: useResource / useHeap / residency sets
    char *macro = NULL;
    { const char *m0 = strstr(src, "#defineN48_ENCODER_NOOPS"); if (m0) { const char *m1 = strstr(m0, "-(void)useResourceGroup:"); size_t n = m1 ? (size_t)(m1 - m0) : 0;
      macro = malloc(n + 1); if (macro) { memcpy(macro, m0, n); macro[n] = 0; } } }
    check(macro && count(macro, "useResource") == 0 && count(macro, "useHeap") == 0,
          "item 6: useResource: and useHeap: are no longer no-ops in the shared encoder macro");
    check(count(src, "#defineN48_ENCODER_USE(DECL)") == 1 && count(src, "N48_ENCODER_USE(nil)") == 2 && count(src, "N48_ENCODER_USE(self->_decl)") == 1,
          "item 6: the three encoders use the retaining implementation (compute keeps its declared textures)");
    check(count(src, "n48_use_one(self->_cb,(DECL),r,u,NO);") == 2 && count(src, "n48_use_one(self->_cb,nil,h,0,YES);") == 2
          && count(src, "n48_use_many(self->_cb,(DECL),r,n,u,NO);") == 2 && count(src, "n48_use_many(self->_cb,nil,h,n,0,YES);") == 2,
          "item 6: every useResource:/useHeap: variant (single, array, with stages) goes through the helper");
    check(count(src, "[cbn48Retain:r];") == 2 && count(src, "[cbn48Retain:m];") == 1 && count(src, "for(idmin[(N48Heap*)rn48LiveMembers])") == 1,
          "item 6: the helper retains the resource, or the heap and each live member, in the command buffer");
    check(count(src, "[hn48Track:self];") == 2 && count(src, "-(void)n48Track:(id)m{@synchronized(self){if(!_mem)_mem=[NSHashTableweakObjectsHashTable];[_memaddObject:m];}}") == 1
          && count(src, "-(NSArray*)n48LiveMembers{@synchronized(self){return_mem?[_memallObjects]:@[];}}") == 1,
          "item 6: a heap's members are tracked (weakly) when they are placed in it");
    check(count(src, "-(void)useResidencySet:(id)s{[selfn48Retain:s];}") == 1 && count(src, "-(void)useResidencySets:(constid__unsafe_unretained*)scount:(NSUInteger)n{") == 1,
          "item 6: a command buffer retains the residency sets it names");
    check(count(src, "forwardInvocation:") == 0 && count(src, "resolveInstanceMethod:") == 0 && count(src, "methodSignatureForSelector:") == 0,
          "no blanket message handler (census policy: a vetted list only)");

    // item 8: indirect dispatch
    check(count(src, "-(void)dispatchThreadgroupsWithIndirectBuffer:(id)ibindirectBufferOffset:(NSUInteger)iothreadsPerThreadgroup:(MTLSize)tpt{") == 1,
          "item 8: dispatchThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerThreadgroup: is implemented on the compute encoder");
    check(count(src, "if(![ibisKindOfClass:[N48Bufferclass]]||!n48nm_indirect_ok((uint64_t)io,(uint64_t)[(N48Buffer*)iblength])){") == 1,
          "item 8: the arguments must be an N48Buffer, 4-byte aligned, with 12 bytes inside it");
    check(count(src, "if([_psomode]!=0){[_cbn48Fail:@\"indirectdispatchofaThreadsDynamickernelisnotsupported") == 1,
          "item 8: a ThreadsDynamic kernel is refused by name (its grid is needed on the CPU)");
    check(count(src, "vkCmdDispatchIndirect(cmd,[(N48Buffer*)ibvkBuffer],(VkDeviceSize)io);") == 1, "item 8: the GPU reads the group counts (vkCmdDispatchIndirect)");
    check(count(src, "[_declenumerateKeysAndObjectsUsingBlock:") == 1 && count(src, "decl[[NSValuevalueWithNonretainedObject:r]]=@[r,@(usage)];") == 1,
          "item 8: useResource: textures are recorded with their usage (latest usage wins)");
    check(at(src, "[_declenumerateKeysAndObjectsUsingBlock:") > 0 && at(src, "[_declenumerateKeysAndObjectsUsingBlock:") < at(src, "vkCmdDispatchIndirect(cmd,"),
          "item 8: the declared textures are prepared before the indirect dispatch");
    check(at(src, "if([_psomode]!=0){[_cbn48Fail:@\"indirectdispatchofaThreadsDynamic") < at(src, "vkCmdDispatchIndirect(cmd,"),
          "item 8: the refusal comes before any command is recorded");

    // the bundle's identity
    check(plist && count(squash(plist), "<key>CFBundleVersion</key><string>35</string>") == 1, "Info.plist keeps CFBundleVersion 35");

    // ---- Part 2: the pure decisions ----
    check(n48nm_required_product(0, 1, 1) == 0 && n48nm_required_product(64, 0, 1) == 0 && n48nm_required_product(64, 1, 1) == 64
          && n48nm_required_product(16, 16, 4) == 1024, "item 1: the required product (zero when a count is zero)");
    check(n48nm_required_product(UINT64_MAX, 2, 1) == UINT64_MAX && n48nm_required_product(1ull << 32, 1ull << 32, 1ull << 32) == UINT64_MAX,
          "item 1: the required product saturates instead of wrapping");
    check(n48nm_max_total_tg(1024, 0) == 1024 && n48nm_max_total_tg(1024, 64) == 64 && n48nm_max_total_tg(1024, 2048) == 1024 && n48nm_max_total_tg(1024, 1024) == 1024,
          "item 1: maxTotalThreadsPerThreadgroup is the required size when it is smaller, else the device bound");
    check(n48nm_db_lo(-1.0f) == 0.0f && n48nm_db_lo(0.25f) == 0.25f && n48nm_db_lo(2.0f) == 1.0f && n48nm_db_lo(NAN) == 0.0f,
          "item 2: the depth bounds minimum is clamped to [0, 1] (NaN gives 0)");
    check(n48nm_db_hi(2.0f) == 1.0f && n48nm_db_hi(0.75f) == 0.75f && n48nm_db_hi(-1.0f) == 0.0f && n48nm_db_hi(NAN) == 1.0f,
          "item 2: the depth bounds maximum is clamped to [0, 1] (NaN gives 1)");
    { n48nm_tvd_t in, out; memset(&in, 0, sizeof in); n48nm_tvd_resolve(&in, 80, 1, 1, &out);
      check(out.pf == 80 && out.lvLoc == 0 && out.lvLen == 1 && out.slLoc == 0 && out.slLen == 1 && out.sw[0] == 2 && out.sw[1] == 3 && out.sw[2] == 4 && out.sw[3] == 5,
            "item 3: an all-zero descriptor resolves to the texture's own format, full ranges and identity swizzle");
      memset(&in, 0, sizeof in); in.pf = 53; in.tt = 2; in.lvLoc = 2; in.lvLen = 3; in.slLoc = 1; in.slLen = 2; in.sw[0] = 5; in.sw[1] = 5; in.sw[2] = 5; in.sw[3] = 5;
      n48nm_tvd_resolve(&in, 80, 9, 9, &out);
      check(out.pf == 53 && out.lvLoc == 2 && out.lvLen == 3 && out.slLoc == 1 && out.slLen == 2 && out.sw[0] == 5, "item 3: explicit fields are kept as given"); }
    check(n48nm_indirect_ok(0, 12) && n48nm_indirect_ok(4, 16) && !n48nm_indirect_ok(2, 16) && !n48nm_indirect_ok(8, 16) && !n48nm_indirect_ok(16, 12) && !n48nm_indirect_ok(0, 11),
          "item 8: indirect arguments: 4-byte aligned and 12 bytes inside the buffer");
    check(N48NM_DS_DEPTH_BOUNDS == 0x80000000u, "item 2: the depth bounds bit is bit 31");
    { int clash = 0; long combos = 0;
      for (int hd = 0; hd < 2; hd++) for (int hs = 0; hs < 2; hs++) for (unsigned cmp = 0; cmp < 8; cmp++) for (int dw = 0; dw < 2; dw++)
      for (unsigned a = 0; a < 8; a++) for (unsigned b = 0; b < 8; b++) { n48ds_face_in_t f = { a, b, a, b }, bk = { b, a, b, a };
          uint32_t k = n48ds_key(hd, hs, cmp, dw, &f, &bk); combos++; if (k & N48NM_DS_DEPTH_BOUNDS) clash++; }
      check(clash == 0 && combos > 0, "item 2: n48ds_key never sets the depth bounds bit (checked over its inputs)"); }

    printf("test-nm272-items: %d checks, %d failed\n", checks, fails);
    free(raw); free(src); free(plist); free(macro);
    return fails ? 1 : 0;
}
