# Integrazione di `tools/ioaccel-layout` (Cobalt64 upstream), layout IOAccelerator per 25G83 e build nella VM

Data: 20 ottobre 2026. Host Linux (CachyOS, kernel 7.2), Python 3, LLVM 21 (`llvm-nm`), GNU c++filt 2.47.
Guest: macOS Tahoe 26.6.2 (25G83), MacPro7,1, VM di build senza passthrough GPU, 12 GiB (valore fissato dallo script
`OpenCore-Boot.sh`, che non accetta override di RAM né da variabile d'ambiente né da argomento).
Scopo: sbloccare la Fase 5.2 generando `IOAccelFamily2_decl.h` con lo strumento upstream, confrontarlo con
l'inventario locale, poi compilare, linkare, firmare e testare `tools/native/navi48accel` nella VM.

## Esito sintetico

| Passo | Esito | Dettaglio |
|---|---|---|
| Upstream: diff `d6c9aed..origin/main` | PASS | Solo `tools/ioaccel-layout/` (9 file, 1225 righe). |
| Integrazione in `cobalt64/tools/ioaccel-layout/` | PASS | 9 file da `git archive origin/main`, SHA-256 identici ai blob. Nessun commit. |
| `dump_vtables.py` (host) | PASS | 98 classi. |
| `gen_header.py` (host) | PASS | 62 classi emesse; 183 slot con firma reale, 484 placeholder `_vslotN`, 13 downgraded. |
| `check_layout.py` (host) | **MATCH** | 16 classi, 3150 slot. |
| Confronto con l'inventario | PASS | 13 classi su 13: slot, pure, dimensioni, superclassi identici (sotto). |
| Rigenerazione deterministica | PASS | Seconda esecuzione: 5 file byte-identici. |
| `make build/accel.o` (host Linux) | PASS | 0 warning. |
| Correzioni ai riferimenti residui | PASS | `tests/plant.sh`, `tests/gate_plants.sh`, `tests/host_test.cpp`, commenti in gate, sorgente e `iodp_vtable_static.h`: percorso `tools/ioaccel-layout`. |
| Build completa nel guest (`make MKSDK=<SDK guest>`) | **PASS** (exit 0) | Link riuscito, kext firmato ad hoc (`Built build/Navi48Accel.kext`). |
| Gate A (linker, 13 classi) | **PASS** | 2720 slot confrontati con la famiglia: override e ereditarietà per indirizzo esatto. |
| Gate B (import del kext) | **PASS** | 882 simboli indefiniti risolti, 0 non esportati da famiglia, kernel o IOGraphicsFamily. |
| Gate C (header fresco e `check_layout`) | **PASS** | sha256 header `4d4a6c1391f86c09`; `check_layout.py` MATCH (16 classi, 3150 slot). |
| Gemello host del layout gate (`layout_gate_host.py`) | **PASS** | ALL MATCH: 13 classi, 2720 slot. |
| Test host `make -C tests all` | 1694 controlli, 14 falliti | Tutti per `INSTALL.md` assente (vedi discrepanze). |
| Planted-break dei gate (`make -C tests gates`) | **PASS**: 25 eseguiti, 0 sfuggiti | Il CONTROL (nessun break) passa. |
| Planted-break host (`make -C tests plants`) | **NON CONCLUSIVO**: 169 eseguiti, 8 "sfuggiti/non applicati" | Il CONTROL fallisce per `INSTALL.md` assente. |
| Kext installato o caricato | NO | Nessun `kmutil install/load`; solo build, firma e test. |

## File modificati (repository)

- `cobalt64/tools/ioaccel-layout/` (nuovo; 9 file identici all'upstream d1f7bad).
- `cobalt64/tools/native/navi48accel/Makefile`: `LAYOUT := ../../ioaccel-layout`; `export C64_MKSDK := $(MKSDK)` (su riga
  propria: un commento in coda lasciava spazi nel valore e rompeva `-I`).
- `cobalt64/tools/native/navi48accel/gates/common.py`: `LAYOUT` punta a `../../../ioaccel-layout`.
- `cobalt64/tools/native/navi48accel/gates/gate_link.py`: il gate C copia `model.json` in una temp dir e imposta
  `C64_LAYOUT_OUT` su di essa. Motivo: il `gen_header.py` upstream non legge `N48_GEN_OUT` (il valore usato prima).
- `cobalt64/tools/native/navi48accel/gates/gen_gate.py`, `src/Navi48Accel.cpp`: solo commenti (percorso).
- `cobalt64/tools/native/navi48accel/tests/host_test.cpp`, `tests/plant.sh`: percorso del TSV
  (`../../ioaccel-layout/generated/vtables/IOFramebuffer.tsv`). Ora il test legge il TSV: 1694 controlli invece di 1667.
- `cobalt64/tools/native/navi48accel/tests/gate_plants.sh`: `L=tools/ioaccel-layout`; copia del layout con `rsync -aL`
  (il symlink diventa file reali nella scratch); `make MKSDK=...` esplicito; `C64_LAYOUT_OUT` impostato sulla scratch.
- `cobalt64/src/navi48-bringup/src/apple/iodp_vtable_static.h`, `src/amd/native_disp_pure.h`: solo commenti (percorso).
- `.gitignore` (radice): `/cobalt64/tools/ioaccel-layout/generated` (symlink locale).
- `FASI.md`: righe 5.1 e 5.2.

Non versionati: `research/ext/layout-out/`, `research/ext/c64-work/` (sotto `/research/ext/`), il symlink `generated`,
`build/`, `__pycache__/`.

## Work dir e output sull'host

- `research/ext/c64-work/kc/`: symlink alle KC di `research/macos/25G83/`.
- `research/ext/c64-work/kexts/`: `com.apple.iokit.IOAcceleratorFamily2` (871 192 B) e `com.apple.driver.AppleParavirtGPU`
  (292 808 B), Mach-O x86_64 standalone estratti con `ipsw kernel extract` (3.1.737) dalla System KC.
- `research/ext/layout-out/`: output di `dump_vtables.py` e `gen_header.py`, più `build/` di `check_layout`.

SHA-256 delle KC (identici all'inventario e alla copia nel guest, verificati con `shasum`):
- `BootKernelExtensions.kc`: `c80161fa3065883753fc285339281361a8469cbb6fb27653c88e2a22eb4807a4`
- `SystemKernelExtensions.kc`: `fbab2d48bf1470fb0ec15dd62a6bb90c39d8bb45ed68240d3c73f1e43e770dee`

## Confronto con l'inventario (`ioaccel_vtable_inventory.md`, `ioaccel_class_sizes.md`)

| Classe | Slot (inv / model) | Pure (inv / model) | Dimensione | Superclasse |
|---|---|---|---|---|
| IOGraphicsAccelerator2 | 350 / 350 | 17 / 17 | 0xdd8 | IOAccelerator |
| IOAccelEventMachineFast2 | 95 / 95 | 4 / 4 | 0xd30 | IOAccelEventMachine2 |
| IOAccelTask | 51 / 51 | 0 / 0 | 0x258 | OSObject |
| IOAccelDisplayMachine | 284 / 284 | 2 / 2 | 0x178 | IOService |
| IOAccelSysMemory | 66 / 66 | 0 / 0 | 0x198 | IOAccelMemory |
| IOAccelMemoryMap | 57 / 57 | 3 / 3 | 0x118 | OSObject |
| IOAccelVidMemory | 69 / 69 | 3 / 3 | 0x110 | IOAccelMemory |
| IOAccelResource2 | 79 / 79 | 7 / 7 | 0x180 | OSObject |
| IOAccel2DContext2 | 368 / 368 | 2 / 2 | 0x1100 | IOAccelContext2 |
| IOAccelSharedUserClient2 | 308 / 308 | 0 / 0 | 0x168 | IOUserClient |
| IOAccelCommandQueue | 337 / 337 | 0 / 0 | 0x6a8 | IOAccelSubmitter2 |
| IOAccelDisplayPipe | 306 / 306 | 0 / 0 | 0x318 | IOService |
| IOFramebuffer | 350 / 350 | 8 / 8 | 0x1d0 | IOGraphicsDevice |
| **Totale** | **2720 / 2720** | **46 / 46** | | |

Gli indici puri coincidono con l'inventario. Il confronto è stato fatto con uno script in scratch.

## Build e gate nel guest

Ambiente richiesto (esportato dal comando, il Makefile esporta `C64_MKSDK`):

```sh
export C64_WORK=$HOME/c64-work                       # kc/ -> /System/Library/KernelCollections/*.kc (identiche, SHA verificati), kexts/ copiati dall'host
export C64_LAYOUT_OUT=$HOME/Developer/rx9060xt/cobalt64/tools/ioaccel-layout/generated   # copia del layout, solo per la build
cd cobalt64/tools/native/navi48accel
make MKSDK=$HOME/Developer/rx9060xt/cobalt64/src/RDNA4FB/MacKernelSDK   # build + gate A/B/C + gemello host
make -C tests all                                    # test host
make -C tests gates                                  # planted-break dei gate (25)
make -C tests plants                                 # planted-break host (non conclusivo, vedi sotto)
```

Il layout generato (`generated/`) è stato copiato nel guest solo per la build e non è versionato. Il guest non ha
installato né caricato alcun kext.

Esito chiave di `make` (estratto dal log): `Built build/Navi48Accel.kext`; `A` 13 classi con `exact family symbol`;
`B 882 undefined symbols, 0 not exported`; `C generated header fresh`; `C check_layout.py: MATCH ... (16 classes)`;
`GATES A/B/C PASS: 2720 vtable slots checked against the family, 882 imports resolved`; gemello:
`ALL MATCH: 13 classes, 2720 slots compared`.

Esito dei planted-break dei gate: `gate plants: 25 run, 0 escaped/failed`, CONTROL `make passed; GATES A/B/C PASS`.

## Discrepanze e problemi trovati nella build

1. `gate_link.py` passava `N48_GEN_OUT` a `gen_header.py`, ma il `gen_header.py` upstream non lo legge (scrive in
   `$C64_LAYOUT_OUT`). Corretto nel gate (`C64_LAYOUT_OUT=tmp` + copia di `model.json`); lo script upstream non è stato modificato.
2. `check_layout.py` richiede `C64_MKSDK`. Il Makefile ora lo esporta da `MKSDK`. Il commento in coda alla riga `export`
   lasciava spazi nel valore (`.../MacKernelSDK   `) e rompeva `-I`: corretto spostando il commento.
3. `gate_plants.sh` eseguiva `check_layout` con il layout reale invece della scratch: corretto (`C64_LAYOUT_OUT` sulla scratch).
4. Il Makefile di default cerca `src/RDNA4FB/MacKernelSDK`. Nel guest esiste (`cobalt64/src/RDNA4FB/MacKernelSDK`), ma
   l'SDK non è nel repo: `MKSDK=` esplicito è necessario sull'host.
5. `libkmodc++.a` non è in `Library/x86_64` del SDK, ma nel fat `Library/universal` (slice x86_64 presente). Il link di
   navi48accel è riuscito con `-L$(MKSDK)/Library/x86_64 -lkmodc++`, quindi la riga risolve in questo SDK. Da tenere d'occhio.
6. **`INSTALL.md` assente** nel repository (citato da `host_test.cpp` e da `plant.sh`). Effetti:
   - `make -C tests all`: 1694 controlli, 14 FAIL, tutti su `INSTALL.md` / le sezioni 0.0.x che lo descrivono
     (prima 1667 controlli: il TSV ora viene letto e aggiunge 27 controlli). Il target esce con errore.
   - `make -C tests plants`: il CONTROL fallisce per lo stesso motivo; 5 plant puntano a `INSTALL.md` e non si applicano
     ("THE PLANT ITSELF DID NOT APPLY"). Il risultato "8 escaped/failed" **non è conclusivo**: un "CAUGHT" non prova
     che il break sia rilevato dalla suite giusta.
   - Il file non è stato ricreato: il suo contenuto va recuperato o riscritto da chi lo ha scritto.
7. Il `layout_gate_host.py` e il gate A/B/C non dipendono da `INSTALL.md`: sono gli unici risultati pienamente validi.
8. Restano i tipi di ritorno (484 slot `_vslotN`, default `uint64_t`) e il layout dei membri (vedi 5.1).

## VM di build

- Avvio: `tools/vm/start-build-vm.sh` in una sessione `tmux` (`macvm`), con `DISPLAY=:0`. `ignore_msrs` già `Y`
  (impostato dall'utente; nessun `sudo` eseguito). RAM 12288 MiB, quella fissata dallo script.
- Accesso SSH: `ssh -i /mnt/vm/builds/build-vm-ed25519 -p 2222 test@127.0.0.1`.
- Spegnimento: richiesto dal guest con `osascript ... shut down` (exit 0), poi ACPI con `tools/vm/qmp.py system_powerdown` (accettato). Il guest non si è spento e non rispondeva più via SSH. Dopo oltre 20 minuti QEMU è stato terminato con SIGTERM (uscita pulita del processo, senza SIGKILL). Lo stato del disco guest (qcow2 e APFS) non è verificato: al prossimo avvio controllare fsck/log di boot.

## Cosa resta

- Ripristinare `INSTALL.md` (oppure correggere i test che lo citano) per rendere valide le suite host e i planted-break host.
- Tipi di ritorno e layout dei membri (5.1), per passare da placeholder a un ABI completo.
- Caricamento del kext e test runtime su hardware (fasi 2 e 5.3): non fatti, come richiesto.
