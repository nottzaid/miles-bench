# Checkpoints

Each step adds to the one before. Switches are environment variables read by the fork
(`bench/configs/s17-frozen.env` has the full set of the current build; `bench/play.sh` sets the
same). What each step gained is in [README.md](../README.md#results)'s step table; the full record
of each is in NOTES.md.

| Step | Name | Switch | Code in the fork | Patch |
|---|---|---|---|---|
| S0 | Unpatched | — | upstream 731c4aae | — |
| S5 | Steps 1-5 | see below | see below | 0001 |
| S6 | Page drops | `VKD3D_ENGINE_PATCH=…,dropdst` | `enginepatch.c` | 0001 |
| S7 | Sparse light grid | `VKD3D_BENCH_LIGHTGRID_SPARSE=1` | `lightgrid.c` | 0001 |
| S8 | Index cache fix | on with the index cache (`VKD3D_BENCH_INDEX_CACHE_FAILFAST=0` restores the old behaviour) | `idxcache.c` | 0001 |
| S9 | Sparse skinning buffer | `VKD3D_BENCH_SKIN_SPARSE=1` | `skinbuf.c` | 0001 |
| S12 | Lighting fix + SSD | (larger initial backing; game moved to the SSD) | `lightgrid.c`, `skinbuf.c` | 0001 |
| S13 | Learned sizes + gates | `VKD3D_BENCH_VRAM_RESERVE=1` (sizes learned per machine) | `learned.c` | 0002 |
| S14 | Index cache eviction fix | on with the index cache | `idxcache.c` | 0003 |
| S15 | Clear keep | `VKD3D_BENCH_CLEAR_KEEP=1` | `command.c`, `enginepatch.c` | 0004 |
| S16 | Render-thread CPU cuts | always on | `command.c`, `idxcache.c`, `enginepatch.c` | 0006 |
| S17 | Open-world index cache | on with the index cache | `idxcache.c`, `command.c` | 0009 (0008, 0010-0012 off unless enabled) |

Patch numbers refer to `patches/vkd3d-proton/`. S5 to S12 were developed before the fork had
commits, so they arrive together in 0001. 0005 adds the index cache's verify mode; 0007 diagnostics
that are off unless enabled; 0008 the bench's key input; 0010-0012 deferred command recording,
measured no gain and off unless `VKD3D_BENCH_CMD_REPLAY=1`; 0013, after `checkpoint-s17`, points
the fork's dxil-spirv submodule at the dxil-spirv fork (no code change).

## S5: steps 1-5

Seven changes, each measured on its own in the static scene and in live A/B:

| Change | Switch | Code |
|---|---|---|
| VRAM reserve for render targets: cold allocations go to system memory once the budget runs low, so render targets, depth and UAVs created later still get VRAM | `VKD3D_BENCH_VRAM_RESERVE` | `memory.c`, `learned.c` |
| Geometry decompression fix in the engine | `VKD3D_ENGINE_PATCH=gdec` | `enginepatch.c` |
| Index cache: indexed draws read their index data from a cache in VRAM instead of across PCIe (about 96% of them) | `VKD3D_BENCH_INDEX_CACHE=1` | `idxcache.c` |
| Particle batching | `VKD3D_BENCH_PARTICLE_BATCH=16` | `command.c` |
| Discarding a render target no longer records a barrier to UNDEFINED, a full pipeline drain (the discard itself stays) | `VKD3D_BENCH_DISCARD_KEEP=1` | `command.c` |
| Particle draw constants through a private descriptor tail | `VKD3D_BENCH_PDRAW=1` | `command.c` |
| Lazy descriptor heaps: 6 of the engine's 8 one-million-descriptor heaps are never written and share one null heap | `VKD3D_BENCH_LAZY_HEAPS=1` | `resource.c` |

S5 also brought long freezes in heavy phases (frames over 100 ms: 127 per fight); S8 found and
fixed their cause in the index cache.

## S6: page drops

Drops destination pages the engine is about to overwrite anyway, so they are never swapped back in
first.

## S7: sparse light grid

The engine's 512 MiB light grid buffer is made sparse and backed only where the engine uses it.

## S8: index cache fix

A full index cache walked its whole ring on every draw it could not place; it now fails fast.

## S9: sparse skinning buffer

The 196 MiB skinning buffer is backed only where the engine uses it.

## S10 and S11: dropped

S10 redirected the render thread's busy-wait loops to blocking fence waits (`VKD3D_ENGINE_PATCH=spin`):
39.44 against S9's 40.19 fps in the fight. S11 gave NVIDIA's shader cache a larger size limit, which
made the driver store nothing at all. Neither was kept.

## S12: lighting fix + SSD

In the open world the sparse light grid and skinning buffer ran out of VRAM to grow into, and the
missing light grid pages left an area dark. They only accept VRAM, so the fix is a larger initial
backing made while VRAM is still free (5120 light grid pages, 32 MiB per skinning half). At the same
time the game moved to the SSD: NVIDIA's shader cache did not work from the HDD, and the same
shaders compiled again, and froze the game, every launch.

## S13: learned sizes + gates

The light grid and skinning backing, the VRAM reserve and the budget held back from the game are
sized from what earlier sessions of this game build on the same GPU actually used (a file each
machine writes for itself; README, Using S17), instead of constants tuned on this PC. Each feature
also checks that it can help before changing anything: a known game build, a separate GPU, sparse
memory support. On another machine the build falls back to stock behaviour wherever a check fails.

## S14: index cache eviction fix

The index cache freed only the first page of each run it evicted, so it refused runs it had room
for. It now frees the whole run (refusals 2153/s to 304/s).

## S15: clear keep

A full clear of a render target that shares its memory with other resources no longer throws the
target's layout away when vkd3d can prove, in GPU order, that no other resource used that memory
since the target last initialized it (about 18 clears per frame). Also review fixes to the learned
sizes, the integrated-GPU gates and the light grid and skinning growth. 0005 adds the index cache
verify mode that checked S15 (0 of 4.9 million draws read different bytes).

## S16: render-thread CPU cuts

Less locking and fewer driver calls on the game's render thread, with nothing the GPU draws
changed: draw counts kept per command list, the index cache bound once per command buffer,
lock-free fence polling, index cache hits under a shared lock, and a lock-free repeat check in
clear keep.

## S17: open-world index cache

In the open world the game copies new geometry into its 800 MiB geometry heap on the GPU
(CopyBufferRegion). S16's index cache then turned itself off for the rest of the session, since its
cached copies could go stale. S17 records the same copy into every cached run that covers the
written bytes, in the same command buffer, and keeps the written pages out of new runs until the
command allocator holding the copy is reset. Writers it cannot mirror (UAVs, clears, query
resolves and the like) take their range out of the cache for good; this game uses none of them on
the heap. The byte-for-byte verify mode found 0 differing draws in 4.3 million. Same-session A/B
with the cache switched live: +4.6% and +4.5% fps in the open world. The fight never copies into
the heap, so it is unchanged there.

Play sessions also run the `scx_bpfland` CPU scheduler while the game is up (`tools/miles-session`,
a system lever, not part of the fork): frames over 40 ms while swinging fell by more than half in
same-session A/B. The dashboard's open-world section has every launch and switch.

## What is left in the fight

The fight is now limited by the GPU: about 21 ms of GPU work per 22.7 ms frame, in render and compute
passes whose shaders translate cleanly. NOTES.md (S16 follow-up) splits the remaining GPU idle time;
`data/headroom.csv` lists what is left and what each part would take.
