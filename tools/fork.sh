#!/usr/bin/env bash
# Rebuild the vkd3d-proton fork from upstream and patches/: upstream at the pinned base, its
# submodules, the dxil-spirv series inside subprojects/dxil-spirv and the vkd3d-proton series on
# top, each on a branch named miles-bench, with the checkpoint tags. Every commit comes out with
# its original hash (patches/fork.env), which the script checks.
#
#   tools/fork.sh [target dir]      default: src/vkd3d-proton, which must not exist yet
#
# Then build it as in README.md (Building).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
dst=${1:-$root/src/vkd3d-proton}
# shellcheck source=../patches/fork.env
source "$root/patches/fork.env"

if [[ -e $dst ]]; then
    echo "$dst already exists; pass another directory" >&2
    exit 1
fi

am() { # repo, series dir
    git -C "$1" -c user.name="$COMMITTER_NAME" -c user.email="$COMMITTER_EMAIL" \
        am -q --committer-date-is-author-date "$2"/*.patch
}
same() { # repo, expected HEAD, what
    local got
    got=$(git -C "$1" rev-parse HEAD)
    if [[ $got != "$2" ]]; then
        echo "$3: got $got, expected $2" >&2
        exit 1
    fi
    echo "$3: $got (as expected)"
}

git clone -q "$VKD3D_URL" "$dst"
git -C "$dst" checkout -q -b miles-bench "$VKD3D_BASE"
git -C "$dst" submodule update -q --init --recursive

dxil=$dst/subprojects/dxil-spirv
git -C "$dxil" checkout -q -b miles-bench "$DXIL_BASE"
am "$dxil" "$root/patches/dxil-spirv"
same "$dxil" "$DXIL_HEAD" dxil-spirv
git -C "$dxil" tag checkpoint-s12 "$DXIL_HEAD"

am "$dst" "$root/patches/vkd3d-proton"
same "$dst" "$VKD3D_HEAD" vkd3d-proton
for t in $TAGS; do
    git -C "$dst" tag "${t%%=*}" "${t#*=}"
done
git -C "$dst" submodule update -q --recursive
echo "Fork ready in $dst (branch miles-bench; tags: $(git -C "$dst" tag -l 'checkpoint-*' | tr '\n' ' '))"
