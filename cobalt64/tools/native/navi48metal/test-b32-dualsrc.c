// bundle 32: dual-source blending (Metal Source1* blend factors -> Vulkan SRC1_*, second fragment output = SPIR-V Index 1 on Location 0).
// Part 1: source wiring, checked as text in Navi48Device.m, n48_spvrefl.h and Info.plist (the Objective-C file needs Vulkan and Metal to link).
// Part 2: reflection of hand-made SPIR-V fragment modules through the real n48s_parse / n48s_reflect: Location 0 Index 0 + Location 0 Index 1
//         is ONE attachment (not two), Index 1 on another Location is refused, an Index above 1 is refused, plain outputs are unchanged.
// Build/run:  cc -O1 -Wall -Wextra -Werror -I<mesa include> -I. -o bin/test-b32-dualsrc test-b32-dualsrc.c && bin/test-b32-dualsrc <dir holding Navi48Device.m, n48_spvrefl.h, Info.plist>
//             (<mesa include> = research/ext/mesa-darwin/include, the Vulkan headers n48_spvrefl.h includes)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "n48_spvrefl.h"

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1); if (!b) { fclose(f); return NULL; }
    size_t got = fread(b, 1, (size_t)n, f); b[got] = 0; fclose(f); return b;
}
static int fails = 0, checks = 0;
static void check(int ok, const char *what) { checks++; if (!ok) { fails++; printf("FAIL: %s\n", what); } else printf("ok  : %s\n", what); }
static const char *at(const char *s, const char *needle) { return s ? strstr(s, needle) : NULL; }
static int count(const char *s, const char *needle) {
    int n = 0; size_t l = strlen(needle); if (!s) return 0;
    for (const char *p = s; (p = strstr(p, needle)) != NULL; p += l) n++;
    return n;
}

/* ------------------------------------------------------------------------------------ hand-made SPIR-V (fragment shader) */
typedef struct { uint32_t w[512]; size_t n; } Body;
static void body_op(Body *b, uint16_t opcode, size_t nops, const uint32_t *ops) {
    b->w[b->n++] = ((uint32_t)(nops + 1) << 16) | opcode;
    for (size_t k = 0; k < nops; k++) b->w[b->n++] = ops[k];
}
typedef struct { int64_t loc; int64_t index; } Out;   /* index -1 = no Index decoration; a value is written as given (0xffffffff allowed) */

/* A minimal fragment module: one Output variable per entry of outs, all of type vec4, then an empty main. */
static size_t build_frag(uint32_t *out, size_t cap, const Out *outs, size_t nouts) {
    Body b; memset(&b, 0, sizeof b);
    const uint32_t main_id = 1, void_t = 2, fn_t = 3, float_t = 4, vec4_t = 5, ptr_out = 6, label = 7, var0 = 8;
    const uint32_t bound = var0 + (uint32_t)nouts;
    uint32_t cap1[1] = { 1 }; body_op(&b, 17, 1, cap1);                     /* OpCapability Shader */
    uint32_t mm[2] = { 0, 1 }; body_op(&b, 14, 2, mm);                      /* OpMemoryModel Logical GLSL450 */
    uint32_t ep[64]; size_t ne = 0;
    ep[ne++] = 4; ep[ne++] = main_id; ep[ne++] = 0x6e69616du; ep[ne++] = 0; /* Fragment %main "main" */
    for (size_t k = 0; k < nouts; k++) ep[ne++] = var0 + (uint32_t)k;      /* interface: the outputs */
    body_op(&b, 15, ne, ep);                                               /* OpEntryPoint */
    uint32_t em[2] = { main_id, 7 }; body_op(&b, 16, 2, em);               /* OpExecutionMode OriginUpperLeft */
    for (size_t k = 0; k < nouts; k++) {
        uint32_t d1[3] = { var0 + (uint32_t)k, 30, (uint32_t)outs[k].loc };          /* Location */
        body_op(&b, 71, 3, d1);
        if (outs[k].index >= 0) {
            uint32_t d2[3] = { var0 + (uint32_t)k, 32, (uint32_t)outs[k].index };    /* Index */
            body_op(&b, 71, 3, d2);
        }
    }
    uint32_t tv[1] = { void_t }; body_op(&b, 19, 1, tv);                  /* OpTypeVoid */
    uint32_t tf[2] = { fn_t, void_t }; body_op(&b, 33, 2, tf);            /* OpTypeFunction %void */
    uint32_t tfl[2] = { float_t, 32 }; body_op(&b, 22, 2, tfl);           /* OpTypeFloat 32 */
    uint32_t tvec[3] = { vec4_t, float_t, 4 }; body_op(&b, 23, 3, tvec);  /* OpTypeVector %float 4 */
    uint32_t tp[3] = { ptr_out, 3, vec4_t }; body_op(&b, 32, 3, tp);      /* OpTypePointer Output %vec4 */
    for (size_t k = 0; k < nouts; k++) { uint32_t v[3] = { ptr_out, var0 + (uint32_t)k, 3 }; body_op(&b, 59, 3, v); } /* OpVariable Output */
    uint32_t fh[4] = { void_t, main_id, 0, fn_t }; body_op(&b, 54, 4, fh); /* OpFunction */
    uint32_t lb[1] = { label }; body_op(&b, 248, 1, lb);                  /* OpLabel */
    body_op(&b, 253, 0, NULL);                                             /* OpReturn */
    body_op(&b, 56, 0, NULL);                                              /* OpFunctionEnd */
    const size_t total = 5 + b.n;
    if (total > cap) return 0;
    out[0] = 0x07230203u; out[1] = 0x00010000u; out[2] = 0; out[3] = bound; out[4] = 0;
    memcpy(out + 5, b.w, b.n * sizeof(uint32_t));
    return total;
}

typedef struct { int parse_rc, reflect_rc, nout; uint32_t outmask; int dual; char why[256]; } Res;
static Res run_frag(const Out *outs, size_t nouts) {
    static uint32_t words[1024];
    Res res; memset(&res, 0, sizeof res);
    size_t nw = build_frag(words, 1024, outs, nouts);
    if (!nw) { res.parse_rc = 9; snprintf(res.why, sizeof res.why, "module too large"); return res; }
    N48sMod m; memset(&m, 0, sizeof m);
    char why[256] = "";
    res.parse_rc = n48s_parse(words, nw, &m, why, sizeof why);
    if (res.parse_rc) { snprintf(res.why, sizeof res.why, "%s", why); return res; }
    N48sRefl *r = calloc(1, sizeof *r);
    res.reflect_rc = n48s_reflect(&m, 1, r);
    res.nout = r->nout; res.outmask = r->outmask; res.dual = r->dual_src;
    snprintf(res.why, sizeof res.why, "%s", r->why);
    free(r); n48s_free(&m);
    return res;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[4096];
    snprintf(path, sizeof path, "%s/Navi48Device.m", dir); char *m = slurp(path);
    snprintf(path, sizeof path, "%s/n48_spvrefl.h", dir); char *h = slurp(path);
    snprintf(path, sizeof path, "%s/Info.plist", dir); char *pl = slurp(path);
    if (!m || !h || !pl) { printf("FAIL: cannot read Navi48Device.m, n48_spvrefl.h or Info.plist in %s\n", dir); return 1; }

    /* ---- part 1: source wiring ---- */
    check(at(m, "    BOOL dualSrc;   // bundle 32:") != NULL, "device: N48R.dualSrc flag");
    check(at(m, "VkPhysicalDeviceFeatures ef = { .dualSrcBlend = pf.dualSrcBlend, .shaderInt64 = pf.shaderInt64,") != NULL, "device: dualSrcBlend requested when RADV reports it");
    check(at(m, "N48R.dualSrc = (pf.dualSrcBlend && pp.limits.maxFragmentDualSrcAttachments >= 1) ? YES : NO;") != NULL, "device: dual-source on only with dualSrcBlend and maxFragmentDualSrcAttachments >= 1");
    check(at(m, "N48LOG(\"radv: dual-source blending %s (dualSrcBlend %u, maxFragmentDualSrcAttachments %u)\"") != NULL, "device: the decision is logged");
    check(at(m, "case MTLBlendFactorSource1Color: if (N48R.dualSrc) return VK_BLEND_FACTOR_SRC1_COLOR; break;") != NULL, "factors: Source1Color -> SRC1_COLOR when enabled");
    check(at(m, "case MTLBlendFactorOneMinusSource1Color: if (N48R.dualSrc) return VK_BLEND_FACTOR_ONE_MINUS_SRC1_COLOR; break;") != NULL, "factors: OneMinusSource1Color -> ONE_MINUS_SRC1_COLOR when enabled");
    check(at(m, "case MTLBlendFactorSource1Alpha: if (N48R.dualSrc) return VK_BLEND_FACTOR_SRC1_ALPHA; break;") != NULL, "factors: Source1Alpha -> SRC1_ALPHA when enabled");
    check(at(m, "case MTLBlendFactorOneMinusSource1Alpha: if (N48R.dualSrc) return VK_BLEND_FACTOR_ONE_MINUS_SRC1_ALPHA; break;") != NULL, "factors: OneMinusSource1Alpha -> ONE_MINUS_SRC1_ALPHA when enabled");
    check(at(m, "    default: break;\n    }\n    *bad = YES;   // an unknown factor, or a Source1* factor while dual-source blending is off\n") != NULL,
          "factors: anything else (and Source1* while off) still sets bad");
    check(at(m, "dualSrcBlend not enabled") == NULL, "factors: the old unconditional Source1* refusal is gone");
    check(at(m, "static BOOL n48_bf_is_src1(MTLBlendFactor f) {") != NULL, "pipeline: n48_bf_is_src1 helper");
    check(at(m, "const BOOL src1 = n48_bf_is_src1(ca.sourceRGBBlendFactor) || n48_bf_is_src1(ca.destinationRGBBlendFactor) ||") != NULL
          && at(m, "n48_bf_is_src1(ca.sourceAlphaBlendFactor) || n48_bf_is_src1(ca.destinationAlphaBlendFactor);") != NULL,
          "pipeline: a blend that uses any Source1* factor is detected for each attachment");
    check(at(m, "if (src1 && i != 0) {") != NULL && count(m, "n48_err(67,") == 1
          && at(m, "n48_err(67, @\"dual-source (Source1*) blend factors are supported on colour attachment 0 only\")") != NULL,
          "pipeline: Source1* on a colour attachment other than 0 is refused (code 67, the only use of 67)");
    check(at(m, "if (src1 && rf && !rf->dual_src) N48LOG(") != NULL, "pipeline: a warning when the fragment writes no Index 1 output");
    check(at(m, "if (rf && !(rf->outmask & (1u << na))) { wm = 0;") != NULL, "write mask: the outmask rule is unchanged");
    check(at(m, "if (bad) { if (err) *err = n48_err(56,") != NULL, "pipeline: the generic blend refusal (56) is still there");
    check(at(h, "case 32: t->index = a[2] > 1 ? 2 : (int)a[2];") != NULL, "reflection: the Index decoration is parsed (a value above 1 is stored as 2)");
    check(at(h, "m->id[i].builtin = m->id[i].index = -1;") != NULL, "reflection: index starts at -1 (none)");
    check(at(h, "if (v->index > 1) { snprintf(r->why") != NULL, "reflection: an Index above 1 is refused");
    check(at(h, "if (v->index == 1 && v->loc != 0) { snprintf(r->why") != NULL, "reflection: Index 1 is refused on any Location but 0");
    check(at(h, "if (v->index == 1) r->dual_src = 1;") != NULL, "reflection: Index 1 sets dual_src");
    check(at(h, "   int dual_src;") != NULL, "reflection: N48sRefl.dual_src");
    check(at(pl, "<key>CFBundleVersion</key>\n\t<string>32</string>") != NULL, "Info.plist: CFBundleVersion 32");

    /* ---- part 2: reflection of hand-made SPIR-V ---- */
    {   /* a: plain single colour output */
        Out o[] = { { 0, -1 } }; Res r = run_frag(o, 1);
        check(r.parse_rc == 0 && r.reflect_rc == 0 && r.nout == 1 && r.outmask == 0x1 && r.dual == 0, "refl a: Location 0, no Index: one attachment, mask 0x1, not dual");
    }
    {   /* b: colour + dual-source second output on the same Location: still ONE attachment */
        Out o[] = { { 0, 0 }, { 0, 1 } }; Res r = run_frag(o, 2);
        check(r.parse_rc == 0 && r.reflect_rc == 0, "refl b: Location 0 Index 0 + Location 0 Index 1 is accepted");
        check(r.nout == 1, "refl b: Index 1 on Location 0 is not an attachment (nout stays 1, not 2)");
        check(r.outmask == 0x1, "refl b: outmask is bit 0 only (the write of output 0 is seen once, so no 'does not write output 0')");
        check(r.dual == 1, "refl b: dual_src set");
    }
    {   /* c: Index 1 alone on Location 0 still counts as a write of output 0 */
        Out o[] = { { 0, 1 } }; Res r = run_frag(o, 1);
        check(r.reflect_rc == 0 && r.nout == 1 && r.outmask == 0x1 && r.dual == 1, "refl c: Index 1 alone on Location 0: one attachment, bit 0 set, dual");
    }
    {   /* d: two plain attachments: unchanged */
        Out o[] = { { 0, -1 }, { 1, -1 } }; Res r = run_frag(o, 2);
        check(r.reflect_rc == 0 && r.nout == 2 && r.outmask == 0x3 && r.dual == 0, "refl d: two plain colour outputs: two attachments, mask 0x3, not dual");
    }
    {   /* e: two attachments with the dual-source pair on attachment 0 */
        Out o[] = { { 0, 0 }, { 0, 1 }, { 1, -1 } }; Res r = run_frag(o, 3);
        check(r.reflect_rc == 0 && r.nout == 2 && r.outmask == 0x3 && r.dual == 1, "refl e: dual pair on Location 0 plus Location 1: two attachments, mask 0x3, dual");
    }
    {   /* f: explicit Index 0 is the same as no Index */
        Out o[] = { { 0, 0 } }; Res r = run_frag(o, 1);
        check(r.reflect_rc == 0 && r.nout == 1 && r.outmask == 0x1 && r.dual == 0, "refl f: explicit Index 0 is an ordinary colour output");
    }
    {   /* g: Index 1 on Location 1 is refused (dual-source is Location 0 only) */
        Out o[] = { { 0, 0 }, { 1, 1 } }; Res r = run_frag(o, 2);
        check(r.reflect_rc == 1 && strstr(r.why, "Index 1 on Location 1") != NULL, "refl g: Index 1 on Location 1 is refused");
    }
    {   /* h: Index 2 is refused */
        Out o[] = { { 0, 2 } }; Res r = run_frag(o, 1);
        check(r.reflect_rc == 1 && strstr(r.why, "above 1") != NULL, "refl h: Index 2 is refused");
    }
    {   /* i: Index 0xffffffff (stored as 2) is refused, not read as no Index */
        Out o[] = { { 0, 0xffffffffLL } }; Res r = run_frag(o, 1);
        check(r.reflect_rc == 1 && strstr(r.why, "above 1") != NULL, "refl i: Index 0xffffffff is refused (not taken as no Index)");
    }

    printf("test-b32-dualsrc: %d checks, %d failed\n", checks, fails);
    free(m); free(h); free(pl);
    return fails ? 1 : 0;
}
