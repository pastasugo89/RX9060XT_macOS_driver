# P0 headless Metal: esito del 21 ottobre 2026

## Stato: P0 eseguito due volte (boot22 e boot23). Tutti i test P0 conformi; T1 è il valore atteso del sorgente

Boot18-23 nella VM di test (Tahoe 26.6.2 / 25G83, RX 9060 XT, stage 17, `navi48-metal=1`, `navi48-aux=1`, `N4X_GPU_PRIMARY=0`).
Boot23 (ultimo) è stato spento con `sudo -n /sbin/shutdown -h now`: nessun panic, `vfs_unmountall(system) end`, QEMU uscito, `qemu-img check` senza errori.
La EFI P1 è stata rigenerata e verificata (`N4X_GPU_PRIMARY=1 ... --check` superato), ma non avviata: il monitor è spento.

## Esiti per test (boot23, ultimo misurato)

| Test | Esito | Note |
|---|---|---|
| T0 device | PASS | `AMD Radeon RX 9060 XT`, registryID `0x10000046e`. Il primo `list` subito dopo il publish del nub ha visto 0 device; il secondo 1 device |
| T1 census | 81 coppie (classe, selettore) mancanti, valore atteso | Lista identica riga per riga al boot22 (`research/hw_dump/p0_boot23/t1.txt`). Il criterio «0» del piano era errato: vedi sotto |
| T2 hot-swap | PASS | `fallback -> real`; quad esatto (0 pixel diversi) 1,08 s dopo l'installazione; il command buffer in volo resta sul fallback. Sorgente: cache del demone `/private/var/tmp/n48m-spv`, vedi nota |
| T3 triangolo | PASS (exact) | 0 di 65536 pixel diversi contro il riferimento CPU calcolato in-process (primo tentativo) |
| T3 quad | PASS (exact) | 0 di 65536 pixel diversi (primo tentativo) |
| T4 compute | PASS | `PASS qccompute (0)` (primo tentativo; nel boot22 servì il terzo) |
| T5 chiavi WindowServer | N/A | WindowServer non avviato in P0 |
| T6 riproducibilità | già fatto (21/10, 70/70) | |
| T7 WindowServer headless | N/A | P2 |

## T1: classificazione dei 81 selettori (decisione: nessuna regressione nostra)

Il census (`test-census.m`, `Navi48Device.m` +load) conta, per ogni classe del bundle, i selettori dei protocolli Metal che la classe non implementa (`class_respondsToSelector`). Il valore «0» del piano non può essere raggiunto da un bundle che non implementa tile, ICB, function table, tessellation, sparse, argument buffer: il census è una diagnosi di copertura, non una rete di compatibilità (lo dice il commento in `research/reports/metal_selector_audit.md` §2B).

Confronto con lo snapshot Cobalt64 importato (`e0665b4`): l'insieme delle implementazioni in `Navi48Device.m` è identico, salvo due differenze.
- `lazyInitialize` cambia da `void` a `BOOL` (`MTLIOAccelDevice`, forward declaration e override). Non è un protocollo che il census scansiona, quindi non modifica il conteggio.
- `productName` usa la macro `N48M_PRODUCT_NAME` (profilo ASIC), già in HEAD.

`test-census.m` differisce da Cobalt64 solo per l'ancora del testo di `+load`. Il census è deterministico su sorgente e SDK: con lo stesso SDK 25G83, Cobalt64 produrrebbe lo stesso insieme (inferenza statica, Cobalt64 non è stato buildato né eseguito qui).

Famiglie dei 81 (conteggio da `t1.txt`, 79 required e 2 optional):

| Famiglia | N | Esempi |
|---|---:|---|
| tile / imageblock | 20 | `setTileBuffer:…`, `dispatchThreadsPerTile:`, `tileWidth` |
| function table / binary function | 18 | `setFragmentVisibleFunctionTable…`, `newVisibleFunctionTableWithDescriptor:`, `functionHandleWithName:` |
| ICB / indirect / parallel encoder | 15 | `executeCommandsInBuffer:…`, `copyIndirectCommandBuffer…`, `drawPrimitives:indirectBuffer:…`, `dispatchThreadgroupsWithIndirectBuffer:…` |
| counter / sampling | 6 | `sampleCountersInBuffer:…`, `resolveCounters:…` |
| argument buffer / resource id / remote | 6 | `gpuResourceID` (texture, sampler, pipeline), `newRemoteBufferViewForDevice:` |
| altro | 5 | `setDepthTestMinBound:maxBound:`, `setVertexAmplificationCount:viewMappings:`, `setStageInRegion:` |
| tessellation / patch | 4 | `drawPatches:…`, `setTessellationFactorBuffer:…` |
| compute reflection / validation | 4 | `reflection`, `requiredThreadsPerThreadgroup`, `shaderValidation`, `allocatedSize` |
| sampler arrays | 3 | `setFragmentSamplerStates:lodMinClamps:…` |

Gap noti del build (argument buffers, `Metal3=0`, tile, sparse) sono quasi tutti dentro queste famiglie. Due voci non erano nell'elenco dei gap noti: le draw e dispatch indiretti (`drawIndexedPrimitives:…indirectBuffer:`, `drawPrimitives:indirectBuffer:`, `dispatchThreadgroupsWithIndirectBuffer:`), e il render encoder parallelo. Sono gap reali dello stesso sorgente Cobalt64, non regressioni nostre: vanno registrati come lavoro futuro.

Criterio aggiornato in `research/reports/metal_deploy_plan.md` §8.3: `census: 81 selector(s) missing in all`, con la lista che deve coincidere con `research/hw_dump/p0_boot22/t1-census.txt` (e `p0_boot23/t1.txt`). STOP: una coppia (classe, selettore) non presente nella lista di riferimento.

Nessuna modifica al codice per T1.

## T2: controllo del nome

`cobalt64/tools/native/mtlprobe/mtlprobe.m`, `cmd_hotswap`: il gate accettava solo `9070`. Ora accetta i nomi dei profili ASIC `9060` o `9070` (`n48_asic.h`). Nessuna opzione nuova.

Nota: il sorgente di default (`--spv-src`, bundle `Contents/Resources/spvcache`) non contiene gli `.spv` degli shader del quad (`8c8b25d8…`, `c9f593d3…`): il primo tentativo ha fallito con `source … not found`. Il quad li usa a runtime dalla cache del demone (`/private/var/tmp/n48m-spv`), e con quella sorgente il test passa. Per T2 si usa `--spv-src /private/var/tmp/n48m-spv`.

## T3: riferimento del triangolo

Il quad calcola il riferimento in-process (`cmd_quad`, CPU). Il triangolo leggeva `expected.raw`, che non esisteva nel pacchetto. Ora `tri_reference` calcola il riferimento in-process con la stessa logica: vertici NDC di `cmd_triangle`, viewport di default, centro pixel dentro il triangolo → `(1.0,0.8,0.0,1.0)`, altrimenti colore di clear `(0.0,0.2,0.4,1.0)`.

Verifiche:
- Python (`numpy`) e C (`clang`, funzione estratta): 0 pixel diversi tra loro.
- Contro il PNG reale della GPU nel boot22 (`research/hw_dump/p0_boot22/out-triangle.png`): 0 di 65536 pixel diversi. Colori unici nel PNG: `(0,51,102)` e `(255,204,0)`.
- Nessun centro pixel entro 0,04 px da un lato: nessuna ambiguità di bordo.
- Boot23, primo tentativo: PASS (exact).

`--expected <raw>` resta disponibile e sostituisce il riferimento in-process solo se passato esplicitamente.

## Panic al restart (boot21): causa non determinata, nessuna modifica

Evidenze, da `/mnt/vm/images/macos-gpu-test/diagnostics/serial-p0-boot21-panic-on-reboot.log` (6406 righe):
- Sequenza: `shutdown -r` alle 12:57:23 → `vfs_unmountall(system) end` → `MACH Reboot` → `Restart all drivers` (PMRD) → `IOPlatformHaltRestartAction -> AppleSMC` → `Debugger called: <panic>`, poi `Nested panic detected - entry count: 2`.
- Panic annidato: `Ticket lock 0xffffff8016968580 is unexpectedly owned by thread 0xffffff8c5b682a90 @lock_ticket.c:155`.
- La stringa del panic primario non è nel seriale, e non ci sono backtrace.
- Dopo l'inizio dello shutdown non compare nessuna riga `Navi48Bringup` o `Navi48Accel`, né in restart né in halt.

Lettura del nostro codice (`cobalt64/src/navi48-bringup`, `cobalt64/tools/native/navi48accel`):
- Il kext non ha handler di halt/restart (`kIOMessageSystemWillRestart` e simili assenti).
- Il kext aux registra un power driver (`Navi48Framebuffer::initForPM`, `registerPowerDriver`).
- Restano thread kernel di polling avviati con `kernel_thread_start` (`navi48_dcn.cpp`, `AppleHardwareHook.cpp`).
- Lo shutdown logga `Kext unloading now disabled`: il teardown dei nostri kext non gira durante il reboot.

Conclusione: il panic è avvenuto nel percorso di restart della piattaforma (PMRD, SMC). Il coinvolgimento dei nostri thread o lock non si può escludere né provare senza backtrace. Non è riprodotto: boot22 a freddo OK, boot23 spento con `-h` senza panic. Nessuna correzione applicata: una modifica senza causa dimostrata sarebbe speculativa.

Raccomandazioni: nel guest di test usare sempre `shutdown -h` (come da comando utente). Se un restart è necessario, raccogliere `/Library/Logs/DiagnosticReports/` e il seriale completo prima.

## Modifiche fatte

- `cobalt64/tools/native/mtlprobe/mtlprobe.m`: T2 (gate `9060`/`9070`), T3 (`tri_reference` in-process). Nessun commit.
- `research/reports/metal_deploy_plan.md` §8.3: criteri T1, T2, T3 aggiornati.
- `research/hw_dump/p0_boot23/`: evidenze del boot23 (`p0_boot23.sha256`).
- `/mnt/vm/images/macos-gpu-test/test-plan.json`: `latest_p0_result` (boot23), `previous_p0_result` (boot22), `status`.
- `/mnt/vm/builds/metal-stack-20261021-p0b/`: pacchetto nuovo, copia di `metal-stack-20261021` con `mtlprobe` ricompilato e `SHA256SUMS` aggiornato (il pacchetto originale è invariato).

## Artefatti nuovi (sha256)

| Artefatto | sha256 |
|---|---|
| `cobalt64/tools/native/mtlprobe/mtlprobe.m` (modificato) | `417f0d82025c41c569a63486b84e1ca8585bdb0b71510b3cf3b681e9fda559a2` |
| `mtlprobe` universale x86_64+arm64, build VM 25G83 | `3177783fcb9f0dcb5ceaf3b01f90d279a4f80fd3e528a7c97d521d04e4d75b70` |
| `metal-stack-20261021-p0b/SHA256SUMS` | `9f88e87fa2647f04fe75f887724be3f61f82ee570e89555a9e48e99cf12f3465` |
| seriale boot23 (`serial_p0_boot23_shutdown.log`) | `2b4d6795488cfe09d6756a8ae579ca2d662c98e6f14c8766d906fd8fafb22145` |
| EFI P1 (`efi_sha256` in `test-plan.json`) | `a412c4dcf24e5e15bbece45d73d73f11906c409d3f2933fe90bcbfe8706bd620` |

Invariati: bundle `Navi48Metal.bundle` (sha del binario `7edf8e31…`, verificato sul guest), kext aux `4d5e257d…`, `n48nub` (`d64a430c…`).

## Operazioni sul guest e sull'host (boot23)

- Build VM: avviata, `mtlprobe` ricompilato con `build.sh` (rc 0, 14 warning preesistenti), copiato sull'host (sha verificato). Spenta con QMP `quit` dopo `sync` nel guest: `system_powerdown` non ha spento il guest, che non ha `sudo` per lo shutdown. `qemu-img check` senza errori.
- Test VM: EFI P0 rigenerata (stage 17, `--native-s1b --metal --csr-active-config 3`), check OK, avvio con `N4X_GPU_ROMBAR=1`. BAR0 a 256 MiB e MEMLOCK 16 GiB verificati prima dell'avvio.
- Deploy: il primo `--deploy` ha sostituito il bundle e copiato `mtlprobe`, poi si è fermato su `cp … n48nub: Permission denied` (file `root:wheel`, residuo di un deploy precedente, contenuto identico). Sul guest: `sudo -n /usr/sbin/chown test ~/n48-metal/n48nub`. Poi `--deploy --accel-resume --yes`: `DEPLOY_OK`.
- Il deploy richiede `--yes` (o la conferma digitata): la conferma interattiva non funziona via pipe né here-string, perché `guest_reachable` consuma lo stdin con `ssh` e `read` riceve EOF. Non è stato modificato lo script (vedi blocchi).
- Il guest è stato spento con `sudo -n /sbin/shutdown -h now`.

## Blocchi incontrati

- Nessun blocco sull'host: BAR0 a 256 MiB, MEMLOCK 16 GiB, KVM e DISPLAY presenti.
- `deploy-metal-stack.sh --deploy` senza `--yes` esce in silenzio su pipe/here-string (`guest_reachable` consuma stdin). Correzione possibile: `ssh -n` in `guest_reachable`. Non applicata.
- `n48nub` root-owned dopo un deploy precedente: il deploy fallisce a metà e lascia il bundle già sostituito. Serve un passo di pulizia (`chown`), perché `sudo` nel guest non consente `rm`.
- `system_powerdown` via QMP non spegne la VM di build (non c'è sessione utente né `sudo` per lo shutdown): serve `quit` dopo `sync`.
- Il primo `mtlprobe list` dopo il publish del nub restituisce 0 device: serve un secondo tentativo o un'attesa.
- Il bundle `spvcache` non contiene gli shader del quad: il hot-swap va alimentato dalla cache del demone (vedi T2).

## Evidenze

- `research/hw_dump/p0_boot23/`: `t0.txt`, `t1.txt`, `t2-hotswap.txt` (PASS), `t2-first-attempt-bundle-spvcache-fail.txt` (primo tentativo, sorgente sbagliata), `t3-triangle.txt`, `t3-quad.txt`, `t4-compute.txt`, `guest_state_before_shutdown.txt`, `serial_p0_boot23_shutdown.log`, `deploy_attempt1_failed_nub_permission.out`, `deploy_attempt2_accel_resume.out`, `guest_t0_first_attempt_zero_devices.txt`, `p0_boot23.sha256`.
- `research/hw_dump/p0_boot22/`: evidenze del boot22 (invariate).
- Boot21 (panic): `/mnt/vm/images/macos-gpu-test/diagnostics/serial-p0-boot21-panic-on-reboot.log`.

## P1 (preparata, NON avviata)

- EFI P1 rigenerata: stage 17, `--native-s1b --metal --primary --metal-disp`, `csr-active-config = 0x03`, `amfi_get_out_of_my_way=1`, kext `navi48-full`, `N4X_GPU_PRIMARY=1`. `N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1 tools/vm/start-gpu-test-vm.sh --check` superato.
- Non avviare finché il monitor è spento: il GOP richiede il monitor acceso per vedere il DP.

## Sequenza successiva

1. Monitor acceso sul DP (utente), poi boot P1 con `N4X_GPU_PRIMARY=1 N4X_GPU_ROMBAR=1`.
2. Confronto T1 census già fatto: 81 atteso, lista di riferimento boot22/boot23.
3. P2 (WindowServer): solo dopo P1.
4. Gap per lavoro futuro: draw e dispatch indiretti, render encoder parallelo, argument buffer (vedi T1).
