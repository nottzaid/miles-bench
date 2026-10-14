"""Continuous GPU timeline from gputime.tsv runs (VKD3D_BENCH_GPUTIME_RUN > 1): for each run of
consecutive sampled frames, the main queue's busy and idle time, and for each idle gap whether the
command buffer after it had already been submitted (the GPU waited on a semaphore: another queue,
a fence, the swapchain) or was submitted late (the GPU waited for the CPU).

    python3 bench/gpuflow.py <capture dir> [seconds at the end, default 30] [-v]
"""
import collections, statistics, sys
cap = sys.argv[1]
window_s = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "-v" else 30
verbose = "-v" in sys.argv
cmds, segs, presents = {}, collections.defaultdict(list), {}
for line in open(f"{cap}/gputime.tsv"):
    f = line.rstrip("\n").split("\t")
    if f[0] == "GS":
        cmds[(int(f[1]), int(f[3]))] = dict(q=f[2], start=int(f[4]), sub=float(f[5]) * 1e6)
    elif f[0] == "GT":
        segs[(int(f[1]), int(f[3]))].append((int(f[4]), int(f[5]), f[6], int(f[7]), int(f[8]), int(f[10])))
    elif f[0] == "GP":
        presents[int(f[1])] = int(f[2])
qcount = collections.Counter(c["q"] for c in cmds.values())
main = qcount.most_common(1)[0][0]
last = max(c["start"] for c in cmds.values())
frames = sorted({fr for (fr, _), c in cmds.items() if c["start"] > last - window_s * 1e9})
# runs of consecutive frames
runs, cur = [], []
for fr in frames:
    if cur and fr != cur[-1] + 1:
        runs.append(cur); cur = []
    cur.append(fr)
if cur: runs.append(cur)
tot = collections.Counter()
lat = []
for run in runs:
    ks = sorted((k for k in cmds if k[0] in run and cmds[k]["q"] == main and segs[k]), key=lambda k: cmds[k]["start"])
    if not ks: continue
    # The GPU timer and the CPU's clock differ by a constant (~2 s here): calibrate on the command
    # buffer that started soonest after its submission (the queue was idle), taken as 50 us.
    off = min(cmds[k]["start"] - cmds[k]["sub"] for k in ks) - 50e3
    for k in ks:
        cmds[k]["sub"] += off
    t0 = cmds[ks[0]]["start"]; prev_end = None
    busy = idle_cpu = idle_wait = 0
    lines = []
    for k in ks:
        c = cmds[k]; end = segs[k][-1][0]
        if prev_end is not None and c["start"] > prev_end:
            gap = c["start"] - prev_end
            # submitted after the queue went idle -> waited for the CPU (part of the gap)
            late = max(0, min(gap, c["sub"] - prev_end))
            idle_cpu += late; idle_wait += gap - late
            if verbose and gap > 200e3:
                lines.append(f"    gap {gap/1e6:6.2f} ms before seq {k[1]} (frame {k[0]}): waited for CPU {late/1e6:.2f}, semaphore {(gap-late)/1e6:.2f}; submitted {(c['sub']-t0)/1e6:.2f}, started {(c['start']-t0)/1e6:.2f}")
        busy += end - max(c["start"], prev_end or 0) if end > (prev_end or 0) else 0
        lat.append((c["start"] - c["sub"]) / 1e6)
        prev_end = max(prev_end or 0, end)
    span = prev_end - t0
    nfr = len(run)
    pt = [presents[f] for f in run if f in presents]
    tot.update(dict(span=span, busy=busy, idle_cpu=idle_cpu, idle_wait=idle_wait, frames=nfr))
    print(f"frames {run[0]}-{run[-1]}: {span/1e6/nfr:6.2f} ms/frame GPU-side, busy {busy/1e6/nfr:6.2f}, idle waiting CPU {idle_cpu/1e6/nfr:5.2f}, idle on semaphores {idle_wait/1e6/nfr:5.2f}"
          + (f"; presents every {statistics.mean(b-a for a,b in zip(pt,pt[1:]))/1e6:.2f} ms" if len(pt) > 1 else ""))
    for l in lines: print(l)
n = tot["frames"]
print(f"\nall: {n} frames: {tot['span']/1e6/n:.2f} ms/frame GPU-side, busy {tot['busy']/1e6/n:.2f}, idle waiting CPU {tot['idle_cpu']/1e6/n:.2f}, on semaphores {tot['idle_wait']/1e6/n:.2f}")
print(f"GPU start - CPU submit (ms): p10 {sorted(lat)[len(lat)//10]:.2f} median {statistics.median(lat):.2f} p90 {sorted(lat)[len(lat)*9//10]:.2f}")
