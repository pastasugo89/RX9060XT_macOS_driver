# Preparazione desktop accelerato RX 9060 XT — 27 ottobre 2026

## Situazione e perimetro

Nelle prove VM P0 il rendering e il compute semplici sono riusciti, ma nei boot P2 44–47 WindowServer non ha prodotto command buffer/frame misurati per la pipe nonostante il compositor Metal risultasse attivo nel boot47. Non c'è ancora evidenza di desktop accelerato funzionante. Il Mac bare metal non ha caricato questi kext; nessuna delle candidate qui sotto è stata installata o provata sull'hardware.

## Framebuffer: frequenza VBL

Nei log boot46 il timer VBL di RDNA4FB è stato armato a 6945 µs, derivato dal preferred EDID (~144 Hz), mentre la modalità esposta e il timing GOP documentato in quelle prove erano ~120 Hz. La differenza è un difetto di coerenza, ma non dimostra che sia la causa di zero frame. Inoltre il codice Navi44 dichiara un timing 2560x1440/120 specifico delle prove VM: occorre ancora dimostrare che esso corrisponda allo scanout del macOS bare metal. Allineare al valore pubblicato non verifica il monitor fisico né sincronizza il timer all'IRQ hardware.

Ho creato una copia separata in `research/builds/macos-20261027/desktop-prep/RDNA4FB-vbl-candidate/`. Quando VBL è richiesto (`rdna4-vbl=1`), la candidata usa il refresh 16.16 riportato da `getInformationForDisplayMode` per la modalità corrente, limita la conversione a 30–240 Hz e conserva il precedente fallback EDID/default se il modo non è disponibile. La conversione usa aritmetica intera a 64 bit e arrotonda al microsecondo. La candidata aggiunge log limitati ai primi tre inviti della callback e ai cambi di stato dell'interrupt, per distinguere un timer armato da callback effettivamente invocate. Non è una misura di fase hardware né prova che le callback siano consumate.

Verifiche offline: `vbl_period_test.cpp` compila con `-Wall -Wextra -Werror` e passa per 30/60/120/240 Hz e valori invalidi; `make -j2` per x86_64 riesce, firma ad hoc `codesign --verify --deep --strict` e `kmutil libraries` passano. SHA-256 dell'eseguibile finale `e32eae72420a1b53244b9027b9e603848b3dbd91575cc3d6e5fc205fd8a9ef69`. Il solo warning compilazione è quello C su `-fapple-kext`. Log nella cartella `desktop-prep`. Non è stato caricato; non corregge i limiti noti del modo hardcoded né garantisce frame o flip.

## Bundle Metal rilocabile

Creata la copia `research/builds/macos-20261027/desktop-prep/Navi48Metal-portable.bundle`: `libn48xlate.dylib` ha ora install ID `@rpath/libn48xlate.dylib` anziché un percorso assoluto nello staging Cargo; dylib e bundle sono rifirmati ad hoc e `codesign --verify --deep --strict` passa. Il plugin carica già la dylib tramite percorso ottenuto dalle risorse: questa modifica rimuove un riferimento non portabile, senza dimostrare che `dlopen` o il runtime Metal funzionino. Confronto contenuti: stessi 75 file, differiscono la dylib, l'eseguibile del bundle rifirmato e la firma delle risorse. Non è stato installato né eseguito.

## Prossime verifiche

1. Rendere leggibile l'EFI reale e creare un backup completo verificato; il mount OCBOOT è in sola lettura ma il contenuto del config non risponde, quindi le candidate locali non dimostrano la configurazione effettiva.
2. Preparare recupero video/accesso indipendente, baseline e monitoraggio adatto; le temperature GPU/CPU bare metal non sono state validate, e il watchdog esterno della vecchia VM non è presente su questo Mac.
3. Prima prova su richiesta dell'utente: discovery separata e controllata; solo dopo procedere progressivamente con headless Metal e display. Per il desktop misurare la modalità fisica effettiva, la chiamata/consumo VBL, i command buffer, le transazioni e il flip, senza assumere che un solo cambiamento risolva il percorso.
