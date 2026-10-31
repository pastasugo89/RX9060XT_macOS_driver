# Piano di recupero: kernel Navi48Bringup 0.0.666 / 0.0.667 (contexts)

Stato: piano scritto offline. Nulla di quanto segue è stato provato su hardware né sull'EFI reale.
Il payload dichiara `hardware_validation: not performed` e `installation: not performed`.
Quando un punto è dedotto dal codice o dai log, e non verificato su un avvio reale, è segnalato come tale.

## 0. Riferimenti fissi

- Payload: `research/builds/macos-20261031/production/kernel-payload-v2`
- UUID del volume EFI: `7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3` (partizione FAT, OCBOOT)
- Config baseline, sha256 `92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb`.
  È identica a `EFI/RECOVERY/pre-contexts-666-config.plist`, sia nel payload sia sull'EFI dopo l'installazione.
- Config candidata, sha256 `eb1a13e457fe69073124406f51116df64fdd401affe84081d54c50a8caa1eea4`.
  La sola differenza è `Kernel/Add[7]/BundlePath`: da `Navi48Bringup-eight-0.0.665.kext` a `Navi48Bringup-contexts-0.0.666.kext`.
- Il 665 resta sull'EFI sia prima sia dopo l'installazione.
- Backup dell'installer: `/Library/Application Support/Navi44/efi-backup-<timestamp>/`, con `EFI/` completo e `backup-manifest.json`.

## 1. Risposte alle domande

### 1.1 La guard di avvio protegge il caso (b)?

No, non per il caricamento del kext. Lo protegge solo per l'attivazione del display.

- Il handoff (`HANDOFF-MACOS-RX9060XT.md`, sezione "Stato confermato") registra che in precedenza la configurazione si bloccava dopo la selezione della regione, prima della rimozione di `cpus=1`. Un ciclo di blocco al boot è quindi uno scenario reale, non ipotetico.
- Il kext esegue la bring-up in `start()` (`cobalt64/src/navi48-bringup/src/Navi48Bringup.cpp:7369`). La stage è letta a riga 7396 da `navi48-stage`. Il gate di `probe()` è a riga 7352 e legge `navi48bringup`.
- Questi boot-args arrivano da OpenCore a ogni avvio. Il log lo conferma: `research/hw_dump/baremetal_boot2/opencore.txt`, righe 39-41 (Delete, poi Setting).
- La guard (`system/.../accelerated-reboot-trial.sh`, nel payload) scrive il latch `begin` alla riga 114. Questo avviene solo dopo l'attesa del traduttore (righe 139-144) e del WindowServer (147-151). Il controllo `expected kernel 666` è a riga 158. L'attivazione (`pipearm 1` riga 223, `killall WindowServer` riga 231) viene dopo.
- Un hang causato dal kext in `start()` avviene prima di qualsiasi latch. Nessuno stato viene scritto. Il riavvio successivo carica di nuovo il 666 con gli stessi boot-args, e il ciclo non ha uscita automatica.
- Se l'hang avviene dopo il latch, il riavvio successivo trova `pending` e rifiuta l'attivazione (`BOOT-STATE.md`, tabella: pending, refuse, reset revisionato). Questo blocca solo l'attivazione. Il kext viene caricato comunque.

### 1.2 Esiste un boot-arg che disattiva il kext, impostabile senza desktop?

- Sì: `navi48bringup` (`Navi48Bringup.cpp:7352`). Se è assente o 0, `probe()` ritorna `nullptr`. Il kext non si aggancia alla GPU e non esegue la bring-up.
- Non è impostabile senza modificare l'EFI. Il valore arriva da `NVRAM/Add` (GUID `7C436110-…`, chiave `boot-args`), e `NVRAM/Delete` elenca `boot-args` (`config.plist`, circa righe 1449 e 1491). OpenCore elimina quindi la variabile e la riscrive a ogni avvio.
- Quindi `nvram boot-args=…` da Terminale di Recovery non sopravvive al prossimo avvio OpenCore. Il log mostra l'ordine Delete poi Setting (`opencore.txt:39,41`). Non verificato con un avvio reale.
- `ResetNvramEntry.efi` (Drivers) e `WriteFlash=false` non cambiano il quadro: OpenCore ripristina comunque i valori di `Add`.

### 1.3 Picker e Recovery

- `ShowPicker=true`, `Timeout=5` (`config.plist:1334,1338`). `ScanPolicy=0` (riga 1386) mostra tutte le voci rilevate.
- `Misc/Entries` è vuoto. Non c'è una voce alternativa con un `Kernel/Add` diverso: `Kernel/Add` è globale a tutte le voci.
- Recovery è avviata da OpenCore con la stessa `Kernel/Add`. Il bundle ha `MinKernel 25.0.0` e `MaxKernel` vuoto (`Kernel/Add[7]`, circa righe 431-445). Il comportamento atteso è che il kext venga iniettato anche in Recovery. Non verificato.
- Recovery quindi non è un bypass: se il kext causa panic o hang, può farlo anche lì.

### 1.4 Procedure più brevi e sicure

**Via d'uscita principale (dalla 0.0.667): Shift nel picker di OpenCore**

Il payload v3 attiva `Misc/Boot/PollAppleHotKeys`. Nel picker di OpenCore seleziona macOS e premi Invio tenendo premuto Shift: macOS parte in modalità provvisoria (`-x`). Il kext 0.0.667 in `probe()` rinuncia a partire con `-x` oppure con `navi48-off=1` (`Navi48Bringup.cpp`, commit `db8b202`). Il desktop parte senza accelerazione e senza driver GPU, e da lì si esegue il ripristino (c) punto 3. Vale per i casi (a) e (b). Non è ancora provato su hardware: va verificato una volta, a freddo, subito dopo l'installazione.

**(a) Panic al boot**

1. Non ripetere il boot più volte. Ogni tentativo ripete lo stesso panic e non lascia alcun latch.
2. Prova la voce Recovery dal picker. Se parte, esegui il ripristino della sezione 2.
3. Se Recovery va in panic, monta l'EFI da un altro computer (partizione FAT con l'UUID sopra). Copia `RECOVERY/pre-contexts-666-config.plist` su `OC/config.plist`. Verifica che il sha256 sia `92379563…`. Facoltativamente rimuovi `OC/Kexts/Navi48Bringup-contexts-0.0.666.kext`. Poi smonta.

**(b) Hang al WindowServer**

- Se il sistema torna alla shell o a Recovery, segui (a) punto 2.
- Altrimenti: spegnimento forzato, senza nuovi tentativi. Il latch è assente (hang prima della riga 114) o `pending` (hang dopo). In entrambi i casi il kext viene caricato di nuovo. Procedi come (a) punto 3.
- Non usare `nvram` come rimedio: non è persistente (1.2).

**(c) Avvio con desktop ma comportamento errato**

1. Blocca l'attivazione al prossimo avvio (root): `sudo touch "/Library/Application Support/Navi44/accelerated-trial/disabled"`. La guard si ferma alla riga 86.
2. Se la sessione è ancora usabile, disarma la GPU: `sudo "/Library/Application Support/Navi44/accelerated-trial/navi48test" accel pipearm 0`. È lo stesso comando di rollback della guard (riga 61). Non verificato in questa sessione.
3. Ripristina l'EFI: `sudo python3 kernel-efi/restore-kernel-efi.py <payload> --dry-run`, poi `--apply`. Aggiungi `--remove-kext` solo se vuoi rimuovere il 666 dall'EFI.
4. Riavvia e verifica: `kmutil showloaded --list-only | grep -i navi48` deve mostrare `com.navi48.bringup (0.0.665)`.
5. Il ripristino non azzera `boot-state.json`. Una nuova attivazione richiede la revisione descritta in `BOOT-STATE.md`.

## 2. Ripristino da Terminale di Recovery, senza Python

Non è garantito che Recovery contenga `python3`. I comandi seguenti usano solo strumenti di sistema. Non sono stati provati e vanno verificati su un Mac con lo stesso layout prima di affidarsi a loro.

```sh
diskutil list                        # individuare la partizione EFI FAT con UUID 7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3
diskutil mount diskXsY               # montaggio in scrittura
ls /Volumes                          # trovare il nome reale del mount
E=/Volumes/EFI/EFI                   # adattare al nome reale
cmp "$E/RECOVERY/pre-contexts-666-config.plist" "$E/OC/config.plist"   # ci si aspetta una differenza
cp "$E/RECOVERY/pre-contexts-666-config.plist" "$E/OC/config.plist.tmp"
mv "$E/OC/config.plist.tmp" "$E/OC/config.plist"                        # rinomina sul FAT
cmp "$E/RECOVERY/pre-contexts-666-config.plist" "$E/OC/config.plist" && echo CONFIG_RESTORED
sync
diskutil unmount diskXsY
```

Se `shasum` è disponibile, `shasum -a 256 "$E/OC/config.plist"` deve dare `92379563…`.

## 3. Lacune trovate e modifica minima proposta

**G1, nessun avvio senza il 666 se il kext va in panic o in hang durante `start()`.** Chiusa dalla 0.0.667 con `-x` / `navi48-off=1` in `probe()` e `PollAppleHotKeys` attivo (vedi 1.4). Con il solo 666 resta aperta. Analisi originale:

- La configurazione attuale non la chiude. `Kernel/Add` è globale, non esistono voci alternative, e `boot-args` non è persistente da NVRAM.
- Proposta preferita, un kill switch da NVRAM non gestito da OpenCore. Cambia `Navi48Bringup::probe()` (`Navi48Bringup.cpp:7350-7352`): prima del gate `navi48bringup`, legge una variabile NVRAM non presente né in `NVRAM/Add` né in `NVRAM/Delete`, per esempio `7C436110-AB2A-4BBB-A880-FE41995C9F82:navi48-kill`. Se vale 1, ritorna `nullptr`. La lettura da `/options` (IODTNVRAM) è da verificare.
  - Modifiche: una funzione nel sorgente, un test host, una nuova build 0.0.667 con `build-production-contexts.py`, e un payload v3. Nessuna modifica a `Kernel/Add` o a `config.plist`.
  - Uso da Recovery: `nvram 7C436110-AB2A-4BBB-A880-FE41995C9F82:navi48-kill=1`. Rimozione: `nvram -d 7C436110-AB2A-4BBB-A880-FE41995C9F82:navi48-kill`. Funziona anche in Recovery, perché anche lì il kext viene caricato.
- Alternativa configurativa, non verificata: una seconda voce in `Misc/Entries` che avvia un secondo loader OpenCore con la config baseline in una cartella separata. Richiede un test hardware. OpenCore potrebbe non risolvere la config del secondo loader come previsto.

**G2, la guard non copre il caricamento del kext.** Non si risolve modificando la guard. La protezione deve stare nel kext, come in G1.

**G3, installazione dell'EFI con la guard vecchia.** La guard in uso prima dell'installazione non ha il controllo `expected kernel 666` né la probe. Con il 666 sull'EFI, l'attivazione girerebbe senza quei controlli. L'installer rifiuta quindi l'installazione se non è presente `APP/disabled` o se i file di sistema revisionati non sono già installati. Installare prima i file di sistema revisionati oppure creare `disabled`.

## 4. Comandi di riferimento

```sh
# Verifica e piano (nessuna scrittura, nessun montaggio in scrittura)
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/install-kernel-efi.py <payload>
# Installazione (scrive l'EFI e crea il backup)
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/install-kernel-efi.py <payload> --apply
# Ripristino dal backup, o dal RECOVERY sull'EFI
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/restore-kernel-efi.py <payload> --backup <dir> --apply
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/restore-kernel-efi.py <payload> --from-recovery --apply
# Test offline
python3 tools/baremetal/navi44-desktop/kernel-efi/test-kernel-efi.py
```
