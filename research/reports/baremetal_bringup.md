# Bare metal: primo avvio di macOS Tahoe 25G83 sul PC (23–26/10/2026)

Obiettivo di questa fase: avviare macOS **senza VM** sul PC dell'utente (Ryzen 7 7700, MSI B840 GAMING PLUS WIFI,
RX 9060 XT), per togliere di mezzo le differenze introdotte da QEMU nel lavoro sul display (vedi `p1_p2_display.md`).
Primo traguardo: arrivare alla GUI del ripristino (BaseSystem) da chiavetta, **senza installare nulla**.

Stato aggiornato al Boot17 (26/10/2026): **l'utente conferma che BOOT17 ha input USB funzionante e ha raggiunto macOS Recovery.** Utility Disco, rete e installer non sono stati verificati da questa sessione; l'installazione non è iniziata. BOOT15 non è stata provata.

## 1. Supporti preparati

| Supporto | Contenuto | Note |
|---|---|---|
| Chiavetta 16 GB SanDisk Cruzer Fit, etichetta `OCBOOT` (GPT, una partizione EFI FAT32) | BOOT17 attiva: `USBMapB840.kext` contiene i due alias Tahoe su 23 porte; config invariata SHA `55d53e17…` | È cambiato solo `EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist` (SHA `71f93330…`); gli altri 27 file EFI sono identici a BOOT16. Backup Info BOOT16 e record in `research/ext/usbtoolbox-linux-tahoe-boot17-candidate/deploy-evidence/20261026T131317524219Z/`; manifest 28/28 e `ocvalidate` 1.0.8 passano. BOOT16 ha dato input negativo; l'utente conferma input positivo e Recovery raggiunta con BOOT17. Supporto smontato nella shell Linux della workspace. Digest BaseSystem solo riferimento precedente, non riletto. |
| Chiavetta 128 GB SanDisk (exFAT, **dati personali dell'utente: non leggere né elencare**) | La documentazione locale registra soltanto la cartella autorizzata `macOS-Tahoe-25G83-installer/Tahoe25G83.iso` (installer completo, 18,4 GB, SHA verificato) aggiunta nello spazio libero | Collegarla alla Recovery solo per il prossimo inventario read-only; non formattare. Il percorso documentato monta l'ISO e avvia `run-tahoe-installer.sh`, provato nella VM ma non ancora sul bare metal. |

Nessuna partizione per macOS è stata ancora creata: il volume `/mnt/vm` (200 GiB Btrfs, `nvme1n1p7`) è intatto.

**Aggiornamento più recente:** BOOT16 ha dato input negativo secondo l’utente. BOOT17 è attiva su OCBOOT e l’utente ora conferma input USB funzionante e Recovery raggiunta. La mappa BOOT16 ometteva `usb-port-number`/`usb-port-type`; l’adattatore ha aggiunto entrambi gli alias alle 23 porte. BOOT17 cambia solo l’Info USB (SHA `71f93330…`) rispetto a BOOT16, con config SHA `55d53e17…` e gli altri 27 file invariati; manifest 28/28 e `ocvalidate` passano. Backup BOOT16: `research/ext/usbtoolbox-linux-tahoe-boot17-candidate/deploy-evidence/20261026T131317524219Z/`. Nessuna modifica BIOS. Restano da verificare dall’interfaccia live Recovery Utility Disco, rete e avvio installer. Dettagli USB: §17 e `research/reports/usb_tahoe_schema_diagnosis_20261026.md`; inventario e prossimi passi: §18 e `research/reports/recovery_install_readonly_20261026.md`.

## 2. EFI OpenCore (base precedente; nuova configurazione in §10)

- Sorgente e generatore: `research/ext/ocboot-baremetal/` (fuori da git). `_tools/build_efi.py` rigenera la EFI
  (opzioni `--debug`, `--varianti`, `--next`, `--next2`); `LEGGIMI.md`, `REVIEW.md`, `QEMU_TEST.md` documentano scelte,
  revisione e test. Varianti DEBUG in `research/ext/ocboot-baremetal-debug/` (`EFI/`, `EFI-next/`, `EFI-next2/`,
  `EFI-next3/`, `VARIANTI/`), ognuna con `SHA256SUMS-EFI.txt`.
- OpenCore 1.0.8 (zip ufficiali RELEASE e DEBUG, sha256 verificati con i digest pubblicati), `ocvalidate` 1.0.8 pulito
  su ogni variante.
- Kext: Lilu 1.7.2, VirtualSMC 1.3.8, MCEReporterDisabler, LucyRTL8125Ethernet 1.2.3 (NIC Realtek 8125),
  `USBMapB840.kext` (mappa codeless dei 4 controller xHCI, porte 1..14), `Navi48Bringup.kext` presente ma **disabilitato**.
  SSDT-EC-USBX-DESKTOP (Dortania, verificato contro la DSDT reale: nessun EC `PNP0C09`).
- Patch AMD_Vanilla per Darwin 25.x: core count `08`, tutte le voci 25.x del master, voce IOPCIFamily `probeBusGated`
  presa dal branch beta per 26.0+. Tutte applicate con `Success` nel log.
- SMBIOS MacPro7,1 con seriali generati con macserial (solo nella EFI, mai in git).
- Quirk Booter attuali: `AvoidRuntimeDefrag`, `DevirtualiseMmio`, `EnableSafeModeSlide`, `FixupAppleEfiImages`,
  `ProvideCustomSlide`, `RebuildAppleMemoryMap`, `SetupVirtualMap`, `SyncRuntimePermissions`, `ResizeAppleGpuBars=-1`.
  Kernel: `ProvideCurrentCpuInfo`, `DummyPowerManagement`, `DisableLinkeditJettison`, `PowerTimeoutKernelPanic`.
- boot-args attuali: `-v keepsyms=1 debug=0x100 -amd_no_dgpu_accel kextlog=0xffff`.

## 3. Cronologia degli avvii reali

| # | Data | EFI | Esito | Evidenze |
|---|---|---|---|---|
| 1 | 24/10 | RELEASE | `boot.efi` torna con `Aborted` dopo ~20 s; simbolo di divieto. Log RELEASE di 12 righe, insufficiente | `research/hw_dump/baremetal_boot1/` |
| 2 | 24/10 | DEBUG | Log completo: patch AMD e kext tutti `Success`, `MAT support is 1`, poi `EB.MM.AKM Err(0xE)` → `EB|STOP 0x16`: `boot.efi` non riesce ad allocare la memoria del kernel | `research/hw_dump/baremetal_boot2/opencore.txt` |
| 3 | 24/10 | `EFI-next` (+`DevirtualiseMmio`) | **Risolto lo STOP 0x16**: devirtualizzati 935 MB di MMIO, `EXITBS:START`, il **kernel parte**: ACPI 16 tabelle, AppleCredentialManager, AppleKeyStore, Lockdown Mode, poi **blocco totale dopo `CoreAnalyticsHub start completed`** | `research/hw_dump/baremetal_boot3/`, foto dell'utente |
| 4 | 24/10 | `EFI-next2` (+`-amd_no_dgpu_accel kextlog=0xffff`) | Stesso blocco; ultima riga visibile `kext com.apple.iokit.IOTimeSyncFamily is already loaded` (innocua) | `research/hw_dump/baremetal_boot4-6/` |
| 5 | 24/10 | `EFI-next2` + **iGPU Raphael disattivata nel BIOS** | Stesso blocco; **Caps Lock non risponde**: blocco totale, non un'attesa | idem |
| 6 | 25/10 | `EFI-next3` (+2 patch ACPI DSDT) | Le patch risultano applicate (`replaced 1 of 1` ×2) ma **stesso blocco** | `research/hw_dump/baremetal_boot4-6/opencore-2026-10-25-092931.txt` |
| 7 | 25/10 | `EFI-installer-smallbar` (`ResizeAppleGpuBars=0`, BIOS ReBAR attivo) | **Stesso blocco**, confermato dall'utente e dalla foto. OpenCore esegue resize BAR0 `14→8` e BAR2 `8→1`, poi `EXITBS:START`; la sola riduzione delle BAR non risolve | `research/hw_dump/baremetal_boot7/`, foto originale `IMG_0666.HEIC` locale |
| 8 | 25/10 | `EFI-installer-mmiof7` (whitelist F7000000) | **Stesso blocco** riferito dall’utente; `F7000000 skip 1`, 806912 KB devirtualizzati e 168 slide validi verificati. Nessuna regressione dello STOP 0x16 | `research/hw_dump/baremetal_boot8/` |

Lo spostamento della chiavetta da una porta del case a una porta posteriore (controller `0b:00.0` dietro un hub
Genesys) non ha cambiato nulla: nella fase di `boot.efi` l'USB è gestito dal firmware.

## 4. Il blocco attuale: cosa sappiamo

- Avviene **dopo** l'inizializzazione ACPI e dei servizi di sicurezza, **prima** di qualsiasi riga di configurazione
  PCI (`PCI configuration begin` non compare) e prima di `Still waiting for root device`.
- È un **blocco totale** (Caps Lock morto), non un'attesa di un dispositivo.
- Non dipende da: grafica integrata (disattivata), accelerazione della 9060 XT (`-amd_no_dgpu_accel`), porta della
  chiavetta, allocazione di memoria del bootloader (risolta).
- Sullo schermo, durante il caricamento ACPI: `ACPI Warning: Unsupported module-level executable opcode 0x70 at table
  offset 0x5436`. Origine individuata: blocco `If (CondRefOf (\_OSI)) { ... TSOS = 0x50 }` a livello di modulo nella
  DSDT (riga ~61657 del disassemblato); di norma innocuo.
- Lo stesso blocco, nello stesso punto, è documentato su un'altra scheda AM5 (X870E, Ryzen 9800X3D, Sequoia) in
  [nullmoth/1401 #21](https://github.com/nullmoth/1401/issues/21), anche lì **dopo** aver risolto lo STOP 0x16 con
  `DevirtualiseMmio`. Lì un utente (Ryzen 7800X3D, B650) lo ha superato con 4 patch ACPI di etorix che rendono
  incondizionati i blocchi `If` del codice AGESA (`OperationRegion CPVS`, variabili `G000`/`G002`/`G004`).

### Patch ACPI provate (boot 6) e perché

La DSDT della B840 contiene lo stesso codice AGESA (`CPVS` a `0x8C01B000`). Il chipset è descritto in due varianti:
`G000 == 1` (switch `GPP7.UP00` con `DP00/20/40/60`) e `G000 == 2` (`GPP7.XH00`, `EP01`, `UP02` con NVMe, Wi-Fi e LAN).
Linux crea `GPP7.XH00`, `GPP7.EP01` e `GPP7.UP02` (verificato in `/sys/bus/acpi/devices`), quindi sulla nostra scheda
il ramo attivo è `G000 == 2`. Le patch di etorix erano per il ramo `G000 == 1`; abbiamo scritto l'equivalente per il
nostro ramo:

| Patch | Find (AML) | Effetto |
|---|---|---|
| 1 | `a08c0c0f909293473030320a0393473030300a02` (20 B) → 20×`A3` | `If ((G002 != 3) && (G000 == 2))` reso incondizionato (crea `XH00`, `EP01`, `UP02`) |
| 2 | `a047d3909293473030320a0392934730303000` (19 B) → 19×`A3` | `If ((G002 != 3) && (G000 != 0))` a livello di modulo reso incondizionato (metodi di `GPP7`) |

Verifiche: ogni Find compare una sola volta, nessun `Else` dopo i blocchi, la DSDT patchata si decompila senza errori
con `iasl` (`XH00`/`EP01`/`UP02` definiti incondizionatamente). **Esito: nessun cambiamento.** L'ipotesi "dispositivi
del chipset mancanti" per questa scheda non è confermata, oppure non è l'unica causa.

## 5. Diagnosi aggiornata dopo il boot8

Il confronto con Simplify e il replay delle patch sulla BootKC del ripristino hanno individuato una patch AMD
non aggiornata per Darwin 25.6, oltre a IOPCIIsHotplugPort disattivata e definizioni CPU legacy mancanti. Il solo
`Success` del patcher non garantiva destinazioni corrette. La vecchia graduatoria delle ipotesi basata su BAR e
MMIO è superata dalle prove negative 7–8 e dai nuovi riscontri: vedere §10.

Le cause del blocco reale non sono ancora isolate. La nuova EFI corregge queste differenze e richiede la seriale
BIOS disattivata, invece di introdurre un'altra sola eccezione MMIO.

## 6. Stato del BIOS e del PC (da ricordare)

- **Grafica integrata Raphael: DISATTIVATA** per la prova 5. Va **riattivata** per tornare alla configurazione VFIO
  (lo schermo di Linux usa l'HDMI della scheda madre in quella modalità). Con l'integrata spenta Linux usa la 9060 XT.
- Secure Boot off, CSM off, Above 4G on, Re-Size BAR on. **Serial/COM disattivata prima del boot9**, confermata da Linux (`PNP0501` stato 0).
- Avvio dalla chiavetta solo con F11 (menu di avvio MSI): l'ordine di avvio non è stato toccato.
- Nessuna scrittura su dischi interni, NVRAM del firmware (`WriteFlash = NO`) o partizioni.

## 7. Prossimi passi (aggiornati dopo il boot9)

1. Mantenere **Serial/COM off**, **Resizable BAR e Above 4G on**, iGPU off.
2. Provare la variante diagnostica della stessa EFI (§11): sola aggiunta di boot-args ACPI e buffer log.
3. Registrare un video dall'inizio del verbose al blocco, oltre alla schermata finale: il log OpenCore non raccoglie
   il seguito del kernel. Prima di cambiare tabelle o quirk cercare errori espliciti e verificare la ripetibilità.
4. Solo dopo la GUI affrontare la destinazione APFS.

## 8. Percorso installer senza accelerazione e nuova EFI (25/10/2026)

Richiesta dell'utente: ottenere prima un macOS installato utilizzabile senza accelerazione, poi lavorare sul driver
da dentro macOS con Codex. Il desktop tramite framebuffer firmware è l'obiettivo della prossima fase, non ancora
una funzionalità verificata sul bare metal di questa macchina.

### Confronto con configurazioni pubbliche

- [aqzas/Hackintosh-Ryzen7700-XFXRX580](https://github.com/aqzas/Hackintosh-Ryzen7700-XFXRX580): stesso Ryzen 7 7700,
  ASRock B650M Riptide, Sonoma 14.5. Il config pubblicato (blob `882a779059829be0439d3d77519997d955e84a79`)
  usa `DevirtualiseMmio=True`, `SetupVirtualMap=True`, `ResizeAppleGpuBars=0`, `UEFI.ResizeGpuBars=-1`.
  Nei quirk Booter la nostra EFI differisce solo per `FixupAppleEfiImages` (chiave più recente) e il resize Apple.
  Non importati: MMIO whitelist, SSDT, USB map, impostazioni della RX580 o vecchie patch kernel.
- [EishoTek/MSI B650M MORTAR](https://github.com/EishoTek/hackintosh-ryzen-7900x-msi-mag-b650m-mortar): configurazione
  MSI AM5 documentata su Sonoma, utile per confronto. Il config attuale contiene anche differenze rispetto alla
  descrizione del README; non è stato assunto come immagine certificata della macchina descritta.
- [mikigal/ryzen-hackintosh](https://github.com/mikigal/ryzen-hackintosh): riferimento generale, non una validazione
  della nostra B840. Letto il config corrente, senza eseguire codice scaricato.
- [Dortania, Booter quirks](https://dortania.github.io/OpenCore-Install-Guide/AMD/zen.html#quirks): ReBAR attivo nel BIOS
  richiede `ResizeAppleGpuBars=0` nel percorso documentato. La documentazione locale OpenCore 1.0.8 conferma che
  `0` sceglie la minima dimensione supportata; non significa BAR da zero byte. La dimensione effettiva va misurata.

Sono stati confrontati plist e documentazione, non analizzati né eseguiti i kext delle EFI altrui. Le EFI di riferimento
sono in `research/ext/am5-efi-reference-20261025/`, fuori da git. Nessuna EFI trovata è stata qualificata sulla nostra
esatta combinazione B840 / BIOS 2.A53 / 9060 XT / Tahoe 25G83.

### Preparazione, attivazione e rollback

Generatore locale: `tools/baremetal/prepare-installer-smallbar.py`. Parte da `EFI-next3`, verifica il digest atteso
del config e tutti i file, crea una cartella nuova senza sovrascrivere le varianti precedenti.

- Output: `research/ext/ocboot-baremetal-debug/EFI-installer-smallbar/`.
- Unica differenza semantica: `Booter.Quirks.ResizeAppleGpuBars: -1 → 0`.
- Invariati: patch AMD Tahoe/core count 08, patch ACPI B840, SMBIOS, kext, boot-args, `DevirtualiseMmio=True`,
  `SetupVirtualMap=True`, `UEFI.ResizeGpuBars=-1`. Nessun kext GPU del progetto abilitato.
- Controlli: differenza semantica limitata a una chiave, tutti gli altri file EFI byte-identici, `ocvalidate`
  1.0.8 senza problemi, manifest di 17 file verificato sia localmente sia dopo la copia sulla chiavetta.
- Config attivo OCBOOT SHA256: `007215f872830c78b5995195bf7d37b7ffa54ac09e7a111aadfa05761e136d64`.
- Config precedente SHA256: `d47cad652e11f86d8b912777291922568770aeb1006d1bfc080e5af359586699`.
- Backup sulla chiavetta: `_configs-pre-smallbar-20261025/config.plist`. Per rollback, ricopiare questo solo file
  in `EFI/OC/config.plist`; nessun binario EFI è cambiato. Record locale: `DEPLOYMENT.json` nella nuova variante.
- Nessuna modifica a BIOS, NVRAM o partizioni interne. **Nuova EFI non ancora avviata sul ferro.**

Il resize è applicato per l'avvio macOS; lasciare ReBAR attivo nel firmware ne conserva la disponibilità per Linux
e per la futura configurazione del driver. La fase driver richiederà comunque una misura delle risorse assegnate,
non il ripristino automatico di una BAR da 16 GiB.

### Installazione e ambiente di lavoro

1. Raggiungere la GUI del ripristino, verificare input e display; nessuna installazione automatica.
2. Preparare lo spazio APFS previsto, dopo verifica di filesystem, spazio e geometria. **La partizione macOS non
   esiste ancora**: `/mnt/vm` è Btrfs da 200 GiB, UUID `be2a9624-d2c1-4778-ac99-fcf9258d3328`.
   Il 25/10 ora è `nvme0n1p7`; le note storiche la chiamano `nvme1n1p7`. Usare UUID/GUID e modello, mai il solo nome NVMe.
   Nessun ridimensionamento effettuato in questa sessione.
3. Installare Tahoe 25G83 con il supporto già preparato; verificare primo login e rete Ethernet.
4. Sincronizzare il repo, installare toolchain e Codex. La documentazione ufficiale della
   [CLI](https://learn.chatgpt.com/docs/codex/cli) descrive l'uso locale da terminale su macOS: è la prima opzione
   per non dipendere dalle prestazioni dell'interfaccia grafica non accelerata. Non si è installato né provato
   Codex sul bare metal in questa sessione.
5. Solo dopo, attivare lo stack GPU per passi con i gate e le protezioni del progetto.

## 9. Boot7 negativo; prova MMIO del boot8 (cronologia, esito negativo)

### Evidenza dell'avvio 7

- Foto fornita dall'utente: `/home/pastasugo89/Scaricati/IMG_0666.HEIC`, convertita in PNG solo per lettura in `/tmp`.
  Conferma ultime righe `CoreAnalyticsHub start completed` e `Kext com.apple.iokit.IOTimeSyncFamily is already loaded`.
  Nessun panic/backtrace visibile. Il messaggio del kext già caricato non è una prova della causa del blocco.
- Config effettivamente su OCBOOT: SHA256 `007215f872830c78b5995195bf7d37b7ffa54ac09e7a111aadfa05761e136d64`.
- Log nuovo `opencore-2026-10-25-100347.txt`: 625 righe prima del padding. Copia ripulita dei seriali in
  `research/hw_dump/baremetal_boot7/opencore-sanitized.txt`, originale solo in `research/ext/baremetal-boot7-audit/`.
  Digest di foto, log originale e config in `research/hw_dump/baremetal_boot7/evidence.json`.
- Log righe 435–442: resize eseguito, BAR0 `14→8` (16 GiB→256 MiB), BAR2 `8→1` (256 MiB→2 MiB).
  Questa è evidenza del bootloader, non una misura delle risorse assegnate da XNU.
- Righe 443–451: tutte le cinque regioni MMIO runtime devirtualizzate (`skip 0`), `saved 935936 KB`,
  168 slide validi (88–255). Le due patch DSDT e le patch kernel previste applicate; ultima riga `EXITBS:START`.
- **Conclusione limitata:** la sola BAR0 da 16 GiB non spiega il blocco, perché il resize non lo elimina.
  La causa del blocco interno al kernel resta sconosciuta.

### Perché provare una sola eccezione MMIO

`DevirtualiseMmio` ha risolto l'allocazione iniziale, ma devirtualizzare ogni regione runtime non è automaticamente
corretto. La documentazione OpenCore (`Configuration.txt:859–867,973–984`) prevede eccezioni per le regioni che
il firmware deve continuare a raggiungere tramite runtime mapping.

La regione `0xF7000000`, lunghezza `0x7E00` pagine, è **presente nella nostra mappa**, non ricavata da un'altra EFI.
Il sorgente locale OpenCore (`OcAfterBootCompatLib/ServiceOverrides.c:281–308`) applica la whitelist all'intero
descrittore contenente l'indirizzo: qui `[0xF7000000,0xFEE00000)`, 126 MiB.

Un [resoconto diretto AM5, messaggio #6](https://forum.amd-osx.com/threads/zen-5-9950x-on-asus-b650-kernel-hangs-after-coreanalyticshub-usb-controller-drops-%E2%80%94-now-tahoe-26-7-1-rx-480-busy-timeout-gfx0.6647/)
attribuisce il superamento dello stesso punto alla sola regione F7000000 lasciata in whitelist. Quel sistema aveva
anche altri adattamenti: è un indizio a favore del test, **non una diagnosi o una garanzia per la B840**.

### Preparazione e attivazione per la prossima prova

- Comando ripetibile: `python3 -I tools/baremetal/prepare-installer-smallbar.py --mmio-f700`.
- Output locale: `research/ext/ocboot-baremetal-debug/EFI-installer-mmiof7/`.
- Sola modifica dal boot7: `Booter.MmioWhitelist = [{Address:4143972352, Enabled:true, Comment:...}]`.
- Restano `DevirtualiseMmio=True`, `ResizeAppleGpuBars=0`, `ResizeGpuBars=-1`; invariati kext, patch, SMBIOS e boot-args.
- Verifica semantica indipendente: rimuovendo l'unica entry, il plist coincide con quello del boot7.
  Altri 16 file EFI byte-identici; `ocvalidate` 1.0.8 e tutti i 17 checksum passano localmente e su OCBOOT.
- Config attivato su OCBOOT SHA256: `b19b38865059e382f7fa350c56b16052f200d434c8c50b1781993e52900a568d`.
- Backup boot7 sulla chiavetta: `_configs-pre-mmiof7-20261025/config.plist`; per rollback ricopiarlo in
  `EFI/OC/config.plist`. Nessuna modifica a BIOS, NVRAM o partizioni interne. **Nuova prova non ancora eseguita.**

Criterio nel prossimo log: `F7000000 ... skip 1`, altre regioni `skip 0`; a mappa invariata `saved 806912 KB`.
La memoria runtime conservata cresce di 126 MiB e può ridurre gli slide validi: non impostare uno slide manuale
e non escludere una regressione dell'allocazione. Poi verificare se supera il punto di blocco, senza dedurlo dai checksum.

### Osservazione CPU ancora da valutare (non modificata)

Disassemblate separatamente in sola lettura DSDT e 15 SSDT tramite `iasl` locale 20260930, tutte con exit 0.
`SSDT2` (CPUSSDT) definisce 16 device `ACPI0007` sotto `\\_SB.PLTF.C000..C00F`, UID 0..15;
non sono presenti dichiarazioni legacy `Processor()` nelle tabelle esaminate. La EFI attiva aggiunge soltanto
SSDT-EC-USBX-DESKTOP. È una differenza concreta da valutare per un eventuale adattamento CPU specifico, **non una
causa dimostrata**; non aggiunti SSDT-CPUR, SSDT-PLUG-ALT o CPU fittizie nella prova MMIO.

Una disassemblazione preliminare con namespace condiviso (`iasl -da`) aveva riportato `AE_ALREADY_EXISTS` tra SSDT:
è un risultato del tool in quella modalità, non viene attribuito al boot macOS. Conservati log e DSL solo in
`research/ext/baremetal-boot7-audit/acpi/`; nessuna tabella firmware binaria aggiunta a git.

## 10. Boot8 negativo; nuova base OpCore Simplify (25/10/2026)

L'utente conferma blocco e verbose invariati. Il log `opencore-2026-10-25-104713.txt` verifica la whitelist eseguita,
806912 KB devirtualizzati, 168 slide validi e kernel **25.6.0**. Evidenze ripulite: `research/hw_dump/baremetal_boot8/`.

Preparata e attivata su OCBOOT `research/ext/opcore-simplify-b840-installer-v2/`:

- Simplify upstream fissato al commit `f0e1e441bb455c33e9695a9c9c50e8ca931d4de8`; collector Linux, flag esplicito
  senza accelerazione e correzione del caricamento dei dump ACPI Linux senza estensione. Patch e strumenti in
  `tools/baremetal/`, copia completa modificabile fuori da git.
- Correzione della patch temporale AMD per Darwin 25.4+; la vecchia variante, nel replay sulla BootKC effettiva,
  trovava i primi due match vicino a kperf e VMX invece che ai due punti dello scheduler della variante aggiornata.
  Il replay raggiungeva comunque Count=2: il vecchio `Success` era un controllo insufficiente.
- IOPCIIsHotplugPort per AM5 abilitata; SSDT-PLUG-ALT generata con UID 0..15 dal firmware. La grafica resta senza
  driver del progetto e con `-amd_no_dgpu_accel`. Conservati mappa USB B840 e due patch DSDT; aggiunti NVMeFix e
  RestrictEvents e i kext selezionati nel profilo documentato.
- OpenCore 1.0.8 DEBUG, `ocvalidate` pulito, otto test di integrazione e 28 file verificati. Backup completo boot8:
  `_EFI-pre-simplify-20261025T112158Z/EFI/` sulla chiavetta. BaseSystem invariato, dischi interni intatti.
- Al momento della preparazione la prova era pendente. **Esito boot9: ancora bloccato**, vedere §11.
  Il replay statico non dimostra da solo la causa completa del blocco o l'avvio della GUI.

Fonte, percorsi, differenze, prove e copertura effettiva della documentazione letta:
[`opcore_simplify_linux_b840.md`](opcore_simplify_linux_b840.md).

## 11. Boot9: foto IMG_0667, seriale off, output ACPI (25/10/2026)

Il log `opencore-2026-10-25-113424.txt` e i 28 file della chiavetta corrispondono alla v2 (config `1f8d43cf…`).
Confermate le due patch DSDT, quattro SSDT aggiunte, nuova patch temporale AMD `26.4+` (2 match),
`IOPCIIsHotplugPort` (1 match) e riduzione BAR. Linux espone ora `PNP0501:00/status = 0`.

La foto mostra Lilu, NVMeFix e RestrictEvents con `started/loaded`, poi intestazioni ACPI. L'ultima riga visibile è
`WSMT`, indirizzo `0x8A5D8000`, lunghezza `0x28`: non è un messaggio d'errore. Nessun panic o backtrace visibile.
L'utente conferma Caps Lock senza risposta dopo 2–3 minuti. Questo non distingue da solo un arresto del kernel
da input USB non operativo. Non raggiunta la GUI.

Nel log OpenCore l'ordine delle tabelle è WSMT (19), APIC (20), IVRS (21), altre SSDT (22–25), quattro tabelle
iniettate (26–29). La foto non mostra le righe da APIC in poi. È un riferimento per la prossima cattura,
**non prova che APIC o WSMT siano difettose**, né che l'AML di PLUG-ALT sia già stata eseguita. Il cambio di
schermata non basta per stabilire un avanzamento rispetto ai boot3–8: ordine e visibilità dei messaggi possono variare.

Evidenze ripulite e digest in `research/hw_dump/baremetal_boot9/`; foto originale e log integrale restano locali.
L'ultima riga del log UEFI è ancora `EXITBS:START`, fine della sua copertura, non localizzazione del blocco XNU.

Per il prossimo test: `research/ext/opcore-simplify-b840-acpi-debug/`, preparata da
`tools/baremetal/prepare-acpi-diagnostic.py`. Il solo campo diverso è `NVRAM.Add.…boot-args`, con aggiunti:
`acpi_layer=0xffffffff acpi_level=0x2087 msgbuf=1048576`. `0x2087` seleziona INIT, DEBUG_OBJECT, INFO, LOAD e
TABLES secondo ACPICA; non abilita il tracciamento completo di ogni istruzione AML. Tutti gli altri 27 payload
sono identici e il plist, rimossi questi argomenti, coincide semanticamente con la v2.

Riferimenti: [Dortania kernel debugging](https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/kernel-debugging.html),
[maschere ACPICA 20160930](https://github.com/acpica/acpica/blob/R09_30_16/source/include/acoutput.h).
I messaggi disponibili dipendono dalla build Apple: questi flag non garantiscono un backtrace né log aggiuntivi.
Nessuna nuova SSDT, kext o patch correttiva; la variante serve a migliorare l'osservazione. Registrare il video del
verbose è necessario perché un buffer più grande non persiste da solo dopo il riavvio e OpenCore non salva il log XNU.

Variante diagnostica **attivata su OCBOOT** il 25/10/2026, UTC 20261025T115242Z.
Config SHA256 `8710fe3bb6f4b4e3b18399ad4749d5262c63987ddcf32b18bf02472e794f7551`; 28 file verificati. Backup config: `_config-pre-acpi-debug-20261025T115242Z/config.plist` sulla chiavetta.
`BaseSystem.dmg` invariato (SHA256 `bbfcbf7bfd09c79465fa92c741ebb665625794c31578b81248f7fa0c2bcd4789`).
Al momento del deployment la prova hardware era pendente; vedere il successivo esito boot10. Nessuna modifica a partizioni interne o BIOS.

## 12. Boot10: riavvio spontaneo durante il verbose (25/10/2026)

L'utente riferisce un reset spontaneo, senza foto o video. Il firmware avvia quindi GRUB e Linux come da ordine
abituale. La GUI di ripristino non è stata raggiunta e nessuna installazione è stata avviata: non è un normale
riavvio tra fasi di installazione. Non sappiamo l'ultima riga comparsa o la causa del reset.

Letto OCBOOT in sola lettura: `opencore-2026-10-25-115613.txt`, 642 righe senza padding. Confermati config
`8710fe3b…`, tutti i 28 payload della variante diagnostica, argomenti ACPI effettivi, kernel 25.6.0 e patch AMD/AM5
applicate. `debug=0x100`, `keepsyms=1`, `ApplePanic=True` e `DisableWatchDog=True` sono già configurati.
Il log finisce a `EXITBS:START`, quindi non copre il reset nella fase kernel. Nessun file panic trovato nella radice
USB; questo non esclude un panic non salvato. Non attribuire il reset ai nuovi argomenti sulla base di una sola prova.

Evidenze e digest: `research/hw_dump/baremetal_boot10/`. Nessuna nuova modifica alla EFI. Prossimo passo:
una sola replica con la stessa OCBOOT, registrando dall'inizio del verbose al reset o blocco; poi rientrare in Linux
per leggere log e video. Se si riavvia ancora non ripetere avvii in ciclo e non modificare l'ordine di boot.

## 13. Conservazione dei log: copertura e recupero panic (25/10/2026)

L'utente dispone di **un solo PC**. Non è disponibile un secondo host su cui ricevere la seriale.

- OpenCore DEBUG e `AppleDebug` già salvano log UEFI e `boot.efi` sulla OCBOOT, non il successivo flusso XNU.
- `ApplePanic=True` è già attivo, ma **il file panic viene recuperato al successivo avvio di OpenCore**:
  `OcMiscEarlyInit` chiama `SavePanicLog`, che legge `AAPL,PanicInfo%04x` tramite `OcReadApplePanicLog` e tenta
  di scrivere `panic-YYYY-MM-DD-HHMMSS.txt` nella radice del supporto. È un rapporto di panic, non tutto il verbose.
  Riferimenti OpenCore 1.0.8: `Library/OcMainLib/OpenCoreMisc.c:325,777`,
  `Library/OcBootManagementLib/ApplePanic.c:242`, `Include/Apple/Guid/AppleVariable.h:220`.
- Correzione alla procedura §12: dopo un reset sospetto **rientrare prima nel menu OpenCore con F11 → OCBOOT**,
  interrompendo il countdown con un tasto freccia; poi riavviare verso Linux. Non serve rilanciare macOS per
  attivare il recupero. Nel config corrente il timeout del picker è 5 s. Non fare Reset NVRAM.
- Controllate in sola lettura le sole voci efivarfs con `panic` nel nome: **nessuna presente** al momento
  dell'analisi. Non c'è quindi un rapporto identificato da recuperare adesso. Un reset senza panic, un arresto
  precoce o un rapporto non persistito restano senza questo tipo di evidenza.
- `Booter.Quirks.DisableVariableWrite=False`; `NVRAM.WriteFlash=False` riguarda gli elementi configurati in
  `NVRAM.Add` e non equivale da solo a bloccare tutte le scritture runtime. Nessuna impostazione NVRAM modificata.
- `msgbuf` e DebugEnhancer ampliano/migliorano la diagnostica ma non assicurano un file persistente prima che
  il sistema abbia raggiunto uno stato in cui può salvarlo. Non aggiunto un kext solo per promettere tale risultato.

Per una cattura testuale indipendente dal kernel bloccato, il metodo pertinente è la seriale hardware.
La [scheda tecnica MSI](https://www.msi.com/Motherboard/B840-GAMING-PLUS-WIFI/Specification) conferma JCOM.
Un registratore seriale autonomo su SD può sostituire il secondo PC; richiede cablaggio e livelli elettrici compatibili,
alimentazione e configurazione corretti. Per usarlo occorrerà predisporre una variante di debug e riabilitare COM;
la seriale resta **disabilitata** nella prova corrente. La ricezione conserva i byte realmente trasmessi, non messaggi
che il kernel non riesce a emettere prima del reset.

Fonti: [Dortania, serial logging](https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/kernel-debugging.html#serial-setup-optional),
[OpenCore 1.0.8, salvataggio panic](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Library/OcMainLib/OpenCoreMisc.c),
[OpenCore 1.0.8, lettura panic](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Library/OcBootManagementLib/ApplePanic.c).
Con l'attrezzatura attuale la cattura immediata resta il video del verbose, analizzabile per fotogrammi.
Nessuna modifica alla EFI o ai dischi applicata durante questa verifica.

## 14. Boot11: video del reset e prova con una CPU logica (25/10/2026)

Video originale locale `IMG_0668.MOV`: 123,263333 s, HEVC 1920×1080, frame rate variabile. Estratti un riepilogo
ogni 8 s, 76 fotogrammi a 5 fps negli ultimi 15 s e 119 fotogrammi nativi nell'intervallo finale 119–121 s.
Originale, immagini e OCR restano in locale; il log ripulito e i digest sono in `research/hw_dump/baremetal_boot11/`.
L'OCR è incompleto a causa del testo sovrapposto tra thread: le conclusioni sotto sono controllate sulle immagini,
non dedotte dalle sole trascrizioni automatiche.

### Cosa mostra effettivamente il video

- Intorno a 111 s: messaggi di caricamento riuscito delle tabelle AML e lista `AppleACPICPU`, con processori abilitati
  e slot disabilitati. Questo boot **prosegue oltre la semplice enumerazione ACPI vista nella foto IMG_0667**.
  Non dimostra che tutta l'inizializzazione ACPI o il funzionamento multicore siano corretti.
- Le lunghe sequenze `ExNameSegment: Bytes from stream` sono debug richiesto dal flag LOAD: nel sorgente
  [ACPICA 20160930, exnames.c](https://github.com/acpica/acpica/blob/R09_30_16/source/components/executer/exnames.c#L263)
  i quattro caratteri del nome vengono stampati uno per riga. Da sole non sono errori o corruzione AML.
- Negli ultimi secondi vengono caricati IOHIDFamily, AppleACPIButtons, AppleRTC e AppleHPET.
- Errore leggibile: **`HPET: map device registers failed`**. Ultima riga leggibile prima del nero:
  **`[addMemoryRange()] AppleVTD is not yet installed as gSystem`**. Non vi è un panic o backtrace leggibile.
- Ultimo frame ancora illuminato a **120,676667 s**, primo nero a **120,693333 s**: tempi ottenuti da `showinfo`
  con seek 119 s e associazione all'indice dei PNG nativi. Il video finisce prima di mostrare il successivo POST;
  l'utente **conferma comparsa autonoma di MSI/GRUB**, quindi si tratta di un reset reale.

L'errore HPET è una pista concreta; non dimostra da solo la causa del reset. La DSDT reale contiene già `\\HPET`,
`PNP0103` e `_CRS` con memoria `0xFED00000`, lunghezza `0x400`, IRQ 0/8; `_STA` dipende da HPEN/OSVR.
Non è corretto importare una SSDT HPET di un altro PC o attribuire il reset all'ultima riga AppleVTD senza stack.
La GPU del progetto non è caricata. Nessuna evidenza nuova che attribuisca il reset alla RX 9060 XT.

Log `opencore-2026-10-25-121010.txt`: config `8710fe3b…` e 28 payload della variante diagnostica verificati;
argomenti ACPI effettivi e patch AMD/AM5 applicate. Termina a EXITBS:START come previsto dalla copertura del logger.
Nessun file panic in radice OCBOOT o variabile efivarfs contenente `panic` nel nome. La riga di avvio OpenCore
`Panic log does not exist` riguarda il momento precedente a questo boot, non dimostra che dopo non ci sia stato panic.

### Prossima prova controllata

Variante locale `research/ext/opcore-simplify-b840-cpus1/`, preparata con:

```sh
python tools/baremetal/prepare-acpi-diagnostic.py --single-cpu
```

Unica differenza dalla EFI filmata: aggiunta **`cpus=1`** a `NVRAM.Add.…boot-args`.
È un test del funzionamento con una sola CPU logica, non una diagnosi di TSC o una soluzione permanente.
Il sorgente [XNU i386_init.c](https://github.com/apple/darwin-xnu/blob/main/osfmk/i386/i386_init.c) usa `cpus`
per limitare `max_ncpus`. Gli oggetti ACPI restano invariati e possono ancora essere elencati tutti.
Non sono abilitate patch `_cpu_thread_alloc` che forzino HT nella EFI corrente; il conteggio fisico AMD resta **08**.

Ripristinando il precedente boot-arg il config coincide semanticamente con quello del boot11; gli altri 27 file sono
byte-identici. `ocvalidate` 1.0.8 e 28 checksum verificati. Config candidato SHA256:
`3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976`.

Se supera il reset, il risultato indica sensibilità alla modalità multiprocessore o alle differenze di temporizzazione:
non isola automaticamente una patch temporale specifica. Se fallisce ancora, non assumere eliminato ogni problema CPU;
confrontare il punto visibile e continuare l'analisi delle risorse ACPI/PCI. Nessuna modifica BIOS o partizione necessaria.

Variante `cpus=1` **attivata su OCBOOT**, UTC 20261025T123357Z.
Backup: `_config-pre-cpus1-20261025T123357Z/config.plist`. Config `3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976`.
Confronto semantico indipendente conferma unica aggiunta cpus=1; 28 payload verificati anche dopo il deployment.
Ripristino invariato (SHA256 `bbfcbf7bfd09c79465fa92c741ebb665625794c31578b81248f7fa0c2bcd4789`). Prova hardware ancora da eseguire.

## 15. Boot12: page fault e prova MMIO mirata (25/10/2026)

La foto `IMG_0669.HEIC` è stata conservata nella cartella locale dell'utente; la conversione PNG e i ritagli leggibili
sono in `research/hw_dump/baremetal_boot12/`. Il panic leggibile nella foto è:

```text
panic(cpu 0 caller 0xffffff80164d50da): Kernel trap at 0xffffff80266e8a61, type = 14=page fault
CR2: 0x00000000fed802b0   RIP: 0xffffff80266e8a61   RAX: 0x00000000fed80000
Fault CPU 0, PL 0, VF 1, error code 0
```

Il caller entra nella catena `_sync_iss_to_iks` → `_panic` → trap del kernel; il caller si allinea al simbolo
`_sync_iss_to_iks + 0x3fa` usando il KernelCache slide riportato. Il RIP che ha faultato non è attribuito con certezza:
la foto segnala un frame pointer non allineato/invalid e termina il backtrace. Non compare un kext di terze parti nel
tratto leggibile. La foto riporta Darwin/XNU 25.6.0. Il suffisso della riga boot-args è tagliato dopo `cpus=`; la EFI
usata per il test conteneva `cpus=1`, ma la sola foto non dimostra che XNU lo abbia applicato.

`CR2` è l'indirizzo lineare del page fault, non una prova dell'indirizzo fisico a cui la CPU tentava di accedere.
La sua parte bassa `0xFED802B0` cade numericamente sia nell'OpRegion SystemMemory `GSMM` della DSDT reale
(`0xFED80000`, lunghezza `0x1000`) sia nell'OpRegion `SMIC` (`0xFED80000`, lunghezza `0x800000`), conservate in
`research/hw_dump/baremetal_inventory/acpi/DSDT`. Il log OpenCore specifico di questo avvio,
`opencore-2026-10-25-185831.txt`, riporta `MMIO devirt 0xF7000000 (0x7E00 pages, 0x800000000000100D) skip 0`:
il descriptor EFI osservato copre `[0xF7000000, 0xFEE00000)` e include il valore numerico di CR2. Questo accostamento
giustifica un esperimento sul mapping, ma non prova che CR2 corrisponda fisicamente a quell'area né identifica la
causa del panic. Nessun `panic-*` è stato recuperato; il messaggio OpenCore all'inizio del boot indicava che non
esisteva un panic log precedente.

Per il boot13 è stata preparata dalla config `cpus=1` una sola differenza: `Booter.MmioWhitelist` contiene
`Address=0xF7000000, Enabled=True`. L'indirizzo è la base del descriptor registrato, non CR2. Gli argomenti boot,
le patch CPU e gli altri payload sono rimasti invariati. L'esperimento verifica se preservare questo descriptor
modifica il sintomo; **non è una correzione confermata**. OpenCore 1.0.8 `ocvalidate` passa, tutti i 28 file EFI
coincidono col manifest e i 27 payload non-config sono byte-identici. Config candidata/deployata SHA256
`55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`; backup del precedente config `cpus=1`
SHA256 `3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976` in
`_config-pre-cpus1-mmio-f700-20261025T193127Z/config.plist` sulla sola chiavetta UUID `A140-3052`.
`BaseSystem.dmg` invariato (SHA256 `bbfcbf7bfd09c79465fa92c741ebb665625794c31578b81248f7fa0c2bcd4789`); il supporto è stato
lasciato smontato. Una successiva invocazione di controllo è stata fermata al preflight perché il config USB era già
quello candidato; non ha effettuato una seconda scrittura.

Il precedente test con whitelist F7000000 nei boot7/8 usava una base EFI e patch AMD anteriori; il suo esito negativo
non risolve questa prova con l'EFI aggiornata. Il reset del boot11 resta distinto dal page fault di boot12: non è
dimostrato che abbiano la stessa causa. Riferimenti:
[OpenCore 1.0.8, configurazione](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Docs/Configuration.tex),
[sorgente UEFI OpenCore 1.0.8](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Library/OcMainLib/OpenCoreUefi.c).

### Boot13: GUI Recovery raggiunta, input non operativo

L'utente riferisce che con la EFI `cpus=1` + whitelist `F7000000` il boot supera il logo Apple e mostra una schermata
animata che invita ad accendere Magic Keyboard/Magic Mouse. Tastiera e mouse non rispondono, anche collegati via cavo;
non è ancora confermato l'avvio dell'app Recovery o la presenza delle sue utility. Quindi boot13 ha superato il blocco
precedente e raggiunto una GUI di avvio, ma **non è una Recovery utilizzabile né un'installazione pronta**.

L'inventario read-only dell'host Linux distingue gli endpoint e i controller. `lsusb -t`, sysfs e
`/proc/bus/input/devices` mostrano dispositivi HID funzionanti lato Linux: la NuPhy Node 75 LP collegata direttamente
via USB sta su AMD xHCI `0000:0a:00.3`, porta root 1 (`usb3/3-1`, `HS01` nella mappa); il mouse Compx `3554:f576`
(identificazione USB locale del GravaStar M2) è su `0000:0a:00.4`, porta root 1 (`usb5/5-1`, anch'essa `HS01`).
Entrambi i controller e quelle porte risultano coperti dalla mappa. Sono presenti anche un dongle NuPhy `19f5:2620`
su `0000:05:00.0` porta 1 e un dongle NuPhy/Nordic `19f5:3247` su `0000:0a:00.3` porta 2. Il Bluetooth integrato
`0489:e10a` (Foxconn, `btusb` su Linux) compare su `0000:05:00.0` porta 6. Non sono stati letti eventi o tasti.

Le quattro personality codeless `USBMapB840.kext` contengono i PCI ID dei controller del dump B840:
`XH00` / `1022:43ef` / `\\_SB.PCI0.GPP7.XH00`, `XHC0` / `1022:15b6` / `\\_SB.PCI0.GP17.XHC0`,
`XHC1` / `1022:15b7` / `\\_SB.PCI0.GP17.XHC1`, `XHC2` / `1022:15b8` / `\\_SB.PCI0.GP19.XHC2`.
Questi dati identificano i dispositivi nel firmware/Linux, ma non sono il selettore usato dal plist: ogni personality
mette `IOPCIPrimaryMatch` al livello superiore mentre dichiara `IOProviderClass=AppleUSBXHCIPCI`. La forma è atipica
rispetto al generatore nativo USBToolBox, e non è stata osservata un'IORegistry macOS del boot13 che provi il bind.
Le porte restano definite (XHC0 e XHC1: `HS01` porta 1, `HS02` porta 2, `SS03` porta 3, `SS04` porta 4; XH00
14 porte; XHC2 una porta). `model=MacPro7,1` coincide con lo SMBIOS configurato. In config
`UEFI.Quirks.ReleaseUsbOwnership=True` e `Kernel.Quirks.XhciPortLimit=False`; il primo non verifica l'opzione XHCI
hand-off del BIOS, che resta ignota. Nessuna corrispondenza di porte al jack fisico è dedotta dalla sola ACPI path.

Per il Boot14 è stata deployata su OCBOOT A140-3052 una variante che cambia unicamente i selettori delle quattro
personality: `research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch/`. Usa il pattern per mappe native
prodotto da USBToolBox: `IOProviderClass=AppleUSBHostController` e
`IOParentMatch={IOPropertyMatch={pcidebug="bus:device:function"}}`, con BDF dal dump Linux `5:0:0`, `10:0:3`,
`10:0:4`, `11:0:0`. Port-count, port data, bundle, class, score e model restano identici. `config.plist` resta
SHA256 `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`; gli altri 27 payload EFI sono byte-identici.
Preflight e postmanifest 28/28 hanno verificato le sole cartelle `EFI/`; `ocvalidate` OpenCore 1.0.8 passa il config
USB e il parsing/invarianza del plist passa. `ocvalidate` non prova il matching IOKit. Backup e record con hash
prima/dopo sono in `research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch/deploy-evidence/`.
SHA256 Info USBMap originale `e351c06e26aba4b6aac63fdb804e06398ba7ae2fbd9713266ac2f149963cbecd`, candidata attiva
`9249e728191fc64b8685407fe4f7446049be988dd9fec30e427262a37ece5edb`.

**Esito Boot14:** l'utente riferisce la stessa schermata animata di pairing di Boot13 e nessun input. Le prove includono
NuPhy e mouse sia via dongle sia cablati, collegati direttamente alle porte della scheda madre. Non è confermato che
siano comparse la GUI Recovery e le sue utility. Il risultato negativo non dimostra che il nuovo selettore sia errato:
senza IORegistry/log runtime macOS non sappiamo se il match parent abbia selezionato i controller. La schermata resta
compatibile con l'assistente Bluetooth; Apple documenta il pairing Recovery, ma la guida consultata è per Apple silicon
e non prova che il flusso sia identico nell'EFI x86. Non è noto un flag documentato per saltarla; saltarla non
renderebbe comunque disponibile un HID. `ReleaseUsbOwnership=True` non dimostra l'impostazione BIOS XHCI hand-off.

Per discriminare il mapping dal percorso nativo, è stata deployata su OCBOOT UUID `A140-3052` una sola variante
**Boot15, test hardware pendente**: `research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch-usb-native/`. Cambia solo
`Kernel.Add[USBMapB840.kext].Enabled` da `true` a `false`, disabilitando l'intera personality codeless e la fusione
della mappa port-count/porte. `config.plist` SHA256 `7bbf4e3e3eaf7ec13aa52780c82412a9b2a5b9dac8de98cba990fb4d884cdafb`;
il manifest elenca 28 file, con solo il config diverso e gli altri 27 identici alla base Boot14; `ocvalidate` 1.0.8
passa. Il backup del config Boot14 SHA256 `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`,
la verifica pre/post, l'output `ocvalidate` sul target e gli script deploy/verifica/rollback sono in
`research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch/deploy-evidence/boot15-20261025T202535Z/`.
Il verifier separato ha confermato manifest Boot15 28/28, SHA del config, Info USBMap invariato e `ocvalidate`; la
chiavetta è smontata. Controller xHCI nativi, boot-args (`cpus=1`, whitelist `F7000000`), altri kext e gli altri file
EFI restano uguali. I limiti di porta dichiarati dalla mappa sono 14/4/4/1, tutti entro 15; senza mappa macOS può
comunque esporre le porte con tipologia predefinita e non c'è garanzia che l'input funzioni. Dortania avverte che la mappa
affidabile si verifica con IORegistry macOS e descrive il default senza mappa come USB 2.0; l'esito del controllo
quindi discrimina l'insieme map/binding da ciò che resta, ma non separa da solo ogni dettaglio.

Se l'input funziona con Boot15, la mappa o il suo binding diventa il ramo causale probabile, da confermare. Se resta
inattivo, il candidato map/binding perde supporto e restano driver/controller, hand-off, topologia ACPI e input stack;
il prossimo test dovrebbe usare una sola porta fisica USB 2.0 posteriore verificata lato Linux per controllare un
root-port diverso. Il test Boot15 non è ancora stato fatto. La chiavetta resta smontata. Il digest BaseSystem
precedente resta un riferimento, senza nuova verifica; le scansioni recenti hanno limitato la verifica ai file EFI.
Riferimenti: [Dortania, USB mapping manuale](https://github.com/dortania/OpenCore-Post-Install/blob/master/usb/manual/manual.md),
[Dortania, preparazione USB e AMD](https://github.com/dortania/OpenCore-Post-Install/blob/master/usb/system-preparation.md),
[Dortania, troubleshooting USB/handoff](https://github.com/dortania/OpenCore-Install-Guide/blob/master/troubleshooting/extended/kernel-issues.md),
[USBToolBox, generazione del match parent nativo](https://github.com/USBToolBox/tool/blob/master/base.py),
[Apple IOKit matching](https://developer.apple.com/library/archive/documentation/DeviceDrivers/Conceptual/IOKitFundamentals/Matching/Matching.html),
[Apple Support, pairing Bluetooth in Recovery](https://support.apple.com/guide/mac-help/macos-recovery-a-mac-apple-silicon-mchl82829c17/mac),
[Apple Support, tastiere cablate e Bluetooth](https://support.apple.com/guide/mac-help/keyboard-and-trackpad-mchlgtd_kbdtrk01/27/mac/27),
[MSI, specifiche e gruppo USB posteriore](https://www.msi.com/Motherboard/B840-GAMING-PLUS-WIFI/Specification).

## 16. BOOT16: mappa nativa USBToolBox generata da Linux (25/10/2026)

BOOT15 con `USBMapB840.kext` disabilitata non è stata avviata: rimane una prova pendente e non ha esito negativo.
Per la prova successiva la mappa è stata ricostruita senza spostare cavi. L'adattatore locale
`tools/baremetal/usbtoolbox_linux_port.py` legge la topologia sysfs già verificata e riusa il builder ufficiale
`BaseUSBMap.build_kext()` al commit USBToolBox `0c6823a2c643a4488888938451194723dc9ae29a` (MIT). Il sorgente upstream
resta invariato; il backend è un adattamento Linux locale. La generazione produce una personality nativa
`AppleUSBHostMergeProperties` con match `AppleUSBHostController` / `IOParentMatch` e PCI ID padre univoci; i BDF Linux
sono mantenuti solo nei metadati. Non è stato aggiunto un eseguibile o il runtime USBToolBox.kext.

La candidata include tutti i raw port verificati dal firmware: XH00 14, XHC0 4, XHC1 4, XHC2 1, tutti sotto il
limite 15. `UsbConnector=255` è riservato ai tre endpoint interni osservati: Mystic Light (`0db0:0076`, XH00 raw 9),
Bluetooth (`0489:e10a`, XH00 raw 10) e il root upstream del hub GL850 (`05e3:0608`, XHC2 raw 1). Gli altri tipi sono
assunzioni: XH00 raw 11–14 restano inclusi con classe USB2 in base al conteggio degli header USB2, senza attribuzione
dei singoli jack; le coppie USB2/SuperSpeed non mappate fisicamente usano il default USB3-A (`UsbConnector=3`). Il
manuale MSI conferma che esistono prese Type-C ma non le associa a un raw port né documenta lo switch USB-C; tale
identità e la negoziazione SuperSpeed restano ignote. Queste ipotesi conservano le porte, non certificano il tipo
fisico. Nessuna porta è dichiarata collaudata su macOS.

La mappa nativa prodotta è `research/ext/usbtoolbox-linux-port-candidate/USBMap.kext/Contents/Info.plist` (SHA-256
`e1ddb59febdddcb63ecf309b37f454159ff23396ae1f511099c4fc94a1065312`). Per mantenere il cambiamento minimo, la EFI
BOOT16 riusa il percorso già presente `EFI/OC/Kexts/USBMapB840.kext` e sostituisce il suo `Contents/Info.plist`;
`Kernel.Add` viene riabilitata nel config (`55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`).
Il preflight sulla chiavetta OCBOOT UUID `A140-3052` ha verificato il manifest BOOT15 completo (28/28) prima di
creare il backup esterno. Le sole due differenze dopo la scrittura sono `EFI/OC/config.plist` e
`EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist`; i restanti 26 file sono identici al BOOT15. Il manifest candidato
28/28 è passato e `ocvalidate` OpenCore 1.0.8 ha restituito 0, senza issue. L'Info è stata sostituita prima del config
(per ultimo); il backup con hash e il record del risultato sono in
`research/ext/usbtoolbox-linux-port-candidate/deploy-evidence/20261025T220633/`. La chiavetta è stata smontata dopo
la verifica. `tools/baremetal/deploy-usbtoolbox-map-b840.py` documenta i controlli di identità, backup, sostituzione
atomica, validazione e rollback.

BOOT16 è stata avviata; l’utente riferisce la stessa schermata animata di pairing e input assente. Questo esito non prova che il match IOKit sia riuscito o fallito. BOOT15 resta non provata. La verifica del nuovo schema Tahoe, l’adattatore aggiornato e la correzione BOOT17 attiva sono in §17 e `research/reports/usb_tahoe_schema_diagnosis_20261026.md`. Riferimenti e comando di generazione BOOT16 restano in `research/reports/usb_mapping_b840_linux_20261025.md`.


## 17. BOOT16 negativa per input e verifica schema Tahoe (26/10/2026)

L’utente riferisce che BOOT16, già avviata, mostra ancora la schermata animata Magic Keyboard/Mouse e non accetta input. BOOT15 con mappa disabilitata non è stata avviata. Non è confermato che si tratti della Recovery completa né che le personality USB siano state selezionate: non abbiamo IORegistry/log macOS del boot. Il risultato non dimostra che la mappa sia l’unica causa.

Nel plist BOOT16 sono state contate 23 porte (14/4/4/1), con zero occorrenze di `usb-port-number` e zero di `usb-port-type`; ogni porta ha invece `port` Data e `UsbConnector` intero. Nel sorgente USBToolBox kext 1.2.0 `fixMapForTahoe()` copia proprio i valori legacy alle proprietà `usb-port-number` e `usb-port-type`, e `mergeProperties()` applica il helper alle porte quando Darwin major >=25. BOOT16 usa la mappa nativa `AppleUSBHostMergeProperties` e non include USBToolBox.kext, quindi quel codice runtime non viene eseguito. La release descrive il supporto Tahoe come WIP. È una lacuna concreta della mappa e una spiegazione plausibile; non è ancora una causa confermata. Fonti, confronto e ambiti ignoti: `research/reports/usb_tahoe_schema_diagnosis_20261026.md`.

La correzione è stata aggiunta anche all’adattatore `tools/baremetal/usbtoolbox_linux_port.py`: per ogni porta verifica e copia `port` in `usb-port-number` e `UsbConnector` in `usb-port-type`, lasciando intatte le chiavi legacy. Una nuova generazione con il builder ufficiale ha riprodotto byte per byte la stessa Info BOOT17 (SHA-256 `71f93330cf748e5a58bfa856c47abd35d80798c8272d7f0bf702c7312f04dd7d`): `research/ext/usbtoolbox-linux-tahoe-regeneration-final-20261026/USBMap.kext/Contents/Info.plist`.

BOOT17 è attiva su OCBOOT UUID `A140-3052`, **test hardware pendente**. La copia è partita dal manifest BOOT16 28/28, ha creato fuori EFI il backup Info BOOT16 SHA `e1ddb59febdddcb63ecf309b37f454159ff23396ae1f511099c4fc94a1065312`, sostituito atomicamente solo `EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist` e superato manifest 28/28 e `ocvalidate` OpenCore 1.0.8. Nuovo Info SHA `71f93330cf748e5a58bfa856c47abd35d80798c8272d7f0bf702c7312f04dd7d`; config `55d53e17…` invariata, altri 27 file identici a BOOT16. Backup e record: `research/ext/usbtoolbox-linux-tahoe-boot17-candidate/deploy-evidence/20261026T131317524219Z/`. Un primo tentativo automatizzato con percorso sorgente errato ha fatto rollback verificato BOOT16 28/28; il rilancio corretto è passato. La chiavetta è smontata. Nessuna modifica BIOS o spostamento cavi. Il prossimo test singolo usa BOOT17 con gli stessi dispositivi e senza variare altro; se l’input resta assente, acquisire IORegistry/log USB prima di cambiare runtime, BIOS o porte.

## 18. Recovery BOOT17 raggiunta: inventario read-only e piano installazione (26/10/2026)

L’utente conferma che con BOOT17 la tastiera e il mouse USB funzionano e il sistema è arrivato a macOS Recovery. La schermata non è accessibile alla shell Linux della workspace: Utility Disco, rete e installer restano da confermare sulla Recovery dal vivo. Nessuna installazione o scrittura su dischi interni è stata eseguita.

La shell della workspace è `Linux MSI-Desktop` (CachyOS x86_64), non un Terminale collegato alla Recovery. L’inventario read-only `lsblk`/`findmnt` vede:

| Elemento nel Linux host | Metadati osservati | Interpretazione/limite |
|---|---|---|
| `/dev/sda1` SanDisk Cruzer Fit, 14,3 GiB, FAT32, UUID `A140-3052` | Nessun mountpoint | OCBOOT è smontata nell’host Linux; non è una vista della Recovery. |
| Samsung `MZVLQ256HBJD-00BH1`, 238,5 GiB | EFI FAT32 512 MiB e Btrfs 238 GiB montato come `/` | Disco del Linux host; non usarlo come destinazione macOS. |
| Lexar EQ790 1 TB, 931,5 GiB | p1 FAT32 100 MiB; p2 16 MiB; p3 NTFS 728,1 GiB; p4 NTFS 823 MiB; p5 FAT32 1 GiB; p6 NTFS 742 MiB; p7 Btrfs 200 GiB | Nessuna partizione APFS/macOS compare nei metadati attuali. Il precedente spazio libero di circa 200 GiB tra p3 e p4 è stato usato per creare p7 (vedi `vm_storage_partition.md`). `parted print free` non è riuscito per permessi; non si certifica qui l’eventuale slack GPT. |
| Lexar p7, Btrfs UUID `be2a9624-d2c1-4778-ac99-fcf9258d3328`, `/mnt/vm` | `df`: 117 GiB usati, 82 GiB disponibili su 200 GiB | Contiene immagini VM, build e backup secondo i documenti. Il vecchio piano di ridurlo a 60 GiB non è applicabile all’occupazione corrente: usato supera già 60 GiB. Non ridurre senza un piano di preservazione e verifica. |
| SanDisk USB da 128 GB | Non compare nel `lsblk` di questa shell | I documenti riportano filesystem exFAT e solo il percorso autorizzato `macOS-Tahoe-25G83-installer/Tahoe25G83.iso`; il supporto non è visibile qui. Non sono stati elencati né letti altri contenuti personali. |

Il report precedente documenta l’ISO completa `/mnt/vm/installers/tahoe-25G83/Tahoe25G83.iso` (18 424 877 056 byte, SHA-256 `376923d7494cfa32b69f383bcfdce46aeedb609fe6a242ea12a6e015bfb77ba4`). È un supporto ISO/HFS+ con l’app di installazione completa, SharedSupport e `run-tahoe-installer.sh`, non una chiavetta di avvio autonoma. Nella guida `VM_MACOS.md` il percorso è montare l’ISO e avviare `sh "/Volumes/Tahoe25G83/run-tahoe-installer.sh"`; l’installazione completa è stata verificata nella VM fino a Setup Assistant, ma questo non prova il percorso in Recovery sul PC. La EFI include `LucyRTL8125Ethernet.kext` per la NIC Realtek 8125; non sappiamo se Recovery abbia riconosciuto Ethernet o se la rete funzioni. La strada locale potrebbe quindi evitare il download, se il supporto si monta correttamente.

Prossimo passo autorizzato e senza scritture: lasciare OCBOOT collegata, connettere la chiavetta da 128 GB solo per rendere disponibile l’ISO e, dalla Recovery, aprire **Utility → Terminale** ed eseguire `diskutil list`. Inviare il testo o una foto dell’elenco prima di aprire Utility Disco o selezionare un disco. Questo permette di identificare i device nel sistema Recovery (che può assegnare nomi diversi da Linux) e verificare se è presente spazio non allocato. Per ora non eseguire `eraseDisk`, `partitionDisk`, inizializzazione, ridimensionamento o formattazione.

Dopo l’identificazione, il piano è verificare i metadati del solo volume esterno (modello/capacità/filesystem), montare l’ISO in sola lettura dalla sua cartella autorizzata, confermare che app e launcher compaiano nel volume `Tahoe25G83`, quindi avviare il launcher documentato. Solo dopo aver identificato separatamente la destinazione si potrà pianificare una partizione APFS senza cancellare l’intero Lexar né le partizioni Windows/Linux. Se non esiste spazio non allocato sufficiente, fermarsi: la p7 attualmente contiene più dati della dimensione prevista dal vecchio piano.

Apple documenta il flusso generale di [reinstallazione da macOS Recovery](https://support.apple.com/it-it/102655) e il formato [APFS in Utility Disco](https://support.apple.com/it-it/guide/disk-utility/dskua9e6a110/mac). Sono riferimenti per le funzioni standard, non istruzioni per inizializzare l’intero disco in questo PC dual-boot non Apple. La shell Linux della workspace non può leggere o controllare l’interfaccia Recovery: i comandi `diskutil` sopra sono da eseguire dall’utente sulla Recovery stessa.
