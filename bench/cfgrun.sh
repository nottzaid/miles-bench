#!/usr/bin/env bash
# One unattended fps measurement of a vkd3d build/config in the scene the user's save loads into
# (2026-10-12: Rhino fight, frozen "Press to Venom Punch" prompt). The game opens on the user's own
# "gaming" workspace without taking the view or focus there (bench/hyprbench.py), so Super+G shows
# it any time; keys reach it from inside its process. Launch, Play, wait for the main menu,
# Continue, wait until the scene has been drawing at full detail for a while, measure 30 s, quit.
# captures/<run>/user-view.tsv logs the user's workspaces and focused window every second.
#
#   bench/cfgrun.sh <run-name> [extra VKD3D_CONFIG flags]
#
# The environment passes through to the game (VKD3D_BENCH_*, VKD3D_ENGINE_PATCH,
# VKD3D_CONFIG_BASE, MEMTRACE). Result: captures/<run>/window.txt and scene.png.
set -euo pipefail
bench=$(cd "$(dirname "$0")/.." && pwd)
run=${1:?usage: cfgrun.sh <run-name> [config]}
cap="$bench/captures/$run"
hb() { python3 "$bench/bench/hyprbench.py" "$@"; }
log() { printf '%s %s\n' "$(date +%T)" "$*"; }

# The user's own game session (or a leftover one) wins: no bench run while the game is up. This is
# before the EXIT trap, which ends the game.
if pgrep -x MilesMorales.ex >/dev/null; then
    log "the game is already running; not starting a bench run"
    exit 2
fi
# The bench's own Wine prefix (a clone of the user's), with the frozen save restored before every
# run: every run starts from the same checkpoint, and nothing the user does in a bench game (or in
# their own) carries over. BENCH_SAVE picks the snapshot in saves/.
export BENCH_PREFIX=${BENCH_PREFIX:-$bench/prefix}
docs="$BENCH_PREFIX/pfx/drive_c/users/zaid/Documents/Marvel's Spider-Man Miles Morales"
save_dir=$(find "$docs" -mindepth 1 -maxdepth 1 -type d -name '7656119*' | head -n 1)  # the Steam account's save folder
[[ -d $bench/saves/${BENCH_SAVE:-warehouse} && -d $save_dir ]] || { log "missing bench prefix or save snapshot"; exit 2; }
rsync -a --delete "$bench/saves/${BENCH_SAVE:-warehouse}/" "$save_dir/"
hb setup
mkdir -p "$cap"
# Detached (setsid -f), so the game's parent chain ends at the user's systemd instead of running up
# to the terminal this script runs in: Hyprland's window swallowing walks that chain and would hide
# a matching terminal window behind the game (Window.cpp:1622 has no workspace check).
rm -f "$cap/run.pid"
VKD3D_BENCH_INPUT=1 VKD3D_CONFIG_EXTRA=${2:-} MEMTRACE=${MEMTRACE:-0} setsid -f bash -c \
    'echo $$ > "$1/run.pid"; exec "$2/bench/run.sh" "$3"' _ "$cap" "$bench" "$run" > "$bench/build/$run-launcher.log" 2>&1
for _ in $(seq 1 50); do [[ -s $cap/run.pid ]] && break; sleep 0.1; done
launcher=$(cat "$cap/run.pid")
wait_launcher() { for _ in $(seq 1 240); do kill -0 "$launcher" 2>/dev/null || return 0; sleep 0.5; done; }
(while sleep 1; do
    printf '%s\t%s\t%s\n' "$(date +%T)" \
        "$(hyprctl -j monitors | jq -r 'map("\(.name)=\(.activeWorkspace.name)\(if .focused then "*" else "" end)") | join(" ")')" \
        "$(hyprctl -j activewindow | jq -r '.class // "-"')"
done > "$cap/user-view.tsv") &
viewlog=$!
python3 "$bench/bench/hyprbench.py" events "$cap/hypr-events.tsv" &
events=$!
# While the user plays the bench game (it has focus), screenshot it every 3 s into play/, so
# anything they see can be looked at afterwards. Such a window is DISTURBED anyway.
mkdir -p "$cap/play"
(while sleep 3; do
    [[ $(hyprctl -j activewindow | jq -r '.class // ""') == steam_app* ]] &&
        python3 "$bench/bench/hyprbench.py" shot "$cap/play/$(date +%H%M%S).png" 2>/dev/null
done) &
playshots=$!
# KEEP_GAME=1: stop once the scene is up and leave the game running (for driving it by hand); the
# rule stays on until `hyprbench.py teardown`.
if [[ ${KEEP_GAME:-0} == 1 ]]; then
    trap 'kill $viewlog $events $playshots 2>/dev/null' EXIT
else
    trap 'kill $viewlog $events $playshots 2>/dev/null; pkill -TERM -x MilesMorales.ex 2>/dev/null || true; wait_launcher; hb teardown' EXIT
fi

for _ in $(seq 1 90); do grep -qa 'Created device\|d3d12_device_caps_init_feature_options4' "$cap/vkd3d.log" 2>/dev/null && break; sleep 2; done
# The launcher draws nothing through vkd3d; frames start once Play is taken. Enter goes to its
# window procedure as a posted WM_KEYDOWN, which it acts on without needing focus.
for try in $(seq 1 30); do
    sleep 2
    grep -q '^F' "$cap/frametrace.tsv" 2>/dev/null && break
    if hb input enter >/dev/null; then
        log "launcher: Play ($try)"
        for _ in $(seq 1 10); do sleep 2; grep -q '^F' "$cap/frametrace.tsv" 2>/dev/null && break 2; done
    fi
done
grep -q '^F' "$cap/frametrace.tsv" || { log "launcher ignores Play"; exit 1; }

# The main menu comes up by itself after the intro logos and the title cinematic, and it needs a
# moment before it takes input. One loop until the scene is up: whenever the menu has been on
# screen for two checks in a row, press Continue (again). Gameplay is recognised by the HUD
# (hyprbench.py hud), which works for any checkpoint; settled = HUD on screen for 21 s in a row
# (the load, the checkpoint's intro and the streaming burst after it are over by then). A
# screenshot every ~15 s goes to shots/ so a failed run can be read afterwards.
mkdir -p "$cap/shots"
shot="$cap/menu.png"
# Open-world saves do not autosave on arrival: there, once Continue was taken and the menu is gone,
# gameplay is the last 100 frames averaging over 1900 draws (the title cinematic behind the menu
# draws ~1650, loading screens far fewer; swinging in the city 2200-3500).
gameplay_draws() {
    tail -n 400 "$cap/frametrace.tsv" | awk -F'\t' '$1 == "F" {d[n++ % 100] = $4} END {
        if (n < 100) exit 1; for (i = 0; i < 100; i++) s += d[i]; exit !(s / 100 > 1900) }'
}
pressed=0 seen=0 steady=0 n=0 start=$SECONDS
while (( SECONDS - start < 420 )); do
    sleep 3
    n=$((n + 1))
    hb shot "$shot" || continue
    (( n % 5 )) || cp "$shot" "$cap/shots/$(printf %03d $((SECONDS - start))).png"
    # CFGRUN_NOHUD=1: once the save is loaded, nothing on screen is the menu any more (a failed
    # chase shows a "Rhino escaped!" card the menu check mistakes for it, and Enter there restarts).
    if [[ ${CFGRUN_NOHUD:-0} == 1 ]] &&
            grep -qa 'Request save type 0' "$docs/Marvel's Spider-Man Miles Morales.log" 2>/dev/null; then
        steady=$((steady + 3))
        (( steady >= 21 )) && break
        continue
    fi
    if hb menu "$shot"; then
        seen=$((seen + 1)); steady=0
        if (( seen >= 2 )); then
            (( pressed < 5 )) || { log "menu ignores Continue"; exit 1; }
            hb input enter || log "Continue not delivered"
            pressed=$((pressed + 1)); seen=0
            log "menu: Continue ($pressed)"
        fi
        continue
    fi
    seen=0
    (( pressed > 0 )) || continue
    # CFGRUN_NOHUD=1: any screen but the menu counts once the game has loaded the save (the game
    # autosaves on arrival; the title screen behind the menu is not the menu either), for checkpoints whose
    # HUD the check misses, such as a chase that keeps restarting.
    if [[ ${CFGRUN_NOHUD:-0} == 1 ]]; then
        if grep -qa 'Request save type 0' "$docs/Marvel's Spider-Man Miles Morales.log" 2>/dev/null || gameplay_draws; then
            steady=$((steady + 3))
        else
            steady=0
        fi
    elif hb hud "$shot"; then steady=$((steady + 3)); else steady=0; fi
    (( steady >= 21 )) && break
done
(( steady >= 21 )) || { log "scene never settled"; exit 1; }
continued=$start
log "scene settled after $((SECONDS - continued)) s"
sleep 10
hb shot "$cap/scene.png"
hb where | tee "$cap/where.txt"
[[ ${KEEP_GAME:-0} != 1 ]] || { log "leaving the game running"; exit 0; }
python3 "$bench/bench/window.py" "$cap/frametrace.tsv" 30 | tee "$cap/window.txt"
# The game's own once-a-minute telemetry (texture usage, demoted bytes, budgets) for this run.
sleep 2
cp "$docs/Marvel's Spider-Man Miles Morales.log" "$cap/game.log" || true
