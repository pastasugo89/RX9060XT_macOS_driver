#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstring>
#include <vector>
#include <chrono>

__global__ void vadd(const float* __restrict__ a, const float* __restrict__ b,
                     float* __restrict__ c, unsigned n) {
  unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) c[i] = a[i] + b[i];
}

#define CK(x) do { hipError_t e = (x); if (e != hipSuccess) { \
  printf("HIP error %s at %s:%d: %s\n", #x, __FILE__, __LINE__, hipGetErrorString(e)); return 1; } } while (0)

int main() {
  int n_dev = 0; CK(hipGetDeviceCount(&n_dev));
  int sel = -1;
  for (int d = 0; d < n_dev; ++d) {
    hipDeviceProp_t p; CK(hipGetDeviceProperties(&p, d));
    printf("device %d: %s gcnArchName=%s CUs=%d warpSize=%d major.minor=%d.%d pciBus=%02x clock=%dkHz mem=%zu MiB\n",
           d, p.name, p.gcnArchName, p.multiProcessorCount, p.warpSize, p.major, p.minor,
           p.pciBusID, p.clockRate, p.totalGlobalMem >> 20);
    if (sel < 0 && strncmp(p.gcnArchName, "gfx1200", 7) == 0) sel = d;
  }
  if (sel < 0) { printf("no gfx1200 device\n"); return 2; }
  CK(hipSetDevice(sel));
  const unsigned n = 1u << 24; // 16M floats = 64 MiB per buffer
  std::vector<float> ha(n), hb(n), hc(n, 0.f);
  for (unsigned i = 0; i < n; ++i) { ha[i] = (float)i * 0.5f; hb[i] = (float)(n - i) * 0.25f; }
  float *da, *db, *dc;
  CK(hipMalloc(&da, n * 4)); CK(hipMalloc(&db, n * 4)); CK(hipMalloc(&dc, n * 4));
  CK(hipMemcpy(da, ha.data(), n * 4, hipMemcpyHostToDevice));
  CK(hipMemcpy(db, hb.data(), n * 4, hipMemcpyHostToDevice));
  dim3 blk(256), grd((n + 255) / 256);
  hipLaunchKernelGGL(vadd, grd, blk, 0, 0, da, db, dc, n); // warmup
  CK(hipGetLastError()); CK(hipDeviceSynchronize());
  hipEvent_t e0, e1; CK(hipEventCreate(&e0)); CK(hipEventCreate(&e1));
  const int iters = 50;
  CK(hipEventRecord(e0));
  for (int it = 0; it < iters; ++it) hipLaunchKernelGGL(vadd, grd, blk, 0, 0, da, db, dc, n);
  CK(hipEventRecord(e1)); CK(hipEventSynchronize(e1));
  float ms = 0; CK(hipEventElapsedTime(&ms, e0, e1));
  CK(hipMemcpy(hc.data(), dc, n * 4, hipMemcpyDeviceToHost));
  unsigned bad = 0;
  for (unsigned i = 0; i < n; ++i) if (hc[i] != ha[i] + hb[i]) { if (bad < 5) printf("mismatch %u: %f vs %f\n", i, hc[i], ha[i] + hb[i]); ++bad; }
  double gbs = (3.0 * n * 4 * iters) / (ms * 1e-3) / 1e9;
  printf("vadd n=%u iters=%d avg=%.4f ms effective=%.1f GB/s mismatches=%u -> %s\n", n, iters, ms / iters, gbs, bad, bad ? "FAIL" : "PASS");
  // tiny launch latency probe
  auto t0 = std::chrono::steady_clock::now();
  for (int it = 0; it < 1000; ++it) { hipLaunchKernelGGL(vadd, dim3(1), dim3(32), 0, 0, da, db, dc, 32u); }
  CK(hipDeviceSynchronize());
  auto t1 = std::chrono::steady_clock::now();
  printf("1000 tiny launches + sync: %.3f ms (%.2f us/launch)\n",
         std::chrono::duration<double, std::milli>(t1 - t0).count(),
         std::chrono::duration<double, std::micro>(t1 - t0).count() / 1000);
  CK(hipFree(da)); CK(hipFree(db)); CK(hipFree(dc));
  return bad ? 1 : 0;
}
