# Trial b31: Metal bundle 31 + guard 31 (MSAA ShaderWrite e viste IOSurface)

Stato: pacchetto preparato per `./stage.sh` e `install-trial.sh`, **non installato**. Il bundle 30 resta attivo finché non esegui `install-trial.sh`. Non testato su hardware né su Metal/RADV: i due fix sono verificati solo con i test host.

## Cosa cambia rispetto al bundle 30

Il bundle 31 è il bundle 30 più due fix (sorgenti in `research/builds/macos-20261031/bundle31b-src/`, diff in `PATCH-vs-bundle30.diff`). Versione `CFBundleVersion` 30 -> 31. `libn48xlate.dylib` e `libvulkan_radeon.dylib` sono identici al bundle 30. Cambia solo `Contents/MacOS/Navi48Metal`.

- **Fix 1: ShaderWrite su texture multisample.** Prima il driver rifiutava la creazione di una texture multisample con `ShaderWrite` (ANGLE/WebGL la richiede). Ora il descrittore viene accettato: il VkImage non riceve lo storage usage (`dropStorage`). Una scrittura da shader su quella texture fa fallire la codifica con `n48Fail` (una volta per processo viene scritto un avviso), quindi la scrittura non viene persa in silenzio. Effetto atteso: il processo GPU di Brave non va più in crash su quella richiesta.
- **Fix 2: viste di texture IOSurface-backed.** Prima una vista su una texture IOSurface veniva rifiutata. Ora le viste sono accettate e risolvono alla texture radice (`n48Owner`), che possiede il VkImage e lo stato di import. Per le viste che cambiano formato la radice deve avere le feature richieste, altrimenti il driver risponde con codice 102.
- Non cambia: la pipeline solo vertice e il placeholder invisibile del bundle 30 restano come sono.

## Guard di avvio

La guard installata oggi è quella del kernel 667 (profilo `stage30-vonly-v1`), non il template del bundle 30. `stage.sh` non usa un template: copia la guard **live** e modifica solo tre righe nella copia:

1. `PROFILE=stage30-vonly-v1` -> `PROFILE=stage31-msaa-iosurface-v1`. Il cambio di nome da solo non cancella un fallimento precedente: il latch resta come descritto in `BOOT-STATE.md`.
2. Il check `bundle_version` da 30 a 31, incluso il messaggio di errore.
3. L'hash di `Contents/MacOS/Navi48Metal`, letto dal bundle nuovo al momento dello stage (non è scritto a mano in nessun file).

Tutto il resto della guard (capability 665/667, probe di isolamento del contesto, controlli dei dylib) resta identico. `stage.sh` rifiuta la copia se il diff contiene altro. Il diff è in `GUARD.diff` nella build dir. Il test offline è `test-guard-edit.py`.

Non toccati: audio (VoodooHDA, nessuna installazione o ricostruzione), `/private/var/tmp/n48m-spv` (non viene spostato).

## Comandi

```sh
cd ~/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/tools/baremetal/navi44-desktop/metal-trial-b31
./stage.sh                              # senza root; default bundle31b-src/build-31/Navi48Metal.bundle
# oppure: ./stage.sh /percorso/Navi48Metal.bundle
sudo ./install-trial.sh
sudo reboot
```

Output dello stage, sotto `research/builds/macos-20261031/trial-b31/` (cartella di build ignorata da git): `payload/` (bundle, guard, `manifest.json`) e `GUARD.diff`.

`stage.sh` si rifiuta se: il bundle non ha `CFBundleVersion` 31; un file del bundle è cambiato negli ultimi 2 minuti; `codesign --verify --deep --strict` fallisce; un processo che cita `build-31` è in esecuzione; il bundle live non è v30 o la guard live non corrisponde ai suoi hash; il diff della guard contiene altro oltre alle tre righe. Il manifest registra anche lo sha256 della guard live usata.

`install-trial.sh` non accetta opzioni. Prima di installare controlla:
- il payload corrisponde al manifest, è il bundle 31 con la guard 31 e la firma è valida;
- il bundle live è v30 e la guard live corrisponde ai suoi hash;
- la guard live ha lo stesso sha256 registrato da `stage.sh` (altrimenti rilancia `./stage.sh`);
- il boot latch non è `pending` o `failed`.

Poi fa i backup (copie, in ordine: bundle v30 in `/Library/GPUBundles/Navi48Metal.bundle.v30-backup-<ts>`; bundle v30, guard v30, boot-state, plist in `/Library/Application Support/Navi44/trial-b31-backup-<ts>/`), esegue lo swap atomico del bundle e installa la guard 31 con rename atomico dopo `bash -n`. Se un passo fallisce, annulla solo ciò che ha cambiato in quella esecuzione e lascia i backup. Non esegue la guard e non riavvia.

## Dopo il riavvio

1. Al login window non accedere per circa 5 minuti: la guard aspetta translator, registry e riavvio di WindowServer.
2. Brave, `chrome://gpu`: verifica WebGL e che il processo GPU non sia in crash. Poi `chrome://flags`: il flag **Skia Graphite** torna a **Default** (non Enabled). Ricarica la pagina e controlla che Graphite non sia più forzato.
3. Icone: Finder, App Store e Mappe devono mostrare le icone reali. Se restano vuote o vecchie, pulisci la cache delle icone di macOS e riavvia Dock e Finder:

   ```sh
   sudo rm -rf /Library/Caches/com.apple.iconservices.store
   killall Dock Finder
   ```

   Il percorso esiste su questa macchina. Il comando non è verificato in documentazione ufficiale per macOS 26: è quello usato finora.
4. Log da raccogliere:
   - `sudo cat /private/var/tmp/navi44-accelerated-trial/run.log` (cerca `REGISTRY_READY`, `WINDOWSERVER_READY`, `LOGIN_SEEN`, `GPU_BOOT_STABLE`, `STOP`, `FAILSAFE`)
   - `sudo cat "/Library/Application Support/Navi44/accelerated-trial/boot-state.json"` (atteso: `phase: stable`, `observation: desktop-stable-120s`)
   - `sudo tail /private/var/tmp/n48m-translate-state/translate.log`
   - dalla radice del progetto: `python3 tools/baremetal/observe_navi44_safety.py`

Se Brave mostra ancora crash del processo GPU, o compositing software o EGL fallito in `chrome://gpu`, il test non è passato: fai il rollback.

## Magenta (ereditato dal bundle 30)

```sh
sudo touch /private/tmp/n48m-magenta     # fallback magenta, dopo il prossimo avvio dei processi grafici
sudo rm /private/tmp/n48m-magenta        # torna al placeholder invisibile
```

## Rollback

```sh
sudo ./rollback-trial.sh                 # ripristina bundle 30 e guard 30 dal backup trial-b31 più recente
sudo ./rollback-trial.sh --backup DIR    # oppure un backup preciso
sudo ./rollback-trial.sh --reset-latch   # solo dopo aver esaminato un latch pending/failed
sudo reboot
```

Il rollback non usa GPU né WindowServer, funziona da Terminal, SSH o login locale, non tocca l'audio. Il bundle 31 sostituito resta in `$RBDIR/displaced-current.bundle`. Se il latch è `pending` o `failed`, la guard 30 rifiuta l'attivazione al boot successivo (modalità software, senza crash); `--reset-latch` archivia `boot-state.json` e lo consente, solo dopo la revisione.

## Opzioni di emergenza

- Bloccare l'attivazione al boot successivo senza modificare i file: `sudo touch "/Library/Application Support/Navi44/accelerated-trial/disabled"`. Rimuovere con `sudo rm` dello stesso file.
- `/private/tmp/n48m-off` è il kill file scritto dalla guard in caso di errore. Al boot successivo viene archiviato e il boot prosegue, quindi da solo non blocca l'attivazione: usa il marker `disabled`.
- OpenCore picker: F11 all'accensione (vedi `research/reports/baremetal_bringup.md`). Il safe boot con Shift non è verificato. Non fare Reset NVRAM.

## Test offline

```sh
/usr/bin/python3 -I test-guard-edit.py
```

Copia la guard live in una cartella temporanea, usa bundle finti e controlla: il diff contiene esattamente le tre righe previste, la guard risultante passa `bash -n` e il check dei hash per la versione 31, il manifest e la rilevazione di manomissioni, e i sei casi che devono essere rifiutati (inclusa una guard con la versione sbagliata e un dylib diverso). Non usa root, GPU, né scrive in `/Library`.

## Note

- Il bundle è costruito da `bundle31b-src/build-31`. Al momento della stesura quella cartella non esisteva: esiste `build-31b`. Non è stato eseguito `stage.sh`: va lanciato dopo che la build è completa.
- `bundle31-src/build-31` (fix con binario `a362ff...`) è un'altra build con le stesse modifiche ma base diversa (HEAD). Non è il candidato di questo pacchetto: `stage.sh` legge l'hash dal bundle che gli passi.
- `install-trial.sh` verifica il payload contro il manifest prima di installare: rilancia `./stage.sh` se la guard live cambia dopo lo stage.
