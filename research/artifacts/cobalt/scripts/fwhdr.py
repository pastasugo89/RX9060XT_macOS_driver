import struct, sys
for p in sys.argv[1:]:
    d=open(p,'rb').read()
    size,hsz,vmaj,vmin,ipmaj,ipmin,ucv,ucsz,ucoff,crc=struct.unpack_from('<IIHHHHIIII',d,0)
    print('%-22s hdr v%d.%d hsz %3d ip %d.%d ucode_ver 0x%08x size %7d' % (p.split('/')[-1],vmaj,vmin,hsz,ipmaj,ipmin,ucv,size))
