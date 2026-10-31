# Trial b30: Metal bundle 30 + guard 30 (pipeline solo-vertice, fallback invisibile)

Stato: pacchetto preparato con `./stage.sh`, **non installato**. Il bundle 29 resta attivo finché non esegui `install-trial.sh`. Non testato su hardware.

## Cosa cambia

- **Pipeline solo vertice** (`bundle30-src/src/Navi48Device.m`): quando una pipeline non ha la funzione di frammento, il driver la crea senza fragment shader (niente traduzione, niente modulo del frammento) con colour write mask a 0. Obiettivo: far disegnare alle icone di Finder, App Store e Mappe senza passare dal percorso del frammento che produceva i placeholder. Dettagli e test in `bundle30-src/RESULTS.md`.
- **Placeholder invisibile al posto del magenta**: quando una pipeline ricade nel fallback, il colore non viene scritto e anche depth e stencil sono disattivati, quindi il fallback è trasparente. La pipeline reale sostituisce il placeholder con l'hot-swap (circa 0,8 s).
- **Kill file per il magenta**: `/private/tmp/n48m-magenta`. Se esiste, il fallback torna a disegnare magenta come prima. Il file viene letto una volta per processo, quindi l'effetto si vede dopo il riavvio (o dopo un nuovo login, se i processi grafici ripartono).
- **Bundle 30**: `/Library/GPUBundles/Navi48Metal.bundle`, sostituito con swap atomico (`renamex_np`). Il v29 resta in:
  - `/Library/GPUBundles/Navi48Metal.bundle.v29-backup-<ts>`
  - `/Library/Application Support/Navi44/trial-b30-backup-<ts>/` (bundle v29, guard v29, boot-state prima dell'install, plist)
- **Guard di avvio** (`/Library/Application Support/Navi44/accelerated-trial/accelerated-reboot-trial.sh`): versione 30, profilo `stage30-vonly-v1`. Diff vs guard 29: `GUARD.diff` (solo profilo, versione e l'hash del binario principale).
- **Non toccati**: audio (VoodooHDA resta com'è, nessuna installazione né ricostruzione), `/private/var/tmp/n48m-spv` (resta al suo posto).

Hash:

| file | sha256 |
|---|---|
| `Contents/MacOS/Navi48Metal` | `8fd0c7e3c3cb73090bcc3b3507985abf3785a2f1a94c2d1ce21d9eb8ea085230` |
| `Resources/libn48xlate.dylib` | `9a371cc19ee3180c13cac8277f3af15fd6de3677df2b96f848a81e51211f1a1a` |
| `Resources/libvulkan_radeon.dylib` | `f6b2053d1b26731ff88c1def9ca2375cc7c0a9a34ebc8e7ab7e2533f6c30e155` |

Il payload contiene 466 voci nel manifest (bundle più guard).

## Comandi

```sh
cd /Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/builds/macos-20261031/trial-b30
./stage.sh                   # senza root: verifica bundle, firma, hash, guard, manifest
sudo ./install-trial.sh
sudo reboot
```

`stage.sh` accetta il path del bundle come primo argomento. Default: `bundle30-src/build-30/Navi48Metal.bundle`. Si rifiuta se `CFBundleVersion` non è 30, se il bundle è stato modificato negli ultimi 2 minuti, se `codesign --verify --deep --strict` fallisce, o se un processo che cita `build-30` è in esecuzione.

`install-trial.sh` non accetta opzioni. Si rifiuta se: il payload non corrisponde al manifest; il bundle live non è v29 o i suoi hash non corrispondono alle costanti del guard v29; il boot latch è `pending` o `failed`. Se un passo fallisce, annulla solo ciò che ha cambiato in quella esecuzione e lascia i backup.

## Dopo il riavvio

1. Al login window non accedere per circa 5 minuti: il guard aspetta il translator, il registry e il riavvio di WindowServer. Poi accedi.
2. Verifica desktop accelerato: nessuna schermata nera, nessun magenta visibile (le aree di fallback risultano trasparenti).
3. Icone: Finder, App Store e Mappe devono mostrare le icone reali. Se restano icone vuote o vecchie, pulisci la cache delle icone di macOS e riavvia Dock e Finder:

   ```sh
   sudo rm -rf /Library/Caches/com.apple.iconservices.store
   killall Dock Finder
   ```

   Il percorso esiste su questa macchina (verificato con `ls`). Il comando di pulizia per macOS 26 non è stato verificato in una documentazione ufficiale: questo è quello usato finora.
4. Brave: apri `chrome://gpu` e verifica WebGL; in caso di software compositing o EGL fallito, il test non è passato.
5. Log da raccogliere:
   - `sudo cat /private/var/tmp/navi44-accelerated-trial/run.log` (cerca `REGISTRY_READY`, `WINDOWSERVER_READY`, `LOGIN_SEEN`, `GPU_BOOT_STABLE`, `STOP`, `FAILSAFE`)
   - `sudo cat "/Library/Application Support/Navi44/accelerated-trial/boot-state.json"` (atteso: `phase: stable`, `observation: desktop-stable-120s`)
   - `sudo cat /private/var/tmp/n48m-translate-state/translate.log` (tail)
   - dalla radice del progetto: `python3 tools/baremetal/observe_navi44_safety.py` (salva `research/hw_dump/navi44-safety-observe-<ts>/observation.json`)

## Magenta, per tornare al comportamento precedente

```sh
sudo touch /private/tmp/n48m-magenta     # fallback magenta, dopo il prossimo avvio dei processi grafici
sudo rm /private/tmp/n48m-magenta        # torna al placeholder invisibile
```

## Rollback

```sh
sudo ./rollback-trial.sh                 # ripristina v29 e guard 29
sudo ./rollback-trial.sh --reset-latch   # solo dopo aver esaminato un latch pending/failed
sudo reboot
```

Il rollback non usa GPU né WindowServer: funziona da Terminal, SSH o login locale. Non tocca l'audio. Se il latch è `pending` o `failed`, il guard v29 rifiuta l'attivazione al boot successivo (modalità software, senza crash). `--reset-latch` archivia `boot-state.json` e consente di nuovo l'attivazione: usalo solo dopo la revisione.

## Opzioni di emergenza

- Bloccare l'attivazione al boot successivo senza modificare i file: `sudo touch "/Library/Application Support/Navi44/accelerated-trial/disabled"` (il guard si ferma prima di cambiare qualcosa). Rimuovere con `sudo rm` dello stesso file.
- `/private/tmp/n48m-off` è il kill file scritto dal guard in caso di errore. Al boot successivo il guard lo archivia e prosegue, quindi da solo non blocca l'attivazione: usa il marker `disabled`.
- OpenCore picker: F11 all'accensione apre il menu (vedi `research/reports/baremetal_bringup.md`). Il safe boot con Shift non è stato verificato (`research/reports/recovery_install_readonly_20261026.md`). Non fare Reset NVRAM.

## Note

- Payload staged da `bundle30-src/build-30/Navi48Metal.bundle` (il traduttore `libn48xlate.dylib` e `libvulkan_radeon.dylib` sono identici al bundle 29).
- Non verificato: se RADV accetta una pipeline senza stage di frammento con colour mask a 0 sulla GPU target; il fallback invisibile scrive anche meno depth e stencil (vedi `bundle30-src/RESULTS.md`, sezione Dubbi).
- `install-trial.sh` verifica il payload contro il suo manifest prima di installare: rilancia `./stage.sh` solo se il bundle cambia.
