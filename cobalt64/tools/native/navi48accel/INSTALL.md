# Navi48Accel: installazione del kext aux (com.navi48.accelprobe)

> **Nota di provenienza.** Questo file è stato ricostruito nel progetto del Navi 44 il 20/10/2026, perché il
> `INSTALL.md` originale non era presente nel repository (né nella storia git né nello snapshot upstream di Cobalt64).
> Il contenuto deriva da `Makefile`, `Info.plist`, `src/Navi48Accel.cpp`, `src/n48accel_pure.h`,
> `tests/host_test.cpp`, `tests/plant.sh`, `build.sh` del bundle e dagli script reali in `tools/pc/`
> (`m6-stage1a-run.sh`, `m6-stage2-run.sh`, `navi48test.c`, `arm-gpu-desktop.sh`). Non è una guida di Cobalt64.
> Le sezioni storiche (0.0.2-0.0.7) descrivono le versioni così come sono nel codice al 20/10/2026.

Il kext aux è un kext di accelerazione caricato nell'Auxiliary Kernel Collection. Non si installa mai con: NEVER `kmutil install --update-all`. Quel comando ricostruisce l'intera collection e può riportare il consenso degli
altri kext. Ogni versione va in un percorso nuovo, e il comando da usare è sempre `kmutil load -p` sul percorso
della versione corrente. NEVER `kmutil install --update-all` as a step of this kext.

Kill switch in ogni momento: boot-arg `navi48-aux=0` (il kext non risponde a nessuna entry point).

Regola comune a tutte le versioni: prima di ogni modifica si salva l'AuxKC corrente in `~/navi48-backup/auxkc-pre-<versione>/`.

## Versioni

| Versione | Contenuto |
|---|---|
| 0.0.2 | milestone #9, route A: accelerator e nub Metal |
| 0.0.3 | pipe di display (ABI 2 del disp hook) |
| 0.0.4 | framebuffer del monitor B (M5) |
| 0.0.5 | client utente `N48N` sull'acceleratore per app sandboxate (G6) |
| 0.0.6 | personality del monitor A |
| 0.0.7 | latch `navi48-m6` (M6 Stage 1a): sblocca il rifiuto con `navi48-metal-ws` |

## Passi comuni

1. Compilare nel progetto: `make MKSDK=<percorso MacKernelSDK>` in `tools/native/navi48accel`. Il make
   fallisce se un gate (A, B, C) o il layout runtime non sono MATCH.
2. Verificare il build: `codesign --verify --strict -v build/Navi48Accel.kext`.
3. Test host: `make -C tests all` e `make -C tests plants` (dalla stessa directory).

## 0.0.7 (aux 0.0.7, M6 Stage 1a)

Percorso nuovo nella directory `/Library/Extensions/`, con il nome versionato 0.0.7. Il percorso del 0.0.6
viene spostato via, non modificato.

Step 4b (installazione della 0.0.7):

1. Backup dell'AuxKC: `mkdir -p ~/navi48-backup/auxkc-pre-0.0.7 && sudo cp /Library/KernelCollections/AuxiliaryKernelExtensions.kc ~/navi48-backup/auxkc-pre-0.0.7/`
2. Copia: `sudo cp -R build/Navi48Accel.kext /Library/Extensions/Navi48Accel-0.0.7.kext && sudo chown -R root:wheel /Library/Extensions/Navi48Accel-0.0.7.kext`
3. Permessi: `sudo chmod -R go-w /Library/Extensions/Navi48Accel-0.0.7.kext`
4. Attributi: `sudo xattr -cr /Library/Extensions/Navi48Accel-0.0.7.kext`
5. Librerie: `sudo kmutil libraries -p /Library/Extensions/Navi48Accel-0.0.7.kext -a x86_64` (nessun simbolo non risolto)
6. Caricamento, una sola volta: `sudo kmutil load -p /Library/Extensions/Navi48Accel-0.0.7.kext`
7. Verifica: `ls -ld /Library/Extensions/Navi48Accel-0.0.7.kext`

Il 0.0.6 si sposta via: `sudo mv /Library/Extensions/Navi48Accel-0.0.6.kext ~/navi48-backup/` (solo dopo che la 0.0.7 è caricata).

Il latch `navi48-m6=1` sblocca il rifiuto del framebuffer con `navi48-metal-ws` presente; senza il latch il
rifiuto resta. NEVER `kmutil install --update-all` anche per questa versione.

    Kill switch at any time: boot-arg `navi48-aux=0` (both framebuffers refuse to start). With navi48-m6=1 they START only when the bring-up kext's routing guard allows it.

Ordine di Stage 1a, come eseguito dagli script PC (`tools/pc/m6-stage1a-run.sh`, config
`stage17-native-1440-metal-disp-amfi-m6.plist` nel loro staging, boot-arg `navi48-m6=1`): verifica del kext
aux caricato; `accel fbpublish 2`; `accel pipeadopt`; `accel pipeagdc 1`; `accel m6stat`. Un fallimento in uno
di questi passi ferma la sequenza: nessun comando successivo.

## 0.0.6 (personality del monitor A)

Percorso nuovo nella directory `/Library/Extensions/`, con il nome versionato 0.0.6.

Step 4b:

1. Backup dell'AuxKC: `mkdir -p ~/navi48-backup/auxkc-pre-0.0.6 && sudo cp /Library/KernelCollections/AuxiliaryKernelExtensions.kc ~/navi48-backup/auxkc-pre-0.0.6/`
2. Copia: `sudo cp -R build/Navi48Accel.kext /Library/Extensions/Navi48Accel-0.0.6.kext && sudo chown -R root:wheel /Library/Extensions/Navi48Accel-0.0.6.kext`
3. Permessi: `sudo chmod -R go-w /Library/Extensions/Navi48Accel-0.0.6.kext`
4. Attributi: `sudo xattr -cr /Library/Extensions/Navi48Accel-0.0.6.kext`
5. Librerie: `sudo kmutil libraries -p /Library/Extensions/Navi48Accel-0.0.6.kext -a x86_64`
6. Caricamento: `sudo kmutil load -p /Library/Extensions/Navi48Accel-0.0.6.kext`
7. Verifica: `ls -ld /Library/Extensions/Navi48Accel-0.0.6.kext`

NEVER `kmutil install --update-all` anche per questa versione.

    Kill switch at any time: boot-arg `navi48-aux=0` (both framebuffers refuse to start). The framebuffers also refuse to start with boot-arg navi48-metal-ws present.

Ordine di Run B (script PC): `fbhold 2`, `fbhold 1`, `fbpublish 2`, `fbpublish 1`, poi `killall -9 WindowServer` per far ripartire il desktop sui due monitor.

## 0.0.5 (G6, client `N48N` per app sandboxate)

Percorso nuovo nella directory `/Library/Extensions/`, con il nome versionato 0.0.5.

Step 4b:

1. Backup dell'AuxKC: `mkdir -p ~/navi48-backup/auxkc-pre-0.0.5 && sudo cp /Library/KernelCollections/AuxiliaryKernelExtensions.kc ~/navi48-backup/auxkc-pre-0.0.5/`
2. Copia: `sudo cp -R build/Navi48Accel.kext /Library/Extensions/Navi48Accel-0.0.5.kext && sudo chown -R root:wheel /Library/Extensions/Navi48Accel-0.0.5.kext`
3. Permessi: `sudo chmod -R go-w /Library/Extensions/Navi48Accel-0.0.5.kext`
4. Attributi: `sudo xattr -cr /Library/Extensions/Navi48Accel-0.0.5.kext`
5. Librerie: `sudo kmutil libraries -p /Library/Extensions/Navi48Accel-0.0.5.kext -a x86_64`
6. Caricamento: `sudo kmutil load -p /Library/Extensions/Navi48Accel-0.0.5.kext`
7. Verifica: `ls -ld /Library/Extensions/Navi48Accel-0.0.5.kext`

NEVER `kmutil install --update-all` anche per questa versione.

    Kill switch at any time: boot-arg `navi48-aux=0` (an 'N48N' open on the accelerator then returns kIOReturnUnsupported).

## 0.0.4 (M5, framebuffer del monitor B)

Percorso: `/Library/Extensions/Navi48Accel-0.0.4.kext` (NEW rispetto ai percorsi precedenti; l'id di bundle
`com.navi48.accelprobe` è lo stesso già approvato).

Nei passi seguenti usare il percorso `/Library/Extensions/Navi48Accel-0.0.4.kext` con la stessa sequenza di
backup, copia, permessi, librerie e `kmutil load -p` della sezione 0.0.5. Anche per questa versione vale
l'avviso: NEVER `kmutil install --update-all`. Step 4b.

## Avviso globale

NEVER `kmutil install --update-all` (see step 4b). Il comando ricostruisce l'intera collection e non è mai il
passo di installazione di questo kext.
