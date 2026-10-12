# 04 — Stack compute e toolchain ISA per gfx1200 (RX 9060 XT / Navi 44)

> Report di analisi (fase 0, nessun codice driver). Lingua: italiano; identificatori, registri e termini di codice in inglese.
> Legenda: **[VERIFICATO]** = controllato su codice sorgente locale, dati hardware dumpati o test eseguito su questa macchina; **[INFERITO]** = deduzione ragionata non verificata direttamente.
> Target: PCI 1002:7590 rev c0, GC 12.0.0 (gfx1200), MES 12, SDMA 7.0.0, PSP/SMU 14.0.2, 32 CU (2 SE x 2 SH x 8 CU).
> Percorsi abbreviati: `LNX` = `research/src/linux/drivers/gpu/drm/amd`, `KFD` = `LNX/amdkfd`, `MESA` = `research/src/mesa`, `MAG` = `research/refs/mac-amdgpu`, `SCR` = scratchpad `.../scratchpad/compute`.

## Indice
0. Sintesi esecutiva
1. amdkfd per gfx12 e cosa servirebbe su macOS
2. mac-amdgpu: bring-up gfx1201 da PCIDriverKit e trasferibilita a un kext x86 per gfx1200
3. Backend LLVM AMDGPU per gfx1200: compilazione, code object, kernel descriptor
4. Test runtime su RX 9060 XT: rocminfo, topologia KFD e HIP vector-add
5. AIR (Apple LLVM bitcode) -> LLVM AMDGPU diretto vs AIR -> SPIR-V -> ACO
6. Raccomandazioni: percorso compute e strategia del compilatore shader
7. Domande aperte

---

## 0. Sintesi esecutiva

1. **Lo stack compute ROCm funziona pienamente su questa RX 9060 XT (gfx1200) sotto Linux** [VERIFICATO]: rocminfo vede l'agent `gfx1200` (32 CU, wave32, L2 4 MB, MALL 32 MB, ISA `gfx1200` + `gfx12-generic`); un vector-add HIP gira a ~300 GB/s (94% del picco GDDR6 128 bit) e ~3.8 us per lancio. KFD per gfx1200 usa MES per le code, CWSR con save area di 15 351 808 B per coda (calcolata dalla formula di `kfd_queue.c` e identica al valore sysfs), doorbell a 64 bit, eventi via signal page + EOP.
2. **KFD non e il modello da portare su macOS**: dipende dall'intero core amdgpu, da sysfs e da HMM. Da KFD vanno presi tre pezzi: logica `add_queue_mes` + MQD v12, blob CWSR gfx12 (MIT, `cwsr_trap_gfx12_hex`), schema fence/eventi. Linux ha gia per gfx12 un modello migliore per Metal: le **user queue PM4 gfx+compute via MES** di amdgpu (`gfx_v12_0.c:1435-1446`), le cui soglie firmware sono soddisfatte esattamente dal firmware di questa scheda.
3. **mac-amdgpu e la migliore "specifica eseguibile" per il bring-up compute RDNA4 fuori da Linux**: sequenza di 15 stage (discovery -> IH -> GMC -> PSP/SOS/TMR -> firmware IP via PSP -> SMU -> IMU/RLC -> CP -> MES -> SDMA), code AQL mappate con `MES MAP_LEGACY_QUEUE` su VMID0, runtime HSA proprio. Per gfx1200 cambiano poco (ID PCI, check GC 12.0.1, MACH 0x4e->0x48, PSP/SMU 14.0.2, firmware `gc_12_0_0`/`sdma_7_0_0`); il passaggio DriverKit/Apple Silicon -> kext/x86 cambia le API ma semplifica (MMIO diretto, DMA host normale, doorbell mappabili). Gap principale: nessuna VM per processo.
4. **Toolchain LLVM per gfx1200 verificata**: clang 23.1.1 e rocm-llvm 22 generano code object **v6** (ABI version 4, flag 0x48), wave32 di default, kernel descriptor da 64 B con i campi gfx12 (`inst_pref_size`, `GLG_EN`, `IMAGE_OP`); ISA gfx12 con contatori di attesa separati, barrier split, ID workgroup architected in TTMP7/TTMP9.
5. **AIR di Apple -> LLVM AMDGPU diretto e fattibile** [VERIFICATO]: bitcode reale del compilatore Metal (Metal 4, AIR 2.8, `metalfe-32023.921`) letto da LLVM 23 upstream; con un lowering meccanico (triple, address space, builtin, barrier, atomici, LDS dinamica) tre kernel MSL reali girano correttamente sulla RX 9060 XT.
6. **Raccomandazione**: milestone compute-first con un kext che porta la sequenza di mac-amdgpu adattata a Navi 44, poi code PM4 user-mode con VM per processo via MES `ADD_QUEUE`; compilatore con uno strato comune di "AIR semantic lowering" e due backend: **LLVM AMDGPU per il compute subito**, **NIR/ACO per la grafica** in seguito.

---

## 1. amdkfd per gfx12 e cosa servirebbe su macOS

Sorgente: `KFD` = `research/src/linux/drivers/gpu/drm/amd/amdkfd` (master 7.3-rc). Il kernel in esecuzione e 7.2.9: dove il comportamento misurato differisce dal sorgente lo segnalo.

### 1.1 Architettura in breve

amdkfd non e un driver autonomo: e un "client" di amdgpu (interfaccia `kfd2kgd_calls`, per gfx12 `gfx_v12_kfd2kgd` in `LNX/amdgpu/amdgpu_amdkfd_gfx_v12.c`). amdgpu fa tutto il bring-up (PSP, SMU, GMC/VM, IH, firmware CP/MES, SDMA), poi chiama `kgd2kfd_device_init()` che espone `/dev/kfd` e la topologia. Per gfx12 KFD **non programma HQD direttamente**: aggiunge/rimuove code tramite il firmware MES (`adev->mes.funcs->add_hw_queue`). Conseguenza chiave per macOS: **un "port di KFD" presuppone un port quasi completo del core amdgpu** (PSP/SMU/GMC/IH/MES). La parte KFD vera e propria (code utente, eventi, memoria per processo, CWSR) e relativamente piccola.

### 1.2 Entry specifiche di GC 12.0.0 in `kfd_device.c` [VERIFICATO]

| Riga | Cosa | gfx1200 (12.0.0) | gfx1201 (12.0.1) |
|---|---|---|---|
| `kfd_device.c:464-471` (`kgd2kfd_probe`) | `gfx_target_version`, `f2g` | `120000`, `&gfx_v12_kfd2kgd` | `120001`, stesso `f2g` |
| `kfd_device.c:176-180` | `event_interrupt_class` | `&event_interrupt_class_v11` (commento `/* GFX12_TODO: Change to v12 version. */`) | idem |
| `kfd_device.c:235-237` | PCIe atomics | `needs_pci_atomics = true`, `no_atomic_fw_version = 2090` | idem |
| `kfd_device.c:200-205` (`kfd_device_info_init`) | SOC15 | `doorbell_size = 8`, `ih_ring_entry_size = 32`, `supports_cwsr = true`, `max_no_of_hqd = 24`, `num_of_watch_points = 4` | idem |
| `kfd_device.c:565-569` | trap handler CWSR | `cwsr_trap_gfx12_hex` (deve stare sotto `KFD_CWSR_TMA_OFFSET` = 4096+2048) | idem |
| `kfd_device.c:602-607` (`kfd_gws_init`) | GWS | `gws_size = 64` sempre per >= 12.0.0 (sysfs `num_gws 64` [VERIFICATO]) | idem |
| `kfd_device.c:110-115` | SDMA 7.0.0 | `num_sdma_queues_per_engine = 8`, `num_reserved_sdma_queues_per_engine = 2` (paging + gfx) -> 6 per KFD (sysfs: 6 [VERIFICATO]) | SDMA 7.0.1, idem |

**PCIe atomics** (`kfd_device.c:776-786`): se la root port non accetta AtomicOps e `mec_fw_version < no_atomic_fw_version`, KFD **rifiuta il device** (`"skipped device ... PCI rejects atomics"`). Il MEC installato e `0xd7a` = 3450 >= 2090, quindi con questo firmware KFD funzionerebbe anche senza atomics. Su un Hackintosh e importante: macOS non abilita AtomicOps sul percorso PCIe per device di terze parti, quindi **conviene usare firmware MEC >= 2090** (gia il caso) e non dipendere da atomics host<->GPU. Nella MQD `cp_hqd_hq_status0 |= 1 << 29` solo se `amdgpu_amdkfd_have_atomics_support()` (`kfd_mqd_manager_v12.c`, `init_mqd`).

### 1.3 Device queue manager con MES (gfx12) [VERIFICATO]

- `device_queue_manager_init()` (`kfd_device_queue_manager.c:3238`), ramo `default:` riga ~3338: per `>= 12.0.0` e `< 12.1.0` chiama `device_queue_manager_init_v12()` (`kfd_device_queue_manager_v12.c`, 90 righe). Con `enable_mes` la policy e HWS gestita da MES (`initialize_cpsch`/`start_cpsch`, righe 2008/2084).
- `kfd_device_queue_manager_v12.c`: solo tre hook ASIC:
  - `set_cache_memory_policy_v12`: `sh_mem_config = SH_MEM_ALIGNMENT_MODE_UNALIGNED << ALIGNMENT_MODE | 3 << INITIAL_INST_PREFETCH`; `sh_mem_bases = (lds_base >> 48) << SHARED_BASE | (scratch_base >> 48)` (`compute_sh_mem_bases_64bit`, riga 50). Le aperture LDS/scratch del flat address space sono quindi definite dai 16 bit alti dell'indirizzo.
  - `update_qpd_v12`, `init_sdma_vm_v12`: banali.
- `add_queue_mes()` (`kfd_device_queue_manager.c:207-283`) riempie `struct mes_add_queue_input` e chiama `adev->mes.funcs->add_hw_queue` (-> `mes_v12_0_add_hw_queue` che emette il pacchetto API `MES_SCH_API_ADD_QUEUE`). Campi essenziali (tutti da replicare in un driver macOS):
  - `process_id` (= PASID), `page_table_base_addr` (PD della VM del processo), `process_va_start/end`, `process_quantum = KFD_MES_PROCESS_QUANTUM` (unita 100 ns, 10 ms), `gang_quantum` (1 ms), `process_context_addr`/`gang_context_addr` (buffer di contesto MES per processo/gang),
  - `doorbell_offset`, `mqd_addr` (MQD in GART), `wptr_addr` (VA utente) e `wptr_mc_addr` (indirizzo MC del BO che contiene il write pointer: MES lo legge per sapere se la coda ha lavoro),
  - `is_kfd_process = 1`, `is_aql_queue`, `queue_size` in dword, `tba_addr`/`tma_addr` (trap handler), `trap_en`, `sh_mem_config_data`, `vm_cntx_cntl`, `queue_type` (compute/sdma), `exclusively_scheduled` (GWS).
- Mappa HQD vista da MES su questa scheda (ring MES dump `hw_dump/rings/decoded_mes_3.0.0.txt`, pacchetto `SET_HW_RSRC`: `vmid_mask_mmhub=0xff00`, `vmid_mask_gfxhub=0xff00`, `compute_hqd_mask[0]=0x0c`, `compute_hqd_mask[1]=0x0c`). Le VMID 8..15 sono gestite da MES per le code utente (KFD/userq); MES puo usare le code 2 e 3 di ciascuna delle 2 pipe MEC = 4 HQD compute, coerente con `num_cp_queues 4` in sysfs; le code 0-1 di ogni pipe restano alle kernel queue di amdgpu. [VERIFICATO]

### 1.4 MQD compute v12 (`kfd_mqd_manager_v12.c`) [VERIFICATO]

`init_mqd()` (riga 95) e `update_mqd()` (riga 183), struct `v12_compute_mqd` (`LNX/include/v12_structs.h`):
- `header = 0xC0310800`; `compute_static_thread_mgmt_se0..7 = 0xFFFFFFFF` (CU mask, poi `update_cu_mask`); `compute_pipelinestat_enable = 1`.
- `cp_hqd_persistent_state = PRELOAD_REQ | 0x55 << PRELOAD_SIZE` (+ `QSWITCH_MODE` se CWSR).
- `cp_hqd_pq_control = 5 << RPTR_BLOCK_SIZE | UNORD_DISPATCH | (log2(size_dw) - 1)`; per AQL `| NO_UPDATE_RPTR | 2 << SLOT_BASED_WPTR | QUEUE_FULL_EN`, e `cp_hqd_aql_control = 1 << CONTROL0`, `cp_hqd_pq_doorbell_control |= DOORBELL_BIF_DROP`.
- `cp_hqd_pq_base = queue_address >> 8`; `rptr_report_addr`, `wptr_poll_addr`; `cp_hqd_pq_doorbell_control = doorbell_off << DOORBELL_OFFSET`.
- `cp_hqd_eop_control = min(0xA, ffs(eop_size/4/4))` (commento: limite HW di 0xFF entry EOP), `cp_hqd_eop_base_addr = eop >> 8`; `eop_buffer_size = 4096` per gfx >= 8 (`kfd_queue.c:527`).
- CWSR: `cp_hqd_ctx_save_base_addr`, `cp_hqd_ctx_save_size`, `cp_hqd_cntl_stack_size/offset`, `cp_hqd_wg_state_offset` = `ctl_stack_size`.
- `cp_hqd_hq_status0 = 1 << 14` (`c_queue_debug_en`, CP imposta `DISPATCH_PTR`) [+ bit 29 con atomics].
- `cp_hqd_quantum = QUANTUM_EN | 1 << SCALE | 1 << DURATION`.
- `load_mqd` usa `wptr_shift = 4` per AQL (wptr conta pacchetti da 64 B) e 0 per PM4 (dword).

Confronto con MQD reale di una coda compute del kernel (non KFD) dumpata: `cp_hqd_pq_control=0xd030890a`, `cp_hqd_persistent_state=0x0be05501`, `cp_hqd_pq_doorbell_control=0x60000018` (`hw_dump/README.md` riga 59-60). Per la MQD di una coda KFD/AQL servirebbe un dump mentre `vadd_hip` gira (vedi domande aperte).

### 1.5 Doorbell [VERIFICATO]

- `doorbell_size = 8` (doorbell a 64 bit, `HSA_CAP_DOORBELL_TYPE_2_0` in sysfs). Le doorbell stanno in BAR2 (256 MB su questa scheda).
- `kfd_doorbell_process_slice()` (`kfd_doorbell.c:50`): con MES la slice per processo la decide `amdgpu_mes_doorbell_process_slice()`; senza MES sarebbe `roundup(8 * KFD_MAX_NUM_OF_QUEUES_PER_PROCESS(1024), PAGE_SIZE)` = 8 KiB.
- `allocate_doorbell()` (`kfd_device_queue_manager.c:544`): code compute -> indice libero nel bitmap del processo; code SDMA -> indice statico `sdma_doorbell_idx[engine] + (queue_id & 1) * KFD_QUEUE_DOORBELL_MIRROR_OFFSET(512) + (queue_id >> 1)`.
- `kfd_doorbell_mmap()` mappa la pagina doorbell del processo in user space: **l'utente scrive direttamente il wptr nella doorbell** (nessuna syscall per dispatch). In macOS l'equivalente e `IOMemoryDescriptor` su un sotto-range di BAR2 + `IOUserClient::clientMemoryForType()` / `IOConnectMapMemory64`.

### 1.6 CWSR e trap handler gfx12 [VERIFICATO]

- Sorgente `KFD/cwsr_trap_handler_gfx12.asm` (1556 righe), compilato con l'assembler proprietario AMD `sp3` (`cpp -DASIC_FAMILY=CHIP_GFX12 ... ; sp3 gfx12.sp3 -hex gfx12.hex`, righe 23-28): **non riassemblabile con LLVM**, ma il binario e incluso come `static const uint32_t cwsr_trap_gfx12_hex[]` in `KFD/cwsr_trap_handler.h:3646-4103` sotto licenza MIT (header righe 1-8): **riusabile tale e quale** in un kext.
- Lo stesso file serve gfx12.0 (`CHIP_GFX12`) e gfx12.5 (`CHIP_GC_12_0_3`); per gfx12.0: niente XNACK, indirizzi 48 bit, niente VGPR "banked", `RELAXED_SCHEDULING_IN_TRAP`, `HAVE_VALU_SGPR_HAZARD`. Nessuna differenza tra gfx1200 e gfx1201.
- Salva TTMP4..11 e TTMP13 (inizializzati dalla logica SPI; contengono tra l'altro gli ID workgroup architected in TTMP7/TTMP9) a offset `size(VGPR)+size(SGPR)+0x40` della save area prima di usarli come temporanei (righe 449-490).
- Layout TBA/TMA: 2 pagine GPU (`KFD_CWSR_TBA_TMA_SIZE`), TMA a `4096 + 2048` (`kfd_priv.h:106-107`).
- Dimensione save area (`kfd_queue_ctx_save_restore_size`, `kfd_queue.c:490-530`) per gfx 120000: per CU `VGPR 0x60000 + SGPR 0x4000 + LDS 0x10000 + HWREG 0x1000 = 0x75000`; `wave_num = cu_num * 32`; `ctl_stack = ALIGN(40 + wave_num*12 + 8, 4096)`. Con 32 CU: `ctl_stack_size = 16384`, `cwsr_size = 16384 + 32*0x75000 = 15 351 808` — **identico al valore sysfs misurato** [VERIFICATO]. Per Navi 48 (64 CU) la formula da ~29.4 MiB [INFERITO].
- La VGPR file per CU di gfx1200/gfx1201 (0x60000 = 384 KiB) e 1.5x quella di gfx10.3 (0x40000): da tenere presente per occupancy e per la save area.

Valutazione per macOS: CWSR serve per (a) preemption a livello di wave da parte di MES (time-slicing tra code/processi), (b) debugger. **Per un milestone compute iniziale si puo disabilitare** (KFD stesso ha `cwsr_enable` come parametro; MQD senza `QSWITCH_MODE` e senza save area): MES fa ancora scheduling ma senza preemption mid-wave; un kernel infinito bloccherebbe la coda. Per un driver Metal di produzione (WindowServer + app) CWSR o almeno preemption a livello di draw/dispatch e necessaria per evitare GPU hang percepiti.

### 1.7 Eventi, segnali e interrupt [VERIFICATO]

- gfx12 usa `event_interrupt_class_v11` (`kfd_int_process_v11.c`). `event_interrupt_isr_v11` (riga 258) filtra le entry IH (32 byte, IH 7.0) per VMID KFD e PASID != 0, scarta le EOP con `AMDGPU_FENCE_MES_QUEUE_FLAG`, e passa al workqueue: `SOC15_INTSRC_CP_END_OF_PIPE` -> `kfd_signal_event_interrupt(pasid, context_id0, 32)`; `SOC21_INTSRC_SDMA_TRAP` (28 bit); `SOC15_INTSRC_SQ_INTERRUPT_MSG` (24 bit, `s_sendmsg` dal shader); `SOC15_INTSRC_CP_BAD_OPCODE`.
- Gli eventi "signal" usano una **signal page** condivisa user/kernel: `KFD_SIGNAL_EVENT_LIMIT = 4096` slot da 8 byte (`kfd_events.c:49-140`, `kfd_event_page_set`). Il runtime HSA fa terminare un dispatch con un `RELEASE_MEM` (AQL: `completion_signal`) che scrive il valore del segnale e genera un interrupt EOP con `context_id` = ID evento; il kernel sveglia chi aspetta in `AMDKFD_IOC_WAIT_EVENTS`.
- Per macOS: l'IH ring 7.0 va servito da un `IOInterruptEventSource`/`IOFilterInterruptEventSource` (MSI) del kext; il wake-up verso user space puo essere un `IOUserClient` async (`sendAsyncResult64`) o un semaforo Mach. Metal (`MTLSharedEvent`, completion handler dei command buffer) mappa naturalmente su questo schema "fence in memoria + interrupt opzionale".

### 1.8 ABI ioctl di KFD (riferimento per un'eventuale emulazione) [VERIFICATO su `/usr/include/linux/kfd_ioctl.h`, KFD ioctl 1.22]

Magic `'K'`; numeri: `GET_VERSION 0x01`, `CREATE_QUEUE 0x02`, `DESTROY_QUEUE 0x03`, `SET_MEMORY_POLICY 0x04`, `UPDATE_QUEUE 0x07`, `CREATE_EVENT 0x08`, `DESTROY_EVENT 0x09`, `SET_EVENT 0x0A`, `RESET_EVENT 0x0B`, `WAIT_EVENTS 0x0C`, `SET_SCRATCH_BACKING_VA 0x11`, `GET_TILE_CONFIG 0x12`, `SET_TRAP_HANDLER 0x13`, `GET_PROCESS_APERTURES_NEW 0x14`, `ACQUIRE_VM 0x15`, `ALLOC_MEMORY_OF_GPU 0x16`, `FREE_MEMORY_OF_GPU 0x17`, `MAP_MEMORY_TO_GPU 0x18`, `UNMAP_MEMORY_FROM_GPU 0x19`, `SET_CU_MASK 0x1A`, `GET_QUEUE_WAVE_STATE 0x1B`, `IMPORT_DMABUF 0x1D`, `ALLOC_QUEUE_GWS 0x1E`, `SMI_EVENTS 0x1F`, `SVM 0x20`, `SET_XNACK_MODE 0x21`, `CRIU_OP 0x22`, `AVAILABLE_MEMORY 0x23`, `EXPORT_DMABUF 0x24`, `RUNTIME_ENABLE 0x25`, `DBG_TRAP 0x26`.
Il sottoinsieme minimo usato da ROCr per un dispatch: `GET_VERSION`, `GET_PROCESS_APERTURES_NEW`, `ACQUIRE_VM` (fd del render node), `ALLOC/MAP_MEMORY_OF_GPU` (VRAM, GTT, userptr, doorbell, MMIO remap), `CREATE_QUEUE` (AQL, ring + rptr/wptr + EOP + CWSR), `CREATE_EVENT`/`WAIT_EVENTS`, `SET_SCRATCH_BACKING_VA`, `SET_TRAP_HANDLER`, `RUNTIME_ENABLE`. Emulare questo ABI su macOS permetterebbe in teoria di ricompilare ROCr/HIP, ma richiede anche la topologia sysfs (`/sys/class/kfd`), che su macOS non esiste. mac-amdgpu infatti **non** emula l'ABI KFD: ha scritto un runtime HSA proprio sopra un `IOUserClient` (sezione 2.5).

### 1.9 Percorso alternativo gia presente in amdgpu: user queue MES (non KFD) [VERIFICATO]

`LNX/amdgpu/gfx_v12_0.c:1435-1446`: per GC 12.0.0/12.0.1 amdgpu registra `userq_mes_funcs` per `AMDGPU_HW_IP_GFX` **e** `AMDGPU_HW_IP_COMPUTE` se `!disable_uq && me_fw >= 3090 && pfp_fw >= 3190 && mec_fw >= 3450 && mes fw >= 147`. Il firmware installato soddisfa **esattamente** queste soglie (ME 0xc12=3090, PFP 0xc76=3190, MEC 0xd7a=3450, MES 0x93=147) [VERIFICATO]. Il parametro `amdgpu.user_queue` vale -1 (`/sys/module/amdgpu/parameters/user_queue` = -1 -> `disable_uq = true`, `gfx_v12_0_early_init`, riga ~3980), quindi oggi Linux usa ancora le kernel queue per Mesa. Questo percorso (`amdgpu_userq.c`, `mes_userqueue.c`, `amdgpu_userq_fence.c`) e il modello piu vicino a cio che un driver Metal vorrebbe: **code user-mode gfx e compute PM4 con doorbell e fence in memoria, gestite da MES, senza KFD/HSA**. Raccomando che il report di bring-up (01) e il piano lo considerino come architettura di submission target.

### 1.10 Cosa servirebbe per un "KFD su macOS" (stima)

| Componente | Linux | Equivalente macOS | Note |
|---|---|---|---|
| Core amdgpu (PSP/SMU/GMC/IH/MES/SDMA) | prerequisito | kext IOPCIDevice x86 | grosso del lavoro (report 01) |
| Process/VM per client | `kfd_process.c`, `amdgpu_vm` | VM GPU per `IOUserClient`/task | 4 livelli, 9-bit block, PASID |
| Code AQL utente via MES | `add_queue_mes`, MQD v12 | stesso codice portato | ADD_QUEUE/REMOVE_QUEUE MES API |
| Doorbell mmap | `kfd_doorbell_mmap` | `clientMemoryForType` su BAR2 | 64 bit |
| Eventi/segnali | signal page + IH EOP | shared memory + MSI + async | |
| CWSR | trap hex + save area 14.6 MiB/coda | stesso blob | opzionale per milestone 1 |
| Topologia `/sys/class/kfd` | sysfs | non esiste | serve un runtime che non la richieda |
| HMM/SVM, XNACK | `kfd_svm.c` (gfx12: `AMDGPU_VM_MTYPE_NC`, `AMDGPU_PTE_IS_PTE`) | non disponibile | da escludere |

Conclusione sezione 1: portare KFD "1:1" non ha senso; ha senso prendere da KFD (a) la logica `add_queue_mes` + MQD v12, (b) il blob CWSR gfx12, (c) lo schema signal-page/EOP, e metterli dietro un'interfaccia `IOUserClient` propria, consumata da un runtime minimale (come fa mac-amdgpu) o direttamente dal driver Metal.

---

## 2. mac-amdgpu: bring-up gfx1201 da PCIDriverKit e trasferibilita

Riferimento: `MAG` = `research/refs/mac-amdgpu` (codice di terze parti, solo letto). Release dichiarata 0.1.96; target **Radeon AI PRO R9700, PCI 1002:7551, gfx1201 (Navi 48)** su Mac Apple Silicon via Thunderbolt 5, macOS Tahoe 26.2+, SIP disabilitato, entitlement DriverKit PCI (`MAG/README.md` righe 1-200).

### 2.1 Architettura

| Strato | File | Ruolo |
|---|---|---|
| Host app Swift | `MAG/Host/MacAMDGPUHostApp.swift` (2608 righe) | attiva la system extension, **legge i firmware dal proprio bundle** (`Contents/Resources/firmware/`) e li passa alla dext, pilota il bring-up stage per stage |
| DriverKit extension (dext) | `MAG/dext/MacAMDGPU.cpp` (5288 righe) + `MAG/dext/amdgpu/*` (~75 file) | `IOService` su `IOPCIDevice`, `IOUserClient` con ~80 selector (`ExternalMethod`), port C++ dei blocchi amdgpu necessari al compute |
| Runtime HSA | `MAG/hsa/src/*` (runtime.cpp, queues.cpp, memory.cpp, executable.cpp, code_object.cpp, transport_iokit.cpp, gpu_signals.cpp ...) | sostituto di ROCr: implementa 119 entry point HSA richiesti da HRX/LSE (`MAG/hsa/API_STATUS.md`), parla con la dext via IOKit (`Transport`, `transport.h`) |
| Compilatore | LLVM upstream da Homebrew (21.1.8) + `ld.lld` (`MAG/docs/LSE_QUICKSTART.md` righe 11-20) | genera code object gfx1201 / gfx12-generic su macOS arm64 |

### 2.2 Sequenza di init (dext) [VERIFICATO sul codice]

`enum class BringupStage` (`MAG/dext/amdgpu/amdgpu_init.h:68-85`) e `run_stage()` (`MAG/dext/amdgpu/amdgpu_init.cpp:743-932`), che dichiara di rispecchiare `amdgpu_device_ip_init` (phase1 -> fw_loading -> phase2):

1. `IPDiscovery` — `discover_ips_on_die()`: legge `mmRCC_CONFIG_MEMSIZE`, copia la discovery binary dalla fine della VRAM attraverso la BAR e la parsa; fallback `LoadDiscoveryBin` da user space. Inizializza anche NBIF 6.3.1 (`nbif_v6_3_1_*`, remap HDP, doorbell aperture, range doorbell SDMA/IH/GC).
2. `IHInit` — `ih_init_full()` (`ih_v7_0.cpp`).
3. `GMCInit` — `gmc_init()` (`gmc_v12_0.cpp`, 1247 righe): solo MMHUB; **GFXHUB viene programmato piu tardi** (in `CPInit`) perche, se programmato prima del caricamento firmware, PSP rifiuta SDMA/CP/MES/RLC con `TEE_BAD_PARAMETERS` (commento righe 873-880).
4. `PSPInit` — `psp_init()` + `psp_read_runtime_db()` a `vram_size - 1 MiB`; **buffer firmware in VRAM** (non GTT) perche su Apple Silicon + TB5 le letture GPU di memoria host via DART restituivano 0 (commento righe 783-799).
5. `PSPLoadSOS` — `psp_load_sos()` (bootloader: KDB, SPL, SYS_DRV, SOC_DRV, INTF_DRV, DBG_DRV, RAS_DRV, IPKEYMGR_DRV, SOS; selector `LoadFirmware` con `kMacAMDGPUFwTypeSOS..TA`, `MacAMDGPU.cpp:184-193`).
6. `PSPRingCreate` — ring PSP + `psp_query_fw_reservation()` (`GFX_CMD_ID_FB_FW_RESERV_ADDR/EXT_ADDR`).
7. `TMRSetup` — `psp_setup_tmr()`.
8. `PSPFwLoad` — solo validazione: i firmware IP sono gia stati inviati dall'host con `LoadFirmware` (codici `0x100 + psp_gfx_fw_type`, file multi-payload `0x200 + n` espansi da `amdgpu_ucode_extract.cpp`). Ordine obbligatorio (commento `MacAMDGPUHostApp.swift:2420-2430`): TA (ASD) -> SMU -> SDMA -> CP PFP/ME/MEC (RS64 + stack) -> MES uni (`gc_*_uni_mes.bin`, due frame: ucode e data) -> IMU I/D -> RLC (ultimo, scatena `AUTOLOAD_RLC`). Fuori ordine PSP risponde 0x5 e poi 0xFFFF0006.
9. `SMUInit` — `smu_test_message()`, `smu_get_version()`, `smu_smc_hw_setup()` (`smu_v14_0.cpp`, scritto per SMU 14.0.3).
10. `IMUInit` — solo verifica (IMU caricato da PSP via `LOAD_IP_FW(IMU_I/IMU_D)`).
11. `RLCInit` — `rlc_wait_for_autoload_complete()`.
12. `CPInit` — `cp_prepare_firmware()`, poi `gmc_gfxhub_gart_enable()` + HDP flush + TLB flush VMID0, `gart_init()`, `gfx_constants_init()`, `rlc_init_full()`.
13. `MESInit` — `cp_start_engines()` + `mes_init_full()` (`mes_v12_1.cpp`: `mes_set_hw_resources`, `mes_set_hw_resources_1`, `mes_kiq_setting`, `mes_enable_unmapped_doorbell_handling`, `mes_init_aggregated_doorbell`, `mes_query_sched_status`).
14. `GFXInit` — `cp_init_full()` (mappa la coda GFX via MES/KIQ).
15. `SDMAInit` — `sdma_init_full()` (`sdma_v7_0.cpp`).

I nomi dei firmware sono derivati dalle versioni IP scoperte (`"psp_\(psp)_sos.bin"`, `"gc_\(gfx)_mec.bin"`, `"sdma_\(sdma).bin"`, `MacAMDGPUHostApp.swift:2345-2450`), con gestione delle varianti `_kicker` per `(0x744B,0x00)` e `(0x7551,0xC8)` (`kickerDeviceList`, riga 1051). La cartella `MAG/firmware/` contiene gia i blob per Navi 44: `gc_12_0_0_{imu,me,mec,mes,mes1,pfp,rlc,toc,uni_mes}.bin`, `psp_14_0_2_{sos,ta}.bin`, `smu_14_0_2.bin`, `sdma_7_0_0.bin` [VERIFICATO con `ls`].

### 2.3 Memoria [VERIFICATO sul codice]

- Tutte le strutture di bootstrap (ring, MQD, EOP, fence, firmware buffer) stanno in **VRAM visibile**, scritte dalla CPU attraverso BAR0 con verifica rilettura (`vram_write_verified`, `amdgpu_vram_io.h`: "DriverKit's PCI memory accessors return void, so verify staged writes"), seguite da `amdgpu_hdp_flush()`.
- GTT: `IOBufferMemoryDescriptor` + `IODMACommand` per BO di dominio `kBODomainGTT` (`MacAMDGPU.cpp:269-303`), mappati nella GART di VMID0; usato per staging host da 4 MiB per connessione (`MAG/docs/HSA_MAPPED_TRANSFER.md`).
- **Nessuna VM per processo**: `amdgpu_aql_abi.h:5-6` "Bounded, owner-only VMID0 dispatch ... not ... an isolation boundary". Tutti i client condividono VMID0 (GART + VRAM fisica); gli indirizzi GPU dei kernel sono indirizzi MC VRAM. Le aperture LDS/scratch sono fissate a `kAQLGroupApertureHi = 0x10000`, `kAQLPrivateApertureHi = 0x20000` (`amdgpu_aql_resources.h:12-13`).
- BO: `BOAlloc/BOFree/BOMap/BOExport/BOImport` (condivisione cross-process con token casuale a 128 bit), mappatura CPU per-BO via `CopyClientMemoryForType`.
- Niente Resizable BAR su macOS ("no public Apple BAR-resizing API", README riga ~130): lavorano con la finestra BAR assegnata.

### 2.4 Code e dispatch [VERIFICATO sul codice]

- Topologia: `kGFX1201ComputePipes = 2`, `kGFX1201QueuesPerPipe = 4`, `kPersistentAQLQueues = 7` (slot 1..7; `amdgpu_queue_topology.h:7-11`). Coincide con Linux `gfx_v12_0_sw_init` per **12.0.0 e 12.0.1** (`mec.num_pipe_per_mec = 2`, `num_queue_per_pipe = 4`, `LNX/amdgpu/gfx_v12_0.c:1415-1424`) [VERIFICATO], quindi vale anche per Navi 44.
- Le code AQL **non** usano `MES ADD_QUEUE` con contesto di processo (come KFD): usano `mes_map_legacy_queue(dev, mes, 1, pipe, queue, doorbell, mqd_addr, wptr_addr)` (`amdgpu_aql.cpp:150-152`), cioe la API MES `MAP_LEGACY_QUEUE` sulla pipe KIQ della MES unificata, con una MQD costruita da `aql_build_mqd()` che riprende la MQD v12 di KFD (`CP_HQD_HQ_STATUS0 = 0x00004000`: bit 14 si, bit 29 no, come KFD senza atomics, `docs/PCIE_ATOMIC_TEST_POLICY.md`).
- Doorbell: `kAQLDoorbell = 0x80`, slot `kAQLDoorbell + slot*2` (doorbell da 64 bit = 2 dword). **Il doorbell lo scrive la dext** (`aql_queue_kick` -> `dev.pci->MemoryWrite64(bar2MemIndex, ...)`, `amdgpu_aql.cpp:172-185`); lato runtime la `doorbell_signal` HSA ha uno `storeHook` che chiama `kickQueue` via IOKit (`hsa/src/queues.cpp:237-240`, riga 93). Quindi ogni "ring" costa una chiamata user->dext (IPC Mach), a differenza di KFD dove l'utente scrive la doorbell mappata.
- Pacchetto AQL, kernarg e descriptor in BO VRAM; `amd_queue_t` (layout ROCr) validato dalla dext (`aql_queue_open`, righe 106-163): scratch allocato dalla dext (mai fidarsi di indirizzi scratch dati dall'utente), `max_cu_id`, `max_wave_id`, `queue_inactive_signal`.
- Completamento: polling di `amd_signal_t` in VRAM (`vram_read_fence64`), IRQ "assisted wakeup" ancora in validazione (README "Upcoming"). Segnali CPU<->GPU con un **mailbox mediato dalla GPU** perche su TB5 le RMW atomiche concorrenti CPU/GPU non funzionano (`docs/ATOMIC_MAILBOX_SERVICE.md`, `PCIE_ATOMIC_TEST_POLICY.md`; 1 000 000 round trip in 222 s = ~4.5k round trip/s).
- SDMA: ring QUEUE0 programmato direttamente; tabella offset scelta a runtime (`sdma_pick_reg_table()`, `amdgpu_sdma.h:167-176`): GC 12.0.x -> offset `gc_12_0_0` (`QUEUE0_RB_CNTL = 0x0080`), GC 12.1.x -> `gc_12_1_0` (0x0200). Attenzione: i commenti in testa a `amdgpu_sdma.h`/`sdma_v7_0.cpp` dicono ancora che R9700 usa il percorso `sdma_v7_1`/`gc_12_1_0`, ma **upstream** mappa SDMA 7.0.0 e 7.0.1 su `sdma_v7_0_ip_block` (`LNX/amdgpu/amdgpu_discovery.c:2833-2835`) con header `gc_12_0_0` (`sdma_v7_0.c:33-34`) e il codice effettivo di mac-amdgpu fa lo stesso: commenti obsoleti, codice corretto anche per SDMA 7.0.0 di Navi 44 [VERIFICATO].

### 2.5 Runtime HSA sostitutivo [VERIFICATO sul codice]

- `Transport` astratto (`hsa/src/transport.h:58-92`): `allocateBuffer/freeBuffer/readBuffer/writeBuffer`, `allocateSharedBuffer`, `createQueue/kickQueue/destroyQueue/serviceQueue`, `dispatchAQL`, `copyBuffers` (SDMA), `exportBuffer/importBuffer`, `invalidateCodeCaches`. Implementazione `transport_iokit.cpp` (833 righe) con `IOConnectCallMethod`.
- Loader ELF proprio (`code_object.cpp:153-170`): accetta solo `e_machine 224`, `EI_ABIVERSION 1..4`, e **solo** `EF_AMDGPU_MACH == 0x4e` (gfx1201) oppure `0x59` + `generic_v1` (gfx12-generic); rifiuta TLS; carica segmenti `PT_LOAD`, legge metadati msgpack.
- `isa.cpp:43` espone `"amdgcn-amd-amdhsa--gfx1201"`; `device_init.cpp:16,36,83` rifiuta device diversi da `1002:7551` e GC diverso da `{12,0,1}`.
- Code AQL user-mode di 64..4096 pacchetti, scratch/LDS dinamici, segnali GPU-backed, IPC di memoria, profiling via timestamp nei completion signal (`tools/rocprofmac`). Le parti "senza piattaforma" (SVM, DMA-BUF, interop) restituiscono errore.

### 2.6 Cosa e specifico di gfx1201/R9700 e cosa cambia per gfx1200/Navi 44

| Punto | mac-amdgpu (Navi 48) | RX 9060 XT (Navi 44) | Azione |
|---|---|---|---|
| PCI ID | `0x7551` hard-coded (`device_init.cpp:16`, `MacAMDGPU.cpp:1949`, `amdgpu_atomic_requester.h:34`) | `0x7590` rev c0 | generalizzare |
| GC | check `== {12,0,1}` in `amdgpu_aql.cpp:19,112`, `amdgpu_dispatch.cpp:18`, `amdgpu_compute_test.cpp:26`, `amdgpu_arch_capabilities.h:29`, `device_init.cpp:36,83` | `{12,0,0}` | accettare 12.0.0 |
| ISA / loader | `EF_AMDGPU_MACH 0x4e`, nome `gfx1201` | `0x48`, `gfx1200` (generic 0x59 identico) | aggiungere 0x48 |
| PSP | 14.0.3, SOS 14_0_3 (+kicker) | **14.0.2**, `psp_14_0_2_sos.bin`, SOS `0x003b0f0d` | `FB_FW_RESERV` richiesto anche qui: upstream lo fa per 14.0.2 se SOS >= 0x3b0e0d (`amdgpu_psp.c:1078-1081`) -> soddisfatto |
| SMU | 14.0.3, `kCompatibleFirmware = 0x00684c00` (104.76.0) per le metriche (`amdgpu_metrics.h:14`) | **14.0.2**, SMC 102.71.0, `driver_if 0x2e` (= `SMU14_DRIVER_IF_VERSION_SMU_V14_0_2`, `smu_v14_0_2_ppt.c:74`) | metriche/PPTable da rivalidare; messaggi base uguali (stesso `smu_v14_0_2_ppt.c` upstream per 14.0.2 e 14.0.3) [INFERITO] |
| SDMA | 7.0.1, `sdma_7_0_1.bin` | 7.0.0, `sdma_7_0_0.bin` | stesso codice (tabella gc_12_0_0) |
| GC firmware | `gc_12_0_1_*` (+ `_kicker` rlc/imu) | `gc_12_0_0_*`, niente kicker per 7590 | nomi gia derivati da discovery |
| NBIF / HDP / IH | NBIF 6.3.1, HDP 7.0.0, IH 7.0.0 | identici | nessuna |
| Topologia MEC | 2 pipe x 4 code | identica | nessuna |
| CU / SE | 64 CU, 4 SE [INFERITO] | 32 CU, 2 SE x 2 SH x 8 CU; RB 8; `gb_addr_config 0x08200545` | `gfx12_compute_masks()` e i limiti scratch leggono dai registri: ok se la discovery e corretta |
| VRAM / BAR | 32 GB, BAR piccola via TB5 | 16 GB, ReBAR attivo su Linux (BAR0 = 16 GB) | su Hackintosh la BAR dipende da firmware/OpenCore (vedi 2.7) |

### 2.7 Trasferibilita a un kext x86 per Hackintosh

**Riutilizzabile quasi 1:1 (logica, non API):**
- La sequenza di bring-up compute (stage 1-15) e l'ordine di caricamento firmware via PSP: e la parte piu preziosa, perche e "Linux amdgpu ridotto al minimo per fare compute" gia debuggato su RDNA4. Per Navi 44 cambiano solo i nomi file e i check di versione.
- Pacchetti MES (`amdgpu_mes_packets.h`), MQD AQL (`aql_build_mqd`), codifica PM4 (`amdgpu_pm4.h`), pacchetti SDMA (`amdgpu_sdma_packets.h`), estrazione ucode (`amdgpu_ucode_extract.cpp`).
- Il runtime HSA e il loader code object come base per un milestone "compute-first" (HIP/OpenCL-like) o come strumento di test del driver.

**Da riscrivere per x86 kext (IOKit in-kernel invece di DriverKit):**
- `IOPCIDevice::MemoryRead/Write` della dext -> mapping diretto delle BAR (`IODeviceMemory`/`mapDeviceMemoryWithIndex`) con accesso MMIO a puntatore: piu veloce, niente IPC per registro.
- Doorbell: su un kext si puo mappare la pagina doorbell (BAR2) nel task utente (`IOMemoryDescriptor::createMappingInTask` / `clientMemoryForType`) e lasciare che l'utente scriva il wptr direttamente come in KFD: elimina la syscall per dispatch (mac-amdgpu paga un IPC Mach per ogni kick).
- Interrupt: `IOInterruptDispatchSource` -> `IOFilterInterruptEventSource` su MSI/MSI-X.
- DMA host: su x86 Hackintosh tipicamente VT-d e disattivato o `DisableIoMapper`, quindi gli indirizzi fisici da `IODMACommand`/`getPhysicalSegment` vanno direttamente nella GART; il problema DART/TB5 (letture GPU di sysmem a 0) **non dovrebbe esistere** [INFERITO]: GTT e memoria host coerente (snooped) tornano disponibili, come su Linux.
- PCIe AtomicOps: su AM5 la root port Zen 4 supporta tipicamente i completer atomici a 32/64 bit [INFERITO], e un kext puo abilitare `AtomicOp Requester Enable` in DevCtl2 del GPU (e degli switch interni) dopo aver verificato routing/completer, come `pci_enable_atomic_ops_to_root()`. Con MEC >= 2090 KFD non li richiede (sezione 1.2); il mailbox di mac-amdgpu resta il fallback.
- Per-process VM: mac-amdgpu gira tutto in VMID0. Per un driver Metal multi-applicazione (WindowServer + app) serve **una VM GPU per task** (VMID 8-15 gestite da MES, page table a 4 livelli, PASID) e quindi `MES ADD_QUEUE` con `page_table_base_addr`/`process_context_addr` come KFD (sezione 1.3), non `MAP_LEGACY_QUEUE`. Questo e il principale gap architetturale.
- Resizable BAR: su macOS x86 OpenCore offre `Booter > Quirks > ResizeAppleGpuBars` e `UEFI > Quirks > ResizeGpuBars`; la documentazione OpenCore indica che macOS gestisce male BAR grandi (limite pratico 1 GB) [INFERITO, da verificare nel report di bring-up]. Il codice di mac-amdgpu funziona con BAR piccola (scritture VRAM via finestra BAR + SDMA), quindi e un buon modello anche se la BAR0 resta a 256 MB.

**Non trasferibile / non necessario:** l'app host SwiftUI e il flusso System Extension (un kext si carica con OpenCore `Kernel > Add`), gli entitlement DriverKit, il workaround DART, il mailbox per atomics (opzionale), la telemetria pinned a SMU 14.0.3.

Giudizio: mac-amdgpu e la migliore "specifica eseguibile" disponibile per un bring-up compute RDNA4 fuori da Linux. La differenza gfx1201 -> gfx1200 e piccola (ID, nomi firmware, PSP/SMU 14.0.2, MACH 0x48); la differenza DriverKit/Apple Silicon -> kext/x86 e grande nelle API ma semplifica il problema (MMIO diretto, DMA host normale, niente TB5).

---

## 3. Backend LLVM AMDGPU per gfx1200: compilazione, code object, kernel descriptor

### 3.1 Toolchain disponibili sulla macchina [VERIFICATO]

| Toolchain | Versione | Target gfx12 riconosciuti da `llc -mcpu=help` |
|---|---|---|
| `/usr/bin/clang` (upstream) | `clang version 23.1.1`, LLVM 23.1.1 | `gfx1200 gfx1201 gfx1250 gfx1251 gfx12-generic gfx12-5-generic` (+ feature `gfx12-insts`, `gfx1200-insts`) |
| `/opt/rocm/llvm/bin/clang` (rocm-llvm) | `AMD clang version 22.0.0git` (commit `f58b06dce1f9`) | `gfx1200 gfx1201 gfx1250 gfx1251 gfx12-generic` |
| `hipcc` | HIP 7.2.53211-3d9ef42 (usa rocm-llvm) | `--offload-arch=gfx1200` |

Device libs (ocml/ockl/opencl) in `/opt/rocm/amdgcn/bitcode/*.bc`: necessari per OpenCL/HIP (senza, `-nogpulib` lascia simboli `get_global_id` non risolti al link — errore riprodotto). Per IR scritto a mano non servono.

Sorgenti di test (miei, in `SCR/src/`): `vadd.cl` (vadd + riduzione LDS 256 elementi con `barrier`), `vadd_hsa.ll` (kernel IR a mano con `llvm.amdgcn.workitem.id.x`, `llvm.amdgcn.workgroup.id.x`, `llvm.amdgcn.dispatch.ptr`), `ps_mesa.ll`/`ps_pal.ll` (stesso `amdgpu_ps` con triple `amdgcn-mesa-mesa3d` e `amdgcn-amd-amdpal`), `vadd.hip`.

Comandi usati (riproducibili):
```
clang -x cl -cl-std=CL2.0 -target amdgcn-amd-amdhsa -mcpu=gfx1200 -O3 --rocm-path=/opt/rocm vadd.cl -o vadd_cl.hsaco
clang -target amdgcn-amd-amdhsa -mcpu=gfx1200 -O3 -c vadd_hsa.ll -o vadd_ir.o && ld.lld -shared vadd_ir.o -o vadd_ir.hsaco
clang -target amdgcn-mesa-mesa3d -mcpu=gfx1200 -O2 -S ps_mesa.ll -o ps_mesa.s
hipcc --offload-arch=gfx1200 -O2 vadd.hip -o vadd_hip
llvm-readelf -h --notes vadd_cl.hsaco ; llvm-objdump -D -j .rodata vadd_cl.hsaco ; llvm-objdump -d vadd_cl.hsaco
```
Nota: un `amdgpu_ps` dentro un modulo `amdgcn-amd-amdhsa` fallisce con `unsupported non-compute shaders with HSA` [VERIFICATO]: per shader grafici si deve usare la triple `amdgcn-mesa-mesa3d` (radeonsi) o `amdgcn-amd-amdpal` (PAL/AMDVLK), che hanno ABI diverse (PAL emette metadati msgpack `.amdgpu_pal_metadata` con i valori dei registri `SPI_SHADER_PGM_RSRC*`; mesa3d emette coppie registro/valore `.long 45096 / 165608 ...` nella sezione `.AMDGPU.config`).

### 3.2 Code object: versione, header ELF, note [VERIFICATO]

`llvm-readelf -h vadd_cl.hsaco`:
```
OS/ABI:      AMDGPU - HSA          (ELFOSABI_AMDGPU_HSA = 64)
ABI Version: 4                     (= ELFABIVERSION_AMDGPU_HSA_V6, cioe code object v6)
Type:        DYN (Shared object file)
Machine:     EM_AMDGPU (224)
Flags:       0x48, gfx1200         (EF_AMDGPU_MACH_AMDGCN_GFX1200 = 0x048, nessun bit xnack/sramecc)
```
- **Default di clang 23 e rocm-llvm 22 = code object v6** (senza `-mcode-object-version` si ottiene ABI Version 4). Misurato con `-mcode-object-version=4/5/6`: ABI 2/3/4; metadati `amdhsa.version` = `[1,1]` per v4, `[1,2]` per v5 **e anche per v6** (v6 cambia solo l'header ELF e abilita i target "generic").
- `-mcpu=gfx12-generic` produce `Flags: 0x1000059, gfx12-generic, generic_v1` (MACH 0x059, `EF_AMDGPU_GENERIC_VERSION`=1 nei bit 24..31). rocminfo elenca l'ISA `amdgcn-amd-amdhsa--gfx12-generic` come seconda ISA dell'agent, quindi un code object generic gira sia su gfx1200 sia su gfx1201.
- Sezioni: `.note` (NT_AMDGPU_METADATA, msgpack, 0xa0c byte), `.dynsym`, `.rodata` (kernel descriptor da 64 byte, allineati a 64), `.text` (allineato a 256), `.AMDGPU.gpr_maximums`.
- Simboli: per ogni kernel `vadd_cl` (FUNC, entry) + `vadd_cl.kd` (OBJECT, 64 B). Con clang 23 OpenCL compare anche `__clang_ocl_kern_imp_vadd_cl` (FUNC): il corpo del kernel viene emesso come funzione chiamabile separata (per consentire chiamate kernel->kernel di OpenCL), e il loader deve ignorarla.
- Note msgpack per kernel (estratto `vadd_cl`): `.kernarg_segment_size: 288`, `.group_segment_fixed_size: 0`, `.private_segment_fixed_size: 0`, `.sgpr_count: 10`, `.vgpr_count: 6`, `.wavefront_size: 32`, `.uses_dynamic_stack: false`, `.symbol: vadd_cl.kd`; target `amdhsa.target: amdgcn-amd-amdhsa-unknown-gfx1200`. `lds_reduce`: `.group_segment_fixed_size: 1024`, kernarg 272.

### 3.3 Kernel descriptor gfx12 (64 byte) [VERIFICATO]

Byte grezzi di `vadd_cl.kd` (offset file 0xdc0):
```
00000000 00000000 20010000 00000000 40120000 00000000 00000000 00000000
00000000 00000000 00000000 20000000 000fe084 00000000 08040000 00000000
```
Decodifica (layout `amd_kernel_code_t`/`kernel_descriptor_t` COV3+, `llvm/Support/AMDHSAKernelDescriptor.h`):

| Offset | Campo | Valore | Significato |
|---|---|---|---|
| 0x00 | `group_segment_fixed_size` | 0 | LDS statica |
| 0x04 | `private_segment_fixed_size` | 0 | scratch per lane |
| 0x08 | `kernarg_size` | 288 | 32 B espliciti + 256 B impliciti COV5 |
| 0x10 | `kernel_code_entry_byte_offset` | 0x1240 | entry = indirizzo KD + 0x1240 = 0x2000 |
| 0x2c | `compute_pgm_rsrc3` | 0x00000020 | gfx12: `INST_PREF_SIZE`=2 (bit 4..11), niente `SHARED_VGPR_COUNT` |
| 0x30 | `compute_pgm_rsrc1` | 0xe00f0000 | VGPR/SGPR granule, `FLOAT_DENORM_MODE_32/16_64`=3, `WGP_MODE`=1, `MEM_ORDERED`=1, `FWD_PROGRESS`=1 |
| 0x34 | `compute_pgm_rsrc2` | 0x00000084 | `USER_SGPR_COUNT`=2 (kernarg ptr), `TGID_X_EN`=1 |
| 0x38 | `kernel_code_properties` | 0x0408 | `ENABLE_SGPR_KERNARG_SEGMENT_PTR` + `ENABLE_WAVEFRONT_SIZE32` |

`llvm-objdump -D -j .rodata` decodifica il KD in direttive `.amdhsa_*`, tra cui le specifiche gfx12: `.amdhsa_inst_pref_size`, `.amdhsa_workgroup_processor_mode 1`, `.amdhsa_memory_ordered 1`, `.amdhsa_forward_progress 1`, `.amdhsa_round_robin_scheduling 0`, `.amdhsa_wavefront_size32 1`, commenti `GLG_EN` e `IMAGE_OP` (nuovi bit di `COMPUTE_PGM_RSRC3` in gfx12). **Wave32 e il default per gfx12** (`wavefront_size: 32`); wave64 resta possibile con `-mattr=+wavefrontsize64`.

Rilevanza per il driver: un kernel descriptor non e altro che il contenuto dei registri `COMPUTE_PGM_LO/HI`, `COMPUTE_PGM_RSRC1/2/3`, `COMPUTE_USER_DATA_*`. Con le code AQL questi campi li legge il CP (firmware MEC, microcodice "AQL"); con code PM4 (come fa RADV/radeonsi) il driver li scrive esplicitamente con `PKT3_SET_SH_REG` prima del `PKT3_DISPATCH_DIRECT`. Quindi un code object LLVM puo essere lanciato anche senza runtime HSA, purche il driver rispetti l'ABI dei user SGPR e il layout dei kernarg impliciti (sezione 3.5).

### 3.4 ISA gfx12 osservata nel disassemblato [VERIFICATO]

`llvm-objdump -d --disassemble-symbols=vadd_cl vadd_cl.hsaco` (estratto):
```
s_clause 0x2
s_load_b32 s4, s[0:1], 0x2c          ; hidden_group_size_x (u16) dai kernarg impliciti
s_load_b64 s[2:3], s[0:1], 0x48      ; hidden_global_offset_x
s_load_b32 s5, s[0:1], 0x18          ; argomento n
s_wait_kmcnt 0x0                     ; gfx12: contatori separati (sostituisce s_waitcnt lgkmcnt)
s_and_b32 s4, s4, 0xffff
s_delay_alu instid0(SALU_CYCLE_1) | instskip(NEXT) | instid1(VALU_DEP_1)
v_mad_co_u64_u32 v[0:1], null, ttmp9, s4, v[0:1]   ; workgroup_id_x letto da TTMP9!
...
v_cmpx_gt_u32_e32 s5, v0
s_cbranch_execz 34
global_load_b32 v2, v[1:2], off
global_load_b32 v3, v[3:4], off
s_wait_loadcnt 0x0                   ; gfx12: s_wait_loadcnt/storecnt/samplecnt/bvhcnt/kmcnt/dscnt/expcnt
v_add_f32_e32 v2, v2, v3
global_store_b32 v[0:1], v2, off
s_endpgm
```
Punti chiave di gfx12 che impattano driver e compilatore:
1. **Architected SGPRs**: in gfx12 l'ID del workgroup arriva in `TTMP9` (x) e `TTMP7` (y in [15:0], z in [31:16]) invece che in SGPR utente; `rsrc2.TGID_X_EN` resta settato ma il valore viene letto da TTMP. Conseguenza: il trap handler (CWSR) **deve preservare TTMP7/TTMP9** e non puo usarli liberamente come su gfx10 (vedi 1.6). Questo vale identico per gfx1200 e gfx1201.
2. **Contatori di attesa separati** (`s_wait_loadcnt`, `s_wait_storecnt`, `s_wait_kmcnt`, `s_wait_samplecnt`, `s_wait_bvhcnt`, `s_wait_dscnt`, `s_wait_expcnt`) e `s_wait_alu depctr_*`: l'encoding e diverso da RDNA2/3, quindi nessun binario gfx10/11 e riusabile; serve un compilatore che conosca gfx12 (LLVM >= 18 o ACO di Mesa >= 24.x).
3. `s_delay_alu` (introdotto in gfx11) obbligatorio per le dipendenze VALU.
4. Encoding `VGLOBAL`/`VBUFFER`/`VIMAGE`/`VSAMPLE` nuovi in gfx12 (MUBUF/MTBUF/MIMG riorganizzati), `v_dual_*` (VOPD) disponibile come in gfx11 (visto in `ps_main`: `v_dual_mov_b32 v2, 0 :: v_dual_mov_b32 v3, 1.0`).
5. **Nessuna differenza di ISA osservabile tra gfx1200 e gfx1201** nel backend: in LLVM gfx1201 e gfx1200 condividono `FeatureISAVersion12` (verificabile con `-mcpu=gfx12-generic` che li copre entrambi); le differenze sono nei parametri del chip (numero di CU/SE/RB, dimensione L2/MALL), non nel set di istruzioni [INFERITO da generic + rocminfo; LLVM elenca gfx1200 e gfx1201 nello stesso generic].

### 3.5 ABI di dispatch che un runtime "fatto in casa" deve rispettare [VERIFICATO sul codice generato]

- User SGPR in ordine fisso (abilitati da `kernel_code_properties`): private segment buffer (su gfx11/12 lo scratch e "architected flat scratch" e questo slot non viene richiesto [INFERITO]), dispatch ptr (`s[0:1]` nel kernel IR `vadd_ir`, che lo usa per leggere `workgroup_size_x` a offset 4 del pacchetto AQL), queue ptr, kernarg segment ptr (`s[2:3]` in `vadd_ir`, `s[0:1]` in `vadd_cl`), dispatch id, flat scratch init (non su gfx12), private segment size.
- `vadd_ir.hsaco`: `.amdhsa_user_sgpr_dispatch_ptr 1`, `.amdhsa_kernarg_size 28` (nessun argomento implicito perche IR a mano). Il codice legge `s_load_b32 s0, s[0:1], 0x4` = `hsa_kernel_dispatch_packet_t.workgroup_size_x`. Quindi se il kernel richiede `dispatch_ptr`, il runtime deve fornire in memoria un pacchetto AQL valido anche se la coda e PM4.
- Kernarg impliciti COV5 (256 B dopo gli espliciti allineati a 8): osservati `hidden_block_count_x` a +0, `hidden_group_size_x` (u16) a +12 (= 0x2c in `vadd_cl`), `hidden_global_offset_x` a +40 (= 0x48). OpenCL/HIP li usano sempre; Metal non ne ha bisogno: un front-end AIR->AMDGPU dovrebbe usare intrinseci (`llvm.amdgcn.workgroup.id.*`, `workitem.id.*`) e passare le dimensioni del threadgroup come argomenti espliciti o costanti, cosi il driver Metal non deve emulare l'HSA ABI.
- `.amdhsa_workgroup_processor_mode 1` (WGP mode, 2 CU che condividono LDS da 128 KB per WGP; rocminfo riporta comunque 64 KB per workgroup) e `.amdhsa_forward_progress 1` sono default di gfx10+.


---

## 4. Test runtime su RX 9060 XT: rocminfo, topologia KFD e HIP vector-add

### 4.1 rocminfo (ROCm 7.2.4, runtime HSA 1.18) [VERIFICATO]

Output completo salvato in `SCR/out/rocminfo.txt`. Agent GPU 1 (la iGPU Raphael gfx1036 e l'agent 2):

| Campo | Valore | Commento |
|---|---|---|
| Name / Marketing | `gfx1200` / `AMD Radeon RX 9060 XT` | Chip ID 0x7590, ASIC Revision 1 |
| Compute Unit / SIMDs per CU | 32 / 2 | 16 WGP; HIP `multiProcessorCount` riporta **16** (conta WGP) |
| Shader Engines / Arrays per SE | 2 / 2 | coerente con IP discovery |
| Cache L1 / L2 / L3 | 32 KB / 4096 KB / 32768 KB | L3 = MALL/Infinity Cache 32 MB di Navi 44 (Navi 48: 64 MB, L2 8 MB [INFERITO da specifiche pubbliche]) |
| Cacheline | 256 B | |
| Max Clock | 2700 MHz | |
| Wavefront / WG max / Max waves per CU | 32 / 1024 / 32 | |
| Queue: Max number / min / max size | 128 / 64 / 131072 pacchetti | `Queue Type: MULTI` |
| Segment GLOBAL | 16 695 296 KB, COARSE GRAINED | `Coherent Host Access: FALSE` |
| Segment GROUP (LDS) | 64 KB | |
| ISA 1 / ISA 2 | `amdgcn-amd-amdhsa--gfx1200` / `amdgcn-amd-amdhsa--gfx12-generic` | |
| Packet Processor uCode | 378 | = MEC fw 0xd7a & 0x3ff |
| SDMA engine uCode | 662 | = SDMA fw 0x00798e96 & 0x3ff |
| IOMMU Support | None | su AM5 l'IOMMU non e usato da KFD per dGPU |
| XNACK | NO | niente retry-fault/page migration on demand |

### 4.2 Topologia KFD da sysfs (lettura non privilegiata) [VERIFICATO]

`/sys/class/kfd/kfd/topology/nodes/1/properties` (nodo con `gfx_target_version 120000`):
```
simd_count 64; max_waves_per_simd 16; lds_size_in_kb 64; gds_size_in_kb 0; num_gws 64;
wave_front_size 32; array_count 4; simd_arrays_per_engine 2; cu_per_simd_array 8; simd_per_cu 2;
max_slots_scratch_cu 32; gfx_target_version 120000; device_id 30096; location_id 768;
drm_render_minor 128; num_sdma_engines 2; num_sdma_queues_per_engine 6; num_cp_queues 4;
cwsr_size 15351808; ctl_stack_size 16384; max_engine_clk_fcompute 2700; fw_version 3450;
capability 1749262976 (0x6843a280); capability2 0; debug_prop 1495 (0x5d7);
sdma_fw_version 36502; num_xcc 1
mem_banks/0: heap_type 1 (FB_PUBLIC); size_in_bytes 17095983104; width 128; mem_clk_max 1258
```
Decodifica di `capability` 0x6843a280 con `/usr/include/linux/kfd_sysfs.h`: `WATCH_POINTS_SUPPORTED` (0x80), `WATCH_POINTS_TOTALBITS`=2 (4 watchpoint), `DOORBELL_TYPE`=2 (`HSA_CAP_DOORBELL_TYPE_2_0`, doorbell a 64 bit), `TRAP_DEBUG_SUPPORT`, `TRAP_DEBUG_WAVE_LAUNCH_TRAP_OVERRIDE_SUPPORTED`, `TRAP_DEBUG_WAVE_LAUNCH_MODE_SUPPORTED`, `ASIC_REVISION`=1, `SVMAPI_SUPPORTED`, `TRAP_DEBUG_FIRMWARE_SUPPORTED`, `TRAP_DEBUG_PRECISE_ALU_OPERATIONS_SUPPORTED`. **Assenti**: `PER_QUEUE_RESET_SUPPORTED`, `FLAGS_COHERENTHOSTACCESS`, `MEM_EDCSUPPORTED`.

Numeri utili per dimensionare un port:
- `cwsr_size` = 15 351 808 B (~14.6 MiB) **per coda** compute: e la save area CWSR (stato di tutte le wave di tutti i CU + control stack). Per un driver macOS e memoria da allocare per ogni coda user-mode se si vuole la preemption a livello di wave.
- `ctl_stack_size` = 16 384 B.
- `num_cp_queues` = 4: HQD compute assegnati a KFD (coerente con `compute_hqd_mask 0x0c` di MES su 2 pipe... vedi 1.3); `num_sdma_queues_per_engine` = 6 (coerente con `sdma_hqd_mask 0xfc`, 6 code per engine).
- `/dev/kfd` e `crw-rw-rw- root:render 237,0`: KFD e accessibile senza privilegi su questa distro.

### 4.3 HIP vector-add [VERIFICATO, eseguito in questa sessione]

`SCR/src/vadd.hip` compilato con `hipcc --offload-arch=gfx1200 -O2` (sezione `.hip_fatbin` di 0x2460 byte con il code object gfx1200). Esecuzione (`SCR/out2/vadd_hip`):
```
device 0: AMD Radeon RX 9060 XT gcnArchName=gfx1200 CUs=16 warpSize=32 major.minor=12.0 pciBus=03 clock=2700000kHz mem=16304 MiB
device 1: AMD Ryzen 7 7700 8-Core Processor gcnArchName=gfx1036 CUs=1 ...
vadd n=16777216 iters=50 avg=0.6714 ms effective=299.9 GB/s mismatches=0 -> PASS
1000 tiny launches + sync: 3.821 ms (3.82 us/launch)
```
(il run precedente aveva dato 0.6685 ms / 301.2 GB/s / 3.83 us: risultati stabili).

Interpretazione:
- 3 buffer x 64 MiB per iterazione = 192 MiB in 0.67 ms = ~300 GB/s, cioe ~94% del picco teorico GDDR6 20 Gbps x 128 bit = 320 GB/s. Il working set (192 MiB) supera la MALL da 32 MB, quindi e una misura di banda DRAM: **la catena KFD -> MES -> MEC/AQL -> wave32 funziona pienamente su gfx1200** con il firmware installato.
- ~3.8 us per lancio (coda AQL user-mode, doorbell scritta da user space, nessuna syscall per dispatch) e il riferimento di latenza da battere/eguagliare con un design macOS a code user-mode.
- Nessun problema specifico di Navi 44 osservato: ROCm 7.2 supporta ufficialmente gfx1200.


---

## 5. AIR (Apple LLVM bitcode) -> LLVM AMDGPU diretto vs AIR -> SPIR-V -> ACO

### 5.1 Le due strade

- **A. AIR -> SPIR-V -> (RADV/ACO o Vulkan)**: quella di Cobalt64 (Metal-on-Vulkan) e di metal2vulkan. Riusa tutto Mesa (NIR, ACO, RADV, gestione descrittori, pipeline grafiche) ma passa per due IR di traduzione e per l'API Vulkan.
- **B. AIR -> LLVM IR "AMDGPU" -> backend LLVM AMDGPU -> ISA gfx1200**: AIR *e gia* LLVM IR (bitcode con triple `air64`), quindi in teoria basta un passo di "retargeting": cambiare triple/datalayout, rimappare address space, sostituire gli intrinseci `air.*` con `llvm.amdgcn.*`/istruzioni LLVM, abbassare l'ABI degli argomenti (metadati `!air.kernel`), poi `llc -mcpu=gfx1200`.
- Variante **B'**: AIR -> NIR (front-end scritto da noi che legge LLVM IR) -> ACO. Non analizzata a fondo qui (report 03/08), ma citata nelle raccomandazioni.

### 5.2 Esperimento: AIR reale Apple eseguito su RX 9060 XT tramite LLVM upstream [VERIFICATO]

Input: fixture generate dal compilatore Apple presenti in `research/refs/metal2vulkan/crates/metal2vulkan-validation/fixtures/public/engine/` (407 file `.air.ll` + 5 `.air` binari; li ho solo letti/copiati come dati in `SCR/air_in`).

1. **Compatibilita bitcode**:
   - `.air` binari (es. `ob3_stage_input.air`): wrapper bitcode `0x0B17C0DE`, triple `air64_v28-apple-macosx26.0.0`, `!llvm.ident = "Apple metal version 32023.921 (metalfe-32023.921.6)"`, `!air.version = {2, 8, 0}`, `!air.language_version = {"Metal", 4, 0, 0}`. `llvm-bcanalyzer -dump`: `IDENTIFICATION` con stringa producer **vuota** ed `EPOCH 0`, `MODULE VERSION 2`, tipi puntatore **typed** (`<POINTER op0=pointee op1=addrspace>`, non `OPAQUE_POINTER`).
   - `llvm-dis` 23.1.1 upstream legge **tutti e 5** i `.air` senza errori, con auto-upgrade a puntatori opachi (`ptr addrspace(1) ... captures(none)`).
   - `llvm-as` 23.1.1 accetta anche il testo AIR typed-pointer (`i32 addrspace(1)*`) prodotto da `metal-dis` (fixture `.air.ll`, versioni compilatore `32023.883` x52 e `32023.921` x90).
   - `opt` rifiuta il modulo finche la triple e `air64_v28` (`opt: unrecognized architecture 'air64_v28' provided`): bisogna **prima** riscrivere triple e datalayout. Datalayout AIR: `e-p:64:64:64-...-n8:16:32` (nessun address space distinto); datalayout AMDGPU usato: `e-m:e-p:64:64-p1:64:64-p2:32:32-p3:32:32-p4:64:64-p5:32:32-...-A5-G1-ni:7:8:9`.
2. **Lowering**: script mio `SCR/scripts/air2amdgpu.py` (~180 righe, livello testo, solo prova di fattibilita) dopo `llvm-dis | sed triple/datalayout | opt -passes=instnamer`:
   - legge `!air.kernel` e i descrittori argomento (`air.buffer` + `air.address_space`, builtin `air.thread_position_in_grid`, `air.thread_index_in_threadgroup`...);
   - `define void @k(...)` -> `define amdgpu_kernel void @k(...)` con i soli buffer come argomenti kernarg (`"air-buffer-no-alias"` -> `noalias`);
   - builtin -> `llvm.amdgcn.workitem.id.x`, `llvm.amdgcn.workgroup.id.x`, dimensione workgroup letta dal pacchetto AQL (`llvm.amdgcn.dispatch.ptr` + 4);
   - `threadgroup` dinamico (`[[threadgroup(0)]]`, address space 3 come argomento) -> global LDS esterno `[0 x i8] addrspace(3)` (dimensione passata al lancio);
   - `air.wg.barrier(i32 flags, i32 scope)` -> `fence syncscope("workgroup") release` + `llvm.amdgcn.s.barrier` + `fence ... acquire`; `air.simdgroup.barrier` -> fence `wavefront` + `llvm.amdgcn.wave.barrier`;
   - `air.atomic.global.add.u.i32(ptr, val, i32 order, i32 scope, i1 volatile)` -> `atomicrmw volatile add ... syncscope("agent") monotonic`; `air.atomic.global.store.i32` -> `store atomic volatile ... monotonic`; `air.min.u.i32` -> `llvm.umin.i32`; `addrspace(2)` (constant AIR) -> `addrspace(4)`.
3. **Compilazione**: `clang -target amdgcn-amd-amdhsa -mcpu=gfx1200 -O3 -c` + `ld.lld -shared` -> `SCR/air_work/air_kernels.hsaco` (6864 B, 3 kernel, code object v6). ISA generata: `global_atomic_add_u32 ... th:TH_ATOMIC_RETURN scope:SCOPE_DEV`, `global_store_b32 ... scope:SCOPE_DEV`; barrier gfx12 split `s_barrier_signal -1` / `s_barrier_wait 0xffff` seguito da `global_inv scope:SCOPE_SE` (acquire a livello workgroup in WGP mode); `ds_store_b32`/`ds_load_b32` per threadgroup memory. Nota: gli attributi AIR `"frame-pointer"="all"` fanno emettere `s_mov_b32 s33, 0` (frame pointer inutile): un lowering serio deve ripulire gli attributi di funzione.
4. **Esecuzione su GPU** (`SCR/src/run_air.hip`, `hipModuleLoad` + `hipModuleLaunchKernel` con `HIP_LAUNCH_PARAM_BUFFER_POINTER`):
```
a4_simdgroup_barrier: PASS (out[0..3]=4 1 10 7)      // out[t] = 3*(t^1)+1, threadgroup mem + simdgroup_barrier
ob1_buffer_atomic: PASS (ctr[0]=10 olds=0 4 1 6)      // atomic_fetch_add relaxed device, 2 gruppi x 2 thread
ob1_threadgroup: PASS (out[0]=0xc0000007 out[7]=0xc0000000) // threadgroup dinamico + threadgroup_barrier
ALL PASS
```
**Conclusione dell'esperimento**: kernel MSL compilati dal compilatore Metal di Apple (Metal 4, AIR 2.8) girano correttamente sulla RX 9060 XT passando per il backend LLVM AMDGPU upstream, con una trasformazione puramente meccanica. Il "core" compute di AIR e quindi abbassabile direttamente a gfx1200.

### 5.3 Address space: mappa obbligatoria [VERIFICATO: enum `AddrSpace` in `metal2vulkan-air/src/ir/types.rs:150-166`; AMDGPU dal datalayout]

| AIR | Significato Metal | AMDGPU | Note |
|---|---|---|---|
| 0 `thread` | privata (alloca, stack) | **5** `private` (scratch) | in AMDGPU lo 0 e *flat/generic*: gli `alloca` AIR in AS0 vanno riscritti in AS5 (datalayout `A5`), poi `InferAddressSpaces` |
| 1 `device` | buffer R/W | 1 `global` | uguale |
| 2 `constant` | buffer read-only | **4** `constant` | in AMDGPU il 2 e `region` (GDS): collisione, va rimappato |
| 3 `threadgroup` | LDS | 3 `local` | uguale; dinamico -> extern LDS |
| 4 `threadgroup_imageblock` | tile memory (TBDR Apple) | 3 (emulazione su LDS) o rifiuto | in AMDGPU il 4 e `constant`: collisione |
| 6 `object_data` | payload object->mesh | LDS / ring task-payload di gfx12 | solo pipeline mesh |
| 7 mesh output | handle opaco | n/a | solo pipeline mesh |

### 5.4 Intrinseci AIR da abbassare

Statistiche sulle 407 fixture `.air.ll` (748 nomi distinti dichiarati; famiglie con piu occorrenze di dichiarazione): `air.convert` 281, `air.sample_texture_2d` 79, `air.atomic` 65, `air.read_texture_2d` 58, `air.get_read_sampler` 55, `air.write_texture_2d` 43, `air.wg` (barrier) 37, `air.simdgroup_matrix_8x8_multiply_accumulate` 27, `air.simdgroup_matrix_8x8_load` 23, `air.dot` 22, `air.fma` 20, `air.discard_fragment` 20, `air.pack` 17, `air.gather_texture_2d` 15, `air.get_simdgroup_size` 14, `air.simd_sum` 13 ... [VERIFICATO con grep]. Il front-end metal2vulkan dichiara un "closed set" di ~326 nomi base in `metal2vulkan-air/src/intrinsics/*.rs` (10 270 righe).

| Famiglia AIR | Lowering verso AMDGPU | Difficolta |
|---|---|---|
| builtin argomenti (`thread_position_in_grid`, `threads_per_threadgroup`, `threadgroup_position_in_grid`, `thread_index_in_simdgroup`, `simdgroup_index_in_threadgroup`, `threads_per_grid`...) | `workitem.id.*`, `workgroup.id.*` (in gfx12 da TTMP7/9), dimensioni dal kernarg o da un "dispatch packet" fornito dal driver, lane id con `llvm.amdgcn.mbcnt.lo/hi` | bassa |
| aritmetica/conversioni (`air.convert.*`, `air.fma`, `air.min/max/clamp`, `air.pack/unpack`) | istruzioni LLVM / `llvm.*`; semantiche di saturazione e rounding di Metal da rispettare | bassa-media |
| math (`sin/cos/tan/atan2/pow/sqrt/rsqrt/...`, `fast_*`) | `llvm.*` + libreria (ocml di ROCm-Device-Libs, licenza aperta) per le precise; `fast_*` -> `llvm.amdgcn.sin/cos/rsq/rcp/exp2/log2` (attenzione: `v_sin_f32` prende l'angolo in giri). Metal compila con `air.compile.fast_math_enable` di default | media (precisione) |
| barrier/fence (`air.wg.barrier`, `air.simdgroup.barrier`, `air.atomic.fence`) | `fence syncscope(...)` + `s.barrier`/`wave.barrier` (verificato) | bassa |
| atomici buffer/threadgroup (`air.atomic.global.*`, `air.atomic.local.*`) | `atomicrmw`/`cmpxchg`/`load/store atomic` con `syncscope("agent"/"workgroup")` (verificato add/store) | bassa |
| SIMD-group (`simd_sum/prefix/shuffle*/ballot/broadcast/any/all`, `quad_*`) | `llvm.amdgcn.readlane/readfirstlane`, `ds.bpermute`, `update.dpp`/`mov.dpp8`, `ballot`, `wave.reduce.*`. **simd width Metal = 32 = wave32 di gfx12**: corrispondenza esatta di `thread_execution_width` | media |
| `simdgroup_matrix_8x8_*` e 16x16x16 (Metal 4) | WMMA gfx12 (`llvm.amdgcn.wmma.f32.16x16x16.f16` ecc., wave32); 8x8 richiede impacchettamento/emulazione | media-alta |
| texture/sampler (`sample/read/write/gather/get_width...`, atomici su texture) | `llvm.amdgcn.image.*` con descrittori T# (256 bit su gfx12) e S# (128 bit) caricati da memoria: **richiede di definire l'ABI dei descrittori del driver Metal** (argument buffer, `MTLResourceID`) | alta (ABI) |
| function constants (`is_function_constant_defined`, `normalize_function_constant_predicate`) | specializzazione prima del codegen (sostituzione con costanti) | bassa |
| vertex/fragment/mesh (`discard_fragment`, interpolazione, `set_position_mesh`...) | convenzioni `amdgpu_vs/ps/gs/hs` + export (`llvm.amdgcn.exp`), interpolazione (`lds.param.load`/`interp.inreg.*` su gfx11+), stato SPI/PA: **tutto il "linkage" grafico va scritto a mano** (in Mesa lo fanno `ac_nir_*` + ACO/radeonsi) | molto alta |
| ICB / ray tracing (`set_*_command`, `intersect*`) | GPU-driven command (PM4 da shader), BVH (`image_bvh*_intersect_ray` di gfx12) | molto alta, fuori scope iniziale |

### 5.5 Compatibilita bitcode Apple LLVM vs upstream: rischi

- [VERIFICATO] Oggi (metalfe-32023.x, Xcode 26-27, AIR 2.8) il reader upstream 23 legge il bitcode Apple. La compatibilita e garantita solo "in avanti" dal lato upstream (LLVM legge bitcode di versioni precedenti); se Apple emettesse record/attributi piu nuovi di quelli noti all'LLVM che usiamo, il reader fallirebbe. Mitigazione: pinnare la versione di LLVM, testare ogni nuova Xcode, oppure usare un reader proprio come metal2vulkan (che ha un bitstream reader in Rust e gestisce anche `TYPE_OPAQUE_POINTER` = 25 per AIR futuri).
- [VERIFICATO] Puntatori typed nel bitcode Apple: upstream li converte in opachi; il tipo dei pointee si perde (metal2vulkan conserva una `PointeeTable` apposta, `bitcode/types.rs`), ma per AMDGPU non serve.
- [INFERITO] Metadati `!air.*` e attributi stringa (`"air-buffer-no-alias"`, `"approx-func-fp-math"`) sono ignorati dall'upstream: nessun errore, ma vanno interpretati da noi. Intrinseci `air.*` sono semplici `declare` (non intrinseci LLVM registrati), quindi non danno errori di verifica.
- [INFERITO] I `.metallib` contengono AIR per funzione (e opzionalmente sorgente/reflection); su macOS, il driver riceve AIR dal `MTLCompilerService` di Apple (front-end MSL->AIR resta di Apple), e il backend del vendor viene chiamato con l'AIR: e esattamente il punto in cui un backend "AIR->gfx1200" si inserirebbe (vedi report 05/06/08 per l'aggancio).

### 5.6 Pro e contro di B (AIR -> LLVM AMDGPU) rispetto ad A (AIR -> SPIR-V -> ACO)

| Criterio | B: AIR -> LLVM AMDGPU | A: AIR -> SPIR-V -> NIR -> ACO |
|---|---|---|
| Numero di traduzioni | 1 (LLVM -> LLVM, stesso IR) | 3 (LLVM -> SPIR-V -> NIR -> ACO IR) |
| Compute | **dimostrato funzionante** (5.2) con lavoro minimo; WMMA, atomici, subgroup tutti esposti in LLVM | funziona (RADV), ma passa per le limitazioni di SPIR-V/Vulkan (puntatori, memoria, subgroup size) |
| Grafica (VS/FS/mesh) | LLVM ha solo l'ISA; il linkage (export, interpolazione, stato SPI, NGG/primitive shader obbligatorio su gfx11+) va reimplementato a mano | ACO + `ac_nir_*` di Mesa gestiscono gia NGG, export, interpolazione, VRS, tess, per gfx12 |
| Qualita codice | LLVM AMDGPU buono per compute (e cio che usa ROCm); per grafica radeonsi-LLVM e piu lento di ACO a compilare | ACO compila molto piu in fretta (importante per compilazione JIT di pipeline Metal) |
| Dimensione / dipendenze | LLVM AMDGPU (~30-60 MB di libreria) dentro il processo di compilazione su macOS: Apple ha gia un LLVM (Apple) nel sistema ma non con target AMDGPU, quindi va spedita una libLLVM propria (mac-amdgpu usa LLVM Homebrew 21.1.8 su macOS arm64) | Mesa (NIR+ACO) e piu leggero e si porta su Darwin (Cobalt64 lo ha fatto) |
| Licenza | Apache 2.0 con eccezione LLVM | MIT (Mesa) |
| Rischio bitcode | dipende dalla compatibilita del reader con Apple LLVM (oggi ok) | uguale se si legge il bitcode con LLVM; nullo con reader proprio |
| Debug | strumenti LLVM (`llc`, `llvm-objdump`, `-print-after-all`) | NIR_DEBUG/ACO_DEBUG, RGP-like via Mesa |


---

## 6. Raccomandazioni: percorso compute e strategia del compilatore shader

### 6.1 Percorso compute (milestone "compute-first")

**R1 — Fare del compute il primo milestone funzionale su macOS, prima del display accelerato e della grafica.** Motivi: (a) mac-amdgpu dimostra che il bring-up compute RDNA4 fuori da Linux e fattibile e ne fornisce l'ordine esatto; (b) non richiede DCN, NGG, stato grafico, ne l'integrazione con WindowServer; (c) produce subito un banco di prova per memoria, code, MES, fence e per il compilatore shader.

**R2 — Base del bring-up: portare la sequenza di mac-amdgpu (stage 1-15) in un kext IOKit x86, non KFD.**
- Adattamenti Navi 44 (tabella 2.6): accettare GC 12.0.0 e PCI 0x7590; firmware `gc_12_0_0_*`, `psp_14_0_2_{sos,ta}`, `smu_14_0_2`, `sdma_7_0_0`, `gc_12_0_0_uni_mes` (i nomi sono gia derivati dalla discovery); PSP 14.0.2 con query `FB_FW_RESERV` (SOS 0x003b0f0d >= 0x3b0e0d); loader che accetti `EF_AMDGPU_MACH 0x48`.
- Sostituzioni API: MMIO a puntatore diretto (BAR5), doorbell BAR2 mappabili in user space, `IOFilterInterruptEventSource` per IH 7.0, `IODMACommand` per GTT. Sfruttare che su x86 la DMA verso memoria host e normale (niente workaround DART/TB5) [INFERITO, da verificare al primo test SDMA host<->VRAM].
- Primo obiettivo misurabile: SDMA copy VRAM<->host e un dispatch compute (es. `vadd_ir.hsaco` di questo report, che non richiede kernarg impliciti) su una coda mappata con `MAP_LEGACY_QUEUE`, completamento via `RELEASE_MEM` + polling. Oracolo: gli stessi kernel girano gia su Linux (sezione 4.3/5.2).

**R3 — Secondo passo: code user-mode con VM per processo, sul modello amdgpu userq/KFD.**
- `MES ADD_QUEUE` con `page_table_base_addr` (VM a 4 livelli, PASID, VMID 8-15 gestite da MES), `process_context_addr`/`gang_context_addr`, MQD v12 (sezione 1.4), doorbell 64 bit mappata nel task, wptr in memoria condivisa.
- Fence/eventi: slot in memoria condivisa scritti da `RELEASE_MEM` + interrupt EOP opzionale con `context_id` -> wake-up via `IOUserClient` async. Questo e anche il modello naturale per `MTLCommandBuffer` completion handler e `MTLSharedEvent`.
- CWSR: inizialmente disabilitato; poi abilitato riusando `cwsr_trap_gfx12_hex` (MIT) con save area di 15 351 808 B per coda (formula 1.6) e TBA/TMA da 2 pagine.
- PCIe AtomicOps: non richiesti con MEC >= 2090 (MEC attuale 3450). Abilitarli solo dopo verifica routing (open question).

**R4 — Formato coda per Metal: PM4, non AQL.** AQL e il formato dell'HSA ABI (dispatch packet, kernarg impliciti, completion signal). Un driver Metal ha bisogno di un unico formato per compute e grafica, con controllo diretto dei registri `COMPUTE_PGM_LO/HI`, `COMPUTE_PGM_RSRC1/2/3`, `COMPUTE_USER_DATA_*`, `COMPUTE_NUM_THREAD_X/Y/Z`, `DISPATCH_DIRECT/INDIRECT`, `ACQUIRE_MEM`, `RELEASE_MEM` (come fa RADV, report 03). AQL resta utile solo per un runtime di test HSA-like (riuso di `MAG/hsa`). Linux stesso offre user queue PM4 gfx+compute via MES per gfx12 (`gfx_v12_0.c:1435-1446`), con soglie firmware soddisfatte dalla scheda: e il riferimento architetturale da seguire.

**R5 — Non emulare l'ABI KFD/ROCr su macOS.** Richiederebbe sysfs di topologia, `mmap` di doorbell/eventi con semantica Linux, HMM/SVM. HIP/OpenCL su macOS non sono un obiettivo del progetto; se servisse un runtime compute generico, partire dal runtime di mac-amdgpu (119 entry point HSA) generalizzato a gfx1200.

### 6.2 Strategia del compilatore shader

**R6 — Un unico strato "AIR semantic lowering" e due backend.**
- Strato comune (indipendente dal backend): lettura del bitcode AIR (LLVM upstream pinnato, oppure reader proprio per robustezza), interpretazione dei metadati `!air.*` (kernel/vertex/fragment, argomenti, builtin, `air.compile.*`), specializzazione delle function constant, **definizione dell'ABI risorse del driver** (come buffer, texture `MTLResourceID`, sampler, argument buffer arrivano allo shader: tabella di descrittori in memoria puntata da user SGPR), regole di precisione/fast-math di Metal.
- **Backend 1 (compute, subito): AIR -> LLVM AMDGPU -> gfx1200.** Dimostrato funzionante (5.2). Da implementare come pipeline di pass C++ (non testo): retarget, rimappatura address space (0->5 per alloca, 2->4, 4->3/rifiuto), riscrittura argomenti in un ABI del driver (user SGPR + kernarg espliciti: niente `dispatch_ptr` ne kernarg impliciti HSA, cosi funziona con code PM4), tabella intrinseci (5.4), pulizia attributi (`frame-pointer`), poi `-mcpu=gfx1200` (o `gfx12-generic` per un binario unico 9060/9070) e lettura del kernel descriptor per programmare `COMPUTE_PGM_RSRC*`. Vantaggi: WMMA e subgroup esposti direttamente, qualita del codice ROCm, tooling LLVM.
- **Backend 2 (grafica, dopo): AIR -> NIR -> ACO** (via SPIR-V con un traduttore tipo metal2vulkan/Cobalt64, oppure con un front-end AIR->NIR dedicato). Motivo: il backend LLVM AMDGPU espone l'ISA ma non il "linkage" grafico (NGG/primitive shader, export, interpolazione, stato SPI/PA, VRS, tessellation) che Mesa ha gia per gfx12 in `ac_nir_*` + ACO; inoltre ACO compila molto piu in fretta, cosa importante per pipeline Metal create a runtime. Il backend LLVM puo restare come oracolo e per kernel compute pesanti; Mesa stesso mantiene `ac_nir_to_llvm` con supporto GFX12 (`MESA/src/amd/llvm/ac_nir_to_llvm.c:2672,2968`), quindi anche "NIR -> LLVM" e un'opzione di ripiego.
- **wave32 ovunque**: `thread_execution_width` Metal = 32 = wave32 gfx12 (default LLVM e ACO). Nessun bisogno di wave64.

**R7 — Toolchain di sviluppo raccomandata (gia verificata qui):** LLVM/clang 23.1 upstream (o rocm-llvm 22) con `-mcpu=gfx1200`, code object v6; `llvm-objdump -d` e `-D -j .rodata` per ISA e KD; `llvm-readelf --notes` per i metadati; `llvm-bcanalyzer`/`llvm-dis` per AIR; HIP `hipModuleLoad` su Linux come banco di prova per kernel prodotti dal nostro compilatore prima di averli su macOS. Su macOS serve una libLLVM con target AMDGPU (Homebrew LLVM la include: mac-amdgpu usa LLVM 21.1.8) da distribuire con il bundle Metal del driver.

**R8 — Test di regressione:** riusare le 407 fixture `.air.ll` di metal2vulkan (generate da `.metal` reali, con risultati attesi descritti nei commenti) come corpus: per ogni fixture compute, lowering -> gfx1200 -> esecuzione via HIP su Linux -> confronto. Ho gia una pipeline funzionante per 3 fixture (`SCR/scripts/air2amdgpu.py`, `SCR/src/run_air.hip`).

### 6.3 Riepilogo differenze Navi 44 vs Navi 48 rilevanti per il compute

| Aspetto | Navi 44 (questa scheda) | Navi 48 |
|---|---|---|
| ISA / LLVM | gfx1200, MACH 0x48, `gfx_target_version 120000` | gfx1201, MACH 0x4e, 120001 |
| Binari | stesso ISA; `gfx12-generic` (0x59) copre entrambi | idem |
| CU / save area CWSR | 32 CU -> 15 351 808 B per coda | 64 CU -> ~29.4 MiB [INFERITO] |
| MEC topologia | 1 MEC x 2 pipe x 4 code | identica |
| Firmware | `gc_12_0_0_*`, `psp_14_0_2`, `smu_14_0_2`, `sdma_7_0_0` | `gc_12_0_1_*` (+kicker), `psp_14_0_3`, `smu_14_0_3`, `sdma_7_0_1` |
| KFD | stesse entry di 12.0.1 (event class v11, CWSR gfx12, atomics fw 2090, GWS 64) | idem |
| L2 / MALL | 4 MB / 32 MB (rocminfo) | 8 MB / 64 MB [INFERITO] |
| VGPR per CU | 0x60000 (384 KiB) | identico |


---

## 7. Domande aperte

Dati privilegiati che servirebbero (non raccolti: regole "no sudo / non toccare lo stato GPU"):
1. `sudo lspci -vvv -s 03:00.0` e delle porte a monte (switch PCIe interno della GPU e root port AM5): `DevCap2` (AtomicOp completer 32/64), `DevCtl2` (AtomicOp Requester Enable, gia attivato da amdgpu?), per decidere se un kext macOS puo abilitare gli atomics PCIe. Insieme a `dmesg | grep -i -E "kfd|atomic"` per vedere se `pci_atomic_requested` e vero su Linux.
2. Dump di una MQD **KFD/AQL** reale e dei pacchetti MES `ADD_QUEUE` mentre `vadd_hip` gira: `sudo cat /sys/kernel/debug/kfd/mqds`, `/sys/kernel/debug/kfd/hqds`, `/sys/kernel/debug/dri/1/amdgpu_mes_*` (o ring MES) durante l'esecuzione. Servono come oracolo per R3 (oggi abbiamo solo le MQD delle kernel queue in `hw_dump/mqd`).
3. Indirizzi effettivi delle aperture LDS/scratch del processo KFD (`AMDKFD_IOC_GET_PROCESS_APERTURES_NEW` si puo chiamare senza root da un mio programma: fattibile in una fase successiva) e `sh_mem_bases` risultante.
4. Valore di `amdgpu.user_queue`: provare su Linux `amdgpu.user_queue=1` (richiede reboot con parametro, quindi fuori dalle regole di questa fase) per validare le user queue MES gfx/compute su questa scheda come modello per macOS.

Domande di progetto:
5. ABI risorse del driver Metal (texture/sampler/argument buffer -> descrittori T#/S# gfx12): va deciso prima di estendere il backend oltre i buffer. Coordinare con i report 03 (RADV descriptor layout) e 08.
6. Dove gira il compilatore su macOS: nel processo `MTLCompilerService` (plugin del bundle Metal del vendor, come fa Apple con il suo backend AMD) o in un servizio proprio? Impatta la distribuzione di libLLVM (dimensione, firma).
7. Su Hackintosh, la BAR0 sara 256 MB o resizable (OpenCore `ResizeAppleGpuBars`/`ResizeGpuBars`)? Il design deve funzionare con BAR piccola (come mac-amdgpu): scritture VRAM via SDMA/finestra.
8. Compatibilita futura del bitcode AIR: Xcode successivi potrebbero emettere bitcode non leggibile da LLVM upstream pinnato; serve un test automatico su nuove versioni del compilatore Metal (non disponibile su questa macchina Linux).
9. `HSA_CAP_PER_QUEUE_RESET_SUPPORTED` assente su questa macchina (kernel 7.2.9) ma impostato per 12.0.0 nel sorgente 7.3-rc (`kfd_topology.c:2024-2029`): verificare con un kernel piu recente; rilevante per il recovery da hang di una singola coda.
10. Differenze di comportamento MES tra 12.0.0 e 12.0.1 (stesso `mes_v12_0.c` upstream, firmware diversi `gc_12_0_0_uni_mes.bin` vs `gc_12_0_1_uni_mes.bin`): non osservabili senza test su entrambe le schede.

---

## Appendice A. Artefatti prodotti (scratchpad, temporanei)

Radice: `/tmp/claude-1000/-home-pastasugo89-Documenti-rx9060xt-metal-driver/75517241-da08-4a95-9813-eba8a30820e6/scratchpad/compute`

| File | Contenuto |
|---|---|
| `src/vadd.cl`, `src/vadd_hsa.ll`, `src/ps_mesa.ll`, `src/ps_pal.ll`, `src/vadd.hip` | sorgenti di test (sezione 3-4) |
| `out2/vadd_cl.hsaco`, `out2/vadd_ir.hsaco`, `out2/cov{4,5,6}.hsaco`, `out2/generic.hsaco`, `out2/ps_mesa.s` | code object gfx1200 / gfx12-generic e assembly PS |
| `out2/vadd_hip`, `out/hip_run.txt`, `out/rocminfo.txt` | test HIP e output rocminfo |
| `air_in/*.air` | copie dei 5 `.air` binari Apple (dati di metal2vulkan) |
| `air_work/*.named.ll`, `air_work/*.amdgpu.ll`, `air_work/air_kernels.hsaco` | pipeline AIR -> AMDGPU (sezione 5.2) |
| `scripts/air2amdgpu.py` | prototipo di lowering AIR -> amdgcn (testo) |
| `src/run_air.hip`, `out2/run_air` | host HIP che esegue i kernel AIR su gfx1200 |

Pipeline riproducibile della sezione 5.2 (per ogni fixture `X`):
```
llvm-as X.air.ll -o X.bc
llvm-dis X.bc -o - | sed "s|^target triple.*|target triple = \"amdgcn-amd-amdhsa\"|; s|^target datalayout.*|<datalayout AMDGPU>|" > X.retarget.ll
opt -passes=instnamer X.retarget.ll -S -o X.named.ll
python3 -I air2amdgpu.py X.named.ll X.amdgpu.ll
clang -target amdgcn-amd-amdhsa -mcpu=gfx1200 -O3 -c X.amdgpu.ll -o X.o
ld.lld -shared *.o -o air_kernels.hsaco && ./run_air air_kernels.hsaco
```
