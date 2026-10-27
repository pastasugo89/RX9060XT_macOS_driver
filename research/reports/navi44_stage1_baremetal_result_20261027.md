# Esito osservazione bare metal Navi44 stage1 — 2026-10-27

## Evidenza raccolta

Sessione macOS 26.6.2, build 25G83. Boot iniziato alle 15:39:07 ora locale. Boot arguments live includono `navi48bringup=1 navi48-stage=1 navi48-interrupts=0` e mantengono `-amd_no_dgpu_accel`.

`kmutil showloaded --list-only` elenca `com.navi48.bringup (0.0.664)`, load tag 88. Il suo UUID (`8E6F15CB-63CB-34C6-A112-77A4630B5DA2`) corrisponde all'UUID del binario candidato in staging; il binario candidato ha SHA-256 `d186c77f925aed420425149be7bb04059d3e6e8a7fb3d758d345afbf3a22846d`. Il volume OCBOOT non era montato durante questa raccolta, quindi non è stato possibile leggere e calcolare l'hash del file attualmente usato dalla EFI; UUID uguale è una corrispondenza utile, non una prova crittografica d'identità dei byte caricati.

IORegistry mostra il servizio `Navi48Bringup` `registered, matched, active`, match PCI `0x75901002`, `MMIO,Verified=Yes`, stadio `survey-readonly`, discovery da on-die TMR, 42 blocchi IP e VRAM rilevata 16.304 MB. Riporta GC 12.0.0, PSP 14.0.2, SMU 14.0.2, SDMA 7.0.0, IH 7.0.0, MMHUB/DCN 4.1.0, HDP 7.0.0, NBIF 6.3.1 e UMC 8.14.0.

Unified log kernel mostra dipendenze risolte, eseguibile caricato, classe registrata e kext avviato alle 15:39:26. Il filtro kernel per error/failure/fault/panic associati a Navi48 non ha corrispondenze; i log non contengono il dettaglio della discovery. `dmesg` non è stato accessibile senza privilegi (`Operation not permitted`), e non è stato usato `sudo`.

`system_profiler SPDisplaysDataType` identifica AMD `1002:7590`, revisione `c0`, con display 2560×1440 online; indica `Kernel Extension Info: No Kext Loaded` e 14 MB di VRAM. La topologia IOKit mostra `.Display_boot` come `IONDRVFramebuffer`. Questi dati sono coerenti con kext di discovery attivo e framebuffer di boot; **non dimostrano accelerazione grafica, VRAM utilizzabile, Metal o stabilità sotto carico**.

## Limiti e azioni

Questa è una verifica passiva dello stato del boot effettuato dall'utente. Non ho caricato kext, letto registri GPU, avviato test GPU o modificato sistema/EFI. Non ho verificato temperature né protezione termica. Il precedente bundle stage1 non va confuso con un driver grafico accelerato.

Output filtrati e checksum sono in [macos_stage1_run_20261027](../hw_dump/macos_stage1_run_20261027/). Il dump contiene solo boot arguments, identificazione kext, proprietà IOKit mirate, topologia GPU essenziale, riepilogo display e log kernel Navi48 filtrato; non contiene l'albero IORegistry completo o seriali SMBIOS.
