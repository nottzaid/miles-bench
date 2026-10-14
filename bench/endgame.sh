#!/usr/bin/env bash
# End a bench game completely: window rule off, game quit, its crash handler and Wine session gone,
# the bench DLLs out of the game folder. Safe to run when nothing is running.
#   bench/endgame.sh
bench=$(cd "$(dirname "$0")/.." && pwd)
game="/home/zaid/Games/Marvel’s Spider-Man - Miles Morales"
# Only the bench's own game (bench prefix); a game the user started from their own prefix is left alone.
bench_games() {
    for p in $(pgrep -x MilesMorales.ex); do
        { tr '\0' '\n' < "/proc/$p/environ"; } 2>/dev/null | grep -qx "WINEPREFIX=$bench/prefix/pfx/\?" && echo "$p"
    done
}
python3 "$bench/bench/hyprbench.py" teardown >/dev/null 2>&1
pids=$(bench_games)
[[ -z $pids ]] || kill -TERM $pids 2>/dev/null
for _ in $(seq 1 30); do [[ -n $(bench_games) ]] || break; sleep 1; done
pids=$(bench_games)
[[ -z $pids ]] || kill -KILL $pids 2>/dev/null
pkill -TERM -f '[c]rs-handler\.exe' 2>/dev/null
WINEPREFIX=$bench/prefix/pfx "$(sed -n 's/^PROTONPATH=//p' "$bench/bench/lutris.env")/files/bin/wineserver" -k 2>/dev/null
for _ in $(seq 1 20); do [[ -e $game/d3d12.dll || -e $game/d3d12core.dll ]] || break; sleep 1; done
left=$(bench_games; ls "$game"/d3d12.dll "$game"/d3d12core.dll 2>/dev/null)
[[ -z $left ]] && echo "bench game ended, nothing left running" || { echo "still there: $left"; exit 1; }
