# Sicurezza termica e di potenza della RX 9060 XT (Navi 44): audit, watchdog kext, watchdog host

Data: 21 ottobre 2026. Stato: compilato nella VM di build (macOS 25G83) ed **eseguito su hardware** nei boot 31 e 32 (sezione 10): protezioni verificate PRESENT, sensore plausibile a riposo, watchdog host armato, nessun TRIP. Nessuna VM
avviata, nessun commit, nessun sudo, nessuna modifica fuori dal repo. Non letti NootRX/NootedRed, nessun codice NullMoth,
nessuna analisi degli interni dei kext Apple.

Requisito: nessun danno alla scheda. Un eccesso di temperatura deve fermare il lavoro e la VM, non limitarsi a una segnalazione.

---

## 1. Esito dell'audit (solo lettura del codice, poi modifiche)

Percorsi relativi a `cobalt64/src/navi48-bringup/src/` salvo diversa indicazione.

### 1a. Messaggi SMU e scritture di tabella

Tutti i messaggi PPSMC che il kext invia (`amd/smu_v14_0.cpp`):

| Messaggio | Dove (riga) | Effetto | Esito |
|---|---|---|---|
| TestMessage, GetSmuVersion, GetDriverIfVersion | 300–400 (ping, versione), `smu_hw_init` | sola lettura | ok |
| SetDriverDramAddrHigh/Low | 499, 503 (`smc_hw_setup`) | puntatore al buffer driver in VRAM | volatile |
| UseDefaultPPTable | 523 | carica la pptable IFWI di default nella SMU | ok (default del firmware) |
| RunDcBtc | 537 | calibrazione di avvio | ok |
| NotifyPowerSource(AC) | 554 | stato alimentazione | ok |
| SetAllowedFeaturesMaskLow/High = 0xFFFFFFFF | 577, 584 | **allarga** la maschera delle feature ammesse | **rischio R1** |
| EnableAllSmuFeatures | 606 | abilita tutte le feature, incluso il DPM | **rischio R2** |
| GetRunningSmuFeaturesLow/High | 625, 661 | sola lettura, ora usata dal gate di protezione | ok |
| DisableAllSmuFeatures | 755 (`smu_disable_all_features`) | **spegne le protezioni** | non chiamata (vedi R6) |
| SetSoftMaxByFreq / SetSoftMinByFreq (GFXCLK) | 773, 784 (`smu_set_soft_freq_range`), 862, 870 (`smu_set_power_state`) | clamp di clock | vedi R3, R5 |
| GetMin/MaxDpmFreq | 820 | sola lettura | ok |
| TransferTableSmu2Dram (metriche, id 5) | 904 (`smu_read_metrics`) | copia SMU→DRAM, sola lettura | ok |
| TransferTableDram2Smu (id 0x13) | definita, nessun chiamante | **nessuna tabella OD o pptable viene caricata** | ok |
| AllowGfxOff / DisallowGfxOff | `amd/amdgpu_init.cpp` 283, 871 | gating GFXOFF, reversibile | ok |

Scritture di memoria: `bar0_memset_vram` (`smu_v14_0.cpp` 478) azzera 64 KiB di VRAM a +0xE00000, lo slot del
driver table che la SMU riempie con le metriche. Non e' una tabella letta dalla SMU come configurazione.

Nessuna scrittura di OverDrive (`TABLE_OVERDRIVE`, id 8), di tensioni (`VoltageOffset*`), di curve ventola, di power
limit (PPT/TDC) o di max/min hard di clock. Verificato con ricerca testuale su `src/`, `tools/` e `tests/`: nessun
riferimento a `TABLE_OVERDRIVE`, `FanZeroRpm`, `SetPptLimit`, `SetHardMin` fuori dal percorso DAL descritto sotto.

Percorso DAL (`amd/smu_dal.cpp`, `amd/smu_dal_pure.h`): invia `SetHardMinByFreq` (0x9, riga 191 e 447) su DISPCLK
e DPPCLK, fino a 320 MHz al livello 2–3 e 600 MHz al livello 4 (`smu_dal_pure.h` 57–88, con tetto al massimo DPM registrato).
Attivo **solo** con boot-arg `navi48-dalsmc=1..4` e con native S1b in POSITIVE PASS. Di default e' spento.

### 1b. Protezioni del firmware

Stato prima del lavoro: `smuFullSetup` era attivo di default per target >= RLCInit (`Navi48Bringup.cpp` 6940–6942),
quindi `EnableAllSmuFeatures` girava al boot. Le feature venivano solo **lette e loggate** (`smu_v14_0.cpp` 625–636), non
verificate. Non esisteva alcun controllo che le protezioni fossero attive.

Maschera reale misurata da questo kext su questa scheda: `GetRunningSmuFeaturesHigh = 0x0498f59e`, `Low = 0x38fffcfb`
(`research/hw_dump/phase2_stage17_*_serial.log`, riga 772 del boot6; `research/hw_dump/pm_info.txt`). Bit richiesti,
secondo `smu14_driver_if_v14_0.h` di Linux:

| Feature | Bit | Presente sulla scheda | Ruolo |
|---|---|---|---|
| FEATURE_THROTTLERS | 23 | si | PPT, TDC e throttling per temperatura (Linux mappa SMU_FEATURE_PPT su questo bit) |
| FEATURE_VR0HOT | 27 | si | informativo |
| FEATURE_FW_CTF | 28 | si | spegnimento critico del firmware |
| FEATURE_FAN_CONTROL | 29 | si | controllo ventola del firmware |

Modifica: `smu_read_protections()` (`smu_v14_0.cpp`, sezione "n4x safety") legge le due word e le verifica con
`n4xs::check_protections` (`amd/n4x_safety_pure.h`). `smu_hw_init` la chiama sia dopo `smc_hw_setup`, sia nel ramo senza
setup. Il risultato e' in `smu_protections_verified()`.

Gate nel ladder (`amd/amdgpu_init.cpp`, `bringup_to`): ogni stage oltre `SMUInit` viene rifiutato con `kIOReturnNotPermitted`
se le protezioni non risultano attive oppure se il watchdog e' in TRIP. Il ladder si ferma a `SMUInit`, come richiesto
("non procedere oltre il bring-up minimo se le protezioni non risultano attive"). Log: `n4x safety: stage N ... NOT run`.

### 1c. Rischi trovati

Ordinati per gravita'. I punti marcati "modificato" hanno ora una guardia; gli altri sono segnalati e lasciati come sono.

- **R1 — maschera feature allargata (non modificato).** `smu_v14_0.cpp` 577–587 invia `SetAllowedFeaturesMask{Low,High} = 0xFFFFFFFF`
  al boot di default. Permette alla SMU di abilitare feature che l'IFWI aveva escluso. La prova che il firmware
  accetti il messaggio non c'e' (nei log storici era `UnknownCmd` in alcuni boot). Proposta: ridurre la maschera ai bit
  gia' presenti nella maschera di default letta prima, oppure rimuovere il messaggio. Non cambiato: serve una misura su hardware.
- **R2 — `EnableAllSmuFeatures` al boot di default (non modificato).** Abilita il DPM. Il commento in
  `amd/amdgpu_init.cpp` 903–906 riporta una misura reale: con la GPU senza lavoro la scheda stava a **304 W** (limite di
  board) con **hotspot 86 °C** e la ventola in salita, prima del clamp. Il clamp di idle (R5) e' la mitigazione attuale.
- **R3 — stati di power che alzano il clock da user space (modificato).** `Navi48UserClient::doPowerState` accettava `High`
  (min 1500 MHz) e `Peak` (min = max = 2400 MHz) senza alcuna guardia. Ora sono rifiutati se il boot-arg
  `navi48-clock-raise=1` non e' presente (default OFF). Dopo un TRIP viene rifiutato anche tutto tranne `Low`.
- **R4 — SetHardMin da DAL e mode trial (modificato).** Vedi 1a. Dietro `navi48-dalsmc` e native S1b, default OFF. Ora
  `N48N_SEL_DAL_STEP`, `N48N_SEL_MODE_TRIAL` e `N48N_SEL_MODE_HOLD` rifiutano dopo un TRIP (`Navi48NativeClient.cpp`).
- **R5 — clamp di idle GFXCLK al boot (non modificato, direzione sicura).** `amd/amdgpu_init.cpp` 925 scrive
  `SetSoftMaxByFreq` con il minimo DPM di PMFW. E' un clamp verso il basso, non un limite oltre il default, ed e' reversibile
  con `navi48test power 0`. Abilitato di default da `navi48-idle-clamp` (`Navi48Bringup.cpp` 6951). Segnalato perche'
  e' una scrittura di max, anche se nel verso sicuro.
- **R6 — `smu_disable_all_features` (non chiamata).** Manda `DisableAllSmuFeatures` (riga 755), che spegne anche
  FW_CTF e THROTTLERS. Nessun chiamante nel repo (`amd/amdgpu_init.cpp` 800 lo cita solo nel commento). Proposta: cancellarla.
- **R7 — `TransferTableDram2Smu` e `smu_set_tools_dram_addr` non chiamati.** Presenti come API, nessun uso. Nessun rischio
  finche' non vengono chiamati; proposta: tenerli fuori dal build o cancellarli.
- **R8 — protezioni verificate con una mappa di bit di IF 0x2E.** La mappa di `smu14_driver_if_v14_0.h` vale per
  l'interfaccia 0x2E; il firmware qui riporta IF 0x33 (`audit` di `research/reports/smu_metrics_if33_audit.md`). La prova
  che i bit siano gli stessi e' la maschera misurata, che ha 23/27/28/29 nelle posizioni attese. Resta una verifica su hardware.
- **R9 — telemetria SMU non validata (usata solo in lettura).** Il layout delle metriche per IF 0x33 non e' validato. Il
  watchdog NON prende decisioni su edge, mem o potenza: quei campi nell'heartbeat sono `na`.
- **R10 — watchdog del solo percorso kext navi44.** Le submission dell'aux kext (`Navi48Accel`, `tools/native/navi48accel`)
  e il percorso Apple (`APPLE_ROUTE=1`, off) non passano dal gate. Il TRIP blocca `Navi48Bringup`; l'aux non e' coperto. Il
  watchdog host ferma comunque la VM.
- **R11 — fan zero-RPM: non implementato (vedi sez. 3).**

### 1d. Audit no-flash / ROM / SPI / NVRAM

Esito: **nessun percorso del kext, degli strumenti del repo o di RDNA4FB scrive ROM, VBIOS, SPI flash, EEPROM/FRU o NVRAM
persistente della GPU.** Ogni impostazione che il driver applica e' volatile: si perde al reset o allo spegnimento.

Verifiche:
- **Accesso PCI.** Il kext scrive solo i bit di comando `setBusMasterEnable(true)` (`Navi48Bringup.cpp` 615) e
  `setMemoryEnable(true)` (7384). Il registro Expansion ROM Base (`kIOPCIConfigExpansionROMBase`, riga 93) e' solo letto.
  Nessun `configWrite` su BAR o ROM. `resize-vfio-bar.py` (host, sudo) cambia la dimensione della BAR dal sysfs; non e' flash
  e non e' eseguito dal kext.
- **Comandi PSP** (`amd/amdgpu_psp.h` 379–388, 410; `amd/psp_v14_0.cpp`): LOAD_ASD (4), SETUP_TMR (5), LOAD_IP_FW (6),
  LOAD_TOC (0x20), AUTOLOAD_RLC (0x21), FB_FW_RESERV_ADDR/EXT (0x50/0x51), INIT/DESTROY ring. Caricano firmware in VRAM/PSP
  (volatile). `INVOKE_CMD` (3) e' definito (riga 381) ma **non inviato**: nessuna chiamata a TA RAS, nessuna scrittura
  RAS EEPROM. Nessun comando FRU, BOOTCFG, SECURE o di aggiornamento firmware.
- **Bootloader PSP** (`src/psp.cpp` 45–55, 229–254): comandi di caricamento sub-blob su C2PMSG_35/36. Volatili.
- **Registri.** Il selettore di lettura registri (`doRegRead`, `Navi48UserClientABI.h` 28) e' solo lettura. Non esiste un
  selettore di scrittura registro grezza. Le scritture DCN passano dall'allowlist (`src/dcn41/dcn41_allow_ranges.h`): deny
  per gli indirizzi indiretti 0x0–0xff (NBIO SMN, da cui si arriverebbe alla SPI ROM), deny per MP1 (0x16000), per il
  "ROM path" di MP0/PSP (0x1ce00), per SMUIO (0x2458000) e per gli altri blocchi MP0/MP1. Nessun range ammesso comprende
  quegli indirizzi (`tools/dcn41/gen_allow.py` 24, 212).
- **RDNA4FB** (`cobalt64/third-party/rdna4fb-n44/0001-navi44-device-match.patch`): solo match del device ID e lettura di
  `kIOPCIConfigVendorID`. Nessuna scrittura.
- **Strumenti.** `tools/vm/prepare-gpu-test-stage.py` scrive EFI e NVRAM della VM (`OVMF_VARS`), non della scheda.
  `start-gpu-test-vm.sh` controlla le ROM e non le scrive. I comandi `dd`, `flash`, `eeprom`, `spi` non compaiono in
  `tools/` (ricerca testuale).

Limite della verifica: ho letto il codice del repo (kext, tools, RDNA4FB). Non ho analizzato in dettaglio il kext
`navi48accel` oltre la ricerca testuale, e non ho verificato il firmware binario.

---

## 2. Watchdog kext (`navi48-safety`)

File: `amd/n4x_safety_pure.h` (logica pura, testabile su Linux), `amd/n4x_safety.h/.cpp` (thread e log).

- **Attivazione.** Default ON sul profilo Navi 44, OFF su Navi 48 (`Navi48Bringup.cpp`, blocco prima di `n48dcn::attach`).
  Boot-arg: `navi48-safety=0|1`, `navi48-safety-warn=<C>` (default 75), `navi48-safety-trip=<C>` (default 80), range accettato
  50–100 con warn < trip; altrimenti default e messaggio `CONFIG-REFUSED`.
- **Sensore.** `THM_TCON_CUR_TMP`, letto con `RREG32` ogni 250 ms. Ricerca nel sorgente Linux: `thm_14_0_2_offset.h`
  (`regTHM_TCON_CUR_TMP` = 0x0000 in THM, BASE_IDX 0), `thm_14_0_2_sh_mask.h` (`CUR_TEMP` = bit 21..31, range select = bit 19).
  La discovery di questa scheda (`research/hw_dump/ip_discovery_table.bin`) riporta **THM hwId 3, v14.0.2, segmento 0 =
  dword 0x16600** (byte 0x59800, la base dell'header). Decodifica: gradi = campo/8, meno 49 se il range bit e' alto
  (`smu10_hwmgr.c`, `smu8_hwmgr.c` di Linux). **Non validata su hardware**: al primo boot l'heartbeat `hotspot=` deve
  concordare con la temperatura junction di idle (~30 °C nel dump Linux, `hwmon.txt`). Un valore fuori 0–125 °C e' un guasto
  del sensore.
- **Heartbeat.** Una riga al secondo sulla seriale: `N4X-SAFETY t=<ms> hotspot=<C|na> edge=na mem=na ppt=na state=OK|WARN|TRIP|STOP
  reason=<r> proto=<0|1> thm=<hex>`. `edge`, `mem` e `ppt` restano `na` (vedi R9).
- **Stati.** OK; WARN sopra la soglia di avviso; **TRIP** sopra la soglia di stop, che e' latched fino al ricaricamento del
  kext; oppure 12 letture consecutive non valide (3 s). Sensore non risolto con watchdog attivo: **TRIP reason=no-sensor**
  (fail closed).
- **Effetto del TRIP.** Il kext non scrive nulla. Rifiuta: `doSubmitIB`, `N48N_SEL_SUBMIT`, `DAL_STEP`, `MODE_TRIAL`,
  `MODE_HOLD`, `doAccelExperiment`, `doPowerState` (tranne `Low`), e il ladder di bring-up (`bringup_to`). Non rilascia gli
  hold di clock gia' attivi: rilasciarli sarebbe una scrittura di clock, che il requisito vieta. Il watchdog host ferma la VM.
- **Mai scritti.** Tensioni, clock, ventola, tabelle, power limit. Solo letture e log.

### Soglie e motivazione

| Soglia | Valore | Motivazione |
|---|---|---|
| Avviso (hotspot) | 75 °C | margine di 5 °C sotto lo stop; decisione dell'utente |
| Stop (hotspot) | **80 °C** | limite massimo deciso dall'utente. Il sensore disponibile e' il junction; l'edge non e' letto. Il junction e' di norma piu' caldo dell'edge, quindi lo stop sul junction e' il lato sicuro |
| Memoria | non implementata | nessun sensore memoria indipendente (metriche non validate) |
| Limiti PPTable | non usati | la pptable del VBIOS non e' disponibile nel repo e hwmon non espone `*_crit`; il minimo "PPTable vs default" non si puo' calcolare. Il default e' quindi quello cautelativo |
| Heartbeat perso (host) | 10 s | un kext bloccato non puo' fermarsi da solo; il silenzio e' lo stop |
| Durata massima (host) | 3600 s dal primo heartbeat | limite di durata del carico; configurabile |

---

## 3. Fan zero-RPM: NON implementato (richiesta riportata)

Richiesta: disattivare lo zero-RPM cambiando solo il campo `FanZeroRpmEnable`, con leggi → modifica → scrivi → rileggi.

Esito: **non lo faccio**, per la regola "se non e' verificabile in sola rilettura, non farlo".

Il percorso Linux per SMU 14.0.2 (`research/src/.../smu14/smu_v14_0_2_ppt.c`, 2444–2447 e 2734–2752) e' un
upload dell'**intera** `OverDriveTable_t` con `TransferTableDram2Smu` (tabella `TABLE_OVERDRIVE` = 8, `smu14_driver_if_v14_0.h`
riga 1870). La struct contiene `FeatureCtrlMask` (riga 752), gli offset di tensione `VoltageOffsetPerZoneBoundary`, i
limiti di Fmax e `FanZeroRpmEnable` (riga 783). Il layout e' quello di IF 0x2E. Il firmware di questa scheda riporta IF
0x33, non validato. Con un layout sbagliato si scriverebbero campi di tensione o di clock. La rilettura conferma solo che la
SMU ha conservato i byte scritti, non che li abbia interpretati allo stesso offset. Il criterio "solo quel campo" quindi non e'
verificabile.

Stato del firmware: zero-RPM resta al default di PMFW (la ventola puo' fermarsi). Per renderlo verificabile servirebbe
prima la validazione del layout OD per IF 0x33 (dump raw della tabella con la stessa procedura proposta per le metriche).

---

## 4. Watchdog host (`tools/vm/gpu-safety-watchdog.py`)

- **Indipendente dal kext.** Segue `diagnostics/serial.log` e parla a QEMU via `qmp.sock`. Nessun privilegio.
- **Stop.** Invia QMP `quit`. Quando QEMU termina, vfio-pci chiude il dispositivo e il kernel lo riporta a riposo. Il
  watchdog non invia SIGKILL: se QEMU non esce entro 15 s, SIGTERM; se sopravvive, lo segnala e chiede intervento manuale.
- **Cause di stop.** `kext-trip:<motivo>` (state=TRIP, o `event=TRIP`/`START-FAILED`); `host-temp:<C>` (hotspot >= 80 anche con
  state=OK); `heartbeat-lost:<s>` (nessun heartbeat per oltre 10 s dopo il primo, cioe' kext armato); `max-runtime:<s>`.
  `state=STOP` (scaricamento pulito) disarma il timeout e non ferma la VM.
- **Lancio.** `tools/vm/start-gpu-test-vm.sh --start` avvia il watchdog prima di `exec OpenCore-Boot.sh`. Se il watchdog
  non scrive `READY` entro 10 s, la VM **non parte** (fail closed). Il vecchio `qmp.sock` e il vecchio `serial.log` vengono
  messi da parte, con il lock della VM gia' tenuto. Variabili: `N4X_SAFETY_WARN_C`, `N4X_SAFETY_TRIP_C`, `N4X_SAFETY_MAX_S`,
  `N4X_SAFETY_DRY_RUN` (registra ma non ferma; stampa un avviso).
- **Stop esplicito.** `start-gpu-test-vm.sh --stop-watchdog` termina solo il watchdog (SIGTERM, dal PID file). Non ferma la VM.
- **Log e report.** `diagnostics/gpu-safety-watchdog.log` (seriale del watchdog) e, a ogni stop,
  `research/hw_dump/gpu_safety_events/<timestamp>-<motivo>/report.json` con la storia degli heartbeat e
  `serial-tail.txt`.
- **Test con seriale finto.** `gpu-safety-watchdog.py --selftest` e `--scenario {ok,warn,trip,lost,hot,stop,maxrt,malformed,nosensor}`.
  Un QMP finto riceve il `quit`; un seriale finto riceve le righe del kext.

---

## 5. Test

- `tools/hosttests/test_n4x_safety_pure.cpp`: 33 check (decodifica THM, soglie, latch, protezioni con la maschera reale,
  formato esatto dell'heartbeat, buffer corto). **PASS.**
- `tools/hosttests/test_gpu_safety_watchdog.py`: 16 test (casi di decisione, parser, coerenza delle soglie con l'header C,
  nove scenari con seriale e QMP finti, dry-run). **PASS.**
- `tools/hosttests/run.sh` aggiornato con i due test sopra.
- `tools/linux-check-kext.sh`: profilo navi44 **54 ok, 0 errori**; profilo navi48 (`EXTRA_FLAGS=-DN4X_ASIC_NAVI48`) **54 ok, 0 errori**.
- `tools/hosttests/run-cobalt64-tests.py`:
  - navi44: prima delle modifiche 66 PASS / 12 FAIL / 28 BUILD / 3 NOCMD. Dopo: stesso risultato (il test `native_s1b_test`
    e' tornato PASS dopo aver spostato il gate di submit dopo la riga S1b, che il test controlla testualmente).
  - navi48: 66 / 12 / 28 / 3, identico alla baseline riga per riga.
  - Il filtro usato sul profilo navi44 per i test native ha eseguito anche `native_s2a_test` (7 FAIL) e
    `native_s2d_test` (26 FAIL): **erano gia' FAIL nella baseline con gli stessi conteggi**.
- Non eseguiti: compilazione e link su macOS, test su hardware, test runtime del kext.
- Nota: `start-gpu-test-vm.sh --start` non e' stato eseguito (la VM non si avvia). Il lancio del watchdog e' stato provato a
  parte con lo stesso comando, in una cartella di scratch: READY, PID file, uscita pulita se QEMU non compare.

---

## 6. Cosa NON puo' fare

- Se il kext si blocca, il **watchdog host** ferma la VM (heartbeat perso). Il kext non puo' fermarsi da solo.
- Il TRIP non rilascia gli hold di clock gia' attivi (lo vieta il requisito: nessuna scrittura di clock). Il watchdog host
  ferma la VM, e il reset VFIO riporta la scheda a riposo.
- Il sensore disponibile e' uno solo (junction). Edge e memoria non sono controllati.
- Non c'e' un controllo di potenza (PPT) basato su telemetria validata. Le protezioni PPT/TDC sono quelle del firmware
  (THROTTLERS), verificate ma non misurate.
- Il reset VFIO dopo la chiusura di QEMU dipende dal supporto di vfio-pci per questa scheda: **da verificare** sulla macchina.
- Il watchdog non copre l'aux kext `Navi48Accel` (R10).

---

## 7. Come verificare

1. Host, senza GPU: `python3 tools/hosttests/test_gpu_safety_watchdog.py` e
   `g++ -std=c++17 -Wall -Wextra -Werror -Icobalt64/src/navi48-bringup/src tools/hosttests/test_n4x_safety_pure.cpp -o /tmp/t && /tmp/t`.
2. Sintassi kext: `tools/linux-check-kext.sh` e `EXTRA_FLAGS=-DN4X_ASIC_NAVI48 tools/linux-check-kext.sh`.
3. Al primo boot con kext nuovo (VM di build, da chiedere): nel seriale cercare `N4X-SAFETY event=START sensor=THM_TCON_CUR_TMP`,
   `protections: ... PRESENT`, e confrontare `hotspot=` a riposo con ~30 °C (`hwmon` junction di idle). Se non concorda, il decode
   THM e' sbagliato: fermare e correggere prima di qualunque carico.
4. Prova di scatto: con la GPU a riposo (~30 °C) lo scatto non avviene. Per provarlo, sul boot di prova usare la coppia valida
   piu' bassa, `navi48-safety-warn=50 navi48-safety-trip=51` (warn deve restare sotto trip e il minimo accettato e' 50), e
   lanciare un carico. Allo scatto `state=TRIP` deve comparire nel seriale, il watchdog host deve scrivere il report e
   fermare la VM. Questa prova richiede un carico: va fatta solo con la VM di test e con la tua autorizzazione.
5. Prova di heartbeat perso: fermare il kext (`kmutil unload`) e verificare che il watchdog host dichiari `state=STOP` senza
   fermare la VM; un blocco vero del kext invece deve produrre `heartbeat-lost`.

---

## 8. Per attivarlo al prossimo boot

- **Kext**: serve la ricompilazione di `Navi48Bringup.kext` con i sorgenti di questo commit (profilo navi44, default). Il kext
  in `/mnt/vm/builds/navi48-full-20261021/` e' precedente e non contiene il watchdog. La build richiede la VM di build, da
  accendere con il tuo via libera (un altro agente la usa ora).
- **Boot-arg** (solo se si vuole cambiare il default): `navi48-safety=0|1`, `navi48-safety-warn`, `navi48-safety-trip`.
  `navi48-clock-raise=1` solo per benchmark deliberati; non e' ammesso nel test-plan (`tools/vm/gpu-preflight.py` e
  `start-gpu-test-vm.sh` controllano le chiavi `navi48-*`, quindi va aggiunto in modo esplicito se serve).
- **Host**: nulla di nuovo da fare. `start-gpu-test-vm.sh --start` lancia il watchdog automaticamente. Per fermare solo il
  watchdog: `--stop-watchdog`.
- **Prima di accendere la scheda**: confermare la cartella di log `research/hw_dump/gpu_safety_events` e i limiti di durata.

---

## 9. Cose da decidere (per te)

1. R1: ridurre o rimuovere `SetAllowedFeaturesMask = 0xFFFFFFFF` del boot di default.
2. R6/R7: cancellare `smu_disable_all_features`, `TransferTableDram2Smu` e `smu_set_tools_dram_addr` inutilizzati.
3. Fan zero-RPM: serve prima la validazione del layout OD per IF 0x33 (non automatizzabile in sola lettura).
4. Soglie: stop a 80 °C e avviso a 75 °C sul junction, come deciso dall'utente. Modificabili con i boot-arg e con `--trip-c`/`--warn-c` (o le variabili `N4X_SAFETY_*`), con il vincolo warn < trip.

---

## 10. Verifica su hardware (21 ottobre 2026, boot31 e boot32)

Build: `/mnt/vm/builds/navi48-safety-20261021/Navi48Bringup.kext`, sha256 binario `cb18a1f9…28d5` (come da `SHA256SUMS`).
Watchdog host: `start-gpu-test-vm.sh --start`, `READY` con warn 75, trip 80, timeout heartbeat 10 s, durata massima 3600 s.
Evidenze: `research/hw_dump/safety_boot31/` (boot31, consenso RDNA4FB) e `research/hw_dump/p2_boot32/` (boot32, P2).

Esiti misurati:

- **Sensore.** `event=START sensor=THM_TCON_CUR_TMP dword=0x16600 warn=75 trip=80` in entrambi i boot. Il decode THM
  dà valori plausibili a riposo: 33–34 °C (boot31, 47 heartbeat) e 33–39 °C (boot32). La temperatura junction di idle
  attesa è circa 30 °C (`hwmon`, sezione 2): la lettura è coerente.
- **Picchi isolati all'avvio.** Un solo campione alto per boot, nel primo secondo dopo `START`: 55 °C (boot31,
  `t=4331 ms`) e 60 °C (boot32, `t=4577 ms`). Il campione successivo, e tutti quelli seguenti, sono tornati a 33–39 °C.
  Non sono un andamento: la causa non è stata determinata (probabilmente il caricamento del ladder con SMU e GFX
  attivi, letto un istante prima della stabilizzazione). Da seguire: se il picco si ripete a ogni avvio, va indagato.
- **Protezioni.** `smu: protections: running 0x0498f59e_38fffcfb ... PRESENT, missing 0`, `VR0HOT(27) on`, in entrambi i
  boot. Il gate del ladder non ha bloccato nulla.
- **Stati.** Nessun `state=WARN` né `state=TRIP` nei due boot. Nessun `event=TRIP`, `START-FAILED` o `CONFIG-REFUSED`.
- **Panic.** Nessun `Debugger called` né panic in seriale nei due boot.
- **Spegnimento.** Boot31 spento con `shutdown -h` (`vfs_unmountall(system) end`, `qemu-img check` pulito). Boot32
  spento con `shutdown -h` dopo l'osservazione dell'utente, come da istruzione del coordinatore (QEMU uscito entro il
  limite di 8 minuti, vedi `research/hw_dump/p2_boot32/`).

Limiti restanti (da non dedurre dai dati sopra):

- La verifica dell'**intervento** di TRIP (la prova di scatto, sezione 7 punto 4) non è stata fatta: sarebbe un carico
  e non è stata autorizzata. Il TRIP non è mai scattato, quindi la soglia 80 °C non è stata provata in pratica.
- Il sensore è il solo junction (R9); edge, memoria e PPT restano `na`.
- Il picco di 55–60 °C a `START` non è spiegato.
- Il watchdog copre il solo kext `Navi48Bringup` (R10); l'aux `Navi48Accel` non è coperto.
