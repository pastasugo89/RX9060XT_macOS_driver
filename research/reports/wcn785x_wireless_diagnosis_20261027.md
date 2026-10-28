# WCN785x su macOS Tahoe: indagine iniziale — 2026-10-27

> Aggiornamento28ottobre: la conclusione iniziale sulla disponibilità è superata. Individuati e compilati driver specifici; vedere tools/baremetal/qualcomm-wcn785x/README.md e unified_repair_20261028.md. Sul PC non sono ancora installati né provati.

## Hardware e osservazioni

- L'inventario Linux `research/hw_dump/baremetal_inventory/lspci_nnk.txt` identifica il Wi-Fi Qualcomm WCN785x `17cb:1107`, sottosistema `105b:e0f7`.
- L'inventario USB Linux registra il Bluetooth `0489:e10a`; il driver Linux btusb classifica esplicitamente questo ID come QCA WCN785x: <https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btusb.c>.
- Sul sistema macOS avviato il nodo PCI `LN00` conserva nella proprietà `compatible` gli ID del Wi-Fi, ma mostra `vendor-id` e `device-id` ffff, `class-code` ffffffff e `IOName` #display. Il generatore di OpenCore Simplify crea un SSDT che applica proprio queste proprietà a un dispositivo di rete sotto Darwin (`research/ext/OpCore-Simplify/Scripts/acpi_guru.py`, circa riga 1943). La corrispondenza indica fortemente un mascheramento ACPI. Va verificato l'AML caricato prima di attribuire l'effetto alla singola candidata EFI. Il nome contenente GPP7 non significa necessariamente che tutti i dispositivi sul bridge siano nascosti.
- Bluetooth `0489:e10a` non è stato individuato nel piano USB corrente. La mappa Linux precedente lo collocava su XH00 raw 10, HS06 interna; la sola presenza della voce nella mappa non dimostra che la porta sia realmente pubblicata o il dispositivo enumerato in macOS.
- I quattro controller AppleUSBXHCIPCI correnti riportano la stessa proprietà `ports`, che combina voci e commenti di più controller; per esempio HS01 descrive l'hub interno XHC2, HS06 il Bluetooth XH00. Nel plist della candidata le personalità hanno invece elenchi diversi. Questo è un indizio di merge/matching non selettivo da verificare; non basta per attribuire con certezza il mancato rilevamento Bluetooth.
- Il profiler Bluetooth mostra un controller BCM_4350C2 UART con indirizzo nullo: non è prova della presenza di un controller Broadcom fisico. Il profiler AirPort non mostra un'interfaccia Wi-Fi utilizzabile.

## Supporto e percorso tecnico

Non è stato individuato un driver macOS funzionante per questo preciso Qualcomm in questa ricerca iniziale. [itlwm](https://github.com/OpenIntelWireless/itlwm) riguarda Wi-Fi Intel, [IntelBluetoothFirmware](https://github.com/OpenIntelWireless/IntelBluetoothFirmware) riguarda Bluetooth Intel; [BrcmPatchRAM](https://github.com/acidanthera/BrcmPatchRAM) è destinato a Broadcom. Non sono prove di compatibilità Qualcomm. Il codice [btqca Linux](https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btqca.c) è riferimento per inizializzazione e firmware, con vincoli di licenza GPL da rispettare.

Priorità: verificare l'effettiva enumerazione della porta e correggere in una copia di prova la mappa USB, mantenendo una EFI di ripristino; solo dopo investigare l'inizializzazione firmware e l'integrazione con lo stack Bluetooth di Tahoe. Per il Wi-Fi occorrono sia visibilità PCI sia un driver compatibile: togliere il mascheramento da solo non implementa il driver. Nessuna modifica EFI, caricamento di kext o scrittura verso i dispositivi è stata effettuata durante questa diagnosi.

## REA

Lo skill REA è disponibile nel progetto, ma il runtime REA e gli strumenti nativi necessari non sono operativi su questo macOS. La copia Node trovata è per Linux. Non è stata eseguita alcuna analisi REA e non va confusa con la presente ispezione di configurazione e sorgenti.

## Candidata diagnostica locale

L'AML della candidata esistente contiene il path completo `\_SB.PCI0.GPP7.UP02.DP90.LN00`; è il Wi-Fi, non `DP80.WN00` Ethernet. Preparata una **sola config diagnostica non distribuita** `research/ext/wcn785x-test-20261027/config-wifi-visible.plist`, a partire dalla candidata all-threads: l'unica differenza semantica è `Enabled=false` per `SSDT-Disable_Network_GPP7.aml`. SHA-256 `26bf06c9ebac7d6157bb2b5a32dbb4e8a2de1c10336f784cbabf107fd7f0cda0`; `plutil -lint` e `ocvalidate` 1.0.8 superati. Non è una EFI completa, non è stata confrontata con la config in uso sulla chiavetta e non va copiata alla cieca. Non è un driver né una soluzione funzionante: l'eventuale avvio della variante va deciso solo dopo confronto con l'EFI realmente attiva, predisposizione di recupero e pianificazione del test.

## Candidata USB locale

Le quattro istanze attive di `AppleUSBXHCIPCI` riportano `port-count=1`, valore che coincide con la personalità XHC2 e non con i valori 14, 4, 4, 1 configurati rispettivamente per XH00, XHC0, XHC1 e XHC2. In particolare il Bluetooth Linux si trova su XH00 raw 10: il port-count osservato è coerente con la sua assenza, ma il risultato di un avvio di prova è necessario per confermarlo.

È stata preparata senza distribuirla `research/ext/wcn785x-test-20261027/USBMapB840-pcidebug.kext/Contents/Info.plist`, che preserva i dati delle porte della mappa candidata precedente e sostituisce solo il matcher delle quattro personalità con `IOParentMatch/IOPropertyMatch/pcidebug`, usando gli identificativi correnti 5:0:0, 10:0:3, 10:0:4 e 11:0:0. Tale struttura è usata dal generatore [USBMap upstream](https://github.com/corpnewt/USBMap/blob/master/USBMap.py). Il plist passa `plutil -lint`; non è stato caricato e la correzione non è verificata. I BDF possono cambiare se cambia l'enumerazione PCI: confrontarli a ogni variazione hardware/configurazione e prima della prova. Una prova deve conservare una EFI funzionante di recupero ed essere coordinata con l'accesso remoto e la disponibilità di tastiera/mouse. Enumerare il dispositivo non garantisce il caricamento del firmware Qualcomm né il funzionamento Bluetooth su Tahoe.
