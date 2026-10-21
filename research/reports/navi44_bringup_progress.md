# Prosecuzione hardware Navi44 — 20 ottobre 2026

## Stato aggiornato — 20 ottobre 2026, boot13

**ACK GFXHUB risolto; tredici boot stage17 completati, con fault spontanei ancora aperti.**
RS64 è preparato prima del GFXHUB e l'ACK obbligatorio passa. Baseline compute
32/32;20 ripetizioni sono state fatte nei boot1–2. S1b/VMID8 boot6 ha superato
positive4/4 e fault/recovery EOP. `vadd_ir` gfx1200 ha superato il test al
boot12 con32 somme e canary corretto.

Boot13 usa il timeout KIQ SET1 Navi44 `0xA`, da Linux `mes_v12_0.c`; non va
confuso col timer oversubscription50 del packet SET principale. Il risultato
stage17 è0 e compute32/32, ma IH ha6 interrupt/7 entry, EOP4, fault3 e CP-error0:
tre fault VMID0 VA0 nei ring169/ring153 durante setup MES. La prima occorrenza
segue SET_HW_RSRC e precede SET1; il timeout corretto non ha rimosso il cluster.
GART Linux idle è basso `0..512MiB`, il GART locale è alto
`0x8400000000..0x840fffffff`; PTE0/placement è ipotesi da verificare, non
causa dimostrata. Serie20 boot consecutivi non iniziata. VM spenta, EFI safe
stage17 senza IRQ/native/vadd opt-in; reset VFIO GPU/audio registrato, reset
ASIC completo non dimostrato. Nessun Metal/IOAccelerator/WindowServer.

La cronologia sottostante conserva gli esiti storici; per stato corrente,
hashes, log e passi successivi vedere
[`phase2_mes_fault_checkpoint.md`](phase2_mes_fault_checkpoint.md) e
[`gfxhub_ack_compute.md`](gfxhub_ack_compute.md).

Richiesta umana successiva al primo test: proseguire con i prossimi passi.
VM separata e overlay sul backup immutato; host sullo stesso boot VFIO con iGPU.

## Configurazione BAR0 risolta per il test

- Root bus, apertura1GiB: kext attivo ma IOPCIFamily omette BAR0 a0x800000000.
- Tentativo portaPCIe, GPU/audio funzioni0/1: bridge visibile ma risorse figli non assegnate;
  nessun kext bringup attaccato. Ripristinata topologia root bus; nessun bypass del driver.
- Host sysfs resource0_resize=8 (256MiB), eseguito solo senza QEMU e senza utenti VFIO,
  ResizeGpuBars=8 nell'EFI: probe-S riuscito, reset completati.
- Stage1: BAR0 IOPCIFamily/config/ReBAR tutti0x90000000+0x10000000, latch concorde;
  kmutil conferma0.0.664 attivo, discovery42IP e16304MiB. Il test cambia sia dimensione
  sia indirizzo: non dimostra quale dei due fosse responsabile del problema a1GiB.

## Stage5: PSP SOS riuscito

Boot con navi48-stage=5 e navi48-interrupts=0, stesso kext compilato.
BAR0 mappato write-combining256MiB; console VMware esterna alla RX a0x80000000.
Regione del test VRAM+[0x4000000,0x6000000). Tre controlli bidirezionali a
0x4000000,0xa000000,0xfff0000: ALL MATCH, byte originali ripristinati.
PSP preflight READY/SOS down, MC[0x8000000000,0x83fc000000).
KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV, HAD_DRV, IPKEYMGR tutti accettati;
RAS assente saltato come previsto. SOS sign-of-life0x26c1f8ad dopo~26ms:
`psp-stage: SUCCESS — SOS alive`. Guest SSH raggiungibile e servizio attivo.
Nessun interrupt, compute, acceleratore o Metal avviato.

## Riproduzione e prove

`tools/vm/prepare-gpu-test-stage.py` configura solo stage ammessi, VM spente e lock
esclusivi; backup EFI per digest, conversione e rilettura FAT verificate, controlloqcow2.
Launcher verifica SHA256 dell'EFI preparata e overlay, oltre ai controlli host.
MEMLOCK alzato solo sulla shell di test UID1000; QEMU non eseguito come root.

Artefatti in `/mnt/vm/images/macos-gpu-test/diagnostics/`:
`pcie-stage1-{serial.log,ioreg.txt,pci.json}`, `bar256-stage1-{serial.log,ioreg.txt,pci.json}`,
`stage5-serial.log`, `stage5-guest-ioreg.txt`, `host-bar0-size-8.json`.

## Stage6: IH, GMC e ring PSP riusciti

Ladder raggiunta6 (PSPRingCreate), result0, conferma IORegistry. IH configurato
senza interruptCPU; GMCInit completo, GART MMHUB e flushTLB ack. Ring PSP4096B
MC0x8004100000, risposta0x80c20000. Query0x50 e0x51 completate con fence1/2 e
status0 in1000us ciascuna; riserve firmware restituite0x3f7e00000+0x3200000
e0x3dac00000+0x400000. Guest SSH operativo.
Artefatti: `stage6-serial.log`, `stage6-guest-ioreg.txt`.

## Primo tentativo stage8: fermo su ring persistente tra avvii

Dopo shutdown guest e reset VFIO completato, SOS era ancora vivo (0x26c22f97) e
C2PMSG_64=0x80c20000 dal precedente ring. Nuovo INIT risponde0x80c20115: errore
PSP, scala fermata allo stage6 con0xe00002ca, reached5. Non attribuiamo un nome
ufficiale allo status0x115; la persistenza SOS/ring è l'ipotesi corroborata dalla
sequenza tra i due avvii. Stage7/8 non eseguiti in questo tentativo.

Modifica mirata a `psp_v14_0.cpp`: se SOS è vivo e la risposta completata è
quella di un precedente KM INIT, invia il normale DESTROY_RINGS, richiede una
nuova risposta senza errori, poi azzera e ricrea il ring. Nessuna adozione di
buffer vecchi, nessun errore convertito in successo; altre risposte non recuperate.
Il comando DESTROY deriva dalla routine già presente e dal driver Linux AMD
(https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/psp_v14_0.c).
Compilazione navi44/APPLE_ROUTE=0 e verifica firma macOS riuscite. Kext nuovo
SHA256690d0b2b524e54eba5e60d3178129f1917c521661a677d80d8f78808c9ff9bbf
(versione ancora0.0.664, distinguere i binari dal digest). Backup EFI prima
della sostituzione e rilettura byte per byte di tutti i file iniettati.

## Stage8 dopo la correzione: riuscito

Prima revisione del filtro non scattava perché0x00c00000 è presente nella
risposta firmware: kmutil confermavaUUID8F6FCCA3-A2D9-3E97-84DF-82538B10AFD9
della prima build modificata, non il vecchio kext. Filtro finale limitato ai due
valori completati osservati0x80c20000 e0x80c20115. Nuovo binarioSHA256
eb3aa4c46c6e069ccae06f16735306510d259eb5a75bd4d08de097f9db48c9a0,
UUIDC3FF023B-B34D-3B89-B398-28F3E03EFE92, firma valida.

Prova da stato persistente0x80c20115: DESTROY_RINGS riceve0x80c30000
(la riga seriale è interlacciata con log Apple), successivo INIT0x80c20000;
query riserve passano. TMRSetup e PSPFwLoad completano, tutti i firmware
embedded accettati. IORegistryStageReached=8, StageResult=0, SSH operativo.
RL assente saltato; ASD non implementato è esplicitamente saltato, non testato.
Il test non dimostra compute o display. Artefatti: `stage8-warm-fix2-serial.log`,
`stage8-warm-fix2-ioreg.txt`, precedenti tentativi1/2 conservati.

## Stage9: SMU e gestione energetica

Stage9 base riuscito: SMU0x00664700 (102.71.0), driverIF0x33, TestMessage
0xabcd0001->0xabcd0002. Il limite originale200MHz è rifiutato con risposta0xff.
Modifica per il solo profilo Navi44: Low interroga GetMinDpmFreq0x1d e
GetMaxDpmFreq0x1e (ID da header Linux AMD), rifiuta range invalidi e usa il minimo
restituito, senza fallback arbitrario. Navi48 conserva il comportamento originale.

Nuova build compilata/firmata e iniettata, SHA256
f1464af6e5f77ed5aa40ec56181fa083a516b5d8d77a6d26d75d866f03a32b9f.
Stage9 con navi48-smu-full=1: UseDefaultPPTable, RunDcBtc e EnableAllSmuFeatures
riusciti. NotifyPowerSource(AC) fallisce, SetAllowedFeaturesMaskLow/High non
supportati; il codice registra questi esiti e usa il defaultIFWI, non li nasconde.
GetRunningSmuFeatures ritorna0x0498f59e38fffcfb, identico al dumpLinux di questa
RX. Bit23THROTTLERS,28FW_CTF,29FAN_CONTROL attivi (header LinuxAMD).
PMFW GFXCLK range500..3500MHz, SetSoftMaxByFreq500 accettato, idle clamp applied.

Tre snapshot metriche letti ma **non validati**: firmwareIF0x33 contro layout
0x2e. Il tool avvisa; temperature/potenza decodificate sono solo plausibili,
non misure certe. Header Linux corrente SmuMetrics è compatibile strutturalmente
con quello locale, ma ciò non prova l'ABI0x33. Nessun carico prolungato previsto.
Artefatti: stage9-basic-serial.log, stage9-driver-log.txt, stage9-full-driver.log,
stage9-full-ioreg.txt, stage9-full-metrics.txt, linux-smu14-driver-if.h.

## Stage11: IMU e RLC riusciti

Stage10 IMU tramite PSP, poi RLC autoload completo: CP_STAT=0,
RLC_RLCS_BOOTLOAD_STATUS=0x8000003f,0us di polling. Stage11RLCInit result0,
conferma IORegistry e SSH. Stesso mask di protezioni SMU e clamp500MHz applied.
Artefatti: stage11-serial.log, stage11-ioreg.txt. Nessun compute ancora eseguito.

## Stage15 esplorativo e blocco GFXHUB reso esplicito

Con build f1464af..., CPInit, MESInit, GFXInit, SDMAInit ritornano successo.
Ring test SDMA0 e1 completi; copia4096B, zero1024dword mismatched;
sweep16casi (fino64KiB) tutti corretti, verificati da finestraMM e BAR0.
IORegistryStageReached15, SDMACopyTest=passed, mismatched0.
**Caveat decisivo:** ensure_gfxhub_gart ignorava il ritorno del flush iniziale
GFXHUB, che aveva già registrato un timeout. Queste copie provano SDMA,
non la correttezza completa della VM GFX o la prontezza compute.

Correzione del controllo: richiede ACK iniziale e propaga il timeout.
Provato anche DisallowGfxOff (messaggio0x29): SMU rispondeOK ma **non risolve**
il timeout. Il core viene mantenuto sveglio nel percorso manuale Navi44,
con rilascio previsto nel teardown; questa è una precondizione verificata,
non una spiegazione dimostrata del guasto. Linux usa anche percorsi tramite
firmware quando MES è pronto; resta da confrontare stato/power/reset GFX e
sequenza di invalidazione, senza saltare l'ACK o ritentare shader alla cieca.

Build compilata/firmata: SHA256
 a8238ee6299993c978c79005e2b48667d98d787aa59ef1bc547dc2561ba0f8a7.
Nuovo tentativo target15: fermaCPInit con0xe00002d6, reached11.
Lettura tardiva via tool root: reg0x28b8=0x00f80001, reg0x28ca=0,
CP_STAT0x21a0=0x80004000. Non è solo un timeout di avvio troppo breve.
Applicato esplicitamente `navi48test power 1`:500MHz accettati anche dopo il
fallimento, evitando di lasciare senza limite il percorso di errore.

Artefatti: stage15-before-gfxoff-fix-serial.log, stage15-ioreg.txt,
stage15-gfxoff-driver.log, stage15-gfxoff-{serial.log,ioreg.txt,shutdown.log},
stage15-gfxhub-late-registers.txt. Il primo log tool in /tmp del guest è stato
pulito al boot successivo: per quel tentativo restano seriale completo e ioreg.

## Chiusura e ripresa

Unload richiesto prima dello shutdown: rifiutato dal kernel perché il kext è
retained/in use. Non abbiamo dichiarato eseguito il teardown o ripristinato
GFXOFF: il comando AllowGfxOff non è stato osservato. Arresto guest fino a
vfs_unmountall(system) end, poi QMPquit quando necessario per il problema SMC
preesistente. Reset VFIO GPU/audio completati; nessun fault IOMMU o errore
VFIO nei log di questa sessione. Non è una prova di reset completo del GFX:
SOS e altri stati persistono tra avvii, come osservato sopra.

QEMU assente, RX/audioVFIO, Linux su iGPU, BAR0host256MiB. qemu-img check
overlay: zeroerrori. EFI fallback stage11 preparata con ultimo kext e digest
verificato, nessuna VM riavviata per il fallback. Il prossimo test deve
risolvere l'ACK e garantire uno stato GPU iniziale verificabile; non aumentare
stage o presentare stage15 come verde finché il controllo non passa.

Controlli: build macOS completa e firma per ogni revisione, controllo sintassi
Linux dei tre moduli modificati siaNavi44 siaNavi48 (3PASS ciascuno), script
Python compilabili, bash-n e gitdiffcheck passano. Non applicate modifiche a
Windows, firmware flash, initramfs normale o configurazione display host.
