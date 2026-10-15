#!/usr/bin/env bash
# Launch Miles Morales the way Lutris does (bench/lutris.env), with the memtrace build of
# vkd3d-proton dropped next to the exe for the duration of the run, and sample memory use.
#
#   bench/run.sh <run-name> [dll-dir]
#
# Output lands in captures/<run-name>/: memtrace.tsv (every D3D12/Vulkan allocation),
# vkd3d.log (vkd3d-proton's own budget log), samples.tsv (RAM/VRAM every 2 s),
# frametrace.tsv (one line per Present).
#
# MEMTRACE=0 skips the allocation trace (its stack captures cost CPU, so leave it off when
# timing). VKD3D_ENGINE_PATCH from the caller's environment passes through (enginepatch.c).
set -euo pipefail

bench=$(cd "$(dirname "$0")/.." && pwd)
game="/home/zaid/Games/Marvel’s Spider-Man - Miles Morales"
run=${1:?usage: run.sh <run-name> [dll-dir]}
# BENCH_DLLS picks another build (e.g. build/qa/install/bin, the descriptor-QA counting build).
dlls=${2:-${BENCH_DLLS:-$bench/build/memtrace/install/bin}}
cap="$bench/captures/$run"

for f in d3d12.dll d3d12core.dll; do
    [[ -f $dlls/$f ]] || { echo "missing $dlls/$f" >&2; exit 1; }
    [[ ! -e $game/$f ]] || { echo "$game/$f already exists; remove it first (left over from a crashed run?)" >&2; exit 1; }
done
mkdir -p "$cap"

sampler_pid=
cleanup() {
    rm -f "$game/d3d12.dll" "$game/d3d12core.dll"
    [[ -n $sampler_pid ]] && kill "$sampler_pid" 2>/dev/null || true
}
trap cleanup EXIT
cp "$dlls/d3d12.dll" "$dlls/d3d12core.dll" "$game/"

winpath() { printf 'Z:%s' "${1//\//\\}"; }

set -a
# shellcheck disable=SC1091
source "$bench/bench/lutris.env"
set +a
# Bench runs use their own prefix (cfgrun.sh sets BENCH_PREFIX): the user's saves and settings in
# their prefix are never touched by a bench run.
[[ -z ${BENCH_PREFIX:-} ]] || export WINEPREFIX=$BENCH_PREFIX
# BENCH_GLCACHE: another NVIDIA shader disk cache directory than the one Lutris sets (the game dir).
[[ -z ${BENCH_GLCACHE:-} ]] || { mkdir -p "$BENCH_GLCACHE" && export __GL_SHADER_DISK_CACHE_PATH=$BENCH_GLCACHE; }
if [[ ${MEMTRACE:-1} != 0 ]]; then
    export VKD3D_MEMTRACE=$(winpath "$cap/memtrace.tsv")
fi
export VKD3D_FRAMETRACE=$(winpath "$cap/frametrace.tsv")
# GPUTIME=1: GPU timeline of one frame in VKD3D_BENCH_GPUTIME_EVERY (gputime.c), off by default
# because its timestamps cost a little on the sampled frames.
if [[ ${GPUTIME:-0} == 1 ]]; then
    export VKD3D_BENCH_GPUTIME=$(winpath "$cap/gputime.tsv")
fi
# QACOUNT=1 (with BENCH_DLLS=build/qa/install/bin and descriptor_qa_checks in the config): per-resource
# shader access counts (descriptor_debug.c), read with bench/qacount.py.
if [[ ${QACOUNT:-0} == 1 ]]; then
    export VKD3D_BENCH_QACOUNT=$(winpath "$cap/qacount.tsv")
fi
export VKD3D_CONFIG=${VKD3D_CONFIG_BASE-log_memory_budget}${VKD3D_CONFIG_EXTRA:+,$VKD3D_CONFIG_EXTRA}
export VKD3D_DEBUG=info
export VKD3D_LOG_FILE=$(winpath "$cap/vkd3d.log")
# Sizes the bench features learned in earlier sessions (learned.c): one file for every run and play
# session, whatever directory the game starts in.
export VKD3D_BENCH_LEARNED_PATH=${VKD3D_BENCH_LEARNED_PATH:-$bench/learned}

"$bench/bench/sample.sh" "$cap/samples.tsv" &
sampler_pid=$!

/usr/bin/umu-run "$game/MilesMorales.exe"
