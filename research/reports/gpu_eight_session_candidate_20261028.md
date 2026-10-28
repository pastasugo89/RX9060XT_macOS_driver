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
GART, un contesto VMID e allocazioni proprie; i limiti restano condivisi. Il tool
utente attuale potrebbe non consentire ancora di richiedere le pagine 6–9.

Test host con ASan/UBSan: test G2 originale 250 verifiche e test dedicato al
profilo a otto sessioni superati. Compilato `native_s1c.cpp` per x86_64 con
profilo 8; non costituisce una build completa del kext né una prova hardware.

Da completare: audit di tutti gli indirizzi e delle risorse VMID 12–15 e delle
finestre GART, build completa coerente con i componenti installati, aggiornamento
del tool diagnostico, test concorrenti e isolamento dei contesti su hardware,
integrazione con guardia di avvio e rollback. Non installato; non riavviare per
questo candidato. VideoToolbox e decodifica video richiedono valutazione separata.
