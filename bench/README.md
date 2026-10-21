# bench

Every script says how to call it in its header. By purpose:

## Launching and driving the game

| Script | What |
|---|---|
| `play.sh` | Play on the current checkpoint with every kept feature on, and record the session |
| `run.sh` | Launch the game the way Lutris does (`lutris.env`) with a bench build of vkd3d-proton next to the exe for the run, and sample memory |
| `cfgrun.sh` | One unattended launch of a build and config: restore a save in the bench prefix, continue into the scene |
| `fightrun.sh` | One measured launch of the Rhino fight (cfgrun.sh, then fightdrive.sh, then fightsum.py) |
| `fightdrive.sh` | Plays the fight with keys injected inside the game: runs, jumps, dodges, the phase prompts |
| `series.sh` | Interleaved launches of several configs (A B C A B C …) |
| `gmseries.sh` | The gaming-mode A/B: interleaved fight launches with the game on screen |
| `probe.sh`, `fightprobe.sh` | One diagnostic launch: GPU timeline and allocation trace, or per-thread CPU during the fight |
| `withcfg.sh` | Run a command with a `configs/*.env` file's variables exported |
| `endgame.sh` | End a bench game completely and take the bench DLLs out of the game folder |
| `hyprbench.py` | Keep the game on its workspace without moving the user's view or focus; key input and screenshots |
| `ui.sh` | Keyboard and screenshots through ydotool and grim (older runs) |
| `sample.sh` | Every 2 s: the game's memory, swap, pinned RAM, VRAM, reads and faults, and GPU use |
| `configs/` | One `.env` per build and feature set measured; `s17-frozen.env` is the current build |

## Scoring launches

| Script | What |
|---|---|
| `fightwin.py` | Score fight launches from the fight's start to the game's Nth autosave request |
| `fightsum.py` | Fight summary for fightrun.sh (frame times, swap-ins, faults, pinned RAM, the game's telemetry) |
| `datasets.py` | Rebuild `data/launches.csv`, `vram.csv` and `gaming_mode.csv` from the captures |
| `fightcsv.py`, `runsum.py`, `gmsum.py` | One line per launch, or per arm of a gaming-mode series |
| `window.py`, `timeline.py` | Frame statistics of a live trace; a samples.tsv as a timeline |

## The open world, uncapped (S17)

Re-created after the S17 runs (their scratch copies were cleared); not re-run since. docs/method.md,
Other benches.

| Script | What |
|---|---|
| `owrun.sh` | One whole open-world (`saves/swing-1017`) or warehouse launch with VSync off for the run, optionally with `scx_bpfland` from launch to exit |
| `circledrive.sh` | The circle route by injected keys, with a stuck check that turns Miles back when fps say he is against a wall |
| `winscore.py` | fps and tails between two frame-trace times |
| `livetoggle.sh`, `segscore.py` | Alternate a system setting (scheduler, governor, C-states, GPU offsets) in one running game; pool the segments per setting |

## Live A/B in a running game

| Script | What |
|---|---|
| `abf.py` | Alternate the engine's feature mask between two values and measure each window |
| `ab.py` | The same for the spin patch |
| `memab.py`, `memhog.c` | Is the game limited by DRAM bandwidth: windows with no load, a CPU-only load and a DRAM load |
| `enginectl.py` | Read or flip the engine patch control block inside the game |
| `budget.py` | Read or change the engine's named memory budgets |

## GPU

| Script | What |
|---|---|
| `gputime.py` | Where a frame's GPU time goes, from the GPU timestamps (`VKD3D_BENCH_GPUTIME`) |
| `gpugaps.py`, `gpuflow.py` | The direct queue's idle time: what each gap waited on (the game, vkd3d's queue thread, the GPU starting), and a continuous timeline |
| `gpudiff.py`, `gpuwin.py` | Heavy against light frames; pass times per same-session window |
| `qacount.py` | Which resources the shaders actually touch, and whether they sit in VRAM or system memory |

## CPU, hitches and memory bandwidth

| Script | What |
|---|---|
| `cpuprof.py`, `threadcpu.py` | Where one game thread spends its CPU time; CPU time per frame for every thread |
| `hitch.py` | What the game's threads were doing during the slowest frames |
| `statepoll.py` | The render thread's state over time, read from outside the game |
| `imc.py`, `missprof.py`, `ldlat.py` | DRAM traffic by source; which code misses L3; which loads stall and on what memory |

## Memory and paging

| Script | What |
|---|---|
| `memreport.py`, `heapuse.py` | Summaries of the allocation trace (`VKD3D_MEMTRACE`) |
| `faultprof.py`, `loadprof.py` | Where the game's major faults happen; what a launch and a save load wait on |
| `coldpages.py`, `zramhuge.py` | Pages that stay swapped out; pages zram could not compress |
| `pagesample.py`, `regionpeek.py` | What a region of the game's memory holds |
| `lgpages.py` | The light grid page allocator's state |
| `ioreplay.py` | Replay the game's streaming reads against the disk under different I/O strategies |

## The game binary and frames

| Script | What |
|---|---|
| `disas.py`, `disasf.py`, `fn.py` | Disassemble the game's code from memory or from the file, with annotations |
| `imgdiff.py` | Compare two screenshots of the same frozen frame (the lossless check) |
