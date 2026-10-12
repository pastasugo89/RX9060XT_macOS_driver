import os, re, sys
root = sys.argv[1]; a = sys.argv[2]; b = sys.argv[3]
pa = 'IP_VERSION(%s)' % a; pb = 'IP_VERSION(%s)' % b
for dp, dn, fn in os.walk(root):
    for f in fn:
        if not f.endswith(('.c', '.h')): continue
        p = os.path.join(dp, f)
        try: L = open(p, errors='ignore').read().split('\n')
        except: continue
        for i, l in enumerate(L):
            for x, y in ((pa, pb), (pb, pa)):
                if x in l:
                    win = '\n'.join(L[max(0, i-3):i+4])
                    if y not in win:
                        print("%s:%d: [%s only] %s" % (os.path.relpath(p, root), i+1, x, l.strip()[:110]))
