#!/usr/bin/env bash
# Controllo di sintassi del kext di bring-up da Linux (nessun SDK Apple richiesto).
# Compila ogni sorgente con clang in modalita' -fsyntax-only contro gli header di MacKernelSDK.
# Non produce un kext: serve a verificare che le modifiche compilino prima di passare a macOS.
#
# Uso: tools/linux-check-kext.sh [file.cpp ...]   (senza argomenti: tutti i sorgenti del Makefile)
# Variabili: MKSDK (default research/ext/MacKernelSDK), CXX (default clang++), CC (default clang)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEXT="$ROOT/cobalt64/src/navi48-bringup"
MKSDK="${MKSDK:-$ROOT/research/ext/MacKernelSDK}"
CXX="${CXX:-clang++}"
CC="${CC:-clang}"

if [ ! -d "$MKSDK/Headers" ]; then
  echo "MacKernelSDK non trovato in $MKSDK (git clone https://github.com/acidanthera/MacKernelSDK)" >&2
  exit 2
fi

COMMON=(-target x86_64-apple-macos11.0 -I"$MKSDK/Headers" -I"$KEXT/src" -I"$KEXT/src/amd"
        -I"$KEXT/../xlat12" -I"$KEXT/../shadercache" -I"$KEXT/../dcn41"
        -DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE -DAPPLE -DNeXT -D_FORTIFY_SOURCE=0
        -nostdinc -fno-builtin -fno-common -mkernel -fapple-kext -fsyntax-only -Wno-everything)
CXXFLAGS=("${COMMON[@]}" -std=c++17 -fno-exceptions -fno-rtti)
CFLAGS=("${COMMON[@]}")
# Flag aggiuntivi, es. EXTRA_FLAGS=-DN4X_ASIC_NAVI48 per il profilo Navi 48
if [ -n "${EXTRA_FLAGS:-}" ]; then read -r -a _x <<< "$EXTRA_FLAGS"; CXXFLAGS+=("${_x[@]}"); CFLAGS+=("${_x[@]}"); fi

cd "$KEXT" || exit 2
if [ $# -gt 0 ]; then
  files=("$@")
else
  files=(src/*.cpp src/amd/*.cpp src/apple/*.cpp src/dcn/*.cpp src/kmod_info.c ../xlat12/xlat12.c ../xlat12/xlat12_ib.c
         ../xlat12/xlat12_headless.c ../shadercache/shadercache.c ../dcn41/*.c)
fi

ok=0; bad=0; failed=()
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  case "$f" in
    *.c) cmd=("$CC" "${CFLAGS[@]}" "$f") ;;
    *)   cmd=("$CXX" "${CXXFLAGS[@]}" "$f") ;;
  esac
  if out=$("${cmd[@]}" 2>&1); then
    ok=$((ok+1))
  else
    bad=$((bad+1)); failed+=("$f")
    echo "== ERRORE: $f"
    echo "$out" | grep -E "error:" | head -5
  fi
done
echo "risultato: $ok ok, $bad con errori"
[ $bad -eq 0 ]
