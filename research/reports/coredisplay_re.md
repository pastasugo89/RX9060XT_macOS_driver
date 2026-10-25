# CoreDisplay (macOS 25G83): percorso InstallTiming, scelta del display principale, correzione proposta

Data: 21/10/2026. Scopo: capire perché il display fisico della RX 9060 XT (RDNA4FB) non diventa principale.
Analisi statica, nessuna VM avviata, nessun sudo, nessun commit, nessuna modifica al codice.

## 0. Fonti e metodo

- Binario: `CoreDisplay` estratto dal dyld shared cache di 25G83 con `ipsw dyld extract` (ipsw 3.1.737, cache UUID `F25A411F-…`). CoreDisplay 291.4, x86_64, sha256 `ef8d4a76…9545e71`. File: `research/macos/25G83/dylibs/CoreDisplay` (gitignored). Il binario conserva i simboli locali, quindi le funzioni interne hanno nome.
- `IOGraphicsFamily` e `AMDFramebuffer` (Apple) estratti dalla System KC con `ipsw kernel extract`: `research/macos/25G83/kexts/` (gitignored).
- Strumenti: `llvm-objdump` per il disassemblato; REA 6.4.0 via CLI con Ghidra 12.1.2 (`GHIDRA_INSTALL_DIR=/opt/ghidra`, JDK portatile `research/ext/jdk/jdk-21.0.12.1+1`). Il server MCP `rea` della sessione non vedeva Ghidra perché il JDK di sistema è solo runtime; la CLI con il JDK portatile ha funzionato. Snapshot: `research/macos/25G83/rea/coredisplay.snapshot` (gitignored).
- Log di riferimento: `research/hw_dump/p2_boot32/`, `research/hw_dump/p2_boot34/` (WindowServer, subsistema CoreDisplay).
- Indirizzi: quelli del dylib estratto (base `0x7ff8…`). Per IOGraphicsFamily e AMDFramebuffer: indirizzi del Mach-O estratto.

Legenda: **Osservato** = letto da codice o log; **Inferito** = deduzione dal codice, non verificata a runtime; **Non verificato** = dato mancante.

## 1. Risposta al punto 1: InstallTiming e origine di 0xe00002c7 / 0xe00002dd

### Sintesi

- Il log `InstallTiming - legacyRng_legacyEnc_legacyBit_legacyClr FAILED … with code 0xe00002c7` **non nasce dal driver**. Nasce in `IOFBInstallMode` (0x7ff805376713), quando `conn->+0x128` (puntatore `caps`) è NULL e le opzioni non hanno il bit 0x10.
- Con `caps == NULL`, `IOCheckTimingWithDisplay` **non chiama mai** `IOFBDriverPreflight`, cioè la chiamata IOConnect al driver. Per questo l'override di `validateDetailedTiming` non viene mai eseguito.
- `caps` viene letto dalla proprietà IORegistry `IOFBTimingRange`. Il dump dell'entry RDNA4FB (`p2_boot34/ioreg_rdna4fb_props_postarm.txt`) **non la contiene**. Il kext AMD di Apple la pubblica (vedi punto 4).

### Catena (pseudocodice sintetico)

```
IODisplayInstallTimings(conn, ...)                          // 0x7ff80537bbfc
    d = IORegistryEntryCreateCFProperty(conn->entry, "IOFBTimingRange")
    if d && len(d) >= 0xf0:
        conn->+0x128 = alloc(0x138); copia i byte di d       // caps
    // altrimenti caps resta NULL
    InstallTiming(conn, mode, opts=2)                       // chiamata con edx = 2

InstallTiming(conn, mode, opts)                             // 0x7ff80537f398
    if caps && caps->+0xea != 0:
        ...InstallTimingWithWireFormats(...)                // ramo "formati wire"
    else:
        r = InstallTimingImpl(conn, mode, opts, true)       // ramo legacy (caps NULL)
    log_mode_add(conn, mode, r, "InstallTiming")            // stampa "... FAILED ... code r"

InstallTimingImpl(conn, mode, opts, log)                    // 0x7ff80537fb8f
    if mode->+0x28 < 0 && !(mode->+0x78 && mode->+0x88): return 0xe00002e6
    r = IOCheckTimingWithDisplay(conn, mode, opts, log)     // sempre chiamata
    if (r & ~4) == 0xe00002e2: return r                     // e2 / e6: si ferma
    return IOFBInstallMode(conn, -1, mode, 0, opts)         // r = c7 qui

IOCheckTimingWithDisplay(conn, mode, opts, log)             // 0x7ff8053797f3
    if caps == NULL || (opts & 8):  goto dict_checks        // salta range e preflight
    CheckTimingWithRange(conn, caps, mode)                  // e2 se fuori range
    IOFBDriverPreflight(conn, mode, log)                    // solo con caps != NULL
dict_checks:                                                // conn->+0x70 (dict)
    ritorna f0 (NotFound) o e6 (UnsupportedMode) in base a "IODisplayEDID" / "established-ids"

IOFBDriverPreflight(conn, mode, log)                        // 0x7ff805377ad1
    if conn->+0x9c & 2: return 0xe00002d7                   // offline
    r = IOConnectCallStructMethod(conn->+0x10, sel=0x11,
                                  in=mode, inSize=0xcc, out, outSize=0xcc)   // 0x7ff805377b2f
    if r == 0 and timing valida: copia output, ritorna 0
    else: log "Failed preflight ... Driver returned 0x%08x"; ritorna e6

IOFBInstallMode(conn, idx, mode, flags, opts)               // 0x7ff805376713
    ...
    if !(opts & 0x10) && conn->+0x128 == NULL:
        return 0xe00002c7                                   // 0x7ff805376f50 (kIOReturnUnsupported)
    ...
    // ramo DetailedTimingsEqual (IOFBDetailedTimings):   ritorna 0xe00002dd se trova un duplicato (0x7ff805376cbf)
```

### Evidenza dai log (`p2_boot34`, `p2_boot32`)

- 72 righe `Attempting to install timing …` (Info, da `InstallTimingImpl`): la funzione viene eseguita.
- 0 righe `Failed preflight …`: `IOFBDriverPreflight` non produce mai l'errore del driver.
- 69 righe `… FAILED … with code 0xe00002c7`, tutte con il nome `legacyRng_legacyEnc_legacyBit_legacyClr`.
- 3 righe `… with code 0xe00002dd` (2560x1440@120, mode 0x80001000). Il nome `legacy…` viene costruito da `log_mode_add` dai campi del descrittore, non è un formato provato.

### Perché l'override di validateDetailedTiming non viene mai chiamato (Osservato)

- `IOFBDriverPreflight` è l'unico punto in cui CoreDisplay chiama il driver con il selector 0x11.
- In `IOCheckTimingWithDisplay`, la chiamata è raggiungibile solo se `caps != NULL` (0x7ff805379825 → salto a 0x7ff80537990c quando `caps == NULL`).
- Con `IOFBTimingRange` assente, `caps` resta NULL, quindi il driver non viene interrogato. Nel log non compare alcun "Failed preflight" perché la chiamata non viene fatta.

### Costanti IOReturn

| Codice | Nome | Stato |
|---|---|---|
| 0xe00002c2 | kIOReturnBadArgument | Osservato: stringa presente in CoreDisplay |
| 0xe00002d7 | kIOReturnOffline | Osservato: stringa presente in CoreDisplay |
| 0xe00002c7 | kIOReturnUnsupported | Nome standard IOKit, non trovato nei binari locali (da confermare con IOReturn.h dell'SDK) |
| 0xe00002e2 / e6 / f0 | NotPermitted / UnsupportedMode / NotFound | Nomi standard, non verificati localmente |
| 0xe00002dd | non identificato | Non verificato |

### Selector IOConnect

- CoreDisplay invia `IOConnectCallStructMethod(conn->+0x10, 0x11, mode, 0xcc, out, 0xcc)` in `IOFBDriverPreflight`.
- In IOGraphicsFamily, `IOFramebufferUserClient::externalMethod` (0x1472518c): selector > 0x15 → `0xe00002c2`; `this+0xe8 & 1` → `0xe00002d7`; altrimenti usa la tabella `methodTemplate` (voci da 24 byte, indice = selector, tabella a 0x14739e20).
- Il metodo 17 corrisponde a `IOFramebuffer::extValidateDetailedTiming` (0x147117b4). Questo è coerente con la nota della patch 0003 del repo, ma la risoluzione dei puntatori nella tabella (chained fixups) **non è verificata**: la query di xref REA è tornata vuota.
- `extValidateDetailedTiming` chiama la virtuale `validateDetailedTiming(void*, uint64)`. La base (0x14721046) restituisce `0xe00002c7` direttamente a 0x1472104a: è il valore che la patch 0003 descrive.

## 2. Risposta al punto 2: scelta del display principale

### Funzioni e flag (Osservato)

- `_CGXMainDisplayDevice` (0x7ff805435e7c): sceglie il display principale tra i dispositivi `CGXDisplayDevice` in lista. Pseudocodice ricostruito (REA):

```
candidato = primo dispositivo con:
    dev->display->+0x128 == 1   (online)
    dev->display->+0x129 != 0   (attivo)
    dev->display->+0x12a == 1   (marcato main, scritto dalla funzione)
    origine (+0xdc, +0xe0) == (0,0)  e  +0x114 == 0
    (+0x12d != 0  oppure  +0x110 == 0)
seconda passata (se nessun candidato): richiede anche w*h + offset != 0
se ancora nulla: "Setting offline display 0x%08x main in CGXMainDisplayDevice"
                 (CoreDisplay::AddMainOfflineBreadcrumb)
```

- `_UpdateCGXDisplayDevice` (0x7ff805430b12): riceve uno `state` dal GPUWrangler. `state+0x120 bit0` → `dev->display->+0x128` (online). Se il dispositivo era main (`+0x12a`) e il bit è 0 → log `Setting main display 0x%08x offline`. I bounds arrivano da `state+0x30..0x48` (doppi) e finiscono in `+0xdc..+0xe8`.
- Il chiamante è il blocco GPUController (`ProcessGPUAdded`, chiamata a 0x7ff8053e4865, vicino a `CreateMetalDevice` e `AddCGXDisplayDeviceToDeviceList`).
- `_CGXConstructVirtualFramebufferSet` (0x7ff80538cbb4): per ogni dispositivo con `+0x128 == 1` usa i bounds reali; altrimenti usa il default 0x500 × 0x400 (1280×1024) in (0,0). Se la lista main è ancora vuota crea il framebuffer di fallback `_CGXConstructVirtualFramebuffer(0,4,8,0x500,0x400,…)`. È il "placeholder/VirtualDisplay".

### Chiavi IORegistry lette da CoreDisplay sul framebuffer (Osservato, stringhe e disassemblato)

- `IOFBTimingRange` (decide `caps`, vedi punto 1), `IOFBDetailedTimings`, `IOFBDependentID` (u32 letto in `conn+0x28`, in `IOFramebufferOpen` 0x7ff805370f4d), `IOFBConfig` (in `IOFBBuildModeList`), `IOFBNeedsRefresh`, `startup-timing`, `IODisplayConnectFlags` (in `IODisplayCreateInfoDictionary` e in `build_mode_list`), `IODisplayEDID`, `IODisplayPrefsKey`, `dpcd-registers`, `IOFBHDMIDongleROM`, `IOFBDependentIndex`.
- `IOFBIntegrated` **non compare in CoreDisplay**: è letto solo da IOGraphicsFamily. Quindi la rimozione di IOFBIntegrated della patch 0004 non tocca direttamente CoreDisplay.
- Nessun riferimento a `AppleDisplay` né a una policy AGDC specifica. `AppleGraphicsControl` compare in `GetCurrentSystemGPUVendorName`, `CGXMuxGetState` e `mux_initialize`: serve a determinare il vendor della GPU di sistema (AMD / Intel / APV / NVIDIA). Il suo effetto sulla scelta del main **non è verificato**.

### Perché il fisico viene scartato (Inferito, da confermare)

1. Senza modalità installate (punto 1), la lista modi resta vuota e i bounds del dispositivo non hanno dimensione valida (w·h = 0).
2. La seconda passata di `_CGXMainDisplayDevice` richiede `w·h + offset != 0`: il fisico non è candidato a main.
3. Nessun candidato → `Setting offline display … main in CGXMainDisplayDevice` → ramo `CGXConstructVirtualFramebufferSet` → VirtualDisplay (`com.apple.VirtualDisplay`), coerente con il log.
4. Il bit online (state+0x120 bit0) viene dal GPUWrangler state del framebuffer. Non ho tracciato fino in fondo da quale proprietà IORegistry derivi quel bit (**Non verificato**).

## 3. Risposta al punto 3: "Failed to obtain mode info"

- Il messaggio `%s: Failed to obtain mode info from IOFBGetDisplayModeInformation()` è in `IOFBSetDisplayModeAndDepth` (0x7ff805372f79 e vicini).
- Il wrapper `_IOFBGetDisplayModeInformation` (0x7ff805372df5):

```
IOFBGetDisplayModeInformation(displayID, modeIdx, out):
    conn = gConnectRefDict[displayID]      // dizionario registrato in IOFramebufferOpen
    if conn == NULL: return 0xe00002c2     // kIOReturnBadArgument
    return __Z30_IOFBGetDisplayModeInformation(conn, modeIdx, out)
           // costruisce il dizionario con IODisplayCreateInfoDictionary e pixel info
```

- `IOFramebufferOpen` (0x7ff805370f4d) inserisce il connect in `gConnectRefDict` sia con la chiave `io_connect` sia con la chiave service. Il log riporta `displayID: 0x0` e `fbRegID: 0x100000318`: la chiave passata è 0, quindi non esiste una voce per quel display.
- **Dato mancante**: un `displayID` valido assegnato dal lato CoreDisplay. Inferito: dipende dal fatto che l'InstallTiming vada a buon fine (punto 1). Il "Failed to obtain mode info" è quindi una conseguenza, non la causa primaria.

## 4. Risposta al punto 4: chiavi e metodi del framebuffer nel percorso AMD

### La chiave "AMDFramebuffer" (Osservato)

- Non è una chiave IORegistry. È un **nome di classe** in una tabella diagnostica a 0x7ff840526580, usata da `_DumpIORegistryFrameBufferInfo` (chiamata da `CoreDisplay::GPU::GPU` a 0x7ff8053cfd88 e da `CGXMappedDisplayStart`).
- Contenuto della tabella: `AppleIntelFramebuffer`, `AMDFramebuffer`, `AppleParavirtFramebuffer`, `IOFramebufferUserClient`, poi `ID`, `Controller`, `Online`, `DepOpen`, `PostOpen`, `Busy_0`, `Busy_1`.
- `Can't get value for key '%s'` è una riga di log. **Non è un gate.**

### Che cosa si aspetta CoreDisplay da un framebuffer di terze parti (Osservato, da AMDFramebuffer di Apple)

`AMDFramebuffer` (kext Apple estratto) pubblica e legge:

- `setInfoProperties()`: alloca un blocco di **0x138 byte**, lo riempie tramite un oggetto helper (`this+0xdd8`, metodo virtuale 0xa28) e lo pubblica con `setProperty("IOFBTimingRange", blocco, 0x138)`. Pubblica anche `IOFBProbeOptions` (bit 0x400 da `this+0x820` bit 10).
- `setDetailedTimings`: pubblica `IOFBDetailedTimings`.
- `validateDetailedTiming(void*, uint64)`: override del driver.
- `getPropertiesForUserClient`: legge `IOFBTimingRange`.

Quindi la proprietà `IOFBTimingRange` (0x138 byte) è il contratto che il framebuffer deve rispettare perché CoreDisplay installi i modi. Il contenuto preciso non è riproducibile dal solo codice CoreDisplay: lo riempie il driver con dati dell'hardware.

### L'assert del test con classe rinominata (Osservato)

- L'assert non viene dalla chiave `AMDFramebuffer`. È in `CoreDisplay_CreateDisplayForCGXDisplayDevice`: quando `CoreDisplay::CreateMetalDevice(accelerator)` fallisce, il codice logga `Failed to create MetalDevice for accelerator …` e poi `Failed to create MetalDevice (null|non-null)` seguito da `___assert_rtn` con `Display::Display(CGXDisplayDevice*)`.
- La causa precisa del fallimento del Metal device (associazione framebuffer ↔ accelerator) **non è stata determinata**. È un filone separato da chiudere con IOAccelerator / `MetalPluginName`.

## 5. Correzione proposta

Ordine di priorità (il punto 1 è la causa diretta osservata).

### 5.1 Pubblicare `IOFBTimingRange` su RDNA4FB (necessario)

Proprietà sull'entry del framebuffer stesso (CoreDisplay usa `IORegistryEntryCreateCFProperty` senza cercare nei parent), prima della pubblicazione dell'entry. Dimensione: **0x138 byte**, come AMD.

| Offset | Tipo | Valore proposto | Motivo (codice) |
|---|---|---|---|
| 0xe4 | u16 | 0xffff | maschera encode; se 0 → `fbRange_b` rifiuta il formato wire (c7) |
| 0xe6 | u16 | 0xffff | maschera bpc |
| 0xe8 | u16 | 0xffff | maschera colore |
| 0xea | u16 | 0xffff | maschera dynamic range (anche `dynamicRange` in CheckTimingWithRange) |
| 0x60…0x6d | u8 | 1 | divisori di granularità: CheckTimingWithRange fa modulo, 0 = divisione per zero |
| 0x20 / 0x28 | u64 | min/max clock | banda di pixel clock; includere 497.75 MHz (GOP 2560×1440@120) |
| 0x40…0xcc | u32 coppie min/max | includere il GOP | H active 2560, blank 160, sync 48/32; V active 1440, blank 85, sync 3/10 |
| 0x3c | u8 | da verificare | bit 0x0c controllati in CheckTimingWithRange; non chiaro quale valore serva |

Nota: la mappatura delle coppie min/max è **parziale** (da `CheckTimingWithRange`, decompilato in `scratchpad/coredisplay_re/ctr.c`). Va completata e verificata prima di scrivere i valori.

### 5.2 Mantenere l'override di validateDetailedTiming (già nella patch 0003)

L'override accetta il timing GOP e restituisce il timing canonico. Con `IOFBTimingRange` presente, la chiamata a IOFBDriverPreflight avviene davvero, quindi l'override diventa rilevante. Da solo, senza `IOFBTimingRange`, non basta.

### 5.3 Correggere il commento della patch 0003

Il commento dice che `0xe00002c7` in CoreDisplay è il ritorno di `extValidateDetailedTiming`. Nel run osservato la c7 nasce invece in `IOFBInstallMode` con `caps == NULL`, e il driver non viene interrogato. Proposta: aggiornare la nota e citare il punto 1.

### 5.4 Verifica attesa dopo la correzione (non eseguita: nessuna VM avviata)

- Nei log WindowServer: nessun `FAILED … 0xe00002c7` per 2560×1440@120.
- Compare `IOFBDriverPreflight` (chiamata sel 0x11) con il log bounded `validateLogs` della patch 0004.
- `Setting main display …` non deve più seguire il ramo VirtualDisplay, se il bit online e i bounds sono corretti (da verificare: punto 2).

## 6. Limiti e cose non verificate

- Mappatura completa di `IOFBTimingRange` (0x138 byte) e dei valori min/max: parziale.
- Nome e numero dei selector IOConnect (metodo 17 = validate): coerente con la patch 0003, non verificato con REA (tabella con chained fixups).
- Origine del bit online (state+0x120) nel GPUWrangler: non tracciata fino alla proprietà IORegistry.
- Effetto di `AppleGraphicsControl` (vendor/mux) sulla scelta del main: non verificato.
- Nomi di 0xe00002c7, e2, e6, f0, dd: standard IOKit o non verificati (vedi tabella).
- Causa del fallimento di `CreateMetalDevice` nel test con classe rinominata: non determinata.
- Tutte le conclusioni sono statiche. Nessun test runtime è stato eseguito.

## 7. Actualización con v6 (boot40): por qué RGB 8 bpc 2560x1440@120 no pasa

Datos usados: `research/hw_dump/p2_boot40/wireformats/` (log WindowServer, `IOFBTimingRange` en hex, EDID del nodo AppleDisplay). Desensamblado y pseudocódigo: `IOCheckTimingWithDisplay`, `InstallTimingImpl`, `InstallTimingWithWireFormats`, `CheckTimingWithRange`, `getParameterNodes` (REA/Ghidra, CLI con JDK portátil). Todo es análisis estático; nada se ha ejecutado.

Corrección de la sección 5: la propuesta de máscaras `0xffff` queda **superada**. La v6 publica `0x0001 / 0x0002 / 0x0003 / 0x0001`, que son las capacidades reales que se necesitan (ver 7.4). Verificado: el blob de boot40 coincide byte a byte con la tabla v6 de `p1_p2_display.md`.

### 7.1 Lista de wire formats y filtros (Osservato)

- `InstallTimingWithWireFormats` prueba **dos listas**: una SDR de 9 elementos (rango SDR, color Native, encoding ∈ {RGB444, 422, 420}, bpc ∈ {12, 10, 8}) y una HDR10 de 6 elementos (rango HDR10, bpc ∈ {12, 10}). En el log: 9 líneas `Declined SDR_*` y 6 `Declined HDR10_*` por modo.
- La línea `InstallTimingWithWireFormats - SDR_420__8_Native FAILED … code 0xe00002c7` **no es el único formato probado**. Imprime el último elemento de la lista. El código `c7` es el valor inicial de `r13`, que queda cuando todos los elementos son rechazados.
- Cada elemento pasa cuatro filtros en orden (`fbRange_b` si falla, código `c7`):
  `map_enc[encode] & caps.e4`, `map_bpc[bpc] & caps.e6`, `map_color[color] & caps.e8`, `map_range[range] & caps.ea`.
  Las mapas estáticas (decodificadas del binario): encoding `{0:0, 1:1, 2:2, 3:4, 4:8}`, bpc `{6:1, 8:2, 10:4, 12:8, 16:16}`, color `{0:0, 1:1, 2:2, 3:4, …, 10:512}`, rango `{0:0, 1:1, 2:2, 3:4, 4:8, 5:16, 6:32}`.
- Resultado con la v6 (caps: e4=0x1, e6=0x2, e8=0x3, ea=0x1):

| Formato | Filtro que lo rechaza | Motivo |
|---|---|---|
| RGB 12 / 10 bpc (SDR) | fbRange_b (c7) | mask bpc `e6=0x2` sólo admite 8 bpc |
| 422 (SDR, 12/10/8) | fbRange_b (c7) | mask encoding `e4=0x1` sólo admite RGB444 |
| 420 (SDR, 12/10/8) | fbRange_b (c7) | igual que 422 |
| HDR10 (todos) | fbRange_b (c7) | mask rango `ea=0x1` sólo admite SDR |
| **RGB 8 bpc SDR** | **pasa los 4 filtros** → `InstallTimingImpl` → **fbRange_a (e2)** | ver 7.2 |
| YCbCr 444 (encoding 2) | no aparece en las listas | — |

- Por tanto **no** es la banda, ni el EDID, ni el enlace DP, ni `force8BPC`: el filtro de máscaras explica todos los rechazos. El texto anterior ("CoreDisplay no prueba RGB/444") es incorrecto: RGB 8 bpc **sí** se prueba. Y no he encontrado ninguna lectura de `force8BPC` en este camino.

### 7.2 Por qué RGB 8 bpc @120 Hz recibe e2 (CheckTimingWithRange)

- Los nodos de parámetros (`pixelEncoding`, `bitsPerColorComponent`, `colorimetry`, `dynamicRange`) comparan el código pedido (mode+0xb4/0xb6/0xb8/0xba) con la máscara de caps (e4/e6/e8/ea). Las subtablas son identidad. Para RGB 8 SDR: `1&1`, `2&2`, `1&3`, `1&1` → **pasan**.
- Los campos de `IODetailedTimingInformationV2` (verificados contra `IOGraphicsTypes.h` del SDK local): `signalConfig` 0x20, `pixelClock` 0x28, `H` 0x40–0x4c, `V` 0x50–0x5c, `numLinks` 0x80, `pixelEncoding` 0x88, `bpc` 0x8a, `colorimetry` 0x8c, `dynamicRange` 0x8e (relativos al timing, que es `mode+0x2c`).
- El timing del candidato 120 Hz es el **DTD de la extensión CEA del EDID**: 497.75 MHz, H 2560+160 (SO 48, SW 32), V 1440+85 (SO 3, SW 10), flags 0x1a. Con el blob v6, **todos los controles de rango pasan**: frecuencia de línea 182 996 Hz ∈ [182 800, 183 200]; frecuencia de cuadro 119 ∈ [119, 121]; Htotal 2720 ≤ 2720; Vtotal 1525 ≤ 1525; activos 2560/1440 exactos; granularidad 1.
- La única condición que hace fallar ese timing es la del número de enlaces (código `0x23`), en `CheckTimingWithRange`:
  `if (1 < numLinks && caps.maxNumLinks != 0 && caps.maxNumLinks < numLinks) → fail`.
  Con `caps.maxNumLinks` (0xd0) = 1 de la v6 y `numLinks = 2`, falla.
- Dónde se fija `numLinks` (`InstallTimingImpl`, antes de `IOCheckTimingWithDisplay`, mismo offset que T+0x80 = mode+0xac):
  - `conn+0x118 == 0` → `numLinks = 0`;
  - `conn+0x118 < clock del modo` → `numLinks = 2`;
  - si no, `numLinks = 1`.
  `conn+0x118` lo escribe `_IODisplayInstallTimings`: **165 000 000 Hz** (0x9d5b340) si `IODisplayIsDigital` está en el diccionario `conn+0x70`; 0 si no. El EDID no tiene VSDB HDMI, así que `LookExtensions` no lo sobrescribe.
- Comprobación cruzada con el log (Inferido, consistente con todas las líneas): con 165 MHz, `numLinks = 2` para todos los modos por encima de 165 MHz (2560×1440@120 497.75; @144 604.25; @99.9 410.5; @60 241.5), y todos dan e2. Los modos por debajo (1920×1080@60 148.5, 1280×720@60) no entran en la regla y fallan por otros motivos (frecuencia de cuadro o activos). **No está observado directamente**: el mensaje `failed range for … 0x%02x check` es de nivel Debug y no aparece en los logs.
- Condición a verificar: que `IODisplayIsDigital` esté en `conn+0x70`. Si no estuviera, `numLinks` sería 0 y el e2 quedaría sin explicar.

### 7.3 Origen de 0xe00002c7 con caps presente, y preflight

- **c7 en v6**: sólo sale de los filtros `fbRange_b` de la lista (y del valor inicial de `r13`). `IOFBInstallMode` nunca se alcanza en el run, porque ningún elemento pasa `IOCheckTimingWithDisplay`. Su c7 (`caps == NULL && !(opts & 0x10)`) ya no aplica con caps presente.
- **Preflight**: `IOFBDriverPreflight` (selector 0x11) se llama sólo si `CheckTimingWithRange` devuelve 0 y, además, `conn+0x240 != 1` (el ramo de la relación de aspecto está protegido por `conn+0x240 == 1`; ese campo lo escribe sólo `InstallDisplayIDEXT`, y este EDID no tiene bloque DisplayID). Para RGB 8 bpc @120, CheckTimingWithRange falla antes → **el driver no se llama**. Esto explica el "validate no llamado" del coordinador.
- Tras corregir `numLinks`, el preflight sí se llamará: `RDNA4FB::validateDetailedTiming` debe aceptar el timing GOP (patch 0003). Después, `ValidateTimingInformation` sólo comprueba coherencia interna (sincronismos dentro del blanking, sin caps ni numLinks; verificado).
- Tras un preflight correcto, `IOCheckTimingWithDisplay` devuelve `0xe00002f0` ("continuar") si `opts & 0x2c == 0` (aquí `opts = 2`, y no hay rama `trng`). Entonces `InstallTimingImpl` llama a `IOFBInstallMode`, que con caps presente ya no devuelve c7 por la regla de caps NULL.

### 7.4 Valores propuestos para IODisplayTimingRangeV2

| Campo (offset) | v6 | Propuesta | Motivo |
|---|---|---|---|
| maxNumLinks (0xd0) | 1 | **0** | El header dice "si es cero, se asume 1 enlace". Con 0, CoreDisplay no aplica el rechazo por numLinks. No se declara ningún enlace dual; es el mismo default de un único enlace. |
| supportedPixelEncoding (0xe4) | 0x0001 | 0x0001 (sin cambios) | RGB444: lo que lleva el scanout. No añadir YCbCr 422/420/444. |
| supportedBitsPerColorComponent (0xe6) | 0x0002 | 0x0002 (sin cambios) | 8 bpc: lo que entrega el GOP. No declarar 10/12. |
| supportedColorimetryModes (0xe8) | 0x0003 | 0x0003 (sin cambios) | Native RGB + sRGB. |
| supportedDynamicRangeModes (0xea) | 0x0001 | 0x0001 (sin cambios) | SDR. No declarar HDR10. |
| maxBandwidth (0xf0) | 14 932 500 000 | **25 920 000 000** (si el enlace es DP HBR3 ×4) | Ancho de banda del enlace con 8b/10b: 4 carriles × 8.1 Gbit/s × 0.8. Sin 8b/10b serían 32.4 Gbit/s. El valor de la v6 era la necesidad del GOP, no la capacidad del enlace. Esto **no** cambia el e2 (ningún lector de 0xf0 en el camino de instalación). El enlace HBR3 ×4 es lo que indica el coordinador; no lo he verificado con DPCD ni logs de link training. |
| version (0x08) | 2 | 2 (sin cambios) | No he encontrado lectores de la versión en este camino. |
| min/max H y V, frame/line rate, granularidad | min=max | sin cambios | Pasan para el DTD 2560×1440@120. |

Cambio adicional en el driver (no en el blob): en `RDNA4FB::validateDetailedTiming`, cuando se acepta el timing GOP, poner `numLinks = 0` (un solo enlace) en la descripción del modo. Así `IOFBInstallMode` y el driver no reciben `numLinks = 2`. Es una desviación documentada de la descripción, no una capacidad nueva. Recomiendo además que la patch 0004 registre también las llamadas aceptadas, no sólo los rechazos.

### 7.5 Qué esperar en el próximo boot (sin ejecutar)

- `CheckTimingWithRange` ya no rechaza 2560×1440@120 por numLinks: no debe aparecer `fbRange_a … 0xe00002e2` para ese modo.
- Debe aparecer la llamada al driver (sel 0x11) para ese timing, y `validate` debe aceptarlo.
- Después, `IOFBInstallMode` decide. Posibles resultados: éxito, `0xe00002dd` (duplicado), o c7. Si el timing del DTD tiene `appleTimingID != 0`, la rama `established-ids` puede devolver e6 antes de llegar ahí.

### 7.6 Límites

- Análisis estático. Los valores de los candidatos vienen del DTD del EDID, no de la memoria de CoreDisplay en ejecución.
- `IODisplayIsDigital` en `conn+0x70`: inferido, no leído.
- La línea `failed range` (Debug) no se ha podido observar.
- Los códigos `0xe00002c7`, `e2`, `e6`, `f0`, `dd`: nombres estándar de IOKit salvo `c2` y `d7`, que están como cadenas en CoreDisplay.
- Nada se ha ejecutado: no hay VM, ni commit, ni cambios en el blob ni en el driver. Los scripts y desensamblados están en `scratchpad/coredisplay_re/` (fuera del repo).

### 7.7 Decodifica del hex real de boot40 (312 bytes)

Fuente: `research/hw_dump/p2_boot40/wireformats/wf40_rdna_x.txt` (`IOFBTimingRange`). Lectura little-endian, según `IODisplayTimingRangeV2`:

| Offset | Bytes (hex) | Valor | Campo |
|---|---|---|---|
| 0x08 | 02 00 00 00 | 2 | version |
| 0x20 / 0x28 | 6e a3 1d 00 … / 10 b1 b2 1d … | 497 250 000 / 498 250 000 Hz | minPixelClock / maxPixelClock |
| 0x34 | 01 | 1 | supportedSyncFlags (separate) |
| 0x40 / 0x44 | 0x77 / 0x79 | 119 / 121 Hz | min/max frame rate |
| 0x48 / 0x4c | 10 ca 02 00 / a0 cb 02 00 | 182 800 / 183 200 Hz | min/max line rate |
| 0x50 / 0x54 | a0 0a / f5 05 | 2720 / 1525 | maxHTotal / maxVTotal |
| 0x60–0x6d | 01 × 14 | 1 | divisores de granularidad |
| 0x70 / 0x74 | 0xa00 / 0xa00 | 2560 | H activo min/max |
| 0x78 / 0x7c | 0xa0 / 0xa0 | 160 | H blanking min/max |
| 0x80 / 0x84 | 0x30 / 0x30 | 48 | H sync offset min/max |
| 0x88 / 0x8c | 0x20 / 0x20 | 32 | H sync width min/max |
| 0x90 / 0x94 | 0x5a0 / 0x5a0 | 1440 | V activo min/max |
| 0x98 / 0x9c | 0x55 / 0x55 | 85 | V blanking min/max |
| 0xa0 / 0xa4 | 3 / 3 | 3 | V sync offset min/max |
| 0xa8 / 0xac | 0x0a / 0x0a | 10 | V sync width min/max |
| 0xb0–0xcc | 0 | 0 | bordes |
| **0xd0** | **01 00 00 00** | **1** | **maxNumLinks** |
| 0xd4 / 0xd8 | 0x79662 / 0x79a4a | 497 250 / 498 250 kHz | link0 min/max clock |
| 0xe4 / 0xe6 / 0xe8 / 0xea | 01 00 / 02 00 / 03 00 / 01 00 | 0x1 / 0x2 / 0x3 / 0x1 | máscaras encoding / bpc / colorimetry / rango |
| 0xf0 | 20 de 0b 7a 03 00 00 00 | 14 932 500 000 bit/s | maxBandwidth |
| 0xf8–0x137 | 0 | — | DSC desactivado |

El valor 0xd0 = 1 combinado con `numLinks = 2` (7.2) es el rechazo que explica el e2 de RGB 8 bpc a 120 Hz (inferido, pendiente de confirmación en ejecución).

## 8. Modo duplicado (0xe00002dd) con v7: causa en el driver y corrección mínima

Fuentes: `research/hw_dump/v7_boot41/prearm` y `postarm` (log WindowServer); `research/ext/RDNA4FB-n44/src/framebuffer.cpp` (v7); desensamblado de CoreDisplay 291.4 (`IOFBInstallMode` 0x7ff805376713, `DetailedTimingsEqual` 0x7ff805377504, `IOFBBuildModeList` 0x7ff8053739e2, `InstallTimingWithWireFormats`, `mode_format_result` 0x7ff805382828) y de IOGraphicsFamily 600 (kext extraído de la System KC: `extSetProperties` 0x1471f2c0, `doSetDetailedTimings` 0x14719644, `IOFramebuffer::close` 0x1471d934, `IOFramebuffer::open`). El código fuente open source de IOGraphics no está en el repo; la comparación se hace contra el binario y contra `IOFramebuffer.h` del SDK local (`research/ext/MacKernelSDK`).

### 8.1 Qué es "duplicado" en `IOFBInstallMode` (Osservato)

`IOFBInstallMode(conn, index, mode, flags, opts)` sólo busca duplicados cuando `index == -1` (instalación nueva desde `InstallTimingImpl`). Hay tres lugares donde compara:

1. **Tabla de modos del conector** `conn+0x88` (registros `IOFBDisplayModeDescription` de 0xcc bytes, con `conn+0x80` como cuenta). Recorre las entradas con flags válidos (`flags & 0x2001 == 0x2001`) y compara con `DetailedTimingsEqual`. Si coincide: fusiona los flags en la entrada y devuelve `0xe00002dd` (rama `LAB_7ff805376cbf`). La rama de opción `opts & 2` usa una variante del mismo criterio.
2. **Array `IOFBDetailedTimings`** del diccionario `conn+0x58`, desde el índice `conn+0xa0`. Si `DetailedTimingsEqual(nuevo, entrada)` coincide, devuelve `0xe00002dd` sin añadir nada.
3. Sólo si no hay coincidencia: crea el diccionario del modo en `conn+0x60`/`conn+0x68`, añade la entrada `IOFBDetailedTimings` y devuelve 0.

`DetailedTimingsEqual` compara, con `opts` sin el bit 0x20, los campos exactos: H activo/blanking/SO/SW, V activo/blanking/SO/SW, `pixelClock` (exacto), polaridad de sync, `numLinks` y los campos de encoding/bpc/colorimetry/rango (`0x88–0x8e`). El timing del GOP instalado en sesión 1 coincide exactamente con el candidato de sesión 2. El ID del nuevo modo es `count + (conn+0xa4 | 0x80000000)`: `0x80001000` en sesión 1 y `0x80000001` en sesión 2, porque `conn+0xa4` es distinto por sesión.

### 8.2 Por qué aparece en sesión 2 y no en sesión 1 (Osservato + Inferido)

- **Sesión 1 (pid 196)**: sin estado previo, `IOFBBuildModeList` no restaura nada. La instalación del GOP llega a la rama nueva y el log muestra `succeeded for mode 0x80001000`.
- Al final de `IOFBBuildModeList`, CoreDisplay envía al driver el diccionario `conn+0x58` con `IOConnectSetCFProperty("IOFBConfig", conn+0x58)` (0x7ff8053762ef). En IOGraphics, `extSetProperties` (0x1471f2c0) hace dos cosas: fija la propiedad `IOFBConfig` en la **entrada del registro del framebuffer** (setter de propiedad del servicio, vtable +0x258: inferido, no verificado; la clave es `gIOFBConfigKey`), y si `IOFBDetailedTimings` está presente llama a `doSetDetailedTimings` → `setDetailedTimings(array)` del driver.
- **Sesión 2 (pid 1274)**: `IOFBBuildModeList` lee `IORegistryEntryCreateCFProperty(entry, "IOFBConfig")` (0x7ff805373dbd) y rellena `conn+0x88` desde `IOFBModes`, es decir, con el modo GOP de la sesión anterior. El `IOFBDetailedTimings` restaurado en `conn+0x58` también lo contiene. Al instalar el mismo GOP, la comparación encuentra la entrada restaurada y devuelve `dd`.
- ¿Por qué persiste la propiedad? La entrada RDNA4FB y su `IOFramebuffer` siguen vivos mientras el kext está cargado; reiniciar WindowServer no los destruye. Sólo IOGraphics escribe `IOFBConfig` (`extSetProperties`) y lo lee (`getConfigMode`, para `IOFBModes`). **No hay ningún `removeProperty("IOFBConfig")` en IOGraphics**, ni en `close` ni en otro sitio (búsqueda de referencias en el binario). `IOFramebuffer::close` (0x1471d934) es la máquina de estados de cierre/energía y no toca `IOFBConfig`.

### 8.3 ¿Cuenta `dd` como éxito? (Osservato)

No. `mode_format_result` (0x7ff805382828) trata `dd` como `Declined … Mode_clone`; la línea `succeeded for mode` la emite `log_mode_add` sólo con código 0. En sesión 2 el 120 Hz nunca produce `succeeded`, y `InstallTimingWithWireFormats` sigue con los demás elementos. El modo restaurado existe en la tabla de CoreDisplay, pero el 120 Hz no se selecciona: `Startup Mode … ioModeID 0x1` y `frames=0`, igual que en el reporte del coordinador.

### 8.4 Qué debe hacer el driver (Propuesta)

Opciones evaluadas:

| Opción | Efecto | Veredicto |
|---|---|---|
| Devolver éxito en la rama `dd` | Esa rama es CoreDisplay, no el driver. Imposible desde RDNA4FB. | Descartada |
| Exponer el alias en `getDisplayModes` | Cambia la lista de modos y los IDs; la restauración de `IOFBModes` seguiría produciendo el duplicado. | No resuelve |
| Vaciar aliases en `setDetailedTimings(nullptr)` sin tocar `IOFBConfig` | `setDetailedTimings` sólo se llama cuando CoreDisplay envía `IOFBConfig`, así que no es fiable. La propiedad restaurada sigue en `IOFBModes`. | Insuficiente |
| **Eliminar la propiedad `IOFBConfig` en `open()`** y reiniciar el estado de alias | `open()` ocurre antes de que `IOFBBuildModeList` lea la propiedad; así la sesión nueva arranca como la primera (instalación nueva → `succeeded`). | **Recomendada** |

Corrección mínima (RDNA4FB, sólo en `framebuffer.cpp`):

1. `RDNA4FB::open()` (framebuffer.cpp:2439). Tras `super::open()`, junto al `removeProperty("IOFBIntegrated")` existente:
   ```
   removeProperty("IOFBConfig");   // la sesión anterior dejó IOFBModes/IOFBDetailedTimings (CoreDisplay → IOGraphics extSetProperties)
   setDetailedTimings(nullptr);    // limpia aliasModes (v7 ya trata nullptr como lista vacía)
   ```
   Aplicar sólo en Navi 44, como el resto de la rama. El mismo patrón ya lo usa `IOFBIntegrated`.
2. No cambiar `setDetailedTimings`, `getDisplayModes`, `getTimingInfoForDisplayMode` ni `ownsDisplayMode`: siguen siendo correctos para la sesión actual.
3. Documentar en la patch 0006 (o siguiente) el motivo: CoreDisplay restaura su tabla desde `IOFBConfig`, y el driver no debe dejar que la sesión anterior determine los modos de la nueva.

Resultado esperado con la corrección: la sesión 2 hace una instalación nueva del 120 Hz, con `validate` aceptando el GOP y `succeeded for mode …`, igual que la sesión 1. Hay que vigilar que `IOFBConfig` vuelva a escribirse al final de la sesión (no es problema: `open()` lo borra en la siguiente).

### 8.5 Límites

- La causa de por qué el modo restaurado no se selecciona (frames=0) no está cerrada: sólo sabemos que no se marca como `succeeded`.
- No he verificado en ejecución que `open()` se llame antes de la primera lectura de `IOFBConfig` en `IOFBBuildModeList`. El orden es el esperado (la conexión se abre antes de construir la lista), pero debe confirmarse en el log de la siguiente sesión.
- La propiedad `IOFBConfig` también lleva configuración de usuario (escalado, rotación) que IOGraphics persiste; borrarla en `open()` la reinicia. Es el comportamiento que queremos para un modo que el driver controla, pero conviene revisarlo si aparecen otras configuraciones que dependan de ella.
- Nombres de constantes y offsets: los del binario de IOGraphics 600 y de CoreDisplay 291.4, no los del código fuente open source.
