# Diagnosi: perché il compositor Metal di WindowServer non produce frame (boot44)

Data: 21/10/2026. Sola lettura sul guest (utente `test`, porta 2223, chiave `/mnt/vm/builds/build-vm-ed25519`).
Evidenze: `research/hw_dump/v8_boot44/compositor_diag/` (checksum in `SHA256SUMS`, estratto in `evidence_extract.txt`).

## Sintesi

- **Causa più probabile: il VBL (vertical blank) non viene mai fornito a CoreDisplay.** RDNA4FB emula il VBL con un timer
  solo se è attivo il boot-arg `rdna4-vbl=1`. Il boot-args di questo boot non lo contiene, e nessun boot documentato in
  `research/hw_dump/` lo ha mai avuto. Senza VBL il compositor non avvia il frame: nessun command buffer, nessuna
  transazione al pipe, nessun flip. Il codice Cobalt64 (`DisplayPipeGuard.cpp`, `Navi48AccelPeer.cpp`) descrive lo stesso
  meccanismo. La catena è coerente con tutti i contatori, ma il cookie VBL del pipe non è stato misurato (vedi Limiti).
- **Correzione proposta:** aggiungere `rdna4-vbl=1` ai boot-args della VM (solo questo flag), riavviare la VM e verificare
  con i criteri sotto. Nessuna modifica di codice.
- Ipotesi (a) "WindowServer usa un altro MTLDevice": **respinta**. Un solo device Navi48 in WindowServer, e il compositor
  si attiva su quello.
- Ipotesi (b) "display machine senza framebuffer": **non confermata**. Il display machine esiste (1 istanza). Resta aperta
  la questione del framebuffer che usa, ma non spiega da sola l'assenza di frame.
- Ipotesi (c) "bundle declinato in WindowServer": **respinta**. In WindowServer il device è accettato (`initWithAcceleratorPort ... -> ok`).
  Il `DECLINED` riguarda solo loginwindow pid 206 prima dell'arm, per policy.

## Stato del boot osservato

- VM avviata alle 19:31:32 (uptime 4 min alle 19:35). Watchdog GPU pronto alle 19:30:58.
- WindowServer pid 202 (pre-arm, avviato alle 19:31:44 nei log), terminato dall'arm. WindowServer pid 828 avviato alle 19:33:08.
- `pipestat 0`/`4` letti alle 19:35 e rileggi alle 19:41: identici al salvataggio `pipestat_0_and_4_postarm.txt`.
  Flags `0x3f` (adottata e armata), factory mask `0xd`, `frames copied 0`, `completed 0`.
- Il boot è quello descritto (boot44). Lo stato non è cambiato durante la diagnosi.

## Evidenze

### 1. Il compositor si attiva sul nostro device, ma non lavora mai

- `19:33:09.133` WindowServer 828: `[com.apple.SkyLight:default] Metal compositor activated.` (nel boot precedente, 19:31:45,
  era `Software compositor activated`).
- Prima dell'attivazione, in WindowServer 828 (uniche occorrenze): `initWithAcceleratorPort 0xe96f -> ok` (19:33:08.786),
  una coda di comandi, una pipeline di render (19:33:08.803), sampler, depth-stencil e heap.
- Conteggi T1: `19:33:19 pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`. Poi `19:34:09` e `19:35:09`:
  `T1 idle: no pipeline/import/command buffer in the last 60 s`.
- Quindi il compositor crea le proprie risorse sul nostro device, ma non crea alcun command buffer.

### 2. Il pipe non riceve alcuna transazione

- `pipestat 0`: `hook calls 267/277/278/279: 1 / 0 / 0 / 0`, `submit pass-through / will-perform: 0 / 0`,
  `bytes copied / frames copied / completed-disarmed: 0 / 0 / 0`.
- Dal sorgente (`cobalt64/tools/native/navi48accel/src/Navi48Accel.cpp:64-71`, `:286-294`): 277 = `performTransaction`,
  278 = `isTransactionComplete`, 279 = `submitTransaction`. Nessuno dei tre è mai stato chiamato. Lo slot 267 non è
  identificato con certezza nel sorgente (è descritto in due modi diversi).
- `pipestat 4`: `vblank timestamp switch ON`, `stamps written 0`, tutti i contatori di skip a 0, `last t_vbl 0`.
  Non è un guasto del flusso VBL: `vbl_stamp_flow` (`cobalt64/src/navi48-bringup/src/amd/native_disp_flow.h:362-384`)
  gira solo dentro la perform di una transazione, che non è mai avvenuta.

### 3. Il VBL di RDNA4FB è disattivato in questo boot

- `research/ext/RDNA4FB-n44/src/framebuffer.cpp:2075`, dentro `RDNA4FB::start()` (riga 2054): `vblRequested = true`
  solo se il boot-arg `rdna4-vbl` è diverso da 0.
- `framebuffer.cpp:1509-1514` (`registerForInterruptType`): se il tipo è `kIOFBVBLInterruptType` e `vblRequested` è falso,
  la registrazione va a `super` e non viene creato alcun timer.
- Con `rdna4-vbl=1`: `framebuffer.cpp:1522-1545` crea l'`IOTimerEventSource` con periodo `1e9 / refreshMilliHz` e scrive
  `vbl: emulated VBL armed, period N us`. `fireVBL` (riga 1502) chiama il callback VBL del pipe.
- Il README di RDNA4FB (riga 97) lo dice esplicitamente: `rdna4-vbl=1` fornisce un VBL emulato "che attiva il frame pacing di
  IOFramebuffer (CVDisplayLink timestamps)... assente senza un handler IRQ hardware".
- Boot-args di questo boot (`kern.bootargs` in `pairing_and_bootargs.txt`): contiene `navi48-metal-ws=1`,
  `navi48-metal-disp=1`, `navi48-agdc=1`, `navi48-interrupts=0`, `amfi_get_out_of_my_way=1`, ma **non** `rdna4-vbl`.
- Nel seriale di questo boot non compare `vbl: emulated VBL armed`. Nessun dump in `research/hw_dump/` contiene
  `rdna4-vbl` o quella riga.
- Il confronto della tabella in `research/reports/p1_p2_display.md` (riga 486) elenca RDNA4FB con "sì (VBL timer)". Il
  timer esiste nel codice, ma è sotto un boot-arg che non è mai stato passato.

### 4. Perché il pipe non può ottenere il VBL

- Il lavoro di Cobalt64 (`cobalt64/src/navi48-bringup/src/apple/DisplayPipeGuard.cpp:1522-1535`, 0.0.334/0.0.335, e
  `Navi48AccelPeer.cpp:4560-4600`, `:4712-4735`) descrive la catena: `IOAccelDisplayPipe::displayModeDidChange` chiama
  `IOFramebuffer::registerForInterruptType('vbl ')`. Il cookie risultante (`pipe+0xd8`) è la sorgente VBL. Con `pipe+0xd8`
  NULL, `enableVBLInterrupt` non fa nulla e nessuna notifica viene consegnata.
- Il team dice che RDNA4FB rifiuta quel tipo senza `rdna4-vbl=1` (commento a `DisplayPipeGuard.cpp:1532`).
- Stesso commento: il fronte 0→1 di `pipe+0x2a0` viene consumato dalla prima registrazione. Se il cookie è ancora NULL, il
  VBL resta spento per tutto il boot. Quindi `rdna4-vbl=1` deve essere attivo dal boot, prima della prima richiesta.

### 5. Il ramo a due display di Cobalt non è disponibile su Navi 44

- Seriale: `Navi48Bringup: disp: boot-arg navi48-m6: REFUSED on Navi 44 (multi-display is Navi 48 only): nothing is latched`.
- Quindi il framebuffer ausiliario `Navi48Framebuffer` (che in Cobalt vive sotto `Navi48DisplayNub`, con `navi48-m6`,
  `navi48-fb2`, `navi48-disp2`, `navi48-dmubcmd`) non può essere usato su Navi 44. Il DP passa da RDNA4FB, e il VBL
  deve venire da RDNA4FB. Il framebuffer ausiliario non ha alcuna sorgente `vbl ` (`Navi48Accel.cpp:216`).

### 6. Display machine e framebuffer (ipotesi b)

- `IOKitDiagnostics` (ioreg): `Navi48DisplayMachine=1`, `IOAccelDisplayMachine=1`, `Navi48DisplayPipe=1`,
  `IOAccelDisplayPipeUserClient2=1`, `IOFramebuffer=1`, `Navi48DisplayNub=0`, `Navi48Framebuffer=0`.
- Il display machine non compare come nodo del registro (probabilmente non è un IOService). Non è quindi vero che "non esiste".
- Il pipe è stato adottato su RDNA4FB (`pipe adopt: recorded pipe ... (Navi48DisplayPipe on RDNA4FB)`). Il pipe usato
  dall'AGDC punta allo stesso oggetto RDNA4FB (`agdc-declared-id: ... SAME OBJECT`).
- Il display machine ha un framebuffer collegato? Non è osservabile da ioreg. Il progetto dice che `IOAccelDisplayMachine::start`
  cerca il framebuffer due livelli sotto il provider, mentre RDNA4FB è un livello sotto il PCI (ioreg riga 2972 vs
  2803). Il progetto non ha verificato questa regola sul binario e io non l'ho verificata.
- Conclusione: il display machine non è una causa dimostrata. Va verificata dopo la correzione del VBL, se i frame restano a zero.

### 7. Altri segnali (osservati, non dimostrati come cause)

- GPUWrangler registra la GPU come `flags 0x10 (IG)`. CoreDisplay registra il display con `isBDW=YES ... isMobile=YES`.
  La GPU è quindi vista come "non-AMD" (vendor bit 0x1). È il bersaglio di `accel fbname 1` nella ricetta Cobalt
  (`navi48_fbname.hpp`: rinomina in `AMDRDNA4FB` per il bit 0x4). Il suo effetto sul compositor non è verificato, e il
  codice chiede una revisione avversariale prima dell'uso. Non è stato eseguito in questo boot (`IOClass = RDNA4FB`, nessuna
  riga `class name NOW`).
- `universalaccessd` (pid 836) fallisce i ping di WindowServer ogni ~12 s dalle 19:33:31. Osservato, non spiegato.
- Nella tabella AGPM `Machine` (`MacPro7,1`) mancano sia 0x7550 sia 0x7590. Non distingue il nostro caso da quello di
  Cobalt, quindi non è una causa.
- `navi48-interrupts=0` non è la causa: il VBL emulato di RDNA4FB è un timer, non dipende dall'IH.

## Confronto con la ricetta a un monitor di Cobalt64

`cobalt64/tools/pc/arm-gpu-desktop.sh` (desktop GPU sul DP, un monitor) esegue: `n48nub publish`, `accel pipeadopt`,
`accel pipeagdc 1`, `accel fbname 1`, `touch /private/tmp/n48m-headless-no`, `accel pipearm 1`, `accel pipereload`,
`killall -9 WindowServer`.

La sequenza eseguita su questa VM è la stessa, senza `fbname 1` (in `tools/vm/deploy-metal-stack.sh:412` è saltato con
`N48_ARM_FBNAME=0`: "la pipe accetta il nome RDNA4FB senza rinomina"). Il kill file `n48m-headless-no` è presente (19:33),
quindi il device non è headless.

Differenze rilevanti rispetto a Cobalt, che non sono nella ricetta a un monitor:

- Cobalt usa `rdna4-vbl`? Nessun riferimento a `rdna4-vbl` nelle sue ricette (`tools/pc/*.sh`), solo nel codice di
  diagnostica. Non posso dire con certezza come Cobalt ottenga il VBL sul suo PC (il 9070 XT, Navi 48). Su Navi 44 la
  strada del framebuffer ausiliario non è disponibile (sezione 5).
- Il ramo `autoarm` (due display) richiede `navi48-m6`, `navi48-fb2`, `navi48-disp2`, `navi48-dmubcmd`: non applicabile su Navi 44.

## Correzione proposta

1. **Boot-arg (unico cambiamento):** aggiungere `rdna4-vbl=1` ai boot-args della variante P2 della VM, con la VM spenta.
   Il flag non è gestito da `tools/vm/prepare-gpu-test-stage.py` (`ADMITTED_KEYS`, riga 40, solo `navi48-*`), quindi lo script
   lo conserva (riga 271, `MANAGED_PREFIXES`). Prima di applicarlo: `prepare-gpu-test-stage.py --dry-run` e verifica che
   `rdna4-vbl=1` compaia nei boot-args calcolati. Se lo script ricostruisce i flag, va aggiunto esplicitamente.
2. **Ordine (prima dell'arm, 0 utenti):** con l'approvazione dell'utente, `accel ucprobe 1` (installa l'hook di log, come nel
   lavoro di Cobalt). Atteso: `VBL BEFORE sel 3 ... pipe+0xd8 cookie ... (a VBL source EXISTS)` prima della prima
   `request_notify`. Se compare NULL, il fronte è bruciato per il boot: va rifatto il boot.
3. **Arm** come oggi (`n48nub publish`, `pipeadopt`, `pipeagdc 1`, `pipearm 1`, riavvio WindowServer). Non eseguire
   `fbname 1` finché non c'è la revisione avversariale richiesta dal codice.
4. **Criteri di verifica nel boot successivo:**
   - seriale: `RDNA4FB: vbl: emulated VBL armed, period N us` (framebuffer.cpp:1545), con N coerente con il timing
     attivo (2560x1440@120, periodo circa 8333 us; il pannello dichiara 143.97 Hz di preferenza, quindi va controllato);
   - `pipestat 0`: `submit` o `will-perform` > 0, `frames copied` > 0;
   - `pipestat 4`: `stamps written` > 0 e `last t_vbl` != 0;
   - T1 WindowServer: `command_buffers` > 0 e `frames` > 0 dopo l'arm;
   - visivo sul DP: orologio aggiornato sulla schermata di login e trasparenze.
5. **Se i frame restano a zero con `rdna4-vbl=1`:** misurare il cookie con `ucprobe`, poi verificare il legame
   display machine ↔ framebuffer (sezione 6). Il passo successivo non è `fbname 1`, ma la revisione del vendor (sezione 7).

Rischi:

- Con `rdna4-vbl=1` il framebuffer espone il VBL già dalla prima sessione di WindowServer. Questo cambia il frame pacing
  anche per la schermata di login. È un timer software, non un IRQ: può avere jitter.
- Il flag non scrive registri hardware. Il rischio è sul comportamento del framebuffer, non sulla GPU.
- L'ordine di inizializzazione è il punto più fragile (sezione 4): va verificato con `ucprobe` al boot successivo.

## Limiti

- Il cookie `pipe+0xd8` non è stato misurato. `accel ucprobe 0` ha risposto `FAILED (0xe00002e2)` senza output, come
  `accel pairing 0`. La chiave dell'inferenza è il codice (RDNA4FB e Cobalt), non una lettura diretta.
- Non ho visto le chiamate di CoreDisplay a `registerForInterruptType`: non sono nei log.
- Non ho analizzato i binari Apple (AppleGraphicsDeviceControl, IOAccelFamily, CoreDisplay). Le affermazioni sul
  comportamento di `super::registerForInterruptType` e del display machine sono riportate dal codice e dai commenti del team.

## Azioni eseguite sul guest

- Letture: `ioreg -l -w0`; `/usr/bin/log show` (senza sudo; `sudo -n log` non è autorizzato); `navi48test accel pipestat 0`
  e `4`; `sysctl kern.bootargs`; lettura di `/private/tmp` (kill file e `n48m-starts`).
- Due verbi inviati per errore e poi verificati: `accel pairing 0` e `accel ucprobe 0`. Entrambi sono documentati come
  sola lettura nel sorgente. Hanno risposto `FAILED (0xe00002e2)` senza output. Dopo, `IOAccelTypes` risulta ancora
  presente e `pipestat 0`/`4` identici a prima.
- Nessun riavvio, nessun arm/disarm, nessuna installazione, nessun sudo sull'host, nessun commit.

## File

- `research/hw_dump/v8_boot44/compositor_diag/`: `ioreg_full.txt`, `wslog_25m.txt`, `wslog_postboot.txt`, `navi_events.txt`,
  `compositor_grep.txt`, `evidence_extract.txt`, `pairing_and_bootargs.txt`, `ucprobe0.txt`, `state_at_start.txt`,
  `final_state_check.txt`, `SHA256SUMS`.
- Codice citato: `cobalt64/src/navi48-bringup/src/amd/native_disp_flow.h`, `cobalt64/src/navi48-bringup/src/apple/DisplayPipeGuard.cpp`,
  `cobalt64/src/navi48-bringup/src/apple/Navi48AccelPeer.cpp`, `cobalt64/tools/native/navi48accel/src/Navi48Accel.cpp`,
  `cobalt64/tools/pc/arm-gpu-desktop.sh`, `tools/vm/prepare-gpu-test-stage.py`, `tools/vm/deploy-metal-stack.sh`,
  `research/ext/RDNA4FB-n44/src/framebuffer.cpp`, `research/ext/RDNA4FB-n44/README.md`.
