#!/usr/bin/env bash
# Gaming mode A/B (`gaming-mode`, ~/Projects/dotfiles): interleaved fight launches (bench/fightrun.sh)
# with the game ON SCREEN on the gaming workspace both times. A = gaming mode paused (the usual
# desktop beside the game), B = gaming mode on (shell stopped, terminals closed, other screens
# disconnected, every other app frozen and swapped out).
#
#   systemd-run --user --unit=gmseries --slice=app.slice --collect \
#       bench/gmseries.sh <prefix> <rounds> <config.env> [arms, default AB]
#
# It runs as an app unit of its own: gaming mode recognises a game only among the user's apps, and
# it freezes the terminal this would otherwise run in. The screen showing the user's workspace when
# the series starts shows the game during each run, and that workspace again after it.
# Results: captures/<prefix>-<arm><round>/ (fight.json, game.log) and build/<prefix>.gmseries.log.
set -u
bench=$(cd "$(dirname "$0")/.." && pwd)
prefix=$1 rounds=$2 cfg=$3 arms=${4:-AB}
export BENCH_DLLS=${BENCH_DLLS:-$bench/build/checkpoint-s12/bin}
gm=$HOME/.local/bin/gaming-mode
out=$bench/build/$prefix.gmseries.log
log() { echo "$(date +%T) $*" >>"$out"; }
home_ws=$(hyprctl -j activeworkspace | jq -r .id)
home_mon=$(hyprctl -j monitors | jq -r --argjson ws "$home_ws" '.[] | select(.activeWorkspace.id == $ws) | .name')
[[ $home_ws =~ ^[0-9]+$ && -n $home_mon ]] || { log "no numbered workspace shown: not starting"; exit 2; }

# Once the game has a window on the gaming workspace, show that workspace on the home screen.
show_game() {
    for _ in $(seq 1 480); do
        if hyprctl -j clients | jq -e 'any(.[]; .workspace.name == "gaming" and (.class | startswith("steam_app")))' >/dev/null; then
            hyprctl dispatch "hl.dsp.workspace.move({ workspace = \"name:gaming\", monitor = \"$home_mon\" })" >/dev/null
            hyprctl dispatch 'hl.dsp.focus({ workspace = "name:gaming" })' >/dev/null
            log "game shown on $home_mon"
            return 0
        fi
        sleep 0.5
    done
    log "no game window after 4 min"
    return 1
}

# The user's workspace back on the home screen, once gaming mode has put the desktop back.
give_back() {
    for _ in $(seq 1 120); do [[ $("$gm" status | head -1) == off* ]] && break; sleep 0.5; done
    hyprctl dispatch "hl.dsp.focus({ workspace = $home_ws })" >/dev/null
}
shower=
trap 'kill $shower 2>/dev/null; "$gm" resume; give_back; log "series over"' EXIT

log "series $prefix: $rounds rounds of $arms, $cfg, DLLs $BENCH_DLLS, home $home_ws on $home_mon"
# One snapshot per run, the same in both arms, 60 s after the game is shown: what the screen scans
# out (the game's buffer directly, or Hyprland's composition), and VRAM by process.
snapshot() {
    sleep 60
    {
        echo "== $(date +%T) $1"
        hyprctl -j monitors | jq -c '.[] | {name, ws: .activeWorkspace.name, directScanoutTo, directScanoutBlockedBy, solitary, solitaryBlockedBy, hardwareCursorsInUse}'
        nvidia-smi --query-gpu=memory.used,memory.reserved --format=csv,noheader
        nvidia-smi | awk '$6 ~ /^(G|C|C\+G)$/ {print "  " $5, $7, $(NF-1)}'
        free -m | awk '/Mem:/ {print "RAM used " $3 " MiB, available " $7}'
    } >>"$bench/build/$prefix.gmseries.snap"
}

run_arm() { # run_arm ARM RUN
    case $1 in
        A | W) "$gm" pause ;;
        B) "$gm" resume ;;
    esac
    log "$2: gaming mode $("$gm" status | head -1)"
    { show_game && snapshot "$2"; } &
    shower=$!
    "$bench/bench/fightrun.sh" "$cfg" "$2" 360 >>"$out" 2>&1
    kill $shower 2>/dev/null
    log "$2: $(tail -1 "$bench/captures/$2/fight.txt" 2>/dev/null)"
    give_back
    sleep 20 # the desktop settles (shell, terminals, thawed apps paging back in)
}

# A warm-up launch first, not counted (W): the first launch reads the game's files cold.
run_arm W "$prefix-W0"
for ((r = 1; r <= rounds; r++)); do
    # Rounds alternate the order (AB, BA, AB...), so neither arm always runs right after the other.
    order=$arms
    ((r % 2)) || order=$(rev <<<"$arms")
    for ((i = 0; i < ${#order}; i++)); do
        run_arm "${order:i:1}" "$prefix-${order:i:1}$r"
    done
done
