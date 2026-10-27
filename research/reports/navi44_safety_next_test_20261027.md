# Preparazione del prossimo test Navi44 — 27 ottobre 2026

## Contesto

Il test bare metal stage1 è riuscito; non sono stati dimostrati Metal o accelerazione. Nella logica di avvio qui analizzata un target `navi48-stage=2`, 3 o 4 non avvia una nuova fase della ladder: `stagePSP()` non fa nulla fino a 5 e `runStages()` è chiamato soltanto dopo il successo della PSP e per target >5. Il target 5 avvia PSP SOS; coinvolge mapping BAR0, verifica dell'apertura con scrittura/ripristino in VRAM e scritture al mailbox PSP. Non è un test read-only. Perciò non è stato preparato o distribuito un avvio stage5 come se fosse pronto.

## Problema riscontrato e prototipo

La build `bf8f7fcb…` con watchdog precedentemente disponibile chiama `stagePSP()` prima di avviare `n4xs::start()`. Non si può sostenere che il watchdog protegga la fase PSP iniziale, né che la successiva ladder sia protetta dall'inizio. Il bundle storico `d186c77…` provato in stage1 non include il watchdog.

Nella copia isolata `research/builds/macos-20261027/desktop-prep/navi44-psp-safety-candidate/` ho preparato una modifica sperimentale:

- Il monitor viene inizializzato prima del setup opzionale degli interrupt e di `stagePSP()`; la configurazione candidata mantiene gli interrupt disattivati.
- Prima di entrare in `stagePSP`, il kext attende fino a 2 s e rifiuta se il watchdog non è in esecuzione, il campione non è valido o OK, oppure ha più di 1 s. Timestamp e ammissibilità sono pubblicati in un'unica variabile atomica per evitare di combinare parti di campioni diversi. La freschezza di 1 s è una scelta sperimentale, non una garanzia di protezione termica.
- Il thread usa una copia stabile del puntatore BAR5 e ne verifica l'intervallo all'avvio; non legge più i campi mutabili del contesto dispositivo. In arresto aspetta che il worker pubblichi il completamento delle letture MMIO prima di consentire lo smontaggio BAR5: se il worker fosse bloccato può ritardare lo spegnimento indefinitamente, con messaggi periodici. Questo non è un join rigoroso del thread: l’epilogo del worker potrebbe ancora eseguire codice del kext dopo la pubblicazione.
- Il gate è **solo all'ingresso**: non impedisce che la temperatura cambi immediatamente dopo, né interrompe una catena PSP già iniziata. Non è una protezione termica completa, né un meccanismo di spegnimento. Il decoder THM è ancora da confrontare con una fonte indipendente sulla stessa GPU.

Il build x86_64 `APPLE_ROUTE=0`, firma ad hoc e `kmutil libraries` sono passati. Test host mirati verificano la decisione per sensore invalido, watchdog fermo, WARN/TRIP, campioni scaduti e clock incoerente; non simulano l'hardware o la concorrenza reale. Come nella build precedente, cinque shader opzionali sono stub vuoti. Nessuna prova runtime della modifica è stata fatta.

## Candidata di osservazione: ancora stage1

Solo in staging è pronta `research/ext/navi44-safety-observe-20261027/EFI/`: conserva la EFI stage1 già avviata, sostituisce il solo binario `Navi48Bringup` con la successiva build sperimentale IOWorkLoop e aggiunge `navi48-safety=1`. Il codice IOWorkLoop e i suoi limiti sono in `research/reports/navi44_ioworkloop_safety_candidate_20261027.md`; il precedente prototipo con thread sopra resta conservato separatamente. Sono conservati `navi48-stage=1`, `navi48-interrupts=0` e `-amd_no_dgpu_accel`; non sono aggiunti `navi48-psp`, Metal o framebuffer. Manifest 31/31, `ocvalidate` 1.0.8, firma e `kmutil libraries` passano. SHA-256 del binario `7b96f043266f96cf479aee9b60d551da8f1d60563e164db11b67d3dddf86c658`.

La candidata non è stata copiata su OCBOOT o avviata. L'attuale OCBOOT resta la stage1 storica già testata; il backup pre-test è sulla chiavetta da 128 GB. La differenza tra candidate sono un boot-arg e il binario kext; il vecchio file e la sua config restano nello staging stage1.

## Raccolta e criteri

`python3 tools/baremetal/observe_navi44_safety.py` raccoglie boot args, proprietà Navi48 e log di questo boot, senza leggere direttamente registri GPU. Può non leggere `dmesg` senza ticket sudo; in quel caso conserva il motivo e usa anche unified log. Non certifica sicurezza: in assenza di heartbeat restituisce UNKNOWN (exit 2); anche con heartbeat marca la temperatura e l'effetto protettivo UNKNOWN. Verificato sul boot attuale con kext storico: nessun heartbeat, exit 2.

Per la prova futura di osservazione attendere un esplicito avvio: verificare che il UUID binario caricato sia quello della candidata, stage1 e IRQ=0, cercare `N4X-SAFETY event=START` e heartbeat nei log; riportare temperatura, raw, WARN/TRIP e stabilità senza benchmark. `proto=0` significa che le protezioni firmware non sono state dimostrate, non che siano assenti. Qualsiasi assenza di campioni o discordanza con una lettura indipendente impedisce di usare il sensore per autorizzare PSP. Preparare recupero dei log e ripristino prima del boot.

Non passare a stage5 sulla base della sola build o di questa guardia: servono verifiche runtime del teardown IOWorkLoop, ulteriore revisione della concorrenza, validazione della misura e un piano per la perdita di video/recupero. Anche con quelle verifiche un gate iniziale non rende la PSP interrompibile.

## Backup del boot stage1 riuscito

Dopo il reboot i numeri dispositivo sono cambiati: OCBOOT è `disk3s1` (prima `disk4s1`) e la chiavetta personale è `disk4s1`. Non usare numeri diskN memorizzati per future scritture: individuare volume e UUID a ogni sessione. OCBOOT è stata montata read-only e tutti i suoi 31 file EFI sono stati confrontati con il manifest stage1. La copia integrale verificata della stage1 riuscita è ora su `/Volumes/Untitled 1/macOS-Tahoe-25G83-installer/OCBOOT-stage1-success-20261027.tar`, SHA-256 `2beaea0412c6fc3e4681a65b5703a24f435f7201a32f44936e5e299d389f78f2`, oltre al backup del boot pre-stage1. OCBOOT è stata smontata; non sono stati modificati file EFI.
