#!/usr/bin/env bash
# Loop route for open-world A/B runs (S17): swing while strafing right so Miles circles the same
# blocks, with a jump between holds to keep him airborne.  circledrive.sh <log> <secs>
# <log> goes in the run's capture folder (captures/<run>/drive.log): the stuck check reads that
# folder's frametrace.tsv.
# Stuck check (VSync-off runs): fps over the last 3 s above STUCK_FPS (default 57; standing still
# runs ~60-64 uncapped, swinging ~40-55) means he is standing against something: turn back and jump.
# Re-created on 2026-10-21 from the session script the S17 runs used (it lived in a scratch folder
# that was cleared); same steps and stuck check.
log=$1 secs=${2:-240}
cd "$(dirname "$0")/.."
cap=$(dirname "$log")
steps=("hold 8000 w shift d" "space")
end=$((SECONDS + secs)); i=0
: > "$log"
recent_fps() {
    tail -n 400 "$cap/frametrace.tsv" | awk -F'\t' '$1 == "F" {t[n++] = $2} END {
        if (n < 2) { print 0; exit } last = t[n-1]; c = 0
        for (i = n - 1; i >= 0 && t[i] > last - 3000; i--) c++
        print c / 3 }'
}
while (( SECONDS < end )); do
    s=${steps[i % ${#steps[@]}]}
    printf '%s %s\n' "$(date +%s.%N)" "$s" >> "$log"
    python3 bench/hyprbench.py input $s > /dev/null 2>&1
    i=$((i + 1))
    if (( i % 2 == 0 )); then
        f=$(recent_fps)
        if awk -v f="$f" -v s="${STUCK_FPS:-57}" 'BEGIN { exit !(f > s) }'; then
            printf '%s stuck (%s fps): escape\n' "$(date +%s.%N)" "$f" >> "$log"
            python3 bench/hyprbench.py shot "$log.stuck-$i.png" > /dev/null 2>&1
            for e in "hold 1500 s shift" "space" "hold 1500 w shift a" "space"; do
                python3 bench/hyprbench.py input $e > /dev/null 2>&1
            done
        fi
    fi
done
