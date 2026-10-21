# Analisi dello spazio per la VM macOS

Data: 18/10/2026. Analisi in sola lettura; nessun file eliminato e nessun
servizio arrestato.

## Perimetro e misure

- Disco Linux: Samsung da 238,5 GiB; filesystem Btrfs da circa 238 GiB,
  circa 227 GiB occupati e 9,4 GiB liberi.
- Analizzati il sistema corrente, la home, `/var/cache`, `/var/log`,
  `/var/lib`, `/var/tmp`, `/root`, `/srv`, `/opt` e l'inventario Snapper.
  Le directory riservate rilevanti sono state controllate con privilegi
  amministrativi. Sono stati inventariati anche i file della home da almeno
  200 MiB.
- Il Lexar da 1 TB contiene Windows e non è montato: non è stato montato
  né analizzato. Liberare file lì non aumenterebbe lo spazio della partizione
  Linux.
- `/tmp`, `/dev/shm` e zram usano RAM: pulirli non libera spazio sull'SSD.
- Le dimensioni delle directory sono stime di `du`/blocchi allocati;
  Btrfs usa compressione e condivisione di extents. Non sono una garanzia
  dello spazio che `df` mostrerà dopo una cancellazione. Non sommare
  directory annidate né le dimensioni logiche di snapshot diversi.

## Prima scelta: dati ricreabili con impatto contenuto

| Candidato | Dimensione/stima recuperabile | Effetto e condizioni |
|---|---:|---|
| Vecchie versioni nella cache pacman, conservando 2 versioni per pacchetto | 3,07 GiB | Risultato di `paccache -d -k 2`; riduce i pacchetti disponibili offline per rollback |
| In alternativa, cache pacman conservando 1 versione per pacchetto | 6,84 GiB | Risultato di `paccache -d -k 1`; alternativa alla riga precedente, non sommarle |
| Artefatti di compilazione e download AUR in `~/.cache/yay` | circa 3,53 GiB | Preservare i file di ricetta: `msty-studio-bin/PKGBUILD` risulta modificato localmente |
| Cache Brave in `~/.cache/BraveSoftware` | 1,15 GiB | Chiudere Brave; conservare il profilo in `~/.config/BraveSoftware` |
| `~/.config/discord/Cache` | 0,51 GiB | Chiudere Discord; conservare account, configurazione e la versione attiva `app-1.0.162` |
| Vecchio log `~/.local/share/xorg/Xorg.0.log.old` | 0,36 GiB | Si perde un vecchio log diagnostico |
| Cache pip `~/.cache/pip` | 0,12 GiB | Nuovi download in caso di reinstallazione |
| Cache npm/npx `~/.npm` | circa 0,24 GiB | Ricreabile; preferire i comandi di gestione cache dello strumento |
| Cestino `~/.local/share/Trash` | 0,16 GiB | Verificare prima che non contenga file da recuperare |

La cache pacman completa occupa 14,97 GiB. Una simulazione con zero versioni
conservate individua 14,95 GiB di archivi eliminabili, ma per prudenza conviene
conservarne almeno una. Non ci sono candidati specifici per pacchetti non
più installati e non risultano pacchetti orfani da `pacman -Qdtq`.

In AUR circa 3,03 GiB appartengono a Msty: `src/`, `pkg/`, il `.deb`
scaricato e il `.pkg.tar.zst`. La copia installata è in `/opt/MstyStudio`.
Circa 0,39 GiB sono il checkout di compilazione di Electron32. Non eliminare
indiscriminatamente tutta la cache AUR, dato il PKGBUILD modificato.

Le voci di questa sezione permettono una stima nominale di circa **9–13 GiB**
recuperabili, a seconda delle versioni pacman conservate e delle cache scelte.

## Maggiore recupero: Distant Horizons, con perdita dei LOD

| Percorso | Dimensione rilevata | Conseguenza |
|---|---:|---|
| `~/.minecraft/Distant_Horizons_server_data/` | 25,00 GiB | Si perde la cache client dei paesaggi lontani, da ricreare/riscaricare |
| `~/minecraft/server/world/data/DistantHorizons.sqlite*` | circa 21,33 GiB | Si perdono i LOD server dell'Overworld |
| `~/minecraft/server/world/DIM-1/data/DistantHorizons.sqlite*` | circa 3,87 GiB | Si perdono i LOD server del Nether |
| `~/minecraft/server/world/DIM1/data/DistantHorizons.sqlite*` | circa 0,25 GiB | Si perdono i LOD server dell'End |

Totale client: 25,00 GiB. Totale server: 25,44 GiB. Combinato: **50,44 GiB**.
Non sono file dimostrati identici: client e server mantengono database distinti.

La documentazione ufficiale identifica questi percorsi come archivi LOD:
[FAQ Distant Horizons](https://gitlab.com/distant-horizons-team/distant-horizons/-/wikis/1-user-guide/1-frequently-asked-questions/1-general/General),
[server owners](https://gitlab.com/distant-horizons-team/distant-horizons/-/wikis/1-user-guide/1-frequently-asked-questions/5-server-owners/Server-Owners).
Ricostruire i LOD richiede tempo e i file possono tornare a crescere se si
mantengono le stesse impostazioni di generazione.

**Il server è attivo**: `lsof` conferma che Java tiene aperti database,
WAL e SHM delle tre dimensioni. Eventuali interventi vanno fatti dopo
l'arresto regolare del server e la chiusura del client. Non cancellare WAL/SHM
separatamente mentre il server funziona.

**Da conservare:** `world/region`, le altre cartelle `region`, `entities`,
`poi`, `playerdata`, `level.dat` e gli altri salvataggi. Il solo
`world/region` occupa 11,36 GiB e contiene il mondo vero, non una cache.

## Snapshot Btrfs

Ci sono **51 snapshot reali** di root, esclusa la voce corrente di Snapper:

| Data | Numero snapshot |
|---|---:|
| 29/05/2026 | 1 |
| 26/09/2026 | 8 |
| 30/09/2026 | 4 |
| 08/10/2026 | 18 |
| 12/10/2026 | 2 |
| 13/10/2026 | 2 |
| 18/10/2026 | 16 |

La configurazione mantiene fino a 50 snapshot normali e 15 importanti;
il numero 16 è marcato come installazione iniziale importante. 331/332
sono la coppia prima/dopo l'installazione degli strumenti VM.

I qgroup Btrfs sono disabilitati: Snapper non espone lo spazio esclusivo
di ciascuno snapshot. Un conteggio alternativo degli extents con
`btrfs filesystem du -s /.snapshots` è stato interrotto dopo oltre tre minuti
senza risultato: non è disponibile una misura affidabile del recupero fisico
degli snapshot. La rimozione selettiva dei vecchi snapshot è un candidato
utile, ma non si deve promettere uno spazio preciso sommando le dimensioni
delle loro directory. Conservare almeno un ripristino recente funzionante
e gestirli attraverso Snapper, senza cancellare a mano `/.snapshots`.

## Altre voci: solo se non servono

| Candidato | Dimensione | Valutazione |
|---|---:|---|
| `~/minecraft/backups/world-after-oom` | 2,82 GiB | Vecchio backup: cancellandolo si perde quel punto di recupero |
| `~/minecraft/backups/world-pre-optimization-2026-08-17-0021.tar.zst` | 2,59 GiB | Secondo backup; meglio spostare i backup se non ce ne sono altri |
| `~/Documenti/Eido/.venv` | 5,20 GiB | Ambiente Python ricreabile; esistono requirements.txt e pyproject.toml, ma si interrompe l'app finché non si reinstallano le dipendenze |
| Vecchie release 0.162.1 in `~/.codex/packages/{standalone,app-server-daemon}/releases/` | circa 0,84 GiB | I collegamenti current puntano a 0.163.0; il daemon osservato usa 0.163.0. Verificare altri processi prima di rimuovere le vecchie release |
| `~/.local/share/pnpm/store` | 1,36 GiB totale | Valutare solo la parte non referenziata con la pulizia prevista da pnpm |
| `~/llama.cpp` | 0,87 GiB | Checkout di sviluppo, non cache generica; prima controllare modifiche locali |
| Flutter/FVM e cache Dart | circa 2,29 GiB | Servono ai progetti Flutter; rimuovere solo se non usati |
| `~/.local/share/goverlay` | 2,15 GiB | Include mod e configurazioni dei giochi: non proporre la rimozione completa come semplice pulizia cache |
| `/opt/LM-Studio` | 2,10 GiB | Disinstallare il pacchetto solo se l'app non serve |
| `/opt/MstyStudio` | 1,03 GiB | Alternativa alla sola pulizia della sua cache di build, se l'app non serve |
| `/opt/wine-cachyos` | 0,76 GiB | Influisce su giochi/app Windows; rimozione tramite gestore pacchetti |
| `/opt/brave-origin-bin` | 0,42 GiB | Seconda installazione Brave; quello osservato in esecuzione è `/opt/brave-bin` |

Le dimensioni delle applicazioni installate non garantiscono il recupero
immediato: gli snapshot di root possono continuare a conservarne i dati.
Non cancellare manualmente file in `/opt` o `/usr`.

## Cosa conservare per questo progetto

- `InstallAssistant.pkg` di 25G83: **17,12 GiB**, installer necessario per la VM.
- `research/macos/`: **6,71 GiB**, binari e cache Apple usati per l'analisi ABI.
- ROCm in `/opt/rocm`: **9,18 GiB**, toolchain e librerie già usate per i
  test gfx1200; non trattarlo come una cache.
- Ghidra, JDK, REA, MacKernelSDK, firmware, dump hardware, sorgenti e patch.
- Il runtime attivo di Codex e i browser Playwright, usati dagli strumenti
  dell'assistente: non svuotare indiscriminatamente tutta `~/.cache`.

I log di sistema occupano solo circa 49 MiB; Flatpak circa 0,10 GiB.
Non sono obiettivi significativi. Docker non risulta avere un daemon attivo;
il controllo privilegiato di `/var/lib` non rileva un grande deposito Docker.

## Ordine consigliato

1. Cache pacman, artefatti AUR preservando le ricette modificate, cache delle
   app e vecchio log Xorg: circa 9–13 GiB nominali.
2. Se accettabile perdere i LOD, cache Distant Horizons client: altri 25 GiB.
3. Solo dopo arresto regolare e scelta esplicita, LOD del server: altri
   25,44 GiB. Le due voci insieme alle cache porterebbero lo spazio libero
   nominale a circa **69–73 GiB**, prima degli effetti di compressione,
   condivisione e altre scritture in corso.
4. Valutare la riduzione degli snapshot più vecchi per ulteriore margine.
5. Backup vecchi e ambiente Python Eido sono scelte aggiuntive, non necessarie
   da cancellare automaticamente.

La sola pulizia ordinaria delle cache non basta per una VM di sviluppo con
macOS, Xcode, build Mesa e snapshot. Anche 69–73 GiB liberi restano un margine
contenuto per questo uso; la dimensione virtuale di un disco qcow2 non è lo
spazio fisico già disponibile.
