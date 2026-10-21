# Prima build macOS — Tahoe 26.6.2 / 25G83

Data: 20 ottobre 2026. Guest x86_64 MacPro7,1, utente `test`, SSH inoltrato
su `127.0.0.1:2222`. Sorgenti in `/Users/test/Developer/rx9060xt`.

## Kext bring-up Navi44

Command Line Tools: Apple clang 21.0.0, SDK MacOSX.sdk delle CLT.
Comando: `make all ASIC=navi44 APPLE_ROUTE=0` in `cobalt64/src/navi48-bringup`.
Build riuscita e firma ad hoc verificata con `codesign --verify --strict`.
Binario Mach-O 64-bit kext bundle x86_64, PCI match 0x75901002.
`kmutil libraries --arch x86_64 --bundle-path ... --undef-symbols` termina con
codice 0: tutte le 412 righe dei simboli importati riportano la definizione
nelle kernel collection di 25G83, nessuna riga non risolta.
Questo non prova il caricamento né il funzionamento sulla scheda.

Il Makefile aveva come obiettivo predefinito una regola per uno shader invece
di `all`; aggiunto `.DEFAULT_GOAL := all` e sincronizzato il Makefile nella VM.
Archivio iniziale sull’host: `/mnt/vm/builds/Navi48Bringup-navi44-build.tar.gz`.

## Acceleratore

`make -C cobalt64/tools/native/navi48accel all` fallisce prima della compilazione:
`../ioaccel-layout/generated/IOAccelFamily2_decl.h` non esiste. È il blocco ABI
noto; l’inventario vtable non sostituisce le intestazioni complete.
`make ... test`: 1661 controlli, 14 fallimenti, tutti riferiti ai percorsi e
alle istruzioni di installazione nel file `INSTALL.md` assente. Non è un test
runtime dell’acceleratore; nessun suo kext è stato prodotto o caricato.

## RADV e strumenti

Sorgenti da `research/ext/mesa-darwin`, con le modifiche locali preservate,
trasferiti senza `.git` e `build-shim`. Python CLT 3.9 non soddisfa Mesa:
installato Python 3.12.15 tramite uv in spazio utente, venv `build-env312`.
Meson 1.12.1, Ninja 1.13.2, Mako 1.4.3, PyYAML 6.0.3, packaging 26.3.
Glslang ufficiale Khronos macOS universal, release main-tot, versione 16.6.0,
in `deps/glslang`; Rust stabile 1.99.1 installato in spazio utente.

Mesa configurato in `deps/mesa-darwin/build-macos` con:

```
-Dgallium-drivers= -Dvulkan-drivers=amd -Dplatforms= -Dllvm=disabled
-Damd-use-llvm=false -Dglx=disabled -Degl=disabled -Dopengl=false
-Dgles1=disabled -Dgles2=disabled -Dvideo-codecs= -Dbuild-tests=false
-Dbuildtype=release
```

Target `src/amd/vulkan/libvulkan_radeon.dylib`, Ninja -j4: build riuscita,
775 operazioni. Mach-O x86_64; solo dipendenze dylib di sistema.
`ctypes.CDLL` nella VM riesce, `vk_icdGetInstanceProcAddr` presente.
Verificati anche gli export radv_darwin_scanout_* e radv_darwin_n48n_*.
Nessuna enumerazione o esecuzione sulla RX 9060 XT (non assegnata alla VM).

## Traduttore e bundle Metal

metal2vulkan al commit fissato `43c46ac8a24adf1a6e872b8a52c706ec9614fad0`,
patch e crate n48xlate da `cobalt64/third-party/metal2vulkan-n48`.
Esito della compilazione riportato nell’aggiornamento sotto.

## Accesso e limiti

Chiave SSH dedicata sull’host `/mnt/vm/builds/build-vm-ed25519` (permessi 600),
chiave pubblica aggiunta all’utente guest. Password non salvata negli script.
Nessuna installazione/caricamento dei driver, modifica SIP/AMFI o passthrough.
Log guest: `validation/` nella radice del progetto trasferito.

### Esito traduttore e prova Metal

`cargo build --release -p n48xlate --target x86_64-apple-darwin -j4` riuscito.
`libn48xlate.dylib` è Mach-O x86_64, si carica con ctypes.CDLL e restituisce
2 da `n48x_abi_version()`.

Lo script Metal originale si arresta al glob `spvcache/*.spv` (file assenti).
Eseguita separatamente la stessa invocazione clang x86_64 del build.sh,
con header Vulkan da Mesa e le stesse opzioni/framework: compilazione e link
riusciti, `validation/Navi48Metal-linkcheck.NOT-INSTALLED` è un Mach-O bundle
x86_64. È una prova di compilazione, **non** un Navi48Metal.bundle completo;
nessun bypass del packaging, nessuna dichiarazione di compatibilità ABI
runtime (incluso il mismatch lazyInitialize già censito).

Archivio di librerie e log: `/mnt/vm/builds/rx9060xt-build-validation.tar.gz`.
SHA-256 uguale nel guest e nell’host:
`bc02005f3c9d7c7c308ce896f579ae29c5b6b9683935183e505b42bae7e88322`.
Contiene `validation/`, RADV e n48xlate. Il kext e il suo log restano anche
nell’archivio iniziale separato. Nessun processo di build lasciato in background.

Fonti degli strumenti aggiunti:
- glslang: https://github.com/KhronosGroup/glslang/releases/tag/main-tot
- Rust/rustup: https://rust-lang.org/tools/install/
- Python gestito: uv da PyPI, download python-build-standalone tramite uv.

Prossimo lavoro: ricostruire gli header/layout IOAccelerator per 25G83 e
sbloccare i gate dell’acceleratore; ricostruire/validare la cache shader e
risolvere i mismatch SPI Metal prima del caricamento. La compilazione non
sostituisce i gate ABI né il bring-up su hardware.

## Aggiornamento ABI Metal e snapshot — 20/10/2026

Corretto `lazyInitialize`: dichiarazione e override BOOL, ritorno della base
preservato; NO se il metodo base manca. Il nuovo `test-lazy-abi.m` viene eseguito
sui binari realmente compilati, non su una copia del metodo. Prima della patch
fallisce: override `v`, Apple `c`. Dopo: `c/c`, risultati NO/YES preservati,
una chiamata base per invocazione; varianti N48_LAZY=0 e1 entrambe PASS.
La sostituzione dell’IMP Apple è soltanto nel processo di test, poi ripristinata;
nessuna inizializzazione del device o chiamata alla reale lazy init Apple.
Lo script ripetibile è `tools/vm/check-metal-abi.sh`, vincolato al guest x86_64 25G83.
Test census esistente: 28 controlli, zero fallimenti. Corretto anche il delimitatore
del test (dipendeva da un commento cambiato) e il controllo NSNotFound per non
sollevare eccezioni su sorgenti diversi. Nessun gate di compatibilità generale
è stato dichiarato superato sulla base di questi soli controlli.

Archivio host `/mnt/vm/builds/rx9060xt-lazy-abi-validation.tar.gz` contiene sorgenti,
binari diagnostici e log pre/post. Dimensioni/superclassi delle13classi recuperate
in `ioaccel_class_sizes.md`; layout dei membri e dichiarazioni restano incompleti.
Snapshot a guest spento e configurazione test separata: `first_gpu_test_plan.md`.
