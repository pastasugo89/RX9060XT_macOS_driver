# Audio analogico posteriore - piano audio-v1 (31 ottobre 2026)

Stato: **NON pronto al deploy.** Candidato staging bloccato su una gate tecnica
non risolta (coesistenza con IOAudioFamily 740.1). Nessuna modifica a EFI,
/Library, /System, nessun sudo, nessun riavvio. OCBOOT è stato solo letto
(montaggio read-only già presente in /Volumes/OCBOOT).

## 1. Evidenze

Sistema: macOS 26.6.2 (25G83), MSI B840 GAMING PLUS WIFI, Ryzen 7700.

- Controller HD Audio: `AZAL@6` sotto `GP17@80001`, `pci1022,15e3`, subsystem
  `pci1462,ee57`, classe 0x040300, attivo ma senza driver (ioreg, letto ora).
  Nessun HDEF/HDAU associato al jack; gli HDAU presenti (`1002:ab40`, `1002:1640`)
  sono le funzioni audio HDMI/DP della GPU Navi48, non il jack.
- CoreAudio enumera solo il dongle USB Corsair VOID ELITE (`system_profiler
  SPAudioDataType`). Nessun device analogico.
- Driver audio caricati: solo `IOAudioFamily 740.1`, `AppleAudioClockLibs`,
  `AppleUSBAudio`. Nessun AppleHDA, nessun AppleALC, nessun VoodooHDA.
- Config OC live: nessuna entry audio in Kernel>Add; boot-args senza `alcid`/layout.
- AppleHDA assente da `/System/Library/Extensions` (verificato). AppleGFXHDA è
  presente ma è il driver HDA dell'Apple GFX, non applicabile a questo controller.
- AppleALC README (letto ora da github.com/acidanthera/AppleALC): "macOS 26
  dropped AppleHDA.kext in DP2" e AppleALC "may require additional actions if
  AppleHDA.kext is necessary". Quindi AppleALC non ha un bersaglio su Tahoe 26.6.2.
- **Codec: non verificato.** I file `postboot/audio-hda-codec.txt`,
  `audio-hda-controller.txt`, `audio-hdef.txt` in
  `research/builds/macos-20261028/postboot/` hanno dimensione zero: nessun dump
  verb/codec è mai stato acquisito. L'unica indicazione è la scheda MSI
  (ALC897, dichiarazione del produttore riportata nel report precedente, non
  rilevata sul sistema). La stringa `Realtek ALC1220` in lspci è SMBIOS/vecchia
  e non va usata. Nessun codec Realtek è esposto a macOS oggi, quindi l'ID
  codec non è leggibile senza un driver che lo inizializzi.
- Config OCBOOT live: SHA-256 `92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb`.
  Corrisponde identico a `research/builds/macos-20261028/gpu-eight-efi-v6/EFI/OC/config.plist`
  (ultimo gruppo deployato). Il valore `8968c7e8...` del report unified_repair
  era il payload precedente, superato.
- Candidati audio precedenti (tutti `prepared-not-installed`):
  - VoodooHDA **3.6.8** (Release368, SHA archivio `9aaa01b2...`, digest GitHub
    verificato dal report precedente). Richiede IOAudioFamily come dipendenza
    esterna: serve AuxKC, che non si costruisce (`kmutil`: codice 31, "No binaries
    or codeless kexts were provided"). Installazione in /Library = sudo: fuori scope.
  - VoodooHDA **3.7.1-alpha** (commit d9e642d, SHA archivio `1182eb30...`), staged
    come `VoodooHDA_BL.kext`, personality solo `1022:15e3`/`1462:ee57`, nessuna
    HDMI. Incorpora IOAudioFamily nel bundle e quindi non dipende dalla
    collezione di sistema. Il manifest interno dice: **"Do not inject before
    resolving this"**: classi IOAudioEngine esportate dal kext (20 simboli
    gMetaClass) sono già registrate dalla IOAudioFamily 740.1 caricata.

## 2. Scelta e ragionamento

Il percorso è VoodooHDA. AppleALC è escluso (AppleHDA assente su Tahoe).

Tra le due versioni VoodooHDA:
- 3.6.8 è l'unica che si carica "come da documentazione" sul sistema, ma richiede
  AuxKC o installazione in /Library. Entrambe sono fuori dai vincoli del task
  (no sudo, no /Library, no AKC) e l'AuxKC è già fallito.
- 3.7.1-alpha si inietta da OpenCore senza AKC e senza modificare /Library
  (un'entry in Kernel>Add), ma **richiede una modifica EFI** e la coesistenza
  con IOAudioFamily 740.1 non è verificata. È la sola via tecnicamente
  percorribile, ed è bloccata.

Quindi la risposta alla domanda "EFI deve cambiare?" è: **sì**, per l'unica via
senza AKC. Non esiste una via senza EFI e senza sudo che sia tecnicamente sound.

Il candidato preparato qui è la variante 3.7.1 con una sola entry in Kernel>Add.

## 3. Artefatti staging (non deployati)

- `config.live-baseline.plist`: copia del config OCBOOT live (SHA `92379563...`).
- `config.candidate-blocked.plist`: baseline + una entry Kernel>Add
  (`VoodooHDA_BL.kext`, `Enabled=true`, `PlistPath`/`ExecutablePath` come da
  bundle). `plutil -lint` OK. Diff: solo indice 16 aggiunto (16 -> 17 entry).
  SHA `4ce3c380...`.
- `EFI-candidate/EFI/OC/`: `config.plist` (identico al candidato) +
  `Kexts/VoodooHDA_BL.kext` (copia del bundle 3.7.1, firma ad hoc, eseguibile
  SHA `ae47fe4c...`).

Validazione non eseguita: `ocvalidate` nel repo è un binario ELF Linux, non
eseguibile su macOS; il report unified_repair dichiara la validazione 1.0.8 su
altre configurazioni, non su questa. `codesign -dv` verifica solo firma ad hoc,
che è accettata da OpenCore.

## 4. Rischi

- **Bloccante**: coesistenza IOAudioFamily. Se VoodooHDA_BL registra classi già
  presenti, il kext può non avviarsi (IOKit warn) o, peggio, creare un'inconsistenza
  al boot. Non è stato testato.
- Boot failure: un kext injection con panic nel probe. Mitigazione: il config
  baseline va conservato integro fuori dal stick (copia privata) e il boot può
  essere ripristinato sostituendo solo `config.plist` sul stick da un altro
  computer. Ma l'utente dovrebbe avere accesso a OCBOOT per il rollback.
- Codec sconosciuto: anche con il kext caricato, VoodooHDA dipende dal codec.
  Nessuna uscita analogica è garantita, e il layout 0 può non attivare il pin
  posteriore. Il readme upstream dichiara "lottery per codec".
- Il readme 3.7.x cita "verified macOS Tahoe 26.7.1, OpenCore 1.0.7": non è
  26.6.2 / OC 1.0.8. Non è una prova per questo sistema.
- Nessun kext nel sistema reale è stato caricato o testato in questo task.

## 5. Gate prima di qualsiasi deploy

1. Verificare coesistenza: confronto simboli IOAudioEngine e OSMetaClass tra
   `VoodooHDA_BL` e IOAudioFamily 740.1 (SystemKC), oppure prova su AuxKC di sola
   prova come da report precedente (fallita, codice 31). Se non risolvibile,
   fermarsi.
2. Leggere il codec dal vivo (senza scritture): richiede che un driver porti
   su il controller; in alternativa usare un Linux live (già usato nel progetto:
   `/proc/asound/card*/codec#0`, `hda-verb` non serve, basta `cat`) e
   registrare il Vendor ID con la stessa coppia `1022:15e3`/`1462:ee57`.
3. Approvazione esplicita dell'utente per modifica EFI (OCBOOT).

## 6. Passi di deploy (NON eseguire finché la gate non è chiusa)

Eseguiti dall'utente, con root e con OCBOOT montato in scrittura:

```sh
# 0. backup privato del config live e verifica SHA
sudo mkdir -p "/Library/Application Support/Navi44/audio-v1-backup"
sudo cp -p /Volumes/OCBOOT/EFI/OC/config.plist "/Library/Application Support/Navi44/audio-v1-backup/config.plist.pre"
shasum -a 256 /Volumes/OCBOOT/EFI/OC/config.plist   # deve essere 92379563...

# 1. copia del kext nella cartella Kexts del stick
sudo cp -R "/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/builds/macos-20261031/audio-v1/EFI-candidate/EFI/OC/Kexts/VoodooHDA_BL.kext" /Volumes/OCBOOT/EFI/OC/Kexts/

# 2. sostituzione atomica del config (solo OC/config.plist)
sudo cp "/Users/pastasugo89/Documents/rx9060xt-import-HChjRy/rx9060xt_metal_driver/research/builds/macos-20261031/audio-v1/config.candidate-blocked.plist" /Volumes/OCBOOT/EFI/OC/config.plist.new
sudo mv /Volumes/OCBOOT/EFI/OC/config.plist.new /Volumes/OCBOOT/EFI/OC/config.plist
sync

# 3. verifica
shasum -a 256 /Volumes/OCBOOT/EFI/OC/config.plist   # deve essere 4ce3c380...
```

## 7. Rollback

Se il boot fallisce: su un altro Mac, o da OpenCore picker con selezione del
config precedente, ripristinare:

```sh
sudo cp "/Library/Application Support/Navi44/audio-v1-backup/config.plist.pre" /Volumes/OCBOOT/EFI/OC/config.plist
sudo rm -R /Volumes/OCBOOT/EFI/OC/Kexts/VoodooHDA_BL.kext
sync
shasum -a 256 /Volumes/OCBOOT/EFI/OC/config.plist   # deve essere 92379563...
```

Il rollback di sole `config.plist` basta: senza l'entry, il kext non viene
caricato anche se resta sul disco.

## 8. Dopo riavvio (solo se il deploy è stato autorizzato)

- `kextstat | grep -i voodoo` deve mostrare `org.voodoo.driver.VoodooHDA`.
- `ioreg -l | grep -i -E 'VoodooHDA|AZAL'`: il controller deve avere un child.
- `system_profiler SPAudioDataType`: deve comparire un device analogico con
  Output Channels > 0.
- Test udibile su casse posteriori, volume e mute, frequenze, hotplug e
  sleep/wake, come da PLAT-01 in COMPLETEZZA_DRIVER_GPU.md §20.
- Log kernel: `log show --last 5m --predicate 'process == "kernel"' | grep -i voodoo`.

---

## 9. AGGIORNAMENTO (richiesta coordinatore): VoodooHDA 3.6.8 via /Library/Extensions + AKC

Il percorso 3.7.1 (sezioni 2 e 6) è respinto. Il percorso scelto è 3.6.8, installato
in `/Library/Extensions` e collegato alla AuxiliaryKernelExtensions.kc, come i kext GPU.
EFI non cambia. L'installazione richiede sudo, eseguito dall'utente con lo script.

### 9.1 Perché l'AKC di 3.6.8 fallisce senza root (exit 31)

- Il messaggio è `Error occurred while building a collection: No binaries or codeless kexts were provided`
  (kc-check in `research/builds/macos-20261028/audio-trial-v1/kc-check/*.log`, `audio-trial-v2/kc-check.log`).
  I log non contengono il comando, ma i tentativi erano eseguiti come utente 501 con kext di proprietà 501:20.
- Causa confermata: su macOS 26 kmutil ignora (tratta come codeless) i kext che non sono di proprietà
  root:wheel. Il nullmoth install.sh lo documenta esplicitamente: `macOS 26 kmutil silently skips kexts not owned by root`
  (`research/ext/nullmoth-postboot-20261028/package/install.sh:~300`).
- Riprodotto oggi senza root (logs in `dryrun/`):
  - test A: VoodooHDA 3.6.8 upstream da solo -> rc=31 `Cannot build collection without binaries as only 1 codeless kexts provided`
  - test B: RDNA4FB 0.0.8 + Navi48Accel 0.0.7 + VoodooHDA candidate -> rc=31 stesso messaggio
  - test C: solo RDNA4FB -> rc=31
- `kmutil print-diagnostics -p` su VoodooHDA: `Invalid ownership (501:20) should be (0:0)` per ogni file;
  `Dependencies: OK`. Lo stesso comando su RDNA4FB caricato dà "Bad code signature" pur essendo
  caricato, quindi quella riga è un artefatto di esecuzione senza root, non un difetto della firma.
- Non sono emersi problemi di dipendenza: IOAudioFamily 740.1 (sistema, caricato) soddisfa `1.1fc9`.
  Firma ad hoc valida (`codesign --verify --deep --strict`: valid on disk). Arch x86_64.
  Non serve modificare Info.plist o rifirmare. Il problema è solo la proprietà.
- Non è stato possibile eseguire un build root-owned senza sudo. La prova definitiva è quindi il
  primo build dell'install script, che è protetto da guardia.

### 9.2 Stato AKC GPU corrente (read-only)

`kmutil showloaded --collection aux`: caricati solo `com.hackintosh.RDNA4FB 0.0.8` e
`com.navi48.accelprobe 0.0.7` (Navi48Accel). `kmutil inspect -A ...AuxiliaryKernelExtensions.kc` elenca anche
`com.highpoint-tech.kext.HighPointRR 4.22.1` e `HighPointIOP 4.4.5` (path `/Library/StagedExtensions/...`, non caricati)
e `com.apple.driver.AppleMobileDevice 4.0` (path Apple). AKC del 27 ottobre 19:06.
Lo script GPU che ha costruito l'AKC non è nel repo: il riferimento verificato è la ricetta nullmoth
(`install.sh:313/449`), che usa lo stesso comando. Da confermare prima del deploy.

### 9.3 Build: file

- `kext/VoodooHDA.kext`: copia del personality Navi44 (`audio-trial-v2/candidate`), firma ad hoc valida.
  SHA-256 in `kext/SHA256SUMS`.
- `install-audio.sh` (sudo): verifica hash e firma; rifiuta se il kext è già installato; registra le
  aux caricate; copia il backup dell'AKC (non cancella nulla); copia il kext in `/Library/Extensions`
  con root:wheel e go-w; costruisce un repo root-owned con tutti i kext di `/Library/Extensions`;
  `kmutil create -n aux --volume-root / --allow-missing-kdk -B ... -S ... --repository ... -A ... -z`;
  guardia: ogni aux caricata e ogni kext in `/Library/` già nell'AKC devono essere nel nuovo AKC,
  altrimenti esce senza modifiche; sostituzione atomica dell'AKC.
- `uninstall-audio.sh` (sudo): stessa guardia senza VoodooHDA; copia il kext in backup, ricostruisce l'AKC,
  sostituisce, poi rimuove il kext.

Test eseguiti: `bash -n` su entrambi; esecuzione come utente: rifiuto `STOP run with sudo` (rc=1, nessun cambiamento);
logica della guardia contro l'AKC live in sola lettura: `missing: []`.

### 9.4 Rischi specifici del percorso 3.6.8

- La guardia include `com.apple.driver.AppleMobileDevice`, che viene dal path Apple. Se il rebuild dal repo
  `/Library/Extensions` non lo include, lo script esce senza modifiche. È il comportamento voluto ma va
  verificato alla prima esecuzione.
- Il nuovo kext richiede approvazione in Impostazioni > Privacy e sicurezza, poi riavvio (come i kext GPU).
- Il candidato non è mai stato caricato. Non c'è prova che il codec risponda sul jack posteriore.
- Il codec resta sconosciuto (sezione 1).
- Rollback: `sudo uninstall-audio.sh`, oppure copiare `"/Library/Application Support/Navi44/audio-v1-backup/<ts>/AuxiliaryKernelExtensions.kc.pre"`
  sopra l'AKC e rimuovere `/Library/Extensions/VoodooHDA.kext`, poi riavviare.
