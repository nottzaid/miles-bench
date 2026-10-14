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
