/*
 * Bounded direct-ICD smoke test for the Darwin RADV build.
 *
 * This deliberately bypasses the Vulkan loader: it uses the public ICD
 * vk_icdGetInstanceProcAddr entrypoint, enumerates devices/queue families,
 * and creates/destroys one device and queue if a compute-capable family exists.
 * It submits no work and does not install or load any kernel extension.
 */
#include <dlfcn.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>

typedef PFN_vkVoidFunction(VKAPI_PTR *PFN_vk_icdGetInstanceProcAddr)(VkInstance, const char *);

#define LOAD(instance, type, name) ((type)get_proc((instance), (name)))

static PFN_vk_icdGetInstanceProcAddr get_proc;

static int
vk_failure(const char *where, VkResult result)
{
   fprintf(stderr, "FAIL %s VkResult=%d\n", where, result);
   return 1;
}

int
main(int argc, char **argv)
{
   if (argc != 2) {
      fprintf(stderr, "usage: %s /path/to/libvulkan_radeon.dylib\n", argv[0]);
      return 2;
   }

   void *icd = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!icd) {
      fprintf(stderr, "FAIL dlopen: %s\n", dlerror());
      return 1;
   }
   get_proc = (PFN_vk_icdGetInstanceProcAddr)dlsym(icd, "vk_icdGetInstanceProcAddr");
   if (!get_proc) {
      fprintf(stderr, "FAIL missing vk_icdGetInstanceProcAddr: %s\n", dlerror());
      dlclose(icd);
      return 1;
   }

   PFN_vkCreateInstance create_instance = LOAD(VK_NULL_HANDLE, PFN_vkCreateInstance, "vkCreateInstance");
   if (!create_instance) {
      fprintf(stderr, "FAIL missing vkCreateInstance\n");
      dlclose(icd);
      return 1;
   }
   VkApplicationInfo app = {
      .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
      .pApplicationName = "radv-icd-smoke",
      .applicationVersion = 1,
      .pEngineName = "direct-ICD bounded test",
      .engineVersion = 1,
      .apiVersion = VK_API_VERSION_1_0,
   };
   VkInstanceCreateInfo instance_info = {
      .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
      .pApplicationInfo = &app,
   };
   VkInstance instance = VK_NULL_HANDLE;
   VkResult result = create_instance(&instance_info, NULL, &instance);
   if (result != VK_SUCCESS)
      return vk_failure("vkCreateInstance", result);
   printf("PASS vkCreateInstance api=1.0\n");

   PFN_vkEnumeratePhysicalDevices enumerate = LOAD(instance, PFN_vkEnumeratePhysicalDevices,
                                                    "vkEnumeratePhysicalDevices");
   PFN_vkGetPhysicalDeviceProperties get_properties = LOAD(instance, PFN_vkGetPhysicalDeviceProperties,
                                                            "vkGetPhysicalDeviceProperties");
   PFN_vkGetPhysicalDeviceQueueFamilyProperties get_queue_properties =
      LOAD(instance, PFN_vkGetPhysicalDeviceQueueFamilyProperties, "vkGetPhysicalDeviceQueueFamilyProperties");
   PFN_vkCreateDevice create_device = LOAD(instance, PFN_vkCreateDevice, "vkCreateDevice");
   PFN_vkGetDeviceQueue get_device_queue = LOAD(instance, PFN_vkGetDeviceQueue, "vkGetDeviceQueue");
   PFN_vkDestroyDevice destroy_device = LOAD(instance, PFN_vkDestroyDevice, "vkDestroyDevice");
   PFN_vkDestroyInstance destroy_instance = LOAD(instance, PFN_vkDestroyInstance, "vkDestroyInstance");
   if (!enumerate || !get_properties || !get_queue_properties || !create_device || !get_device_queue ||
       !destroy_device || !destroy_instance) {
      fprintf(stderr, "FAIL missing required Vulkan entrypoint\n");
      return 1;
   }

   uint32_t device_count = 0;
   result = enumerate(instance, &device_count, NULL);
   if (result != VK_SUCCESS || device_count == 0) {
      destroy_instance(instance, NULL);
      dlclose(icd);
      if (result != VK_SUCCESS)
         return vk_failure("vkEnumeratePhysicalDevices(count)", result);
      fprintf(stderr, "FAIL no physical devices enumerated\n");
      return 1;
   }
   VkPhysicalDevice *devices = calloc(device_count, sizeof(*devices));
   if (!devices) {
      destroy_instance(instance, NULL);
      dlclose(icd);
      fprintf(stderr, "FAIL host allocation for %u handles\n", device_count);
      return 1;
   }
   result = enumerate(instance, &device_count, devices);
   if (result != VK_SUCCESS) {
      free(devices);
      destroy_instance(instance, NULL);
      dlclose(icd);
      return vk_failure("vkEnumeratePhysicalDevices(list)", result);
   }
   printf("PASS vkEnumeratePhysicalDevices count=%u\n", device_count);

   int matched = 0, created_queue = 0;
   for (uint32_t d = 0; d < device_count; d++) {
      VkPhysicalDeviceProperties properties;
      get_properties(devices[d], &properties);
      printf("DEVICE[%u] name=\"%s\" vendor=0x%04x device=0x%04x api=%u.%u.%u\n", d,
             properties.deviceName, properties.vendorID, properties.deviceID,
             VK_VERSION_MAJOR(properties.apiVersion), VK_VERSION_MINOR(properties.apiVersion),
             VK_VERSION_PATCH(properties.apiVersion));
      if (properties.vendorID != 0x1002 || properties.deviceID != 0x7590)
         continue;
      matched = 1;

      uint32_t family_count = 0;
      get_queue_properties(devices[d], &family_count, NULL);
      VkQueueFamilyProperties *families = calloc(family_count, sizeof(*families));
      if (!families) {
         fprintf(stderr, "FAIL host allocation for %u queue families\n", family_count);
         break;
      }
      get_queue_properties(devices[d], &family_count, families);
      uint32_t compute_family = UINT32_MAX;
      for (uint32_t q = 0; q < family_count; q++) {
         printf("QUEUE[%u] flags=0x%x count=%u\n", q, families[q].queueFlags, families[q].queueCount);
         if (compute_family == UINT32_MAX && families[q].queueCount &&
             (families[q].queueFlags & VK_QUEUE_COMPUTE_BIT))
            compute_family = q;
      }
      if (compute_family != UINT32_MAX) {
         float priority = 0.0f;
         VkDeviceQueueCreateInfo queue_info = {
            .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = compute_family,
            .queueCount = 1,
            .pQueuePriorities = &priority,
         };
         VkDeviceCreateInfo device_info = {
            .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            .queueCreateInfoCount = 1,
            .pQueueCreateInfos = &queue_info,
         };
         VkDevice device = VK_NULL_HANDLE;
         result = create_device(devices[d], &device_info, NULL, &device);
         if (result == VK_SUCCESS) {
            VkQueue queue = VK_NULL_HANDLE;
            get_device_queue(device, compute_family, 0, &queue);
            if (queue) {
               printf("PASS vkCreateDevice/vkGetDeviceQueue family=%u; no commands submitted\n", compute_family);
               created_queue = 1;
            } else {
               fprintf(stderr, "FAIL vkGetDeviceQueue returned NULL\n");
            }
            destroy_device(device, NULL);
         } else {
            fprintf(stderr, "FAIL vkCreateDevice VkResult=%d\n", result);
         }
      } else {
         fprintf(stderr, "INFO matching device exposes no compute queue\n");
      }
      free(families);
      break;
   }

   free(devices);
   destroy_instance(instance, NULL);
   dlclose(icd);
   if (!matched) {
      fprintf(stderr, "FAIL expected PCI identity 1002:7590 not enumerated\n");
      return 1;
   }
   if (!created_queue) {
      fprintf(stderr, "FAIL matching device did not produce a usable compute queue\n");
      return 1;
   }
   puts("RESULT PASS identity+compute-queue Vulkan init; no GPU work submitted");
   return 0;
}
