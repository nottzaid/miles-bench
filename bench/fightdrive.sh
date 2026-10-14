#!/usr/bin/env bash
# Keep Miles moving through the bench checkpoint (the Rhino fight) until killed, with keys injected
# inside the game (hyprbench.py input, no focus needed): runs, jumps and dodges in a fixed loop, so
# frames come from gameplay (camera motion, Rhino's attacks, deaths and checkpoint reloads) rather
# than a still scene, and the fight stays in its first phase. Run it next to abf.py or a memory sampler.
#
#   bench/fightdrive.sh [log file]
set -uo pipefail
bench=$(cd "$(dirname "$0")/.." && pwd)
log=${1:-/dev/null}
hb() { python3 "$bench/bench/hyprbench.py" input "$@" >/dev/null 2>&1; }
# ctrl answers the fight's "get on Rhino's back" prompts; without it the fight waits at the first
# one in slow motion (a still scene). With it the fight moves through its phases and the game
# autosaves at each, so compare launches over the same phases (fightrun.sh FIGHT_SAVES), not the
# same number of seconds.
moves=(
    "hold 2500 w shift" "space" "hold 1500 a shift" "hold 400 ctrl" "hold 2500 s shift" "space"
    "hold 1500 d shift" "hold 400 ctrl" "hold 1200 w" "space" "space" "hold 1800 d shift"
)
while pgrep -x MilesMorales.ex >/dev/null; do
    for m in "${moves[@]}"; do
        hb $m || echo "$(date +%T) not delivered: $m" >> "$log"
    done
done
