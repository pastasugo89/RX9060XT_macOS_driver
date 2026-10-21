# Audit indipendente della fase 1

Data: 20 ottobre 2026. Ambito: voci 1.1–1.8 di `FASI.md`, sola lettura di sorgenti e prove già presenti, più verifiche host Linux ripetibili. Nessuna VM, GPU o modifica al codice è stata usata. Le modifiche preesistenti nel checkout sono state lasciate intatte.

## Esito

Le prove disponibili sostengono il completamento dei criteri 1.1–1.8, con due precisazioni di portata: la voce 1.5 documenta l’impostazione del registro nel codice ma non un controllo del valore sulla GPU; la voce 1.8 include una build macOS reale documentata, non ripetuta in questo audit. La suite Cobalt64 non è tutta verde: contiene esiti storicamente non passanti/non compilabili, confrontati con la baseline.

## Criteri ed evidenze

| Voce | Esito | Evidenza e limite |
|---|---|---|
| 1.1 Rotta Apple esclusa di default | Comprovata | `Makefile` imposta `APPLE_ROUTE ?= 0`; la lista degli oggetti conserva `DisplayPipeGuard.cpp` e `apple_route_off.cpp`. `research/reports/apple_route_split.md` registra i 95 simboli sostituiti, il link Linux senza simboli di progetto irrisolti o duplicati e il controllo precedente di 53/53 sorgenti con le varianti di route. La cancellazione definitiva è deliberatamente rinviata ai test hardware: non è parte di questa voce. |
| 1.2 Profili ASIC | Comprovata | `Makefile` seleziona `navi44` per default e gestisce `navi48`; `asic_profile.h`, `probe()` e il template `Info.plist` scelgono ID PCI e profilo corrispondenti. Le due verifiche Linux di sintassi hanno compilato 53/53 unità per il profilo predefinito e 53/53 con `N4X_ASIC_NAVI48`. |
| 1.3 Firmware Navi 44 | Comprovata | I dieci blob installati Navi 44 corrispondono tutti ai SHA-256 attesi in `cobalt64/tools/fetch-firmware.sh` (verifica read-only effettuata sui file in `cobalt64/src/navi48-bringup/firmware/`). `tools/hosttests/run.sh` ha inoltre passato il parsing del container PSP e l’estrazione di tutti i payload GC/SDMA per Navi 44 e Navi 48. La verifica hash dei dieci blob è risultata PASS. |
| 1.4 Caps GFX da IP discovery | Comprovata | `IpDiscovery::gcInfo()` legge e valida la tabella GC e `gfx_gpu_early_init()` usa le caps scoperte, con fallback al profilo e controlli dei limiti degli array. `tools/hosttests/run.sh` ha letto il dump Navi 44 e riportato 2 SE, 2 SA/SE, 4 RB/SE, 8 CU/SA, esito PASS. |
| 1.5 Golden DB_MEM_CONFIG | Comprovata nel sorgente | `gfx_v12_0.cpp` applica la maschera e il valore `0x8000` a `DB_MEM_CONFIG`. L’implementazione è presente e compilabile; questo audit non ha verificato il valore scritto a runtime sulla GPU. |
| 1.6 Shader di self-test gfx1200/gfx1201 | Comprovata | Ho riassemblato in `/tmp` i due sorgenti `store_magic.s` e `store_magic_hsa.s` per `gfx1200`, cambiando solo la direttiva target, e confrontato le sezioni `.text` con i due `.bin` tracciati per `gfx1201`: entrambi i confronti sono byte-identical. I file del repository non sono stati modificati. |
| 1.7 Test host | Comprovata con esiti misti già presenti | `tools/hosttests/run.sh`: PASS, inclusi dump discovery, container PSP e payload GC/SDMA. `run-cobalt64-tests.py` è stato eseguito per entrambi i profili: ciascuno riporta 66 PASS, 12 FAIL, 28 BUILD, 2 NOCMD; nessuna regressione rispetto alla baseline, come conferma lo script. La baseline di 108 righe contiene 65 PASS, 13 FAIL, 28 BUILD e 2 NOCMD: un test precedentemente FAIL (`native_s1b_test`) ora è PASS. Le 28 BUILD dipendono da fixture/header mancanti o non pubblicati; i FAIL e NOCMD restano esiti non verdi e sono confrontati con il riferimento, non promossi a successi. |
| 1.8 Build | Comprovata dalle evidenze registrate | `tools/linux-check-kext.sh` ha passato 53/53 unità per ciascuno dei due profili nell’audit. `research/reports/macos_build_validation.md` registra la build completa macOS Tahoe 26.6.2/25G83, Navi 44 con `APPLE_ROUTE=0`, firma ad hoc verificata e `kmutil` con 412 import risolti. Non ho riavviato né ricostruito la VM. La compilazione Linux resta un controllo di sintassi, non genera da sola un kext. |

## Comandi eseguiti

- `tools/hosttests/run.sh` — exit 0; discovery GC, parser PSP e payload firmware GC/SDMA passati per entrambi i profili disponibili.
- `tools/linux-check-kext.sh` — 53 ok, 0 errori.
- `EXTRA_FLAGS=-DN4X_ASIC_NAVI48 tools/linux-check-kext.sh` — 53 ok, 0 errori.
- `tools/hosttests/run-cobalt64-tests.py --asic navi44 --jobs 4` — exit 0, nessuna regressione; 66 PASS, 12 FAIL, 28 BUILD, 2 NOCMD.
- `tools/hosttests/run-cobalt64-tests.py --asic navi48 --jobs 4` — exit 0, nessuna regressione; 66 PASS, 12 FAIL, 28 BUILD, 2 NOCMD.
- Verifica read-only SHA-256 dei dieci file firmware Navi 44 — 10/10 PASS.
- Riassemblaggio LLVM `gfx1200` e confronto binario dei due shader self-test — 2/2 identici ai blob tracciati.

## Limiti e note per il coordinamento

Gli esiti Cobalt64 restano misti in entrambe le configurazioni; la frase “test host verdi” va intesa come assenza di regressioni rispetto alla baseline, non come tutti i test PASS. La baseline stessa ha 2 casi NOCMD, oltre ai conteggi PASS/FAIL/BUILD spesso riportati in breve.

Il record macOS è una prova documentale del 20/10 e non è stato riprodotto perché richiede la VM guest. Nessun risultato di questo audit sostituisce una verifica del registro su hardware; la fase 1 non richiede hardware e la voce 1.5 qui è coperta a livello di implementazione/compilazione.
