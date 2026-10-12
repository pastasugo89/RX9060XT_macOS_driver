/* Read-only: amdgpu_device_initialize (DRM_IOCTL_VERSION + INFO queries) and amdgpu_query_sw_info. */
#include <fcntl.h>
#include <stdio.h>
#include <stdint.h>
#include <unistd.h>
#include <amdgpu.h>
int main(void) {
   int fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
   if (fd < 0) { perror("open"); return 1; }
   uint32_t maj, min; amdgpu_device_handle dev;
   if (amdgpu_device_initialize(fd, &maj, &min, &dev)) { fprintf(stderr, "init failed\n"); return 1; }
   uint32_t a32 = 0, prt = 0;
   int r1 = amdgpu_query_sw_info(dev, amdgpu_sw_info_address32_hi, &a32);
   int r2 = amdgpu_query_sw_info(dev, amdgpu_sw_info_address_prt_wa_control_bit, &prt);
   uint64_t s, e; amdgpu_va_range_query(dev, amdgpu_gpu_va_range_general, &s, &e);
   printf("drm %u.%u address32_hi=0x%x (r=%d) prt_wa_control_bit=%u (r=%d) va_general=[0x%llx,0x%llx)\n",
          maj, min, a32, r1, prt, r2, (unsigned long long)s, (unsigned long long)e);
   amdgpu_device_deinitialize(dev); close(fd); return 0;
}
