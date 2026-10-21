#!/usr/bin/env bash
# In one running bench game, alternate a system setting A/B every <secs> while swinging, and log
# segment bounds on the frame trace's clock (data/s17_levers.csv: the scheduler rows, wh-gpu).
#   SUDO_PW=... bench/livetoggle.sh <run> <mode> <segments> <secs>
# mode: gov (schedutil | performance), cstate (all | C3 and deeper off), scx (none | $SCX_CMD,
#       default scx_lavd), bpfland (none | scx_bpfland), gpu (0/0 | $GPU_OC offsets)
# Segments go to captures/<run>/<mode>.seg; score them with bench/segscore.py.
# DRIVE: the driver run meanwhile (default bench/circledrive.sh; `true` to stand still).
# Re-created on 2026-10-21 from the session script the S17 runs used (it lived in a scratch folder
# that was cleared); same modes and segment logging.
cap=$1 mode=$2 n=$3 secs=$4
cd "$(dirname "$0")/.."
sud() { echo "$SUDO_PW" | sudo -S -p '' "$@"; }
lastf() { tac captures/$cap/frametrace.tsv | grep -m1 '^F' | cut -f2; }
apply() {  # $1 = A or B
    case $mode in
    gov) g=schedutil; [[ $1 == B ]] && g=performance
         for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo $g | sud tee $f >/dev/null; done ;;
    cstate) v=0; [[ $1 == B ]] && v=1
         for c in /sys/devices/system/cpu/cpu*/cpuidle; do for st in 3 4 5; do echo $v | sud tee $c/state$st/disable >/dev/null; done; done ;;
    gpu) if [[ $1 == B ]]; then sud python3 tools/gpuclk.py set $GPU_OC >/dev/null
         else sud python3 tools/gpuclk.py set 0 0 >/dev/null; fi ;;
    scx|bpfland) bin=${SCX_CMD:-scx_lavd}; [[ $mode == bpfland ]] && bin=scx_bpfland
         if [[ $1 == B ]]; then sud bash -c "setsid $bin > captures/$cap/scx.log 2>&1 & echo \$! > captures/$cap/scx.pid"; sleep 2
         else [[ -f captures/$cap/scx.pid ]] && sud kill $(cat captures/$cap/scx.pid) 2>/dev/null; rm -f captures/$cap/scx.pid; sleep 2; fi ;;
    esac
}
${DRIVE:-bench/circledrive.sh} captures/$cap/toggle.drive.log $(( n * secs + 20 )) &
drv=$!
out=captures/$cap/$mode.seg; : > $out
for ((i = 0; i < n; i++)); do
    cfg=A; (( i % 2 )) && cfg=B
    apply $cfg; sleep 3
    a=$(lastf); sleep $((secs - 3)); b=$(lastf)
    echo "$cfg $a $b" >> $out
done
apply A
wait $drv
