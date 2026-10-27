# Telemetria termica macOS — RX 9060 XT / Ryzen 7 7700

Data acquisizione: 27 ottobre 2026. Verifiche effettuate sul macOS bare metal con comandi in sola lettura e senza `sudo`. Il risultato attuale è **UNKNOWN** per temperatura CPU, temperatura RX 9060 XT e stato della protezione termica.

## Evidenza host

| Fonte | Risultato osservato | Interpretazione |
|---|---|---|
| `powermetrics --samplers smc -n 1 -i 1000` | Exit 1: `powermetrics must be invoked as the superuser` | Nessuna lettura ottenuta. Non è stato tentato `sudo`. |
| `ioreg -r -c IOHWSensor -l -w0` | Zero nodi `IOHWSensor` nella risposta della classe | Nessun sensore termico pubblicato tramite questa classe. |
| `ioreg -r -c AppleSMC -l -w0` | Classe/client AppleSMC presenti, nessuna chiave temperatura nel filtro | La presenza di AppleSMC non è una lettura termica. |
| `system_profiler SPDisplaysDataType -detailLevel mini` | GPU AMD, PCI `1002:7590`, VRAM riportata 14 MB | Identificazione/enumerazione del display; non prova accelerazione né misura temperature. |
| `kmutil showloaded` | Lilu 1.7.3, VirtualSMC 1.3.9, Apple AMDSupport 7.0.1 | Non risultano SMCAMDProcessor, AMDRyzenCPUPowerManagement, SMCProcessor, SMCSuperIO o kext Cobalt/Navi. AMDSupport non dimostra un sensore o accelerazione. |
| `pmset -g therm` | Nessun livello di thermal warning, performance warning o CPU power registrato | Stato termico qualitativo assente; non è una temperatura né una conferma di protezione. |
| `sysctl machdep.xcpm.cpu_thermal_level machdep.xcpm.gpu_thermal_level` | CPU 0, GPU 0 | Valori XCPM senza misura in °C. Lo zero non prova che il sistema sia fresco o sicuro. |

Il JSON filtrato della verifica live è [monitor-live.jsonl](../hw_dump/macos_thermal_audit_20261027/monitor-live.jsonl). Le acquisizioni sorgenti precedenti (comandi e codici di uscita) sono nella stessa directory. Nessun output grezzo con indirizzi IORegistry, UUID o seriali viene incluso nel report.

## Monitor preparato

Il monitor manuale è in [macos_thermal_watch.py](../../cobalt64/tools/thermal-readonly/macos_thermal_watch.py); istruzioni in [README.md](../../cobalt64/tools/thermal-readonly/README.md). Chiama solo comandi macOS in sola lettura, non privilegiati e fissati nel codice; rifiuta l'esecuzione come root (exit 77). Non accede a MMIO, non legge registri GPU, non carica kext, non controlla ventole o clock e non attiva spegnimenti.

Le temperature CPU e GPU restano `UNKNOWN`. Una futura label “CPU die temperature” di powermetrics sarebbe conservata solo come candidata non verificata finché la sorgente SMC non sia convalidata su Ryzen 7 7700/VirtualSMC. Una label generica “GPU die temperature” non viene attribuita alla RX discreta, dato che il Ryzen 7 7700 include anche una GPU integrata. La lettura per la GPU richiederebbe un'identificazione esplicita della sorgente legata a PCI `1002:7590`.

Comando consigliato per controllare la disponibilità:

```sh
python3 -B cobalt64/tools/thermal-readonly/macos_thermal_watch.py --check
```

Sul Mac osservato termina con **exit code 2** e stampa `CHECK=UNKNOWN thermal_protection=UNKNOWN`. È fail-closed sui sensori mancanti. Se in futuro entrambi i valori fossero presenti ma il percorso di protezione rimanesse sconosciuto, il codice sarebbe 3; il check non dà un esito “sicuro”. Senza `--check`, exit code 0 significa solo che il JSON è stato prodotto. Il monitor non parte da solo.

La suite offline usa fixture simulate e mock delle query OS; **10 test passano**. Verifica label esatte, valori fuori intervallo, attribuzione GPU, stati XCPM a zero, parsing nodi IOHWSensor, errore powermetrics, rifiuto dell'esecuzione root e semantica fail-closed di `--check`. Non interroga l'hardware durante i test.

## Limiti del codice Cobalt64 e dati storici

Il watchdog termico Cobalt64 trovato in `navi48-bringup` legge `THM_TCON_CUR_TMP` tramite `RREG32` ogni 250 ms dal kext. È una lettura MMIO dentro al driver, non un sensore host macOS non privilegiato; non l'ho eseguita né usata qui. Il documento [gpu_safety.md](gpu_safety.md) descrive inoltre metriche SMU con layout IF 0x33 non convalidato. Questi percorsi non forniscono una telemetria host attuale verificata.

Lo stesso report riporta una vecchia osservazione R2 di 304 W e hotspot 86 °C con DPM attivo, precedente al clamp allora introdotto. È un'evidenza storica di un altro percorso, non una misura del boot o della configurazione attuale. Le soglie del watchdog Cobalt64 documentate per test precedenti non sono state applicate a questo monitor.

AMD riporta per Ryzen 7 7700 un Tjmax di 95 °C. È il limite operativo di specifica, non una temperatura osservata né un obiettivo di esercizio. La scheda AMD RX 9060 XT elenca 160 W di typical board power; nella specifica consultata non ho trovato una soglia di temperatura junction, quindi il monitor non imposta limiti GPU arbitrari. [Specifiche Ryzen 7 7700](https://www.amd.com/en/products/processors/desktops/ryzen/7000-series/amd-ryzen-7-7700.html), [specifiche RX 9060 XT](https://www.amd.com/en/products/graphics/desktops/radeon/9000-series/amd-radeon-rx-9060xt.html).

## Alternativa concreta per misurare prima di carichi prolungati

Per la CPU, consultare prima il monitor hardware BIOS/UEFI della scheda e verificare che la ventola CPU reagisca normalmente. Per entrambe le temperature, il percorso pratico è un avvio Linux mantenuto separato: identificare la scheda con PCI `1002:7590`, poi leggere solo i canali hwmon del device corrispondente. Usare `k10temp` per la CPU solo se il kernel riconosce esplicitamente il Ryzen 7 7700 e il valore è coerente con la lettura BIOS; la pagina kernel consultata elenca Zen 3 per Family 19h e non conferma specificamente questo modello Zen 4. La documentazione kernel descrive i canali temperatura GPU esposti da `amdgpu`, ma non conferma da sola il supporto di ogni canale sulla RX 9060 XT: verificare label e device PCI. [Interfaccia termica hwmon di amdgpu](https://docs.kernel.org/gpu/amdgpu/thermal.html), [documentazione k10temp](https://docs.kernel.org/hwmon/k10temp.html).

Come possibile futura via macOS, i README di [SMCAMDProcessor](https://github.com/trulyspinach/SMCAMDProcessor) e del fork [SMCAMDProcessor-personal](https://github.com/DrogaBox/SMCAMDProcessor-personal) dichiarano supporto per letture AMD, ma il primo richiede sia `AMDRyzenCPUPowerManagement.kext` sia `SMCAMDProcessor.kext`; descrive inoltre P-State/power management e fan override. Il fork dichiara generazioni Zen 4 e Tahoe, ma le sue affermazioni non provano la compatibilità con questa scheda madre, BIOS e CPU. Non sono stati scaricati, installati o caricati. Prima di considerarli, serve un audit specifico dei sorgenti/release e delle funzioni di scrittura, con confronto delle letture con BIOS e Linux sullo stesso hardware.

Finché non c'è una lettura attendibile, evitare benchmark o workload prolungati CPU/GPU in questa sessione macOS: il monitor preparato registra l'assenza di telemetria, non può proteggere l'hardware.
