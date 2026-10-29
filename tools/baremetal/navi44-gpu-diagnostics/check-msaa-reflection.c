/* Check the actual reflection header against a real shader from the runtime. */
#include "n48_spvrefl.h"
int main(int argc, char **argv) {
 if(argc!=3)return 2;
 FILE *f=fopen(argv[1],"rb");if(!f)return 3;
 fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);if(n<20||n%4){fclose(f);return 4;}
 uint32_t *w=malloc((size_t)n);if(!w){fclose(f);return 5;}
 if(fread(w,1,(size_t)n,f)!=(size_t)n){fclose(f);free(w);return 6;}fclose(f);
 N48sMod m;char why[256];if(n48s_parse(w,(size_t)n/4,&m,why,sizeof why)){free(w);return 7;}
 N48sRefl *r=calloc(1,sizeof *r);if(!r){n48s_free(&m);free(w);return 8;}
 int rc=n48s_reflect(&m,1,r);if(!rc)rc=!r->bind[0][32].used||r->bind[0][32].multisampled!=(uint32_t)atoi(argv[2]);
 free(r);n48s_free(&m);free(w);return rc;
}
