# Piano di deploy Metal (Navi48Metal) nella VM di test — 20 ottobre 2026

Stato: piano scritto, **nulla è stato installato o eseguito nella VM** (un altro agente la usa per un boot hardware).
Lavoro svolto sull'host Linux: packaging di `build.sh`, generazione locale della spvcache, piano.

## 0. Esito in breve

- `build.sh` si fermava sul glob `spvcache/*.spv` quando la cartella non esiste (zsh: `no matches found`). Ora la
  cartella si legge da `N48_SPVCACHE_DIR`, il glob è null-safe e una cache **vuota** è rifiutata salvo
  `N48_ALLOW_EMPTY_SPVCACHE=1`. Una cache **parziale** è sempre accettata.
- Dal codice risulta che il bundle funziona con cache vuota o parziale: WindowServer riceve la pipeline di fallback
  magenta, il daemon di traduzione produce gli SPIR-V dagli AIR scaricati e il bundle li sostituisce a caldo.
- Generata in locale la spvcache da SkyLight e CoreDisplay: **35 blob AIR carvati, 35 tradotti, 0 falliti, 35/35
  `spirv-val --target-env vulkan1.2` PASS**. QuartzCore e CoreImage non sono estratti in `research/macos/25G83`:
  zero voci per quelle librerie.
- Le chiavi (sha256 dell'AIR) non si possono confrontare con il census del PC (`~/navi48-native/census2` non è su
  questo host). Il confronto va fatto nella VM con i dump reali di WindowServer (sez. 4.5, T5).

## 1. Cosa richiede il packaging e cosa fa il bundle su un miss

### 1.1 Packaging (build.sh)

- `build.sh` copia in `Contents/Resources/spvcache/` i file `*.spv` e `*.meta.json` trovati in `spvcache/`
  accanto allo script. Non genera nulla; la cache è un input.
- Prima della modifica: cartella assente o vuota = errore zsh (`no matches found`) con `set -e`, quindi nessun bundle.
- Il bundle non controlla quante voci ci sono né che siano complete; ogni voce è una cache per chiave (sha256 del
  bitcode della funzione), quindi una voce mancante è semplicemente un miss.

### 1.2 Runtime su miss

Riferimenti: `cobalt64/tools/native/navi48metal/Navi48Device.m` (numeri di riga del file al 20/10/2026).

| Processo | Miss in `spvcache` | Riferimento |
|---|---|---|
| WindowServer | fallback magenta per il render, no-op per il compute; AIR scaricato in `/private/tmp/n48m/<uid>/<sha>.air`; hot-swap quando compaiono `.spv`/`.meta.json` | `n48_fallback_ok` r.162 (`n48g_fallback_ok` in `n48_gate.h` r.145: WS sempre ammesso); fallback render r.3905-3921; compute r.6077-6082; dump r.2018-2027; hot-swap r.3685-3740 |
| App ammessa | traduzione in processo (`libn48xlate.dylib` + bitcode reader di sistema), poi attesa fino a 3 s del daemon, poi fallback | r.3297-3305, r.3755-3785 (C1, solo app) |
| root tool (`N48M_ALLOW=1`) | come l'app, con gli hook `N48M_TEST_*` | r.131-133 |

Il daemon `com.navi48.translate` (utente `nobody`) processa gli AIR scaricati: `pc-translate.sh` → `pc-translate.py`
(`n48-llvm-dis`, `metal2vulkan --emit-meta`, patch formato storage image) e installa prima il `.meta.json`, poi il
`.spv` in `/private/var/tmp/n48m-spv`, che il bundle osserva. Il daemon salta le chiavi già presenti in
`Resources/spvcache` del bundle (`pc-translate.sh`, funzione `scan_once`).

### 1.3 Conseguenza

- Cache vuota: WindowServer parte, mostra magenta dove usa shader mancanti, il desktop resta sulla strada del
  fallback finché il daemon non traduce. Senza daemon il magenta resta per sempre (nessun hot-swap).
- Cache parziale: stesso comportamento per le sole chiavi mancanti; le presenti sono usate subito.
- Il compute di WindowServer con miss è un no-op: un effetto mancante, non un crash (commento del codice r.6078-6079).
- Quindi la spvcache è un acceleratore, non un prerequisito: il daemon genera ciò che serve dai dump.

## 2. Modifiche fatte

| File | Modifica |
|---|---|
| `cobalt64/tools/native/navi48metal/build.sh` | intestazione: 2 variabili documentate; sezione spvcache riscritta: `N48_SPVCACHE_DIR` (default `spvcache/` accanto allo script), glob null-safe `(N)`, rifiuto della cache vuota salvo `N48_ALLOW_EMPTY_SPVCACHE=1`, avviso se `.spv` e `.meta.json` non coincidono. `zsh -n` OK. |
| `cobalt64/.gitignore` | `/tools/native/navi48metal/spvcache/` (la cache del bundle non si versiona) |
| `.gitignore` | `/research/ext/spvcache-25G83/` (output locale da shader Apple) |

Test della sola logica di packaging (zsh, copia della sezione di `build.sh`; la parte clang/codesign richiede macOS e
non è stata eseguita):

| Caso | Esito |
|---|---|
| cartella assente, nessuna opzione | exit 1, messaggio con le due opzioni |
| cartella vuota, nessuna opzione | exit 1 |
| cartella vuota, `N48_ALLOW_EMPTY_SPVCACHE=1` | exit 0, 0 file copiati |
| 2 `.spv` + 1 `.meta.json` | exit 0, avviso di disallineamento, 3 file copiati |
| output reale 25G83 (35 + 35) | exit 0, 70 file copiati |

## 3. Spvcache 25G83 generata in locale

Output fuori da git: `research/ext/spvcache-25G83/` (ignorato). Contenuto: `air/` (blob AIR carvati, 572 KiB),
`spvcache/` (35 `.spv` + 35 `.meta.json`, 376 KiB), `MANIFEST.tsv`, `translate.log`, `translate.log.rc`, `tools/carve_air.py`.
Gli AIR e gli SPIR-V derivano da shader Apple: non vanno versionati né ridistribuiti.

### 3.1 Strumenti

| Strumento | Versione / origine | Note |
|---|---|---|
| metal2vulkan | upstream `steelbrain/metal2vulkan` @ `43c46ac8…` + `cobalt64/third-party/metal2vulkan-n48/patches/0001…patch` (`git apply --check` pulito), build `cargo build --release --features serde --bin metal2vulkan` | Revisione indicata dal NOTICE e usata da `pc-translate.py` (`--local`, `METAL2VULKAN_LLVM_DIS`). La copia in `research/refs/metal2vulkan` è la 0.2 riscritta (`--profile`, niente `--local`): **non** è quella della pipeline. |
| rustc / cargo | rustup 1.99.1, profilo minimal, in `~/.cargo` (spazio utente, nessun sudo) | NOTICE: Rust >= 1.87 |
| llvm-dis stand-in | `cobalt64/tools/native/autotranslate/n48-llvm-dis` invariato: su Linux usa `/usr/bin/clang` (clang 23.1.3) | Legge AIR (`air64_v28`) e ripristina datalayout/triple |
| validatore | `/usr/bin/spirv-val` (SPIRV-Tools v2026.4) passato a `--validator` | Reale, non lo stub |
| carving AIR | `tools/carve_air.py` (stessa regola di `scripts/mtlb-extract` upstream: magic `0x0b17c0de`, offset byte, dimensione da `BitcodeOffset+BitcodeSize`); limite 4 MiB come `MAXBYTES` di `pc-translate.py` (l'upstream usa 512 KiB) | Nessun nome di funzione dal carver: i nomi nel manifest vengono dal `entry_point` del meta |
| driver | `cobalt64/tools/native/autotranslate/pc-translate.py` invariato, `TMPDIR` nella scratchpad | `--timeout 20`, `--max-bytes 4194304` come nel daemon |

### 3.2 Procedura

```sh
W=research/ext/spvcache-25G83; R=research/macos/25G83/root/System
python3 -I $W/tools/carve_air.py $R/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/SkyLightShaders.air64.metallib $W/air/SkyLight SkyLight
python3 -I $W/tools/carve_air.py $R/Frameworks/CoreDisplay.framework/Versions/A/Resources/default.metallib $W/air/CoreDisplay CoreDisplay
cd cobalt64/tools/native/autotranslate
for f in $W/air/*/*.air; do
  python3 -I pc-translate.py "$f" --out $W/spvcache --m2v <metal2vulkan> --overrides overrides.txt \
     --validator /usr/bin/spirv-val --timeout 20 --max-bytes 4194304
done
```

### 3.3 Esito

- Blob AIR carvati: **35** unici (SkyLight 31, CoreDisplay 4). Scartati per dimensione (>4 MiB): 0. Header malformati: 0.
  Ogni occorrenza del magic `0x0b17c0de` coincide con un `BC C0DE` grezzo (SkyLight 31 e 31, CoreDisplay 4 e 4),
  quindi non ci sono AIR senza wrapper persi.
- Tradotti da `pc-translate.py`: **OK 35, FAIL 0** (`translate.log`, 35 righe `OK`).
- `spirv-val --target-env vulkan1.2` sui 35 `.spv`: **PASS 35, FAIL 0**.
- Stage: 8 Vertex, 27 Fragment, 0 kernel di compute. Storage image patch applicata: 0.
- Dimensioni `.spv`: da 380 a 19 476 byte, totale 138 120 byte (135 KiB); la cartella `spvcache/` con i meta pesa 376 KiB.

### 3.4 Limiti

1. **QuartzCore e CoreImage: nessun `default.metallib` estratto** (`research/macos/25G83` non contiene quei framework).
   Le chiavi del census per quelle librerie (parte delle 275 funzioni OK sul PC) mancano. Il daemon le tradurrà
   dai dump di WindowServer, quindi non è bloccante per il desktop, ma la cache è parziale.
2. **Chiavi non verificate**: l'sha256 del blob carvato è uguale a `-[MTLFunction bitcodeData]` solo se il carving
   coincide con il bitcode che Metal restituisce. Il census (`results.tsv`) non è su questo host. Verifica in VM: T5.
3. **Stesso traduttore, host diverso**: la traduzione è su Linux. Un `.spv` diverso dal Mac per lo stesso AIR non
   sarebbe un errore del bundle, ma va misurato (T6).
4. **Nessun compute**: le 2 librerie non hanno kernel; per il compute di WindowServer resta il no-op.
5. Il carver non legge i nomi delle funzioni: `--local` (`overrides.txt`: `sum_rgba_*`, `write_tex`) non si applica
   a questi blob. Non sono funzioni Apple, quindi nessun effetto qui.

## 4. Piano di deploy nella VM (da eseguire, non eseguito)

Presupposti: VM `macos-build` (Tahoe 25G83, MacPro7,1) con la RX 9060 XT passthrough, quando l'altro agente la
rilascia. I passi di hardware seguono `research/reports/first_gpu_test_plan.md` (discovery stage 1 prima di tutto).

### 4.1 Gate da soddisfare prima di installare il bundle

| # | Gate | Stato al 20/10 | Fonte |
|---|---|---|---|
| G1 | kext bring-up Navi44 caricato, stage 17 raggiunto | 🟨 (Fase 2.1: 13 boot, fault GCVM aperti) | FASI 2.1 |
| G2 | S1b **POSITIVE PASS** (basta questo per pubblicare il nub; il FAIL del fault leg è già noto) | positivo PASS, fault REFUSED | `radv_icd_smoke.md`; `native_metal_pure.h:43` |
| G3 | aux `Navi48Accel` gate A/B/C MATCH | ✅ (5.2) ma `INSTALL.md` assente | FASI 5.2 |
| G4 | RADV con patch 0001-0010, 1002:7590 | 🟨 (ICD enumerato; nessun submit) | `radv_icd_smoke.md` |
| G5 | `Navi48Metal.bundle` compilato (x86_64) con cache valida o vuota con opt-in | parziale: questo lavoro | sez. 2-3 |
| G6 | `libn48xlate.dylib` x86_64 | ✅ 20/10 (ABI 2) | `macos_build_validation.md` |

### 4.2 Artefatti da costruire sul guest (macOS, CLT)

1. metal2vulkan @43c46ac + patch 0001, `--features serde`, **x86_64 macOS** (build sul guest: il Linux non serve qui).
2. `spirv-val` x86_64 macOS (SPIRV-Tools) accanto a `pc-translate.py`, così il daemon usa il validatore reale
   invece dello stub (`pc-translate.sh` r.30: `if [ -x "$HERE/spirv-val" ]`).
3. `n48xlate`: `cargo build --release -p n48xlate --target x86_64-apple-darwin` (NOTICE).
4. Spvcache: copiare `research/ext/spvcache-25G83/spvcache/` nel guest (dati, non codice); oppure vuota con
   `N48_ALLOW_EMPTY_SPVCACHE=1`.
5. Bundle: `N48_SPVCACHE_DIR=<dir> ASIC=navi44 N48_RADV_LIB=<dylib> N48_XLATE_LIB=<dylib> build.sh` →
   `build/Navi48Metal.bundle.tar`. `N48_VK_INC` punta agli header Vulkan di Mesa.
6. Kext aux `Navi48Accel` (`make MKSDK=<SDK>`): **prima** va ripristinato `INSTALL.md` (blocco noto 5.2), altrimenti
   non c'è un riferimento per consenso e file.
7. Test host: `tools/native/mtlprobe/build.sh` (x86_64 + arm64 + universal).

### 4.3 Installazione (ordine)

Tutti i passi con `sudo` nel guest; nulla nel volume di sistema sigillato.

1. Verificare SIP e stato kext: `csrutil status`; `kmutil showloaded --list-only | grep -i navi48`. Solo lettura.
2. Kext bring-up: non installarlo finché G1 non è chiuso; nella VM il percorso è quello già usato (`navi48bringup=1`).
3. Kext aux `Navi48Accel-0.0.7.kext` in `/Library/Extensions/`: `kmutil libraries -p <dir> -a x86_64`, poi **una**
   `kmutil load`, consenso utente in Impostazioni (una volta per binario: il consenso sta nel database di
   `kernelmanagerd`, non in un bit di `csr-active-config`, misurato su PC: `esp-kext.sh` r.6-14).
4. Bundle: `sudo mkdir -p /Library/GPUBundles` e copia di `Navi48Metal.bundle` (estratto con `tar --no-xattrs`), vecchio
   bundle spostato da parte. Nessun riavvio per il bundle.
5. Daemon di traduzione (solo se si vuole il desktop oltre il magenta):
   - `/usr/local/navi48/` (root:wheel 755): `pc-translate.sh`, `pc-translate.py`, `n48-llvm-dis`, `overrides.txt`,
     `n48-translate.sb`, `metal2vulkan` (x86_64), `spirv-val` (opzionale), `n48-spirv-val-stub`.
   - Creare `/private/var/tmp/n48m-translate-state` **prima** del `bootstrap`: il plist ha `StandardOutPath` su
     quella directory e launchd la apre prima di lanciare lo script, che la crea solo dopo (da verificare nella VM).
   - `cp com.navi48.translate.plist /Library/LaunchDaemons/`; `sudo launchctl bootstrap system /Library/LaunchDaemons/com.navi48.translate.plist`.
   - Verifica: `launchctl print system/com.navi48.translate`, `tail /private/var/tmp/n48m-translate-state/translate.log`.
6. Boot-args (sezione 4.4), poi riavvio.
7. Kill switch e flag: `/private/tmp/n48m-off` **assente**; `/private/tmp/n48m-headless-no` assente nella prima prova
   (WindowServer headless, nessun display: vedi blocchi, sez. 5).

### 4.4 Boot-arg

| Boot-arg | Ruolo | Fonte |
|---|---|---|
| `navi48bringup=1` | il probe del kext è attivo (senza, il kext è inerte) | `esp-kext.sh` r.26 |
| `navi48-stage=17` | sale fino allo stage dopo il quale gira il self-test nativo S1b | `Navi48Bringup.cpp:6906` (commento) |
| `navi48-native=1` | gate S1b (conflitti: `native_s1b_pure.h:141`) | `Navi48Bringup.cpp:6889` |
| `navi48-metal=1` | pubblica `Navi48MetalNub` (solo con S1b positivo) | `Navi48MetalNub.cpp:214` |
| `navi48-metal-ws=1` | apre il client nativo a uid 88 (WindowServer) | `Navi48NativeClient.cpp:64` |
| `navi48-metal-fact=<mask>` | classi aux opzionali (default 0) | `native_metal_pure.h:137` |
| `navi48-metal-disp=1` | pipe di display (serve per il video; dipende da 4.2 GOP, ancora ⬜) | `native_disp.cpp:572` |

Set usato nelle simulazioni del PC (`tools/pc/m6-stage2-sim/rbin/sysctl`, r.4):
`navi48-stage=17 navi48-native=1 navi48-metal=1 navi48-metal-disp=1 navi48-metal-ws=1 navi48-dmubcmd=1 navi48-disp2=1 navi48-fb2=1 navi48-m6=1 navi48-m6flip=1 navi48-m6flip1=1 npci=0x2000`.
Per la prima prova headless: le ultime 4 ramificazioni display (`metal-disp`, `dmubcmd`, `disp2`, `fb2`, `m6flip*`) **non** servono e
non vanno attivate: sono i rami di display che toccano `navi48_disp2.h` e `navi48_dmubcmd.h`, fuori dal perimetro di questo lavoro.

Impostazione: nella VM `sudo nvram boot-args="..."` (da verificare che la VM accetti la scrittura senza disattivare
SIP; altrimenti via config OpenCore dell'EFI della VM). Gli script PC `esp-config.sh` non si usano (vedi 4.6).

### 4.5 Scala di test (Cobalt64, in ordine)

Gli eseguibili vanno lanciati come root con `N48M_ALLOW=1` (il bundle rifiuta i root non ammessi, r.268-269).

| Test | Comando | Esito atteso | Stop se |
|---|---|---|---|
| T0 device | `sudo N48M_ALLOW=1 mtlprobe list` | un device, nome "AMD Radeon RX 9060 XT" | nessun device, o declino |
| T1 census | `sudo N48M_ALLOW=1 N48M_CENSUS=1 mtlprobe list` | riga `census: N selector(s) missing`; confronto con `test-census.m` (28 check) | errori di load del bundle |
| T2 hot-swap (oracolo) | `sudo N48M_ALLOW=1 mtlprobe hotswap --spv-src <dir> --side-dir <tmp>` | magenta, poi quad esatto dopo lo swap; in-flight resta fallback | nessun swap entro `--wait` |

Nota T2: `hotswap` usa gli shader quad del probe, non quelli della spvcache: i suoi `.spv` si ottengono dal probe stesso (`mtlprobe dumpair` sul guest, poi traduzione). La spvcache qui serve a T5/T7.
| T3 triangolo/quad | `mtlprobe triangle out.png`, `mtlprobe quad` | immagine di riferimento | pipeline NIL |
| T4 compute | `mtlprobe compute`, `qccompute` | risultato CPU di riferimento | `COMPUTE FALLBACK` inatteso |
| T5 WindowServer, chiavi | avvio di WindowServer con il bundle; poi `ls /private/tmp/n48m/*/` | i nomi dei `.air` dumpati: confrontare con `MANIFEST.tsv`; intersezione = prova che le chiavi coincidono | nessun dump: il bundle non ha preso il ramo WS |
| T6 riproducibilità | sul guest: `pc-translate.py` sui 35 AIR in `air/`, `cmp` dei `.spv` con quelli di Linux | byte-identici (stesso traduttore) | differenze: documentare, non è un errore del bundle |
| T7 WindowServer headless | `sudo log stream --predicate 'process == "WindowServer"'` e `log show` su `Navi48Metal` | WS in vita, nessun crash; righe `FALLBACK`, `HOT-SWAP`, `spvcache hit` | crash, `DECLINED` inattesa |

Cache vuota vs piena: stesso test T7 con cache vuota (`N48_ALLOW_EMPTY_SPVCACHE=1`) e con quella piena. Il primo mostra
il percorso magenta→hot-swap; il secondo mostra i hit.

### 4.6 Adattamenti rispetto agli script PC

| Script PC | Assunzione PC | Nella VM |
|---|---|---|
| `m6-stage1*-deploy.sh`, `m6-stage2-run.sh` | `ssh navi48` (`N48_HOST`), `~/n48-metal`, `/Users/testuser` | `ssh -p 2222 test@127.0.0.1`; percorsi `/Users/test/Developer/rx9060xt` |
| `esp-config.sh`, `esp-kext.sh` | ESP OpenCore del disco macOS, `~/navi48-staging/configs` | boot-args via `nvram` nel guest o EFI della VM; nessun ESP |
| `autoarm/` (LaunchDaemon) | avvio automatico al login window del PC, arm del display | **non installare** nella prima prova: arma il display e fa un riavvio di WindowServer |
| `arm-gpu-desktop.sh` | `headless-no`, watch di WindowServer | non usare prima di T7 |
| `reboot-pc.sh` | riavvio del PC | `sudo shutdown -r now` nel guest |
| `navi48test` | `~/navi48-staging/navi48test` (autoarm `AA_CLI`) | `~/navi48-staging/navi48test` nel guest (da compilare: `navi48test.c`) |

## 5. Blocchi e rischi

1. **`INSTALL.md` assente** (citato dai test di `navi48accel` e dal `build.sh` del bundle). Va ripristinato o rigenerato
   prima del consenso del kext aux (5.2). Non è stato fatto qui.
2. **Desktop "a video" bloccato da FASI 4.2** (adozione del GOP e flip HUBP): senza `navi48-metal-disp=1` e display
   nativo, WindowServer non presenta. La prima prova è solo headless (T0-T7).
3. **metal2vulkan per il daemon**: va compilato sul guest (x86_64). Non esiste una build macOS in questo repo.
   Se il daemon usa un traduttore diverso da quello della spvcache, la cache resta valida (è per chiave) ma le chiavi
   del daemon avranno un `KEY` diverso: nessun problema, solo più lavoro.
4. **Stub spirv-val**: il daemon, senza `spirv-val` accanto, dichiara valido tutto (`n48-spirv-val-stub`). Le
   traduzioni andrebbero validate sull'host (come descritto nello stub). Consigliato il validatore reale (4.2 punto 2).
5. **Verifica di `launchd` su `StandardOutPath`**: se la directory non c'è, il job può non partire. Da provare nella VM.
6. **Sicurezza di WindowServer**: il bundle ha un contatore di crash (`/private/tmp/n48m-starts`, >=3 avvii in 300 s
   senza uscita pulita fanno declinare). Dopo un crash in prova: rimuovere `n48m-starts` solo dopo aver letto i log.
7. **Chiavi non ancora provate** (3.4, punto 2): T5 le prova o le smentisce. Se smentite, la spvcache non serve a nulla
   e il lavoro di generazione va rifatto con le chiavi giuste (il daemon in ogni caso traduce dai dump).
8. **Licenze**: `libn48xlate` e metal2vulkan 0.1 (fork) sono LGPL-3.0-or-later e restano separati dal codice MIT
   (NOTICE). Il bundle li contiene come file caricati a runtime, come descritto nel NOTICE.

## 6. Testo proposto per FASI 5.3

Da incollare nella riga 5.3 (lo stato resta 🟨):

> Il 20/10 `build.sh` accetta una spvcache parziale o vuota (`N48_SPVCACHE_DIR`; vuota solo con
> `N48_ALLOW_EMPTY_SPVCACHE=1`). Generata in locale, fuori da git, la cache da SkyLight e CoreDisplay: 35 di 35 AIR
> tradotti con metal2vulkan 0.1 @43c46ac + patch n48, 35 di 35 validati con spirv-val vulkan1.2; QuartzCore e
> CoreImage non sono estratti. Chiavi da confermare con i dump di WindowServer nella VM. Piano di deploy:
> `research/reports/metal_deploy_plan.md`. Restano: `INSTALL.md`, daemon su guest, prova headless con cache
> vuota e piena, display (4.2).

## 7. File toccati / creati

- Modificati: `cobalt64/tools/native/navi48metal/build.sh`, `cobalt64/.gitignore`, `.gitignore`.
- Creati (fuori da git): `research/ext/m2v/metal2vulkan/` (clone @43c46ac + patch + `n48xlate`, binario in `target/`),
  `research/ext/spvcache-25G83/` (`air/`, `spvcache/`, `MANIFEST.tsv`, `translate.log`, `translate.log.rc`, `tools/carve_air.py`).
- Creati (tracciato): questo file.
- Installato in `~/.cargo` e `~/.rustup`: rustup 1.99.1 minimal (spazio utente).
- Non toccati: `tools/vm/`, `FASI.md`, `dcn/`, file display, NootRX/NootedRed, NullMoth. Nessun commit, nessun sudo,
  nessuna modifica a host/GPU/bootloader, VM non usata.

## 8. Primo boot completo: fasi P0, P1, P2 e comandi finali (aggiornato 21/10/2026)

Riscritto il 21/10 dopo il lavoro su prepare, kext e kit di armamento. Le boot-arg sono quelle lette dal codice (file:riga).
Nessuna fase è stata eseguita: la VM di test non è stata avviata (lavoro da remoto). Ogni fase è un boot distinto.

### 8.0 Stato dei gate

| Gate | Stato al 21/10 | Fonte |
|---|---|---|
| G1 kext bring-up, stage 17 | 🟨: 13 boot stage 17, tre fault GCVM VMID0 aperti, nessuna serie di 20 boot pulita | FASI 2.1, `test-plan.json` |
| G2 S1b positivo | PASS (boot 6); boot 3 e 4 REFUSED storici | `gfxhub_ack_compute.md` |
| G3 aux Navi48Accel | ✅ compilato nella VM di build (macOS 25G83, `MKSDK` assoluto, `make -B all` exit 0). Gate A 2720 slot, B 882 import, C header fresco e check_layout MATCH; `make -C tests all` 1694 check, 0 falliti; plants host 169/0; gate plants 25/0. Incluso in `metal-stack-20261021/kext/Navi48Accel.kext`, sha256 binario `4d5e257d880ed5fe076a933159ee6ef4d4a8d5bc93f067e3e7cf07512a7d3b8c`, `SHA256SUMS` 63 righe OK. Approvazione utente ancora richiesta (8.2) | fork build 21/10, `SHA256SUMS` |
| G4 RADV | dylib x86_64 con patch 0001-0010, ICD enumerato, nessun submit | `radv_icd_smoke.md` |
| G5 bundle | `Navi48Metal.bundle.tar` costruito, spvcache 35/35 validata | FASI 5.3 |
| G6 libn48xlate | ABI 2, x86_64 | FASI 5.3 |
| Kext principale navi44 | ✅ ricompilato per il boot completo (`ASIC=navi44 APPLE_ROUTE=0`, gopsnap opt-in), `/mnt/vm/builds/navi48-full-20261021/Navi48Bringup.kext`, sha256 binario `d186c77f925aed420425149be7bb04059d3e6e8a7fb3d758d345afbf3a22846d` | fork build 21/10 |

Il kext di diagnostica gopsnap (`navi48-gopsnap-stage2`, sha `8078c349…`) resta quello del boot di osservazione, non quello del boot completo.

### 8.1 Blocchi residui (il primo boot completo non è ancora pronto)

1. **Prepare (era blocco 1): risolto.** `prepare-gpu-test-stage.py` scrive `navi48-metal`, `navi48-metal-ws`, `navi48-metal-disp`, `navi48-aux` (lista esplicita, il resto è rifiutato). Testato in `--dry-run` e su una copia della directory di test (scrittura reale su copia, coerenza del launcher superata). I file reali sono invariati.
2. **Display (blocco 2): aperto.** `navi48-metal-disp=1` (P1) e il desktop sul monitor dipendono dal flip GOP (FASI 4.2). Il B2 (fallback 1920x1080) è chiuso nel codice: Navi 44 usa 2560x1440. Senza il flip la superficie del desktop non arriva al monitor: P1 può verificare l'adozione della pipe, P2 può verificare WindowServer ma non produce un desktop visibile.
3. **Kext aux (blocco 3): pacchetto risolto.** Il kext è nel pacchetto con sha256 (vedi 8.0). Serve ancora l'approvazione utente (blocco 4).
4. **Approvazione del kext aux (blocco 4): aperto.** Metodo A (documentato come usato): approvazione nella finestra GTK della VM di test, che richiede `N4X_GPU_PRIMARY=0` (quindi solo in P0), poi `--accel-resume`. Metodo B non verificato. Metodo C non usato.
5. **Sudo nel guest (blocco 5): aperto.** La regola sudoers non è installata: `deploy-metal-stack.sh --sudo-help`. Senza regola, `--deploy`, `--shutdown`, `--arm-desktop` escono prima di modificare qualcosa.
6. **Chiavi T5 (blocco 6): aperto.** Nessun dump WindowServer ancora.
7. **`n48nub` (nuovo).** Il publish del nub Metal usa `~/n48-metal/n48nub` (ricetta Cobalt64), che non è nel pacchetto: va presente nel guest. `--arm-check` lo verifica.
8. **Interazione metal-ws (nuovo).** Con `navi48-metal-ws` presente, `Navi48Accel.cpp:620` non fa partire il framebuffer aux: il DP va alla GPU desktop. È l'effetto voluto di P2, ma va verificato in P2 prima di armare.
9. **Passo `fbname 1` (nuovo, da rivedere).** La ricetta di armamento di Cobalt64 lo esegue; il commento in `navi48test.c` dice che non va eseguito senza una revisione avversariale. Il kit lo mantiene perché è nella ricetta e lo ripristina con `fbname 0` nel rollback. Da decidere prima di P2.
10. **Formato di `pipestat 0` (nuovo, non verificato sul guest).** `--arm-check` legge la riga `flags` (bit 2 adottata, bit 4 armata) dal testo di `navi48test.c` (righe 2242-2249). Se il formato differisce, il kit si ferma senza agire. Da verificare alla prima esecuzione di P1.

### 8.2 Comandi finali

Ordine: P0, poi P1, poi P2. Ogni fase è un boot con il suo EFI. In P2 l'adozione della pipe va rifatta nello stesso boot, perché l'armamento la presuppone.

**Fase P0: Metal headless, senza display** (`N4X_GPU_PRIMARY=0`, finestra GTK per l'approvazione)

Host (VM spenta):
```
python3 tools/vm/prepare-gpu-test-stage.py 17 --native-s1b --metal --dry-run
python3 tools/vm/prepare-gpu-test-stage.py 17 --native-s1b --metal
N4X_GPU_ROMBAR=1 tools/vm/start-gpu-test-vm.sh --check
N4X_GPU_ROMBAR=1 tools/vm/start-gpu-test-vm.sh --start
```
Guest, tramite il kit:
```
tools/vm/deploy-metal-stack.sh --dry-run
tools/vm/deploy-metal-stack.sh --deploy                 # digitare DEPLOY
# approvazione del kext aux in Impostazioni di Sistema > Privacy e sicurezza (finestra GTK), poi:
tools/vm/deploy-metal-stack.sh --accel-resume
tools/vm/deploy-metal-stack.sh --verify
```
Nel guest, con sudo:
```
sudo -n ~/n48-metal/n48nub publish                      # nub Metal (navi48-metal=1)
sudo N48M_ALLOW=1 ~/navi48-staging/mtlprobe list         # T0, poi T1-T4 secondo 8.3
```
Chiusura: `tools/vm/deploy-metal-stack.sh --shutdown`, poi raccolta (8.4).

**Fase P1: adozione della pipe** (`--primary --metal-disp`, `N4X_GPU_PRIMARY=1`; bloccata dal flip per l'immagine a video)

Host:
```
python3 tools/vm/prepare-gpu-test-stage.py 17 --native-s1b --metal --primary --metal-disp
N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1 tools/vm/start-gpu-test-vm.sh --start
```
Guest:
```
sudo -n ~/n48-metal/n48nub publish
sudo -n ~/navi48-staging/navi48test accel pipeadopt
sudo -n ~/navi48-staging/navi48test accel pipestat 0     # riga "flags": bit 2 = adottata
```

**Fase P2: WindowServer su un monitor** (`--primary --metal-disp --metal-ws`)

Host:
```
python3 tools/vm/prepare-gpu-test-stage.py 17 --native-s1b --metal --primary --metal-disp --metal-ws
N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1 tools/vm/start-gpu-test-vm.sh --start
```
Guest, stesso boot, poi host:
```
sudo -n ~/navi48-staging/navi48test accel pipeadopt        # presupposto dell'armamento, nel guest
tools/vm/deploy-metal-stack.sh --arm-check                 # sola lettura: si ferma al primo presupposto mancante
tools/vm/deploy-metal-stack.sh --arm-desktop --dry-run     # obbligatorio: piano host e guest, nessuna scrittura
tools/vm/deploy-metal-stack.sh --arm-desktop               # digitare ARM; richiede 0 utenti nel guest
```
`--arm-desktop` non esegue nulla se un presupposto manca (il desktop resta su CPU). Dopo il riavvio di WindowServer, se la pipe non risulta armata o WindowServer non riparte, esegue rollback: `pipearm 0`, `fbname 0`, rimozione di `/private/tmp/n48m-headless-no`.

Per tutte le fasi il launcher `--check` deve passare con la stessa variabile `N4X_GPU_PRIMARY` del piano (coerenza EFI e launcher, verificata da `start-gpu-test-vm.sh --check`).

### 8.2.1 Boot-arg usate dalle fasi (codice, file:riga)

| Boot-arg | Valore | Lettura nel codice | Fase |
|---|---|---|---|
| `navi48bringup` | `1` | `cobalt64/src/navi48-bringup/src/Navi48Bringup.cpp:7351` | tutte |
| `navi48-stage` | `17` | `Navi48Bringup.cpp:7395` | tutte |
| `navi48-interrupts` | `0` (esplicito) | `Navi48Bringup.cpp:7405` (assente = 1) | tutte |
| `navi48-native` | `1` | `Navi48Bringup.cpp:6889` (conflitti a `:6902`) | P0, P1, P2 |
| `navi48-metal` | `1` | `cobalt64/src/navi48-bringup/src/Navi48MetalNub.cpp:214` | P0, P1, P2 |
| `navi48-aux` | `1` esplicito | `cobalt64/tools/native/navi48accel/src/Navi48Accel.cpp:86` (solo `=0` spegne) | P0, P1, P2 |
| `navi48-metal-disp` | `1` | `cobalt64/src/navi48-bringup/src/amd/native_disp.cpp:573` | P1, P2 |
| `navi48-metal-ws` | `1` | `Navi48NativeClient.cpp:64` (uid 88); `Navi48Accel.cpp:620` (blocca il framebuffer aux) | P2 |
| `navi48-m6` | assente | `native_disp.cpp:586` (Navi 44 lo rifiuta) | tutte |
| `navi48-fb2` | assente | `Navi48DisplayNub.cpp:55` (rotta Apple) | tutte |

### 8.2.2 Blocchi di approvazione e recupero

- Kext aux che non carica: `navi48-aux=0` al boot successivo (`prepare-gpu-test-stage.py --aux-kill`), il bundle resta.
- WindowServer in loop: `/private/tmp/n48m-off` e `/private/tmp/n48m-starts` (8.5).

### 8.3 Criteri T0-T7

I comandi sono quelli di `mtlprobe` e `navi48test` nel guest, in `~/navi48-staging/`. Ogni test richiede
`sudo N48M_ALLOW=1` (il bundle rifiuta i root non ammessi).

| Test | Comando | Criterio di PASS | Criterio di STOP |
|---|---|---|---|
| T0 device | `sudo N48M_ALLOW=1 ~/navi48-staging/mtlprobe list` | exit 0, un device "AMD Radeon RX 9060 XT" | nessun device, o rifiuto del bundle |
| T1 census | `sudo N48M_ALLOW=1 N48M_CENSUS=1 ~/navi48-staging/mtlprobe list` | stderr `census: 81 selector(s) missing in all` (valore atteso del sorgente attuale con SDK 25G83, corrisponde a 79 required + 2 optional); la lista di `(classe, selettore)` deve coincidere con `research/hw_dump/p0_boot22/t1-census.txt` (riga per riga). Il valore `0` non è atteso: il census misura la copertura dei protocolli MTL intera, e il bundle non implementa tile, ICB, function table, patch, sparse, argument buffer (gap noti, identici su Cobalt64). `test-census.m`: 28 check verdi sul host | un (classe, selettore) assente dalla lista di riferimento (regressione), errori di load del bundle |
| T2 hot-swap | `sudo N48M_ALLOW=1 ~/navi48-staging/mtlprobe hotswap --spv-src <dir> --side-dir <tmp> --wait 60` | log `HOT-SWAP ...: fallback -> real`; il quad passa dopo il swap; un frame in volo resta fallback | nessun `fallback -> real` entro `--wait`; SKIP solo se il nome del device non contiene `9060` né `9070` (nomi dei profili ASIC) |
| T3 triangolo/quad | `sudo N48M_ALLOW=1 ~/navi48-staging/mtlprobe triangle out.png`; `... quad` | `mtlprobe: PASS (exact)` o `PASS quad (exact)`; con tolleranza bordi il PASS riporta lo 0,5%. Il triangolo confronta con un riferimento CPU calcolato in-process (`tri_reference`, come il quad), non con un file; `--expected <raw>` lo sostituisce solo se passato esplicitamente | `FAIL quad`, `SKIP`, pipeline nil |
| T4 compute | `sudo N48M_ALLOW=1 ~/navi48-staging/mtlprobe qccompute` (o `compute`) | risultato uguale al riferimento CPU | `COMPUTE FALLBACK` inatteso (nel bundle è un no-op, vedi `Navi48Device.m` r.6077-6082) |
| T5 chiavi WindowServer | `ls /private/tmp/n48m/*/` dopo l'avvio di WindowServer | i nomi `<sha>.air` dumpati intersecano `research/ext/spvcache-25G83/MANIFEST.tsv` | nessun dump: il bundle non ha preso il ramo WS |
| T6 riproducibilità traduzione | **già fatto** nella VM di build (21/10): 70/70 file identici per nome e sha256 Mac vs Linux | — | — |
| T7 WindowServer headless | `log show --last 10m --predicate 'process == "WindowServer"'` (e `log stream` durante il test) | WS in vita, nessun crash; righe `spvcache hit` e `FALLBACK`/`HOT-SWAP` coerenti con la cache; nessun `DECLINED` inatteso | crash, più di 2 avvii in 300 s (`/private/tmp/n48m-starts`), `DECLINED` inatteso |

Criteri globali di STOP per ogni boot: panic del kernel (seriale), fault GCVM VMID0 che salgono dopo il boot, WS in
loop di riavvio, nessun ritorno dal guest allo shutdown, `n48m-starts` con tre voci in 300 s. Al primo STOP: nessun
test successivo, raccolta completa, poi shutdown.

Messaggi di `mtlprobe` e della suite sono quelli del sorgente (`mtlprobe.m`, `Navi48Device.m`), non sono stati eseguiti
sul guest di test.

### 8.4 Cosa raccogliere, per boot

Cartella: `/mnt/vm/images/macos-gpu-test/diagnostics/<boot_id>/` (sull'host), con sha256.

- `diagnostics/serial.log` copiato dopo lo shutdown (il launcher lo scrive durante il boot).
- Nel guest, prima dello shutdown: `nvram boot-args`, `kmutil showloaded --list-only | grep -iE 'navi48|accelprobe'`,
  `ioreg -l -p IOService -w0 | grep -iE 'navi48|AMD'` (filtrato), `launchctl print system/com.navi48.translate` (se avviato).
- `log show --last 30m --predicate 'process == "WindowServer" OR subsystem == "com.navi48.metal"' > ws.log`.
- `/private/tmp/n48m-starts`, `/private/tmp/n48m/` (elenco), `/private/var/tmp/n48m-translate-state/translate.log`.
- `/Library/Logs/DiagnosticReports/` (crash di WindowServer, se presenti).
- Sha256 di: bundle installato (`Navi48Metal.bundle/Contents/MacOS/Navi48Metal`), kext aux (`/Library/Extensions/Navi48Accel-*.kext`),
  `~/navi48-staging/*`.
- Log di deploy: `diagnostics/deploy/deploy-<stamp>.log` (scritto da `deploy-metal-stack.sh --deploy`).
- Dopo il boot, aggiornare `test-plan.json` con `latest_*` solo per i risultati misurati. Mai con ipotesi.

### 8.5 Procedura di recupero

- Kext aux che non carica: `navi48-aux=0` (kill switch) al boot successivo; il bundle resta.
- Bundle che fa danni: `sudo rm -rf /Library/GPUBundles/Navi48Metal.bundle` e rinominare il `.prev-<stamp>`.
- Daemon: `sudo launchctl bootout system/com.navi48.translate`.
- WindowServer in loop: `/private/tmp/n48m-off` (kill file) e `/private/tmp/n48m-starts` letto prima di rimuoverlo.
- Il launcher della VM di test rifiuta l'avvio se la VM di build è in esecuzione (`.vm.lock`).
