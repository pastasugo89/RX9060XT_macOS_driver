# Percorso primario su Navi 44: desktop nativo su un monitor DP

Audit del 20/10/2026. Sola lettura del codice più due modifiche di verifica (nessuna VM avviata, nessun commit).
Ground truth: dump boot15 `research/hw_dump/gop_dump_stage1_boot15_rombar1_serial.log` (vedi `gop_vm_readout_plan.md` §9).

## 0. Sintesi

- **Nessuna parte necessaria al percorso primario è stata rifiutata su Navi 44.** M6, disp2, dmubcmd e mode trial non sono
  richiesti dal desktop su un DP: il link è già addestrato dal GOP e la modalità è la stessa (nessun cambio di timing).
- **Nessun DIG1 / PHY B / SYMCLKB / DP1 cablato nel percorso primario.** Verificato con grep su `apple/`, `amd/native_disp*`,
  `amd/native_s1b*`, `amd/native_s1c.cpp`, `Navi48NativeClient.cpp`, `Navi48UserClient.cpp`, `Navi48Bringup.cpp`: zero occorrenze.
  Le occorrenze residue sono in `navi48_disp2*` (refused su Navi 44), `navi48_dispread` e `navi48_gopsnap` (sola lettura,
  dati), `navi48_modetrial_pure.h` (già derivato da `navi48_disp_profile.h`, refused su Navi 44).
- **BLOCCANTE B1 (pitch):** la superficie del GOP ha pitch 0x033f = 832 px. Il kext accetta solo `pitchPx >= width`
  (`dcn/navi48_scanout_pure.h:50-57`, `geom_check`) e il mode trial richiede `pitchPx == 2560`
  (`dcn/navi48_dcn.cpp:2134`). Il kext non scrive mai `DCSURF_SURFACE_PITCH` (`kOffSurfPitch` è solo letto,
  `navi48_dcn.cpp:481,585,1393,1495`). Quindi lo scanout del GOP viene rifiutato, oppure, se il pitch non viene
  riprogrammato, scandito con passo sbagliato. Non risolto: serve il boot successivo con i registri di viewport (§3).
- **Due modifiche di questo passo:** `navi48_gopsnap.h` ora legge anche viewport e tiling del HUBP0 (164 righe, non 160).
  Nessun altro codice di percorso primario è cambiato.

## 1. Traccia end-to-end (Navi 44, multi-display OFF)

| Stadio | Dove | Registri / oggetti | Note |
|---|---|---|---|
| 1. Adozione pipe GOP | `dcn/navi48_dcn.cpp:252-261` (`lit_otg`), `:1682-1712` (`vbl_refresh`); `amd/native_disp_flow.h:470-485` (`adopt_inner`) | OTG0 (lit), DCCG `DP_DTO0` per il clock (BASE_IDX 1) | L'adozione (verbo 83 `pipeadopt`) non scrive registri: lavora su oggetti Apple (`accel_layout_ok`, `probe_pipe`, `pipe_ok` in `native_disp_pure.h:187-199`). |
| 2. Aux path (fbpublish) | `Navi48DisplayNub.cpp:51-60, 108-140` | `navi48-fb2` | Non serve. Con fb2 attivo il nub di display blocca `pipeadopt`/`pipearm` tramite `fb_interlock_refuses` (`native_disp.cpp:698`). **fb2 deve restare assente.** |
| 3. Verbi del kext principale | `Navi48UserClient.cpp:603`, `Navi48Bringup.cpp:7786`, `amd/native_disp.cpp:693` (`n48disp_verb`) | verbi 83-90; descrittori FBSC/FBVR (`Navi48UserClient.cpp:34-37`) | Latch `navi48-metal-disp=1` (`native_disp.cpp:569-579`). `pipeagdc` 88 richiede `navi48-agdc=1` (`DisplayPipeGuard.cpp:2008-2015`). |
| 4. Selettori DP | `Navi48NativeClient.cpp:208-224` | `n48dcn::bind` su SCAN_QUERY/ACQUIRE/REGISTER/PRESENT/STATUS | `bind` è incondizionato. Solo i selettori SCANX monitor A/B sono sotto M6 (`:232-248`). |
| 5. Flip HUBP0 | `navi48_dcn.cpp:1835-1921` (`scanAcquire`), `:1964-2000` (`scanPresent`) → `src/dcn41/dcn41_hubp.c:14` | HUBP0 `PRIMARY_SURFACE_ADDRESS(_HIGH)`, `DCSURF_FLIP_CONTROL`, `VMID_SETTINGS_0`, `SURFACE_CONTROL` | Scrive solo indirizzo e controlli di flip. Nessun lock OTG master (`dcn41_otg_lock` senza chiamanti): il flip si latcha al VUPDATE successivo. |
| 6. Vblank e IRQ | `Navi48Bringup.cpp:7199-7228` → `navi48_dcn.cpp:669-757` (`ihEntry`), `:1531-1560` (`scanIrq`) | VUPDATE_NO_LOCK su OTG0 (`:1880-1883`) | Non verificato su Navi 44: i registri IRQ non sono nel dump. |
| 7. Watchdog | `navi48_dcn.cpp:1645-1665` (`scan_watchdog_loop`, 50 ms), `:1561-1640` (`scan_restore`), `navi48_scanout_pure.h:25,249` (idle 5 s) | HUBP0 address (restore a `fb` console) | `scanShutdown` attende il thread (`navi48_dcn.hpp:182`). |
| 8. Autoarm | `tools/pc/arm-gpu-desktop.sh`, `tools/pc/autoarm/n48-autoarm.sh` | §5 | Solo `arm-gpu-desktop.sh` è compatibile con un monitor DP. |

## 2. Registri per istanza, confronto con il dump Navi 44

Legenda: **sì** = il registro usato dal percorso ha su Navi 44 lo stesso valore/istanza osservato; **no** = istanza diversa;
**?** = non letto nel dump, non verificabile.

| Registro (dword) | Istanza | Usato in | Dump Navi 44 | Esito |
|---|---|---|---|---|
| `OTG0_OTG_CONTROL` (0x05003) | OTG0 | `lit_otg`, gopsnap | 0x00011201 (master en) | sì |
| `OTG0_OTG_H_TOTAL` / `H_BLANK` (0x04fea/0x04feb) | OTG0 | RASTER_OK | 0xa9f / 0x00700a70 | sì |
| `OTG0_OTG_V_TOTAL` / `V_BLANK` (0x04fef/0x04ff8) | OTG0 | modo | 0x5f4 / 0x005205f2 | sì (vse 10 non letto) |
| `OTG0_OTG_STATUS_FRAME_COUNT` (0x1b4d) | OTG0 | liveness | 3866 → 3872 in 50 ms | sì |
| `OTG0_OTG_MASTER_UPDATE_LOCK` (0x05049) | OTG0 | non scritto dal kext | 0 | sì |
| `HUBPREQ0_DCSURF_PRIMARY_SURFACE_ADDRESS` (0x03aca/0x03acb) | HUBP0 | `fmReadPrimary` `:1410`, `scan_restore` `:1601`, flip | 0x80_00000000 | sì (VRAM offset 0) |
| `HUBPREQ0_DCSURF_SURFACE_PITCH` (0x03ac7) | HUBP0 | `:585,1393,1495` (solo lettura) | 0x033f = 832 px | **no** (B1) |
| `HUBP0_DCHUBP_CNTL` (0x03ab4) | HUBP0 | underflow | 0x000f0002 | sì |
| `HUBP0_DCSURF_SURFACE_CONFIG` (0x03aa5) | HUBP0 | `fmHubpGeom` `:1389`, check formato | 0x08 = ARGB8888 | sì (vedi §3) |
| `HUBP0_DCSURF_ADDR_CONFIG` / `TILING_CONFIG` (0x05e6/0x05e7) | HUBP0 | geometria | non letto (ora in gopsnap) | **?** |
| `HUBP0_DCSURF_PRI_VIEWPORT_START/DIMENSION` (0x05e9/0x05eb) | HUBP0 | `scan_read_geom` `:1493` | non letto (ora in gopsnap) | **?** |
| `HUBP0_DCSURF_FLIP_CONTROL`, `VMID_SETTINGS_0`, `SURFACE_CONTROL` | HUBP0 | flip | non letti | **?** |
| `DPP_TOP0_DPP_CONTROL` (0x04185) | DPP0 | pipeline | 0x70000010 (clock on) | sì |
| `MPCC0_MPCC_CONTROL` (0x09003) | MPCC0 | pipeline | 0xffff0461 | sì |
| `OPP_PIPE0_OPP_PIPE_CONTROL` (0x04d4c) | OPP0 | pipeline | 0x3 (clock on) | sì |
| `ODM0_OPTC_DATA_SOURCE_SELECT` (0x04f8b) | ODM0 | non usato dal kext | 0xfff00000 | non decodificato |
| `DIG0_DIG_FE_CNTL` / `FE_EN` (0x05553/0x05555) | DIG0 | gopsnap | src 0 (OTG0) / 1 | sì |
| `DIG0_DIG_BE_CNTL` (0x0557c) | DIG0 | gopsnap | 0x100 (FE0) | sì |
| `DIG0_STREAM_MAPPER_CONTROL` (0x053cd) | DIG0 | gopsnap | 0 (link 0 = PHY A) | sì |
| `DP0_DP_LINK_CNTL` (0x055de) | DP0 | gopsnap | 0x110 (training complete) | sì |
| `DP0_DP_VID_STREAM_CNTL` (0x055e2) | DP0 | `kRegDpStream[kLitDp]` (derivato) | 0x00010201 | sì |
| `SYMCLKA_CLOCK_ENABLE` (0x00160) | SYMCLKA | gopsnap | 0x11 | sì |
| `UNIPHYA_LINK_CNTL` (0x05d2d) | PHY A | gopsnap | 0 | non decodificato |
| `RDPCSTX0_RDPCSTX_CNTL` (0x05df0) | PHY A | gopsnap | 0xffffffff (non leggibile) | **?** |
| `HPD1_DC_HPD_INT_STATUS` (0x04c22) | HPD1 | gopsnap | 0 | sì (non indica presenza) |
| `DMCUB_SCRATCH0` (0x036a3) | DMCUB | gopsnap | 0x82 (mailbox + power init) | sì |
| `DCSURF`-related IRQ (VUPDATE) | OTG0 | `scanIrq`, `ihEntry` | non letto | **?** |
| `DP_DTO0` (BASE_IDX 1, dword 0x80/0x81) | DCCG | `vbl_refresh` | non letto | **?** |
| `DP1_DP_VID_STREAM_CNTL` (0x05706) | DP1 | non usato (refused) | 0x00100200 | fuori percorso |
| `DIG1_DIG_BE_CLK_CNTL` (0x0569f) | DIG1 | non usato | 0x1 | fuori percorso |

## 3. Superficie: formato, pitch, tiling, modo

**Formato.** Il campo `SURFACE_PIXEL_FORMAT` del registro hardware non usa l'enum software di `dc_hw_types.h`. La
codifica del registro è quella di `research/src/.../display/dc/hubp/dcn20/dcn20_hubp.c` (righe 463-490):
ARGB1555 = 1, RGB565 = 3, ARGB8888/ABGR8888 = **8**, ARGB2101010 = 10, ARGB16161616_UNORM = **26 = 0x1a**,
ARGB16161616F = 24, video 4:2:0 YCbCr = 65.
- Il GOP scandisce **0x08 = ARGB8888, 32 bpp**. Il kext accetta solo questo (`kFmtArgb8888 = 8`, `geom_check`).
- **0x1a (DTN di KWin)** è ARGB16161616_UNORM = AB48, a 64 bpp. Coerente con il DTN `1ah` di `research/display/README.md`.
- Correzione: l'enum software dell'analisi non va usato per leggere `HUBPn_DCSURF_SURFACE_CONFIG`.

**Pitch.** Il campo `PITCH` vale `pitch − 1` (il codice `hubp401` scrive `surface_pitch − 1`; il kext lo legge con
`+1`). Il campo 0x033f = 831 corrisponde a **832 px**. Con 32 bpp sono 3328 byte per riga. Non corrisponde a una
superficie lineare 2560 px (serve 0x09ff) né a 1280 px per pipe (0x04ff). Due ipotesi da verificare con il dump successivo:
(a) la superficie GOP ha un viewport più stretto (832 px) e il pitch è giusto; (b) il pitch è in unità diverse per
un'altra modalità di tiling. In entrambi i casi il kext non può ancora accettarla (B1).

**Tiling e viewport.** Il dump non li contiene. `navi48_gopsnap.h` ora legge `HUBP0_DCSURF_ADDR_CONFIG` (0x05e6),
`TILING_CONFIG` (0x05e7: `SW_MODE` bit 2:0, `DIM_TYPE` bit 8:7), `PRI_VIEWPORT_START` (0x05e9) e
`PRI_VIEWPORT_DIMENSION` (0x05eb). Il boot successivo dirà la dimensione del viewport e il tiling reali. Il kext
accetta solo `SW_MODE 0` (lineare) e nessun DCC (`geom_check`, `kGeomTiling`, `kGeomDcc`).

**Modo.** Il GOP è `SINK-A 2560x1440@119.998` (riga CTA DTD di `cobalt64/src/dcn41/dcn41_modes_navi44.h`:
htot 2719, hse 32, hbs 2672, hbe 112, vtot 1524, vse 10, vbs 1522, vbe 82, clock 497,75 MHz). Il dump OTG0 coincide
campo per campo. Per questo modo non serve un mode trial: l'adozione è same-mode. Il mode trial su Navi 44 resta
rifiutato (golden same-mode non catturato).

**Dimensione scanout.** Il kext deriva la dimensione dalla console di RDNA4FB (`Console,Width/Height/RowBytes/Depth`,
`Navi48Bringup.cpp:2413-2436`), non dal registro HUBP. Quindi ci sono due fonti (console e HUBP) che il dump non
concilia. Il prossimo boot deve riportarle entrambe.

## 4. Confronto con il percorso Navi 48 (0.0.621)

Il desktop su un DP del 0.0.621 (`research/refs/7000-macos`) usava DIG1/PHY B/SYMCLKB/DP1 su Navi 48 e OTG0/HUBP0 per il
flip. Su Navi 44 il pipe primario è DIG0/PHY A/SYMCLKA/DP0 (tabella `N4X_DISP_DP_*`, `navi48_disp_profile.h`). OTG0 e HUBP0
sono gli stessi nei due profili, quindi il flip è indipendente dal profilo. Il percorso primario dipende dal profilo
solo nelle costanti DP/DIG/SYMCLK già parametrizzate.

## 5. Boot-args per un desktop nativo su un monitor DP (Navi 44)

Da `tools/pc/esp-config.sh` e dai lettori `PE_parse_boot_argn` del codice. "Assente" significa non passato.

| Boot-arg | Valore | Motivo |
|---|---|---|
| `navi48bringup` | 1 | attiva il kext |
| `navi48-stage` | 17 | boot S1b (la catena nativa richiede S1b positive) — **da confermare** (inferito da `esp-config.sh` e dal log S1b) |
| `navi48-native` | 1 | client nativo |
| `navi48-metal` | 1 | Metal nub; richiede il PASS positivo di S1b (`native_metal_pure.h:43`) |
| `navi48-metal-disp` | 1 | latch dei verbi 83-90 (`native_disp.cpp:569-579`) |
| `navi48-agdc` | 1 | `pipeagdc` 88 (`DisplayPipeGuard.cpp:2013`) |
| `navi48-metal-ws` | 1 | client WindowServer uid 88 (`Navi48NativeClient.cpp:64`) |
| `navi48-interrupts` | 1 (default) | IRQ attivi |
| `navi48-psp` | default (auto a stage ≥ 5) | |
| `navi48-accel-gate` | 1 (default) | |
| `navi48-multisession`, `navi48-apps` | assenti (default SINGLE) | |
| `navi48-fb2` | **assente** | con fb2 il nub di display blocca pipeadopt/pipearm |
| `navi48-m6`, `navi48-m6flip`, `navi48-m6flip1` | assenti | multi-display |
| `navi48-disp2`, `navi48-dmubcmd` | assenti | refused su Navi 44 |
| `navi48-row120`, `navi48-accel-experiment`, `navi48-boot-chain`, `navi48-*-test`, `navi48-eop-bridge`, `navi48-shader-cache` | assenti | conflitti con la maschera native S1b (`native_s1b_pure.h:160-165`) |
| `navi48-gopsnap` | assente per il desktop | diagnostica di sola lettura, solo per verifica |
| `navi48-dalsmc`, `navi48-mirror-gart`, `navi48-display-pairing` | assenti | non richiesti |
| `rdna4-off` | assente | `pipeadopt` richiede RDNA4FB |

## 6. Autoarm

- **`tools/pc/autoarm/n48-autoarm.sh`: non usare per un monitor.** Richiede sei argomenti (`navi48-m6`, `navi48-m6flip`,
  `navi48-fb2`, `navi48-metal-disp`, `navi48-disp2`, `navi48-dmubcmd`; riga 147), presume due monitor (monitor B
  2560x1440 e, opzionale, A 1920x1080), usa `disp2 status 2` come baseline DP e `disp2 crc` come riferimento CRC. Tutti
  questi sono refused su Navi 44.
- **`tools/pc/arm-gpu-desktop.sh`: il percorso compatibile.** Sequenza: `n48nub publish` (il **Metal** nub, non il
  display nub), `accel pipeadopt`, `accel fbname 1`, flag headless `/private/tmp/n48m-headless-no`, `accel pipearm 1`,
  `accel pipereload`, `killall -9 WindowServer`. Presume `navi48-metal-disp=1`, `navi48-agdc=1`, `navi48-metal`, ma **non
  li verifica**. Non ha valori CRC di riferimento. Non controlla geometria o pitch prima di `pipearm` (B1).
- **`tools/pc/autoarm/n48-autoarm-watch.sh`:** rimuove il flag headless al cambio di pid di WindowServer. Compatibile.
- **`tools/pc/display-topology.sh`:** dump ioreg in sola lettura, nessuna ipotesi.
- **`tools/pc/accel-run.sh`:** non letto per intero; riferisce la console 1920x1080 (riga 1565). Ipotesi su CRC e monitor: **?**.

Raccomandazione: per il desktop su Navi 44 serve uno script dedicato (basato su `arm-gpu-desktop.sh`) che verifichi
i boot-arg della tabella §5 prima di armare, e che legga la geometria HUBP (pitch, viewport) prima di `pipearm`.

## 7. Rischi residui e blocchi

- **B1 (bloccante) pitch 832 px.** `geom_check` rifiuta il pitch < width; `mt_otg_ok` richiede 2560. Il kext non riscrive
  il pitch. Opzioni: (a) il boot successivo dimostra che il viewport del GOP è 832 px e allora la superficie non è quella
  del desktop; (b) il viewport è 2560 e il pitch registrato è in altra unità, quindi `geom_check` va corretto; (c) il pitch
  va scritto esplicitamente con la larghezza della superficie del desktop, dietro `N4X_ASIC_NAVI44`. Decisione dopo il dump.
- **B2 fallback 1920x1080: CHIUSO nel codice (21/10/2026).** Il fallback è per profilo in `amd/asic_profile.h` (`N4X_AGDC_FB_*`):
  Navi 44 usa 2560x1440 con la riga SINK-A @120 di `dcn41_modes_navi44.h` (blanking 160/85, front 48/3, sync 32/10); Navi 48
  resta 1920x1080 con CEA 1080p60. Usato da `apple/display_pipe_guard.h` (`n48_agdc_timing_for`) e `apple/DisplayPipeGuard.cpp`
  (`agdc_endpoint`). Host: Navi 44 e Navi 48 con la baseline invariata (66 PASS / 12 FAIL / 28 BUILD / 3 NOCMD). Il pin T30 in
  `gfx_copyguard_test.cpp` non è eseguibile su Linux (fixture mancante, BUILD già in baseline). Restano fuori da B2, stesso
  tipo di fallback: `Navi48Bringup.cpp` (mode 6 case b, `n48_live_dim(..., 1920u)`) e `Navi48AccelPeer.cpp` (copia flush 1920).
  Verificare al boot che il raster live sia trovato (`dcn: read-only raster path BUILT`).
- **B3 IRQ/vblank non verificati su Navi 44.** Il dump non contiene i registri IRQ né `DP_DTO0`. `ihEntry`, `scanIrq` e
  `vbl_refresh` restano da confermare sul primo boot desktop.
- **B4 monitor B e tabelle M6.** `apple/`, `Navi48DisplayOps.h:28-55` (monitor A/B, 1920x1080 e 2560x1440 fissi): fuori
  dal percorso ma da non attivare su Navi 44.
- **B5 autoarm.** `n48-autoarm.sh` non è utilizzabile; `arm-gpu-desktop.sh` non verifica i propri presupposti (§6).
- **B6 catena nativa.** `navi48-metal=1` richiede il PASS positivo di S1b, e la catena stage17 + native + metal non è mai
  stata eseguita come desktop su Navi 44. Solo S1b (boot6) è PASS.
- **B7 modificatore.** `0x200000000082305` non è nel kext (solo nel golden vector xlat12). Se Apple alloca superfici
  tiled (swizzle 3) o con DCC, `geom_check` le rifiuta (`kGeomTiling`, `kGeomDcc`). Verificare il modificatore che
  WindowServer chiede.
- **B8 OPTC data source.** `ODM0_OPTC_DATA_SOURCE_SELECT` = 0xfff00000 non decodificato. Non usato dal kext, ma indica una
  configurazione di pipe da capire prima di un flip.
- **B9 spegnimento.** Il boot15 è terminato con `quit` QMP dopo ACPI senza completamento: nessun `vfs_unmountall(system) end`.
  Ogni boot desktop va chiuso con arresto regolare.
- **B10 mode trial.** Rifiutato su Navi 44. Il desktop non ne ha bisogno (same-mode), ma `mt_otg_ok` (B1) dipende dalla
  stessa geometria: se B1 si chiude, anche l'OTG ok resta un controllo da riscrivere per Navi 44.

## 8. Test

- `tools/linux-check-kext.sh`: 53/53 per Navi 44 e per Navi 48.
- `tools/hosttests/run.sh`: exit 0, incluso `test_gopsnap` (164 righe contro `dcn_4_1_0_offset.h`) e `test_disp_profile` per entrambi i profili.
- `tools/hosttests/run-cobalt64-tests.py`: Navi 44 e Navi 48 con 66 PASS, 12 FAIL, 28 BUILD, 3 NOCMD. Confronto per test con la
  baseline pre-modifica: identico per entrambi i profili, nessuna regressione. I BUILD sono fixture mancanti preesistenti.
- Modifiche di questo passo: `navi48_gopsnap.h` (+4 righe HUBP0 viewport/tiling, count 164). Nessun altro cambio al percorso primario.
