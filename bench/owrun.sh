#!/usr/bin/env bash
# One whole open-world or warehouse launch for S17's comparisons (data/s17_launches.csv), with the
# bench prefix's game VSync off for the run (uncapped) and, when asked, scx_bpfland from before the
# launch to exit, as bench/play.sh runs it.
#
#   SUDO_PW=... bench/owrun.sh <ow|wh> <config> <run> <scx 0|1> [drive secs]
#
# ow: saves/swing-1017, circle route (bench/circledrive.sh), scored over the drive minus its first
#     20 s (bench/winscore.py). wh: the warehouse cfgrun window (captures/<run>/window.txt).
# GPU_OC="<core> <mem>": NVML offsets for the whole launch (tools/gpuclk.py; measured, not used).
# Re-created on 2026-10-21 from the session script the S17 runs used (combo.sh, in a scratch folder
# that was cleared): same steps, scheduler waits and scoring; logs now go to build/<run>.owrun.log.
cd "$(dirname "$0")/.."
kind=$1 cfg=$2 cap=$3 scx=$4 secs=${5:-150}
reg=prefix/pfx/user.reg
sud() { echo "$SUDO_PW" | sudo -S -p '' "$@"; }
setvsync() {  # with the bench prefix's wineserver gone (it writes user.reg when it exits)
    for i in $(seq 40); do pgrep -x wineserver >/dev/null || break; sleep 1; done
    sed -i "/Miles Morales\\\\\\\\Graphics\]/,/^\[/ s/^\"VSync\"=dword:0000000./\"VSync\"=dword:0000000$1/" $reg
}
# A scheduler that was just stopped takes up to ~1 s to unregister; one started meanwhile fails.
scxwait() { for i in $(seq 40); do [[ $(cat /sys/kernel/sched_ext/state) == $1 ]] && return 0; sleep 0.5; done; return 1; }
scxstop() { [[ -f captures/$cap/scx.pid ]] && sud kill $(cat captures/$cap/scx.pid) 2>/dev/null; rm -f captures/$cap/scx.pid; scxwait disabled; }
bench/endgame.sh >/dev/null 2>&1
scxwait disabled || { echo "$cap: a sched_ext scheduler is still attached"; exit 1; }
trap 'bench/endgame.sh >/dev/null 2>&1; scxstop; [[ -n ${GPU_OC:-} ]] && sud python3 tools/gpuclk.py reset >/dev/null; setvsync 1' EXIT
[[ -n ${GPU_OC:-} ]] && sud python3 tools/gpuclk.py set $GPU_OC | head -2 | tr '\n' ' '
setvsync 0
avail=$(free -m | awk '/^Mem/ {print $7}')
rm -rf captures/$cap; mkdir -p captures/$cap
if [[ $scx == 1 ]]; then
    sud bash -c "setsid scx_bpfland > captures/$cap/scx.log 2>&1 & echo \$! > captures/$cap/scx.pid"
    scxwait enabled || { echo "$cap: bpfland did not attach"; exit 1; }
fi
sched=scx-$(cat /sys/kernel/sched_ext/state)
if [[ $kind == wh ]]; then
    timeout 560 bench/withcfg.sh bench/configs/$cfg.env bench/cfgrun.sh $cap > build/$cap.owrun.log 2>&1
    echo "$cap ($cfg, $sched, avail ${avail}M): $(cut -c1-75 captures/$cap/window.txt 2>/dev/null | head -1) $(grep -ac 'err:' captures/$cap/vkd3d.log) err"
else
    BENCH_SAVE=swing-1017 CFGRUN_NOHUD=1 KEEP_GAME=1 timeout 400 bench/withcfg.sh bench/configs/$cfg.env bench/cfgrun.sh $cap > build/$cap.owrun.log 2>&1
    pgrep -x MilesMorales.ex >/dev/null || { echo "$cap: game not up"; tail -2 build/$cap.owrun.log; exit 1; }
    sleep 8
    lastf() { tac captures/$cap/frametrace.tsv | grep -m1 '^F' | cut -f2; }
    bench/circledrive.sh captures/$cap/drive.log $secs &
    sleep 20; a=$(lastf); wait; b=$(lastf)
    stuck=$(grep -c stuck captures/$cap/drive.log)
    echo "$cap ($cfg, $sched, avail ${avail}M, stuck $stuck): $(python3 bench/winscore.py captures/$cap/frametrace.tsv $a $b) $(grep -ac 'err:' captures/$cap/vkd3d.log) err"
fi
