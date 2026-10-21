# miles-bench

*Marvel's Spider-Man: Miles Morales* on half its recommended PC, with nothing taken away from what
it draws. The machine is a GTX 1060 3 GB, an i5-4670 and 7.7 GiB of RAM; the game asks for a
GTX 1060 6 GB and 16 GB. The game runs through Proton, and every change here lives in
vkd3d-proton, the layer that translates its Direct3D 12 calls to Vulkan. No setting is lowered and
no frame is drawn differently: each change is checked against the unpatched build. It is built
for the game's launch build, `MilesMorales.exe` 1.1116.0.0 ([Using S17](#using-s17)).

## Results

The Rhino fight, played by injected keys from its start to the game's 3rd autosave request, at the
same graphics settings, unpatched against S16, the last step measured in the fight (S17 changes
only the open world and leaves the fight as it was):

| | Unpatched (S0) | S16 | |
|---|---:|---:|---|
| Frames per second | 25.2 | 44.1 | +75% |
| 95th-percentile frame time | 58.9 ms | 30.1 ms | −28.8 ms |
| Frames over 40 ms, per minute | 528 | 14 | −97% |
| Driver-pinned system RAM | 2,616 MiB | 1,941 MiB | −675 MiB |
| The game's memory reads from swap or disk, per minute | 5,700 | 2,900 | −49% |

Step by step (each row is the mean of that step's launches; the last column compares a step only
with launches of the step before in the same series, which is the fair comparison):

| Step | Name | Disk | Launches | fps | Frames over 40 ms / min | Frames over 100 ms / fight | Pinned RAM (MiB) | fps vs previous step, same series |
|---|---|---|---:|---:|---:|---:|---:|---|
| S0 | Unpatched | SSD | 2 | 25.2 | 528 | 10.5 | 2,616 | — |
| S5 | Steps 1-5 | HDD | 2 | 33.2 | 165 | 127 | 2,361 | +35.53% (v10, v11, 2 + 2) |
| S6 | Page drops | HDD | 2 | 33.5 | 162 | 122 | 2,333 | +1.09% (v10, v11, 2 + 2) |
| S7 | Sparse light grid | HDD | 1 | 35.4 | 152 | 166 | 2,043 | +0.28% (v11, 1 + 1) |
| S8 | Index cache fix | HDD | 3 | 38.5 | 46 | 5 | 2,039 | +7.65% (v11, 1 + 1) |
| S9 | Sparse skinning buffer | HDD | 3 | 39.1 | 54 | 5.7 | 1,883 | −0.06% (v12, 2 + 2) |
| S12 | Lighting fix + SSD | SSD | 4 | 42.5 | 17 | 5 | 2,091 | — (the disk changed) |
| S13 | Learned sizes + gates | SSD | 6 | 43.2 | 18 | 5.3 | 2,003 | +0.23% (v15, 2 + 2) |
| S14 | Index cache eviction fix | SSD | 12 | 43.3 | 15 | 5.3 | 1,963 | +0.48% (v16, 4 + 4) |
| S15 | Clear keep | SSD | 16 | 44.0 | 14 | 5.3 | 1,955 | +3.12% (v18, v19, 8 + 8) |
| S16 | Render-thread CPU cuts | SSD | 8 | 44.1 | 14 | 5.5 | 1,941 | +1.22% (v21, v22, 8 + 8) |
| S17 | Open-world index cache | SSD | — | — | — | — | — | not in the fight bench: changes the open world only |

S17 changes only the open world. Swinging there with the game uncapped, whole launches of S17
with the `scx_bpfland` scheduler (how `bench/play.sh` plays it) against S16: 48.0 against 46.6 fps
(+3.0%), frames over 40 ms 5.2 against 12.6 a minute (−59%), frames over 50 ms 1.0 against 2.4 a
minute. Launches spread several fps on the same build; switched live inside one game, S17's index
cache gave +4.5% fps and `scx_bpfland` cut slow frames by about 60%.

Only the last column isolates a step. The disk, the desktop's video memory and the hidden game
window also move the absolute figures; [docs/method.md](docs/method.md) explains how a launch is
measured and what can skew a comparison, and [docs/checkpoints.md](docs/checkpoints.md) what each
step changes and where. The dashboard charts every launch behind these tables:
`python3 dashboard/preview.py` renders it from `data/` into `build/dashboard-preview.html`.

## What is in the repository

| Path | What |
|---|---|
| `patches/` | The vkd3d-proton fork as a patch series on upstream, plus one dxil-spirv patch. `tools/fork.sh` rebuilds the fork from them with the original commit hashes. |
| `bench/` | Launching, driving and measuring the game, the analysis scripts, and one `.env` per build measured. Index in [bench/README.md](bench/README.md). |
| `data/` | The tables behind the results and the dashboard. Described in [data/README.md](data/README.md). |
| `dashboard/` | The dashboard page (`index.html`, drawn from the tables in `data/`) and `preview.py`, which renders it locally. |
| `docs/` | How the bench measures, and what each checkpoint changes. |
| `NOTES.md` | The lab notebook: every finding, measurement and dead end, in the order they happened. |
| `saves/` | Save snapshots the bench loads: `warehouse` (the Rhino fight), `user-1013` (the Rhino chase), `swing-1017` and `user-1017` (the open world). |
| `tools/` | `fork.sh`; `miles-session` (runs `scx_bpfland` for the length of a play session) and its installer; `gpuclk.py` (NVML clock offsets, measured and not used); the Ghidra client and analysis options used for the reverse engineering. |
| `tests/` | A smoke test of the allocation tracer. |
| `flake.nix` | The Nix dev shell: mingw-w64 cross compiler, meson, ninja, glslang, Wine (for widl), Ghidra, Python. |

Not in the repository: `captures/` (11 GB of raw recordings: frame traces, samples, the game's
logs), `analysis/` (decompilations of the game's code and dumps of its shaders, which belong to
its publisher; `tools/ghidra-client/dc.sh` writes the decompilations), `build/`, `prefix/` and the Ghidra
install under `tools/`, and `learned/`, the sizes this machine's sessions learned (every machine
learns its own). The tables in `data/` are rebuilt from the captures by
`bench/datasets.py`. The built DLLs of the current checkpoint are attached to the
`checkpoint-s17` release, with their SHA-256 sums; `tools/fork.sh` tags every checkpoint in the
fork it rebuilds.

## Using S17

S17 is built for `MilesMorales.exe` **1.1116.0.0**, the game's November 2022 launch build. Five of
its patches work on the game's own code and data (page drops, geometry decoding, the index cache,
the sparse light grid and skinning buffers): they check the exe and stay off on any other build,
and no later build has been tried. It was measured with GE-Proton11-5, whose vkd3d-proton is the
fork's base, on an NVIDIA GTX 1060 3 GB. Every feature first checks that it can help (the known
game build, a separate GPU, sparse buffers) and keeps vkd3d-proton's stock behaviour where a check
fails.

1. Get `d3d12.dll` and `d3d12core.dll`: from the `checkpoint-s17` release, or build them (below).
2. Copy both next to `MilesMorales.exe`. Deleting them goes back to stock vkd3d-proton.
3. Switch the features on with environment variables, for example as Steam launch options:

   ```
   VKD3D_BENCH_VRAM_RESERVE=1 VKD3D_ENGINE_PATCH=gdec,dropdst VKD3D_BENCH_INDEX_CACHE=1 VKD3D_BENCH_PARTICLE_BATCH=16 VKD3D_BENCH_DISCARD_KEEP=1 VKD3D_BENCH_PDRAW=1 VKD3D_BENCH_LAZY_HEAPS=1 VKD3D_BENCH_LIGHTGRID_SPARSE=1 VKD3D_BENCH_SKIN_SPARSE=1 VKD3D_BENCH_CLEAR_KEEP=1 %command%
   ```

   or the same variables in Lutris's environment settings. [docs/checkpoints.md](docs/checkpoints.md)
   says what each one does.

The VRAM reserve and the light grid and skinning buffers size themselves from earlier sessions of
the same game build on the same GPU, kept in `vkd3d-proton.MilesMorales.exe.learned`. The first
session has nothing to go on: it runs those three as stock and measures, and the sessions after it
use what it measured. The file goes in the directory the game starts in (normally its own
folder), or in `VKD3D_BENCH_LEARNED_PATH`.

On Linux with a sched_ext kernel, the `scx_bpfland` CPU scheduler during play halved the slow
frames while swinging through the open world in A/B within one game (NOTES.md, 2026-10-21). It is
not part of the DLLs: `bench/play.sh` starts it with the game and stops it at exit through
`tools/miles-session` (`sudo tools/install-miles-session.sh` installs it with a sudo rule for just
that). Running `scx_bpfland` by hand for the session does the same.

To check that it is on, run once with `VKD3D_DEBUG=info` added: vkd3d-proton's log (on Steam,
`PROTON_LOG=1` writes it to `~/steam-<appid>.log`) then has an `engine patch:` or `bench:` line for
each feature it switched on. `engine patch: exe timestamp ... is not the known build` means the
game is not 1.1116.0.0.

## Building

`tools/fork.sh` needs git and network access (it clones upstream); the build needs Nix, whose
flake pins the cross compiler and tools. Without Nix, vkd3d-proton's own build instructions should
apply (mingw-w64, meson, ninja, glslang, widl); that route is untested here.

```sh
tools/fork.sh                                    # src/vkd3d-proton: upstream 731c4aae + patches/, checked by hash
git -C src/vkd3d-proton checkout checkpoint-s17  # S17 itself (the tip of the series today)
nix develop --command bash -c '
  meson setup --cross-file "$MILES_CROSS_FILE" -Dbuildtype=release -Denable_trace=false \
    -Dc_args=-Wno-error=incompatible-pointer-types \
    --prefix "$PWD/build/memtrace/install" build/memtrace src/vkd3d-proton &&
  ninja -C build/memtrace install'
```

The DLLs land in `build/memtrace/install/bin` and should match the `checkpoint-s17` release byte
for byte: check them against its `SHA256SUMS` (independent builds from fresh clones here did).

## Running the bench

The bench scripts are this machine's: they hard-code its paths (`bench/lutris.env`,
`bench/configs/*.env`, the game folder in `bench/run.sh` and `bench/endgame.sh`) and expect the game
installed through Lutris with GE-Proton11-5, and Hyprland with a `gaming` workspace. Bench launches
run in their own copy of the Wine prefix (`prefix/`, copied from the player's) and restore a save
from `saves/` first, so every launch starts from the same checkpoint and nothing touches the
player's own saves; `bench/play.sh` uses the player's prefix (`~/.local/share/wine`).

- `bench/play.sh` plays the game on the current checkpoint with every kept feature switched on, and
  records the session in `captures/`.
- `bench/fightrun.sh <config.env> <run>` measures one launch of the fight; `bench/series.sh`
  interleaves launches of several configs.
- `bench/fightwin.py 3 captures/<run>...` scores launches from the fight's start to the 3rd autosave
  request; `bench/datasets.py` rebuilds `data/` from the captures.

The bench never moves the player's view: the game opens silently on its workspace and renders there
hidden (`bench/hyprbench.py`).

## Licences

The patches modify vkd3d-proton (LGPL-2.1) and dxil-spirv (MIT) and stay under those licences.
`saves/` are save files the game wrote (story progress and settings, no account data). No licence
has been chosen for the rest yet.
