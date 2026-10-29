#!/usr/bin/env python3
"""Exercise the actual shader cache file helpers under macOS Seatbelt."""
import pathlib, subprocess, tempfile, json
root=pathlib.Path(__file__).resolve().parents[3]
header=root/'cobalt64/tools/native/navi48metal'
source=r'''
#include "n48_xlate.h"
int main(int argc, char **argv) {
 if(argc!=3)return 10;
 char p[4096]; snprintf(p,sizeof p,"%s/result",argv[1]);
 int allowed=atoi(argv[2]);
 if(n48x_cache_writable(argv[1]) != allowed)return 11;
 if(!allowed)return 0;
 if(n48x_write_atomic(p,"data",4))return 12;
 struct stat st;
 if(lstat(p,&st)||!S_ISREG(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&0022)||st.st_size!=4)return 13;
 return unlink(p)?14:0;
}
'''
with tempfile.TemporaryDirectory(prefix='n48-cache-sandbox-') as tmp:
 d=pathlib.Path(tmp).resolve(); (d/'probe.c').write_text(source)
 subprocess.run(['clang','-O1','-Wall','-Wextra','-Werror','-I'+str(header),str(d/'probe.c'),'-o',str(d/'probe')],check=True)
 writable=d/'writable'; denied=d/'denied'; writable.mkdir(mode=0o700); denied.mkdir(mode=0o700)
 profile='(version 1)(deny default)(allow process* sysctl-read mach-lookup file-read*)(allow file-write-data file-write-create file-write-unlink (subpath '+json.dumps(str(writable))+'))'
 for target,allowed in [(writable,1),(denied,0)]:
  subprocess.run(['/usr/bin/sandbox-exec','-p',profile,str(d/'probe'),str(target),str(allowed)],check=True)
 print('Shader cache: allowed writes succeed with chmod denied; denied directory rejected.')
