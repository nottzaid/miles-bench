# miles-bench

Goal: Marvel's Spider-Man: Miles Morales running on half the recommended spec
(16 GB RAM / GTX 1060 6GB → this machine: 7.7 GiB RAM, GTX 1060 3GB) with no loss in output.
"Lossless" is checked, not assumed: every change gets a before/after frame comparison at a fixed
photo-mode camera, plus the memtrace and sampler numbers.

## Target

| What | Version |
|---|---|
| Game | MilesMorales.exe 1.1116.0.0 (launch build, Nov 18 2022), 61 MiB .text, no packer/DRM sections |
| Proton | GE-Proton11-5 via Lutris + umu-run, prefix `~/.local/share/wine` |
| vkd3d-proton | 731c4aae5 (`src/vkd3d-proton`, same commit as GE-Proton11-5) |
| Driver | NVIDIA 580.178.04 |

Middleware in the process that can also allocate GPU memory: NVIDIA Streamline
(sl.interposer.dll), XeSS (libxess.dll), FSR2, Bink, HBAO+ (D3D11).

## Baseline, 2026-10-10, idle in game, stock vkd3d-proton

RAM (`/proc/<pid>/smaps`):
- RSS 3.3 GiB + 1.4 GiB in zram swap (zram is RAM too: 1.8 GiB swapped data held in 855 MiB).
- 1.55 GiB of the RSS is `/dev/nvidiactl` mappings: system RAM the NVIDIA driver allocated for
  Vulkan host-visible memory (one 800 MiB block, one 128 MiB, several 61-64 MiB). Pinned, so it
  cannot be swapped; memory pressure falls on the game's own heap instead.
- Game/Wine anonymous memory: 1.58 GiB resident + 1.28 GiB swapped. Large VirtualAlloc arenas
  (e.g. 991 MiB reserved, 284 MiB resident).
- A later sample (during the toolchain download) had RSS 2.4 GiB / swap 2.5 GiB: the swappable
  heap got pushed out while the pinned driver memory stayed.

VRAM (nvidia-smi): 3004 / 3072 MiB used. Game 2347 MiB; desktop 480 MiB
(noctalia 259, Hyprland 180, kitty 42).

Open question #1: what is in the 1.55 GiB of driver-pinned system RAM? Candidates: D3D12 upload
heaps (streaming staging), readback heaps, or DEFAULT-heap resources that spilled out of full VRAM.
memtrace answers this directly.

## Play session, 2026-10-10 (stock vkd3d-proton, `captures/stock-play/`)

`bench/timeline.py captures/stock-play/samples.tsv`. ~6 min, of which ~4 min in play.
- Driver-pinned RAM 1553 MiB and game VRAM ~2430 MiB were flat for the entire session: fixed pools
  sized at startup, not streaming-dependent.
- Streaming bursts (t=61, 108, 177, 204-225 s) read 25-41 MB/s from the HDD and at the same time
  swap the game's heap back in from zram at up to 14k major faults/s (~56 MB/s); GPU utilisation
  drops to 38-69% during them. Steady play: ~0.5 MB/s disk, ~250 faults/s.
- The game's own resident heap swings 0.7-1.8 GiB with 1.5-2.7 GiB of it in zram.
- Storage: game is on sda, a WD5000AAKX 7200 rpm HDD (btrfs zstd:3). /home is a Kingston SSD.

## Bench status

- memtrace build: `build/memtrace/install/bin/{d3d12,d3d12core}.dll`. Loads in Proton from the
  app dir (build string `731c4aae5991b33+`). nixpkgs' mingw gcc uses the mcf thread model, so the
  DLLs also import ntdll keyed-event/section functions (mcfgthread, statically linked); upstream's
  build doesn't. Wine implements them; revisit if anything thread-related misbehaves.
- `tests/memtrace_smoke.c`: committed/upload/heap/placed/SetName/release, prints its own function
  RVAs to compare with memtrace's exe_rva column. Not yet passed: while the game runs, VRAM is so
  full that a second Vulkan device fails with VK_ERROR_OUT_OF_DEVICE_MEMORY. Run with the game closed:
  test prefix is `build/testpfx`, see the command in the session log / run.sh env.

## Findings, 2026-10-10 evening (traces in captures/trace1, captures/trace2-l0sys)

- memtrace smoke test passed under GE-Proton (tests/memtrace_smoke.c): sizes, names, and exe_rva all
  land in the right functions.
- The game writes its own memory telemetry once a minute to
  `~/.local/share/wine/pfx/drive_c/users/zaid/Documents/Marvel's Spider-Man Miles Morales/*.log`:
  Video Budget/Usage, Sys Usage, Tex Usage/Budget, Demoted, fps. Copied per run as captures/<run>/game.log.
- Engine budget table (bench/budget.py reads/writes it live): {entries*, count} at RVA 0x84aecf0,
  24-byte entries {name*, len, crc, bytes}. Values: AssetHeap 996, FileSystem 680, ManagedBuffer 800,
  InitAllocator 404, DynamicHeap 384, SoundBank 264, Physics 256, TextureAlloc 3320,
  TextureAllocLow/Medium/High/Ultra 1000/2000/3000/3874 MiB, ... /proc/<pid>/mem is readable and
  writable for the game (Wine relaxes ptrace for it).
- GPU-visible system RAM is ~2.5 GiB (half of it unmapped, so invisible in RSS). VRAM ~2.2 GiB.
  - ManagedBuffer: 800 MiB WC sysmem buffer from D3DBufferManager::InitBuffer (fn 0x1d6e0e0);
    high-water 620 MiB early in a session. Not much slack.
  - Render targets: aliased ~4x inside 498 MiB of heaps. Heaps overall 93% full. Not wasteful.
  - Streamed textures: ~940 MiB "Demoted" to system RAM. Texture budget for Medium is 2000 MiB but
    only ~1.1 GiB fits in VRAM next to RTs/buffers.
- Hypothesis tested and rejected: vkd3d placing CUSTOM/L0/NOT_AVAILABLE heaps in VRAM causes a
  demotion loop. VKD3D_BENCH_L0_SYSMEM=1 moves them to sysmem (placement now matches Windows) but
  Demoted/Video Usage/Sys Usage are unchanged (938 vs 936 MiB). Kept as an option, not a memory win.
- In progress: texture budget experiment. Photo Mode gives a deterministic frame (two captures:
  PSNR 68.5 dB, 0 px changed). Frame A captured at budget 2000 (captures/trace2-l0sys/photo/A.png).
  TextureAllocMedium set to 1100 in the live process; the game only applies it when Texture Quality is
  changed in Settings (not on its own, not on checkpoint reload). B (1100) and A2 (2000 again) still to do.
- Driving the game: bench/ui.sh (ydotool + grim). Hyprland is Lua-configured:
  `hyprctl dispatch 'hl.dsp.focus({ workspace = "name:gaming" })'`. The save is in the opening Rhino
  chase: leaving Photo Mode resumes play and the chase fails after a few seconds; Esc doesn't pause
  during the "Press C" tutorial prompt.

## Findings, 2026-10-11: smoothness (captures/spin-ab*, rt-attr, gpuprof*, cfg-*)

- Gameplay steady state is GPU-bound: frozen "Press C" prompt scene, 32-33 fps, GPU 93-97%,
  Render Thread ~80% of a core, process ~270% of 400%. Internal res 968x544 + FSR2 to 1080p.
- Every CPU wait for the GPU in the renderer is a busy loop (pause x50 helper 0x20c6840, QPC
  timeout check 0x1d9f400). Sites: PushBuffer::WaitForFrame 0x1d7c6ab, RenderPipeline::WaitFor
  x4, RenderDataRing::WaitForTail, three bare fence waits, and the query readback loop 0x1d98783
  (engine D3D11-style GetData at 0x1deb000 polls the query's fence). In the in-game pause menu the
  Render Thread burns 100% of a core at GPU 7%. Patch: `VKD3D_ENGINE_PATCH=spin` (enginepatch.c)
  redirects those calls to a blocking fence wait, 11/11 sites, stable, toggle live with
  `bench/enginectl.py spin=0|1`. In GPU-bound gameplay the spin is only 1-3% of a core, so fps is
  unchanged; it frees a core when frames are cheap (menus, loading).
- Title-screen hitches every ~5.4 s (100-160 ms) are camera cuts in the title cinematic: the cut
  frame redraws the main view with ~5.7k draws (vs ~300) because last-frame occlusion data is
  invalid. Not gameplay. Found with frametrace R lines (draws per render target per frame).
- Exe load base moves between runs (0x6ffff4610000, 0x6ffff4630000): always read it from
  /proc/<pid>/maps before mapping perf addresses (build/exe-base).
- No PIX markers in this retail build. NVIDIA Pascal reports shaderFloat16=0, so vkd3d reports
  Native16BitShaderOpsSupported=0 (no slow-FP16 trap).
- vkd3d's timestamp profiler (-Denable_profiling, needs -Wno-error=incompatible-pointer-types
  with GCC 15) stalls after ~150 frames with this game; not usable as-is.
- Streaming I/O: ~95% of disk reads come from one thread, "NxStorage Command", as synchronous
  ReadFile (no OVERLAPPED), median 146 KiB, one at a time. NxStorage has a DirectStorage path
  (`EnableDirectStorage` config bool read at 0x1c08061, `LoadLibrary("dstorage.dll")` +
  DStorageGetFactory at 0x2218750) that is off in this port; archives are DSAR v3.
- Archives on btrfs (compress=zstd:3) are fragmented: 6634 physical discontinuities over 47 GiB,
  2.4 GiB in <=512 KiB extents, 1181 btrfs-compressed extents. Worst: g00s001 (966 extents).
- `bench/ioreplay.py` replays a checkpoint reload's 3169 reads with cold page cache (and a 512 MiB
  read to flush the drive cache): serial 7.5 s, QD8 6.9-8.2 s, coalescing gaps <=256 KiB 6.7 s.
  Contiguous uncompressed copies (/mnt/games/.miles-bench-layout, 3 files) were 3-30% faster
  serially (noisy). In-game the same reads took 13.4 s inside pread: CPU contention and other HDD
  users (NVIDIA GLCache lives in the game dir on the HDD) cost more than layout.

## Findings, 2026-10-12: the GPU is starved over PCIe (live play, stock GE vkd3d)

- `nvidia-smi dmon -s pt` while swinging around in play: SM "busy" 81-99%, yet 47-70 W of the 120 W
  limit at full clocks (1923 MHz, 72 C, no throttle reasons). PCIe rx (into the GPU) 240-4758 MB/s,
  tx 650-3226 MB/s, sustained. Game log: fps 22.4, Video Budget 2266 / Usage 2500 MB, Demoted 777 MB.
  PCIe 3.0 x16 link is fine. Desktop holds 480 MiB VRAM (Hyprland 213, noctalia 185, kitty 80).
- GPU-written targets spilled to system memory at level load (trace1, t=170-185 s, after the menu
  filled VRAM): five 1792x1792 R16 shadow cascades + 1408x1408 (34 MiB), 1920x1080 R32G8X24 depth
  (17 MiB), 1920x1080 RGBA8 RT+UAV, 256x256 RGBA16F UAVs. vkd3d placement is fixed at allocation time,
  so they stay in sysmem all session. trace2 (VKD3D_BENCH_L0_SYSMEM=1) kept the cascades in VRAM: the
  L0 option was only judged on memory totals before, never on fps.
- Correction: the failed vkAllocateMemory calls are ordinary VRAM (type 7: 10,787 in trace1), not BAR
  (13). memreport printed only the first six, which happened to be BAR. Upload heaps already use
  plain sysmem, so `no_upload_hvv` should change nothing.
- Descriptor heaps: 8 allocations of 64,000,256 B + 8 of 8,000,000 B, created
  within 0.5 s at t=90.4 s = eight 1,000,000-descriptor shader-visible heaps, 549 MiB. 3 in the BAR
  window (VRAM, 198 MiB), 5 in pinned sysmem (351 MiB). Owner and which heap is bound: next run
  (memtrace DC lines, frametrace DH/DB lines).
- Lossless check noise floor: two Photo Mode captures of the same frame (trace2 photo/base-a vs base-b)
  differ in 43,076 pixels, max channel error 14 (imgdiff "exact:" line). The earlier "0 px changed" was
  a >8 threshold. A change counts as lossless only if A-vs-B stays within the A-vs-A' floor.

## Findings, 2026-10-12 evening: what crosses PCIe, and why (Venom Punch scene, 30 s windows)

| run | config | fps | p50 ms | p95 | p99 | W | rx MB/s | tx MB/s |
|---|---|---|---|---|---|---|---|---|
| cfg2-base / -b | stock-equivalent | 29.4 / 28.1 | 33.6 / 35.1 | 41.2 / 44.3 | 45.4 / 48.3 | 65 / 66 | 2509 / 2648 | 2570 / 2402 |
| cfg2-res / -b | `VKD3D_BENCH_VRAM_RESERVE_MB=192` | 37.6 / 38.6 | 24.5 / 23.4 | 34.2 / 35.8 | 38.8 / 41.8 | 72 / 74 | 2361 / 2322 | 923 / 843 |
| lg-res | reserve + `lgcap` 3072 pages | 38.7 | 24.0 | 33.8 | 37.6 | 72 | 2100 | 1059 |
| geo-res | reserve + geometry mirror | 24.0 | 41.6 | 50.9 | 56.8 | 61 | 3384 | 2837 |
| desc-sys | reserve + all descriptor heaps sysmem | 28.2 | 35.0 | 43.9 | 47.8 | 64 | 2239 | 2525 |
| desc-place | reserve + `DESC_SYSMEM_IDX=3,4,7,8` | 35.9 | 27.9 | 35.5 | 39.9 | 70 | 2240 | 1225 |

- Reserve (+32%) is placement only: same render-target set, same game telemetry (Tex Usage 1206,
  Demoted 840), sharpness ratio vs base 1.096 inside the base/base noise (0.67-1.40). Frames from
  different launches differ 22-24 dB PSNR stock vs stock (fire/lighting state), so pixel diffs
  across launches prove nothing; Photo Mode in a free-roam spot is the way to a pixel proof.
- ManagedBuffer (D3DBufferManager::InitBuffer 0x1d6e0e0, 800 MiB from budget entry "ManagedBuffer"):
  CUSTOM WC L0 sysmem, persistently mapped at [obj+0x5b8], two whole-buffer bindless views
  (structured stride 16, raw). The GPU draws geometry straight from sysmem: IB bound ~4061/s,
  ~69.5k indexed draws/s reading 516 MB/s of indices, vertices pulled through the views. CPU writes
  it once (~798 MiB), never again in steady state; GPU never writes it.
- Geometry in VRAM does not fit a 3 GB card: NVIDIA sparse buffers only allow memory type 7 (VRAM)
  (a standalone test program), so no hybrid VRAM/sysmem tiling; a full mirror (geomirror.c,
  `VKD3D_BENCH_GEOMETRY_VRAM=1`) pushes render targets out (Video Usage 2403 vs Budget 2177) and
  loses. Kept for bigger cards. Write-watch scan costs ~0.45 ms per submission.
- Light Grid Data Buffer (LightGridManager init 0x1c2d800, buffer at 0x1c2dc70): 512 MiB DEFAULT UAV,
  pages = min(requested, 0x1fff) x 64 KiB; allocator 0x1c2cdf0 (+0 pages, +0x10 page descriptors,
  +0x30 262144-entry CPU lookup = the 1 MiB "Light Grid Lookup" buffers). Snapshot scan: 2652 of
  8191 pages ever non-zero (166 MiB). `VKD3D_ENGINE_PATCH=lgcap` + `VKD3D_BENCH_LIGHTGRID_PAGES=N`
  patches the cap at 0x1c2d856 (experiment; frees ~320 MiB VRAM). Lossless route: sparse-bind
  tiles for pages the lookup references.
- Other big buffers: 77 MiB Scene Gpu Registry (0x1e18850): 411 pages used, highest 656. 196 MiB
  CUSTOM L1 UAV (0x1dff76b<0x1da36ab): 364 used, highest 1750.
- Descriptor heaps are created in a fixed order; by creation index (1-based): #1 and #2 hot
  (~52k binds/s), #3 bound once, #4 never, #5/#6 ~7.7k/s, #7/#8 bound once or never. Stride 64 B per
  descriptor. Stock places #1-#3 in BAR. All in sysmem: 38 -> 28 fps. desc-place moved #3,4,7,8 out
  but #2 (0x6e) and #6 (0x7c) still fell to sysmem: BAR filled. Next: make #1/#2 always win BAR.

## Findings, 2026-10-13: render thread, occlusion queries, upload copies (v4 runs, kept = reserve 192)

- Render thread (FUN_141d9f660): sleeps on cond 0x83cd148 while state word 0x83cd138 == 1; the
  main thread (FUN_141d9f210) waits while state > 1, copies the 0x810-byte command handler table
  0x83ca9a8 -> 0x83cd1b8 every frame, sets state 2 and wakes it. State 3 = processing commands
  (handler = [0x83cd1b8 + id*8], name = [0x83cb1b8 + id*8]); at the end WaitForFrame (call at
  0x1d9feb3 -> 0x1d7c5d0, loops the 5 contexts at 0x83deef0) then state 1 + wake 0x83cd180.
  PushBuffer object 0x83de920 (+0x588 fence, +0x5c8 active list slot). Registration: FUN_141d929d0.
- `bench/statepoll.py` polls the state word: the render thread waits for the game thread only
  ~1.6 ms/frame and renders ~21.8 ms/frame, so it is the CPU critical path (85% of a core; main 36%,
  Job Hi 0/1 ~37%).
- Occlusion queries: commands 0x74 ProcessQueries (0x1d98f00), 0x75 FinalizeQueriesBlocking
  (0x1d98700; spin at 0x1d98783; second copy 0x1d974a0), 0x76 non-blocking (0x1d98800). Query
  object: +0x30 result block (flags u16 at +0x1e: 1 has result, 2 issued, 4 finalized), GetData =
  context vtable+0xe8. Consumers: lens flare/corona fades (0x1ef8370) and gameplay visibility
  checks (0x1b40860, 0xeb44c3, 0xeb3f78). The blocking finalize costs ~300 ms/s of render-thread
  spin (~90 waits/s, ~3.4 ms each).
- `VKD3D_ENGINE_PATCH=qdefer` (defer unready results to the frame end) and `qasync` (read results
  one frame later, blocking only before the next ProcessQueries) remove the spin. Neither helps:
  qdefer just moves the wait to the frame end (GPU is still ~6 ms behind), qasync is -2.3% in every
  same-session A/B window (GPU idle-waiting-CPU 2.4 -> 0.7 ms but GPU busy per frame up).
- Heavy frames (~28 vs ~16 ms GPU) carry +2.1 ms of vkd3d's UNDEFINED -> TRANSFER_DST discard
  before CopyTextureRegion uploads into sysmem A8 textures (1920x1088, 960x544; stack 0x1ded168 <-
  0x1d913f0). `VKD3D_BENCH_COPY_NO_DISCARD=1|2` (lossless) cuts it 1.9 -> 0.3 ms/frame; fps -0.1%.
- `bench/abf.py`: same-session A/B by toggling `engine_ctl.features` live (ABBA, 20 s windows);
  noise ~±0.5 fps, far below launch-to-launch spread. Bits: 1 keep sysmem images on copy, 2 keep
  all, 4 qasync. `bench/series.sh` interleaves launches A B A B for configs that can't toggle live.
- Descriptor-QA access counting (build/qa, `QACOUNT=1`, `bench/qacount.py`): 267M descriptor
  accesses/frame; 70.3% to VRAM, 1.5% sysmem textures, 1.4% the 800 MiB ManagedBuffer (3.8M/frame),
  26.7% unmapped. Sysmem textures are cold (2-7k accesses/MiB) vs VRAM textures (250-860k/MiB), so
  the reserve's hot/cold split is right. Light grid 512 MiB: 3.75M accesses (7.3k/MiB).
- Descriptor heap binds (kept config): #1/#2 BAR ~295/s, #3 ~1/s, #5/#6 sysmem 42/s, #4/#7/#8 ~0.
  BAR budget 205 MiB (desktop uses ~40 of 246) fits three 61 MiB heaps only.
- GhidraMCP 2.0 (LaurieWired) headless on port 8081, project tools/ghidra-proj (full analysis,
  1152 s); `tools/ghidra-client/gq.py <tool> key=value`, `tools/ghidra-client/dc.sh <rva>...` ->
  analysis/decomp/<rva>.c. Start it only with the game closed (2-3 GB RAM):
  `cd tools; G=$PWD/ghidra_12.1.4_PUBLIC; WHL=$(ls $PWD/dl-ghidramcp/GhidraMCP-release-2-0/*.whl);
  nohup env GHIDRA_INSTALL_DIR=$G JAVA_TOOL_OPTIONS=-Xmx3g uvx --python 3.13 --from
  "ghidra-mcp[headless] @ file://$WHL" ghidra-mcp --headless --binary "<game>/MilesMorales.exe"
  --project $PWD/ghidra-proj --project-name MilesMorales --no-analyze --ghidra-install-dir $G
  --transport streamable-http --mcp-host 127.0.0.1 --mcp-port 8081 > ghidra-mcp.log 2>&1 &`
  (ready at "Serving MilesMorales.exe").

## Findings, 2026-10-13 night: the machine's memory

- RAM is a single 8 GB DDR3-1600 DIMM (dmidecode: slot DIMM_B1, other three empty), so one
  channel: 12.8 GB/s (11.9 GiB/s) peak. The CPU's memory controller counters (uncore_imc, read with
  `sudo perf stat`, `bench/imc.py`) in the kept config's 30 s window (v4-dp-B1): DRAM read 4.91 +
  write 1.82 = 6.73 GiB/s, of which CPU cores 4.14 and PCIe (the GPU reading/writing system
  memory) 2.62 GiB/s. That is ~56% of peak on average, with frame-phase bursts on top.
- Memory pressure: the GPU's pinned system-memory heaps (~1.5 GB mapped through nvidiactl plus
  driver allocations) and zram (2 GB of RAM holding 4.2 GB) leave the game ~230 MB of resident
  heap; ~2.7 GB of it sits in zram. Steady state costs little (~18 major faults/s, mostly the main
  thread, ~1 ms/s), streaming bursts cost more.
- CPU: intel_cpufreq passive + schedutil, 3.4-3.6 GHz on all four cores under the game (= the
  i5-4670's all-core turbo). THP always, swappiness 150.
- DRAM sensitivity, same session (`bench/memab.py`, v4-mem; `bench/memhog.c` takes 30% of one core
  either spinning or streaming a copy): none 41.72 fps, spin 41.51, mem 36.78 (3 windows each).
  The copy added only 1.2 GiB/s (6.6 -> 7.9 GiB/s total) yet cut the GPU's PCIe throughput 2.81 ->
  2.55 GiB/s and fps by 11.4%: the channel saturates around 8 GiB/s for this mix, so every GiB/s of
  traffic the software wastes costs ~9% fps. Passes that slow down (`bench/gpuwin.py`): G-buffer
  968x544 +0.53 ms, shadow passes +0.47 ms, particles +0.25 ms; the big compute passes don't move.
- CPU DRAM traffic by code (`bench/missprof.py`, L3-miss sampling): game 80%, of it 17% in one
  routine, exe 0x1c97030 = vertex decoder (4 vertices per call: int16 positions + 10:10:10 normals
  -> 48-byte float vertices), ~55 call sites in 0x1c8a000-0x1c93600, run by Job Hi 0/1, the render
  thread and the main thread. Every sampled source pointer is in the 800 MiB geometry heap
  (ManagedBuffer), which is write-combined: CPU reads of it are uncached, unprefetched, 4 DRAM reads
  per 64 B line. PEBS load latency (`bench/ldlat.py`): 25.6% of the game's sampled load-stall time,
  844 cycles per load vs ~300 for ordinary misses (render thread 6.8%, job threads 17%).
- Fix: `VKD3D_BENCH_GEOMETRY_CACHED=1` (geomirror.c, heap.c) backs that one heap with memory type 9
  (HOST_VISIBLE | HOST_COHERENT | HOST_CACHED) instead of 8. Lossless: same bytes, the heap keeps
  the properties the game asked for. v4-gc: geometry heap 25.6% -> 0.5% of load-stall time, total
  stall -19%, game CPU 62% -> 55% of the machine, fps 42.92 (in range). Series v4-gcs pending.
- v4-gcs (interleaved launches, stopped after one pair): cached heap 40.69 vs kept 41.81 fps, game CPU
  55% vs 62%, but PCIe tx 780 -> 1113 MB/s and GPU sysmem traffic +7%: the GPU reads coherent
  (snooped) memory less efficiently, so the cached heap trades GPU time for CPU time. Dropped.
- Kept instead: `VKD3D_ENGINE_PATCH=gdec` (enginepatch.c). The decoder's four movups loads of its
  64-byte source block become MOVNTDQA through a cave (16-byte alignment checked; unaligned sources
  run the original loads). On write-combined memory MOVNTDQA fills a streaming buffer with the
  whole line once. The heap stays type 8, the GPU sees nothing different. Live switch: features
  bit 16 restores the original loads. v4-gd: decoder loads 844 -> 331 cycles, geometry heap 25.6%
  -> 8.6% of load-stall time; same-session A/B +2.9% fps (45.02 vs 43.75, every window).
- Index cache reworked (idxcache.c, `VKD3D_BENCH_INDEX_CACHE=1`): 4 KiB pages instead of 64 KiB
  (`VKD3D_BENCH_INDEX_CACHE_PAGE_SHIFT`, `_MB`), ~96% of indexed draws served from VRAM. Live
  switch: features bit 8 bypasses it. Same-session A/B +4.4% (44.81 vs 42.93). Both together +6.8%
  (44.99 vs 42.12; p50 19.9 vs 21.8 ms, p99 31.9 vs 34.4); DRAM 6.50 -> 5.88 GiB/s at more frames
  (-15% per frame), GPU PCIe traffic -18%. CPU ms/frame: Job Hi 0/1 8.3 -> 5.7, main 8.6 -> 7.3,
  render thread 20.5 -> 19.7.
- Index cache invalidation (needed for it to be lossless): D3DBufferManager (global instance
  0x1482542a0, mapped heap pointer +0x5b8, flags +0x5f0/+0x5f1) fills the ManagedBuffer only
  through 0x1d6e810 (mgr, heap, mapped, offset, data, size), called from the AllocateBuffer lambda
  0x1d6d4a0 (at 0x1d6d5e8), the deferred-list flush 0x1d6dba0 (at 0x1d6dbfd) and render command
  0xa1 0x1d912b0 (at 0x1d9130f); the lambda is called only from AllocateBuffer 0x1d6d770 (at
  0x1d6d7e7) and returns {heap, mapped, ..., +0x14 offset, +0x1c size}. All four call sites are
  retargeted to wrappers that report the written range after the write; each report stamps the
  pages with a new generation, and a cached run serves a draw only if none of its pages were
  written after its copy. Any CopyBufferRegion into the heap turns the cache off. With everything
  on: +7.0% (45.61 vs 42.62, v4-ic).
- Proof: `VKD3D_BENCH_INDEX_CACHE_VERIFY=1` keeps the cache in CPU-readable memory and compares
  every 16th hit (runs copied >= 4 presents earlier) byte for byte with the heap. v4-icv/v4-icv2:
  757,782 compared reads over 323 s (load, the Rhino fight driven by injected keys, a death and a
  checkpoint reload), 0 mismatches; 76 runs found written after their copy and recopied (what
  would have been wrong geometry without invalidation).
- benchinput.c: keys w a s d shift ctrl and `hold <ms> <keys...>` (`hyprbench.py input hold 3000 w
  shift`). The bench checkpoint is the Rhino fight (factory interior); the game autosaves into the
  bench prefix when it progresses, so back up and restore its save (build/save-backup/).
- Other GPU-visible memory the CPU reads: a 16 MiB readback chunk (type 9, already cached) that the
  render thread copies ~0.5 MiB/frame out of (memcpy at 0x216b820): 3.4% of stall time, inherent.
- Crash in v4-dp-B2 (descriptor placement): access violation in Wine's critical-section wait path
  (ntdll RtlpWaitForCriticalSection -> RtlWaitOnAddress) on a game I/O thread (0x1c09xxx);
  dump in captures/v4-dp-B2/crash. Not in vkd3d. Its crash handler (crs-handler.exe) kept the
  Wine session alive and broke the next launch; series.sh now closes it (never reports).
- The bench prefix had `drive_c/users/steamuser` as an absolute link into the player's own prefix
  (copied from it), so the game ran on the player's profile (saves, logs, crash reports). Now
  `steamuser -> zaid` inside the bench prefix (umu only creates the link when it is missing). The
  player's save files were untouched since 2026-10-12 21:02 (their own play).

## Findings, 2026-10-13 day: GPU frame, particle loop, dead ends (v5 runs)

- Geometry heap in VRAM, v2 (`VKD3D_BENCH_GEOMETRY_VRAM=1 VKD3D_BENCH_GEOMIRROR_HOOKS=1`,
  geomirror.c): the 800 MiB ManagedBuffer mirrored into VRAM, synced from the engine's write hooks
  (no write watch). 26.35 fps vs ~43: VRAM full (2274/2279 MiB), PCIe rx 3.7 GB/s from evictions,
  the game's swap +800 MiB for the pageable shadow. Geometry does not fit 3 GB next to the rest.
  Dropped (code stays, off by default).
- Root signatures (INFO log in state.c, first 64): the game uses descriptor tables only (SRV table
  77 entries, CBV table 7, UAV table, sampler table), CBV ranges are arrays, all volatile. Nothing
  to hoist into push constants / static CBVs; `force_static_cbv` run v5-scbv-B0 42.00 fps = noise.
- GPU frame (`GPUTIME=1`, bench/gputime.py, light frame ~19.5 ms): compute ~12.3 ms, render ~7.2,
  barriers ~1.4, copies ~0.85. Heavy frames (23-32 ms) are single segments stretched by 3-6 ms
  while the desktop compositor uses the GPU (Hyprland 5-9% SM even idle; "other gpu sm" 10-13% in
  benches). Render thread spends ~30% spinning at 0x20c6790 (engine waits; not a lever).
- Particle loop (FUN_141edfa80, analysis/decomp/1ee04a2.c): ~60 systems per frame, each 3-8
  compute steps, every step behind a global UAV barrier: 662c25e757553f79 simulate
  (DispatchIndirect), f560236567e1f82d spawn, e3b454ffb034d091 args (1x1x1), 181b4e975cc87a56 /
  e11b26be234a8b05 / 42042f6cfbcbc60c sort, 84bec3df6e178db7 / b15604df3ab336ac prepare draw, then
  a 96-byte CopyBufferRegion of the system's args. All systems share two scratch buffers (2 MiB
  R32G32B32A32_UINT, 1 MiB R32G32_UINT), which is what forces the whole loop into one serial chain
  of ~300 tiny dispatches, each waiting for the GPU to drain.
- Lossy experiment (features bit 0x20, three of the barriers dropped): +6.0%, which showed the room.
- Kept: `VKD3D_BENCH_PARTICLE_BATCH=16` (command.c). Up to 16 consecutive systems are recorded
  into per-step secondary command buffers (step j of every system -> phase j) and spliced phase by
  phase with one full memory barrier between phases, so 16 systems' step j run concurrently and
  the loop has ~6 barriers per batch instead of ~6 per system. Exactness: every particle shader's
  descriptor accesses are constant offsets (SPIR-V: 662c SRV m0+{0,5,6,10..13,56,57,76} UAV
  m2+{0,1,2}, ...), the scratch buffers are learned from simulate's UAV 1/2 seen in two different
  systems, and system i >= 1 of a batch gets its own committed copy i of each scratch buffer: the
  exact descriptor entries are rewritten in the shader-visible heap (the engine copies fresh tables
  per system into a ring, checked with pdiag, features 0x80). Any shared entry, unknown call or
  failure splices the batch first (guard vtable: 128 thunks swapped in while a batch is open) or
  turns batching off for good with an ERR. Barriers inside the loop (UAV + buffer transitions)
  become phase boundaries; the 96-byte copies join the batch. Live switch: features bit 0x40;
  bits 24-29 lower the batch size live.
- Results: same session +10.3% (44.36 -> 48.93 fps, p99 34.2 -> 30.5 ms). Batch size (v5-pk): off
  45.82, 8 50.15, 16 50.57, 32 50.75 -> 16 (45 MiB of scratch copies in VRAM vs 93 for 32).
  Screenshots on vs off: PSNR 48.48 dB / 0.17% pixels > 8, same as two "off" shots of the running
  scene (49.53 dB / 0.14%): particles animate, the difference is the frame time, not the content.
  ~15 systems and ~5.6 phases per batch, 0 errors.
- v5-gt (kept + batching, GPU timing): light frames ~17.6-17.9 ms of GPU work (~56 fps ceiling);
  GPU idle waiting for the CPU 1.67 ms/frame, mostly from rare 22-30 ms CPU gaps.
- Left on the table: ~57 particle draws per frame are each a 3840-byte upload copy with two
  transitions and a full-screen render pass with one draw (~0.55-0.7 ms/frame); the big compute
  passes (7377a06a ~2 ms, c9d908 ~1.9, 53df85 ~1.4, 13005b60 ~1.0) and the 8192x5120 shadow atlas
  (~2.5 ms) would need shader-level work.
- Memory in the running scene (v5-mem): RSS 1.97 GB (nvidiactl 1547 MiB pinned), game anon
  278 MiB resident / 2.53 GB in zram; largest arenas 0x1f6c0000 (998 MiB, 592 swapped),
  0x7fff0000 (990, 314), 0x100401000 (355, all swapped). Major faults ~7/s: swap is not what makes
  the static scene hitch.

## Findings, 2026-10-13 afternoon: progression, discard barriers, hitches, particle draws

- Progression (v5-prog, two interleaved launches per step, all windows clean, DRAM from
  `perf stat` uncore_imc via bench/imc.py):

  | step | fps (2 runs) | mean | p99 ms | GPU W | PCIe rx/tx MB/s | DRAM GiB/s |
  |---|---|---|---|---|---|---|
  | A stock GE vkd3d | 30.78 / 31.91 | 31.35 | 46.6 / 46.1 | 65 | 2470/2506, 2770/2373 | 7.42 / 7.15 |
  | B + reserve 192 | 42.39 / 42.24 | 42.32 (+35%) | 39.8 / 37.0 | 70 | 2204/1096, 2321/1015 | 6.69 / 6.60 |
  | C + gdec + index cache | 43.54 / 44.86 | 44.20 (+41%) | 42.6 / 34.4 | 73 | 2194/973, 1820/1116 | 6.42 / 6.13 |
  | D + particle batch 16 | 47.68 / 44.97 | 46.33 (+48%) | 36.0 / 39.5 | 76 | 2243/961, 2089/897 | 6.64 / 6.93 |

  Launch-to-launch spread is ~2 fps, so steps under that are measured live (bench/abf.py).
- `VKD3D_BENCH_DISCARD_KEEP=1` (features 0x100, command.c
  d3d12_command_list_discard_attachment_barrier): DiscardResource on a render target no longer
  records an UNDEFINED -> layout barrier (16 per frame, ~9 us each, full pipeline drain); the
  discard itself (load op) stays. Lossless by spec: after DiscardResource the contents are
  undefined anyway. Live: 49.22 -> 49.74 fps (+1.1%), every on-window above every off-window;
  screenshots off/on 50.3-50.5 dB, off/off 50.7 dB.
- Hitches (bench/hitch.py, v5-pd3, 30 s): median frame 17.5 ms, p99 30.9, 6 frames > 35 ms. In
  slow frames the render thread spins at 0x20c6790 waiting for the GPU (up to 11 ms), and the
  main thread sleeps 10-40 ms inside Wine server calls (server_call_unlocked < wine_server_call,
  NtSetEvent, inproc_wait ioctl). Lesson: perf script output has to be streamed; holding a 30 s
  trace in memory (~3 GB) got the game OOM-killed once.
- Particle draws (`VKD3D_BENCH_PDRAW=1`, features 0x400 = off; command.c "particle draw
  constants"): ~57-60 draws per frame, each "barrier GENERIC_READ -> COPY_DEST, 3840-byte copy from
  the upload heap, barrier back, draw" on ~8 buffers reused round-robin. Copies are deferred and
  batched (one barrier pair per ~11 draws); each draw reads its constants from the upload-heap
  bytes the copy would have taken. First versions rewrote the engine's CBV ring entries in place:
  unsafe (static slots 255/262 hold the same buffers' CBVs and are reused across frames; other
  draws' sliding CBV windows cover the rewritten entries; caught by write tracking, v5-pd7).
  Kept version: the 1M resource heaps get 4096 private descriptors past the app's end (state.c
  layouts sized to match, GetDesc reports the app's count), and only the particle shaders
  (10 VS + 6 PS hashes, each reads only its tables' first descriptor per SPIR-V) get their CBV
  table pointed at a private CBV for that draw; the engine's base goes back before the next draw.
  Every source descriptor is compared again at ExecuteCommandLists (volatile ranges).
  v5-pp1: 11.1 draws and 11.7 copies per flush, 0 errors; live 50.52 -> 51.03 fps (+1.0%, every
  on-window above every off-window, p99 29.6 -> 29.3 ms); screenshots off/on 50.3-56.6 dB vs
  off/off 50.7 dB.
- Load profile (bench/loadprof.py, v5-pp3): menu load is HDD-bound (85-87% busy, 42-52 MB/s); the
  save load (74 s) has the HDD only 45% busy while ~12K pages/s swap in and ~12.7K/s swap out
  (zram): it waits on memory, not the disk. ~1M major faults from launch to the settled scene.
  zram holds 223K incompressible ("huge") pages (~870 MB) that free nothing when swapped.
- The game's GPU memory in system RAM (memreport, v4-res-mt): 2.65 GB, all pinned by the driver:
  type 1 (not mapped, so not in RSS) 1201 MiB = ~1.2 GB of textures that did not fit VRAM; type 8
  1080 MiB budgeted (800 MiB ManagedBuffer geometry, 264 MiB upload) + 351 MiB internal
  (descriptor heaps). In the scene the game's own anon memory is ~220 MB resident, 2.7 GB in zram.
- Descriptor heaps: the engine creates 8 shader-visible CBV_SRV_UAV heaps of 1,000,000
  descriptors (64 MB descriptor buffer + 7.7 MB raw-VA/offset buffer each): 3 in the BAR window
  (type 10), 5 in pinned system RAM (type 8). Binds over a session (frametrace DB): #1/#2 ~148K
  each, #5/#6 ~22.8K each, #3/#7 once at startup, #4/#8 never. Contents (VKD3D_BENCH_HEAPSCAN=1,
  metadata scan every 30 s): only #1 and #2 ever hold a view (150-260K each); #3-#8 hold nothing
  but null descriptors, #5/#6 included.
- Kept: `VKD3D_BENCH_LAZY_HEAPS=1` (resource.c "lazy heaps"). Every large shader-visible resource
  heap starts out sharing one never-written null heap (system memory) for all of its descriptor
  memory, GPU and CPU side; its first descriptor write or copy (every CPU access goes through
  d3d12_desc_decode_va) gives it memory of its own, built aside and published under a lock that
  binding also takes. Borrowed heaps are byte-for-byte what a fresh heap is. The one theoretical
  difference: a list that bound a heap before its first write and is submitted after it reads
  null where the original reads the new descriptors; counted at ExecuteCommandLists (ERR).
  v5-lz1: #1/#2 materialize at startup (bound 1-2 times before), #3-#8 stay shared. Driver-pinned
  RAM 1548 -> 1263 MB (-285 MB), the BAR slot of #3 goes to game data (game VRAM 2241 -> 2294).
  Faults up to the settled scene 1.02M / 1.14M (two eager runs) -> 0.53M, swap at settle
  2.4-2.7 GB -> 1.9 GB (single runs).
- Bench pitfalls: capture names must be new (cfgrun.sh does not clear captures/<run>, a reused
  name read stale logs); wait for the previous run's DLL cleanup in the game dir before launching.

## Findings, 2026-10-13 midday: series v6-prog, load faults

- Series v6-prog (2 interleaved rounds; arms A stock, B = reserve+gdec+idxcache+batch16,
  C = B + discard keep + pdraw, D = C + lazy heaps; all windows clean, DRAM in captures/v6-prog-imc):
  A 30.17/30.80, B 47.41/48.75, C 47.48/48.24, D 49.44/49.56 fps (p99 49.3/45.5 -> 35.5/34.4 ms).
  Swap-ins launch -> scene: A 645K/698K, B 718K/669K, C 677K/654K, D 239K/344K. Pinned RAM in
  the scene 1546 -> 1265 MB; the game's own resident memory 220-290 -> 420-500 MB.
- Lazy heaps exactness: the 2 startup lists that bind heap #1/#2 before its first write set no
  descriptor tables and no directly-indexed root signature (checked at submission, v6-fin1).
- Load faults (bench/faultprof.py, every major fault, v6-fin1, 300 s): 412K, 99.6% in user code,
  none inside read(). 58% land in the engine's big contiguous arena (0x7ffe1000..). Top sites:
  exe+0x3b59ecb (memcpy, rep movsb) 43K, exe+0x20cc644/0x20cc764 (an LZ-style decompressor at
  ~0x20cc5b2 writing its output) 46K, exe+0x3b5a1e0.. (large memcpy with vmovntdq stores),
  exe+0x1c5209f. So most swap-ins are destinations about to be overwritten by a copy or a
  decompression. Next idea: reset (MEM_RESET) the whole pages of large copy/decompress
  destinations first. A ReadFile-destination reset was tried in code and dropped: reads fault ~0.

## Findings, 2026-10-13 noon: swap-ins of dead data (dropdst)

- Fault sites by instruction (v6-fin1, faults.data): memcpy's rep movsb (0x3b59ecb, copies of
  8 KiB-1.5 MiB) 51K; its non-temporal loop (0x3b5a1e0.., copies > 1.5 MiB) 31K on the stores
  and 2.4K on the loads; memset's rep stosb (0x3b5a579) 6.6K; the LZ4 decoder 0x20cc4f0
  (LZ4_decompress_safe, no dictionary; NxStorage Command thread, 14 callers + 3 function tables)
  52K, all on its stores. In the save load (90-120 s) 118K of 210K faults are these stores:
  pages swapped out to zram and swapped back in only to be overwritten.
- `VKD3D_ENGINE_PATCH=dropdst` (enginepatch.c): memcpy 0x3b59ee0, memset 0x3b5a590 and the LZ4
  decoder enter through a cave (2-byte atomic short jmp into the int3 padding before each entry,
  safe while the engine runs). For copies >= 16 KiB (`VKD3D_BENCH_DROPDST_MIN`) the hook reads the
  destination's pagemap and MEM_RESETs (Wine: madvise DONTNEED) the runs of whole pages that are
  swapped and not present; the copy then gets zero pages instead of swap-ins. Overlapping
  source/destination: skipped. LZ4: the decoded size comes from engine_lz4_size, a walk of the
  block through the decoder's own checks; fuzzed against the game's decoder code run natively
  (a standalone harness): 19,877 blocks (9,496 valid, 10,381 corrupt/truncated), 0 disagreements,
  and the decoder's output never depends on the destination's previous contents.
- Wine pitfall: files are opened by the wineserver, so `\\?\unix\proc\self\pagemap` opened
  from the game is the wineserver's pagemap (all reads succeed, every entry 0). The hook finds its
  own /proc/<pid> by comm + a probe page (present) followed by a reserved page (absent).
- v7-dd1 (the /proc/self version, so no resets: hook cost only): 243K pagemap reads by the scene,
  1.0 s of hook time over the launch (~4 us each); ~1,600 copies >= 16 KiB/s in the scene.
  It measured 55.3 fps vs 49.5 for the same config in v6-prog: other GPU load was 12-16% during
  v6-prog and 3% now. Only arms of one interleaved series are comparable.

- Series v7-dd (2 interleaved rounds; A = kept config, B = A + dropdst with the /proc/<pid> fix):
  save load (last Continue -> scene, bench/runsum.py) A 47 / 50 s, B 42 / 46 s (-9%); major faults
  launch -> scene A 315,966 / 359,197, B 218,775 / 245,415 (-31%); pages reset 118,652 / 122,824
  (0 errors; ~1,600 LZ4 blocks onto swapped pages); 4th-8th longest frame gaps over the run
  A 0.31-0.37 / 0.38-0.69 s, B1 0.24-0.28 s. fps A 55.54 / 54.94, B 52.91 / 54.79 (B1 had higher
  PCIe rx, 2142 vs ~1950 MB/s: placement differs per launch) -> same-session on/off A/B (v7-ddab).
  Steady scene: ~1,280 hooked copies/s, ~7.6 us each (~1% of a core) before the pinned-range skip
  (vkd3d_bench_pinned_add/remove in memory.c: copies into vkd3d-mapped GPU memory skip the read).

- v7-ddab2 (same session, features 256 = dropdst on, 2304 = off; ABBA x4, 20 s): on 57.89 57.02
  58.22 58.03, off 58.04 58.03 58.32 58.34 -> on -0.7% (-0.2% without the 57.02 window, which a
  ninja build of mine overlapped); p99 26.7 vs 26.6 ms. Series v7-dd also showed more frames
  > 40 ms with the hook (11 / 9 vs 4 / 4). Suspect: pagemap reads take the process's mmap lock.
  Fix under test (v7-ddab3): only threads named NxStorage*, Asset Load*, Archive Asset* run the
  hook (GetThreadDescription, cached per thread); copies into vkd3d-mapped memory skip the read
  (67K of 322K hooked calls in v7-ddab2).
- v7-ddab3: the thread filter matched nothing (0 hooked copies): the game names its threads with
  the MSVC 0x406D1388 exception, which Wine forwards only to the Linux thread name, so
  GetThreadDescription returns empty. (Proton enables syscall user dispatch, so a raw prctl from PE
  code is not an option either.) Useful side result: with the hook doing nothing, on vs off still
  read 58.56 vs 58.98 fps (B +0.7%, 3 of 4 pairs): the live toggle has a ~0.7% bias of its own, so
  v7-ddab2's -0.7% is that bias, not the hook. Filter removed; dropdst kept as in v7-ddab2.
- The static scene now sits at the 60 Hz frame-callback cap the bench gives the hidden window
  (hyprbench.py HIDDEN_FPS = 60): ~58.5-59 fps, p50 16.6 ms. It can no longer show gains.

## Findings, 2026-10-13 afternoon: gameplay is paging-bound; the light grid (captures v7-trav1, v8-*)

- Gameplay bench: `bench/fightdrive.sh` keeps Miles running, jumping and dodging in the Rhino fight
  (keys injected in-process, no focus), so Rhino charges, Miles dies and the checkpoint reloads.
  `bench/fightrun.sh <cfg> <run> [secs]` = launch + load + fight + `bench/fightsum.py` summary
  (fps, percentiles, frames > 40/100 ms, worst, swap-ins, major faults, pinned MiB, game
  telemetry, light grid losses). abf.py windows now also report swap-ins and major faults.
- v7-trav1 (s6 config, dropdst toggled live during the fight, 12 x 20 s): 26.5-39.8 fps, p99
  59-318 ms, worst frames 82-713 ms, 1.8K-38.7K swap-ins per window. The live toggle is drowned
  by deaths/reloads (the 36-39K swap-in windows). Frames over 150 ms all carry 10-15K draws
  (normal frames 3-6K): ~27 us a draw, the render path walking swapped-out object data.
- Fault profile of 150 s of fight (`faultprof.py`): 173,881 major faults (1,160/s); main thread
  67%, Render Thread 14.5%, Job Hi/Lo 14%. Regions: 990 MiB arena 0x7fff0000 24%, AssetHeap
  (998 MiB, 0x1f6c0000) 19%, 0x15a2000 13%, sound 0x1dfe50000 7%.
- Memory in the fight: 7.9 GB total, 0.53 GB available; zram 4.1 GB of pages in 2.0 GB, 211K
  incompressible slots (826 MiB). The game: 1.9 GB RSS (1265 MiB of it /dev/nvidiactl, pinned) +
  2.45 GB swapped; vkd3d heap #1 (GPU memory in system RAM, pinned) 2351 MiB; game telemetry
  Video Usage 2431 > Budget 2346, Sys Usage 2337, Demoted 912 MB.
- zramhuge.py must run as root: the kernel hides swap slots in pagemap from other users (every
  swapped page read as slot 0, so the first run said 0 MiB incompressible). As root (v7-trav1):
  2750 MiB swapped, 559 MiB incompressible, 72 MiB zero pages. AssetHeap 224 MiB incompressible;
  the 326 MiB region 0x1dfe50000 is 84% incompressible and holds RIFF "data" chunks (compressed
  audio banks). Not dead data: cold but live (sounds play from it).

### Light grid sparse (`VKD3D_BENCH_LIGHTGRID_SPARSE=1`, lightgrid.c) - S7 candidate

- RE (Ghidra): LightGridManager::Init 0x1c2d800 creates "Light Grid Data Buffer" =
  min(requested, 0x1fff) pages x 64 KiB (512 MiB) via 0x1d9d6a0 -> CreateHeap(512 MiB, DEFAULT,
  buffers only) + CreatePlacedResource at offset 0. Pages come from a 3-level bitmap allocator
  (struct exe+0x6a453a8 = LightGridManager 0x6a45150 + 0x258: level0/1/2 pointers, count, used,
  highest; init 0x2164100, free 0x2163f20; level 2 = 1 bit per page, MSB first). Page n-1 is the
  null page: both 1 MiB "Light Grid Lookup" tables are filled with it ((n-1) << 12 | 0x3c0) and
  cells reach other pages only through lookup entries written after allocation (0x1c2d650,
  0x1c2d310, flush 0x1c2cd70; per-volume page arrays at +0x70, freed by 0x1c532b0/0x1c531d0).
- Allocation is first fit and dense (live reader `bench/lgpages.py`): scene 1732 pages in use,
  highest 1731; load peak 2650 (the old "2652 pages ever non-zero"); fight 1732-1919.
- Mechanism: the heap keeps 64 KiB of its own; the placed buffer becomes a sparse buffer (vkd3d
  reserved resource, memory type 7). Null page + pages 0..bound-1 are backed by fresh VRAM (NVIDIA
  zeroes new allocations, as for the original heap); bound starts at 2048 pages
  (`VKD3D_BENCH_LIGHTGRID_INITIAL`) and grows in 4 MiB chunks to stay 512 pages
  (`VKD3D_BENCH_LIGHTGRID_MARGIN`) ahead of the highest allocated page. Every ExecuteCommandLists
  scans the bitmap (top-down, a few loads) and binds synchronously (internal sparse queue + fence)
  before submitting. Backed pages are never unbacked, so a reused page keeps its contents as before.
- v8-lg1 (first version): growth failed once VRAM refilled (vkAllocateMemory -1) and the failure
  was sticky: pages 1472-1731 in use but unbacked = lights lost. Discarded. Fix: growth retries
  every 20 ms, a page in use beyond the backed range is logged as "LOSS", and the game's VRAM budget
  (IDXGIAdapter3::QueryVideoMemoryInfo, DXVK vtable slot 14, hooked at D3D12CreateDevice) is lowered
  by two margins (64 MiB) plus any shortfall, so the streamer keeps room for growth.
- v8-lg2: budget hook live (reported budget 64 MiB lower), grew 2049 -> 3201 pages during the load
  (peak page 2650), 0 LOSS through load and 90 s of fight. vkd3d heap #1 (pinned system RAM)
  2351 -> 2031 MiB, game Sys Usage 2337 -> 2036 MB; Demoted unchanged (909-912 MB): the freed VRAM
  went to vkd3d allocations that used to fall back to system memory.
- Series v8-fs (fightrun.sh, 180 s of driven fight each, ABBA; A = s6-dropdst, B = s7-lightgrid):
  A1 29.85 / A2 34.68 fps vs B1 35.35 / B2 37.23 (+12.5% on the means; both B above both A);
  p95 79.4 / 60.6 vs 56.5 / 42.9 ms; frames > 40 ms 802 / 495 vs 535 / 383; > 100 ms 125 / 87 vs
  99 / 94 (mostly death/reload frames); swap-ins 237K / 199K vs 83K / 72K (-64%); game major
  faults 175K / 148K vs 58K / 49K; pinned 2337 / 2378 vs 2062 / 2046 MiB; light grid losses 0.
  Kept as S7 (bench/configs/s7-lightgrid.env, bench/play.sh).

## Findings, 2026-10-13 evening: same-content gameplay series, index cache full-ring walks (v10-gp)

- Fixed-seconds fight windows were unfair: faster builds got further into the fight (the game
  autosaves at the start of each phase) and were measured on heavier phases (v8-gp, aborted).
  Without ctrl the fight waits at the first "get on Rhino's back" prompt in slow motion, a still
  scene (v9-gp, aborted). Escape does not open the pause menu from injected input, so no restart loop.
- `bench/fightwin.py <n> <captures>`: metrics from the start of the fight to the game's n-th
  autosave (frames from frametrace via fight-start.json, game major faults from samples.tsv, save
  times from game.log), written to <capture>/fightwin<n>.json; `bench/fightcsv.py --window=n`
  uses them. Stock reaches its 3rd autosave in ~270 s (360 s cap), so the series is scored to the
  3rd autosave.
- v10-gp (FIGHT_SAVES=4, cap 360 s; S0 S5 S6 S7 S7 S6 S5 S0). To the 3rd autosave: S0-1 272 s,
  24.06 fps, p95 59.2 ms, 2929 frames > 40 ms, 18 > 100 ms, 531K major faults; S5-1 240 s,
  32.49 fps, p95 54.4, 723 > 40 ms but 136 > 100 ms (worst 754 ms), 382K major faults.
- S5's > 100 ms frames cluster right after the first autosave (phase two starts): ~10 s of
  65 ms-average frames peaking at 110 ms, while stock's same stretch averages ~57 ms. The frame
  trace's IC lines show the VRAM index cache "full" for ~12K draws a second there (hits ~35K/s,
  misses ~15/s): the runs drawn in the last 8 presents fill the 64 MiB ring. Each failed
  allocation walked the whole ring (2 x 16,384 pages, thousands of runs) under idxc_lock before
  giving up, ~800 times a frame. Fix (idxcache.c): after a failed search, runs at least that big
  are refused for the rest of the present without walking (nothing becomes evictable within a
  present: run_last only grows), so the outcome is the same, minus the walk. IC lines gained a
  last column (ring search steps). `VKD3D_BENCH_INDEX_CACHE_FAILFAST=0` restores the walk for A/B.

- v11-gp (FIGHT_SAVES=3; S5-S7 configs now pin `VKD3D_BENCH_INDEX_CACHE_FAILFAST=0`, S8 = S7 + the
  fix). A low-memory guard stopped the series after S8-1 (it kills background shells when RAM
  is critical; the game always gets there). Launches now
  run one at a time in the foreground. To the 3rd autosave: S0 24.86 fps (15 frames > 100 ms),
  S5 33.81 (118), S6 35.31 (130), S7 35.41 (166; 2.18 billion ring search steps), S8 38.12
  (6 > 100 ms, p99 136.6 -> 45.0 ms, worst 593 -> 126 ms; 22.9 million search steps, same number
  of draws refused: 532K vs 644K). Kept as S8.
- Crash in v12-s9t1: the same signature as v4-dp-B2 (thread 0x2a0, ntdll+0x3a960 reading address
  0x2a0, critical section at exe+0x80cb738, game I/O thread exe+0x1c09c3e); read with
  a minidump reader. A Wine / game critical-section crash seen twice in ~100 launches,
  not the patch under test.

### Skinning buffer sparse (`VKD3D_BENCH_SKIN_SPARSE=1`, skinbuf.c) - S9

- RE: SkinningBuffer::InitD3DBuffers 0x1da3530 (from the skinning manager init 0x1da39d0, manager
  at 0x83ce300) creates a 196 MiB CUSTOM / NOT_AVAILABLE / L1 buffers-only heap + placed buffer,
  plus a same-size "SkinningBuffer_CPU" from the InitAllocator (only ~15 MiB of it ever touched).
  The manager splits the buffer into two frame halves of 98 MiB ((total - frozen) / 2, settings
  at 0x84268e8 / 0x84268f0, frozen = 0) and allocates from each with the engine's lock-free bump
  allocator {u64 base, u32 size, u32 used, u32 align} at manager + 0x10 + half * 0x80: alloc
  0x2162ef0 (4 call sites, all `alloc(&mgr[0x10 + frame * 0x80], size)`), aligned alloc 0x2162f20
  (4 call sites, other allocators), reset at the end of a render-thread frame (0x1da3200 ->
  0x2162ff0). InitAllocator (0x7fff0000 arena, 990 MiB) is the engine's bump allocator for
  init-time data, full (976 allocations).
- Live counters (stock, fight): a half never passes ~11 MiB of its 98 MiB.
- Mechanism: the heap gets no memory, the buffer becomes sparse (memory type 7); each half is
  backed from its start to a bound (initial 16 MiB, `VKD3D_BENCH_SKIN_INITIAL_MB`) kept 8 MiB
  (`VKD3D_BENCH_SKIN_MARGIN_MB`) ahead of the highest allocation, in 4 MiB chunks. The 8 bump
  allocator call sites are redirected to skinbuf.c copies (same atomic operations) that back an
  allocation's range synchronously before returning it, through stubs that preserve every
  register but rax (the callers are whole-program optimised). Every ExecuteCommandLists checks
  both halves' `used` against the bounds (would catch an allocation path the hooks miss). The
  light grid's DXGI budget hook also holds two skinning margins.
- v12 (ABBA, S8 vs S9): fps S9 39.66 / 37.53, S8 40.26 / 36.98 (equal); > 100 ms frames 6 / 5 vs
  6 / 3; vkd3d heap #1 (pinned system RAM) 1903 / 1858 vs 2042 / 2058 MiB (-150 MiB); 32 MiB of
  VRAM backed instead of 196; 0 losses over ~60K skinning allocations, 0 submissions over a bound.
  Major faults unchanged (52-59K): the freed RAM ends up as page cache. Kept as S9 (memory).

### After S9: where the fight's frame goes (v12-S9-gt, v12-S9-cpu, v13-*)

- GPU (GPUTIME, 93 sampled frames): 23.3 ms of work in a 27 ms span: render passes 11.0 ms,
  compute 10.1 ms (7377a06a 1.87 ms and 13005b60 0.95 ms on a 48x27x16 grid, 53df85 1.36 ms and
  b9458a24 0.84 ms at 240x135, c9d908 1.29 ms indirect), 174 barrier-only segments 1.47 ms, copies
  0.6 ms. Idle between command buffers: with per-frame clock alignment 4.3 ms/frame is work not
  yet submitted (vkQueueSubmit2 late) and 0.7 ms waiting after submission, so not cross-queue
  copy waits. GPU utilisation in the fight 86-92%.
- CPU (threadcpu, 20 s): 2.92 of 4 cores busy: main + other MilesMorales.ex threads 19.3 ms/frame,
  Render Thread 17.6, Job Hi 0/1 ~8.1 each, Job Lo 0/1 ~6.7 each. Render thread: engine 48.6%
  (17% of it the pause spin 0x20c6820, a leaf without .pdata, so profiles show 0x20c6790),
  d3d12core 15.4% (frametrace draw counting 3.6% -> now opt-in, index cache lookup 1.8%),
  NVIDIA 14.1%, ntdll 9% (RtlAcquire/ReleaseSRWLockExclusive, RtlWakeAddressAll: vkd3d mutexes).
- perf sched (8 s): Render Thread / vkd3d_queue wake-up delay 0.085 / 0.066 ms average, so the
  late submissions are recording time, not scheduling. Outside the game: Proton's xalia.exe
  (172 ms CPU, 11K wake-ups per 8 s), and the bench's own sampler (awk over smaps 370 ms,
  pgrep 175 ms, nvidia-smi 140 ms per 8 s, plus page-table walks under the game's mmap lock).
- Fixed: `VKD3D_FRAMETRACE_DETAIL=1` now needed for per-target R lines (the run bookkeeping took
  3.6% of the render thread); bench/sample.sh reads /proc/<pid>/status, walks smaps every 30 s
  only, and keeps two long-running nvidia-smi loops. Both also apply to play.sh sessions.
- `VKD3D_ENGINE_PATCH=spin` again (S10 candidate): 39.44 vs S9 40.19 fps in one pair. Dropped.
- Slow frames left in S9 (137/136 > 40 ms per run): 55-65% coincide with no fault burst, no full
  index cache and no draw spike: heavy GPU frames.

## Bench, 2026-10-12: driving the game without touching the desktop

- The game runs on the player's `gaming` workspace (Super+G shows it). For one run,
  `bench/hyprbench.py setup` adds a runtime window rule (after the config's, so it wins): silent
  placement, no initial focus, activation requests ignored, render while hidden at 60 Hz
  (`misc:render_unfocused_fps`). `teardown` turns it off. No headless outputs, no focus or cursor
  moves. (The first version moved `gaming` to a headless output; Super+G then led nowhere visible.
  The second let the game's main window take the view when it opened: Hyprland re-applies only
  content-matching rules after the config's rule sets content=game, and the config sends
  content=game non-silently to "gaming". The bench rule now also matches `content = ".*"`.
  Reproduced and fixed with a throwaway window first; v3-res left the view untouched.)
- Rendering hidden is measurement-neutral: in v3-res the game was on screen for 12 s; visible 34.0 fps,
  hidden 34.3 / 34.5 in the same launch. Launch-to-launch spread for one config is ~35-39 fps, so
  matrix steps get two or more launches each.
- The game is started detached (`setsid -f`) so Hyprland's swallowing (it walks the parent chain,
  no workspace check) can never hide the terminal the bench runs in.
- `VKD3D_BENCH_INPUT=1` (libs/vkd3d/benchinput.c): keys from inside the game process. Write a key
  name to `/proc/<pid>/root/run/user/1000/vkd3d-input`; answer in `vkd3d-input.done`. Launcher
  (wndproc 0x21ea670) gets posted WM_KEYDOWN (it never checks focus); the game window (wndproc
  0x21dfc80) gets WM_INPUT with tagged handles, answered by a GetRawInputData import hook
  (IAT 0x3d19ca0). `hyprbench.py input enter`.
- Screenshots: `grim -T <stableId>` captures the game window even on a hidden workspace.
- `captures/<run>/user-view.tsv` (the workspaces + focused window per second) and
  `hypr-events.tsv` (Hyprland event stream) record that a run left the view alone.
- Probes: `VKD3D_FRAMETRACE_VA=1` (VW/VX/VR lines per watched buffer, BS snapshot scans on
  `touch /proc/<pid>/root/run/user/1000/vkd3d-scan`), `VKD3D_MEMTRACE_DEPTH=N`,
  `VKD3D_BENCH_DESC_SYSMEM[_IDX]`, `VKD3D_BENCH_GEOMIRROR_SYNC_EVERY`.

## Bench

- `flake.nix`: devShell (mingw-w64 gcc, meson/ninja/glslang, wine for widl, Ghidra, Python with pefile/capstone).
- `src/vkd3d-proton/libs/vkd3d/memtrace.c`: with `VKD3D_MEMTRACE=<file>`, logs every D3D12
  resource/heap create/destroy/name and every vkAllocateMemory/vkFreeMemory, with the calling
  game function as `exe_rva` (stack walk past Streamline/upscaler wrappers). Patch exported to
  `patches/memtrace.patch`.
- `bench/run.sh <name>`: launches the game like Lutris does, with the memtrace DLLs copied next
  to the exe only for the run. Output in `captures/<name>/`.
- `bench/sample.sh`: RAM/swap/pinned/VRAM every 2 s.
- `src/vkd3d-proton/libs/vkd3d/enginepatch.c`: in-memory engine patches (`VKD3D_ENGINE_PATCH=spin`)
  and `VKD3D_FRAMETRACE=<file>` (per-present times, draw counts, per-render-target draws in
  heavy frames). `bench/enginectl.py`, `bench/ab.py`: live A/B of the spin patch.
- `bench/ioreplay.py`: replay the game's streaming reads under different I/O strategies.
- `bench/cfgrun.sh <name> [vkd3d config]` + `bench/window.py`: unattended launch → Continue →
  30 s fps window in the prompt scene → quit. window.py also reports GPU power and PCIe rx/tx.
  `VKD3D_CONFIG_BASE=` (empty) drops run.sh's default log_memory_budget for fps runs.
- `VKD3D_BENCH_VRAM_RESERVE_MB=N` (memtrace.c, memory.c): cold allocations (engine L0 demotion heaps,
  committed sampled-only textures; game texture heaps too with `VKD3D_BENCH_VRAM_RESERVE_TEXHEAPS=1`)
  go to sysmem once less than N MiB of the VRAM budget is left, so render targets, depth and UAVs
  created later still get VRAM.

- Tools added 2026-10-13 afternoon: `bench/configs/*.env` + `bench/withcfg.sh <cfg> <cmd>` (configs
  exported one VAR=value per line; `env $CFG` in the Bash tool's zsh passes one giant variable),
  `bench/endgame.sh` (ends only the bench-prefix game: rule off, game, crash handler, wineserver,
  DLLs), `bench/runsum.py <runs>` (fps, p99, save load s, faults to scene, dropdst counters),
  `bench/probe.sh <run>` (KEEP_GAME + GPUTIME + MEMTRACE, then zramhuge + perf trace summaries of
  the game and its wineserver, then endgame), `bench/zramhuge.py` (swapped / incompressible pages per
  mapping from pagemap + zram block_state), `bench/pagesample.py` (compressibility and first bytes
  of sampled pages of a range).

## Plan

1. Measure: memtrace run through a fixed route (load save → swing a set path → photo mode at a fixed spot).
2. Attribute: group live memory by name / format / caller RVA; open the top callers in Ghidra.
3. Classify each big consumer: needed working set, over-provisioned pool, duplicate, never-touched,
   translation-layer overhead (vkd3d/driver), or spill.
4. Fix in the cheapest layer that is lossless: vkd3d-proton (heap placement, sparse/lazy backing,
   upload-heap policy), a hook DLL around the game's allocator/pool sizes, or a binary patch.
5. Verify every fix: same frames (photo-mode diff), memtrace + samples before/after.

## play-1013-2008: free-roam freezes (seen in play, not fixed yet)
~6 min of play on the optimized Lutris entry had short freezes without the loading icon.
frametrace: 37 frames > 500 ms, 7 > 1 s; the gameplay ones are mostly a cluster at 180-290 s, each
0.5-0.7 s. No swap-in or disk-read burst lines up with them (samples.tsv). vkd3d.log: VRAM ran out
in free roam and the sparse patches could not grow: lightgrid_grow "no VRAM ... retrying" (up to
1601 failed attempts), light grid LOSS on ~1300 submissions (page 3494 in use, 3456 backed), skinning
LOSS on ~100 submissions (24 MiB backed per half, 25.6 MiB used). The driven-fight bench never needed
this much, which is why v11/v12 showed 0 losses. Suspect: retried VRAM allocations stall frames; LOSS
also means wrong lighting/skinning (possibly the "weird" visuals seen earlier). Not proven: the
err lines carry no timestamps. Next: timestamp grow/LOSS lines into frametrace, cost each failed
allocation, then make the patches give back VRAM instead of losing (reserve headroom or fall back
to a fully backed allocation).

## 2026-10-14: free-roam freezes = shader compiles (NVIDIA cache unusable on the HDD)
- New instrumentation (frametrace E lines, same clock as F): light grid / skinning grow attempts and
  losses, every vkAllocateMemory that fails or takes > 2 ms (memory.c), every pipeline compile
  >= 2 ms with its PSO hash and thread, and vkd3d's late draw-time pipeline variants (state.c).
- play-1014-1624 (the Rhino chase played on the optimized build, hitch.py attached; analysed
  offline with a one-off script): ~45 freezes of 0.45-1.3 s. Growth attempts and driver
  allocations are all < 11 ms; in the worst freeze the Render Thread was on-CPU 558 of 578 ms in
  libnvidia-gpucomp (NVIDIA's shader compiler). No late vkd3d variants: the game creates PSOs on
  demand and they compile in full.
- psoA/psoB (bench, user-1013 save = the chase, CFGRUN_NOHUD=1): 238 PSOs that compiled slowly in A
  compiled slowly again in B (20.8 s): the driver's disk cache was not serving them. Cache at the
  Lutris path (game folder, HDD): psoB 40.8 s of compiles in the first 150 s, 142 >= 100 ms. Same
  cache copied to the SSD: psoC3 (+2 GB size limit) 1.3 s / 0, psoQ (default limit) 1.5 s / 2.
  Copied to the HDD under a plain ASCII path: psoP 85 s / 220. Fresh cache on the SSD: E1 450 s
  (cold), E2 1.0 s / 0. So the location on the HDD is the cause, not the size limit or the path
  name (both drives btrfs zstd:3, same options). __GL_SHADER_DISK_CACHE_SIZE=10737418240 (psoC)
  made the driver store nothing at all.
- Fix: play.sh points the cache at $bench/glcache (SSD, seeded from the game folder's). Then the
  whole game moved to the SSD (~/Games/Marvel's Spider-Man - Miles Morales).
- Light grid / skinning losses in the open world (the game runs ~230 MiB over its own VRAM budget,
  so growth found no VRAM; light grid highest page up to 4341, skinning 25.6 MiB/half): growth now
  falls back to system memory (vkd3d_bench_sysmem_type: a type of the buffer without DEVICE_LOCAL)
  instead of failing, so no page in use is ever unbacked.
- Correction: the system memory fallback cannot work here. The sparse light grid and skinning
  buffers only accept memory type 7 (VRAM; memoryTypeBits 0x80), so ssd2 still had 320 LOSS lines
  and the dark area was still there (missing light grid pages read as zero = no lights). Fix:
  larger initial backing, made while VRAM is still free: light grid 5120 pages (320 of 512 MiB;
  the chase peaked at page 4341), skinning 32 MiB per half (peak 25.6). ssd3 (game on the SSD, the
  chase): 0 LOSS lines, no failed growth. Savings vs stock shrink to ~192 MiB (light grid) and
  ~132 MiB (skinning); the fight-bench numbers (v11/v12) were measured with the smaller backing and
  on the HDD, so the progression has to be re-measured on the SSD.
- The game moved to ~/Games/Marvel's Spider-Man - Miles Morales (SSD) on 2026-10-14 (rsync, 94 files,
  51,409,538,724 bytes, identical); the HDD copy at /mnt/games was deleted after the check. bench
  scripts and the stock Lutris entry point at the SSD (old yml: .bak-hdd). ssd1: the chase's
  shader compiles 5.1 s in the first 150 s (HDD: 40.8 s), no frame > 300 ms after the first minute.

## Checkpoint S12 (2026-10-14)

Re-measured on the SSD (fight bench, FIGHT_SAVES=3): stock v13-S0-1/2 24.91/25.40 fps, p95 58.9/58.8 ms,
~529 frames over 40 ms a minute; S12 (the s9 config with the larger sparse backing) v13-S12-1/2
42.76/41.91 fps, p95 30.6/32.1 ms, ~18 a minute, GPU busy 94.1/94.8% (the GPU is the limit now).

Rollback point for the next experiments:
- src/vkd3d-proton branch miles-bench, tag checkpoint-s12 (on upstream 731c4aae); dxil-spirv
  branch miles-bench, tag checkpoint-s12 (on cc75a0c9). The same changes as plain diffs:
  patches/vkd3d-proton-checkpoint-s12.patch, patches/dxil-spirv-checkpoint-s12.patch.
- This repo: tag checkpoint-s12.
- The measured binaries: build/checkpoint-s12/bin (SHA256SUMS next to it; built 17:51, before
  ssd3 and v13-S12). bench/play.sh plays that copy (PLAY_DLLS overrides), never build/memtrace.
- Back to it: `git -C src/vkd3d-proton switch miles-bench && git -C src/vkd3d-proton reset --hard
  checkpoint-s12`, rebuild, or just run with BENCH_DLLS=build/checkpoint-s12/bin.

## Gaming mode (desktop side, 2026-10-14): `gaming-mode` in ~/Projects/dotfiles

Not RE: a desktop change (dotfiles `files/bin/gaming-mode`, hooked from Hyprland), measured here.
While the gaming workspace is shown with a window, it stops the shell (Noctalia, with a no-fade
layer rule first), closes terminals over session servers (reattached after), force-disconnects the
other screens (sysfs, root helper), and freezes + swaps out every other app unit.
- NVIDIA's VK_EXT_memory_budget heapBudget = 3072 - used(all processes) - 69 MiB reserved, so every
  MiB the desktop frees goes straight into the game's DXGI budget.
- Series gm1 (`bench/gmseries.sh`, run as its own app unit; game ON SCREEN both arms, S12 frozen
  DLLs, warm-up W0 then AB/BA/AB; A = gaming mode paused, B = on): `bench/gmsum.py gm1`.
  fps 44.35 -> 45.37 (+2.3%, every B above every A, closest pair 0.08 apart; to the 3rd autosave request as
  in the step bench: 44.35 -> 45.68, +3.0%, see Dashboard audit); game Video Budget
  2245 -> 2752 MB (+506), Video Usage 2324 -> 2785; pinned sysmem ~2130 -> ~1680 MiB; swap-ins
  22.4K -> 6.0K per run (~78/s -> ~21/s); game major faults -31%; frames > 100 ms 10.3 -> 7.3.
  Direct scanout active in both arms during the fight (Hyprland never composites the game).
- Demoted stays ~915 MB in both arms: the engine reads "VMEM Budget" once at startup (2466-2526 MB
  in both arms: gaming mode engages when the window is shown, i.e. after that read). Freed VRAM
  during play goes to vkd3d allocations that otherwise fall back to sysmem (as in v8-lg2).
  Next: engage gaming mode before the game starts and measure whether the engine keeps more
  textures in VRAM.
- Series gm2 (B = on when shown, C = on from the game's first instruction via `gaming-mode launch`,
  BENCH_WRAP in run.sh; warm-up then BC/CB/BC): the engine's startup "VMEM Budget" was 2997 MB in C
  vs 2465 in B (+532), yet Demoted stayed 1070 -> ~915 MB in both and fps C 45.28 vs B 44.92
  (+0.8%, ranges overlap: noise). The engine's texture demotion does not follow the VRAM budget at
  startup or live: it is the engine's own decision (a game-side lever, not a desktop one).

## Portability audit (2026-10-15): can S12 be worse than stock on another machine?

Read against: more VRAM, plenty of RAM and no swap, faster CPU or GPU, AMD/Intel/UMA, other
resolutions, another game build, with or without gaming mode. Gains do not depend on gaming mode
(all measured on the plain desktop; the patches read the live budget). Per kept step:
- Inert or better everywhere: VRAM reserve (refuses only when usage + size + reserve > budget,
  memory.c vkd3d_bench_vram_reserve_refuses), gdec (build + byte checked; MOVNTDQA on non-WC memory
  is a plain load), pdraw, lazy heaps, discard keep (command.c discard_attachment_barrier: vkd3d puts
  no barrier between two ordinary passes writing one RT either, so the discard case is ordered as
  every RT write already is; skipping UNDEFINED keeps valid compression metadata), particle batching
  (GPU side; its CPU cost where the CPU is the limit is unmeasured).
- dxil-spirv change: descriptor-QA counting only; play DLLs come from build/memtrace,
  enable_descriptor_qa=false, so not compiled in.
- Defects on other setups (none affects this machine):
  - index cache: engine_patch_init returns on an unknown exe build before installing the geometry
    write hooks, but vkd3d_index_cache_wanted checks only env + heap shape, so after a game update
    the cache would run without invalidation (stale indices possible). Also no UMA check.
  - light grid / skinning: heap.c shrinks the heap before checking sparse support;
    vkd3d_lightgrid_create_placed returns E_INVALIDARG without an internal sparse queue, so the
    game's CreatePlacedResource fails at startup.
- Costs with nothing to gain: dropdst reads pagemap per copy >= 16 KiB even when nothing is
  swapped (~1% of a core); the DXGI budget hook always hides 2 light grid + 2 skinning margins
  (~80 MiB); index cache lookups ~1.8% of the render thread (matters only when it is the limit).
- Fixed sizes tuned to this card: reserve 192 MiB (late RTs scale with resolution), light grid
  initial 5120 / margin 512 pages, skinning 32 / 8 MiB per half, index cache 64 MiB, batch 16.
Plan: every step acts on a measured need or is identical to stock; test the stronger-machine
cases here with live A/B at lower resolution (CPU-bound) and lower texture quality (VRAM to spare).

## S13 (2026-10-15): sizes measured instead of fixed, gates for other machines (build/memtrace)

Code (src/vkd3d-proton, uncommitted on top of checkpoint-s12): learned.c keeps per-exe-build values in
learned/vkd3d-proton.MilesMorales.exe.learned (VKD3D_BENCH_LEARNED_PATH, set by run.sh), written by a
thread at most every 10 s. Config bench/configs/s13-learned.env; S12 A/B arm bench/configs/s12-frozen.env.
- Gates: index cache needs the geometry write hooks and a non-UMA device; light grid / skinning need
  sparse buffers (checked before the heap shrinks) and skinning all 8 redirects; dropdst skips pagemap
  reads while the game's VmSwap is 0 (re-read every 100 ms).
- Light grid / skinning initial backing = learned peak + one margin (whole buffer before anything is
  learned); peaks recorded on every check. Seeded from logged sessions: 4342 pages, 25.6 MiB/half.
- Budget the game sees: growth hold now ramps with need, PLUS a learned hold. Lesson: S12's fixed
  2+2 margins (80 MiB) also kept the texture streamer off vkd3d's later VRAM (the streamer runs
  70-95 MiB over whatever budget it is told). Growth-only hold (6 MiB): 119-269 failed VRAM
  allocations, 39.2-40.0 fps (v14-S13-1, v14-S13r192-1); S13 + hold 80 + reserve 192 forced: 0 fails,
  43.09 (v14-S13h80-1). The hold is raised live by each failed non-cold VRAM allocation (largest in a
  2 s window; the driver refused 6 MiB with ~20 MiB of budget left, so a refusal always counts).
- VRAM reserve (VKD3D_BENCH_VRAM_RESERVE=1): need = reserve - least VRAM left after any non-cold VRAM
  allocation after VRAM first ran short (failure = negative). Counting only RT/DS/UAV/buffer demand
  was wrong: the game's texture heaps also eat the reserve. S12 operating point leaves 22.6 MiB at the
  tightest moment (v14-S13h80-1). Seeded at S12's 192 MiB reserve / 80 MiB hold; they only rise
  (max over sessions); trimming the slack needs several sessions of evidence.
- Bench hygiene: Steam's web helper took ~240 MiB of VRAM (desktop 915 vs 673 MiB before the run,
  v14-learn2); a Super+G during a run engaged gaming mode mid-fight (v14-learn). Runs now pause
  gaming-mode (pause/resume) and check desktop VRAM first.
- Series v15 (same evening, ABBA, FIGHT_SAVES=3, final build): S12 43.27 / 41.87 (mean 42.57), S13
  42.69 / 42.66 (mean 42.68, +0.25%: equal); 0 failed VRAM allocations in all four; S13 pins ~15 MiB
  less system RAM. Earlier S12 run the same evening: 42.70.
- Gaming mode transitions hitch the game (v14-learn, by accident): enter -> slow frames up to 435 ms,
  leave -> 398 ms, re-enter -> 179 ms. Taken apart on 2026-10-15 (captures/gmt1: the S13 game held
  still at 60 Hz, hidden, each step timed against its frames; one-off driver scripts,
  `gaming-mode` traced with PS4=$EPOCHREALTIME):
  - Most of v14-learn's "7 s" was the game's own pre-fight scene (48 ms frames before the Super+G).
  - The big stalls are the TV's modeset, whichever way it is done: connector forced off 97-226 ms
    worst frame, back on 106-208 ms; Hyprland DPMS off 292 ms (and frees no VRAM; forcing the
    connector off frees 328 MiB). Hyprland's thread is blocked in the commit, so the game's
    presents stall with it. On enter the game is on screen: this is the visible hitch.
  - Swapping out frozen apps is not a hitch source: 600 MiB reclaimed synchronously at normal
    priority, worst frame 21 ms (two busy cores for 2 s: 27 ms). Moved to the background at idle
    priority anyway, so enter no longer holds the lock while a big app swaps out.
  - A window mapping or closing on a visible workspace costs 30-110 ms frames even at nice 19
    (compositor side, not CPU): kitty's start/close, Noctalia's start. On leave the game is hidden.
  - Leave took 2.2 s, mostly `running_like` forking `cmp` per process (0.35 s per scan, repeated
    while waiting): now compared in the shell (11 ms), leave 1.1 s, terminal back at 0.26 s,
    extra frame time during leave 733 -> 440 ms.
  - Deploying dotfiles (home-manager switch) reloads Hyprland's config, which drops the bench's
    runtime rule and render_unfocused_fps (the hidden game fell to 15 fps): re-run
    `bench/hyprbench.py setup` after a deploy during a run.
  - Mirror mode (display-mode, Super+Shift+M: the TV mirrors HDMI-A-1 at 1080p60): gaming mode used
    to cut the TV there too (only the game's sound kept a screen), so the game vanished from it.
    Fixed 2026-10-15: a screen mirroring the game's screen is kept, so mirror mode has no TV
    modeset at all on Super+G. Its cost instead: Hyprland 0.56.2 never scans out directly on a
    mirrored monitor (Monitor.cpp isDSBlocked, DS_BLOCK_MIRROR), so every game frame is copied
    (monitor + TV). Not measured yet.
  Open: the TV modeset on enter (extended mode). Options: keep the TV off during short desktop visits while the game
  runs, or take the TV off before Super+G reveals the game (a ~0.3 s later switch instead of a
  stall). Not decided.
- Textures in system RAM (item 3, 2026-10-15, captures/tex1 tex2, S13, gaming mode paused): the GPU
  reads 2.08 GB/s over PCIe in the fight (peak 3.9, ~50 MB a frame) with SM 90% / memory controller
  24% busy: it waits on system memory. But what lives there is already the coldest data per MiB
  (descriptor-QA counts, 2026-10-13: sysmem textures 2-7k accesses/MiB, ManagedBuffer ~4.75k, VRAM
  textures 250-860k). Demoted 916 MiB = 573.6 MiB of L0 heaps in SYS + 342.8 MiB that vkd3d already
  put in VRAM. Placed resources fill 2755 of 3651 MiB of heap space, but 708 MiB of the gap is the
  light grid and skinning heaps (backed lazily already) and ~160 MiB is spread over ~2000 small
  heaps the engine fills as it streams. Vertices cannot be cached per page (NVIDIA sparse buffers
  are VRAM-only, the vertex views span the whole heap). No large lossless lever here: the PCIe wait
  is what fitting this game into 3 GB costs.
- Checkpoint S13 (2026-10-15): binaries build/checkpoint-s13/bin (SHA256SUMS), source = checkpoint-s12
  + patches/vkd3d-proton-checkpoint-s13.patch (committed: vkd3d fork tag checkpoint-s13). bench/play.sh plays it (PLAY_DLLS=
  build/checkpoint-s12/bin goes back). Play sessions share learned/ with the bench, so open-world
  play raises the light grid / skinning peaks, the reserve and the hold for later sessions.
- Adaptive particle batch (item 2, 2026-10-15, dropped before building): copies 16-31 only on a
  machine that never ran short of VRAM. Not worth it: 16 -> 32 measured +0.18 fps (v5-pk, 50.57 vs
  50.75, noise) for 48 MiB more VRAM; on this card it changes nothing (a reserve is learned); and a
  first session on a tight machine would hold the extra 48 MiB until VRAM ran short, which would
  then be learned into the reserve, and learned values only rise. No way to free the copies safely
  mid-session without fence tracking.

## S14 (2026-10-15): index cache eviction fix (checkpoint-s14)

- Bug (idxcache.c idxc_alloc_locked, since the cache began): the eviction loop compared run_of[i]
  with the run being evicted while it cleared run_of[i], so it stopped after the first page and the
  rest of each evicted run stayed attached to it: counted as used, never reusable until the ring
  wrapped onto the run's first page again. The cache refused runs it had room for.
- New frame trace lines: IA (cache MiB held by runs last drawn 0, 1, 2, 3, 4-7, 8+ presents ago,
  free MiB) and IS (requests / failures per run size class, largest gap at a failure).
- Fight, S13 vs fixed (ia1/ia2 captures): refusals 2153/s -> 304/s average, seconds with any
  refusal 135 -> 14; true hot set (runs drawn in the last 8 presents) 8.5 MiB, not the 15.3 MiB the
  orphans made it look like. Verify run (ia3v, VKD3D_BENCH_INDEX_CACHE_VERIFY=1): 636,136 hits
  compared byte for byte, 0 mismatches. It never served wrong data before either: orphans were
  only lost space.
- Series v16 (2026-10-15 05:07-05:50, ABBA x2, FIGHT_SAVES=3, gaming mode paused; A = s13-frozen.env,
  B = the fix with S13's read-only learned values, bench/configs/candidate-vs-s13.env):
  A 41.99 / 42.66 / 43.98 / 44.89 (mean 43.38), B 43.35 / 42.86 / 43.89 / 44.26 (mean 43.59, +0.5%:
  equal within noise; fps drifted up through the series, which ABBA cancels). p99 38.0 -> 37.1 ms,
  frames > 40 ms 257 -> 238, > 100 ms 27 -> 28; failed VRAM allocations A 2/6/0/0, B 0 in all four.
- Checkpoint S14: vkd3d fork commit 375c0f99, tag checkpoint-s14 (patch:
  patches/vkd3d-proton-checkpoint-s14.patch); binaries build/checkpoint-s14/bin (SHA256SUMS), the
  read-only learned copy = S13's; config bench/configs/s14-frozen.env. bench/play.sh plays S14.
- Review: the fix is correct. Its new "largest gap" stat walks the whole ring on every
  failed search under the lock (16K steps x ~300 failures/s): measured inside B anyway, to be gated.


## S15 (2026-10-15): clear keep + review fixes (checkpoint-s15)

- Where the barrier time goes (v12-S9-gt GN notes): of ~1.2-2.4 ms/frame of
  "empty" GPU segments, the costly vkd3d-internal ones are (a) the particle phases (work hidden in
  secondaries), (b) one barrier per frame right before the G-buffer pass that transitions 4 colour
  targets from UNDEFINED: 121-131 us at the fight's 968x544, 276-284 us at 1080p, (c) the depth
  buffer's UNDEFINED transition (24-77 us), (d) the present blit (87 us). Layout changes between
  known layouts cost 2-10 us; it is UNDEFINED that NVIDIA pays for.
- Why: vkd3d transitions every full clear of a *placed* render target from UNDEFINED (another
  resource on the same memory may have written it). The engine places each G-buffer target in a
  heap of its own together with 11 smaller dynamic-resolution variants of it, all at offset 0
  (memtrace tex2), so all of them may alias.
- Probe (s15-ck1, still scene, live ABBA via features 0x1000): skip it when the heap's last clear
  was the same resource: 57.53 -> 58.42 fps (+1.6%, every on-window above every off-window),
  ~18 kept clears per frame; screenshots on/off within the scene's own animation noise.
- Kept version (`VKD3D_BENCH_CLEAR_KEEP=1`, command.c "clear keep"): a heap qualifies while all it
  ever held are single-subresource RT/DS textures (UAV access allowed, no simultaneous access), never
  tile-mapped, only used from direct lists on one queue. D3D12 requires the first operation on an
  RT/DS texture after another resource used its memory to be a Clear, Discard or Copy, all of which
  vkd3d sees, so writes it cannot see (UAVs through descriptors) only ever come from the owner. Every use of such a resource in a list (all of
  d3d12_command_list_track_resource_usage: render passes, clears, discards, copies, resolves,
  barriers; reads count too) is an event; ExecuteCommandLists replays each list's events in
  submission order, giving the heap's GPU-order owner and whether a clear transitioned it from
  UNDEFINED since it became owner. A full clear keeps the layout only if that GPU-order state says
  the cleared resource owns and initialized the memory, no other unsubmitted list has used the heap,
  and nothing else in this list used it first. A kept clear whose list is submitted after another
  list that used the heap (out-of-order submission) fails the replay check: ERR, feature off.
- Review fixes in the same build (a review of S13/S14; each checked against the code first):
  - learned.c: a first raise of a key racing a smaller one could leave the smaller value (CAS loop on
    "unknown"): fixed. Values that no memory size can have (negative, > 1 TiB) are ignored. The
    writer thread pins the DLL. The file now records the GPU (vendor, device, VRAM heap size): a
    file learned on another GPU is dropped for later sessions. Sessions that force the reserve or
    the hold (VKD3D_BENCH_VRAM_RESERVE_MB/_TEXHEAPS/_CHUNKS, VKD3D_BENCH_BUDGET_HOLD_MB) no longer
    write the reserve or the hold.
  - Integrated GPUs: no VRAM reserve, no budget hold, no index cache (deviceType, not only UMA).
  - Light grid / skinning: a failed growth used to leave "wanted" at its target (up to the whole
    buffer after a failed initial backing), so the budget hook hid that much VRAM from the game for
    the rest of the session; now only what the pages in use need stays wanted. A growth the game
    needs that finds no VRAM raises the budget hold like any other failed VRAM allocation.
  - Lazy backing (learned peak + margin) only where VRAM has run short before (a reserve is
    learned); elsewhere both buffers are backed whole, as stock, so a scene no earlier session
    reached can never meet a growth that finds no VRAM on a big card.
  - Not changed, with reasons: max(growth room, hold) is deliberate (the hold is a floor that
    replaced S12's fixed 80 MiB growth margins; 0 light-grid losses in v15/v16). Refusals count
    toward the hold even with budget left (the driver refused 6 MiB with ~20 MiB left). The "largest
    gap" stat costs ~30 us per failed search that gets past fail-fast (about one per present).
  - Index cache, verify mode: every cached draw now also records the run and generation it used, and
    ExecuteCommandLists checks that the source pages were not written and the run not evicted
    between recording and submission (the reviewer's "CPU write after record" / "late execution").
- s15-ck2 (safe version, UAV-capable targets excluded): +0.5% (58.22 -> 58.52, every on-window above
  every off-window), but only ~290 kept clears/s vs ~1050/s in the probe: most dynamic-resolution
  targets allow UAV access (flags 0x5). Relaxed on the D3D12 initialization rule above (s15-ck3).
- s15-ck3 (relaxed, kept version): off 57.65 / 58.87 / 58.90 / 58.85, on 58.84 / 59.52 / 59.43 /
  59.45 (+1.3%; +1.0% leaving out the first pair, which ran while the scene was still settling);
  ~950 kept clears/s in steady state, 0 failed GPU-order checks; screenshots off/on 50.9 / 57.8 dB
  vs on/on 50.8 dB and off/off 57.1 dB (the scene's own animation).
- Review round 2 (clear keep), applied:
  - A kept clear replayed on a heap that has since stopped qualifying is a failed check (it was only
    checked for owner/initialized before).
  - Second queue / non-direct list: the first use of a qualifying heap from a non-direct list, or
    the first replayed event on a second queue, makes the heap stop qualifying; if a kept clear was
    ever recorded on it, clear keep goes off for the session (fences, not this replay, order queues).
  - Out of memory growing a list's event or heap array: the heap stops qualifying (a missing event
    would hide a use from the replay).
  - Shared heaps (SHARED, SHARED_CROSS_ADAPTER) and heaps opened from a host address never qualify.
  - Per-list cost: one record per (list, heap) with the first and last resource and a "mixed" flag
    replaces the scan of the list's events; a use repeating the list's last use of the heap by the
    same resource is not stored.
  - DISCARD_KEEP (part of S5) skipped the UNDEFINED barrier of every discarded render target, placed ones
    included, and a discard is how D3D12 activates a placed target after an alias, so that skip was
    only safe by luck. Now it applies to committed targets as before, and to placed ones only when
    clear keep proves the target owns and initialized the memory (a discard is then a kept clear;
    otherwise it transitions from UNDEFINED and counts as the initialization).
  - Depth: kept depth clears transition (if the depth layout must change) from the layout the
    resource has, like the render pass would, instead of from UNDEFINED. Only a clear covering
    every aspect counts as an initialization (depth-stencil formats have two planes, so they never
    qualify anyway: single-subresource rule).
  - Not changed (residual, documented): a list submitted out of order whose kept clear fails the
    replay check has already been recorded, so that one submission runs with the kept clear (the
    check turns the feature off for everything after it; the fix would split command buffers at
    every clear). The learned file belongs to the first GPU the game creates a device on (hybrid
    laptops that switch GPUs relearn: values recorded on another GPU are zeroed).
- v17 fight A/B (S14 frozen vs the build before the round-2 edits, ABBA x2, 3rd autosave): A 44.46 /
  45.55 / 44.71 / 42.38 = 44.28, B 44.52 / 43.72 / 45.20 / 44.43 = 44.47 fps (+0.4%, inside the
  fight's run-to-run spread); p99 35.6 vs 36.4 ms, frames over 40 ms 51.5 vs 49, over 100 ms 6.75 vs
  7, 0 light-grid losses, same demoted MiB; failed 6 MiB VRAM allocations A 0/4/0/2, B 0/0/2/6 (the
  same small allocation, in both arms). ~91% of full clears of placed targets kept, 0 failed checks.
- Review round 3 found a real bug in the round-2 dedupe: a new (list, heap) record started with
  last_id = the resource, so the first use of a heap in a list that already had other events was
  dropped as a "repeat", hiding an activation by copy/resolve/UAV clear from the replay (a later
  clear of the aliased target could then be kept with no ERR). Fixed (last_id starts at 0);
  confirmed by the reviewer. s15-ck4 (pre-fix build): +2.6%; not used.
- s15-ck5 (final build, static scene, live A/B of the bit): off 58.09 / 58.11 / 58.00 / 57.84, on
  59.48 / 59.41 / 59.00 / 59.43: 58.01 -> 59.33 fps (+2.3%, every on-window above every off-window).
  The off arm is now slower than S14 by the discard fix (placed render targets transition from
  UNDEFINED on discard again unless clear keep proves them), so the fight A/B against frozen S14
  is the measure that counts. Steady state: ~57,000 kept per 30 s against 30 transitions; 0 failed
  checks, never off; screenshots off/on 50.5 / 55.8 dB vs on/on 50.3 dB and off/off 57.1 dB.
- v18 fight A/B (S14 frozen vs the final build, staged as build/s15-staged; ABBA x2, 3rd autosave):
  A 44.41 / 43.02 / 42.60 / 43.18 = 43.30, B 44.43 / 44.83 / 43.38 / 44.36 = 44.25 fps (+2.2%); p95
  30.1 -> 29.9, p99 36.8 -> 36.5 ms, frames over 40 ms 52.5 vs 52.8 per run, over 100 ms 6.0 vs 7.0,
  worst 118 vs 122 ms, 0 light-grid losses. The >100 ms frames are the same fight moments in every
  run of both arms (2-3 frames at each autosave / phase change), none next to an allocation event.
  ~91% of full clears of placed targets kept, 0 failed checks, never off.
- Failed VRAM allocations (the game's 6.1 MiB heaps; each burst raises the budget hold by 6.1 MiB;
  first try ~3.5 ms, retries ~0.05 ms): v18 A 0/0/0/4, B 0/0/16/14 (v17: A 0/4/0/2, B 0/0/2/6).
  Checked: vkd3d's own accounting (heap #0 usage through loading, light grid 4865 pages, skinning
  36 MiB, reserve 192 MiB, hold 80 MiB) is identical in B2/B6/B7/A8; other processes held 525 MiB in
  every run. The difference is the game's own VRAM in v18-B6/B7 (+32 MiB, already 20 s before the
  fight, i.e. from loading), absent from B2/B3 on the same build and from v17's B runs, while S14 runs
  show the same spread in the game's own telemetry (Video Usage v18-A1 2533, v17-A8 2526 MiB vs
  2485). Taken as run variance (nothing in S15 allocates); a confirmation series follows (v19).
- Checkpoint: fork commit 012433f4, tag checkpoint-s15 (diff vs checkpoint-s14 =
  patches/vkd3d-proton-checkpoint-s15.patch, byte-identical to the diff the v18 build was made
  from); binaries build/checkpoint-s15/bin (SHA256SUMS; d3d12core b28f5086..., d3d12 5a9cc229...,
  unchanged), read-only learned copy = S14's; config bench/configs/s15-frozen.env. bench/play.sh
  plays S15 (VKD3D_BENCH_CLEAR_KEEP=1). Back to S14: PLAY_DLLS=build/checkpoint-s14/bin.
- v19 confirmation (frozen S14 vs frozen S15, order BAAB x2, the reverse of v18): A 42.52 / 43.97 /
  44.24 / 40.46 = 42.79, B 44.96 / 44.44 / 43.11 / 45.73 = 44.56 fps (+4.1%); p95 30.7 -> 29.4, p99
  36.9 -> 34.9 ms, over 40 ms 48.5 -> 45.5, over 100 ms 7.25 -> 6.25, worst 122 -> 116 ms; 0 light-grid
  losses, 0 failed clear-keep checks (~91% kept). Failed VRAM allocations A 0/10/16/19, B 0/0/50/0:
  they come with a game state, not a build. Some launches load with ~32 MiB more of the game's own
  VRAM (nvidia-smi, 2403-2412 vs 2371-2386 MiB, from before the fight starts), in both arms (v18 B6,
  B7; v19 A2, A3, A6, A7, B5); every failure burst is in such a launch. The first budget the game is
  given (2563-2575 MiB) does not predict it. That state also costs fps (S14 42.8 vs 43.3, S15 43.6 vs
  44.9), and v19 drew it for all four S14 launches, so v19's +4.1% overstates; v18 + v19 together:
  S14 43.05, S15 44.40 fps (+3.1%).
- Index cache, verify at submission (VKD3D_BENCH_INDEX_CACHE_VERIFY=1, s15 + verify): the page-level
  check from round 1 flagged, over one fight (16.1M cached draws), 3 draws whose source pages were
  written between recording and submission and 10,470 whose run "was evicted". Both are page-level
  upper bounds: the table entry is re-pointed when a later draw needs a longer run from the same page
  (the old run stays intact and drawable), and a write anywhere in a 4 KiB page bumps its generation.
  The check now compares, at submission, the exact bytes each cached draw will read (cached copy vs
  source; copies at least two presents old) and counts reused cache pages separately (fork, after
  checkpoint-s15; verify-only code, play builds unchanged). v19-verify3: 5,222,164 cached draws
  checked, 4,945,315 compared byte for byte, 0 differ, 0 reused, 0 late (page level: 5,217
  re-pointed, 3 pages written since). The verify build reads the write-combined source on the CPU,
  so it ran at 4 fps; a diagnostic, not a measurement.

## S16 (2026-10-15): render-thread CPU cuts (checkpoint-s16)

Goal: 52 fps in the fight (S15: ~44-45). Where the S15 frame goes (fight, ~45 fps,
~21.8 ms/frame; one-off scripts):
- GPU (v20-S15-gt): queue 0 compute 9.65 ms, render 9.61, barrier-only 1.10, copies 0.63: ~21 ms of
  GPU work per frame. Heaviest shaders 7377a06a 1.72 ms, 53df85 1.32, c9d908 1.14, 13005b60 1.00,
  b9458a24 0.68, b24add 0.55, 3990525 0.33; their SPIR-V (analysis/shaders) is clean
  (OpRawAccessChainNV, almost no NoContraction): no lossless codegen lever there. The ~21 full
  ALL_COMMANDS barriers per frame are the particle-batch phase barriers (their time is particle work
  in secondaries); the depth layout changes (~0.2 ms) are inherent; the present blit is 0.08 ms.
- Clocks (v20-S15-clk, nvidia-smi 1 Hz): 1911 MHz core / 4006 MHz memory throughout, P0, PCIe gen3 x16,
  77 W of a 120 W limit, 77 C, no throttle reason in any sample. No clock lever.
- No VK_EXT_descriptor_heap / mutable descriptors on this driver, and the game's root signatures use
  multi-descriptor volatile CBV tables, so CBVs cannot be hoisted into root descriptors.
- DRAM (v20-S15-mem, uncore IMC counters): 7.3-7.9 GiB/s of the single channel's 11.9 GiB/s; CPU
  cores 5.6-5.8, GPU over PCIe 1.6-2.3. 91% of the CPU's L3-miss traffic is the game process, 75% in
  MilesMorales.exe itself, spread over many functions (top one 3.2%); vkd3d (d3d12core) 4%.
- GPU idle: nvidia-smi utilization ~92% (~1.7 ms/frame idle), from late submissions by the render
  thread (~90 us per command buffer from record to submit); waits on other queues are 0.04 ms.
- CPU (v20-S15-cpu, per-thread CPU time): Render Thread 18.88 ms/frame (2.1 ms of it the game's own
  pause spin), main thread 18.36, job threads 6-9 each. Render thread by module: game 48.6%,
  d3d12core 17%, NVIDIA driver 16%, ntdll 5.5%, msvcrt 5.1%.
- Render-thread call stacks (perf LBR, v21-dev-lbr): d3d12_fence_GetCompletedValue 5.0% (the fence
  mutex, contended with the fence worker: SRW acquire + wake), the global atomic in
  vkd3d_frametrace_count_draw ~4%, vkd3d_index_cache_lookup's lock ~3.1%, one
  vkCmdBindIndexBuffer2KHR per cached indexed draw, clear keep's ck_use lock.
  d3d12_desc_copy_range is 6.4% inclusive, 4.7% of it memmove: the descriptor payload copies
  (~2 MB/frame of real data movement), left alone. begin_render_pass 8.7%, mostly NVIDIA driver time.
- Changes (fork, all lossless: identical GPU work and D3D12-visible behaviour):
  1. Frame trace: draws are counted per command list (list->bench_draws, reset with the list) and
     added to the frame's count in ExecuteCommandLists, instead of a global atomic per draw from
     every recording thread. Diagnostic only; run.sh/play.sh sessions always have the trace on.
  2. Index cache: the cache buffer is bound whole once (offset 0, VK_WHOLE_SIZE) and each cached draw
     passes firstIndex = cache offset / index size (the old per-draw bind when the offset is not
     index-aligned or does not fit 32 bits). A shadow (list->bench_idxc_bound, type, command buffer)
     is cleared wherever the index binding can change: list reset, invalidate_all_state,
     IASetIndexBuffer, ExecuteIndirect index-buffer tokens, and update_index_buffer's bind of the
     game's buffer; index_buffer.is_dirty stays set after a cached draw, so the next uncached draw
     rebinds the game's buffer as before.
  3. Clear keep: ck_use checks the list's own (list, heap) records before taking vkd3d_ck_lock and
     returns when the use repeats the record's last resource (ck_add_event would store nothing).
  4. Fences: GetCompletedValue reads virtual_value with an acquire load and no mutex; the two runtime
     stores (CPU signal, the worker's signal loop) are release stores, still under the mutex.
  5. Index cache: idxc_lock is a reader/writer lock; a hit on a fresh run is served under the shared
     lock (table, generations and runs only change under the exclusive lock; the hit writes only the
     run's last-drawn present, atomically, and the hit count). Misses, stale runs and verify mode
     take the exclusive lock and the unchanged full path.
- v21-dev (changes 1-3): Render Thread 18.18 ms/frame (-0.7 ms vs S15).
- Review (all five changes): no lossless defect. One real race in 5: two shared-lock hits could
  store their present counts out of order, so a run's last-drawn present could go back by one
  (eviction margin 7 presents instead of 8). Fixed: the store is a CAS max (and is skipped when the
  value is already current). Also checked by the reviewer: every Vulkan index bind and every
  command-buffer switch clears or re-keys the shadow; VK_WHOLE_SIZE with offset 0 is valid and every
  index read stays in range; no fence reader relied on the mutex for ordering (a poller may now see
  an intermediate value of a multi-signal batch, each a completed GPU-order signal: valid D3D12).
  Not changed: the hit counter stays one relaxed atomic per cached draw.
- v21 fight A/B (S15 frozen vs changes 1-5 before the review fix, build/s16-staged; ABBA x2, 3rd
  autosave): A 43.67 / 43.71 / 43.75 / 44.00 = 43.78, B 43.64 / 44.25 / 44.05 / 43.87 = 43.95 fps
  (+0.4%); p95 30.30 -> 30.08, p99 37.1 -> 36.0 ms, over 40 ms 52 -> 48 per run, over 100 ms 7 -> 7,
  worst 121 vs 122 ms; 0 light-grid losses. All four B launches drew the game's +32 MiB VRAM state
  (game total ~2925 vs ~2893 MiB; other processes 501-521 MiB in every run), one A launch did (A5):
  failed 6 MiB allocations A 8/2/12/0, B 2/24/16/24, fallen back to system memory as before (demoted
  912-920 MiB in both). That state costs fps (v19), so B's lead is despite it.
- v22 fight A/B (S15 frozen vs the final build with the review fix, build/s16b-staged; order BAAB
  x2, the reverse of v21): A 44.16 / 41.11 / 43.53 / 44.08 = 43.22, B 44.58 / 43.44 / 43.60 / 44.93 =
  44.14 fps (+2.1%); p95 30.60 -> 30.14, p99 36.40 -> 36.23 ms, over 40 ms 51 -> 52, over 100 ms
  7.25 -> 7.0; 0 light-grid losses. The +32 MiB state: A 3 of 4 launches (A3, A6, A7), B 2 of 4 (B4,
  B5), so v21's 4 of 4 was the draw (S15 over v18-v22: 10 of 24 launches; S16 6 of 8; p ~0.1).
- v21 + v22 (16 launches): S15 43.50, S16 44.05 fps (+1.25%; +1.22% with every launch cut at the 3rd
  autosave request, see Dashboard audit); within the same VRAM state +1.6% (high:
  43.12 vs 43.81) and +2.0% (low: 43.89 vs 44.76). p95 30.45 -> 30.11, p99 36.75 -> 36.10 ms. Spike
  frames pooled over all 16 launches: over 60 ms 15.5 vs 16.0 per launch, over 100 ms 7.1 vs 7.0,
  their median 111.7 vs 111.8 ms (the same autosave / phase-change frames in every launch).
- Not the 52 fps asked for: the fight is GPU-bound (~21 ms of GPU work per ~22 ms frame), and the
  CPU cuts only remove render-thread time where it delays a submission.
- Checkpoint: fork commit 9369c583, tag checkpoint-s16 (diff vs checkpoint-s15 =
  patches/vkd3d-proton-checkpoint-s16.patch, includes the verify-only commit 51ccb440); binaries
  build/checkpoint-s16/bin = the v22 B build (SHA256SUMS; d3d12core 88676f50..., d3d12 5a9cc229...,
  unchanged), read-only learned copy = S15's (58ee4aeb...); config bench/configs/s16-frozen.env.
  bench/play.sh plays S16. Back to S15: PLAY_DLLS=build/checkpoint-s15/bin.

## S16 follow-up (2026-10-15): where the GPU's idle time goes (no lever on vkd3d's side)

- Question: the fight is GPU-bound but the direct queue still idles between command buffers (gputime:
  2.9-4.8 ms per sampled frame; nvidia-smi ~92% busy, ~1.7 ms/frame). How much of that is vkd3d's?
- Diagnostics added (fork 058a0850, off unless enabled): gputime's GS lines carry the
  ExecuteCommandLists time, the return of vkQueueSubmit2 and the submit's semaphores
  (bench/gpugaps.py splits each gap: game late / vkd3d queue thread / submitted but not started);
  VKD3D_BENCH_PRESENT_TIMING=1 times the present task. Configs bench/configs/diag-*.env.
- v23-S16-gt (S16 + diagnostics): idle 4.06 ms/frame = game late 2.27, queue thread 0.54, submitted
  but not started 1.25 (an upper bound: it includes the 70-150 us an idle GPU takes to start a new
  submission, and gaps filled by command buffers recorded before the sampled frame, which gputime
  does not track). Most game-late idle sits mid-frame (before the 5th command buffer: 0.7-3.3 ms
  waits for the render thread), not at the frame start.
- vkd3d chains every submission on a D3D12 queue with a binary "serializing" semaphore on NVIDIA
  (upstream 53288f6f; other drivers get a reusable full-barrier command buffer). Probe
  (VKD3D_BENCH_SUBMIT_BARRIER, v23-sb-gt, removed): measured only where the next command buffer was
  already queued, a boundary costs 12.5 us (median) with the semaphore and 13.2 us with the barrier
  command buffer. Not a lever.
- vkd3d queue trace (VKD3D_QUEUE_PROFILE, v23-qp): the direct queue's submission thread spends per
  frame 1.22 ms presenting (the swapchain present runs on it), 0.85 ms submitting, 0.58 ms in queue
  waits, 0.55 ms waiting for signals not yet submitted (median 0.5 us, up to 13.6 ms). Against the
  submission timeline, only ~0.15 ms/frame of GPU idle overlaps that thread's work (0.002 ms the
  present); the rest is the game submitting late.
- Present (v23-pt): the game runs VSync on at 60 Hz (its log), so vkd3d presents FIFO (mode 2):
  acquire 39 us, blit submit 59 us, vkQueuePresentKHR 761 us median (p90 3.6 ms) on the queue thread,
  while the GPU is still busy with earlier work.
- Conclusion: the idle is the game's render thread (S16 already took vkd3d's own locking off it);
  what is left on vkd3d's side is ~0.15 ms/frame. (Overstated, see Dashboard audit: the 0.54 ms
  between ExecuteCommandLists and vkQueueSubmit2 is only ~0.15 ms the queue thread working; the rest is
  unexplained, and the 1.25 ms submitted-not-started is neither thread.) Toward 52 fps the remaining cost is GPU work
  (~21 ms/frame), which earlier analysis found no lossless lever for (S16 section).

## Dashboard audit (2026-10-15): like-for-like checks

Started from the question why frames over 100 ms rose from 5.0 (S8) to 7.0 (S16).
- Window: v10-v13 HDD launches were read with bench/fightwin.py (fight start to the 3rd autosave
  request); fight.json from v13 on (fightrun polls game.log once a second) ran 0.36-1.0 s past the
  request and caught 1-2 frames of that autosave's own stall (104-127 ms). Every launch now via
  `bench/fightwin.py 3` (captures/<run>/fightwin3.json). Frames over 100 ms: S8 5.0, S9 5.7, S12 5.0,
  S13-S15 5.3, S16 5.5; from S8 on 5.3 per fight, 3.6 of them between 1 s before and 4 s after the
  1st/2nd autosave request, the same on the HDD (S8-S9) and the SSD (S12-S16). No regression.
  Same-series fps: S16 vs S15 +1.22% (v21, v22), S15 vs S14 +3.12% (v18, v19), S14 +0.48%, S13 +0.23%.
- Gaming mode (gm1/gm2) used fight.json's longer window (259-333 s, past the 3rd autosave). To the
  3rd request: gm1 44.35 -> 45.68 fps (+3.0%, every B above every A still), over 100 ms 6.0 -> 3.7;
  gm2 B 45.15, C 45.49 (+0.8%). Swap-ins stay whole-run (the counter is read only at start and end).
- On screen vs the step bench: the same S12 build within hours ran 44.35 fps in gm1's normal-desktop
  arm (game on screen, direct scanout, warm-up launch first) and 42.49 in v13/v15 (hidden, the
  desktop composited): +4.4%. Cause not isolated. The 2026-10-12 check that hidden rendering is
  neutral was one 12 s peek at ~34 fps; it does not settle this. A/B pairs are unaffected (both arms
  hidden), absolute fps are the bench's own.
- Desktop VRAM (total - game, samples.tsv): ~630-660 MiB in v10-v15 and gm1-A, ~520 in v16-v19,
  ~500-527 in v21/v22 (cause not recorded). Same S13 build, v15 -> v16: desktop -136 MiB, game
  budget 2264 -> 2396 MiB, usage +140, pinned 2092 -> 1959 MiB. So the dashboard's "budget ~100 MiB
  higher since S13" and the pinned fall after S13 were the desktop; within series S13-S16 moved
  pinned by 15 MiB or less. Headline S0 (v13, desktop 638) vs S16 (507): ~134 of the -675 MiB pinned
  is the desktop, and up to ~0.8% fps (gm1's gain per MiB of budget, an upper bound).
- Major faults: HDD launches 37-531 thousand per fight vs 7-20 thousand on the SSD (HDD sessions
  also had ~1.6-1.9 GB in zram, game RSS ~2.4 vs ~3.0 GB). The headline uses SSD launches only, now
  per minute (windows run 131-272 s): 5.7 -> 2.9 thousand (-49%).
- GPU idle: the v23 split (game late 2.27, hand-over to vkQueueSubmit2 0.54, submitted not started
  <= 1.25 ms per traced frame) is from frames with timestamps on (4.06 ms idle vs ~1.6 untraced by
  nvidia-smi): shares, not time to win. Of the 0.54 ms the queue thread is busy ~0.15; what holds the
  rest is open (waits the game requested, or the thread's wake-up, are candidates). Render thread at
  S15: game 48.6%, d3d12core 17%, NVIDIA 16%, so "game late" is not all game code.
- Switching: the TV-off worst frame 227 ms was with the bar running; gaming mode stops the bar first
  (97 ms in the one such test).

## Repository (2026-10-15): layout, the fork as a patch series, authorship

- On GitHub; the layout is in README.md. `patches/` holds the fork as a per-commit series on
  upstream and replaced the per-checkpoint diffs, which stay in this repository's checkpoint
  commits; `tools/fork.sh` rebuilds the fork from upstream and checks every hash. `analysis/`
  (decompilations and shader dumps from the game) was taken out of the whole history before
  publishing and stays local.
- The `checkpoint-s16` release (2026-10-16) carries DLLs built from the committed checkpoint-s16 by
  README's Building steps (d3d12core 45b1ec67..., d3d12 5a9cc229...): builds from fresh clones of
  the repository, on different days and paths, were byte-identical. The measured binaries in
  build/checkpoint-s16/bin (d3d12core 88676f50..., build id 51ccb440...+) differ from them only in
  the build id; play.sh keeps using those. The tag now marks the repository with S16 current, so the
  release's source archive has README and the patch series.
- `learned/` is no longer tracked: every machine writes its own. The copy S13-S16 were measured with
  (58ee4aeb...) is in the S13 checkpoint commit and in build/checkpoint-s1*/learned.
- Every commit in the fork was re-created on 2026-10-15 with the author and committer
  `Zaid <nottzaid@tutamail.com>`; its trees and dates are unchanged (backups:
  build/backup-pre-trailer-2026-10-15/, build/backup-pre-public-2026-10-15/). Fork hashes cited
  earlier in these notes map to:

  | Fork commit | Before | Now |
  |---|---|---|
  | S12 | 892135ac | 0c669bcb |
  | S13 | 50382a55 | 1fdba59f |
  | S14 | 375c0f99 | e34af541 |
  | S15 | 012433f4 | e8c7c69f |
  | idxcache verify | 51ccb440 | 565fe641 |
  | S16 | 9369c583 | aaf4215c |
  | diagnostics | 058a0850 | 4820c6f7 |
  | dxil-spirv (S12) | c015cfc3 | 6d25da1b |

  Each checkpoint DLL in build/checkpoint-s1* was built from the working tree just before its
  checkpoint was committed, so it reports the commit before (old hash; S12's the upstream base) as
  vkd3d's build id (vkd3d_build, which keys its pipeline cache). A rebuild from a checkpoint commit
  gets that commit's new hash as its id, so vkd3d's pipeline cache starts over once.


## 2026-10-20: S17 dev, driven open world (swing-1017 save), hitch causes
- Driver: saves/swing-1017 (post skill-tree tutorial) + a swing loop of hyprbench `hold` steps
  (W+Shift swings, A/D turns, Space, X). benchinput `hold` now repeats key-down every 30 ms (the
  skill tree's hold-to-unlock needs it). The game polls XInput only after it enumerates a
  controller, so the virtual pad (`pad`) is not used.
- Warm caches, S17 dev, 240 s swinging (s17-explore4): 43.5 fps, p95 33.3 ms, 39 frames > 50 ms,
  fps per 10 s 36-56, VRAM 2926/3072 MiB. Slow frames: first-ever PSO compiles on the render
  thread (13, avg 139 ms), bursts of 2-11 ms sysmem vkAllocateMemory (12), render-thread CPU-heavy
  frames with a flat profile (14).
- The 5.4 s periodic hitch in play-1017-0205 only exists at 50-150 s: game activity, not a timer.
- GPL probe (VKD3D_BENCH_GPL_PROBE, cold-mono vs cold-gpl, empty NVIDIA cache, vkd3d cache off):
  on 580.178 the library build costs as much as the monolithic compile (334 vs 388 s over 2587
  PSOs); fast link and LTO link ~0.02 ms. GPL alone does not hide cold compiles. Dropped.
- pso firstbind (cold-3): 1099 of 1206 slow-compiled PSOs are first bound > 1 s after creation
  (median ~283 s). They are compiled by the game's four PSO worker threads (~113 s each when cold);
  only ~32 slow ones are created on the render thread and bound at once. The worker compiles
  overlap most slow frames: 4 compile threads on a 4-core CPU starve the main/render threads.
  Tried (cold-4): vkCreate*Pipelines at THREAD_PRIORITY_IDLE on threads other than the presenting
  one. Proton maps it to nice (the "Pipeline creation" threads went to nice 11; the game runs its
  own threads at nice -5). Worse: compile-caused slow frames averaged 442 ms (cold-3: 218 ms) and
  worker compile overlap of slow frames rose to 0.57 busy threads per frame-ms (cold-3: 0.31,
  normal frames ~0). The game waits for its workers' PSOs; slower workers lengthen the wait, so
  the stalls are compile latency, not CPU contention. Reverted.
- Slow allocations (cold-3): 790 are the game's small CUSTOM (L0) texture heaps in sysmem
  (heap type 4, flags 0x44, 13 KiB-2.9 MiB), 323 dedicated committed textures falling back to
  sysmem, ~200 VRAM heaps. Next: sub-allocate small texture heaps from chunks (pool), so a spill
  is not a 2-11 ms driver allocation on the frame.
- GPU: 1898 MHz, 79 C, SW power cap hit only 9 s in total; raising the power limit (120 -> 140 W)
  would barely help. Clock offsets via NVML are the remaining GPU lever.
- Warm driven runs (warmdrive: swing-1017, 200 s): warm-A 49.1 fps but a 9.2 s frame (worker
  compiles of 1-2.7 s at load: pipelines new to the game-folder NVIDIA cache, since this save's
  location was never loaded on that cache before); warm-C (same, second time) 43.9 fps, p95 32.1,
  8 frames > 50 ms (4 compiles, 3 plain, 1 allocation), 32 of warm-A's 36 slow PSOs served from
  cache (median 9.5 ms). The cache (one 255 MB .bin) is not being evicted; no size override needed.
- Memory domains (NVIDIA 580, GTX 1060): buffers 0x781, textures 0x82, render targets 0x80;
  sysmem fallback buffers 0x301, textures 0x2, render targets none. So vkd3d reports resource heap
  tier 1, the game makes per-category heaps, and vkd3d never sub-allocates image heaps.
- Tried: VKD3D_BENCH_TEXHEAP_POOL, small sampled-texture heaps sub-allocated from chunks at tier 1.
  First version crashed in the driver: at tier 1 a DENY_BUFFERS chunk gets no global buffer, and the
  zero-fill used a null buffer. Fixed, then warm-B3: 29.9 fps, 2069 slow allocations in the window
  (warm-C ~200), 3351 pool fallbacks, VRAM 3003 MiB. Partly used 16 MiB VRAM chunks push other
  resources out to system memory, and sysmem texture chunks cannot carry the clearing buffer
  (type 1 takes no buffers). Reverted. In warm sessions allocations are rarely in slow frames anyway.
- Next: warm open-world throughput (43.9 fps average, 10 s windows 38-51) is the main gap.

## 2026-10-21: S17 dev, system levers, memory, deferred command recording

- Loop route for A/B (scratchpad circledrive.sh: `hold 8000 w shift d`, `space`): circles the same
  blocks at 44-55 fps, but can still end against a wall (60 fps cap, useless) after minutes. Live
  toggles in 12 s segments (livetoggle.sh) compare system settings inside one game.
- System levers, live A/B in one game: performance governor ~= schedutil (clocks average 3554 MHz
  while swinging; the i5-4670's 4-core turbo is 3.6 GHz, so nothing to gain); `scx_lavd
  --performance` 48.7 vs 47.7 fps, >40 ms frames 4.9 vs 7.6/min (small, one run); GPU +100 MHz
  core / +250 NVML memory (= +500 MHz in Afterburner terms): no gain in 8 usable pairs (46.4 vs
  47.4). The GPU is not the limit while swinging; the render thread is.
- Memory: the bench game runs with ~130 MB free. The game's own memory is 2.4-3 GB of which 1.8-2.3
  GB sits in zram; the driver pins ~2.2 GB of GPU allocations in system RAM (type 8 host-visible
  1148 MiB, incl. the 800 MiB geometry heap, of which 662 MiB was written within minutes; type 1
  texture spill 926 MiB), since the desktop holds ~500 MiB of VRAM (Hyprland 224, noctalia 213,
  kitty 60). Major faults while swinging: 89% on the Asset Load Thread (streaming), main ~76/s,
  render thread 0. Real play runs under gaming mode (~/.local/bin/gaming-mode: shell stopped,
  terminals closed, apps frozen and swapped out), bench runs do not (the game is on a hidden
  workspace); forcing it on re-reads the Hyprland config, which resets render_unfocused_fps to 15
  (rerun `hyprbench.py setup` after).
- Render thread (perf LBR, 31k samples): 15.3% libnvidia-glcore, 13.5% d3d12core, ~5% Wine/libc
  around the driver calls, 6.8% the game's pause backoff (0x20c6840) called only from the occlusion
  query finalize spin (0x1d98783, see 2026-10-11): ~20% of the critical thread is driver recording.
- Deferred command recording (fork cmdreplay.c, `VKD3D_BENCH_CMD_REPLAY=1`, config s17-rp): command
  lists' command buffers record into per-buffer op streams; one worker thread replays them into the
  driver. Wrappers for every device function that can see a command buffer are generated
  (cmdreplay_gen.py); pool operations, submission and destroys order themselves after the worker.
  First run: no errors over minutes of open world, 115-296k ops/s replayed, only
  vkCmdSetDepthBias2EXT goes direct (9 calls). Clean-slate review (opus): no crash path for this
  game; fixed interop handles, per-device entry points, vkDestroyDevice ordering, destroy chunk
  size, NULL-handle guards (vkDestroyPipelineCache(NULL) per PSO release), vkFreeMemory left
  unqueued (VRAM back at once). Baseline for the A/B (rpA-1, s17-dev, loop route 88 s): 48.70 fps,
  p95 27.6 ms, render thread 16.3 ms/frame, main 15.7. The replay run (rpB-1) was stopped by Claude
  Code's low-memory guard before it measured.
- Deferred command recording, continued. Guard waits were pool operations waiting for every
  published chunk: now they wait only for their own pool's last chunk (plus vkCmdExecuteCommands
  chunks when the pool has secondaries), and render-thread guard waits went to zero. Feature bit
  0x2000 (REPLAY_OFF) switches pools to direct recording at their next reset, so replay can be A/B'd
  in one game. Result: no gain. Circling sessions (rpT-1..3) are noise (12 usable pairs average
  +0.1 fps, single windows 38-55 fps); standing with VSync off (st-rp1, 12 ABBA pairs): replay on
  60.1 fps vs off 60.7, p95 19.6 vs 18.8 ms. The render thread saves ~1-1.6 ms/frame, but the worker
  spends ~5 ms/frame of a fourth core the game's job threads need. Kept off (fork 93e5d388).
- Measuring method. Launch-to-launch spread on the circle route is +-4 fps and 4-15 s windows
  inside one session spread +-20%, so circling A/Bs cannot resolve a few percent. Standing still in
  the open world with the bench prefix's VSync off (registry `VSync`=0 for the run only; the game is
  not capped then: 13% of frames under 15 ms) gives +-0.3-0.6 fps per window. Circling uncapped
  with 15 s live-toggle segments still resolves tail changes (frames > 40 ms per minute).
- S17's index cache (mirrors GPU writes instead of turning itself off) vs off, same session
  (feature 0x8), standing, VSync off: swing-1017 58.01 vs 55.48 fps (st-ic1), user-1017 61.84 vs
  59.15 (st-ic2, 10 pairs, -4.35% +- 0.35 off). S16 turns the cache off in the open world (the
  user's play-1017-0205 log: "CopyBufferRegion writes the geometry heap"), so this is S17's gain
  over S16 there. s17-verify2: 4.3M cached draws compared byte for byte, 0 differ.
- Schedulers (live toggle, s17-dev, VSync off):
  | Run | Scene | stock | sched_ext | tails |
  |---|---|---|---|---|
  | st-scx1 | standing user-1017 | 64.19 | scx_lavd 64.54 | p95 17.8 -> 17.0 |
  | st-bpf1 | standing user-1017 | 63.73 | scx_bpfland 64.64 | p95 18.4 -> 17.0, p99 21.1 -> 18.0 |
  | tr-bpf1 | circling 12x15 s | 47.89 | scx_bpfland 50.10 | >40 ms 10.4 -> 3.7/min, >50 ms 5 -> 0 |
  | tr-bpf2 | circling 12x15 s | 44.47 | scx_bpfland 45.59 | >40 ms 16.2 -> 6.2/min, >50 ms 6 -> 1 |
  | tr-lavd1 | circling 12x15 s | 45.19 | scx_lavd --performance 45.86 | >40 ms 8.3 -> 9.2/min |
  scx_bpfland (defaults) cuts slow frames while traversing by more than half in both sessions;
  scx_lavd does not.
- GPU clock offsets in the GPU-bound warehouse fight (GPU 96% busy), live toggle, VSync off:
  +100 core / +250 NVML memory 59.00 -> 60.91 fps (+3.2%, wh-gpu1); +150 / +500 58.40 -> 61.35
  (+5.1%, wh-gpu2), no Xid errors. The open world is CPU-bound and does not gain. Offsets are reset
  after each run; not applied (a hardware choice for the user).
- Render thread while circling (prof-3, perf 40 s, s17-dev): game code 56%, libnvidia-glcore 14%,
  d3d12core 12% (index cache lookup 1.4%, descriptor copies ~2.8%, SetPipelineState 0.9%, the
  rest under 0.5% each), ucrtbase 4.5%, ntdll 3.5%, libc 3.5%. Little left in vkd3d to take.
- Fight regression check, S16 (s16-frozen) vs S17 (s17-dev), warehouse prompt, VSync off, launches
  interleaved: S16 56.09 / 57.25 / 55.71 (mean 56.35), S17 55.38 / 55.99 / 57.40 / 55.93 (mean 56.18):
  -0.3%, inside launch spread (S16 alone spans 1.5 fps). No GPU write into the geometry heap in the
  fight, so S17's mirroring path never runs there. The fourth S16 launch was cut short by Claude
  Code's low-memory guard (it also left the bench prefix's VSync at 0; restored by hand).
- Candidate for play: S17 + scx_bpfland for the game session. Not applied yet (the user asked for
  the Lutris entry to stay on S16 until everything is settled).

## S17 (2026-10-21): checkpoint-s17, scx_bpfland for play sessions, GPU offsets dropped

- Whole-launch A/B, S16 frozen on the kernel scheduler vs S17 with scx_bpfland from launch to exit
  (as play runs it), VSync off, swing-1017 circle route, 130 s windows (cb-ow-*; launches whose
  scheduler did not match the plan are listed by what actually ran, see the race below):
  S16 stock 43.41 / 44.28 / 50.14 / 46.41 / 48.90 fps (mean 46.6), frames > 40 ms 29.3 / 14.9 / 4.1 /
  9.5 / 5.4 per min (mean 12.6), > 50 ms 15 / 5 / 2 / 4 / 1; S17 + bpfland 49.06 / 48.57 / 47.87 / 46.61
  (mean 48.0), 5.9 / 2.3 / 4.0 / 8.7 per min (mean 5.2), > 50 ms 2 / 1 / 3 / 3. Launch spread is wide;
  the same-game toggles (S17's cache +4.5%, bpfland's halved tails) are the precise measurements and
  agree. Warehouse fight (cb-wh-*): S16 stock 57.28 / 56.51 / 55.95, S17 stock 57.11, S17 + bpfland
  57.02 / 57.65: unchanged. The series was cut short by Claude Code's low-memory guard after
  cb-ow-B16 (the game, bpfland and VSync 0 it left behind were cleaned up by hand).
- Scheduler race: a scheduler that was just killed takes up to ~1 s to unregister, and scx_bpfland
  started meanwhile exits with "another sched_ext scheduler is already running" (cb-ow-B3, cb-wh-B9
  ran without it; cb-wh-A7 started while B6's was unregistering). The runner and tools/miles-session
  now wait for /sys/kernel/sched_ext/state.
- Review of fork 038bf927 (index cache mirroring; clean-slate, Opus): mirrored path correct
  (ordering, transfer-queue fills, allocator-reset lifetime, pins, locking; diagnostics inert when
  unset). Gaps only in writers that exclude instead of mirroring (already-recorded draws over an
  excluded range would read stale indices) and in writers neither mirrored nor excluded (CopyTiles
  to a heap buffer, ExecuteIndirect UAV root arguments, reserved resources mapped onto the heap).
  This game: 0 exclusions in all 49 S17-era logs (the INFO "no live run overlapped" never appears
  either), and s17-verify2's byte-for-byte check would catch any untracked writer: 4,291,564
  compared, 0 differ, 0 submitted late. Shipped as is.
- GPU offsets +150 core / +500 memory for whole launches: warehouse 59.99 / 59.97 fps (+4.6% over
  S17 + bpfland at stock clocks), but the open-world launch (oc-ow-1) lost the device 36 s into
  swinging (VK_ERROR_DEVICE_LOST in vkd3d, no Xid in the kernel log) and Hyprland aborted at the same
  moment (hyprlandCrashReport993.txt, 07:56:36, CHyprOpenGLImpl::begin assert: its GL context died
  with the GPU fault). No other session in the captures ever lost the device. Not stable: dropped,
  tools/miles-session keeps 0 / 0.
- Checkpoint: fork commit 93e5d388, tag checkpoint-s17, patches/vkd3d-proton 0008-0012 (tools/fork.sh
  rebuilds it with every hash checked). Binaries build/checkpoint-s17/bin = the build/s17 DLLs every
  S17 measurement used (SHA256SUMS; d3d12core 6abf96ab..., d3d12 6a9bbc1d...; built from 93e5d388's
  tree before it was committed, so the build id is c5c06ee3's), read-only learned copy 58ee4aeb...;
  config bench/configs/s17-frozen.env. Deferred command recording is in the binary but off.
- Play: bench/play.sh plays S17 and runs tools/miles-session (installed root-owned by
  tools/install-miles-session.sh with a sudo rule for exactly `miles-session start <pid>` / `stop`):
  scx_bpfland in a transient unit miles-session.service, stopped by play.sh's exit trap or, if
  play.sh dies first, by the unit's own watch on its pid. End-to-end check on the bench prefix
  (play-e2e-s17): S17 DLLs in place and bpfland attached while the game ran; after it exited the
  kernel scheduler was back, the unit gone, the DLLs removed. Back to S16: PLAY_DLLS=build/checkpoint-s16/bin
  PLAY_LEVERS=0.
- Dashboard, README and docs updated for S17 (2026-10-21, later): S17 is in data/steps.csv without
  fight launches (the fight never copies into the geometry heap), the headline takes the last step
  with fight launches (still S16), and a new open-world section draws data/s17_launches.csv (every
  whole launch above, uncapped) and data/s17_levers.csv (the same-session switches). The fight
  series by the bench's method (build/v24-one.sh) stays undone at the user's call: only v24-A1 ran.
- Release `checkpoint-s17` (2026-10-21): DLLs built from the committed checkpoint-s17 by README's
  Building steps (Nix GCC 15.3), d3d12core c48b6f86..., d3d12 5a9cc229... (unchanged since S16). A
  fresh clone from GitHub and this repository built them byte-identical. The layout matters: meson
  embeds source paths relative to the build directory (`../../src/vkd3d-proton/...`), so a build
  outside `<repo>/build/<dir>` differs (a first try in the scratchpad did). Smoke test
  (rel-s17-smoke, user-1017): build id 56ed43c5e1bc2f5, every feature on, the usual err lines only.
- The measured S17 binaries (build/checkpoint-s17/bin, from build/s17) are not the same compiler:
  build/s17 was set up in the Nix shell (GCC 15.3) but later incremental rebuilds ran outside it, and
  the cross file names the compiler without a path, so they used the system's mingw-w64-gcc 16.2
  (Arch) and linked its static libgcc / libstdc++ with their debug info (the 20 MB size; .text
  5,293,648 against the release's 5,224,576 bytes). Same source. The S17 numbers that matter are
  same-session switches, which the compiler does not touch; the whole-launch S16 vs S17 comparisons
  also changed the compiler (no fight difference). Play keeps the measured binaries. Rebuild only
  inside `nix develop`.
