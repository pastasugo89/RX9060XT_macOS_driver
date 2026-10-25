# P2 contro la ricetta desktop di Cobalt64: confronto sistematico

Data: 23/10/2026. Sola analisi di codice, script e log del repo. Nessuna VM, nessun sudo, nessun commit, nessuna analisi di binari Apple.
Riferimenti di codice relativi a `cobalt64/src/navi48-bringup/` salvo diversa indicazione. Evidenze di boot in `research/hw_dump/`.

## Sintesi

1. **La ricetta Cobalt per un monitor non è quella del nostro `accel ucprobe`.** La variante `stage17-accel-pdb0-qn` è la variante dell'esperimento Apple (rotta Apple, fase 4). Non fa parte dell'armamento desktop, e con il nostro kext non può funzionare: (a) `navi48-native=1` e `navi48-accel-experiment=1` sono in conflitto, quindi la variante toglie il nub Metal; (b) con `APPLE_ROUTE=0` (la build del nostro port) `ucprobe` è uno stub che non installa alcun hook.
2. **Il `kIOReturnNotPermitted` (0xe00002e2) di `ucprobe` nel boot46 non viene dal gate di esposizione.** Il kext stesso lo dice nel seriale: `REFUSING the accel verbs: the native VM self-test ran on this boot ... reboot without navi48-native=1 for that path`. Con `navi48-native=1` il test nativo S1b lascia la GPU in stato "usato" e rifiuta tutti i verbi accel tranne quelli esentati (i verbi pipe 83..98 sono esentati, `ucprobe` 81 no).
3. **Il VBL della pipe non viene dal kext Cobalt via IRQ.** Il callback VBL che CoreDisplay riceve passa da `IOFramebuffer::registerForInterruptType('vbl ')`, cioè dal timer emulato di RDNA4FB (`rdna4-vbl=1`). Il kext non ha una sorgente `vbl ` propria (`tools/native/navi48accel/src/Navi48Accel.cpp:216`). L'IRQ DCN (VUPDATE/VSTARTUP) alimenta solo la diagnostica `dcnvbl` e il watchdog di `dcnflip`. I timestamp dei vblank della pipe sono campionati per polling dei registri OTG (`vbl_sample`, `amd/native_disp.cpp:155`). Quindi `navi48-interrupts=0` non blocca il VBL.
4. **Errore concreto di RDNA4FB, non di boot-arg.** Il periodo del timer VBL viene dal timing EDID preferito (143.97 Hz, 6945 us), non dal timing GOP installato (2560x1440@120, 497.75 MHz, 2720x1525, circa 8334 us). Il codice upstream ha la stessa logica (`research/refs/RDNA4FB/src/framebuffer.cpp:1517-1522`), quindi il difetto è nel nostro uso del pannello (preferito a 144 Hz, scanout a 120 Hz).
5. **Il VBL armato non ha sbloccato i frame.** Con `rdna4-vbl=1` (boot46) i contatori del compositor sono uguali al boot44 senza il flag: `pipelines gfx=1 comp=0 command_buffers=0 frames=0`. Il VBL è necessario ma non sufficiente. Il collo di bottiglia resta a monte del primo command buffer.
6. **Ci sono differenze di boot-arg reali, ma nessuna è un "interruttore" mancante ovvio.** Le differenze verso la variante desktop probabile sono `navi48-multisession=1` (e probabilmente `navi48-apps=1`), `navi48-interrupts` (default 1 contro il nostro 0), `npci=0x2000`, e soprattutto `fbname 1` (che noi saltiamo, con buone ragioni: sul nostro RDNA4FB ha fatto abortire WindowServer, boot30).

## Metodo e limiti

- Ricetta Cobalt per un monitor: `cobalt64/tools/pc/arm-gpu-desktop.sh` (la sequenza di armamento) e `cobalt64/tools/pc/autoarm/n48-autoarm.sh` (la versione automatica a due display, non applicabile a Navi 44). Il rollback documentato in `cobalt64/tools/pc/m6-stage1a-run.sh` (riga 19-20) indica la variante `stage17-native-1440-metal-disp-amfi-ms-apps` come "la" variante desktop: è la variante di cui `arm-gpu-desktop.sh` si aspetta i boot-arg.
- **Non verificato:** il contenuto esatto dei file `.plist` delle varianti. Vivono sul PC in `~/navi48-staging/configs/` e non sono nel repo. Quindi la composizione della variante desktop è ricostruita dai test (`cobalt64/src/navi48-bringup/tests/native_disp_test.cpp:1473-1477`, `native_m6_plant.sh`, `m6-stage1a-deploy.sh:135-136`) e dal codice, non letta dal file. Da confermare con una lettura read-only sul PC.
- `research/refs/7000-macos` (il "60 fps su un DP", README riga 26): lo snapshot contiene il README e il kext, ma non `arm-gpu-desktop.sh`, non le varianti e non una ricetta. La dichiarazione esiste, la ricetta no. Non ho potuto ricavare da lì boot-arg aggiuntivi.
- Log di boot46: la cattura non include le righe `CoreDisplay INFO` (né `InstallTimingWithWireFormats`), né i log di WindowServer del pid 1093 (quello post-arm). Quindi "mode non installato" e "Metal compositor non attivato" nel boot46 **non sono provati**: sono assenze di cattura. Vedi punto 0 della lista.

## 1. Tabella di confronto

Legenda impatto: **VBL** = callback di vblank verso CoreDisplay; **Tx** = transazioni della display pipe (submit/perform/complete); **Flip** = presentazione a schermo.

| # | Voce (boot-arg / passo / variante / file) | Cobalt, desktop un monitor | Nostro P2 (boot46) | Differenza | Impatto atteso su VBL / Tx / Flip |
|---|---|---|---|---|---|
| 1 | `navi48bringup=1`, `navi48-stage=17` | sì (variante `ms-apps`, probabile) | sì | nessuna | nessuno |
| 2 | `navi48-native=1` (S1b) | sì | sì | nessuna | nessuno sulla presentazione; blocca i verbi accel (vedi 1, sintesi) |
| 3 | `navi48-metal=1` (nub Metal) | sì | sì | nessuna | nessuno (nub pubblicato) |
| 4 | `navi48-metal-disp=1` (rotta display) | sì | sì | nessuna | nessuno (verbi pipe ammessi) |
| 5 | `navi48-metal-ws=1` (client WindowServer, uid 88) | sì (dedotto dal rollback: `arm-gpu-desktop.sh` richiede WS ammesso) | sì | nessuna | nessuno; con `ws` il framebuffer aux non parte (piano §8.1 punto 8) |
| 6 | `navi48-agdc=1` (per `pipeagdc 1`) | sì (la stessa funzione `agdc_publish_locked` esige `navi48-agdc=1`, `apple/DisplayPipeGuard.cpp:2011-2014`) | sì (`pipeagdc` status 0, poi 12) | nessuna | AGDC presente: Tx lookup ok |
| 7 | `navi48-aux` | default on | `=1` esplicito | nessuna | nessuno |
| 8 | `navi48-interrupts` (IH/MSI) | default **1** (assente = 1, `Navi48Bringup.cpp:7402-7407`) | **0**: `ih: ... ENABLE_INTR=0, polled mode=yes` | **DIFFERENZA** | Nessuna sul VBL (vedi sintesi 3). Possibile sulla completion (EOP/fence) delle Tx. Rischio noto: nei boot IRQ 7-13 sulla Navi 44 sono comparsi fault GCVM VMID0 spontanei (`research/reports/phase2_mes_fault_checkpoint.md`) |
| 9 | `navi48-multisession=1`, `navi48-apps=1` (+ probabile `navi48-g5`) | sì (probabile, nella `ms-apps`) | **assenti**: sessione nativa singola (VMID 8), nessuna allow-list app | **DIFFERENZA** | Modello di sessione WindowServer (`amd/native_s1c.cpp:1843-1872`): una sola sessione contro fino a quattro. Effetto sulla Tx: incerto, medio |
| 10 | `navi48-smu-full` | default "full" (`Navi48Bringup.cpp:6939-6942`) | assente (= full) | nessuna effettiva | nessuno |
| 11 | `rdna4-vbl=1` (RDNA4FB, timer VBL) | non nelle ricette del repo. `DisplayPipeGuard.cpp:1532` dice che RDNA4FB rifiuta `vbl ` senza questo flag: quindi Cobalt deve averlo da qualche parte (da verificare sul PC) | sì | non determinata | **VBL**: necessario (senza, nessun VBL). Non sufficiente (boot46) |
| 12 | Periodo del VBL (RDNA4FB, codice `framebuffer.cpp:1517-1522`) | dal timing EDID preferito, uguale allo scanout sul loro pannello (non verificato) | dal EDID preferito 143.97 Hz = **6945 us**; scanout GOP 2560x1440@120 = **~8334 us** | **DIFFERENZA di codice** | **VBL** a 144 Hz contro scanout a 120 Hz: pacing errato, dovuto al nostro pannello. Da correggere (lista, punto 2) |
| 13 | `npci=0x2000` | presente nelle varianti Cobalt con ReBAR (`native_rebar_plant.sh:140`, `native_rebar_test.cpp:392-411`) | assente | **DIFFERENZA** | Configurazione PCI/BAR. Effetto sul display non noto. Verificare la variante sul PC |
| 14 | `amfi_get_out_of_my_way=1` | sì | sì | nessuna | nessuno |
| 15 | `csr-active-config` | non determinato dal repo | 0x03 | non determinata | non noto |
| 16 | `navi48-m6`, `m6flip`, `m6flip1`, `fb2`, `disp2`, `dmubcmd` | solo nelle varianti multi-display (`autoarm`, `m6-*`) | assenti (corretto) | nessuna | su Navi 44 `m6`, `disp2`, `dmubcmd` sono rifiutati (`dcn/navi48_disp_profile.h:34-40`, `asic_profile.h:116-117`). `fb2` crea un display nub che blocca il nub Metal (`native_metal_pure.h:46`) |
| 17 | `navi48-pdb0=1` | non nel desktop: è la via VMID0 "B'" della rotta Apple (`gmc_v12_0.cpp:738-742`) | assente | nessuna | nessuno; **non aggiungere**: cambia la base della tabella GFXHUB VMID0 |
| 18 | `navi48-sdma-qn-test`, `accel-experiment`, `boot-chain`, `eop-bridge`, `shader-cache`, `sdma-q1/srbm/vmfrag-test` | non nel desktop | assenti | nessuna | confliggono con `navi48-native` (`native_s1b_pure.h:160-169`): con uno di questi il gate è RIFIUTATO e il nub Metal non si pubblica |
| 19 | `navi48-clock-raise` | assente | assente | nessuna | **non attivare mai** (alza clock) |
| 20 | `navi48-safety` (default ON su Navi 44) | default | default | nessuna | nessuno; resta attivo |
| 21 | Passo: nub `publish` | sì, poi `sleep 2` | sì (`deploy-metal-stack.sh` remote arm, P0) | nessuna | nessuno |
| 22 | Passo: `pipeadopt` | una volta, subito dopo il publish | un primo tentativo con status 3 (aux non ancora caricato), poi ok (`flags 0x3b`) | ordine/retry | nessuno sulla Tx (la pipe risulta adottata) |
| 23 | Passo: `pipeagdc 1` | sì | sì | nessuna | nessuno |
| 24 | Passo: **`fbname 1`** (rinomina classe in `AMDRDNA4FB`) | **sì, sempre** (`arm-gpu-desktop.sh`) | **no** (`N48_ARM_FBNAME=0`) | **DIFFERENZA** | Sul nostro RDNA4FB `fbname 1` ha fatto abortire WindowServer (boot30): `Can't get value for key 'AMDFramebuffer'` in `CoreDisplay_CreateDisplayForCGXDisplayDevice`. Impatto sul vendor (IG/isBDW contro AMD): non dimostrato sulla presentazione |
| 25 | Passo: flag `n48m-headless-no` | prima di `pipearm`, dopo `fbname` | prima di `pipeagdc` | ordine | nessuno |
| 26 | Passo: `pipearm 1` (0xccf=1) | sì | sì | nessuna | nessuno |
| 27 | Passo: `pipereload` + `killall -9 WindowServer` + `sleep 15` | sì | sì | nessuna | nessuno |
| 28 | Watcher che rimuove flag e contatore al cambio pid WS (`n48watch`, `n48-autoarm-watch.sh`) | sì | **no** | **DIFFERENZA** | Nessun effetto sul primo frame. Dopo un riavvio WS successivo il flag resta e la sessione può essere forzata headless |
| 29 | Backstop `CI_USE_MTL_DAG_FOR_CIKL_SRC=0` | sì | sì (`deploy-metal-stack.sh:416`) | nessuna | nessuno |
| 30 | Timing installato 2560x1440@120 ("succeeded for mode") | visto nel boot44 (sessione 828) | **non catturato** nel boot46 | non determinata | **Tx/Flip**: se il modo non è installato, CoreDisplay non usa il timing. Da verificare (lista, punto 0) |
| 31 | `Metal compositor activated` (sessione WS post-arm) | visto nel boot44 (pid 828, 19:33:09) | **non catturato** nel boot46 (nessun log del pid 1093) | non determinata | **Tx**. Il contatore T1 del pid 1093 (`gfx=1 comp=0`) è identico al boot44, quindi lo stato "compositor" è verosimilmente lo stesso (da confermare) |
| 32 | Cookie VBL della pipe (`pipe+0xd8`, `pipeguard`/`ucprobe`) | non misurato da noi; Cobalt lo legge con la rotta Apple | **non misurabile**: `ucprobe` rifiutato da `native`, e con `APPLE_ROUTE=0` è uno stub (`native/apple_route_off.cpp:289-294`) | non applicabile | **VBL**: il cookie è inferibile dal fatto che RDNA4FB ha armato il timer (`vbl: emulated VBL armed`, 15:40:28), ma non verificato |

## 2. Cosa significa `stage17-accel-pdb0-qn`

- È il **nome di un file di configurazione** sul PC (`~/navi48-staging/configs/`), non nel repo. Il suo contenuto esatto non è verificabile qui.
- Il nome compone tre parti, dedotte dai boot-arg che il codice legge:
  - `accel`: `navi48-accel-experiment=1` (la fase 4, rotta Apple: `Navi48Bringup.cpp:7449-7451`).
  - `pdb0`: `navi48-pdb0=1` (GFXHUB VMID0 su PDB0, `Navi48Bringup.cpp:6977-6982`).
  - `qn`: verosimilmente `navi48-sdma-qn-test=1` (`Navi48Bringup.cpp:7002-7008`). Non ne sono certo: è una deduzione dal nome.
- **Cosa non contiene:** `navi48-native=1`, `navi48-metal=1`, `navi48-metal-ws=1`, `navi48-metal-disp=1`. Il gate S1b rifiuta la combinazione con `accel-experiment` (`native_s1b_pure.h:160-169`), quindi il nub Metal non si pubblica. Quindi questa variante non è compatibile con P2.
- **Perché il messaggio di `navi48test` la cita:** il testo di errore di `navi48test.c:1994-1995` è scritto per il caso del `fire` con gate chiuso. Per `ucprobe` il messaggio è fuorviante (vedi sintesi 2).
- **Con la nostra build** (`APPLE_ROUTE=0`, `research/reports/metal_deploy_plan.md` §8.0): `ucprobe` è uno stub (`native/apple_route_off.cpp:289-294`) che risponde stato 1 "no accelerator vtable" senza installare hook. Quindi nessun boot-arg permette di misurare il cookie con il kext che usiamo. Il passo "variante `stage17-accel-pdb0-qn` per misurare il cookie" del boot46 va **ritirato**.

## 3. Risposte alle domande

**a) Quali boot-arg la ricetta desktop richiede che noi non passiamo?**
Dal codice e dai test, il desktop Cobalt per un monitor richiede `navi48-native=1`, `navi48-metal=1`, `navi48-metal-disp=1`, `navi48-metal-ws=1`, `navi48-agdc=1`, `navi48-stage=17`, `amfi_get_out_of_my_way=1` (tutti presenti da noi). Non passiamo: `navi48-multisession=1`, `navi48-apps=1` (probabili nella `ms-apps`), `navi48-interrupts=1` (default Cobalt), `npci=0x2000` (nelle varianti con ReBAR). `navi48-pdb0`, `sdma-qn`, `accel-experiment`, `eop-bridge`, `boot-chain`, `fb2`, `m6*`, `disp2`, `dmubcmd` **non** vanno aggiunti: o confliggono con il nub Metal o non esistono su Navi 44.

**b) Ordine di armamento e flag file.**
Cobalt: nub publish → `pipeadopt` → `pipeagdc 1` → `fbname 1` → flag `n48m-headless-no` → `pipearm 1` → `pipereload` → `killall -9 WindowServer` → `sleep 15` → watcher che toglie flag e contatore al cambio pid → backstop CIKL. Noi: nub publish → `pipeadopt` (con un primo tentativo fallito) → `pipeagdc 1` → flag → `pipearm 1` → `pipereload` → `killall` → nessun watcher. Differenze: `fbname` (vedi tabella, 24) e il watcher (28). L'ordine dei passi è equivalente, salvo `fbname`.

**c) Il VBL/vsync della pipe deve venire dal kext Cobalt (IRQ DCN, `navi48-interrupts`) o solo da RDNA4FB?**
Solo da RDNA4FB, nell'architettura che Cobalt usa. Prove: (1) `Navi48Accel.cpp:216` ("no 'vbl ' source"); (2) `DisplayPipeGuard.cpp:1529-1535` (la registrazione del `vbl ` passa da `registerForInterruptType` di IOFramebuffer, cioè RDNA4FB); (3) l'IRQ DCN (`dcn/navi48_dcn.cpp:695-704`) è usata da `dcnvbl` e da `dcnflip`, non dal callback della pipe. Il timestamp VBL della pipe è campionato per polling OTG (`vbl_sample`). Quindi `navi48-interrupts` non è la sorgente del VBL. Resta aperta la questione della completion (EOP) delle transazioni, che dipende dall'IH: con `=0` il percorso è quello "polled", che Cobalt dichiara "invariato" (`Navi48Bringup.cpp:7402-7405`), ma per le Tx non è verificato.

**d) Il VBL armato è sufficiente?** No (boot46, vedi sintesi 5).

## 4. Lista ordinata delle modifiche per P2

Ogni modifica va fatta con la VM spenta, come le precedenti, e va verificata nel boot successivo con i criteri dei report esistenti. Nessuna alza clock o tensioni. Nessuna è stata applicata.

**0. Solo lettura, prima di modificare nulla (rischio: nullo).**
Ricatturare i log di WindowServer del pid post-arm con un predicato esplicito (`process == "WindowServer"` e `eventMessage CONTAINS "compositor" OR "InstallTiming" OR "Display"`), per verificare: (a) `Metal compositor activated` del pid 1093; (b) `succeeded for mode 2560x1440@120`. Se (a) manca, il collo è a monte del compositor; se (b) manca, il modo non è installato. Aggiungere al log, con il prossimo boot, il conteggio delle chiamate di `fireVBL` e dei callback consegnati (il log attuale ha solo `vbl: emulated VBL armed`).

**1. (Rischio basso) Non applicare `fbname 1`.** Già nella ricetta del nostro `deploy-metal-stack.sh` (`N48_ARM_FBNAME=0`): tenerlo a 0. Se si rivaluta, serve prima capire la chiave `AMDFramebuffer` che CoreDisplay cerca sul nostro framebuffer (il messaggio dell'assert) e non cambiare il nome alla cieca. Rischio alto (abort di WindowServer, con possibile loop di riavvii).

**2. (Rischio basso, codice RDNA4FB) Periodo del VBL dal timing GOP installato.**
Modifica in `research/ext/RDNA4FB-n44/src/framebuffer.cpp` (`registerForInterruptType`, righe 1517-1522): calcolare `vblPeriodUS` dal timing GOP attivo (`497750000 Hz`, totali 2720x1525, cioè circa 8334 us) invece che dal EDID preferito. Il timer non scrive registri hardware. Rischio: basso (solo pacing). **Richiede** una build nuova (nuovo SHA), quindi un nuovo consenso GUI del kext e un nuovo boot. Effetto atteso: VBL e scanout alla stessa frequenza. Necessario ma probabilmente non sufficiente.

**3. (Rischio medio) Allineare la sessione nativa alla variante desktop: `navi48-multisession=1` e `navi48-apps=1`.**
Da fare solo dopo la lettura read-only del `.plist` `stage17-native-1440-metal-disp-amfi-ms-apps` sul PC, per confermare la composizione. Cambia il modello di sessione (VMID 8 per WindowServer, 9..11 per le altre, `native_s1c.cpp:1843-1857`) e abilita l'allow-list app (default deny). Nessun effetto su clock e tensioni. Effetto atteso sulla Tx: incerto.

**4. (Rischio medio-alto, da tenere separato) `navi48-interrupts=1`.**
Non serve per il VBL (vedi sintesi 3). Serve solo se la completion (EOP) delle Tx risulta bloccata dopo i punti 2 e 3. Nei boot IRQ 7-13 sulla Navi 44 sono comparsi fault GCVM VMID0 spontanei (`research/reports/phase2_mes_fault_checkpoint.md`): va provato in un boot a sé, con tutta la strumentazione, non insieme ad altre modifiche.

**5. (Rischio basso-medio, da verificare) `npci=0x2000`.**
Presente nella variante Cobalt con ReBAR. Non serve per il VBL. Prima di aggiungerlo: verificare sul PC cosa fa la variante, e che la VM con `N4X_GPU_ROMBAR=1` non ne venga disturbata.

**6. (Rischio basso, operativo) Watcher del flag headless e un solo `pipeadopt` dopo il publish.**
Aggiungere al `remote_arm_script` il watcher di `n48-autoarm-watch.sh` dopo il riavvio di WindowServer, e fare `pipeadopt` una volta, dopo un `sleep 2`. Non cambia la presentazione, ma evita stati residui a un riavvio successivo.

**Da non fare, in nessun punto della lista:**
- `navi48-m6`, `navi48-m6flip`, `navi48-m6flip1`, `navi48-fb2`, `navi48-disp2`, `navi48-dmubcmd`: non esistono su Navi 44 (`supported()` ritorna falso) o bloccano il nub Metal (`fb2`).
- `navi48-pdb0`: cambia la tabella GFXHUB VMID0 (rischio alto sulla GPU).
- `navi48-accel-experiment`, `navi48-sdma-qn-test` (e `sdma-q1/srbm/vmfrag-test`), `navi48-boot-chain`, `navi48-eop-bridge`, `navi48-shader-cache`: confliggono con `navi48-native=1`, il nub non si pubblica.
- `navi48-clock-raise`: alza i clock. Non attivare.
- `navi48-safety=0`: spegnerebbe il watchdog termico. Resta a default.
- `stage17-accel-pdb0-qn` per misurare il cookie: ritirato (vedi sintesi 2).

## 5. Ipotesi di collo di bottiglia da verificare dopo i punti 0 e 2

Non ancora provate, in ordine di costo:
1. Il VBL non arriva a CoreDisplay (cookie NULL o richiesta di notifica mai armata). Verifica: contatore di `fireVBL` e dei callback (punto 0).
2. Il modo non è installato (`succeeded` assente), quindi CoreDisplay non avvia il display link. Verifica: punto 0(b).
3. Il vendor della GPU per CoreDisplay è `IG`/`isBDW=YES isMobile=YES` (osservato nel boot44 e nel boot46, `get_display_device_info`), mentre Cobalt sul 9070 XT presenta AMD. Possibile effetto sul percorso di presentazione. Non verificato, e il fix noto (`fbname 1`) è pericoloso.
4. La sessione WindowServer post-arm usa il compositor software (ipotesi, da confermare con il punto 0a).

## Riferimenti principali

- Ricetta Cobalt: `cobalt64/tools/pc/arm-gpu-desktop.sh`, `cobalt64/tools/pc/autoarm/n48-autoarm.sh`, `cobalt64/tools/pc/m6-stage1a-run.sh` (righe 19-20), `cobalt64/tools/pc/navi48test.c` (verbi 81, 83..90, 1778-1803, 1994-1995).
- Gate e boot-arg: `cobalt64/src/navi48-bringup/src/Navi48Bringup.cpp` (7402-7407, 7449-7530, 7595-7610, 7952, 8904), `amd/native_s1b.cpp:71-80`, `amd/native_s1b_pure.h:160-169`, `amd/native_disp_pure.h:86-99`, `amd/native_metal_pure.h:40-50`, `dcn/navi48_disp_profile.h:34-40`, `amd/asic_profile.h:116-117`, `apple/DisplayPipeGuard.cpp:1529-1535, 2011-2014`, `native/apple_route_off.cpp:289-294`, `Makefile:33-47`.
- RDNA4FB: `research/ext/RDNA4FB-n44/src/framebuffer.cpp` (1513-1545, 2073-2075); upstream `research/refs/RDNA4FB/src/framebuffer.cpp` (stessa logica).
- Nostro stato: `research/reports/p1_p2_display.md` (boot30 fbname, boot41-46), `research/reports/compositor_diag.md`, `research/reports/metal_deploy_plan.md` §8, `research/hw_dump/vbl_boot46/` (serial, counters), `research/hw_dump/v8_boot44/` (compositor attivato nel pid 828), `tools/vm/deploy-metal-stack.sh` (355-421), `tools/vm/prepare-gpu-test-stage.py`.
