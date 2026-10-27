# Revisione del prossimo passo bare metal Navi44 — 2026-10-27

## Raccomandazione

Il prossimo stadio **effettivo** è PSP SOS (numero 5), ma non raccomando di eseguirlo ancora. I target 2–4, secondo l'ordine di avvio nel sorgente attuale, non avviano `runStages()` e ripetono soltanto la discovery stage1: sarebbero un falso avanzamento. Il target 5 esegue invece `stagePSP()`, che mappa BAR0, prova finestre VRAM con scrittura/ripristino, scrive dati in VRAM e invia la catena firmware al PSP.

Il kext storico usato per stage1 non ha il watchdog. La build macOS 27/10 lo contiene, ma il codice avvia il watchdog **dopo** `stagePSP()` e dopo ogni `runStages()` invocato da `stagePSP()`. Quindi per stage5 il watcher arriva a operazione conclusa; per target superiori anche la ladder è già passata prima dell'avvio. La guardia `bringup_to()` non sostituisce questo avvio: `n4xs::refused()` legge il livello, inizializzato `kLevelOk`, mentre `gRunning` è inizialmente zero. Stage5 non passa da quella guardia né dalla verifica delle protezioni SMU.

Per ora terrei l'hardware allo stato stage1. Un passo diagnostico separato, da valutare e autorizzare prima di distribuirlo, sarebbe la build watchdog solo a stage1 per verificare il sensore `THM_TCON_CUR_TMP` sul bare metal; questo non rende stage5 protetto. Prima di un futuro stage5 serve rivedere l'ordine/gate nel codice affinché una lettura iniziale valida e un watchdog attivo precedano la prima scrittura, oltre a validare la lettura contro BIOS/Linux. Non ho modificato o distribuito nulla.

## Prove del percorso e log

- La ladder enumera `1 IPDiscovery`, `2 IHInit`, `3 GMCInit`, `4 PSPInit`, `5 PSPLoadSOS`, `6 PSPRingCreate`, `7 TMRSetup`, `8 PSPFwLoad`, `9 SMUInit`, poi IMU/RLC/CP/MES/GFX/SDMA/PM4/compute. ([enum](../builds/macos-20261027/src/cobalt64/src/navi48-bringup/src/amd/amdgpu_init.h:33))
- `start()` legge il target, chiama `stagePSP()` e solo dopo chiama `n4xs::start()`. `stagePSP()` si attiva con `navi48-psp=1` o `navi48-stage>=5`; se SOS riesce, `runStages(target)` viene chiamata solo per `target>5`. ([entry](../builds/macos-20261027/src/cobalt64/src/navi48-bringup/src/Navi48Bringup.cpp:7394), [PSP](../builds/macos-20261027/src/cobalt64/src/navi48-bringup/src/Navi48Bringup.cpp:573))
- Conseguenza pratica: stage2–4 non eseguono IH/GMC/PSPInit nella logica corrente; target5 esegue PSP SOS senza `runStages`; target6+ esegue PSP e poi rientra nella ladder da IHInit. Non saltare direttamente a target6.
- Risultato bare metal corrente: il report del 27/10 registra stage1 `survey-readonly`, 42 IP e MMIO verified; il display resta su `IONDRVFramebuffer`, senza accelerazione provata. Il report termico macOS dà CPU, RX e protezione termica `UNKNOWN`.
- L'esito storico di stage5 è positivo solo nel percorso macOS in VM con RX passthrough: PSP preflight READY, SOS alive, sign-of-life `0x26c1f8ad`; nessun interrupt/compute/Metal. Il report dice che la console VMware era esterna alla RX. Non prova stage5 bare metal. ([VM progress](navi44_bringup_progress.md:41))

Per un futuro test stage5, registrare `PSP,Stage`, `PSP,LastStep`, `PSP,LastStatus`, `PSP,ContainerSOSVersion`, `PSP,VramMCBase` e `PSP,FwPriMC`. Il successo specifico è `PSP,Stage=sos-alive` più `psp-stage: SUCCESS — SOS alive (sign-of-life ...)`. Fermarsi a qualsiasi `no-bar0`, `no-vram-region`, `aperture-mismatch`, `bad-container`, `bad-fwpri`, `preflight-refused` o `chain-failed`; raccogliere lo stato e non provare un altro stage nello stesso boot. A stage5 non aspettarsi `Navi48,StageResult`: `runStages()` non viene chiamata.

Un target superiore deve riportare `Navi48,StageReachedName`, `Navi48,StageResult=0` e i relativi marker di ogni stadio, ma non è il prossimo esperimento. La cronologia VM riporta guasti/riavvii mentre GMCInit (stadio3) riprogramma MMHUB con la console sulla GPU; inoltre successivi test stage17 hanno avuto fault spontanei. Mantenere il display della scheda fuori dal percorso di prova.

## Confronto kext e termica

| Kext | SHA-256 binario | Stato | Implicazione |
|---|---|---|---|
| Storico stage1 `d186c77f…3f3a22846d` | `d186c77f925aed420425149be7bb04059d3e6e8a7fb3d758d345afbf3a22846d` | Versione Info.plist 0.0.664; il report di sicurezza dice che precede il watchdog. L'UUID caricato sul boot stage1 coincide con quello dell'artefatto candidato, ma l'hash della EFI live non fu letto in quella raccolta. | Non ha watchdog; `navi48-safety=1` non aggiungerebbe codice assente. È l'unico binario provato in questa sessione bare metal, limitatamente a stage1. |
| Build macOS 27/10 `bf8f7fcb…3fb18ae6` | `bf8f7fcb8fe2c9791b5337dfa25cfd468fef667870594548df8a9ab3ffb18ae6` | Build locale Navi44, x86_64, firma ad hoc/verifiche statiche passate; include `n4x_safety.o`, ma non ha prova runtime bare metal. Versione plist uguale 0.0.664 non significa equivalenza. | Watchdog predefinito ON nel profilo Navi44, soglie default warn 75 °C/trip 80 °C; nel codice parte troppo tardi per stage5. Il bundle ha anche cinque blob shader opzionali vuoti, dettaglio in `BUILD_REPORT.md`. |
| Build watchdog precedente `cb18a1f9…28d5` | hash abbreviato dal report storico | Il report `gpu_safety.md` descrive sensore plausibile e protezioni presenti in boot con la scheda reale, nel percorso test documentato come VM/host-watchdog. | Non equivale alla prova bare metal corrente e il watchdog host QMP ferma una VM, non un macOS bare metal. Il trip a 80 °C non è mai stato testato. |

La safety build legge `THM_TCON_CUR_TMP` ogni 250 ms, produce heartbeat e fail-closed con TRIP se il sensore manca; da sola non spegne il sistema e non controlla ventole/clock. I dati 33–39 °C documentati con `cb18...` appartengono a boot precedenti; non sono misure della sessione macOS corrente. Anche il precedente picco 304 W/86 °C è un'osservazione storica di un altro percorso, non la temperatura attuale.

Se in futuro si valuta il nuovo watchdog, a stage1 controllare `N4X-SAFETY event=START sensor=THM_TCON_CUR_TMP`, heartbeat con hotspot plausibile e assenza di `no-sensor`, `START-FAILED` o `TRIP`; confrontare la lettura con BIOS/Linux prima di attribuirle validità. A stage1 `proto=0` può essere atteso perché SMUInit non è stato eseguito, quindi non spacciarlo per protezioni SMU verificate. Per un vero stage5 gate, thread attivo non basta: attendere almeno una lettura valida e richiedere esplicitamente stato non-TRIP prima della prima scrittura.

La telemetria macOS attuale non dà CPU/GPU °C (`macos_thermal_safety_20261027.md:3-15`). Prima di qualunque PSP load: abilitare la iGPU Raphael nel firmware, collegare lì il monitor, verificare la via di recupero Linux e avere una lettura termica attendibile. Mantenere interrupt disabilitati, nessun aux/Metal/compute, un solo stadio per boot. Se compare WARN (75 °C), TRIP (80 °C), sensore non valido, assenza di heartbeat, errore PSP, perdita/corruzione display o hang, arrestarsi: il watchdog kext non termina macOS e il watchdog host documentato è solo per VM.

## File consultati

- [`first_gpu_test_plan.md`](first_gpu_test_plan.md)
- [`navi44_bringup_progress.md`](navi44_bringup_progress.md)
- [`navi44_stage1_baremetal_result_20261027.md`](navi44_stage1_baremetal_result_20261027.md)
- [`gpu_safety.md`](gpu_safety.md)
- [`macos_thermal_safety_20261027.md`](macos_thermal_safety_20261027.md)
- [`BUILD_REPORT.md`](../builds/macos-20261027/BUILD_REPORT.md)

Esame limitato a documenti e codice Cobalt64 locale; nessun test, build, lettura sensore, accesso GPU, distribuzione o modifica EFI eseguiti.
