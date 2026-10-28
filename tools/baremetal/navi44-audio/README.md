# Prova audio analogico MSI B840 / Ryzen 7700

Preparazione locale, senza installazione o caricamento:

```sh
python3 tools/baremetal/navi44-audio/prepare.py \
  --archive /percorso/VoodooHDA.kext-368.zip \
  --output research/builds/audio-trial-nuovo
```

Usare solo l'archivio ufficiale Release368 di CloverHackyColor/VoodooHDA.
Il tool verifica il digest, restringe il matching a 1022:15e3 / 1462:ee57,
rimuove la personality HDMI e firma il candidato. Non modifica il sistema.

Il risultato richiede una prova AuxKC coordinata. La presenza del jack e la
riproduzione audio non sono provate da una firma valida. L'ID codec e il routing
posteriore devono essere verificati dal vivo prima di dichiarare il fix riuscito.
Vedere il report `research/reports/native_browser_sensors_audio_20261028.md`.
