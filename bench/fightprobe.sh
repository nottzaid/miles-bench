#!/usr/bin/env bash
# CPU attribution during the driven fight: launch a config, load the checkpoint, start the fight
# driver, and after <delay> seconds sample per-thread CPU per frame (threadcpu.py) and profile the
# given threads (cpuprof.py, cycles:u), then end the bench game.
#
#   bench/fightprobe.sh <config.env> <run> [delay s, default 40] [thread names...]
# Results: captures/<run>/threadcpu.txt, captures/<run>/cpu-<thread>/ and cpuprof-<thread>.txt.
# PROBE_CMD='...' runs that command instead (output in captures/<run>/probe.txt).
set -uo pipefail
bench=$(cd "$(dirname "$0")/.." && pwd)
cfg=$1 run=$2 delay=${3:-40}
shift 3 2>/dev/null || shift $#
threads=("$@")
(( ${#threads[@]} )) || threads=("Render Thread" "MilesMorales.ex")
cap=$bench/captures/$run
trap '"$bench/bench/endgame.sh" >/dev/null 2>&1' EXIT
KEEP_GAME=1 "$bench/bench/withcfg.sh" "$cfg" timeout 590 "$bench/bench/cfgrun.sh" "$run" > "$bench/build/$run-cfgrun.log" 2>&1 ||
    { echo "$run: launch failed"; exit 1; }
"$bench/bench/fightdrive.sh" "$cap/drive.log" &
drv=$!
sleep "$delay"
if [[ -n ${PROBE_CMD:-} ]]; then
    # PROBE_CMD: one custom probe instead of the CPU sampling (run with bash -c, $cap exported).
    export cap
    bash -c "$PROBE_CMD" > "$cap/probe.txt" 2>&1
    kill $drv 2>/dev/null; wait $drv 2>/dev/null
    cat "$cap/probe.txt"
    exit 0
fi
python3 "$bench/bench/threadcpu.py" "$cap" 20 > "$cap/threadcpu.txt" 2>&1
for t in "${threads[@]}"; do
    d="$cap/cpu-${t// /_}"
    python3 "$bench/bench/cpuprof.py" "$d" "$t" 15 40 > "$cap/cpuprof-${t// /_}.txt" 2>&1
done
kill $drv 2>/dev/null; wait $drv 2>/dev/null
cat "$cap/threadcpu.txt"
