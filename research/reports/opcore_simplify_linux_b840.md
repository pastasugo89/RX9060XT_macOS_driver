# OpCore Simplify su Linux: EFI B840 senza accelerazione (25/10/2026)

Stato: **boot9 bloccato; boot10–11 con variante diagnostica si riavviano. Il video del boot11 supera l'elenco ACPI**.
Il boot8 con whitelist F7000000 e il boot9 con la nuova base non raggiungono la GUI del ripristino. Non è stata
installata alcuna partizione macOS. Il driver GPU del progetto non è presente nella nuova EFI.

## Risultato più importante: patch AMD non aggiornata per il kernel effettivo

Il log del boot8 riporta `Read kernel version 25.6.0`. La vecchia EFI usava la patch
`Visual | thread_invoke, thread_dispatch | Remove non-monotonic time panic | 12.0+`, con pattern `...80040000...`.
Il ramo AMD_Vanilla utilizzato da Simplify contiene una correzione specifica per Darwin **25.4.0+**:
il campo cercato diventa `...90040000...`, e la patch precedente termina a `25.3.99`.

Fonte diretta: [commit del 29/03/2026](https://github.com/laobamac/AMD_Vanilla/commit/28788772e05a434dd06c149833a20d76151117f5).
Snapshot usato: commit `a174cca80efe2377fde3b902666c70863ea66454`, blob `53b4b7e4bfa0951d1b2b1001c5d94e4d6f28eeed`.
Il download è verificato sia con identità Git blob sia con SHA256 del testo locale.

### Verifica sul kernel della chiavetta, non soltanto sul nome della patch

Estratto in sola lettura il membro effettivamente avviato:
`Volume2/3C964619-6590-4DD2-B356-291DE195971B/boot/System/Library/KernelCollections/BootKernelExtensions.kc`
dal `BaseSystem.dmg` di OCBOOT. SHA256 della BootKC:
`c80161fa3065883753fc285339281361a8469cbb6fb27653c88e2a22eb4807a4`.
Identità Mach-O x86_64 verificata anche con REA; nessuna esecuzione del kernel sul sistema Linux.

`tools/baremetal/audit-kernel-patches.py` riproduce **in memoria**, nell'ordine del config, le patch kernel abilitate,
con Find/Mask, Replace/ReplaceMask, Base, Limit, Count e Skip. Il file Apple originale rimane invariato.
Il comportamento è confrontato con OpenCore 1.0.8 `KextPatcher.c:310` e `OcMiscLib/DataPatcher.c:106`.

| Variante della patch temporale | Primi due match nel replay sequenziale | Simbolo definito precedente |
|---|---|---|
| Vecchia, applicata nel boot8 | file `0x291d00`, VA `0xffffff8000491d00` | `_kperf_lazy_wait_sample + 0x20` |
| Vecchia, secondo match | file `0x2e78ca`, VA `0xffffff80004e78ca` | `_vmx_hv_support + 0x2a` |
| Nuova, per Darwin 25.4+ | file `0x18ed52`, VA `0xffffff800038ed52` | `_thread_block_reason + 0x18a2` |
| Nuova, secondo match | file `0x18fcda`, VA `0xffffff800038fcda` | `_thread_dispatch + 0x71a` |

Entrambe le configurazioni raggiungono tutti i conteggi richiesti nel replay. Il vecchio log segnava infatti
`replace count - 2` e `Success`: **il conteggio non garantisce la correttezza delle destinazioni**.
È una lacuna concreta nei controlli precedenti, corretta nella nuova EFI.

Limite: questo è un replay statico della BootKC estratta; non include le trasformazioni degli altri quirk di
OpenCore né osserva gli indirizzi realmente modificati nel boot8. I nomi indicano il simbolo definito precedente,
non una ricostruzione completa dei confini delle funzioni. Il confronto rende la vecchia patch un problema serio
da correggere, ma non dimostra da solo la causa completa del blocco sul PC.

Evidenza ripulita e ripetibile: `research/hw_dump/baremetal_simplify_audit/sequential-patch-audit.json`.

## Altre differenze concrete rispetto alla vecchia EFI

- **Enumerazione PCI AM5:** `CaseySJ | IOPCIIsHotplugPort` era presente ma disabilitata nella EFI precedente.
  Simplify la abilita per Raphael; la nuova configurazione la abilita.
- **CPU ACPI:** il firmware espone 16 dispositivi `ACPI0007`, UID 0..15, sotto `_SB.PLTF`, senza oggetti legacy
  `Processor()`. Simplify genera `SSDT-PLUG-ALT.aml` con esattamente 16 oggetti e gli stessi UID.
  È un adattamento delle definizioni CPU, non la prova di power management XCPM funzionante su AMD.
  `DummyPowerManagement` resta attivo. Non è stata importata la CPUR generica a 64 CPU per altre schede.
- **Seriale:** prima della preparazione Linux esponeva `PNP0501:00/status = 15`.
  Prima del boot9 l'utente ha disattivato COM; ora Linux conferma **stato 0**. Il blocco persiste.
- La sola riduzione delle BAR (boot7) e la whitelist F7000000 (boot8) non hanno migliorato il risultato.
  ReBAR resta abilitato nel BIOS, con `ResizeAppleGpuBars=0` e `ResizeGpuBars=-1`.

Queste modifiche formano una nuova base generata e revisionata. Il boot9 conferma che non bastano a raggiungere
la GUI; non isolano il contributo di ciascuna modifica.

## Adattamento di OpCore Simplify

Upstream: [lzhoang2801/OpCore-Simplify](https://github.com/lzhoang2801/OpCore-Simplify), commit
`f0e1e441bb455c33e9695a9c9c50e8ca931d4de8`, licenza BSD-3-Clause.
La copia modificabile è in `research/ext/OpCore-Simplify/`; modifiche riproducibili e licenza sono conservate in
`tools/baremetal/opcore-simplify-linux.patch` e `tools/baremetal/OpCore-Simplify.LICENSE`.

L'esecuzione Python su Linux era **già supportata** upstream. Sono stati aggiunti:

1. Raccolta hardware Linux in sola lettura dal menu `E`, con report validato dallo schema upstream. Ambito del
   collector: desktop AMD Raphael, identificazione chipset dal nome della scheda, GPU AMD Navi identificabile.
   Qui rileva 7700, B840, `1002-7590`, ReBAR effettivo, PCI Path e ACPI Path, NIC e controller reali.
   Non legge contenuti dei dischi, seriali DMI, MAC, EDID o credenziali Wi-Fi. Audio codec e Bluetooth non sono
   raccolti da questo collector iniziale; non è un sostituto generale di Hardware Sniffer.
2. `--allow-unaccelerated`: quando tutte le GPU sono incompatibili, permette un solo dGPU AMD identificato.
   La GPU rimane dichiarata **incompatibile**, conserva ID e percorsi reali, non viene spenta o inserita tra i
   dispositivi da disabilitare. Non si selezionano kext grafici né patch OCLP per essa. Viene aggiunto
   `-amd_no_dgpu_accel` per Darwin 23 e successivi.
3. `--no-update`: mantiene la revisione modificata. La modalità sperimentale evita anch'essa l'auto-update.
4. Correzione dei nomi di output nel caricamento ACPI per dump Linux senza estensione (`DSDT`, `SSDT2`):
   upstream cercava erroneamente `.dsl` anziché `DSDT.dsl`/`SSDT2.dsl`. Dopo la correzione carica 17 tabelle.

Senza il flag sperimentale la RX 9060 XT continua a essere rifiutata. Il bypass GPU non disabilita i controlli CPU.
Generare la EFI non certifica né accelerazione né raggiungibilità del desktop senza accelerazione.

## EFI pronta sulla chiavetta

Output locale: `research/ext/opcore-simplify-b840-installer-v2/`.
La EFI è costruita passando attraverso `OCPE.build_opencore_efi`, non copiando solo alcune impostazioni da un plist
esterno. Il profilo B840 applica poi adattamenti espliciti, registrati in `PREPARATION.json`:

- OpenCore **1.0.8 DEBUG** e Sample.plist della stessa release, archivio con SHA256 già verificato.
  Il downloader upstream proponeva una build Dortania 1.0.9: il profilo mantiene 1.0.8 per coerenza con il validatore.
- ACPI: EC, USBX, PLUG-ALT per i 16 thread e disabilitazione della Wi-Fi Qualcomm non supportata.
  Mantenute le due patch DSDT B840 già verificate. USB Reset generico rimosso, mantenendo la mappa B840 esistente.
- Kext: Lilu 1.7.3, VirtualSMC 1.3.9, AppleMCEReporterDisabler 1.2, RTL812xLucy 1.1.100,
  NVMeFix 1.1.4, RestrictEvents 1.1.7 e USBMapB840. Lilu precede i propri dipendenti.
  Non aggiunti sensori, driver del progetto o kext grafici. Rimossi USBToolBox/UTBDefault e CtlnaAHCIPort generici.
  NVMeFix non costituisce una certificazione di compatibilità di ogni SSD presente.
- Patch AMD specifiche per Darwin 25.6, conteggio core fisici `08`, IOPCIIsHotplugPort abilitata,
  patch temporale aggiornata e variante PAT scelta da Simplify per GPU AMD.
- `DevirtualiseMmio=True`, whitelist vuota dopo il boot8 negativo, ReBAR ridotto soltanto all'avvio macOS.
- Identità SMBIOS precedente conservata fuori da git, log DEBUG mantenuti, `WriteFlash=False`, SIP non disabilitata
  da questo profilo. Presente il driver APFS allineato fornito da OcBinaryData e selezionato da Simplify per Tahoe.

Config SHA256: `1f8d43cf677eb2cce93fc792ebe13fd897760b4897126ae2d3988bf26b4cbc08`.
**28 file EFI verificati** localmente, nello staging e dopo l'attivazione su OCBOOT (`A140-3052`).
Backup completo precedente sulla chiavetta: `_EFI-pre-simplify-20261025T112158Z/EFI/`.
`BaseSystem.dmg` verificato invariato prima/dopo; nessuna scrittura a partizioni interne.

## Verifiche completate

- Report del sistema reale: schema valido, zero errori e warning.
- Otto test di integrazione: rifiuto GPU predefinito; bypass sperimentale con identità invariata; controlli CPU
  ancora attivi; GPU multiple ambigue rifiutate; versione macOS troppo vecchia rifiutata; GPU compatibile invariata;
  boot-arg generato senza kext grafico; esportazione Linux dal menu reale.
- Generazione e compilazione delle SSDT; checksum AML validi; ricontrollo degli UID 0..15.
- Verifica di ogni plist, eseguibile kext e driver referenziato dal config; dipendenze e assenza di disable-gpu
  sulla scheda che deve mostrare l'installer.
- `ocvalidate` **1.0.8** senza problemi; manifest SHA256 completo; backup e deployment verificati.
- Replay sequenziale delle patch kernel sulla BootKC del ripristino: conteggi previsti raggiunti.
  Non equivale a un test dell'avvio sul ferro.

Comandi, dalla radice del progetto:

```sh
python tools/baremetal/prepare-opcore-simplify.py
python tools/baremetal/gather-simplify-b840.py
python tools/baremetal/linux_hardware.py research/ext/OpCore-Simplify/Report-Linux.json
python tools/baremetal/test-simplify-linux.py
python tools/baremetal/build-simplify-b840.py --output research/ext/simplify-b840-nuova-prova
```

Il collector e il builder rifiutano output già esistenti. La preparazione usa il compilatore iasl e macserial già
presenti nel progetto; `--iasl` e `--macserial` permettono di specificare percorsi espliciti.
Il downloader conserva cronologia e digest in `OCK_Files/history.json`: il comando di raccolta può aggiornare
i pacchetti, mentre il build registra e controlla i file effettivamente utilizzati. Gli snapshot di questa prova
restano locali. Non sostituire queste EFI con una futura rigenerazione senza revisionarne il diff.

Per l'interfaccia interattiva:

```sh
python research/ext/OpCore-Simplify/OpCore-Simplify.py --no-update --allow-unaccelerated
```

## Documentazione letta e decisioni ricavate

Letti il README upstream di Simplify e il flusso completo di selezione/build; esaminati checker, customizer,
generatore config, selezione kext, caricamento ACPI e generazione delle tabelle pertinenti.
Scaricati localmente i repository delle guide Dortania per consultazione. Capitoli letti integralmente per questa
verifica: Zen, limiti hardware, installer Linux, kernel issues, boot process, debug, Tahoe; guida ACPI per CPU,
EC/USBX, clock, RHUB, estrazione/compilazione e troubleshooting. Consultate le sezioni pertinenti del riferimento
OpenCore **1.0.8** e i sorgenti di MMIO e patcher. Questo elenco identifica la copertura effettiva, non certifica
una lettura integrale di ogni capitolo per tutte le piattaforme Intel e laptop.

| Fonte primaria | Conseguenza pratica |
|---|---|
| [Dortania Zen](https://dortania.github.io/OpenCore-Install-Guide/AMD/zen.html) | ReBAR BIOS attivo richiede ResizeAppleGpuBars=0; seriale/COM disabilitata; VirtualSMC e patch AMD necessarie |
| [Dortania kernel issues](https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/extended/kernel-issues.html) | Verificare patch aggiornate, mappa memoria e dispositivi; ultima riga verbose non identifica necessariamente la causa |
| [Dortania disabilitazione GPU](https://dortania.github.io/OpenCore-Install-Guide/extras/spoof.html) | Non usare wegnoegpu per spegnere l'unica scheda destinata al display dell'installer |
| [Dortania PLUG](https://dortania.github.io/Getting-Started-With-ACPI/Universal/plug.html) | Il PLUG classico riguarda XCPM Intel; distinguere l'adattamento degli oggetti CPU dal power management AMD |
| [OpenCore Configuration](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Docs/Configuration.tex) | Quirk specifici del firmware, validator della versione corretta, BAR ridotte solo per macOS |
| [AMD_Vanilla Darwin 25.4+](https://github.com/laobamac/AMD_Vanilla/commit/28788772e05a434dd06c149833a20d76151117f5) | Usare il pattern aggiornato per la patch temporale su 25.6 |

## Esito boot9 e prossimo avvio diagnostico

Boot9: la foto IMG_0667 mostra i kext avviati e l'elenco ACPI fino a WSMT; nessun panic visibile, Caps Lock fermo.
Il log conferma patch `26.4+`, hotplug AM5 e quattro SSDT; 28 file corrispondono al manifest v2. Non dimostrato
un avanzamento rispetto alla precedente schermata. Evidenze in `research/hw_dump/baremetal_boot9/` e dettagli
in [baremetal_bringup.md §11](baremetal_bringup.md#11-boot9-foto-img_0667-seriale-off-output-acpi-25102026).

1. Mantenere **Serial/COM off**, **Above 4G e ReBAR on**, iGPU off.
2. Prossima variante `research/ext/opcore-simplify-b840-acpi-debug/`: stessi payload, sola aggiunta ai boot-args di
   `acpi_layer=0xffffffff acpi_level=0x2087 msgbuf=1048576`. `ocvalidate` e 28 checksum verificati; nessuna nuova
   patch correttiva. Non garantisce log ulteriori se la build Apple non include i corrispondenti messaggi.
3. Registrare il verbose dall'inizio al blocco; mantenere visibile l'intera area di testo. OpenCore non salva i
   messaggi XNU successivi all'handoff. Nessun Reset NVRAM richiesto.

L'installazione resta successiva alla GUI e alle verifiche della destinazione: `/mnt/vm` è ancora Btrfs,
UUID `be2a9624-d2c1-4778-ac99-fcf9258d3328`, non APFS. I nomi nvme0/nvme1 cambiano tra riavvii.

Variante diagnostica **attivata su OCBOOT** il 25/10/2026, UTC 20261025T115242Z.
Config SHA256 `8710fe3bb6f4b4e3b18399ad4749d5262c63987ddcf32b18bf02472e794f7551`; 28 file verificati. Backup config: `_config-pre-acpi-debug-20261025T115242Z/config.plist` sulla chiavetta.
`BaseSystem.dmg` invariato (SHA256 `bbfcbf7bfd09c79465fa92c741ebb665625794c31578b81248f7fa0c2bcd4789`).
Al momento del deployment la prova era pendente; esito successivo: **boot10 riavviato spontaneamente**, senza
video o panic report acquisito. Log e 28 payload confermano la variante; nessuna ulteriore modifica EFI.
Prossima prova: una sola replica della stessa OCBOOT con video dall'inizio del verbose. Il ritorno a GRUB dopo il
reset segue l'ordine di avvio del firmware e non certifica avanzamento dell'installer. Nessuna modifica a partizioni interne o BIOS.

## Aggiornamento dopo il video del boot11

La replica è stata eseguita: `IMG_0668.MOV` mostra caricamento delle tabelle AML e AppleACPICPU, poi avvio dei driver
di periferica, errore `HPET: map device registers failed`, messaggio AppleVTD e schermo nero. POST/GRUB successivi
confermati dall'utente. Nessun panic/backtrace leggibile o recuperato; causa non isolata.

Prossima variante **`research/ext/opcore-simplify-b840-cpus1/`**, con sola aggiunta `cpus=1`: test temporaneo con
una CPU logica, mantenendo core count fisico AMD 08, tutte le SSDT, kext, riduzione BAR e diagnostica. Config SHA256
`3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976`. Plist validato, 28 file verificati,
27 payload diversi dal config identici alla variante filmata. Dettagli, criteri e limiti nel report baremetal §14.

Variante `cpus=1` **attivata su OCBOOT**, UTC 20261025T123357Z.
Backup: `_config-pre-cpus1-20261025T123357Z/config.plist`. Config `3e65bd9af20a11398188c1965e008b681f9ffabcd4fe0b73393635ba55711976`.
Confronto semantico indipendente conferma unica aggiunta cpus=1; 28 payload verificati anche dopo il deployment.
Ripristino invariato (SHA256 `bbfcbf7bfd09c79465fa92c741ebb665625794c31578b81248f7fa0c2bcd4789`). Prova hardware ancora da eseguire.
