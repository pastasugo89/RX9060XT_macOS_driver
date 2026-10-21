# Navi48Metal.bundle: build, installazione e file di controllo

> **Nota di provenienza.** Questo file è stato ricostruito nel progetto del Navi 44 il 21/10/2026, perché il
> `INSTALL.md` originale non era presente nel repository (né nella storia git né nello snapshot upstream di Cobalt64).
> Il contenuto deriva da `build.sh`, `Info.plist` (CFBundleVersion 20, 0.1.1), dagli header dei test
> `test-bNN-plant.sh` (descrizione di ogni build), dai sorgenti `Navi48Device.m`, `n48_*.h` e dai commenti di
> `cobalt64/src/navi48-bringup` (boot-arg e file di controllo), e dal piano `research/reports/metal_deploy_plan.md`
> sez. 4.3-4.4. Non è una guida di Cobalt64. Dove il repository non documenta un fatto, il file lo dichiara.

## 1. Versione corrente

Build **20** (`CFBundleVersion` 20, `CFBundleShortVersionString` 0.1.1, identificatore `com.navi48.metal`).
Profilo ASIC di default: `navi44` (RX 9060 XT, PCI 1002:7590). Il bundle va costruito con lo stesso profilo del
kext (`make ASIC=navi44`) e del RADV incluso (patch 0010, default Navi 44).

## 2. Storia dei build

| Build | Contenuto (da header `test-bNN-plant.sh`) |
|---|---|
| 9 | Crash study, voci 1 e 2: `n48_cienv.h`, `n48_texdesc.h` |
| 10 | Depth/stencil e MSAA: `n48_depth.h`, `n48_texdesc.h` (2DMS) |
| Build 11 (CFBundleVersion 11, M6 Stage 1a) | Quale display possiede una superficie IOSurface: tabella `Navi48,M6Surf` del nub Metal, guardia di encode e decisione a completamento (`n48_m6route.h`, `test-m6route.c`) |
| Build 12 (CFBundleVersion 12) | Nel repository non esiste uno script `test-b12-plant.sh`: il contenuto di questo build non è documentato qui |
| Build 13 (CFBundleVersion 13, M6 Stage 1b) | Scanout del monitor B dal bundle, istanza 2 (`n48_m6x.h`, `n48_dispflip.h`) |
| 14 | Traduzione shader in processo (`libn48xlate.dylib`, `n48_xlate.h`), sezione 1 della nota NATIVE-S8-INPROC |
| Build 15 (CFBundleVersion 15, M6 Stage 2) | Il monitor A come terzo display composto dalla GPU, istanza 1; array di stato per istanza `[DP, monitor A, monitor B]`. File di disattivazione `n48m-noflip1` e `n48m-noflip2` (sez. 5) |
| 16 | Fix di app, round 1: ledger degli import, fallback mai nil, cache di import, politica use-count (`n48_ledger.h`, `n48_impcache.h`) |
| 17 | Fix di revisione R-B1 (gate di dimensione anche sul piano del DP) e R-S2 (retry a quattro parole del monitor B) |
| 18 | Fix di app, round 2: query di occlusione (P2), funzioni collegate nella traduzione (P3), census dei selettori. La misura di semantica di occlusione (`test-occlusion-semantics.m`) è stata eseguita su un Mac host; il suo output non è nel repository |
| 19 | Menu mancanti: `RG16Uint` (voce di tabella, clear intero, maschera di fallback, file di disattivazione) |
| 20 | Correzione dello scroll HDMI (F1-F4: superfici di scanout note, supersede per slot, re-copy, linea di 10 s per istanza). Build corrente |

### 2.1 Comportamento richiesto dal codice (build 11-15)

- **Tabella M6** (build 11): con `navi48-m6=1` il kernel pubblica `Navi48,M6Surf` nel nub Metal e il bundle presenta
  solo le superfici che il kernel associa all'istanza 0. Il bit di risposta `N48N_SCANQ_M6` (1u << 5) segnala che il
  latch è attivo. I bit `N48N_SCANQ_M6FLIP` (1u << 6, `navi48-m6flip`) e `N48N_SCANQ_M6FLIP1` (1u << 7,
  `navi48-m6flip1`) segnalano le istanze 2 e 1 (`Navi48NativeABI.h`).
- **SKIP e DROP** (`n48df_skip_content`, `Navi48Device.m`): un frame che non sarà presentato per decisione della
  tabella viene contato, registrato (primi 12) e lo slot viene rilasciato senza aggiornare `last_seq`.
- **KEEP-ALIVE** (build 13-15, `n48_m6x.h`): il pipe del monitor B va in idle quando nulla cambia, e il watchdog di
  idle del kernel (5 s) conta come attività una chiamata `Status2`. Il tick di 1 s **deve** chiamare `Status2` mentre
  l'istanza 2 è attiva; senza, un monitor B fermo torna alle barre dopo 5 s.

## 3. Build

Dal repository, nel guest macOS x86_64 (Command Line Tools sufficienti per clang; per la traduzione serve
`libn48xlate.dylib` x86_64, cioè il crate `n48xlate` di `cobalt64/third-party/metal2vulkan-n48`):

```sh
cd tools/native/navi48metal
ASIC=navi44 N48_RADV_LIB=<libvulkan_radeon.dylib x86_64> N48_XLATE_LIB=<libn48xlate.dylib x86_64> \
  N48_VK_INC=-I<include Vulkan di Mesa> N48_SPVCACHE_DIR=<dir .spv/.meta.json> ./build.sh
```

- `N48_SPVCACHE_DIR`: coppie `*.spv` e `*.meta.json`. La cache parziale è accettata; una cache **vuota** è rifiutata
  salvo `N48_ALLOW_EMPTY_SPVCACHE=1` (il bundle mostra allora solo il fallback magenta, vedi sez. 4).
- `N48_LAZY=0` e `N48_9D=0` producono le varianti di test del bundle; il default è quello distribuito.
- Output: `build/Navi48Metal.bundle.tar` (creato con `bsdtar --no-xattrs`). La variante `arm64` del sorgente è solo
  un controllo di compilazione e non va installata (`build/sanity/`).

## 4. Installazione del bundle (nel guest, con sudo)

Il bundle non richiede riavvio. Il percorso è `/Library/GPUBundles/Navi48Metal.bundle`.

```sh
sudo mkdir -p /Library/GPUBundles
[ -d /Library/GPUBundles/Navi48Metal.bundle ] && sudo mv /Library/GPUBundles/Navi48Metal.bundle \
    /Library/GPUBundles/Navi48Metal.bundle.prev-$(date +%Y%m%d-%H%M%S)
sudo tar --no-xattrs -xf build/Navi48Metal.bundle.tar -C /Library/GPUBundles
sudo chown -R root:wheel /Library/GPUBundles/Navi48Metal.bundle
codesign --verify --strict -v /Library/GPUBundles/Navi48Metal.bundle
```

Il bundle rifiuta i processi root che non sono strumenti con `N48M_ALLOW=1` (vedi sez. 6).

## 5. File di controllo (presenza del file = funzione disattivata)

| File | Effetto | Definito in |
|---|---|---|
| `/private/tmp/n48m-off` | disattivazione generale (L1): il processo rifiuta il device; per WindowServer è il kill switch | `n48_gate.h`, `Navi48Device.m` |
| `/private/tmp/n48m-starts` | contatore di avvii di WindowServer (una riga per avvio): tre avvii in 300 s fanno rifiutare (L2) | `Navi48Device.m` |
| `/private/tmp/n48m-headless-no` | `isHeadless` = NO (il default è YES), letto una volta per processo | `Navi48Device.m` |
| `/private/tmp/n48m-noflip1` | disattiva lo scanout dell'istanza 1 (monitor A, build 15) | `n48_m6x.h`, `navi48_scanx_flow.h` |
| `/private/tmp/n48m-noflip2` | disattiva lo scanout dell'istanza 2 (monitor B, build 15) | `n48_m6x.h`, `navi48_scanx_flow.h` |
| `/private/tmp/n48m-noinproc` | disattiva la traduzione in processo (`libn48xlate`) | `n48_xlate.h`, `Navi48Device.m` |
| `/private/tmp/n48m-noimpcache` | disattiva la cache di import (build 16) | `n48_impcache.h` |
| `/private/tmp/n48m-noioalias` | disattiva le azioni di alias per command buffer (P1, build 16), anche nelle applicazioni | `n48_ioalias.h`, `Navi48Device.m` |
| `/private/tmp/n48m-nousecount` | nessun conteggio d'uso: comportamento identico ad Apple, usato per la diagnosi (build 16) | `n48_ledger.h`, `Navi48Device.m` |

I file sono letti dal bundle a ogni inizializzazione: la rimozione ha effetto al prossimo avvio del processo.

## 6. Variabili di test (solo strumenti root con `N48M_ALLOW=1`)

`N48M_ALLOW=1` apre il device a un processo root. Gli hook `N48M_TEST_*` sono ignorati senza `N48M_ALLOW=1`.
Esempi definiti in `Navi48Device.m`: `N48M_TEST_IGNORE_KILL=1` (ignora `n48m-off`, mai per WindowServer),
`N48M_TEST_FALLBACK_AS_WS=1` (fallback come in WindowServer, usato da `mtlprobe hotswap`),
`N48M_TEST_HIDE_BUNDLE_SPV=1`, `N48M_TEST_SIDE_DIR=<dir>`, `N48M_TEST_DISPFLIP=1`,
`N48M_TEST_OPEN_REFUSE=<n>`, `N48M_TEST_IMPORT_FAIL_EVERY=<n>`.

## 7. Boot-arg che abilitano il bundle (letti dal kext)

Le boot-arg sono nel kext (`cobalt64/src/navi48-bringup`); il bundle non le legge. Valori e siti di lettura:

| Boot-arg | Ruolo | Sito di lettura |
|---|---|---|
| `navi48bringup=1` | probe del kext attivo (senza, inerte) | `Navi48Bringup.cpp` (`probe`) |
| `navi48-stage=N` | stadio di bring-up | `Navi48Bringup.cpp` |
| `navi48-native=1` | gate S1b; rifiutato se sono armate le boot-arg in conflitto (`native_s1b_pure.h`) | `Navi48Bringup.cpp` (`bootArgU32`) |
| `navi48-metal=1` | pubblica il nub Metal (`Navi48MetalNub`) | `Navi48MetalNub.cpp` |
| `navi48-metal-fact=<mask>` | classi aux opzionali | `Navi48MetalNub.cpp` |
| `navi48-metal-ws=1` | ammette WindowServer (uid 88) al client nativo | `Navi48NativeClient.cpp` |
| `navi48-metal-disp=1` | pipe di display (latch) | `native_disp.cpp` |
| `navi48-m6=1`, `navi48-m6flip=1`, `navi48-m6flip1=1` | latch M6 (build 11, 13, 15) | `native_disp.cpp` |
| `navi48-fb2=1` | framebuffer del monitor B | `Navi48DisplayNub.cpp` |
| `navi48-aux=0` | kill switch del kext aux `Navi48Accel` (assente = attivo) | `Navi48Accel.cpp` |

Set di prova documentato nel piano: `navi48bringup=1 navi48-stage=17 navi48-native=1 navi48-metal=1
navi48-metal-disp=1 navi48-metal-ws=1` (vedi `metal_deploy_plan.md` sez. 8).

## 8. Daemon di traduzione `com.navi48.translate`

Il daemon (utente `nobody`) traduce gli AIR scaricati dal bundle in `.spv` e `.meta.json` in
`/private/var/tmp/n48m-spv`, che il bundle osserva per l'hot-swap. Il daemon salta le chiavi già presenti in
`Resources/spvcache` del bundle. File: `cobalt64/tools/native/autotranslate/`.

1. `/usr/local/navi48/` (root:wheel 755): `pc-translate.sh`, `pc-translate.py`, `n48-llvm-dis`, `overrides.txt`,
   `n48-translate.sb`, `metal2vulkan` (x86_64), `spirv-val` (x86_64, opzionale; senza di esso è usato lo stub
   `n48-spirv-val-stub`, che dichiara valido tutto).
2. **Prima** del bootstrap: `sudo mkdir -p /private/var/tmp/n48m-translate-state` (il plist ha `StandardOutPath` in
   quella directory).
3. `sudo cp com.navi48.translate.plist /Library/LaunchDaemons/`
4. `sudo launchctl bootstrap system /Library/LaunchDaemons/com.navi48.translate.plist`
5. Verifica: `launchctl print system/com.navi48.translate`; `tail /private/var/tmp/n48m-translate-state/translate.log`.
6. Disattivazione: `sudo launchctl bootout system/com.navi48.translate`.

Variabili di test del daemon (solo prove): `N48_SRC`, `N48_OUT`, `N48_STATE`, `N48_BUNDLE`, `N48_HERE`,
`N48_ONCE=1` (una passata), `N48_NO_SANDBOX=1`, `N48_SKIP_OWNER=1`, `N48_POLL`.

## 9. Test host

Eseguibili sull'host con clang, senza GPU; leggono il repository e il `Info.plist`:

```sh
cd tools/native/navi48metal
cc -O1 -D_GNU_SOURCE -Wall -Wextra -Werror -o /tmp/test-m6route test-m6route.c && /tmp/test-m6route .
cc -O1 -D_GNU_SOURCE -Wall -Wextra -Werror -o /tmp/test-m6x test-m6x.c && /tmp/test-m6x .
```

Test di planted-break: `test-bNN-plant.sh` (uno per build, `test-b11` … `test-b20`). Ogni script copia i file
reali in una scratch tree, applica una rottura e pretende che almeno un test fallisca.

## 10. Disinstallazione

```sh
sudo launchctl bootout system/com.navi48.translate 2>/dev/null; sudo rm -f /Library/LaunchDaemons/com.navi48.translate.plist
sudo rm -rf /Library/GPUBundles/Navi48Metal.bundle
```

Il bundle precedente, se spostato con il suffisso `.prev-`, si ripristina rinominandolo.

## 11. Licenze

`libn48xlate.dylib` e il fork metal2vulkan (`cobalt64/third-party/metal2vulkan-n48`) sono LGPL-3.0-or-later e
restano separati dal codice MIT del bundle (vedi `NOTICE`). La spvcache contiene blob derivati da shader Apple:
non va distribuita fuori dal progetto.
