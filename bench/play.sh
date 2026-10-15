#!/usr/bin/env bash
# Play Miles Morales on the best build the bench has kept so far, and record the session for
# hitch and streaming analysis (frame times, RAM/VRAM/disk samples, the game's own log).
#
#   ~/Projects/miles-bench/bench/play.sh [session-name]
#
# The game opens the way it does from Lutris (the user's config puts it on "gaming" and goes
# there). Quit the game normally; the bench DLLs are removed from the game folder afterwards.
# Kept steps (NOTES.md; series v6-prog: 30.5 -> 49.5 fps in the static scene; gameplay series
# v11/v12, the driven fight to its 3rd autosave: stock 24.9 fps -> ~38.6 fps, frames over 100 ms
# 15 -> ~5, p99 74 -> ~45 ms; all exact): VRAM reserve, geometry decompression fix, index cache
# (with fail-fast allocation, the binary's default), particle batching, discard barriers,
# particle draw constants, lazy descriptor heaps, dead-destination page drops (dropdst), sparse
# light grid, sparse skinning buffer (both backed further up front since 2026-10-14: in the open
# world they had run out of VRAM, and missing light grid pages left an area dark). The game
# lives on the SSD since 2026-10-14: its NVIDIA shader cache (the game folder, as Lutris sets it)
# was unusable on the HDD, so the same shaders were compiled, and froze the game, every launch.
set -euo pipefail
bench=$(cd "$(dirname "$0")/.." && pwd)
name=${1:-play-$(date +%m%d-%H%M)}

if pgrep -x MilesMorales.ex >/dev/null; then
    echo "The game is already running." >&2
    exit 1
fi

# S13: the VRAM reserve, the budget held back from the game and the light grid / skinning backing are
# sized from what earlier sessions measured (learned/, see run.sh), not fixed (NOTES.md, S13).
export VKD3D_BENCH_VRAM_RESERVE=1
export VKD3D_ENGINE_PATCH=gdec,dropdst
export VKD3D_BENCH_INDEX_CACHE=1
export VKD3D_BENCH_PARTICLE_BATCH=16
export VKD3D_BENCH_DISCARD_KEEP=1
export VKD3D_BENCH_PDRAW=1
export VKD3D_BENCH_LAZY_HEAPS=1
export VKD3D_BENCH_LIGHTGRID_SPARSE=1
export VKD3D_BENCH_SKIN_SPARSE=1
export VKD3D_CONFIG_BASE=
export MEMTRACE=0
# The frozen checkpoint build (S13: checkpoint-s12 + patches/vkd3d-proton-checkpoint-s13.patch,
# build/checkpoint-s13/SHA256SUMS), not build/memtrace: experiments rebuild that one, and a play
# session must never pick them up. S12 stays in build/checkpoint-s12 (PLAY_DLLS to go back).
export BENCH_DLLS=${PLAY_DLLS:-$bench/build/checkpoint-s13/bin}
"$bench/bench/run.sh" "$name"
cp "$HOME/.local/share/wine/pfx/drive_c/users/zaid/Documents/Marvel's Spider-Man Miles Morales/Marvel's Spider-Man Miles Morales.log" \
    "$bench/captures/$name/game.log" 2>/dev/null || true
echo "Session recorded in $bench/captures/$name"
