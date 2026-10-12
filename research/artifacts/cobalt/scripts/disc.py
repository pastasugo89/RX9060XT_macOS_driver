import struct, sys
d = open(sys.argv[1],'rb').read()
sig, vmaj, vmin, csum, bsize = struct.unpack_from('<IHHHH', d, 0)
print('bin sig %#x v%d.%d size %d' % (sig, vmaj, vmin, bsize))
tables = [struct.unpack_from('<HHHH', d, 12+8*i) for i in range(6)]
print('tables', tables)
ipoff = tables[0][0]
s, ver, sz, tid, ndies = struct.unpack_from('<IHHIH', d, ipoff)
print('ipds sig %#x ver %d size %d ndies %d' % (s, ver, sz, ndies))
dies = [struct.unpack_from('<HH', d, ipoff+14+4*i) for i in range(ndies)]
names = {1:'MP1',2:'MP2',3:'THM',4:'SMUIO',5:'FUSE',6:'CLKA',8:'PWR',11:'GC',12:'UVD/VCN',13:'AUDIO_AZ',14:'ACP',15:'DCI',20:'DMU?',21:'DCO',22:'DIO',23:'XDMA',24:'DCEAZ',25:'DAZ',26:'SDPMUX',27:'NTB',30:'IOHC',31:'L2IMU',32:'VCE',33:'MMHUB',34:'ATHUB',35:'DBGU_NBIO',36:'DFX',37:'DBGU0',38:'DBGU1',39:'OSSSYS',40:'HDP',41:'SDMA0',42:'SDMA1',43:'ISP',44:'DBGU_IO',45:'DF',46:'CLKB',47:'FCH',48:'DFX_DAP',49:'L1IMU_PCIE',50:'L1IMU_NBIF',51:'L1IMU_IOAGR',52:'L1IMU3',53:'L1IMU4',54:'L1IMU5',55:'L1IMU6',56:'L1IMU7',57:'L1IMU8',58:'L1IMU9',59:'L1IMU10',60:'L1IMU11',61:'L1IMU12',62:'L1IMU13',63:'L1IMU14',64:'L1IMU15',65:'WAFLC',66:'FCH_USB_PD',67:'SDMA2',68:'SDMA3',69:'PCIE',70:'PCS',71:'DDCL',72:'SST',73:'LSDMA',74:'IOAGR',75:'NBIF',76:'IOAPIC',77:'SYSTEMHUB',78:'NTBCCP',79:'UMC',80:'SATA',81:'USB',82:'CCXSEC',83:'XGMI',84:'XGBE',85:'MP0'}
# Use linux soc15_hw_ip ids
hw = {1:'MP1',2:'MP2',3:'THM',4:'SMUIO',5:'FUSE',6:'CLKA',8:'PWR',11:'GC',12:'UVD',13:'AUDIO_AZ',14:'ACP',15:'DCI',16:'DMU',17:'DCO',18:'DIO',19:'XDMA',20:'DCEAZ',21:'DAZ',22:'SDPMUX',23:'NTB',24:'VPE',25:'IOHC',26:'L2IMU',27:'VCE',28:'MMHUB',29:'ATHUB',30:'DBGU_NBIO',31:'DFX',32:'DBGU0',33:'DBGU1',34:'OSSSYS',35:'HDP',36:'SDMA0',37:'SDMA1',38:'ISP',39:'DBGU_IO',40:'DF',41:'CLKB',42:'FCH'}
for did, doff in dies:
    die_id, nips = struct.unpack_from('<HH', d, doff)
    print('die', die_id, 'nips', nips)
    p = doff+4
    for i in range(nips):
        hid, inst, nb, maj, mnr, rev, flags = struct.unpack_from('<HBBBBBB', d, p)
        bases = struct.unpack_from('<%dI'%nb, d, p+8)
        print('  hwid %3d inst %d v%d.%d.%d nb %d bases %s' % (hid, inst, maj, mnr, rev, nb, ' '.join('%#x'%b for b in bases)))
        p += 8 + 4*nb
