# Percorso abbreviato verso Metal e desktop — 27 ottobre 2026

L'utente chiede di evitare un boot per ogni stage. Stage1 bare metal è passato. P0 nella vecchia VM con RX 9060 XT in passthrough ha superato un set limitato headless Metal (quad/triangolo esatti, compute, hot-swap), ma P2 con WindowServer non ha prodotto command buffer o frame. Questi due risultati motivano un tentativo raggruppato stage17 + Metal headless dopo preflight concreto, seguito dalla risoluzione del percorso display. Non si può prevedere che funzioni sul bare metal.

## Confronto essenziale

P0 aveva `navi48-stage=17 navi48-interrupts=0 navi48-native=1 navi48-metal=1 navi48-aux=1`, un display virtuale separato dalla RX, e includeva `Navi48Bringup`, `Navi48Accel`, bundle `Navi48Metal`, `n48nub`, `mtlprobe` e supporto traduzione/cache. Nel bare metal la RX è display principale, la sessione corrente è stage1, non c'è GPU VM separata, la lettura termica è non validata e l'attuale kext storico non ha watchdog. Un errore della RX potrebbe quindi togliere il display o riavviare. Non copiare la ricetta VM alla cieca: i suoi script richiedono QEMU/SSH e il watchdog QMP host, qui assenti.

IORegistry live del 27/10 mostra sulla RX `1002:7590` la prima `IODeviceMemory` di 268435456 byte (256 MiB), stessa dimensione BAR0 documentata nel P0 VM; ciò non dimostra che geometria, posizionamento framebuffer o mapping possano essere gestiti senza rischio in bare metal. ReBAR e il comportamento dell'apertura reale richiedono preflight specifico. Un test stage17 esegue anche compute e accessi VRAM/firmware; non è una sola prova passiva.

## Preparazione

Compilati separatamente `research/builds/macos-20261027/desktop-prep/fast-metal-tools/n48nub` e `mtlprobe` per x86_64. `mtlprobe` ha 5 warning SDK/deprecazione; nessuno dei tool è stato eseguito. Build RDNA4FB, bundle Metal e kext aux già esistono in staging; la variante PSP IOWorkLoop con gate termico è sperimentale e non ha prova runtime né lettura sensore validata. Il gate PSP controlla solo l'ingresso e non interrompe una PSP già in corso.

Le EFI vecchia e stage1 riuscita hanno backup indipendente sulla chiavetta 128 GB; il ripristino Linux non è stato ancora provato in questa sessione. Per un tentativo accelerato serve un'immagine EFI e kit bare-metal verificati, un modo realmente praticabile di recuperare il computer se la RX principale perde video, e decidere come valutare/limitare il rischio termico senza inventare temperature sicure. Non è necessario imporre un reboot per ciascun numero intermedio se questi presupposti sono soddisfatti, ma non è corretto presentare il desktop P2 come già risolto.

Nessuna modifica EFI o installazione bundle è stata fatta; nessun test GPU è stato lanciato durante questa preparazione.

## Kit bozza assemblato

È stata assemblata in `research/ext/navi44-fast-metal-draft-20261027/` una bozza locale con EFI stage17/native/Metal, watchdog IOWorkLoop sperimentale `351afbe9…`, `Navi48Accel`, bundle Metal portabile, traduttore/validatore preservati, script autotranslate e i tool x86_64. Manifest 124/124, ocvalidate e codesign passati; librerie aux esaminate con kmutil. Il kit non è pronto per boot o distribuzione: non è stata verificata sul bare metal la sua sequenza di caricamento, l'effetto di `-amd_no_dgpu_accel`, il servizio traduttore, il sensore o il recupero video. La bozza non è stata copiata su OCBOOT; l'attuale stage1 resta avviabile.

## Log stage1 acquisito senza riavvio

Compilato `navi48test` x86_64 e usato il solo comando di lettura `log` con il driver stage1 attivo; non è stato chiamato alcun comando GPU di scrittura o compute. Il buffer interno recuperato in `research/hw_dump/macos_stage1_run_20261027/navi48-driver-ring.txt` (SHA-256 `ed167124f05d9b70f6d60e24d287ea5636b96579a0b12257c79b5a3eee95ec71`) conferma che BAR0 PCI, IOPCIFamily e ReBAR coincidono a 256 MiB, PSP bootloader READY ma SOS non avviato (come previsto per stage1) e stage1 completato. `dcn ... no mapped BAR5 in the device context` indica che i verbi via deviceContext non hanno necessariamente accesso alla mappatura stage1: non interpretare una lettura da essi come termometria valida senza prova. Questo migliora la diagnosi ma non verifica stage17.

## Allineamento P0 e situazione presente

La bozza combina build diverse dal P0: main sperimentale `351af…`, aux `faad…` e bundle portabile ricompilato. Recuperato dal tar di preservazione l'aux P0 `research/builds/macos-20261027/desktop-prep/p0-reference-kext/Navi48Accel.kext`, hash binario `4d5e257d880ed5fe076a933159ee6ef4d4a8d5bc93f067e3e7cf07512a7d3b8c`, firma verificata. Bundle di riferimento P0 `research/builds/macos-20261027/userspace/reference/Navi48Metal.bundle`, hash del binario `7edf8e319fe5408d5cb6220ee5bd571420200cd6128805ad345a50fb86aeed2d`; bring-up storico `d186c77…` è già conservato ed è il binario stage1. Il recupero aiuta a distinguere regressioni, ma non dimostra funzionamento bare metal; il main storico non possiede watchdog.

P0 usava `csr-active-config=3`, mentre il draft conserva `csr-active-config=0` della EFI attuale. L'impatto sul caricamento dell'aux e sul bundle in questa installazione non è stato determinato; nessuna modifica SIP è stata eseguita. Corretto nel draft il commento di configurazione che erroneamente chiamava storico il nuovo binario. `ocvalidate` e manifest ripetuti con successo.

Una copia mirata dei componenti P0 originali (15 file: aux, bundle, daemon e tool) è stata estratta dall'archivio di preservazione in `research/ext/navi44-fast-metal-p0-reference-20261027/`, con confronto 15/15 contro il manifest conservato e verifica firma aux. Sono file di riferimento, non distribuiti o eseguiti; l'assenza della cache runtime VM e la mancanza di watchdog nel kext principale storico rimangono limiti.

## Boot arg di disabilitazione AMD: prima identificazione statica

Nel `SystemKernelExtensions.kc` x86_64 25G83 estratto localmente, sei occorrenze esatte di `-amd_no_dgpu_accel` ricadono nei segmenti `__TEXT` delle immagini fileset Apple `com.apple.kext.AMDRadeonX4000`, `AMDRadeonX5000` e `AMDRadeonX6000`, due per immagine. Accanto all'occorrenza X6000 è presente il messaggio che associa il flag alla disattivazione dell'accelerazione del dispositivo. Questa è un'ispezione statica della stringa e delle sezioni Mach-O, non una prova REA delle diramazioni o una prova che il flag blocchi o non blocchi il nostro bundle custom. Non rimuoverlo o dichiararlo compatibile sulla sola base di questa evidenza; verificare il percorso di caricamento in modo mirato.

## Preflight termico con privilegi

Eseguito `sudo powermetrics --samplers smc -n 1 -i 1000` sul boot stage1 attivo, con singolo campione. Exit 0 ma vari `Invalid key detected!` e sezione `SMC sensors` vuota: nessuna temperatura CPU o GPU ottenuta, nessuna telemetria valida da attribuire alla RX. Questo controllo non prova né smentisce le protezioni firmware. Il sensore THM e il watchdog sperimentale restano non collaudati.

## Preflight verso un unico boot stage17

Candidata aggiornata di solo staging `research/ext/navi44-stage17-preflight-20261027/`: bring-up con watchdog IOWorkLoop e guardia console `5bec2414…`, stage17/native/Metal, IRQ=0; aux P0 presente ma disabilitato nella EFI perché il test P0 lo caricava dinamicamente. La config omette `-amd_no_dgpu_accel` e imposta CSR 0x03, come la prova VM, ma questo modifica le protezioni SIP e resta non verificato su questa macchina. La guardia console ora rifiuta geometria vuota/incoerente, range fuori limite o parziale; non garantisce che la descrizione firmware sia il vero scanout corrente. Console fuori BAR0 è rifiutata di default, e il bypass non è una verifica; non abilitarlo a intuito. Manifest, firma, ocvalidate e kmutil passano.

Controllo `sudo powermetrics --samplers smc -n 1 -i 1000` sul Mac: nessun sensore pubblicato e diversi `Invalid key detected!`; nessun valore CPU/GPU è stato ottenuto. Resta necessario confrontare o comunque classificare la telemetria del watchdog senza chiamarla convalidata. Una fase PSP già partita non è interrompibile dal gate.

Il bundle Metal P0 e i due tool hanno uno script di installazione/disinstallazione con dry-run e test su root fittizia in `research/ext/navi44-userspace-p0-stage-20261027/`. Il deploy da questa sessione è stato rifiutato da `sudo` prima di eseguire lo script perché uid 501 non viene risolto (Directory Services e DiskManagement non raggiungibili da questa sessione). L'utente ha riferito che Terminale locale risolve correttamente l'account; è stato richiesto di eseguire il solo comando locale per bundle e tool. Alla data di questa annotazione l'esito non è ancora disponibile; non si assuma installato.

OCBOOT è tuttora la versione stage1 funzionante: nessuna EFI stage17 è stata scritta. Prima del reboot stage17 rimangono irrisolti caricamento aux/consenso, interazione CSR/flag, assenza di video alternativo effettivamente verificato e recupero Linux non collaudato. Non si deve dichiarare che il prossimo reboot attivi l'accelerazione desktop: il P2 VM rimane con zero frame.

## Tentativo bundle e rootless

Su richiesta dell'utente, avviato dal Terminale locale lo script per installare soltanto bundle P0 e tool; il primo `ditto` ha risposto `Operation not permitted` e il rollback automatico ha rimosso i path creati. Verificato che bundle, due tool e receipt sono assenti. `/Library/GPUBundles` live porta il flag `restricted` e attributo `com.apple.rootless=KernelExtensionManagement`; SIP è enabled e `csr-active-config` è zero. È un blocco di protezione rootless, non una password sbagliata. Tentativo di installazione suggerito troppo presto; non ripeterlo a SIP invariato.

La P0 VM usava csr 0x03 e il bundle venne installato con successo. I bit 0 e 1 XNU sono `CSR_ALLOW_UNTRUSTED_KEXTS` e `CSR_ALLOW_UNRESTRICTED_FS` (sorgente primaria <https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/csr.h>). Candidata stage17 in staging già imposta 0x03: si può valutare un singolo reboot stage17/CSR03, poi installare bundle e caricare aux dopo l'avvio, evitando un riavvio separato solo per SIP. La scrittura su questo specifico Tahoe bare metal con CSR03 non è ancora verificata; inoltre la stage17 attiverebbe firmware/compute e il suo watchdog e recupero video restano non convalidati. L'EFI operativa non è stata modificata. Non dichiarare che CSR03 garantisca il successo, né aggirare a intuito la protezione alterando percorsi o permessi di sistema.
