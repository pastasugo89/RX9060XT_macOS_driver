# USB B840: raccolta Linux per la mappa porte

## Strumento disponibile

Il programma ufficiale USBToolBox dichiara discovery su Windows e macOS, non Linux; il suo runtime USBToolBox.kext è destinato a macOS. Il collector locale in `tools/baremetal/usb_topology_linux.py` resta un aiuto read-only: da solo non è USBToolBox e non produce il suo `usb.json`. Il nuovo adattatore `tools/baremetal/usbtoolbox_linux_port.py` traduce la topologia Linux nel modello del generatore ufficiale e invoca il suo `BaseUSBMap.build_kext()` per produrre una candidata nativa. Entrambi leggono solo identità/topologia da sysfs: niente eventi input/tasti, seriali periferiche, contenuti storage o MMIO; il collector usa il seriale del solo root hub quando contiene un BDF PCI.

Prima vista:

```sh
python3 tools/baremetal/usb_topology_linux.py inventory
```

Per associare il ricevitore del mouse GravaStar (`3554:f576`) alle prese, lasciare collegata la NuPhy cablata per mantenere l'input Linux e poter scrivere le etichette nel terminale; avviare:

```sh
python3 tools/baremetal/usb_topology_linux.py watch --output /tmp/usb-b840-pass1-20261025-mouse.jsonl --match-vidpid 3554:f576 --prompt-label
```

Poi spostare **solo il ricevitore del mouse** una presa alla volta, digitare al prompt l'etichetta visibile della presa e attendere la nuova enumerazione prima del movimento seguente. Il file non viene sovrascritto se esiste già. `Ctrl-C` termina la raccolta. Non scollegare la NuPhy cablata.

Ogni evento annota separatamente controller PCI, `pcidebug` decimale per USBToolBox, root-port Linux, percorso `route` completo del dispositivo (inclusi eventuali hub a valle), `_ADR` raw ACPI, eventuale `peer_companion` e label fisica inserita dall'utente. Il collector distingue le identità osservate dalle proprietà firmware. Il suo JSONL è un formato di supporto locale, non uno schema ufficiale o un input USBToolBox verificato.

## Stato dell'inventario host

Il collector ha letto da sysfs questi controller e numeri di porta. Il legame porta Linux → `_ADR` è esposto dal firmware e verificabile attraverso `firmware_node`; il kernel Linux usa il raw port number per trovare il device ACPI del root port. `peer` segnala il companion fra personalità USB2 e SuperSpeed. Questi dati non identificano ancora il jack fisico.

| Controller PCI (pcidebug) | Root hub Linux | Porte Linux → `_ADR` ACPI | Companion dichiarati |
|---|---|---|---|
| `0000:05:00.0` (`5:0:0`) | USB2 | p1–p10 → raw 5–14 | p1–p4 ↔ SS p1–p4 (raw 1–4) |
| `0000:05:00.0` (`5:0:0`) | SS | p1–p4 → raw 1–4 | p1–p4 ↔ USB2 p1–p4 (raw 5–8) |
| `0000:0a:00.3` (`10:0:3`) | USB2 | p1–p2 → raw 1–2 | p1–p2 ↔ SS p1–p2 (raw 3–4) |
| `0000:0a:00.3` (`10:0:3`) | SS | p1–p2 → raw 3–4 | p1–p2 ↔ USB2 p1–p2 (raw 1–2) |
| `0000:0a:00.4` (`10:0:4`) | USB2 | p1–p2 → raw 1–2 | p1–p2 ↔ SS p1–p2 (raw 3–4) |
| `0000:0a:00.4` (`10:0:4`) | SS | p1–p2 → raw 3–4 | p1–p2 ↔ USB2 p1–p2 (raw 1–2) |
| `0000:0b:00.0` (`11:0:0`) | USB2 | p1 → raw 1 | nessuno esposto |

Lo snapshot live mostra anche un hub USB2 (`05e3:0608`) sotto `0b:00.0` root p1 e un dispositivo a valle con percorso `route=1.1`. Questo illustra perché il root-port è quello upstream del controller e il percorso completo serve a distinguere le diramazioni dietro un hub; non viene letto alcun contenuto di archiviazione.

Le porte osservate già occupate includono NuPhy `19f5:1030` su `0a:00.3` USB2 p1; NuPhy `19f5:3247` su `0a:00.3` p2; dongle NuPhy `19f5:2620` su `05:00.0` USB2 p1; mouse `3554:f576` su `0a:00.4` USB2 p1; Bluetooth Foxconn su `05:00.0` p6; e Mystic Light su `05:00.0` p5. Sono posizioni correnti Linux, non associazioni a prese fisiche. Le velocità correnti dei dispositivi NuPhy/mouse sono 12 Mb/s, quindi USB 2 compatibile; il lato SuperSpeed dei companion non è stato negoziato durante questa raccolta.

## Jack fisici dichiarati dal manuale MSI

La guida MSI per il modello esatto B840 GAMING PLUS WIFI elenca sul pannello posteriore: quattro USB 2.0 Type-A (dal hub GL850), due USB 5Gbps Type-A, una USB 10Gbps Type-A e una USB 10Gbps Type-C. Le quattro Type-A USB2 dietro GL850 sono porte downstream di un hub: possono condividere un solo collegamento/porta root verso il controller Linux. Per distinguerle va mantenuto il `route` completo, che include il percorso attraverso l'hub; non si deve assegnare una porta root separata a ciascun jack. Per il front panel MSI dichiara due header USB 2.0 (`JUSB1~2`, quattro porte Type-A in totale), un header USB 5Gbps (`JUSB3`, due Type-A) e `JUSBC1` per una Type-C USB 5Gbps. L'utente riferisce che sono collegate solo le USB-A frontali e non la Type-C frontale.

Il disegno “Back Panel Connectors” a p. 23 numera i gruppi/jack; la sezione header è alle pp. 42–43 e il block diagram a p. 60 mostra i gruppi USB front/rear e il chip GL850. Manuale e schema stabiliscono quantità, forma e classe nominale dei connettori, ma non associano da soli ogni jack a un indice root-port/raw `_ADR`. Nessun colore o ordine grafico è usato qui per inferire la mappa.

Con i soli dispositivi USB2 disponibili si possono annotare prese USB-A in cui il dongle è fisicamente collegabile. Lato SuperSpeed di un companion resta dichiarato dal firmware/sysfs ma non verificato con trasferimento SuperSpeed; non è una mappa completa validata. Le Type-C e le prese interne non ancora raggiunte dal dispositivo rimangono senza label osservata. Non usare la chiavetta USB personale da 128 GB né aprire file di storage.

## Riferimenti primari

- [USBToolBox tool README](https://github.com/USBToolBox/tool/blob/master/README.md) e [USBToolBox kext README](https://github.com/USBToolBox/kext/blob/main/README.md).
- [MSI B840 GAMING PLUS WIFI User Guide (PDF)](https://download-2.msi.com/archive/mnu_exe/mb/B840GAMINGPLUSWIFI_English.pdf), soprattutto pp. 23, 42–43 e 60.
- [Linux USB sysfs ABI](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/ABI/testing/sysfs-bus-usb) e [Linux USB ACPI bridge](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/usb/core/usb-acpi.c).

## Adattatore Linux e candidata USBToolBox (25/10/2026)

Il sorgente ufficiale `USBToolBox/tool` è conservato localmente in `research/ext/usbtoolbox-tool`, checkout sparse al commit `0c6823a2c643a4488888938451194723dc9ae29a` (MIT; il file `LICENSE` upstream resta nel checkout ignorato). Il README ufficiale dichiara supporto Windows/macOS. Il backend locale non modifica quel sorgente: `usbtoolbox_linux_port.py` legge il collector read-only, crea controller e porte nel formato usato da `BaseUSBMap`, controlla l'unicità PCI e chiama il builder upstream vero. I due punti UI del builder sono sostituiti da prompt mock stretti: il modello target `MacPro7,1` e il solo menu finale atteso; prompt inattesi interrompono la generazione. I componenti terminale/colori sono solo display shim. La mappa usa classi native `AppleUSBHostMergeProperties`; non richiede il binario o il runtime USBToolBox.kext.

Generazione riproducibile dalla root del progetto (l'output si rifiuta di sovrascrivere una candidata esistente):

```sh
git clone --filter=blob:none --no-checkout https://github.com/USBToolBox/tool.git research/ext/usbtoolbox-tool
git -C research/ext/usbtoolbox-tool sparse-checkout init --no-cone
git -C research/ext/usbtoolbox-tool sparse-checkout set --no-cone /base.py /Scripts/ /resources/Info.plist /LICENSE /README.md
git -C research/ext/usbtoolbox-tool fetch --depth=1 origin 0c6823a2c643a4488888938451194723dc9ae29a
git -C research/ext/usbtoolbox-tool checkout --detach 0c6823a2c643a4488888938451194723dc9ae29a
python3 tools/baremetal/usb_topology_linux.py inventory
python3 tools/baremetal/usbtoolbox_linux_port.py generate \
  --upstream research/ext/usbtoolbox-tool \
  --output research/ext/usbtoolbox-linux-port-candidate \
  --model MacPro7,1
python3 tools/baremetal/usbtoolbox_linux_port.py prepare-config \
  --candidate research/ext/usbtoolbox-linux-port-candidate \
  --baseline-efi research/ext/opcore-simplify-b840-cpus1-mmio-f700-usb-parentmatch-usb-native/EFI \
  --ocvalidate research/ext/ocboot-baremetal/_dl/opencore/src/Utilities/ocvalidate/ocvalidate.linux
```

Per una rigenerazione successiva, usare una nuova directory `--output` e `--candidate`; le destinazioni esistenti non sono sovrascritte.

La candidata nativa generata è `research/ext/usbtoolbox-linux-port-candidate/USBMap.kext/Contents/Info.plist` (SHA-256 `e1ddb59febdddcb63ecf309b37f454159ff23396ae1f511099c4fc94a1065312`). Il matcher nativo contiene i PCI ID univoci (`0x43ef1022`, `0x15b61022`, `0x15b71022`, `0x15b81022`) sotto `IOParentMatch/IOPCIPrimaryMatch`; il BDF Linux resta solo nei metadati. Verifica sul plist generato: XH00 14 porte, XHC0 4, XHC1 4, XHC2 1; tutti gli indici provengono da ACPI `_ADR` raw e restano entro il limite 15. Sono incluse tutte le porte scoperte.

La candidata EFI locale `research/ext/usbtoolbox-linux-port-candidate/EFI/` parte dalla baseline BOOT15 (config SHA-256 `7bbf4e3e3eaf7ec13aa52780c82412a9b2a5b9dac8de98cba990fb4d884cdafb`). Per contenere il diff, riusa il percorso `OC/Kexts/USBMapB840.kext`: la sola voce `Kernel.Add` passa da disabilitata ad abilitata e il suo `Contents/Info.plist` è sostituito con il plist nativo prodotto dal builder USBToolBox. Il confronto semantico del config conferma che questa è l'unica modifica alla config; i 26 file EFI restanti sono byte-identici, senza file aggiunti o rimossi. SHA-256 del config candidato: `55d53e17585af340d3d23c99bd2a305390c7c64005d1735f31d07b742012ac25`. `ocvalidate` OpenCore 1.0.8 Linux passa. La candidata è stata copiata su OCBOOT UUID `A140-3052` come BOOT16; l’utente ha poi riferito lo stesso pairing animato e input assente.

Classificazione dei connettori inclusa nei commenti e in `porting-metadata.json`:

- **Osservato e interno (`UsbConnector=255`)**: Mystic Light `0db0:0076` su XH00 raw 9; Bluetooth Foxconn `0489:e10a` su XH00 raw 10; hub GL850 `05e3:0608` su XHC2 raw 1. Il Cruzer Fit `0781:5571` è osservato a valle del hub su route `1.1`; non crea un root-port aggiuntivo e non è letto alcun contenuto storage.
- **Dedotto per conteggio, jack non attribuito (`UsbConnector=0`)**: XH00 raw 11–14 sono quattro root port USB2 senza peer, coerenti per quantità con i quattro USB2 Type-A frontali riportati dal manuale. Non è dimostrato che ogni raw corrisponda proprio a un header/jack specifico.
- **Assunto e mantenuto (`UsbConnector=3`)**: le altre coppie USB2/SuperSpeed sono incluse con default USB3 Type-A. Il manuale dichiara anche jack Type-C, ma non identifica l'indice ACPI corrispondente né il comportamento del suo switch; non è stata fatta una prova SuperSpeed. La forma A/C e il mapping fisico restano quindi ignoti. Questo default conserva le porte candidate per HID senza dichiarare i tipi fisici come osservati.

La verifica `ocvalidate` controlla la struttura OpenCore del config; non verifica il match IOKit in macOS, la negoziazione USB3 o l'input Recovery. BOOT15, con la mappa disabilitata, non è stata avviata né provata e resta non classificata, non negativa. BOOT16 è stata avviata; l'utente riferisce la stessa schermata animata Magic Keyboard/Mouse e nessun input. L'esito non prova se il matching IOKit abbia applicato la mappa; la diagnosi Tahoe e la candidata locale BOOT17 sono in `research/reports/usb_tahoe_schema_diagnosis_20261026.md`. Il preflight deployment ha controllato i 28 file del manifest BOOT15; ha creato un backup fuori dalla EFI con config SHA `7bbf4e3e3eaf7ec13aa52780c82412a9b2a5b9dac8de98cba990fb4d884cdafb` e Info SHA `9249e728191fc64b8685407fe4f7446049be988dd9fec30e427262a37ece5edb`. Dopo aver sostituito prima `Info.plist` e poi il config, il manifest candidato 28/28 e `ocvalidate` 1.0.8 sono passati; 26 payload sono rimasti byte-identici. Record/backup: `research/ext/usbtoolbox-linux-port-candidate/deploy-evidence/20261025T220633/`; il supporto è stato smontato. Il comando di deploy verificabile è `python3 tools/baremetal/deploy-usbtoolbox-map-b840.py --backup research/ext/usbtoolbox-linux-port-candidate/deploy-evidence/20261025T220633` dopo il mount RW del solo volume OCBOOT previsto; lo script rifiuta UUID o manifest inattesi e una seconda installazione della candidata. Nessun cavo è stato spostato. Riferimenti upstream: [README USBToolBox](https://github.com/USBToolBox/tool/blob/0c6823a2c643a4488888938451194723dc9ae29a/README.md), [builder `BaseUSBMap`](https://github.com/USBToolBox/tool/blob/0c6823a2c643a4488888938451194723dc9ae29a/base.py), [licenza MIT](https://github.com/USBToolBox/tool/blob/0c6823a2c643a4488888938451194723dc9ae29a/LICENSE).


## Esito BOOT16 e compatibilità proprietà Tahoe (26/10/2026)

L'utente riferisce che BOOT16 ripete la schermata animata di pairing Magic Keyboard/Mouse senza input. La candidata contiene 23 porte ma nessuna delle chiavi `usb-port-number`/`usb-port-type`: il runtime USBToolBox 1.2.0 le aggiunge in `fixMapForTahoe()` a partire da `port`/`UsbConnector` quando macOS major è almeno 25; BOOT16 invece usa una personality nativa senza quel runtime. La correzione è stata applicata come BOOT17: Info SHA `71f93330cf748e5a58bfa856c47abd35d80798c8272d7f0bf702c7312f04dd7d`; config BOOT16 invariata e gli altri 27 file EFI identici. Preflight BOOT16 e postmanifest BOOT17 28/28, `ocvalidate` 1.0.8 PASS. Backup BOOT16 SHA `e1ddb59febdddcb63ecf309b37f454159ff23396ae1f511099c4fc94a1065312` e record in `research/ext/usbtoolbox-linux-tahoe-boot17-candidate/deploy-evidence/20261026T131317524219Z/`; supporto smontato. BOOT17 è attiva ma il test hardware è pendente. Evidenza, hash, fonti upstream e limiti: [`usb_tahoe_schema_diagnosis_20261026.md`](usb_tahoe_schema_diagnosis_20261026.md).
