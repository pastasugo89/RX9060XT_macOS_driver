// OpenCL C kernel compiled for amdgcn-amd-amdhsa gfx1200
__kernel void vadd_cl(__global const float *a, __global const float *b,
                      __global float *c, uint n) {
  uint i = get_global_id(0);
  if (i < n) c[i] = a[i] + b[i];
}

__kernel void lds_reduce(__global const float *in, __global float *out) {
  __local float tile[256];
  uint l = get_local_id(0);
  tile[l] = in[get_global_id(0)];
  barrier(CLK_LOCAL_MEM_FENCE);
  for (uint s = 128; s > 0; s >>= 1) {
    if (l < s) tile[l] += tile[l + s];
    barrier(CLK_LOCAL_MEM_FENCE);
  }
  if (l == 0) out[get_group_id(0)] = tile[0];
}
