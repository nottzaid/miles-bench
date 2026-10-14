#!/usr/bin/env bash
# One diagnostic launch of a config: GPU timeline (GPUTIME), allocation trace (MEMTRACE), and once the
# scene is up, which of the game's swapped pages zram could not compress. Ends the game afterwards.
#   SUDO_PW=... [config env...] bench/probe.sh <run-name>
# Results: captures/<run>/gputime.tsv, memtrace.tsv, zramhuge.txt; read with bench/gputime.py and
# bench/memreport.py.
set -u
bench=$(cd "$(dirname "$0")/.." && pwd)
run=${1:?usage: probe.sh <run-name>}
trap '"$bench/bench/endgame.sh"' EXIT
KEEP_GAME=1 GPUTIME=1 MEMTRACE=1 timeout 590 "$bench/bench/cfgrun.sh" "$run" || exit 1
sleep 45
printf '%s\n' "$SUDO_PW" | sudo -S -p '' python3 "$bench/bench/zramhuge.py" > "$bench/captures/$run/zramhuge.txt" 2>&1
# Syscalls of the game's threads and of its wineserver for 10 s in the scene (server round trips
# are write/read pairs on the server pipes).
game=$(pgrep -x MilesMorales.ex | head -1)
ws=$(for p in $(pgrep -x wineserver); do tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -q "^WINEPREFIX=$bench/prefix" && echo $p; done | head -1)
for who in game ws; do
    pid=${!who}
    [[ -n $pid ]] || continue
    printf '%s\n' "$SUDO_PW" | sudo -S -p '' perf trace -s -p "$pid" -o "$bench/captures/$run/syscalls-$who.txt" -- sleep 10 >/dev/null 2>&1
done
