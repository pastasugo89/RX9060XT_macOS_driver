# BOOT16 USB HID: Tahoe schema diagnosis and BOOT17 correction (26/10/2026)

## Esito

La nuova pista è concreta e verificata nel codice: BOOT16 genera una mappa nativa con 23 porte, ma nessuna contiene `usb-port-number` o `usb-port-type`; contiene soltanto le proprietà legacy `port` e `UsbConnector`. Il runtime USBToolBox 1.2.0 copia espressamente queste due proprietà legacy nei nuovi nomi quando applica la mappa su macOS con major version almeno 25 (Tahoe). BOOT16 non carica quel runtime: usa `AppleUSBHostMergeProperties`, perciò il suo percorso nativo non esegue `fixMapForTahoe()`. Questa è una lacuna reale della candidata che le prove precedenti non avevano rilevato; è una spiegazione plausibile dell'input assente, non una causa dimostrata finché una mappa corretta non viene provata.

BOOT16 è stata avviata; l'utente riferisce la stessa schermata animata di pairing Magic Keyboard/Mouse e nessun input. Questo documenta un esito negativo del test di input, ma non prova che macOS abbia selezionato o applicato le personality USB. BOOT15 (mappa disabilitata) resta non provata. Recovery e le sue utility non sono state confermate.

## Evidenza locale

- Il `Info.plist` BOOT16 ha quattro personality, con 14/4/4/1 porte (23 in totale); parsing: **0/23** porte con `usb-port-number` e **0/23** con `usb-port-type`.
- Ogni voce mantiene `port` come Data a 4 byte derivato dall'ACPI `_ADR` raw e `UsbConnector` come intero. PCI parent matching, controller, raw port, numero di porte e classificazioni della mappa non sono stati modificati nella nuova candidata.
- La config BOOT16 abilita soltanto la mappa codeless nativa `USBMapB840.kext`; non include USBToolBox.kext/UTBMap runtime. La mappa nativa non può ottenere gli alias dal helper C++ del kext USBToolBox.
- Il risultato BOOT16 non discrimina schema, matching IOKit, controller, hand-off BIOS o stack HID Recovery: non sono disponibili IORegistry/log macOS del boot che confermino il bind o l'applicazione della mappa.

## Fonti primarie e interpretazione

Il [codice USBToolBox kext 1.2.0, `fixMapForTahoe()` e `mergeProperties()`](https://github.com/USBToolBox/kext/blob/1.2.0/USBToolBox/USBToolBox.cpp) duplica `port` in `usb-port-number` e `UsbConnector` in `usb-port-type`, richiamando la conversione per la proprietà `ports` quando `version_major >= 25`. La [release 1.2.0](https://github.com/USBToolBox/kext/releases/tag/1.2.0) descrive Tahoe support come WIP; nell'[issue Tahoe del repository](https://github.com/USBToolBox/kext/issues/15) il maintainer chiede se sia stato usato 1.2.0 e in seguito chiarisce che la trasformazione manuale non serve con quella versione. Questo concorda sul fatto che il runtime 1.2.0 compensa mappe legacy.

Il builder USBToolBox usato per BOOT16 è il commit pinned [`0c6823a2c643a4488888938451194723dc9ae29a`, `base.py`](https://github.com/USBToolBox/tool/blob/0c6823a2c643a4488888938451194723dc9ae29a/base.py), che produce `port` e `UsbConnector` legacy; il generatore crea una personality nativa. Un cambiamento corroborante è visibile nel [diff della PR #66 di Corpnewt/USBMap](https://github.com/corpnewt/USBMap/pull/66/files): il diff aggiunge `usb-port-number`/`usb-port-type` e anche i nomi `kUSBHostPortPropertyPortNumber`/`kUSBHostPortPropertyPortType` mantenendo le chiavi precedenti. È una proposta di codice in un PR e non la usiamo come prova del contratto Apple né assumiamo che il PR sia parte della versione installata. Le fonti dimostrano il comportamento del codice USBToolBox, non la semantica interna completa del driver Apple in questa build di Tahoe. Perciò la conclusione operativa è “BOOT16 manca gli alias che il runtime USBToolBox 1.2.0 aggiunge a Tahoe”, non “l'omissione è certamente la causa dell'HID inattivo”.

Il match BOOT16 usa i PCI ID AMD univoci osservati sul PC: `1022:43ef`, `1022:15b6`, `1022:15b7`, `1022:15b8`; il BDF resta nei metadati Linux. Le porte e il parent selector provengono dal generatore ufficiale, ma l'esito negativo non prova se IOKit abbia fatto match. Non è emersa in queste fonti una regressione specifica per questi quattro ID. Il `ReleaseUsbOwnership=True` in OpenCore non documenta il valore dell'impostazione firmware “XHCI hand-off”; quel punto resta ignoto e non è stato cambiato.

Il [README del fork GenericUSBXHCI citato](https://github.com/al3xtjames/GenericUSBXHCI/blob/master/README.md) dichiara che quel fork rifiuta il caricamento su 10.11 e successivi; questo esclude quel ramo legacy come test utile su Tahoe, ma non classifica fork indipendenti non esaminati. Le istruzioni [Dortania sulla mappatura manuale](https://github.com/dortania/OpenCore-Post-Install/blob/master/usb/manual/manual.md) confermano inoltre che associazione controller/jack e tipo USB-C richiedono evidenza IORegistry e prova fisica; l'attuale mappa conserva tutte le porte e lascia l'A/C non osservato come assunzione, quindi non è una spiegazione aggiuntiva dimostrata.

## BOOT17 attiva

`research/ext/usbtoolbox-linux-tahoe-boot17-candidate/EFI/` è la EFI BOOT17, derivata dalla candidata BOOT16. Per ciascuna delle stesse 23 porte aggiunge esattamente due chiavi: `usb-port-number` con lo stesso Data di `port`, e `usb-port-type` con lo stesso intero di `UsbConnector`. Tutti i campi originali restano presenti. Non cambia config, selettori PCI, bundle path, numero/classificazione delle porte, altri kext o file EFI.

SHA-256 della nuova `USBMapB840.kext/Contents/Info.plist`: `71f93330cf748e5a58bfa856c47abd35d80798c8272d7f0bf702c7312f04dd7d`. Il config resta `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`. Rispetto a BOOT16 cambia un solo file EFI (27/28 identici); `SHA256SUMS-EFI.txt` verifica 28/28. `ocvalidate` OpenCore 1.0.8 passa senza issue. L’adattatore Linux `tools/baremetal/usbtoolbox_linux_port.py` ora aggiunge e valida gli stessi alias durante la generazione nativa, rispecchiando il helper upstream USBToolBox 1.2.0. La rigenerazione effettiva in `research/ext/usbtoolbox-linux-tahoe-regeneration-final-20261026/` ha prodotto lo stesso Info SHA byte per byte. I metadati indicano `properties_added=46` (due per ciascuna di 23 porte). La generazione finale e `prepare-config` riproducono la stessa Info e passano `ocvalidate`; contro BOOT15 la EFI locale ha 26 file invariati e cambia solo Info USB più config (riattivazione della mappa).

BOOT17 è stata applicata su OCBOOT UUID `A140-3052` dopo preflight del manifest BOOT16 28/28 e backup Info BOOT16 fuori EFI. Il solo path modificato è `EFI/OC/Kexts/USBMapB840.kext/Contents/Info.plist`; postmanifest BOOT17 28/28 e `ocvalidate` OpenCore 1.0.8 PASS. Backup SHA `e1ddb59febdddcb63ecf309b37f454159ff23396ae1f511099c4fc94a1065312`, record in `research/ext/usbtoolbox-linux-tahoe-boot17-candidate/deploy-evidence/20261026T131317524219Z/`. La chiavetta è smontata. **BOOT17 è attiva, ma il test hardware è pendente**.

## Riproduzione locale

Dalla root del progetto, con la copia pinned USBToolBox già presente in `research/ext/usbtoolbox-tool`, generare in una nuova cartella per non sovrascrivere artefatti esistenti:

```sh
python3 tools/baremetal/usbtoolbox_linux_port.py generate \
  --upstream research/ext/usbtoolbox-tool \
  --output research/ext/usbtoolbox-linux-tahoe-regeneration-new \
  --model MacPro7,1
python3 tools/baremetal/usbtoolbox_linux_port.py prepare-config \
  --candidate research/ext/usbtoolbox-linux-tahoe-regeneration-new \
  --baseline-efi research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch-usb-native/EFI \
  --ocvalidate research/ext/ocboot-baremetal/_dl/opencore/src/Utilities/ocvalidate/ocvalidate.linux
```

## Prossimo test singolo

Usare BOOT17 attiva per un solo avvio con gli stessi dispositivi e senza spostare cavi: l'unica variabile rispetto a BOOT16 è la presenza dei due alias Tahoe. Annotare se l'input HID viene riconosciuto. Se l'input resta assente, il passo utile successivo è acquisire IORegistry/log USB da macOS per distinguere applicazione della mappa da mancato matching/controller/HID; non ripetere tentativi cambiando contemporaneamente runtime USBToolBox, porte, BIOS o driver. La correzione EFI è stata applicata alla sola Info; nessuna modifica BIOS è stata fatta. L’esito hardware di BOOT17 resta da raccogliere.
