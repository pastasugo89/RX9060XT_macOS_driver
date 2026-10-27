#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
int main(void) {
 if(!dlopen("/System/Library/Frameworks/CoreDisplay.framework/CoreDisplay",RTLD_NOW)) return 1;
 for(uint32_t i=0;i<_dyld_image_count();i++) if(strstr(_dyld_get_image_name(i),"CoreDisplay.framework")) {
 unsigned char *b=(unsigned char*)_dyld_get_image_header(i); FILE *f=fopen("/private/tmp/n44-core-display.bin","wb"); fwrite(b+286829,1,3300,f); fclose(f); unsigned long start=289801-110;
 for(unsigned long j=start;j<289801;j++) printf("%02x%s",b[j],((j-start)%16==15)?"\n":" "); puts("");
 for(unsigned long j=start;j+7<289801;j++) if(b[j]==0x48 && b[j+1]==0x8d && (b[j+2]&0xc7)==5) {
 int32_t d;memcpy(&d,b+j+3,4); unsigned char *p=b+j+7+d; char s[300]={0};mach_vm_size_t n=0;
 if(mach_vm_read_overwrite(mach_task_self(),(mach_vm_address_t)p,299,(mach_vm_address_t)s,&n)==KERN_SUCCESS) printf("LEA %lx: %.299s\n",j,s);
 }
 }
}
