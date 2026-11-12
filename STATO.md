> **English summary:** [`docs/STATUS.md`](docs/STATUS.md) gives the current status and roadmap in English. The rest of this file is in Italian.

# Stato del progetto — 26 ottobre 2026

Driver Metal per **AMD Radeon RX 9060 XT** (Navi 44, `1002:7590`) su macOS Tahoe 26.6.2 (build 25G83), come port di
[Cobalt64](cobalt64/README.md) (RX 9070 XT). Dettaglio fase per fase in [`FASI.md`](FASI.md); qui il quadro d'insieme.

## In una riga

**Aggiornamento, 26/10:** macOS Tahoe 26.6.2 (25G83) è avviato su bare metal e il progetto è stato importato in macOS. `sysctl` rileva 8 core fisici e 16 processori logici; `system_profiler` rileva la RX 9060 XT (`1002:7590`) come display principale, con 14 MB di VRAM riportata e nessun kext grafico caricato. Non è stata verificata la stabilità prolungata né ottenuta accelerazione grafica bare metal. La sessione Codex è ora proseguita su macOS.

**Build su macOS, 27/10:** toolchain isolata preparata; Navi44Bringup, RDNA4FB, Navi48Accel, RADV, n48xlate e bundle Navi48Metal compilati in staging. Gate A/B/C e 1694 controlli host dell'ausiliario passati; nessun componente è stato caricato o provato sulla GPU. La build Navi44 contiene cinque blob opzionali sostituiti da stub vuoti; il traduttore ha un install name assoluto da valutare prima di distribuire il bundle. Dettagli e limiti in `research/builds/macos-20261027/BUILD_REPORT.md`.

**Preparazione desktop, 27/10:** candidate locali non distribuite per VBL del framebuffer (periodo dal modo pubblicato, diagnostica callback) e per bundle Metal con install ID rilocabile; build e controlli offline passati, nessuna prova su GPU o dimostrazione di desktop accelerato. La corrispondenza tra modo pubblicato e scanout fisico resta da verificare. Dettagli in `research/reports/desktop_accel_preparation_20261027.md`.

**Primo test autorizzato, 27/10:** OCBOOT verificata 28/28, backup EFI reale verificato su chiavetta 128 GB; candidata discovery stage1 distribuita e verificata 31/31, ma non ancora avviata. Dettagli e ripristino in `research/reports/navi44_stage1_candidate_20261027.md`.

**Prossimo test in preparazione, 27/10:** trovata inizializzazione del watchdog successiva alla PSP; preparata build sperimentale con gate iniziale e candidata di sola osservazione ancora stage1, non distribuita né provata. Il sensore resta non validato e il gate non può interrompere la PSP già iniziata. `research/reports/navi44_safety_next_test_20261027.md`.

Lo stack del driver funziona sulla GPU (bring-up, compute, Metal headless verificato), ma **il desktop accelerato a
video non è ancora stato ottenuto**: in VM WindowServer non mandava lavoro al nostro display. Sul bare metal Tahoe è
installato, la mappa BOOT17 fornisce input USB e l'utente è arrivato al desktop dopo la rimozione del limite `cpus`.

## Cosa funziona (verificato su hardware, nella VM con la GPU in passthrough)

| Area | Risultato | Riferimento |
|---|---|---|
| Bring-up GPU | PSP, SMU, IMU/RLC, GFX, MES, SDMA fino allo stage 17; ACK GFXHUB | `research/reports/gfxhub_ack_compute.md` |
| Compute | shader baseline 32/32, `vadd_ir` gfx1200 corretto, VMID8 positivo e recupero da fault | `research/reports/phase2_mes_fault_checkpoint.md` |
| Acceleratore IOAccelerator | layout da `ioaccel-layout` upstream: MATCH 3150 slot; kext aux compilato, gate A/B/C verdi, caricato in macOS | `research/reports/ioaccel_layout_upstream.md` |
| **Metal headless (P0)** | `MTLDevice` "AMD Radeon RX 9060 XT"; quadrato e triangolo identici al pixel al riferimento; compute PASS; hot-swap shader PASS | `research/reports/p0_headless_metal.md` |
| Display (lettura) | il GOP accende OTG0/HUBP0/DIG0/PHY A (DP) a 2560x1440@120; superficie ARGB8888 lineare pitch 2560 | `research/display/gop_vm_readout_plan.md` |
| Display (macOS) | RDNA4FB v8 su `0x7590`: modo 2560x1440@120 installato, monitor **display principale** anche dopo il riavvio di WindowServer; VBL emulato attivo; pipe adottata/armata, AGDC pubblicato | `research/reports/p1_p2_display.md` |
| Sicurezza della scheda | watchdog nel kext (sensore THM, TRIP 80 °C) + watchdog host (chiude la VM); protezioni firmware verificate attive; nessuna scrittura di tensioni, clock, curve ventola o flash | `research/reports/gpu_safety.md` |

## Dove siamo bloccati

### 1. Desktop accelerato in VM (P2)

WindowServer attiva il compositor Metal sul nostro device e il nostro monitor è principale, ma **non arriva nessuna
transazione alla display pipe** (`command_buffers=0`, `frames=0`, `submit 0`). A video: login window ridisegnata,
orologio assente, nessuna trasparenza. Provati senza esito: VBL emulato (`rdna4-vbl=1`), boot-arg della ricetta
Cobalt64 (`navi48-multisession`, `navi48-apps`, `npci`). Analisi: `research/reports/compositor_diag.md`,
`research/reports/p2_vs_cobalt_recipe.md`, `research/reports/coredisplay_re.md`.

Ipotesi di fondo: alcune differenze dell'ambiente VM (GPU sul bus 0, SMC emulato, nessuna topologia PCIe reale) che
Cobalt64 su bare metal non ha. Per questo il lavoro si è spostato sul bare metal.

### 2. Bare metal (dal 23/10)

Chiavetta di avvio con OpenCore 1.0.8 + ripristino di Tahoe 25G83. Dopo undici avvii:

- risolti l'abort di `boot.efi` e lo `STOP 0x16` (memoria) con `DevirtualiseMmio`;
- **il kernel parte** sul Ryzen 7 7700 (patch AMD tutte applicate);
- **output fermo dopo `CoreAnalyticsHub start completed` nei boot3–8** (tastiera morta), invariato con: grafica integrata spenta,
  `-amd_no_dgpu_accel`, due patch ACPI della DSDT AGESA.

Report completo, cronologia, ipotesi e passi successivi: [`research/reports/baremetal_bringup.md`](research/reports/baremetal_bringup.md).

**Avvii 7 e 8 negativi**: resize BAR e whitelist F7000000 risultano eseguiti, stesso blocco. L'audit con
OpCore Simplify ha individuato una patch AMD temporale precedente a Darwin 25.4 applicata su **25.6**: nel replay
sulla BootKC della chiavetta i primi due match sono vicini a funzioni estranee allo scheduler, benché il log
riportasse `Success`. La nuova EFI usa la correzione 25.4+, abilita IOPCIIsHotplugPort per AM5 e aggiunge le
16 definizioni CPU generate dal firmware. Questo corregge problemi concreti; la causa completa del blocco
resta sconosciuta: anche il boot9 con la nuova base non raggiunge la GUI.

**Boot9 negativo, nuova schermata:** foto IMG_0667, kext Lilu/NVMeFix/RestrictEvents avviati e ultima riga visibile
`ACPI: WSMT`. Nessun panic; Caps Lock non risponde dopo 2–3 minuti. Patch aggiornata, hotplug AM5 e quattro SSDT
confermati nel log; 28 payload verificati. La diversa ultima riga non dimostra avanzamento né identifica il colpevole.
**Serial/COM ora disattivata**, confermata da Linux (stato 0); ReBAR/Above 4G restano attivi.
La variante `research/ext/opcore-simplify-b840-acpi-debug/` mantiene la v2 e cambia soltanto i boot-args
per la diagnostica ACPI e il buffer log: **già attiva su OCBOOT**, con backup del config e ripristino invariato.
**Boot10: riavvio spontaneo durante il verbose**, senza cattura; il firmware torna a GRUB e Linux. Il nuovo log
conferma gli argomenti diagnostici e le patch, ma termina all'handoff; nessun panic file nella radice USB.
Causa e punto del riavvio sconosciuti; nessuna GUI o installazione raggiunta. Evidenze in `research/hw_dump/baremetal_boot10/`.

**Boot11, video IMG_0668:** prosegue oltre l'elenco ACPI, carica le tabelle AML, stampa AppleACPICPU e arriva ad
IOHIDFamily/AppleACPIButtons/AppleRTC/AppleHPET. Negli ultimi fotogrammi `HPET: map device registers failed`,
poi messaggio AppleVTD e nero a 120,69 s; l'utente conferma POST/GRUB autonomo. Nessun panic/backtrace leggibile
o rapporto recuperato. Questo localizza meglio l'output finale, non la causa del reset.
**Boot12, foto IMG_0669:** page fault XNU 25.6.0 su CPU 0, `CR2=0xFED802B0`, `RIP=0xffffff80266e8a61`; il caller
visibile è nella catena `_sync_iss_to_iks`/`_panic`, mentre il RIP non è attribuito con certezza e il backtrace termina
su frame pointer invalido. CR2 è un indirizzo lineare; coincide numericamente con due OpRegion DSDT a base FED80000
e ricade nel descriptor EFI `[0xF7000000,0xFEE00000)`, senza provare una corrispondenza fisica.
**Boot13:** `cpus=1` + whitelist `F7000000` supera il logo Apple e arriva a una schermata animata di pairing Bluetooth
Magic Keyboard/Mouse. La NuPhy Node75 e il mouse GravaStar M2 non rispondono via cavo. **Boot14:** stessa GUI animata,
input ancora inattivo; l'utente conferma prove sia con i dongle USB sia cablati, collegati direttamente alla scheda
madre. GUI Recovery/utilità non confermate: non è ancora un ripristino utilizzabile. Linux vede NuPhy `19f5:1030`
(HID su XHC0 `HS01`, `1022:15b6`) e mouse Compx `3554:f576` (HID su XHC1 `HS01`, `1022:15b7`); entrambi i controller
e le porte sono coperti dalla mappa. Boot14 aveva cambiato solo i selettori a `AppleUSBHostController` +
`IOParentMatch/IOPropertyMatch(pcidebug)`, ma il test negativo non prova che il binding sia corretto o errato su macOS.
**BOOT15 (mappa disabilitata) non è mai stato avviato né provato**, quindi resta non classificato. L'utente riferisce
che BOOT16 ha ripetuto la schermata animata Magic Keyboard/Mouse senza input. L'analisi del plist ha trovato 0/23
porte con gli alias Tahoe `usb-port-number`/`usb-port-type`: il runtime USBToolBox 1.2.0 li aggiunge per Darwin >=25,
ma BOOT16 usava una mappa nativa senza quel runtime. Questa omissione è reale e plausibile, non una causa confermata.
Sulla sola EFI OCBOOT è ora presente **BOOT17**: copia BOOT16 con i due alias aggiunti a tutte le 23 porte, mantenendo
controller, match, raw port 14/4/4/1 e le tre classificazioni interne osservate come 255. È cambiato solo
`EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist` (SHA `71f93330…`); config invariata (`55d53e17…`) e altri 27 file
identici. Preflight BOOT16 28/28, postmanifest BOOT17 28/28 e `ocvalidate` 1.0.8 passano. Backup dell'Info BOOT16 e
record in `research/ext/usbtoolbox-linux-tahoe-boot17-candidate/deploy-evidence/20261026T131317524219Z/`; chiavetta
A140-3052 smontata. **L'utente conferma BOOT17 con input USB funzionante e Recovery raggiunta**; le utility, la rete e
l'installer non sono state verificate da questa sessione. `ReleaseUsbOwnership=True` non dimostra l'impostazione BIOS
XHCI hand-off, che resta ignota. Nessun bypass pairing o altro kext/binario aggiunto. Il reset boot11 e il panic boot12
restano distinti. BIOS invariato. Per i prossimi passi senza scritture vedere
`research/reports/recovery_install_readonly_20261026.md`; dettagli USB nei report §§15–17 e
`research/reports/usb_tahoe_schema_diagnosis_20261026.md`.
Dettaglio: [`opcore_simplify_linux_b840.md`](research/reports/opcore_simplify_linux_b840.md).

**Storage e installazione bare metal (26/10):** sul Lexar la partizione archivio Btrfs da 50 GiB è montata su
`/mnt/vm` (UUID `0ae89dbc-e934-4c12-a6bd-90d01e5bd0da`). Sono stati ripristinati e verificati gli archivi dei
materiali selezionati, inclusi i due file GRUB protetti; i 445 hash del manifest passano come utente. Per rendere
leggibili i materiali sono state corrette solo 51 directory genitore implicite; nessun file o chiave è stato toccato.
I dischi VM non sono stati preservati. L’utente conferma che Tahoe è stato installato e BOOT17 è arrivata a Setup
Assistant; dopo la scelta della regione il caricamento è rimasto per circa 30 minuti. Il primo resoconto diceva che
puntatore e rotella rispondevano; in una precisazione successiva l’utente riferisce che poi il puntatore si fermò e il
blocco diventò completo. Ethernet era collegata; dopo il riavvio il PC è tornato a Linux e il primo login non è avvenuto.
Il video IMG_0681 è una ripresa di verbose startup con errori kext, non una schermata di panic leggibile; l’errore
IOVersatile non è attribuito come causa del blocco successivo. Nel video successivo Ethernet era scollegata prima dell’avvio, ma Setup Assistant è rimasto fermo alla regione e poi si è bloccato completamente anche offline.
I metadati Linux read-only vedono
APFS sul Lexar e archivio Btrfs da 50 GiB; gli indici attuali sono p5 e p4. Il volume APFS è 161,924,251,648 byte
(150 GiB preparati più 862,978,048 byte) e il suo PARTUUID è diverso dalla fotografia preinstallazione. Due vecchie
partizioni Windows Recovery, identificate da GUID nei metadati storici, non compaiono più; il volume NTFS Windows e
l’EFI da 1 GiB sono ancora presenti. La causa del cambiamento GPT non è attribuita e non è stata tentata una riparazione.
Linux non ha montato APFS. Il video IMG_0681 è stato campionato lungo tutta la clip: non mostra un panic leggibile; l’ultimo frame è nero. Il test offline Ethernet è negativo. L'utente riferisce che Shift+Invio non seleziona la voce nel picker, dunque Safe Boot non è stato verificato. Dopo il deployment precedente, la variante `cpus=2` non è stata avviata. OCBOOT contiene la prova all-threads: è stato rimosso solo `cpus=2`, con gli altri 27 file EFI invariati; manifest 28/28 e `ocvalidate` 1.0.8 sono passati. L'utente ha poi avviato macOS e completato la configurazione; `sysctl` su macOS conferma 8 core fisici e 16 processori logici. XNU tratta `cpus=VALUE` come massimo dei processori logici. La patch AMD per gli 8 core fisici è rimasta invariata. Backup `cpus=2` e BOOT17 `cpus=1` sono fuori da EFI. Procedura e hash: `research/reports/recovery_install_readonly_20261026.md` e `research/ext/opcore-all-threads-candidate-20261026/`; il video è documentato in `research/ext/boot-setup-video-0681/analysis.md`.

## Promemoria operativi

- **BIOS ora**: grafica integrata **disattivata** (da riattivare per le prove in VM con VFIO).
- Le prove in VM richiedono la voce GRUB VFIO "una tantum" (`tools/vm/prepare-vfio-test-boot.py arm` + riavvio), poi
  BAR0 a 256 MiB (`tools/vm/resize-vfio-bar.py 8`) e `memlock` ≥ 14 GiB per il processo che lancia la VM.
- La chiavetta da 128 GB contiene dati personali: si scrive solo nella cartella `macOS-Tahoe-25G83-installer/`.
- Il lavoro precedente è nei commit `22e50f0`…`a0de0d3`; audit e strumenti bare metal del 25/10 sono ancora modifiche
  locali non committate. Restano fuori da git, per scelta: le EFI
  e gli strumenti scaricati in `research/ext/`, i seriali SMBIOS, le tabelle ACPI binarie della scheda e i binari Apple.

### 27 ottobre 2026, 22:46 — primo desktop accelerato bare metal

Stage19c ha completato 120 s con WindowServer PID 517 stabile: utente conferma trasparenze/effetti e uso del desktop; log conferma 5.734 presentazioni scanout senza errori GPU nel campione. Il passaggio decisivo è stato completare la ricetta Cobalt64 con `fbname 1`, correggendo prima attesa del nub e verifica del nome troncato a 8 byte dal tool. Magenta iniziale correlato a 65 pipeline placeholder, tutte sostituite da shader reali durante la sessione. Stage20 (bundle 22) predispone 167 shader in cache, inclusi 132 runtime validati, e mantiene RADV/traduttore e logica del driver. Pronto il test monouso al prossimo riavvio; versione21 funzionante salvata in `/Library/GPUBundles/Navi48Metal.bundle.stage19c-working`. Dettagli nel rapporto `research/reports/navi44_vs_cobalt64_desktop_20261027.md`. La scomparsa del magenta al prossimo login è ancora da verificare.

### Stage21 predisposto — correzioni combinate desktop

Al posto dello Stage20 ancora non avviato, predisposto Stage21/bundle23: 212 shader in cache, riduzione logging ripetitivo in 16 punti, hot-swap a 100ms con controlli di sicurezza dei file conservati (224 verifiche passate), traduttore a priorità normale dal prossimo boot. Sessione accelerata corrente PID517 preservata; backup versione21 funzionante e versione22. Restano da misurare miglioramenti ed eventuali artefatti nel nuovo avvio; shader mai incontrati possono richiedere ancora traduzione. Rapporto `research/reports/navi44_vs_cobalt64_desktop_20261027.md`.

### 31 ottobre 2026 — Bundle 29 e 30 installati (traduttore NullMoth, icone, audio)

- **Bundle 29** (profilo `stage29-nullmoth-v1`): traduttore `libn48xlate` sul fork di NullMoth `ceba63c` (LGPL, bindless spento), protezioni contro view e sampler nulli, swizzle delle texture campionate, memo dei fallimenti di traduzione definitivi, formato privato 84, sampler di riserva a livello 0. Avvio `desktop-stable-120s`.
- **Audio**: VoodooHDA 3.6.8 in `/Library/Extensions` più AuxKC; l'utente conferma che le casse funzionano.
- **Regressione corretta**: l'installer b29 aveva spostato `/private/var/tmp/n48m-spv`, l'unica fonte di WindowServer per gli shader assenti dallo spvcache del bundle. Il Centro di Controllo restava sui segnaposto magenta. Cache ripristinata, hot-swap avvenuto senza riavvio, installer corretto.
- **Bundle 30** (profilo `stage30-vonly-v1`): una pipeline senza fragment function diventa una pipeline Vulkan con il solo vertex. iconservicesagent la usa per la maschera stencil delle icone a livelli; prima finiva sul segnaposto e Finder, App Store e Mappe uscivano vuote. Il segnaposto di WindowServer è ora invisibile (`/private/tmp/n48m-magenta` ripristina il magenta). Avvio `desktop-stable-120s`; RADV accetta la pipeline con il solo vertex. Esito visivo sulle icone da confermare.
- **Limite delle 8 sessioni confermato sul dispositivo** (`session-check.py`): 8 slot su 8 occupati (WindowServer e sette servizi di sistema). Le app aperte dopo, come WhatsApp, Brave e il Finder rilanciato, ricevono `0xe00002c7` e disegnano in software. Dall'analisi del codice: il 666 cambia solo il numero di contesti; allow-list e ruolo restano identici, e `0xe00002c7` non corrisponde né all'esaurimento (`0xe00002c5`) né all'allow-list (`0xe00002c1`). Va prima identificato lo strato che lo restituisce (evento di trace 15).
- **Aperti**: errore `vkCreateDescriptorPool = -2` nel picco del login; banda nera in alto (dura fino a circa 1 s, quindi difficilmente legata alla frequenza; studio dei 60 Hz in `research/reports/macos-20261031/refresh-60hz-feasibility.md`); decodifica video VCN assente.
- Sorgenti: `cobalt64/tools/native/navi48metal/`, `cobalt64/third-party/metal2vulkan-n48/patches/0002-*`, installer in `tools/baremetal/navi44-desktop/metal-trial-b29|b30/` e `tools/baremetal/navi44-audio/voodoohda-v1/`. Rapporti in `research/reports/macos-20261031/`.

### 31 ottobre 2026 (sera) — Kernel 0.0.667 avviato: limite delle 8 sessioni superato

- **OpenCore in locale**: copiato dalla chiavetta alla partizione EFI di CachyOS (`disk1s1`, 82 file verificati), avviato dalla voce GRUB "macOS Tahoe (OpenCore)" (`tools/baremetal/grub-opencore/`). Le chiavette non servono più.
- **Kernel 0.0.667** (64 contesti logici su 8 VMID dinamici, ammissione senza allow-list con budget: 9 record riservati, 8 per processo, 32 per uid) installato con `kernel-efi/install-kernel-efi.py`; voce OpenCore "Ripristino EFI: driver funzionanti (665)" con `startup.nsh`.
- Primo avvio in modalità software: il verificatore del profilo accettava solo la build 666. Corretto (`b312552`), latch archiviato dopo la revisione.
- Secondo avvio: `CONTEXT_PROFILE_VERIFIED` (dynamic_vmids true), `LOGICAL_CONTEXT_CAPACITY_VERIFIED=64`, `login-window-stable-300s`. Registro del driver: 71 aperture ammesse, nessun rifiuto; ammesse anche app prima escluse (Brave, Mappe, App Store, Dov'è, Libri, Calcolatrice). L'utente conferma accelerazione e app funzionanti.
- **Ancora aperto**: icone a livelli (Finder, App Store, Mappe). Le pipeline con solo vertex funzionano; restano 8479 letture di texture mai collegate in iconservicesagent. Ipotesi in verifica: texture passate tramite argument buffer / `gpuResourceID`, non implementati nel bundle.

### 1-5 novembre 2026 — bundle 34, kernel 0.0.671, 60 Hz

- **Bundle 34** (azzeramento della memoria video nuova, WindowServer escluso) installato. Le icone sono ancora sbagliate: indagine in corso sul lato WindowServer.
- **Blocco dopo circa 25 minuti di uptime (<1 fps), risolto in 0.0.671:** i buffer GTT erano allocati fisicamente contigui (fino a 64 MiB) sotto il lock globale dei client. Con la RAM frammentata, `vm_page_find_contiguous(num=1024)` falliva scandendo tutta la memoria (~150 ms per tentativo, 418 volte in 3 minuti), mentre ogni client GPU restava fermo. 0.0.671 usa pagine sparse allocate fuori dai lock (`644c07d`). Da verificare su un uptime lungo.
- **60 Hz funzionanti** (0.0.670/0.0.671 + RDNA4FB 0.0.9): `refresh 60` allunga V_TOTAL da 1525 a 3050 righe con lo stesso clock; il monitor LG lo accetta, l'utente conferma che la banda nera in alto è sparita. Il flag `/Library/Application Support/Navi44/accelerated-trial/refresh-60` attiva i 60 Hz a ogni avvio; cancellarlo riporta a 120 Hz.
- Issue #1 (riproducibilità della baseline 0.0.665): `baselines/0.0.665/` pubblicata (`2c34dd1`), issue chiusa.


### 9 novembre 2026 — bundle 38: icone risolte

- **Bundle 38** (profilo `stage38-swz-v1`, `50f2597`) installato. Causa delle icone sbagliate: IconServices passa i livelli grigio + alfa come texture RG8 su IOSurface o buffer con swizzle (R,R,R,G); il bundle applicava lo swizzle solo alle texture ordinarie, quindi il vetro diventava giallo (blu a 0) e ogni livello un quadrato nero (alfa a 1). L'utente conferma il Dock corretto in tutti gli stili, anche trasparente e tinto. Le icone già in cache dentro Impostazioni di Sistema restano vecchie fino al rinnovo della cache. Residuo minore nel confronto in-process: blocchi su Dov'è (stile predefinito) e punta del razzo di Giochi in scuro.
- **Banda nera in alto**: con i 60 Hz è molto più rara ma ricompare ogni tanto. Indagine sul percorso di presentazione (flip, slot di scanout, copia D) in corso.

### 12 novembre 2026 — kernel 0.0.673: banda nera sparita

- Causa: il GOP lasciava al display solo 3 segmenti DET (192 KB), quindi i cambi di frequenza della memoria cadevano nel vblank di 85 righe senza margine. 0.0.673 (`d8b72c0`) porta DET0 a 20 segmenti e programma i watermark di Linux; installato (payload v9, guardia 673). L'utente non vede più la banda.
- Al primo avvio: 3 underflow circa 10 s dopo il login; il fallback ha rimesso lo stutter forzato off e bloccato la UCLK a 1258 MHz (scheda ~33 W contro ~25 W). Nessun underflow dopo. In preparazione 0.0.674 con fallback a due stadi (prima solo stutter off, poi il blocco).
- Schermo nero con solo il puntatore (12/11, 60 Hz al boot): blocco di sistema dopo `WINDOWSERVER_READY`, causa aperta; i 60 Hz restano disattivati.
