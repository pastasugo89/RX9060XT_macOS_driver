import subprocess,time,re
p='research/builds/macos-20261027/desktop-prep/fast-metal-tools/navi48test'
def read():
 t=time.monotonic_ns(); s=subprocess.check_output([p,'accel','dcnstate'],text=True); e=time.monotonic_ns()
 m=re.search(r'frame count\s*:\s*(\d+)',s); o=re.search(r'lit OTG\s*:\s*(\d+)',s)
 if not m or not o: raise ValueError(s)
 return ((t+e)/2,int(m.group(1)),int(o.group(1)),(e-t)/1e6)
a=read(); time.sleep(8); b=read();
print('first:',a,'second:',b)
print('frames_per_second:',(b[1]-a[1])/((b[0]-a[0])/1e9),'uncertainty_sources: frame quantization and subprocess timing')
