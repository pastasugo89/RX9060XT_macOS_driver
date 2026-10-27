# Audit EFI per l’avvio di Recovery su AM5 — 25 ottobre 2026

## Esito operativo

Al momento della stesura iniziale (prima del Boot13), la prova immediata giustificata dalle evidenze era `cpus=1`, poi testata sul PC. L'esito aggiornato e la prova input Boot14 sono registrati in fondo a questo audit. La prima analisi non aggiungeva kext, argomenti o SSDT: le alternative esaminate o erano già coperte dalla EFI, o appartenevano a grafica accelerata, gestione energetica, modelli CPU ibridi, oppure a sintomi PCI non corrispondenti al punto raggiunto.

Il video del boot11 mostra una fase di avvio più avanzata dell’elenco ACPI: vengono caricati AppleACPICPU, IOHIDFamily, AppleACPIButtons, AppleRTC e AppleHPET. Seguono `HPET: map device registers failed` e la riga AppleVTD; il video diventa nero e l’utente conferma il ritorno a MSI/GRUB. Non appare panic o backtrace. Queste ultime righe non stabiliscono la causa del reset.

## Audit della configurazione pronta

La cartella candidata è `research/ext/opcore-simplify-b840-cpus1/`. Ho verificato sia la copia locale sia il file presente sulla partizione `/dev/sda1` identificata dal solo UUID `A140-3052`:

- SHA-256 del `config.plist`: `3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976` su entrambe le copie.
- Tutti i 28 file sotto `EFI/` corrispondono al manifest locale; la radice USB non contiene il manifest.
- `ocvalidate` della stessa release OpenCore 1.0.8 non segnala problemi sul config USB effettivo né sulla copia locale.
- Il confronto plist con la variante diagnostica del boot11 è identico dopo aver rimosso `cpus=1` dalla stringa `boot-args`. È l’unica differenza semantica; gli altri 27 payload sono invariati.
- Gli argomenti effettivi letti dal config USB sono `-v debug=0x100 keepsyms=1 -amd_no_dgpu_accel kextlog=0xffff acpi_layer=0xffffffff acpi_level=0x2087 msgbuf=1048576 cpus=1`.
- La patch AMD di core count resta `BA 08 00 00 00` (otto core fisici), con `ProvideCurrentCpuInfo=True` e `Kernel.Emulate.DummyPowerManagement=True`. `cpus=1` limita il numero di CPU logiche usate da XNU; non si deve cambiare il valore fisico `08` in `01`.
- Il controllo della chiavetta è stato in sola lettura; dopo la verifica è stata lasciata smontata come prima. Nessun altro volume è stato consultato.

La verifica non ha riletto integralmente `BaseSystem.dmg`; il record del deployment conserva il digest raccolto prima e dopo la scrittura. La prova hardware è ancora pendente.

## Kext, patch e argomenti

| Elemento | Stato sulla EFI e significato | Decisione per il prossimo avvio |
|---|---|---|
| Patch AMD per Tahoe 25.6 | AMD_Vanilla documenta il supporto Ryzen 7000 e il core count in core fisici. Il commit `2878877` separa la vecchia patch temporale, limitata a Darwin 25.3.99, dalla nuova variante 25.4+ usata qui. Il replay già conservato sulla BootKC effettiva 25.6 trova la variante nuova vicino a `_thread_block_reason` e `_thread_dispatch`; i vecchi pattern avevano matchato altre funzioni. | Conservare patch temporale 25.4+, conteggio fisico `08` e patch AM5 già auditati. Il conteggio `Success` di OpenCore da solo non è prova della destinazione; la BootKC e il replay sono il controllo utile. |
| `AppleMCEReporterDisabler` | Presente, v1.2; il log OpenCore del boot11 registra l’iniezione riuscita. La FAQ AMD-OSX lo richiede per macOS 12.3 e successivi per il problema AppleMCEReporter. | Già copre quel caso; non spiega il reset osservato e non va duplicato. |
| `RestrictEvents` | Presente, v1.1.7 e caricato. Il progetto documenta patch di brand CPU e restrizioni/UI per configurazioni Mac; non è un driver di avvio SMP, ACPI o HPET. | Lasciare invariato. |
| `CpuTopologyRebuild` | Assente. Il README del progetto lo limita alle CPU Intel ibride Alder/Raptor Lake e ad Arrow Lake sperimentale; non al Ryzen 7 7700. La regola corrente di 1401 che lo seleziona è specifica di Arrow Lake. | Non aggiungere a Zen 4. |
| `NullCPUPowerManagement` e gestione AMD | `NullCPUPowerManagement` assente; `Kernel.Emulate.DummyPowerManagement=True` è già configurato. Dortania descrive DummyPowerManagement come alternativa per i sistemi AMD. Il kext comunitario `AMDRyzenCPUPowerManagement` è destinato a funzioni aggiuntive di power management e la guida post-install avverte che può causare instabilità o problemi di boot. | Non sostituire né sovrapporre questi meccanismi durante il test di bootstrap. Nessun bisogno dimostrato di introdurre power management AMD. |
| `SSDT-CPUR`, CPU ACPI | Dortania include `SSDT-CPUR` per le piattaforme AMD Zen B550/A520 e successive, perché corregge definizioni CPU ACPI. La EFI locale usa invece `SSDT-PLUG-ALT.aml` generata dalla tabella firmware reale: UID 0–15 per 16 oggetti `ACPI0007` sotto `_SB.PLTF`, verificati nel report precedente; non importa il prebuilt generico. | Conservare la tabella adattata alla DSDT B840. Il video mostra che AML e AppleACPICPU vengono caricati; non prova comunque che la gestione multicore sia corretta. |
| `SSDT-EC`, `SSDT-USBX`, mappa USB | Entrambe le SSDT sono abilitate. `USBMapB840.kext` è caricato; mappa quattro controller e le porte USB 1–14. Nel video non compare “Waiting for root device”, ma l’avvio della BootKC da solo non convalida tutti i controller e le porte USB. | Per il test singolo pendente non introdurre ulteriori modifiche USB: niente USBToolBox/UTBDefault, reset USB generico o modifiche alle mappe senza un sintomo che le giustifichi. |
| GPU senza accelerazione | `-amd_no_dgpu_accel` è già presente e viene passato al kernel. Dortania lo documenta come flag Apple per avviare AMD in VESA, alternativa al flag WEG `-radvesa`. Non sono iniettati WhateverGreen o kext GPU del progetto. Il README di 1401 documenta una propria regola Tahoe che rimuove WhateverGreen e i suoi argomenti per sistemi AMD; è una scelta implementativa dichiarata da 1401, non una prova universale che WEG fallisca su ogni Tahoe. | I flag WEG `-radvesa` e `-wegnoegpu` non offrono qui un beneficio dimostrato rispetto a `-amd_no_dgpu_accel`; `-radvesa` è un’opzione di WhateverGreen per la modalità VESA, mentre `-wegnoegpu` ha lo scopo di disabilitare le GPU esterne. |
| `npci` / PCI | Above 4G e ReBAR sono attivi, `ResizeAppleGpuBars=0`, `ResizeGpuBars=-1`; il boot11 procede oltre l’inizializzazione ACPI iniziale e mostra AppleHPET. La FAQ AMD-OSX indica `npci=0x3000` come percorso alternativo quando si disattiva Above 4G per blocchi presso AppleACPICPU; la guida Dortania dice di non combinarli. `pci-debug` è anche il nome di un campo IORegistry in documentazione Apple, non una ricetta da copiare come argomento `pci-debug=`. | Nessun `npci` per questa prova: la modalità BIOS attuale è l’alternativa documentata e il reset non si manifesta al punto “PCI configuration”. Non modificare BIOS. |
| TSC e altri flag CPU | `cpus=1` è elencato nel riferimento OpenCore come massimo numero di CPU usate. Il boot log mostra la stima OpenCore TSC intorno a 3,8 GHz; il video non mostra il panic “non-monotonic time” né una traccia di mancata sincronizzazione TSC. | Non sommare flag TSC, `pci-debug` o altri argomenti. Registrare prima l’esito della singola modifica già pronta; `cpus=1` da solo non prova né corregge una causa TSC. |

Disabilitare l’accelerazione AMD cambia il percorso del driver grafico e mantiene la visualizzazione di base GOP. Non elimina la scansione dei processori, l’avvio dei servizi ACPI, l’enumerazione PCI, la gestione della mappa memoria o le dipendenze firmware del kernel. È quindi coerente mantenere la GPU custom fuori dal test e non interpretare la modalità VESA come una prova che CPU/ACPI/firmware siano irrilevanti.

## Passo operativo condizionale

Eseguire una volta la EFI già pronta con acquisizione video continua dall’avvio OpenCore. Non occorre un reset NVRAM o una modifica BIOS. Il criterio positivo è un avanzamento osservabile fino alla GUI di Recovery, non semplicemente una riga finale diversa.

- Se raggiunge la GUI o supera nettamente il punto del reset, il risultato dimostra sensibilità al numero di CPU logiche o alla temporizzazione, ma non identifica una patch SMP o TSC. Solo dopo aver conservato il video si può preparare una seconda prova numerica (per esempio `cpus=8`) con un’unica variazione, per capire se il limite dipende dal numero di CPU attive.
- Se resetta ancora nello stesso intervallo, `cpus=1` non basta a sbloccare l’avvio. Non c’è allora una base per aggiungere kext CPU, cambiare `npci` con Above 4G attivo, importare una SSDT HPET da altra scheda o alterare altri argomenti. Prima di una nuova EFI, confrontare in sola lettura le risorse HPET/mappa memoria esposte dal firmware Linux con quelle già annotate e usare un’eventuale differenza osservabile per scegliere una sola modifica successiva.
- Se il punto del reset si sposta, preservare il filmato e trattarlo come informazione sul confine raggiunto, non come causa confermata.

## Fonti primarie consultate

- [AMD-OSX AMD_Vanilla](https://github.com/AMD-OSX/AMD_Vanilla) e [commit AMD_Vanilla 2878877 per Darwin 25.4+](https://github.com/laobamac/AMD_Vanilla/commit/28788772e05a434dd06c149833a20d76151117f5).
- [OpenCore Configuration 1.0.8](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Docs/Configuration.tex), [riferimento OpenCore ai boot-args come `cpus=VALUE`](https://dortania.github.io/docs/latest/Configuration.html) e [guida AMD Zen di Dortania](https://dortania.github.io/OpenCore-Install-Guide/AMD/zen.html).
- [Dortania: SSDT AMD EC/USBX e CPUR](https://github.com/dortania/Getting-Started-With-ACPI/blob/master/ssdt-methods/ssdt-prebuilt.md) e [Dortania: flag GPU](https://dortania.github.io/GPU-Buyers-Guide/misc/bootflag.html).
- [WhateverGreen, boot arguments](https://github.com/acidanthera/WhateverGreen) e [RestrictEvents](https://github.com/acidanthera/RestrictEvents).
- [CpuTopologyRebuild](https://github.com/b00t0x/CpuTopologyRebuild), [guida Dortania al power management AMD](https://dortania.github.io/OpenCore-Post-Install/universal/pm.html), [FAQ AMD-OSX su AppleMCEReporter/AppleACPICPU](https://github.com/AMD-OSX/AMD-OSX-FAQ/blob/main/faq.txt) e [Apple: debug delle fault VT-d/PCI](https://developer.apple.com/library/archive/documentation/HardwareDrivers/Conceptual/ThunderboltDevGuide/DebuggingThunderboltDrivers/DebuggingThunderboltDrivers.html).
- [1401: regole applicate a Tahoe e troubleshooting del bootstrap](https://github.com/nullmoth/1401) (riferimento alle decisioni dichiarate da quel progetto, non garanzia trasferibile a questa scheda).

## Aggiornamento dopo Boot12 (25/10/2026)

L'esito hardware successivo non è più pendente: la foto `IMG_0669` mostra un page fault XNU 25.6.0 su CPU 0
(`CR2=0xFED802B0`, `RIP=0xffffff80266e8a61`); il backtrace leggibile non attribuisce il RIP a un'immagine e termina
su un frame pointer invalido. Il valore di CR2 è un indirizzo lineare: coincide numericamente con gli OpRegion DSDT
`GSMM`/`SMIC` a base `0xFED80000` e ricade nel descriptor EFI `0xF7000000–0xFEE00000` registrato nel log di boot12,
ma ciò non dimostra una mappatura fisica o una causa. Il reset boot11 rimane un evento distinto.

Per la prova successiva è stata attivata su OCBOOT UUID `A140-3052` una variante derivata dalla cpus=1 con sola voce
`Booter.MmioWhitelist` alla base `0xF7000000`: config SHA256 `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`;
backup precedente SHA256 `3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976`. Tutti i 28 file EFI, `ocvalidate`
1.0.8 e l'invarianza di `BaseSystem.dmg` sono stati ricontrollati; la chiavetta è smontata. La variante è un esperimento
su descriptor, non una correzione provata. Una seconda invocazione del deploy è stata fermata dal preflight perché
il config era già aggiornato: nessuna seconda scrittura è avvenuta. Il risultato successivo è riportato qui sotto.

## Aggiornamento dopo Boot13 e preparazione Boot14 (25/10/2026)

Boot13 con `cpus=1` e whitelist F7000000 supera il logo Apple e raggiunge una schermata animata di pairing Bluetooth
Magic Keyboard/Mouse. La NuPhy Node75 e il mouse GravaStar M2 non rispondono anche collegati via cavo; la NuPhy cablata
risulta HID funzionante in Linux. Non è confermato che la schermata Recovery/utilità sia già stata raggiunta. La guida
Apple descrive il pairing in Recovery come procedura per accessori Bluetooth e dice che l'assistente non appare se è
già collegato un input; la fonte consultata è specifica per Apple silicon e non dimostra identico flusso sull'EFI x86.
Non è stato trovato un flag Apple documentato per saltare l'assistente, e saltarlo non renderebbe disponibile un HID.

La verifica del plist USB ha trovato una forma di selettore non canonica: `IOPCIPrimaryMatch` è al livello superiore
di ogni personality, che dichiara `IOProviderClass=AppleUSBXHCIPCI`. La forma nativa generata da USBToolBox usa invece
`IOProviderClass=AppleUSBHostController` con `IOParentMatch={IOPropertyMatch={pcidebug="B:D:F"}}`. È stata quindi
deployata su OCBOOT `A140-3052` una variante per Boot14 che cambia solo i quattro selettori USBMap: BDF `5:0:0`,
`10:0:3`, `10:0:4`, `11:0:0`; port mapping, model, kext set, boot args e config restano uguali al Boot13.
Il config resta SHA256 `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`; 28/28 file EFI combaciano
con il manifest candidato e `ocvalidate` 1.0.8 passa il config. Il backup dell'Info originale (`e351c06…`), il nuovo
hash (`9249e72…`), i manifest e il record sono in
`research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch/deploy-evidence/`. Il selettore è una possibile
spiegazione del mancato input, non un difetto o fix runtime provato. La chiavetta è smontata; il digest BaseSystem
precedente resta solo un riferimento, senza nuova verifica: un controllo inline interrotto aveva tentato per errore
la scansione/hash dell'intero volume, ma non è noto se abbia raggiunto BaseSystem e non ha prodotto un nuovo digest.
La scrittura e il successivo postcheck hanno scandito solo `EFI/`. In quel momento il test Boot14 era pendente; il
risultato negativo è riportato nell'aggiornamento seguente.
`ReleaseUsbOwnership=True` non stabilisce l'impostazione XHCI hand-off del BIOS, che resta ignota.

## Aggiornamento dopo Boot14, preparazione e deploy del controllo Boot15 (25/10/2026)

L'utente riferisce che Boot14 mostra la stessa schermata animata di pairing di Boot13 e che NuPhy e mouse restano
inattivi. Ha provato gli input sia con i dongle USB sia cablati, collegandoli direttamente alla scheda madre.
La GUI Recovery/utilità non è ancora confermata. Il BOOT14 selector-only non ha quindi risolto il sintomo, ma il
risultato da solo non prova il mancato binding: non abbiamo IORegistry o log runtime macOS con cui sapere se le
personality abbiano selezionato i controller.

Il controllo discriminante pronto è una sola variante, deployata sulla sola EFI e non testata su hardware:
`research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch-usb-native/`. Deriva dalla base Boot14
(`config.plist` SHA256 `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`) e cambia solo
`Kernel.Add[USBMapB840.kext].Enabled` da `true` a `false`. Questo disabilita le quattro personality codeless e il
merge delle porte, lasciando intatti controller nativi Apple, `cpus=1`, whitelist `F7000000`, altri kext, tabella
porte e tutti gli altri payload. Il config BOOT15 SHA256 è
`7bbf4e3e3eaf7ec13aa52780c82412a9b2a5b9dac8de98cba990fb4d884cdafb`; il manifest `SHA256SUMS-EFI.txt` registra
28 file EFI: solo `EFI/OC/config.plist` è cambiato, gli altri 27 combaciano byte per byte con Boot14. `ocvalidate`
OpenCore 1.0.8 passa senza errori (`ocvalidate.txt`). Il deploy ha verificato in sola lettura l'intero manifest
Boot14 (28/28), UUID `A140-3052`, volume vfat e trasporto USB; ha salvato fuori EFI la config Boot14 con SHA256
`55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`, quindi ha sostituito atomicamente con fsync
il solo config. Un processo verifier separato ha confermato manifest Boot15 28/28, config SHA,
`USBMapB840.kext/Contents/Info.plist` invariato a `9249e728191fc64b8685407fe4f7446049be988dd9fec30e427262a37ece5edb`
e `ocvalidate` 1.0.8 sul target. La chiavetta è stata smontata dopo il controllo. Backup, manifest e record pre/post
sono in `research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch/deploy-evidence/boot15-20261025T202535Z/`;
la preparazione resta registrata in `PREPARATION.json` nella cartella Boot15.

È un controllo dell'intera mappa/binding contro l'enumerazione nativa, non una correzione. Il mapping dichiara
14/4/4/1 porte, tutte sotto il limite 15; l'assenza della mappa fa ricadere la tipologia delle porte sul default
macOS secondo la guida Dortania, ma non garantisce l'enumerazione HID. La stessa guida raccomanda l'osservazione
dell'IORegistry macOS per verificare una mappa. Un eventuale successo rende la mappa/binding il ramo probabile,
ancora da confermare; un nuovo esito negativo lascia aperti controller/driver, hand-off firmware, ACPI/topologia e
stack input. Boot15 è deployata ma il test hardware è pendente. Le fonti tecniche essenziali sono USBToolBox `base.py` (selettore
PCI BDF e personalità native), Apple IOKit matching, Dortania USB manual mapping e OpenCore 1.0.8 Configuration.

