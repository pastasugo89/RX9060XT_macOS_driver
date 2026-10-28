# Brave, CPU, sensori e audio analogico: verifica del 28 ottobre 2026

## Stato del sistema e del candidato

Il sistema attivo conserva Metal bundle 24, Navi48Bringup 0.0.664,
Navi48Accel 0.0.7 e RDNA4FB 0.0.8. In questa verifica non sono stati
installati/caricati driver, ricostruite le cache di avvio, modificati EFI,
refresh rate o impostazioni audio. Nessun riavvio richiesto.

Le acquisizioni binarie e i log completi rimangono nella directory locale
ignorata `research/builds/macos-20261028/`; non sono sorgenti redistribuibili.

## Brave e capacità del driver

Riproduzione con profilo Brave temporaneo separato, stesso eseguibile installato,
`https://vorssaint.com`, nessuna forzatura GPU o disabilitazione del sandbox.
DevTools `SystemInfo.getInfo` conferma `gpu_compositing=disabled_software`,
`rasterization=disabled_software`, `webgl=disabled_off`, `webgpu=disabled_off`.
Il profilo di prova è stato chiuso tramite il proprio endpoint Browser.close;
il browser personale è rimasto aperto.

Lo stderr del processo GPU mostra il rifiuto N48N `0xe00002c7`, seguito dal
fallimento EGL. Al momento della prova i quattro client nativi presenti erano
WindowServer, WallpaperSequoia, Warp (`stable`) e VTDecoderXPCServ. Il ring del
kernel riporta ExclusiveAccess: tutti e quattro gli slot occupati. Questo prova
la saturazione attuale; non dimostra che ogni lentezza abbia questa sola causa.

La disassemblazione statica di IOService nel BootKC 25G83 mostra che la variante
newUserClient a cinque argomenti chiama lo slot 239, ma dopo un errore tenta il
fallback IOUserClientClass e può restituire Unsupported. Il rifiuto per capacità
può quindi apparire al chiamante come assenza del supporto. La variante a quattro
argomenti dell'acceleratore è presente; non mancava l'intero instradamento.

Candidato Navi48Accel 0.0.8: override dello slot 238 per N48N, inoltro del risultato
della variante a quattro argomenti senza tradurlo; per gli altri tipi restano il
wrapper IOService e le properties originali. Kill switch mantenuto su entrambi
gli ingressi. Nessun aumento di slot o modifica di VMID, risorse o scheduler.

Validazione: 1.697 controlli host ASan/UBSan; build x86_64 e firma ad hoc;
2.720 slot vtable confrontati, 882 import risolti; layout host e 70 controlli
negativi su DisplayPipe/Framebuffer passati. Due mutazioni mirate sono rilevate
quando si perde la propagazione dell'errore o il gate dello slot 238.
Il test kernel dal vivo è ancora da eseguire. Questo candidato corregge la
propagazione dell'errore, **non risolve da solo la saturazione**. Portare il numero
di sessioni oltre quattro richiede anche una revisione del protocollo statistiche
(le pagine 4 e 5 hanno già significati globali) e dei limiti per sessione.

## Reverse engineering CPU e REA

Installata la skill ufficiale `morluto/rea`, commit
`8f9af920efb39d22b5a915605403b67a1005bc0e`, percorso
`~/.codex/skills/reverse-engineer-anything`. La skill non installa engine né
registra automaticamente un server MCP. L'analisi eseguita usa LLVM locale,
non una decompilazione REA. [Progetto e istruzioni](https://github.com/morluto/rea).

`tools/baremetal/extract-kernel-function.py` estrae intervalli limitati da simboli
del BootKC in oggetti Mach-O di analisi non eseguibili e registra SHA-256 prima e
dopo. Verificato su cpuid_set_info, xcpm_bootstrap, xcpm_init, machine_idle,
tsc_init e sulle due varianti newUserClient. Non modifica il kernel.

Nel config EFI effettivo Cpuid1Data e Cpuid1Mask sono vuoti: non c'è una maschera
CPUID Intel da rimuovere. Le patch AMD del kernel restano necessarie per percorsi
GenuineIntel, identificazione famiglia e MSR; eliminare queste patch e aggiungere
un kext non sostituisce automaticamente il supporto AMD nel bootstrap XNU.
Il CPPC attuale rimane separato dalla futura raccolta dei sensori.

## Sensori: baseline misurata e integrazione da realizzare

Verifica non privilegiata delle sole chiavi sensore con il tool ufficiale
VirtualSMC, sorgente fissato a `b5c62c2311540c529c00996d0d9cec33f8e571c9`.
Nessun comando di scrittura, discovery di chiavi riservate o controllo ventole.
TC0D/TC0E/TC0F/TC0P/TC0C, TG0D/TG0P/TG0H/TG0M, TA0P/TN0P e PCPR/PSTR
restituiscono zero byte, non temperature di 0 °C. FNum restituisce 0; F0Ac e
F1Ac non hanno dati. Il ritorno processo 0 del tool upstream non basta a dire
che un sensore esiste: vanno verificati dimensione e tipo del dato.

- CPU Ryzen 7700: raccoglitore termico per family 19h/model 61h, letture SMN
  serializzate e rispettive unità/validità; esportazione tramite VirtualSMC.
  Il driver [Linux k10temp](https://github.com/torvalds/linux/blob/master/drivers/hwmon/k10temp.c)
  documenta il registro termico Zen e distingue i valori CCD validi. Le
  temperature CCD non equivalgono a sensori indipendenti per ciascun core.
- GPU: riutilizzare il campionamento THM già presente nel watchdog del driver;
  pubblicare valore, validità e freschezza senza aggiungere polling MMIO da un
  secondo driver. Edge, memoria, potenza e RPM da SMU restano subordinati alla
  verifica del layout; vedere `smu_metrics_if33_audit.md`.
- Scheda madre/ventole: identificare il Super I/O effettivo prima di attivare un
  plugin e mappare ingressi, fattori di scala e tachimetri. Il nome della scheda
  madre, da solo, non identifica il chip o la disposizione dei sensori.

[VirtualSMC](https://github.com/acidanthera/VirtualSMC) offre l'API plugin;
[SMCAMDProcessor](https://github.com/trulyspinach/SMCAMDProcessor) separa il plugin
SMC dal raccoglitore AMDRyzenCPUPowerManagement, da cui dipende. Installare soltanto
il plugin non produce letture; installare l'intero driver senza isolarne le
scritture energetiche può interferire con il CPPC attuale. Nessuno dei due è
stato aggiunto all'EFI durante questa verifica. **Esportazione sensori non ancora
implementata o validata dal vivo.**

## Jack audio posteriore

L'utente conferma casse collegate al jack posteriore. CoreAudio enumera solo il
dongle USB Corsair; nessun device analogico. AppleHDAController e IOHDACodecDevice
non sono presenti. Il controller reale è AZAL `1022:15e3`, subsystem
`1462:ee57`, sotto GP17, non un HDEF già configurato. Non ci sono AppleALC,
VoodooHDA o proprietà audio nel config attivo.

[MSI dichiara ALC897](https://tw.msi.com/Motherboard/B840-GAMING-PLUS-WIFI/Specification).
La descrizione SMBIOS `Realtek ALC1220` nel vecchio lspci non è una risposta ai
verb del codec e non viene usata per scegliere un layout. L'ID codec effettivo
rimane da leggere. AppleHDA è assente da questa installazione, in accordo con
la [nota ufficiale AppleALC per Tahoe](https://github.com/acidanthera/AppleALC).
Aggiungere solo alcid/AppleALC non risolve la dipendenza mancante.

Preparato `audio-trial-v2` con il binario ufficiale
[VoodooHDA Release368](https://github.com/CloverHackyColor/VoodooHDA/releases/tag/Release368),
archivio SHA-256 verificato rispetto al digest GitHub
`9aaa01b245f4827b2de5edfdc028700b9bc8823f03bfb1daf280b8571f88adb0`.
Il tool `tools/baremetal/navi44-audio/prepare.py` ricrea la prova in staging:
unica personality per controller/subsystem reali, nessuna personality HDMI GPU,
nessuna rinomina ACPI, boost 0 e PCM iniziale 75. Firma ad hoc e permessi del bundle verificati. `kmutil libraries` risolve gli
import del candidato nelle collezioni effettive 25G83, inclusa IOAudioFamily 740.1;
questo non è una verifica della compatibilità completa del driver.
Non imposta pin del codec a tentativi e non seleziona automaticamente un'uscita.

È un candidato **non installato e non testato nel kernel**, che richiede una
prova AuxKC coordinata: questa versione dipende da IOAudioFamily, quindi non va
semplicemente copiata nell'EFI. La variante upstream 3.7 incorpora IOAudioFamily
ma non è lo stesso binario della release 3.6.8 qui verificata. I tentativi di costruire una AuxKC di sola prova, anche come root e con i permessi
del bundle corretti, con copie locali di BootKC e
SystemKC e output nel workspace, terminano con codice 31 (`No binaries or codeless
kexts were provided`). Non è una cache installabile verificata. La presenza di
IOAudioFamily nella SystemKC è stata verificata con kmutil inspect; non basta a
superare il problema di costruzione. Nessuna collezione di sistema modificata.
Non sono stati
eseguiti installer di terzi, comandi di caricamento o modifiche SIP. Per dichiarare
il fix servono enumerazione del codec e del line-out, playback analogico udibile,
controllo volume/mute e una prova dopo riavvio/sospensione.

## Frequenza monitor e prossima prova

Il monitor resta fisicamente a 120 Hz. Il framebuffer corrente espone una sola
modalità e setDisplayMode non programma un cambio fisico. Modificare il numero
advertised a 60 non costituirebbe la prova A/B richiesta. L'EDID contiene una
modalità 60 Hz, ma la programmazione DCN Navi44 completa con ripristino resta da
implementare. Nessun fix per la banda nera è dichiarato verificato.
