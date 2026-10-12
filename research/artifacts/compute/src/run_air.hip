// Host test: launch AIR-derived gfx1200 kernels (air2amdgpu.py output) through hipModule API.
#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstring>
#include <vector>

#define CK(x) do { hipError_t e = (x); if (e != hipSuccess) { \
  printf("HIP error %s at line %d: %s\n", #x, __LINE__, hipGetErrorString(e)); return 1; } } while (0)

static int launch(hipFunction_t f, void *args, size_t argsz, unsigned grid, unsigned block, unsigned lds) {
  void *cfg[] = {HIP_LAUNCH_PARAM_BUFFER_POINTER, args, HIP_LAUNCH_PARAM_BUFFER_SIZE, &argsz, HIP_LAUNCH_PARAM_END};
  CK(hipModuleLaunchKernel(f, grid, 1, 1, block, 1, 1, lds, nullptr, nullptr, cfg));
  CK(hipDeviceSynchronize());
  return 0;
}

int main(int argc, char **argv) {
  int n = 0; CK(hipGetDeviceCount(&n));
  int sel = -1;
  for (int d = 0; d < n; ++d) { hipDeviceProp_t p; CK(hipGetDeviceProperties(&p, d));
    if (!strncmp(p.gcnArchName, "gfx1200", 7)) { sel = d; break; } }
  if (sel < 0) { printf("no gfx1200\n"); return 2; }
  CK(hipSetDevice(sel));
  hipModule_t m; CK(hipModuleLoad(&m, argv[1]));
  int fails = 0;

  { // a4_simdgroup_barrier: 1 group x 32 threads, out[t] = 3*(t^1)+1
    hipFunction_t f; CK(hipModuleGetFunction(&f, m, "a4_simdgroup_barrier"));
    unsigned *d; CK(hipMalloc(&d, 32 * 4)); CK(hipMemset(d, 0xff, 32 * 4));
    struct { void *out; } a = {d};
    if (launch(f, &a, sizeof a, 1, 32, 0)) return 1;
    unsigned h[32]; CK(hipMemcpy(h, d, sizeof h, hipMemcpyDeviceToHost));
    int bad = 0; for (unsigned t = 0; t < 32; ++t) bad += h[t] != 3u * (t ^ 1u) + 1u;
    printf("a4_simdgroup_barrier: %s (out[0..3]=%u %u %u %u)\n", bad ? "FAIL" : "PASS", h[0], h[1], h[2], h[3]);
    fails += bad != 0;
  }
  { // ob1_buffer_atomic: 4 threads (2 groups x 2), idx all 0 -> ctr[0] = 1+2+3+4 = 10
    hipFunction_t f; CK(hipModuleGetFunction(&f, m, "ob1_buffer_atomic"));
    unsigned hidx[4] = {0, 0, 0, 0}, hctr[8] = {0};
    unsigned *didx, *dctr; CK(hipMalloc(&didx, 16)); CK(hipMalloc(&dctr, 32));
    CK(hipMemcpy(didx, hidx, 16, hipMemcpyHostToDevice)); CK(hipMemcpy(dctr, hctr, 32, hipMemcpyHostToDevice));
    struct { void *idx; void *ctr; } a = {didx, dctr};
    if (launch(f, &a, sizeof a, 2, 2, 0)) return 1;
    CK(hipMemcpy(hctr, dctr, 32, hipMemcpyDeviceToHost));
    // olds are distinct prefix sums of a permutation of {1,2,3,4}: each < 10, all distinct
    int bad = hctr[0] != 10;
    for (int i = 4; i < 8; ++i) for (int j = i + 1; j < 8; ++j) bad += hctr[i] == hctr[j];
    printf("ob1_buffer_atomic: %s (ctr[0]=%u olds=%u %u %u %u)\n", bad ? "FAIL" : "PASS", hctr[0], hctr[4], hctr[5], hctr[6], hctr[7]);
    fails += bad != 0;
  }
  { // ob1_threadgroup: 1 group x 8 threads, dynamic LDS 32 B; idx[t]=t, idx[8+t]=7-t -> out[t] = 0xC0000000|(7-t)
    hipFunction_t f; CK(hipModuleGetFunction(&f, m, "ob1_threadgroup"));
    unsigned hidx[16]; for (unsigned t = 0; t < 8; ++t) { hidx[t] = t; hidx[8 + t] = 7 - t; }
    unsigned *didx, *dout; CK(hipMalloc(&didx, 64)); CK(hipMalloc(&dout, 32));
    CK(hipMemcpy(didx, hidx, 64, hipMemcpyHostToDevice)); CK(hipMemset(dout, 0, 32));
    struct { void *idx; void *out; } a = {didx, dout};
    if (launch(f, &a, sizeof a, 1, 8, 32)) return 1;
    unsigned h[8]; CK(hipMemcpy(h, dout, 32, hipMemcpyDeviceToHost));
    int bad = 0; for (unsigned t = 0; t < 8; ++t) bad += h[t] != (0xC0000000u | (7 - t));
    printf("ob1_threadgroup: %s (out[0]=%#x out[7]=%#x)\n", bad ? "FAIL" : "PASS", h[0], h[7]);
    fails += bad != 0;
  }
  printf("%s\n", fails ? "SOME FAILED" : "ALL PASS");
  return fails;
}
