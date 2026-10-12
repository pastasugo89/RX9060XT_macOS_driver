import struct, sys
names=['UNK','SOS','SYS_DRV','KDB','TOC','SPL','RL','SOC_DRV','INTF_DRV','DBG_DRV','RAS_DRV','IPKEYMGR','SPDM_DRV']
for p in sys.argv[1:]:
    d=open(p,'rb').read()
    size,hsz,vmaj,vmin,ipmaj,ipmin,ucv,ucsz,ucoff,crc=struct.unpack_from('<IIHHHHIIII',d,0)
    print('%s: size %d hdr v%d.%d ip %d.%d' % (p.split('/')[-1],size,vmaj,vmin,ipmaj,ipmin))
    off=32
    cnt,=struct.unpack_from('<I',d,off); off+=4
    if vmin==1: aux,=struct.unpack_from('<I',d,off); off+=4; print('  aux index',aux)
    for i in range(cnt):
        t,ver,o,s=struct.unpack_from('<IIII',d,off+16*i)
        print('  %-9s ver 0x%08x size %7d' % (names[t] if t<len(names) else t, ver, s))
