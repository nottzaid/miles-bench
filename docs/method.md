# How the bench measures

## The machine

| | |
|---|---|
| GPU | GTX 1060 3 GB, NVIDIA 580.178.04, PCIe 3.0 x16 |
| CPU | i5-4670, 4 cores, no SMT |
| RAM | 7.7 GiB, one DIMM, zram swap |
| OS | CachyOS, Hyprland |
| Game | MilesMorales.exe 1.1116.0.0, via Lutris and GE-Proton11-5 |
| vkd3d-proton | upstream 731c4aae (the commit GE-Proton11-5 ships), plus `patches/` |

The game runs at the same graphics settings in every launch; nothing here lowers them.

## The fight bench

`bench/fightrun.sh <config.env> <run>` measures one launch:

1. `bench/cfgrun.sh` restores the `warehouse` save into the bench's own Wine prefix, starts the game
   with the config's environment, and continues into the Rhino fight checkpoint. The game opens on
   the `gaming` workspace without taking the view or focus (`bench/hyprbench.py`), and renders there
   hidden.
2. `bench/fightdrive.sh` plays the fight with keys injected inside the game process
   (`libs/vkd3d/benchinput.c`): runs, jumps, dodges, and the prompts that move the fight through its
   phases.
3. The game saves automatically at the start of each phase. `bench/fightwin.py 3` scores the launch
   from the start of the fight to the game's 3rd autosave request, read from its own log. A build
   that plays faster would otherwise be measured over later, heavier phases, so every launch is cut
   at the same point of the fight, not after a fixed time.
4. `bench/sample.sh` records memory, I/O and GPU state every 2 s throughout; the frame times come
   from the fork's frame trace (`VKD3D_FRAMETRACE`).

### Series

Two builds are compared in one session, launch by launch, in an alternating order (ABBA, then BAAB
in a second series), so drift over a session hits both. Launches of one build differ by a few
percent, and whole sessions by a few percent more, so a step is only ever compared with the step
before in the same series. A launch's name starts with its series (`v13-S12-1`, `v21-B2`).

### Metrics

| Metric | From |
|---|---|
| fps, 95th / 99th percentile frame time | The frame trace over the window |
| Frames over 40 ms per minute | The same; the headline smoothness measure |
| Frames over 100 ms per fight | The same. Since S8, about 3.6 of the 5.3 per fight come within seconds of the game's 1st or 2nd autosave: its own save stalls |
| Driver-pinned system RAM | GPU memory vkd3d holds in system RAM: Vulkan memory heap #1's usage in vkd3d's log at the end of the run |
| Major faults | The game's page-ins from swap or disk (`/proc/<pid>/stat`), per minute of the window |
| GPU busy | nvidia-smi utilization over the window: the share of time any GPU work ran, the desktop's included |
| Desktop VRAM | Total VRAM in use minus the game's: what every other process held |

### Lossless

A change is kept only if the frames come out the same. Checked with screenshots of a frozen frame
from a fixed Photo Mode camera (`bench/imgdiff.py`), where a change must stay within the difference
between two captures of the same build. Two more checks: the frame trace's `LOSS` lines, which
should read zero (light grid or skinning pages read with nothing behind them), and, for the index
cache, a verify mode that compares the exact bytes every cached draw reads at submission
(0 of 4.9 million draws differed at S15).

## What can skew a comparison

- **The disk.** S5 to S9 ran with the game on the HDD, S12 onward on the SSD. The move fixed the
  driver's shader cache (on the HDD the same shaders compiled again every launch), so S9 to S12 is
  not a pure step.
- **The desktop's video memory.** The game's budget is the card's 3 GB minus what every process
  uses. From series v16 on, the desktop held about 130 MiB less, and on the same S13 build the
  game's budget rose by as much and its pinned RAM fell by 134 MiB. Steps after S13 did not cut
  pinned RAM themselves.
- **Hidden vs on screen.** The bench renders the game hidden. In the gaming-mode series, with the
  game on screen and a warm-up launch first, the same S12 build ran 4.4% faster than in the step
  bench within hours. Relative results hold (both arms are hidden); absolute fps are the bench's.
- **Windows of different length.** The fight takes 130 to 270 s to reach its 3rd autosave, so counts
  that grow with time (slow frames, faults) are reported per minute.

Until 2026-10-15 the launches from v13 on were scored up to a second past the 3rd autosave
request, which caught part of that autosave's own stall; `data/` now scores every launch the same
way (NOTES.md, Dashboard audit).

## Other benches

- **The static scene** (`bench/cfgrun.sh`, before the fight bench): a frozen checkpoint scene with no
  gameplay. It measured unpatched to S5 (30.5 to 49.5 fps); later builds run it close to the 60 fps
  the bench gives its hidden window, so it can only show small differences.
- **The chase** (`saves/user-1013`): the first 150 s of the Rhino chase in free roam, for shader
  compile stalls and the light grid and skinning losses that left an area dark before S12.
- **Live A/B** (`bench/abf.py`, `bench/memab.py`): switching a feature on and off in one running game,
  for features that can toggle live.
- **The open world, uncapped** (S17; `bench/owrun.sh`, `bench/circledrive.sh`, `bench/winscore.py`):
  whole launches from `saves/swing-1017`, with the bench prefix's VSync off for the run, swinging
  in circles around the same blocks by injected keys and scored over about 130 s. Launches of the
  same build spread by several fps, because the city around the route is not the same each time.
  The precise measurements are switches flipped inside one running game: feature bits through the
  live A/B, and system settings (CPU scheduler, governor, C-states, GPU offsets) alternated every
  15 s by `bench/livetoggle.sh` and pooled per setting by `bench/segscore.py`; standing still,
  uncapped, repeats within 0.3 to 0.6 fps. The scripts that drove the S17 runs lived in a scratch
  folder that was cleared; these are re-creations of them (same steps, waits and scoring), checked
  against the bench's interfaces but not re-run. NOTES.md, S17, has the runs.
