#!/bin/bash
# Exercise the actual daemon cache functions on Bash 3 (the macOS system shell).
set -eu
D=$(cd "$(dirname "$0")" && pwd)
W=$(mktemp -d "${TMPDIR:-/private/tmp}/n48decided.XXXXXX")
trap 'rm -rf -- "$W"' EXIT
sed -n '/^decided_load()/,/^oldkey_of()/p' "$D/pc-translate.sh" | sed '$d' > "$W/functions.sh"
source "$W/functions.sh"
DONE=$W/done
KEY=0123456789ab
sha_a=$(printf '%064d' 1); sha_b=$(printf '%064d' 2)
sha_c=$(printf '%064d' 3); sha_d=$(printf '%064d' 4)
printf '%s bundle\n%s %s ok\n%s oldkey ok\n%s FAIL\n' \
  "$sha_a" "$sha_b" "$KEY" "$sha_c" "$sha_d" > "$DONE"
decided_load
decided "$sha_a"
decided "$sha_b"
! decided "$sha_c"
! decided "$sha_d"
# A new decision must take effect in this scan, including FAILs.
decided_record "$sha_c" "$KEY" FAIL
decided "$sha_c"
# Truncating/replacing the done list between scans must invalidate the cache.
: > "$DONE"
decided_load
! decided "$sha_a"
! decided "$sha_b"
! decided "$sha_c"
# Changing the translator key must retry both successes and failures.
decided_record "$sha_b" "$KEY" ok
decided_record "$sha_c" "$KEY" FAIL
KEY=abcdef012345
decided_load
! decided "$sha_b"
! decided "$sha_c"
decided_record "$sha_a" bundle
decided_load
decided "$sha_a"
# No substring/prefix match may skip an unrelated shader.
! decided "${sha_a%?}"
! decided "${sha_a}0"
echo 'test-decided-cache: PASS (bundle, current/old key, success/failure, same-scan updates, refresh, exact keys)'
