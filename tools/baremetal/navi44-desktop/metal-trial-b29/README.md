# Trial b29: Metal bundle 29 + guard 29 (+ audio opzionale)

Stato: pacchetto preparato, **non installato**. Il bundle 28 resta attivo finché non esegui install-trial.sh.

## Cosa cambia

- Traduttore: `libn48xlate.dylib` deriva da NullMoth (LGPL-3.0-or-later; sorgente e PROVENANCE in `research/builds/macos-20261031/nullmoth-xlate-v1`). Il bundle include correzioni ispirate a NullMoth (vedi `bundle29-src/RESULTS.md`).
- `/Library/GPUBundles/Navi48Metal.bundle`: sostituito con il bundle 29 (swap atomico `renamex_np`). Il v28 resta in:
  - `/Library/GPUBundles/Navi48Metal.bundle.v28-backup-<ts>`
  - `/Library/Application Support/Navi44/trial-b29-backup-<ts>/` (bundle v28, guard v28, boot-state prima dell'install, plist, log audio)
- Guard di avvio (`/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh`): versione 29, profilo `stage29-nullmoth-v1`. Diff vs guard 28: `GUARD.diff`.
- `/private/var/tmp/n48m-spv` resta al suo posto: è la cache da cui WindowServer prende gli shader assenti dallo spvcache del bundle (spostarla al primo install del 31/10 ha causato le schermate magenta). `N48M_MOVE_SPV=1` ripristina il vecchio comportamento.
- Audio (opzionale, default ON, eseguito per ultimo): VoodooHDA via `../audio-v1/install-audio.sh`. Con `--no-audio` viene saltato.

## Comandi

```sh
cd /Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/builds/macos-20261031/trial-b29
./stage.sh                   # senza root: verifica bundle, firma, hash, guard, manifest
sudo ./install-trial.sh      # oppure: sudo ./install-trial.sh --no-audio
sudo reboot
```

`stage.sh` accetta il path del bundle come primo argomento. Default: `bundle29-src/build-29-newxlate/Navi48Metal.bundle`. Si rifiuta se `CFBundleVersion` non è 29, se il bundle è stato modificato negli ultimi 2 minuti, se `codesign --verify --deep --strict` fallisce, o se un processo che cita `build-29` è in esecuzione.

`install-trial.sh` si rifiuta se: il payload non corrisponde al manifest; il bundle live non è v28 o i suoi hash non corrispondono alle costanti del guard v28; il boot latch è `pending` o `failed`.

## Dopo il riavvio

1. Al login window non accedere per circa 5 minuti: il guard aspetta il translator, il registry e il riavvio di WindowServer. Poi accedi.
2. Verifica desktop accelerato: icone Finder, Dock, trasparenze, nessuna schermata nera.
3. Brave: apri `chrome://gpu` e verifica WebGL; in caso di software compositing o EGL fallito, il test non è passato.
4. Audio (se installato): Impostazioni di Sistema > Suono, scegli l'uscita VoodooHDA. Approva l'estensione in Privacy e sicurezza se richiesto.
5. Log da raccogliere:
   - `sudo cat /private/var/tmp/navi44-accelerated-trial/run.log` (cerca `REGISTRY_READY`, `WINDOWSERVER_READY`, `LOGIN_SEEN`, `GPU_BOOT_STABLE`, `STOP`, `FAILSAFE`)
   - `sudo cat "/Library/Application Support/Navi44/accelerated-trial/boot-state.json"` (atteso: `phase: stable`, `observation: desktop-stable-120s`)
   - `sudo cat /private/var/tmp/n48m-translate-state/translate.log` (tail)
   - dalla radice del progetto: `python3 tools/baremetal/observe_navi44_safety.py` (salva `research/hw_dump/navi44-safety-observe-<ts>/observation.json`)

## Rollback

```sh
sudo ./rollback-trial.sh            # ripristina v28 e guard 28
sudo ./rollback-trial.sh --audio    # rimuove anche VoodooHDA
sudo ./rollback-trial.sh --reset-latch   # solo dopo aver esaminato un latch pending/failed
sudo reboot
```

Il rollback non usa GPU né WindowServer: funziona da Terminal, SSH o login locale. Se il latch è `pending` o `failed`, il guard v28 rifiuta l'attivazione al boot successivo (modalità software, senza crash). `--reset-latch` archivia `boot-state.json` e consente di nuovo l'attivazione: usalo solo dopo la revisione.

## Opzioni di emergenza

- Bloccare l'attivazione al boot successivo senza modificare i file: `sudo touch "/Library/Application Support/Navi44/accelerated-trial/disabled"` (il guard si ferma prima di cambiare qualcosa). Rimuovere con `sudo rm` dello stesso file.
- `/private/tmp/n48m-off` è il kill file scritto dal guard in caso di errore. Al boot successivo il guard lo archivia e prosegue, quindi da solo non blocca l'attivazione: usa il marker `disabled`.
- OpenCore picker: F11 all'accensione apre il menu (vedi `research/reports/baremetal_bringup.md`). Il safe boot con Shift non è stato verificato (`research/reports/recovery_install_readonly_20261026.md`). Non fare Reset NVRAM.

## Note

- Payload staged da `bundle29-src/build-29-newxlate/Navi48Metal.bundle` (binary `2c8ff5d0...`, `libn48xlate.dylib` `9a371cc1...`, `libvulkan_radeon.dylib` `f6b2053d...` invariato). 466 voci nel manifest.
- Lo stage precedente (build-29 con traduttore 28) è conservato in `payload.prev-20261031-132252`.
- `install-trial.sh` verifica il payload contro il suo manifest prima di installare: rilancia `./stage.sh` solo se il bundle cambia.
