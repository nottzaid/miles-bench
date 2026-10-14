#!/usr/bin/env bash
# One gameplay measurement: launch with a config, load the bench checkpoint (the Rhino fight), play
# it with bench/fightdrive.sh (runs, jumps, dodges, the ctrl prompts that move the fight through its
# phases, Rhino's charges), summarise with bench/fightsum.py and end the bench game.
#
#   bench/fightrun.sh <config.env> <run> [max secs, default 360]
#
# The window ends at the game's FIGHT_SAVES-th autosave (default 4; it saves at the start of each
# phase), so every launch is measured over the same stretch of the fight; fight.json records how
# long that took ("secs"). Result: captures/<run>/fight.json (one JSON line) and fight.txt.
set -uo pipefail
bench=$(cd "$(dirname "$0")/.." && pwd)
cfg=$1 run=$2 secs=${3:-360} saves=${FIGHT_SAVES:-4}
gamelog="$bench/prefix/pfx/drive_c/users/zaid/Documents/Marvel's Spider-Man Miles Morales/Marvel's Spider-Man Miles Morales.log"
cap=$bench/captures/$run
if ! KEEP_GAME=1 "$bench/bench/withcfg.sh" "$cfg" timeout 590 "$bench/bench/cfgrun.sh" "$run" \
        > "$bench/build/$run-cfgrun.log" 2>&1; then
    echo "$run: launch failed"; tail -3 "$bench/build/$run-cfgrun.log"
    "$bench/bench/endgame.sh" >/dev/null 2>&1; exit 1
fi
python3 "$bench/bench/fightsum.py" "$cap" start > "$cap/fight-start.json"
"$bench/bench/fightdrive.sh" "$cap/drive.log" &
drv=$!
end=$((SECONDS + secs))
while (( SECONDS < end )) && (( $(grep -c "Request save type" "$gamelog" 2>/dev/null) < saves )); do sleep 1; done
kill $drv 2>/dev/null; wait $drv 2>/dev/null
python3 "$bench/bench/fightsum.py" "$cap" end "$cap/fight-start.json" > "$cap/fight.json" 2> "$cap/fight.txt"
cp "$gamelog" "$cap/game.log" 2>/dev/null || true
cat "$cap/fight.txt"
"$bench/bench/endgame.sh" >/dev/null 2>&1
