# Fault GCVM durante l'inizializzazione MES — checkpoint aggiornato 20 ottobre 2026

> Stato autoritativo per ripresa: aggiornato dopo il boot13 e l'oracolo Linux.
> Le sezioni successive conservano la cronologia dei boot8 e precedenti.

## Stato sintetico Fase1/Fase2

Fase1 è completata con la baseline esplicitata: audit
[`phase1_completion_audit.md`](phase1_completion_audit.md) confronta entrambe
le varianti Navi44/Navi48, 66 PASS / 12 FAIL / 28 BUILD / 2 NOCMD contro
65 / 13 / 28 / 2 alla baseline `d6c9aed`; nessuna regressione. Sintassi Linux
53/53 per profilo, firmware Navi44 10/10 SHA e shader gfx1200 identico al
golden. La build macOS è documentata separatamente e non è stata rifatta
dall'audit finale.

Fase2 **non è completa**. Sono documentati 13 boot stage17 totali, non 13 boot
puliti; il conteggio della serie richiesta di 20 boot consecutivi è ancora 0.
Le 20 ripetizioni compute si riferiscono esclusivamente ai boot stage17 1 e 2.
L'ACK GFXHUB resta obbligatorio ed è passato in tutti i boot riportati; il
compute baseline32/32 continua a passare. S1b boot6 è un PASS completo ma non
sostituisce la classificazione dei fault spontanei GCVM VMID0 osservati nei
boot IRQ. Il boot13 ha riprodotto tutti e tre i fault.

## Correzioni e prove successive al boot8

- **Boot9 — wire ABI MES.** Il confronto Linux ha trovato in
  `SET_HW_RESOURCES_1` padding extra dopo `api_status`, che spostava i campi
  successivi di 8 byte. La struttura locale ora allinea timestamp dw6,
  flags dw8, debug pointer dw10, size dw12, timeout dw13, cooperative dw14 e
  cleaner dw16, con controlli di wire layout. Modifiche in
  `cobalt64/src/navi48-bringup/src/amd/mes_v12_1.cpp` e
  `cobalt64/src/navi48-bringup/src/amd/mes_api_wire.h`; test host
  `tools/hosttests/test_mes_set_hw_resources_1_wire.cpp`. Log
  `research/hw_dump/phase2_stage17_meswire_boot9_serial.log`, SHA-256
  `4087ce3cbb326246ac79adb7a9bd1472ac380ff4401d8209979a423579e08a1c`.
  Questa correzione non dimostra causalità sui fault VMID0.
- **Boot10/11/12 — kernel vadd_ir.** HSACO gfx1200 descrittore effettivo:
  `a`, `b`, `c` puntatori ai byte 0/8/16, `n` u32 al byte24; il file assembly
  omonimo era stale (kernarg288) e non è stato usato. Integrazione e controlli
  ABI per dispatch ptr/kernarg ptr e workgroup size, con canary, in
  `tools/build-vadd-ir.sh`, `cobalt64/src/navi48-bringup/src/amd/vadd_ir_abi.h`
  e `compute_test.cpp`.
  Boot10 ha avuto dispatch senza EOP per mapping kernarg; boot11 ha eseguito
  il calcolo ma il waiter ha dato un falso negativo; boot12 è il risultato
  conclusivo: 32 somme attese e canary corretto. Log boot10
  `phase2_stage17_vadd_boot10_serial.log` SHA-256
  `0e89aa0eb4fc3ddb985cda1fa37873c73646e79621b73f004ddd48c03f3dd591`;
  boot11 `phase2_stage17_vadd_boot11_serial.log` SHA-256
  `e1e2ebefcd4350ad325ddcf504a24b0c67c5020ebecf8f94ea3d3aa6897e41c3`;
  boot12 `phase2_stage17_vadd_boot12_serial.log` SHA-256
  `461f0a3e7fc6aebf5b770a438db1d1f13f735a18155c766a4d1629b657e0ad7d`.
- **Timeout SET1 Navi44 e boot13.** Linux `mes_v12_0.c` GC12.0 usa timeout
  KIQ unmap `0xA` (100 ms unit); il precedente valore100 derivava dal ramo
  v12_1 e non è corretto per questo target. Il valore locale è stato portato
  a `0xA`; la correzione wire sposta tale campo a dw13. Non confondere con
  l'oversubscription timer50 in `SET_HW_RESOURCES` dw55, che resta50.
  Boot13 ha stage17 result0, compute32/32, EOP4, fault3, CP-error0 e IH6/7.
  Fault: GFX ring169 VMID0 VA0 write, status `0x40b52`, dopo SET_HW_RSRC;
  ring153 VMID0 VA0 read e ring169 VMID0 VA0 write, status `0x40b53`, dopo
  SET1. Il primo evento precede SET1: timeout `0xA` non ne può essere causa;
  il cluster resta irrisolto anche dopo la correzione.
  Log `research/hw_dump/phase2_stage17_timeout10_boot13_serial.log`, SHA-256
  `04a7d1f295cb2ed268bb536fd315052db0aaea7c5b3b690b16983bfed2a1192b`.
  Kext eseguibile della build corrente SHA-256
  `25026d2dd41c91a5aca6850718638e146c2930ec703f6c7aba6493735cefc1aa`;
  bundle tar `/mnt/vm/builds/phase2-timeout-fix.kext.tar.gz` SHA-256
  `08a2e4581334d269d30fcc1e944e89bcebee70f88fd4f6b2678a80f3ec188ecb`.

## S1b e VMID8 — esito separato

Il boot6 nativo è PASS completo: VMID8 positive4/4 (lowwrite, highwrite,
mixed, compute), compute32/32 e fault leg con fault osservato e successivo EOP
di recovery. CP_DEBUG è stato letto (`0x20408400`) dopo il normale RMW; non è
stato forzato. Questo esito è separato dai boot3/4 in cui il fault leg fu
REFUSED (`CP_DEBUG=0x20400400`). In questo incremento boot6 resta il risultato
completo valido. Non confondere S1b con la serie di boot stage17 clean.

## Oracle Linux runtime e limiti del confronto

Acquisizione: `research/hw_dump/linux-oracle-20261020T181307Z/`, risultato
`guest_poweroff_qemu_exit_0`; kernel guest `7.2.10-1-cachyos`, amdgpu3.64.0,
PCI1002:7590, MES0x93, SMC102.71.0. Nessun GCVM/UTCL2 fault nell'inizializzazione
idle; non era attiva una queue utente. Il ring MES3.1.0 ha 22 frame da64 dword;
SET1 timeout dw13=0xA, mentre oversubscription SET dw55=50. GART Linux
`0..0x1fffffff` (512 MiB); GART macOS
`0x8400000000..0x840fffffff` (256 MiB). I blob firmware Linux decompressi
coincidono con gli embedded; SHA: uni-MES
`ee058438467479d05d3d54ec9b0a592cac50bfa3834e65c6e90bd0e675c087d1`, ME
`17487eb283d479ddb6331bc850a623e3f1217907e25aa5acf89602fb3eaeaf94`, MEC
`28b1e5bae440044887bab53a374db7bb971f7cc2780ab2b55c561e19f24d7fac`, SMU
`1b2054e3f710d1ab8dbdf6ff35914ad376b51caa6337831260c955add874b2ee`.

`gpu_metrics.bin` è export Linux tradotto version1.3/120 byte e hwmon riporta
idle edge29C/junction30C/mem30C/SoC circa8W. L'IF0x33 identificato dal firmware
è GetDriverIfVersion, non prova la versione ABI della metrics table; non c'è
layout IF0x33 indipendentemente validato. Il risultato Linux mostra che il
percorso idle upstream inizializza MES e firmware senza i fault macOS osservati,
ma non rende automaticamente equivalente il contesto macOS e non valida
telemetria SMU proprietaria.

L'oracolo è stato lanciato una volta con GPU passthrough senza audio. QEMU ha
avvertito che il reset GPU dipende dal gruppo16 non posseduto; il journal host
ha registrato successivamente reset VFIO GPU/audio `reset done`. VM off al
checkpoint, ma reset ASIC completo non dimostrato. Initramfs offline
prevalidata in `/mnt/vm/builds/linux-oracle-offline-validation/initramfs.img`,
43,320,788 byte, SHA-256
`1fbfeb1f1fe4acfc3f38347823deca43786176c522f78613b2b10adf22478dca`;
il runner runtime ha costruito una propria immagine temporanea (vedi
`research/reports/linux_oracle_setup.md`).

## Stato host, VM ed EFI al checkpoint

Boot13 guest macOS ha completato `vfs_unmountall(system) end`; solo dopo è
stato inviato QMP quit. QEMU è assente; SSH2223/QMP non attivi. Journal host ha
registrato reset VFIO GPU/audio (`reset done`); non è prova di reset ASIC
completo. GPU `03:00.0` e audio `03:00.1` restano legate a vfio-pci, iGPU al
driver host. Nessuna modifica Windows, flash o reboot host.

La VM macOS è spenta. EFI ripreparata stage17 senza `navi48-native=1`, IRQ e
vadd opt-in; `test-plan.json`: `stage=17`, `interrupts=false`,
`native_s1b=false`, `vadd_ir=false`, `vm_running=false`. EFI SHA-256
`88487b31aa78c31c36dacdae3c061c318ef5602990360c937ed2c34b675e836b`.
Kext corrente SHA eseguibile sopra. Nella storia boot12 e boot13 IRQ erano
abilitati per diagnosi; non sono default EFI. Nessun carico lungo, Metal o
WindowServer è stato avviato.

## Ripresa precisa

1. Esaminare il contratto Linux/macOS di GART low placement e **PTE all'indice
   zero**, inclusa la dummy/reserved first page e i mapping WB scheduler/query/
   fence; nessun alias VA0 senza fonte e test causale. Il GART basso Linux è
   la differenza concreta da verificare, non causa dimostrata.
2. Decodificare e confrontare gli indirizzi runtime dei frame MES e i mapping
   fisici di scheduler context, query/status fence e cleaner, oltre ai timeout
   (oversub SET dw55=50 vs unmap SET1 dw13=10). Il packet SET principale è
   staticamente compatibile; i pointer e PTE runtime restano prioritari.
3. Valutare reset completo tramite evidenza indipendente; completare il ramo
   C2PMSG/mode1 + AtomBIOS `asic_init` solo se richiesto dal criterio di reset.
   Boot13 mostra C2PMSG35=`0x80000000`, C2PMSG81=0 prima SOS e `0x55ac8702`
   dopo SOS: il ramo SOS già vivo non è stato esercitato.
4. Dopo classificazione/rimozione dei fault inattesi, eseguire una serie nuova
   di20 boot consecutivi con criteri espliciti e log per ciascun boot; il
   contatore della serie parte da0. Non contare i boot storici né le20
   ripetizioni compute.
5. SMU IF0x33 rimane caveat: acquisire dati grezzi con ABI/versione esatta o
   correlare a una fonte indipendente; l'export Linux tradotto non basta.

Non ripetere prove in questo incremento: la VM è lasciata spenta per richiesta
di contenimento uso/crediti. Fase2 resta aperta; non assegnare PASS a reset,
telemetria IF0x33, assenza di fault, confronto runtime completo o serie20.

## Evidenze precedenti

- Boot6 S1b, senza interrupt: gate VMID8 accettato, positive 4/4 (lowwrite,
  highwrite, mixed, compute), compute 32/32; fault leg PASS con recovery EOP.
  Kext SHA-256 `816d0b99cb3d2100a6a168b755abaadeb981151eb7f5d183fd58f40d36b0d375`;
  log `research/hw_dump/phase2_stage17_native-s1b_boot6_serial.log`, SHA-256
  `4dcf6a49a82102260fe038fcb3405f13874e4d41f93a4b743b0f64611573c082`.
- Boot7 IRQ: stage17, shader32/32, EOP4, fault3, CP error0. Vedi il relativo
  log `research/hw_dump/phase2_stage17_irq_boot7_serial.log`.
- Boot8 ha ripetuto lo stage17 con IRQ e strumentazione read-only. Kext SHA-256
  `ac9eb4568d662d06a94553c047b80a37762a4c5e04911dfd5d0ac0d9826b884`.
  Log `research/hw_dump/phase2_stage17_irq_diag_boot8_serial.log`, SHA-256
  `dae6790802afd36ad51fabba482cc2c3b47cfecb8ef1c9fef5ae62d8ebe7dbb0`.

## Boot8: causa ancora aperta, evento localizzato

La strumentazione in `mes_v12_1.cpp` campiona VMID0, GART, i primi quattro
dword di scheduler context/status fence e lo stato fault prima/dopo
`SET_HW_RSRC` e `SET_HW_RSRC_1`. Non cambia packet, CP_DEBUG, fault policy o
mask VMID. Sintassi Linux Navi44/Navi48: PASS.

Prima dei packet: VMID0 `CNTL=0x3fffc01`, PDB `0x04700001`, pagine
`0x08400000..0x0840ffff`, GART `0x8400000000..0x840fffffff`; i buffer scheduler
e status fence sono allocati a MC `0x8400023000` e `0x8400024000`, tutti dentro
l'apertura. Prima dell'invio gli header dei buffer sono zero; dopo
`SET_HW_RSRC`, `sch_ctx[0]` diventa `0x10fa0`, mentre status fence resta zero.

1. Subito dopo `SET_HW_RSRC`: IH client GFX `0x0a`, ring169, VMID0, write
   (`data[1]=0x20`), timestamp `0x4ab137992ed`. Stato GCVM `0x40b52`:
   VA0, walker_err1, perm5, mapping_err1, CID5. Il fence API MES completa
   con status1.
2. Dopo `SET_HW_RSRC_1`: ring153 read (`data[1]=0x40`, ts`0x4ab13afa4ae`)
   e ring169 write (`data[1]=0x20`, ts`0x4ab13afa678`), ancora VMID0/VA0;
   status cumulativo `0x40b53`, `more=1`. Il fence completa con status2.
3. La successiva `QUERY_SCHEDULER_STATUS` (`0x400b1`) completa con status3
   senza un quarto fault. IH totale: 6 interrupt/7 entries, EOP4/fault3/
   CP-error0. Stage17 e lo shader 32/32 passano; i fault sono reali e restano
   un difetto anche se non bloccano questo workload.

L'audit statico Linux conferma base PDB e range GART coerenti, depth0/block0
come nel percorso Linux ordinario. `PDB 0x04700001` risolve a MC
`0x8004700000`; le allocazioni registrate sono nel range. Linux disabilita la
identity aperture CONTEXT1 e non richiede una mappatura VA0 per VMID0. Il range
locale è256MiB contro512MiB nel profilo Linux, ma gli indirizzi usati sono nei
primi `0x26000` byte. Queste cause sono escluse dai dati disponibili; non è
stato aggiunto alcun alias a VA0.

Il packet Linux `SET_HW_RESOURCES` è di64 dword e il layout, i flag principali,
i pointer scheduler/status e l'event-history nullo sono coerenti con il codice
locale (`disable_mes_log=1`). Il runtime Navi44 dichiara basi GC 4, MMHUB2,
OSSSYS2; il packet riempie i segmenti extra con zero. Il blob golden mostra
valori in posizioni base extra; non è ancora dimostrato che il dump sia
comparabile per ASIC/struttura né come quei campi spieghino un accesso VA0.
Non alterare i segmenti sulla sola base di tale differenza. La policy locale
VMID mask `0xfe` riserva VMID8 per il test S1b ed è coperta da test; la
divergenza dal mask Linux `0xff00` non spiega il fault VMID0 e non è stata
modificata.

## Stato PSP e arresto

All'ingresso PSP del boot8: `C2PMSG_35=0x80000000` e `C2PMSG_81=0` prima del
caricamento del SOS; in seguito il firmware riporta `C2PMSG_81=0x55ac8702`.
Quindi il ramo mode1 per SOS già vivo non era necessario in questo boot, ma il
recupero mode1 + AtomBIOS `asic_init` non è implementato né validato.

Il guest ha completato `vfs_unmountall(system) end` alla riga4552; QEMU è uscito
dopo il poweroff del guest, senza QMP quit prima dell'unmount. EFI ripreparata
stage17 con IRQ e native opt-in disabilitati; launcher `--check` passa e
`qemu-img check` dell'EFI non segnala errori. VM spenta. Host VFIO preflight
conferma GPU/audio legate a `vfio-pci`; non prova da solo un reset ASIC
completo.

## Prossimi passi fase2

Il boot8 è l'ottavo stage17 complessivo, non una serie consecutiva. Le20
ripetizioni compute sono solo nei primi due boot. Il fault leg/recovery S1b
VMID8 del boot6 resta distinto dai fault spontanei VMID0 nei boot IRQ7/8.
Non forzare CP_DEBUG o mappare VA0. La Fase2 resta incompleta per la causa dei
fault MES/GCVM, reset completo e ramo mode1/AtomBIOS, confronto golden/MQD
completo, telemetry IF0x33 indipendentemente validata, kernel compute ulteriori
e20 boot consecutivi con criteri di reset/stabilità verificati.
