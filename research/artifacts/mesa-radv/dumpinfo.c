/* Read-only dump of every AMDGPU_INFO value RADV/ac_gpu_info.c consumes,
 * printed as a canned-device initializer (format of mesa amdgpu_devices.c).
 * Only DRM_IOCTL_AMDGPU_INFO / DRM_IOCTL_VERSION / DRM_IOCTL_GET_CAP are used:
 * no BO, no CS, no state change.  Build: cc -O1 dumpinfo.c -ldrm -ldrm_amdgpu */
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>
#include <amdgpu.h>
#include <amdgpu_drm.h>

static int q(int fd, uint32_t query, void *out, uint32_t size, void (*fill)(struct drm_amdgpu_info *, void *), void *arg)
{
   struct drm_amdgpu_info r;
   memset(&r, 0, sizeof(r));
   memset(out, 0, size);
   r.return_pointer = (uintptr_t)out;
   r.return_size = size;
   r.query = query;
   if (fill)
      fill(&r, arg);
   return drmCommandWrite(fd, DRM_AMDGPU_INFO, &r, sizeof(r));
}
static void fill_ip(struct drm_amdgpu_info *r, void *a) { r->query_hw_ip.type = *(uint32_t *)a; }
static void fill_fw(struct drm_amdgpu_info *r, void *a) { r->query_fw.fw_type = *(uint32_t *)a; }
static void fill_reg(struct drm_amdgpu_info *r, void *a)
{
   r->read_mmr_reg.dword_offset = *(uint32_t *)a;
   r->read_mmr_reg.count = 1;
   r->read_mmr_reg.instance = 0xffffffff;
}
static void fill_sensor(struct drm_amdgpu_info *r, void *a) { r->sensor_info.type = *(uint32_t *)a; }

int main(int argc, char **argv)
{
   const char *path = argc > 1 ? argv[1] : "/dev/dri/renderD128";
   int fd = open(path, O_RDWR | O_CLOEXEC);
   if (fd < 0) { perror(path); return 1; }

   drmVersionPtr v = drmGetVersion(fd);
   printf("/* node %s: driver %s %d.%d.%d */\n", path, v->name, v->version_major, v->version_minor, v->version_patchlevel);
   drmFreeVersion(v);
   uint64_t cap;
   if (!drmGetCap(fd, DRM_CAP_SYNCOBJ, &cap)) printf("/* DRM_CAP_SYNCOBJ = %" PRIu64 " */\n", cap);
   if (!drmGetCap(fd, DRM_CAP_SYNCOBJ_TIMELINE, &cap)) printf("/* DRM_CAP_SYNCOBJ_TIMELINE = %" PRIu64 " */\n", cap);
   if (!drmGetCap(fd, DRM_CAP_ADDFB2_MODIFIERS, &cap)) printf("/* DRM_CAP_ADDFB2_MODIFIERS = %" PRIu64 " */\n", cap);
   else printf("/* DRM_CAP_ADDFB2_MODIFIERS: not answered on this node */\n");

   uint32_t major, minor;
   amdgpu_device_handle dev;
   if (amdgpu_device_initialize(fd, &major, &minor, &dev) == 0) {
      uint32_t a32 = 0, prt = 0;
      int r1 = amdgpu_query_sw_info(dev, amdgpu_sw_info_address32_hi, &a32);
      printf("/* amdgpu_sw_info_address32_hi = 0x%08x (r=%d) */\n", a32, r1);
#ifdef AMDGPU_SW_INFO_HAS_PRT
      (void)prt;
#endif
      uint64_t s = 0, e = 0;
      amdgpu_va_range_query(dev, amdgpu_gpu_va_range_general, &s, &e);
      printf("/* amdgpu_va_range_query(general) = [0x%" PRIx64 ", 0x%" PRIx64 ") */\n", s, e);
      printf("/* marketing name = %s */\n", amdgpu_get_marketing_name(dev));
      amdgpu_device_deinitialize(dev);
   }

   const char *ipn[] = {"GFX", "COMPUTE", "DMA", "UVD", "VCE", "UVD_ENC", "VCN_DEC", "VCN_ENC", "VCN_JPEG", "VPE"};
   for (uint32_t t = 0; t < 10; t++) {
      struct drm_amdgpu_info_hw_ip ip;
      uint32_t cnt = 0;
      int r = q(fd, AMDGPU_INFO_HW_IP_INFO, &ip, sizeof(ip), fill_ip, &t);
      q(fd, AMDGPU_INFO_HW_IP_COUNT, &cnt, sizeof(cnt), fill_ip, &t);
      if (r) { printf("/* hw_ip %s: r=%d */\n", ipn[t], r); continue; }
      printf(".hw_ip_%s = { /* count=%u */\n   .hw_ip_version_major = %u,\n   .hw_ip_version_minor = %u,\n"
             "   .capabilities_flags = UINT64_C(0x%" PRIx64 "),\n   .ib_start_alignment = %u,\n   .ib_size_alignment = %u,\n"
             "   .available_rings = 0x%x,\n   .ip_discovery_version = 0x%x,\n},\n",
             ipn[t], cnt, ip.hw_ip_version_major, ip.hw_ip_version_minor, (uint64_t)ip.capabilities_flags,
             ip.ib_start_alignment, ip.ib_size_alignment, ip.available_rings, ip.ip_discovery_version);
   }

   struct { uint32_t id; const char *n; } fws[] = {
      {AMDGPU_INFO_FW_GFX_ME, "gfx_me"}, {AMDGPU_INFO_FW_GFX_PFP, "gfx_pfp"}, {AMDGPU_INFO_FW_GFX_MEC, "gfx_mec"},
      {AMDGPU_INFO_FW_GFX_RLC, "gfx_rlc"}, {AMDGPU_INFO_FW_SMC, "smc"}, {AMDGPU_INFO_FW_SDMA, "sdma"},
      {AMDGPU_INFO_FW_SOS, "sos"}, {AMDGPU_INFO_FW_VCN, "vcn"}, {AMDGPU_INFO_FW_DMCUB, "dmcub"},
      {AMDGPU_INFO_FW_MES, "mes"}, {AMDGPU_INFO_FW_MES_KIQ, "mes_kiq"}, {AMDGPU_INFO_FW_IMU, "imu"},
      {AMDGPU_INFO_FW_TOC, "toc"},
   };
   for (unsigned i = 0; i < sizeof(fws) / sizeof(fws[0]); i++) {
      struct drm_amdgpu_info_firmware fw;
      int r = q(fd, AMDGPU_INFO_FW_VERSION, &fw, sizeof(fw), fill_fw, &fws[i].id);
      printf(".fw_%s = { .ver = %u /* 0x%x */, .feature = %u, }, /* r=%d */\n", fws[i].n, fw.ver, fw.ver, fw.feature, r);
   }

   uint32_t reg = 0x263e, val = 0;
   int rr = q(fd, AMDGPU_INFO_READ_MMR_REG, &val, sizeof(val), fill_reg, &reg);
   printf(".mmr_regs = { 0x263e, 0xffffffff, 0x%08x, }, /* GB_ADDR_CONFIG r=%d */\n", val, rr);

   uint32_t max_ibs[AMDGPU_HW_IP_NUM] = {0};
   if (!q(fd, AMDGPU_INFO_MAX_IBS, max_ibs, sizeof(max_ibs), NULL, NULL)) {
      printf("/* AMDGPU_INFO_MAX_IBS:");
      for (int i = 0; i < AMDGPU_HW_IP_NUM; i++) printf(" %u", max_ibs[i]);
      printf(" */\n");
   }

   struct drm_amdgpu_info_device d;
   int rd = q(fd, AMDGPU_INFO_DEV_INFO, &d, sizeof(d), NULL, NULL);
   printf(".dev = { /* r=%d sizeof=%zu */\n", rd, sizeof(d));
#define P32(f) printf("   ." #f " = %u, /* 0x%x */\n", d.f, d.f)
#define P64(f) printf("   ." #f " = UINT64_C(0x%" PRIx64 "),\n", (uint64_t)d.f)
   P32(device_id); P32(chip_rev); P32(external_rev); P32(pci_rev); P32(family); P32(num_shader_engines);
   P32(num_shader_arrays_per_engine); P32(gpu_counter_freq); P64(max_engine_clock); P64(max_memory_clock);
   P32(cu_active_number); P32(cu_ao_mask);
   printf("   .cu_bitmap = {");
   for (int i = 0; i < 4; i++) { printf(" {"); for (int j = 0; j < 4; j++) printf(" 0x%x,", d.cu_bitmap[i][j]); printf(" },"); }
   printf(" },\n");
   P32(enabled_rb_pipes_mask); P32(num_rb_pipes); P32(num_hw_gfx_contexts); P32(pcie_gen); P64(ids_flags);
   P64(virtual_address_offset); P64(virtual_address_max); P32(virtual_address_alignment); P32(pte_fragment_size);
   P32(gart_page_size); P32(ce_ram_size); P32(vram_type); P32(vram_bit_width); P32(vce_harvest_config);
   P32(gc_double_offchip_lds_buf); P64(prim_buf_gpu_addr); P64(pos_buf_gpu_addr); P64(cntl_sb_buf_gpu_addr);
   P64(param_buf_gpu_addr); P32(prim_buf_size); P32(pos_buf_size); P32(cntl_sb_buf_size); P32(param_buf_size);
   P32(wave_front_size); P32(num_shader_visible_vgprs); P32(num_cu_per_sh); P32(num_tcc_blocks);
   P32(gs_vgt_table_depth); P32(gs_prim_buffer_depth); P32(max_gs_waves_per_vgt); P32(pcie_num_lanes);
   P64(high_va_offset); P64(high_va_max); P32(pa_sc_tile_steering_override); P64(tcc_disabled_mask);
   P64(min_engine_clock); P64(min_memory_clock); P32(tcp_cache_size); P32(num_sqc_per_wgp); P32(sqc_data_cache_size);
   P32(sqc_inst_cache_size); P32(gl1c_cache_size); P32(gl2c_cache_size); P64(mall_size); P32(enabled_rb_pipes_mask_hi);
   P32(shadow_size); P32(shadow_alignment); P32(csa_size); P32(csa_alignment); P32(userq_ip_mask);
   printf("},\n");

   struct drm_amdgpu_memory_info m;
   q(fd, AMDGPU_INFO_MEMORY, &m, sizeof(m), NULL, NULL);
   printf(".mem = {\n");
#define PH(h) printf("   ." #h " = { .total_heap_size = UINT64_C(%" PRIu64 "), .usable_heap_size = UINT64_C(%" PRIu64 \
                   "), .heap_usage = UINT64_C(%" PRIu64 "), .max_allocation = UINT64_C(%" PRIu64 ") },\n", \
                   (uint64_t)m.h.total_heap_size, (uint64_t)m.h.usable_heap_size, (uint64_t)m.h.heap_usage, \
                   (uint64_t)m.h.max_allocation)
   PH(vram); PH(cpu_accessible_vram); PH(gtt);
   printf("},\n");

   struct drm_amdgpu_info_vram_gtt vg;
   if (!q(fd, AMDGPU_INFO_VRAM_GTT, &vg, sizeof(vg), NULL, NULL))
      printf("/* VRAM_GTT: vram_size=%" PRIu64 " vram_cpu_accessible_size=%" PRIu64 " gtt_size=%" PRIu64 " */\n",
             (uint64_t)vg.vram_size, (uint64_t)vg.vram_cpu_accessible_size, (uint64_t)vg.gtt_size);
   uint64_t ts = 0;
   if (!q(fd, AMDGPU_INFO_TIMESTAMP, &ts, sizeof(ts), NULL, NULL))
      printf("/* TIMESTAMP = %" PRIu64 " */\n", ts);
   uint32_t sens_ids[] = {AMDGPU_INFO_SENSOR_GFX_SCLK, AMDGPU_INFO_SENSOR_GFX_MCLK, AMDGPU_INFO_SENSOR_GPU_TEMP};
   const char *sn[] = {"GFX_SCLK", "GFX_MCLK", "GPU_TEMP"};
   for (int i = 0; i < 3; i++) {
      uint32_t sv = 0;
      int r = q(fd, AMDGPU_INFO_SENSOR, &sv, sizeof(sv), fill_sensor, &sens_ids[i]);
      printf("/* SENSOR_%s = %u (r=%d) */\n", sn[i], sv, r);
   }
   struct drm_amdgpu_info_gpuvm_fault f;
   int rf = q(fd, AMDGPU_INFO_GPUVM_FAULT, &f, sizeof(f), NULL, NULL);
   printf("/* GPUVM_FAULT r=%d status=0x%x addr=0x%" PRIx64 " vmhub=%u */\n", rf, f.status, (uint64_t)f.addr, f.vmhub);
   close(fd);
   return 0;
}
