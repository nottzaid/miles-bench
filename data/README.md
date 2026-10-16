# data

The tables behind the results in README.md and the dashboard (`dashboard/`), one CSV each.

## Built from the captures

`python3 bench/datasets.py` rebuilds these three from `captures/` (`--check` compares instead of
writing). Every launch is scored from the fight's start to the game's 3rd autosave request
(docs/method.md).

| File | One row per | Columns |
|---|---|---|
| `launches.csv` | fight bench launch (`runs.csv`) | step, disk, fps, p95_ms, p99_ms, frames_over_40ms, frames_over_100ms, worst_ms, window_s, over40_per_min, game_major_faults, pinned_ram_mib, gpu_busy_pct, desktop_vram_mib, over100_near_autosave |
| `vram.csv` | launch marked `in_vram_table` in `runs.csv` | the engine's last VRAM report: video_budget_mib, video_usage_mib, texture_usage_mib, demoted_mib; desktop_vram_mib |
| `gaming_mode.csv` | gaming-mode launch (`gm_runs.csv`) | arm, fps, p99_ms, frames_over_100ms, window_s, game_major_faults; swap-ins over the whole run (swapins_whole_run, whole_run_s, swapins_per_s); the engine's mean budget and usage, pinned RAM, demoted textures, its budget at startup; desktop_vram_mib |

- `pinned_ram_mib` and `demoted_mib` are end-of-run states, and the gaming-mode swap-ins cover the
  whole run, because those counters were read only at its start and end.
- `over100_near_autosave` counts frames over 100 ms that ended between 1 s before and 4 s after the
  game's 1st or 2nd autosave request.
- `desktop_vram_mib` is total VRAM in use minus the game's, averaged over the window.

Inputs: `runs.csv` (capture, step, disk, whether it goes in the VRAM table) and `gm_runs.csv`
(series, capture, launch order, arm).

## Written by hand

| File | What | Source |
|---|---|---|
| `steps.csv` | Each checkpoint: order, name, what it changes, kind | docs/checkpoints.md |
| `headroom.csv` | What is left to gain after S16 and what each part would take | NOTES.md, S16 and its follow-up |
| `gpu_frame.csv` | Average GPU time per frame by kind of segment at S15 | `bench/gputime.py` on v20-S15-gt |
| `static_scene.csv` | The static scene, two rounds per arm, unpatched to S5 | series v6-prog |
| `chase.csv` | Shader compiling and missing-lighting submissions in the first 150 s of the chase | psoA/B/P/Q and ssd1-3 captures |

The figures in `headroom.csv` that come from launches (GPU busy, pinned RAM, VRAM) are the means of
`launches.csv` and `vram.csv` for S16; the rest cite the capture they come from.
