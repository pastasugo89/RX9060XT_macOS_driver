# Baseline GPU bare metal macOS — 2026-10-27

Raccolta diagnostica di sola lettura. Non sono stati caricati kext, modificati registri GPU o toccati EFI/dischi di sistema. Gli output di `system_profiler` e IORegistry sono stati filtrati per escludere seriali/UUID/EDID e proprietà non pertinenti.

## Ambiente

- macOS 26.6.2, build 25G83; Darwin `25.6.0`; architettura `x86_64`.
- MacPro7,1 riportato dal sistema; AMD Ryzen 7 7700, 8 core fisici / 16 logici.
- `kern.bootargs`: `-v debug=0x100 keepsyms=1 -amd_no_dgpu_accel kextlog=0xffff acpi_layer=0xffffffff acpi_level=0x2087 msgbuf=1048576`.
- `xcode-select -p` è terminato con exit code 2: nessuna active developer directory selezionata. Git, clang e Python non sono stati eseguiti.

## GPU e kext

- `system_profiler SPDisplaysDataType`: vendor AMD `0x1002`, device `0x7590`, VRAM riportata 14 MB, `Kernel Extension Info: No Kext Loaded`. Display online e principale a 2560×1440.
- `kmutil showloaded` è riuscito. Il filtro per GPU/progetto ha trovato solo `com.apple.iokit.IOGraphicsFamily (600)` e `com.apple.kext.AMDSupport (7.0.1)`; nessun kext Navi44/Navi48/RDNA4FB o del progetto compare nell'output filtrato. La presenza di `AMDSupport` da sola non prova accelerazione.
- IORegistry: proprietà `compatible` include `pci1002,7590`, classe VGA; il percorso del controllo GPU passa per `IONDRVFramebuffer/AGPM`. Il dato `reg` corrisponde alla funzione PCI 03:00.0; l'output selezionato non mostra un acceleratore del progetto. Questo è coerente con l'assenza di kext grafico riportata da `system_profiler`.

## Stato dei comandi

- `sw_vers`, `sysctl`, `system_profiler`, `kmutil showloaded` e `ioreg` hanno restituito exit code 0. `kmutil` ha scritto su stderr solo `No variant specified, falling back to release`.
- `xcode-select -p`: exit code 2 e messaggio `Unable to get active developer directory`.
- File associati: `sw_vers.txt`, `sysctl.txt`, `system_profiler_displays.txt`, `kmutil_graphics_project.txt`, `ioreg_gpu_topology.txt` e relativi `.status`/`.stderr`.

## Link importati corretti

Dopo aver verificato tipo, vecchio target e presenza dei nuovi target, sono stati aggiornati solo questi tre symlink:

- `research/ext/cobalt64-upstream/re/linux-dc` → `../../../src/linux`
- `research/ext/c64-work/kc/BootKernelExtensions.kc` → `../../../macos/25G83/root/System/Library/KernelCollections/BootKernelExtensions.kc`
- `research/ext/c64-work/kc/SystemKernelExtensions.kc` → `../../../macos/25G83/root/System/Library/KernelCollections/SystemKernelExtensions.kc`

Tutti e tre i target sono presenti e risolvibili. `cobalt64/re/linux-dc`, già relativo e valido, non è stato modificato. Nessun contenuto dei target è stato cambiato.
