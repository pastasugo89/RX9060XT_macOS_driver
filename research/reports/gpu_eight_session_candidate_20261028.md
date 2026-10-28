# Profilo sperimentale a otto sessioni GPU

Il sistema osservato aveva quattro sessioni occupate (WindowServer, Wallpaper,
Warp e VTDecoder), e Brave ha ripiegato sul compositing software. La modifica
consente un profilo di build opt-in `NATIVE_SESSIONS=8`, mantenendo quattro
sessioni come valore predefinito. Le sessioni aggiuntive utilizzano VMID 12–15,
fuori dalla maschera MES 1–7 impostata dal driver. Questo è un controllo statico,
non una prova che i VMID aggiuntivi funzionino sull'hardware.

Le pagine statistiche storiche 0–3, globale 4 e G5 5 mantengono il significato;
le sessioni 4–7 sono esposte su 6–9. Gli slot DEAD e la riserva per WindowServer
restano applicati a tutti gli slot. Ogni slot aggiuntivo richiede una finestra
GART, un contesto VMID e allocazioni proprie; i limiti restano condivisi. Il tool utente aggiornato distingue le pagine 6–9 dalla globale e da G5
usando la pagina richiesta, non il numero dello slot restituito.

Test host con ASan/UBSan: test G2 originale 250 verifiche e test dedicato al
profilo a otto sessioni superati. Build completa x86_64 su copia del sorgente di bring-up effettivo con profilo 8,
firma verificata. Il binario è sperimentale e non costituisce una prova hardware.
I 28 indirizzi CONTEXT relativi ai VMID 12–15 coincidono con gli offset GC 12.0
negli header Linux per control, base, start ed end.

Da completare: audit delle risorse VMID 12–15 e delle finestre GART,
verifica del profilo completo rispetto ai componenti installati, test concorrenti e isolamento dei contesti su hardware,
integrazione con guardia di avvio e rollback. Non installato; non riavviare per
questo candidato. VideoToolbox e decodifica video richiedono valutazione separata.


## Diagnosi video iniziale

`VTIsHardwareDecodeSupported` chiamato il 28 ottobre dal processo di test
non autorizzato e con quattro sessioni occupate ha restituito false per H.264,
HEVC, VP9 e AV1. Il processo ha contemporaneamente ricevuto il rifiuto N48N.
Il risultato è specifico alla configurazione e al processo al momento del test:
non prova che l'hardware non possa decodificare né che aumentare gli slot attivi
una pipeline VideoToolbox. Dopo l'avvio del candidato occorre ripetere il test
e misurare codec, frame persi, CPU e decoder durante la riproduzione YouTube.

## Ulteriore verifica VCN

Il solo aumento delle sessioni non implementa un decoder hardware. Il codice
corrente dichiara esplicitamente che le doorbell VCN/VPE non sono portate
(`amd/nbif_v6_3_1.h`); riferimenti VCN nel percorso Apple non provano che il
percorso nativo le inizializzi o registri un decoder. AMD/Linux descrive VCN
come motore separato di codifica/decodifica, collegato a MMHUB
([documentazione del driver AMDGPU](https://docs.kernel.org/gpu/amdgpu/driver-core.html)).
La disponibilità di un decoder VideoToolbox dipende anche dal formato e dalle
risorse ([Apple: richiesta decodifica hardware](https://developer.apple.com/documentation/videotoolbox/kvtvideodecoderspecification_requirehardwareacceleratedvideodecoder)).
Un risultato negativo attuale non autorizza ad annunciare che YouTube userà VCN
solo perché Brave ottiene un contesto Metal.

Il candidato riproducibile `build-eight-sessions.py` controlla che il binario
base nella EFI corrente corrisponda a quello della build sorgente 0.0.664,
quindi costruisce separatamente una 0.0.665 con otto sessioni e verifica la
firma. Questo controllo identifica il binario base ma non prova da solo che
ogni file sorgente locale riproduca senza differenze quel binario. Il candidato
rimane privo di installazione e richiede verifiche ABI, integrazione e rollback.
