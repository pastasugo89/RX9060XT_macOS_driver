import struct, sys
HW = {1:'MP1',2:'MP2',3:'THM',4:'SMUIO',5:'FUSE',6:'CLKA',10:'PWR',11:'GC',12:'VCN/UVD',13:'AUDIO_AZ',14:'ACP',15:'DCI',271:'DMU',16:'DCO',272:'DIO',17:'XDMA',18:'DCEAZ',274:'DAZ',19:'SDPMUX',20:'NTB',21:'VPE',22:'UMSCH',24:'IOHC',28:'L2IMU',32:'VCE',34:'MMHUB',35:'ATHUB',36:'DBGU_NBIO',37:'DFX',38:'DBGU0',39:'DBGU1',40:'OSSSYS',41:'HDP',42:'SDMA0',43:'SDMA1',44:'ISP',45:'DBGU_IO',46:'DF',47:'CLKB',48:'FCH',49:'DFX_DAP',50:'L1IMU_PCIE',51:'L1IMU_NBIF',52:'L1IMU_IOAGR',66:'WAFLC',68:'SDMA2',69:'SDMA3',70:'PCIE',80:'PCS',89:'DDCL',90:'SST',91:'LSDMA',100:'IOAGR',108:'NBIF',124:'IOAPIC',128:'SYSTEMHUB',144:'NTBCCP',150:'UMC',168:'SATA',170:'USB',176:'CCXSEC',200:'XGMI',216:'XGBE',255:'MP0',294:'ATU',295:'AIGC'}
d = open(sys.argv[1],'rb').read()
sig, vmaj, vmin, csum, size = struct.unpack_from('<IHHHH', d, 0)
print('binary sig %#x ver %d.%d size %d' % (sig, vmaj, vmin, size))
off = 12
if vmaj >= 2:
    ntab, pad = struct.unpack_from('<HH', d, 12); off = 16
else:
    ntab = 6
tabs = []
for i in range(ntab):
    o, c, s, p = struct.unpack_from('<HHHH', d, off + 8*i)
    tabs.append((o, c, s))
    print(' table %d off %#x size %d' % (i, o, s))
ipo = tabs[0][0]
sig, ver, sz, tid, ndies = struct.unpack_from('<IHHIH', d, ipo)
print('ip_discovery sig %#x ver %d size %d dies %d' % (sig, ver, sz, ndies))
dies = [struct.unpack_from('<HH', d, ipo + 14 + 4*i) for i in range(ndies)]
flags = d[ipo + 14 + 64]
b64 = (ver == 4) and (flags & 1)
for die_id, doff in dies:
    did, nips = struct.unpack_from('<HH', d, doff)
    print('die %d nips %d' % (did, nips))
    p = doff + 4
    for i in range(nips):
        hw_id, inst, nba, ma, mi, rev, b = struct.unpack_from('<HBBBBBB', d, p)
        p += 8
        bases = []
        for j in range(nba):
            if b64:
                bases.append(struct.unpack_from('<Q', d, p)[0]); p += 8
            else:
                bases.append(struct.unpack_from('<I', d, p)[0]); p += 4
        name = HW.get(hw_id, str(hw_id))
        print('  %-10s hwid %3d inst %d ver %d.%d.%d subrev/var %#x bases %s' % (name, hw_id, inst, ma, mi, rev, b, ' '.join('%#x' % x for x in bases)))
# harvest table
if len(tabs) > 2 and tabs[2][0]:
    ho = tabs[2][0]
    hs, hv = struct.unpack_from('<II', d, ho)
    print('harvest sig %#x ver %d' % (hs, hv))
    for i in range(32):
        hw, inst, r = struct.unpack_from('<HBB', d, ho + 8 + 4*i)
        if hw: print('  harvested', HW.get(hw, hw), 'inst', inst)
if len(tabs) > 4 and tabs[4][0]:
    mo = tabs[4][0]
    print('mall table raw', d[mo:mo+48].hex())
