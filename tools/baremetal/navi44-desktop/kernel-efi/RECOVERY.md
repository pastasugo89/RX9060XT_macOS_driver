# Piano di recupero: kernel Navi48Bringup 0.0.667 (payload v3)

Stato: scritto offline. Nulla di quanto segue è stato provato su hardware né sull'EFI reale.
Il payload dichiara `hardware_validation: not performed` e `installation: not performed`.
Ciò che è dedotto dal codice o dalla documentazione, e non verificato su un avvio reale, è segnalato come tale.

## 0. Dove vive OpenCore

- OpenCore ora è avviato da GRUB, con la voce `macOS Tahoe (OpenCore)`, e vive sulla partizione EFI interna di CachyOS.
  La chiavetta OCBOOT (UUID `7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3`) non serve più.
- Partizione target: `disk1s1`, FAT32, VolumeUUID `97C4AA5C-B87D-3786-B1B3-F84A76840DEF`,
  GPT partition UUID `CA42FCAB-D077-43EE-B98D-F1BAFC0F6F90`. Il default del payload v3 è questo UUID.
- Payload v3 (kernel 0.0.667): `research/builds/macos-20261031/production/kernel-payload-v3`.
  Versioni superate, conservate: `kernel-payload-v3.superseded-hotkeys/` (PollAppleHotKeys) e
  `kernel-payload-v3.superseded-stick-uuid/` (UUID della chiavetta, con BOOT/).
- Baseline, configurazione funzionante con kernel 0.0.665, sha256 `92379563c75677729be3433ce4f5d659fcdf32c7d8729b3feadd9e1daa7934cb`.
  Già presente sulla partizione locale (copiata oggi dalla chiavetta).
- Configurazione v3, sha256 `5ea9932d7fd53e97062021a72c6613f76bb96a3ecccce12d942fa8b796d531c6`.

## 1. Cosa cambia sull'EFI, e cosa non viene toccato

Scope: l'installer e il ripristino leggono e scrivono solo `EFI/OC/**` e `EFI/RECOVERY/**`.
Tutto il resto della partizione è ignorato e non viene mai letto, richiesto o scritto:

- `EFI/cachyos/` (loader e file di test di CachyOS), `EFI/boot/bootx64.efi` (fallback di CachyOS),
  `navi44-grub/`, `System Volume Information/`.
- `EFI/BOOT/`: non viene mai scritto. Su FAT `BOOT` e `boot` sono la stessa cartella: nel payload
  non c'è `BOOT/`, e l'installer non lo crea.

Tre modifiche alla configurazione funzionante, nessun'altra (verificato con `production-kernel-payload.py check`):

| Percorso | Prima (665) | Dopo (v3) |
|---|---|---|
| `Kernel/Add[7]/BundlePath` | `Navi48Bringup-eight-0.0.665.kext` | `Navi48Bringup-contexts-0.0.667.kext` |
| `Misc/Tools[0]/Name` | `Ripristino EFI (UEFI Shell)` | `Ripristino EFI: driver funzionanti (665)` |
| `Misc/Tools[0]/Comment` | `Recovery shell: restore stage17 config` | `Restores RECOVERY/funzionante-665.plist (kernel 665) and reboots` |

`Misc/Boot/PollAppleHotKeys` resta `false`. Lo Shift nel picker non è più parte del piano: l'utente ha riferito
che non funziona.

File aggiunti oltre al kext:

- `RECOVERY/pre-contexts-667-config.plist`: byte della baseline, sha256 `92379563…`.
- `RECOVERY/funzionante-665.plist`: byte della baseline, sha256 `92379563…`. È la copia da ripristinare.
- `OC/Tools/startup.nsh`: script della shell UEFI, sha256 `318f9fb9…`, fine riga CRLF.

`RECOVERY/stage17.plist` e `OC/Tools/OpenShell.efi` restano invariati.

## 2. Ripristino dal picker di OpenCore (percorso principale)

1. Al boot, in GRUB, scegli `macOS Tahoe (OpenCore)`. GRUB è il percorso di avvio di OpenCore: non cambia la
   configurazione, che resta quella di `OC/config.plist`.
2. Nel picker di OpenCore scegli `Ripristino EFI: driver funzionanti (665)`.
   Il picker ha `Timeout` di 5 secondi (`Misc/Boot/Timeout`): seleziona la voce entro quel tempo,
   altrimenti parte la voce predefinita di macOS.
3. Dopo la selezione non premere altri tasti e attendi.
4. Comportamento atteso, non verificato su questa macchina: OpenShell esegue `startup.nsh` dalla propria cartella
   dopo circa 5 secondi. ESC prima dello scadere lo salta.
5. Lo script cerca su `fs0`…`fs9` una partizione che contenga insieme `EFI\RECOVERY\funzionante-665.plist`,
   `EFI\OC\Tools\OpenShell.efi` e `EFI\OC\config.plist`. Sulla prima trovata copia `funzionante-665.plist`
   su `EFI\OC\config.plist`, attende 5 secondi e riavvia.
6. Il riavvio carica il kext 0.0.665 e il desktop deve tornare accelerato (sezione 4).

Atteso, non verificato: la voce `Tools` avvia OpenShell e non passa per l'iniezione dei kext di macOS. Quindi il
kext 0.0.667 non viene caricato da questa voce, anche se causa un panic nell'avvio di macOS.

Se lo script non trova una partizione con i file attesi, stampa i comandi manuali e resta nella shell: vedi sezione 3.

## 3. Ripristino manuale nella shell UEFI

Dalla shell, nell'ordine:

```
map -r
fs0:
ls \EFI\RECOVERY
```

Se `ls` non mostra `funzionante-665.plist`, prova `fs1:`, poi `fs2:` e così via, finché la trovi (sulla partizione
CachyOS compaiono `\EFI\OC` e `\EFI\RECOVERY`). Quando la trovi:

```
cp -q \EFI\RECOVERY\funzionante-665.plist \EFI\OC\config.plist
reset
```

`cp -q` non stampa un esito verificabile: se a schermo compare un errore, non riavviare; usa la sezione 5.

## 4. Guardia di attivazione (desktop accelerato dopo il ripristino)

La guardia `accelerated-reboot-trial.sh` ha un ramo per il kernel caricato:

- `com.navi48.bringup (0.0.667)`: i controlli di capacità a 64 contesti (VMID dinamico, contesto logico 63), come prima.
- `com.navi48.bringup (0.0.665)`: i controlli a 64 contesti sono saltati; il resto è la guardia live (bundle-30) invariata.
- altro kernel: `STOP expected kernel 667 or 665`.

Rispetto alla guardia live il diff contiene solo aggiunte (nessuna riga live è rimossa o modificata).
Il formato `com.navi48.bringup (0.0.665)` nell'output di `kmutil showloaded` è stato confermato nei log del repo.
Il comportamento a runtime non è verificato.

## 5. Ripristino da Terminale di Recovery (senza Python e senza la shell)

Non è garantito che Recovery contenga `python3`. I comandi usano solo strumenti di sistema. Non sono stati provati:
verifica su un Mac con lo stesso layout prima di affidarsi a loro.

```sh
diskutil info disk1s1 | grep -E 'Volume UUID|Mount Point'   # conferma 97C4AA5C-B87D-3786-B1B3-F84A76840DEF
diskutil mount disk1s1                  # montaggio in scrittura
E=/Volumes/EFI/EFI                      # adattare al nome reale del mount (ls /Volumes)
shasum -a 256 "$E/RECOVERY/funzionante-665.plist"   # ci si aspetta 92379563…
cp "$E/RECOVERY/funzionante-665.plist" "$E/OC/config.plist.tmp"
mv "$E/OC/config.plist.tmp" "$E/OC/config.plist"    # rinomina sul FAT
cmp "$E/RECOVERY/funzionante-665.plist" "$E/OC/config.plist" && echo CONFIG_RESTORED
sync
diskutil unmount disk1s1
```

## 6. Installazione e ripristino con gli script (offline, non eseguiti)

Il target di default è la partizione CachyOS (UUID della sezione 0). Con `--efi-uuid` si può scegliere un altro volume,
per esempio la chiavetta `7ADF2DE6-4394-3D07-AC2B-E79E1D78A2F3`, ma non è più il percorso previsto.

```sh
# verifica e piano, nessuna scrittura
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/install-kernel-efi.py research/builds/macos-20261031/production/kernel-payload-v3
# installazione: scrive solo OC/ e RECOVERY/, crea il backup, non attiva e non riavvia
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/install-kernel-efi.py research/builds/macos-20261031/production/kernel-payload-v3 --apply
# ripristino dal backup, o dal RECOVERY sull'EFI
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/restore-kernel-efi.py <payload-v3> --backup <dir> --apply
sudo python3 tools/baremetal/navi44-desktop/kernel-efi/restore-kernel-efi.py <payload-v3> --from-recovery --apply
# test offline
python3 tools/baremetal/navi44-desktop/kernel-efi/test-kernel-efi.py
python3 tools/baremetal/navi44-desktop/test-production-kernel-guard.py
```

- L'installer applica solo le modifiche elencate in `config_edits` del manifest (percorso, vecchio valore, nuovo valore).
  Un payload senza elenco, come v2, viene rifiutato. Un payload che elenca file fuori da `OC/` e `RECOVERY/` viene rifiutato.
- `restore-kernel-efi.py --remove-kext` rimuove il kext 0.0.667. Le copie in `RECOVERY/` e `OC/Tools/startup.nsh`
  restano. Lo script non le rimuove: `startup.nsh` copia la baseline, quindi è innocuo.
- L'installazione richiede `APP/disabled` oppure i file di guardia revisionati (vedi `install-kernel-efi.py`).

## 7. Lacune note

**G1, un panic in `start()` del kext 0.0.667 non è coperto dal picker.** La voce `Tools` evita il kext (sezione 2),
ma il percorso di avvio macOS resta quello con il kext. Non è stato verificato. Il rimedio operativo è la voce del picker.

**G2, la guardia non protegge il caricamento del kext.** Protegge solo l'attivazione del display. Un hang in `start()`
avviene prima di qualsiasi latch di stato.

**G3, la guardia deve essere quella revisionata prima dell'installazione.** Vedi `APP/disabled` in `install-kernel-efi.py`.

**G4, GRUB e picker.** Il passaggio da GRUB non è stato provato: non è verificato che la voce `macOS Tahoe (OpenCore)`
porti al picker con i `Timeout` attesi.

Il picker non è un percorso sicuro verso il 665 se la voce `Tools` non viene riconosciuta: in quel caso restano
le sezioni 3 e 5.

**Nota, non una via di recupero:** il kext 0.0.667 rinuncia a partire con `-x` o con `navi48-off=1` (commit `db8b202`).
Lo Shift nel picker non funziona su questa macchina, quindi questo interruttore non è raggiungibile dal picker.
