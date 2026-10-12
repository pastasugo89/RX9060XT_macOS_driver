# Display della RX 9060 XT: dati raccolti e conseguenze per il port

Raccolti il 12/10/2026 su Linux 7.2.9-cachyos con `amdgpu` caricato, **in sola lettura** (sysfs, debugfs,
journal). Nessun registro scritto, nessun file debugfs scrivibile toccato (`force`, `trigger_hotplug`,
`test_pattern`, `edid_override`, `sdp_message` esclusi).

| File | Contenuto |
|---|---|
| `connectors/<nome>/` | sysfs per connettore: `status`, `enabled`, `dpms`, `modes`, `edid.bin` (solo DP-1 ha un monitor) |
| `connectors/DP-1/edid_decoded.txt` | `edid-decode` dell'EDID del monitor |
| `debugfs/connector_*.txt` | `link_settings`, `phy_settings`, bpc, DSC, LTTPR, HDCP, VRR per connettore |
| `debugfs/drm_atomic_state.txt` | stato atomico DRM: CRTC, piani, framebuffer, connettori |
| `debugfs/dtn_log_active.txt` | DTN log **con il monitor acceso** (quello in `hw_dump/` era a pipe spente) |
| `debugfs/framebuffers.txt`, `debugfs/dm_capabilities.txt` | framebuffer DRM, capacità DM |
| `vbios_display_objects.{txt,json}` | tabella degli oggetti display del VBIOS, decodificata da `tools/vbios_display_objects.py` |

## 1. Connettori (VBIOS `displayobjectinfo` v1.5)

VBIOS 113-P816G493-S05, scheda Sapphire (subsystem `1da2:a493`). Tre percorsi, nessun PHY D:

| # | Connettore | Encoder | PHY | DIG | DDC/AUX (linea I2C) | HPD | Velocità max (VBIOS) | DRM Linux |
|---|---|---|---|---|---|---|---|---|
| 1 | DisplayPort | `0x211e` UNIPHY enum 1 | **UNIPHY_A** | DIGA | DDC1 / AUX0 (linea 0) | **HPD1** | 13 500 MHz (UHBR13.5) | DP-1 |
| 2 | HDMI-A | `0x221e` UNIPHY enum 2 | **UNIPHY_B** | DIGB | DDC2 (linea 1) | **HPD2** | 10 000 MHz | HDMI-A-1 |
| 3 | HDMI-A | `0x2120` UNIPHY1 enum 1 | **UNIPHY_C** | DIGC | DDC3 (linea 2) | **HPD3** | 10 000 MHz | HDMI-A-2 |

I pin GPIO sono indirizzi assoluti nel segmento DMU 2 (base `0x34c0` dalla tabella discovery):
`DC_GPIO_DDC1_A` `0x28d1`, `DC_GPIO_HPD_A` `0x28f5` con shift 0/8/16 = HPD1/2/3. Il blocco DMU in
discovery è **4.1.0**, lo stesso di Navi 48: gli offset `dcn_4_1_0` e il codice `dcn41` di Cobalt64 valgono
anche qui.

## 2. Monitor e modo attivo

- **LG UltraGear** (GSM 23687, 2025), 2560x1440, 10 bpc, HDR (blocco HDR static metadata), HDCP 1.4/2.2.
  Timing: 144 Hz (DTD base, 604,25 MHz), 120/100/60 Hz (CTA), **180 Hz preferito** nel blocco DisplayID 1.2
  Type I (719,55 MHz; front 48/3, sync 32/10, +H −V).
- Modo attivo sotto KWin: **2560x1440 a 180 Hz** su crtc-0, framebuffer `AB48` (16 bit per canale), modifier
  GFX12 `0x200000000082305` con DCC.
- **Link DP: 4 lane HBR3 (8,1 Gbps)**, già addestrato, niente DSC né FEC, nessun LTTPR, 10 bpc in uscita.
  A 10 bpc servono 21,6 Gbps, quindi HBR3 x4 (25,92) è il minimo; a 8 bpc basterebbe HBR2 x4.

## 3. Pipeline DCN (DTN log a 180 Hz)

- **ODM combine 2:1**: HUBP0 e HUBP1 da 1280x1440 ciascuno → DPP0/1 → MPCC0/1 → OPP0/1 → **un solo OTG0**.
- OTG0: `htot 2719 vtot 1469 h_bs 2672 h_be 112 h_se 32 hpol 0 v_bs 1467 v_be 27 v_se 10 vpol 1`.
- Link encoder 0 (PHY A): `DP_LINK_TRAINING_COMPLETE = 1`; gli altri due a 0.
- Clock: dispclk 367 MHz, dppclk 362 MHz, dcfclk 233 MHz, fclk 307 MHz, socclk 417 MHz.
- **Perché ODM 2:1**: dispclk e dppclk arrivano a 2 GHz (`dcn4_soc_bb.h`), ma `vmin_limit.dispclk_khz = 600000`.
  Con 719 MHz su una pipe sola la GPU dovrebbe alzare la tensione; con due pipe a ~360 MHz resta alla
  minima. È una scelta di consumo, non un limite. Una pipe sola a 180 Hz è possibile, ma richiede di chiedere
  allo SMU un dispclk sopra 600 MHz (vale anche per i 165 Hz di Cobalt64, a 646 MHz).
- HUBP: `sw_mode 3h`, `dcc_en 1`, formato `1ah` (il framebuffer AB48 di KWin).

Al boot c'era un framebuffer del firmware (`simpledrm` nel journal), quindi il GOP accende lo schermo prima
del sistema operativo. **Su quale pipe lo accenda (OTG, DIG FE, PHY) non è ancora osservato**: serve un avvio
con `amdgpu` in blacklist (fase 0.5, ultimo punto).

## 4. Conseguenze per Cobalt64

Cobalt64 non fa link training DP: **adotta l'uscita DP che il GOP ha già acceso** (`dcn41_otg_timing`, "same-mode
re-timing" e poi cambi di timing sullo stesso link) e accende gli HDMI aggiuntivi da sé, tramite DMUB.

| Risorsa | Scheda di Cobalt64 (RX 9070 XT) | Nostra scheda (RX 9060 XT) |
|---|---|---|
| DP del GOP (protetto dalla guardia di `disp2`) | OTG0 / **DIG1 / PHY B / DP_AUX1** / HPD2 | OTG0 / **DIG0 / PHY A / AUX0** / HPD1 (da confermare col GOP) |
| Istanza HDMI 1 di `disp2` ("monitor A") | OTG1 / DIG2 / PHY C / ddc2 / hpd3 | **identica**: il nostro HDMI-A-2 è PHY C / linea 2 / HPD3 |
| Istanza HDMI 2 di `disp2` ("monitor B") | OTG2 / DIG3 / **PHY D** / ddc3 / hpd4 | **non esiste**: va sostituita con OTG2 / DIG1 / **PHY B** / linea 1 / HPD2 |

Quindi, sulla nostra scheda:

1. La guardia di `navi48_disp2.h` vieta DIG1, PHY B e DP_AUX1 (la pipe del GOP *loro*). Va resa per scheda:
   da noi va protetto DIG0/PHY A/AUX0, mentre DIG1/PHY B diventano l'istanza del primo HDMI.
2. L'istanza 2 (`N48D2_INST_MONB`, generata dall'istanza 1 rinominando DIG2→DIG3, SYMCLKC→SYMCLKD, FE2→FE3,
   UNIPHY_C→UNIPHY_D) va rigenerata con DIG2→DIG1, SYMCLKC→SYMCLKB, FE2→FE1, UNIPHY_C→UNIPHY_B, OTG2 invariato.
3. I comandi DMUB (`navi48_dmubcmd.h`: `phyc`/`phyd enable`, `pclk otg1/otg2`, ddc3/hpd4, PLL) vanno adattati:
   PHY B al posto di PHY D.
4. `navi48_modetrial_*` e `Navi48NativeABI.h` danno per scontati OTG0 + DIG1 per il DP: da noi DIG0.
5. Tabella dei modi: **fatta** (`cobalt64/src/dcn41/dcn41_modes_navi44.h`, generata dall'EDID).

I punti 1-4 toccano allowlist di registri scritte a mano, ciascuna verificata dai loro test host. Si fanno
**dopo** aver osservato la pipe del GOP, perché è da quella che dipende cosa proteggere.

## Come rifare la raccolta

```sh
tools/vbios_display_objects.py research/hw_dump/vbios.rom \
  --regs research/src/linux/drivers/gpu/drm/amd/include/asic_reg/dcn/dcn_4_1_0_offset.h --json out.json
ASIC=navi44 python3 cobalt64/tools/dcn41/gen_modes.py      # tabella dei modi (da tools/dcn41/boards/navi44/)
```
