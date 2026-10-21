# Audit statico telemetria SMU IF 0x33

Data: 20 ottobre 2026. Solo sorgenti e log esistenti; nessuna VM/GPU avviata e nessun codice modificato.

## Esito

Non ho trovato una definizione pubblica AMD/Linux di `SmuMetrics_t` specifica per il PMFW Navi 44 `102.71.0`. Il sorgente AMD Linux locale `research/src/linux/.../smu_v14_0_2_ppt.c` assegna a SMU 14.0.2 il driver IF `0x2E` (righe 74, 2940), e il corrispondente header `smu14_driver_if_v14_0.h` contiene un solo layout `SmuMetrics_t`. Anche la copia corrente upstream Linux mantiene `0x2E` e quella struttura; non documenta un layout specifico per FW IF `0x33` ([driver Linux SMU 14.0.2](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/pm/swsmu/smu14/smu_v14_0_2_ppt.c), [header metrics SMU 14](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu14_driver_if_v14_0.h)).

Il binario firmware locale/dump identifica SMC `0x00664700` = `102.71.0` (`research/hw_dump/firmware_info.txt:23`); i log stage 9 registrano IF firmware `0x33` (`navi44_bringup_progress.md`, §Stage9). Questi dati provano quale interfaccia espone il firmware installato, ma non pubblicano il layout che la accompagna. `driver_if` e `fw_if` sono versioni dell'interfaccia di messaggi SMU; il loro disaccordo, preso da solo, non dimostra che l'ABI della metrics table sia diversa.

Linux SMU 14.0.2 non interroga una versione separata della metrics table: la mappa messaggi in `research/src/linux/drivers/gpu/drm/amd/pm/swsmu/smu14/smu_v14_0_2_ppt.c:93-148` include `GetDriverIfVersion` e `TransferTableSmu2Dram`, ma non `GetMetricsTableVersion`. Quest'ultimo esiste come voce generica (`smu_types.h:300`), non come messaggio mappato per questo ASIC. `smu_cmn_check_fw_version()` legge e registra le due IF e ritorna 0 senza confrontarle (`smu_cmn.c:1084-1106`); dunque in questo percorso il disaccordo non blocca l'inizializzazione. Il report Linux di bring-up annota un warning per il mismatch (§2.12, riga 738), ma il codice della funzione agganciata al controllo mostra `dev_info_once`, non una comparazione o un warning dedicato.

Il dump esistente è raccolto su RX 9060 XT inizializzata da Linux e contiene `gpu_metrics.bin` esportato da sysfs come `gpu_metrics v1.3` (`research/hw_dump/README.md:1-14`); il relativo `firmware_info.txt:23` riporta SMC `102.71.0`. Linux alloca la tabella SMU metrics come `sizeof(SmuMetricsExternal_t)` (`smu_v14_0_2_ppt.c:389-390`) e la trasferisce con `SMU_TABLE_SMU_METRICS` (`smu_cmn.c:1197-1224`), poi converte i campi nella struttura pubblica `gpu_metrics_v1_3` (`smu_v14_0_2_ppt.c:2142-2225`). Questo costituisce evidenza di telemetry Linux operativa sotto quel FW; `gpu_metrics.bin` è però un export tradotto, non la raw `SmuMetricsExternal_t`, e il dump non conserva la tabella PMFW raw né il dmesg insieme ai dati. Non prova quindi gli offset raw né, da solo, l'accoppiamento esatto IF per quella raccolta.

## Layout noto soltanto per IF 0x2E

La struttura Linux IF 0x2E in `smu14_driver_if_v14_0.h:1649-1727` ha 260 byte. Gli offset ricavabili dal layout AMD/Linux e duplicati dall’attuale `SmuMetrics` sono:

| Campi | Offset byte (hex) | Dettaglio |
|---|---:|---|
| `CurrClock[11]` | `0x00` | 11 `uint32_t`, GFX/SOC/UCLK/FCLK ai primi quattro slot |
| `MetricsCounter` | `0x68` | `uint32_t` |
| `AverageGfxActivity`, `AverageUclkActivity` | `0x7C`, `0x7E` | `uint16_t` ciascuno |
| `EnergyAccumulator` | `0x84` | `uint32_t` |
| `AverageSocketPower`, `AverageTotalBoardPower` | `0x88`, `0x8A` | `uint16_t`; l’unità va letta dal contratto della versione corrispondente |
| `AvgTemperature[12]` | `0x8C` | `uint16_t`; EDGE `0x8C`, HOTSPOT `0x8E`, MEM `0x94` |
| `AvgTemperatureFanIntake` | `0xA4` | `uint16_t` |
| `PcieRate`, `PcieWidth` | `0xA6`, `0xA7` | byte |
| `AvgFanPwm`, `AvgFanRpm` | `0xA8`, `0xAA` | byte e `uint16_t` |

Il wrapper Linux `SmuMetricsExternal_t` incapsula la struct seguita da riserve e padding (`:1729-1735`). Il kext locale copia 260 byte e logga solo i primi 128 (`cobalt64/src/navi48-bringup/src/amd/smu_v14_0.cpp:871-876, 918-923`), quindi i dump raw salvati non coprono neppure gli offset IF 0x2E delle metriche di potenza/temperatura.

## Compatibilità e convalida richiesta

`amdgpu_smu.h:293-379` conserva il layout 0x2E e dichiara esplicitamente 0x33 non verificato. `smu_read_metrics()` confronta l’IF osservato con `0x2E`, ma poi legge e decodifica comunque i valori; i range in `smu_v14_0.cpp:881-889` scartano spostamenti grossolani, non spostamenti plausibili o di singoli campi. Le letture salvate (clock, temperature e potenza plausibili) non stabiliscono l’ABI e non vanno promosse a misure validate.

Per accettare un layout raw 0x33 servono il header/spec AMD relativo al PMFW esatto oppure una derivazione sperimentale che registri **l’intera tabella raw**, versione e dimensione trasferita, e correli ogni offset richiesto a riferimenti indipendenti su quella GPU: clock, sensori termici, potenza e tachimetro in più stati controllati. Vanno validati ordine, unità e dimensione, non solo range. L'evidenza di export Linux impedisce di concludere che il solo mismatch IF renda impossibile la telemetry; non convalida però il layout duplicato localmente. In assenza della prova sugli offset, EDGE/HOTSPOT/MEM, socket/board power e gli altri campi decodificati devono restare marcati non verificati; non c’è base per sostituire il layout 0x2E con una presunta struct raw 0x33.
