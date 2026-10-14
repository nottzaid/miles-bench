#!/usr/bin/env bash
# Run a command with a bench config's variables exported (one VAR=value per line in the file; # comments).
#   bench/withcfg.sh bench/configs/<name>.env <command> [args...]
set -euo pipefail
cfg=${1:?usage: withcfg.sh <config file> <command...>}
shift
while IFS= read -r line; do
    [[ -z $line || $line == \#* ]] && continue
    export "${line?}"
done < "$cfg"
exec "$@"
