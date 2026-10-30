# Driver GPU completo per RX 9060 XT su macOS: requisiti e piano di copertura

Data della ricerca: **29 ottobre 2026**. Target del progetto: **Navi 44 / RX 9060 XT, RDNA 4, macOS x86_64**, inizialmente Tahoe 26.6.2 / 25G83.

Questo documento definisce cosa costruire, integrare e verificare. **Non certifica che il driver attuale possieda queste capacità.** Le caselle aperte rappresentano requisiti ancora da chiudere con evidenza, compresi quelli per cui esiste già codice parziale. Le sezioni di verifica sono una proposta ingegneristica per questo progetto, non una certificazione Apple o AMD.

## 1. Che cosa significa davvero «driver completo»

Un driver GPU è uno stack: comprende il controllo dell'hardware, la gestione della memoria e delle code, un compilatore di shader, le API grafiche e l'integrazione con il sistema operativo. Avere il desktop trasparente dimostra solo che una parte dello stack funziona.

L'obiettivo è **eseguire correttamente qualsiasi applicazione che rispetti il contratto delle API e delle capacità supportate**, senza doverla aggiungere a una lista di nomi o inventare uno shader sostitutivo per farla partire. I problemi riprodotti in un'app devono diventare test di una funzione generale: allocazione, sincronizzazione, compilazione, presentazione, ecc.

Nessun driver offre ogni API, ogni estensione e ogni funzione di qualsiasi GPU. «100%» deve avere un riferimento verificabile: hardware preciso, versioni delle API, profili, formati, limiti, versioni del sistema e suite di test. Anche il superamento di una suite non dimostra l'assenza matematica di ogni bug.

**Per questo progetto la completezza richiede:** copertura completa del profilo macOS concordato, sfruttamento documentato delle capacità della scheda, compatibilità generale delle API aggiuntive scelte, prestazioni misurate e gestione affidabile degli errori. Una capacità mancante richiesta dall'obiettivo rimane un lavoro aperto; restituire `false` evita un crash, ma non implementa quella capacità.

### I termini che si confondono più spesso

| Termine | Che cosa fa | Dove si colloca nel nostro progetto |
| --- | --- | --- |
| Driver kernel / KMD | Controlla GPU, memoria, code, interrupt, display e recupero dagli errori | Fondamenta indispensabili |
| Driver utente / UMD | Implementa API e prepara i comandi per la GPU | Metal e backend RADV nel disegno attuale |
| Metal | API Apple per grafica e calcolo | Percorso principale per macOS e le sue applicazioni |
| Vulkan | API grafica/calcolo multipiattaforma | Backend interno attuale e possibile API pubblica; i due risultati vanno verificati separatamente |
| OpenGL | API grafica desktop, usata anche da software meno recente | Serve un'implementazione e un'integrazione macOS dedicate |
| OpenGL ES / EGL | API grafica e gestione dei contesti/superfici, usate anche da livelli di compatibilità | Percorso distinto da OpenGL desktop |
| WebGL 1/2 | Grafica web basata su OpenGL ES | Implementata dal browser, che usa il suo backend grafico |
| WebGPU | API web per grafica e compute | Implementata dal browser, con backend come Metal o Vulkan |
| ANGLE | Traduce OpenGL ES verso API di piattaforma | Uno dei percorsi di Chromium/Brave per WebGL |
| Dawn / Tint | Implementazione WebGPU e compilatore WGSL usati nell'ecosistema Chromium | Consumatori del driver; non sostituiscono il driver hardware |
| SPIR-V / AIR / MSL | Rappresentazioni o linguaggi degli shader | Richiedono traduzione e compilazione corrette, non una semplice conversione di nomi |
| VideoToolbox / VCN | API video macOS / blocco hardware video AMD | Necessari per collegare la decodifica/codifica hardware alle app macOS |
| OpenCL | API di calcolo parallelo | Compatibilità aggiuntiva; su macOS Apple l'ha deprecata |
| ROCm / HIP | Piattaforma di calcolo AMD / ambiente e API di programmazione | Porting separato e ampio; Metal o Vulkan funzionanti non lo rendono disponibile automaticamente |
| CUDA | Ecosistema di calcolo NVIDIA | Non è una funzione nativa obbligatoria di una Radeon |
| Direct3D / DXVK / vkd3d | API Windows / livelli di traduzione | Compatibilità opzionale sopra lo stack; non requisito del desktop macOS |
| MPS / Core ML | Librerie e framework Apple per calcolo, immagini e modelli | Devono essere verificati sopra Metal; enumerare la GPU non prova che funzionino |

Riferimenti per questa distinzione: [RADV e divisione KMD/UMD](https://docs.mesa3d.org/drivers/radv.html), [Metal](https://developer.apple.com/documentation/metal), [ANGLE](https://chromium.googlesource.com/angle/angle/), [Dawn](https://dawn.googlesource.com/dawn/+/refs/heads/main/README.md), [matrice ROCm](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html).

## 2. Architettura da completare

Il percorso principale attualmente scelto nel repository è:

```text
App macOS / WindowServer / Core Animation / browser
                         |
                       Metal
                         |
               Navi48Metal: contratto Metal
                         |
          AIR -> metal2vulkan/n48xlate -> SPIR-V
                         |
               RADV: comandi e shader AMD
                         |
       winsys Darwin + ABI del client + driver kernel
                         |
        GPU Navi 44: GFX / SDMA / memoria / firmware
```

Il display e il video richiedono rami propri: **DCN e integrazione display macOS** per inviare i frame al monitor; **VCN e integrazione VideoToolbox** per i codec. La freccia Metal → Vulkan descrive la nostra architettura, non quella di tutti i driver Apple.

Un'app Vulkan potrebbe usare direttamente un ICD RADV esposto al loader. MoltenVK compie invece la traduzione Vulkan → Metal: aggiungerlo sopra questo stack può introdurre un giro Vulkan → Metal → Vulkan. Non risolve le lacune del nostro Metal e non deve essere usato come prova che l'ICD nativo è completo. [Loader Vulkan](https://docs.vulkan.org/guide/latest/loader.html), [architettura MoltenVK](https://github.com/KhronosGroup/MoltenVK).

### Regole di sviluppo generali

- [ ] **ARCH-01 — Eliminare l'ammissione per nome dell'app dal prodotto finale.** Accesso secondo identità, autorizzazioni e isolamento del sistema; le liste sperimentali possono rimanere soltanto negli strumenti di laboratorio.
- [ ] **ARCH-02 — Correggere contratti e strutture.** Vietare correzioni basate sul dominio del sito, sull'hash dello shader o sul nome della funzione per aggirarne la semantica.
- [ ] **ARCH-03 — Separare implementazione e diagnostica.** Nessun requisito di avvio con flag speciali, privilegi root o sandbox disabilitato per l'uso normale.
- [ ] **ARCH-04 — Rendere coerenti le capacità.** Una stessa funzione non può essere dichiarata disponibile a WindowServer e incompleta alle app senza un motivo contrattuale documentato e verificato.
- [ ] **ARCH-05 — Conservare gli errori reali.** Distinguere risorse esaurite, input non valido, capacità non implementata e GPU persa; nessun successo fittizio o immagine magenta al posto di un risultato valido.
- [ ] **ARCH-06 — Rendere riproducibile lo stack.** Versioni e hash di kext, ABI, bundle Metal, RADV, traduttore, firmware e cache devono essere registrati insieme.

Le applicazioni restano test utili. I workaround possono essere necessari anche in driver maturi, ma devono avere causa, ambito e test espliciti; non diventare l'architettura del progetto.

## 3. Contratto misurabile e inventario delle capacità

Una checklist scritta a mano non può enumerare in modo affidabile ogni metodo, formato e combinazione di una specifica. La copertura esaustiva deve essere ottenuta anche da inventari derivati dalle versioni fissate di SDK e specifiche. Apple organizza Metal per famiglie e capacità; Vulkan distingue proprietà, feature, estensioni, limiti e formati. [Famiglie Metal](https://developer.apple.com/documentation/metal/detecting-gpu-features-and-metal-software-versions), [tabelle Metal](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf), [query Vulkan](https://docs.vulkan.org/guide/latest/querying_extensions_features.html).

- [ ] **SPEC-01 — Inventario hardware reale:** PCI/subsystem/revisione, Navi 44, target compilatore, CU, VRAM, BAR, IP GFX/DCN/VCN/SDMA/SMU, connettori, VBIOS e firmware. Non derivarlo da una stringa di modello modificata.
- [ ] **SPEC-02 — Matrice piattaforma:** build macOS, architettura x86_64, SDK, ABI Apple usate, configurazioni bare metal e passthrough da qualificare separatamente.
- [ ] **SPEC-03 — Profilo Metal esplicito:** tutte le righe obbligatorie di Mac2; inventario delle funzioni Metal 3 e delle successive API applicabili, con verifica hardware/runtime. Metal 4 e famiglie Apple non si ottengono cambiando un getter.
- [ ] **SPEC-04 — Profilo Vulkan pubblico:** versione core, estensioni, feature e requisiti WSI da raggiungere; corrispondenza fra capacità di RADV upstream e capacità effettive del port Darwin.
- [ ] **SPEC-05 — Profili aggiuntivi:** OpenGL desktop, GLES/EGL, WebGL 1/2, WebGPU e OpenCL con versioni fissate; ROCm/HIP con un progetto di porting e criteri propri.
- [ ] **SPEC-06 — Registro leggibile dalla macchina:** creare `research/capabilities/gpu-capabilities.csv` con ID, riferimento alla specifica, obbligatorietà, hardware disponibile, implementazione, capacità dichiarata, test, esito, evidenza e versione provata.
- [ ] **SPEC-07 — Inventario completo delle entry point:** metodi Metal pubblici richiesti e SPI effettivamente consumati, entry point Vulkan/GL/CL scelti, compresi metodi ereditati e callback.
- [ ] **SPEC-08 — Inventario completo dei formati:** per formato registrare campionamento, filtro, render target, blend, storage, atomiche, MSAA/resolve, blit, vista, import/export e allineamenti.
- [ ] **SPEC-09 — Classificazione senza ambiguità:** `mancante`, `parziale`, `implementato non verificato`, `verificato`, `non applicabile per hardware/piattaforma`. Un requisito mancante non diventa non applicabile perché difficile.
- [ ] **SPEC-10 — Copertura contabile:** ogni riga obbligatoria deve avere una prova; fallimenti, test saltati e casi non classificati devono restare visibili. Nessuna percentuale «completo» ricavata contando metodi o caselle.

## 4. Fondamenta hardware e driver kernel

Il riferimento AMDGPU separa memoria, interrupt, ring, virtualizzazione degli indirizzi e blocchi hardware. Ne usiamo i contratti hardware come riferimento; le interfacce Linux DRM non sono direttamente le API di macOS. [Infrastruttura AMDGPU](https://docs.kernel.org/gpu/amdgpu/driver-core.html).

- [ ] **KMD-01 — Inizializzazione deterministica:** cold boot, riavvio, ingresso dopo altro OS; gestione dello stato ereditato e dei fallimenti parziali.
- [ ] **KMD-02 — PCIe e DMA:** BAR e ReBAR, mapping MMIO, indirizzi DMA, IOMMU quando presente, interrupt e ordine delle scritture corretti.
- [ ] **KMD-03 — Blocchi hardware:** inizializzazione e spegnimento ordinato di PSP/SMU, GFX, SDMA, interrupt hub, VM hub, DCN e VCN pertinenti alla scheda.
- [ ] **KMD-04 — Firmware:** selezione per IP/revisione, caricamento verificato e gestione delle versioni; nessuna assunzione che Navi 44 e Navi 48 siano intercambiabili.
- [ ] **KMD-05 — ABI utente/kernel:** dimensioni, allineamenti, versioni, compatibilità, copia sicura dei parametri e codici d'errore conservati.
- [ ] **KMD-06 — Validazione delle richieste:** handle, offset, dimensioni, overflow, permessi e proprietà delle risorse; nessuna lettura/scrittura arbitraria da un client.
- [ ] **KMD-07 — Concorrenza kernel:** locking, ordinamento, interrupt contro teardown, reference counting e assenza di use-after-free.
- [ ] **KMD-08 — Chiusura pulita:** rilascio dopo uscita normale, crash o terminazione forzata; nessuna DMA su pagine già liberate.

**Prova di chiusura:** cicli di apertura/chiusura, input malformati, inizializzazione interrotta e stress concorrente con controlli dell'integrità. Un test compute singolo non chiude questa sezione.

## 5. Memoria GPU e risorse

- [ ] **MEM-01 — Usare la VRAM disponibile:** budget e contabilizzazione reali; regioni riservate esplicite; limiti riportati coerenti con ciò che si può allocare.
- [ ] **MEM-02 — Memoria di sistema paginata:** mapping di liste di pagine per i normali dati applicativi; memoria fisicamente contigua solo dove l'hardware la richiede.
- [ ] **MEM-03 — Spazi virtuali per processo:** page table, VMID, map/unmap, TLB, protezioni e isolamento fra client.
- [ ] **MEM-04 — Residency e pressione:** budgeting, riuso, suballocazione, eviction/migrazione e paging ove richiesti dal contratto; errori OOM prevedibili senza bloccare il desktop.
- [ ] **MEM-05 — Semantica Metal Shared/Managed/Private:** coerenza CPU/GPU, `didModifyRange`, sincronizzazione dei readback, cache e flush/invalidate.
- [ ] **MEM-06 — Texture:** tiling/swizzle, pitch, mip, layer, cube/array/3D, viste e reinterpretazione ammessa; compressione interna e metadata quando utilizzati.
- [ ] **MEM-07 — Heap e aliasing:** dimensioni/allineamenti, risorse sovrapposte, transizioni e durata dei riferimenti.
- [ ] **MEM-08 — Import/export:** IOSurface, memoria host e risorse interprocesso, con proprietà, durata, offset, piani e permessi verificati.
- [ ] **MEM-09 — Nessuna perdita di dati:** inizializzazione quando richiesta dalle API e dai vincoli di sicurezza del consumatore; nessuna esposizione della memoria di altri processi.
- [ ] **MEM-10 — Limiti raggiungibili:** test di buffer piccoli/grandi, texture massime, frammentazione e grandi working set, senza dipendere dall'ordine casuale degli avvii.

**Prova di chiusura:** stress di allocazione/free/import, confronto dei dati CPU/GPU e prove in pressione. Un limite di 4 GiB dichiarato con allocazioni applicative molto più piccole che falliscono va spiegato e corretto, non accettato come supporto completo.

## 6. Code, scheduler e sincronizzazione

- [ ] **SCHED-01 — Più processi attivi:** virtualizzare o riciclare i contesti hardware; il numero di VMID fisici non deve diventare il limite fisso delle applicazioni apribili.
- [ ] **SCHED-02 — Più code per client:** grafica, compute e trasferimenti con dipendenze esplicite e ordine corretto.
- [ ] **SCHED-03 — Fairness e priorità:** mantenere interattivo il desktop sotto carico; evitare starvation e inversioni di priorità.
- [ ] **SCHED-04 — Preemption e timeout:** supporto coerente con hardware/firmware, identificazione del lavoro responsabile e limiti alle attese.
- [ ] **SCHED-05 — Invio asincrono:** batching, più frame in volo e notifiche di completamento; niente attesa CPU globale dopo ogni draw.
- [ ] **SYNC-01 — Barriere di memoria:** visibilità e ordine fra scritture/letture CPU, GFX, compute, SDMA e display.
- [ ] **SYNC-02 — Fence ed eventi:** rispettare il punto di encode, gli stage e lo scope; non trattare tutte le dipendenze come inizio/fine del command buffer.
- [ ] **SYNC-03 — Eventi condivisi:** timeline, listener, handle interprocesso e ciclo di vita, se richiesti dal profilo.
- [ ] **SYNC-04 — Hazard tracking:** distinguere risorse tracked/untracked e alias; implementare `useResource`/residency secondo il contratto scelto.
- [ ] **SYNC-05 — Completion ed errori:** callback una sola volta, timestamp affidabili, ordine degli handler, sblocco dei waiter anche dopo perdita della GPU.

**Prova di chiusura:** producer/consumer su code e processi differenti, risorse aliasate, sincronizzazione nello stesso buffer e carichi prolungati. Testare il risultato numerico, non soltanto che la chiamata ritorni. [Sincronizzazione Metal](https://developer.apple.com/documentation/metal/resource-synchronization).

## 7. Compilatore di shader e pipeline

Il traduttore AIR → SPIR-V e il compilatore SPIR-V → ISA AMD sono due componenti distinti. Il primo deve preservare il programma Metal; il secondo deve generare codice per l'ASIC corretto. [Pipeline RADV](https://docs.mesa3d.org/drivers/radv.html), [ISA pubblica RDNA 4](https://docs.amd.com/v/u/en-US/rdna4-instruction-set-architecture).

- [ ] **COMP-01 — Ingressi Metal:** librerie precompilate, compilazione da sorgente dove richiesta, selezione degli entry point, linking e costanti di funzione.
- [ ] **COMP-02 — ABI shader:** binding, strutture, layout, padding, matrici, vettori, puntatori, address space e reflection coerenti con le risorse effettive.
- [ ] **COMP-03 — Controllo del flusso:** branch, loop, switch, phi, chiamate e trasformazioni strutturali senza cambiare il risultato.
- [ ] **COMP-04 — Semantica numerica:** FP16/FP32, interi, conversioni, NaN/Inf, signed zero, denormal, arrotondamento e fast-math secondo profilo; FP64 soltanto dove effettivamente richiesto/supportato.
- [ ] **COMP-05 — Immagini e sampler:** coordinate, LOD, gradienti/derivate, gather, compare, fetch, read/write e multisample.
- [ ] **COMP-06 — Compute:** dimensioni del dispatch, gruppi parziali, memoria locale, atomiche, barriere e operazioni SIMD/subgroup.
- [ ] **COMP-07 — Interfaccia fra stage:** attributi, interpolazione, built-in, clip/cull, uscite multiple, depth/stencil e dual-source blending.
- [ ] **COMP-08 — Funzioni avanzate:** argument buffer, indirizzi GPU e binding indiretti; tessellation, mesh, ray tracing e function pointer secondo la matrice applicabile.
- [ ] **COMP-09 — API di pipeline:** creazione sincrona/asincrona, reflection, errori, archivi/cache e tutte le opzioni che possono cambiare il programma.
- [ ] **COMP-10 — Cache affidabile:** chiavi comprendenti codice, opzioni, device e versioni; operazioni atomiche, concorrenza, invalidazione e accesso nei sandbox normali.
- [ ] **COMP-11 — Tempi e memoria limitati:** rispettare i vincoli del sottoprogetto metal2vulkan, attualmente 20 s e 500 MiB per tentativo; aggiungere obiettivi più severi per i percorsi interattivi.
- [ ] **COMP-12 — Risultato corretto:** validazione SPIR-V più esecuzione e confronto con un riferimento; uno SPIR-V valido può comunque calcolare un risultato sbagliato.

**Prova di chiusura:** corpus sintetico per feature e combinazioni, test differenziali, fuzzing e regressioni dei casi reali ridotti a riproduttori generali. Nessun fallback magenta considerato un successo.

## 8. Metal: rendering, compute e oggetti API

Questa sezione va espansa automaticamente usando SDK e tabelle Metal fissati in SPEC. Rispondere a un selettore o ereditare un metodo non dimostra di implementarne la semantica.

- [ ] **MTL-01 — Oggetti e ABI:** device, library, function, pipeline, queue, command buffer, encoder, risorse, errori e callback, con firme e durata corrette.
- [ ] **MTL-02 — Geometria:** vertex descriptor, formati e stride, draw indicizzati/non indicizzati, istanze, offset, primitive e viewport/scissor.
- [ ] **MTL-03 — Rasterizzazione:** winding/culling, clipping, profondità, stencil, depth bias, raster order e tutte le modalità richieste.
- [ ] **MTL-04 — Colore e blending:** write mask, MRT, blend indipendente, fattori Source1, precisione e conversioni lineare/sRGB.
- [ ] **MTL-05 — Render pass:** clear/load/store/discard, resolve, MSAA colore e depth/stencil, combinazioni e pass senza allegati dove consentiti.
- [ ] **MTL-06 — Texture e sampler:** tutti i formati obbligatori, BC quando previsto, viste, array, cubemap, filtri, anisotropia e addressing.
- [ ] **MTL-07 — Blit:** copie buffer/texture, righe/piani, mipmap, fill, sincronizzazione e readback.
- [ ] **MTL-08 — Compute generale:** dispatch diretti/indiretti, threadgroup memory, limiti, atomiche e cooperazione fra thread.
- [ ] **MTL-09 — Argument buffer e indirizzi GPU:** tier dichiarato realmente eseguibile, encoder, array e residency; indirizzi stabili e validi per la durata prevista.
- [ ] **MTL-10 — Lavoro indiretto:** draw/dispatch indiretti e indirect command buffer secondo disponibilità; nessuna factory ereditata non funzionante dietro un getter positivo.
- [ ] **MTL-11 — Query:** occlusion, contatori e timestamp richiesti, reset/availability e risultati effettivi.
- [ ] **MTL-12 — Risorse avanzate:** sparse, memoryless, heap di placement e risorse condivise soltanto quando applicabili; capacità mancanti censite esplicitamente.
- [ ] **MTL-13 — Funzioni moderne della scheda:** piano verificato per tessellation, mesh/object shader, ray tracing/acceleration structure, librerie dinamiche e funzioni collegate ove esposte dal target.
- [ ] **MTL-14 — API più recenti:** inventario distinto per Metal 3/4, compiler, argument table e nuovi modelli di comando; non dedurre il supporto dal nome commerciale della GPU.
- [ ] **MTL-15 — Coerenza delle query:** famiglia, limiti, sample count, formato e feature devono concordare fra tutte le entry point e con le prove.

**Prova di chiusura:** test per ciascuna riga obbligatoria del profilo e per le combinazioni, con immagini/readback confrontati. I tier degli argument buffer hanno conseguenze reali sul binding e sul lavoro CPU. [Tabelle Metal](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf), [argument buffer](https://developer.apple.com/documentation/metal/managing-groups-of-resources-with-argument-buffers).

## 9. Integrazione macOS, compositor e condivisione

- [ ] **MAC-01 — Registrazione del device:** IORegistry, acceleratore, associazione display/GPU e selezione da Metal; proprietà coerenti di GPU discreta, memoria e display.
- [ ] **MAC-02 — Compatibilità ABI Apple:** classi basi, metodi ereditati, oggetti condivisi e SPI realmente necessari verificati sulla build supportata.
- [ ] **MAC-03 — IOSurface interprocesso:** import/export, alias, use-count, lifetime, lock, planes, cache e sincronizzazione di producer/consumer.
- [ ] **MAC-04 — WindowServer/Core Animation:** composizione di finestre, effetti, maschere, ombre e superfici offscreen con aggiornamenti corretti anche senza movimento del mouse.
- [ ] **MAC-05 — CAMetalLayer e drawable:** acquisizione, più frame in volo, resize, presentazione, rilascio e gestione dell'occlusione; niente riciclo prima che rendering e scanout siano conclusi.
- [ ] **MAC-06 — AppKit/SwiftUI/MetalKit:** percorsi standard per viste, finestre e contenuti accelerati senza preparazione per singola app.
- [ ] **MAC-07 — Core Image e framework di calcolo:** filtri, compilazione e reflection richieste; verificare MPS/MPSGraph con risultati numerici e risorse reali.
- [ ] **MAC-08 — Cattura e accesso remoto:** screenshot, registrazione e condivisione dello schermo, eventuali display virtuali, senza alterare il normale scanout.
- [ ] **MAC-09 — Sessioni:** login/logout, blocco/sblocco, cambio utente e riavvio dei processi grafici, con rilascio delle risorse.
- [ ] **MAC-10 — Sandbox normale:** cache, compilazione, import e apertura dei client funzionanti con le autorizzazioni standard; niente disabilitazione globale della sicurezza del browser.

**Prova di chiusura:** desktop e app eterogenee contemporaneamente, cattura e cambio sessione; controllare assenza di reset, corruzione e crescita persistente delle risorse. Il contratto dei drawable include il completamento del lavoro prima della presentazione. [Drawable Metal](https://developer.apple.com/library/archive/documentation/3DDrawing/Conceptual/MTLBestPracticesGuide/Drawables.html).

## 10. Display, refresh, colore e uscita video

La pipeline display deve essere corretta anche se il rendering offscreen lo è già. Il riferimento DC AMD distingue programmazione del display, sincronizzazione e gestione colore. [Display Core](https://docs.kernel.org/gpu/amdgpu/display/index.html).

- [ ] **DISP-01 — Connettori e monitor:** EDID, modalità realmente supportate, DisplayPort/HDMI, hotplug e link training.
- [ ] **DISP-02 — Cambio modalità reale:** risoluzione, pixel clock, timing e refresh; implementare **2560×1440 a 60 Hz effettivi**, oltre alla modalità 120 Hz, con ritorno sicuro.
- [ ] **DISP-03 — Vblank e flip:** scheduling della presentazione, latch, fence e durata dei buffer; evitare tearing, frame parziali e riuso precoce.
- [ ] **DISP-04 — Aggiornamenti parziali:** damage/dirty region, resize e riuso delle superfici senza bande nere o rettangoli non ridisegnati.
- [ ] **DISP-05 — Cursore:** posizione, hotspot, formato, composizione e aggiornamento del cursore hardware/software.
- [ ] **DISP-06 — Colore:** gamma/LUT, ICC, conversione RGB/YCbCr e full/limited range; formati 8/10 bit ove disponibili.
- [ ] **DISP-07 — HDR/EDR e VRR:** implementare le capacità realmente supportate da scheda, collegamento, monitor e sistema; non dichiararle in base al solo EDID.
- [ ] **DISP-08 — Più display:** routing, desktop esteso/mirror, refresh differenti, cambio del principale e spostamento delle finestre.
- [ ] **DISP-09 — Funzioni del collegamento:** DSC/MST e altre modalità soltanto se applicabili; registrare supporto hardware e stato implementativo.
- [ ] **DISP-10 — Ciclo energetico:** spegnimento/riaccensione del monitor, sleep/wake e ripristino del link e dei contenuti.

**Prova di chiusura:** pattern temporali e di colore, sequenze di frame identificabili e verifiche sul monitor. Un numero «60 Hz» nelle proprietà senza cambio dei timing non soddisfa DISP-02. I test a 60 Hz sono diagnostica e una modalità da supportare; non autorizzano a considerare risolto un difetto ancora presente a 120 Hz.

## 11. Video: decodifica, codifica e presentazione

Grafica 3D, decodifica del codec e presentazione del video sono tre cose diverse. La presenza della GPU in Metal o la voce `Video Decode: enabled` del browser non provano che VCN decodifichi quel filmato. VideoToolbox offre una proprietà per interrogare il decoder hardware effettivamente selezionato. [Verifica hardware decode](https://developer.apple.com/documentation/videotoolbox/kvtdecompressionpropertykey_usinghardwareacceleratedvideodecoder), [capacità generali RDNA](https://www.amd.com/en/technologies/rdna.html).

- [ ] **VID-01 — Inventario VCN:** IP, firmware, ring, memoria, sessioni, codec e limiti hardware specifici di Navi 44.
- [ ] **VID-02 — Matrice codec:** per H.264, HEVC, VP9 e AV1 verificare separatamente decode/encode, profilo, livello, bit depth, chroma, risoluzione, fps e numero di stream; supportare dove l'hardware e la piattaforma lo consentono.
- [ ] **VID-03 — Gestione del motore:** avvio/arresto, sessioni concorrenti, timestamp, riferimenti fra frame, stream corrotti e recupero.
- [ ] **VID-04 — VideoToolbox:** integrazione nel percorso che macOS usa davvero per scoprire e impiegare decoder/encoder; identificazione della GPU e interrogazione dell'uso hardware.
- [ ] **VID-05 — CoreVideo/IOSurface:** CVPixelBuffer, texture condivise, formati NV12/P010 ove pertinenti, piani, pitch e sincronizzazione senza copie evitabili.
- [ ] **VID-06 — Rendering del video:** conversione YUV/RGB, scaling, deinterlacciamento ove richiesto, colore/HDR e sincronizzazione audio/video.
- [ ] **VID-07 — Encode:** bitrate, qualità, keyframe, latenza, flush e cattura schermo; verificare risultati e uso del blocco hardware.
- [ ] **VID-08 — Streaming reale:** seek, pause/resume, fullscreen, picture-in-picture, stream multipli e contenuti 24/25/30/50/60 fps.
- [ ] **VID-09 — Vulkan Video:** supporto e test distinti se si espone anche questa API; non equivale a integrare VideoToolbox.
- [ ] **VID-10 — Contenuti protetti:** documentare requisiti e limiti di DRM, HDCP e servizi; nessuna promessa che il solo driver abiliti FairPlay o servizi soggetti a requisiti ulteriori.

**Prova di chiusura:** frame confrontati con riferimenti, contatori hardware/VideoToolbox, CPU e frame persi misurati su clip locali ripetibili. Un video sorgente 30 fps deve riprodursi a 30 fps: un display 120 Hz non crea fotogrammi aggiuntivi.

## 12. Vulkan come API pubblica

Il backend Vulkan usato internamente da Metal non è automaticamente un driver Vulkan distribuibile alle applicazioni. Occorrono loader/ICD, interfacce, presentazione e qualificazione. [Loader](https://docs.vulkan.org/guide/latest/loader.html), [Vulkan CTS](https://github.com/KhronosGroup/VK-GL-CTS/blob/main/external/vulkancts/README.md).

- [ ] **VK-01 — ICD e loader:** discovery, manifest, entry point, dispatch, versioni e coexistence con altre implementazioni.
- [ ] **VK-02 — Contratto core:** ogni funzione obbligatoria della versione scelta, più estensioni dichiarate, formati, limiti e feature effettivamente attivate.
- [ ] **VK-03 — Winsys Darwin completo:** memoria, submit, sincronizzazione, fault e multiclient coerenti con le attese di RADV.
- [ ] **VK-04 — WSI macOS:** creazione della superficie, swapchain, acquire/present, resize, ricreazione dopo perdita/out-of-date, modi di presentazione e colori supportati.
- [ ] **VK-05 — Interop:** memoria/semafori esterni e collegamento con IOSurface/Metal dove esposti; niente handle di compatibilità fittizi.
- [ ] **VK-06 — Feature avanzate:** descriptor indexing/buffer address, sparse, mesh, ray tracing, atomiche e altre estensioni secondo hardware e versione scelta.
- [ ] **VK-07 — Debug e diagnostica:** validation layer utilizzabili, informazioni fault e oggetti nominabili senza interferire con la release.
- [ ] **VK-08 — Conformità:** esecuzione della mustpass CTS pertinente, report completo e gestione dei fallimenti; conformità ufficiale dichiarabile solo secondo il processo Khronos.

## 13. OpenGL desktop, OpenGL ES ed EGL

OpenGL desktop e WebGL non sono sinonimi. Zink può implementare OpenGL sopra Vulkan, ma il port macOS e l'integrazione con il percorso delle applicazioni vanno realizzati e verificati: non basta compilare Mesa. Apple considera OpenGL/OpenCL tecnologie deprecate, comunque da trattare esplicitamente se si vuole coprire il software che le usa. [Zink](https://docs.mesa3d.org/drivers/zink.html), [indicazioni Apple](https://developer.apple.com/documentation/apple-silicon/porting-your-macos-apps-to-apple-silicon).

- [ ] **GL-01 — Percorso macOS delle app:** definire come servire i contesti CGL/NSOpenGL richiesti e la loro integrazione con finestre e superfici; una libreria GL privata non sostituisce automaticamente OpenGL.framework.
- [ ] **GL-02 — Versioni e profili:** coprire quelli richiesti dalle app macOS, compreso il percorso legacy pertinente; un eventuale OpenGL 4.6 via Mesa è un obiettivo separato dalle API Apple disponibili alle app esistenti.
- [ ] **GL-03 — Implementazione completa:** stato, GLSL, texture/FBO, draw, query, sync, buffer mapping e sharing di contesti secondo versione.
- [ ] **GL-04 — GLES/EGL:** contesti, configurazioni, superfici e scambio immagini; non dedurli dal successo di un contesto desktop.
- [ ] **GL-05 — Architettura senza cicli:** confrontare Zink → RADV con eventuali altri percorsi; evitare dipendenze circolari GL → Metal → Vulkan → GL.
- [ ] **GL-06 — Qualificazione:** CTS OpenGL/GLES/EGL e test dei contesti/superfici macOS sul percorso effettivamente usato dalle app.

## 14. WebGL, WebGPU e browser

Il browser implementa le API web sopra il backend selezionato. ANGLE traduce OpenGL ES; Dawn implementa WebGPU. Dobbiamo soddisfare quei contratti e verificarli nel sandbox, senza scrivere un «driver per vorssaint». [ANGLE](https://chromium.googlesource.com/angle/angle/), [Dawn](https://dawn.googlesource.com/dawn/+/refs/heads/main/README.md).

- [ ] **WEB-01 — WebGL 1 e 2:** shader, texture, framebuffer, readback, estensioni e context loss/recovery; usare le suite Khronos, non una sola demo.
- [ ] **WEB-02 — WebGPU:** adapter/device, WGSL, compute/render, buffer mapping, limiti, error scope e device lost; verificare il backend effettivo e il CTS.
- [ ] **WEB-03 — Canvas/compositor/raster:** coprire anche i percorsi 2D, Skia e condivisione delle immagini fra processi, distinti da WebGL/WebGPU.
- [ ] **WEB-04 — Sandbox e processi:** nessun requisito di avviare il browser con `--no-sandbox`, forzature globali GPU o pulizia manuale delle cache a ogni aggiornamento.
- [ ] **WEB-05 — Avvio e riavvio:** il processo GPU deve sopravvivere al carico, liberare i client dopo crash e non ricadere continuamente nel renderer software.
- [ ] **WEB-06 — Motori diversi:** qualificare Chromium/Brave, WebKit/Safari e Firefox con percorsi e limiti osservati, senza assumere che usino tutti ANGLE o Dawn.
- [ ] **WEB-07 — Prove generali più regressioni:** CTS, scene 2D/3D/compute e video; siti reali come vorssaint restano regressioni di integrazione, non criteri unici di completezza.

**Prova di chiusura:** [WebGL CTS](https://github.com/KhronosGroup/WebGL) e [WebGPU CTS](https://github.com/gpuweb/cts), immagini/readback, frame time e stato del processo GPU prima/durante/dopo. Una pagina `gpu` verde è diagnostica, non prova sufficiente di correttezza o velocità.

## 15. Compute, AI, OpenCL, ROCm e compatibilità aggiuntive

### Calcolo macOS e librerie Apple

- [ ] **CALC-01 — Metal compute completo:** kernel, riduzioni, scan, matrici, immagini, precisioni e grandi dataset, con correttezza numerica e tempi misurati.
- [ ] **CALC-02 — MPS/MPSGraph:** testare operazioni rappresentative e percorsi realmente selezionati; distinguere libreria disponibile e kernel eseguiti sulla nostra GPU.
- [ ] **CALC-03 — Core ML:** verificare quali modelli/backend possono usare la GPU, con output e profiling; nessuna equivalenza automatica con Neural Engine o capacità Apple silicon.
- [ ] **CALC-04 — Librerie/app compute:** qualificare backend Metal e Vulkan di carichi come elaborazione immagini e inferenza; usare test ripetibili, non nomi ammessi nel driver.

MPS è un framework di kernel ottimizzati sopra Metal; perciò il suo funzionamento è un requisito di integrazione, non una seconda GPU da implementare. [Panoramica Metal e framework collegati](https://developer.apple.com/documentation/metal).

### OpenCL

- [ ] **CL-01 — Runtime e integrazione:** scegliere versione/profilo, compiler, discovery e percorso delle applicazioni; verificare se servire l'interfaccia Apple, un ICD separato o entrambi.
- [ ] **CL-02 — Contratto completo:** memoria, immagini, eventi, code, atomiche, math e interop; tutte le feature obbligatorie del profilo e solo quelle opzionali effettivamente implementate.
- [ ] **CL-03 — Backend:** valutare un port di Rusticl/Mesa o altra implementazione riusabile senza presumere supporto macOS già pronto.
- [ ] **CL-04 — Conformità:** eseguire OpenCL CTS e test delle applicazioni sul runtime distribuito.

[Apple OpenCL](https://developer.apple.com/opencl/), [Rusticl](https://docs.mesa3d.org/drivers/rusticl.html), [OpenCL CTS](https://github.com/KhronosGroup/OpenCL-CTS).

### ROCm / HIP

La matrice AMD consultata riguarda Linux e Windows: **non fornisce un percorso ufficiale ROCm macOS per questo progetto**. Un port richiederebbe molto più del driver grafico. Non lo considero già ottenuto né una dipendenza di YouTube/WebGL. [Compatibilità ufficiale ROCm](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html).

- [ ] **HIP-01 — Studio del port macOS:** separare dipendenze da KFD/HSA/Linux, runtime, ABI, loader e supporto del compilatore per Navi 44.
- [ ] **HIP-02 — Primitive runtime:** caricamento dei code object, code compute, memoria, copie, eventi, atomiche e gestione degli errori; memoria condivisa/faulting solo se implementabile nel contratto scelto.
- [ ] **HIP-03 — Toolchain HIP:** compilazione host/device per macOS x86_64 e ISA corretta, linking, librerie device e diagnostica.
- [ ] **HIP-04 — Librerie:** BLAS, FFT, primitive parallele e librerie ML desiderate, ciascuna con test e misure; non promettere PyTorch accelerato perché un kernel HIP elementare funziona.
- [ ] **HIP-05 — Qualificazione:** test del runtime e delle librerie, correttezza e prestazioni; documentare come port sperimentale finché non qualificato.

### Estensioni dell'ecosistema

- [ ] **EXT-01 — Direct3D:** se richiesto, qualificare Wine/DXVK/vkd3d sopra le capacità Vulkan/Metal ottenute; Windows non diventa macOS per effetto del driver.
- [ ] **EXT-02 — CUDA/SYCL/altre API:** trattare eventuali livelli compatibili come progetti separati, con copertura e limiti espliciti; CUDA non è il backend hardware nativo della Radeon.
- [ ] **EXT-03 — Ray tracing e AI hardware:** mappare le funzioni pubblicamente esponibili dei blocchi RDNA 4 in Metal/Vulkan/compute e verificarne l'uso; non confondere il supporto del silicio con quello del runtime.
- [ ] **EXT-04 — Scaling e frame generation:** FSR/MetalFX o altri SDK sono consumatori dello stack; qualificare quelli applicabili, senza presentarli come prerequisiti di un draw corretto.

Queste voci tengono visibile l'ambizione di sfruttare la scheda. Non sono tutte prerequisiti del desktop macOS, e non vanno usate per nascondere lacune delle fondamenta.

## 16. Energia, sensori, affidabilità e prestazioni

### Gestione della scheda

- [ ] **PWR-01 — Clock e potenza:** prestazioni dinamiche, transizioni idle/carico, power gating e limiti termici con policy adatte a Navi 44.
- [ ] **PWR-02 — Sensori reali:** temperatura GPU/hotspot/memoria dove disponibili, clock, potenza, utilizzo, VRAM e RPM; unità, validità e freschezza verificabili.
- [ ] **PWR-03 — Esportazione macOS:** un solo proprietario delle letture hardware e pubblicazione stabile per strumenti di monitoraggio/VirtualSMC; nessuno zero inventato per un sensore mancante.
- [ ] **PWR-04 — Ventole e protezioni:** firmware e driver devono conservare una policy sicura; controlli manuali soltanto se implementati e qualificati.
- [ ] **PWR-05 — Sleep/wake/shutdown:** arresto delle code e della DMA, ripristino dei blocchi e corrette transizioni energetiche; coordinamento con ACPI/PCIe.

Riferimento: [controlli energetici e termici AMDGPU](https://docs.kernel.org/gpu/amdgpu/thermal.html).

### Errori e sicurezza

- [ ] **REL-01 — Hang detection:** distinguere shader lento, deadlock, pagina non valida, fence persa e motore fermo.
- [ ] **REL-02 — Recovery:** recupero per motore/contesto o reset secondo hardware; notificare la perdita del device e terminare tutte le attese dipendenti.
- [ ] **REL-03 — Contenimento:** un'app in errore non deve corrompere altri client; se il reset globale interrompe il compositor, gestirlo e documentarlo senza chiamarlo isolamento completo.
- [ ] **REL-04 — Telemetria utile:** submission, contesto, motivi di fault, memoria, clock, tempi CPU/GPU e presentazione, con overhead contenuto e log limitati.
- [ ] **REL-05 — Test avversi:** input malformati, cancellazione durante GPU work, process death, pressione di memoria e concorrenza; nessuna esposizione cross-process.
- [ ] **REL-06 — Recovery di installazione:** rollback coerente dell'intero stack e compatibilità fra versioni, senza avviare kernel/bundle con ABI incompatibili.

Il modello Linux distingue responsabilità kernel e user space nella propagazione dei reset: è un riferimento architetturale, non codice da trasferire alla cieca in XNU. [Device reset](https://github.com/torvalds/linux/blob/master/Documentation/gpu/drm-uapi.rst).

### Prestazioni misurate

- [ ] **PERF-01 — Individuare il collo di bottiglia:** separare compilazione, invio CPU, attesa code, esecuzione GPU, trasferimenti, decoder e presentazione.
- [ ] **PERF-02 — Cache fredda e calda:** misurare separatamente la prima apertura e l'uso successivo; riportare il peggior caso oltre alla media.
- [ ] **PERF-03 — Ridurre il lavoro superfluo:** copie, allocazioni per frame, serializzazione, polling e compilazioni duplicate; ottimizzazioni ammesse solo a risultato invariato.
- [ ] **PERF-04 — Frame pacing:** P50/P95/P99, massimo, frame persi e latenza; non limitarsi agli fps medi.
- [ ] **PERF-05 — Concorrenza reale:** desktop, browser, video e compute contemporanei; registrare CPU, GPU, clock, memoria e temperature.
- [ ] **PERF-06 — Confronti onesti:** stessa scheda con driver maturo su altro OS per test hardware equivalenti; Mac supportato per semantica Metal. Separare differenze di API, compiler, risoluzione e carico.
- [ ] **PERF-07 — Budget per workload:** fissare soglie prima del test; per animazioni 60 fps il budget è circa 16,67 ms, a 120 fps circa 8,33 ms. Non ogni carico può raggiungerli a qualsiasi qualità.
- [ ] **PERF-08 — Assenza di regressioni:** ogni modifica deve mostrare correttezza e prestazioni della suite di riferimento, non soltanto un punteggio migliore in un'app.

## 17. Prove necessarie per accettare una release

Le suite ufficiali sono una base, da affiancare alle prove specifiche di macOS e dell'hardware. [VK-GL-CTS](https://github.com/KhronosGroup/VK-GL-CTS), [WebGL CTS](https://github.com/KhronosGroup/WebGL), [WebGPU CTS](https://github.com/gpuweb/cts).

| Area | Evidenza richiesta |
| --- | --- |
| Metal | Inventario SDK/profilo chiuso, test semantici con readback/immagini e prove framework; nessuna presunta certificazione pubblica Metal equivalente al CTS Khronos |
| Vulkan | CTS per versione/estensioni dichiarate, log completi, validation layer e WSI; distinguere test locali e riconoscimento ufficiale |
| GL/GLES/EGL | CTS pertinenti e verifica del percorso di contesto/superficie macOS |
| WebGL/WebGPU | CTS sul browser distribuito con backend e renderer registrati |
| Shader | Test di traduzione, validazione ed esecuzione differenziale; input non supportati e timeout tracciati |
| Memoria/scheduler | Pressione, frammentazione, molti client, più code, isolamento, teardown e failure injection |
| Display | Modalità reali, sequenze temporali, hotplug, sleep/wake, colore e più monitor |
| Video | Clip locali note, codec/profilo documentati, selezione hardware e qualità/frame pacing |
| Performance | Tracce CPU/GPU/display, benchmark equivalenti e budget espliciti |
| Affidabilità | Soak test e cicli di avvio/sessione/energia con inventario degli errori |

- [ ] **TEST-01 — Harness riproducibile:** build, test, acquisizioni e report senza preparazione manuale per ciascuna app.
- [ ] **TEST-02 — Oracoli indipendenti:** confronti numerici/immagini con tolleranze motivate e riferimenti non prodotti dallo stesso bug.
- [ ] **TEST-03 — Completezza dei risultati:** totale, pass, fail, skip e non eseguibili; un test che manca del loader o non trova il device non è passato.
- [ ] **TEST-04 — Qualificazione continuativa:** fissare un primo ciclo di 24 h di carico misto e 20 cicli di boot/sessione/energia, estendendolo ai difetti osservati. Sono soglie iniziali del progetto, non garanzie assolute.
- [ ] **TEST-05 — Artefatto verificabile:** manifest, sorgenti/patch, hash dei binari, hardware/OS, comandi, log, risultati e problemi aperti.
- [ ] **TEST-06 — Accettazione:** nessuna riga obbligatoria incompleta, nessun errore noto nei percorsi promessi, capacità dichiarate coerenti e prestazioni entro i budget concordati.

## 18. Dove siamo oggi: evidenze e lacune

Questa è una lettura delle prove disponibili nel repository, **non un nuovo collaudo completo della macchina**. Le osservazioni storiche vanno associate alla propria build; una modifica presente nei sorgenti non è necessariamente installata.

| Ambito | Evidenza disponibile | Che cosa non dimostra |
| --- | --- | --- |
| Desktop Metal | L'utente riferisce trasparenze/animazioni funzionanti; restano flash e stutter | Completezza Metal, display e sincronizzazione |
| Browser | Il test temporaneo `brave-trial7.json` riporta feature GPU attive ma solo 3 callback di animazione in circa 16 s | Rendering fluido o corretto; neppure quel contatore da solo localizza il guasto |
| Shader | Correzioni generali di cache, MSAA e dual-source in sviluppo; test locali presenti | Copertura del compilatore e di tutte le pipeline |
| Memoria | Prove recenti mostrano import host riusciti e altre allocazioni GTT fallite | Gestione generale della pressione e grandi working set |
| Multiclient | Il passaggio a otto sessioni ha ampliato il bring-up | Uno scheduler capace di virtualizzare i contesti per un normale desktop |
| Contratto Metal | Il sorgente conserva differenze di capacità fra app e WindowServer e percorsi parziali | Correttezza delle famiglie/tier esposti; serve un audit aggiornato, non il solo census dei selector |
| Display | Modalità corrente documentata a 120 Hz; prova fisica a 60 Hz ancora richiesta | Che basti modificare una proprietà per cambiare frequenza |
| Video | Stutter segnalato e statistiche browser | Decodifica hardware VCN/VideoToolbox funzionante per ciascun codec |
| Altre API | RADV è impiegato internamente | Vulkan pubblico, GL desktop, OpenCL o ROCm qualificati |

Evidenze locali: [prove cache/MSAA](research/reports/gpu_cache_msaa_trial_20261029.md), [audit storico Metal](research/reports/metal_selector_audit.md), [test browser/CPU/audio/sensori](research/reports/native_browser_sensors_audio_20261028.md), [test browser trial7, artefatto locale](research/builds/macos-20261029/dual-source-candidate/brave-trial7.json). L'audit del 13 ottobre è utile per identificare aree da ricontrollare, non per attribuire oggi gli stessi difetti a ogni build.

## 19. Ordine di realizzazione per ottenere uno stack generale

| Fase | Risultato da consegnare | Condizione per procedere |
| --- | --- | --- |
| A — Contratto | Inventario hardware/API, registro capacità e baseline riproducibile | Nessuna capacità obbligatoria senza classificazione e test pianificato |
| B — Fondamenta | Memoria paginata, multiclient, scheduler, sincronizzazione, isolamento e recovery | Stress indipendente dalle app e rilascio corretto delle risorse |
| C — Metal | Compilatore e runtime conformi al profilo, metodi/query/risorse coerenti | Test semantici completi del profilo scelto, senza ammissione per nome |
| D — macOS/display | Compositor, IOSurface, drawable, modalità 60/120 Hz e ciclo energetico | Desktop generale stabile e frame presentati correttamente |
| E — Video/browser | VCN/VideoToolbox e backend standard dei browser | Codec e CTS web verificati, nessuna ricaduta software sistematica |
| F — API e compute | ICD Vulkan pubblico, GL/GLES/EGL, OpenCL, framework compute | Suite e integrazione di ciascun percorso chiuse |
| G — Capacità avanzate | Feature hardware moderne e port ROCm/HIP se incluso nel prodotto finale | Evidenza separata per ogni feature/runtime; nessuna equivalenza presunta |
| H — Qualificazione | Prestazioni, soak, packaging e rollback | Matrice del prodotto finale chiusa e report pubblicabile |

Le fasi possono sovrapporsi quando indipendenti. B e C risolvono classi di problemi che riemergerebbero in molte app: non va sostituita questa base con una serie infinita di correzioni per i singoli programmi. Completare D o E non significa aver completato F o G.

## 20. Audio, Bluetooth, Wi-Fi, CPU e sensori della piattaforma

Restano nell'obiettivo complessivo del PC, con driver e criteri separati. L'audio DisplayPort/HDMI è invece collegato anche alla funzione audio della GPU e alla sua pipeline display.

- [ ] **PLAT-01 — Jack analogico posteriore:** identificare il codec reale, inizializzare controller/codec, routing e pin, esportare l'uscita in CoreAudio; verificare canali, volume, frequenze, hotplug e sleep/wake.
- [ ] **PLAT-02 — Audio DP/HDMI:** enumerazione del dispositivo e capacità del sink, sincronizzazione e hotplug, se questa uscita è richiesta.
- [ ] **PLAT-03 — Qualcomm Bluetooth:** firmware/transport USB, pairing e sicurezza, HID della tastiera, riconnessione, sleep/wake e stabilità; il collegamento al telefono non prova l'intero stack.
- [ ] **PLAT-04 — Qualcomm Wi-Fi:** connessione, throughput, risparmio energetico e integrazione macOS del modulo integrato, senza sostituirlo implicitamente con altro hardware.
- [ ] **PLAT-05 — AirDrop/Continuity:** verificare anche il percorso Wi-Fi/AWDL e l'integrazione di sistema; Bluetooth acceso da solo non basta. La diagnosi locale documenta lacune ancora aperte.
- [ ] **PLAT-06 — CPU Ryzen:** compatibilità XNU, topologia, timer, scheduler e CPPC/power management; distinguere patch del kernel, presentazione CPUID e veri driver. Un kext non sostituisce automaticamente il supporto CPU nel bootstrap.
- [ ] **PLAT-07 — Sensori CPU/scheda madre:** acquisizione e unità corrette, Super I/O identificato, mappa tensioni/ventole e plugin SMC; evitare conflitti fra due gestori energetici.
- [ ] **PLAT-08 — Spegnimento reale:** diagnosticare cause ACPI/USB/PCIe/wake/firmware e dimostrare che dopo shutdown il PC rimane spento; non attribuirlo automaticamente alla GPU.
- [ ] **PLAT-09 — Collaudo integrato:** rete, Bluetooth HID, audio, carico CPU/GPU e ciclo energetico contemporanei, con log e regressioni.

Per le evidenze correnti di queste aree vedere [diagnosi locale audio/CPU/sensori](research/reports/native_browser_sensors_audio_20261028.md) e [diagnosi wireless](research/reports/wcn785x_wireless_diagnosis_20261027.md). Questa sezione conserva le richieste, senza dichiarare risolti i componenti che hanno soltanto un candidato in staging.

## 21. Regola per dichiarare concluso il progetto

**Un driver completo è un insieme di contratti implementati e verificati, non un elenco di log verdi o un'app che finalmente parte.** Ogni requisito deve rimandare a codice, versione, test ed evidenza sulla macchina target. Le funzioni hardware/piattaforma non disponibili vanno motivate; le funzioni desiderate ancora da creare restano aperte. Il documento non autorizza installazioni né richiede un riavvio: definisce il lavoro da discutere e poi eseguire.
