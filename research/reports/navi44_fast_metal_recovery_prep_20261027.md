# Recupero EFI stage1 Linux: preparazione in staging — 27/10/2026

## Esito

Preparato [lo script Linux di recovery](../ext/navi44-fast-metal-recovery-prep-20261027/tools/restore-stage1-efi-linux.sh), il manifest stage1 e una suite di prova isolata. Non ho scritto sulla chiavetta da 128 GB, su OCBOOT, sull’EFI attiva o sui dischi di sistema; non ho collegato cavi, riavviato o caricato kext.

L’archivio reale `/Volumes/Untitled 1/macOS-Tahoe-25G83-installer/OCBOOT-stage1-success-20261027.tar` è leggibile; SHA-256 osservato `2beaea0412c6fc3e4681a65b5703a24f435f7201a32f44936e5e299d389f78f2`, uguale al digest registrato nel report stage1. `tar -tf` conta 31 file `EFI/...`; i file estratti in una directory temporanea coincidono byte per byte con il candidato stage1 locale. Differiscono solo due directory vuote nel candidato (`EFI/OC/Resources`, `EFI/OC/Tools`), non incluse nell’archivio. Il nuovo manifest contiene i 31 hash e ha SHA-256 `96877ab31d3abccf1aa2e70c8688b5ef0e9637d44da8e78d8a27b0dd7ced62b2`.

## Garanzie dello script

Lo script rifiuta target diversi dalla partizione FAT UUID `A140-3052`, montaggi non `vfat` o `ro`, archive/manifest con hash o lista errati e supporti di recovery non fisicamente distinti dal target. Richiede che la directory di backup sia sullo stesso device indipendente dell’archivio. Non esegue mount/unmount: l’operatore deve identificare e montare i volumi in Linux. `--check` è read-only; `--restore` richiede un flag di conferma sulla command line e una seconda conferma interattiva.

Prima di cambiare `EFI/`, salva la directory corrente in un tar con checksum sulla chiavetta di recovery; conserva anche la directory corrente sul target con nome `EFI_PRE_STAGE1_<timestamp>`. Estrae il pacchetto in staging sul volume, verifica tutti i 31 hash, poi sostituisce la sola directory `EFI/` e verifica di nuovo. Se la verifica dopo la sostituzione fallisce, il trap sposta la nuova EFI in `EFI_FAILED_RESTORE_<timestamp>` e ripristina la directory precedente. Non riavvia.

## Test

`bash -n` passa per script e test harness. La suite `tests/test_restore_stage1.sh` riporta **14 PASS / 0 FAIL**:

- `--check` accetta il target simulato senza cambiare un marker preesistente;
- rifiuta UUID errato, target o recovery in sola lettura, archivio e target sullo stesso device, archivio alterato e conferma errata;
- applica il restore solo in directory temporanee, verifica i 31 hash e conserva snapshot della EFI precedente;
- una failure injection dopo il rename dimostra il rollback automatico e la conservazione della directory fallita.

Il mock simula i comandi Linux e i block device. Per la prova, copia temporanea dello script modifica solo i controlli Linux/block-device/TTY e usa un wrapper BSD tar che rimuove le opzioni specifiche GNU. Il ripristino effettivo su Linux e su VFAT non è quindi verificato.

## Limiti ancora aperti

- L’avvio Linux dal menu firmware non è stato verificato; la procedura non può rendere disponibile un ambiente di recupero se il Mac non riesce ad avviare Linux.
- Non è stata testata l’identificazione live del device con `blkid`, `findmnt` e `lsblk`, né un mount VFAT in scrittura.
- Un blackout/SIGKILL nel piccolo intervallo tra i due rename può impedire al trap di ripristinare automaticamente; l’archivio indipendente consente il recupero manuale da Linux.
- L’HDMI della scheda madre non costituisce un percorso video verificato: iGPU disabilitata nel BIOS e output macOS non testato.

Il backup e il manifest sono preparati; il rollback non va considerato collaudato finché Linux e il ripristino reale non saranno verificati.

## Copia su supporto indipendente

Dopo la preparazione locale, lo script, il manifest e il README sono stati copiati nella directory nuova `/Volumes/Untitled 1/macOS-Tahoe-25G83-installer/OCBOOT-stage1-recovery-kit-20261027/`, sul supporto da 128 GB autorizzato per il progetto. I tre file copiati sono stati riletti e confrontati con gli originali SHA-256: 3/3. L'archivio `OCBOOT-stage1-success-20261027.tar` si trova nella directory superiore. Non è stata scritta OCBOOT e non è stato eseguito il ripristino su un dispositivo reale. Il precedente script config-only resta separato; per un ripristino completo usare il kit stage1 dopo la verifica del boot Linux.
