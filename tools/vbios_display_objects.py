#!/usr/bin/env python3
"""Mappa dei connettori dal VBIOS AtomBIOS (atomfirmware) di una scheda RDNA4.

Legge la tabella displayobjectinfo (v1.4/v1.5) e la tabella gpio_pin_lut e stampa, per ogni percorso
display: connettore, encoder (-> PHY / transmitter UNIPHY_x), linea DDC/AUX, pin HPD, capacita'
dell'encoder (HBR3, UHBR, HDMI 6G) e posizione sulla staffa. Sostituisce le costanti per scheda di
Cobalt64 (navi48_disp2.h), come fa Linux in dc/bios/bios_parser2.c.

Strutture da drivers/gpu/drm/amd/include/atomfirmware.h e ObjectID.h (Linux, MIT).

Uso: tools/vbios_display_objects.py research/hw_dump/vbios.rom [--json out.json]
     opzionale: --regs <dcn_X_offset.h> per dare un nome ai registri GPIO
"""
import json
import re
import struct
import sys

# ObjectID.h
OBJ_TYPE = {1: "GPU", 2: "ENCODER", 3: "CONNECTOR", 4: "ROUTER", 5: "GENERIC"}
CONNECTOR = {0x01: "DVI-I single", 0x02: "DVI-I dual", 0x03: "DVI-D single", 0x04: "DVI-D dual",
             0x05: "VGA", 0x0C: "HDMI-A", 0x0D: "HDMI-B", 0x0E: "LVDS", 0x13: "DisplayPort",
             0x14: "eDP", 0x16: "LVDS eDP", 0x17: "USB-C"}
# encoder id + enum -> transmitter (bios_parser2.c / bios_parser_helper: UNIPHY enum 1 = link A, 2 = B...)
UNIPHY = {0x1E: "AB", 0x20: "CD", 0x21: "EF", 0x25: "G"}
DEVICE_TAG = {0x0002: "LCD1", 0x0020: "LCD2", 0x0008: "DFP1", 0x0080: "DFP2", 0x0200: "DFP3",
              0x0400: "DFP4", 0x0800: "DFP5", 0x0040: "DFP6"}
ENC_CAPS = [(0x01, "MST"), (0x02, "HBR2"), (0x04, "HDMI6G"), (0x08, "HBR3"), (0x10, "DP2"),
            (0x20, "UHBR10"), (0x40, "UHBR13.5"), (0x80, "UHBR20"), (0x100, "USB-C")]
# dcn_4_1_0_sh_mask.h: DC_GPIO_HPD_A__DC_GPIO_HPDn_A__SHIFT -> HPD n (hw_translate_dcn401.c)
HPD_SHIFT = {0x00: "HPD1", 0x08: "HPD2", 0x10: "HPD3", 0x18: "HPD4", 0x1A: "HPD5", 0x1C: "HPD6"}
REC = {1: "I2C", 2: "HPD_INT", 3: "CONNECTOR_CAP", 4: "CONNECTOR_SPEED", 9: "GPIO_CNTL", 16: "HPDPIN_LUT",
       17: "AUXDDC_LUT", 20: "ENCODER_CAP", 21: "BRACKET_LAYOUT", 22: "FORCED_TMDS_CAP",
       23: "DISP_CONNECTOR_CAPS", 25: "BRACKET_LAYOUT_V2"}
MASTER_DATA = ["utilitypipeline", "multimedia_info", "smc_dpm_info", "sw_datatable3", "firmwareinfo",
               "sw_datatable5", "lcd_info", "sw_datatable7", "smu_info", "sw_datatable9",
               "sw_datatable10", "vram_usagebyfirmware", "gpio_pin_lut", "sw_datatable13", "gfx_info",
               "powerplayinfo", "sw_datatable16", "sw_datatable17", "sw_datatable18",
               "sw_datatable19", "sw_datatable20", "sw_datatable21", "displayobjectinfo",
               "indirectioaccess", "umc_info", "sw_datatable25", "sw_datatable26", "dce_info",
               "vram_info", "sw_datatable29", "integratedsysteminfo", "asic_profiling_info",
               "voltageobject_info", "sw_datatable33", "sw_datatable34"]


def u8(b, o): return b[o]
def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]


def objid(v):
    return {"raw": v, "type": OBJ_TYPE.get((v >> 12) & 7, "?%d" % ((v >> 12) & 7)),
            "enum": (v >> 8) & 7, "id": v & 0xFF}


def transmitter(v):
    o = objid(v)
    if o["type"] != "ENCODER":
        return None
    pair = UNIPHY.get(o["id"])
    if not pair or o["enum"] < 1 or o["enum"] > len(pair):
        return "encoder 0x%02x enum %d" % (o["id"], o["enum"])
    return "UNIPHY_" + pair[o["enum"] - 1]


def load_reg_names(path):
    names = {}
    if not path:
        return names
    for line in open(path):
        m = re.match(r"#define\s+reg(DC_GPIO_\w+)\s+(0x[0-9a-fA-F]+)", line)
        if m:
            names[int(m.group(2), 16)] = m.group(1)
    return names


def parse(rom, reg_names):
    if rom[0:2] != b"\x55\xaa":
        raise SystemExit("non e' una ROM PCI (manca 55 AA)")
    hdr = u16(rom, 0x48)
    if rom[hdr + 4:hdr + 8] != b"ATOM":
        raise SystemExit("header ATOM non trovato a 0x%x" % hdr)
    master = u16(rom, hdr + 8 + 2 * 12)  # masterdatatable_offset (13o campo u16 dopo "ATOM")
    tables = {n: u16(rom, master + 4 + 2 * i) for i, n in enumerate(MASTER_DATA)}
    out = {"rom_header": hdr, "master_data_table": master,
           "subsystem": "%04x:%04x" % (u16(rom, hdr + 8 + 2 * 8), u16(rom, hdr + 8 + 2 * 9))}

    # gpio_pin_lut v2.1: header + N x {u32 data_a_reg_index, u8 bitshift, u8 mask_bitshift, u8 gpio_id, u8 rsvd}
    gpio = {}
    g = tables["gpio_pin_lut"]
    if g:
        size = u16(rom, g)
        for o in range(g + 4, g + size, 8):
            reg, shift, mshift, gid = u32(rom, o), u8(rom, o + 4), u8(rom, o + 5), u8(rom, o + 6)
            gpio[gid] = {"gpio_id": gid, "reg_index": reg, "bitshift": shift, "mask_bitshift": mshift}
    # l'indice e' assoluto (base del segmento DMU + offset dell'header Linux): si sceglie la base che
    # da' un nome al maggior numero di pin, contando solo i registri "_A" (la LUT punta sempre a quelli:
    # DC_GPIO_DDCn_A, DC_GPIO_HPD_A...); i DC_GPIO_* sono troppo fitti per contarli tutti
    a_regs = {off: n for off, n in reg_names.items() if n.endswith("_A")}
    best, seg = 0, None
    for b in {p["reg_index"] - off for p in gpio.values() for off in a_regs}:
        n = sum(1 for p in gpio.values() if p["reg_index"] - b in a_regs)
        if n > best:
            best, seg = n, b
    for p in gpio.values():
        p["reg_name"] = reg_names.get(p["reg_index"] - seg) if seg is not None else None
    out["gpio_segment_base"] = seg
    out["gpio_pins"] = sorted(gpio.values(), key=lambda p: p["gpio_id"])

    t = tables["displayobjectinfo"]
    size, frev, crev = u16(rom, t), u8(rom, t + 2), u8(rom, t + 3)
    supported, npath = u16(rom, t + 4), u8(rom, t + 6)
    out["displayobjectinfo"] = {"offset": t, "size": size, "rev": "%d.%d" % (frev, crev),
                                "supported_devices": supported}
    paths = []
    for i in range(npath):
        p = t + 8 + i * 16
        disp, drec, enc = u16(rom, p), u16(rom, p + 2), u16(rom, p + 4)
        if crev >= 5:
            tag = u16(rom, p + 12)
            erec = 0
        else:
            erec, tag = u16(rom, p + 8), u16(rom, p + 12)
        c = objid(disp)
        path = {"index": i, "connector_objid": "0x%04x" % disp,
                "connector": CONNECTOR.get(c["id"], "0x%02x" % c["id"]), "connector_enum": c["enum"],
                "encoder_objid": "0x%04x" % enc, "transmitter": transmitter(enc),
                "device_tag": DEVICE_TAG.get(tag, "0x%04x" % tag), "records": []}
        for base in (drec, erec):
            if not base:
                continue
            o = t + base  # offset dei record relativo all'inizio della tabella (bios_parser2)
            while o < len(rom) - 2 and rom[o] != 0xFF and rom[o + 1] != 0:
                rtype, rsize = rom[o], rom[o + 1]
                r = {"type": REC.get(rtype, rtype), "raw": rom[o:o + rsize].hex()}
                if rtype == 1:
                    iid = rom[o + 2]
                    r.update(i2c_id="0x%02x" % iid, hw_cap=bool(iid & 0x80), engine=(iid & 0x70) >> 4,
                             line=iid & 0x0F, slave=rom[o + 3])
                    pin = gpio.get(iid)
                    if pin:
                        r["gpio"] = pin["reg_name"] or "reg 0x%x" % pin["reg_index"]
                elif rtype == 2:
                    pid = rom[o + 2]
                    r.update(hpd_gpio_id=pid, plugin_state=rom[o + 3])
                    pin = gpio.get(pid)
                    if pin:
                        r["gpio"] = pin["reg_name"] or "reg 0x%x" % pin["reg_index"]
                        r["gpio_bitshift"] = pin["bitshift"]
                        if pin["reg_name"] == "DC_GPIO_HPD_A" and pin["bitshift"] in HPD_SHIFT:
                            r["hpd"] = HPD_SHIFT[pin["bitshift"]]
                elif rtype == 4:
                    r["max_speed_mhz"] = u32(rom, o + 2)
                elif rtype == 20:
                    caps = u32(rom, o + 2)
                    r.update(caps="0x%x" % caps, caps_names=[n for b, n in ENC_CAPS if caps & b])
                elif rtype in (3, 23):
                    r["caps"] = "0x%x" % (u16(rom, o + 2) if rtype == 3 else u32(rom, o + 2))
                elif rtype == 22:
                    r["max_tmds_mhz"] = rom[o + 2] * 2.5
                elif rtype == 25:
                    r.update(bracket_len_mm=rom[o + 2], bracket_width_mm=rom[o + 3],
                             conn_num=rom[o + 4], mini=rom[o + 5])
                elif rtype == 21:
                    r.update(bracket_len_mm=rom[o + 2], bracket_width_mm=rom[o + 3], conn_num=rom[o + 4])
                path["records"].append(r)
                o += rsize
        paths.append(path)
    out["paths"] = paths
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    jpath = regs = None
    if "--json" in args:
        jpath = args[args.index("--json") + 1]
    if "--regs" in args:
        regs = args[args.index("--regs") + 1]
    rom = open(args[0], "rb").read()
    info = parse(rom, load_reg_names(regs))
    d = info["displayobjectinfo"]
    print("VBIOS: header ATOM 0x%x, displayobjectinfo v%s a 0x%x, subsystem %s, %d percorsi"
          % (info["rom_header"], d["rev"], d["offset"], info["subsystem"], len(info["paths"])))
    for p in info["paths"]:
        print("\n[%d] %-12s (obj %s, enum %d)  encoder %s -> %s  tag %s"
              % (p["index"], p["connector"], p["connector_objid"], p["connector_enum"],
                 p["encoder_objid"], p["transmitter"], p["device_tag"]))
        for r in p["records"]:
            extra = {k: v for k, v in r.items() if k not in ("type", "raw")}
            print("     %-20s %s" % (r["type"], extra if extra else r["raw"]))
    if jpath:
        json.dump(info, open(jpath, "w"), indent=1)
        print("\nscritto " + jpath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
