# P1 / P2 display: stato del boot24 (21 ottobre 2026)

## Stato: P1 bloccata prima dell'adozione (serve una regola sudo nel guest)

Boot24 avviato con `N4X_GPU_ROMBAR=1 N4X_GPU_PRIMARY=1 tools/vm/start-gpu-test-vm.sh --start`, EFI P1
(`a412c4dc…`, `--primary --metal-disp`, csr 0x03, amfi_get_out_of_my_way=1). Checksum pre-avvio in
`research/hw_dump/p1_boot24/pre_boot_sha256.txt`.

- Il monitor DP ha mostrato picker OpenCore, boot e login window di macOS (riferito dal coordinatore).
- Guest raggiungibile in SSH sulla porta 2223 con la chiave della VM di build (`/mnt/vm/builds/build-vm-ed25519`,
  utente `test`). Nessuna password inserita. Guest 26.6.2 / 25G83, WindowServer in esecuzione, 0 utenti connessi.
- `navi48test` non era nel guest: compilato dal sorgente `cobalt64/tools/pc/navi48test.c` (clang, 0 warning, sha256
  `15df385d…`), senza privilegi.
- `pipeadopt` (verbo 83) NON eseguito. `sudo -n` nel guest non autorizza `navi48test`: `sudo -n -l` elenca NOPASSWD
  solo per shutdown, mkdir, mv, cp, chmod, chown, tar, xattr, kmutil, launchctl e il nub. Senza root,
  `navi48test accel pipestat 0` fallisce con `IOServiceOpen failed (0xe00002e2)`.
- Di conseguenza non sono state fatte letture HUBP0 (B1) né armamento (P2).

## Cosa serve per procedere (decisione utente, nella VM di test)

Da un terminale del guest con la password dell'utente `test` (non eseguito da me), per la regola di
`deploy-metal-stack.sh --sudo-help` più le voci che il kit di armamento richiede e che oggi mancano:

```
test ALL=(root) NOPASSWD: /Users/test/navi48-staging/navi48test *
test ALL=(root) NOPASSWD: /usr/bin/touch, /bin/rm, /usr/bin/killall
```

Le voci `touch`, `rm`, `killall` servono all'armamento (`--arm-desktop`: flag headless, rollback, riavvio di
WindowServer). Senza queste voci il kit si ferma al primo passo che le usa. `pgrep` non richiede sudo.

Nota: allargare la regola a `navi48test *` consente qualunque verbo di root alla VM di test. È il compromesso già
accettato per `mtlprobe`, da fare solo sulla VM di test.

## Prossimi passi dopo la regola

1. `navi48test accel pipeadopt` (unica scrittura di P1), poi `pipestat 0` (bit 2 = adottata).
2. Lettura read-only di HUBP0 con `navi48test accel dispcensus plane` (pagine 10..43, marcate READ-ONLY): pitch,
   viewport, formato. Atteso per B1: 2560x1440, pitch 2560, ARGB8888 lineare.
3. P2 solo dopo P1 e con via libera: `deploy-metal-stack.sh --arm-check`, `--arm-desktop --dry-run`, poi `--arm-desktop`.

## Evidenze

- `research/hw_dump/p1_boot24/`: `pre_boot_sha256.txt`, `start_time.txt`, `guest_p1_adopt.txt` (+ `.sha256`).
- Seriale del boot: `/mnt/vm/images/macos-gpu-test/diagnostics/serial.log` (il boot23 è in `research/hw_dump/p0_boot23/`).
- Nessun commit, nessuna modifica al repo oltre a questo report e alle note in `FASI.md`.

## Aggiornamento (stessa sessione, dopo autorizzazione del coordinatore)

Le regole sudoers sono state installate nel guest: `/etc/sudoers.d/navi48-test` (root:wheel 0440, validato con
`visudo -c`, password passata solo su stdin, mai in file). Restano le due righe della P0 più:

```
test ALL=(root) NOPASSWD: /Users/test/navi48-staging/navi48test accel *
test ALL=(root) NOPASSWD: /usr/bin/touch /private/tmp/n48m-headless-no, /bin/rm -f /private/tmp/n48m-headless-no, /usr/bin/killall -9 WindowServer
```

Esiti:

- **Nub Metal**: `n48nub publish` eseguito (il primo `pipeadopt` senza nub dava status 3, "publish the nub first").
- **pipeadopt**: status **9** (`kPipeMismatch`, "the pipe does not belong to this accelerator / display machine / RDNA4FB").
  Flags restano 0x31: bit 2 (adottata) assente. La pipe è vista (ours 1/1, tracciata), ma il controllo di
  coerenza (back-link accel/DM/RDNA4FB, framebuffer, conteggio 1) non passa. La causa non è determinabile senza
  cambiare codice o leggere di più; il verbo non modifica lo stato quando rifiuta.
- **B1 (lettura `dispcensus plane`, read-only)**: CHIUSO nella lettura. HUBP0 `PRIMARY_SURFACE_ADDRESS` = 0x80_00000000
  (offset 0 della VRAM), `SURFACE_PITCH` = 0x9ff (pitch 2560 px), `SURFACE_CONFIG` = 0x08 (ARGB8888), viewport
  `PRI_VIEWPORT_DIMENSION` = 0x05a00a00 (2560x1440), `TILING_CONFIG` = 0x80 (SW_MODE 0, lineare).
  Il boot15 (display emulato) dava pitch 832: il pitch 2560 si vede solo con `--primary`.
- **fbname 1 (punto 9)**: NON eseguito. Il sorgente (`cobalt64/tools/pc/navi48test.c` r.1778-1779) dice "DEFAULT OFF ...
  Not to be run without an adversarial review". È una rinomina di classe a runtime su un oggetto IOKit vivo, quindi un
  rischio di stabilità del kernel, non solo funzionale. Per la regola del coordinatore non procedo. La ricetta
  `arm-gpu-desktop.sh` (r.18) lo include, quindi il percorso a un monitor lo richiede.
- **arm-check (sola lettura)**: FAIL. (a) il boot non ha `navi48-metal-ws=1`: P2 richiede un boot nuovo con EFI
  `--metal-ws`, e l'adozione va rifatta in quel boot; (b) il digest EFI del piano non corrisponde più, perché il qcow2 è
  scrivibile e cambia dopo il boot (era già la nota del coordinatore). `--arm-desktop` non è stato eseguito.

Stato: P1 non completato (pipeadopt rifiutato). P2 non eseguito. Nessun armamento, nessun flag headless creato.
VM accesa, sulla login window, WindowServer in esecuzione, 0 utenti. Spegnimento non eseguito.

Evidenze aggiuntive: `research/hw_dump/p1_boot24/guest_p1_adopt_run.txt`, `guest_p1_nub_publish.txt`,
`guest_p1_pipeadopt_2.txt`, `guest_p1_dispcensus_plane.txt`, `arm_check_readonly.txt`, `p1_evidence.sha256`.

## Analisi status 9 e piano RDNA4FB (21/10, dopo la raccolta del guest)

### Evidenze raccolte (boot24, spento regolarmente: `vfs_unmountall(system) end`, `qemu-img check` senza errori)

- `ioreg`: nessun servizio `RDNA4FB` o `AMDRDNA4FB` (0 occorrenze). Il framebuffer del GPU è `.Display_boot`,
  classe `IONDRVFramebuffer` (IONDRVSupport di Apple), sotto il PCI della GPU. Presenti anche `AMDSupport` (Apple, 7.0.1)
  e `com.navi48.accelprobe` 0.0.7 (aux) e `com.navi48.bringup` 0.0.664. `kmutil`: nessun RDNA4FB.
- Seriale (`serial_p1_boot24_shutdown.log`, sha256 `ad3d1f2f…`): r.3427-3428 `pipe adopt: requestProbe(1) -> 0`, poi
  `the pipe does not belong to this accelerator / display machine / RDNA4FB (9)`. Console: `2560x1440 rowBytes 10240`,
  VRAM offset 0 (r.313-314).
- `dispcensus plane`: B1 chiuso (vedi sopra).

### Condizioni di kPipeMismatch (codice)

- `native_disp_pure.h:195`: `pipe_verdict` restituisce `kPipeMismatch` quando `count != 1`, o `!backAccel`, o `!backDm`,
  o `!backFb`, o `!fbOurs`. Il percorso è quello legacy: `navi48-m6` assente, quindi `ents.n == 0` (`native_disp_pure.h:192`).
- `native_disp.cpp:407-435` (`probe_pipe`): `fbOurs` (r.430) e `backFb` (r.431) sono impostati solo se `find_fb()` trova un
  servizio. `find_fb()` (r.396-405) cerca `RDNA4FB` poi `AMDRDNA4FB`. Se non c'è, entrambi restano false.
- Con il nostro ioreg `find_fb()` non trova nulla: **fbOurs = false, backFb = false, quindi kPipeMismatch (9)**. Ipotesi
  verificata per il ramo fbOurs/backFb. I back-link backAccel/backDm (r.434-435) non sono osservabili senza il probe: restano da
  confermare al boot con RDNA4FB.
- Nota: `find_fb` usa `waitForMatchingService(m, 0)` (r.401), non bloccante quando non c'è niente (il verbo è tornato subito).

### Conferma RDNA4FB

Il percorso Cobalt64 presuppone RDNA4FB come framebuffer: `fb_name_ok` (`native_agdc_pure.h:65`), `find_fb`, EDID da
`EDID,DDC<line>` di RDNA4FB (`Navi48DisplayNub.cpp:154-168`), VRAM range (`Navi48UserClient.cpp:37`), scanout
(`Navi48Bringup.cpp:3989-4021`). Senza RDNA4FB la pipe non si adotta, per costruzione.

RDNA4FB (`research/refs/RDNA4FB`, progetto BSD-3 separato, non tracciato da git) fa match solo su 0x7550/0x7551
(`Info.plist` r.28-38 e `framebuffer.cpp:2038-2047`). Legge la console da `PE_state.video`, usa BAR5 per l'MMIO (512 KiB
su questa VM, come sul host: `lspci`, Region 5), prende connettori e AUX dalle tabelle VBIOS (`getDisplayPaths`, il
numero di AUX viene dal record del connettore, quindi nulla di Navi48 è cablato lì). Scrive il minimo: AUX/DDC per EDID,
DPCD per il sleep, cursore opt-in, nessun riprogrammazione dello scanout (README).

### Modifiche applicate (sicure, nessuna al kext Cobalt64)

1. Patch RDNA4FB `cobalt64/third-party/rdna4fb-n44/0001-navi44-device-match.patch`: aggiunge `0x75901002` al match
   (`Info.plist`) e accetta `0x7590` nel probe (`framebuffer.cpp`), con log della variante. Nessuna modifica per Navi 48.
   Il patch si applica pulito alla copia pristina (`git apply --check`).
2. Kext compilato nella VM di build (macOS 25G83, `make` con `MKSDK` = `research/ext/MacKernelSDK`, perché il submodule di
   RDNA4FB è vuoto): `/mnt/vm/builds/rdna4fb-n44-20261021/RDNA4FB.kext`. Sha256 binario `1f95d5e1…`,
   `SHA256SUMS` nella stessa cartella. Log in `research/hw_dump/build_rdna4fb_n44/`. Il match nel binario è verificato con `plutil`.
3. `tools/vm/deploy-metal-stack.sh` (solo `remote_arm_script` e il piano):
   - presupposto guest: `com.hackintosh.RDNA4FB` caricato, altrimenti stop (r.361-362);
   - `fbname 1` disattivato di default, attivabile con `N48_ARM_FBNAME=1` (r.390-392);
   - `pipeagdc 1` ora richiede `agdc status : 0`: prima bastava la riga, e status 1 (boot-arg assente) passava (r.50-51).
   Sintassi verificata (`bash -n`, script guest estratto e validato). Il dry-run host si ferma correttamente sui presupposti di P1.
4. Linux: `tools/linux-check-kext.sh` 53/53 ok sia Navi 44 sia Navi 48 (nessuna modifica al kext Cobalt64).
   Il controllo Linux di RDNA4FB non è significativo: fallisce identico sulla copia pristina per l'header IOGraphics
   mancante, quindi la verifica vera è la build macOS.
5. EFI P2 preparata: `prepare-gpu-test-stage.py 17 --native-s1b --metal --primary --metal-disp --metal-ws`, `--check` superato
   con `N4X_GPU_ROMBAR=1 N4X_GPU_PRIMARY=1`. VM spenta, non avviata.

### fbname 1: revisione avversariale

- Cosa scrive: un solo puntatore (8 byte), il campo `className` di `OSMetaClass` della classe `RDNA4FB` (`gMetaClass`,
  dati del kext RDNA4FB). Da `"RDNA4FB"` a `"AMDRDNA4FB"` (simboli interned). Cambia solo i lettori di stringhe
  (`getClassName`, `IOObjectCopyClass`, ioreg, `CFStringFind` in CoreDisplay per il vendor AMD). Il matching IOKit usa
  il nome di registrazione, quindi non cambia.
- Quando: solo a comando esplicito `accel fbname 1`, con RDNA4FB caricato. Senza RDNA4FB rifiuta (`FBN_NO_FRAMEBUFFER`).
- Guardie: l'indirizzo viene trovato per ricerca, deve essere unico (`fbname_scan.h`), il predecessore deve essere un puntatore
  kernel plausibile e la sua classe deve essere `IOFramebuffer` (`navi48_fbname.cpp:174-181`), read-back dopo la scrittura.
- Punto debole: la verifica del predecessore (r.174-176) dereferenzia la parola prima di sapere che punti a memoria mappata.
  `n48_fbname_plausible_kptr` controlla solo allineamento e metà alta. Un falso positivo porterebbe a un panic del kernel.
  Il rischio è basso ma non nullo: è un rischio di stabilità, non solo di funzionalità.
- Ripristino: `accel fbname 0` e `restore_on_unload` (solo dallo stop del kext Navi48Bringup, non da quello di RDNA4FB).
- Cosa può rompersi: CoreDisplay vede un vendor AMD e può attivare percorsi Apple per AMD sul nostro framebuffer. Effetti
  in WindowServer possibili, con loop protetto da `n48m-starts`.
- Serve con RDNA4FB caricato? **Per l'adozione no**: `fbOurs` accetta già `RDNA4FB` (`native_disp.cpp:430`).
  Serve solo al vendor di CoreDisplay, e non è dimostrato che serva al desktop su Navi 44.
- Decisione proposta: **non eseguirlo al primo boot P2**. Il kit lo lascia disattivato (`N48_ARM_FBNAME=0`). Se WindowServer
  o CoreDisplay mostrano un comportamento legato al vendor, si rivaluta con l'utente.

### Piano minimo P2 (da eseguire solo con il tuo via libera)

Stato host: VM di test spenta; EFI P2 pronta; kext RDNA4FB n44 pronto (`/mnt/vm/builds/rdna4fb-n44-20261021/`).

1. Boot: `N4X_GPU_ROMBAR=1 N4X_GPU_PRIMARY=1 tools/vm/start-gpu-test-vm.sh --start` (seriale in `diagnostics/serial.log`).
   Il monitor deve essere sul DP quando compare la login window.
2. Guest (chiave della VM di build, porta 2223, nessuna password): `sudo -n ~/n48-metal/n48nub publish`.
3. Installazione RDNA4FB: `scp` del kext in `~/rdna4fb-stage/`, poi `sudo -n cp -R` in `/Library/Extensions/`,
   `sudo -n chown -R root:wheel`, `sudo -n kmutil load -b com.hackintosh.RDNA4FB` (o `kmutil libraries` + load).
   **Approvazione**: su Tahoe un kext di terze parti richiede il consenso in Impostazioni (Privacy e sicurezza). Il consenso
   va dato dove si vede il display: il DP, primario in questo boot. Alternativa: approvazione in una sessione GTK
   (`N4X_GPU_PRIMARY=0`) come in P0, se il consenso resta valido tra i boot (per Navi48Accel è successo). Da decidere.
4. `sudo -n ~/navi48-staging/navi48test accel pipeadopt`: atteso status 0, poi `pipestat 0` con bit 2.
5. **Decisione AGDC**: `pipeagdc 1` (ora obbligatorio per l'armamento) richiede il boot-arg `navi48-agdc=1`, che
   `prepare-gpu-test-stage.py` non ammette. Il boot-arg pubblica un oggetto AGDC con manipolazioni di vtable e metaclass (`DisplayPipeGuard.cpp`):
   è un rischio di stabilità, non di sola funzionalità. Non l'ho aggiunto. Senza AGDC il kit si ferma prima di toccare la
   pipe, desktop su CPU. Serve una tua decisione per aggiungerlo.
6. `deploy-metal-stack.sh --arm-check` (sola lettura), `--arm-desktop --dry-run`, poi `--arm-desktop` digitando `ARM`
   solo con 0 utenti nel guest. `fbname` resta disattivato.
7. Stop al primo: panic (seriale), WindowServer in loop (`n48m-starts`), `RDNA4FB` che non fa start, pipe non adottata.

Recupero: `sudo -n mv /Library/Extensions/RDNA4FB.kext <dove>` e `sudo -n kmutil unload -b com.hackintosh.RDNA4FB`
(`rm` non è nella lista sudo del guest, quindi si usa `mv`). Il kill switch `rdna4-off=1` non è ammesso dal preparatore,
quindi serve una modifica all'EFI.

### Osservazione attesa dopo l'arm (per la domanda all'utente)

Login window ridisegnata da WindowServer sulla GPU: trasparenze dei menu e effetti attivi. Possibili riquadri magenta
temporanei, perché la spvcache è parziale: shader mancanti con fallback finché il daemon non traduce. Il monitor può
restare nero per qualche secondo durante il riavvio di WindowServer.

### Stato attuale

- VM di test spenta, VM di build spenta (quit QMP dopo `sync`, come P0: sudo non ha password sulla build VM, né è lecito configurarlo).
- Nessun flag headless creato. Nessun armamento. Nessun boot di test oltre P1 (boot24).
- Repo: `cobalt64/third-party/rdna4fb-n44/` (patch), `tools/vm/deploy-metal-stack.sh` (kit), `research/reports/p1_p2_display.md`,
  `research/hw_dump/p1_boot24/`, `research/hw_dump/build_rdna4fb_n44/`. Fuori da git: `research/ext/RDNA4FB-n44/`, `/mnt/vm/builds/rdna4fb-n44-20261021/`.
- Nessun commit.

## Boot25 (P2): stato al fermo per consenso GUI (21/10)

- EFI P2 preparata con `--metal-ws --agdc --rdna4fb <kext> --csr-active-config 0x03 --amfi-get-out-of-my-way`
  (`prepare-gpu-test-stage.py`, opzioni nuove `--agdc` e `--rdna4fb`). Voce `Kernel->Add` RDNA4FB presente, file in
  `EFI/OC/Kexts/RDNA4FB.kext`, boot-arg `navi48-agdc=1` presenti. `--check` superato.
- Injection OpenCore: RDNA4FB **non caricato**. Nessuna riga RDNA4FB nel seriale (`research/hw_dump/p2_boot25/`).
- Caricamento da `/Library/Extensions` (`sudo -n kmutil load -p`): **«com.hackintosh.RDNA4FB not approved to load. Please
  approve using System Settings»** (`kmutil_load_rdna4fb_attempt1.txt`). Serve il consenso GUI: l'approvazione è richiesta anche
  con `csr-active-config` 0x03.
- Nub Metal pubblicato (`navi48-metal`, registry 0x100000442). `pipeadopt` status 9 come nel boot24, perché manca RDNA4FB
  (`guest_pipeadopt_attempt1.txt`). `pipeagdc` non eseguito.
- Login window sul DP, 0 utenti. VM accesa.

Azione richiesta (utente, al monitor DP): vedi il messaggio al coordinatore. Dopo il consenso, va fatto il log out.

## Boot27 (P2, primary + metal-disp + metal-ws + agdc + rdna4fb): stato al fermo (21/10)

- Consenso RDNA4FB dato in GTK (boot26). Spegnimento pulito di boot26 (`vfs_unmountall(system) end`, nessun panic).
  Su boot26 `kmutil load` ha risposto «requires a reboot»: la registrazione è avvenuta, il caricamento dopo il riavvio.
- Panic a spegnimento di boot25 (P2, senza consenso, RDNA4FB assente): `Ticket lock ... unexpectedly owned` in
  `IOPlatformHaltRestartAction -> AppleSMC`, stessa firma del boot21. Seriale: `p2_boot25/serial_p2_boot25_shutdown_PANIC.log`.
  Chiuso con QMP `quit` dopo più di 8 minuti, disco OK (`qemu-img check`). Causa non determinata.
- Boot27: RDNA4FB caricato (0.0.1) e attaccato sotto `S30@6` (PCI della GPU), con `display0`/`AppleDisplay`.
  Nub pubblicato. `pipeadopt` status 0, flags 0x3b (bit 2 adottata, bit 4 non armata). `pipeagdc 1`: `agdc status : 0 (PUBLISHED)`.
- `--arm-check`: fallisce su «EFI verificata». Causa: il qcow2 è aperto da QEMU in scrittura (`qemu-img` riporta
  «Failed to get shared write lock») e il digest cambia durante il boot. Il controllo non può passare con la VM accesa.
  `do_arm` lo esegue prima del dry-run, quindi anche `--arm-desktop --dry-run` si ferma. Nessuna azione è stata eseguita.
- Bug corretto in `tools/vm/deploy-metal-stack.sh` (`remote_arm_script`, due righe): il parser di `pipestat 0` cercava
  `flags : 0x..`, ma il formato reale è `flags / factory mask : 0x3b / 0xd`. Regex ora `flags[^:]*: *0x..`. Verificato su
  entrambi i formati. Con il parser corretto i presupposti guest passano: `ARM_CHECK_PASS` (`arm_check_guest_after_parser_fix.txt`).
- Decisione richiesta: il controllo host «EFI verificata» va sostituito con un controllo valido a VM accesa (per esempio il
  digest registrato dal launcher al `--start`), oppure lo si esegue solo a VM spenta. Non l'ho modificato.

Stato: VM accesa, login window sul DP, nessun utente, nessun armamento, nessun flag headless.

### Armamento P2 (boot27), esito (21/10, ~15:41)

- Controllo EFI a VM accesa: `start-gpu-test-vm.sh --start` ora scrive `.launch-efi.sha256` (digest al lancio). Per boot27,
  avviato prima della modifica, il file è stato ricavato dal `pre_boot_sha256.txt` registrato subito prima del `--start`, e
  confrontato con `test-plan.json` (uguali). Il controllo «EFI verificata» usa il record quando `.vm.lock` è tenuto dal launcher,
  altrimenti il file live come prima.
- `ssh -n` in `guest_reachable`: lo stdin resta libero per la conferma ARM (prima `ssh` lo consumava).
- Status AGDC 12 («già pubblicato») accettato come pubblicato: `pipeagdc 1` rieseguito nello stesso boot.
- `--arm-check`: `ARM_CHECK_PASS` (`arm_check_after_fix.txt`). `--arm-desktop --dry-run`: ok (`arm_desktop_dry_run2.txt`).
- `--arm-desktop` con `ARM`: `ARM_OK`, pipe armata (flags 0x3f), WindowServer pid 1038 ripartito, 0 utenti.
  `accel+0xccf` = 1 (armato). `fbname` saltato (N48_ARM_FBNAME=0). Log: `arm_desktop_run.txt`,
  `guest_after_arm.txt`. Log AGDC: WindowServer (pid 1038) fa chiamate `vendor_doDeviceAttribute` all'AGDC.
- Crash report di WindowServer nella cartella DiagnosticReports: `WindowServer-2026-10-21-123958.ips`, di un'ora precedente
  alla sessione (non di questo arm).
- Non verificato: l'immagine sul DP. Da confermare con l'utente (vedi messaggio al coordinatore).

### Daemon di traduzione e shader dopo l'arm (boot27, 21/10 ~15:43)

- Daemon `com.navi48.translate`: installato (`/Library/LaunchDaemons/com.navi48.translate.plist`, `/usr/local/navi48/` root:wheel),
  `state = running`, utente `nobody`, come in P0. Stato: `translate_daemon_state.txt`, `translate/n48m-translate-state/`.
- Traduzioni: 13 `OK`, 0 fallite (`translate.log`, `done`). I due nuovi, dopo l'arm: `29164ba4…` (GPUPass, fragment, 8968 B)
  e `c0708ccd…` (ViewportToNDC, vertex, 1708 B), entrambi `OK` alle 15:41:25 e 15:41:27. Validati da `spirv-val` reale.
- WindowServer (uid 88) all'avvio (15:41:23): **due soli miss** nella spvcache, quelli due shader. Dump AIR su `/private/tmp/n48m/88`,
  poi traduzione e hot-swap alle 15:41:27: `HOT-SWAP ViewportToNDC / GPUPass: fallback -> real (built in 10.553 ms)`. Nessun
  riavvio. Dopo: `gfx=2 comp=0 imports=0`, `T1 idle` (nessun frame nei 60 s successivi).
- Non confermata l'ipotesi del coordinatore «shader mancanti per blur e materiali»: nei log non ci sono altri miss, né richieste di
  compute (`comp=0`, nessun `COMPUTE FALLBACK`). Sul DP la data trasparente è coerente con i due shader attivi; l'orologio grande
  scomparso non è spiegato dai log. Possibile causa: WindowServer non disegna frame (`frames=0`) finché non cambia lo schermo.
- Nessun fallimento: nessun AIR da copiare per analisi. I due AIR sono in `research/ext/n48m-air-boot27-20261021/` (fuori da git,
  derivano da shader Apple), con `SHA256SUMS`. Metadati JSON in `research/hw_dump/p2_boot27/n48m_ws/` e `n48m_ws_json.sha256`.
- Log: `ws_navi48metal_fallback_40m.txt`, `ws_log_20m_user.txt` (troncato a 400 righe). `log show` come root non è nella lista
  sudo del guest: la lettura è solo a livello utente, con messaggi pubblici.

### Input QMP e catena di presentazione (boot27, 21/10 ~15:44-15:46)

- Input: tablet USB assoluto (`query-mice`: `QEMU HID Tablet`, absolute) con 6 movimenti assoluti; tasto Shift giù/su via
  `input-send-event`. Nel log di WindowServer il tasto arriva (`Keyboard event` → SecurityAgent, 15:45:04). I movimenti del
  tablet non compaiono nel log filtrato.
- Contatori prima e dopo l'input (`counters_before.txt`, `counters_after_input.txt`), invariati: `pipestat 0`: `hook calls 267 = 1`,
  `submit pass-through / will-perform 0 / 0`, `frames copied 0`, `submit interval 0`; `pipestat 4`: `last t_vbl 0`, `stamps written 0`.
  WindowServer: `T1 counts ... frames=0 command_buffers=0`, `T1 idle` a ogni minuto (15:42:23, 15:43:23, 15:44:23, 15:45:23).
- Nel seriale, unica chiamata di slot 267 sulla pipe dopo il reload: `slot 267 ... -> stand-in object; the pipe is marked active (call 1)`.
  Nessuna chiamata successiva.
- **Punto di arresto, nel log di WindowServer (pid 1038), 15:41:22.981 - 15:41:23.181**:
  - `(reg) gpu ... vid.did=1002.7590` e `Creating FB 1 of 1`, `fbRegID 0x100000319`, cioè RDNA4FB (id ioreg 0x100000319). Il framebuffer è registrato.
  - `IOFBSetDisplayModeAndDepth: Setting mode 0x0 with depth 0x0 on displayID: 0x0`, poi `Failed to obtain mode info from IOFBGetDisplayModeInformation()`.
  - `Setting main display 0x00000000 offline` in `CGXConstructVirtualFramebuffer`, `Display id 0x00000000 -> ...`. Il display fisico non va online per CoreDisplay.
  - WindowServer compone quindi su un framebuffer virtuale (`com.apple.VirtualDisplay`, `Metal compositor activated`). Il DP non riceve frame.
  - Errori ripetuti `set_device_transfer_callback: can't set device gamma (0xe00002c7)` e `GetThermalCompensationAttributes ... (e00002ce)`:
    il framebuffer non fornisce gli attributi gamma/colore.
- RDNA4FB, lato kext: `getDisplayModeCount` = 1, `getInformationForDisplayMode` OK (2560x1440 60 Hz), `getConnectionCount` = 1,
  `kConnectionFlags` = 0, `kConnectionEnable` = 1 (`research/ext/RDNA4FB-n44/src/framebuffer.cpp:2232-2262`, `2364-2387`).
  L'ioreg mostra `IOFBConfig` con `IOFBModes` ID 1 (2560x1440, 60 Hz) e `IOFBNeedsRefresh = Yes`
  (`ioreg_rdna4fb_display_nodes.txt`). `display0`/`AppleDisplay` sono attaccati sotto RDNA4FB.

Conclusione: la catena si ferma prima di Metal. RDNA4FB si attacca, WindowServer ne crea il framebuffer, ma CoreDisplay
non porta il display online (`displayID 0`, richiesta di modo 0 fallita), quindi non c'è un display fisico su cui comporre.
WindowServer non emette command buffer che scrivono la superficie di display (`frames=0`), la pipe non riceve submit
(`submit 0`), e l'HUBP0 non riceve flip. Il cursore non si muove sul DP perché nessun frame arriva al display.

Cosa dovrebbe vedere l'utente: il DP mostra l'ultimo frame scritto dalla console (login window, date e orologio come
prima dell'arm). Il cursore non si muove. Non c'è magenta nuovo.

Da indagare (non fatto, per non riavviare): perché CoreDisplay non considera online il display di RDNA4FB, cioè quali
proprietà/flag di connessione o di framebuffer (`kConnectionFlags`, `IOFBNeedsRefresh`, dati di `IODisplayConnect`) fanno
diventare un display "online" per CoreDisplay. Le modifiche richiedono un boot di prova.

### Boot30 (P2 con RDNA4FB v2, 21/10 ~15:52-15:55)

- RDNA4FB v2 caricata: sha `a5ba00d7…` su disco e nel kext caricato (dimensione 0xa354, v1 0xa324). `IOFBConfig` dichiara
  2560x1440 a 120 Hz (DM 0x78). Il consenso è stato dato in GTK (boot29) e non è servito un riavvio.
- CoreDisplay PRIMA dell'arm (WS pid 194): `Creating FB 1 of 1`, `Setting mode 0x0 ... displayID 0x0`,
  `Failed to obtain mode info`. Il display principale resta `0x00000000` offline. Compare
  `Unable to find display pipe for IOFB service / regID: 0x9473 / 0x100000320`.
  Il modo a 120 Hz NON ha cambiato il comportamento: CoreDisplay non porta il display online.
- Dopo `pipeadopt` (status 0, flags 0x3b) e `pipeagdc 1` (PUBLISHED): nessun nuovo evento CoreDisplay sul display;
  il display principale resta offline.
- `--arm-check` ARM_CHECK_PASS; `--arm-desktop --dry-run` ok; `--arm-desktop` ARM_OK, pipe armata (flags 0x3f), WS pid 724.
- Contatori dopo l'arm (`counters_after_arm.txt`): `hook calls 1`, `submit pass-through 0`, `frames copied 0`,
  `submit interval 0`, `last t_vbl 0`. WindowServer: `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`.
- Conclusione: il display non è online per CoreDisplay, quindi WindowServer non presenta frame sul DP (frames=0, flip 0).
  Il cursore hardware resta l'unico elemento visibile sul DP (osservato dall'utente prima dell'arm).
- Atteso dall'utente dopo l'arm: nessuna trasparenza nuova, nessun riquadro; l'immagine resta quella dell'ultimo frame.

### Analisi fbname vs pipe lookup (21/10, dopo boot30)

- Codice: `navi48_fbname.hpp` dichiara lo scopo di fbname: far risolvere a CoreDisplay il vendor AMD (bit 0x4) via
  `GetGPUVendorForFramebufferService`. Cambia solo i lettori di stringhe (`navi48_fbname.cpp`, commento in testa).
  `fb_name_ok` e `probe_pipe` accettano già RDNA4FB, quindi l'adozione non dipende dal nome.
- La pipe per CoreDisplay passa per IOPresentment: `native_agdc_pure.h:6` (serve AGDC per le risposte 1/0x980/0x921/0x711),
  `agdc-probe.c:4-6` (ioPresentmentGetNodeMap sale dai parent del framebuffer). Non c'è nessun riferimento al vendor per la lettura della pipe.
- Log (`ws_pipe_vendor_lines.txt`): `IOPresentment: Unable to acquire map` compare a ogni avvio di WindowServer prima dell'AGDC
  (`agdc 0x0`). Sul pid 724, dopo l'arm, l'AGDC è registrato (`agdc 0x10000043f`) e l'errore non compare più.
  `Unable to find display pipe for IOFB` resta solo su pid precedenti (187, 195, 1038).
- Conclusione: l'ipotesi del coordinatore (la pipe dipende dal nome/vendor AMD) non è supportata dal codice. Il lookup della pipe
  dipende da AGDC e dalla pipe adottata, e l'errore sparisce con l'AGDC. fbname NON è stato eseguito.
- Causa più probabile del display ancora offline: CoreDisplay non completa la creazione del display, perché il modo non passa
  il controllo (`Failed to obtain mode info` su displayID 0x0) anche con AGDC e pipe presenti. Da confermare con un test esplicito:
  fbname 1 come esperimento di vendor (rischio accettato in VM), oppure lettura del modo richiesto da IOPresentment.

### Esperimento fbname 1 (boot30, 21/10 ~15:56-15:58)

- Prima: WindowServer pid 724, framebuffer `RDNA4FB`, pipe armata (0x3f), CoreDisplay `displayID 0x0`, `Failed to obtain mode info`,
  `frames=0`. Disarmo pulito (`pipearm 0`, flags 0x3b) prima della ricetta.
- Ricetta (`deploy-metal-stack.sh --arm-desktop`, `N48_ARM_FBNAME=1`): `pipeagdc 1` (12, già pubblicato), `fbname 1`
  → `class name NOW: AMDRDNA4FB` (ioreg `fb0:0 /AMDRDNA4FB`), `pipearm 1` → ARMED/ok, `killall -9 WindowServer`.
- Dopo: WindowServer pid 1280 e 1256 **abortiti** (SIGABRT, `consecutiveCrashCount 1`), crash report
  `WindowServer-2026-10-21-155716.ips` e `155720.ips` (in `fbname_exp/`). Stack: `CoreDisplay_CreateDisplayForCGXDisplayDevice`
  → `__assert_rtn` → `abort` (chiamato da `AddCGXDisplayDeviceToDeviceList` ← `CGXDisplayDriverInitialize` ← `WSInitialize`).
  CoreDisplay in quel punto stava creando il display con il framebuffer rinominato: `Can't get value for key 'AMDFramebuffer'`.
  Il bundle Navi48Metal ha contato 4 avvii anomali in 300 s e ha dichiarato DECLINED (crash counter ≥ 3).
- Rollback del kit: `pipearm 0`, `fbname 0`, flag rimosso. Nome classe riportato a `RDNA4FB`, pipe disarmata (flags 0x3b).
  WindowServer pid 1323 in esecuzione alle 15:57:30. `/private/tmp/n48m-starts` ha 5 voci.
- Panic del kernel: nessuno (seriale senza `Debugger called`).
- Conclusione: fbname 1 cambia il percorso di CoreDisplay (AMD) e fa asserire CoreDisplay sul nostro framebuffer. Non porta il
  display online. La causa più probabile dell'offline è quindi il percorso di creazione del display di CoreDisplay per RDNA4FB
  (modo richiesto con displayID 0x0), non il nome.

## Boot31 (P0 + kext di sicurezza, consenso RDNA4FB) e boot32 (P2 con RDNA4FB v3 e watchdog), 21/10 ~16:45-16:58

Evidenze: `research/hw_dump/safety_boot31/` (seriale, heartbeat, log watchdog, `ws_prearm_log_show.txt`, `SHA256SUMS`) e
`research/hw_dump/p2_boot32/` (`coredisplay_summary_boot32.txt`, `ws_coredisplay_last15m.txt`, `ws_postarm_log_show.txt`,
`guest_postarm_raw.txt`, `user_observation_after_arm.txt`, `serial_p2_boot32_*.log`, `SHA256SUMS`).

### Boot31 (P0, kext navi48-safety, RDNA4FB v2 caricato da /Library/Extensions)

- Kext di sicurezza partito con le protezioni PRESENT. Ladder completo a stage 17, esito 0x0, S1b POSITIVE PASS. Dettagli in `gpu_safety.md` sez. 10.
- RDNA4FB v2 già caricata (consenso dei boot precedenti). Installata la v3 in `/Library/Extensions` (v2 spostata in `~/rdna4fb-stage/backup-v2/`). `kmutil load -p` ha risposto «not approved to load»: la richiesta di consenso è partita. L'utente ha dato il consenso in finestra QEMU, senza riavvio.
- Spegnimento con `shutdown -h`, pulito. Nessun crash WindowServer nel boot.
- Crash WindowServer presenti nel guest, tutti precedenti a questo boot: `WindowServer-2026-10-21-123958.ips` (pid 201, `CoreDisplay::Assert` in `CGXMappedDisplayStart`, prima di fbname), `…155716.ips` (pid 1256) e `…155720.ips` (pid 1280), entrambi del boot30 (fbname 1). Il dialogo «WindowServer si è chiuso in modo inaspettato» mostrato al login riguarda questi file, non un crash del boot31.

### Boot32 (P2: --primary --metal-disp --metal-ws --agdc --rdna4fb v3, csr 0x03, amfi)

- EFI P2 e hash pre-avvio: `p2_pre_boot_sha256.txt` (EFI `50ca1b18…`, kext sicurezza `cb18a1f9…`, RDNA4FB v3 `61fac769…`). `--check` con `N4X_GPU_PRIMARY=1` superato. Il display primario è la RX 9060 XT.
- RDNA4FB v3 caricata dalla EFI. Dimensione in memoria `0xa514`, contro `0xa354` della v2: la verifica è indiretta, perché non ho hashato il binario caricato.
- Sicurezza: START con protezioni PRESENT. Un campione iniziale a 60 °C, poi 33–39 °C. Nessun WARN/TRIP. Dettagli in `gpu_safety.md` sez. 10.
- Utente sul DP: login window CPU-rendered (orologio grigio scuro opaco, campo password opaco, data con bagliore). Nessun login.

**CoreDisplay prima dell'arm (WS pid 194)**

- `Display 0x1b572300: Unit 0: Startup Mode 2560 x 1440 ... IOReturn 0x0`, `online enabled, Bounds (0,0)[2560 x 1440]`. Il display fisico è online. La riga Startup Mode NON porta `0xe00002c7`.
- `InstallTiming` per 2560x1440 NON accettato: falliscono 120/144/99.9/60 Hz con `0xe00002c7`, e 120 Hz anche con `0xe00002dd` (modo 0x80001000). Falliscono anche gli altri modi.
- `Creating FB 1 of 1`, `IOFBSetDisplayModeAndDepth: Setting mode 0x0 ... displayID 0x0 ... Failed to obtain mode info`. La richiesta di modo fallisce ancora.
- `com.apple.VirtualDisplay:server` creato subito dopo il display fisico. Quindi il VirtualDisplay NON è assente.
- Il display fisico NON risulta principale: restano `Setting main display 0x00000000 offline`, e nessuna riga `main display 0x1b572300`.
- Gamma: 17 righe `set_device_transfer_callback: can't set device gamma (0xe00002c7)`.

**Armamento (boot32)**

- `n48nub publish`: state 1 (published). `pipeadopt`: il primo ha dato status 0 ma `pipestat` ha letto flags `0x31` (adottata assente); il secondo ha dato `0x3b`, con bit 2 (adottata). Il kit ha accettato dopo il secondo. Da ricordare: il primo `pipeadopt` non ha lasciato traccia evidente.
- `pipeagdc 1`: status 12 (già pubblicato). `--arm-check`: ARM_CHECK_PASS. `--arm-desktop --dry-run`: ok.
- `--arm-desktop` con ARM: ARM_OK. WindowServer pid 1247. Flags `0x3f`, pipe armata, `accel+0xccf` = 1.
- `fbname` saltato (default N48_ARM_FBNAME=0).

**CoreDisplay e SkyLight dopo l'arm (WS pid 1247)**

- Stesse righe del pre-arm: Startup Mode 2560x1440 (IOReturn 0x0), display online, VirtualDisplay creato a 16:54:46.
- `SkyLight: Metal compositor activated` (16:54:46).
- `InstallTiming`: falliscono ancora i modi 2560x1440 con `0xe00002c7` e `0xe00002dd`. Il modo 0x80000000 e 0x80001000 falliscono entrambi.
- `Navi48Metal` T1 counts (16:54:56): `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`.
- `pipestat 0`: hook calls 1, submit pass-through 0, will-perform 0, frames copied 0, completed 0.
- `pipestat 4`: vblank timestamp switch ON, stamps written 0, skipped tutti 0.
- Nessun frame e nessun flip misurati fino alla chiusura (ultima riga di log 16:57:27).

**Osservazione dell'utente dopo l'arm (foto del DP, riportata dal coordinatore)**

- Lo schermo si è ridisegnato. La data è visibile. L'OROLOGIO è scomparso. Il campo password non ha trasparenza.
- Prima dell'arm (CPU) l'orologio c'era e la data aveva già il bagliore.
- Interpretazione: il ridisegno avviene, ma nessun frame Metal misurato (`frames=0`) scrive la superficie. Quindi il cambiamento non è attribuibile al compositor Metal senza una prova. Da indagare: la sorgente del ridisegno e perché l'orologio sparisce.

### Stato

- Il desktop su GPU NON è verificato. Il flip sulla superficie del GOP resta aperto (FASI 4.2). I contatori dicono che nessun frame Metal scrive il display.
- Due blocchi noti: (1) la richiesta di modo di CoreDisplay (`displayID 0x0`, `Failed to obtain mode info`) e la mancata accettazione di `InstallTiming` a 2560x1440 (`0xe00002c7`, `0xe00002dd`); (2) il display fisico non è principale.
- Spento con `shutdown -h`. Chiusura pulita (`vfs_unmountall(system) end`, nessun panic), `qemu-img check` senza errori, watchdog uscito rc=0.
- Prossimo passo proposto: capire il perché di `InstallTiming` 0xe00002c7/0xe00002dd e della richiesta di modo fallita, in un boot di sola osservazione, senza armamento.

## Analisi IOGraphics e RDNA4FB v4 (patch 0003), 21/10 dopo boot32

Sorgente: IOGraphics-600 di Apple (github.com/apple-oss-distributions/IOGraphics, copia in scratchpad). Solo sorgenti
open source e documentazione: nessun binario Apple analizzato. CoreDisplay e WindowServer sono chiusi: i log di
`research/hw_dump/p2_boot32/` dicono quale metodo fallisce, il sorgente dice cosa risponde il framebuffer.
Percorsi nel testo: `IOGraphicsFamily/...` del tarball IOGraphics-600. Codici: `research/ext/MacKernelSDK/Headers/IOKit/IOReturn.h`.

### Causa di 0xe00002c7 (kIOReturnUnsupported, IOReturn.h:108 `iokit_common_err(0x2c7)`)

- **InstallTiming** (log `ws_coredisplay_last15m.txt` r.4009-4033, mode `0x80001000`, framebuffer `0x100000318`): il metodo
  user-client 17 (`IOFramebufferUserClient.cpp:352`) chiama `IOFramebuffer::extValidateDetailedTiming`
  (`IOFramebuffer.cpp:4320-4352`, chiamata a `validateDetailedTiming` a r.4344). RDNA4FB v3 non sovrascrive
  `validateDetailedTiming`: il base (`IOFramebuffer.cpp:12910-12915`, return a r.12914) risponde `kIOReturnUnsupported`.
- **setDetailedTimings**: stesso problema nel base (`IOFramebuffer.cpp:12918-12922`), chiamato da `doSetDetailedTimings`
  (r.7891-7902) e da `matchFramebuffer` (r.7955).
- **Gamma** (`can't set device gamma`, 17 righe): `extSetGammaTable` (`IOFramebuffer.cpp:3175-3274`) → `updateGammaTable`
  (r.3483-3521: prima `setGammaTable` con sync, poi il fallback a 4 argomenti) → base `setGammaTable` (r.12881-12895),
  unsupported. RDNA4FB non lo sovrascrive.
- Il valore 0xe00002c7 compare anche per `setStartupDisplayMode` (base r.12857): era il bug della v2, risolto dalla v3.

### Causa di 0xe00002dd (kIOReturnPortExists, IOReturn.h:130 `iokit_common_err(0x2dd)`)

- Compare **una sola volta**, sul candidato 2560x1440@119.997589 Hz (r.4033 del log, 16:50:24.848501). Tutti gli altri
  candidati, incluso 2560x1440@59.95 e @99.94, ricevono 0xe00002c7.
- **Nessuna riga di IOGraphics restituisce questo codice** (ricerca su tutto il tarball: zero occorrenze di
  `PortExists`, `0x2dd`, `e00002dd`). Quindi l'origine è fuori dal sorgente aperto: CoreDisplay (chiuso) o il kernel.
- Ipotesi NON verificata: la pref `startup-timing` (`IOFramebuffer.cpp:2734-2741`, `extSetStartupDisplayMode`) conserva
  il timing 120 Hz del GOP, e CoreDisplay lo trova già registrato. Il codice v4 non cambia questa pref. Se 0xe00002dd
  resta dopo la v4, l'ipotesi va verificata (ad esempio svuotando la pref, in un boot di test).

### Altre cause nel log

- `Failed to obtain mode info` con `Setting mode 0x0 ... fbRegID 0x100000318` (r.~4035-4040): CoreDisplay chiede il modo 0
  a questo framebuffer, perché nessun modo è stato installato. Le conseguenze sono nel punto precedente.
- `GetThermalCompensationAttributes ... (e00002ce)` (3 righe, 16:54:46): è `kIOReturnNotReadable` di `extGetAttribute`
  per `kIOFBRed/Green/BlueGammaScaleAttribute` ('gslr' 'gslg' 'gslb'). Il codice (`IOFramebuffer.cpp:11369-11405`)
  risponde NotReadable finché la property `IOFBRedGammaScale` (`IOFramebuffer.cpp:119-120`) non esiste. Non passa dal
  `getAttribute` virtuale: l'override di `getAttribute` non sarebbe bastato.

### Modo alias, non modo nuovo

- `matchFramebuffer` (r.7922-7990) usa `kIODisplayModeIDReservedBase | kIODisplayModeIDAliasBase` = `0x80000000 | 0x40000000`
  (`IOGraphicsTypesPrivate.h:32`: `kIODisplayModeIDAliasBase = 0x40000000`). Non è `0x80001000`: quello è un ID di
  CoreDisplay. Il flusso è: validate (r.7944) → setDetailedTimings (r.7955) → `setDisplayMode(0xC0000000, 0)` (r.7979,
  chiamata diretta al driver, senza `doSetDisplayMode`) → `aliasMode` (r.8006).
- Conseguenza: anche con validate accettato, il `setDisplayMode` del driver deve accettare l'ID alias. In v3 accetta solo
  l'ID 1, quindi `matchFramebuffer` fallisce comunque. Questo era il blocco nascosto dietro le righe `InstallTiming`.
- `getTimingInfoForDisplayMode`, `getInformationForDisplayMode`, `getPixelInformation` devono rispondere per l'alias:
  `doSetup` (r.10726) e `closestDepth` (r.2608) li interrogano. Senza risposta, `haveFB` diventa false
  (r.10700-10716, `activeWidth < 128`).
- `kIOTimingIDApple_0x0_0hz_Offline` = 550 (`IOGraphicsTypes.h:1441`), `kIOTimingIDInvalid` = 0 (r.1383): il
  `appleTimingID = 0` della v3 non è un modo offline (controllato in r.7821-7825).

### Tabella metodi: RDNA4FB v3 / Navi48Framebuffer / necessario per CoreDisplay

Navi48Framebuffer è `cobalt64/tools/native/navi48accel/src/Navi48Accel.cpp:217-` (righe dei metodi 617-800). Non è più
completo di RDNA4FB sul fronte timing: non sovrascrive nessuno dei metodi di timing o gamma. È più completo sugli
attributi (tabelle `fb_attr`, `fb_connection_attr` in `n48accel_pure.h:191-211`).

| Metodo IOFramebuffer | RDNA4FB v3 | Navi48Framebuffer | Necessario per CoreDisplay / IOGraphics | v4 (0003) |
|---|---|---|---|---|
| validateDetailedTiming | base, 2c7 (r.12910) | base, 2c7 | SÌ: InstallTiming, matchFramebuffer (r.7944) | accetta solo il timing GOP, ritorna il canonico |
| setDetailedTimings | base, 2c7 (r.12918) | base, 2c7 | SÌ: doSetDetailedTimings (r.7891), matchFramebuffer (r.7955), IOFBConfig (r.11681) | memorizza gli alias, nessun hardware |
| getTimingInfoForDisplayMode | solo modo 1 (GOP), altri base 2c7 (r.12901) | base, 2c7 | SÌ: doSetup (r.10726), extGetInformationForDisplayMode (r.11489) | modo 1 + alias |
| setDisplayMode | solo (1,0) | solo (1,0) (`fb_mode_ok`) | SÌ: matchFramebuffer chiama `setDisplayMode(0xC0000000,0)` (r.7979) | (1,0) + alias |
| getDisplayModes / Count | (1) | (1) | SÌ: CoreDisplay vede "Found 1 modes [1, 0]" | invariato (1) |
| getInformationForDisplayMode | solo 1 | solo 1 | SÌ: extGetInformationForDisplayMode (r.11449) | 1 + alias |
| getPixelInformation | solo 1 | solo 1 | SÌ: closestDepth (r.2608), haveFB (r.10700) | 1 + alias |
| getCurrentDisplayMode | 1 | 1 | SÌ: extGetCurrentDisplayMode (r.2670-2683, usa aliasMode) | invariato |
| getStartupDisplayMode / setStartupDisplayMode | 1 (Navi 44) | solo getStartup | SÌ: extSetStartupDisplayMode (r.2714), base r.12857/12865 | invariato |
| setGammaTable (4 e 5 arg) | base, 2c7 (r.12881/12890) | base, 2c7 | SÌ: updateGammaTable (r.3483-3521), extSetGammaTable (r.3175) | accetta, non programma |
| getAttribute 'gslr' 'gslg' 'gslb' | via extGetAttribute, property assente → 2ce (r.11369-11405) | stesso | SÌ: ThermalCompensation | property `IOFBRed/Green/BlueGammaScale` = 1<<16 in start() |
| getAttribute 'crsr' (cursore hw) | 0 o 1 (hwCursorReady) | 0 (software) | SÌ: IOGraphics sceglie cursore sw/hw | invariato |
| setAttribute kIOPowerAttribute | sì | sì | SÌ: power state | invariato |
| getAttributeForConnection Enable/CheckEnable/Flags/HLDDCSense | sì | sì | SÌ: connessione IODisplay | invariato |
| getAttributeForConnection gamma scale, overscan, VBL mult. | base (r.13246-13318) | base | SÌ (ma nessun errore nei log) | invariato |
| setAttributeForConnection kConnectionPower | sì | sì | SÌ (display sleep) | invariato |
| getDDCBlock / hasDDCConnect | sì (EDID) | sì | SÌ: EDID | invariato |
| registerForInterruptType / setInterruptState | sì (VBL timer) | no | SÌ con IOFramebuffer VBL | invariato |
| kConnectionControllerDepthsSupported, ColorModesSupported, ScalerInfo | non gestiti | non gestiti | NON VISTI nei log: da verificare | nessun cambio |

### Patch 0003 (`cobalt64/third-party/rdna4fb-n44/0003-navi44-timing-gamma.patch`, 228 righe, sha256 `f98a2496…`)

Solo Navi 44 (`rdna4_is_navi44`); Navi 48 resta sul base. Nessuna scrittura hardware nuova.

- `validateDetailedTiming`: accetta un `IOFBDisplayModeDescription` (dimensione di matchFramebuffer) o un
  `IODetailedTimingInformationV2` nudo. Accetta solo il timing GOP: 2560x1440, clock 497.75 MHz ±0.1 %, H 2560+160
  (sync 48/32, +), V 1440+85 (sync 3/10, −). Altrimenti `kIOReturnUnsupported` e log delle sole righe 2560x1440
  rifiutate (clock, blanking, sync: 4 righe per boot, il dato che manca). Sull'accettato scrive il clock canonico e
  compila `info` (2560x1440, 120 Hz in 16.16, Valid|Safe).
- `setDetailedTimings`: sostituisce ad ogni chiamata la lista degli alias (fino a 8) per i timing GOP, con
  `detailedTimingModeID` (`__reservedA[0]`) diverso da 0 e da 1. Ritorna successo. Non riprogramma.
- `ownsDisplayMode` (nuovo membro privato + `aliasModes[8]`, `aliasModeCount`): 1 sempre, più gli alias installati.
  `setDisplayMode`, `getInformationForDisplayMode`, `getPixelInformation`, `getTimingInfoForDisplayMode` lo usano.
  `getDisplayModes` resta (1): il modo unico non cambia.
- `setGammaTable` (4 e 5 argomenti): accetta e ignora. Non c'è LUT gamma pilotato da RDNA4FB; il ramp resta quello del GOP.
- `start()`: property `IOFBRedGammaScale`, `IOFBGreenGammaScale`, `IOFBBlueGammaScale` = `1<<16` (unità: `IOFramebuffer.cpp:3292`)
  per Navi 44. Solo property, nessun registro.

Verifiche (21/10, nessuna build di kext, nessuna VM):
- Pristina `research/refs/RDNA4FB` + 0001 + 0002 + 0003 con `patch -p1` e con `git apply --check`: applicazione pulita,
  risultato uguale a `research/ext/RDNA4FB-n44/src` (v4). La copia di lavoro è aggiornata alla v4 (era uguale alla v3).
- `clang++ -fsyntax-only` (target x86_64-apple-macos11.0, header `research/ext/MacKernelSDK/Headers`, flag del Makefile):
  v3 e v4 compilano con 0 errori e 0 warning, anche con `-Wall -Wextra`. Gli `override` nuovi sono verificati dal compilatore
  (un test con firma errata viene rifiutato).

Rischi (da leggere prima del boot):
1. **0xe00002dd non è spiegato**. Il candidato 120 Hz può restare rifiutato con 2dd anche dopo la v4 (vedi sopra).
2. **Corrispondenza stretta**: se il candidato 120 Hz di CoreDisplay ha blanking o sync diversi dal GOP (per esempio CVT-RB),
   resta 0xe00002c7. Il log `validate: 2560x1440 candidate refused` dirà i campi reali al boot successivo.
3. **Alias nel modo corrente**: dopo matchFramebuffer, `extGetCurrentDisplayMode` risponde `aliasMode = 0xC0000000`, che non è
   nella lista (1). Il comportamento di CoreDisplay con un modo corrente fuori lista non è verificato.
4. **Gamma ignorato**: il ramp di ColorSync o del profilo CoreDisplay non viene applicato. Il GOP è lineare, quindi l'effetto
   è una resa diversa dalla correzione, non un'alterazione.
5. **Nessuna scrittura hardware**, ma `start()` già contiene letture e ping DMUB/SMU della v3: invariato.
6. **Versione del kext**: `VERSION` 0.0.1 invariato. Il binario si riconosce dal sha256 (come la v3, `61fac769…`).

Cosa serve per la build (VM di build, non fatta): `make` con `MKSDK=research/ext/MacKernelSDK` nella VM 25G83 (la copia
`research/ext/RDNA4FB-n44/` è già la v4), poi il consenso GUI del nuovo binario (`kmutil load -p`, come per la v3). Dopo il
boot, nel log di WindowServer da cercare: `InstallTiming ... FAILED` (con quali codici), `Setting main display` (con o senza
`0x1b572300`), `can't set device gamma` (deve sparire), `GetThermalCompensationAttributes` (deve sparire), e nel seriale le
righe `RDNA4FB: validate:` e `RDNA4FB: setDetailedTimings:`.

## Flag IOFBIntegrated, console base e patch 0004 (21/10, dopo boot34)

Fonti: IOGraphics-600 (scratchpad), log `research/hw_dump/p2_boot32`, `p2_boot34` (seriale, `kernel_wsl_prearm_full.log`).

### Dove IOGraphics usa "integrated" (tutto il sorgente aperto)

- `IOFramebuffer.cpp:1379`, `IOFBController::init`: risale i provider fino al primo `IOPCIDevice` e pone
  `fIntegrated = (getBusNumber() == 0)`. È stato del controller (`:442`), non della sottoclasse. Anche `fExternal` (`:1380`)
  viene da `kIOPCITunnelledKey`.
- `IOFramebuffer.cpp:9031`, dentro `IOFramebuffer::open()` (r.8940): `setProperty(kIOFBIntegratedKey, kOSBooleanTrue)`
  (`kIOFBIntegratedKey` = `"IOFBIntegrated"`, `IOGraphicsTypesPrivate.h:147`). `open()` è chiamata da `newUserClient`
  per il tipo server (`IOFramebuffer.cpp:4021`, WindowServer) e per i framebuffer dipendenti (`:9345`).
- `IOFramebuffer.cpp:10301`: l'unico altro uso, nella guardia di shutdown che lascia lo schermo nero. È condizionato da
  `isVendorDevicePresent(kVendorDeviceNVidia)`: senza una GPU NVIDIA nel sistema non ha effetto.
- Nel sorgente aperto NESSUNO legge `IOFBIntegrated` o `fIntegrated` per backlight, lid, online/connect, `matchFramebuffer`
  o InstallTiming (ricerca su tutto il tarball). Il pannello interno passa da altro: `kConnectionFlags` con
  `kIOConnectionBuiltIn` (`IOBacklightDisplay.cpp:203`, `fb->setProperty(kIOFBBuiltInKey, ...)` a `:248`) e
  `fBuiltInPanel` da `kIODisplayOptionBacklight` (`IOFramebuffer.cpp:8146`, clamshell r.9456-9512). RDNA4FB risponde 0
  a `kConnectionFlags` (framebuffer.cpp:2592, v5) e quindi non è un pannello interno.
- Conclusione: l'effetto di `IOFBIntegrated` su CoreDisplay (InstallTiming, display principale) non è visibile in
  IOGraphics. È un consumatore chiuso. È un'ipotesi da testare, non una causa dimostrata.

### Controllabilità da sottoclasse

- `fIntegrated` (controller) NON è controllabile: il valore è calcolato in `init()` da `IOPCIDevice::getBusNumber()`, di
  Apple, e il controller è un oggetto interno (`IOFBController`). Nessun override della sottoclasse lo raggiunge.
- La property sì: `IOFramebuffer::open()` è `virtual` (`IOFramebuffer.h:492`). La sottoclasse la sovrascrive: chiama
  `super::open()` e poi rimuove `IOFBIntegrated`. Rimuovere (e non impostare a false) è la scelta che coincide con un
  discrete card: IOGraphics non pubblica mai la property in quel caso. Il punto è sicuro: `open()` gira sotto il gate
  dell'IOFramebuffer, e `removeProperty` è un'operazione del registry.
- Non tocco `kConnectionFlags`/`kIOConnectionBuiltIn`: il pannello interno resta fuori (come da v4).

### Console base 0x90000000 (non è la v4)

- `captureConsoleInfo` (`framebuffer.cpp:21-47`): prende `v_baseAddr` da `IOPlatformExpert::getConsoleInfo`
  (`PE_state.video`, scritto dal bootloader/GOP) e azzera i 12 bit bassi. Il bit 0 (`0x...001`) è il "flag bit" che il log
  segnala. Il codice è identico in v3 e v4: la 0003 non tocca `captureConsoleInfo` (diff verificato).
- Il valore cambia da boot a boot, non per la v4: `0x80000001` nei boot 29, 31, 33 e nel primo avvio del kernel di boot34
  (17:11:52); `0x90000001` nei boot 27, 28, 30, 32 (v3) e nel secondo avvio di boot34 (17:14:02). `kernel_wsl_prearm_full.log`
  contiene due banner Darwin, quindi due avvii distinti, con due valori.
- Coerenza con la superficie GOP: il log Cobalt64 di boot34 (`serial_p2_boot34_postarm.log:370`) dice
  `vram: BAR0 plan: IOPCIFamily [0x90000000, +256 MiB)`. La base di console è quindi BAR0 + offset VRAM 0 (lato CPU), e
  corrisponde alla superficie primaria a MC `0x80_00000000` (offset 0 della VRAM, vedi sopra, lato GPU). Il valore
  cambia perché il firmware/IOPCIFamily assegna BAR0 in modo diverso da un boot all'altro.

### Validate non raggiunto: cosa dice il codice

- Percorso user-client: `IOFramebufferUserClient::externalMethod` (`IOFramebufferUserClient.cpp:310-375`, metodo 17 a r.352)
  → `RPC_GUARD` (r.55-60, `kIOReturnOffline` se terminating/inactive) → `extValidateDetailedTiming` (`IOFramebuffer.cpp:4320`):
  dimensione output diversa → `kIOReturnBadArgument` (0xe00002c2), poi `extEntry(false)` → `kIOReturnOffline`
  (0xe00002d7) se il framebuffer non è online (`IOFramebuffer.cpp:4170-4200`), poi `validateDetailedTiming`.
- Nessuno di questi gate produce 0xe00002c7. Quindi, se la v4 non ha loggato nemmeno una chiamata a validate, il 2c7 viene
  da CoreDisplay prima della chiamata, oppure da un percorso di IOKit che non passa dal nostro metodo. La patch 0004 logga
  le prime 8 chiamate di `validateDetailedTiming` con `descripSize`: se il log resta vuoto, la causa è lato CoreDisplay.

### Patch 0004 (`cobalt64/third-party/rdna4fb-n44/0004-navi44-integrated-flag.patch`, sha256 `60049eb3…`)

- `open()` (nuovo override, Navi 44 solo): `super::open()`, poi `removeProperty("IOFBIntegrated")`.
- `validateDetailedTiming`: log delle prime 8 chiamate (`RDNA4FB: validate: call N, descripSize S, description set|NULL`).
- Versione `0.0.5` in `Info.plist` (`CFBundleShortVersionString` e `CFBundleVersion`), `Makefile` (`VERSION`) e
  `src/kmod_info.c` (`KMOD_EXPLICIT_DECL`).
- Solo Navi 44. Nessuna scrittura hardware.
- Verifiche: catena 0001-0004 applicata con `patch -p1` alla pristina, risultato uguale a v5. `clang++ -fsyntax-only -Wall
  -Wextra`: 0 errori, 0 warning nuovi rispetto a v4. `Info.plist` valido (plistlib). `kmod_info.c` compila.

### Rischi

1. Se CoreDisplay non dipende da `IOFBIntegrated`, la 0004 non cambia nulla sul display: è un test, non una correzione.
2. Il log di validate dirà se CoreDisplay chiama il metodo; con zero righe, il problema è a monte.
3. `removeProperty` dopo `open()`: se un client legge la property prima di `open()`, la vede ancora. Non osservato.
4. La versione 0.0.5 cambia l'identità del kext (sha256); va riconciliata con la lista dei binari approvati.
5. Non testata su VM (niente build, niente boot, come richiesto).

## Boot36 (consenso RDNA4FB v5) e boot37 (P2 root bus con v5), 21/10 ~17:35-18:15

Evidenze: `research/hw_dump/safety_boot36/` (consenso v5) e `research/hw_dump/p2_boot37/` (seriale, log kernel e WindowServer pre/post arm, `ioreg_full_prearm.txt`, contatori, `gpu_safety_event_heartbeat_lost/`, `SHA256SUMS*`).

### Build e versione
- RDNA4FB v5 = pristina + 0001..0004 (0004 = `IOFBIntegrated` rimosso dopo `super::open()` su Navi 44). Versione 0.0.5. Build nella VM di build, simboli `open`, `validateDetailedTiming(void*, IOByteCount)`, `setDetailedTimings(OSArray*)`, `setGammaTable` (due overload) definiti, firma ad-hoc, `IOPCIPrimaryMatch` con `0x75901002`. Sha binario `18177778…`. Kext in `/mnt/vm/builds/rdna4fb-n44-v5-20261021/` con `SHA256SUMS`.

### Esiti
- Consenso (boot36, GTK, topologia root bus): `kmutil load` ha dato «not approved»; l'utente ha consentito senza riavviare. Shutdown pulito, watchdog rc=0.
- Boot37 (P2, root bus, `N4X_GPU_ROOTPORT` non impostata): kext di sicurezza partito con protezioni PRESENT. RDNA4FB 0.0.5 caricata (dimensione in memoria `0xac64`).
- **`ioreg -l -w0` completo, nodo RDNA4FB (righe 2890–3012)**: `IOFBIntegrated` ASSENTE (la 0004 funziona). `IOFBDetailedTimings` e `IOFBStartupTiming` ASSENTI. Presenti `IOFBRed/Green/BlueGammaScale = 65536`, `IOFBConfig` (modo 1, 2560x1440), `IOFBCurrentPixelClock = 497750000`, `IOFBNeedsRefresh = Yes`.
- **`RDNA4FB: validate`**: 0 righe, prima e dopo l'arm, con v5. Anche `setDetailedTimings:` 0. Il metodo non emette log per i candidati di InstallTiming.
- **`InstallTiming`** (pre arm): 14× `0xe00002c7`, 1× `0xe00002dd` (2560x1440@120). Post arm: 23× `0xe00002c7`, 1× `0xe00002dd`. Invariato rispetto a v3 e v4.
- **Display**: `Setting main display 0x00000000 offline` 12 righe pre, 13 post. `0x1b572300` online a `Startup Mode 2560x1440`, `IOReturn 0x0`, non principale. VirtualDisplay creato. Gamma `device gamma`: 0 righe.
- **Arm**: `n48nub publish` OK. `pipeadopt` status 3 al primo tentativo, status 0 con flags `0x3b` al secondo. `pipeagdc 1` PUBLISHED. `arm-check` PASS, `arm-desktop --dry-run` OK, ARM_OK con WindowServer pid 900 e flags `0x3f`.
- **Contatori dopo l'arm**: `pipestat 0` hook calls 1, submit pass-through 0, will-perform 0, frames copied 0, completed 0. Navi48Metal T1: `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`. Nessun frame o flip misurato.
- **Osservazione utente dopo l'arm**: nessuna differenza. Orologio assente, nessuna trasparenza.

### Heartbeat e spegnimento
- Boot37: 2198 heartbeat, hotspot 35–40 °C (media 38,2), zero WARN/TRIP. Protezioni PRESENT all'avvio.
- Spegnimento: `shutdown -h` ha completato `vfs_unmountall(system) end`. Poi durante la halt: panic `Ticket lock ... unexpectedly owned` in `IOPlatformHaltRestartAction -> AppleSMC`, stessa firma dei boot 21 e 25 (vedi sopra). L'ultimo heartbeat precede il panic. Il watchdog ha letto il silenzio come `heartbeat-lost:10.2s` e ha chiuso QEMU via QMP (rc=2, come da design). `qemu-img check` pulito. Evento in `research/hw_dump/p2_boot37/gpu_safety_event_heartbeat_lost/`.
- Il panic in halt è ricorrente con questa configurazione (boot 21 riavvio, boot 25 spegnimento, boot 37 spegnimento). Non è causato dal kext di sicurezza (il kext non ha handler di halt). Da indagare.

### Causa del blocco display (RE, `research/reports/coredisplay_re.md`)
- CoreDisplay legge `IOFBTimingRange` dalla IORegistry. RDNA4FB non la pubblica (il dump boot34/37 non la contiene). Senza `IOFBTimingRange`, `caps` resta NULL, il driver non viene interrogato e `validateDetailedTiming` non viene mai chiamato: spiega l'assenza di `validate:`.
- Il prossimo passo è la v6, che pubblica `IOFBTimingRange`. Non ancora fatta.

### Stato
- Il desktop su GPU NON è verificato. Il display fisico non è principale e il flip GOP resta aperto (FASI 4.2). Prossimo passo: v6 con `IOFBTimingRange`.
- Evidenze: `research/hw_dump/safety_boot36/`, `research/hw_dump/p2_boot37/`.

## Patch 0005: IOFBTimingRange (21/10, dopo il RE di CoreDisplay)

Base: `research/reports/coredisplay_re.md`, sezione 1 (caps NULL → IOFBInstallMode 0xe00002c7; il driver non viene interrogato).
Fonti open source: IOGraphics-600 (`IOGraphicsTypes.h`, `IONDRVFramebuffer.cpp:1450-1470`, `IOFramebuffer.cpp:4874`).

### Struttura scelta

- Tipo: `IODisplayTimingRangeV2` (`IOGraphicsTypes.h:796`). Dimensione verificata: **0x138 = 312 byte** (`static_assert`
  contro l'header MacKernelSDK). V1 è 0xF0: stessi offset fino a 0xEF, quindi CoreDisplay che legge 0xF0 byte vede lo stesso.
- Pubblicazione: `RDNA4FB::publishTimingRange()`, chiamata in `start()` **prima di `super::start()`**, perché
  `IOFramebuffer::start` chiama `registerService()` alla fine (`IOFramebuffer.cpp:4874`). IOGraphics pubblica la stessa
  proprietà in `IONDRVFramebuffer::setInfoProperties` (`:1450-1470`), chiamata da `checkDriver` e da `processConnectChange`.
  Solo Navi 44 (`(vd >> 16) == 0x7590`).
- Chiave: `kIOFBTimingRangeKey` = `"IOFBTimingRange"` (`IOGraphicsTypes.h:1461`), come `setProperty(key, &r, 0x138)`.

### Valori (campo, offset, valore)

| Campo (V2) | Offset | Valore | Motivo |
|---|---|---|---|
| version | 0x08 | 2 (`kIOTimingRangeV2`) | l'enum esiste per questo; il commento dell'header dice "init 0": ambiguo, vedi rischi |
| minPixelClock / maxPixelClock | 0x20 / 0x28 | 497.25 / 498.25 MHz | GOP 497.75 MHz ±0.1 % (stessa tolleranza della 0003) |
| maxPixelError | 0x30 | 500000 Hz | ±0.1 % |
| supportedSyncFlags | 0x34 | 0x1 separate syncs | GOP H+ V− (digitale) |
| supportedSignalLevels / Configs | 0x38 / 0x3c | 0 / 0 | analogico e CEA interlacciato: non per DP |
| min/maxFrameRate | 0x40 / 0x44 | 119 / 121 Hz | 2720×1525 a 497.75 MHz = 120.0 Hz |
| min/maxLineRate | 0x48 / 0x4c | 182800 / 183200 Hz | 497.75 MHz / 2720 = 183.0 kHz, ±0.1 % |
| maxHorizontalTotal / maxVerticalTotal | 0x50 / 0x54 | 2720 / 1525 | totali del GOP |
| charSize* (14 u8) | 0x60…0x6d | 1 | divisore 1 (0 = divisione per zero, come da RE) |
| H active / blank / SO / PW (min=max) | 0x70, 0x78, 0x80, 0x88 | 2560, 160, 48, 32 | GOP |
| V active / blank / SO / PW (min=max) | 0x90, 0x98, 0xa0, 0xa8 | 1440, 85, 3, 10 | GOP |
| border min/max (8 u32) | 0xb0…0xcc | 0 | nessun bordo |
| maxNumLinks | 0xd0 | 1 | un link |
| min/maxLink0PixelClock (kHz) | 0xd4 / 0xd8 | 497250 / 498250 | come il clock Hz |
| link1 min/max | 0xdc / 0xe0 | 0 | nessun secondo link |
| supportedPixelEncoding | 0xe4 | 0x0001 RGB444 | solo RGB che lo scanout porta |
| supportedBitsPerColorComponent | 0xe6 | 0x0002 8 bpc | il GOP è 32 bpp ARGB |
| supportedColorimetryModes | 0xe8 | 0x0003 native RGB + sRGB | |
| supportedDynamicRangeModes | 0xea | 0x0001 SDR | |
| maxBandwidth | 0xf0 | 14 932 500 000 bit/s | documentato come "max bandwidth del topology in bit/s": 497.75 MHz × 24 bpp × 10/8 |
| DSC (0xf8…0x137) | — | 0 | nessun DSC |

### Confronto con la mappa del report RE

- Maschere 0xe4–0xea: **coincidono** (sono supportedPixelEncoding, BitsPerColor, Colorimetry, DynamicRange). Il valore
  proposto dal report era 0xffff. **Deviazione**: uso solo ciò che lo scanout porta (RGB444, 8 bpc, sRGB/native RGB, SDR).
  Dichiarare 0xffff significherebbe dichiarare YCbCr, 10/12/16 bpc, HDR, che non sappiamo pilotare: la 0003 non controlla
  l'encoding del timing. Se CoreDisplay rifiuta con 0xe00002c7 per un campo di formato, il primo sospetto è questa scelta.
- Divisori 0x60–0x6d = 1: **coincidono**.
- Coppie min/max 0x40–0xcc: **coincidono** nell'intervallo (rate 0x40–0x4c, totali 0x50–0x54, granularità 0x60–0x6d,
  H/V 0x70–0xac, bordi 0xb0–0xcc). Il report chiamava 0x3c "u8, da verificare": è u32 `supportedSignalConfigs`, non u8.
- 0x20/0x28 u64 clock: **coincidono**.
- Non ho riletto la decompilazione di `CheckTimingWithRange`: la semantica dei campi viene dagli header e dal sorgente IOGraphics.

### Scaler e altre proprietà

- `kIOFBScalerInfoKey` (`IONDRVFramebuffer.cpp:1472-1478`): NON aggiunta. Serve per scalatura e rotazione; il modo è nativo.
- `kIOFBProbeOptionsKey` (bit 0x400 `kIOFBSetTransform`): NON aggiunta. Stesso motivo.
- `IODisplayConnectFlags` (letta da CoreDisplay secondo il report RE; IONDRV la scrive sul nub, `:1486`): NON aggiunta,
  perché il report RE non dice che il percorso di InstallTiming la legga. Da verificare se il prossimo boot mostra
  altro. Il nostro `kConnectionFlags` risponde 0 (non built-in).

### validateDetailedTiming (0003) e commenti

- Il preflight di CoreDisplay invia `IOFBDisplayModeDescription`, **0xCC = 204 byte** (verificato con sizeof sull'header):
  il ramo della 0003 che accetta quella dimensione è quello giusto.
- Commento della 0003 corretto: validate è raggiunto solo via IOFBDriverPreflight (sel 0x11) con IOFBTimingRange presente.
  Anche il paragrafo della 0002 che attribuiva a validate la 0xe00002c7 è stato corretto (solo commenti).

### Verifiche (nessuna VM, nessuna build)

- Catena 0001–0005 applicata con `patch -p1` alla pristina: risultato uguale alla v6 (`research/ext/RDNA4FB-n44/src`).
- `clang++ -fsyntax-only -Wall -Wextra` con MacKernelSDK: 0 errori, 0 warning nuovi rispetto alla v5. `static_assert` sul
  0x138 superato. `Info.plist` valido (plistlib), `kmod_info.c` compila.
- Patch: `cobalt64/third-party/rdna4fb-n44/0005-navi44-timing-range.patch` (sha256 `4aacce50…`), 165 righe.
- Versione 0.0.6 in `Info.plist` (short e bundle), `Makefile` (`VERSION`), `src/kmod_info.c`.

### Rischi

1. **version = 2**: il commento dell'header dice "init 0" per il campo version di V2. Se CoreDisplay legge la versione e
   si aspetta 0 per il V2, il range viene ignorato o letto come V1 (che coincide fino a 0xEF, quindi il danno è limitato
   ai campi di coda, non al clock).
2. **Encoding/bpc/colorimetria stretti** (vedi deviazione): un formato che CoreDisplay vuole e non dichiariamo dà 0xe00002c7.
3. **maxBandwidth** = requisito del GOP, non del link: se CoreDisplay usa un calcolo diverso (per esempio senza 8b/10b o
   con overhead DP), può rifiutare. Il valore sta sotto HBR2 x4 (17.28 Gbit/s payload).
4. **Range esatto (min = max) per H/V**: un candidato con blanking diverso (CVT-RB) viene rifiutato con 0xe00002c2 o c7.
   È lo scopo (adozione same-mode), ma il primo boot deve mostrare i candidati rifiutati nel log (`validate: ... refused`).
5. **0xe00002dd** (PortExists) sul candidato 120 Hz non è ancora spiegato: può restare con il range attivo.
6. **Versione 0.0.6**: cambia l'identità del kext (sha256); va riconciliata con l'approvazione GUI.
7. Non testata su VM: nessuna scrittura hardware nuova; la pubblicazione è una property.

Cosa cercare al prossimo boot: `IOFBDriverPreflight` (chiamata sel 0x11), le righe `RDNA4FB: validate: call N` (della 0004),
`published IOFBTimingRange (312 bytes)`, nessun `FAILED … 0xe00002c7` per 2560×1440@120, e `Setting main display` senza il
ramo VirtualDisplay.

## Patch 0006 (v7, 0.0.7): maxNumLinks 0, bandwidth HBR3 x4, configurazione da DeviceProperties (21/10)

Base: `research/reports/coredisplay_re.md` §7 (e2 = `CheckTimingWithRange`, `numLinks = 2` contro `maxNumLinks = 1`).

### Valori di default (senza proprietà)

| Campo | v6 (0005) | v7 (0006) | Motivo |
|---|---|---|---|
| maxNumLinks (0xd0) | 1 | **0** | "0 = un link" (header IODisplayTimingRangeV2). Il controllo `1 < numLinks && maxNumLinks != 0 && maxNumLinks < numLinks` non scatta (§7.2) |
| maxBandwidth (0xf0) | 14.93 Gbit/s | **25.92 Gbit/s** | HBR3 x4 con 8b/10b: 4 × 8.1 × 0.8. Il campo è la banda massima del topology (documentato) |
| maschere 0xe4/e6/e8/ea | 0x1/0x2/0x3/0x1 | invariate | RGB444 / 8 bpc / native RGB + sRGB / SDR |
| version (0x08) | 2 | 2 | invariato |
| clock 0x20/0x28, link0 0xd4/0xd8, H/V, frame/line rate, totali, granularità | GOP | invariati | |

Nel driver, `validateDetailedTiming` accetta il timing GOP e **imposta `numLinks = 0`** nel descrittore. Serve dopo il preflight
(il descrittore viene ricopiato solo dopo `CheckTimingWithRange`), quindi non è la correzione del e2: è coerenza con `IOFBInstallMode`.
Il log ora registra anche le **accettazioni** (`validate: GOP timing accepted (n): clock …, numLinks 0`, primi 16), oltre ai rifiuti (primi 16).

### Verifica del link DP (sola lettura, dai dump del repo)

- `DP0_DP_LINK_CNTL` = **0x110** nel boot15 (GOP, `gop_dump_stage1_boot15_rombar1_serial.log`, riga `gopsnap`). Campi
  (`dcn_4_1_0_sh_mask.h`): `DP_LINK_TRAINING_COMPLETE` (bit 4) = 1, `DP_LINK_STATUS` (bit 8) = 1. Il link era addestrato e attivo.
- Nel boot17 lo stesso registro è 0 (`gop_observe_stage1_boot17_..._gopsnap.txt`): già fuori dal GOP, non è un dato di riferimento.
- **Numero di lane e rate NON leggibili** dallo snapshot: `DP0_DP_CONFIG` (0x2121, `DP_UDI_LANES` a maschera 0x3) e il registro del
  rate non sono nel gopsnap. Lo snapshot ha solo `DP0_DP_LINK_CNTL`, `DP0_DP_VID_STREAM_CNTL`, `DIG0_DIG_BE_CNTL` (0x100).
- **Assunzione** (non verificata sul link della VM): 4 lane HBR3 (`research/display/README.md`, §2). Quella nota viene da una sessione
  Linux con un altro monitor (LG UltraGear, 180 Hz) e non dal GOP della VM. Il GOP della VM lavora a 497.75 MHz × 24 bpc: servono
  ~11.9 Gbit/s di payload, cioè HBR2 x4 (17.28) basta già. Un cap a 25.92 non fa danni: il solo modo dichiarato sta sotto
  qualunque link di 4 lane HBR2 o superiore.

### Configurazione senza ricompilare (patch 0006, `publishTimingRange`)

Lettura all'avvio (`start()` → `publishTimingRange()`, solo 0x7590) dalle proprietà del nodo PCI, che OpenCore DeviceProperties
inietta. Un valore è Data little-endian di 1, 2, 4 o 8 byte, oppure un Number. Chiavi (tutte opzionali):

| Proprietà | Tipo | Limite del driver |
|---|---|---|
| `rdna4fb-tr-disable` | flag | non pubblicare |
| `rdna4fb-tr-blob` | Data, 312 byte | l'intera struttura; esclude le chiavi scalari; passa gli stessi limiti |
| `rdna4fb-tr-version` | u32 | 0 o 2 |
| `rdna4fb-tr-maxnumlinks` | u32 | 0 o 1 |
| `rdna4fb-tr-maxbandwidth` | u64 | ≤ 25 920 000 000 bit/s |
| `rdna4fb-tr-clock-min` | u32 Hz | min > 0, la banda contiene 497.75 MHz; min/max → anche link 0 (kHz) |
| `rdna4fb-tr-clock-max` | u32 Hz | ≤ 600 MHz |
| `rdna4fb-tr-encodings` | u16 | sottoinsieme di 0x0001 (RGB444), non zero |
| `rdna4fb-tr-bpc` | u16 | sottoinsieme di 0x0002 (8 bpc), non zero |
| `rdna4fb-tr-colorimetry` | u16 | sottoinsieme di 0x0003, non zero |
| `rdna4fb-tr-dynrange` | u16 | sottoinsieme di 0x0001 (SDR), non zero |

- Un valore che rompe un limite viene **rifiutato e loggato** (`… refused: <motivo> (default kept)`); il default del campo resta.
  Il controllo è sull'intera struttura candidata (`rdna4_range_refusal`), quindi i valori combinati restano coerenti.
- Log finale: `published IOFBTimingRange (default|overrides|blob, 312 bytes): version …, clock …, links …, bandwidth …, encodings …`.
- Test host (C++, estratto da `framebuffer.cpp`): il default passa; maxNumLinks 2, clock max 650 MHz, clock min 500 MHz, encodings 0x4 e
  0xffff, bpc 0x4 e 0, dynrange 0x2, colorimetry 0x4, bandwidth 32.4 G, version 1, link0 min > max vengono rifiutati; maxNumLinks 1 passa.

### PciRoot per OpenCore

- Dal boot40 (`research/hw_dump/p2_boot40/ioreg_full_boot40.txt`, nodo `S30@6 <class IOPCIDevice>`): `pcidebug = "0:6:0"`,
  `acpi-path = "IOACPIPlane:/_SB/PCI0/S30@60000"`, `device-id = 0x7590`, `vendor-id = 0x1002`.
- Path OpenCore: **`PciRoot(0x0)/Pci(0x6,0x0)`** (constante `RDNA4_TR_PATH` in `tools/vm/prepare-gpu-test-stage.py`).

### tools/vm/prepare-gpu-test-stage.py

- Nuove opzioni: `--rdna4fb-tr KEY=VALUE` (ripetibile; chiavi come sopra, senza `rdna4fb-tr-`) e `--rdna4fb-tr-blob FILE` (312 byte,
  esclusivo con le chiavi scalari). Scrivono `cfg['DeviceProperties']['Add']['PciRoot(0x0)/Pci(0x6,0x0)']` come Data little-endian.
- Senza le opzioni lo script **rimuove** le proprie chiavi `rdna4fb-tr-*` da quel path: il kext usa i default.
- Controllo "coerente": lo script non ha `--check`; la modalità senza scrittura è `--dry-run`. Le stesse regole del kext
  (`apply_rdna4fb_tr` / `rdna4_tr_refusal`) fermano lo script con errore prima di scrivere l'EFI. Valori fuori limite = errore.
- Il `plan` riceve `rdna4fb_timing_range` (riepilogo, o `default`).
- Verifica: `py_compile` ok; funzioni estratte e provate in isolamento (valori validi scritti, fuori limite rifiutati, blob di
  dimensione sbagliata rifiutato, chiavi gestite rimosse). **Il `--dry-run` completo non è stato eseguito**: QEMU tiene il write lock
  su `OpenCore.stage1.qcow2` (VM accesa). Va rifatto a VM spenta.

### Verifiche kext

- Catena 0001–0006 applicata con `patch -p1` alla pristina: risultato uguale alla v7 (`research/ext/RDNA4FB-n44/src`).
- Patch: `cobalt64/third-party/rdna4fb-n44/0006-navi44-timing-range-config.patch` (381 righe, sha256 `9cf72ef5…`).
- `clang++ -fsyntax-only -Wall -Wextra` con MacKernelSDK: 0 errori, 0 warning. `static_assert` 0x138 superato.
- Versione 0.0.7 in `Info.plist` (short e bundle), `Makefile` (`VERSION`), `src/kmod_info.c`.

### Rischi

1. **Assunzione del link** (4 lane HBR3, non letta): il cap a 25.92 è un limite dichiarato, non una misura. Se il link reale
   fosse diverso, CoreDisplay potrebbe accettare un modo che il link non porta. Per il solo modo GOP non cambia nulla.
2. **maxNumLinks 0 vs 1**: l'header dice "0 = un link"; non verificato che CoreDisplay tratti 0 come 1 ovunque (il controllo
   letto da §7.2 non scatta con 0). Se un altro controllo legge il campo, il prossimo boot lo mostrerà come c7/e2.
3. **Override di DeviceProperties**: OpenCore può non passare `Data` di 1/2 byte come vorrebbe il kext; il log `… applied` /
   `refused` lo dice al boot. Un valore sbagliato non può allargare la dichiarazione oltre i limiti (controllo nel kext).
4. **Log**: al massimo 16 accettazioni e 16 rifiuti per boot, più una riga per ogni chiave letta e il riepilogo.
5. **Versione 0.0.7**: cambia l'identità del kext (sha256), da riconciliare con l'approvazione GUI.
6. Nessuna VM, nessun commit, nessuna scrittura hardware nuova. La pubblicazione resta una property.

Cosa cercare al prossimo boot: `published IOFBTimingRange (default, 312 bytes): version 2, clock 497250000..498250000 Hz,
links 0, bandwidth 25920000000 bit/s, encodings 0x1, bpc 0x2, colorimetry 0x3, dynrange 0x1`; poi `validate: GOP timing accepted`
e l'assenza di `FAILED … 0xe00002c7` / `fbRange_a … 0xe00002e2` per 2560×1440@120.

## Boot41 (v7, 0.0.7, consenso): stato al fermo (21/10, 18:57-19:05)

Evidenze: `research/hw_dump/v7_boot41/` (seriale, log watchdog, stato guest, esito di `kmutil`, `SHA256SUMS`).

### Build v7
- `RDNA4FB` = pristina + 0001..0006 (verificato: la catena applicata alla pristina dà il sorgente di `research/ext/RDNA4FB-n44`, differenza solo `.git`). Versione 0.0.7 in `Info.plist`, `Makefile`, `kmod_info.c`.
- Build nella VM di build (Darwin 25.6.0), `make MKSDK=<SDK>` con `research/ext/MacKernelSDK` (slice `Library/x86_64`), exit 0, 1 warning (`-fapple-kext` su `kmod_info.c`, come prima).
- Simboli presenti: `open`, `validateDetailedTiming(void*, unsigned long long)`, `setDetailedTimings(OSArray*)`, `publishTimingRange`, `setGammaTable` (due overload). Stringhe: `published IOFBTimingRange (%s, %lu bytes): version …`, `validate: GOP timing accepted`, `rdna4fb-tr-disable`. `IOPCIPrimaryMatch` contiene `0x75901002`. Firma ad hoc, `codesign --verify` valido.
- Copia: `/mnt/vm/builds/rdna4fb-n44-v7-20261021/` (`RDNA4FB.kext`, `SHA256SUMS`, log di build). Binario `222eb96e…`, `Info.plist` `bc99dccf…`. `_CodeSignature/CodeResources` `6686de10…` è identico a v5/v6: il file contiene solo l'hash delle risorse, non del binario né del plist, quindi non distingue le build.
- VM di build spenta: `sync`, QMP `quit`, `qemu-img check` pulito.

### Boot41 (P0-like: stage 17, `--native-s1b --metal --csr-active-config 3`, nessun `--primary`/`--amfi`/`--rdna4fb`)
- Launcher `--check` e `--start` con `N4X_GPU_ROMBAR=1`, `N4X_GPU_PRIMARY=0`. Watchdog host armato (START, soglie 75/80 °C).
- Kext safety: START, `smu: protections … PRESENT, missing 0`, `VR0HOT(27) on`. Heartbeat 86, hotspot 33–38 °C, zero WARN/TRIP.
- Guest: boot-args e `csr-active-config 0x03` come da piano. Sul guest, prima della sostituzione, RDNA4FB v6 (0.0.6) era caricato da `/Library/Extensions` (SHA `578bc71a…`).
- Backup v6: `~/rdna4fb-stage/backup-v6/RDNA4FB.kext` (SHA `578bc71a…`). Originale spostato in `~/rdna4fb-stage/replaced-v6-20261021T190000/`.
- v7 installata in `/Library/Extensions/RDNA4FB.kext` (root:wheel, SHA `222eb96e…`, identica al SHA256SUMS).
- `sudo -n kmutil load -p /Library/Extensions/RDNA4FB.kext`: «Extension with identifiers com.hackintosh.RDNA4FB not approved to load. Please approve using System Settings.» rc=27. È la richiesta di consenso, da approvare in Impostazioni di Sistema > Privacy e sicurezza (finestra GTK).
- Errore mio: lo script di raccolta ha rieseguito `kmutil load -p` una seconda volta (rc=28, «requires a reboot»). La v7 non è stata caricata: `kmutil showloaded` mostra solo `RDNA4FB (0.0.6)`. Nessun effetto sul guest.
- Nel seriale la riga `published IOFBTimingRange (312 bytes): clock 497250000..498250000 Hz, GOP 2560x1440@120` è della v6 (la v7 stampa il formato `(default|…, 312 bytes): version 2 …`).

### Stato
- In attesa del consenso dell'utente nella finestra QEMU. Poi: shutdown, EFI P2 (passo 3), con la v7 caricata al boot.

### Passo 3 (21/10, 19:01-19:04): EFI P2 e avvio
- Consenso dato dall'utente nella finestra QEMU (riferito dal coordinatore). La richiesta approvata è quella della v7: unica richiesta generata, sul file `/Library/Extensions/RDNA4FB.kext` SHA `222eb96e…`. Spegnimento guest: `sudo -n shutdown -h now`, QEMU uscito da solo, nessun panic (`vfs_unmountall(system) end`), watchdog rc=0, `qemu-img check` pulito.
- Deviazione dal comando del passo 3: senza `--rdna4fb`. Lo script rifiuta l'injection OpenCore (`IOGraphicsFamily` non è nella Boot KC) e, con l'injection attiva, la v7 si caricherebbe due volte (injection e `/Library/Extensions`). La v7 viene quindi solo da `/Library/Extensions` (consenso). Il `--rdna4fb-tr` non è stato passato (default).
- EFI P2: `--primary --metal-disp --metal-ws --agdc --amfi-get-out-of-my-way --csr-active-config 3` (stage 17, native-s1b, metal). Boot-args: `navi48-metal-ws=1 navi48-metal-disp=1 navi48-agdc=1 amfi_get_out_of_my_way=1`.
- Avvio: `N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1 start-gpu-test-vm.sh --start`, watchdog READY (warn 75, trip 80). QEMU partito alle 19:03.

### Passo 4 (21/10, 19:03-19:10): boot42 (P2, v7), righe chiave e arm

Evidenze: `research/hw_dump/v7_boot41/prearm/` (log unificato WindowServer e seriale pre-arm, `key_lines_prearm.txt`) e `research/hw_dump/v7_boot41/postarm/` (post-arm, `key_lines_postarm.txt`, `pipestat_0_and_4.txt`), tutte con `SHA256SUMS`.

**Prima dell'arm (WindowServer pid 196, boot42)**
- `RDNA4FB: published IOFBTimingRange (default, 312 bytes): version 2, clock 497250000..498250000 Hz, links 0, bandwidth 25920000000 bit/s, encodings 0x1, bpc 0x2, colorimetry 0x3, dynrange 0x1`.
- `validate: call 1, descripSize 204`, `GOP timing accepted (1): clock 497750000 Hz, numLinks 0`. Rifiuti: 0. `setDetailedTimings: 1 alias mode(s)`.
- `InstallTimingWithWireFormats - SDR_RGB__8_Native succeeded for mode 0x80001000 (2560x1440 to 2560x1440@120.0) … as 0x0001, 0x0002, 0x0001, 0x0001`. È la prima volta che 2560x1440@120 viene installato su questo percorso. Gli altri formati e modi (`SDR_420`, `fbRange_b`, c7) restano falliti come prima.
- `Display 0x1b572300: Unit 0: Startup Mode 2560 x 1440 … online enabled`. `loginUI: main display 0x1b572300 frame={{0,0},{2560,1440}}`. Il `Setting main display 0x00000000 offline` è in gran parte pre-sessione; il display 0x1b572300 risulta principale per la login window.
- VirtualDisplay: creato (4 occorrenze nella sessione). Gamma: presente (`CGXSetDisplayColorProfileAndTransfer ... succeeded`).

**Arm (sequenza completa)**
- `n48nub publish`: state 1 (published).
- `pipeadopt`: primo tentativo, `flags 0x31` (adottata assente). Secondo tentativo, `flags 0x3b`. Il kit legge l'adozione come bit 0x2 (`FLV & 2`), che in 0x3b è presente (il bit 2 del piano è il valore 0x2, non il bit di indice 2).
- `pipeagdc 1`: status 12 (already published).
- `--arm-check`: ARM_CHECK_PASS. Richiede `N48_TEST_SSH_KEY=/mnt/vm/builds/build-vm-ed25519`: senza, lo script cerca la chiave di default e riporta «non raggiungibile».
- `--arm-desktop --dry-run`: piano ok, nessuna scrittura.
- `--arm-desktop` (ARM): ARM_OK, WindowServer ripartito (pid 1274, 19:08:31), `flags 0x3f`, `accel+0xccf = 1`, pipe ARMED.

**Dopo l'arm (WindowServer pid 1274)**
- `pipestat 0`: flags 0x3f, hook calls 1, handled 1, submit pass-through 0, will-perform 0, bytes/frames copied 0, completed 0.
- `pipestat 4`: status 0 (OK).
- Navi48Metal T1: `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0` (conteggio su 10 s). Nessun frame e nessun flip misurato.
- RDNA4FB: `validate` accetta di nuovo il timing GOP (call 1 e 2). Ma nella sessione 1274 il candidato 2560x1440@120 (mode 0x80000001) viene rifiutato: `SDR_RGB__8_Native` con `Mode_clone … 0xe00002dd` (duplicato, il modo è già installato dalla sessione precedente), gli altri formati con `fbRange_b` c7. Nessun `succeeded` nella sessione post-arm. Il log non dice se il modo installato in pid 196 resta attivo: da verificare.
- Seriale: 336 heartbeat `N4X-SAFETY`, hotspot 33–39 °C, zero WARN/TRIP, zero panic.

**Cosa deve vedere l'utente (da confermare sul DP)**
- Nessun cambiamento atteso oltre al desktop composto. Il frame count resta 0: l'osservazione dell'utente è la prova che conta. Se il DP mostra ancora la login window o niente, il flip GOP (FASI 4.2) è ancora il blocco.

### Osservazione utente e causa (21/10, dopo l'arm di boot42)
- Osservazione dell'utente sul DP: nessuna differenza. Niente orologio, niente trasparenza. Il frame count resta 0 e nessun flip è misurato.
- Causa (`research/reports/coredisplay_re.md` §8): la prima sessione WindowServer installa il 2560x1440@120 e CoreDisplay scrive la proprietà `IOFBConfig` sulla entry del framebuffer. Il kext non la rimuove mai (nessun `removeProperty` in IOGraphics). Alla sessione successiva (pid 1274) `IOFBBuildModeList` la legge, ricostruisce il modo GOP, e l'installazione dà `0xe00002dd` (duplicato). Riavviare WindowServer non distrugge la entry, perché il kext resta caricato.
- Correzione raccomandata (non ancora applicata): in `RDNA4FB::open()`, `removeProperty("IOFBConfig")` e reset degli alias prima che CoreDisplay legga la proprietà. Va nella patch successiva (0007 / v8).

### Spegnimento boot42 (21/10, 19:19)
- `sudo -n shutdown -h now`: `vfs_unmountall(system) end`, nessun panic, QEMU uscito da solo, watchdog rc=0.
- `qemu-img check mac_hdd_ng.img`: nessun errore.
- Evidenze di spegnimento in `research/hw_dump/v7_boot41/postarm/` (`serial_boot42_shutdown.log`, `gpu-safety-watchdog-final.log`, SHA256 aggiornati).

### Prossimo giro
- v8 (`rdna4fb-n44-v8`, con la correzione di `IOFBConfig` in `open()`): ripetere i passi 1-4 nell'ordine, con lo stesso consenso GUI e la stessa sequenza di EFI. Nessun passo è stato eseguito per v8.

## Patch 0007 (v8, 0.0.8): duplicato 0xe00002dd tra sessioni WindowServer (21/10)

Base: `research/reports/coredisplay_re.md` §8 (IOFBConfig ripristinato alla sessione successiva → `Mode_clone` → 0xe00002dd).
Verifica nel sorgente IOGraphics-600 (scratchpad, non solo binario): i riferimenti sono `IOGraphicsFamily/...`.

### Risposte dal sorgente

- **`open()` non è per sessione.** Il corpo di `IOFramebuffer::open()` è protetto da `if (opened) continue;` (`IOFramebuffer.cpp:8959`).
  Il flag `opened` viene impostato una sola volta (`:9308`) e **non viene mai riazzerato** (tutte le occorrenze: `:4439`, `:8959`,
  `:9308`, `:13017`, e `IOFramebuffer.h:351` per la definizione). Quindi il corpo gira una volta per oggetto framebuffer.
  Il codice che un override aggiunge **dopo** `super::open()` invece gira a ogni chiamata: la rimozione di `IOFBIntegrated` (0004) è
  già così. A ogni connessione server `newUserClient` chiama `open()` (`:4013-4021`).
- **`close()` è virtuale** (`IOFramebuffer.h:494`). Viene chiamato da `closeWork` (`:10264-10269`), pianificato da `extClose` (`:10243`),
  che a sua volta è chiamato da `IOFramebufferUserClient::stop()` (`IOFramebufferUserClient.cpp:229`): cioè quando il client server
  termina. `close()` finisce con `fServerConnect = NULL` (`:10385`), che apre la sessione successiva.
- **Lettori e scrittori di `IOFBConfig`** (`kIOFBConfigKey`, `IOGraphicsTypes.h:1561`): scrittura solo in `extSetProperties`
  (`IOFramebuffer.cpp:11670-11674`); lettura in `getConfigMode` (`:10579-10611`, per `IOFBModes`). Nessun `removeProperty` di
  `IOFBConfig` nel sorgente (grep).
- **Dentro `IOFBConfig`**: `IOFBModes` (array di dizionari; ogni voce ha `ID` = `kIOFBModeIDKey` e `DM`; `IOFramebuffer.h`,
  `IOGraphicsTypes.h:1563-1564`) e, a livello superiore, `IOFBDetailedTimings` (`kIOFBDetailedTimingsKey`, `:11679`, poi
  `doSetDetailedTimings`).
- **Tipo di connessione di CoreDisplay**: il report RE non lo dice. Un server connection chiama `open()`; una shared
  (`kIOFBSharedConnectType`) no. Non verificato, e per questo i due hook non dipendono dal tipo (vedi sotto).

### Punti scelti

| Hook | Quando gira | Cosa fa |
|---|---|---|
| `close()` (override, dopo `super::close()`) | fine di ogni sessione (ultimo client server uscito) | pota `IOFBConfig` **e svuota `aliasModes`** |
| `newUserClient()` (override, dopo `super::newUserClient`, solo se successo e tipo server) | inizio di ogni sessione WindowServer | pota `IOFBConfig`; **non** tocca gli alias |

- `close()` è il punto che cattura la scrittura di CoreDisplay della sessione N prima che la N+1 legga. Non dipende dal tipo
  di connessione, né dall'ordine interno di `IOFBBuildModeList`.
- `newUserClient` è la rete di sicurezza: la potatura si ripete all'inizio di ogni sessione server. Non svuota gli alias perché
  `matchFramebuffer` può installare un alias tra due sessioni (quando nessun WindowServer è connesso); cancellarlo lì
  lascerebbe `getInformation(0xC0000000)` senza risposta.
- Il ritorno di successo è obbligatorio: `kIOReturnExclusiveAccess` significa che la sessione precedente è ancora viva.

### Cosa viene potato (solo ciò che causa il duplicato)

- Voci di `IOFBModes` con `ID` in `[0x80000000, 0xFFFFFF00)`: ID generati da CoreDisplay e alias (0x80001000, 0x80000001,
  0xC0000000). Il modo 1 e le sue voci `DM` restano: `getConfigMode(1, DM)` alimenta l'uiScale di `matchFramebuffer`
  (`IOFramebuffer.cpp:10709-10716`), che la rimozione totale di `IOFBConfig` (proposta del report §8.4) avrebbe rotto.
- Voci di `IOFBDetailedTimings` che sono il timing GOP (`OSData` di 0xa0 byte, `rdna4_is_gop_timing`).
- Tutto il resto di `IOFBConfig` resta: `IOFBScalerUnderscan`, impostazioni utente, altre chiavi.
- Se il risultato è vuoto, `IOFBConfig` viene rimosso; altrimenti viene riscritto con `setProperty`.
- Ogni potatura è loggata: `close: IOFBConfig pruned: N IOFBModes entrie(s) …, M GOP detailed timing(s); K alias mode(s) cleared`
  (o `… kept` per `newUserClient`); anche `no IOFBConfig` quando la proprietà manca.

### Differenza con il report RE §8.4

La proposta del report era rimuovere `IOFBConfig` in `open()`. Non l'ho adottata per tre motivi verificati nel sorgente:
(1) `open()` gira una sola volta per oggetto (sopra), quindi lì la pulizia non sarebbe per sessione; (2) `IOFBModes` contiene anche il
modo GOP (§8.2 del report), quindi togliere solo `IOFBDetailedTimings` non basta: va potato anche `IOFBModes`; (3) `getConfigMode(1, DM)`
serve a `matchFramebuffer`. Il risultato è una potatura chirurgica, non la rimozione completa.

### Verifiche

- `clang++ -fsyntax-only -Wall -Wextra` con MacKernelSDK: 0 errori, 0 warning. `close`, `newUserClient` e `pruneSessionConfig`
  compilano con la firma dell'header.
- Catena 0001–0007 applicata con `patch -p1` alla pristina: risultato uguale alla v8 (`research/ext/RDNA4FB-n44/src`).
- Patch: `cobalt64/third-party/rdna4fb-n44/0007-navi44-session-config.patch` (160 righe, sha256 `17c324bc…`).
- Versione 0.0.8 in `Info.plist` (short e bundle), `Makefile` (`VERSION`), `src/kmod_info.c`.
- La logica di dizionario (`OSDictionary`/`OSArray`) **non è stata provata su host**: serve libkern. È compile-only.

### Cosa cercare al prossimo boot

1. Dopo la chiusura di WindowServer: `close: IOFBConfig pruned: …` (con i conteggi della sessione appena chiusa).
2. All'avvio della sessione successiva: `newUserClient: IOFBConfig pruned: … 0 GOP detailed timing(s)` oppure conteggi
   diversi da zero se la chiusura non è avvenuta.
3. In sessione 2: `validate: GOP timing accepted`, `succeeded for mode 0x…` per 2560×1440@120 (non `Declined … Mode_clone`
   né `0xe00002dd`), `main display 0x1b572300`.

### Rischi

1. **Ordine non verificato sul binario di CoreDisplay**: se CoreDisplay scrive `IOFBConfig` dopo il `close()` della sessione precedente
   (improbabile: la scrittura è nella build della lista, dentro la sessione), la potatura di `newUserClient` la copre comunque.
2. **Alias svuotati a fine sessione**: la sessione successiva li ricrea con `validate` + `setDetailedTimings` (matchFramebuffer). Se un
   modo alias viene chiesto prima che la sessione lo reinstalli, la risposta è "non mio" (`ownsDisplayMode` false).
3. **Logica di dizionario non testata su host** (vedi sopra): possibile errore di refcount o di chiave. Il log dirà i conteggi.
4. **Impostazioni utente di IOFBConfig** conservate; quelle che dipendono dai modi alias (scalatura del modo GOP, se mai configurate)
   vanno perse con la potatura. Non ce ne sono nei log del progetto.
5. **Versione 0.0.8**: cambia l'identità del kext (sha256); da riconciliare con l'approvazione GUI.
6. Nessuna VM, nessun commit, nessuna scrittura hardware nuova.

## Boot43 (v8, 0.0.8, consenso): stato al fermo (21/10, 19:24-19:27)

- Patch 0001..0007 applicate alla pristina: identiche alla copia di lavoro `research/ext/RDNA4FB-n44/` (sola differenza `.git`). Patch 0007: `cobalt64/third-party/rdna4fb-n44/0007-navi44-session-config.patch`, sha `17c324bc…`.
- Build nella VM di build (`make MKSDK=…/MacKernelSDK`, exit 0). Simboli: `close`, `newUserClient`, `pruneSessionConfig(const char*, bool)`, `setDetailedTimings`, `validateDetailedTiming`, `publishTimingRange`, `open`. Stringhe: `IOFBConfig pruned`, `published IOFBTimingRange (`, `0.0.8`. Firma ad hoc valida, match `0x75901002`.
- Copia: `/mnt/vm/builds/rdna4fb-n44-v8-20261021/` (`RDNA4FB.kext`, `SHA256SUMS`, log). Binario `373c6c14…`, `Info.plist` `f16b6680…`. VM di build spenta, `qemu-img check` pulito.
- EFI P0-like (`17 --native-s1b --metal --csr-active-config 3`), launcher `N4X_GPU_PRIMARY=0 N4X_GPU_ROMBAR=1`, watchdog armato. Guest su, kext safety START, protezioni PRESENT, 22 heartbeat finora, hotspot 33–38 °C, zero WARN/TRIP, zero panic.
- Guest: v7 (0.0.7, già consentita) caricata al boot. Backup v7: `~/rdna4fb-stage/backup-v7/RDNA4FB.kext` (SHA `222eb96e…`). Originale spostato in `~/rdna4fb-stage/replaced-v7-20261021T192520/`. v8 installata in `/Library/Extensions/RDNA4FB.kext` (root:wheel, SHA `373c6c14…`).
- `sudo -n kmutil load -p`: «not approved to load» rc=27. Una sola chiamata. Richiesta di consenso in attesa della GUI.
- Evidenze in `research/hw_dump/v8_boot43/` (SHA256SUMS).

### Boot43 proseguito: consenso v8, spegnimento, EFI P2 (boot44, 21/10, 19:28-19:32)
- Consenso GUI v8 dato dall'utente senza riavvio (riferito dal coordinatore).
- Spegnimento guest: `sudo -n shutdown -h now` → `vfs_unmountall(system) end`, poi panic in halt `Ticket lock 0xffffff8020168580 is unexpectedly owned … @lock_ticket.c:155` in `IOPlatformHaltRestartAction -> AppleSMC`. Stessa firma dei boot 21, 25, 37. Il watchdog ha visto il silenzio (heartbeat-lost 10.2 s) e ha chiuso QEMU come da progetto (rc=2). Hotspot all'ultimo heartbeat 37 °C, nessun TRIP. Evento: `research/hw_dump/gpu_safety_events/20261021T192828-heartbeat-lost_10.2s`. `qemu-img check` pulito.
- EFI P2 per v8: `--primary --metal-disp --metal-ws --agdc --amfi-get-out-of-my-way --csr-active-config 3`, senza `--rdna4fb` (come per la v7), TR di default.
- Avvio: `N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1`, watchdog READY/START alle 19:31:35. QEMU partito. Attesa del passo 4 (solo dopo che l'utente passa al DP).

## Boot44 (v8, 0.0.8): passo 4 completo (21/10, 19:32-19:34)

Evidenze: `research/hw_dump/v8_boot44/` (log unificato pre e post arm, `key_lines.txt`, `pipestat_0_and_4_postarm.txt`, seriale, log watchdog, `SHA256SUMS`).

**Prima dell'arm (WindowServer pid 202, 19:31:39)**
- `published IOFBTimingRange (default, 312 bytes): version 2, clock 497250000..498250000 Hz, links 0, bandwidth 25920000000 bit/s`.
- `validate: call 1`, `GOP timing accepted (1): clock 497750000 Hz, numLinks 0`.
- `newUserClient: no IOFBConfig; 0 alias mode(s) kept` (prima sessione, nessuna proprietà da potare, atteso).
- `InstallTimingWithWireFormats - SDR_RGB__8_Native succeeded for mode 0x80001000 (2560x1440@120.0)`.
- `Startup Mode 2560 x 1440 … online enabled`. `loginUI: main display 0x1b572300 frame={{0,0},{2560,1440}}`.

**Arm**
- `n48nub publish`: state 1 (published). `pipeadopt` al primo tentativo: flags 0x3b (adottata, bit 0x2). `pipeagdc 1`: status 0 (PUBLISHED).
- `--arm-check`: ARM_CHECK_PASS. `--arm-desktop --dry-run`: ok. `--arm-desktop` (ARM): ARM_OK, flags 0x3f, pipe ARMED, `accel+0xccf = 1`.

**Dopo l'arm: chiusura e seconda sessione**
- Chiusura della sessione pid 202 (`killall`, 19:33:06): `RDNA4FB: close: IOFBConfig pruned: 1 IOFBModes entrie(s) of the reserved range, 1 GOP detailed timing(s); 1 alias mode(s) cleared`. Il potaggio avviene alla chiusura, come previsto dalla 0007.
- Seconda sessione pid 828 (19:33:08): `RDNA4FB: newUserClient: IOFBConfig pruned: 0 IOFBModes entrie(s) of the reserved range, 0 GOP detailed timing(s); 0 alias mode(s) kept`. Già pulita dalla chiusura.
- `validate: call 2`, `GOP timing accepted (2): clock 497750000 Hz, numLinks 0`. `setDetailedTimings: 1 alias mode(s)`.
- **Nella seconda sessione**: `InstallTimingWithWireFormats - SDR_RGB__8_Native succeeded for mode 0x80000000 (2560x1440 to 2560x1440@120.0)`. Zero `Mode_clone`, zero `0xe00002dd`. Per pid 828: succeeded 1, dd 0, Mode_clone 0, c7 141 (gli altri formati e modi restano falliti come prima).
- `main display 0x1b572300 frame={{0,0},{2560,1440}}` anche nella seconda sessione.

**Contatori**
- `T1 counts/10s [WindowServer pid 828]`: `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`.
- `pipestat 0`: flags 0x3f, hook calls 1, handled 1, submit pass-through 0, will-perform 0, frames copied 0, completed 0.
- `pipestat 4`: vblank timestamp switch ON, stamps written 0, skipped 0.
- Nessun frame e nessun flip misurato. Il flip GOP (FASI 4.2) resta il punto aperto.

**Safety**: 155 heartbeat, hotspot 33–38 °C, zero WARN/TRIP, zero panic. Watchdog armato.

**Da verificare**: osservazione dell'utente sul DP dopo l'arm (orologio, trasparenza, desktop composto). I contatori dicono ancora frames=0.

### Osservazione utente dopo l'arm del boot44 e boot45 (rdna4-vbl) (21/10, 19:33-19:49)
- Osservazione dell'utente sul DP dopo l'arm del boot44 (v8): nessuna differenza. Niente orologio, niente trasparenza, come per la v7.
- Diagnosi del coordinatore (`research/reports/compositor_diag.md`): il VBL emulato di RDNA4FB si arma solo con `rdna4-vbl=1` (`framebuffer.cpp:2075`, `:1522`). Senza, il compositor non produce command buffer né frame. Il boot44 non aveva il flag.
- Spegnimento boot44: `shutdown -h` → `vfs_unmountall(system) end`, nessun panic, QEMU uscito da solo, watchdog rc=0, `qemu-img check` pulito. Evidenze in `research/hw_dump/v8_boot44/` (`serial_boot44_shutdown.log`, watchdog finale, SHA256 aggiornati).
- Script: nuova opzione `--rdna4-vbl` in `tools/vm/prepare-gpu-test-stage.py` (il valore precedente di `rdna4-vbl` viene sempre rimosso, quindi il flag è esplicito a ogni run; registrato in `test-plan.json` come `rdna4_vbl`). Launcher `tools/vm/start-gpu-test-vm.sh`: controllo di coerenza `rdna4-vbl=1` ↔ `rdna4_vbl` del piano (fail closed).
- EFI P2 boot45: `--primary --metal-disp --metal-ws --agdc --amfi-get-out-of-my-way --csr-active-config 3 --rdna4-vbl`, senza `--rdna4fb` (v8 da `/Library/Extensions`), TR di default. `--dry-run` conferma il flag; senza l'opzione viene rimosso.
- Avvio: `N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1`, watchdog armato alle 19:48:43. QEMU partito. Restano da fare: `RDNA4FB: vbl: emulated VBL armed` nel seriale, `accel ucprobe 1` (approvato), arm, contatori.

## Boot46 (v8, 0.0.8, rdna4-vbl=1, 23/10/2026): VBL armato, arm eseguito, frames 0

Evidenze: `research/hw_dump/vbl_boot46/` (SHA256SUMS). EFI P2 `--native-s1b --metal --primary --metal-disp --metal-ws --agdc --amfi-get-out-of-my-way --csr-active-config 3 --rdna4-vbl`, kext di sicurezza `cb18a1f9` (uguale a `SHA256SUMS` del build), RDNA4FB v8 da `/Library/Extensions`. `test-plan.json` coerente (`rdna4_vbl: true`, `primary_display: true`).

**Avvio e sicurezza**
- Watchdog READY 15:39:36; QEMU avviato; `N4X-SAFETY START` 15:40:13, protezioni `PRESENT` (`0x0498f59e_38fffcfb`, bit 23/27/28/29 presenti).
- Heartbeat: 227 nel seriale post-arm; hotspot 30-35 °C; zero WARN/TRIP, zero panic. Gli avvisi `WARNING` nel seriale sono quelli noti del bring-up (discovery GC 12.0.0, `GB_ADDR_CONFIG`, SATA).

**Kext e VBL**
- `RDNA4FB: vbl: emulated VBL armed, period 6945 us` (framebuffer.cpp:1545), presente in entrambe le sessioni. Il periodo corrisponde a circa 144 Hz (preferred EDID 2560x1440@143.973 Hz), non agli 8333 us di 120 Hz previsti nella diagnosi: da chiarire quale timing è installato.
- `validate: GOP timing accepted` in entrambe le sessioni (call 1 e 2), `setDetailedTimings: 1 alias mode(s)`.

**WindowServer e display**
- Prima sessione (pid 202, 15:40) e seconda sessione (pid 1093, dopo l'arm): `Display id 0x00000000 -> 0x1b572300`, `main display 0x1b572300`. La login window è visibile sul DP (osservazione del coordinatore).
- Riga `InstallTimingWithWireFormats ... succeeded for mode 2560x1440@120`: **non osservata** in questo boot, né nel seriale né nel log unificato (presente in boot44). Non è chiaro se l'installazione del modo sia avvenuta.
- Dopo l'arm: `AGDC LINKCFG endpoint 2560x1440 pixelClock 497750000 ... timing LIVE raster`, `device_preserves_framebuffer: needs_refresh = YES`.

**ucprobe e adozione**
- `accel ucprobe 1`: `FAILED (0xe00002e2)`, ripetuto dopo l'adozione. Il messaggio dice che il gate di esposizione è chiuso e chiede la variante live `stage17-accel-pdb0-qn`. Il hook non è installato: **il cookie `pipe+0xd8` non è stato misurato** su questo boot.
- `n48nub publish`: `state 1 (published)`. Primo `pipeadopt`: status 3 (`no Navi48Accelerator under our nub`). Il kext aux `com.navi48.accelprobe (0.0.7)` è comparso nel registro dopo la publish, senza un caricamento da parte mia (non ho eseguito `kmutil load`). Secondo `pipeadopt`: status 0, `flags 0x3b` (adottata, bit 2).
- `pipeagdc 1`: status 0 (PUBLISHED), poi 12 (already published).

**Arm** (`deploy-metal-stack.sh --arm-check` PASS, `--arm-desktop --dry-run` OK, `--arm-desktop` con conferma `ARM`): `ARM_OK`, `accel+0xccf = 1`, flags `0x3f`, WindowServer pid 1093, `fbname 1` saltato (N48_ARM_FBNAME=0).

**Contatori dopo l'arm** (`guest_postarm_counters_boot46.txt`)
- `pipestat 0`: `flags 0x3f`, factory `0xd`, hook calls 267 = 1, 277/278/279 = 0; submit pass-through 0, will-perform 0, bytes/frames copied 0, completed 0.
- `pipestat 4`: vblank timestamp switch ON, `stamps written 0`, tutti i contatori di skip a 0, `last t_vbl 0`.
- T1 WindowServer 1093: `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`.

**Lettura**
- `rdna4-vbl=1` arma il timer VBL (confermato nel seriale), ma il compositor non sottopone alcuna transazione alla pipe: `submit 0`, `stamps 0`, `command_buffers 0`. Il VBL armato è quindi necessario ma non sufficiente per i frame.
- Il cookie VBL della pipe (`pipe+0xd8`) non è verificato, perché `ucprobe` non è installabile in questa variante: è la misura che deciderebbe se il fronte è stato consumato prima della prima registrazione.
- Non è ancora verificato il desktop composto sul DP. Con `frames=0` non ci si aspetta orologio o trasparenza aggiornati.

**Prossimo passo (da decidere dal coordinatore)**
1. Verificare il timing installato (2560x1440@120 vs il periodo di 144 Hz) e perché `succeeded for mode` non compare in questo boot.
2. Per la misura del cookie serve la variante `stage17-accel-pdb0-qn`, cioè un nuovo boot con altre boot-args: non eseguita.

**Osservazione utente dopo l'arm (boot46)**: nessuna differenza. Orologio assente, nessuna trasparenza. Coerente con i contatori (frames 0, submit 0).

**Spegnimento boot46 (23/10, 15:46)**: `sudo -n /sbin/shutdown -h now` -> `vfs_unmountall(system) end`, `CPU halted`, nessun panic. QEMU uscito da solo (nessun quit QMP necessario). Watchdog `rc=0`, 355 heartbeat in totale, zero WARN/TRIP. `qemu-img check` (sola lettura) pulito. Evidenze finali: `research/hw_dump/vbl_boot46/` (`serial_boot46_final.log`, `watchdog_boot46_final.log`, `qemu_img_check_boot46.txt`, `user_observation_boot46.txt`, SHA256SUMS).

## Boot47 (v8, 0.0.8, rdna4-vbl=1, multisession, apps, npci=0x2000; 23/10/2026): arm e cattura post-arm

Evidenze: `research/hw_dump/vbl_boot47/` (SHA256SUMS). EFI P2 come boot46 più `navi48-multisession=1 navi48-apps=1 npci=0x2000` (`prepare-gpu-test-stage.py --multisession --apps --npci`, controllo in `start-gpu-test-vm.sh --check`). `navi48-interrupts=0` invariato. Kext di sicurezza `cb18a1f9`.

- Avvio: watchdog READY 15:55:50. Kext di sicurezza START, protezioni PRESENT, `vbl: emulated VBL armed, period 6945 us`, `validate: GOP timing accepted (1)`. 40 heartbeat pre-arm, 97 in totale, zero WARN/TRIP, zero panic.
- Nub `publish` OK, `pipeadopt` al primo tentativo (`flags 0x3b`), `pipeagdc 1` PUBLISHED, `--arm-check` PASS, `--arm-desktop --dry-run` OK, `--arm-desktop` con `ARM`: ARM_OK, flags 0x3f. WindowServer pid 705 (sessione post-arm, avviata 15:57:19).
- Pid 705: `Navi48Metal: +load ... MTLDevice` (device creato), `T1 pool/drawopt ON`, `Metal compositor activated` (15:57:19.588, sostituisce `Software compositor` del pid 191). `Display id 0x00000000 -> 0x1b572300`, `Created FB 1 of 1`, `GPU: FB: 1 of 1 opened`, `force8BPC = NO` (era YES nel pid 191).
- Kernel: `validate: call 2`, `GOP timing accepted (2)`, `close: IOFBConfig pruned` del pid 191, `agdc ... from pid 705 -> kAGDCGPUCapability: 1 framebuffer, RDNA4FB`, `LINKCFG endpoint 2560x1440 pixelClock 497750000 timing LIVE raster`.
- **Non osservato:** `succeeded for mode` e `InstallTiming` (0 occorrenze nel log WindowServer, nel log di sistema e nel seriale, come nel boot46 e a differenza del boot44).
- Contatori post-arm: `pipestat 0` flags 0x3f, hook 267=1, submit 0, will-perform 0, frames copied 0, completed 0. `pipestat 4` vblank switch ON, stamps 0, `last t_vbl 0`. T1 pid 705: `pipelines gfx=1 comp=0 imports=0 command_buffers=0 frames=0`.
- Lettura: il compositor Metal si attiva (`Metal compositor activated`) ma non invia command buffer né transazioni alla pipe. Il collo è a monte del primo command buffer, come nei boot 44-46. Le opzioni multisession/apps non cambiano la Tx. Osservazione utente da riportare dal coordinatore.
- Evidenze: `wslog_full_10m_postarm.txt` (log WindowServer intero, 10 min, senza filtri), `subsystems_10m_postarm.txt` (predicato su WindowServer, SkyLight, Navi48Metal, CoreDisplay, RDNA4FB, DisplayPipe), `pipestat_postarm.txt`, `serial_boot47_postarm_clean.txt`, `watchdog_boot47.log`, `test-plan_boot47.json`.

**Osservazione utente boot47 dopo l'arm** (riferita dal coordinatore): nessuna differenza. Orologio assente, nessuna trasparenza, login window invariata. Coerente con `frames=0` e `command_buffers=0` nel pid 705.

**Spegnimento boot47 (23/10, 15:58)**: `sudo -n /sbin/shutdown -h now` -> `vfs_unmountall(system) end`, `CPU halted`, poi il panic in halt `Ticket lock ... unexpectedly owned ... @lock_ticket.c:155` in `IOPlatformHaltRestartAction -> AppleSMC`. Stessa firma dei boot 21, 25, 37 e 43. Il watchdog ha rilevato il silenzio (`heartbeat-lost 10.1 s`) e ha inviato QMP quit (rc=2), come previsto dal progetto. Evento: `research/hw_dump/gpu_safety_events/20261023T155855-heartbeat-lost_10.1s/`. Heartbeat totali 138, zero WARN/TRIP. `qemu-img check` (sola lettura) pulito. Evidenze finali: `research/hw_dump/vbl_boot47/` (`serial_boot47_final.txt`, `watchdog_boot47_final.log`, `qemu_img_check_boot47.txt`, `user_observation_boot47.txt`, SHA256SUMS).
