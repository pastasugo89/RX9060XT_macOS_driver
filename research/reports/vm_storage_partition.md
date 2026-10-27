# Volume Btrfs per la VM sul Lexar

## Aggiornamento 26/10/2026 — layout per macOS

Su autorizzazione dell’utente, la vecchia p7 da 200 GiB che conteneva le VM è stata sostituita. Il layout corrente sul
Lexar è p7 Btrfs da 50 GiB per l’archivio di lavoro preservato e p8 da 150 GiB con tipo GPT Apple APFS, ancora senza
filesystem. p1–p6 sono state mantenute dalla procedura approvata. La prima esecuzione ha terminato dopo aver scritto la
GPT e formattato p7, lasciandola vuota; non è stata ripetuta. La procedura restore-only ha ripristinato l’archivio e
aggiornato la sola UUID della voce `/mnt/vm` in fstab. `tar --compare` è passato per l’archivio principale e per quello
GRUB protetto; i checksum approvati corrispondono. Il log è
`research/ext/vm-preservation-20261026/lexar-restore-20261026T161046Z/progress.jsonl`.

Il fix accessibilità successivo ha portato a 0755 solo 51 directory genitore implicite create come root:root 0700;
nessun file, chiave o directory esplicita dell’archivio è stato modificato. Il manifest di 445 file passa come
`pastasugo89`; log: `research/ext/vm-preservation-20261026/lexar-restore-20261026T161046Z/fix-parent-permissions.jsonl`.

La p8 non è stata formattata da Linux: la formattazione APFS e l’installazione restano da fare, dopo aver identificato
in Recovery la partizione da 150 GiB sul Lexar. Vedi `research/reports/recovery_install_readonly_20261026.md`.

Stato storico del 20/10/2026, dopo la riduzione di Windows eseguita
dall'utente; il layout iniziale qui sotto è stato superato dall'aggiornamento
26/10 in cima al documento.

## Risultato iniziale (20/10/2026)

| Voce | Valore |
|---|---|
| Disco | Lexar SSD EQ790 1TB, `/dev/nvme1n1` |
| Seriale verificato prima delle operazioni | `QBA343R000865P220C` |
| Nuova partizione | `/dev/nvme1n1p7` |
| Primo settore, da 512 byte | `1527257088` |
| Ultimo settore incluso | `1946687487` |
| Dimensione | `419430400` settori, `214748364800` byte, **200 GiB** |
| Filesystem / etichetta | Btrfs / `macos-vm` |
| UUID filesystem | `be2a9624-d2c1-4778-ac99-fcf9258d3328` |
| Mount | `/mnt/vm` |
| Spazio disponibile iniziale indicato da df | circa **198 GiB** |

Directory già scrivibili dall'utente `pastasugo89`:

- `/mnt/vm/images`: dischi virtuali;
- `/mnt/vm/installers`: supporti d'installazione;
- `/mnt/vm/builds`: build;
- `/mnt/vm/backups`: backup della VM.

Il punto di mount sottostante è root-owned: in assenza del volume l'utente
non può scriverci per errore come se fosse spazio sul Samsung. Non è stato
ancora configurato alcun servizio libvirt o launcher di VM per usarlo.

## Precauzioni e controlli eseguiti

1. Verificati il seriale del disco, GUID GPT e intervalli di tutte le sei
   partizioni originali. Lo spazio disponibile era un intervallo non allocato
   da circa 200 GiB tra Windows p3 e ripristino p4.
2. Salvati backup GPT e fstab **sul Samsung Linux, non sul Lexar**.
3. Eseguito `sfdisk --append --no-act` e verificato che aggiungesse soltanto p7.
4. Aggiunta p7 con cancellazione automatica delle firme disabilitata. Nessun
   uso di `--force`, spostamento o ridimensionamento delle partizioni esistenti.
5. Verificata la geometria kernel di p7 e l'assenza di firme prima di
   `mkfs.btrfs --nodiscard --label macos-vm /dev/nvme1n1p7`, senza `--force`.
6. Confrontati i sei record GPT prima/dopo: identici start, size, tipo,
   UUID, nomi e attributi; unica voce aggiunta p7. GUID del disco invariato.
7. Confrontati prima/dopo gli SHA-256 del primo e ultimo MiB di ciascuna
   partizione originale: invariati dopo creazione, formattazione e montaggio.
   È un controllo dei confini, non una verifica completa del contenuto NTFS.
8. `sfdisk --verify` termina senza errori. Il numero di partizione 7 non
   segue l'ordine fisico sul disco: è previsto, per mantenere i numeri p1–p6.
9. Aggiunta una sola voce a `/etc/fstab`, con UUID e `nofail`; `findmnt
   --verify --verbose` termina senza errori né avvisi. Verificata la generazione
   dell'unità systemd `mnt-vm.mount`.
10. Test di scrittura, fsync e rilettura nelle quattro directory come utente
    normale, con file temporanei poi rimossi. Verificato che `/mnt/vm` sia
    un filesystem diverso da `/`.

Windows e le sue partizioni EFI/di ripristino non sono stati montati.
L'avvio di Windows non è stato testato durante questa sessione.

## Backup e configurazione

Backup locali esclusi da git, accessibili all'utente:

`research/ext/storage-backups/lexar-before-macosvm-20261020/`

Contengono JSON e dump testuale della GPT originale, primo/ultimo MiB del
disco, hash dei confini delle partizioni, risultato della simulazione e
delle operazioni, fstab prima/dopo e copia dello script eseguito.

Voce aggiunta a `/etc/fstab`:

```fstab
UUID=be2a9624-d2c1-4778-ac99-fcf9258d3328 /mnt/vm btrfs defaults,noatime,compress=zstd:1,nofail,x-systemd.device-timeout=10s 0 0
```

La partizione Linux originale resta sul Samsung, separata da questo volume.
Nessun installer, sorgente o altro file del progetto è stato trasferito.
Alla data del 20/10, la VM macOS era ancora da creare e lo spazio era
disponibile. La VM è stata poi installata e, il 26/10, dismessa su
autorizzazione dell'utente per predisporre il target macOS bare metal.
