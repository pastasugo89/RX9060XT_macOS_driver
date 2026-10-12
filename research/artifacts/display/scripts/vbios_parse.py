#!/usr/bin/env python3
# Minimal ATOMFIRMWARE (SOC15+) VBIOS parser written for this report.
# Usage: python3 -I vbios_parse.py <vbios.rom>
import struct, sys

rom = open(sys.argv[1], 'rb').read()
u8 = lambda o: rom[o]
u16 = lambda o: struct.unpack_from('<H', rom, o)[0]
u32 = lambda o: struct.unpack_from('<I', rom, o)[0]

print('ROM size %d bytes, sig %02x%02x, size-in-512 %d' % (len(rom), rom[0], rom[1], rom[2]))
pcir = u16(0x18)
print('PCIR @%#x sig=%r vendor=%04x device=%04x' % (pcir, rom[pcir:pcir+4], u16(pcir+4), u16(pcir+6)))
hdr = u16(0x48)
print('ATOM ROM header @%#x' % hdr)
size, frev, crev = u16(hdr), u8(hdr+2), u8(hdr+3)
print('  rom header size %d rev %d.%d sig %r' % (size, frev, crev, rom[hdr+4:hdr+8]))
f = struct.unpack_from('<4s' + 'H'*15 + 'I', rom, hdr+4)
names = ['bios_segment_address','protectedmodeoffset','configfilenameoffset','crc_block_offset','vbios_bootupmessageoffset','int10_offset','pcibusdevinitcode','iobaseaddress','subsystem_vendor_id','subsystem_id','pci_info_offset','masterhwfunction_offset','masterdatatable_offset','reserved']
vals = dict(zip(names, f[1:15]))
vals['pspdirtableoffset'] = f[16] if len(f) > 16 else None
for k in names + ['pspdirtableoffset']:
    v = vals.get(k)
    if v is not None:
        print('  %-26s %#x' % (k, v))

CMD = ['asic_init','cmd_function1','cmd_function2','cmd_function3','digxencodercontrol','cmd_function5','cmd_function6','cmd_function7','cmd_function8','cmd_function9','setengineclock','setmemoryclock','setpixelclock','enabledisppowergating','cmd_function14','cmd_function15','cmd_function16','cmd_function17','cmd_function18','cmd_function19','cmd_function20','cmd_function21','cmd_function22','cmd_function23','cmd_function24','cmd_function25','cmd_function26','cmd_function27','cmd_function28','cmd_function29','cmd_function30','cmd_function31','cmd_function32','cmd_function33','blankcrtc','enablecrtc','cmd_function36','cmd_function37','cmd_function38','cmd_function39','cmd_function40','getsmuclockinfo','selectcrtc_source','cmd_function43','cmd_function44','cmd_function45','setdceclock','getmemoryclock','getengineclock','setcrtc_usingdtdtiming','externalencodercontrol','cmd_function51','cmd_function52','cmd_function53','processi2cchanneltransaction','cmd_function55','cmd_function56','cmd_function57','cmd_function58','cmd_function59','computegpuclockparam','cmd_function61','cmd_function62','dynamicmemorysettings','memorytraining','cmd_function65','cmd_function66','setvoltage','cmd_function68','readefusevalue','cmd_function70','cmd_function71','cmd_function72','cmd_function73','cmd_function74','cmd_function75','dig1transmittercontrol','cmd_function77','processauxchanneltransaction','cmd_function79','getvoltageinfo']
DATA = ['utilitypipeline','multimedia_info','smc_dpm_info','sw_datatable3','firmwareinfo','sw_datatable5','lcd_info','sw_datatable7','smu_info','sw_datatable9','sw_datatable10','vram_usagebyfirmware','gpio_pin_lut','sw_datatable13','gfx_info','powerplayinfo','sw_datatable16','sw_datatable17','sw_datatable18','sw_datatable19','sw_datatable20','sw_datatable21','displayobjectinfo','indirectioaccess','umc_info','sw_datatable25','sw_datatable26','dce_info','vram_info','sw_datatable29','integratedsysteminfo','asic_profiling_info','voltageobject_info','sw_datatable33','sw_datatable34']

def thdr(o):
    return u16(o), u8(o+2), u8(o+3)

mc = vals['masterhwfunction_offset']
s, fr, cr = thdr(mc)
print('\nMaster COMMAND table @%#x size %d rev %d.%d' % (mc, s, fr, cr))
ncmd = (s - 4) // 2
present = 0
for i in range(min(ncmd, len(CMD))):
    off = u16(mc + 4 + 2*i)
    if off:
        present += 1
        if off + 6 <= len(rom):
            ts, tf, tc = thdr(off)
            print('  [%2d] %-28s @%#06x size %5d rev %d.%d' % (i, CMD[i], off, ts, tf, tc))
        else:
            print('  [%2d] %-28s @%#06x (outside image)' % (i, CMD[i], off))
print('  -> %d of %d command table slots non-zero' % (present, ncmd))

md = vals['masterdatatable_offset']
s, fr, cr = thdr(md)
print('\nMaster DATA table @%#x size %d rev %d.%d' % (md, s, fr, cr))
ndt = (s - 4) // 2
DT = {}
for i in range(min(ndt, len(DATA))):
    off = u16(md + 4 + 2*i)
    if off:
        ts, tf, tc = thdr(off)
        DT[DATA[i]] = (off, ts, tf, tc)
        print('  [%2d] %-22s @%#06x size %5d rev %d.%d' % (i, DATA[i], off, ts, tf, tc))

# ---------- firmware info ----------
if 'firmwareinfo' in DT:
    o, ts, tf, tc = DT['firmwareinfo']
    print('\nfirmwareinfo v%d.%d' % (tf, tc))
    rev = u32(o+4); cap = u32(o+16)
    print('  firmware_revision %#x  firmware_capability %#x' % (rev, cap))
    caps = {0x1:'FIRMWARE_POSTED',0x2:'GPU_VIRTUALIZATION',0x40:'WMI_SUPPORT',0x80:'HWEMU_ENABLE',0x100:'HWEMU_UMC_CFG',0x200:'SRAM_ECC',0x400:'ENABLE_2STAGE_BIST_TRAINING',0x8000:'ENABLE_2ND_USB20PORT',0x20000:'DYNAMIC_BOOT_CFG_ENABLE',0x40000:'MMHUB/DPMSUPPORT?'}
    print('  caps bits:', [n for b, n in caps.items() if cap & b])
    if tc >= 5:
        print('  fw_protect_region_size_in_kb %d' % u32(o+20))
        print('  bios_scratch_reg_startaddr %#x' % u32(o+24))
        print('  mem_module_id %d cooling %d hw_blt_mode %d' % (u8(o+36), u8(o+37), u8(o+38)))
        print('  mc_baseaddr hi/lo %#x/%#x' % (u32(o+40), u32(o+44)))
        print('  board_i2c_feature id %d gpio %#x slave %#x ras_rom_slave %#x' % (u8(o+48), u8(o+49), u8(o+50), u8(o+51)))
        print('  pplib_pptable_id %#x' % u32(o+60))
        print('  maco_pwrlimit_mw %d usb_pwrlimit_mw %d fw_reserved_size_in_kb %d' % (u32(o+76), u32(o+80), u32(o+84)))
        print('  spi_rom_size %#x support_dev_in_objinfo %#x disp_phy_tunning_size %d' % (u32(o+100), u16(o+104), u16(o+106)))
    elif tc == 4:
        print('  bootup sclk %d mclk %d (10kHz)' % (u32(o+8), u32(o+12)))
        print('  bios_scratch_reg_startaddr %#x' % u32(o+24))
        print('  fw_reserved_size_in_kb %d' % u32(o+0x5c))

# ---------- dce info ----------
if 'dce_info' in DT:
    o, ts, tf, tc = DT['dce_info']
    print('\ndce_info (atom_display_controller_info) v%d.%d size %d' % (tf, tc, ts))
    print('  display_caps %#x' % u32(o+4))
    print('  bootup_dispclk_10khz %d -> %.1f MHz' % (u32(o+8), u32(o+8)/100))
    print('  dce_refclk_10khz %d  i2c_engine_refclk_10khz %d' % (u16(o+12), u16(o+14)))
    print('  ss: dvi %d%%o rate %d | hdmi %d rate %d | dp %d rate %d (0.001%% / 10Hz)' % (u16(o+16), u16(o+18), u16(o+20), u16(o+22), u16(o+24), u16(o+26)))
    print('  ss modes dvi/hdmi/dp %d/%d/%d' % (u8(o+28), u8(o+29), u8(o+30)))
    print('  dfp_hardcode_mode %d @%d  vga_hardcode_mode %d @%d' % (u8(o+32), u8(o+33), u8(o+34), u8(o+35)))
    print('  dpphy_refclk_10khz %d  hw_chip_id %#x' % (u16(o+36), u16(o+38)))
    print('  dcnip_min_ver %#x dcnip_max_ver %#x' % (u8(o+40), u8(o+41)))
    print('  max_disp_pipe_num %d max_vbios_active_disp_pipe_num %d max_ppll_num %d max_disp_phy_num %d max_aux_pairs %d remotedisplayconfig %#x' % tuple(u8(o+42+i) for i in range(6)))
    print('  dispclk_pll_vco_freq %d  dp_ref_clk_freq %d' % (u32(o+48), u32(o+52)))
    print('  max_mclk_chg_lat %d  max_sr_exit_lat %d  max_sr_enter_exit_lat %d (0.1us)' % (u32(o+56), u32(o+60), u32(o+64)))
    print('  dc_golden_table_offset %#x ver %#x' % (u16(o+68), u16(o+70)))
    if tc >= 5:
        names5 = ['aux_dphy_rx_control0_val','aux_dphy_tx_control_val','aux_dphy_rx_control1_val','dc_gpio_aux_ctrl_0_val','dc_gpio_aux_ctrl_1_val','dc_gpio_aux_ctrl_2_val','dc_gpio_aux_ctrl_3_val','dc_gpio_aux_ctrl_4_val','dc_gpio_aux_ctrl_5_val']
        for i, n in enumerate(names5):
            print('  %-26s %#010x' % (n, u32(o+72+4*i)))

# ---------- gpio pin lut ----------
GPIO_REGS = {0x28c9:'DC_GPIO_GENERIC_A',0x28d1:'DC_GPIO_DDC1_A',0x28d5:'DC_GPIO_DDC2_A',0x28d9:'DC_GPIO_DDC3_A',0x28dd:'DC_GPIO_DDC4_A',0x28e1:'DC_GPIO_DDC5_A',0x28e5:'DC_GPIO_DDC6_A',0x28e9:'DC_GPIO_DDCVGA_A',0x28f1:'DC_GPIO_GENLK_A',0x28f5:'DC_GPIO_HPD_A',0x2911:'DC_GPIO_I2S_SPDIF_A',0x2f13:'DC_GPIO_PWRSEQ_A_Y'}
HPD_BITS = {0:'HPD1',8:'HPD2',16:'HPD3',24:'HPD4',26:'HPD5'}
gpio = {}
if 'gpio_pin_lut' in DT:
    o, ts, tf, tc = DT['gpio_pin_lut']
    n = (ts - 4) // 8
    print('\ngpio_pin_lut v%d.%d: %d entries (data_a_reg_index is absolute dword; DCN seg2 base = 0x34c0)' % (tf, tc, n))
    for i in range(n):
        p = o + 4 + 8*i
        reg, sh, msh, gid = u32(p), u8(p+4), u8(p+5), u8(p+6)
        rel = reg - 0x34c0
        nm = GPIO_REGS.get(rel, '?')
        extra = ''
        if nm == 'DC_GPIO_HPD_A':
            extra = HPD_BITS.get(sh, '')
        if gid & 0x80:
            extra += ' I2C_HW engine=%d line=%d' % ((gid >> 4) & 7, gid & 0xf)
        gpio[gid] = (reg, sh, nm, extra)
        print('  gpio_id %#04x reg %#06x (seg2+%#06x %-20s) bitshift %2d %s' % (gid, reg, rel, nm, sh, extra))

# ---------- display object table ----------
CONN = {0x0C:'HDMI_TYPE_A',0x13:'DISPLAYPORT',0x14:'eDP',0x17:'USBC',0x03:'DUAL_LINK_DVI_I?',0x02:'SINGLE_LINK_DVI_I?'}
ENC = {0x1E:'INTERNAL_UNIPHY',0x20:'INTERNAL_UNIPHY1',0x21:'INTERNAL_UNIPHY2',0x25:'INTERNAL_UNIPHY3'}
TRANS = {(0x1E,1):'TRANSMITTER_UNIPHY_A (PHY A)',(0x1E,2):'TRANSMITTER_UNIPHY_B (PHY B)',(0x20,1):'TRANSMITTER_UNIPHY_C (PHY C)',(0x20,2):'TRANSMITTER_UNIPHY_D (PHY D)',(0x21,1):'TRANSMITTER_UNIPHY_E',(0x21,2):'TRANSMITTER_UNIPHY_F',(0x25,1):'TRANSMITTER_UNIPHY_G'}
DEVTAG = {0x0002:'LCD1',0x0020:'LCD2',0x0008:'DFP1',0x0080:'DFP2',0x0200:'DFP3',0x0400:'DFP4',0x0800:'DFP5',0x0040:'DFP6'}
REC = {1:'I2C',2:'HPD_INT',3:'CONNECTOR_CAP',4:'CONNECTOR_SPEED_UPTO',9:'OBJECT_GPIO_CNTL',16:'HPDPIN_LUT',17:'AUXDDC_LUT',20:'ENCODER_CAP',21:'BRACKET_LAYOUT',22:'FORCED_TMDS_CAP',23:'DISP_CONNECTOR_CAPS',25:'BRACKET_LAYOUT_V2'}
def objstr(oid):
    t = (oid >> 12) & 7; e = (oid >> 8) & 7; i = oid & 0xff
    if t == 3: return 'CONNECTOR %s enum%d (%#06x)' % (CONN.get(i, hex(i)), e, oid)
    if t == 2: return 'ENCODER %s enum%d (%#06x)' % (ENC.get(i, hex(i)), e, oid)
    return 'type%d id%#x enum%d (%#06x)' % (t, i, e, oid)

def records(base, off):
    p = base + off
    out = []
    for _ in range(32):
        rt, rs = u8(p), u8(p+1)
        if rt == 0xff or rs == 0: break
        body = rom[p+2:p+rs]
        desc = REC.get(rt, 'type%d' % rt)
        if rt == 1:
            iid, sl = body[0], body[1]
            desc += ' i2c_id=%#04x (hw_cap=%d engine=%d line=%d) slave=%#x' % (iid, iid >> 7, (iid >> 4) & 7, iid & 0xf, sl)
            if iid in gpio: desc += ' -> %s' % gpio[iid][2]
        elif rt == 2:
            desc += ' pin_id=%#04x plugin_state=%d' % (body[0], body[1])
            if body[0] in gpio: desc += ' -> %s %s' % (gpio[body[0]][2], gpio[body[0]][3])
        elif rt == 20:
            caps = struct.unpack_from('<I', body)[0]
            bits = {0x1:'MST_EN',0x2:'HBR2_EN',0x4:'HDMI6Gbps_EN',0x8:'HBR3_EN',0x10:'DP2',0x20:'UHBR10_EN',0x40:'UHBR13_5_EN',0x80:'UHBR20_EN',0x100:'USB_C_TYPE'}
            desc += ' encodercaps=%#x %s' % (caps, [n for b, n in bits.items() if caps & b])
        elif rt == 23:
            desc += ' connectcaps=%#x' % struct.unpack_from('<I', body)[0]
        elif rt == 4:
            desc += ' connector_max_speed=%d MHz' % struct.unpack_from('<I', body)[0]
        elif rt == 25:
            desc += ' bracketlen=%d width=%d conn_num=%d mini_type=%d' % (body[0], body[1], body[2], body[3])
        elif rt == 21:
            desc += ' raw=%s' % body.hex()
        elif rt == 22:
            desc += ' maxtmdsclk=%d MHz' % (body[0]*2.5)
        else:
            desc += ' raw=%s' % body.hex()
        out.append(desc)
        p += rs
    return out

if 'displayobjectinfo' in DT:
    o, ts, tf, tc = DT['displayobjectinfo']
    supp, npath = u16(o+4), u8(o+6)
    print('\ndisplayobjectinfo v%d.%d size %d: supporteddevices %#x number_of_path %d' % (tf, tc, ts, supp, npath))
    psz = 16 if tc == 5 else 16
    for i in range(npath):
        p = o + 8 + i*psz
        if tc == 5:
            dob, drec, enc, r1, r2, r3, tag, r4 = struct.unpack_from('<8H', rom, p)
        else:
            dob, drec, enc, ext, erec, eext, tag = struct.unpack_from('<7H', rom, p)
        e_id = enc & 0xff; e_en = (enc >> 8) & 7
        print('  path %d: %s' % (i, objstr(dob)))
        print('          encoder %s -> %s' % (objstr(enc), TRANS.get((e_id, e_en), '?')))
        print('          device_tag %#06x (%s) disp_recordoffset %#x' % (tag, DEVTAG.get(tag, '?'), drec))
        for r in records(o, drec):
            print('          record: ' + r)

# ---------- vram usage ----------
if 'vram_usagebyfirmware' in DT:
    o, ts, tf, tc = DT['vram_usagebyfirmware']
    print('\nvram_usagebyfirmware v%d.%d' % (tf, tc))
    if tc >= 2:
        print('  fw_region_start_address_in_kb %#x used_by_firmware_in_kb %d driver_region0_start_kb %#x used_by_driver_region0_kb %d' % (u32(o+4), u16(o+8), u32(o+12), u32(o+16)))
    else:
        print('  start_address_in_kb %#x used_by_firmware_in_kb %d used_by_driver_in_kb %d' % (u32(o+4), u16(o+8), u16(o+10)))

for k in ('smu_info', 'umc_info', 'vram_info', 'integratedsysteminfo', 'lcd_info', 'powerplayinfo', 'gfx_info', 'multimedia_info', 'voltageobject_info', 'asic_profiling_info', 'smc_dpm_info', 'indirectioaccess', 'utilitypipeline'):
    if k in DT:
        o, ts, tf, tc = DT[k]
        print('%-22s present v%d.%d size %d' % (k, tf, tc, ts))
    else:
        print('%-22s ABSENT' % k)

if 'smu_info' in DT:
    o, ts, tf, tc = DT['smu_info']
    print('\nsmu_info v%d.%d raw first 64 bytes: %s' % (tf, tc, rom[o:o+64].hex()))
