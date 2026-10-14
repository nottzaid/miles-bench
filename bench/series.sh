#!/usr/bin/env bash
# Interleaved launches for configs that can't be switched live.
#   bench/series.sh <prefix> <rounds> <envA> <envB> [<envC> ...]
# Each env: a space-separated VAR=value list (quoted; "" for none). Runs A B C A B C ... via cfgrun.sh.
set -u
bench=$(cd "$(dirname "$0")/.." && pwd)
prefix=$1 rounds=$2
shift 2
arms=("$@")
wineserver=$(sed -n 's/^PROTONPATH=//p' "$bench/bench/lutris.env")/files/bin/wineserver
for ((r = 1; r <= rounds; r++)); do
    for ((i = 0; i < ${#arms[@]}; i++)); do
        arm=$(printf "\\x$(printf %x $((65 + i)))")
        e=${arms[i]}
        run=$prefix-$arm$r
        env $e timeout 590 "$bench/bench/cfgrun.sh" "$run" > "$bench/build/$run.series.log" 2>&1
        echo "$run: $(grep -E '^fps' "$bench/captures/$run/window.txt" 2>/dev/null | cut -c1-80) | $(grep -E '^window' "$bench/captures/$run/window.txt" 2>/dev/null)"
        pkill -TERM -x MilesMorales.ex 2>/dev/null; sleep 5
        # A crash leaves the game's crash handler (crs-handler.exe, a report dialog nobody answers)
        # holding the run's Wine session open, and the next launch then hangs at the launcher.
        if pgrep -f 'crs-handler\.exe' >/dev/null; then
            echo "$run: game crashed (crash handler closed, nothing reported)"
            pkill -TERM -f 'crs-handler\.exe'
        fi
        WINEPREFIX=$bench/prefix "$wineserver" -k 2>/dev/null
        for _ in $(seq 1 30); do pgrep -x wineserver >/dev/null || break; sleep 1; done
    done
done
