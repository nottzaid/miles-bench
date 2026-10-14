#!/usr/bin/env bash
# Drive the game during bench runs: keyboard through ydotool (a uinput device, so the game sees a
# real keyboard) and screenshots through grim. Needs `ydotoold -p /run/user/1000/.ydotool_socket`.
#
#   ui.sh tap <key>...          press and release each key in turn
#   ui.sh hold <secs> <key>...  hold the keys together for <secs>
#   ui.sh shot <file.png>       half-scale screenshot of the game monitor
set -euo pipefail
export YDOTOOL_SOCKET=/run/user/1000/.ydotool_socket

declare -A code=(
    [esc]=1 [enter]=28 [tab]=15 [space]=57 [shift]=42 [ctrl]=29 [alt]=56
    [up]=103 [down]=108 [left]=105 [right]=106
    [w]=17 [a]=30 [s]=31 [d]=32 [e]=18 [f]=33 [q]=16 [r]=19 [m]=50 [p]=25 [v]=47 [x]=45 [z]=44 [c]=46 [g]=34 [t]=20 [y]=21 [1]=2 [2]=3 [3]=4 [4]=5
)

keycode() { [[ -n ${code[$1]:-} ]] || { echo "unknown key: $1" >&2; exit 1; }; echo "${code[$1]}"; }

case ${1:-} in
    tap)
        for k in "${@:2}"; do
            c=$(keycode "$k")
            ydotool key "$c:1"; sleep 0.08; ydotool key "$c:0"; sleep 0.35
        done ;;
    hold)
        secs=$2; shift 2
        for k in "$@"; do ydotool key "$(keycode "$k"):1"; done
        sleep "$secs"
        for k in "$@"; do ydotool key "$(keycode "$k"):0"; done ;;
    shot)
        grim -o HDMI-A-1 -s 0.5 "$2" ;;
    *)
        sed -n '2,8p' "$0"; exit 1 ;;
esac
