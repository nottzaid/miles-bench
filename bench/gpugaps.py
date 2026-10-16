"""GPU idle on the direct queue from a gputime.tsv (python3 bench/gpugaps.py <capture dir>).
Idle gaps on the direct queue, split three ways with the GS line's ExecuteCommandLists time:
game  - the GPU ran out of work before the game called ExecuteCommandLists for the next command buffer
queue - ExecuteCommandLists was called, but vkd3d's queue thread had not yet called vkQueueSubmit2
gpu   - vkQueueSubmit2 was called, the GPU had not started the command buffer yet
CPU times are moved onto the GPU clock with a per-frame offset: the smallest (GPU start - vkQueueSubmit2)
among the 7 nearest sampled frames, so 'gpu' is relative to the fastest start seen. It includes the
~70-150 us an idle GPU takes to start a new submission, and gaps where command buffers recorded before the
sampled frame (not tracked) ran: read it as an upper bound (NOTES, S16 follow-up)."""
import collections, statistics, sys

cap = sys.argv[1]
cbs = collections.defaultdict(list)  # frame -> [queue, seq, gpu_start, submit, ecl, submit_end]
ends = {}
for line in open(f'{cap}/gputime.tsv'):
    f = line.rstrip('\n').split('\t')
    if f[0] == 'GS':
        ecl = float(f[6]) if len(f) > 6 else 0.0
        se = float(f[7]) if len(f) > 7 else 0.0
        cbs[int(f[1])].append([f[2], int(f[3]), int(f[4]) / 1e6, float(f[5]), ecl, se])
    elif f[0] == 'GT':
        k = (int(f[1]), f[2], int(f[3]))
        ends[k] = max(ends.get(k, 0), int(f[4]) / 1e6)
frames = sorted(cbs)
mins = {fr: min(c[2] - c[3] for c in cbs[fr]) for fr in frames}
off = {fr: min(mins[frames[j]] for j in range(max(0, i - 3), min(len(frames), i + 4))) for i, fr in enumerate(frames)}
q0 = collections.Counter(c[0] for fr in frames for c in cbs[fr]).most_common(1)[0][0]

tot = collections.Counter()
n = 0
handoff, drv, start_lat = [], [], []
for fr in frames:
    lst = sorted([c for c in cbs[fr] if c[0] == q0 and (fr, c[0], c[1]) in ends], key=lambda c: c[2])
    if len(lst) < 2:
        continue
    n += 1
    o = off[fr]
    for c in lst:
        if c[4]:
            handoff.append((c[3] - c[4]) * 1000)
        if c[5]:
            drv.append((c[5] - c[3]) * 1000)
        start_lat.append((c[2] - o - c[3]) * 1000)
    for a, b in zip(lst, lst[1:]):
        idle0 = ends[(fr, a[0], a[1])]
        start = b[2]
        if start <= idle0:
            continue
        sub = b[3] + o
        ecl = b[4] + o if b[4] else None
        g = q = d = 0.0
        if ecl is None:
            tot['no ecl'] += start - idle0
            continue
        g = max(0.0, min(ecl, start) - idle0)
        q = max(0.0, min(sub, start) - max(ecl, idle0))
        d = max(0.0, start - max(sub, idle0))
        tot['game'] += g
        tot['queue'] += q
        tot['gpu'] += d
        tot['all'] += start - idle0


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))] if v else float('nan')


print(f'{n} frames on {q0}: idle between command buffers {tot["all"] / n:.2f} ms/frame: '
      f'game late {tot["game"] / n:.2f}, vkd3d queue thread {tot["queue"] / n:.2f}, '
      f'vkQueueSubmit2 to GPU start {tot["gpu"] / n:.2f}' + (f', no ECL time {tot["no ecl"] / n:.2f}' if tot['no ecl'] else ''))
for name, v in (('ECL -> vkQueueSubmit2 (us)', handoff), ('vkQueueSubmit2 call (us)', drv),
                ('vkQueueSubmit2 -> GPU start, above the fastest (us)', start_lat)):
    if v:
        print(f'  {name}: n {len(v)} median {statistics.median(v):.0f} p90 {pct(v, .9):.0f} p99 {pct(v, .99):.0f} mean {statistics.mean(v):.0f}')
