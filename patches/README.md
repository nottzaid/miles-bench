# patches

The vkd3d-proton fork, as a series of commits on upstream, so this repository carries it without
upstream's history. The same commits and checkpoint tags are on GitHub: `vkd3d-proton/fork` and
`dxil-spirv/fork` link to the forks at the commit each series ends on (links only: `git submodule
update` skips them).

| Series | Upstream | Base |
|---|---|---|
| `vkd3d-proton/` | https://github.com/HansKristian-Work/vkd3d-proton | 731c4aae, the commit GE-Proton11-5 ships |
| `dxil-spirv/` | https://github.com/HansKristian-Work/dxil-spirv (vkd3d-proton's `subprojects/dxil-spirv`) | cc75a0c9, the commit that base pins |

| Patch | Checkpoint | What |
|---|---|---|
| vkd3d-proton 0001 | S12 | Every step kept up to S12 (S5 to S9 and the lighting fix), and the bench's instrumentation: allocation trace, frame trace, GPU timing, in-process key input |
| vkd3d-proton 0002 | S13 | Sizes learned from earlier sessions, gates for other machines |
| vkd3d-proton 0003 | S14 | Index cache eviction frees whole runs |
| vkd3d-proton 0004 | S15 | Clear keep, review fixes |
| vkd3d-proton 0005 | | Index cache verify mode: compares the exact bytes each cached draw reads at submission |
| vkd3d-proton 0006 | S16 | Render-thread CPU cuts |
| vkd3d-proton 0007 | | Diagnostics: submission and present timing (off unless enabled) |
| vkd3d-proton 0008 | | Bench input: more keys, autorepeat while held, virtual XInput pad |
| vkd3d-proton 0009 | | Index cache mirrors GPU copies into the geometry heap instead of turning itself off; PSO and allocation diagnostics (off unless enabled) |
| vkd3d-proton 0010-0012 | S17 | Deferred command recording through a replay worker (off unless `VKD3D_BENCH_CMD_REPLAY=1`; measured no gain), review fixes |
| vkd3d-proton 0013 | | The dxil-spirv submodule's URL names the dxil-spirv fork, which carries its commit (no source change; `checkpoint-s17` is the commit before) |
| dxil-spirv 0001 | S12 | Per-resource access counting for the descriptor-QA build |

`fork.env` pins the bases, the commit each series ends on and the checkpoint tags.

## Rebuilding the fork

```sh
tools/fork.sh [dir]      # default src/vkd3d-proton
```

It clones upstream, checks out the base with its submodules, applies the dxil-spirv series inside
`subprojects/dxil-spirv` and the vkd3d-proton series on top, each on a branch `miles-bench`, and tags
the checkpoints. Each commit was made with the committer and dates equal to the author's, and
`git am --committer-date-is-author-date` reproduces that, so every commit comes out with its original
hash; the script stops if one does not.

## Updating the series

After new commits on the fork's `miles-bench` branch:

```sh
git -C src/vkd3d-proton format-patch -q --zero-commit --no-signature -o "$PWD/patches/vkd3d-proton" 731c4aae..miles-bench
git -C src/vkd3d-proton/subprojects/dxil-spirv format-patch -q --zero-commit --no-signature -o "$PWD/patches/dxil-spirv" cc75a0c9..miles-bench
```

then update `VKD3D_HEAD`, `DXIL_HEAD` and `TAGS` in `fork.env`, and run `tools/fork.sh` into a
scratch directory to check it. Commit with the committer equal to the author and the same date
(a plain `git commit` does; an amend or a rebase moves the committer date unless given
`--committer-date-is-author-date`), or the hashes will not reproduce.

Then push the branches and the new tags to the forks on GitHub (unarchive them first; the
dxil-spirv fork only if its series changed) and move the links to the new heads:
`git update-index --cacheinfo 160000,<VKD3D_HEAD>,patches/vkd3d-proton/fork` (and the same for
`dxil-spirv/fork`), then commit them with `fork.env`.
