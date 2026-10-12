# Separazione della "rotta Apple" dal kext (fase 1.1)

Data: 12/10/2026. Albero: `cobalt64/src/navi48-bringup/`. Interruttore: `make APPLE_ROUTE=0` (default) / `APPLE_ROUTE=1`
(build completa di Cobalt64, invariata).

## Cosa esce dalla build con `APPLE_ROUTE=0`

| Unità | Righe | Perché |
|---|---|---|
| `apple/AppleHardwareHook.cpp` | 34 906 | hook nel driver AMD di Apple (ring, VM, GART, KIQ, catena di boot, gfxneuter) |
| `apple/Navi48AccelPeer.cpp` | 5 030 | patch dell'acceleratore AMDRadeonX6000, copie di residenza, flush hook |
| `apple/Navi48Ttl.cpp` | 1 112 | il servizio TTL che sostituisce quello di Apple |
| `apple/AppleTtlHook.cpp` | 159 | il redirect di `HWServices::getTtl()` |
| `../xlat12/*.c`, `../shadercache/shadercache.c` | — | traduttore gfx10.3→gfx12 e cache shader, usati solo dai file sopra |

Resta compilato `apple/DisplayPipeGuard.cpp`, perché contiene anche codice display nativo: il servizio AGDC della
rotta nativa (`navi48-metal-disp=1`, verbo 88), le statistiche m6, il descrittore di scanout del user client
(`clientMemoryForType` 'FBSC'/'FBVR') e gli helper di RDNA4FB.

## Come è stata misurata la dipendenza

Gli oggetti Mach-O sono compilati da Linux (clang `-target x86_64-apple-macos11.0` + MacKernelSDK). Poi i simboli
non definiti degli oggetti nativi (più DisplayPipeGuard) sono incrociati con quelli definiti dalle unità escluse:
**95 simboli**, di cui 92 usati da `Navi48Bringup.cpp`. La classificazione di ciascuno, con l'evidenza file:riga del
percorso di default, è stata fatta leggendo definizioni e chiamanti:

- **Hook su percorsi caldi** (`hw_mkh_gate/holder/spin/lockwait`, bridge EOP/trap, `hw_cm_armed`, …): nello stato
  di default restituiscono costanti (nessun holder, nessun arm). Stub con le stesse costanti.
- **Verbi raggiungibili senza `accel fire`**: stub che riproducono lo stato di default, compresi i valori non nulli
  (`kiq lastPropMs = 0xFFFFFFFF`, `ucprobe out[10] = 0xFF<<40`, `rearm out[1] = 1`, `rootwrite out[1] = 0xFF`,
  `vm_page_scan out[7] = 0xffffffff`, i codici di stato di `flushhook`/`ucprobe`/`gfx_probe`/`gfx_capture`).
- **Verbi dopo `accel fire`**: irraggiungibili, perché `accelExperimentFired` si imposta solo quando
  `install_ttl_hook` riesce, e senza HWServices di Apple non riesce mai. Il chiamante risponde `kIOReturnNotReady`
  prima di arrivare alla funzione.
- **Codice nativo vero, copiato** in `src/native/apple_route_off.cpp`:
  - `hw_hook_ramtop_init` / `hw_hook_ramtop_derived_or_zero`: il limite della RAM ricavato dalla mappa EFI, usato dal
    rifiuto delle pagine di dispositivo in `BoImportHost` (`amd/native_s1c.cpp`);
  - `hw_hook_uptime_us`.
- **`gfxneuter`**: instrada ancora i tre interruttori il cui stato vive nel codice nativo: 37 (priorità della
  finestra MM), 74 (flip mode), 83 (attesa del TLB flush della GMC). La guardia "continuous arm" che consultano è
  stato della rotta Apple, sempre assente qui. Gli altri interruttori rispondono 11 (rifiutato, nulla cambiato).
- **`gNavi48Ttl`**: un oggetto con vtable che non può stare in un file di stub. Le sue 4 righe in `Navi48Bringup.cpp`
  sono sotto `#if N4X_APPLE_ROUTE`, con i valori di default (0 chiamate, primo non supportato = −1).

## Differenze di comportamento (solo con boot-arg non di default)

- `navi48-boot-chain`, `navi48-shader-cache`, `navi48-eop-bridge`: ignorati, con una riga di log.
- `navi48-accel-experiment` + `accel fire`: risponde subito "HWServices never appeared" invece di cercarlo per 2 s.
- I verbi diagnostici che oggi leggono registri o VRAM anche senza Apple (37, 40-42, 47, 48, 52-54, 64) rispondono
  "vuoto/rifiutato". Il verbo 40 non azzera più lo stato di fault GCVM: se servisse, va dato al codice nativo un
  verbo suo.

## Verifiche

- Collegamento da Linux degli oggetti della build `APPLE_ROUTE=0`: 0 simboli del progetto non definiti, 0 doppie
  definizioni. I soli `fw_*` richiesti sono il set Navi 44 e i due shader di self-test (il blob della shader cache
  e gli shader di blit gfx1201 non servono più).
- `tools/linux-check-kext.sh`: 53/53 con `APPLE_ROUTE=0`, `APPLE_ROUTE=1` e profilo Navi 48.
- `tools/hosttests/run-cobalt64-tests.py`: 65 PASS, nessuna regressione rispetto al riferimento.
- Da fare su macOS: `make` reale (link con il kernel), poi i test di bring-up della fase 2.

## Passo successivo

Quando la rotta nativa sarà provata su hardware, si potranno cancellare le unità escluse e gli header `apple/`
usati solo da loro. Nel frattempo `APPLE_ROUTE=1` resta come riferimento, per confrontare con il comportamento
originale di Cobalt64.
