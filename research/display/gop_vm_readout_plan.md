# Osservazione dello stato GOP in VM: procedura (Fase 0.5 e 4.1)

Obiettivo: sapere quale pipe (OTG / HUBP / DIG / link encoder / PHY) accende il GOP UEFI sulla RX 9060 XT,
senza riavviare l'host e senza scritture di registro. Questo documento è il piano: nessuna VM è stata avviata
per prepararlo. Dati di partenza: `research/display/README.md` §3-§4.

## 0. Esito dell'analisi

- **Ipotesi confermata in linea di principio, ma la configurazione attuale la impedisce.** Il launcher della VM
  passa la scheda con `-device vfio-pci,host=0000:03:00.0,rombar=0`: la ROM BAR è disattivata, quindi OVMF non
  trova la option ROM della scheda e il GOP non viene eseguito. La ROM va esposta con `N4X_GPU_ROMBAR=1` (vedi §0, §2.1). Non serve riavviare l'host: la scheda è già in `vfio-pci` e QEMU la resetta all'apertura.
- **Lettura in sola lettura già pronta nel codice.** Aggiunta una diagnostica al boot, attivabile con
  `navi48-gopsnap=1`, che legge (una volta, in `attach()`, prima di qualsiasi stage di scrittura) 160 registri
  DCN più 4 contatori di frame per la verifica di attività. Modulo: `cobalt64/src/navi48-bringup/src/dcn/navi48_gopsnap.h`;
  glue: `gopSnapshot()` in `cobalt64/src/navi48-bringup/src/dcn/navi48_dcn.cpp`.
- **Un solo punto fisico da fare:** collegare un cavo DP dalla RX 9060 XT al monitor LG (vedi §3).
- **Boot14 (esito): il DP non si è acceso.** Il monitor è tornato su HDMI per mancanza di segnale. Causa verificata:
  `research/hw_dump/vbios.rom` (58 880 byte) contiene **solo** l'immagine PCI legacy (code type 0), con il bit
  "last image" non impostato: la catena è troncata. L'immagine UEFI GOP (code type 3) che segue non è nel file, quindi
  OVMF non aveva un GOP da eseguire. La ROM fisica è di 128 KiB (`/sys/bus/pci/devices/0000:03:00.0/rom`, 131072 byte,
  dato riportato dall'utente). **`vbios.rom` non va usato per il boot di osservazione.**
- **Opzione corretta:** `N4X_GPU_ROMBAR=1` sul launcher (`rombar=1`, nessun file): QEMU legge la ROM fisica della
  scheda via VFIO, senza root. Il default resta `rombar=0`. Vedi §2.1.
- **Decisione richiesta all'utente:** il motivo storico di `rombar=0` non è documentato nel repo. Con l'opzione
  opt-in il comportamento di bring-up non cambia.

## 1. Verifiche statiche fatte

| Controllo | Risultato |
|---|---|
| `rombar` / `romfile` negli script del repo (`tools/vm/`) | Nessuna occorrenza. Il launcher effettivo è `/mnt/vm/images/macos-gpu-test/OpenCore-Boot.sh` (fuori dal repo), con `rombar=0`. Anche `test-plan.json` riporta `"rombar": 0`. |
| ROM disponibile | `research/hw_dump/vbios.rom` (58 880 byte, firma `55aa`, ATOM, device 0x7590), estratto da debugfs `amdgpu_vbios` su Linux 7.2.9. **È troncato**: una sola immagine legacy (code type 0, last image = 0), senza GOP UEFI (vedi §0). L'oracolo Linux (`tools/vm/linux-oracle.sh`) passa la scheda con `vfio-pci,host=` senza `rombar`, quindi con la ROM esposta di default: amdgpu ha letto il VBIOS dalla ROM BAR ("Fetched VBIOS from ROM BAR"). Quell'avvio è `-kernel` diretto, senza OVMF: prova che la ROM è leggibile con quel device, non che il GOP venga eseguito. |
| Reset all'apertura VFIO | `reset_method = bus` (sysfs di `0000:03:00.0`). QEMU, aprendo il device, resetta la scheda: il GOP che OVMF esegue dopo parte da stato freddo. |
| Driver e boot VGA | `driver` = `vfio-pci`; `boot_vga` = 0 (la GPU primaria è l'iGPU). Il monitor è oggi sull'iGPU. |
| Connettori | Il DP della scheda è il PHY A / DIG0 / AUX0 / HPD1 (VBIOS, `research/display/README.md` §1). Nel DTN log a 180 Hz con Linux, il link encoder 0 (PHY A) risultava addestrato; gli altri due no. Questo dato era con il driver Linux attivo, non è la prova del GOP. |
| Ordine nel boot | `attach()` è chiamato in `start()` dopo le sole letture di survey (`navi48-stage=1`, `navi48-interrupts=0`). `setMemoryEnable(true)` in `start()` scrive il bit Memory Space del comando PCI prima di ogni lettura DCN: è già il comportamento dello stage 1 misurato il 20/10. |

## 2. Modifiche proposte agli script (NON applicate)

### 2.1 Launcher QEMU (fuori dal repo, `/mnt/vm/images/macos-gpu-test/OpenCore-Boot.sh`)

Sostituire la riga del device GPU:

Il launcher è ora parametrizzato (backup `OpenCore-Boot.sh.bak-20261020`):

```diff
-  -device vfio-pci,host=0000:03:00.0,rombar=0
+  -device "vfio-pci,host=0000:03:00.0,${GPU_ROM_OPT}"    # GPU_ROM_OPT=rombar=0 di default
```

- nessuna variabile: `rombar=0`, come prima (bring-up invariato);
- `N4X_GPU_ROMBAR=1`: `rombar=1`, la ROM fisica della scheda via VFIO. **Questa è l'opzione da usare per l'osservazione GOP**;
- `N4X_GPU_ROMFILE=<file>`: `romfile=<file>`. Da non usare con `vbios.rom` (troncato, vedi §0). Le due variabili
  sono esclusive. `start-gpu-test-vm.sh` controlla la combinazione e, per il file, PCIR 1002:7590 e part number.

Nessuno script del repo scrive la riga `vfio-pci`: `tools/vm/prepare-build-vm.sh` riscrive solo il launcher della VM di build. Il launcher di test sta in `/mnt/vm` e va modificato a mano (o dall'utente).

### 2.2 `tools/vm/prepare-gpu-test-stage.py` (flag di osservazione)

Lo script oggi rifiuta qualunque `navi48-*` non previsto (`assert not any(f.startswith('navi48-') ...)`):
senza questa modifica `navi48-gopsnap=1` fa fallire la preparazione.

```diff
@@
 p.add_argument('--vadd-ir', action='store_true', help='Stage17 only: run bounded gfx1200 vadd_ir after baseline dispatch')
+p.add_argument('--gopsnap', action='store_true', help='Stage1 only: read-only GOP snapshot at kext attach (navi48-gopsnap=1), no write')
 ...
 assert not args.vadd_ir or args.stage == 17, '--vadd-ir requires stage17'
+assert not args.gopsnap or args.stage == 1, '--gopsnap is an observation boot: stage 1 only'
 ...
-    flags = [f for f in original_flags if not f.startswith(('navi48-stage=', 'navi48-smu-full=', 'navi48-native=', 'navi48-interrupts=', 'navi48-vadd-ir='))]
+    flags = [f for f in original_flags if not f.startswith(('navi48-stage=', 'navi48-smu-full=', 'navi48-native=', 'navi48-interrupts=', 'navi48-vadd-ir=', 'navi48-gopsnap='))]
 ...
     if args.vadd_ir:
         flags.append('navi48-vadd-ir=1')
+    if args.gopsnap:
+        flags.append('navi48-gopsnap=1')
 ...
-            native_s1b=args.native_s1b, vadd_ir=args.vadd_ir, interrupts=args.interrupts,
+            native_s1b=args.native_s1b, vadd_ir=args.vadd_ir, gopsnap=args.gopsnap, interrupts=args.interrupts,
```

### 2.3 `tools/vm/start-gpu-test-vm.sh` (coerenza del piano)

Dopo la riga `assert ('navi48-vadd-ir=1' in ...)` aggiungere:

```diff
+assert ('navi48-gopsnap=1' in plan['boot_args'].split()) == plan.get('gopsnap', False)
```

Con queste tre modifiche l'avvio di osservazione è: `stage 1`, `navi48-interrupts=0`, `navi48-gopsnap=1`, nessun
opt-in di compute, di SMU completo, di native S1b o di vadd. Lo script `--start` non richiede altre modifiche.

## 3. Cosa fa l'utente fisicamente

1. Nessuna VM accesa. Lasciare l'host così com'è: Linux sull'iGPU, RX 9060 XT e audio ancora in `vfio-pci`.
2. Accendere il monitor LG (UltraGear, 2560x1440). Non è necessario spegnere il PC.
3. Collegare un cavo **DisplayPort** dalla RX 9060 XT al monitor, usando **la stessa porta DP che in
   `research/display/` il kernel chiamava DP-1** (quella con l'EDID del monitor). Il cavo HDMI dell'iGPU può restare.
4. Sul monitor selezionare l'ingresso **DisplayPort** (non HDMI). Se l'immagine del GOP compare su quell'ingresso
   è già la prima prova che il GOP ha acceso il DP.
5. Non collegare altri monitor alla RX 9060 XT (la prima osservazione è con un solo output).
6. Non fare riavvii dell'host, non toccare BIOS o dischi.
7. Quando la VM è in esecuzione: osservare lo schermo del monitor durante il boot OVMF e poi il boot di macOS, e
   annotare cosa compare su quale ingresso (testo, schermo nero, nulla). Il risultato va riportato insieme al log.

## 4. Procedura di boot di osservazione, passo per passo

Storage e lock: la VM di build e la VM di test non devono girare insieme (lock in `/mnt/vm/images/*/.vm.lock`).

1. **Verifica dell'ambiente** (host, senza avviare nulla):
   `bash tools/vm/start-gpu-test-vm.sh --check` deve restare in "Controlli preliminari superati". Il controllo
   usa il piano corrente; va rieseguito dopo ogni cambio di EFI.
2. **Applicare le modifiche di §2** (launcher, `prepare-gpu-test-stage.py`, `start-gpu-test-vm.sh`). Solo dopo
   l'OK dell'utente.
3. **Compilare il kext con il modulo nuovo** nella VM di build (`start-build-vm.sh`), come già fatto il 20/10:
   nel guest `cd ~/Developer/rx9060xt && make all ASIC=navi44 APPLE_ROUTE=0`. Copiare `Navi48Bringup.kext` sull'host
   (`scp -P 2222`) in una cartella di builds. Spegnere la VM di build (arresto regolare) prima di passare al punto 4.
4. **Salvare il log precedente**: il `serial.log` di `/mnt/vm/images/macos-gpu-test/diagnostics/` viene riscritto
   ad ogni avvio. Copiarlo con un nome datato.
5. **Preparare l'EFI di osservazione** (VM spenta):
   `python3 tools/vm/prepare-gpu-test-stage.py 1 --kext <percorso>/Navi48Bringup.kext --gopsnap`
   Lo script verifica il kext (`IOPCIPrimaryMatch` 0x75901002, Mach-O x86_64), inietta i file, scrive i boot-arg e
   verifica l'EFI risultante.
   Boot-arg risultanti: `navi48bringup=1 navi48-stage=1 navi48-interrupts=0 navi48-gopsnap=1` più quelli esistenti
   (`keepsyms=1 -v debug=0x108 serial=3 msgbuf=1048576`).
6. **Controllo finale**: `N4X_GPU_ROMBAR=1 bash tools/vm/start-gpu-test-vm.sh --check`, poi `N4X_GPU_ROMBAR=1 … --start` (il launcher verifica SHA256
   dell'EFI e dell'overlay, lock, KVM, VFIO e memoria). Il log è `diagnostics/serial.log`.
7. **Sequenza attesa**: OVMF esegue la option ROM della scheda (il monitor deve mostrare il GOP) → OpenCore →
   macOS → kext `Navi48Bringup` `start()` → `dcn: read-only raster path BUILT` → blocco `gopsnap:` (§5).
   Lo stage 1 non esegue il ladder: niente PSP, SMU, compute o interrupt.
8. **Estrarre il dump**: `grep 'gopsnap:' diagnostics/serial.log > diagnostics/gop-observe-<data>.txt`.
   Attese 160 righe di registro, una riga `rows resolved` e 4 righe `frames`.
9. **Chiusura**: arresto regolare di macOS (`vfs_unmountall` nel log), poi QMP `quit` se QEMU resta aperto.
   Verificare il reset VFIO nel log. Non lasciare la VM in esecuzione. Il monitor può restare collegato.
10. **Non ripetere** lo stesso avvio più volte senza motivo: ogni avvio con GOP acceso cambia lo stato della scheda
    (anche il reset di VFIO). Un secondo avvio è utile solo per confermare un risultato, con log separato.

## 5. Cosa legge il kext

Tutte le letture passano da `gLr` (device di sola lettura, `dcn41_abs_rd` + `rreg`); non c'è alcun percorso di
scrittura in `gopSnapshot()`. Ogni riga è `gopsnap: <nome> abs <dword> = <valore>`; `abs` è l'indirizzo dword
assoluto in BAR5 (segmenti DMU del dump: 0xc0, 0x34c0, 0x9000, verificati da `tools/hosttests/test_gopsnap.cpp`).

| Gruppo | Righe | Cosa dice |
|---|---|---|
| `OTGn_OTG_CONTROL` | 4 | bit 0 = `OTG_MASTER_EN`: l'OTG è acceso |
| `OTGn_OTG_STATUS`, `_STATUS_POSITION` | 8 | stato raster |
| `OTGn_OTG_H_TOTAL`, `_H_BLANK_START_END`, `_V_TOTAL`, `_V_BLANK_START_END` | 16 | timing programmato |
| `OTGn_OTG_MASTER_UPDATE_LOCK` | 4 | lock di aggiornamento |
| `ODMn_OPTC_DATA_SOURCE_SELECT` | 4 | sorgente dell'OPTC (ODM) |
| `HUBPREQn_DCSURF_PRIMARY_SURFACE_ADDRESS` (+`_HIGH`), `_SURFACE_PITCH` | 12 | indirizzo e pitch della superficie che il GOP scandisce |
| `HUBPn_DCHUBP_CNTL`, `HUBPn_DCSURF_SURFACE_CONFIG` | 8 | bit 0 `HUBP_BLANK_EN`; config = formato |
| `DPP_TOPn_DPP_CONTROL`, `MPCCn_MPCC_CONTROL/STATUS`, `OPP_PIPEn_OPP_PIPE_CONTROL` | 16 | pipeline DPP / MPC / OPP |
| `DIGn_DIG_FE_CNTL`, `_FE_CLK_CNTL`, `_FE_EN_CNTL`, `_BE_CNTL`, `_BE_CLK_CNTL`, `_BE_EN_CNTL` | 24 | front end: `DIG_SOURCE_SELECT` [2:0] = OTG; back end: `DIG_FE_SOURCE_SELECT` [14:8] = FE collegati; `DIG_ENABLE` |
| `DIGn_STREAM_MAPPER_CONTROL` | 4 | `DIG_STREAM_LINK_TARGET` [2:0] = link encoder della DIG |
| `DPn_DP_LINK_CNTL`, `DPn_DP_VID_STREAM_CNTL` | 8 | bit 4 `DP_LINK_TRAINING_COMPLETE` |
| `UNIPHYA..D_LINK_CNTL` | 4 | link encoder |
| `SYMCLKA..D_CLOCK_ENABLE` | 4 | bit 0 clock enable, bit 4 FE_EN, [10:8] `FE_SRC_SEL` (BASE_IDX 1) |
| `DC_GPIO_HPD_A`, `HPD1..3_DC_HPD_INT_STATUS` | 4 | selettore e stato hot-plug |
| `RDPCSTXn_RDPCSTX_CNTL`, `_PHY_CNTL0` | 8 | PHY |
| `DMCUB_CNTL`, `DMCUB_SEC_CNTL`, `DMCUB_INTERRUPT_STATUS`, `DMCUB_TIMER_CURRENT` | 4 | stato del microcontrollore |
| `DMCUB_SCRATCH0..15` | 16 | `DMCUB_SCRATCH0` = `dmub_fw_boot_status` (`dcn41_dmub.h`) |
| `DMCUB_INBOX1_*`, `DMCUB_OUTBOX1_*`, `DMCUB_REGION4_*`, `DMCUB_REGION3_CW7_*` | 12 | anelli e finestre del firmware; il contenuto degli anelli non viene letto |

Dopo la tabella il kext legge due volte i contatori `OTGn_OTG_STATUS_FRAME_COUNT` (bit [23:0]), a 50 ms di
distanza, e stampa `frames A -> B in 50 ms (running | STOPPED)`. Un OTG attivo avanza di circa 3-9 frame a
60-180 Hz. Il valore `0xFFFFFF` indica registro non leggibile, non un OTG fermo.

Il kext non legge DMCUB INBOX1 né REGION4 come memoria (sarebbe `dmubring`/`region4read`, verbi già esistenti,
che richiedono il client nativo). Questa diagnostica li legge solo come registri.

## 6. Criteri per interpretare il dump

Ordine di lettura: prima la vitalità, poi la catena di un solo pipe.

**A. Vitalità e MMIO**
- Tutti i valori `0xffffffff` / `0xffffff` dei contatori: MMIO non valido (BAR5 non mappato o dominio spento).
  Fermarsi: problema di boot o di mapping, non di GOP.
- Riga `rows resolved` diversa da 160/160: tabella non coerente con il kext. Fermarsi.

**B. Quanti pipe sono accesi**
- Atteso: **un solo OTG** con `OTG_MASTER_EN` = 1 e contatore `running`. Il dato Linux
  (`max_vbios_active_disp_pipe_num 1`, `research/reports/02-linux-display-dcn401.md`) dice che il GOP accende al
  massimo una pipe.
- Più OTG attivi, o nessuno: vedi §7.

**C. Catena del pipe acceso (OTG n)**
1. `ODMn_OPTC_DATA_SOURCE_SELECT` e `HUBPn_DCHUBP_CNTL` (`HUBP_BLANK_EN` = 0) indicano quali HUBP alimentano
   l'OTG. Con ODM 2:1 (come a 180 Hz su Linux) sono HUBP0 e HUBP1 insieme.
2. `HUBPREQn_DCSURF_PRIMARY_SURFACE_ADDRESS` diverso da zero e dentro la VRAM: è la superficie del GOP. Va
   confrontato con il framebuffer che macOS riceve dal boot (`PE_Video`/`getConsoleInfo`, `05-cobalt64-deepdive.md`).
3. `DIGn_DIG_FE_CNTL[2:0]` = numero dell'OTG: quale DIG è collegato all'OTG.
4. `DIGn_DIG_BE_EN_CNTL` `DIG_ENABLE` = 1 e `DIGn_STREAM_MAPPER_CONTROL[2:0]` = link: quale link encoder.
5. `DPn_DP_LINK_CNTL` bit 4 (`DP_LINK_TRAINING_COMPLETE`) del link: il DP è addestrato.
6. `SYMCLKx_CLOCK_ENABLE` del link con `FE_SRC_SEL` [10:8] = link: il clock di simbolo è alimentato.

**D. Esito per connettore (confronto con il VBIOS)**

| Osservato | Significato | Azione |
|---|---|---|
| OTG0 → DIG0 → link 0 (PHY A) → DP0, `TRAINING_COMPLETE` = 1, HPD1 | Il DP del GOP è sul connettore previsto dal VBIOS | Coerente con il VBIOS Navi 44: proteggere DIG0 / PHY A / SYMCLKA / AUX0; DIG1 / PHY B libero per HDMI-A-1; DIG2 / PHY C per HDMI-A-2 |
| OTG0 → DIG1 → link 1 (PHY B) | Il GOP ha acceso l'altro connettore (HDMI-A-1) | Verificare il cavo e la porta: il DP non è stato usato. Ripetere con il DP sulla porta giusta. Non cambiare le guardie |
| OTG n → DIG n → link n con n ≥ 2 | Connettore diverso da quelli del VBIOS | Fermarsi. Serve analisi del VBIOS e della tabella connettori |
| Un OTG attivo ma nessun DIG collegato a quell'OTG | Pipe senza uscita (frame in corso ma niente encoder) | Riportare lo stato completo, non adattare le guardie |
| `TRAINING_COMPLETE` = 0 con OTG attivo | Il GOP non ha addestrato il link (ad esempio modo senza link training) | Fermarsi: l'adozione della pipe richiede di capire se il GOP usa un modo senza DP link |

**E. Timing e modo**
- `OTG_H_TOTAL` / `V_TOTAL` confrontati con `cobalt64/src/dcn41/dcn41_modes_navi44.h` (5 modi fino a 180 Hz).
  La tabella dichiara i registri OTG uguali al DTN log a 180 Hz (`htot` 2719, `vtot` 1469). Un match dice quale
  modo il GOP ha scelto. Nessun match: è un modo fuori tabella, da annotare.

**F. DMCUB**
- `DMCUB_CNTL` e `DMCUB_SCRATCH0` diversi da zero, `DMCUB_INBOX1_BASE_ADDRESS` ≠ 0: il firmware DMUB del GOP è
  vivo. Cobalt64 dipende da DMUB per PHY e PLL (`dmubsend`): se è vivo, quei comandi sono utilizzabili.
- Tutto a zero: DMUB non avviato dal GOP. Cambia il piano: l'adozione dovrà fare senza DMUB (o avviarlo, decisione
  da prendere con l'utente).

**G. Confronto con la VM prima del GOP**
- Non c'è un dump "pre-GOP" nel protocollo: se serve, un avvio con `rombar` disattivato e `navi48-gopsnap=1` dà il
  riferimento "scheda spenta" (tutti gli OTG fermi). Opzionale, un solo avvio in più.

## 7. Stop e casi negativi

- **Nessun OTG attivo, nessuna superficie**: il GOP non ha acceso nulla. Ordine di verifica: (1) `rombar`/`romfile`
  applicato davvero (controllo: QEMU con la ROM presente, il log OVMF deve mostrare la ROM della scheda); (2) cavo
  DP sulla porta giusta; (3) monitor su ingresso DP; (4) EDID visibile. Non ripetere più di un avvio senza un cambio
  concreto.
- **Schermo del monitor nero ma dump con DIG0 acceso**: il link può essere attivo senza immagine. È un risultato
  valido: si riporta così com'è.
- **Il kext non parte o non stampa `gopsnap`**: non è un problema di GPU. Controllare `navi48bringup=1`,
  `navi48-stage=1` e il log di `start()`. Non cambiare lo stage per aggirare il problema.
- **Un valore non si capisce**: riportarlo tal quale con la riga di log, senza interpretarlo.

Non sono previste scritture. Se un passo richiedesse di scrivere un registro, la procedura si ferma.

## 8. Blocchi aperti e decisioni

1. **`rombar=0`** resta il default del launcher; l'osservazione usa `N4X_GPU_ROMBAR=1` (§2.1). Il motivo storico di `rombar=0` non è documentato: chiedere all'utente.
2. **Cavo DP e porta**: l'utente deve collegare il DP sulla porta che il kernel chiamava DP-1 (§3, punto 3).
3. **Build del kext** con `gopSnapshot()` nella VM di build (§4, punto 3). Non ancora fatta.
4. **Dopo il dump**: si decide se le guardie di `navi48_disp2.h` / `navi48_dmubcmd.h` passano alle costanti
   `N4X_DISP_*` (già presenti in `asic_profile.h`, non usate). Questo passo dipende dal risultato di §6.
5. **Verifica di compilazione e test**: test host `tools/hosttests/test_gopsnap.cpp` (156+4 righe contro
   `dcn_4_1_0_offset.h`, segmenti DMU del dump, costanti di profilo) e check kext per entrambi i profili; vedi
   il riepilogo nel documento di lavoro.

## 9. Esito del dump (boot15, `N4X_GPU_ROMBAR=1`, stage 1)

Fonte: `research/hw_dump/gop_dump_stage1_boot15_rombar1_serial.log` (sha256 in `.sha256` accanto). 160/160 righe risolte,
nessuna scrittura. Conferma visiva dell'utente: il DP della RX 9060 XT si è acceso mostrando la schermata OVMF, poi
l'immagine è rimasta ferma; OpenCore e macOS vanno sul display emulato di QEMU (vmware-svga), che quindi è il display
primario durante OpenCore e macOS. Il GOP ha acceso l'uscita DP e il framebuffer è rimasto statico.

**Vitalità.** `OTG0_OTG_STATUS_FRAME_COUNT` 3866 → 3872 in 50 ms (running). OTG1, OTG2, OTG3 fermi (0).
Un solo OTG attivo: coerente con il limite Linux di una pipe del GOP.

**Modo.** Il timing di OTG0 coincide con la riga `SINK-A 2560x1440@120` (EDID CTA DTD) di
`cobalt64/src/dcn41/dcn41_modes_navi44.h`: htot 2719, hse 32, hbs 2672, hbe 112, vtot 1524, vse 10, vbs 1522, vbe 82.
Clock 497,75 MHz, 119,998 Hz, DP su UNIPHY_A / DIGA / HPD1 / DDC0. Il contatore fa 6 frame in 50 ms, cioè 120 Hz.
Il GOP ha scelto questo modo, non il 180 Hz della DisplayID preferita.

**Catena del pipe** (un solo pipe, niente ODM 2:1 come a 180 Hz su Linux):
- HUBP0: `DCHUBP_CNTL` = 0x000f0002, `HUBP_BLANK_EN` (bit 0) = 0: attivo.
- HUBP0 surface del GOP: `HUBPREQ0_DCSURF_PRIMARY_SURFACE_ADDRESS` = 0x80_00000000 (high 0x80, low 0). È la base MC della
  VRAM (0x8000000000, la stessa del log PSP dello stage 5): **la scanout del GOP sta all'offset 0 della VRAM**.
- HUBP1, HUBP2, HUBP3: indirizzo 0, nessuna superficie.
- DPP0: `DPP_TOP0_DPP_CONTROL` = 0x70000010, bit 4 (clock) a 1. DPP1-3 = 0x70000000, clock spento.
- MPCC0-3 `MPCC_CONTROL` = 0xffff0461 (identici). `MPCC_STATUS` MPCC0 = 0x2, MPCC1-3 = 0x5: non decodificato.
- OPP0 `OPP_PIPE_CONTROL` = 0x3 (clock enable a 1). OPP1-3 = 0.
- `ODM0..3_OPTC_DATA_SOURCE_SELECT` = 0xfff00000 (campo `OPTC_SEG0_SRC_SEL` 0, non decodificato come selezione attiva).

**DIG, link, DP, clock.**
- DIG0: `DIG_FE_CNTL` source = 0 (OTG0); `DIG_FE_EN_CNTL` = 1; `DIG_BE_CNTL` = 0x0100 (FE0 collegato); `DIG_BE_EN_CNTL` = 1.
  `DIG_STREAM_MAPPER_CONTROL` = 0: link encoder 0 (UNIPHY_A, PHY A).
- DIG1, DIG2, DIG3: FE/BE spenti, stream mapper 0.
- DP0: `DP_LINK_CNTL` = 0x110, `DP_LINK_TRAINING_COMPLETE` (bit 4) = 1, enable (bit 8) = 1. `DP_VID_STREAM_CNTL` = 0x10201, bit 0 = 1.
  DP1-3 spenti.
- SYMCLKA: `CLOCK_ENABLE` = 1, `FE_EN` (bit 4) = 1. SYMCLKB, C, D a 0.
- UNIPHYA-D `LINK_CNTL` = 0 (non decodificato). `RDPCSTX0-3` `CNTL` e `PHY_CNTL0` = 0xffffffff, compresi i PHY non
  usati: la finestra PHY non è leggibile e non dà lo stato del PHY. Lo stato del link si ricava da DIG0/DP0/SYMCLKA.
- HPD1-3 `DC_HPD_INT_STATUS` = 0, `DC_GPIO_HPD_A` = 0: nessun interrupt pendente, non è un segnale di presenza.

**DMCUB (vivo, lasciato dal GOP).**
- `DMCUB_SCRATCH0` = 0x82 = `DCN41_DMUB_BOOT_MAILBOX_RDY` (0x002) | `HW_POWER_INIT_DONE` (0x080).
- `DMCUB_INBOX1`: base 0x80000000, size 0x2000 (8 KiB), WPTR = RPTR = 0x700 (anello fermo).
- `DMCUB_TIMER_CURRENT` avanza; `DMCUB_CNTL` = 0x001900c6.
- `DMCUB_REGION4_OFFSET` 0xdac00000, `_HIGH` 0x83, `REGION4_TOP_ADDRESS` 0x8000ffff.
- `DMCUB_SCRATCH4` = 0x001d003a, non decodificato.

**Verdetto.** Il GOP accende DIG0 / PHY A (link encoder 0) / DP0 / OTG0 / HUBP0 / DPP0 / OPP0 / SYMCLKA, con la
superficie all'offset 0 della VRAM e un modo 2560x1440@120 CTA DTD. Questo conferma la mappa Navi 44 del VBIOS
(DP = PHY A / AUX0 / HPD1). DIG1-3 non sono accesi: sono liberi per HDMI-A-1 (PHY B) e HDMI-A-2 (PHY C). Il DMCUB è
vivo con il mailbox pronto, quindi è utilizzabile dai verbi `dmubsend` (condizione per le sequenze DMUB di Cobalt64).

**Non ancora decodificato (da chiudere con le enum di Linux).** Formato della superficie (`SURFACE_PIXEL_FORMAT` = 0x08,
non 0x1a del framebuffer KWin); significato del pitch (`PITCH` = 0x033f); `MPCC_STATUS`; `ODM_SRC_SEL`; `UNIPHY_*_LINK_CNTL`.
La porta fisica (DP-1 di Linux) non è identificata dal dump: è coerente con il VBIOS.
