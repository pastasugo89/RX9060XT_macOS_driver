# Trial metal generico: bundle N -> N+1 (caso attuale: bundle 32)

Stato: pacchetto generico per `stage.sh`, `install-trial.sh` e `rollback-trial.sh`. Il bundle 32 è già in staging (`research/builds/macos-20261031/trial-b32/`, creato con `stage.sh` senza root). **Non installato:** il bundle 31 resta attivo finché non esegui `install-trial.sh`. Non testato su hardware né su Metal/RADV: i test sono offline.

Il pacchetto `../metal-trial-b31/` non è stato modificato e resta per il bundle 31.

## Regole

- **N** è la versione del bundle live: `CFBundleVersion` di `/Library/GPUBundles/Navi48Metal.bundle` (ora 31). Il check `bundle_version` della guard live deve dichiarare la stessa versione.
- Il bundle candidato deve avere `CFBundleVersion` **N+1** (ora 32). Qualsiasi altra versione viene rifiutata.
- Il **profilo** è un argomento obbligatorio di `stage.sh`, nella forma `stage<N+1>-<nome>` (per il bundle 32: `stage32-dualsrc-v1`).
- La guard nuova è una copia della guard live in cui cambiano solo tre righe: `PROFILE=`, il check `bundle_version` (incluso il messaggio) e l'hash di `Contents/MacOS/Navi48Metal`. Le costanti delle due dylib devono già coincidere con quelle del bundle candidato. Il diff è in `GUARD.diff`.

## Comandi

```sh
cd ~/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/tools/baremetal/navi44-desktop/metal-trial
./stage.sh ~/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/builds/macos-20261031/bundle32-src/build-32/Navi48Metal.bundle stage32-dualsrc-v1
sudo ./install-trial.sh
sudo reboot
```

`stage.sh` non richiede root e scrive solo in `research/builds/macos-20261031/trial-b<N+1>/` (cartella ignorata da git): `payload/` (bundle, guard, `manifest.json`) e `GUARD.diff`. Si rifiuta se: non riceve esattamente due argomenti (manca il profilo); il bundle non ha `CFBundleVersion` N+1; il profilo non è `stage<N+1>-…`; un file del bundle è cambiato negli ultimi 2 minuti; `codesign --verify --deep --strict` fallisce; un processo che cita `build-<N+1>` è in esecuzione; la guard live non corrisponde al bundle live; il diff della guard contiene altro oltre alle tre righe.

`install-trial.sh` non accetta opzioni. Ricava N dal bundle live e cerca il payload in `trial-b<N+1>/`. Prima di installare controlla:
- il payload corrisponde al manifest, che registra la versione live (N), la candidata (N+1), il profilo nuovo e quello live; il bundle è N+1 con la guard N+1 e la firma è valida;
- il bundle live è N e la guard live corrisponde ai suoi hash;
- la guard live ha lo stesso sha256 registrato da `stage.sh` (altrimenti rilancia `./stage.sh`);
- il boot latch non è `pending` o `failed`.

Poi fa i backup, solo come copie: il bundle N in `/Library/GPUBundles/Navi48Metal.bundle.vN-backup-<ts>`; in `/Library/Application Support/Navi44/trial-b<N+1>-backup-<ts>/` il bundle N, la guard N, boot-state e il plist. Esegue lo swap atomico del bundle e installa la guard N+1 con rename atomico dopo `bash -n` e il check degli hash. Se un passo fallisce, o se lo interrompi con Ctrl-C (anche TERM o HUP), lo script annulla solo ciò che ha cambiato in quella esecuzione e lascia i backup. Il ripristino decide dallo stato reale su disco (versione del bundle live, copie presenti), non da variabili di flusso, e stampa lo stato finale su stderr. Dopo un install riuscito il bundle 31 sostituito resta in `…/trial-b<N+1>-backup-<ts>/displaced-v31.bundle`; se l'install viene annullato, il bundle 31 torna live e il bundle 32 scartato va in `…/trial-b32-backup-<ts>/failed-b32.bundle`. Non esegue la guard e non riavvia.

Per il bundle 32 i backup sono `Navi48Metal.bundle.v31-backup-<ts>` e `/Library/Application Support/Navi44/trial-b32-backup-<ts>/`.

## Cosa cambia nel bundle 32: dual-source blending

Fonte: `research/builds/macos-20261031/bundle32-src/RESULTS.md`. Base: il bundle 31 installato. Cambiano `src/Navi48Device.m`, `src/n48_spvrefl.h` e la versione.

- **Prima (bundle 31):** ogni fattore `MTLBlendFactorSource1*` veniva rifiutato. Il caso osservato in Brave, pipeline Skia Graphite/Dawn, falliva con l'errore 56, "blend factor/operation not supported (dual-source Source1* factors)".
- **Ora:** se RADV espone `dualSrcBlend` (su questa macchina `maxFragmentDualSrcAttachments = 1`), il dispositivo lo attiva e i quattro fattori Source1 vengono mappati ai fattori Vulkan `SRC1_*`. Il driver scrive `radv: dual-source blending on` alla creazione del dispositivo.
- L'`Index` degli output del frammento viene letto. `Index 1` su `Location 0` abilita la dual-source; `Index` maggiore di 1, o `Index 1` su un'altra Location, vengono rifiutati.
- I fattori Source1 su un attachment diverso dal 0 vengono rifiutati con errore 67. Se l'attachment 0 li usa ma il frammento non scrive l'output `Index 1`, viene scritto un `WARN` e la pipeline non viene rifiutata.
- Traduttore e dylib invariati: `libn48xlate.dylib` e `libvulkan_radeon.dylib` hanno gli stessi hash del bundle 31.

**Non verificato:** non ci sono test a runtime. Il fallimento di Brave non è stato riprodotto. Le pipeline Graphite/Dawn possono fallire per altre ragioni. Le pipeline di fallback magenta con Source1* ora vengono create, con la seconda sorgente indefinita (solo `WARN`).

## Dopo il riavvio

1. Al login window non accedere per circa 5 minuti: la guard aspetta translator, registry e riavvio di WindowServer.
2. Log della guard: `sudo cat /private/var/tmp/navi44-accelerated-trial/run.log` (cerca `REGISTRY_READY`, `WINDOWSERVER_READY`, `LOGIN_SEEN`, `GPU_BOOT_STABLE`, `STOP`, `FAILSAFE`).
3. Stato del latch: `sudo cat "/Library/Application Support/Navi44/accelerated-trial/boot-state.json"`. Atteso: `profile` `stage32-dualsrc-v1`, `phase: stable`, `observation: desktop-stable-120s`.
4. Brave, `chrome://gpu`: WebGL funziona e il processo GPU non è in crash. Poi apri una pagina che usa Skia Graphite o WebGPU (Dawn): il processo GPU non deve crashare.
5. Log del driver: le righe `Navi48Metal: ...` vanno sullo stderr del processo che carica il bundle, cioè il processo GPU di Brave, non in `run.log`. Per vederle, avvia Brave da Terminale con stderr su un file e cerca `Navi48Metal:`. Deve comparire `radv: dual-source blending on`. Non deve più fallire nessuna pipeline con errore 56 (`blend factor/operation not supported`): il messaggio arriva a Brave, non a `run.log`.
6. Icone (regressione dal bundle 31): Finder, App Store e Mappe devono mostrare le icone reali. Se restano vuote o vecchie, pulisci la cache delle icone e riavvia Dock e Finder: `sudo rm -rf /Library/Caches/com.apple.iconservices.store`, poi `killall Dock Finder`. Il comando non è verificato nella documentazione ufficiale di macOS 26: è quello usato finora.
7. `sudo tail /private/var/tmp/n48m-translate-state/translate.log`, e dalla radice del progetto `python3 tools/baremetal/observe_navi44_safety.py`.

Se Brave mostra ancora crash del processo GPU, compositing software o EGL fallito in `chrome://gpu`, il test non è passato: fai il rollback.

## Magenta (ereditato)

```sh
sudo touch /private/tmp/n48m-magenta    # fallback magenta, dopo il prossimo avvio dei processi grafici
sudo rm /private/tmp/n48m-magenta       # torna al placeholder invisibile
```

## Rollback

```sh
cd ~/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/tools/baremetal/navi44-desktop/metal-trial
sudo ./rollback-trial.sh                 # ripristina il bundle 31 e la guard 31 dal backup trial-b32 più recente
sudo ./rollback-trial.sh --backup DIR    # oppure un backup preciso
sudo ./rollback-trial.sh --reset-latch   # solo dopo aver esaminato un latch pending/failed
sudo reboot
```

Il default è il backup più recente `trial-b<N+1>-backup-*`, dove N+1 è la versione del bundle live (32). Il rollback rifiuta un `--backup` che non abbia quel nome o che non contenga il bundle N verificato. Non usa GPU né WindowServer: funziona da Terminal, SSH o login locale, e non tocca l'audio. Il bundle 32 sostituito resta in `/Library/Application Support/Navi44/trial-b32-rollback-<ts>/displaced-current.bundle`. Se il rollback si interrompe (errore o Ctrl-C), il bundle 32 e la guard 32 tornano live come prima e lo stato finale viene stampato.

Se il latch è `pending` o `failed`, la guard 31 rifiuta l'attivazione al boot successivo (modalità software, senza crash). `--reset-latch` archivia `boot-state.json` e la consente: usalo solo dopo la revisione.

## Opzioni di emergenza

- Bloccare l'attivazione al boot successivo senza toccare i file: `sudo touch "/Library/Application Support/Navi44/accelerated-trial/disabled"`, da rimuovere con `sudo rm` dello stesso file.
- `/private/tmp/n48m-off` è il kill file scritto dalla guard in caso di errore. Al boot successivo viene archiviato e il boot prosegue, quindi da solo non blocca l'attivazione: usa il marker `disabled`.
- OpenCore picker: F11 all'accensione (vedi `research/reports/baremetal_bringup.md`). Il safe boot con Shift non è verificato. Non fare Reset NVRAM.

## Test offline

```sh
/usr/bin/python3 -I test-guard-edit.py
```

Non usa root né GPU e non scrive in `/Library`: legge la guard live e le dylib live (sola lettura) e lavora su copie in una cartella temporanea. Controlla:
- N=31→32 con una copia della guard live: il diff è esattamente le tre righe, la guard passa `bash -n` e `guard-check`, il manifest è corretto e una guard manomessa viene rifiutata;
- un caso sintetico N=9→10 (cambio di cifre);
- i rifiuti di `edit-guard`: N+1 sbagliato, profilo mancante o di un'altra versione, dylib diversa, stesso binario, versione o profilo duplicati;
- i rifiuti di `stage.sh` che avvengono prima di scrivere nulla: nessun argomento, profilo mancante, bundle con versione N o N+2, percorso inesistente.

Installazione e rollback non sono stati eseguiti sul sistema. I percorsi di annullamento (errore, ERR, Ctrl-C, TERM, HUP) sono stati verificati in un sandbox temporaneo: il codice reale degli script viene estratto tra i marcatori `helpers` e `traps`, senza root e senza scrivere in `/Library`. Il cambio di ownership (`chown root:wheel`) è sostituito da un finto nel sandbox, perché fuori da root non è verificabile.

## Note

- Il bundle successivo (33) segue la stessa procedura: `./stage.sh <bundle33> stage33-<nome>`, poi `sudo ./install-trial.sh`. Il backup sarà `trial-b33-backup-*`.
- Se il bundle live cambia dopo lo stage, `install-trial.sh` si ferma: rilancia `./stage.sh`.
