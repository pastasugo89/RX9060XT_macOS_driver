# RDNA4FB: perché OpenCore non lo carica e cosa cambia (21/10/2026)

Scopo: capire perché `Kernel → Add` non ha caricato RDNA4FB nel boot25 e rendere l'iniezione iniettabile in un solo boot per iterazione.

## Esito in breve

- **Causa**: RDNA4FB dipende da `com.apple.iokit.IOGraphicsFamily`. Su macOS 25G83 questo kext sta solo in `SystemKernelExtensions.kc`, non in `BootKernelExtensions.kc`. OpenCore inietta solo nella Boot KC, quindi il prelink del kext fallisce. Il fallimento è registrato dai log di OpenCore sull'ESP, non nel seriale del kernel.
- **Non è risolvibile con una modifica di configurazione o di `Info.plist`**: il binario importa 74 simboli `IOFramebuffer` non definiti. Togliere la libreria dal plist non li risolve.
- **Quindi non esiste un'iniezione OpenCore funzionante per RDNA4FB.** Il percorso valido resta `/Library/Extensions` (Aux KC, con consenso GUI). Il problema di produttività va attaccato dal lato del consenso, non dall'iniezione.
- **Modifica applicata**: `tools/vm/prepare-gpu-test-stage.py` ora rifiuta `--rdna4fb` prima di scrivere nell'EFI, invece di produrre un boot inutile da 30–40 minuti.

## Evidenze

### 1. Log di OpenCore sull'ESP (la risposta era già lì)

La EFI di test contiene nella radice i log `opencore-YYYY-MM-DD-HHMMSS.txt`, scritti a ogni boot (`Misc → Debug → Target = 0x43`, già attivo, nessuna modifica necessaria). Copiati in sola lettura con `mcopy`, in `/tmp/claude-1000/-home-pastasugo89-Documenti-rx9060xt-metal-driver/c5febbc7-db60-4955-83b9-2fa35d22be97/scratchpad/oclogs/`, contengono:

```
OC: Prelinked injection RDNA4FB.kext (RDNA4FB Navi 44 match 0x75901002 (cobalt64 patch 0001), test VM P2) - Invalid Parameter
```

Presente in 6 log su 6 dei boot con RDNA4FB iniettato: `opencore-2026-10-21-132708`, `-133743`, `-144940`, `-151331`, `-152502`, `-153712`. Nei log dei boot senza iniezione (es. `-153510`, il boot di consenso) la riga non compare. `Navi48Bringup.kext`, iniettato nello stesso config, non produce mai una riga d'errore.

Il report `p1_p2_display.md` (boot25) diceva «nessuna riga RDNA4FB nel seriale». Non aveva controllato i log OpenCore sull'ESP, che invece contengono l'errore.

### 2. Boot KC di 25G83 (`research/macos/25G83/`)

Parsing dei `LC_FILESET_ENTRY` dei due file KC (nessun root):

| Kext | BootKernelExtensions.kc (204 voci) | SystemKernelExtensions.kc (172 voci) |
|---|---|---|
| com.apple.iokit.IOPCIFamily | sì | no |
| com.apple.iokit.IOGraphicsFamily | **no** | **sì** |

Navi48Bringup richiede solo IOPCIFamily più i `com.apple.kpi.*` (sempre disponibili): è caricabile da OpenCore. RDNA4FB richiede anche IOGraphicsFamily: non lo è.

Il `README.md` di RDNA4FB (sezione «Why not a Lilu plugin / OpenCore injection?») documenta lo stesso vincolo, con un fallimento già osservato su hardware in una build precedente.

### 3. Simboli del binario (`rdna_efi.bin`, sha256 `578bc71a…`)

- 363 simboli esterni non definiti; 74 sono `IOFramebuffer`/`IOGraphics*` (es. `__ZN13IOFramebuffer10gMetaClassE`, `__ZN13IOFramebuffer10getVBLTimeEPyS0_`). Il kext è una sottoclasse di `IOFramebuffer`: la dipendenza è strutturale, non un dettaglio del plist.
- Firma: entrambi i Mach-O hanno `LC_CODE_SIGNATURE` e `CodeResources` vuoto (`files: []`). La firma non distingue i due kext e non è la causa.

### 4. Sorgente OpenCore (riassunto, non citazione diretta)

Il sorgente pubblico di `OcAppleKernelLib/PrelinkedKext.c` (letto tramite un riassunto del fetch, quindi da verificare) indica che, nel percorso Boot KC, una libreria assente non viene saltata ma sostituita da uno stub di simboli senza vtable. La risoluzione dei simboli fallisce poi per `IOFramebuffer`. Il codice di stato `EFI_INVALID_PARAMETER` non è stato ricondotto a una riga precisa: è una stima, non una verifica.

Nota: la stringa citata nel README (`Dependency ... was not found`) non compare nelle stringhe del `OpenCore.efi` di questa EFI. Il messaggio attuale è quello qui sopra.

## Cosa ho cambiato

**`tools/vm/prepare-gpu-test-stage.py`**
- Nuova costante `BOOT_KC_ENTRIES` (`research/macos/25G83/BootKernelExtensions.entries`) e funzione `boot_kc_missing(info)`: restituisce le librerie non-kpi di `OSBundleLibraries` che non sono nella Boot KC.
- In `--rdna4fb`, dopo il controllo del bundle e prima di qualsiasi `mmd`/`mcopy`, un `assert` rifiuta il kext se manca una libreria. Il messaggio rimanda a questo report.
- Verifica: `py_compile` OK. `boot_kc_missing` testata sui due Info.plist reali: RDNA4FB → `['com.apple.iokit.IOGraphicsFamily']`; Navi48Bringup → `[]`.
- Non è stato fatto il `--dry-run` end-to-end: fallisce prima della guardia su `qemu-img convert` senza `-U`, perché il qcow2 risulta lockato. È un limite preesistente dello script, non modificato.
- Non ho aggiunto `--rdna4fb-inject`: un flag di iniezione che rifiuta sempre il kext del progetto sarebbe fuorviante. `--rdna4fb` resta invariato come nome per non rompere i riferimenti in `p1_p2_display.md`.

**RDNA4FB `Info.plist`**: nessuna patch. Togliere `IOGraphicsFamily` dal plist non risolve i 74 simboli; sarebbe una modifica che sembra un fix e non lo è.

**Configurazione OpenCore**: nessuna modifica. Il log su ESP è già attivo (`Target = 0x43`).

## Come verificare

Senza boot:
1. `python3 tools/vm/prepare-gpu-test-stage.py 17 ... --rdna4fb <kext> --dry-run` deve fallire con «RDNA4FB injection refused» (una volta sistemato il lock di `qemu-img`, vedi sopra).
2. Il config dello staging (`staging/config.stage17.plist`) non deve avere voce RDNA4FB in `Kernel.Add` quando non si passa `--rdna4fb`. Già così per la preparazione corrente.

Al prossimo boot con consenso (nessuna iniezione):
3. Log OpenCore: nessuna riga `Prelinked injection RDNA4FB`.
4. Seriale: prima di tutto il `kmutil load` deve dare esito «not approved» oppure «requires a reboot»; dopo il riavvio, `RDNA4FB: probe on PCI device 0x75901002` (come nel boot28).

## Produttività: cosa resta aperto

Il costo reale non è l'iniezione ma il consenso: ogni build (cdhash diverso) richiede approvazione GUI, e l'approvazione richiede un riavvio (boot26: «requires a reboot»). Sono quindi almeno due boot per versione, a meno che l'approvazione non sopravviva al rebuild.

- **Ipotesi da verificare con un solo boot**: l'approvazione è legata alla firma. Firmare ogni build con la stessa identità di firma (certificato di firma stabile) potrebbe far sopravvivere il consenso a un rebuild. Non verificato: serve un boot per controllarlo.
- **Non farò** aggiramenti del database delle approvazioni dei kext (`KextPolicy`) o della SIP: il consenso è un controllo di sicurezza macOS.
- **Logica testabile senza VM**: parser AtomBIOS, EDID, calcolo dei timing non toccano i simboli di `IOFramebuffer` e si possono compilare e testare sull'host, con il pattern di `tools/hosttests/test_n4x_safety_pure.cpp`.

## Riferimenti

- `research/hw_dump/p2_boot25/` (seriale e `kmutil_load_rdna4fb_attempt1.txt`)
- `research/reports/p1_p2_display.md` (sezione boot25, da correggere: la causa è nei log OC sull'ESP)
- `research/refs/RDNA4FB/README.md` (sezione OpenCore injection)
- `research/macos/25G83/BootKernelExtensions.entries`, `research/macos/25G83/root/System/Library/KernelCollections/`
- Log OC: `opencore-2026-10-21-*.txt` nella radice dell'EFI di `/mnt/vm/images/macos-gpu-test/OpenCore/OpenCore.stage1.qcow2` (copie in sola lettura in `/tmp/claude-1000/-home-pastasugo89-Documenti-rx9060xt-metal-driver/c5febbc7-db60-4955-83b9-2fa35d22be97/scratchpad/oclogs/`)
