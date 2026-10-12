import json,re,sys
prof=json.load(open(sys.argv[1]))['capabilities']['device']
txt=open(sys.argv[2]).read()
feats={}
for s,m in prof['features'].items():
    for k,v in m.items(): feats.setdefault(k,[]).append((s,v))
exts=prof['extensions']
need_f=sorted(set(re.findall(r'VkFeature::([A-Za-z0-9]+)',txt)))
need_e=sorted(set(re.findall(r'VkExtension::([A-Za-z0-9]+)',txt)))
miss=[]
for f in need_f:
    n=f[0].lower()+f[1:]
    # fix common acronyms
    cands=[n, n.replace('Int64','Int64'), re.sub(r'^shaderInt64','shaderInt64',n)]
    hit=None
    for k in feats:
        if k.lower()==n.lower(): hit=(k,feats[k]); break
    val = any(v for s,v in hit[1]) if hit else None
    print(f"F {f:45s} -> {hit[0] if hit else '??':45s} {val}")
for e in need_e:
    # ExtExternalMemoryHost -> VK_EXT_external_memory_host
    parts=re.findall(r'[A-Z][a-z0-9]*',e)
    name='VK_'+parts[0].upper()+'_'+'_'.join(p.lower() for p in parts[1:])
    print(f"E {e:45s} -> {name:45s} {name in exts}")
