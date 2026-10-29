# Correzioni cache e binding multisample — prova reale 29 ottobre

Stato: candidati locali, NON installati in modo persistente. Il bundle attivo rimane 25, SHA256 `ed45a207dd742f74c3d3b2dccc6d9a214d919a7dd1109a30618bb0c60fcb5c3e`. Le cinque prove temporanee hanno sempre ripristinato atomicamente il bundle originale e la voce Brave della lista APP. Nessuna modifica alla EFI o richiesta di riavvio.

## Modifiche implementate

- La cache della traduzione prova realmente creazione, scrittura e rimozione di un file. Se la cache Darwin è vietata dal processo, prova una sottocartella privata sotto Darwin temp/TemporaryItems, senza ampliare la sandbox. La pubblicazione atomica accetta un file privato del chiamante quando chmod è vietato, purché scrivibile dal proprietario e non scrivibile da gruppo/altri.
- Il binding di immagini sampled ora distingue immagini single-sample e multisample dalla reflection del vero SPIR-V. L'operando MS di OpTypeImage viene conservato e verificato rispetto alla texture collegata. Il vecchio rifiuto indiscriminato di texture2d_ms è rimosso. Non viene abbassato il numero di campioni dichiarato: quella prova non risolveva il problema ed è stata scartata.
- Il probe Brave può conservare stderr dal solo profilo isolato, e provare SkiaGraphite disattivato senza modificare il profilo dell'utente.

## Verifica

Compilazione x86_64 Objective-C con -Wall -Wextra -Werror, firma del bundle candidato, 134 controlli della traduzione e prova Seatbelt sui veri helper di file. La prova Seatbelt consente scritture e vieta chmod: la pubblicazione riesce e una cartella vietata viene rifiutata. Il checker reflection è stato eseguito su uno shader multisample realmente prodotto da Brave.

Nella prova reale il processo GPU di Brave sceglie la cartella temporanea e trova gli shader tradotti. Il precedente errore `cannot create the crash marker` sparisce. Dopo la correzione del binding sparisce anche l'errore `texture2d_ms ... not supported`. Questo NON completa l'accelerazione del browser: `vorssaint.com` finisce ancora in software, circa 7,5 fps nel test di 15 secondi. Nuove evidenze: pipeline rifiutata per blend Source1 (dual-source blending non attivato/implementato nel bridge), fallimento Graphite insertRecording e, nei processi successivi, allocazioni RADV da 9 MiB rifiutate. Disattivare SkiaGraphite non ha risolto. Il prossimo intervento deve verificare davvero il percorso dual-source del traduttore/SPIR-V e il budget/pool applicativo; aggiungere solo costanti Vulkan non prova un rendering corretto.

Log/JSON locali: `research/builds/macos-20261029/cache-candidate/trial2.log`, `trial3.log`, `trial4.log`, `trial5.log` e i rispettivi JSON. I log provengono da profili temporanei, non dalla navigazione privata dell'utente.

## Altri componenti richiesti

- Audio posteriore: scaricato e verificato l'archivio ufficiale VoodooHDA v3.7.1-alpha (commit d9e642d; SHA256 1182eb3039268a36525d6eb64d906f0e03cba50a6246d2b0557aaf20fb5b0fa4), candidata firmata con matching solo 1022:15e3/1462:ee57 e senza personality HDMI. La release incorpora IOAudioFamily e non ha dipendenza esterna da essa. Tuttavia esporta classi IOAudioEngine già presenti nella IOAudioFamily 740.1 attualmente caricata: coesistenza non verificata. Non installare questa alpha come soluzione completa. Rimane disponibile anche la precedente candidata 3.6.8, il cui percorso AuxKC non è risolto.
- Bluetooth: sul sistema sono effettivamente caricati BluetoothWCN7850 1.0.0, BlueToolFixup 2.7.3, IntelBTPatcher 2.5.0; il controller ha un indirizzo non nullo ed è acceso. Questo non dimostra pairing HID o AirDrop. QwzWifi e QwzAirport sono caricati; il port selezionato documenta limiti AWDL, quindi non si può promettere AirDrop con un semplice fix Bluetooth.
- Monitor: resta 120 Hz; nessun cambio fisico a 60 Hz implementato. Sensori aggiuntivi e spegnimento non hanno nuove modifiche in questo candidato.

Fonti: [profilo sandbox GPU Chromium](https://chromium.googlesource.com/chromium/src/+/main/sandbox/policy/mac/gpu.sb), [VoodooHDA upstream](https://github.com/CloverHackyColor/VoodooHDA/blob/main/readme.md), [release audio](https://github.com/CloverHackyColor/VoodooHDA/releases/tag/v3.7.1-alpha). Il comportamento dei candidati su questa macchina è stabilito dai log locali, non dalle sole dichiarazioni upstream.
