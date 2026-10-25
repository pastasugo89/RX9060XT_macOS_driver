# Bare metal: primo avvio di macOS Tahoe 25G83 sul PC (23–25/10/2026)

Obiettivo di questa fase: avviare macOS **senza VM** sul PC dell'utente (Ryzen 7 7700, MSI B840 GAMING PLUS WIFI,
RX 9060 XT), per togliere di mezzo le differenze introdotte da QEMU nel lavoro sul display (vedi `p1_p2_display.md`).
Primo traguardo: arrivare alla GUI del ripristino (BaseSystem) da chiavetta, **senza installare nulla**.

Stato al 25/10/2026: **il kernel di macOS parte sul ferro, ma si blocca in modo totale (tastiera morta) subito dopo
`CoreAnalyticsHub start completed`. La GUI del ripristino non è mai stata raggiunta.**

## 1. Supporti preparati

| Supporto | Contenuto | Note |
|---|---|---|
| Chiavetta 16 GB SanDisk Cruzer Fit, etichetta `OCBOOT` (GPT, una partizione EFI FAT32) | `EFI/` attiva (oggi la variante `EFI-next3`), `com.apple.recovery.boot/BaseSystem.dmg` + `.chunklist` di 25G83 (sha verificati), cartelle `EFI-release`, `EFI-debug1`, `EFI-next1`, `EFI-next2` (varianti precedenti) e `_logs-boot*` (log OpenCore) | Era la chiavetta d'installazione di CachyOS: cancellata su richiesta dell'utente |
| Chiavetta 128 GB SanDisk (exFAT, **dati personali dell'utente: non leggere né elencare**) | Solo la cartella `macOS-Tahoe-25G83-installer/Tahoe25G83.iso` (installer completo, 18,4 GB, sha verificato) aggiunta nello spazio libero | Da usare dal ripristino con `hdiutil attach`; da cancellare dopo l'installazione |

Nessuna partizione per macOS è stata ancora creata: il volume `/mnt/vm` (200 GiB Btrfs, `nvme1n1p7`) è intatto.

## 2. EFI OpenCore

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

## 5. Ipotesi aperte, in ordine di probabilità

1. **Resizable BAR attivo nel BIOS.** La BASE-EFI AMD più diffusa e altre EFI AM5 funzionanti richiedono Resizable BAR
   **disattivato** (con Above 4G attivo); più fonti collegano i blocchi in questa fase all'enumerazione PCI con ReBAR.
   Con ReBAR la BAR0 della 9060 XT è 16 GiB. Prova a costo zero: solo BIOS.
2. **Porta seriale/COM attivata nel BIOS** (la checklist precedente chiedeva COM1 attiva per i log): le EFI AM5 di
   riferimento la tengono **disattivata**. Prova a costo zero: solo BIOS.
3. **Altri blocchi AGESA `CPVS`** non coperti dalle due patch (es. `If (G002 != 1)` per `GPP0/GPP2`, `If (G002 != 2)` per
   `GPP8`, `If (G001 == 1)`, `If (G027 == One)`), o la necessità di conoscere i valori reali di `G000..G004`
   (leggibili da Linux come root dalla memoria `0x8C01B000`, sola lettura).
4. **Uno dei nostri kext** (LucyRTL8125, USBMapB840, VirtualSMC): prova con la variante `02-no-kext`
   (`research/ext/ocboot-baremetal-debug/VARIANTI/`).
5. **Topologia GPU sul bare metal**: `AMDSupport` di Apple si aggancia alla 9060 XT (osservato nei dump della VM);
   `-amd_no_dgpu_accel` non lo impedisce. Possibile rimedio: nascondere la GPU ai driver Apple (DeviceProperties o
   SSDT) mantenendo il framebuffer del GOP.

Per diagnosticare senza tentativi alla cieca serve un **log del kernel** oltre la schermata: COM1 con cavo
null-modem verso un secondo dispositivo, oppure i boot-arg `-v` + `debug=0x100` + `msgbuf` e un'attivazione NMI
(`debug=0x144`) per ottenere un backtrace quando il sistema è bloccato.

## 6. Stato del BIOS e del PC (da ricordare)

- **Grafica integrata Raphael: DISATTIVATA** per la prova 5. Va **riattivata** per tornare alla configurazione VFIO
  (lo schermo di Linux usa l'HDMI della scheda madre in quella modalità). Con l'integrata spenta Linux usa la 9060 XT.
- Secure Boot off, CSM off, Above 4G on, Re-Size BAR on (da verificare/provare off, ipotesi 1).
- Avvio dalla chiavetta solo con F11 (menu di avvio MSI): l'ordine di avvio non è stato toccato.
- Nessuna scrittura su dischi interni, NVRAM del firmware (`WriteFlash = NO`) o partizioni.

## 7. Prossimi passi proposti

1. Avvio 7: **stessa chiavetta**, BIOS con **Resizable BAR = Disabled** (Above 4G resta Enabled) e **porta seriale
   disattivata**. Se supera il blocco, rimettere un'impostazione alla volta per sapere quale contava.
2. Se il blocco resta: variante senza kext aggiuntivi (`VARIANTI/02-no-kext`), poi lettura dei valori reali di
   `CPVS` da Linux e patch ACPI mirate.
3. Valutare la cattura del log del kernel (cavo seriale o NMI) prima di ulteriori tentativi.
