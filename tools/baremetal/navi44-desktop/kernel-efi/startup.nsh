echo Ripristino EFI: cerco la partizione con RECOVERY\funzionante-665.plist
echo Se la trovo copio la configurazione funzionante (kernel 665) su OC\config.plist e riavvio.
for %a in fs0 fs1 fs2 fs3 fs4 fs5 fs6 fs7 fs8 fs9
if exist %a:\EFI\RECOVERY\funzionante-665.plist then
if exist %a:\EFI\OC\Tools\OpenShell.efi then
if exist %a:\EFI\OC\config.plist then
echo Trovata su %a: copio RECOVERY\funzionante-665.plist su OC\config.plist
cp -q %a:\EFI\RECOVERY\funzionante-665.plist %a:\EFI\OC\config.plist
echo Ripristino eseguito su %a: riavvio tra 5 secondi.
stall 5000000
reset
endif
endif
endif
endfor
echo Nessuna partizione con i file attesi: ripristino automatico non eseguito.
echo Comandi manuali da digitare in questa shell:
echo   map -r
echo   fs0:   poi fs1: fs2: ... finche trovi la cartella \EFI\RECOVERY
echo   ls \EFI\RECOVERY
echo   cp -q \EFI\RECOVERY\funzionante-665.plist \EFI\OC\config.plist
echo   reset
